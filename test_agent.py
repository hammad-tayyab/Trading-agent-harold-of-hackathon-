"""
AI Trading Agent — Kraken Futures Demo
=======================================
Python port of the browser-based JS trading agent.
Uses Kraken's public REST API for market data and demo futures API for paper trading.
Groq (llama-3.3-70b-versatile) acts as the decision-maker.

Requirements:
    pip install requests python-dotenv groq

Usage:
    python trading_agent.py
"""

import os
import time
import hmac
import hashlib
import base64
import json
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv
from groq import Groq

# ─── CONFIG & ENVIRONMENT ──────────────────────────────────────────────────────
load_dotenv()

API_KEY    = os.getenv("KRAKEN_DEMO_KEY")
API_SECRET = os.getenv("KRAKEN_DEMO_SECRET")
GROQ_KEY   = os.getenv("GROQ_API_KEY")

if not all([API_KEY, API_SECRET, GROQ_KEY]):
    raise ValueError("Missing environment variables. Please check your .env file.")

groq_client = Groq(api_key=GROQ_KEY)

SYMBOL      = "PI_XBTUSD"
TRADE_SIZE  = 50
TAKE_PROFIT = 0.1
STOP_LOSS   = -0.1
CYCLE_SEC   = 300
MONITOR_SEC = 10

KRAKEN_PUBLIC = "https://api.kraken.com/0/public"
KRAKEN_DEMO   = "https://demo-futures.kraken.com/derivatives"

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("agent")

# ─── RETRY HELPER ──────────────────────────────────────────────────────────────

def with_retry(fn, retries=3, delay=5):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            if attempt == retries:
                raise RuntimeError(f"All {retries} retries failed: {e}") from e
            log.warning(f"Network error (attempt {attempt}/{retries}): {e} — retrying in {delay}s...")
            time.sleep(delay * attempt)

# ─── KRAKEN AUTHENTICATION ─────────────────────────────────────────────────────

def kraken_sign(endpoint_path: str, nonce: str, post_data: str) -> str:
    message   = post_data + nonce + endpoint_path
    sha256    = hashlib.sha256(message.encode()).digest()
    secret    = base64.b64decode(API_SECRET)
    signature = hmac.new(secret, sha256, hashlib.sha512).digest()
    return base64.b64encode(signature).decode()

def auth_headers(endpoint_path: str, nonce: str, post_data: str) -> dict:
    return {
        "APIKey":       API_KEY,
        "Authent":      kraken_sign(endpoint_path, nonce, post_data),
        "Nonce":        nonce,
        "Content-Type": "application/x-www-form-urlencoded",
    }

# ─── MARKET DATA ───────────────────────────────────────────────────────────────

def fetch_ticker(pair: str = "XBTUSD") -> dict:
    r = requests.get(f"{KRAKEN_PUBLIC}/Ticker", params={"pair": pair}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    ticker = list(data["result"].values())[0]
    return {
        "price":  float(ticker["c"][0]),
        "vol24":  float(ticker["v"][1]),
        "high24": float(ticker["h"][1]),
        "low24":  float(ticker["l"][1]),
        "vwap24": float(ticker["p"][1]),
    }


def fetch_ohlc(pair: str = "XBTUSD", interval: int = 60) -> list:
    r = requests.get(
        f"{KRAKEN_PUBLIC}/OHLC",
        params={"pair": pair, "interval": interval},
        timeout=30
    )
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    candles = [v for v in data["result"].values() if isinstance(v, list)][0]
    return candles


def calc_sma(closes: list, n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def calc_momentum(closes: list, n: int = 4) -> str:
    if len(closes) < n + 1:
        return "unknown"
    recent = closes[-n:]
    ups   = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
    downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
    if ups > downs:   return "up"
    if downs > ups:   return "down"
    return "flat"


def build_signals(ticker: dict, ohlc: list) -> dict:
    closes  = [float(c[4]) for c in ohlc]
    volumes = [float(c[6]) for c in ohlc]

    sma_6h  = calc_sma(closes, 6)
    sma_24h = calc_sma(closes, min(24, len(closes)))

    last_vol = volumes[-1] if volumes else 0
    avg_vol  = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 1
    spike    = last_vol > avg_vol * 2

    price = ticker["price"]

    return {
        "price":             price,
        "sma_6h":            round(sma_6h,  2) if sma_6h  else None,
        "sma_24h":           round(sma_24h, 2) if sma_24h else None,
        "price_vs_sma_6h":  ("above" if price > sma_6h  else "below") if sma_6h  else "unknown",
        "price_vs_sma_24h": ("above" if price > sma_24h else "below") if sma_24h else "unknown",
        "momentum":          calc_momentum(closes),
        "volume_spike":      spike,
        "volume_24h":        round(ticker["vol24"], 2),
        "high_24h":          ticker["high24"],
        "low_24h":           ticker["low24"],
    }

# ─── GROQ DECISION ─────────────────────────────────────────────────────────────

def ask_groq(signals: dict) -> dict:
    """
    Send market signals to Groq (llama-3.3-70b-versatile) and get a trading decision.
    Uses JSON mode for structured output. Includes exponential backoff for rate limits.
    """
    prompt = f"""You are a crypto futures trading agent on Kraken demo.

Current market signals for PI_XBTUSD:
{json.dumps(signals, indent=2)}

Rules:
- Only trade if signals are clearly aligned (momentum + SMA agreement)
- Never exceed 5% portfolio per trade
- When uncertain: HOLD

Respond with ONLY a valid JSON object matching this schema exactly:
{{"action": "buy" | "sell" | "hold", "amount_percent": <integer 0-5>, "reasoning": "<one short sentence>"}}"""

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
                    sleep_time = 10 * (2 ** (attempt - 1))  # 10s, 20s, 40s, 80s
                    log.warning(f"Groq rate limited (429). Retrying in {sleep_time}s... (Attempt {attempt}/{max_retries})")
                    time.sleep(sleep_time)
                    continue

            log.error(f"Groq API Error: {e}")
            return {"action": "hold", "amount_percent": 0, "reasoning": "API error fallback"}

    return {"action": "hold", "amount_percent": 0, "reasoning": "Max retries exceeded due to rate limits"}

# ─── ORDER EXECUTION ───────────────────────────────────────────────────────────

def place_order(side: str, size: int, symbol: str) -> dict:
    path      = "/api/v3/sendorder"
    http_path = f"{KRAKEN_DEMO}/api/v3/sendorder"
    nonce     = str(int(time.time() * 1000))

    post_data = f"orderType=mkt&symbol={symbol}&side={side}&size={size}"
    headers   = auth_headers(path, nonce, post_data)
    body      = {"orderType": "mkt", "symbol": symbol, "side": side, "size": str(size)}

    r = requests.post(http_path, headers=headers, data=body, timeout=30)
    r.raise_for_status()
    return r.json()


def get_demo_price(symbol: str) -> float | None:
    try:
        ticker = fetch_ticker("XBTUSD")
        return ticker["price"]
    except Exception:
        return None


def close_position(position: dict, reason: str) -> None:
    log.warning(f"Closing position: {reason}")
    try:
        res = place_order("sell", position["size"], position["symbol"])
        if res.get("result") == "success":
            log.info("Position closed successfully.")
        else:
            log.error(f"Close failed: {res}")
    except Exception as e:
        log.error(f"Close error: {e}")

# ─── MAIN AGENT LOOP ───────────────────────────────────────────────────────────

def monitor_position(position: dict) -> dict | None:
    try:
        curr = with_retry(lambda: get_demo_price(position["symbol"]))
        if curr is None:
            return position

        pnl = ((curr - position["entryPrice"]) / position["entryPrice"]) * 100
        log.info(f"PnL: {pnl:+.2f}%  |  price ${curr:,.2f}")

        if pnl >= TAKE_PROFIT:
            log.info(f"✅ Take profit hit! +{pnl:.2f}%")
            close_position(position, "Take profit hit")
            return None

        if pnl <= STOP_LOSS:
            log.warning(f"🛑 Stop loss hit! {pnl:.2f}%")
            close_position(position, "Stop loss hit")
            return None

    except Exception as e:
        log.error(f"Monitor error: {e}")

    return position


def signal_cycle(position: dict | None) -> dict | None:
    log.info("─── Signal cycle starting ───")
    try:
        log.info("Fetching ticker...")
        ticker = with_retry(lambda: fetch_ticker("XBTUSD"))

        log.info("Fetching OHLC...")
        ohlc   = with_retry(lambda: fetch_ohlc("XBTUSD", interval=60))

        signals = build_signals(ticker, ohlc)
        log.info(f"Signals → price=${signals['price']:,.2f}  momentum={signals['momentum']}  "
                 f"vs_sma_6h={signals['price_vs_sma_6h']}  vs_sma_24h={signals['price_vs_sma_24h']}  "
                 f"spike={signals['volume_spike']}")

        log.info("Asking Groq...")
        decision = ask_groq(signals)
        log.info(f"Groq decision → {decision['action'].upper()} {decision['amount_percent']}% | {decision['reasoning']}")

        action = decision["action"]

        if action == "buy" and position is None:
            log.info("Executing BUY via Kraken demo...")
            res = place_order("buy", TRADE_SIZE, SYMBOL)

            if res.get("result") == "success":
                ev          = res["sendStatus"]["orderEvents"][0]
                entry_price = float(ev["price"])
                filled_size = int(ev["amount"])
                position    = {"entryPrice": entry_price, "size": filled_size, "symbol": SYMBOL}
                log.info(f"✅ Position opened @ ${entry_price:,.2f}  size={filled_size}")
            else:
                log.error(f"Order failed: {res.get('sendStatus')}")

        elif action == "sell" and position is not None:
            log.info("Groq says SELL → closing position...")
            close_position(position, f"AI decision: {decision['reasoning']}")
            position = None

        else:
            log.info("HOLD — no trade executed.")

    except Exception as e:
        log.error(f"Signal cycle error: {e}")

    return position


def run():
    log.info("=" * 50)
    log.info("  AI Trading Agent — Kraken Futures Demo")
    log.info("=" * 50)
    log.info(f"Symbol={SYMBOL}  Size={TRADE_SIZE}  TP={TAKE_PROFIT}%  SL={STOP_LOSS}%")
    log.info("Starting agent... (Ctrl+C to stop)")

    position        = None
    last_cycle_time = 0

    try:
        while True:
            now = time.time()

            if now - last_cycle_time >= CYCLE_SEC:
                position        = signal_cycle(position)
                last_cycle_time = now

            if position:
                position = monitor_position(position)

            time.sleep(MONITOR_SEC)

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt → stopping agent...")
        if position:
            log.warning("Closing open position before exit...")
            close_position(position, "Manual stop")
        log.info("Agent stopped. Goodbye.")


if __name__ == "__main__":
    run()