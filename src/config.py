import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "polymarket.db"))

# --- Polymarket API base URLs (no auth required for read-only) ---
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com"

# --- The Graph (Polygon subgraph) ---
THEGRAPH_API_KEY = os.getenv("THEGRAPH_API_KEY", "")
SUBGRAPH_ID = "Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp"
SUBGRAPH_URL = (
    f"https://gateway.thegraph.com/api/{THEGRAPH_API_KEY}/subgraphs/id/{SUBGRAPH_ID}"
    if THEGRAPH_API_KEY
    else ""
)

# --- Allium ---
ALLIUM_API_KEY = os.getenv("ALLIUM_API_KEY", "")
ALLIUM_QUERY_ID = os.getenv("ALLIUM_QUERY_ID", "")
ALLIUM_API_BASE = "https://api.allium.so/api/v1"

# --- DuckDB (optional, for fast bulk ingestion) ---
USE_DUCKDB = os.getenv("USE_DUCKDB", "").lower() in ("1", "true", "yes")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", str(PROJECT_ROOT / "data" / "polymarket.duckdb"))

# --- Discord ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# --- Rate limits (per 10-second window, conservative — ~50% of documented maximums) ---
GAMMA_RATE_LIMIT = int(os.getenv("GAMMA_RATE_LIMIT", "250"))
DATA_API_RATE_LIMIT = int(os.getenv("DATA_API_RATE_LIMIT", "150"))
CLOB_RATE_LIMIT = int(os.getenv("CLOB_RATE_LIMIT", "1000"))

# --- Retry / backoff ---
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 1.0  # seconds; exponential: 1, 2, 4, 8, 16

# --- Pagination defaults ---
GAMMA_PAGE_SIZE = 500
DATA_API_PAGE_SIZE = 1000

# --- Ingest window (default: last N months) ---
# Set via env `LAST_N_MONTHS` to limit trade ingestion to recent history.
# Increased to 6 months to avoid filtering out recently-created markets
LAST_N_MONTHS = int(os.getenv("LAST_N_MONTHS", "6"))
# Data API trade ordering: 'desc' for newest->oldest, 'asc' for oldest->newest
DATA_API_TRADES_ORDER = os.getenv("DATA_API_TRADES_ORDER", "desc").lower()

# --- SSL Verification ---
# WARNING: Disabling SSL verification is a security risk!
# Only disable if you're behind a corporate proxy/firewall with SSL inspection
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() in ("1", "true", "yes")
