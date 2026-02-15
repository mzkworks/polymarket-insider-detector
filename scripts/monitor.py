"""
Start real-time monitoring of flagged wallets with Discord alerts.

Usage:
    python -m scripts.monitor [--min-score N] [--poll-interval N]

Flags:
    --min-score N       Minimum insider score to monitor (default: 25)
    --poll-interval N   Seconds between polls (default: 30)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from rich.console import Console

from src.alerts.discord import DiscordAlerter
from src.alerts.monitor import InsiderMonitor
from src.data.database import Database

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, default=25.0)
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()

    db = Database()
    db.initialize_schema()

    discord = DiscordAlerter()

    monitor = InsiderMonitor(
        db=db,
        discord=discord,
        min_score=args.min_score,
        poll_interval=args.poll_interval,
    )

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, monitor.stop)

    console.print("[bold]Polymarket Insider Monitor[/bold]")
    console.print(f"  Min score: {args.min_score}")
    console.print(f"  Poll interval: {args.poll_interval}s")
    console.print(f"  Discord: {'enabled' if discord.enabled else 'NOT CONFIGURED'}")
    console.print()

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM wallet_scores WHERE insider_score >= ?",
            (args.min_score,),
        ).fetchone()
        console.print(f"  Flagged wallets: {row['cnt']}")

    console.print()
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
