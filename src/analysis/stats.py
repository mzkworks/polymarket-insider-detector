from __future__ import annotations

import math

import numpy as np
from scipy import stats


def binomial_p_value(wins: int, total: int, avg_market_prob: float) -> float:
    """Calculate the p-value for a wallet's win rate using a binomial test.

    If a wallet bought "Yes" tokens at an average implied probability of avg_market_prob,
    what's the probability of winning at least `wins` out of `total` trades by chance?

    A low p-value (e.g. < 0.001) means the win rate is statistically unlikely to be luck.

    Args:
        wins: Number of winning trades.
        total: Total number of resolved trades.
        avg_market_prob: Average implied probability at entry (the price they paid).

    Returns:
        p-value (0 to 1). Lower = more suspicious.
    """
    if total == 0 or avg_market_prob <= 0 or avg_market_prob >= 1:
        return 1.0
    # One-sided test: probability of getting >= this many wins by chance
    result = stats.binomtest(wins, total, avg_market_prob, alternative="greater")
    return float(result.pvalue)


def size_win_correlation(sizes: list[float], wins: list[bool]) -> float:
    """Calculate Pearson correlation between trade sizes and win outcomes.

    A positive correlation means the wallet bets bigger when they win —
    a strong insider signal.

    Args:
        sizes: List of trade sizes (USDC amounts).
        wins: List of boolean win outcomes, same length as sizes.

    Returns:
        Correlation coefficient (-1 to 1). Higher = more suspicious.
        Returns 0.0 if insufficient data or no variance.
    """
    if len(sizes) < 3 or len(sizes) != len(wins):
        return 0.0
    win_floats = [1.0 if w else 0.0 for w in wins]
    # Check for zero variance (all same size or all wins/losses)
    if np.std(sizes) == 0 or np.std(win_floats) == 0:
        return 0.0
    corr, _ = stats.pearsonr(sizes, win_floats)
    return float(corr) if not math.isnan(corr) else 0.0


def compute_pnl(price: float, size: float, is_winner: bool, side: str) -> float:
    """Compute profit/loss for a single trade.

    For a BUY:
      - Winner: payout is size/price (number of shares * $1) - size (cost) = size * (1/price - 1)
      - Loser: lose the entire cost = -size

    For a SELL:
      - Winner: received size upfront, don't owe payout = +size
      - Loser: received size but owe payout = -(payout - size)

    Simplified: we treat all trades as directional bets on the outcome.
    """
    if side == "BUY":
        if is_winner:
            # Bought shares at `price`, each pays $1. Shares = size / price.
            return size * (1.0 / price - 1.0) if price > 0 else 0.0
        else:
            return -size
    else:  # SELL
        if is_winner:
            # Sold shares — counterparty loses. Profit = size * (1 - price) / price
            return size
        else:
            return -size * (1.0 / price - 1.0) if price > 0 else 0.0


def timing_score(entry_timestamp: int, resolution_timestamp: int) -> float:
    """Calculate seconds between trade entry and market resolution.

    Lower = more suspicious (trading right before resolution).

    Args:
        entry_timestamp: Unix timestamp of the trade.
        resolution_timestamp: Unix timestamp of market resolution.

    Returns:
        Seconds before resolution. Negative means traded after resolution.
    """
    return float(resolution_timestamp - entry_timestamp)


def composite_insider_score(
    win_rate: float,
    p_value: float,
    timing_avg: float,
    size_corr: float,
    total_pnl: float,
    total_trades: int,
) -> float:
    """Compute a composite insider score from 0-100.

    Weights:
      - p_value significance: 40% (most important — statistical anomaly)
      - timing: 25% (trading close to resolution)
      - size-win correlation: 20% (betting bigger on winners)
      - win rate bonus: 10% (raw win rate above 70%)
      - volume bonus: 5% (more trades = more confidence)

    Returns:
        Score from 0 to 100. Higher = more suspicious.
    """
    score = 0.0

    # P-value component (0-40 points)
    # Transform p-value to a score: lower p-value = higher score
    if p_value > 0:
        # -log10(p_value): p=0.05 -> 1.3, p=0.001 -> 3, p=0.000001 -> 6
        log_p = -math.log10(max(p_value, 1e-30))
        # Scale: 2+ is interesting, 6+ is very suspicious, cap at 15
        p_score = min(log_p / 15.0, 1.0) * 40.0
        score += p_score

    # Timing component (0-25 points)
    # Average entry 1 hour before resolution = max score
    if timing_avg > 0:
        hours_before = timing_avg / 3600.0
        if hours_before < 1:
            score += 25.0
        elif hours_before < 6:
            score += 25.0 * (1.0 - (hours_before - 1) / 5.0)
        elif hours_before < 24:
            score += 10.0 * (1.0 - (hours_before - 6) / 18.0)
        # > 24 hours = no timing bonus

    # Size-win correlation (0-20 points)
    if size_corr > 0:
        score += min(size_corr, 1.0) * 20.0

    # Win rate bonus (0-10 points, only above 70%)
    if win_rate > 0.7:
        score += min((win_rate - 0.7) / 0.3, 1.0) * 10.0

    # Volume bonus (0-5 points, scaled by trade count)
    if total_trades >= 20:
        score += min((total_trades - 20) / 80.0, 1.0) * 5.0

    return round(min(score, 100.0), 2)
