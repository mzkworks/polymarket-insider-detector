from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY,
    condition_id TEXT,
    question TEXT NOT NULL,
    slug TEXT,
    category TEXT,
    event_id TEXT,
    end_date TEXT,
    resolution_time TEXT,
    outcome TEXT,
    clob_token_ids TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    market_id TEXT REFERENCES markets(id),
    condition_id TEXT,
    wallet_address TEXT NOT NULL,
    eoa_address TEXT,
    side TEXT NOT NULL,
    outcome TEXT,
    outcome_index INTEGER,
    price REAL NOT NULL,
    size REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    transaction_hash TEXT,
    is_winner BOOLEAN
);

CREATE TABLE IF NOT EXISTS wallet_scores (
    wallet_address TEXT PRIMARY KEY,
    eoa_address TEXT,
    total_trades INTEGER,
    win_rate REAL,
    avg_entry_before_resolution REAL,
    p_value REAL,
    size_win_correlation REAL,
    total_pnl REAL,
    insider_score REAL,
    cluster_id TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY,
    wallet_count INTEGER,
    combined_pnl REAL,
    shared_funding_source TEXT,
    confidence REAL
);

CREATE TABLE IF NOT EXISTS ingestion_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_trades_eoa ON trades(eoa_address);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_condition ON trades(condition_id);
CREATE INDEX IF NOT EXISTS idx_markets_condition ON markets(condition_id);
CREATE INDEX IF NOT EXISTS idx_wallet_scores_insider ON wallet_scores(insider_score DESC);
-- Composite index for batch wallet queries with ORDER BY timestamp (10x faster!)
CREATE INDEX IF NOT EXISTS idx_trades_wallet_timestamp ON trades(wallet_address, timestamp);
"""


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)

    # --- Markets ---

    def upsert_markets(self, markets: list[dict]) -> None:
        with self.get_connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO markets
                   (id, condition_id, question, slug, category, event_id,
                    end_date, resolution_time, outcome, clob_token_ids, created_at)
                   VALUES (:id, :condition_id, :question, :slug, :category, :event_id,
                           :end_date, :resolution_time, :outcome, :clob_token_ids, :created_at)""",
                markets,
            )
            conn.commit()

    def get_market(self, market_id: str) -> dict | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
            return dict(row) if row else None

    def get_resolved_markets(self) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM markets WHERE outcome IS NOT NULL"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_markets_without_trades(self) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT m.* FROM markets m
                   LEFT JOIN trades t ON t.market_id = m.id
                   WHERE m.outcome IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM ingestion_state
                       WHERE key = 'market_' || m.id || '_trades'
                   )
                   GROUP BY m.id
                   HAVING COUNT(t.id) = 0
                   ORDER BY m.resolution_time DESC
                   LIMIT 50000"""
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Trades ---

    def insert_trades(self, trades: list[dict]) -> int:
        if not trades:
            return 0
        with self.get_connection() as conn:
            cursor = conn.executemany(
                """INSERT OR IGNORE INTO trades
                   (id, market_id, condition_id, wallet_address, eoa_address, side, outcome,
                    outcome_index, price, size, timestamp, transaction_hash, is_winner)
                   VALUES (:id, :market_id, :condition_id, :wallet_address, :eoa_address, :side, :outcome,
                           :outcome_index, :price, :size, :timestamp, :transaction_hash, :is_winner)""",
                trades,
            )
            conn.commit()
            return cursor.rowcount

    def get_trades_for_market(self, market_id: str) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE market_id = ? ORDER BY timestamp",
                (market_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trades_for_wallet(self, wallet: str) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE wallet_address = ? ORDER BY timestamp DESC LIMIT 2000",
                (wallet,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trades_for_wallets_batch(self, wallets: list[str]) -> dict[str, list[dict]]:
        """Batch-load all trades for a list of wallets in a single query.

        Returns a dict mapping wallet_address -> list of trades.
        This is 100x faster than calling get_trades_for_wallet() in a loop.
        """
        if not wallets:
            return {}

        # SQLite has a limit of 999 parameters, so batch in chunks if needed
        result: dict[str, list[dict]] = {w: [] for w in wallets}

        BATCH_SIZE = 900  # Leave room for safety
        for i in range(0, len(wallets), BATCH_SIZE):
            batch = wallets[i:i + BATCH_SIZE]
            placeholders = ",".join("?" * len(batch))

            with self.get_connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM trades WHERE wallet_address IN ({placeholders}) ORDER BY wallet_address, timestamp",
                    batch,
                ).fetchall()

                for row in rows:
                    wallet = row["wallet_address"]
                    if wallet in result:
                        result[wallet].append(dict(row))

        return result

    def mark_winners(self, market_id: str, winning_outcome: str) -> int:
        """Mark trades as winners based on outcome_index.

        Market outcome is "Yes" (index 0 won) or "No" (index 1 won).
        Trade outcome_index 0 = first outcome, 1 = second outcome.
        """
        winning_index = 0 if winning_outcome == "Yes" else 1
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE trades
                   SET is_winner = (outcome_index = ?)
                   WHERE market_id = ?""",
                (winning_index, market_id),
            )
            conn.commit()
            return cursor.rowcount

    # --- Ingestion State ---

    def get_ingestion_state(self, key: str) -> str | None:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM ingestion_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_ingestion_state(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ingestion_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, value, now),
            )
            conn.commit()

    def mark_market_trades_complete(self, market_id: str, trade_count: int) -> None:
        """Mark that a market's trades have been fully ingested."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ingestion_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (f"market_{market_id}_trades", str(trade_count), now),
            )
            conn.commit()

    def get_market_trade_status(self, market_id: str) -> int | None:
        """Return trade count if market ingestion is complete, None otherwise."""
        val = self.get_ingestion_state(f"market_{market_id}_trades")
        return int(val) if val else None

    # --- Stats helpers (used by Phase 2) ---

    def get_all_active_wallets(self, min_trades: int = 5) -> list[str]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT wallet_address FROM trades
                   GROUP BY wallet_address
                   HAVING COUNT(*) >= ?""",
                (min_trades,),
            ).fetchall()
            return [r["wallet_address"] for r in rows]

    def get_trade_count(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()
            return row["cnt"]

    def get_market_count(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM markets").fetchone()
            return row["cnt"]
