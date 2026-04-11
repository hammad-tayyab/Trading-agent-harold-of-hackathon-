# ⚡ HAROLD
### *The AI Trading Agent That Never Sleeps*

```
██╗  ██╗ █████╗ ██████╗  ██████╗ ██╗     ██████╗
██║  ██║██╔══██╗██╔══██╗██╔═══██╗██║     ██╔══██╗
███████║███████║██████╔╝██║   ██║██║     ██║  ██║
██╔══██║██╔══██║██╔══██╗██║   ██║██║     ██║  ██║
██║  ██║██║  ██║██║  ██║╚██████╔╝███████╗██████╔╝
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═════╝
```

> *"Markets are a device for transferring money from the impatient to the patient."*
> Harold doesn't have patience. Harold has algorithms.

---

## 🧠 What Is Harold?

Harold is a **fully autonomous AI crypto trading agent** built for the [lablab.ai Hackathon](https://lablab.ai). He wakes up every 5 minutes, reads the market, consults an LLM brain powered by **Groq + LLaMA 3.3 70B**, and decides whether to buy, sell, or wait — all without a single human touching the keyboard.

He also has an **on-chain identity** via **ERC-8004**, signs his trade intents with **EIP-712**, and routes executions through a **whitelisted Risk Router contract**. Harold isn't just a bot. Harold is a *verifiable agent*.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       HAROLD CORE                        │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │  Kraken CLI  │───▶│ Signal Engine│───▶│ Groq LLM  │  │
│  │  Market Data │    │ SMA + Range  │    │ LLaMA 3.3 │  │
│  └──────────────┘    └──────────────┘    └─────┬─────┘  │
│                                                │        │
│  ┌─────────────────────────────────────────────▼──────┐  │
│  │                  Decision Router                    │  │
│  │         BUY  ──▶  Paper Trade via Kraken CLI       │  │
│  │         SELL ──▶  Exit + CSV log                   │  │
│  │         HOLD ──▶  Sleep & Monitor PnL              │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   HAROLD ON-CHAIN (ERC-8004)             │
│                                                         │
│  Agent Identity Registry  →  Reputation Registry        │
│  EIP-712 Trade Signatures →  EIP-1271 Wallet Support    │
│  Risk Router Contract     →  DEX Execution (Sepolia)    │
└─────────────────────────────────────────────────────────┘
```

---

## 🔥 Features

### 🤖 AI Brain — Groq + LLaMA 3.3 70B
- Sub-second inference via Groq's ultra-fast API
- JSON-mode output for deterministic, parseable decisions
- Position-aware prompting — Harold knows his own PnL before deciding to hold or cut
- Temperature `0.1` — consistent, logical, not hallucinating moon calls

### 📊 Signal Pipeline
| Signal | Source | What It Tells Harold |
|---|---|---|
| `price` | Kraken CLI | Current BTC price |
| `sma_6h` | OHLC (6 candles × 60min) | Short-term trend |
| `sma_24h` | OHLC (24 candles × 60min) | Medium-term baseline |
| `momentum` | Last 5 candles (up/down count) | Recent price direction |
| `range_position` | (price - low24) / (high24 - low24) | Is BTC near top or bottom of today's range? |
| `volume_spike` | Last vol vs 20-candle avg | Unusual buying/selling pressure |

### 🛡️ Risk Management
- **Take Profit**: `+1.0%` — lock gains fast
- **Stop Loss**: `-1.0%` — cut losses, no ego
- **Position monitor**: checks every 15 seconds
- **Entry gate**: requires SMA alignment + momentum before buying
- **Overbought guard**: won't buy if `range_position > 85%`
- **CSV trade log**: every action timestamped and auditable

### 🔗 On-Chain Identity (ERC-8004 Track)
- **Agent Identity Registry** — Harold has a verifiable on-chain identity deployed on Sepolia testnet
- **Reputation Registry** — trade history and performance attestations stored on-chain
- **EIP-712 Typed Signatures** — every trade intent is cryptographically signed before execution
- **EIP-1271** — smart contract wallet support for agent authentication
- **EIP-155** — chain-ID binding prevents replay attacks across networks
- **Risk Router Contract** — all DEX executions go through a whitelisted Uniswap-style router; Harold cannot go rogue

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
pip install groq python-dotenv requests
```

### 3. Configure `.env`
```env
GROQ_API_KEY=your_groq_key_here
```
> Get a free Groq key at [console.groq.com](https://console.groq.com)

### 4. Install Kraken CLI
```bash
# Follow official Kraken CLI setup
# Ensure `kraken` is in your PATH and paper trading is enabled
```

### 5. Run Harold
```bash
python trading_agent.py
```

Harold will log every decision, every signal, every trade. Watch him work.

---

## 📁 Repo Structure

```
├── trading_agent.py     # Harold's main brain — Groq + Kraken CLI
├── kraken_demo.py       # v3 — legacy demo futures integration
├── test_agent.py        # Early prototype
├── harold_state.json    # Persistent state across restarts
├── trades_log.csv       # Full trade audit log
├── .gitignore
├── LICENSE
└── README.md            # You are here
```

---

## 📈 Sample Output

```
00:50:09  INFO     ━━━ HAROLD AI STARTING (COMPETITION MODE) ━━━
00:50:17  INFO     Groq → BUY 4% | Bullish SMA crossover with upward momentum
00:50:17  INFO     🚀 Bought @ $83,241.00
00:55:22  INFO     Monitor: PnL +0.73% | BTC $83,849.00
01:00:31  INFO     Monitor: PnL +1.02% | BTC $84,091.00
01:00:31  INFO     ✅ Take profit hit. Profit locked.
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

- ✅ **Kraken Track** — Paper trading agent with live market data and AI decisions
- ✅ **ERC-8004 Track** — On-chain agent identity, reputation, and verified trade execution

---

## ⚠️ Disclaimer

Harold trades with **paper money only** (Kraken demo / paper mode). This is a hackathon project — not financial advice. Do not give Harold your real money. Harold is confident, not infallible.

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

**Built in sleepless nights. Powered by Groq. Trusted by no one's real money.**

*Harold is always watching the charts.*

</div>