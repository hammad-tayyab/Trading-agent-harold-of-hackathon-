"""
Harold — AI Trading Agent v4 (Web3 Sepolia Edition)
=========================================================
Configured for Ethereum (ETH/USD) market analysis, executing
real on-chain transactions via the WETH contract on Sepolia.
Fully ERC-8004 Compliant (Intent + Execution + Validation + Reputation).
"""

import os
import time
import json
import logging
import requests
import csv

from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from web3 import Web3
from web3.exceptions import TimeExhausted

from trade_intent import submit_trade
from validation_client import post_checkpoint

# ─── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()

GROQ_KEY = os.getenv("GROQ_API_KEY")
RPC_URL = os.getenv("SEPOLIA_RPC_URL")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
AGENT_ID = os.getenv("AGENT_ID")

if not all([GROQ_KEY, RPC_URL, WALLET_ADDRESS, PRIVATE_KEY, AGENT_ID]):
    raise ValueError("Missing keys in .env file (GROQ, RPC, WALLET, PRIV_KEY, or AGENT_ID).")

AGENT_ID = int(AGENT_ID)
groq_client = Groq(api_key=GROQ_KEY)

# Web3 Setup
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    raise ConnectionError("Failed to connect to the Sepolia RPC URL.")

# WETH Contract on Sepolia
WETH_ADDRESS = Web3.to_checksum_address("0xfff9976782d46cc05630d1f6ebab18b2324d6b14")
WETH_ABI = [
    {"constant": False, "inputs": [], "name": "deposit", "outputs": [], "payable": True, "stateMutability": "payable", "type": "function"},
    {"constant": False, "inputs": [{"name": "wad", "type": "uint256"}], "name": "withdraw", "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view", "type": "function"}
]
weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=WETH_ABI)

# Reputation Registry Contract (For ERC-8004 Compliance)
REPUTATION_ADDRESS = Web3.to_checksum_address("0x423a9904e39537a9997fbaF0f220d79D7d545763")
REPUTATION_ABI = [
    {"name": "submitFeedback", "type": "function", "inputs": [{"name": "agentId", "type": "uint256"}, {"name": "score", "type": "uint8"}, {"name": "outcomeRef", "type": "bytes32"}, {"name": "comment", "type": "string"}, {"name": "feedbackType", "type": "uint8"}], "outputs": [], "stateMutability": "nonpayable"}
]
reputation_contract = w3.eth.contract(address=REPUTATION_ADDRESS, abi=REPUTATION_ABI)

SYMBOL_API = "ETHUSD"

TAKE_PROFIT = 5.50      # Increased from 3.50 - let winners run
STOP_LOSS   = -2.75     # Increased from -1.5 - reduce whipsaw, eliminate -0.2% exits
MIN_HOLD_TIME = 20     # 20 seconds - don't sell on AI signals too early
AI_CYCLE_SEC     = 180  # Increased from 180 - reduce trade frequency
MONITOR_SEC      = 5 

# Risk Management & Rankings Optimization
# MAX_DRAWDOWN_PCT = 5.0  # 5% drawdown limit (hard constraint)
MIN_CONFIDENCE_NORMAL = 65  # Minimum confidence for trades in normal conditions
# MIN_CONFIDENCE_HIGH_DD = 80  # Higher bar when drawdown > 3%
POSITION_SIZE_BASE = 0.15  # 15% base (will scale down with drawdown)
# POSITION_SIZE_MIN = 0.05   # Minimum 5% position size even at high drawdown

STATE_FILE = "harold_state.json"
CSV_FILE   = "trades_log.csv"
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
                # Initialize entry_time for old positions that don't have it
                if position and "entry_time" not in position:
                    position["entry_time"] = time.time()
                return position
        except Exception as e:
            log.error(f"Failed to load state file: {e}")
    return None

def load_metrics() -> dict:
    """Load or initialize cumulative performance metrics."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "peak_equity": 0.0,
        "total_pnl_usd": 0.0,
        "max_drawdown_pct": 0.0,
        "trades_closed": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "trade_pnls": [],
    }

def save_metrics(metrics: dict):
    """Save cumulative performance metrics."""
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
    wei_bal = w3.eth.get_balance(WALLET_ADDRESS)
    return float(w3.from_wei(wei_bal, 'ether'))

def calculate_current_equity(eth_bal: float, position: dict | None, current_price: float) -> float:
    """Calculate total account equity (ETH + WETH position marked to market)."""
    equity_usd = eth_bal * current_price  # ETH balance in USD
    if position:
        position_value_usd = position["size"] * current_price
        equity_usd += position_value_usd
    return equity_usd

# def calculate_drawdown(current_equity: float, peak_equity: float) -> float:
#     """Calculate current drawdown percentage."""
#     if peak_equity <= 0:
#         return 0.0
#     return ((peak_equity - current_equity) / peak_equity) * 100.0

# def get_dynamic_position_size(drawdown_pct: float, base_size_pct: float = POSITION_SIZE_BASE) -> float:
#     """Scale position size based on current drawdown (risk management)."""
#     if drawdown_pct >= 4.5:  # Near max drawdown
#         return POSITION_SIZE_MIN
#     elif drawdown_pct >= 3.0:  # Elevated risk
#         return base_size_pct * 0.6
#     elif drawdown_pct >= 1.5:  # Moderate risk
#         return base_size_pct * 0.8
#     else:
#         return base_size_pct

def execute_buy(amount_eth: float) -> str | None:
    try:
        log.info(f"Executing Buy (Wrapping {amount_eth:.4f} ETH to WETH)...")
        amount_wei = w3.to_wei(amount_eth, 'ether')
        nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
        
        tx = weth_contract.functions.deposit().build_transaction({
            'from': WALLET_ADDRESS,
            'value': amount_wei,
            'gas': 100000,
            'maxFeePerGas': w3.eth.gas_price * 2,
            'maxPriorityFeePerGas': w3.eth.gas_price,
            'nonce': nonce,
            'chainId': 11155111
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            return w3.to_hex(tx_hash)
        return None
    except Exception as e:
        log.error(f"Failed to execute buy: {e}")
        return None

def execute_sell(amount_eth: float) -> str | None:
    try:
        # Check actual on-chain WETH balance to avoid 'Insufficient Balance' revert
        actual_weth_bal_wei = weth_contract.functions.balanceOf(WALLET_ADDRESS).call()
        amount_wei = w3.to_wei(amount_eth, 'ether')

        if amount_wei > actual_weth_bal_wei:
            log.warning(f"Adjusting sell: State says {amount_eth}, but on-chain balance is {w3.from_wei(actual_weth_bal_wei, 'ether')}")
            amount_wei = actual_weth_bal_wei

        if amount_wei == 0:
            return None

        log.info(f"Executing Sell (Unwrapping {w3.from_wei(amount_wei, 'ether')} WETH)...")
        
        nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
        tx = weth_contract.functions.withdraw(amount_wei).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 120000, # Increased gas limit
            'maxFeePerGas': w3.eth.gas_price * 2,
            'maxPriorityFeePerGas': w3.eth.gas_price,
            'nonce': nonce,
            'chainId': 11155111
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            return w3.to_hex(tx_hash)
        return None
    except Exception as e:
        log.error(f"Failed to execute sell: {e}")
        return None

def record_outcome(pnl_usd: float, amount_usd: float, notes: str):
    """ERC-8004 Reputation Pillar: Posts the PnL of a closed trade."""
    for tries in range(5):
        try:
            log.info(f"Reporting PnL (${pnl_usd:+.2f}) to ReputationRegistry...")
            # feedbackType: 1=positive, 2=negative, 0=neutral
            feedback_type = 1 if pnl_usd > 0 else (2 if pnl_usd < 0 else 0)
            
            # Calculate a 0-100 score based on return percentage
            pnl_pct = (pnl_usd / amount_usd) * 100.0 if amount_usd > 0 else 0
            score = max(0, min(100, int(50.0 + (pnl_pct * 10.0))))

            nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
            tx = reputation_contract.functions.submitFeedback(
                AGENT_ID, score, b"\x00"*32, notes, feedback_type
            ).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": nonce,
                "gas": 200000,
                "maxFeePerGas": w3.eth.gas_price * 2,
                "maxPriorityFeePerGas": w3.eth.gas_price,
                "chainId": 11155111
            })
            signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            log.info("✅ Reputation Outcome Recorded!")
            break
        except Exception as e:
            log.error(f"⚠️ Reputation Tx Failed (Non-fatal): {tries} {e}")
    

# ─── SAFETY WRAPPERS ───────────────────────────────────────────────────────────
def safe_post_checkpoint(action, pair, amount_usd, reasoning, score, trade_approved, tx_hash):
    """Wraps validation to prevent script crashes on RPC timeouts."""
    try:
        # Updated keyword arguments to match the new validation_client.py
        post_checkpoint(
            action=action, 
            pair=pair, 
            amount_usd=amount_usd, 
            reasoning=reasoning, 
            score=score, 
            approved=trade_approved, 
            trade_tx=tx_hash
        )
    except Exception as e:
        log.error(f"⚠️ Failed to post checkpoint (Network congestion): {e}")

# ─── MARKET DATA ───────────────────────────────────────────────────────────────
def fetch_ticker() -> dict:
    try:
        r = requests.get("https://api.kraken.com/0/public/Ticker", params={"pair": SYMBOL_API}, timeout=10)
        r.raise_for_status()
        t = list(r.json()["result"].values())[0]
        return {"price": float(t["c"][0]), "high24": float(t["h"][1]), "low24": float(t["l"][1])}
    except:
        return {"price": 0.0, "high24": 0.0, "low24": 0.0}

def fetch_ohlc_with_retry(interval: int = 1, max_attempts: int = 3) -> list:
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair": SYMBOL_API, "interval": interval}, timeout=15)
            r.raise_for_status()
            candles = r.json()["result"].get("XETHZUSD", [])
            if candles: return candles
        except Exception:
            pass
        time.sleep(2 ** attempt) 
    return []

# ─── SIGNAL ENGINE ─────────────────────────────────────────────────────────────
def build_signals(ticker: dict, ohlc: list) -> dict:
    price = ticker["price"]
    if not ohlc or price == 0.0: return {"price": price, "error": "No data"}
    closes  = [float(c[4]) for c in ohlc]
    sma_10m = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
    sma_30m = sum(closes[-30:]) / 30 if len(closes) >= 30 else None
    recent = closes[-5:]
    ups   = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
    downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
    momentum = "up" if ups >= 3 else ("down" if downs >= 3 else "flat")
    return {
        "price": price,
        "sma_10m": round(sma_10m, 2) if sma_10m else None,
        "sma_30m": round(sma_30m, 2) if sma_30m else None,
        "momentum": momentum,
    }

# ─── GROQ AI ───────────────────────────────────────────────────────────────────
def ask_groq(signals: dict, position: dict | None, available_eth: float, trade_history: list) -> dict:
    price = signals.get("price", 0)
    # return {"action": "sell", "amount_percent": 12, "reasoning": "Holding for too long and can get profit by selling now", "confidence": 85}

    position_ctx = "NO OPEN POSITION. Ready to enter."
    if position:
        pnl = ((price - position["entry"]) / position["entry"]) * 100
        position_ctx = f"OPEN POSITION:\n  Entry Price : ${position['entry']:,.2f}\n  WETH Size: {position['size']}\n  Current PnL : {pnl:+.2f}%"

    prompt = f"""You are Harold, an elite quantitative trading AI executing ON-CHAIN.
Goal: Maximize risk-adjusted returns. Drawdown control = win percentage calculation.

━━━ MARKET DATA ━━━
{json.dumps(signals, indent=2)}
Available Liquid ETH: {available_eth:.4f} ETH
{position_ctx}

━━━ DISCIPLINE RULES ━━━
1. ONLY enter HIGH-CONVICTION setups. Quality >> Quantity.
2. BUY only if: price > SMA10m AND (momentum="up" OR price significantly > SMA30m).
   - If momentum="flat", HOLD and wait for confirmation.
   - Never chase momentum="down" positions.
3. SELL if: confirmed reversal (momentum "down" + price below SMA10m + SMA10m < SMA30m).
   - Do NOT sell on single indicator. Require 2+ confirmations.
4. Amount: Be conservative. Start with 8-12% position sizing.
5. Confidence score reflects your edge certainty:
   - 70-100: High-conviction setup with 2+ technical confirmations
   - 50-69: Reasonable setup but needs monitoring
   - <50: Weak signal, recommend HOLD

━━━ RESPOND ONLY IN EXACT JSON ━━━
{{"action": "buy"|"sell"|"hold", "amount_percent": <8-12>, "reasoning": "<Why this trade (SMA/momentum/price levels)>", "confidence": <50-100>}}"""

    for _ in range(3):
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=100,
            )
            return json.loads(resp.choices[0].message.content)
        except:
            time.sleep(5)
    return {"action": "hold", "amount_percent": 0, "reasoning": "Retries failed"}

def log_status(ticker_price: float, position: dict | None, current_equity: float):
    eth_bal = get_eth_balance()
    # dd_status = f"DD: {drawdown_pct:.2f}% / {MAX_DRAWDOWN_PCT}%"
    # if drawdown_pct > MAX_DRAWDOWN_PCT:
    #     dd_status = f"⚠️ {dd_status} [TRADING SUSPENDED]"
    # elif drawdown_pct > 3.0:
    #     dd_status = f"⚡ {dd_status} [CONSERVATIVE MODE]"
    dd_status = ""  # Drawdown checking disabled for testing
    
    if position:
        trade_pnl_pct = ((ticker_price - position["entry"]) / position["entry"]) * 100
        trade_pnl_usd = trade_pnl_pct / 100 * (position["size"] * position["entry"])
        if "entry_time" in position:
            time_held = int(time.time() - position["entry_time"])
        else:
            # Old position without entry_time tracking
            time_held = 0
            position["entry_time"] = time.time()
        position_str  = f"| POSITION: {position['size']:.4f} WETH [PnL: {trade_pnl_pct:+.2f}%] [Held: {time_held}s]"
    else:
        position_str = "| NO OPEN POSITION"
    log.info(f"📡 ETH: ${ticker_price:,.2f} | Equity: ${current_equity:,.0f} {position_str}")

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────
def run():
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("   HAROLD V5 — RISK-ADJUSTED OPTIMIZER  ")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    eth_balance = get_eth_balance()
    if eth_balance < 0.01:
        log.warning("⚠️ Low Sepolia ETH balance. You need ETH for gas!")

    position = load_state()
    metrics = load_metrics()
    last_ai_time = 0
    
    # Initialize peak equity from first price check
    ticker = fetch_ticker()
    initial_equity = calculate_current_equity(eth_balance, position, ticker["price"])
    if metrics["peak_equity"] == 0.0:
        metrics["peak_equity"] = initial_equity
    trade_history = []

    try:
        while True:
            now = time.time()
            ticker = fetch_ticker()
            if ticker["price"] == 0.0:
                time.sleep(MONITOR_SEC)
                continue

            price = ticker["price"]
            
            # ─ EQUITY & DRAWDOWN TRACKING ─
            eth_bal = get_eth_balance()
            current_equity = calculate_current_equity(eth_bal, position, price)
            
            # Update peak equity if current is higher
            if current_equity > metrics["peak_equity"]:
                metrics["peak_equity"] = current_equity
                save_metrics(metrics)
            
            # drawdown_pct = calculate_drawdown(current_equity, metrics["peak_equity"])  # DISABLED FOR TESTING
            log_status(price, position, current_equity)
            
            # ─ EMERGENCY HALT: Drawdown exceeds 5% limit ─
            # if drawdown_pct > MAX_DRAWDOWN_PCT:  # DISABLED FOR TESTING
            #     log.critical(f"🛑 DRAWDOWN LIMIT BREACHED ({drawdown_pct:.2f}%). Trading suspended!")
            #     if position:
            #         log.warning("Force-closing open position due to max drawdown...")
            #         tx_hash = execute_sell(position["size"])
            #         if tx_hash:
            #             pnl_usd = (position["size"] * price) - (position["size"] * position["entry"])
            #             log_trade_to_csv("SELL(DD_HALT)", price, position["size"], tx_hash, "Max drawdown halt")
            #             position = None
            #             save_state(None)
            #     time.sleep(MONITOR_SEC * 2)
            #     continue

            # ── SAFETY TRIGGERS (TP/SL) ──
            sl_tp_fired = False
            if position:
                pnl = ((price - position["entry"]) / position["entry"]) * 100
                if pnl >= TAKE_PROFIT or pnl <= STOP_LOSS:
                    act = "SELL(TP)" if pnl >= TAKE_PROFIT else "SELL(SL)"
                    trade_value_usd = position["size"] * price
                    pnl_usd = trade_value_usd - (position["size"] * position["entry"])
                    
                    log.info(f"⚠️ SAFETY TRIGGER: {act} detected at {pnl:+.2f}%. Requesting Intent...")
                    
                    try:
                        intent_result = submit_trade(action="SELL", pair="ETH/USD", amount_usd=trade_value_usd)
                    except Exception as e:
                        log.error(f"RiskRouter RPC failed: {e}")
                        continue
                    
                    if intent_result.get("approved"): # Updated dictionary access
                        log.info(f"✅ Safety Intent Approved. Selling now...")
                        tx_hash = execute_sell(position["size"])
                        if tx_hash:
                            log_trade_to_csv(act, price, position["size"], tx_hash, f"Trigger {pnl:.2f}%")
                            
                            # Track in metrics for risk-adjusted scoring
                            metrics["trades_closed"] += 1
                            if pnl_usd > 0:
                                metrics["winning_trades"] += 1
                            else:
                                metrics["losing_trades"] += 1
                            metrics["trade_pnls"].append(pnl_usd)
                            metrics["total_pnl_usd"] += pnl_usd
                            save_metrics(metrics)
                            
                            # Calculate validation score: higher for winners, defensive for losses
                            if pnl >= TAKE_PROFIT:
                                val_score = 95
                            elif pnl <= STOP_LOSS:
                                val_score = 60  # Lower for stopped trades
                            else:
                                val_score = 75
                            
                            # Validation
                            safe_post_checkpoint(
                                action="SELL", pair="ETH/USD", amount_usd=trade_value_usd,
                                reasoning=f"Automated safety exit: {act} at {pnl:.2f}%",
                                score=val_score, trade_approved=True, tx_hash=tx_hash
                            )
                            # Reputation
                            record_outcome(pnl_usd, trade_value_usd, f"Safety {act} Exit")
                            
                            position = None
                            save_state(None)
                            sl_tp_fired = True
                    else:
                        log.error(f"❌ Safety Intent REJECTED by RiskRouter: {intent_result.get('reason')}") # Updated dict access
            
            # ── AI CYCLE ──
            if not sl_tp_fired and (now - last_ai_time >= AI_CYCLE_SEC):
                ohlc = fetch_ohlc_with_retry()
                signals = build_signals(ticker, ohlc)
                eth_bal = get_eth_balance()
                
                decision = ask_groq(signals, position, eth_bal, trade_history)
                log.info(f"🧠 [HAROLD DECISION] --> {decision['action']} | CONFIDENCE: {decision.get('confidence', 50)} | 📝 {decision['reasoning']}")
                
                # ─ CONFIDENCE-BASED RISK FILTER ─
                confidence = float(decision.get("confidence", 50))
                # min_confidence = MIN_CONFIDENCE_HIGH_DD if drawdown_pct > 3.0 else MIN_CONFIDENCE_NORMAL  # DISABLED FOR TESTING
                min_confidence = MIN_CONFIDENCE_NORMAL  # Use normal threshold only
                
                if decision["action"] in ["buy", "sell"] and confidence < min_confidence:
                    log.info(f"🚫 Confidence {confidence:.0f} below threshold {min_confidence}. HOLD.")
                    decision["action"] = "hold"

                # ── BUY LOGIC ──
                if decision["action"] == "buy" and position is None:
                    percent = max(8.0, min(12.0, float(decision.get("amount_percent", 10))))
                    
                    # Dynamic position sizing based on drawdown
                    # dynamic_percent = get_dynamic_position_size(drawdown_pct, percent)  # DISABLED FOR TESTING
                    dynamic_percent = percent  # Use fixed percentage
                    trade_size = round(eth_bal * (dynamic_percent / 100), 5)
                    trade_value_usd = trade_size * price
                    
                    if trade_size > 0.005: 
                        log.info(f"Submitting BUY intent (Conf: {confidence:.0f}, DD: {drawdown_pct:.2f}%) for ${trade_value_usd:.2f}...")
                        try:
                            intent_result = submit_trade(action="BUY", pair="ETH/USD", amount_usd=trade_value_usd)
                        except Exception as e:
                            log.error(f"RiskRouter RPC failed: {e}")
                            continue
                        
                        if intent_result.get("approved"): # Updated dictionary access
                            tx_hash = execute_buy(trade_size)
                            if tx_hash:
                                position = {"entry": price, "size": trade_size, "entry_time": time.time()}
                                save_state(position)
                                log_trade_to_csv("BUY", price, trade_size, tx_hash, decision["reasoning"])

                                # Validation score reflects confidence
                                val_score = min(100, int(50 + (confidence * 0.5)))  # 50-100 range (drawdown checks disabled)
                                
                                safe_post_checkpoint(
                                    action="BUY", pair="ETH/USD", amount_usd=trade_value_usd,
                                    reasoning=decision["reasoning"], score=val_score,
                                    trade_approved=True, tx_hash=tx_hash
                                )
                        else:   
                            log.warning(f"🚫 Intent Rejected: {intent_result.get('reason')}") # Updated dict access

                # ── STRATEGIC SELL LOGIC ──
                elif decision["action"] == "sell" and position is not None:
                    # Check if minimum hold time has passed
                    time_held = time.time() - position.get("entry_time", time.time())
                    # if time_held < MIN_HOLD_TIME:
                    #     log.info(f"⏱️  Hold time only {time_held:.0f}s, need {MIN_HOLD_TIME}s. Ignoring AI sell signal.")
                    # else:
                    trade_value_usd = position["size"] * price
                    pnl_usd = trade_value_usd - (position["size"] * position["entry"])

                    log.info(f"Submitting SELL intent (Conf: {confidence:.0f}, DD: {drawdown_pct:.2f}%) for ${trade_value_usd:.2f}...")
                    try:
                        intent_result = submit_trade(action="SELL", pair="ETH/USD", amount_usd=trade_value_usd)
                    except Exception as e:
                        log.error(f"RiskRouter RPC failed: {e}")
                        continue
                    
                    if intent_result.get("approved"): # Updated dictionary access
                        try:
                            tx_hash = execute_sell(position["size"])
                            if tx_hash:
                                log_trade_to_csv("SELL(AI)", price, position["size"], tx_hash, decision["reasoning"])
                                log.info(f"💰 Sell Executed! TX: {tx_hash}")

                                # Track in metrics for risk-adjusted scoring
                                metrics["trades_closed"] += 1
                                if pnl_usd > 0:
                                    metrics["winning_trades"] += 1
                                else:
                                    metrics["losing_trades"] += 1
                                metrics["trade_pnls"].append(pnl_usd)
                                metrics["total_pnl_usd"] += pnl_usd
                                save_metrics(metrics)
                                
                                # Validation score reflects confidence + profitability
                                pnl_pct = (pnl_usd / trade_value_usd) * 100 if trade_value_usd > 0 else 0
                                val_score = min(100, int(50 + (confidence * 0.3) + (pnl_pct * 2)))
                                
                                # Validation
                                safe_post_checkpoint(
                                    action="SELL", pair="ETH/USD", amount_usd=trade_value_usd,
                                    reasoning=decision["reasoning"], score=val_score,
                                    trade_approved=True, tx_hash=tx_hash
                                )
                                # Reputation
                                record_outcome(pnl_usd, trade_value_usd, "Strategic AI Exit")

                                position = None
                                save_state(None)
                            else:
                                log.error("❌ Intent was approved, but execution failed!")
                        except Exception as e:
                            log.error(f"Failed to execute sell after intent approval: {e}")
                    else:
                        log.warning(f"🚫 Intent Rejected by RiskRouter: {intent_result.get('reason')}") # Updated dict access
            
                last_ai_time = now

            time.sleep(MONITOR_SEC)

    except KeyboardInterrupt:
        log.info("Shutdown. Good luck on chain!")

if __name__ == "__main__":
    run()