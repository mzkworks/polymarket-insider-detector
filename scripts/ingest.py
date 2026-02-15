"""
Pull resolved markets and trades from Polymarket into SQLite.

Usage:
    python -m scripts.ingest [--full]

Flags:
    --full    Ignore watermarks and re-ingest everything
"""

import asyncio
import logging
import sys

from typing import Any, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from src.data.database import Database
from src.data.polymarket_client import PolymarketClient
from src.config import USE_DUCKDB, DUCKDB_PATH, DB_PATH, LAST_N_MONTHS
from src.data.duckdb_writer import DuckDBWriter
import time
from datetime import datetime

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def ingest_markets(
    client: PolymarketClient, db: Database, full: bool = False
) -> int:
    """Fetch all closed markets from Gamma API into the database."""
    start_offset = 0
    if not full:
        saved = db.get_ingestion_state("market_offset")
        if saved:
            start_offset = int(saved)
            console.print(f"  Resuming from offset {start_offset}")

    total = 0
    async for page, next_offset in client.iter_all_markets(
        closed=True, start_offset=start_offset
    ):
        normalized = [client.normalize_market(m) for m in page]
        db.upsert_markets(normalized)
        db.set_ingestion_state("market_offset", str(next_offset))
        total += len(normalized)
        console.print(f"  Markets fetched: {total}", end="\r")

    console.print(f"  Markets fetched: {total}    ")
    return total


async def ingest_trades_for_market(
    client: PolymarketClient, db: Database, market: dict, since_ts: Optional[int] = None
) -> int:
    """Fetch all trades for a single resolved market."""
    condition_id = market.get("condition_id")
    if not condition_id:
        return 0

    total = 0
    insert_sql = (
        """INSERT OR IGNORE INTO trades
           (id, market_id, condition_id, wallet_address, side, outcome,
            outcome_index, price, size, timestamp, transaction_hash, is_winner)
           VALUES (:id, :market_id, :condition_id, :wallet_address, :side, :outcome,
                   :outcome_index, :price, :size, :timestamp, :transaction_hash, :is_winner)"""
    )

    # Use a single DB connection for all pages of this market to avoid
    # repeatedly opening/closing connections and committing per page.
    with db.get_connection() as conn:
        cursor = conn.cursor()
        async for page in client.iter_trades_for_market(condition_id, since_ts=since_ts):
            normalized = [client.normalize_trade(t, market["id"]) for t in page]
            if not normalized:
                continue
            cursor.executemany(insert_sql, normalized)
            # rowcount may be -1 for sqlite in some builds; fall back to len
            try:
                inserted = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else len(normalized)
            except Exception:
                inserted = len(normalized)
            total += inserted
        conn.commit()

    # Mark winners based on market outcome
    if market.get("outcome") and total > 0:
        db.mark_winners(market["id"], market["outcome"])

    return total


async def ingest_all_trades(client: PolymarketClient, db: Database, since_ts: Optional[int] = None) -> int:
    """Ingest trades for all resolved markets that don't have trades yet."""
    markets = db.get_markets_without_trades()
    if not markets:
        console.print("  No markets need trade ingestion.")
        return 0

    # Disable market filtering by timestamp - it's too aggressive and filters out valid markets
    # Just process all markets that need trades
    console.print(f"  Found {len(markets)} markets needing trade ingestion")

    # Tunables - conservative settings for stability
    CONCURRENCY = 10        # concurrent market fetchers (stable, won't deadlock)
    QUEUE_MAX = 20000      # max in-flight normalized trades
    BATCH_SIZE = 2000      # DB writer batch size

    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_MAX)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def producer(market: dict):
        async with sem:
            try:
                condition_id = market.get("condition_id")
                if not condition_id:
                    return
                trade_count = 0
                async for page in client.iter_trades_for_market(condition_id, since_ts=since_ts):
                    normalized = [client.normalize_trade(t, market["id"]) for t in page]
                    trade_count += len(normalized)
                    for t in normalized:
                        await queue.put(t)
                # signal end of this market so the consumer can mark winners and completion
                await queue.put({"_end_market": market["id"], "_outcome": market.get("outcome"), "_count": trade_count})
            except Exception:
                logger.exception("Producer failed for market %s", market.get("id"))

    async def consumer(total_markets: int) -> int:
        """Consume normalized trades from the queue and write in batches.

        If `USE_DUCKDB` is enabled, write into DuckDB for fast bulk ingestion,
        otherwise write to the project's SQLite DB.
        """
        inserted_total = 0
        start_time = time.time()

        if USE_DUCKDB:
            writer = DuckDBWriter(DUCKDB_PATH)
            writer.create_schema()

            markets_completed = 0
            batch: list[dict] = []
            while True:
                item = await queue.get()
                if item is None:
                    if batch:
                        writer.insert_trades_batch(batch)
                        inserted_total += len(batch)
                        batch = []
                    queue.task_done()
                    break

                if isinstance(item, dict) and item.get("_end_market"):
                    if batch:
                        writer.insert_trades_batch(batch)
                        inserted_total += len(batch)
                        batch = []
                    market_id = item["_end_market"]
                    outcome = item.get("_outcome")
                    trade_count = item.get("_count", 0)
                    if outcome is not None:
                        writer.mark_winners(market_id, outcome)
                    # Mark this market as completed for resumable ingestion
                    db.mark_market_trades_complete(market_id, trade_count)
                    markets_completed += 1

                    # Calculate ETA
                    elapsed = time.time() - start_time
                    markets_per_sec = markets_completed / elapsed if elapsed > 0 else 0
                    remaining = total_markets - markets_completed
                    eta_seconds = remaining / markets_per_sec if markets_per_sec > 0 else 0
                    eta_minutes = int(eta_seconds / 60)
                    eta_hours = eta_minutes // 60
                    eta_mins = eta_minutes % 60

                    queue.task_done()
                    if eta_hours > 0:
                        console.print(
                            f"  Markets: {markets_completed}/{total_markets} "
                            f"({markets_per_sec:.1f}/sec) ETA: {eta_hours}h{eta_mins}m    ",
                            end="\r"
                        )
                    else:
                        console.print(
                            f"  Markets: {markets_completed}/{total_markets} "
                            f"({markets_per_sec:.1f}/sec) ETA: {eta_mins}m    ",
                            end="\r"
                        )
                    continue

                batch.append(item)
                if len(batch) >= BATCH_SIZE:
                    writer.insert_trades_batch(batch)
                    inserted_total += len(batch)
                    batch = []
                queue.task_done()

            # final flush handled above; export to sqlite for compatibility
            try:
                writer.export_to_sqlite(DB_PATH)
            finally:
                writer.close()

            return inserted_total

        # Fallback: write to SQLite (existing behavior)
        insert_sql = (
            """INSERT OR IGNORE INTO trades
               (id, market_id, condition_id, wallet_address, side, outcome,
                outcome_index, price, size, timestamp, transaction_hash, is_winner)
               VALUES (:id, :market_id, :condition_id, :wallet_address, :side, :outcome,
                       :outcome_index, :price, :size, :timestamp, :transaction_hash, :is_winner)"""
        )

        markets_completed = 0

        with db.get_connection() as conn:
            cursor = conn.cursor()
            batch: list[dict] = []
            while True:
                item = await queue.get()
                if item is None:
                    if batch:
                        cursor.executemany(insert_sql, batch)
                        conn.commit()
                        inserted_total += len(batch)
                        batch = []
                    queue.task_done()
                    break

                if isinstance(item, dict) and item.get("_end_market"):
                    if batch:
                        cursor.executemany(insert_sql, batch)
                        conn.commit()
                        inserted_total += len(batch)
                        batch = []
                    market_id = item["_end_market"]
                    outcome = item.get("_outcome")
                    trade_count = item.get("_count", 0)
                    if outcome is not None:
                        winning_index = 0 if outcome == "Yes" else 1
                        cursor.execute(
                            """UPDATE trades
                               SET is_winner = (outcome_index = ?)
                               WHERE market_id = ?""",
                            (winning_index, market_id),
                        )
                        conn.commit()
                    # Mark this market as completed for resumable ingestion
                    db.mark_market_trades_complete(market_id, trade_count)
                    markets_completed += 1

                    # Calculate ETA
                    elapsed = time.time() - start_time
                    markets_per_sec = markets_completed / elapsed if elapsed > 0 else 0
                    remaining = total_markets - markets_completed
                    eta_seconds = remaining / markets_per_sec if markets_per_sec > 0 else 0
                    eta_minutes = int(eta_seconds / 60)
                    eta_hours = eta_minutes // 60
                    eta_mins = eta_minutes % 60

                    queue.task_done()
                    if eta_hours > 0:
                        console.print(
                            f"  Markets: {markets_completed}/{total_markets} "
                            f"({markets_per_sec:.1f}/sec) ETA: {eta_hours}h{eta_mins}m    ",
                            end="\r"
                        )
                    else:
                        console.print(
                            f"  Markets: {markets_completed}/{total_markets} "
                            f"({markets_per_sec:.1f}/sec) ETA: {eta_mins}m    ",
                            end="\r"
                        )
                    continue

                batch.append(item)
                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(insert_sql, batch)
                    conn.commit()
                    inserted_total += len(batch)
                    batch = []
                queue.task_done()

            return inserted_total

    # start consumer
    consumer_task = asyncio.create_task(consumer(len(markets)))

    # start producers
    producer_tasks = [asyncio.create_task(producer(m)) for m in markets]

    # wait for producers to finish
    await asyncio.gather(*producer_tasks)

    # send sentinel(s) for consumer to finish
    await queue.put(None)

    # wait for consumer to process all items
    await queue.join()
    if not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    total_trades = db.get_trade_count()
    return total_trades


async def main():
    full = "--full" in sys.argv
    # allow overriding months via --months=N
    months = None
    for arg in sys.argv[1:]:
        if arg.startswith("--months="):
            try:
                months = int(arg.split("=", 1)[1])
            except Exception:
                months = None

    if full:
        console.print("[bold yellow]Full re-ingestion mode[/bold yellow]")

    # Disable time filtering - fetch all trades for all markets
    # The aggressive filtering was causing issues, skipping valid markets
    since_ts = None

    db = Database()
    db.initialize_schema()

    async with PolymarketClient() as client:
        console.print("[bold]Phase 1: Ingesting markets from Gamma API...[/bold]")
        market_count = await ingest_markets(client, db, full=full)
        console.print(f"  [green]Markets ingested/updated: {market_count:,}[/green]")

        resolved = len(db.get_resolved_markets())
        console.print(f"  Resolved markets in DB: {resolved:,}")

        console.print("[bold]Phase 2: Ingesting trades from Data API...[/bold]")
        trade_count = await ingest_all_trades(client, db, since_ts=since_ts)
        console.print(f"  [green]New trades ingested: {trade_count:,}[/green]")

        total_trades = db.get_trade_count()
        total_markets = db.get_market_count()
        console.print()
        console.print("[bold green]Ingestion complete![/bold green]")
        console.print(f"  Total markets in DB: {total_markets:,}")
        console.print(f"  Total trades in DB:  {total_trades:,}")


if __name__ == "__main__":
    asyncio.run(main())
