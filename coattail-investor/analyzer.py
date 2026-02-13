"""
Portfolio Analysis and Consensus Scoring Engine.

Analyzes 13F holdings across tracked investors to identify consensus picks,
high-conviction overlap, and smart money momentum.
"""

import logging
from collections import defaultdict

import pandas as pd

from config import (
    CONSENSUS_MIN_HOLDERS,
    SIGNIFICANT_CHANGE_PCT,
    TOP_CONSENSUS_COUNT,
    TRACKED_INVESTORS,
    WATCHLIST_SIZE,
)

logger = logging.getLogger(__name__)


# ─── Per-Investor Analysis ───────────────────────────────────────────────────


def analyze_investor(quarterly_data: list[dict]) -> dict:
    """
    Analyze a single investor's portfolio from their quarterly filings.

    Args:
        quarterly_data: List of quarterly filing dicts (most recent first).

    Returns:
        Analysis dict with top holdings, changes, concentration, etc.
    """
    if not quarterly_data:
        return {"error": "No data available"}

    latest = quarterly_data[0]
    holdings = latest["holdings"]
    prior = quarterly_data[1] if len(quarterly_data) > 1 else None

    # Sort by portfolio weight
    holdings_sorted = sorted(holdings, key=lambda h: h["value"], reverse=True)

    # Top 10 holdings
    top_10 = holdings_sorted[:10]

    # Concentration metrics
    total_value = sum(h["value"] for h in holdings)
    top_5_value = sum(h["value"] for h in holdings_sorted[:5])
    top_10_value = sum(h["value"] for h in holdings_sorted[:10])

    concentration = {
        "top_5_pct": (top_5_value / total_value * 100) if total_value > 0 else 0,
        "top_10_pct": (top_10_value / total_value * 100) if total_value > 0 else 0,
        "total_positions": len(holdings),
        "total_value_millions": total_value / 1000,  # value is in thousands
    }

    # Build current holdings lookup by CUSIP
    current_by_cusip = {h["cusip"]: h for h in holdings}

    # Quarter-over-quarter changes
    new_positions = []
    increased_positions = []
    decreased_positions = []
    exited_positions = []
    turnover_value = 0

    if prior:
        prior_by_cusip = {h["cusip"]: h for h in prior["holdings"]}
        prior_total = sum(h["value"] for h in prior["holdings"])

        # Find new and changed positions
        for cusip, h in current_by_cusip.items():
            if cusip not in prior_by_cusip:
                new_positions.append(h)
                turnover_value += h["value"]
            else:
                prior_h = prior_by_cusip[cusip]
                if prior_h["shares"] > 0:
                    change_pct = (h["shares"] - prior_h["shares"]) / prior_h["shares"]
                else:
                    change_pct = 1.0 if h["shares"] > 0 else 0

                h["change_pct"] = change_pct
                h["prior_shares"] = prior_h["shares"]

                if change_pct > SIGNIFICANT_CHANGE_PCT:
                    increased_positions.append(h)
                    turnover_value += abs(h["value"] - prior_h["value"])
                elif change_pct < -SIGNIFICANT_CHANGE_PCT:
                    decreased_positions.append(h)
                    turnover_value += abs(h["value"] - prior_h["value"])

        # Find exited positions
        for cusip, h in prior_by_cusip.items():
            if cusip not in current_by_cusip:
                h["change_pct"] = -1.0
                exited_positions.append(h)
                turnover_value += h["value"]

        turnover_rate = (turnover_value / prior_total * 100) if prior_total > 0 else 0
    else:
        turnover_rate = 0

    # Sector allocation (approximation based on issuer names)
    sector_allocation = _estimate_sector_allocation(holdings)

    return {
        "investor_name": latest["investor_name"],
        "quarter": latest["quarter"],
        "filing_date": latest["filing_date"],
        "top_10": [_holding_summary(h) for h in top_10],
        "new_positions": [_holding_summary(h) for h in new_positions],
        "increased_positions": sorted(
            [_holding_summary(h) for h in increased_positions],
            key=lambda x: x.get("change_pct", 0),
            reverse=True,
        ),
        "decreased_positions": sorted(
            [_holding_summary(h) for h in decreased_positions],
            key=lambda x: x.get("change_pct", 0),
        ),
        "exited_positions": [_holding_summary(h) for h in exited_positions],
        "concentration": concentration,
        "turnover_rate": turnover_rate,
        "sector_allocation": sector_allocation,
    }


def _holding_summary(h: dict) -> dict:
    """Create a summary dict from a raw holding."""
    return {
        "name": h["nameOfIssuer"],
        "ticker": h.get("ticker", h["cusip"]),
        "cusip": h["cusip"],
        "value_thousands": h["value"],
        "shares": h["shares"],
        "weight_pct": h.get("portfolioWeight", 0),
        "change_pct": h.get("change_pct"),
        "put_call": h.get("putCall", ""),
    }


def _estimate_sector_allocation(holdings: list[dict]) -> dict[str, float]:
    """
    Rough sector estimation based on well-known company names.
    A proper implementation would use SIC codes or a classification API.
    """
    sector_keywords = {
        "Technology": [
            "apple", "microsoft", "google", "alphabet", "meta", "amazon",
            "nvidia", "amd", "intel", "oracle", "salesforce", "adobe",
            "cisco", "ibm", "qualcomm", "broadcom", "texas instrument",
            "snowflake", "palantir", "crowdstrike", "datadog",
        ],
        "Financial": [
            "bank", "jpmorgan", "goldman", "morgan stanley", "wells fargo",
            "citigroup", "visa", "mastercard", "american express", "capital one",
            "schwab", "blackrock", "berkshire", "insurance", "financial",
        ],
        "Healthcare": [
            "unitedhealth", "johnson & johnson", "pfizer", "merck", "abbvie",
            "eli lilly", "thermo fisher", "abbott", "danaher", "medtronic",
            "health", "pharma", "biotech", "medical", "therapeutics",
        ],
        "Consumer": [
            "procter", "coca-cola", "pepsi", "walmart", "costco", "nike",
            "mcdonald", "starbucks", "home depot", "target", "consumer",
        ],
        "Energy": [
            "exxon", "chevron", "conocophillips", "schlumberger", "energy",
            "petroleum", "oil", "occidental",
        ],
        "Industrial": [
            "caterpillar", "deere", "honeywell", "3m", "general electric",
            "raytheon", "lockheed", "boeing", "industrial",
        ],
        "Communication": [
            "verizon", "at&t", "t-mobile", "comcast", "disney", "netflix",
            "charter", "communication",
        ],
    }

    total_value = sum(h["value"] for h in holdings)
    if total_value == 0:
        return {}

    sector_values = defaultdict(float)

    for h in holdings:
        name_lower = h["nameOfIssuer"].lower()
        classified = False

        for sector, keywords in sector_keywords.items():
            if any(kw in name_lower for kw in keywords):
                sector_values[sector] += h["value"]
                classified = True
                break

        if not classified:
            sector_values["Other"] += h["value"]

    return {
        sector: round(value / total_value * 100, 1)
        for sector, value in sorted(sector_values.items(), key=lambda x: -x[1])
    }


# ─── Cross-Investor Consensus Analysis ──────────────────────────────────────


def build_consensus(all_investor_data: dict[str, list[dict]]) -> dict:
    """
    Build cross-investor consensus analysis.

    Args:
        all_investor_data: Dict mapping investor name to list of quarterly data.

    Returns:
        Consensus analysis dict with scored picks, new picks, exit warnings, etc.
    """
    total_investors = len(TRACKED_INVESTORS)

    # Aggregate all current holdings by CUSIP
    stock_data = defaultdict(lambda: {
        "holders": [],
        "total_value": 0,
        "avg_weight": 0,
        "weights": [],
        "directions": [],  # 1=new/increased, 0=steady, -1=decreased/exited
        "names": set(),
        "tickers": set(),
        "cusip": "",
    })

    investor_analyses = {}
    latest_quarter = None

    for inv_name, quarters in all_investor_data.items():
        if not quarters:
            continue

        analysis = analyze_investor(quarters)
        investor_analyses[inv_name] = analysis

        latest = quarters[0]
        if latest_quarter is None or latest["quarter"] > latest_quarter:
            latest_quarter = latest["quarter"]

        # Process current holdings
        for h in latest["holdings"]:
            cusip = h["cusip"]
            entry = stock_data[cusip]
            entry["holders"].append(inv_name)
            entry["total_value"] += h["value"]
            entry["weights"].append(h.get("portfolioWeight", 0))
            entry["names"].add(h["nameOfIssuer"])
            entry["tickers"].add(h.get("ticker", cusip))
            entry["cusip"] = cusip

        # Track direction of changes
        for h in analysis.get("new_positions", []):
            cusip = h["cusip"]
            stock_data[cusip]["directions"].append(1)

        for h in analysis.get("increased_positions", []):
            cusip = h["cusip"]
            stock_data[cusip]["directions"].append(1)

        for h in analysis.get("decreased_positions", []):
            cusip = h["cusip"]
            stock_data[cusip]["directions"].append(-1)

        for h in analysis.get("exited_positions", []):
            cusip = h["cusip"]
            stock_data[cusip]["directions"].append(-1)
            # Add exited stocks to tracking even though not in current holdings
            entry = stock_data[cusip]
            if inv_name not in entry["holders"]:
                entry["names"].add(h["name"])
                entry["tickers"].add(h.get("ticker", cusip))

    # Calculate consensus scores
    scored_stocks = []
    for cusip, data in stock_data.items():
        num_holders = len(data["holders"])
        avg_weight = sum(data["weights"]) / len(data["weights"]) if data["weights"] else 0

        # Direction multiplier
        if data["directions"]:
            avg_direction = sum(data["directions"]) / len(data["directions"])
            if avg_direction > 0.3:
                direction_mult = 1.2
                direction_label = "Adding"
            elif avg_direction < -0.3:
                direction_mult = 0.7
                direction_label = "Reducing"
            else:
                direction_label = "Steady"
                direction_mult = 1.0
        else:
            direction_mult = 1.0
            direction_label = "Steady"

        # Consensus score = holders * avg_weight * direction
        score = num_holders * avg_weight * direction_mult

        name = max(data["names"], key=len) if data["names"] else "Unknown"
        ticker = next(
            (t for t in data["tickers"] if t != cusip and len(t) <= 5),
            next(iter(data["tickers"]), cusip),
        )

        scored_stocks.append({
            "cusip": cusip,
            "name": name,
            "ticker": ticker,
            "num_holders": num_holders,
            "total_investors": total_investors,
            "holders": data["holders"],
            "avg_weight": round(avg_weight, 2),
            "direction": direction_label,
            "direction_score": avg_direction if data["directions"] else 0,
            "consensus_score": round(score, 2),
        })

    # Sort by consensus score
    scored_stocks.sort(key=lambda x: x["consensus_score"], reverse=True)

    # Identify different categories
    consensus_picks = [s for s in scored_stocks if s["num_holders"] >= CONSENSUS_MIN_HOLDERS]
    top_consensus = consensus_picks[:TOP_CONSENSUS_COUNT]

    # New consensus picks (3+ investors initiated this quarter)
    new_consensus = _find_new_consensus_picks(investor_analyses, stock_data)

    # High conviction overlap (in 3+ top-10 lists)
    high_conviction = _find_high_conviction_overlap(investor_analyses, stock_data)

    # Smart money momentum (3+ investors increased)
    smart_momentum = _find_smart_money_momentum(investor_analyses, stock_data)

    # Exit warnings (3+ investors reduced/exited)
    exit_warnings = _find_exit_warnings(investor_analyses, stock_data)

    return {
        "quarter": latest_quarter or "Unknown",
        "total_investors": total_investors,
        "investors_with_data": len(investor_analyses),
        "total_stocks_tracked": len(stock_data),
        "top_consensus": top_consensus,
        "all_consensus": consensus_picks,
        "new_consensus_picks": new_consensus,
        "high_conviction_overlap": high_conviction,
        "smart_money_momentum": smart_momentum,
        "exit_warnings": exit_warnings,
        "investor_analyses": investor_analyses,
        "watchlist": _build_watchlist(consensus_picks),
    }


def _find_new_consensus_picks(
    investor_analyses: dict, stock_data: dict
) -> list[dict]:
    """Find stocks that 3+ investors initiated positions in this quarter."""
    new_by_cusip = defaultdict(list)

    for inv_name, analysis in investor_analyses.items():
        for h in analysis.get("new_positions", []):
            new_by_cusip[h["cusip"]].append(inv_name)

    results = []
    for cusip, investors in new_by_cusip.items():
        if len(investors) >= CONSENSUS_MIN_HOLDERS:
            data = stock_data.get(cusip, {})
            name = max(data.get("names", {"Unknown"}), key=len)
            ticker = next(
                (t for t in data.get("tickers", set()) if t != cusip and len(t) <= 5),
                cusip,
            )
            results.append({
                "cusip": cusip,
                "name": name,
                "ticker": ticker,
                "initiated_by": investors,
                "num_initiators": len(investors),
            })

    return sorted(results, key=lambda x: x["num_initiators"], reverse=True)


def _find_high_conviction_overlap(
    investor_analyses: dict, stock_data: dict
) -> list[dict]:
    """Find stocks appearing in 3+ investors' top 10 holdings."""
    top10_counts = defaultdict(list)

    for inv_name, analysis in investor_analyses.items():
        for h in analysis.get("top_10", []):
            top10_counts[h["cusip"]].append({
                "investor": inv_name,
                "weight": h["weight_pct"],
            })

    results = []
    for cusip, holders in top10_counts.items():
        if len(holders) >= CONSENSUS_MIN_HOLDERS:
            data = stock_data.get(cusip, {})
            name = max(data.get("names", {"Unknown"}), key=len)
            ticker = next(
                (t for t in data.get("tickers", set()) if t != cusip and len(t) <= 5),
                cusip,
            )
            avg_weight = sum(h["weight"] for h in holders) / len(holders)
            results.append({
                "cusip": cusip,
                "name": name,
                "ticker": ticker,
                "in_top10_of": [h["investor"] for h in holders],
                "num_top10": len(holders),
                "avg_weight_in_top10": round(avg_weight, 2),
            })

    return sorted(results, key=lambda x: x["num_top10"], reverse=True)


def _find_smart_money_momentum(
    investor_analyses: dict, stock_data: dict
) -> list[dict]:
    """Find stocks where 3+ investors increased positions simultaneously."""
    increased_by_cusip = defaultdict(list)

    for inv_name, analysis in investor_analyses.items():
        for h in analysis.get("new_positions", []):
            increased_by_cusip[h["cusip"]].append(inv_name)
        for h in analysis.get("increased_positions", []):
            increased_by_cusip[h["cusip"]].append(inv_name)

    results = []
    for cusip, investors in increased_by_cusip.items():
        if len(investors) >= CONSENSUS_MIN_HOLDERS:
            data = stock_data.get(cusip, {})
            name = max(data.get("names", {"Unknown"}), key=len)
            ticker = next(
                (t for t in data.get("tickers", set()) if t != cusip and len(t) <= 5),
                cusip,
            )
            results.append({
                "cusip": cusip,
                "name": name,
                "ticker": ticker,
                "increased_by": investors,
                "num_increasing": len(investors),
            })

    return sorted(results, key=lambda x: x["num_increasing"], reverse=True)


def _find_exit_warnings(
    investor_analyses: dict, stock_data: dict
) -> list[dict]:
    """Find stocks where 3+ investors reduced or exited simultaneously."""
    reduced_by_cusip = defaultdict(list)

    for inv_name, analysis in investor_analyses.items():
        for h in analysis.get("decreased_positions", []):
            reduced_by_cusip[h["cusip"]].append({
                "investor": inv_name,
                "change_pct": h.get("change_pct", 0),
                "action": "reduced",
            })
        for h in analysis.get("exited_positions", []):
            reduced_by_cusip[h["cusip"]].append({
                "investor": inv_name,
                "change_pct": -1.0,
                "action": "exited",
            })

    results = []
    for cusip, reducers in reduced_by_cusip.items():
        if len(reducers) >= CONSENSUS_MIN_HOLDERS:
            data = stock_data.get(cusip, {})
            name = max(data.get("names", {"Unknown"}), key=len)
            ticker = next(
                (t for t in data.get("tickers", set()) if t != cusip and len(t) <= 5),
                cusip,
            )
            avg_reduction = sum(r["change_pct"] for r in reducers) / len(reducers)
            results.append({
                "cusip": cusip,
                "name": name,
                "ticker": ticker,
                "reduced_by": [r["investor"] for r in reducers],
                "num_reducing": len(reducers),
                "avg_reduction_pct": round(avg_reduction * 100, 1),
            })

    return sorted(results, key=lambda x: x["num_reducing"], reverse=True)


def _build_watchlist(consensus_picks: list[dict]) -> list[dict]:
    """Build the final actionable watchlist from consensus picks."""
    watchlist = []

    for pick in consensus_picks[:WATCHLIST_SIZE]:
        rationale_parts = []
        rationale_parts.append(
            f"Held by {pick['num_holders']} of {pick['total_investors']} tracked investors"
        )

        if pick["direction"] == "Adding":
            rationale_parts.append("investors are adding")
        elif pick["direction"] == "Reducing":
            rationale_parts.append("investors are reducing")

        holders_str = ", ".join(pick["holders"][:5])
        if len(pick["holders"]) > 5:
            holders_str += f" +{len(pick['holders']) - 5} more"

        watchlist.append({
            "rank": len(watchlist) + 1,
            "ticker": pick["ticker"],
            "name": pick["name"],
            "cusip": pick["cusip"],
            "consensus_score": pick["consensus_score"],
            "num_holders": pick["num_holders"],
            "avg_weight": pick["avg_weight"],
            "direction": pick["direction"],
            "holders": pick["holders"],
            "holders_display": holders_str,
            "rationale": "; ".join(rationale_parts),
            "valuation": None,  # Filled in by valuation.py
        })

    return watchlist


# ─── Stock Lookup ────────────────────────────────────────────────────────────


def find_stock_across_investors(
    ticker_or_name: str, all_investor_data: dict[str, list[dict]]
) -> dict:
    """
    Find a specific stock's holdings across all tracked investors.

    Args:
        ticker_or_name: Ticker symbol or partial company name to search for.
        all_investor_data: Dict of all investor quarterly data.

    Returns:
        Dict with stock info and which investors hold it.
    """
    search = ticker_or_name.upper()
    search_lower = ticker_or_name.lower()

    holders = []

    for inv_name, quarters in all_investor_data.items():
        if not quarters:
            continue

        latest = quarters[0]
        for h in latest["holdings"]:
            ticker_match = h.get("ticker", "").upper() == search
            name_match = search_lower in h["nameOfIssuer"].lower()
            cusip_match = h["cusip"].upper() == search

            if ticker_match or name_match or cusip_match:
                holders.append({
                    "investor": inv_name,
                    "name": h["nameOfIssuer"],
                    "ticker": h.get("ticker", h["cusip"]),
                    "cusip": h["cusip"],
                    "value_thousands": h["value"],
                    "shares": h["shares"],
                    "weight_pct": h.get("portfolioWeight", 0),
                    "quarter": latest["quarter"],
                })
                break

    holders.sort(key=lambda x: x["weight_pct"], reverse=True)

    stock_name = holders[0]["name"] if holders else ticker_or_name
    stock_ticker = holders[0]["ticker"] if holders else ticker_or_name

    return {
        "search_term": ticker_or_name,
        "stock_name": stock_name,
        "stock_ticker": stock_ticker,
        "num_holders": len(holders),
        "total_tracked": len(TRACKED_INVESTORS),
        "holders": holders,
    }
