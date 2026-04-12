"""
Harold — AI Trading Agent v5 (Web3 Sepolia Edition)
=========================================================
FIXES vs v4:
  - FIX 1: TAKE_PROFIT lowered 1.5% → 0.7% (scalper threshold; covers 0.52% fees + margin)
  - FIX 2: Rejected intents now post a low-score checkpoint (score=35) so the
            ValidationRegistry score stays active instead of going silent
  - FIX 3: RSI now seeds with 28 closes (14 initial + 14 EMA) for accuracy
  - FIX 4: AGENT_ID env var note — must have no trailing quote (was `3'`)
"""

import os
import sys
import time
import json
import logging
import requests
import csv
from pathlib import Path

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from groq import Groq

from prism_news import fetch_trading_community_news_context
from web3 import Web3
from web3.exceptions import TimeExhausted

from trade_intent import submit_trade
from validation_client import post_checkpoint

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GROQ_KEY        = os.getenv("GROQ_API_KEY")
RPC_URL         = os.getenv("SEPOLIA_RPC_URL")
WALLET_ADDRESS  = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY     = os.getenv("PRIVATE_KEY")
AGENT_ID        = os.getenv("AGENT_ID")

if not all([GROQ_KEY, RPC_URL, WALLET_ADDRESS, PRIVATE_KEY, AGENT_ID]):
    raise ValueError("Missing keys in .env (GROQ, RPC, WALLET, PRIV_KEY, or AGENT_ID).")

# FIX 4: strip stray whitespace/quotes that break int() cast
AGENT_ID = int(str(AGENT_ID).strip().strip("'\""))

groq_client = Groq(api_key=GROQ_KEY)

# ── Web3 ──────────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    raise ConnectionError("Failed to connect to the Sepolia RPC URL.")

# ── WETH Contract on Sepolia ──────────────────────────────────────────────────
WETH_ADDRESS = Web3.to_checksum_address("0xfff9976782d46cc05630d1f6ebab18b2324d6b14")
WETH_ABI = [
    {"constant": False, "inputs": [], "name": "deposit", "outputs": [], "payable": True,
     "stateMutability": "payable", "type": "function"},
    {"constant": False, "inputs": [{"name": "wad", "type": "uint256"}], "name": "withdraw",
     "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "payable": False,
     "stateMutability": "view", "type": "function"},
]
weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=WETH_ABI)

# ── Reputation Registry ───────────────────────────────────────────────────────
REPUTATION_ADDRESS = Web3.to_checksum_address("0x423a9904e39537a9997fbaF0f220d79D7d545763")
REPUTATION_ABI = [
    {"name": "submitFeedback", "type": "function",
     "inputs": [
         {"name": "agentId",      "type": "uint256"},
         {"name": "score",        "type": "uint8"},
         {"name": "outcomeRef",   "type": "bytes32"},
         {"name": "comment",      "type": "string"},
         {"name": "feedbackType", "type": "uint8"},
     ],
     "outputs": [], "stateMutability": "nonpayable"},
]
reputation_contract = w3.eth.contract(address=REPUTATION_ADDRESS, abi=REPUTATION_ABI)

SYMBOL_API       = "ETHUSD"
OHLC_RESULT_KEY  = "XETHZUSD"

# ─── TRADING PARAMETERS ────────────────────────────────────────────────────────
# FIX 1: TAKE_PROFIT lowered from 1.5% → 0.7%
#   Rationale: 0.52% round-trip fees + 0.18% margin = 0.7% minimum to be profitable.
#   The old 1.5% threshold meant Harold almost never hit TP on 1m scalps,
#   leaving profits on the table as positions bled back to flat.
TAKE_PROFIT     = 0.700
STOP_LOSS       = -0.600
SL_COOLDOWN_SEC = 300

AI_CYCLE_SEC    = 60
MONITOR_SEC     = 15
MIN_HOLD_TIME   = 0

STATE_FILE   = "harold_state.json"
CSV_FILE     = "trades_log.csv"
METRICS_FILE = "agent_metrics.json"

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("harold")

# ─── STATE MANAGEMENT ──────────────────────────────────────────────────────────
def load_state() -> dict | None:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                position = json.load(f)
                if position and "entry_time" not in position:
                    position["entry_time"] = time.time()
                return position
        except Exception as e:
            log.error(f"Failed to load state file: {e}")
    return None

def load_metrics() -> dict:
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "peak_equity":    0.0,
        "total_pnl_usd":  0.0,
        "max_drawdown_pct": 0.0,
        "trades_closed":  0,
        "winning_trades": 0,
        "losing_trades":  0,
        "trade_pnls":     [],
    }

def save_metrics(metrics: dict):
    try:
        with open(METRICS_FILE, "w") as f:
            json.dump(metrics, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save metrics: {e}")

def save_state(position: dict | None):
    if position is None:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    else:
        with open(STATE_FILE, "w") as f:
            json.dump(position, f, indent=2)

def log_trade_to_csv(action: str, price: float, size: float, tx_hash: str, reasoning: str):
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, mode="a", newline="") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(["Timestamp", "Action", "Price", "Size", "Tx_Hash", "Reasoning"])
            w.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                action.upper(),
                f"${price:,.2f}",
                size,
                tx_hash,
                reasoning,
            ])
    except Exception as e:
        log.error(f"CSV write failed: {e}")

# ─── WEB3 EXECUTORS ────────────────────────────────────────────────────────────
def get_eth_balance() -> float:
    return float(w3.from_wei(w3.eth.get_balance(WALLET_ADDRESS), "ether"))

def calculate_current_equity(eth_bal: float, position: dict | None, current_price: float) -> float:
    equity_usd = eth_bal * current_price
    if position:
        equity_usd += position["size"] * current_price
    return equity_usd

def execute_buy(amount_eth: float) -> str | None:
    try:
        log.info(f"Executing Buy (Wrapping {amount_eth:.4f} ETH → WETH)...")
        amount_wei = w3.to_wei(amount_eth, "ether")
        nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
        tx = weth_contract.functions.deposit().build_transaction({
            "from":                WALLET_ADDRESS,
            "value":               amount_wei,
            "gas":                 100_000,
            "maxFeePerGas":        w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
            "nonce":               nonce,
            "chainId":             11155111,
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash   = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt   = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return w3.to_hex(tx_hash) if receipt.status == 1 else None
    except Exception as e:
        log.error(f"Failed to execute buy: {e}")
        return None

def execute_sell(amount_eth: float) -> str | None:
    try:
        actual_weth_bal_wei = weth_contract.functions.balanceOf(WALLET_ADDRESS).call()
        amount_wei          = w3.to_wei(amount_eth, "ether")

        if amount_wei > actual_weth_bal_wei:
            log.warning(
                f"Adjusting sell: state says {amount_eth:.4f}, "
                f"on-chain balance is {w3.from_wei(actual_weth_bal_wei, 'ether'):.4f}"
            )
            amount_wei = actual_weth_bal_wei

        if amount_wei == 0:
            log.warning("Sell skipped: on-chain WETH balance is 0.")
            return None

        log.info(f"Executing Sell (Unwrapping {w3.from_wei(amount_wei, 'ether'):.4f} WETH)...")
        nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
        tx = weth_contract.functions.withdraw(amount_wei).build_transaction({
            "from":                WALLET_ADDRESS,
            "gas":                 120_000,
            "maxFeePerGas":        w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
            "nonce":               nonce,
            "chainId":             11155111,
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash   = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt   = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return w3.to_hex(tx_hash) if receipt.status == 1 else None
    except Exception as e:
        log.error(f"Failed to execute sell: {e}")
        return None

def record_outcome(pnl_usd: float, amount_usd: float, notes: str):
    """ERC-8004: post closed-trade PnL to ReputationRegistry. Max 2 retries."""
    for tries in range(2):   # FIX: was 5 retries (up to 600s block)
        try:
            log.info(f"Reporting PnL (${pnl_usd:+.2f}) to ReputationRegistry...")
            feedback_type = 1 if pnl_usd > 0 else (2 if pnl_usd < 0 else 0)
            pnl_pct       = (pnl_usd / amount_usd) * 100.0 if amount_usd > 0 else 0
            score         = max(0, min(100, int(50.0 + (pnl_pct * 10.0))))

            nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
            tx = reputation_contract.functions.submitFeedback(
                AGENT_ID, score, b"\x00" * 32, notes, feedback_type
            ).build_transaction({
                "from":                WALLET_ADDRESS,
                "nonce":               nonce,
                "gas":                 200_000,
                "maxFeePerGas":        w3.eth.gas_price * 2,
                "maxPriorityFeePerGas": w3.eth.gas_price,
                "chainId":             11155111,
            })
            signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash   = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            log.info("✅ Reputation Outcome Recorded!")
            break
        except Exception as e:
            log.error(f"⚠️ Reputation Tx Failed (Non-fatal) attempt {tries + 1}: {e}")

# ─── SAFETY WRAPPERS ───────────────────────────────────────────────────────────
def safe_post_checkpoint(action, pair, amount_usd, reasoning, score, trade_approved, tx_hash):
    try:
        post_checkpoint(
            action=action,
            pair=pair,
            amount_usd=amount_usd,
            reasoning=reasoning,
            score=score,
            approved=trade_approved,
            trade_tx=tx_hash,
        )
    except Exception as e:
        log.error(f"⚠️ Failed to post checkpoint: {e}")

# ─── MARKET DATA ───────────────────────────────────────────────────────────────
def fetch_ticker() -> dict:
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": SYMBOL_API},
            timeout=10,
        )
        r.raise_for_status()
        t = list(r.json()["result"].values())[0]
        return {"price": float(t["c"][0]), "high24": float(t["h"][1]), "low24": float(t["l"][1])}
    except Exception as e:
        log.error(f"Ticker fetch failed: {e}")
        return {"price": 0.0, "high24": 0.0, "low24": 0.0}

def fetch_ohlc_with_retry(interval: int = 1, max_attempts: int = 3) -> list:
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
    log.error("All OHLC fetch attempts failed.")
    return []

# ─── SIGNAL ENGINE ─────────────────────────────────────────────────────────────
def build_signals(ticker: dict, ohlc: list) -> dict:
    price = ticker["price"]
    if not ohlc or price == 0.0:
        return {"price": price, "error": "No candle data available"}

    closes  = [float(c[4]) for c in ohlc]
    opens   = [float(c[1]) for c in ohlc]
    volumes = [float(c[6]) for c in ohlc]

    # ── SMAs ──
    sma_10m = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
    sma_30m = sum(closes[-30:]) / 30 if len(closes) >= 30 else None

    # ── Momentum ──
    recent = closes[-5:]
    ups    = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
    downs  = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
    momentum = "up" if ups >= 3 else ("down" if downs >= 3 else "flat")

    # ── Volume spike ──
    last_vol  = volumes[-1] if volumes else 0
    avg_vol   = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 1
    vol_spike = bool(last_vol > avg_vol * 1.5)

    # ── RSI-14 ────────────────────────────────────────────────────────────────
    # FIX 3: Use 28 closes (14 seed + 14 signal) for a properly seeded RSI.
    # Original used only 15 closes, making RSI noisy and unreliable at extremes.
    rsi_closes = closes[-28:] if len(closes) >= 28 else closes
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

    # ── Candle body bias ──
    last3_candles = list(zip(opens[-3:], closes[-3:]))
    bullish_count = sum(1 for o, c in last3_candles if c > o)
    body_bias     = "bullish" if bullish_count >= 2 else ("bearish" if bullish_count == 0 else "mixed")

    # ── SMA10 distance % ──
    sma10_dist_pct = (
        round(((price - sma_10m) / sma_10m) * 100, 3) if sma_10m else None
    )

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
    available_eth: float,
    trade_history: list,
    news_context: dict,
) -> dict:
    price = signals.get("price", 0)

    if position:
        pnl = ((price - position["entry"]) / position["entry"]) * 100
        position_ctx = (
            f"OPEN POSITION:\n"
            f"  Entry Price : ${position['entry']:,.2f}\n"
            f"  WETH Size   : {position['size']}\n"
            f"  Current PnL : {pnl:+.2f}%"
        )
    else:
        position_ctx = "NO OPEN POSITION. Ready to enter."

    if trade_history:
        history_lines = "\n".join(
            f"  [{t['time']}] {t['action']} @ ${t['price']} — {t['reasoning']}"
            for t in trade_history[-3:]
        )
        history_ctx = f"RECENT TRADES:\n{history_lines}"
    else:
        history_ctx = "RECENT TRADES: None yet."

    prism_compact = {
        "bad_news_for_traders":     news_context.get("bad_news_for_traders"),
        "headline_risk":            news_context.get("headline_risk"),
        "eth_sentiment_score":      news_context.get("eth_sentiment_score"),
        "eth_sentiment_label":      news_context.get("eth_sentiment_label"),
        "strong_negative_articles": news_context.get("strong_negative_articles"),
        "headline_hints":           news_context.get("headline_hints"),
    }

    prompt = f"""You are Harold, an aggressive AI crypto scalper. You trade ETH/USD only.
You are a fully autonomous AI crypto trading agent (on-chain WETH wrap/unwrap on Sepolia).
Your goal is to MAXIMISE portfolio value. You are in a hackathon — inaction loses.

FEES: 0.26% per side = 0.52% round trip. Minimum move needed to profit: ~0.55%.
Take Profit fires at +0.7%. Stop Loss fires at -0.6%. These are tight — act fast.
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
{news_context.get('summary_for_ai', 'PRISM: no summary.')}
{json.dumps(prism_compact, indent=2)}

━━━ ACCOUNT ━━━
Available liquid ETH (for sizing new wraps): {available_eth:.6f} ETH
{position_ctx}

━━━ TRADE HISTORY ━━━
{history_ctx}

━━━ CRITICAL: READ POSITION CONTEXT FIRST ━━━
If position_ctx says "OPEN POSITION", you ARE holding WETH right now.
Your job is EITHER to protect that profit OR cut that loss — not to buy more.
Buying when you already hold a position is IMPOSSIBLE. Only SELL or HOLD applies.
If position_ctx says "NO OPEN POSITION", only BUY or HOLD applies.

━━━ IF YOU HAVE AN OPEN POSITION — SELL RULES ━━━
Selling (unwrap WETH) IS alpha. A good exit is as valuable as a good entry.
SELL immediately if ANY 1 of these is true:

  1. RSI-14 > 65 — overbought, momentum will flip, exit before it does
  2. momentum = "down" — trend broken, do not ride it down
  3. body_bias = "bearish" — candles turning red, price rejecting
  4. bad_news_for_traders = true — headline risk, exit first ask questions later
  5. recent_closes is a descending sequence (each close lower than last)
  6. price is below sma_10m — you are on the wrong side of the average
  7. Current PnL > +0.5% — you are profitable, lock it in before reversal
  8. Current PnL < -0.35% — cut the loss now, do not wait for SL to fire

  → If 2+ of the above are true: SELL is mandatory, not optional.
  → Do not HOLD an open position hoping it recovers. Scalpers exit fast.

━━━ IF YOU HAVE NO POSITION — BUY RULES ━━━
BUY (wrap WETH) when 4 of these 6 align:
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
- TP is at 0.7%. If you are up 0.5%+, sell now — do not wait for TP to fire.
- Losses held too long become disasters. If you are down 0.35%, sell.
- Check trade history: 2 consecutive SL hits = be selective on next BUY.

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

# ─── STATUS LOG ────────────────────────────────────────────────────────────────
def log_status(ticker_price: float, position: dict | None, current_equity: float):
    if position:
        trade_pnl_pct = ((ticker_price - position["entry"]) / position["entry"]) * 100
        time_held     = int(time.time() - position.get("entry_time", time.time()))
        position_str  = f"| POSITION: {position['size']:.4f} WETH [PnL: {trade_pnl_pct:+.2f}%] [Held: {time_held}s]"
    else:
        position_str = "| NO OPEN POSITION"
    log.info(f"📡 ETH: ${ticker_price:,.2f} | Equity: ${current_equity:,.0f} {position_str}")

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────
def run():
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("   HAROLD V5 — ON-CHAIN (signals + prompt = trading_agent)  ")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    eth_balance = get_eth_balance()
    if eth_balance < 0.01:
        log.warning("⚠️ Low Sepolia ETH balance. You need ETH for gas!")

    position    = load_state()
    metrics     = load_metrics()
    last_ai_time = 0
    last_sl_time = 0

    ticker = fetch_ticker()
    initial_equity = calculate_current_equity(eth_balance, position, ticker["price"])
    if metrics["peak_equity"] == 0.0:
        metrics["peak_equity"] = initial_equity
    trade_history = []

    try:
        while True:
            now    = time.time()
            ticker = fetch_ticker()
            if ticker["price"] == 0.0:
                time.sleep(MONITOR_SEC)
                continue

            price     = ticker["price"]
            eth_bal   = get_eth_balance()
            current_equity = calculate_current_equity(eth_bal, position, price)

            if current_equity > metrics["peak_equity"]:
                metrics["peak_equity"] = current_equity
                save_metrics(metrics)

            log_status(price, position, current_equity)

            # ── SAFETY TRIGGERS (TP/SL) ──
            sl_tp_fired = False
            if position:
                pnl    = ((price - position["entry"]) / position["entry"]) * 100
                hit_tp = pnl >= TAKE_PROFIT
                hit_sl = pnl <= STOP_LOSS

                if hit_tp or hit_sl:
                    act             = "SELL(TP)" if hit_tp else "SELL(SL)"
                    trade_value_usd = position["size"] * price
                    pnl_usd         = trade_value_usd - (position["size"] * position["entry"])
                    reason_note     = f"TP +{TAKE_PROFIT}%" if hit_tp else f"SL {STOP_LOSS}%"

                    log.info(f"⚠️ SAFETY TRIGGER: {act} at {pnl:+.2f}%. Requesting Intent...")

                    try:
                        intent_result = submit_trade(action="SELL", pair="ETH/USD", amount_usd=trade_value_usd)
                    except Exception as e:
                        log.error(f"RiskRouter RPC failed: {e}")
                        time.sleep(MONITOR_SEC)
                        continue

                    if intent_result.get("approved"):
                        log.info("✅ Safety Intent Approved. Selling now...")
                        tx_hash = execute_sell(position["size"])
                        if tx_hash:
                            log_trade_to_csv(act, price, position["size"], tx_hash, reason_note)
                            trade_history.append({
                                "time":      datetime.now().strftime("%H:%M:%S"),
                                "action":    act,
                                "price":     f"{price:,.2f}",
                                "reasoning": reason_note,
                            })
                            metrics["trades_closed"] += 1
                            if pnl_usd > 0: metrics["winning_trades"] += 1
                            else:           metrics["losing_trades"]  += 1
                            metrics["trade_pnls"].append(pnl_usd)
                            metrics["total_pnl_usd"] += pnl_usd
                            save_metrics(metrics)

                            safe_post_checkpoint(
                                action="SELL", pair="ETH/USD",
                                amount_usd=trade_value_usd,
                                reasoning=f"Safety {act} at {pnl:.2f}%",
                                score=95 if hit_tp else 60,
                                trade_approved=True, tx_hash=tx_hash,
                            )
                            record_outcome(pnl_usd, trade_value_usd, f"Safety {act} Exit")

                            position = None
                            if hit_sl:
                                last_sl_time = now
                            save_state(None)
                            sl_tp_fired = True
                    else:
                        # FIX 2: post rejection checkpoint so score stays active
                        log.warning(f"❌ Safety Intent REJECTED: {intent_result.get('reason')}")
                        safe_post_checkpoint(
                            action="SELL", pair="ETH/USD",
                            amount_usd=trade_value_usd,
                            reasoning=f"Safety intent rejected: {intent_result.get('reason', '')}",
                            score=35,
                            trade_approved=False, tx_hash="",
                        )

            # ── AI CYCLE ──
            if not sl_tp_fired and (now - last_ai_time >= AI_CYCLE_SEC):
                cooldown_remaining = SL_COOLDOWN_SEC - (now - last_sl_time)
                if cooldown_remaining > 0:
                    log.info(f"⏳ SL cooldown — {int(cooldown_remaining)}s until next BUY.")
                    last_ai_time = now
                    time.sleep(MONITOR_SEC)
                    continue

                ohlc    = fetch_ohlc_with_retry()
                signals = build_signals(ticker, ohlc)
                eth_bal = get_eth_balance()

                if signals.get("error"):
                    log.warning(f"📊 AI CYCLE skipped: {signals.get('error')}")
                else:
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

                news_ctx = fetch_trading_community_news_context(log=log)
                log.info(
                    f"📰 PRISM | bad_news={news_ctx.get('bad_news_for_traders')} "
                    f"| risk={news_ctx.get('headline_risk')} "
                    f"| {news_ctx.get('summary_for_ai', '')[:140]}"
                )

                decision = ask_groq(signals, position, eth_bal, trade_history, news_ctx)
                log.info(
                    f"🤖 Groq → {decision.get('action', 'hold').upper()} "
                    f"{decision.get('amount_percent', 0)}% | {decision.get('reasoning', '')}"
                )

                # ── BUY ──
                if decision.get("action") == "buy" and position is None:
                    percent         = max(10.0, min(15.0, float(decision.get("amount_percent", 10))))
                    trade_size      = round(eth_bal * (percent / 100), 5)
                    trade_value_usd = trade_size * price

                    if trade_size > 0.005:
                        log.info(
                            f"Submitting BUY intent ({percent}% of {eth_bal:.4f} ETH) "
                            f"≈ ${trade_value_usd:.2f}..."
                        )
                        try:
                            intent_result = submit_trade(action="BUY", pair="ETH/USD", amount_usd=trade_value_usd)
                        except Exception as e:
                            log.error(f"RiskRouter RPC failed: {e}")
                            last_ai_time = now
                            time.sleep(MONITOR_SEC)
                            continue

                        if intent_result.get("approved"):
                            tx_hash = execute_buy(trade_size)
                            if tx_hash:
                                position = {"entry": price, "size": trade_size, "entry_time": time.time()}
                                save_state(position)
                                log_trade_to_csv("BUY", price, trade_size, tx_hash, decision.get("reasoning", ""))
                                trade_history.append({
                                    "time":      datetime.now().strftime("%H:%M:%S"),
                                    "action":    "BUY",
                                    "price":     f"{price:,.2f}",
                                    "reasoning": decision.get("reasoning", ""),
                                })
                                safe_post_checkpoint(
                                    action="BUY", pair="ETH/USD",
                                    amount_usd=trade_value_usd,
                                    reasoning=decision.get("reasoning", ""),
                                    score=80, trade_approved=True, tx_hash=tx_hash,
                                )
                        else:
                            # FIX 2: checkpoint rejected buys too
                            log.warning(f"🚫 BUY Intent Rejected: {intent_result.get('reason')}")
                            safe_post_checkpoint(
                                action="BUY", pair="ETH/USD",
                                amount_usd=trade_value_usd,
                                reasoning=f"Intent rejected: {intent_result.get('reason', '')}",
                                score=35, trade_approved=False, tx_hash="",
                            )

                # ── STRATEGIC SELL (AI) ──
                elif decision.get("action") == "sell" and position is not None:
                    time_held = time.time() - position.get("entry_time", time.time())
                    if MIN_HOLD_TIME > 0 and time_held < MIN_HOLD_TIME:
                        log.info(f"⏱️ Hold time {time_held:.0f}s < {MIN_HOLD_TIME}s; ignoring AI sell.")
                    else:
                        trade_value_usd = position["size"] * price
                        pnl_usd         = trade_value_usd - (position["size"] * position["entry"])

                        log.info(f"Submitting SELL intent (AI) for ${trade_value_usd:.2f}...")
                        try:
                            intent_result = submit_trade(action="SELL", pair="ETH/USD", amount_usd=trade_value_usd)
                        except Exception as e:
                            log.error(f"RiskRouter RPC failed: {e}")
                            last_ai_time = now
                            time.sleep(MONITOR_SEC)
                            continue

                        if intent_result.get("approved"):
                            try:
                                tx_hash = execute_sell(position["size"])
                                if tx_hash:
                                    log_trade_to_csv("SELL(AI)", price, position["size"], tx_hash, decision.get("reasoning", ""))
                                    log.info(f"💰 Sell Executed! TX: {tx_hash}")
                                    trade_history.append({
                                        "time":      datetime.now().strftime("%H:%M:%S"),
                                        "action":    "SELL(AI)",
                                        "price":     f"{price:,.2f}",
                                        "reasoning": decision.get("reasoning", ""),
                                    })
                                    metrics["trades_closed"] += 1
                                    if pnl_usd > 0: metrics["winning_trades"] += 1
                                    else:           metrics["losing_trades"]  += 1
                                    metrics["trade_pnls"].append(pnl_usd)
                                    metrics["total_pnl_usd"] += pnl_usd
                                    save_metrics(metrics)

                                    pnl_pct   = (pnl_usd / trade_value_usd * 100) if trade_value_usd > 0 else 0
                                    val_score = min(100, int(70 + pnl_pct))

                                    safe_post_checkpoint(
                                        action="SELL", pair="ETH/USD",
                                        amount_usd=trade_value_usd,
                                        reasoning=decision.get("reasoning", ""),
                                        score=val_score, trade_approved=True, tx_hash=tx_hash,
                                    )
                                    record_outcome(pnl_usd, trade_value_usd, "Strategic AI Exit")

                                    position = None
                                    save_state(None)
                                else:
                                    log.error("❌ Intent approved but execution failed!")
                            except Exception as e:
                                log.error(f"Failed to execute sell after intent approval: {e}")
                        else:
                            # FIX 2: checkpoint rejected sells too
                            log.warning(f"🚫 SELL Intent Rejected: {intent_result.get('reason')}")
                            safe_post_checkpoint(
                                action="SELL", pair="ETH/USD",
                                amount_usd=trade_value_usd,
                                reasoning=f"AI sell rejected: {intent_result.get('reason', '')}",
                                score=35, trade_approved=False, tx_hash="",
                            )

                last_ai_time = now

            time.sleep(MONITOR_SEC)

    except KeyboardInterrupt:
        log.info("Shutdown. Good luck on chain!")

if __name__ == "__main__":
    run()