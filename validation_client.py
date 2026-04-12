"""
validation_client.py
====================
Posts EIP-712 attestations to the ValidationRegistry on Sepolia.

FIXES vs original:
  - FIX 1: retries reduced from 3 → 2 (max block time: 2 × 120s = 240s vs 600s)
  - FIX 2: module-level post_checkpoint() now also callable for REJECTED intents
            so the ValidationRegistry score doesn't go dark between real trades
"""

import hashlib, json, os, time, logging
from eth_account import Account
from web3 import Web3
from contracts import ADDRESSES, VALIDATION_REGISTRY_ABI, CHAIN_ID

log = logging.getLogger("validation")


class ValidationClient:
    def __init__(self):
        rpc           = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
        self.w3       = Web3(Web3.HTTPProvider(rpc))
        self.op_key   = os.getenv("OPERATOR_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
        self.op_acc   = Account.from_key(self.op_key)
        self.agent_id = int(os.getenv("AGENT_ID"))          # NOTE: ensure no trailing quote in .env
        self.registry = self.w3.eth.contract(
            address=self.w3.to_checksum_address(ADDRESSES["ValidationRegistry"]),
            abi=VALIDATION_REGISTRY_ABI,
        )

    def post_checkpoint(
        self,
        action: str,
        pair: str,
        amount_usd: float,
        reasoning: str,
        score: int = 75,
        approved: bool = False,
        trade_tx: str = "",
        retries: int = 2,          # FIX 1: was 3 (up to 600s block); now 2 (max 240s)
    ) -> str:
        ts             = int(time.time())
        amount_scaled  = int(amount_usd * 100)
        r_hash         = hashlib.sha3_256(reasoning.encode()).hexdigest()

        raw    = f"{self.agent_id}|{ts}|{action}|{pair}|{amount_scaled}|{r_hash}".encode()
        c_hash = self.w3.keccak(raw)

        status_tag = "OK" if approved else "REJ"
        notes      = f"{action} {pair} ${amount_usd:.2f} | {status_tag} | {reasoning[:50]}"

        # FIX 2: post even on rejections — lower score keeps registry active
        # Caller should pass score=30-40 for rejected intents rather than skipping entirely
        clamped_score = min(max(int(score), 0), 100)

        tx_out = ""
        for attempt in range(retries):
            try:
                tx = self.registry.functions.postEIP712Attestation(
                    self.agent_id, c_hash, clamped_score, notes
                ).build_transaction({
                    "from":     self.op_acc.address,
                    "nonce":    self.w3.eth.get_transaction_count(self.op_acc.address),
                    "gas":      200_000,
                    "gasPrice": int(self.w3.eth.gas_price * 1.2),
                    "chainId":  CHAIN_ID,
                })
                signed = Account.sign_transaction(tx, self.op_key)
                tx_out = self.w3.eth.send_raw_transaction(signed.raw_transaction).hex()
                log.info(f"Checkpoint posted ({'approved' if approved else 'rejected'} | score={clamped_score}): {tx_out}")
                break
            except Exception as e:
                log.warning(f"Checkpoint attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)   # backoff: 1s
                else:
                    log.error("All checkpoint retries exhausted.")

        # Always write to local log regardless of chain success
        with open("checkpoints.jsonl", "a") as f:
            f.write(json.dumps({
                "agentId":  self.agent_id,
                "hash":     c_hash.hex(),
                "score":    clamped_score,
                "approved": approved,
                "tx":       tx_out,
                "trade_tx": trade_tx,
                "reason":   reasoning,
            }) + "\n")

        return tx_out


# ── Module-level singleton ────────────────────────────────────────────────────
_client: ValidationClient | None = None

def post_checkpoint(**kwargs) -> str:
    global _client
    if not _client:
        _client = ValidationClient()
    return _client.post_checkpoint(**kwargs)