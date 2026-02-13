from __future__ import annotations

"""
Purchase Timing Engine.

Combines technical indicators, fundamental analysis, news sentiment,
and consensus data to produce actionable purchase recommendations:
  - WHEN to buy (timing zone)
  - At WHAT PRICE (target entry price / buy zone)
  - Based on the investor's TIME HORIZON (short / medium / long)

Generates price targets, support/resistance levels, and risk-adjusted
entry recommendations.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)


# ─── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class PriceLevel:
    """A notable price level (support or resistance)."""

    price: float
    level_type: str  # "support" or "resistance"
    source: str  # e.g. "SMA200", "52w_low", "BB_lower"
    strength: str = "MODERATE"  # STRONG / MODERATE / WEAK


@dataclass
class BuyZone:
    """Target buy zone for a stock."""

    ideal_entry: float  # Best entry price
    buy_below: float  # Buy at or below this price
    strong_buy_below: float  # Aggressive accumulation zone
    stop_loss: float  # Suggested stop loss level
    risk_reward_ratio: float = 0.0  # Ratio of upside to downside


@dataclass
class HorizonRecommendation:
    """Recommendation for a specific investment time horizon."""

    horizon: str  # "short" (1-3mo), "medium" (3-12mo), "long" (1-5yr)
    horizon_label: str  # Human-readable label
    action: str  # "BUY NOW", "WAIT FOR DIP", "ACCUMULATE", "AVOID", "HOLD"
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    target_price: float  # Expected price at end of horizon
    expected_return_pct: float  # Expected return %
    entry_strategy: str  # How to enter the position
    rationale: list[str] = field(default_factory=list)


@dataclass
class PurchaseRecommendation:
    """Complete purchase timing recommendation for a stock."""

    ticker: str = ""
    name: str = ""
    current_price: float = 0.0
    as_of: str = ""  # Date of analysis

    # Overall signal
    overall_action: str = "HOLD"  # BUY NOW / ACCUMULATE / WAIT / AVOID
    overall_confidence: str = "MEDIUM"
    summary: str = ""

    # Price levels
    support_levels: list[PriceLevel] = field(default_factory=list)
    resistance_levels: list[PriceLevel] = field(default_factory=list)

    # Buy zone
    buy_zone: BuyZone | None = None

    # Horizon-specific recommendations
    short_term: HorizonRecommendation | None = None
    medium_term: HorizonRecommendation | None = None
    long_term: HorizonRecommendation | None = None

    # Input scores (from other modules)
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    news_score: float = 0.0
    consensus_score: float = 0.0

    # Key considerations
    bull_case: list[str] = field(default_factory=list)
    bear_case: list[str] = field(default_factory=list)

    error: str | None = None


# ─── Core Engine ──────────────────────────────────────────────────────────────


def generate_purchase_recommendation(
    ticker: str,
    name: str = "",
    technical_score: float = 0.0,
    fundamental_score: float = 0.0,
    news_score: float = 0.0,
    consensus_score: float = 0.0,
    num_holders: int = 0,
    direction: str = "Steady",
) -> PurchaseRecommendation:
    """
    Generate a complete purchase timing recommendation for a stock.
    """
    rec = PurchaseRecommendation(
        ticker=ticker,
        name=name,
        as_of=datetime.now().strftime("%Y-%m-%d"),
        technical_score=technical_score,
        fundamental_score=fundamental_score,
        news_score=news_score,
        consensus_score=consensus_score,
    )

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")

        if hist.empty or len(hist) < 30:
            rec.error = "Insufficient price history"
            return rec

        close = hist["Close"].values
        rec.current_price = float(close[-1])

        # Compute price levels
        rec.support_levels = _find_support_levels(close, rec.current_price)
        rec.resistance_levels = _find_resistance_levels(close, rec.current_price)

        # Compute buy zone
        rec.buy_zone = _compute_buy_zone(
            close, rec.current_price, rec.support_levels
        )

        # Generate horizon recommendations
        rec.short_term = _short_term_recommendation(
            ticker, close, rec.current_price,
            technical_score, fundamental_score, news_score, consensus_score,
            direction,
        )
        rec.medium_term = _medium_term_recommendation(
            ticker, close, rec.current_price,
            technical_score, fundamental_score, news_score, consensus_score,
            num_holders, direction,
        )
        rec.long_term = _long_term_recommendation(
            ticker, close, rec.current_price,
            technical_score, fundamental_score, news_score, consensus_score,
            num_holders, direction,
        )

        # Overall action
        rec.overall_action = _determine_overall_action(rec)
        rec.overall_confidence = _determine_confidence(rec)

        # Bull / bear cases
        rec.bull_case = _build_bull_case(
            rec, technical_score, fundamental_score, news_score,
            consensus_score, num_holders, direction,
        )
        rec.bear_case = _build_bear_case(
            rec, technical_score, fundamental_score, news_score,
            consensus_score, direction,
        )

        # Summary
        rec.summary = _generate_summary(rec)

    except Exception as e:
        logger.error(f"Purchase recommendation failed for {ticker}: {e}")
        rec.error = str(e)

    return rec


# ─── Support / Resistance ────────────────────────────────────────────────────


def _find_support_levels(
    close: np.ndarray, current_price: float
) -> list[PriceLevel]:
    """Identify key support levels below the current price."""
    levels = []

    # SMA 50
    if len(close) >= 50:
        sma50 = float(np.mean(close[-50:]))
        if sma50 < current_price:
            pct_below = (current_price - sma50) / current_price * 100
            strength = "STRONG" if pct_below < 10 else "MODERATE"
            levels.append(PriceLevel(
                price=round(sma50, 2), level_type="support",
                source="SMA 50", strength=strength,
            ))

    # SMA 200
    if len(close) >= 200:
        sma200 = float(np.mean(close[-200:]))
        if sma200 < current_price:
            levels.append(PriceLevel(
                price=round(sma200, 2), level_type="support",
                source="SMA 200", strength="STRONG",
            ))

    # Bollinger lower band
    if len(close) >= 20:
        sma20 = float(np.mean(close[-20:]))
        std20 = float(np.std(close[-20:]))
        bb_lower = sma20 - 2 * std20
        if bb_lower < current_price:
            levels.append(PriceLevel(
                price=round(bb_lower, 2), level_type="support",
                source="Bollinger Lower", strength="MODERATE",
            ))

    # 52-week low
    low_52w = float(np.min(close))
    if low_52w < current_price:
        levels.append(PriceLevel(
            price=round(low_52w, 2), level_type="support",
            source="52-Week Low", strength="STRONG",
        ))

    # Recent swing lows (local minima in last 60 days)
    recent = close[-60:] if len(close) >= 60 else close
    for i in range(2, len(recent) - 2):
        if (recent[i] < recent[i-1] and recent[i] < recent[i-2] and
                recent[i] < recent[i+1] and recent[i] < recent[i+2]):
            price = float(recent[i])
            if price < current_price * 0.98:  # at least 2% below
                levels.append(PriceLevel(
                    price=round(price, 2), level_type="support",
                    source="Swing Low", strength="WEAK",
                ))

    # Sort by price descending (nearest support first)
    levels.sort(key=lambda x: x.price, reverse=True)
    return levels[:6]


def _find_resistance_levels(
    close: np.ndarray, current_price: float
) -> list[PriceLevel]:
    """Identify key resistance levels above the current price."""
    levels = []

    # SMA 50 if above price
    if len(close) >= 50:
        sma50 = float(np.mean(close[-50:]))
        if sma50 > current_price:
            levels.append(PriceLevel(
                price=round(sma50, 2), level_type="resistance",
                source="SMA 50", strength="MODERATE",
            ))

    # SMA 200 if above price
    if len(close) >= 200:
        sma200 = float(np.mean(close[-200:]))
        if sma200 > current_price:
            levels.append(PriceLevel(
                price=round(sma200, 2), level_type="resistance",
                source="SMA 200", strength="STRONG",
            ))

    # Bollinger upper band
    if len(close) >= 20:
        sma20 = float(np.mean(close[-20:]))
        std20 = float(np.std(close[-20:]))
        bb_upper = sma20 + 2 * std20
        if bb_upper > current_price:
            levels.append(PriceLevel(
                price=round(bb_upper, 2), level_type="resistance",
                source="Bollinger Upper", strength="MODERATE",
            ))

    # 52-week high
    high_52w = float(np.max(close))
    if high_52w > current_price * 1.02:
        levels.append(PriceLevel(
            price=round(high_52w, 2), level_type="resistance",
            source="52-Week High", strength="STRONG",
        ))

    levels.sort(key=lambda x: x.price)
    return levels[:5]


# ─── Buy Zone Computation ────────────────────────────────────────────────────


def _compute_buy_zone(
    close: np.ndarray,
    current_price: float,
    support_levels: list[PriceLevel],
) -> BuyZone:
    """Compute the ideal buy zone based on support levels and volatility."""
    # Average true range as proxy for volatility
    if len(close) >= 15:
        daily_changes = np.abs(np.diff(close[-15:]))
        avg_daily_move = float(np.mean(daily_changes))
    else:
        avg_daily_move = current_price * 0.015  # default 1.5%

    # Nearest strong support
    strong_supports = [s.price for s in support_levels if s.strength == "STRONG"]
    nearest_support = strong_supports[0] if strong_supports else current_price * 0.92

    # Buy below: current price minus ~1 ATR
    buy_below = round(current_price - avg_daily_move * 2, 2)

    # Strong buy: near support level
    strong_buy = round(
        min(nearest_support * 1.02, current_price * 0.95), 2
    )

    # Ideal entry: between current and buy_below
    ideal_entry = round((current_price + buy_below) / 2, 2)

    # Stop loss: below nearest support
    stop_loss = round(nearest_support * 0.97, 2)

    # Risk/reward: assume upside target = distance from support to resistance
    upside = current_price * 1.15 - ideal_entry  # 15% target
    downside = ideal_entry - stop_loss
    rr = round(upside / downside, 2) if downside > 0 else 0

    return BuyZone(
        ideal_entry=ideal_entry,
        buy_below=buy_below,
        strong_buy_below=strong_buy,
        stop_loss=stop_loss,
        risk_reward_ratio=rr,
    )


# ─── Horizon Recommendations ────────────────────────────────────────────────


def _short_term_recommendation(
    ticker: str,
    close: np.ndarray,
    current_price: float,
    tech_score: float,
    fund_score: float,
    news_score: float,
    consensus_score: float,
    direction: str,
) -> HorizonRecommendation:
    """1-3 month recommendation -- heavily weighted toward technicals & news."""
    # Short-term: 50% technical, 30% news, 10% fundamental, 10% consensus
    composite = (
        tech_score * 0.50 +
        news_score * 0.30 +
        fund_score * 0.10 +
        min(consensus_score / 5, 20) * 0.10  # normalize consensus
    )

    # Recent momentum (20-day return)
    if len(close) >= 20:
        momentum_20d = (close[-1] - close[-20]) / close[-20] * 100
    else:
        momentum_20d = 0

    # Volatility
    if len(close) >= 20:
        daily_returns = np.diff(close[-21:]) / close[-21:-1]
        vol = float(np.std(daily_returns) * np.sqrt(252) * 100)
    else:
        vol = 25  # default

    # Target price: current + momentum-adjusted projection
    expected_monthly_return = composite / 100 * 0.08  # scale down
    target = round(current_price * (1 + expected_monthly_return * 2), 2)
    expected_return = round((target - current_price) / current_price * 100, 1)

    # Action
    action, rationale = _determine_action(
        composite, momentum_20d, direction, "short"
    )

    # Confidence
    if abs(composite) > 40 and abs(news_score) > 30:
        confidence = "HIGH"
    elif abs(composite) > 20:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Entry strategy
    if action in ("BUY NOW", "ACCUMULATE"):
        if vol > 30:
            entry_strategy = "Scale in over 2-3 weeks to average out volatility"
        else:
            entry_strategy = "Enter at current levels or on any 2-3% pullback"
    elif action == "WAIT FOR DIP":
        entry_strategy = f"Set limit order 3-5% below current price (~${current_price * 0.96:.2f})"
    else:
        entry_strategy = "Monitor for improved technical setup before entering"

    return HorizonRecommendation(
        horizon="short",
        horizon_label="Short-Term (1-3 months)",
        action=action,
        confidence=confidence,
        target_price=target,
        expected_return_pct=expected_return,
        entry_strategy=entry_strategy,
        rationale=rationale,
    )


def _medium_term_recommendation(
    ticker: str,
    close: np.ndarray,
    current_price: float,
    tech_score: float,
    fund_score: float,
    news_score: float,
    consensus_score: float,
    num_holders: int,
    direction: str,
) -> HorizonRecommendation:
    """3-12 month recommendation -- balanced across all factors."""
    # Medium: 30% tech, 30% fundamental, 20% news, 20% consensus
    composite = (
        tech_score * 0.30 +
        fund_score * 0.30 +
        news_score * 0.20 +
        min(consensus_score / 5, 20) * 0.20
    )

    # Trend (60-day return)
    if len(close) >= 60:
        trend_60d = (close[-1] - close[-60]) / close[-60] * 100
    else:
        trend_60d = 0

    # Target: composite-adjusted 6-month projection
    base_annual_return = 0.11  # market average
    score_adj = composite / 100 * 0.15
    expected_6m_return = (base_annual_return + score_adj) * 0.5
    target = round(current_price * (1 + expected_6m_return), 2)
    expected_return = round(expected_6m_return * 100, 1)

    action, rationale = _determine_action(
        composite, trend_60d, direction, "medium"
    )

    # Consensus boost
    if num_holders >= 5:
        rationale.append(f"Strong institutional consensus ({num_holders} top investors)")
    elif num_holders >= 3:
        rationale.append(f"Solid institutional backing ({num_holders} top investors)")

    confidence = "HIGH" if abs(composite) > 35 else ("MEDIUM" if abs(composite) > 15 else "LOW")

    if action in ("BUY NOW", "ACCUMULATE"):
        entry_strategy = "Build position over 4-6 weeks using dollar-cost averaging"
    elif action == "WAIT FOR DIP":
        entry_strategy = "Set alerts at key support levels and accumulate on pullbacks"
    else:
        entry_strategy = "Wait for fundamental catalyst or technical reversal"

    return HorizonRecommendation(
        horizon="medium",
        horizon_label="Medium-Term (3-12 months)",
        action=action,
        confidence=confidence,
        target_price=target,
        expected_return_pct=expected_return,
        entry_strategy=entry_strategy,
        rationale=rationale,
    )


def _long_term_recommendation(
    ticker: str,
    close: np.ndarray,
    current_price: float,
    tech_score: float,
    fund_score: float,
    news_score: float,
    consensus_score: float,
    num_holders: int,
    direction: str,
) -> HorizonRecommendation:
    """1-5 year recommendation -- heavily weighted toward fundamentals & consensus."""
    # Long-term: 10% tech, 45% fundamental, 5% news, 40% consensus
    composite = (
        tech_score * 0.10 +
        fund_score * 0.45 +
        news_score * 0.05 +
        min(consensus_score / 5, 20) * 0.40
    )

    # Long-term target: fundamental value projection
    base_annual_return = 0.11
    score_adj = composite / 100 * 0.10
    annual_return = base_annual_return + score_adj

    # 3-year target
    target = round(current_price * (1 + annual_return) ** 3, 2)
    expected_return = round(((1 + annual_return) ** 3 - 1) * 100, 1)

    action, rationale = _determine_action(
        composite, 0, direction, "long"
    )

    # Long-term adjustments
    if num_holders >= 4 and direction == "Adding":
        if action == "WAIT FOR DIP":
            action = "ACCUMULATE"
        rationale.append("Multiple top investors are actively building positions")

    if fund_score > 30:
        rationale.append("Strong fundamental profile supports long-term value creation")
    elif fund_score < -20:
        rationale.append("Weak fundamentals create long-term headwinds")

    confidence = "HIGH" if abs(composite) > 30 else ("MEDIUM" if abs(composite) > 10 else "LOW")

    if action in ("BUY NOW", "ACCUMULATE"):
        entry_strategy = (
            "Initiate core position now and add on any significant dips. "
            "Consider investing 1/3 now, 1/3 on a 5% pullback, 1/3 on a 10% pullback."
        )
    elif action == "WAIT FOR DIP":
        entry_strategy = (
            "Add to watchlist and accumulate gradually on market pullbacks. "
            "Target entry on 10-15% corrections from current levels."
        )
    else:
        entry_strategy = "Not recommended for long-term portfolio at current valuations"

    return HorizonRecommendation(
        horizon="long",
        horizon_label="Long-Term (1-5 years)",
        action=action,
        confidence=confidence,
        target_price=target,
        expected_return_pct=expected_return,
        entry_strategy=entry_strategy,
        rationale=rationale,
    )


# ─── Action Logic ────────────────────────────────────────────────────────────


def _determine_action(
    composite: float,
    momentum: float,
    direction: str,
    horizon: str,
) -> tuple[str, list[str]]:
    """Determine buy/hold/avoid action and rationale."""
    rationale = []

    if composite > 35:
        action = "BUY NOW"
        rationale.append("Strong positive signal across multiple indicators")
    elif composite > 15:
        if direction == "Adding":
            action = "ACCUMULATE"
            rationale.append("Favorable indicators with institutional buying momentum")
        else:
            action = "BUY NOW" if momentum > 5 else "ACCUMULATE"
            rationale.append("Moderately positive outlook supports position building")
    elif composite > -10:
        if direction == "Adding" and horizon != "short":
            action = "ACCUMULATE"
            rationale.append("Neutral indicators but smart money is buying")
        else:
            action = "WAIT FOR DIP"
            rationale.append("Mixed signals suggest waiting for better entry")
    elif composite > -30:
        action = "WAIT FOR DIP" if direction != "Reducing" else "AVOID"
        rationale.append("Negative indicators warrant caution")
    else:
        action = "AVOID"
        rationale.append("Strong negative signals across multiple indicators")

    # Direction-based commentary
    if direction == "Adding":
        rationale.append("Top investors are increasing their positions")
    elif direction == "Reducing":
        rationale.append("Top investors are trimming their positions")

    # Momentum commentary
    if horizon == "short" and abs(momentum) > 10:
        if momentum > 10:
            rationale.append(f"Strong recent momentum (+{momentum:.1f}% in 20 days)")
        else:
            rationale.append(f"Negative momentum ({momentum:.1f}% in 20 days)")

    return action, rationale


def _determine_overall_action(rec: PurchaseRecommendation) -> str:
    """Determine the overall action from horizon recommendations."""
    actions = []
    if rec.short_term:
        actions.append(rec.short_term.action)
    if rec.medium_term:
        actions.append(rec.medium_term.action)
    if rec.long_term:
        actions.append(rec.long_term.action)

    if not actions:
        return "HOLD"

    # Priority: if majority says BUY NOW, then BUY NOW
    buy_count = sum(1 for a in actions if a == "BUY NOW")
    accumulate_count = sum(1 for a in actions if a == "ACCUMULATE")
    avoid_count = sum(1 for a in actions if a == "AVOID")

    if buy_count >= 2:
        return "BUY NOW"
    if buy_count + accumulate_count >= 2:
        return "ACCUMULATE"
    if avoid_count >= 2:
        return "AVOID"
    return "WAIT FOR DIP"


def _determine_confidence(rec: PurchaseRecommendation) -> str:
    """Determine overall confidence."""
    confidences = []
    if rec.short_term:
        confidences.append(rec.short_term.confidence)
    if rec.medium_term:
        confidences.append(rec.medium_term.confidence)
    if rec.long_term:
        confidences.append(rec.long_term.confidence)

    high_count = sum(1 for c in confidences if c == "HIGH")
    if high_count >= 2:
        return "HIGH"
    if high_count >= 1 or sum(1 for c in confidences if c == "MEDIUM") >= 2:
        return "MEDIUM"
    return "LOW"


def _build_bull_case(
    rec: PurchaseRecommendation,
    tech_score: float, fund_score: float, news_score: float,
    consensus_score: float, num_holders: int, direction: str,
) -> list[str]:
    """Build the bull case arguments."""
    points = []
    if tech_score > 20:
        points.append("Technical indicators are bullish with favorable trend setup")
    if fund_score > 20:
        points.append("Strong fundamentals with attractive valuation metrics")
    if news_score > 20:
        points.append("Positive news sentiment and growth catalysts identified")
    if num_holders >= 4:
        points.append(f"High conviction from {num_holders} of the world's top investors")
    if direction == "Adding":
        points.append("Institutional investors are actively increasing positions")
    if rec.buy_zone and rec.buy_zone.risk_reward_ratio > 2:
        points.append(f"Favorable risk/reward ratio of {rec.buy_zone.risk_reward_ratio:.1f}:1")
    if rec.long_term and rec.long_term.expected_return_pct > 30:
        points.append(f"Significant long-term upside potential ({rec.long_term.expected_return_pct:.0f}%)")
    return points[:5]


def _build_bear_case(
    rec: PurchaseRecommendation,
    tech_score: float, fund_score: float, news_score: float,
    consensus_score: float, direction: str,
) -> list[str]:
    """Build the bear case arguments."""
    points = []
    if tech_score < -20:
        points.append("Bearish technical setup with negative momentum")
    if fund_score < -20:
        points.append("Stretched valuations or weak fundamental profile")
    if news_score < -20:
        points.append("Negative news flow and identified risk factors")
    if direction == "Reducing":
        points.append("Institutional investors are trimming positions")
    if rec.buy_zone and rec.buy_zone.risk_reward_ratio < 1:
        points.append("Unfavorable risk/reward at current price levels")

    # Always include some caution
    if not points:
        points.append("13F filings are delayed 45+ days -- positions may have changed")
        points.append("Market conditions can change rapidly regardless of indicators")

    return points[:5]


def _generate_summary(rec: PurchaseRecommendation) -> str:
    """Generate a human-readable summary."""
    action_text = {
        "BUY NOW": f"{rec.ticker} shows strong buy signals across multiple time horizons",
        "ACCUMULATE": f"{rec.ticker} merits gradual position building at current levels",
        "WAIT FOR DIP": f"{rec.ticker} is interesting but warrants patience for a better entry",
        "AVOID": f"{rec.ticker} carries too many negative signals for new positions currently",
        "HOLD": f"{rec.ticker} shows mixed signals -- hold existing positions but wait to add",
    }

    summary = action_text.get(rec.overall_action, f"Analysis complete for {rec.ticker}")

    if rec.buy_zone:
        summary += (
            f". Ideal entry zone: ${rec.buy_zone.ideal_entry:.2f}-"
            f"${rec.buy_zone.buy_below:.2f}"
        )

    if rec.long_term:
        summary += f". Long-term target: ${rec.long_term.target_price:.2f}"

    return summary + "."


# ─── Batch Analysis ──────────────────────────────────────────────────────────


def generate_watchlist_recommendations(
    watchlist: list[dict],
) -> list[dict]:
    """
    Generate purchase recommendations for every stock in the watchlist.

    Expects watchlist items to already have 'indicators' and 'news' keys
    from the indicators and news_analyzer modules.
    """
    for i, item in enumerate(watchlist):
        ticker = item.get("ticker", "")
        if not ticker or len(ticker) > 5 or not ticker.isalpha():
            item["recommendation"] = None
            continue

        logger.info(f"  [{i + 1}/{len(watchlist)}] Generating recommendation for {ticker}...")

        # Extract scores from enriched data
        tech_score = 0.0
        fund_score = 0.0
        news_score = 0.0

        indicators = item.get("indicators")
        if indicators:
            tech_score = indicators.technical.technical_score
            fund_score = indicators.fundamental.fundamental_score

        news = item.get("news")
        if news:
            # Convert news sentiment (-1 to 1) to our scale (-100 to 100)
            news_score = news.avg_sentiment * 100

        rec = generate_purchase_recommendation(
            ticker=ticker,
            name=item.get("name", ""),
            technical_score=tech_score,
            fundamental_score=fund_score,
            news_score=news_score,
            consensus_score=item.get("consensus_score", 0),
            num_holders=item.get("num_holders", 0),
            direction=item.get("direction", "Steady"),
        )
        item["recommendation"] = rec

    return watchlist
