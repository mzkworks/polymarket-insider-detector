"""
Score all wallets and populate the wallet_scores table.

Usage:
    python -m scripts.score [--min-trades N] [--top N]

Flags:
    --min-trades N   Minimum trades to score a wallet (default: 20)
    --top N          Show top N wallets after scoring (default: 25)
"""
from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.table import Table

from src.analysis.wallet_scorer import WalletScorer
from src.data.database import Database

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def print_leaderboard(scores: list[dict], top_n: int = 25) -> None:
    """Print a rich table of the top suspicious wallets."""
    table = Table(title=f"Top {top_n} Suspicious Wallets", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Wallet", style="cyan", max_width=20)
    table.add_column("Score", style="bold red", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("P-Value", justify="right")
    table.add_column("Avg Timing", justify="right")
    table.add_column("Size Corr", justify="right")
    table.add_column("PnL", justify="right", style="green")

    for i, s in enumerate(scores[:top_n], 1):
        wallet = s["wallet_address"]
        short_wallet = f"{wallet[:6]}...{wallet[-4:]}" if len(wallet) > 12 else wallet

        # Format timing as human readable
        timing = s["avg_entry_before_resolution"]
        if timing == float("inf"):
            timing_str = "N/A"
        elif timing < 3600:
            timing_str = f"{timing / 60:.0f}m"
        elif timing < 86400:
            timing_str = f"{timing / 3600:.1f}h"
        else:
            timing_str = f"{timing / 86400:.1f}d"

        # Format p-value in scientific notation
        p_val = s["p_value"]
        if p_val < 0.001:
            p_str = f"{p_val:.2e}"
        else:
            p_str = f"{p_val:.4f}"

        table.add_row(
            str(i),
            short_wallet,
            f"{s['insider_score']:.1f}",
            str(s["total_trades"]),
            f"{s['win_rate']:.1%}",
            p_str,
            timing_str,
            f"{s['size_win_correlation']:.3f}",
            f"${s['total_pnl']:,.0f}",
        )

    console.print(table)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    db = Database()
    db.initialize_schema()

    trade_count = db.get_trade_count()
    if trade_count == 0:
        console.print("[yellow]No trades in database. Run ingestion first:[/yellow]")
        console.print("  python -m scripts.ingest")
        return

    console.print(f"[bold]Scoring wallets (min {args.min_trades} trades)...[/bold]")
    console.print(f"  Trades in DB: {trade_count:,}")

    scorer = WalletScorer(db, min_trades=args.min_trades)

    console.print("  [dim]Querying wallets with GROUP BY... (this may take 1-2 minutes with 207M trades)[/dim]")
    wallets = db.get_all_active_wallets(min_trades=args.min_trades)
    console.print(f"  [green]Eligible wallets: {len(wallets):,}[/green]")

    if not wallets:
        console.print("[yellow]No wallets meet the minimum trade threshold.[/yellow]")
        return

    scores = scorer.score_all_wallets(min_trades=args.min_trades)
    console.print(f"  [green]Scored: {len(scores):,} wallets[/green]")

    scorer.save_scores(scores)
    console.print(f"  [green]Saved to wallet_scores table[/green]")

    # Print leaderboard
    console.print()
    print_leaderboard(scores, top_n=args.top)

    # Summary stats
    if scores:
        console.print()
        high_scores = [s for s in scores if s["insider_score"] >= 50]
        medium_scores = [s for s in scores if 25 <= s["insider_score"] < 50]
        console.print(f"  [red]High suspicion (score >= 50): {len(high_scores)}[/red]")
        console.print(f"  [yellow]Medium suspicion (25-50): {len(medium_scores)}[/yellow]")
        console.print(f"  Total scored: {len(scores)}")


if __name__ == "__main__":
    main()
