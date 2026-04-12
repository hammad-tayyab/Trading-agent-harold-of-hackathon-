import os, time, json, logging, hashlib
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
from contracts import ADDRESSES, RISK_ROUTER_ABI, RISK_ROUTER_DOMAIN, TRADE_INTENT_TYPES, CHAIN_ID, MAX_TRADE_USD, MAX_TRADES_PER_HOUR

log = logging.getLogger("trade_intent")

class TradeIntentClient:
    def __init__(self):
        rpc = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
        self.w3 = Web3(Web3.HTTPProvider(rpc))
        self.op_key = os.getenv("OPERATOR_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
        self.ag_key = os.getenv("AGENT_WALLET_PRIVATE_KEY") or self.op_key
        self.op_acc = Account.from_key(self.op_key)
        self.ag_acc = Account.from_key(self.ag_key)
        self.agent_id = int(os.getenv("AGENT_ID"))
        self.router = self.w3.eth.contract(address=ADDRESSES["RiskRouter"], abi=RISK_ROUTER_ABI)
        self.history = []

    def submit_trade(self, action, pair, amount_usd, retries=3):
        # 1. Safety & Normalization
        action = action.upper()
        pair = "XBTUSD" if "BTC" in pair.upper() else "ETHUSD"
        
        if amount_usd > MAX_TRADE_USD or len([t for t in self.history if t > time.time()-3600]) >= MAX_TRADES_PER_HOUR:
            return {"approved": False, "reason": "Safety/Rate Limit"}

        # 2. Build Intent
        nonce = self.router.functions.getIntentNonce(self.agent_id).call()
        intent = {
            "agentId": self.agent_id, "agentWallet": self.ag_acc.address,
            "pair": pair, "action": action, "amountUsdScaled": int(amount_usd * 100),
            "maxSlippageBps": 100, "nonce": nonce, "deadline": int(time.time()) + 300
        }
        
        # 3. Sign (EIP-712)
        encoded = encode_typed_data(full_message={"types": {"EIP712Domain": [{"name": "name", "type": "string"},{"name": "version", "type": "string"},{"name": "chainId", "type": "uint256"},{"name": "verifyingContract", "type": "address"}], **TRADE_INTENT_TYPES}, "domain": RISK_ROUTER_DOMAIN, "primaryType": "TradeIntent", "message": intent})
        sig = Account.sign_message(encoded, self.ag_key).signature

        # 4. Submit with Retry Loop
        itup = (intent["agentId"], intent["agentWallet"], intent["pair"], intent["action"], intent["amountUsdScaled"], intent["maxSlippageBps"], intent["nonce"], intent["deadline"])
        
        for attempt in range(retries):
            try:
                tx = self.router.functions.submitTradeIntent(itup, sig).build_transaction({
                    "from": self.op_acc.address,
                    "nonce": self.w3.eth.get_transaction_count(self.op_acc.address),
                    "gas": 300_000,
                    "gasPrice": int(self.w3.eth.gas_price * 1.2), # 20% bump
                    "chainId": CHAIN_ID
                })
                tx_hash = self.w3.eth.send_raw_transaction(Account.sign_transaction(tx, self.op_key).raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt.status == 1:
                    self.history.append(time.time())
                    log.info(f"Trade Intent Submitted: {tx_hash.hex()}")
                    return {"approved": True, "tx_hash": tx_hash.hex()}
            except Exception as e:
                log.warning(f"Retry {attempt+1} failed: {e}")
                if attempt < retries - 1: time.sleep(2 ** attempt)
        
        return {"approved": False, "reason": "Chain failure after retries"}

_c = None
def submit_trade(**kwargs):
    global _c
    if not _c: _c = TradeIntentClient()
    return _c.submit_trade(**kwargs)