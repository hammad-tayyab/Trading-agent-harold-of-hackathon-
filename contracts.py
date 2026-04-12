"""
contracts.py
============
This file acts as the "address book" and "translation manual" for the smart contracts.

The hackathon organizers deployed these contracts on the Sepolia test blockchain. 
ALL teams use these exact same addresses so the main leaderboard can track everyone fairly.

Do NOT change these addresses — the hackathon infrastructure relies on them!
"""

# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT ADDRESSES — Sepolia Testnet (Chain ID: 11155111)
# ─────────────────────────────────────────────────────────────────────────────

ADDRESSES = {
    "AgentRegistry":      "0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3",
    "HackathonVault":     "0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90",
    "RiskRouter":         "0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC",
    "ReputationRegistry": "0x423a9904e39537a9997fbaF0f220d79D7d545763",
    "ValidationRegistry": "0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1",
}

CHAIN_ID = 11155111  # Sepolia

# ─────────────────────────────────────────────────────────────────────────────
# ABIs (Application Binary Interfaces)
# 
# Think of an ABI as a "translation manual" for a smart contract. Since the 
# contracts live on the blockchain and speak a different language, the ABI tells 
# our Python code exactly what functions exist and what data they require.
# ─────────────────────────────────────────────────────────────────────────────

AGENT_REGISTRY_ABI = [
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentWallet",   "type": "address"},
            {"name": "name",          "type": "string"},
            {"name": "description",   "type": "string"},
            {"name": "capabilities",  "type": "string[]"},
            {"name": "agentURI",      "type": "string"},
        ],
        "outputs": [{"name": "agentId", "type": "uint256"}],
    },
    {
        "name": "isRegistered",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "",        "type": "bool"}],
    },
    {
        "name": "getAgent",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "operatorWallet", "type": "address"},
                    {"name": "agentWallet",    "type": "address"},
                    {"name": "name",           "type": "string"},
                    {"name": "description",    "type": "string"},
                    {"name": "capabilities",   "type": "string[]"},
                    {"name": "registeredAt",   "type": "uint256"},
                    {"name": "active",         "type": "bool"},
                ],
            }
        ],
    },
    {
        "name": "getSigningNonce",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "",        "type": "uint256"}],
    },
    {
        "name": "AgentRegistered",
        "type": "event",
        "inputs": [
            {"name": "agentId",        "type": "uint256", "indexed": True},
            {"name": "operatorWallet", "type": "address", "indexed": True},
            {"name": "agentWallet",    "type": "address", "indexed": False},
            {"name": "name",           "type": "string",  "indexed": False},
        ],
    },
]

HACKATHON_VAULT_ABI = [
    {
        "name": "claimAllocation",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "getBalance",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "hasClaimed",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "allocationPerTeam",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

RISK_ROUTER_ABI = [
    {
        "name": "submitTradeIntent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "intent",
                "type": "tuple",
                "components": [
                    {"name": "agentId",         "type": "uint256"},
                    {"name": "agentWallet",     "type": "address"},
                    {"name": "pair",            "type": "string"},
                    {"name": "action",          "type": "string"},
                    {"name": "amountUsdScaled", "type": "uint256"},
                    {"name": "maxSlippageBps",  "type": "uint256"},
                    {"name": "nonce",           "type": "uint256"},
                    {"name": "deadline",        "type": "uint256"},
                ],
            },
            {"name": "signature", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "simulateIntent",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "intent",
                "type": "tuple",
                "components": [
                    {"name": "agentId",         "type": "uint256"},
                    {"name": "agentWallet",     "type": "address"},
                    {"name": "pair",            "type": "string"},
                    {"name": "action",          "type": "string"},
                    {"name": "amountUsdScaled", "type": "uint256"},
                    {"name": "maxSlippageBps",  "type": "uint256"},
                    {"name": "nonce",           "type": "uint256"},
                    {"name": "deadline",        "type": "uint256"},
                ],
            },
        ],
        "outputs": [
            {"name": "valid",  "type": "bool"},
            {"name": "reason", "type": "string"},
        ],
    },
    {
        "name": "getIntentNonce",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "",        "type": "uint256"}],
    },
    {
        "name": "TradeApproved",
        "type": "event",
        "inputs": [
            {"name": "agentId",         "type": "uint256", "indexed": True},
            {"name": "intentHash",      "type": "bytes32", "indexed": False},
            {"name": "amountUsdScaled", "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "TradeRejected",
        "type": "event",
        "inputs": [
            {"name": "agentId",    "type": "uint256", "indexed": True},
            {"name": "intentHash", "type": "bytes32", "indexed": False},
            {"name": "reason",     "type": "string",  "indexed": False},
        ],
    },
]

VALIDATION_REGISTRY_ABI = [
    {
        "name": "postEIP712Attestation",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId",        "type": "uint256"},
            {"name": "checkpointHash", "type": "bytes32"},
            {"name": "score",          "type": "uint8"},
            {"name": "notes",          "type": "string"},
        ],
        "outputs": [],
    },
    {
        "name": "getAverageValidationScore",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "",        "type": "uint256"}],
    },
]

REPUTATION_REGISTRY_ABI = [
    {
        "name": "submitFeedback",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId",      "type": "uint256"},
            {"name": "score",        "type": "uint8"},
            {"name": "outcomeRef",   "type": "bytes32"},
            {"name": "comment",      "type": "string"},
            {"name": "feedbackType", "type": "uint8"},
        ],
        "outputs": [],
    },
    {
        "name": "getAverageScore",
        "type": "function",
        "stateMutability": "view",
        "inputs":  [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "",        "type": "uint256"}],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# EIP-712 DOMAINS
# 
# EIP-712 is a standard for signing digital messages. This setup acts like a 
# "wax seal" on an envelope. It proves that a trade request genuinely came from 
# Harold, and ensures hackers can't reuse the signature for a different contract.
# ─────────────────────────────────────────────────────────────────────────────

RISK_ROUTER_DOMAIN = {
    "name":              "RiskRouter",
    "version":           "1",
    "chainId":           CHAIN_ID,
    "verifyingContract": ADDRESSES["RiskRouter"],
}

AGENT_REGISTRY_DOMAIN = {
    "name":              "AITradingAgent",
    "version":           "1",
    "chainId":           CHAIN_ID,
    "verifyingContract": ADDRESSES["AgentRegistry"],
}

TRADE_INTENT_TYPES = {
    "TradeIntent": [
        {"name": "agentId",         "type": "uint256"},
        {"name": "agentWallet",     "type": "address"},
        {"name": "pair",            "type": "string"},
        {"name": "action",          "type": "string"},
        {"name": "amountUsdScaled", "type": "uint256"},
        {"name": "maxSlippageBps",  "type": "uint256"},
        {"name": "nonce",           "type": "uint256"},
        {"name": "deadline",        "type": "uint256"},
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# RISK LIMITS
# 
# Simple guardrails to stop the AI from overtrading or taking bad risks.
# The blockchain contract (RiskRouter) has its own strict limits too.
# ─────────────────────────────────────────────────────────────────────────────

MAX_TRADE_USD          = 999_999   # No local cap; we let the blockchain enforce the max size.
MAX_TRADES_PER_HOUR    = 10        # Prevent the AI from spamming trades (max 10 an hour).
MAX_DRAWDOWN_PCT       = 5         # (Disabled mostly) Stop trading if we lose 5% of peak money.
DEFAULT_SLIPPAGE_BPS   = 100       # Allow a 1% wiggle room on price (100 basis points).
INTENT_DEADLINE_SECS   = 300       # A trade intent expires in 5 minutes (300 seconds).