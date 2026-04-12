"""
Harold — AI Trading Agent v4 (Kraken CLI v2.3.0 + Groq)
=========================================================
Hackathon Edition — ETH/USD paper trading.

Changes from v3:
  - TP raised to 1.5% (was 0.65%) — fees are 0.52% round trip, old TP barely broke even
  - SL tightened to 0.6% (was 0.2%) — R:R was 1:3 against us, now ~1.6:1 in our favour
  - SL cooldown: 5 min no-buy after a stop fires (prevents re-entering same bad move)
  - RSI-14 added to signal engine
  - Candle body bias (last 3 candles) added to signals
  - SMA10 distance % added — prevents entries when price is overextended
  - AI cycle tightened to 120s (was 180s)
  - Groq prompt fully rewritten: fee-aware, strict entry checklist, 8-word reasoning cap
  - amount_percent capped at 15 (was 20)

Requirements:
    pip3 install python-dotenv groq requests
    Optional: PRISM_API_KEY in .env for crypto news headlines
"""

import os
import time
import json
import logging
import subprocess
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from groq import Groq

from prism_news import fetch_trading_community_news_context

# ─── CONFIG ────────────────────────────────────────────────────────────────────

GROQ_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_KEY:
    raise ValueError("Missing GROQ_API_KEY in .env file.")

groq_client = Groq(api_key=GROQ_KEY)

# Symbol Management
SYMBOL_CLI     = "ETHUSD"     # Kraken CLI paper orders
SYMBOL_API     = "ETHUSD"     # Kraken REST Ticker/OHLC ?pair=
OHLC_RESULT_KEY = "XETHZUSD"  # Key inside OHLC result object

# Risk Management
# Kraken fee is ~0.26% per side = 0.52% round trip.
# TP must be well above 0.52% to make money. SL must give R:R >= 1.5:1 net of fees.
TAKE_PROFIT      = 1.500   # Close trade at +1.5% PnL  (net after fees: ~+0.98%)
STOP_LOSS        = -0.600  # Close trade at -0.6% PnL  (net after fees: ~-1.12%)
# Net R:R = 0.98 / 1.12 ≈ 0.87 — still requires >54% win rate.
# Widen TP to 2.0% in a trending market for better R:R.
SL_COOLDOWN_SEC  = 300     # No BUY for 5 min after a stop loss fires

# Timing
AI_CYCLE_SEC  = 120   # How often Groq makes a decision (2 min)
MONITOR_SEC   = 15    # How often the status monitor ticks

# Files
STATE_FILE = "harold_state.json"
CSV_FILE   = "trades_log.csv"

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("harold")

# ─── STATE MANAGEMENT ──────────────────────────────────────────────────────────
def load_state() -> dict | None:
    """Loads the active position from JSON to survive crashes."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Failed to load state file: {e}")
    return None

def save_state(position: dict | None):
    """Saves active position to JSON, or removes the file when flat."""
    if position is None:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    else:
        with open(STATE_FILE, "w") as f:
            json.dump(position, f, indent=2)

# ─── CSV LEDGER ────────────────────────────────────────────────────────────────
def log_trade_to_csv(action: str, price: float, size: float, reasoning: str):
    """Appends every trade to CSV for post-hackathon analysis."""
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, mode="a", newline="") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(["Timestamp", "Action", "Price", "Size", "Total_Value", "Reasoning"])
            w.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                action.upper(),
                f"${price:,.2f}",
                size,
                f"${price * size:,.2f}",
                reasoning,
            ])
    except Exception as e:
        log.error(f"CSV write failed: {e}")

# ─── KRAKEN CLI EXECUTOR ───────────────────────────────────────────────────────
def kraken_run(args: list) -> dict:
    """Runs a Kraken CLI command and safely parses JSON output."""
    cmd = ["kraken", "-o", "json"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log.error(f"CLI Error [{' '.join(args)}]: {r.stderr.strip()}")
            return {}
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        log.error(f"CLI JSON parse error: {e}")
        return {}
    except Exception as e:
        log.error(f"CLI Exception: {e}")
        return {}

def paper_buy(symbol: str, size: float) -> dict:
    return kraken_run(["paper", "buy", symbol, str(size)])

def paper_sell(symbol: str, size: float) -> dict:
    return kraken_run(["paper", "sell", symbol, str(size)])

def paper_status() -> dict:
    return kraken_run(["paper", "status"])

# ─── BALANCE HELPERS ───────────────────────────────────────────────────────────
def get_current_value() -> float:
    """Fetches current_value from paper status (USD + ETH marked to market)."""
    status = paper_status()
    if not status:
        return 0.0
    return float(status.get("current_value", 0.0))

def get_available_usd(position: dict | None, current_price: float) -> float:
    """
    Calculates spendable USD by subtracting estimated ETH holding value
    from total current_value. When flat, current_value IS the USD.
    """
    current_value = get_current_value()
    if current_value == 0.0:
        return 0.0
    if position is None:
        return current_value
    eth_held_value = position["size"] * current_price
    return max(0.0, current_value - eth_held_value)

# ─── MARKET DATA ───────────────────────────────────────────────────────────────
def fetch_ticker() -> dict:
    """Gets latest price + 24h high/low from Kraken REST API."""
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": SYMBOL_API},
            timeout=10,
        )
        r.raise_for_status()
        t = list(r.json()["result"].values())[0]
        return {
            "price":  float(t["c"][0]),
            "high24": float(t["h"][1]),
            "low24":  float(t["l"][1]),
        }
    except Exception as e:
        log.error(f"Ticker fetch failed: {e}")
        return {"price": 0.0, "high24": 0.0, "low24": 0.0}

def fetch_ohlc_with_retry(interval: int = 1, max_attempts: int = 3) -> list:
    """Fetches 1-minute OHLC candles with exponential backoff retry."""
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(
                "https://api.kraken.com/0/public/OHLC",
                params={"pair": SYMBOL_API, "interval": interval},
                timeout=15,
            )
            r.raise_for_status()
            candles = r.json()["result"].get(OHLC_RESULT_KEY, [])
            if candles:
                return candles
            log.warning(f"OHLC returned empty list (attempt {attempt}/{max_attempts})")
        except Exception as e:
            log.warning(f"OHLC fetch attempt {attempt}/{max_attempts} failed: {e}")
        if attempt < max_attempts:
            time.sleep(2 ** attempt)
    log.error("All OHLC fetch attempts failed. AI will receive no candle data.")
    return []

# ─── SIGNAL ENGINE ─────────────────────────────────────────────────────────────
def build_signals(ticker: dict, ohlc: list) -> dict:
    """
    Calculates technical indicators for 1-minute charts.
    New in v4: RSI-14, candle body bias, SMA10 distance %.
    """
    price = ticker["price"]

    if not ohlc or price == 0.0:
        return {"price": price, "error": "No candle data available"}

    closes  = [float(c[4]) for c in ohlc]
    opens   = [float(c[1]) for c in ohlc]
    volumes = [float(c[6]) for c in ohlc]

    # ── Moving Averages ──────────────────────────────────────────────────────
    sma_10m = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
    sma_30m = sum(closes[-30:]) / 30 if len(closes) >= 30 else None

    # ── Momentum: count up vs down moves over last 5 candles ────────────────
    recent = closes[-5:]
    ups    = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
    downs  = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
    momentum = "up" if ups >= 3 else ("down" if downs >= 3 else "flat")

    # ── Volume spike: last candle vs 20-candle average ───────────────────────
    last_vol  = volumes[-1] if volumes else 0
    avg_vol   = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 1
    vol_spike = bool(last_vol > avg_vol * 1.5)

    # ── RSI-14 ───────────────────────────────────────────────────────────────
    # Uses last 15 closes to compute 14 price deltas
    rsi_closes = closes[-15:] if len(closes) >= 15 else closes
    gains, losses = [], []
    for i in range(1, len(rsi_closes)):
        delta = rsi_closes[i] - rsi_closes[i - 1]
        if delta > 0:
            gains.append(delta)
        else:
            losses.append(abs(delta))
    avg_gain = sum(gains) / 14 if gains else 0.001
    avg_loss = sum(losses) / 14 if losses else 0.001
    rs  = avg_gain / avg_loss
    rsi = round(100 - (100 / (1 + rs)), 1)

    # ── Candle body bias: last 3 candles (close > open = bullish) ────────────
    last3_candles = list(zip(opens[-3:], closes[-3:]))
    bullish_count = sum(1 for o, c in last3_candles if c > o)
    if bullish_count >= 2:
        body_bias = "bullish"
    elif bullish_count == 0:
        body_bias = "bearish"
    else:
        body_bias = "mixed"

    # ── SMA10 distance %: how far price is from SMA10 ────────────────────────
    # >0.4% above = overextended, likely to revert before a clean entry
    sma10_dist_pct = (
        round(((price - sma_10m) / sma_10m) * 100, 3)
        if sma_10m else None
    )

    # ── Last 5 closes as price history for AI trend context ──────────────────
    recent_closes = [round(c, 2) for c in closes[-5:]]

    return {
        "price":          price,
        "sma_10m":        round(sma_10m, 2) if sma_10m else None,
        "sma_30m":        round(sma_30m, 2) if sma_30m else None,
        "above_sma_10m":  bool(sma_10m and price > sma_10m),
        "above_sma_30m":  bool(sma_30m and price > sma_30m),
        "sma10_dist_pct": sma10_dist_pct,
        "momentum":       momentum,
        "volume_spike":   vol_spike,
        "rsi_14":         rsi,
        "body_bias":      body_bias,
        "recent_closes":  recent_closes,
    }

# ─── GROQ AI ───────────────────────────────────────────────────────────────────
def ask_groq(
    signals: dict,
    position: dict | None,
    available_usd: float,
    trade_history: list,
    news_context: dict,
) -> dict:
    """
    Asks Groq to analyze the market and make a fully autonomous decision.
    Prompt v4: fee-aware, strict checklist-based entry rules, no flip-flopping.
    """
    price = signals.get("price", 0)

    # ── Position context ─────────────────────────────────────────────────────
    if position:
        pnl = ((price - position["entry"]) / position["entry"]) * 100
        position_ctx = (
            f"OPEN POSITION:\n"
            f"  Entry Price : ${position['entry']:,.2f}\n"
            f"  ETH Size    : {position['size']}\n"
            f"  Current PnL : {pnl:+.2f}%"
        )
    else:
        position_ctx = "NO OPEN POSITION. Ready to enter."

    # ── Recent trade history (last 3) ────────────────────────────────────────
    if trade_history:
        history_lines = "\n".join(
            f"  [{t['time']}] {t['action']} @ ${t['price']} — {t['reasoning']}"
            for t in trade_history[-3:]
        )
        history_ctx = f"RECENT TRADES:\n{history_lines}"
    else:
        history_ctx = "RECENT TRADES: None yet."

    # ── Compact PRISM news struct ────────────────────────────────────────────
    prism_compact = {
        "bad_news_for_traders":     news_context.get("bad_news_for_traders"),
        "headline_risk":            news_context.get("headline_risk"),
        "eth_sentiment_score":      news_context.get("eth_sentiment_score"),
        "eth_sentiment_label":      news_context.get("eth_sentiment_label"),
        "strong_negative_articles": news_context.get("strong_negative_articles"),
        "headline_hints":           news_context.get("headline_hints"),
    }

    prompt = f"""You are Harold, an aggressive AI crypto scalper. You trade ETH/USD only.
Your goal is to MAXIMISE portfolio value. You are in a hackathon — inaction loses.

FEES: 0.26% per side = 0.52% round trip. Minimum move needed to profit: ~0.55%.
A fast exit on a losing trade saves more than a slow exit on a winning one.

━━━ MARKET SIGNALS ━━━
Price         : ${signals['price']:,.2f}
SMA-10m       : {signals.get('sma_10m')} | SMA-30m: {signals.get('sma_30m')}
Above SMA-10m : {signals.get('above_sma_10m')} | Above SMA-30m: {signals.get('above_sma_30m')}
SMA10 dist %  : {signals.get('sma10_dist_pct')}%
RSI-14        : {signals.get('rsi_14')}   (oversold <40 | overbought >65)
Momentum      : {signals.get('momentum')}
Candle bodies : {signals.get('body_bias')}
Volume spike  : {signals.get('volume_spike')}
Last 5 closes : {signals.get('recent_closes')}

━━━ NEWS SENTIMENT (PRISM) ━━━
{news_context.get('summary_for_ai', 'PRISM: no data.')}
{json.dumps(prism_compact, indent=2)}

━━━ ACCOUNT ━━━
Available USD : ${available_usd:,.2f}
{position_ctx}

━━━ TRADE HISTORY ━━━
{history_ctx}

━━━ CRITICAL: READ POSITION CONTEXT FIRST ━━━
If position_ctx says "OPEN POSITION", you ARE holding ETH right now.
Your job is EITHER to protect that profit OR cut that loss — not to buy more.
Buying when you already hold a position is IMPOSSIBLE. Only SELL or HOLD applies.
If position_ctx says "NO OPEN POSITION", only BUY or HOLD applies.

━━━ IF YOU HAVE AN OPEN POSITION — SELL RULES ━━━
Selling IS alpha. A good exit is as valuable as a good entry.
SELL immediately if ANY 1 of these is true:

  1. RSI-14 > 65 — overbought, momentum will flip, exit before it does
  2. momentum = "down" — trend broken, do not ride it down
  3. body_bias = "bearish" — candles turning red, price rejecting
  4. bad_news_for_traders = true — headline risk, exit first ask questions later
  5. recent_closes is a descending sequence (each close lower than last)
  6. price is below sma_10m — you are on the wrong side of the average
  7. Current PnL > +0.8% — you are profitable, lock it in before reversal
  8. Current PnL < -0.35% — cut the loss now, do not wait for SL to fire

  → If 2+ of the above are true: SELL is mandatory, not optional.
  → Do not HOLD an open position hoping it recovers. Scalpers exit fast.

━━━ IF YOU HAVE NO POSITION — BUY RULES ━━━
BUY when 4 of these 6 align:
  1. momentum = "up" OR 3+ consecutive rising closes
  2. body_bias = "bullish" OR "mixed" with upward closes
  3. RSI-14 below 65
  4. price above sma_10m
  5. sma10_dist_pct below +0.6%
  6. bad_news_for_traders = false

  → volume_spike = true AND momentum = "up": HIGH CONVICTION → BUY 20%
  → 4-5 conditions met: BUY 15%
  → exactly 3 conditions met, trend clearly up: BUY 10%

━━━ HOLD — only valid when ━━━
  No position AND signals are genuinely mixed with no clear direction.
  Never HOLD an open position when a SELL condition is triggered.

━━━ MINDSET ━━━
- You scalp. You do not invest. Get in, get out, repeat.
- Profits left on the table are losses. If you are up, sell.
- Losses held too long become disasters. If you are down 0.35%, sell.
- Check trade history: 2 consecutive SL hits = be selective on next BUY.
  Recent profits = trust the signals, keep cycling.

━━━ RESPOND IN EXACT JSON ONLY — NO OTHER TEXT ━━━
{{"action": "buy"|"sell"|"hold", "amount_percent": <10-20>, "reasoning": "<8 words max>"}}"""
    for attempt in range(1, 4):
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=100,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            err = str(e).lower()
            if ("429" in err or "rate limit" in err) and attempt < 3:
                wait = 5 * attempt
                log.warning(f"Groq rate limit. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            log.error(f"Groq error (attempt {attempt}): {e}")
            return {"action": "hold", "amount_percent": 0, "reasoning": "API error"}

    return {"action": "hold", "amount_percent": 0, "reasoning": "Max retries hit"}

# ─── STATUS MONITOR ────────────────────────────────────────────────────────────
def log_status(ticker_price: float, position: dict | None, starting_balance: float):
    """Prints a one-line status showing price, open trade PnL, and total capital PnL."""
    current_value = get_current_value()
    total_pnl_usd = current_value - starting_balance
    total_pnl_pct = (total_pnl_usd / starting_balance) * 100 if starting_balance else 0

    if position:
        trade_pnl_pct = ((ticker_price - position["entry"]) / position["entry"]) * 100
        trade_pnl_usd = trade_pnl_pct / 100 * (position["size"] * position["entry"])
        position_str  = (
            f"| TRADE PnL: {trade_pnl_pct:+.2f}% (${trade_pnl_usd:+,.2f}) "
            f"[entry=${position['entry']:,.2f}, size={position['size']} ETH]"
        )
    else:
        position_str = "| NO OPEN TRADE"

    log.info(
        f"📡 PRICE: ${ticker_price:,.2f} "
        f"| CAPITAL: ${current_value:,.2f} ({total_pnl_pct:+.2f}%, ${total_pnl_usd:+,.2f}) "
        f"{position_str}"
    )

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────
def run():
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  HAROLD V4 — HACKATHON MODE ACTIVATED  ")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── 1. Init / verify paper account ────────────────────────────────────────
    status = paper_status()
    if not status:
        log.info("No paper account found. Initialising with $10,000...")
        kraken_run(["paper", "init", "--balance", "10000"])
        status = paper_status()
        if not status:
            log.critical("Paper account init failed twice. Cannot continue. Exiting.")
            return

    starting_balance = float(status.get("starting_balance", 10000.0))
    log.info(f"Paper account confirmed. Starting balance: ${starting_balance:,.2f}")

    # ── 2. Recover crash state ─────────────────────────────────────────────────
    position = load_state()
    if position:
        log.info(
            f"💾 Recovered open trade — "
            f"entry=${position['entry']:,.2f}, size={position['size']} ETH"
        )

    # ── 3. Runtime state ───────────────────────────────────────────────────────
    last_ai_time  = 0
    last_sl_time  = 0   # Timestamp of last stop-loss fire (cooldown tracker)
    trade_history = []  # In-memory last 3 trades for AI context

    try:
        while True:
            now    = time.time()
            ticker = fetch_ticker()

            if ticker["price"] == 0.0:
                log.warning("Price fetch returned 0. Skipping this tick.")
                time.sleep(MONITOR_SEC)
                continue

            price = ticker["price"]

            # ── STATUS MONITOR ────────────────────────────────────────────────
            log_status(price, position, starting_balance)

            # ── SAFETY MONITOR: SL / TP ───────────────────────────────────────
            sl_tp_fired = False

            if position:
                pnl = ((price - position["entry"]) / position["entry"]) * 100

                if pnl >= TAKE_PROFIT:
                    log.info(f"✅ TAKE PROFIT HIT at {pnl:+.2f}% — Selling {position['size']} ETH")
                    res = paper_sell(SYMBOL_CLI, position["size"])
                    if res:
                        log_trade_to_csv("SELL(TP)", price, position["size"], f"TP +{TAKE_PROFIT}%")
                        trade_history.append({
                            "time":      datetime.now().strftime("%H:%M:%S"),
                            "action":    "SELL(TP)",
                            "price":     f"{price:,.2f}",
                            "reasoning": f"TP +{TAKE_PROFIT}%",
                        })
                        position = None
                        save_state(None)
                        sl_tp_fired = True
                    else:
                        log.error("TP sell order failed on Kraken CLI.")

                elif pnl <= STOP_LOSS:
                    log.warning(f"🛑 STOP LOSS at {pnl:+.2f}% — Selling {position['size']} ETH")
                    res = paper_sell(SYMBOL_CLI, position["size"])
                    if res:
                        log_trade_to_csv("SELL(SL)", price, position["size"], f"SL {STOP_LOSS}%")
                        trade_history.append({
                            "time":      datetime.now().strftime("%H:%M:%S"),
                            "action":    "SELL(SL)",
                            "price":     f"{price:,.2f}",
                            "reasoning": f"SL {STOP_LOSS}%",
                        })
                        position     = None
                        last_sl_time = now  # Start cooldown
                        save_state(None)
                        sl_tp_fired = True
                    else:
                        log.error("SL sell order failed on Kraken CLI.")

            # ── AI DECISION CYCLE ─────────────────────────────────────────────
            if not sl_tp_fired and (now - last_ai_time >= AI_CYCLE_SEC):

                # SL cooldown check — don't re-enter immediately after a stop
                cooldown_remaining = SL_COOLDOWN_SEC - (now - last_sl_time)
                if cooldown_remaining > 0:
                    log.info(
                        f"⏳ SL cooldown active — "
                        f"{int(cooldown_remaining)}s until next BUY allowed."
                    )
                    last_ai_time = now
                    time.sleep(MONITOR_SEC)
                    continue

                ohlc    = fetch_ohlc_with_retry()
                signals = build_signals(ticker, ohlc)

                log.info(
                    f"📊 AI CYCLE | ${signals['price']:,.2f} "
                    f"| SMA10: {signals.get('sma_10m')} "
                    f"| SMA30: {signals.get('sma_30m')} "
                    f"| RSI: {signals.get('rsi_14')} "
                    f"| Mom: {signals.get('momentum')} "
                    f"| Body: {signals.get('body_bias')} "
                    f"| Dist: {signals.get('sma10_dist_pct')}% "
                    f"| VolSpike: {signals.get('volume_spike')}"
                )

                available_usd = get_available_usd(position, price)

                news_ctx = fetch_trading_community_news_context(log=log)
                log.info(
                    f"📰 PRISM | bad_news={news_ctx.get('bad_news_for_traders')} "
                    f"| risk={news_ctx.get('headline_risk')} "
                    f"| {news_ctx.get('summary_for_ai', '')[:140]}"
                )

                decision = ask_groq(
                    signals, position, available_usd, trade_history, news_ctx
                )
                log.info(
                    f"🤖 Groq → {decision['action'].upper()} "
                    f"{decision.get('amount_percent', 0)}% | {decision['reasoning']}"
                )

                # ── EXECUTE: BUY ──────────────────────────────────────────────
                if decision["action"] == "buy" and position is None:
                    percent      = max(10.0, min(15.0, float(decision.get("amount_percent", 10))))
                    usd_to_spend = available_usd * (percent / 100)
                    trade_size   = round(usd_to_spend / price, 5)

                    log.info(
                        f"🚀 BUY {trade_size} ETH "
                        f"(${usd_to_spend:,.2f} at {percent}% of ${available_usd:,.2f})"
                    )
                    res = paper_buy(SYMBOL_CLI, trade_size)

                    if res:
                        position = {"entry": price, "size": trade_size}
                        save_state(position)
                        log_trade_to_csv("BUY", price, trade_size, decision["reasoning"])
                        trade_history.append({
                            "time":      datetime.now().strftime("%H:%M:%S"),
                            "action":    "BUY",
                            "price":     f"{price:,.2f}",
                            "reasoning": decision["reasoning"],
                        })
                    else:
                        log.error("BUY order failed on Kraken CLI.")

                # ── EXECUTE: SELL (AI decision) ───────────────────────────────
                elif decision["action"] == "sell" and position is not None:
                    log.info(f"📉 AI SELL {position['size']} ETH at ${price:,.2f}")
                    res = paper_sell(SYMBOL_CLI, position["size"])

                    if res:
                        log_trade_to_csv("SELL(AI)", price, position["size"], decision["reasoning"])
                        trade_history.append({
                            "time":      datetime.now().strftime("%H:%M:%S"),
                            "action":    "SELL(AI)",
                            "price":     f"{price:,.2f}",
                            "reasoning": decision["reasoning"],
                        })
                        position = None
                        save_state(None)
                    else:
                        log.error("AI SELL order failed on Kraken CLI.")

                last_ai_time = now

            time.sleep(MONITOR_SEC)

    except KeyboardInterrupt:
        print("\n")
        log.info("Manual shutdown received.")
        if position:
            while True:
                ans = input(
                    f"⚠️  Open position: {position['size']} ETH. Close it now? (y/n): "
                ).strip().lower()
                if ans == "y":
                    log.info("Selling open position before exit...")
                    res = paper_sell(SYMBOL_CLI, position["size"])
                    if res:
                        log_trade_to_csv(
                            "SELL(EXIT)", price, position["size"], "Manual shutdown"
                        )
                        save_state(None)
                        log.info("Position closed. State cleared.")
                    else:
                        log.error("Failed to close position on Kraken CLI.")
                    break
                elif ans == "n":
                    log.info("Leaving position open. State saved for next run.")
                    break
                else:
                    print("Please enter 'y' or 'n'.")

        log.info("Harold signing off. Good luck in the hackathon!")

if __name__ == "__main__":
    run()