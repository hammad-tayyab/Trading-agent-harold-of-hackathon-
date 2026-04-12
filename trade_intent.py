"""
trade_intent.py
===============
This file handles sending trade requests to the smart contracts on Sepolia.

Instead of directly swapping tokens, the AI creates an "Intent" (a signed message 
saying "I want to buy $500 of ETH"). The RiskRouter smart contract checks 
if this trade is safe and within hackathon rules before approving it. 
"""

import os, time, json, logging, hashlib
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
from contracts import (
    ADDRESSES, RISK_ROUTER_ABI, RISK_ROUTER_DOMAIN,
    TRADE_INTENT_TYPES, CHAIN_ID, MAX_TRADES_PER_HOUR,
)

log = logging.getLogger("trade_intent")


class TradeIntentClient:
    """
    A helper class that connects to the blockchain, holds our secure wallet keys, 
    and packages our AI's trade ideas into proper blockchain messages.
    """
    def __init__(self):
        rpc = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
        self.w3       = Web3(Web3.HTTPProvider(rpc))
        self.op_key   = os.getenv("OPERATOR_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
        self.ag_key   = os.getenv("AGENT_WALLET_PRIVATE_KEY") or self.op_key
        self.op_acc   = Account.from_key(self.op_key)
        self.ag_acc   = Account.from_key(self.ag_key)
        self.agent_id = int(os.getenv("AGENT_ID"))          # NOTE: ensure no trailing quote in .env
        self.router   = self.w3.eth.contract(
            address=self.w3.to_checksum_address(ADDRESSES["RiskRouter"]),
            abi=RISK_ROUTER_ABI,
        )
        self.history  = []   # timestamps of recent submitted intents

    # ── INTERNAL: package & sign a trade idea ───────────────────────────────
    def _build_intent(self, action: str, pair: str, amount_usd: float) -> tuple[dict, bytes]:
        """
        Takes a simple trade idea (like "BUY ETHUSD for $100") and bundles it 
        into a strict format the smart contract expects. It then "signs" it 
        so the contract knows nobody tampered with the message.
        """
        nonce  = self.router.functions.getIntentNonce(self.agent_id).call()
        intent = {
            "agentId":         self.agent_id,
            "agentWallet":     self.ag_acc.address,
            "pair":            pair,
            "action":          action,
            "amountUsdScaled": int(amount_usd * 100),
            "maxSlippageBps":  100,
            "nonce":           nonce,
            "deadline":        int(time.time()) + 300,
        }
        encoded = encode_typed_data(full_message={
            "types": {
                "EIP712Domain": [
                    {"name": "name",              "type": "string"},
                    {"name": "version",           "type": "string"},
                    {"name": "chainId",           "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **TRADE_INTENT_TYPES,
            },
            "domain":      RISK_ROUTER_DOMAIN,
            "primaryType": "TradeIntent",
            "message":     intent,
        })
        sig = Account.sign_message(encoded, self.ag_key).signature
        return intent, sig

    # ── INTERNAL: convert dictionary to list ─────────────────────────────────
    @staticmethod
    def _intent_tuple(intent: dict) -> tuple:
        """
        Smart contracts prefer simple lists (tuples) rather than Python dictionaries.
        This function simply converts the data into the format the blockchain needs.
        """
        return (
            intent["agentId"],
            intent["agentWallet"],
            intent["pair"],
            intent["action"],
            intent["amountUsdScaled"],
            intent["maxSlippageBps"],
            intent["nonce"],
            intent["deadline"],
        )

    # ── PUBLIC: ask permission to trade ───────────────────────────────────────
    def submit_trade(self, action: str, pair: str, amount_usd: float, retries: int = 3) -> dict:
        """
        Called by Harold when he wants to make a trade. This function packages the 
        request, optionally asks the network "would this succeed?" (simulation), 
        and if it looks good, formally submits it to the blockchain.
        """
        # 1. Normalise inputs
        action = action.upper()
        pair   = "XBTUSD" if "BTC" in pair.upper() else "ETHUSD"

        # 2. Rate-limit check (no USD cap — chain enforces its own)
        recent_count = len([t for t in self.history if t > time.time() - 3600])
        if recent_count >= MAX_TRADES_PER_HOUR:
            log.warning(f"Rate limit: {recent_count} intents submitted in last hour.")
            return {"approved": False, "reason": "Rate Limit"}

        # 3. Build & sign intent
        try:
            intent, sig = self._build_intent(action, pair, amount_usd)
        except Exception as e:
            log.error(f"Failed to build/sign intent: {e}")
            return {"approved": False, "reason": f"Signing error: {e}"}

        itup = self._intent_tuple(intent)

        # 4. FIX 2: Pre-simulate (free view call) — skip gas-burning TX if chain will reject
        try:
            valid, reason = self.router.functions.simulateIntent(itup).call()
            if not valid:
                log.warning(f"simulateIntent rejected before submission: {reason}")
                return {"approved": False, "reason": f"Simulation: {reason}"}
            log.info(f"simulateIntent: ✅ valid — proceeding to submit")
        except Exception as e:
            # simulateIntent failing is non-fatal — proceed anyway
            log.warning(f"simulateIntent call failed (non-fatal, proceeding): {e}")

        # 5. Submit with retry loop
        for attempt in range(retries):
            try:
                tx = self.router.functions.submitTradeIntent(itup, sig).build_transaction({
                    "from":     self.op_acc.address,
                    "nonce":    self.w3.eth.get_transaction_count(self.op_acc.address),
                    "gas":      300_000,
                    "gasPrice": int(self.w3.eth.gas_price * 1.2),
                    "chainId":  CHAIN_ID,
                })
                tx_hash = self.w3.eth.send_raw_transaction(
                    Account.sign_transaction(tx, self.op_key).raw_transaction
                )
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt.status == 1:
                    self.history.append(time.time())
                    log.info(f"Trade Intent Submitted: {tx_hash.hex()}")
                    return {"approved": True, "tx_hash": tx_hash.hex()}
                else:
                    log.warning(f"TX mined but status=0 (reverted). Attempt {attempt + 1}/{retries}")

            except Exception as e:
                log.warning(f"Submit attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)   # backoff: 1s, 2s

        return {"approved": False, "reason": "Chain failure after retries"}


# ── Module-level singleton ────────────────────────────────────────────────────
_client: TradeIntentClient | None = None

def submit_trade(**kwargs) -> dict:
    global _client
    if not _client:
        _client = TradeIntentClient()
    return _client.submit_trade(**kwargs)