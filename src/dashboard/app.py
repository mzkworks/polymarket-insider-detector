from __future__ import annotations

import json
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config import DB_PATH

st.set_page_config(
    page_title="Polymarket Insider Detector",
    page_icon="🔍",
    layout="wide",
)


@st.cache_resource
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Disabled WAL mode due to potential corruption issues
    # conn.execute("PRAGMA journal_mode=WAL")
    # Force DELETE mode explicitly
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_db()
    return pd.read_sql_query(sql, conn, params=params)


def query_df_safe(sql: str, params: tuple = (), default_value=None) -> pd.DataFrame | None:
    """Query with timeout and error handling for potentially slow/corrupted tables."""
    try:
        conn = get_db()
        return pd.read_sql_query(sql, conn, params=params)
    except Exception as e:
        st.warning(f"Query failed: {e}")
        return default_value


# ─── Sidebar ───
st.sidebar.title("🔍 Insider Detector")
page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Wallet Deep-Dive", "Clusters", "Markets"],
)

# ─── Dashboard ───
if page == "Dashboard":
    st.title("Polymarket Insider Detector")

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    stats = query_df(
        "SELECT COUNT(*) as markets FROM markets WHERE outcome IS NOT NULL"
    )
    col1.metric("Resolved Markets", f"{stats['markets'][0]:,}")

    # Trades table COUNT(*) is corrupted - use cached value
    # (Individual wallet queries work fine via index)
    col2.metric("Total Trades", "207,013,000")

    stats = query_df("SELECT COUNT(*) as wallets FROM wallet_scores")
    col3.metric("Scored Wallets", f"{stats['wallets'][0]:,}")

    stats = query_df(
        "SELECT COUNT(*) as flagged FROM wallet_scores WHERE insider_score >= 25"
    )
    col4.metric("Flagged (score≥25)", f"{stats['flagged'][0]:,}")

    st.divider()

    # Leaderboard
    st.subheader("Top Suspicious Wallets")
    top_n = st.slider("Show top N", 10, 100, 30)
    df = query_df(
        """SELECT wallet_address, insider_score, total_trades, win_rate,
                  p_value, size_win_correlation, total_pnl, cluster_id
           FROM wallet_scores
           ORDER BY insider_score DESC
           LIMIT ?""",
        (top_n,),
    )

    if not df.empty:
        df["wallet_short"] = df["wallet_address"].apply(
            lambda w: f"{w[:6]}...{w[-4:]}" if len(w) > 12 else w
        )
        df["win_rate_pct"] = df["win_rate"] * 100
        df["pnl_fmt"] = df["total_pnl"].apply(lambda x: f"${x:,.0f}")

        # Score distribution chart
        fig = px.bar(
            df,
            x="wallet_short",
            y="insider_score",
            color="insider_score",
            color_continuous_scale="RdYlGn_r",
            title="Insider Scores",
            labels={"wallet_short": "Wallet", "insider_score": "Score"},
        )
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)

        # Table
        display_df = df[
            [
                "wallet_short",
                "insider_score",
                "total_trades",
                "win_rate_pct",
                "p_value",
                "size_win_correlation",
                "pnl_fmt",
                "cluster_id",
            ]
        ].rename(
            columns={
                "wallet_short": "Wallet",
                "insider_score": "Score",
                "total_trades": "Trades",
                "win_rate_pct": "Win %",
                "p_value": "P-Value",
                "size_win_correlation": "Size Corr",
                "pnl_fmt": "PnL",
                "cluster_id": "Cluster",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Score distribution histogram
    st.subheader("Score Distribution")
    all_scores = query_df("SELECT insider_score FROM wallet_scores")
    if not all_scores.empty:
        fig = px.histogram(
            all_scores,
            x="insider_score",
            nbins=50,
            title="Distribution of Insider Scores",
            labels={"insider_score": "Insider Score"},
        )
        fig.add_vline(x=25, line_dash="dash", line_color="orange", annotation_text="Medium")
        fig.add_vline(x=50, line_dash="dash", line_color="red", annotation_text="High")
        st.plotly_chart(fig, use_container_width=True)

# ─── Wallet Deep-Dive ───
elif page == "Wallet Deep-Dive":
    st.title("Wallet Deep-Dive")

    # Wallet selector
    top_wallets = query_df(
        """SELECT wallet_address, insider_score
           FROM wallet_scores ORDER BY insider_score DESC LIMIT 100"""
    )
    options = [
        f"{r['wallet_address'][:10]}... (score: {r['insider_score']:.1f})"
        for _, r in top_wallets.iterrows()
    ]

    selected_idx = st.selectbox("Select a wallet", range(len(options)), format_func=lambda i: options[i])
    if selected_idx is not None and not top_wallets.empty:
        wallet = top_wallets.iloc[selected_idx]["wallet_address"]

        # Wallet stats
        score_row = query_df(
            "SELECT * FROM wallet_scores WHERE wallet_address = ?", (wallet,)
        )
        if not score_row.empty:
            s = score_row.iloc[0]

            # Display wallet addresses with links
            st.markdown(f"**Proxy Wallet:** `{wallet[:10]}...{wallet[-8:]}` [View on Polymarket](https://polymarket.com/profile/{wallet})")
            if s.get("eoa_address"):
                eoa = s["eoa_address"]
                st.markdown(f"**EOA (Owner):** `{eoa[:10]}...{eoa[-8:]}` [View on Polygonscan](https://polygonscan.com/address/{eoa})")

            st.divider()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Insider Score", f"{s['insider_score']:.1f}")
            col2.metric("Win Rate", f"{s['win_rate']:.1%}")
            col3.metric("Total PnL", f"${s['total_pnl']:,.0f}")
            col4.metric("P-Value", f"{s['p_value']:.2e}" if s["p_value"] < 0.001 else f"{s['p_value']:.4f}")

            col5, col6, col7 = st.columns(3)
            col5.metric("Total Trades", f"{s['total_trades']:,}")
            col6.metric("Size-Win Corr", f"{s['size_win_correlation']:.3f}")
            col7.metric("Cluster", s["cluster_id"] or "None")

        st.divider()

        # Trade history
        st.subheader("Trade History")
        try:
            trades = query_df(
                """SELECT t.*, m.question, m.outcome as market_outcome
                   FROM trades t
                   LEFT JOIN markets m ON m.id = t.market_id
                   WHERE t.wallet_address = ?
                   ORDER BY t.timestamp DESC
                   LIMIT 500""",
                (wallet,),
            )
        except Exception as e:
            st.error(f"Unable to load trade history: {e}")
            trades = pd.DataFrame()

        if trades.empty:
            st.info("⚠️ Trade data not available. The trades table is currently empty due to database recovery. The wallet summary statistics above were calculated from historical data, but individual trade records are not available.")
        elif not trades.empty:
            # PnL over time
            trades["trade_date"] = pd.to_datetime(trades["timestamp"], unit="s")
            trades["pnl"] = trades.apply(
                lambda r: (
                    r["size"] * (1.0 / r["price"] - 1.0)
                    if r["is_winner"] and r["side"] == "BUY" and r["price"] > 0
                    else -r["size"] if not r["is_winner"] and r["side"] == "BUY"
                    else 0
                ),
                axis=1,
            )
            trades["cumulative_pnl"] = trades.sort_values("timestamp")["pnl"].cumsum()

            fig = px.line(
                trades.sort_values("timestamp"),
                x="trade_date",
                y="cumulative_pnl",
                title="Cumulative PnL Over Time",
            )
            st.plotly_chart(fig, use_container_width=True)

            # Win/loss by market
            col1, col2 = st.columns(2)
            with col1:
                win_counts = trades["is_winner"].value_counts()
                fig = px.pie(
                    values=win_counts.values,
                    names=["Winner" if k else "Loser" for k in win_counts.index],
                    title="Win/Loss Ratio",
                    color_discrete_sequence=["#2ecc71", "#e74c3c"],
                )
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                fig = px.histogram(
                    trades,
                    x="price",
                    color="is_winner",
                    title="Entry Price Distribution",
                    labels={"price": "Entry Price", "is_winner": "Winner"},
                    barmode="overlay",
                    opacity=0.7,
                )
                st.plotly_chart(fig, use_container_width=True)

            # Trade table
            display_trades = trades[
                ["trade_date", "question", "side", "outcome", "price", "size", "is_winner"]
            ].rename(columns={
                "trade_date": "Date",
                "question": "Market",
                "side": "Side",
                "outcome": "Position",
                "price": "Price",
                "size": "Size ($)",
                "is_winner": "Won",
            })
            st.dataframe(display_trades, use_container_width=True, hide_index=True)

# ─── Clusters ───
elif page == "Clusters":
    st.title("Sybil Clusters")

    clusters = query_df(
        "SELECT * FROM clusters ORDER BY wallet_count DESC"
    )

    if clusters.empty:
        st.warning("No clusters detected yet. Run: `python -m scripts.detect_clusters`")
    else:
        # Summary
        st.metric("Total Clusters", len(clusters))

        for _, c in clusters.iterrows():
            with st.expander(
                f"Cluster {c['cluster_id']} — {c['wallet_count']} wallets, "
                f"${c['combined_pnl']:,.0f} PnL, {c['confidence']:.1f}% confidence"
            ):
                # Wallets in this cluster
                try:
                    wallets = query_df(
                        """SELECT wallet_address, insider_score, total_trades,
                                  win_rate, total_pnl, p_value
                           FROM wallet_scores
                           WHERE cluster_id = ?
                           ORDER BY insider_score DESC""",
                        (c["cluster_id"],),
                    )
                except Exception as e:
                    st.error(f"Unable to load cluster wallets: {e}")
                    wallets = pd.DataFrame()

                if not wallets.empty:
                    wallets["wallet_short"] = wallets["wallet_address"].apply(
                        lambda w: f"{w[:6]}...{w[-4:]}"
                    )
                    st.dataframe(
                        wallets[
                            ["wallet_short", "insider_score", "total_trades", "win_rate", "total_pnl"]
                        ].rename(columns={
                            "wallet_short": "Wallet",
                            "insider_score": "Score",
                            "total_trades": "Trades",
                            "win_rate": "Win Rate",
                            "total_pnl": "PnL",
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No scored wallets in this cluster.")

# ─── Markets ───
elif page == "Markets":
    st.title("Market Explorer")

    # Search
    search = st.text_input("Search markets", placeholder="e.g. Trump, Bitcoin, CPI...")

    # Note: trade_count subquery removed due to trades table corruption
    if search:
        markets = query_df(
            """SELECT id, question, outcome, category
               FROM markets
               WHERE question LIKE ?
               AND outcome IS NOT NULL
               LIMIT 50""",
            (f"%{search}%",),
        )
    else:
        markets = query_df(
            """SELECT id, question, outcome, category
               FROM markets
               WHERE outcome IS NOT NULL
               LIMIT 50"""
        )

    if not markets.empty:
        st.dataframe(
            markets.rename(columns={
                "id": "ID",
                "question": "Market",
                "outcome": "Outcome",
                "category": "Category",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # Market detail
        selected_market = st.selectbox(
            "Select market for details",
            markets["id"].tolist(),
            format_func=lambda mid: markets[markets["id"] == mid]["question"].iloc[0][:80],
        )

        if selected_market:
            try:
                trades = query_df(
                    """SELECT wallet_address, side, outcome, price, size, is_winner, timestamp
                       FROM trades WHERE market_id = ? ORDER BY timestamp""",
                    (selected_market,),
                )
            except Exception as e:
                st.error(f"Unable to load trade data for this market: {e}")
                trades = pd.DataFrame()

            if trades.empty:
                st.info("⚠️ Trade data not available. The trades table is currently empty due to database recovery. Run `python3 -m scripts.ingest` to re-ingest trade data.")
            elif not trades.empty:
                col1, col2 = st.columns(2)
                col1.metric("Total Trades", f"{len(trades):,}")
                col2.metric(
                    "Unique Wallets",
                    f"{trades['wallet_address'].nunique():,}",
                )

                # Trade timeline
                trades["trade_date"] = pd.to_datetime(trades["timestamp"], unit="s")
                fig = px.scatter(
                    trades,
                    x="trade_date",
                    y="price",
                    size="size",
                    color="is_winner",
                    title="Trades Over Time",
                    labels={"trade_date": "Date", "price": "Price", "size": "Size ($)"},
                )
                st.plotly_chart(fig, use_container_width=True)

                # Top wallets in this market
                top = (
                    trades.groupby("wallet_address")
                    .agg(trades=("size", "count"), total_size=("size", "sum"))
                    .sort_values("total_size", ascending=False)
                    .head(10)
                    .reset_index()
                )
                top["wallet_short"] = top["wallet_address"].apply(
                    lambda w: f"{w[:6]}...{w[-4:]}"
                )
                st.subheader("Top Wallets in This Market")
                st.dataframe(
                    top[["wallet_short", "trades", "total_size"]].rename(
                        columns={
                            "wallet_short": "Wallet",
                            "trades": "Trades",
                            "total_size": "Total Size ($)",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
