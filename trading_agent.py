"""
AI Trading Agent — Harold (Kraken CLI Paper Mode)
================================================
Integrated with:
- Kraken CLI for live market data and paper trading.
- Groq (llama-3.3-70b-versatile) for AI analysis.
- CSV Logging for competition performance tracking.

Requirements:
    pip3 install python-dotenv groq requests
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
from groq import Groq

# ─── CONFIG & ENVIRONMENT ──────────────────────────────────────────────────────
load_dotenv()

GROQ_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_KEY:
    raise ValueError("Missing GROQ_API_KEY in .env file.")

groq_client = Groq(api_key=GROQ_KEY)

# Trading Settings
SYMBOL      = "XBTUSD"
TRADE_SIZE  = 0.001
TAKE_PROFIT = 1.0
STOP_LOSS   = -1.0
CYCLE_SEC   = 60
MONITOR_SEC = 15

# ─── LOGGING SETUP ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("harold")

# ─── COMPETITION LEDGER (CSV) ──────────────────────────────────────────────────

def log_trade_to_csv(action, price, size, reasoning):
    file_exists = os.path.isfile('trades_log.csv')
    try:
        with open('trades_log.csv', mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(['Timestamp', 'Action', 'Price', 'Size', 'Total_Value', 'Reasoning'])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                action.upper(),
                f"${price:,.2f}",
                size,
                f"${(price * size):,.2f}",
                reasoning
            ])
    except Exception as e:
        log.error(f"Failed to write to CSV: {e}")

# ─── KRAKEN CLI WRAPPER ────────────────────────────────────────────────────────

def kraken_run(args: list) -> dict:
    cmd = ["kraken", "-o", "json"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.error(f"CLI Error: {result.stderr.strip()}")
            return {}
        return json.loads(result.stdout)
    except Exception as e:
        log.error(f"CLI Timeout/JSON Error: {e}")
        return {}

# ─── MARKET DATA ───────────────────────────────────────────────────────────────

def fetch_ticker(symbol: str = "XBTUSD") -> dict:
    data = kraken_run(["ticker", symbol])
    if not data: return {"price": 0.0}
    ticker_data = list(data.values())[0]
    return {
        "price":  float(ticker_data.get("last") or ticker_data.get("c", [0])[0]),
        "high24": float(ticker_data.get("high") or ticker_data.get("h", [0, 1])[1]),
        "low24":  float(ticker_data.get("low")  or ticker_data.get("l", [0, 1])[1]),
    }

def fetch_ohlc(interval: int = 60) -> list:
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": "XBTUSD", "interval": interval},
            timeout=30
        )
        r.raise_for_status()
        return r.json()["result"].get("XXBTZUSD", [])
    except Exception:
        return []

def build_signals(ticker: dict, ohlc: list) -> dict:
    if not ohlc:
        return {"price": ticker["price"], "momentum": "unknown"}

    closes  = [float(c[4]) for c in ohlc]
    volumes = [float(c[6]) for c in ohlc]

    # SMAs
    sma_6  = sum(closes[-6:])  / 6  if len(closes) >= 6  else None
    sma_24 = sum(closes[-24:]) / 24 if len(closes) >= 24 else sum(closes) / len(closes)

    # Momentum: last 5 candles
    recent = closes[-5:]
    ups   = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
    downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
    momentum = "up" if ups >= 3 else ("down" if downs >= 3 else "flat")

    # Volume spike
    last_vol = volumes[-1] if volumes else 0
    avg_vol  = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 1
    vol_spike = last_vol > avg_vol * 2

    # Price position within 24h range
    price    = ticker["price"]
    high24   = ticker.get("high24", price)
    low24    = ticker.get("low24",  price)
    range24  = high24 - low24 if high24 != low24 else 1
    range_pct = round(((price - low24) / range24) * 100, 1)  # 0=at low, 100=at high

    return {
        "price":            price,
        "sma_6h":           round(sma_6,  2) if sma_6  else None,
        "sma_24h":          round(sma_24, 2),
        "price_vs_sma_6h":  ("above" if sma_6 and price > sma_6  else "below") if sma_6 else "unknown",
        "price_vs_sma_24h": "above" if price > sma_24 else "below",
        "momentum":         momentum,
        "volume_spike":     vol_spike,
        "range_position":   f"{range_pct}% of 24h range",
        "high_24h":         high24,
        "low_24h":          low24,
    }

# ─── AI CORE ───────────────────────────────────────────────────────────────────

def ask_groq(signals: dict, position: dict | None) -> dict:
    """
    Sends enriched market signals + position context to Groq.
    Returns a structured trading decision.
    """

    position_context = (
        f"OPEN POSITION: entry=${position['entry']:,.2f}, "
        f"current PnL={(( signals['price'] - position['entry']) / position['entry'] * 100):+.2f}%"
        if position else "NO OPEN POSITION"
    )

    prompt = f"""You are Harold, an elite quantitative crypto trading agent operating on Kraken paper trading.
Your single objective: maximize net PnL while protecting capital.

━━━ MARKET SNAPSHOT ━━━
{json.dumps(signals, indent=2)}

━━━ PORTFOLIO STATE ━━━
{position_context}

━━━ DECISION FRAMEWORK ━━━

ENTRY CONDITIONS (all must be met to BUY):
  • price_vs_sma_24h = "above"          → trend is bullish
  • price_vs_sma_6h  = "above"          → short-term confirms
  • momentum         = "up"             → recent candles rising
  • range_position   < 85%              → not overbought near 24h high

EXIT CONDITIONS (any one triggers SELL if in position):
  • momentum turns "down"
  • price_vs_sma_6h flips to "below"
  • range_position > 90%               → extended, likely reversal zone

HOLD when:
  • signals are mixed or conflicting
  • no position and entry conditions not fully met
  • volume_spike = false with weak momentum  → low conviction, wait

CAPITAL RULES:
  • amount_percent 1–2 → low conviction (1–2 signals align)
  • amount_percent 3–4 → medium (3 signals align)
  • amount_percent 5   → max (all signals align + volume spike)
  • Never go 5% when range_position > 80%

━━━ OUTPUT ━━━
Respond ONLY with a single valid JSON object. No explanation outside JSON.

{{
  "action": "buy" | "sell" | "hold",
  "amount_percent": <integer 0-5>,
  "reasoning": "<concise professional justification, max 15 words>"
}}"""

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=128,
            )
            return json.loads(response.choices[0].message.content)

        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "rate limit" in error_msg or "quota" in error_msg:
                if attempt < max_retries:
                    sleep_time = 10 * (2 ** (attempt - 1))
                    log.warning(f"Groq rate limited. Retrying in {sleep_time}s... ({attempt}/{max_retries})")
                    time.sleep(sleep_time)
                    continue
            log.error(f"Groq API Error: {e}")
            return {"action": "hold", "amount_percent": 0, "reasoning": "API error fallback"}

    return {"action": "hold", "amount_percent": 0, "reasoning": "Max retries exceeded"}

# ─── MAIN TRADING ENGINE ───────────────────────────────────────────────────────

def run():
    log.info("━━━ HAROLD AI STARTING (COMPETITION MODE) ━━━")
    position        = None
    last_cycle_time = 0

    try:
        while True:
            now = time.time()

            # 1. AI Decision Cycle
            if now - last_cycle_time >= CYCLE_SEC:
                ticker   = fetch_ticker(SYMBOL)
                ohlc     = fetch_ohlc()
                signals  = build_signals(ticker, ohlc)
                decision = ask_groq(signals, position)  # position passed for context

                log.info(f"Groq → {decision['action'].upper()} {decision['amount_percent']}% | {decision['reasoning']}")

                if decision["action"] == "buy" and position is None:
                    res = kraken_run(["paper", "order", "buy", SYMBOL, str(TRADE_SIZE), "--type", "market"])
                    if res:
                        position = {"entry": ticker["price"], "size": TRADE_SIZE}
                        log_trade_to_csv("BUY", ticker["price"], TRADE_SIZE, decision["reasoning"])
                        log.info(f"🚀 Bought @ ${ticker['price']:,.2f}")

                elif decision["action"] == "sell" and position is not None:
                    kraken_run(["paper", "order", "sell", SYMBOL, str(TRADE_SIZE), "--type", "market"])
                    log_trade_to_csv("SELL", ticker["price"], TRADE_SIZE, f"AI: {decision['reasoning']}")
                    log.info(f"📉 AI closed position @ ${ticker['price']:,.2f}")
                    position = None

                last_cycle_time = now

            # 2. Safety Monitor (TP / SL)
            if position:
                current_price = fetch_ticker(SYMBOL)["price"]
                pnl = ((current_price - position["entry"]) / position["entry"]) * 100
                log.info(f"Monitor: PnL {pnl:+.2f}% | BTC ${current_price:,.2f}")

                if pnl >= TAKE_PROFIT:
                    kraken_run(["paper", "order", "sell", SYMBOL, str(position["size"]), "--type", "market"])
                    log_trade_to_csv("SELL (TP)", current_price, position["size"], f"Hit TP +{TAKE_PROFIT}%")
                    position = None
                    log.info("✅ Take profit hit. Profit locked.")

                elif pnl <= STOP_LOSS:
                    kraken_run(["paper", "order", "sell", SYMBOL, str(position["size"]), "--type", "market"])
                    log_trade_to_csv("SELL (SL)", current_price, position["size"], f"Hit SL {STOP_LOSS}%")
                    position = None
                    log.warning("🛑 Stop loss triggered.")

            time.sleep(MONITOR_SEC)

    except KeyboardInterrupt:
        log.info("Manual shutdown. Goodbye.")

if __name__ == "__main__":
    run()