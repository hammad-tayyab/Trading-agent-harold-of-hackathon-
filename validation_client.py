import hashlib, json, os, time, logging
from pathlib import Path
from eth_account import Account
from web3 import Web3
from contracts import ADDRESSES, VALIDATION_REGISTRY_ABI, CHAIN_ID

log = logging.getLogger("validation")

class ValidationClient:
    def __init__(self):
        rpc = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
        self.w3 = Web3(Web3.HTTPProvider(rpc))
        self.op_key = os.getenv("OPERATOR_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
        self.op_acc = Account.from_key(self.op_key)
        self.agent_id = int(os.getenv("AGENT_ID"))
        self.registry = self.w3.eth.contract(
            address=self.w3.to_checksum_address(ADDRESSES["ValidationRegistry"]),
            abi=VALIDATION_REGISTRY_ABI
        )

    def post_checkpoint(self, action, pair, amount_usd, reasoning, score=75, approved=False, trade_tx="", retries=3):
        ts = int(time.time())
        amount_scaled = int(amount_usd * 100)
        r_hash = hashlib.sha3_256(reasoning.encode()).hexdigest()
        
        raw = f"{self.agent_id}|{ts}|{action}|{pair}|{amount_scaled}|{r_hash}".encode()
        c_hash = self.w3.keccak(raw)
        notes = f"{action} {pair} ${amount_usd:.2f} | {'OK' if approved else 'REJ'} | {reasoning[:50]}"

        tx_out = ""
        for attempt in range(retries):
            try:
                tx = self.registry.functions.postEIP712Attestation(
                    self.agent_id, c_hash, min(max(int(score), 0), 100), notes
                ).build_transaction({
                    "from": self.op_acc.address,
                    "nonce": self.w3.eth.get_transaction_count(self.op_acc.address),
                    "gas": 200_000,
                    "gasPrice": int(self.w3.eth.gas_price * 1.2), # 20% bump to clear faster
                    "chainId": CHAIN_ID,
                })
                signed = Account.sign_transaction(tx, self.op_key)
                tx_out = self.w3.eth.send_raw_transaction(signed.raw_transaction).hex()
                log.info(f"Checkpoint Success: {tx_out}")
                break 
            except Exception as e:
                log.warning(f"Attempt {attempt+1} failed: {e}")
                if attempt < retries - 1: time.sleep(2 ** attempt) # Backoff: 1s, 2s...
                else: log.error("All retries exhausted.")

        with open("checkpoints.jsonl", "a") as f:
            f.write(json.dumps({
                "agentId": self.agent_id, "hash": c_hash.hex(), "score": score,
                "tx": tx_out, "trade_tx": trade_tx, "reason": reasoning
            }) + "\n")
        return tx_out

_c = None
def post_checkpoint(**kwargs):
    global _c
    if not _c: _c = ValidationClient()
    return _c.post_checkpoint(**kwargs)