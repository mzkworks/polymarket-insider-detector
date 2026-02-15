from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx

from src.data.database import Database

logger = logging.getLogger(__name__)

# Two wallets trading the same market within this window are "temporally correlated"
TEMPORAL_WINDOW_SECONDS = 300  # 5 minutes
# Minimum edge weight (number of co-trades) to keep an edge in the graph
# Increased to 50 to require VERY strong coordination signals
MIN_EDGE_WEIGHT = 50
# Minimum cluster size to report
MIN_CLUSTER_SIZE = 3
# Minimum number of connections a wallet must have to be considered for clustering
# Increased to 15 to only cluster wallets with exceptional coordination
MIN_DEGREE = 15
# Minimum confidence score (0-100) for a cluster to be saved
# Lowered to 35% to capture high-quality clusters while filtering weak ones
MIN_CLUSTER_CONFIDENCE = 35.0


class ClusterDetector:
    """Detect sybil clusters — groups of wallets likely controlled by one entity.

    Signals used:
      1. Temporal correlation: wallets trading the same markets within minutes
      2. Behavioral similarity: similar position sizes and timing patterns
      3. Funding source analysis: shared funding (requires Allium, stubbed)

    Uses networkx graph + Louvain community detection.
    """

    def __init__(self, db: Database):
        self.db = db
        self.graph = nx.Graph()

    def build_temporal_graph(self, min_score: float = 0.0) -> nx.Graph:
        """Build a graph where wallets are nodes and edges represent
        suspicious temporal correlations (trading same market within 5 min).

        Edge weight = number of co-trading events.

        Args:
            min_score: Only analyze wallets with insider_score >= this value (0 = all wallets)
        """
        self.graph = nx.Graph()

        # Get high-risk wallets if min_score is set
        high_risk_wallets = set()
        if min_score > 0:
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT wallet_address FROM wallet_scores WHERE insider_score >= ?",
                    (min_score,)
                ).fetchall()
                high_risk_wallets = {row["wallet_address"] for row in rows}
                logger.info("Filtering to %d wallets with score >= %.1f", len(high_risk_wallets), min_score)

        with self.db.get_connection() as conn:
            # Get all markets that have multiple wallets trading
            markets = conn.execute(
                """SELECT market_id, COUNT(DISTINCT wallet_address) as wallet_count
                   FROM trades
                   GROUP BY market_id
                   HAVING wallet_count >= 2"""
            ).fetchall()

        logger.info("Analyzing %d markets with 2+ wallets", len(markets))

        for idx, market_row in enumerate(markets, 1):
            market_id = market_row["market_id"]
            trades = self.db.get_trades_for_market(market_id)

            # Filter to high-risk wallets if specified
            if min_score > 0:
                trades = [t for t in trades if t["wallet_address"] in high_risk_wallets]
                if len(trades) < 2:
                    continue

            self._find_temporal_pairs(trades)

            # Progress logging every 500 markets
            if idx % 500 == 0 or idx == len(markets):
                logger.info(f"Progress: {idx}/{len(markets)} markets processed ({100*idx/len(markets):.1f}%)")

        # Prune weak edges
        edges_to_remove = [
            (u, v) for u, v, d in self.graph.edges(data=True)
            if d.get("weight", 0) < MIN_EDGE_WEIGHT
        ]
        self.graph.remove_edges_from(edges_to_remove)

        # Remove isolated nodes
        isolates = list(nx.isolates(self.graph))
        self.graph.remove_nodes_from(isolates)

        # Remove nodes with degree < MIN_DEGREE (weakly connected wallets)
        # These wallets don't have enough coordination signals to be considered clustered
        low_degree_nodes = [
            node for node, degree in self.graph.degree()
            if degree < MIN_DEGREE
        ]
        self.graph.remove_nodes_from(low_degree_nodes)
        logger.info(
            "Removed %d wallets with fewer than %d connections",
            len(low_degree_nodes),
            MIN_DEGREE,
        )

        logger.info(
            "Graph: %d nodes, %d edges after pruning",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )
        return self.graph

    def _find_temporal_pairs(self, trades: list[dict]) -> None:
        """Find pairs of wallets trading within TEMPORAL_WINDOW_SECONDS."""
        # Sort by timestamp
        sorted_trades = sorted(trades, key=lambda t: t["timestamp"])

        for i, t1 in enumerate(sorted_trades):
            for j in range(i + 1, len(sorted_trades)):
                t2 = sorted_trades[j]
                delta = t2["timestamp"] - t1["timestamp"]

                if delta > TEMPORAL_WINDOW_SECONDS:
                    break  # No more trades within window

                w1 = t1["wallet_address"]
                w2 = t2["wallet_address"]

                if w1 == w2:
                    continue

                # Same market, same direction = suspicious coordination
                same_side = t1["outcome_index"] == t2["outcome_index"]

                if self.graph.has_edge(w1, w2):
                    self.graph[w1][w2]["weight"] += 1
                    if same_side:
                        self.graph[w1][w2]["same_side_count"] += 1
                    self.graph[w1][w2]["markets"].add(t1["market_id"])
                else:
                    self.graph.add_edge(
                        w1, w2,
                        weight=1,
                        same_side_count=1 if same_side else 0,
                        markets={t1["market_id"]},
                    )

    def _add_behavioral_similarity(self) -> None:
        """Boost edge weights for wallets with similar trading behavior."""
        with self.db.get_connection() as conn:
            for u, v in list(self.graph.edges()):
                # Compare average trade sizes
                u_stats = conn.execute(
                    "SELECT AVG(size) as avg_size, AVG(price) as avg_price FROM trades WHERE wallet_address = ?",
                    (u,),
                ).fetchone()
                v_stats = conn.execute(
                    "SELECT AVG(size) as avg_size, AVG(price) as avg_price FROM trades WHERE wallet_address = ?",
                    (v,),
                ).fetchone()

                if u_stats and v_stats and u_stats["avg_size"] and v_stats["avg_size"]:
                    # Size similarity: ratio of smaller to larger (1.0 = identical)
                    size_ratio = min(u_stats["avg_size"], v_stats["avg_size"]) / max(
                        u_stats["avg_size"], v_stats["avg_size"]
                    )
                    if size_ratio > 0.7:  # Similar sizing
                        self.graph[u][v]["weight"] += 2
                        self.graph[u][v]["size_similarity"] = round(size_ratio, 3)

    def detect_communities(self) -> list[dict]:
        """Run Louvain community detection on the graph.

        Returns list of cluster dicts ready for DB insertion.
        """
        if self.graph.number_of_nodes() == 0:
            logger.info("No nodes in graph — no clusters to detect")
            return []

        # Add behavioral similarity before community detection
        # DISABLED: Too slow for large graphs (requires DB query per edge)
        # self._add_behavioral_similarity()

        # Louvain community detection
        communities = nx.community.louvain_communities(
            self.graph, weight="weight", resolution=1.0, seed=42
        )

        clusters = []
        for community in communities:
            if len(community) < MIN_CLUSTER_SIZE:
                continue

            cluster_id = f"cluster_{uuid.uuid4().hex[:8]}"
            wallets = list(community)

            # Calculate cluster-level stats
            subgraph = self.graph.subgraph(wallets)
            total_edge_weight = sum(
                d.get("weight", 0) for _, _, d in subgraph.edges(data=True)
            )
            same_side_total = sum(
                d.get("same_side_count", 0) for _, _, d in subgraph.edges(data=True)
            )

            # Get combined PnL from wallet_scores
            combined_pnl = 0.0
            with self.db.get_connection() as conn:
                for w in wallets:
                    row = conn.execute(
                        "SELECT total_pnl FROM wallet_scores WHERE wallet_address = ?",
                        (w,),
                    ).fetchone()
                    if row and row["total_pnl"]:
                        combined_pnl += row["total_pnl"]

            # Confidence based on edge density and same-side trading
            max_edges = len(wallets) * (len(wallets) - 1) / 2
            edge_density = subgraph.number_of_edges() / max_edges if max_edges > 0 else 0
            same_side_ratio = same_side_total / total_edge_weight if total_edge_weight > 0 else 0
            confidence = round(min((edge_density * 0.5 + same_side_ratio * 0.5) * 100, 100), 2)

            # Skip low-confidence clusters (likely coincidental co-trading, not coordination)
            if confidence < MIN_CLUSTER_CONFIDENCE:
                logger.debug(
                    "Skipping cluster with %d wallets (confidence %.1f%% < %.1f%%)",
                    len(wallets), confidence, MIN_CLUSTER_CONFIDENCE
                )
                continue

            cluster = {
                "cluster_id": cluster_id,
                "wallet_count": len(wallets),
                "combined_pnl": round(combined_pnl, 2),
                "shared_funding_source": None,  # Requires Allium
                "confidence": confidence,
                "wallets": wallets,  # Not stored in clusters table, used for reporting
                "edge_weight": total_edge_weight,
                "same_side_ratio": round(same_side_ratio, 3),
            }
            clusters.append(cluster)

        clusters.sort(key=lambda c: c["confidence"], reverse=True)
        logger.info("Detected %d clusters", len(clusters))
        return clusters

    def save_clusters(self, clusters: list[dict]) -> None:
        """Save clusters to DB and update wallet_scores with cluster_id."""
        with self.db.get_connection() as conn:
            # Clear existing cluster data
            conn.execute("DELETE FROM clusters")
            conn.execute("UPDATE wallet_scores SET cluster_id = NULL")

            for cluster in clusters:
                conn.execute(
                    """INSERT OR REPLACE INTO clusters
                       (cluster_id, wallet_count, combined_pnl, shared_funding_source, confidence)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        cluster["cluster_id"],
                        cluster["wallet_count"],
                        cluster["combined_pnl"],
                        cluster["shared_funding_source"],
                        cluster["confidence"],
                    ),
                )
                # Update wallet_scores with cluster assignment
                for wallet in cluster["wallets"]:
                    conn.execute(
                        "UPDATE wallet_scores SET cluster_id = ? WHERE wallet_address = ?",
                        (cluster["cluster_id"], wallet),
                    )
            conn.commit()
        logger.info("Saved %d clusters to database", len(clusters))

    def run(self, min_score: float = 0.0) -> list[dict]:
        """Full pipeline: build graph → detect communities → save.

        Args:
            min_score: Only analyze wallets with insider_score >= this value (0 = all wallets)
        """
        self.build_temporal_graph(min_score=min_score)
        clusters = self.detect_communities()
        if clusters:
            self.save_clusters(clusters)
        return clusters
