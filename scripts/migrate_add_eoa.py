#!/usr/bin/env python3
"""Migration script to add eoa_address column to trades and wallet_scores tables."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH


def migrate():
    """Add eoa_address column to trades and wallet_scores tables."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("Starting migration: adding eoa_address column...")

    try:
        # Check if column already exists in trades
        cursor = conn.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]

        if "eoa_address" not in columns:
            print("  Adding eoa_address column to trades table...")
            conn.execute("ALTER TABLE trades ADD COLUMN eoa_address TEXT")
            conn.commit()
            print("  ✓ Added eoa_address to trades")
        else:
            print("  ✓ eoa_address already exists in trades")

        # Check if column already exists in wallet_scores
        cursor = conn.execute("PRAGMA table_info(wallet_scores)")
        columns = [row[1] for row in cursor.fetchall()]

        if "eoa_address" not in columns:
            print("  Adding eoa_address column to wallet_scores table...")
            conn.execute("ALTER TABLE wallet_scores ADD COLUMN eoa_address TEXT")
            conn.commit()
            print("  ✓ Added eoa_address to wallet_scores")
        else:
            print("  ✓ eoa_address already exists in wallet_scores")

        # Create index on eoa_address for fast lookups
        print("  Creating index on trades.eoa_address...")
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_eoa ON trades(eoa_address)")
            conn.commit()
            print("  ✓ Created index on trades.eoa_address")
        except sqlite3.OperationalError as e:
            if "already exists" in str(e):
                print("  ✓ Index already exists")
            else:
                raise

        print("\n✅ Migration complete!")
        print("\nNext steps:")
        print("  1. Re-run ingestion to populate eoa_address for new trades")
        print("  2. Re-run wallet scoring to populate eoa_address in wallet_scores")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
