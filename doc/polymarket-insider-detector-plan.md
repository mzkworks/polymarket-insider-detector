# Polymarket Insider Detector — Project Plan

## Project Summary

A real-time analytics and alerting system that identifies statistically anomalous wallets on Polymarket and sends Discord alerts when flagged wallets make new trades. Built with Python, powered by Polymarket APIs + Allium for cross-chain forensics.

**Team:** 4–5 people (Mac + Windows)
**Budget:** Free tier only
**Timeline:** ASAP
**Alerts:** Discord webhooks

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      STAGE 1: DATA INGESTION                │
│                                                             │
│  Polymarket Gamma API ──→ Markets, outcomes, resolution     │
│  Polymarket CLOB API  ──→ Historical trades, orderbook      │
│  Polymarket Data API  ──→ Positions, trade history           │
│  Allium API           ──→ Wallet funding, cross-chain data  │
│                              │                               │
│                              ▼                               │
│                     SQLite Database                           │
│              (markets, trades, wallets, scores)              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 STAGE 2: WALLET SCORING ENGINE               │
│                                                             │
│  For each wallet, calculate:                                │
│  • Win rate (% of trades that resolved correctly)           │
│  • Timing score (avg time between entry and resolution)     │
│  • P-value (statistical probability of results by chance)   │
│  • Position sizing (do they bet big only when they win?)    │
│  • Composite "insider score" combining all signals          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              STAGE 3: CLUSTER / SYBIL DETECTION             │
│                                                             │
│  • Funding source analysis (via Allium)                     │
│  • Temporal correlation (wallets trading same markets       │
│    within minutes of each other)                            │
│  • Behavioral fingerprinting (similar sizing, timing)       │
│  • Graph analysis to group related wallets                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│           STAGE 4: REAL-TIME MONITOR + DISCORD ALERTS       │
│                                                             │
│  Polymarket WebSocket ──→ Live trade stream                 │
│            │                                                │
│            ▼                                                │
│  Filter: Is this wallet flagged? ──→ No: ignore            │
│            │                                                │
│           Yes                                               │
│            │                                                │
│            ▼                                                │
│  Discord Webhook ──→ Alert with market, position, size,    │
│                      wallet score, and context              │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Best data science ecosystem, beginner-friendly |
| Database | SQLite → PostgreSQL later | SQLite = zero setup, works everywhere, good for prototyping |
| HTTP client | `httpx` or `requests` | API calls to Polymarket + Allium |
| WebSocket | `websockets` library | Real-time trade monitoring |
| Stats | `scipy` + `numpy` | P-value calculations, statistical tests |
| Clustering | `networkx` | Graph-based sybil detection |
| Alerts | Discord webhooks | Free, simple HTTP POST |
| Dashboard (later) | Streamlit | Quick web UI, Python-native, no frontend skills needed |
| Cross-platform | Docker (optional) | Ensures Mac + Windows consistency |

---

## API Overview & Free Tier Limits

### Polymarket APIs (all free, no API key needed for read-only)

| API | Base URL | What it gives us |
|-----|----------|-----------------|
| Gamma API | `https://gamma-api.polymarket.com` | Market metadata, events, resolution info |
| CLOB API | `https://clob.polymarket.com` | Orderbook, prices, trade history |
| Data API | `https://data-api.polymarket.com` | Wallet positions, trade history |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com` | Real-time trade stream |
| Subgraph | GraphQL endpoint | On-chain token data |

**Rate limits:** Documented at `docs.polymarket.com/quickstart/introduction/rate-limits` — we'll need to respect these and add retry logic.

### Allium API (free tier)

| Feature | Endpoint | Use case |
|---------|----------|----------|
| Wallet transactions | `/api/v1/developer/wallet/transactions` | Trace wallet funding sources |
| Wallet balances | `/api/v1/developer/wallet/balances` | Current holdings |
| Custom SQL | `/api/v1/explorer/queries/{id}/run-async` | Complex cross-chain queries |

**Rate limit:** 1 request/second. Register at `https://api.allium.so/api/v1/register` with name + email to get API key.

---

## Build Phases & Timeline

### Phase 1: Foundation (Days 1–3)
> **Goal:** Set up the project, pull market data, store it locally.

**Tasks:**
1. Set up Python environment with `pyproject.toml` (works on Mac + Windows)
2. Write Polymarket API client (markets, events, trades)
3. Design SQLite schema (markets, trades, wallets, scores)
4. Build data ingestion pipeline — pull all resolved markets and their trades
5. Register for Allium API key

**Deliverable:** A local database with historical Polymarket trades you can query.

**Who can work on this:** 1–2 people

---

### Phase 2: Wallet Scoring Engine (Days 3–6)
> **Goal:** Score every wallet by how "suspicious" their trading pattern is.

**Tasks:**
1. For each wallet, calculate:
   - **Win rate** = (winning trades) / (total trades)
   - **Timing score** = average (resolution_time - entry_time) per trade
   - **P-value** = binomial test: given N trades at average market probability, what's the chance of this win rate?
   - **Size-win correlation** = do they bet bigger when they win?
2. Combine into a composite "insider score"
3. Filter: only flag wallets with 20+ trades (statistical significance)
4. Rank and store top suspicious wallets

**The math explained simply:**

If a market is priced at 50% (coin flip), and a wallet wins 19 out of 20 trades, the p-value answers: "What's the probability of winning 19+ out of 20 fair coin flips?" The answer is ~0.00002 — extremely unlikely by chance.

```python
from scipy.stats import binom_test
p_value = binom_test(19, 20, 0.5, alternative='greater')
# p_value ≈ 0.00002 → almost certainly not luck
```

The twist: we don't use 0.5 — we use the actual market price at the time of their entry. If they bought "Yes" at $0.90 (90% implied probability) and it resolved Yes, that's not impressive. If they bought at $0.10 and it resolved Yes, that's very suspicious.

**Deliverable:** A ranked list of wallets sorted by insider score with full stats.

**Who can work on this:** 1–2 people (someone comfortable with basic math)

---

### Phase 3: Cluster Detection (Days 5–8)
> **Goal:** Find groups of wallets that are likely controlled by the same entity.

**Tasks:**
1. **Temporal correlation:** Find wallets that trade the same markets within a short window (e.g., <5 minutes apart)
2. **Funding source analysis (Allium):** Check if multiple flagged wallets were funded from the same address
3. **Behavioral similarity:** Similar position sizes, similar timing patterns, similar market selection
4. **Graph construction:** Build a network where wallets are nodes and suspicious correlations are edges
5. Use community detection (e.g., Louvain algorithm via `networkx`) to identify clusters

**Deliverable:** Identified clusters of related wallets with confidence scores.

**Who can work on this:** 1–2 people

---

### Phase 4: Real-Time Monitor + Discord Alerts (Days 6–9)
> **Goal:** Watch flagged wallets in real time and alert on Discord when they trade.

**Tasks:**
1. Set up Discord webhook (free — just create a webhook in your Discord server settings)
2. Connect to Polymarket WebSocket for live trade stream
3. Filter incoming trades against the flagged wallet list
4. When a match is found, send a rich Discord embed with:
   - Wallet address (linked to on-chain explorer)
   - Market name and current price
   - Position direction (Yes/No) and size
   - Wallet's insider score and historical win rate
   - Time until market resolution (if known)
5. Add reconnection logic (WebSockets drop — need auto-reconnect)

**Discord alert format example:**
```
🚨 INSIDER ALERT — High Confidence

Wallet: 0xabc...def (Score: 94.2)
Market: "Will CPI exceed 3.5% for January 2026?"
Position: YES @ $0.23 — $47,000
Win Rate: 97.3% on 67 trades
Avg Entry: 47 min before resolution
Cluster: Part of 12-wallet network

⚡ Resolution in ~2 hours
```

**Deliverable:** A running process that sends Discord alerts when flagged wallets trade.

**Who can work on this:** 1–2 people

---

### Phase 5: Dashboard & Polish (Days 8–12)
> **Goal:** Web UI for the team to explore data without running scripts.

**Tasks:**
1. Streamlit dashboard with:
   - Leaderboard of suspicious wallets
   - Individual wallet deep-dive (trade history, timing chart, p-value)
   - Cluster visualization (network graph)
   - Active market monitor
2. Docker setup so anyone on the team can run it
3. Documentation and README

**Deliverable:** A browser-based dashboard + containerized deployment.

**Who can work on this:** 1 person

---

## Project File Structure

```
polymarket-insider-detector/
├── README.md
├── pyproject.toml              # Dependencies + project config
├── .env.example                # Template for API keys
├── docker-compose.yml          # One-command setup for team
├── Dockerfile
│
├── src/
│   ├── __init__.py
│   ├── config.py               # Settings, env vars, constants
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── polymarket_client.py   # Gamma, CLOB, Data API wrapper
│   │   ├── allium_client.py       # Allium API wrapper
│   │   ├── websocket_client.py    # Real-time trade stream
│   │   └── database.py            # SQLite schema + queries
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── wallet_scorer.py       # Win rate, timing, p-value
│   │   ├── cluster_detector.py    # Sybil detection + graph analysis
│   │   └── stats.py               # Statistical utilities
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── monitor.py             # Real-time wallet watcher
│   │   └── discord.py             # Discord webhook sender
│   │
│   └── dashboard/
│       ├── __init__.py
│       └── app.py                 # Streamlit dashboard
│
├── scripts/
│   ├── ingest.py                  # Run full historical data pull
│   ├── score.py                   # Run wallet scoring
│   ├── detect_clusters.py         # Run cluster detection
│   └── monitor.py                 # Start real-time monitoring
│
└── data/
    └── polymarket.db              # SQLite database (gitignored)
```

---

## Database Schema

```sql
-- Markets and their outcomes
CREATE TABLE markets (
    id TEXT PRIMARY KEY,              -- Polymarket condition_id
    question TEXT NOT NULL,
    slug TEXT,
    category TEXT,
    resolution_time TIMESTAMP,
    outcome TEXT,                     -- 'Yes' or 'No' or NULL if unresolved
    created_at TIMESTAMP
);

-- Individual trades
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    market_id TEXT REFERENCES markets(id),
    wallet_address TEXT NOT NULL,
    side TEXT NOT NULL,               -- 'Yes' or 'No'  
    price REAL NOT NULL,              -- Entry price (0-1)
    size REAL NOT NULL,               -- USDC amount
    timestamp TIMESTAMP NOT NULL,
    is_winner BOOLEAN                 -- Did this side win? (set after resolution)
);

-- Wallet-level aggregated scores
CREATE TABLE wallet_scores (
    wallet_address TEXT PRIMARY KEY,
    total_trades INTEGER,
    win_rate REAL,
    avg_entry_before_resolution REAL,  -- Seconds before resolution
    p_value REAL,                      -- Statistical significance
    size_win_correlation REAL,         -- Bet bigger when winning?
    total_pnl REAL,
    insider_score REAL,                -- Composite score (0-100)
    cluster_id TEXT,                   -- Which cluster they belong to
    last_updated TIMESTAMP
);

-- Cluster groupings
CREATE TABLE clusters (
    cluster_id TEXT PRIMARY KEY,
    wallet_count INTEGER,
    combined_pnl REAL,
    shared_funding_source TEXT,        -- Common funder address if found
    confidence REAL                    -- How confident we are this is one entity
);

-- Indexes for performance
CREATE INDEX idx_trades_wallet ON trades(wallet_address);
CREATE INDEX idx_trades_market ON trades(market_id);
CREATE INDEX idx_trades_timestamp ON trades(timestamp);
CREATE INDEX idx_wallet_scores_insider ON wallet_scores(insider_score DESC);
```

---

## Team Task Allocation (Suggested)

| Person | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|--------|---------|---------|---------|---------|---------|
| Person A | API client + DB schema | Wallet scorer | — | — | Dashboard |
| Person B | Data ingestion pipeline | P-value stats | — | Discord alerts | — |
| Person C | — | — | Temporal correlation | WebSocket monitor | Docker |
| Person D | Allium client | — | Funding analysis + graph | — | Docs |

---

## Setup Instructions (for each team member)

### 1. Install Python 3.11+
- **Mac:** `brew install python@3.11`
- **Windows:** Download from `python.org`, check "Add to PATH"

### 2. Clone the repo and install dependencies
```bash
git clone <your-repo-url>
cd polymarket-insider-detector
python -m venv .venv

# Mac/Linux:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Set up environment variables
```bash
cp .env.example .env
# Edit .env with your Allium API key and Discord webhook URL
```

### 4. Register for Allium API key
```bash
curl -X POST https://api.allium.so/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "your@email.com"}'
```

### 5. Create Discord webhook
- Go to your Discord server → Settings → Integrations → Webhooks
- Create a new webhook, copy the URL
- Paste into `.env` as `DISCORD_WEBHOOK_URL`

---

## Key Dependencies (requirements.txt)

```
httpx>=0.27.0          # Async HTTP client
websockets>=12.0       # WebSocket connections
scipy>=1.12.0          # Statistical tests (binomial test, p-values)
numpy>=1.26.0          # Numerical computing
networkx>=3.2          # Graph analysis for cluster detection
python-dotenv>=1.0.0   # Environment variable management
streamlit>=1.31.0      # Dashboard UI
plotly>=5.18.0         # Interactive charts
pandas>=2.2.0          # Data manipulation
rich>=13.7.0           # Pretty terminal output
```

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Polymarket rate limits | Can't pull enough data | Implement exponential backoff, cache aggressively, stagger requests |
| WebSocket disconnections | Miss real-time trades | Auto-reconnect with backoff, periodic polling as fallback |
| False positives | Flagging legitimate traders | Require minimum 20 trades, p-value < 0.001, manual review |
| Market manipulation (not insider) | Different signal than insider trading | Timing score helps distinguish — insiders trade right before resolution, manipulators trade to move price |
| Allium rate limit (1/sec) | Slow cluster analysis | Batch requests, cache results, run cluster analysis offline |
| Database size | SQLite slows with millions of rows | Migrate to PostgreSQL when needed, add proper indexes now |

---

## Legal Disclaimer

This tool analyzes publicly available on-chain data for research and analytics purposes. While identifying statistically anomalous trading patterns is legal, acting on information you believe to be derived from insider knowledge may create legal exposure depending on your jurisdiction. Consult a legal professional before using this tool's outputs for trading decisions.

---

## Next Steps

1. **Set up the Git repo** and share with team
2. **Each team member:** Install Python, register for Allium API key, create Discord webhook
3. **Start Phase 1** — build the Polymarket API client and database
4. **Check in after Day 3** — you should have a populated database to query

Ready to start coding? Begin with `src/data/polymarket_client.py`.
