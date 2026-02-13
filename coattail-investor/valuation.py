from __future__ import annotations

"""
Basic Valuation Screening for Consensus Picks.

Uses yfinance to pull current market data and compare against the filing
quarter-end price to produce valuation traffic lights.
"""

import logging
from datetime import datetime, timedelta

import yfinance as yf

from config import VALUATION_GREEN_MAX, VALUATION_YELLOW_MAX

logger = logging.getLogger(__name__)


def get_valuation_data(ticker: str, quarter_end_date: str | None = None) -> dict:
    """
    Fetch valuation data for a single stock.

    Args:
        ticker: Stock ticker symbol.
        quarter_end_date: Quarter-end date string (YYYY-MM-DD) for comparison.

    Returns:
        Dict with current price, filing-date price, change, P/E, P/B, etc.
    """
    result = {
        "ticker": ticker,
        "current_price": None,
        "quarter_end_price": None,
        "price_change_pct": None,
        "pe_ratio": None,
        "price_to_book": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "pct_of_52w_range": None,
        "market_cap": None,
        "signal": "UNKNOWN",
        "signal_emoji": "?",
        "error": None,
    }

    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("regularMarketPrice") is None:
            # Try fast_info as fallback
            try:
                fast = stock.fast_info
                result["current_price"] = getattr(fast, "last_price", None)
                result["market_cap"] = getattr(fast, "market_cap", None)
                result["fifty_two_week_high"] = getattr(fast, "year_high", None)
                result["fifty_two_week_low"] = getattr(fast, "year_low", None)
            except Exception:
                result["error"] = "No data available"
                return result
        else:
            result["current_price"] = info.get("regularMarketPrice") or info.get("currentPrice")
            result["pe_ratio"] = info.get("trailingPE") or info.get("forwardPE")
            result["price_to_book"] = info.get("priceToBook")
            result["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh")
            result["fifty_two_week_low"] = info.get("fiftyTwoWeekLow")
            result["market_cap"] = info.get("marketCap")

        # Get quarter-end price for comparison
        if quarter_end_date and result["current_price"]:
            result["quarter_end_price"] = _get_historical_price(
                stock, quarter_end_date
            )

            if result["quarter_end_price"] and result["quarter_end_price"] > 0:
                change = (
                    (result["current_price"] - result["quarter_end_price"])
                    / result["quarter_end_price"]
                )
                result["price_change_pct"] = round(change * 100, 1)

                # Traffic light signal
                abs_change = abs(change)
                if abs_change <= VALUATION_GREEN_MAX:
                    result["signal"] = "GREEN"
                    result["signal_emoji"] = "GREEN"
                elif abs_change <= VALUATION_YELLOW_MAX:
                    result["signal"] = "YELLOW"
                    result["signal_emoji"] = "YELLOW"
                else:
                    result["signal"] = "RED"
                    result["signal_emoji"] = "RED"

        # 52-week range position
        if result["fifty_two_week_high"] and result["fifty_two_week_low"] and result["current_price"]:
            range_size = result["fifty_two_week_high"] - result["fifty_two_week_low"]
            if range_size > 0:
                result["pct_of_52w_range"] = round(
                    (result["current_price"] - result["fifty_two_week_low"]) / range_size * 100, 1
                )

    except Exception as e:
        logger.error(f"Error fetching valuation for {ticker}: {e}")
        result["error"] = str(e)

    return result


def _get_historical_price(stock: yf.Ticker, date_str: str) -> float | None:
    """Get the closing price for a stock on or near a given date."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Fetch a range around the date to handle weekends/holidays
        start = dt - timedelta(days=5)
        end = dt + timedelta(days=5)

        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if hist.empty:
            return None

        # Find the closest date to our target
        target = dt.strftime("%Y-%m-%d")
        if target in hist.index.strftime("%Y-%m-%d"):
            return float(hist.loc[target]["Close"])

        # Return the last available price before the target date
        before_target = hist[hist.index <= dt.strftime("%Y-%m-%d")]
        if not before_target.empty:
            return float(before_target.iloc[-1]["Close"])

        return float(hist.iloc[0]["Close"])

    except Exception as e:
        logger.debug(f"Could not get historical price for {date_str}: {e}")
        return None


def screen_watchlist(
    watchlist: list[dict], quarter_end_date: str | None = None
) -> list[dict]:
    """
    Add valuation data to each item in the watchlist.

    Args:
        watchlist: List of watchlist dicts from analyzer.
        quarter_end_date: Quarter-end date for price comparison.

    Returns:
        Updated watchlist with valuation data added.
    """
    logger.info(f"Screening {len(watchlist)} watchlist stocks for valuation...")

    for i, item in enumerate(watchlist):
        ticker = item.get("ticker", "")

        # Skip identifiers that are clearly CUSIPs (9+ alphanumeric, no
        # alpha-only match).  Allow tickers with hyphens like BRK-B.
        clean = ticker.replace("-", "").replace(".", "")
        if not ticker or len(clean) > 5 or (len(clean) >= 6 and not clean.isalpha()):
            item["valuation"] = {
                "signal": "UNKNOWN",
                "signal_emoji": "?",
                "error": "No valid ticker",
            }
            continue

        logger.info(f"  [{i + 1}/{len(watchlist)}] Screening {ticker}...")

        val_data = get_valuation_data(ticker, quarter_end_date)
        item["valuation"] = val_data

    return watchlist


def _quarter_to_end_date(quarter: str) -> str:
    """Convert a quarter string like '2025-Q4' to its end date."""
    parts = quarter.split("-")
    if len(parts) != 2:
        return ""

    year = parts[0]
    q = parts[1]

    end_dates = {
        "Q1": f"{year}-03-31",
        "Q2": f"{year}-06-30",
        "Q3": f"{year}-09-30",
        "Q4": f"{year}-12-31",
    }

    return end_dates.get(q, "")


def enrich_consensus_with_valuation(consensus: dict) -> dict:
    """
    Add valuation data to the consensus analysis results.

    Enriches the watchlist and top consensus picks with current valuation data.
    """
    quarter = consensus.get("quarter", "")
    quarter_end = _quarter_to_end_date(quarter) if quarter else None

    # Screen watchlist
    if consensus.get("watchlist"):
        consensus["watchlist"] = screen_watchlist(
            consensus["watchlist"], quarter_end
        )

    # Screen top consensus picks
    if consensus.get("top_consensus"):
        for pick in consensus["top_consensus"]:
            if pick.get("valuation"):
                continue  # Already enriched via watchlist
            ticker = pick.get("ticker", "")
            clean = ticker.replace("-", "").replace(".", "")
            if ticker and len(clean) <= 5:
                pick["valuation"] = get_valuation_data(ticker, quarter_end)
            else:
                pick["valuation"] = {
                    "signal": "UNKNOWN",
                    "signal_emoji": "?",
                    "error": "No valid ticker",
                }

    return consensus
