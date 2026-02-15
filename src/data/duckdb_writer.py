from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from src.config import DUCKDB_PATH, DB_PATH


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
    market_id TEXT,
    condition_id TEXT,
    wallet_address TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT,
    outcome_index INTEGER,
    price DOUBLE,
    size DOUBLE,
    timestamp INTEGER,
    transaction_hash TEXT,
    is_winner BOOLEAN
);
"""


class DuckDBWriter:
    """Fast bulk writer using DuckDB for ingestion, with optional export to SQLite.

    Usage:
        writer = DuckDBWriter(path)
        writer.create_schema()
        writer.insert_trades_batch(list_of_dicts)
        writer.insert_markets_batch(list_of_dicts)
        writer.export_to_sqlite(sqlite_path)
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or DUCKDB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path)
        # enable faster writes
        self.con.execute("PRAGMA threads=4")

    def create_schema(self) -> None:
        self.con.execute(SCHEMA_SQL)

    def insert_trades_batch(self, trades: Iterable[dict]) -> int:
        df = pd.DataFrame(list(trades))
        if df.empty:
            return 0
        # Ensure columns order
        cols = [
            "id",
            "market_id",
            "condition_id",
            "wallet_address",
            "side",
            "outcome",
            "outcome_index",
            "price",
            "size",
            "timestamp",
            "transaction_hash",
            "is_winner",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols]
        # Use DuckDB's insert-from-dataframe capability
        self.con.register("_tmp_df", df)
        self.con.execute("INSERT INTO trades SELECT * FROM _tmp_df")
        self.con.unregister("_tmp_df")
        return len(df)

    def insert_markets_batch(self, markets: Iterable[dict]) -> int:
        df = pd.DataFrame(list(markets))
        if df.empty:
            return 0
        # align columns similar to schema
        cols = [
            "id",
            "condition_id",
            "question",
            "slug",
            "category",
            "event_id",
            "end_date",
            "resolution_time",
            "outcome",
            "clob_token_ids",
            "created_at",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols]
        self.con.register("_tmp_markets", df)
        self.con.execute("INSERT OR REPLACE INTO markets SELECT * FROM _tmp_markets")
        self.con.unregister("_tmp_markets")
        return len(df)

    def mark_winners(self, market_id: str, outcome: str | None) -> int:
        if outcome is None:
            return 0
        winning_index = 0 if outcome == "Yes" else 1
        res = self.con.execute(
            "UPDATE trades SET is_winner = (outcome_index = ?) WHERE market_id = ?",
            (winning_index, market_id),
        ).rowcount
        return res or 0

    def export_to_sqlite(self, sqlite_path: str | None = None) -> None:
        sqlite_path = sqlite_path or DB_PATH
        # Read entire tables into pandas and write to sqlite using to_sql
        # This is I/O heavy but one-time; DuckDB is fast at reading.
        markets_df = self.con.execute("SELECT * FROM markets").df()
        trades_df = self.con.execute("SELECT * FROM trades").df()

        # Write to sqlite using pandas - APPEND to preserve existing data
        import sqlite3

        conn = sqlite3.connect(sqlite_path)
        # Use "append" mode to add to existing tables, not replace them
        markets_df.to_sql("markets", conn, if_exists="append", index=False)
        trades_df.to_sql("trades", conn, if_exists="append", index=False)
        conn.close()

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
