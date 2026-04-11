# ⚡ HAROLD
### *The Trustless Autonomous Trading Agent*

```
██╗  ██╗ █████╗ ██████╗  ██████╗ ██╗     ██████╗
██║  ██║██╔══██╗██╔══██╗██╔═══██╗██║     ██╔══██╗
███████║███████║██████╔╝██║   ██║██║     ██║  ██║
██╔══██║██╔══██║██╔══██╗██║   ██║██║     ██║  ██║
██║  ██║██║  ██║██║  ██║╚██████╔╝███████╗██████╔╝
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═════╝
```

> *"Every trade Harold makes is signed, verified, and permanently etched on-chain.*
> *Not because he has to. Because he has nothing to hide."*

---

![Build](https://img.shields.io/badge/Build-Passing-brightgreen?style=for-the-badge&logo=github)
![Network](https://img.shields.io/badge/Network-Sepolia-blue?style=for-the-badge&logo=ethereum)
![Standard](https://img.shields.io/badge/Standard-ERC--8004-orange?style=for-the-badge)
![LLM](https://img.shields.io/badge/LLM-LLaMA%203.3%2070B-purple?style=for-the-badge&logo=meta)
![Mode](https://img.shields.io/badge/Mode-Paper%20Trading-yellow?style=for-the-badge)
![Hackathon](https://img.shields.io/badge/lablab.ai-Hackathon-red?style=for-the-badge)

---

## 🧠 What Is Harold?

Harold is a **fully autonomous, cryptographically verifiable AI trading agent**. He wakes up every 5 minutes, ingests live market data from Kraken and macro news from the Prism API, runs it through a Groq-powered LLaMA 3.3 70B brain, and fires a signed trade intent — all without a single human touching the keyboard.

But Harold isn't just another black-box bot. Every decision he makes is:
- **Structured** via EIP-712 typed signatures before execution
- **Validated** against his own on-chain reputation (ERC-8004)
- **Settled** transparently on the Sepolia testnet

Harold isn't just a bot. Harold is a **verifiable agent**.

---

## 🚨 The Problem: The Black Box of AI Trading

AI trading agents are everywhere. But ask one a simple question — *"Why did you make that trade?"* — and you'll get silence.

Most agents operate as opaque pipelines:

```
Market Data → Black Box AI → Trade Executed → ???
```

There's no audit trail. No accountability. No way to know if the agent followed its own rules, got manipulated by bad data, or simply hallucinated a moon call.

**This is the black box problem.** And it's why institutional adoption of AI trading agents stalls at the trust layer.

### Harold's Solution: Reputation On-Chain

Harold solves this by implementing **ERC-8004** — the Trustless Agents standard — to anchor his identity and trade history directly on-chain.

| The Old Way | Harold's Way |
|---|---|
| Decisions logged in a private DB | Trade intents signed with EIP-712 |
| No accountability after the fact | Reputation registry on Sepolia |
| Trust the dev team's word | Verify the contract yourself |
| Black box reasoning | Structured JSON intent + on-chain attestation |

Every trade Harold executes passes through a **whitelisted Risk Router contract**. He cannot go rogue. He cannot exceed his own parameters. The chain enforces it.

> *Harold doesn't ask you to trust him. He asks you to verify him.*

---

## 🏗️ Architecture

```
╔═══════════════════════════════════════════════════════════════╗
║                        HAROLD CORE                            ║
║                                                               ║
║  ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐  ║
║  │  Kraken CLI │──▶│ Signal Engine│──▶│   Groq LLM Brain   │  ║
║  │  OHLC Data  │   │ SMA + Range  │   │   LLaMA 3.3 70B    │  ║
║  └─────────────┘   └──────────────┘   └────────┬───────────┘  ║
║                                                │               ║
║  ┌─────────────┐                               │               ║
║  │  Prism API  │──────── News Sentiment ───────┘               ║
║  │  Macro Data │                               │               ║
║  └─────────────┘                               ▼               ║
║                                  ┌─────────────────────────┐   ║
║                                  │    Trade Intent (JSON)  │   ║
║                                  │    EIP-712 Signed       │   ║
║                                  └────────────┬────────────┘   ║
║                                               │                ║
║  ┌────────────────────────────────────────────▼────────────┐   ║
║  │                   ERC-8004 Reputation Check             │   ║
║  │   Does this trade violate Harold's on-chain rep rules?  │   ║
║  │          PASS ──▶ Risk Router ──▶ Sepolia Exec          │   ║
║  │          FAIL ──▶ Blocked. Intent logged. Harold waits. │   ║
║  └─────────────────────────────────────────────────────────┘   ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## ⚙️ Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Data** | Kraken CLI | Real-time price, OHLC, volume feeds |
| **Data** | Prism API | News sentiment + macro signal analysis |
| **Intelligence** | Groq + LLaMA 3.3 70B | Sub-second trade decision inference |
| **Trust** | ERC-8004 | On-chain agent identity & reputation registry |
| **Trust** | EIP-712 | Typed structured signing of trade intents |
| **Trust** | EIP-1271 | Smart contract wallet authentication |
| **Trust** | EIP-155 | Chain-ID binding, replay attack prevention |
| **Execution** | Sepolia Testnet | Transparent, auditable trade settlement |
| **Execution** | Risk Router Contract | Whitelisted DEX execution gateway |

---

## 🔥 Features

### 🤖 Intelligence — Groq + LLaMA 3.3 70B + Prism
- Sub-second inference via Groq's ultra-fast API
- JSON-mode output for deterministic, parseable decisions
- **Prism API integration** for live news sentiment and macro signals — Harold reads the news *before* reading the chart
- Position-aware prompting — Harold knows his own PnL before deciding to hold or cut
- Temperature `0.1` — consistent, logical, not hallucinating moon calls

### 📊 Signal Pipeline

| Signal | Source | What It Tells Harold |
|---|---|---|
| `price` | Kraken CLI | Current BTC spot price |
| `sma_6h` | OHLC (6 × 60min) | Short-term trend direction |
| `sma_24h` | OHLC (24 × 60min) | Medium-term baseline |
| `momentum` | Last 5 candles | Recent price direction |
| `range_position` | (price − low24) / (high24 − low24) | Where BTC sits in today's range |
| `volume_spike` | Last vol vs 20-candle avg | Unusual buying/selling pressure |
| `news_sentiment` | Prism API | Macro and crypto news tone score |

### 🛡️ Risk Management
- **Take Profit**: `+1.0%` — lock gains fast, no greed
- **Stop Loss**: `-1.0%` — cut losses, no ego
- **Position monitor**: checks every 15 seconds
- **Entry gate**: requires SMA alignment + momentum before buying
- **Overbought guard**: won't buy if `range_position > 85%`
- **On-chain enforcement**: Risk Router contract blocks any out-of-policy execution
- **CSV trade log**: every action timestamped and auditable

### 🔗 On-Chain Identity (ERC-8004)

| Component | Description |
|---|---|
| **Agent Identity Registry** | Harold's verifiable on-chain identity on Sepolia |
| **Reputation Registry** | Cumulative trade history and performance attestations |
| **EIP-712 Trade Intents** | Every trade cryptographically structured and signed off-chain |
| **EIP-1271 Wallet** | Smart contract wallet support for agent authentication |
| **EIP-155 Binding** | Chain-ID prevents cross-network replay attacks |
| **Risk Router** | All DEX executions gated through a whitelisted contract |

---

## 🚀 Quick Start

### 1. Clone
```bash
git clone https://github.com/hammad-tayyab/Trading-agent-harold-of-hackathon
cd Trading-agent-harold-of-hackathon
```

### 2. Set up environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`
```env
# LLM
GROQ_API_KEY=your_groq_key_here

# Market Data
KRAKEN_API_KEY=your_kraken_key_here
KRAKEN_API_SECRET=your_kraken_secret_here

# News & Macro
PRISM_API_KEY=your_prism_key_here

# On-Chain
WEB3_PROVIDER_URL=https://sepolia.infura.io/v3/your_project_id
AGENT_PRIVATE_KEY=your_wallet_private_key_here
RISK_ROUTER_ADDRESS=0xYourDeployedContractAddress
```

> ⚠️ Never commit your `.env` file. It is in `.gitignore` by default.

### 4. Install Kraken CLI
```bash
# Follow official Kraken CLI setup
# Ensure `kraken` is in PATH and paper trading mode is enabled
```

### 5. Launch Harold
```bash
python3 main/MainStuff.py
```

Harold will log every decision, every signal, every signed intent, and every trade. Watch him work.

---

## 📁 Repo Structure

```
├── main/
│   ├── MainStuff.py          # 🧠 Entry point — Harold's full pipeline
│   ├── trade_intent.py       # EIP-712 intent construction & signing
│   ├── validation_client.py  # ERC-8004 reputation validation
│   ├── contracts.py          # Web3 + Risk Router interaction
│   ├── agent_metrics.json    # Live performance metrics
│   └── checkpoints.jsonl     # Decision audit trail (JSONL)
├── trades_log.csv            # Full signed trade audit log
├── trading_agent.py          # Legacy standalone agent
├── .env                      # 🔒 Secret keys (never commit)
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔍 How to Audit Harold

Harold is designed to be verified, not trusted blindly. Here's how to audit any trade he makes:

### Step 1 — Pull a trade intent from `trades_log.csv`

Each row contains:
```
timestamp, action, price, pnl, intent_hash, eip712_signature, sepolia_tx_hash
```

### Step 2 — Reconstruct the EIP-712 typed data

The intent schema Harold signs:
```json
{
  "types": {
    "TradeIntent": [
      { "name": "agentId",   "type": "address" },
      { "name": "action",    "type": "string"  },
      { "name": "symbol",    "type": "string"  },
      { "name": "price",     "type": "uint256" },
      { "name": "timestamp", "type": "uint256" }
    ]
  },
  "domain": {
    "name": "Harold",
    "version": "1",
    "chainId": 11155111
  }
}
```

### Step 3 — Verify the signature

```python
from eth_account import Account
from eth_account.messages import encode_typed_data

# Reconstruct and verify
recovered = Account.recover_message(encoded_intent, signature=eip712_signature)
assert recovered == HAROLD_AGENT_ADDRESS
```

### Step 4 — Cross-reference on Sepolia

Paste the `sepolia_tx_hash` into [sepolia.etherscan.io](https://sepolia.etherscan.io) and verify:
- Tx originated from Harold's Risk Router contract
- Input data matches the signed intent
- On-chain reputation registry was updated post-execution

> Every trade, end-to-end. No black box. No trust required.

---

## 📈 Sample Output

```
00:50:09  INFO  ━━━ HAROLD AI STARTING (COMPETITION MODE) ━━━
00:50:11  INFO  Prism → News Sentiment: +0.62 (Bullish macro)
00:50:17  INFO  Groq  → BUY 4% | SMA crossover + bullish sentiment alignment
00:50:17  INFO  EIP-712 intent signed: 0xabcd...ef01
00:50:18  INFO  ERC-8004 check: PASS (rep score 94/100)
00:50:18  INFO  🚀 Bought @ $83,241.00 | Tx: 0x1234...5678
00:55:22  INFO  Monitor: PnL +0.73% | BTC $83,849.00
01:00:31  INFO  Monitor: PnL +1.02% | BTC $84,091.00
01:00:31  INFO  ✅ Take profit hit. Profit locked. Reputation updated.
```

---

## 👥 Team

Built at **lablab.ai Hackathon** by a team of 8.

| Role | Owner |
|---|---|
| Agent Architecture & AI Pipeline | [@hammad-tayyab](https://github.com/hammad-tayyab) |
| On-Chain Identity (ERC-8004) | Team |
| EIP-712 / Risk Router Integration | Team |
| Smart Contract Deployment (Sepolia) | Team |

---

## 🏆 Tracks Entered

- ✅ **Kraken Track** — Paper trading agent with live market data, news sentiment, and AI decisions
- ✅ **ERC-8004 Track** — On-chain agent identity, reputation, and verified trade execution

---

## ⚠️ Disclaimer

Harold trades with **paper money only** (Kraken demo / paper mode). This is a hackathon project — not financial advice. Do not give Harold your real money. Harold is confident, not infallible.

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

**Built in sleepless nights. Signed by EIP-712. Verified by no one's trust.**

*Harold is always watching the charts. The chain is always watching Harold.*

</div>
