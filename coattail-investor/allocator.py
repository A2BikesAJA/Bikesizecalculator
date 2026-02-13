from __future__ import annotations

"""
Portfolio Allocation Engine for Coattail Investor Tool.

Takes a dollar amount to invest and builds a proportionally-weighted portfolio
from consensus picks, matching each position's size to its consensus score
and the tracked managers' average weighting.
"""

import logging
import math
from dataclasses import dataclass, field

import yfinance as yf

from config import (
    ALLOC_MAX_SINGLE_POSITION_PCT,
    ALLOC_MIN_POSITION_SIZE,
    ALLOC_STRATEGY_WEIGHTS,
)

logger = logging.getLogger(__name__)


def _fetch_current_price(ticker: str) -> float | None:
    """Fetch the current market price for a ticker via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        if price:
            return float(price)
        fast = stock.fast_info
        price = getattr(fast, "last_price", None)
        if price:
            return float(price)
    except Exception as e:
        logger.debug(f"Could not fetch price for {ticker}: {e}")
    return None


# ─── Data Structures ─────────────────────────────────────────────────────────


@dataclass
class Position:
    """A single position in the allocated portfolio."""

    ticker: str
    name: str
    cusip: str
    consensus_score: float
    num_holders: int
    avg_weight: float
    direction: str
    raw_weight_pct: float = 0.0       # weight before capping/normalization
    final_weight_pct: float = 0.0     # weight after constraints applied
    dollar_allocation: float = 0.0    # actual dollars to invest
    share_price: float | None = None
    shares_whole: int = 0             # whole shares to buy
    shares_fractional: float = 0.0    # exact fractional shares
    fractional_ok: bool = False       # whether broker supports fractional
    leftover: float = 0.0            # cash leftover from rounding
    valuation_signal: str = "UNKNOWN"
    holders: list[str] = field(default_factory=list)


@dataclass
class PortfolioAllocation:
    """Complete portfolio allocation result."""

    total_investment: float
    strategy: str
    num_positions: int
    positions: list[Position]
    cash_invested: float = 0.0
    cash_remaining: float = 0.0
    largest_position_pct: float = 0.0
    smallest_position_pct: float = 0.0
    effective_positions: float = 0.0   # 1/HHI concentration measure


# ─── Weighting Strategies ────────────────────────────────────────────────────


def _score_weight(picks: list[dict]) -> list[tuple[dict, float]]:
    """Weight positions proportionally to consensus score."""
    total_score = sum(p["consensus_score"] for p in picks)
    if total_score == 0:
        equal = 100.0 / len(picks) if picks else 0
        return [(p, equal) for p in picks]
    return [(p, p["consensus_score"] / total_score * 100) for p in picks]


def _equal_weight(picks: list[dict]) -> list[tuple[dict, float]]:
    """Weight all positions equally."""
    w = 100.0 / len(picks) if picks else 0
    return [(p, w) for p in picks]


def _holder_weight(picks: list[dict]) -> list[tuple[dict, float]]:
    """Weight proportionally to number of institutional holders."""
    total_holders = sum(p["num_holders"] for p in picks)
    if total_holders == 0:
        return _equal_weight(picks)
    return [(p, p["num_holders"] / total_holders * 100) for p in picks]


def _conviction_weight(picks: list[dict]) -> list[tuple[dict, float]]:
    """
    Hybrid: score * direction_boost * valuation_discount.

    Favours stocks that are highly scored, being added to, and still
    reasonably priced relative to the filing date.
    """
    boosted = []
    for p in picks:
        base = p["consensus_score"]

        # Direction boost
        if p.get("direction") == "Adding":
            base *= 1.25
        elif p.get("direction") == "Reducing":
            base *= 0.75

        # Valuation discount — penalise stocks that have already run up
        val = p.get("valuation") or {}
        signal = val.get("signal", "UNKNOWN")
        if signal == "GREEN":
            base *= 1.10
        elif signal == "YELLOW":
            base *= 0.90
        elif signal == "RED":
            base *= 0.70

        boosted.append((p, base))

    total = sum(b for _, b in boosted)
    if total == 0:
        return _equal_weight(picks)
    return [(p, b / total * 100) for p, b in boosted]


STRATEGY_MAP = {
    "score": _score_weight,
    "equal": _equal_weight,
    "holders": _holder_weight,
    "conviction": _conviction_weight,
}


# ─── Allocation Engine ───────────────────────────────────────────────────────


def allocate_portfolio(
    watchlist: list[dict],
    total_dollars: float,
    strategy: str = "conviction",
    max_positions: int | None = None,
    max_single_pct: float | None = None,
    min_position_dollars: float | None = None,
    fractional_shares: bool = False,
    exclude_red: bool = False,
) -> PortfolioAllocation:
    """
    Build a portfolio allocation from the consensus watchlist.

    Args:
        watchlist:           Ranked consensus picks (from analyzer + valuation).
        total_dollars:       Dollar amount available to invest.
        strategy:            Weighting strategy — "score", "equal", "holders",
                             or "conviction" (default).
        max_positions:       Cap the number of holdings (None = use all picks).
        max_single_pct:      Max weight for any single position (default from config).
        min_position_dollars: Skip positions smaller than this (default from config).
        fractional_shares:   If True, compute fractional share counts;
                             otherwise round down to whole shares.
        exclude_red:         If True, skip stocks with RED valuation signal.

    Returns:
        PortfolioAllocation with fully computed positions.
    """
    if max_single_pct is None:
        max_single_pct = ALLOC_MAX_SINGLE_POSITION_PCT
    if min_position_dollars is None:
        min_position_dollars = ALLOC_MIN_POSITION_SIZE

    # ── Filter picks ─────────────────────────────────────────────────────
    picks = list(watchlist)  # shallow copy
    if exclude_red:
        picks = [
            p for p in picks
            if (p.get("valuation") or {}).get("signal", "UNKNOWN") != "RED"
        ]

    if max_positions and len(picks) > max_positions:
        picks = picks[:max_positions]

    if not picks:
        return PortfolioAllocation(
            total_investment=total_dollars,
            strategy=strategy,
            num_positions=0,
            positions=[],
            cash_remaining=total_dollars,
        )

    # ── Compute raw weights ──────────────────────────────────────────────
    weight_fn = STRATEGY_MAP.get(strategy, _conviction_weight)
    weighted = weight_fn(picks)

    # ── Apply position cap ───────────────────────────────────────────────
    # Iteratively redistribute excess weight from capped positions
    capped = _apply_position_cap(weighted, max_single_pct)

    # ── Convert to Position objects ──────────────────────────────────────
    positions: list[Position] = []
    for pick, weight in capped:
        dollar_alloc = total_dollars * weight / 100.0

        if dollar_alloc < min_position_dollars:
            continue  # skip tiny positions

        val = pick.get("valuation") or {}
        price = val.get("current_price")

        # Fallback: fetch live price if valuation data is missing
        if not price or price <= 0:
            ticker = pick.get("ticker", "")
            if ticker and len(ticker) <= 5 and ticker.isalpha():
                price = _fetch_current_price(ticker)

        if price and price > 0:
            exact_shares = dollar_alloc / price
            if fractional_shares:
                shares_whole = 0
                shares_frac = round(exact_shares, 4)
                actual_cost = shares_frac * price
            else:
                shares_whole = int(exact_shares)
                shares_frac = 0.0
                actual_cost = shares_whole * price
            leftover = dollar_alloc - actual_cost
        else:
            shares_whole = 0
            shares_frac = 0.0
            actual_cost = dollar_alloc
            leftover = 0.0

        pos = Position(
            ticker=pick.get("ticker", "?"),
            name=pick.get("name", "Unknown"),
            cusip=pick.get("cusip", ""),
            consensus_score=pick.get("consensus_score", 0),
            num_holders=pick.get("num_holders", 0),
            avg_weight=pick.get("avg_weight", 0),
            direction=pick.get("direction", "Steady"),
            raw_weight_pct=round(weight, 2),
            final_weight_pct=round(weight, 2),
            dollar_allocation=round(dollar_alloc, 2),
            share_price=price,
            shares_whole=shares_whole,
            shares_fractional=round(shares_frac, 4),
            fractional_ok=fractional_shares,
            leftover=round(leftover, 2),
            valuation_signal=val.get("signal", "UNKNOWN"),
            holders=pick.get("holders", []),
        )
        positions.append(pos)

    # ── Recalculate final weights after min-position filtering ────────────
    if positions:
        total_allocated = sum(p.dollar_allocation for p in positions)
        for p in positions:
            p.final_weight_pct = round(p.dollar_allocation / total_allocated * 100, 2)
    else:
        total_allocated = 0

    cash_invested = sum(
        (p.shares_whole * p.share_price if p.share_price and not p.fractional_ok
         else p.shares_fractional * p.share_price if p.share_price and p.fractional_ok
         else p.dollar_allocation)
        for p in positions
    )
    cash_remaining = total_dollars - cash_invested

    # Concentration measure (effective N = 1 / HHI)
    weights_dec = [p.final_weight_pct / 100 for p in positions]
    hhi = sum(w * w for w in weights_dec)
    effective_n = (1.0 / hhi) if hhi > 0 else 0

    return PortfolioAllocation(
        total_investment=total_dollars,
        strategy=strategy,
        num_positions=len(positions),
        positions=positions,
        cash_invested=round(cash_invested, 2),
        cash_remaining=round(cash_remaining, 2),
        largest_position_pct=max((p.final_weight_pct for p in positions), default=0),
        smallest_position_pct=min((p.final_weight_pct for p in positions), default=0),
        effective_positions=round(effective_n, 1),
    )


def _apply_position_cap(
    weighted: list[tuple[dict, float]], cap_pct: float
) -> list[tuple[dict, float]]:
    """
    Iteratively cap any position that exceeds cap_pct and redistribute
    the excess proportionally to uncapped positions.
    """
    items = [(p, w) for p, w in weighted]
    max_iters = 20  # prevent infinite loop

    for _ in range(max_iters):
        excess = 0.0
        uncapped_total = 0.0
        any_capped = False

        for i, (p, w) in enumerate(items):
            if w > cap_pct:
                excess += w - cap_pct
                items[i] = (p, cap_pct)
                any_capped = True
            else:
                uncapped_total += w

        if not any_capped:
            break

        # Redistribute excess to uncapped positions proportionally
        if uncapped_total > 0:
            for i, (p, w) in enumerate(items):
                if w < cap_pct:
                    bump = excess * (w / uncapped_total)
                    items[i] = (p, w + bump)

    return items


# ─── Rebalancing Helper ─────────────────────────────────────────────────────


def compare_allocations(
    current: PortfolioAllocation, target: PortfolioAllocation
) -> list[dict]:
    """
    Compare a current allocation to a new target and produce trade list.

    Returns a list of trade dicts: ticker, action (BUY/SELL/HOLD),
    share_delta, dollar_delta.
    """
    current_map = {p.ticker: p for p in current.positions}
    target_map = {p.ticker: p for p in target.positions}
    all_tickers = set(current_map) | set(target_map)

    trades = []
    for ticker in sorted(all_tickers):
        cur = current_map.get(ticker)
        tgt = target_map.get(ticker)

        cur_dollars = cur.dollar_allocation if cur else 0
        tgt_dollars = tgt.dollar_allocation if tgt else 0
        delta = tgt_dollars - cur_dollars

        cur_shares = (cur.shares_whole or cur.shares_fractional) if cur else 0
        tgt_shares = (tgt.shares_whole or tgt.shares_fractional) if tgt else 0
        share_delta = tgt_shares - cur_shares

        if abs(delta) < 1.0:
            action = "HOLD"
        elif delta > 0:
            action = "BUY"
        else:
            action = "SELL"

        trades.append({
            "ticker": ticker,
            "name": (tgt or cur).name,
            "action": action,
            "current_dollars": round(cur_dollars, 2),
            "target_dollars": round(tgt_dollars, 2),
            "dollar_delta": round(delta, 2),
            "share_delta": round(share_delta, 4) if isinstance(share_delta, float) else share_delta,
            "current_weight": cur.final_weight_pct if cur else 0,
            "target_weight": tgt.final_weight_pct if tgt else 0,
        })

    trades.sort(key=lambda t: abs(t["dollar_delta"]), reverse=True)
    return trades
