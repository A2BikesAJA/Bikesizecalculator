from __future__ import annotations

"""
Key Indicators Module -- Technical & Fundamental Analysis.

Computes the indicators that top investors evaluate before entering
or exiting a position: RSI, MACD, moving-average trends, P/E, PEG,
debt-to-equity, free-cash-flow yield, and more.  Each indicator is
scored and rolled into a composite BUY / HOLD / SELL signal.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)


# ─── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators for a single stock."""

    ticker: str = ""
    current_price: float = 0.0

    # Moving averages
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None

    # Price vs MAs
    above_sma_50: bool | None = None
    above_sma_200: bool | None = None
    golden_cross: bool | None = None  # SMA50 > SMA200
    death_cross: bool | None = None  # SMA50 < SMA200

    # RSI
    rsi_14: float | None = None

    # MACD
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    macd_bullish: bool | None = None

    # Bollinger Bands
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_position: float | None = None  # 0 = at lower, 1 = at upper

    # Volume
    avg_volume_20d: float | None = None
    volume_ratio: float | None = None  # latest / avg

    # 52-week
    high_52w: float | None = None
    low_52w: float | None = None
    pct_from_high: float | None = None
    pct_from_low: float | None = None

    # Composite
    technical_score: float = 0.0  # -100 to +100
    technical_signal: str = "HOLD"  # BUY / HOLD / SELL

    error: str | None = None


@dataclass
class FundamentalIndicators:
    """Fundamental analysis indicators for a single stock."""

    ticker: str = ""

    # Valuation
    pe_trailing: float | None = None
    pe_forward: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    ev_to_ebitda: float | None = None

    # Profitability
    profit_margin: float | None = None
    operating_margin: float | None = None
    roe: float | None = None
    roa: float | None = None

    # Growth
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    # Balance sheet
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None

    # Cash flow
    free_cash_flow: float | None = None
    fcf_yield: float | None = None
    operating_cash_flow: float | None = None

    # Dividends
    dividend_yield: float | None = None
    payout_ratio: float | None = None

    # Market
    market_cap: float | None = None
    beta: float | None = None

    # Composite
    fundamental_score: float = 0.0  # -100 to +100
    fundamental_signal: str = "HOLD"  # BUY / HOLD / SELL

    error: str | None = None


@dataclass
class StockIndicators:
    """Combined technical + fundamental analysis for a single stock."""

    ticker: str = ""
    name: str = ""
    technical: TechnicalIndicators = field(default_factory=TechnicalIndicators)
    fundamental: FundamentalIndicators = field(default_factory=FundamentalIndicators)
    composite_score: float = 0.0  # -100 to +100
    composite_signal: str = "HOLD"  # BUY / HOLD / SELL
    signal_strength: str = "NEUTRAL"  # STRONG / MODERATE / NEUTRAL
    key_factors: list[str] = field(default_factory=list)


# ─── Technical Analysis ───────────────────────────────────────────────────────


def compute_technical_indicators(ticker: str) -> TechnicalIndicators:
    """
    Compute technical indicators for a stock using 1 year of daily data.
    """
    result = TechnicalIndicators(ticker=ticker)

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")

        if hist.empty or len(hist) < 30:
            result.error = "Insufficient price history"
            return result

        close = hist["Close"].values
        volume = hist["Volume"].values
        result.current_price = float(close[-1])

        # ── Moving averages ──
        if len(close) >= 20:
            result.sma_20 = float(np.mean(close[-20:]))
        if len(close) >= 50:
            result.sma_50 = float(np.mean(close[-50:]))
        if len(close) >= 200:
            result.sma_200 = float(np.mean(close[-200:]))

        # EMA 12 / 26
        result.ema_12 = float(_ema(close, 12))
        result.ema_26 = float(_ema(close, 26))

        # Price vs MAs
        if result.sma_50 is not None:
            result.above_sma_50 = result.current_price > result.sma_50
        if result.sma_200 is not None:
            result.above_sma_200 = result.current_price > result.sma_200
        if result.sma_50 is not None and result.sma_200 is not None:
            result.golden_cross = result.sma_50 > result.sma_200
            result.death_cross = result.sma_50 < result.sma_200

        # ── RSI (14-day) ──
        result.rsi_14 = float(_rsi(close, 14))

        # ── MACD ──
        macd_line = result.ema_12 - result.ema_26
        signal_line = float(_ema(np.array([result.ema_12 - result.ema_26]), 9))
        # Approximate: use EMA(12) - EMA(26) series for proper MACD signal
        macd_series = _ema_series(close, 12) - _ema_series(close, 26)
        if len(macd_series) >= 9:
            signal_series = _ema_series(macd_series, 9)
            result.macd_line = float(macd_series[-1])
            result.macd_signal = float(signal_series[-1])
            result.macd_histogram = result.macd_line - result.macd_signal
            result.macd_bullish = result.macd_line > result.macd_signal

        # ── Bollinger Bands (20-day, 2 std) ──
        if len(close) >= 20:
            sma20 = np.mean(close[-20:])
            std20 = np.std(close[-20:])
            result.bb_upper = float(sma20 + 2 * std20)
            result.bb_middle = float(sma20)
            result.bb_lower = float(sma20 - 2 * std20)
            bb_range = result.bb_upper - result.bb_lower
            if bb_range > 0:
                result.bb_position = float(
                    (result.current_price - result.bb_lower) / bb_range
                )

        # ── Volume ──
        if len(volume) >= 20:
            result.avg_volume_20d = float(np.mean(volume[-20:]))
            if result.avg_volume_20d > 0:
                result.volume_ratio = float(volume[-1] / result.avg_volume_20d)

        # ── 52-week high/low ──
        result.high_52w = float(np.max(close))
        result.low_52w = float(np.min(close))
        if result.high_52w > 0:
            result.pct_from_high = float(
                (result.current_price - result.high_52w) / result.high_52w * 100
            )
        if result.low_52w > 0:
            result.pct_from_low = float(
                (result.current_price - result.low_52w) / result.low_52w * 100
            )

        # ── Score technical indicators ──
        result.technical_score = _score_technical(result)
        result.technical_signal = _signal_from_score(result.technical_score)

    except Exception as e:
        logger.error(f"Technical analysis failed for {ticker}: {e}")
        result.error = str(e)

    return result


def _ema(data: np.ndarray, period: int) -> float:
    """Calculate the latest EMA value for an array."""
    if len(data) < period:
        return float(np.mean(data))
    multiplier = 2 / (period + 1)
    ema_val = float(np.mean(data[:period]))
    for price in data[period:]:
        ema_val = (float(price) - ema_val) * multiplier + ema_val
    return ema_val


def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
    """Calculate EMA series for an array."""
    if len(data) < period:
        return data.copy()
    result = np.zeros_like(data, dtype=float)
    result[:period] = np.mean(data[:period])
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        result[i] = (float(data[i]) - result[i - 1]) * multiplier + result[i - 1]
    return result


def _rsi(prices: np.ndarray, period: int = 14) -> float:
    """Calculate RSI."""
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _score_technical(t: TechnicalIndicators) -> float:
    """
    Score technical indicators on a -100 to +100 scale.
    Positive = bullish, negative = bearish.
    """
    score = 0.0
    weights_total = 0.0

    # RSI (weight: 20)
    if t.rsi_14 is not None:
        weights_total += 20
        if t.rsi_14 < 30:
            score += 20  # oversold = bullish
        elif t.rsi_14 < 40:
            score += 10
        elif t.rsi_14 > 70:
            score -= 20  # overbought = bearish
        elif t.rsi_14 > 60:
            score -= 5

    # Moving average trend (weight: 25)
    if t.above_sma_50 is not None:
        weights_total += 12.5
        score += 12.5 if t.above_sma_50 else -12.5
    if t.above_sma_200 is not None:
        weights_total += 12.5
        score += 12.5 if t.above_sma_200 else -12.5

    # Golden / death cross (weight: 15)
    if t.golden_cross is not None:
        weights_total += 15
        if t.golden_cross:
            score += 15
        elif t.death_cross:
            score -= 15

    # MACD (weight: 20)
    if t.macd_bullish is not None:
        weights_total += 20
        if t.macd_bullish:
            score += 15
            if t.macd_histogram and t.macd_histogram > 0:
                score += 5
        else:
            score -= 15
            if t.macd_histogram and t.macd_histogram < 0:
                score -= 5

    # Bollinger band position (weight: 10)
    if t.bb_position is not None:
        weights_total += 10
        if t.bb_position < 0.2:
            score += 10  # near lower band = oversold
        elif t.bb_position > 0.8:
            score -= 10  # near upper band = overbought

    # Distance from 52-week high (weight: 10)
    if t.pct_from_high is not None:
        weights_total += 10
        if t.pct_from_high > -5:
            score -= 5  # near high
        elif t.pct_from_high < -20:
            score += 10  # pulled back significantly

    if weights_total == 0:
        return 0.0
    return round(score / weights_total * 100, 1)


# ─── Fundamental Analysis ────────────────────────────────────────────────────


def compute_fundamental_indicators(ticker: str) -> FundamentalIndicators:
    """
    Fetch and evaluate fundamental indicators for a stock.
    """
    result = FundamentalIndicators(ticker=ticker)

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        # Valuation
        result.pe_trailing = info.get("trailingPE")
        result.pe_forward = info.get("forwardPE")
        result.peg_ratio = info.get("pegRatio")
        result.price_to_book = info.get("priceToBook")
        result.price_to_sales = info.get("priceToSalesTrailing12Months")
        result.ev_to_ebitda = info.get("enterpriseToEbitda")

        # Profitability
        result.profit_margin = _to_pct(info.get("profitMargins"))
        result.operating_margin = _to_pct(info.get("operatingMargins"))
        result.roe = _to_pct(info.get("returnOnEquity"))
        result.roa = _to_pct(info.get("returnOnAssets"))

        # Growth
        result.revenue_growth = _to_pct(info.get("revenueGrowth"))
        result.earnings_growth = _to_pct(info.get("earningsGrowth"))

        # Balance sheet
        result.debt_to_equity = info.get("debtToEquity")
        result.current_ratio = info.get("currentRatio")
        result.quick_ratio = info.get("quickRatio")

        # Cash flow
        result.free_cash_flow = info.get("freeCashflow")
        result.operating_cash_flow = info.get("operatingCashflow")
        mkt_cap = info.get("marketCap")
        if result.free_cash_flow and mkt_cap and mkt_cap > 0:
            result.fcf_yield = round(result.free_cash_flow / mkt_cap * 100, 2)

        # Dividends
        result.dividend_yield = _to_pct(info.get("dividendYield"))
        result.payout_ratio = _to_pct(info.get("payoutRatio"))

        # Market
        result.market_cap = mkt_cap
        result.beta = info.get("beta")

        # Score
        result.fundamental_score = _score_fundamental(result)
        result.fundamental_signal = _signal_from_score(result.fundamental_score)

    except Exception as e:
        logger.error(f"Fundamental analysis failed for {ticker}: {e}")
        result.error = str(e)

    return result


def _to_pct(value) -> float | None:
    """Convert a decimal ratio (0.15) to percentage (15.0)."""
    if value is None:
        return None
    try:
        return round(float(value) * 100, 2)
    except (ValueError, TypeError):
        return None


def _score_fundamental(f: FundamentalIndicators) -> float:
    """
    Score fundamental indicators on a -100 to +100 scale.
    """
    score = 0.0
    weights_total = 0.0

    # P/E ratio (weight: 15)
    pe = f.pe_forward or f.pe_trailing
    if pe is not None and pe > 0:
        weights_total += 15
        if pe < 15:
            score += 15  # cheap
        elif pe < 20:
            score += 8
        elif pe < 30:
            score -= 3
        elif pe < 50:
            score -= 10
        else:
            score -= 15  # very expensive

    # PEG ratio (weight: 15)
    if f.peg_ratio is not None and f.peg_ratio > 0:
        weights_total += 15
        if f.peg_ratio < 1.0:
            score += 15  # undervalued relative to growth
        elif f.peg_ratio < 1.5:
            score += 8
        elif f.peg_ratio < 2.0:
            score += 0
        elif f.peg_ratio < 3.0:
            score -= 8
        else:
            score -= 15

    # ROE (weight: 10)
    if f.roe is not None:
        weights_total += 10
        if f.roe > 20:
            score += 10
        elif f.roe > 12:
            score += 5
        elif f.roe > 0:
            score += 0
        else:
            score -= 10

    # Debt to equity (weight: 10)
    if f.debt_to_equity is not None:
        weights_total += 10
        if f.debt_to_equity < 50:
            score += 10  # low debt
        elif f.debt_to_equity < 100:
            score += 5
        elif f.debt_to_equity < 200:
            score -= 5
        else:
            score -= 10

    # Revenue growth (weight: 10)
    if f.revenue_growth is not None:
        weights_total += 10
        if f.revenue_growth > 20:
            score += 10
        elif f.revenue_growth > 10:
            score += 5
        elif f.revenue_growth > 0:
            score += 2
        else:
            score -= 10

    # Earnings growth (weight: 10)
    if f.earnings_growth is not None:
        weights_total += 10
        if f.earnings_growth > 25:
            score += 10
        elif f.earnings_growth > 10:
            score += 5
        elif f.earnings_growth > 0:
            score += 2
        else:
            score -= 10

    # FCF yield (weight: 10)
    if f.fcf_yield is not None:
        weights_total += 10
        if f.fcf_yield > 8:
            score += 10
        elif f.fcf_yield > 5:
            score += 7
        elif f.fcf_yield > 2:
            score += 3
        elif f.fcf_yield > 0:
            score += 0
        else:
            score -= 10

    # Profit margin (weight: 10)
    if f.profit_margin is not None:
        weights_total += 10
        if f.profit_margin > 20:
            score += 10
        elif f.profit_margin > 10:
            score += 5
        elif f.profit_margin > 0:
            score += 0
        else:
            score -= 10

    # Operating margin (weight: 5)
    if f.operating_margin is not None:
        weights_total += 5
        if f.operating_margin > 25:
            score += 5
        elif f.operating_margin > 15:
            score += 3
        elif f.operating_margin > 0:
            score += 0
        else:
            score -= 5

    # Beta / risk (weight: 5)
    if f.beta is not None:
        weights_total += 5
        if 0.8 <= f.beta <= 1.2:
            score += 3  # moderate risk
        elif f.beta < 0.5 or f.beta > 2.0:
            score -= 5  # extreme

    if weights_total == 0:
        return 0.0
    return round(score / weights_total * 100, 1)


# ─── Combined Analysis ───────────────────────────────────────────────────────


def analyze_stock_indicators(
    ticker: str, name: str = ""
) -> StockIndicators:
    """
    Run full technical + fundamental analysis for a stock and produce a
    composite signal.
    """
    tech = compute_technical_indicators(ticker)
    fund = compute_fundamental_indicators(ticker)

    # Composite: 50% technical, 50% fundamental
    composite = round(tech.technical_score * 0.5 + fund.fundamental_score * 0.5, 1)
    signal = _signal_from_score(composite)

    # Strength
    if abs(composite) >= 40:
        strength = "STRONG"
    elif abs(composite) >= 20:
        strength = "MODERATE"
    else:
        strength = "NEUTRAL"

    # Key factors
    factors = _identify_key_factors(tech, fund)

    return StockIndicators(
        ticker=ticker,
        name=name,
        technical=tech,
        fundamental=fund,
        composite_score=composite,
        composite_signal=signal,
        signal_strength=strength,
        key_factors=factors,
    )


def analyze_watchlist_indicators(
    watchlist: list[dict],
) -> list[dict]:
    """
    Analyze indicators for every stock in the consensus watchlist.

    Returns the watchlist items enriched with an 'indicators' key.
    """
    results = []
    for i, item in enumerate(watchlist):
        ticker = item.get("ticker", "")
        if not ticker or len(ticker) > 5 or not ticker.isalpha():
            item["indicators"] = None
            results.append(item)
            continue

        logger.info(f"  [{i + 1}/{len(watchlist)}] Analyzing indicators for {ticker}...")
        indicators = analyze_stock_indicators(ticker, item.get("name", ""))
        item["indicators"] = indicators
        results.append(item)

    return results


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _signal_from_score(score: float) -> str:
    if score >= 20:
        return "BUY"
    elif score <= -20:
        return "SELL"
    return "HOLD"


def _identify_key_factors(
    tech: TechnicalIndicators, fund: FundamentalIndicators
) -> list[str]:
    """Identify the most impactful factors driving the signal."""
    factors = []

    # Technical factors
    if tech.rsi_14 is not None:
        if tech.rsi_14 < 30:
            factors.append("RSI oversold (<30) -- potential bounce")
        elif tech.rsi_14 > 70:
            factors.append("RSI overbought (>70) -- potential pullback")

    if tech.golden_cross:
        factors.append("Golden cross (SMA50 > SMA200) -- bullish trend")
    elif tech.death_cross:
        factors.append("Death cross (SMA50 < SMA200) -- bearish trend")

    if tech.macd_bullish is True:
        factors.append("MACD bullish crossover")
    elif tech.macd_bullish is False:
        factors.append("MACD bearish crossover")

    if tech.bb_position is not None:
        if tech.bb_position < 0.1:
            factors.append("Price near lower Bollinger Band -- oversold")
        elif tech.bb_position > 0.9:
            factors.append("Price near upper Bollinger Band -- overbought")

    if tech.pct_from_high is not None and tech.pct_from_high < -25:
        factors.append(f"Trading {abs(tech.pct_from_high):.0f}% below 52-week high")

    # Fundamental factors
    pe = fund.pe_forward or fund.pe_trailing
    if pe is not None:
        if pe < 15:
            factors.append(f"Low P/E ({pe:.1f}) -- potential value")
        elif pe > 40:
            factors.append(f"High P/E ({pe:.1f}) -- premium valuation")

    if fund.peg_ratio is not None and fund.peg_ratio < 1.0:
        factors.append(f"PEG ratio {fund.peg_ratio:.2f} -- undervalued vs growth")

    if fund.roe is not None and fund.roe > 20:
        factors.append(f"Strong ROE ({fund.roe:.1f}%)")

    if fund.debt_to_equity is not None and fund.debt_to_equity > 200:
        factors.append(f"High debt/equity ({fund.debt_to_equity:.0f}%) -- leverage risk")

    if fund.revenue_growth is not None and fund.revenue_growth > 20:
        factors.append(f"Strong revenue growth ({fund.revenue_growth:.1f}%)")

    if fund.fcf_yield is not None and fund.fcf_yield > 5:
        factors.append(f"Attractive FCF yield ({fund.fcf_yield:.1f}%)")

    if fund.earnings_growth is not None and fund.earnings_growth < 0:
        factors.append(f"Declining earnings ({fund.earnings_growth:.1f}%)")

    return factors[:8]  # Cap at 8 most important
