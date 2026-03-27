# AI Trading Agent 🤖📈

> Autonomous AI-powered trading agent built with Kraken CLI — submitted for the [AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/ai-trading-agents) on lablab.ai.

**Team:** Harolds of Hackathon &nbsp;|&nbsp; **Challenge:** Kraken CLI &nbsp;|&nbsp; **Event:** March 30 – April 12, 2026

---

## What It Does

This project is an autonomous trading agent that connects to the Kraken exchange, analyses live market data, and executes trades programmatically — with no human intervention required.

The agent follows a continuous loop:

1. **Perceive** — fetches real-time OHLCV price data from Kraken via the CLI
2. **Analyse** — computes technical indicators (RSI, EMA) to identify market signals
3. **Reason** — passes signals to an LLM, which decides whether to buy, sell, or hold
4. **Execute** — applies risk controls, then places orders through the Kraken CLI

---

## Project Structure

```
ai-trading-agent/
│
├── agent/
│   ├── data.py          # Kraken CLI integration and market data fetching
│   ├── indicators.py    # RSI, EMA, and signal computation
│   ├── reasoning.py     # LLM prompt and decision parsing
│   └── execution.py     # Risk controls and order execution
│
├── config/
│   └── settings.py      # Thresholds, timeframes, and shared config
│
├── tests/
│   └── test_agent.py    # Unit tests
│
├── docs/
│   └── architecture.md  # System design and technical decisions
│
├── .env.example         # Required environment variables (template)
├── requirements.txt     # Python dependencies
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- [Kraken CLI](https://github.com/kraken-hq/kraken-cli) installed
- A Kraken account (paper trading sandbox works for testing)
- An LLM API key (OpenAI / Anthropic / etc.)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/ai-trading-agent.git
cd ai-trading-agent

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Fill in your keys inside .env

# 4. Run the agent in paper trading mode
python agent/main.py --mode paper
```

### Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
LLM_API_KEY=
TRADING_PAIR=XBTUSD
TIMEFRAME=1h
MAX_POSITION_SIZE=0.05
DAILY_LOSS_LIMIT=0.10
```

---

## Risk Controls

The agent enforces hard limits on every trade before execution:

- **Position sizing** — never risks more than 5% of portfolio per trade
- **Stop-loss** — automatically exits a position if it drops beyond the threshold
- **Daily loss limit** — halts all trading if total losses exceed 10% in a single day
- **Paper trading mode** — test safely with zero real money before going live

---

## Tech Stack

| Layer | Technology |
|---|---|
| Exchange connectivity | Kraken CLI |
| Market data | Kraken REST API (via CLI) |
| AI reasoning | LLM (TBD) |
| Language | Python 3.10+ |
| Indicators | pandas-ta / manual implementation |

---

## Team

| Name | Role |
|---|---|
| TBD | Project Lead |
| TBD | Data Pipeline & Kraken CLI |
| TBD | Indicators & Strategy |
| TBD | AI Reasoning Layer |
| TBD | Risk Controls & Execution |
| TBD | Presentation & Social |

---

## License

This project is licensed under the [MIT License](LICENSE).
