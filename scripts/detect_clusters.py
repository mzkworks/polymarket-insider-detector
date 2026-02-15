"""
Detect sybil clusters — groups of wallets likely controlled by one entity.

Usage:
    python -m scripts.detect_clusters [--min-score N]

Flags:
    --min-score N    Only analyze wallets with insider_score >= N (default: 25)
                     Use 0 to analyze all wallets (slow for large datasets)
"""
from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.table import Table

from src.analysis.cluster_detector import ClusterDetector
from src.data.database import Database

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, default=25.0,
                       help="Only analyze wallets with insider_score >= this value (default: 25)")
    args = parser.parse_args()

    db = Database()
    db.initialize_schema()

    trade_count = db.get_trade_count()
    if trade_count == 0:
        console.print("[yellow]No trades in database. Run ingestion first.[/yellow]")
        return

    console.print(f"[bold]Detecting sybil clusters...[/bold]")
    console.print(f"  Trades: {trade_count:,}")
    if args.min_score > 0:
        console.print(f"  [cyan]Filtering to wallets with score >= {args.min_score}[/cyan]")

    detector = ClusterDetector(db)
    clusters = detector.run(min_score=args.min_score)

    if not clusters:
        console.print("[yellow]No clusters detected yet. Need more trade data.[/yellow]")
        return

    # Print results
    table = Table(title="Detected Sybil Clusters", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Cluster ID", style="cyan", max_width=18)
    table.add_column("Wallets", justify="right")
    table.add_column("Confidence", justify="right", style="bold")
    table.add_column("Combined PnL", justify="right", style="green")
    table.add_column("Same-Side %", justify="right")
    table.add_column("Sample Wallets", max_width=40)

    for i, c in enumerate(clusters, 1):
        wallets_str = ", ".join(
            f"{w[:6]}...{w[-4:]}" for w in c["wallets"][:3]
        )
        if len(c["wallets"]) > 3:
            wallets_str += f" +{len(c['wallets']) - 3} more"

        table.add_row(
            str(i),
            c["cluster_id"],
            str(c["wallet_count"]),
            f"{c['confidence']:.1f}%",
            f"${c['combined_pnl']:,.0f}",
            f"{c['same_side_ratio']:.0%}",
            wallets_str,
        )

    console.print(table)
    console.print(f"\n  Total clusters: {len(clusters)}")


if __name__ == "__main__":
    main()
