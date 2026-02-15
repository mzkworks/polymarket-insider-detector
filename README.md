# Polymarket Insider Trading Detector

A comprehensive system for detecting potential insider trading and coordinated sybil networks on Polymarket prediction markets.

## Overview

This project analyzes historical trading data from Polymarket to identify suspicious trading patterns that may indicate insider knowledge or coordinated wallet clusters. It uses statistical analysis, temporal correlation graphs, and community detection algorithms to flag high-risk wallets.

## Features

- **Data Ingestion**: Resumable ingestion of Polymarket markets and trades via multiple APIs (Gamma, Data API)
- **Wallet Scoring**: Statistical analysis of trading patterns including:
  - Win rate analysis with binomial testing
  - Timing analysis (average entry time before market resolution)
  - Size-win correlation (do wallets bet more when they win?)
  - Total PnL calculation
  - Composite insider score (0-100)
- **Cluster Detection**: Identify coordinated wallet networks using:
  - Temporal correlation graphs (wallets trading same markets within 5 minutes)
  - Louvain community detection
  - Behavioral similarity analysis
- **Interactive Dashboard**: Streamlit web interface to explore findings

## Architecture

```
src/
├── analysis/          # Scoring and clustering algorithms
│   ├── cluster_detector.py
│   ├── stats.py
│   └── wallet_scorer.py
├── data/             # Data ingestion and storage
│   ├── database.py
│   ├── dns_resolver.py
│   └── polymarket_client.py
└── dashboard/        # Streamlit web UI
    └── app.py

scripts/
├── ingest.py         # Data ingestion script
├── score.py          # Wallet scoring script
└── detect_clusters.py # Cluster detection script
```

## Setup

### Prerequisites

- Python 3.10+
- ~3GB disk space for database

### Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file (optional):
```bash
SSL_VERIFY=true
USE_DUCKDB=false
LAST_N_MONTHS=6
```

### DNS Configuration (Important!)

This project includes a custom DNS resolver to bypass ISP blocking of Polymarket domains. It automatically uses Google DNS (8.8.8.8) for Polymarket API calls.

If you're in a region where Polymarket is blocked, the custom resolver will handle it automatically.

## Usage

### 1. Ingest Data

Fetch markets and trades from Polymarket:

```bash
python -m scripts.ingest --months=6
```

**Options:**
- `--months N`: Fetch markets from last N months (default: 6)
- Ingestion is fully resumable - safe to stop and restart

**For long-running ingestion:**
```bash
# Windows: Use the auto-restart loop
run_ingestion_loop.bat

# Monitor progress
check_progress.bat
```

### 2. Score Wallets

Analyze wallets and calculate insider scores:

```bash
python -m scripts.score --min-trades 20 --top 25
```

**Options:**
- `--min-trades N`: Minimum trades required to score a wallet (default: 20)
- `--top N`: Show top N suspicious wallets (default: 25)

### 3. Detect Clusters

Find coordinated wallet networks:

```bash
python -m scripts.detect_clusters --min-score 25
```

**Options:**
- `--min-score N`: Only analyze wallets with insider_score >= N (default: 25)
  - Use `--min-score 0` to analyze all wallets (slow!)
  - Higher values = faster, more focused analysis

### 4. Launch Dashboard

Explore results in interactive web interface:

```bash
python -m streamlit run src/dashboard/app.py
```

Open http://localhost:8502 in your browser.

## Configuration

### Key Parameters

**Wallet Scoring:**
- `MIN_TRADES = 20`: Minimum BUY trades on resolved markets to score a wallet

**Cluster Detection:**
- `TEMPORAL_WINDOW_SECONDS = 300`: Two wallets trading within 5 minutes = correlated
- `MIN_EDGE_WEIGHT = 10`: Minimum co-trades to keep an edge in the graph
- `MIN_CLUSTER_SIZE = 2`: Minimum wallets to report a cluster

**Rate Limiting:**
- Gamma API: 50 req/10s
- Data API: 20 req/1s (smooth)
- CLOB API: 50 req/10s

## Database

**Storage:** SQLite (~2GB for full historical data)

**Schema:**
- `markets`: Market metadata
- `trades`: Individual trades
- `wallet_scores`: Calculated scores per wallet
- `clusters`: Detected sybil clusters
- `ingestion_state`: Resumable ingestion tracking

## Results Summary

After ingestion (example from 6-month analysis):
- **412K** total markets
- **3.3M** trades
- **11.7K** wallets scored
- **1.4K** high-risk wallets (score >= 25)
- **3 massive clusters** detected with $1.46B combined PnL

## Technical Details

### ISP Blocking Bypass

The project includes a custom DNS resolver that:
1. Pre-resolves Polymarket domains using Google DNS (8.8.8.8)
2. Monkey-patches `socket.getaddrinfo()` to use cached IPs
3. Handles both string and bytes hostnames
4. Bypasses ISP DNS hijacking without requiring VPN

### Cluster Detection Algorithm

1. Build temporal correlation graph
2. Filter to high-risk wallets (min_score threshold)
3. Find wallet pairs trading same market within 5 minutes
4. Weight edges by number of co-trades
5. Add behavioral similarity bonuses (similar trade sizes)
6. Prune weak edges (MIN_EDGE_WEIGHT)
7. Run Louvain community detection
8. Calculate cluster confidence scores

## Performance Optimization

- **Composite indexes** on (wallet_address, timestamp) for fast queries
- **Incremental scoring**: Only score wallets with >= min_trades
- **Graph filtering**: Use min_score to reduce graph size before clustering
- **Edge pruning**: MIN_EDGE_WEIGHT to focus on strong signals

## Troubleshooting

### Ingestion stuck/slow
- Check `check_progress.bat` to monitor progress
- Ingestion is resumable - safe to restart
- Network issues? The script has exponential backoff retry logic

### Cluster detection taking too long
- Increase `--min-score` to reduce wallets analyzed
- Increase `MIN_EDGE_WEIGHT` in `cluster_detector.py`
- Check if graph is too dense (>1M edges)

### SSL verification errors
- Set `SSL_VERIFY=false` in `.env` if behind corporate proxy
- ⚠️ This disables security checks - only use if necessary

## Contributing

This project was built to detect suspicious trading patterns on prediction markets. Suggestions and improvements welcome!

## Disclaimer

This tool is for research and analysis purposes only. Results indicate *potential* insider trading or coordination but are not definitive proof. Always verify findings through additional research.

## License

MIT
