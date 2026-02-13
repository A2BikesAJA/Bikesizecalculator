from __future__ import annotations

"""
Coattail Investor -- Flask Web Application.

Provides a browser-based interface for the Coattail Investor research tool,
wrapping the same analysis, allocation, and simulation engines used by the CLI.
"""

import json
import logging
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Ensure local modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, TRACKED_INVESTORS, get_investor_by_name

app = Flask(__name__)
logger = logging.getLogger(__name__)

# ─── Background task state ───────────────────────────────────────────────────

_task_state = {"running": False, "message": "", "done": False, "error": ""}
_task_lock = threading.Lock()


def _set_task(running=False, message="", done=False, error=""):
    with _task_lock:
        _task_state.update(running=running, message=message, done=done, error=error)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _load_cached_data() -> dict[str, list[dict]]:
    """Load all cached investor holdings data."""
    all_data = {}
    for investor in TRACKED_INVESTORS:
        cache_file = DATA_DIR / f"holdings_{investor['cik']}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                all_data[investor["name"]] = json.load(f)
        else:
            all_data[investor["name"]] = []
    return all_data


def _has_cached_data() -> bool:
    """Check if any cached data exists."""
    for investor in TRACKED_INVESTORS:
        cache_file = DATA_DIR / f"holdings_{investor['cik']}.json"
        if cache_file.exists():
            return True
    return False


def _investor_summary() -> list[dict]:
    """Quick summary of each tracked investor's cached status."""
    summaries = []
    for inv in TRACKED_INVESTORS:
        cache_file = DATA_DIR / f"holdings_{inv['cik']}.json"
        info = {
            "name": inv["name"],
            "entity": inv["entity"],
            "cik": inv["cik"],
            "category": inv["category"],
            "notes": inv["notes"],
            "has_data": False,
            "quarters": 0,
            "latest_quarter": "N/A",
            "filing_date": "N/A",
            "num_holdings": 0,
            "total_value_m": 0,
        }
        if cache_file.exists():
            with open(cache_file) as f:
                data = json.load(f)
            if data:
                info["has_data"] = True
                info["quarters"] = len(data)
                info["latest_quarter"] = data[0].get("quarter", "N/A")
                info["filing_date"] = data[0].get("filing_date", "N/A")
                info["num_holdings"] = data[0].get("num_holdings", 0)
                info["total_value_m"] = round(
                    data[0].get("total_value_thousands", 0) / 1000, 1
                )
        summaries.append(info)
    return summaries


# ─── Routes ──────────────────────────────────────────────────────────────────


@app.route("/")
def dashboard():
    investors = _investor_summary()
    has_data = any(i["has_data"] for i in investors)

    categories = {}
    for inv in investors:
        cat = inv["category"]
        categories.setdefault(cat, []).append(inv)

    total_value = sum(i["total_value_m"] for i in investors)
    data_count = sum(1 for i in investors if i["has_data"])

    return render_template(
        "dashboard.html",
        investors=investors,
        categories=categories,
        has_data=has_data,
        total_value=total_value,
        data_count=data_count,
        total_investors=len(investors),
    )


@app.route("/investors")
def investors_list():
    investors = _investor_summary()
    return render_template("investors.html", investors=investors)


@app.route("/investor/<name>")
def investor_detail(name):
    from analyzer import analyze_investor

    inv = get_investor_by_name(name)
    if not inv:
        return render_template("error.html", message=f"Investor '{name}' not found."), 404

    cache_file = DATA_DIR / f"holdings_{inv['cik']}.json"
    if not cache_file.exists():
        return render_template(
            "investor_detail.html",
            investor=inv,
            analysis=None,
            error="No cached data. Fetch filings first.",
        )

    with open(cache_file) as f:
        data = json.load(f)

    analysis = analyze_investor(data)
    return render_template("investor_detail.html", investor=inv, analysis=analysis, error=None)


@app.route("/consensus")
def consensus_page():
    from analyzer import build_consensus, resolve_consensus_tickers

    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        return render_template("consensus.html", consensus=None, error="No cached data. Fetch filings first.")

    consensus = build_consensus(all_data)

    # Resolve CUSIPs to real tickers so every row shows a symbol
    try:
        consensus = resolve_consensus_tickers(consensus)
    except Exception as e:
        logger.warning(f"Ticker resolution failed: {e}")

    # Enrich with valuation signals (every stock must have a signal)
    try:
        from valuation import enrich_consensus_with_valuation
        consensus = enrich_consensus_with_valuation(consensus)
    except Exception as e:
        logger.warning(f"Valuation enrichment failed: {e}")

    return render_template("consensus.html", consensus=consensus, error=None)


@app.route("/stock", methods=["GET", "POST"])
def stock_lookup():
    from analyzer import find_stock_across_investors

    result = None
    ticker = ""

    if request.method == "POST":
        ticker = request.form.get("ticker", "").strip()
        if ticker:
            all_data = _load_cached_data()
            if any(v for v in all_data.values()):
                result = find_stock_across_investors(ticker, all_data)

    return render_template("stock.html", result=result, ticker=ticker)


@app.route("/allocate", methods=["GET", "POST"])
def allocate_page():
    from allocator import allocate_portfolio
    from analyzer import build_consensus

    allocation = None
    error = None
    form_data = {
        "dollars": 10000,
        "strategy": "conviction",
        "max_positions": "",
        "max_weight": "",
        "fractional": False,
        "exclude_red": False,
    }

    if request.method == "POST":
        try:
            dollars = float(request.form.get("dollars", 10000))
            strategy = request.form.get("strategy", "conviction")
            max_positions = request.form.get("max_positions", "")
            max_weight = request.form.get("max_weight", "")
            fractional = request.form.get("fractional") == "on"
            exclude_red = request.form.get("exclude_red") == "on"

            form_data = {
                "dollars": dollars,
                "strategy": strategy,
                "max_positions": max_positions,
                "max_weight": max_weight,
                "fractional": fractional,
                "exclude_red": exclude_red,
            }

            if dollars <= 0:
                error = "Investment amount must be positive."
            else:
                all_data = _load_cached_data()
                if not any(v for v in all_data.values()):
                    error = "No cached data. Fetch filings first."
                else:
                    consensus = build_consensus(all_data)

                    try:
                        from analyzer import resolve_consensus_tickers
                        consensus = resolve_consensus_tickers(consensus)
                    except Exception:
                        pass

                    try:
                        from valuation import enrich_consensus_with_valuation
                        consensus = enrich_consensus_with_valuation(consensus)
                    except Exception:
                        pass

                    watchlist = consensus.get("watchlist", [])
                    if not watchlist:
                        error = "No consensus watchlist available."
                    else:
                        alloc = allocate_portfolio(
                            watchlist=watchlist,
                            total_dollars=dollars,
                            strategy=strategy,
                            max_positions=int(max_positions) if max_positions else None,
                            max_single_pct=float(max_weight) if max_weight else None,
                            fractional_shares=fractional,
                            exclude_red=exclude_red,
                        )
                        allocation = {
                            "total_investment": alloc.total_investment,
                            "strategy": alloc.strategy,
                            "num_positions": alloc.num_positions,
                            "cash_invested": alloc.cash_invested,
                            "cash_remaining": alloc.cash_remaining,
                            "largest_position_pct": alloc.largest_position_pct,
                            "smallest_position_pct": alloc.smallest_position_pct,
                            "effective_positions": alloc.effective_positions,
                            "positions": [asdict(p) for p in alloc.positions],
                            "skipped": alloc.skipped,
                        }
        except ValueError:
            error = "Invalid input. Please enter valid numbers."
        except Exception as e:
            error = f"Allocation failed: {e}"

    return render_template(
        "allocator.html", allocation=allocation, error=error, form=form_data
    )


@app.route("/simulate", methods=["GET", "POST"])
def simulate_page():
    from simulator import run_full_simulation

    report_data = None
    error = None
    form_data = {
        "dollars": float(request.args.get("dollars", 20000)),
        "years": int(request.args.get("years", 5)),
        "simulations": int(request.args.get("simulations", 10000)),
        "seed": int(request.args.get("seed", 42)),
        "monthly_contribution": float(request.args.get("monthly_contribution", 0)),
        "dividend_yield": float(request.args.get("dividend_yield", 1.5)),
        "dividend_mode": request.args.get("dividend_mode", "reinvest"),
    }

    if request.method == "POST":
        try:
            dollars = float(request.form.get("dollars", 20000))
            years = int(request.form.get("years", 5))
            simulations = int(request.form.get("simulations", 10000))
            seed = int(request.form.get("seed", 42))
            monthly_contribution = float(request.form.get("monthly_contribution", 0))
            dividend_yield_pct = float(request.form.get("dividend_yield", 1.5))
            dividend_mode = request.form.get("dividend_mode", "reinvest")

            form_data = {
                "dollars": dollars,
                "years": years,
                "simulations": simulations,
                "seed": seed,
                "monthly_contribution": monthly_contribution,
                "dividend_yield": dividend_yield_pct,
                "dividend_mode": dividend_mode,
            }

            if dollars <= 0:
                error = "Investment amount must be positive."
            elif monthly_contribution < 0:
                error = "Monthly contribution cannot be negative."
            else:
                report = run_full_simulation(
                    initial=dollars,
                    years=years,
                    num_simulations=simulations,
                    seed=seed,
                    monthly_contribution=monthly_contribution,
                    dividend_yield=dividend_yield_pct / 100,  # convert pct to decimal
                    dividend_mode=dividend_mode,
                )

                scenarios = []
                for s in report.scenarios:
                    yearly = [
                        {
                            "year": y.year,
                            "starting_value": y.starting_value,
                            "ending_value": y.ending_value,
                            "annual_return_pct": y.annual_return_pct,
                            "cumulative_return_pct": y.cumulative_return_pct,
                            "contributions_this_year": y.contributions_this_year,
                            "dividends_this_year": y.dividends_this_year,
                        }
                        for y in s.yearly
                    ]
                    scenarios.append({
                        "name": s.name,
                        "label": s.label,
                        "description": s.description,
                        "annual_return": s.annual_return,
                        "annual_volatility": s.annual_volatility,
                        "final_value": s.final_value,
                        "total_return_pct": s.total_return_pct,
                        "total_profit": s.total_profit,
                        "cagr": s.cagr,
                        "yearly": yearly,
                        "total_contributions": s.total_contributions,
                        "total_dividends": s.total_dividends,
                        "total_invested": s.total_invested,
                    })

                mc = report.monte_carlo
                report_data = {
                    "initial_investment": report.initial_investment,
                    "years": report.years,
                    "monthly_contribution": report.monthly_contribution,
                    "dividend_yield": report.dividend_yield,
                    "dividend_mode": report.dividend_mode,
                    "total_contributions": report.total_contributions,
                    "total_invested": report.total_invested,
                    "scenarios": scenarios,
                    "monte_carlo": {
                        "num_simulations": mc.num_simulations,
                        "annual_return": mc.annual_return,
                        "annual_volatility": mc.annual_volatility,
                        "p5": mc.p5,
                        "p10": mc.p10,
                        "p25": mc.p25,
                        "p50": mc.p50,
                        "p75": mc.p75,
                        "p90": mc.p90,
                        "p95": mc.p95,
                        "mean": mc.mean,
                        "prob_profit": mc.prob_profit,
                        "prob_double": mc.prob_double,
                        "prob_loss_10pct": mc.prob_loss_10pct,
                        "prob_loss_25pct": mc.prob_loss_25pct,
                        "median_path": mc.median_path,
                        "p25_path": mc.p25_path,
                        "p75_path": mc.p75_path,
                        "total_contributions": mc.total_contributions,
                        "total_invested": mc.total_invested,
                        "total_dividends_median": mc.total_dividends_median,
                        "contribution_path": mc.contribution_path,
                    },
                }
        except ValueError:
            error = "Invalid input. Please enter valid numbers."
        except Exception as e:
            error = f"Simulation failed: {e}"

    return render_template(
        "simulator.html", report=report_data, error=error, form=form_data
    )


@app.route("/schedule")
def schedule_page():
    from scheduler import check_new_filings, get_current_filing_period
    from datetime import datetime

    period = get_current_filing_period()
    filing_info = check_new_filings()

    year = datetime.now().year
    deadlines = [
        {"quarter": f"{year-1}-Q4", "quarter_end": f"{year-1}-12-31", "deadline": f"{year}-02-14"},
        {"quarter": f"{year}-Q1", "quarter_end": f"{year}-03-31", "deadline": f"{year}-05-15"},
        {"quarter": f"{year}-Q2", "quarter_end": f"{year}-06-30", "deadline": f"{year}-08-14"},
        {"quarter": f"{year}-Q3", "quarter_end": f"{year}-09-30", "deadline": f"{year}-11-14"},
        {"quarter": f"{year}-Q4", "quarter_end": f"{year}-12-31", "deadline": f"{year+1}-02-14"},
    ]

    return render_template(
        "schedule.html",
        period=period,
        filing_info=filing_info,
        deadlines=deadlines,
    )


@app.route("/signals")
def signals_page():
    """
    Signals & Timing page -- combines key indicators, news analysis,
    and purchase timing recommendations for consensus picks.
    """
    from analyzer import build_consensus

    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        return render_template(
            "signals.html", stocks=None,
            error="No cached data. Fetch filings first.",
        )

    consensus = build_consensus(all_data)

    try:
        from analyzer import resolve_consensus_tickers
        consensus = resolve_consensus_tickers(consensus)
    except Exception:
        pass

    watchlist = consensus.get("watchlist", [])
    if not watchlist:
        return render_template(
            "signals.html", stocks=None,
            error="No consensus watchlist available. Run Consensus analysis first.",
        )

    # Enrich with indicators, news, and purchase recommendations
    try:
        from indicators import analyze_stock_indicators
        from news_analyzer import analyze_stock_news
        from purchase_timing import generate_purchase_recommendation

        enriched = []
        for item in watchlist[:10]:  # Top 10 for performance
            ticker = item.get("ticker", "")
            name = item.get("name", "")
            clean = ticker.replace("-", "").replace(".", "")
            if not ticker or len(clean) > 5 or len(clean) < 1:
                continue

            # Run analysis
            indicators = analyze_stock_indicators(ticker, name)
            news = analyze_stock_news(ticker, name, max_articles=8)

            news_score = news.avg_sentiment * 100 if news else 0
            rec = generate_purchase_recommendation(
                ticker=ticker,
                name=name,
                technical_score=indicators.technical.technical_score,
                fundamental_score=indicators.fundamental.fundamental_score,
                news_score=news_score,
                consensus_score=item.get("consensus_score", 0),
                num_holders=item.get("num_holders", 0),
                direction=item.get("direction", "Steady"),
            )

            enriched.append({
                "ticker": ticker,
                "name": name,
                "consensus_score": item.get("consensus_score", 0),
                "num_holders": item.get("num_holders", 0),
                "direction": item.get("direction", "Steady"),
                "indicators": _indicators_to_dict(indicators),
                "news": _news_to_dict(news),
                "recommendation": _recommendation_to_dict(rec),
            })

    except Exception as e:
        logger.error(f"Signals analysis failed: {e}")
        return render_template(
            "signals.html", stocks=None,
            error=f"Analysis failed: {e}",
        )

    return render_template("signals.html", stocks=enriched, error=None)


@app.route("/signals/<ticker>")
def signal_detail(ticker):
    """Detailed signal analysis for a single stock."""
    from analyzer import build_consensus

    all_data = _load_cached_data()
    consensus = build_consensus(all_data) if any(v for v in all_data.values()) else {}
    watchlist = consensus.get("watchlist", [])
    item = next((w for w in watchlist if w.get("ticker", "").upper() == ticker.upper()), None)

    try:
        from indicators import analyze_stock_indicators
        from news_analyzer import analyze_stock_news
        from purchase_timing import generate_purchase_recommendation

        indicators = analyze_stock_indicators(ticker, item.get("name", "") if item else "")
        news = analyze_stock_news(ticker, item.get("name", "") if item else "", max_articles=12)

        news_score = news.avg_sentiment * 100 if news else 0
        rec = generate_purchase_recommendation(
            ticker=ticker,
            name=item.get("name", "") if item else "",
            technical_score=indicators.technical.technical_score,
            fundamental_score=indicators.fundamental.fundamental_score,
            news_score=news_score,
            consensus_score=item.get("consensus_score", 0) if item else 0,
            num_holders=item.get("num_holders", 0) if item else 0,
            direction=item.get("direction", "Steady") if item else "Steady",
        )

        stock = {
            "ticker": ticker.upper(),
            "name": item.get("name", ticker.upper()) if item else ticker.upper(),
            "consensus_score": item.get("consensus_score", 0) if item else 0,
            "num_holders": item.get("num_holders", 0) if item else 0,
            "direction": item.get("direction", "Steady") if item else "Steady",
            "indicators": _indicators_to_dict(indicators),
            "news": _news_to_dict(news),
            "recommendation": _recommendation_to_dict(rec),
        }

    except Exception as e:
        logger.error(f"Signal detail failed for {ticker}: {e}")
        return render_template(
            "signal_detail.html", stock=None,
            error=f"Analysis failed for {ticker}: {e}",
        )

    return render_template("signal_detail.html", stock=stock, error=None)


def _indicators_to_dict(ind) -> dict:
    """Convert StockIndicators dataclass to template-friendly dict."""
    t = ind.technical
    f = ind.fundamental
    return {
        "composite_score": ind.composite_score,
        "composite_signal": ind.composite_signal,
        "signal_strength": ind.signal_strength,
        "key_factors": ind.key_factors,
        "technical": {
            "score": t.technical_score,
            "signal": t.technical_signal,
            "current_price": t.current_price,
            "sma_50": t.sma_50,
            "sma_200": t.sma_200,
            "rsi_14": t.rsi_14,
            "macd_bullish": t.macd_bullish,
            "macd_histogram": t.macd_histogram,
            "bb_position": t.bb_position,
            "golden_cross": t.golden_cross,
            "death_cross": t.death_cross,
            "above_sma_50": t.above_sma_50,
            "above_sma_200": t.above_sma_200,
            "volume_ratio": t.volume_ratio,
            "pct_from_high": t.pct_from_high,
            "pct_from_low": t.pct_from_low,
            "high_52w": t.high_52w,
            "low_52w": t.low_52w,
            "error": t.error,
        },
        "fundamental": {
            "score": f.fundamental_score,
            "signal": f.fundamental_signal,
            "pe_trailing": f.pe_trailing,
            "pe_forward": f.pe_forward,
            "peg_ratio": f.peg_ratio,
            "price_to_book": f.price_to_book,
            "price_to_sales": f.price_to_sales,
            "ev_to_ebitda": f.ev_to_ebitda,
            "roe": f.roe,
            "roa": f.roa,
            "profit_margin": f.profit_margin,
            "operating_margin": f.operating_margin,
            "revenue_growth": f.revenue_growth,
            "earnings_growth": f.earnings_growth,
            "debt_to_equity": f.debt_to_equity,
            "current_ratio": f.current_ratio,
            "free_cash_flow": f.free_cash_flow,
            "fcf_yield": f.fcf_yield,
            "dividend_yield": f.dividend_yield,
            "market_cap": f.market_cap,
            "beta": f.beta,
            "error": f.error,
        },
    }


def _news_to_dict(news) -> dict:
    """Convert StockNewsAnalysis to template-friendly dict."""
    return {
        "article_count": news.article_count,
        "avg_sentiment": news.avg_sentiment,
        "positive_count": news.positive_count,
        "negative_count": news.negative_count,
        "neutral_count": news.neutral_count,
        "news_signal": news.news_signal,
        "signal_strength": news.signal_strength,
        "outlook": news.outlook,
        "growth_catalysts": news.growth_catalysts,
        "risk_factors": news.risk_factors,
        "articles": [
            {
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "published": a.published,
                "sentiment": a.sentiment,
                "sentiment_score": a.sentiment_score,
                "impact": a.impact,
            }
            for a in news.articles[:10]
        ],
        "error": news.error,
    }


def _recommendation_to_dict(rec) -> dict:
    """Convert PurchaseRecommendation to template-friendly dict."""
    def _horizon_dict(h):
        if h is None:
            return None
        return {
            "horizon": h.horizon,
            "horizon_label": h.horizon_label,
            "action": h.action,
            "confidence": h.confidence,
            "target_price": h.target_price,
            "expected_return_pct": h.expected_return_pct,
            "entry_strategy": h.entry_strategy,
            "rationale": h.rationale,
        }

    def _buy_zone_dict(bz):
        if bz is None:
            return None
        return {
            "ideal_entry": bz.ideal_entry,
            "buy_below": bz.buy_below,
            "strong_buy_below": bz.strong_buy_below,
            "stop_loss": bz.stop_loss,
            "risk_reward_ratio": bz.risk_reward_ratio,
        }

    return {
        "current_price": rec.current_price,
        "as_of": rec.as_of,
        "overall_action": rec.overall_action,
        "overall_confidence": rec.overall_confidence,
        "summary": rec.summary,
        "buy_zone": _buy_zone_dict(rec.buy_zone),
        "support_levels": [
            {"price": s.price, "source": s.source, "strength": s.strength}
            for s in rec.support_levels
        ],
        "resistance_levels": [
            {"price": r.price, "source": r.source, "strength": r.strength}
            for r in rec.resistance_levels
        ],
        "short_term": _horizon_dict(rec.short_term),
        "medium_term": _horizon_dict(rec.medium_term),
        "long_term": _horizon_dict(rec.long_term),
        "bull_case": rec.bull_case,
        "bear_case": rec.bear_case,
        "technical_score": rec.technical_score,
        "fundamental_score": rec.fundamental_score,
        "news_score": rec.news_score,
        "consensus_score": rec.consensus_score,
        "error": rec.error,
    }


# ─── API Endpoints (AJAX) ───────────────────────────────────────────────────


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    """Start fetching data in background thread."""
    with _task_lock:
        if _task_state["running"]:
            return jsonify({"status": "already_running"})

    quarters = int(request.json.get("quarters", 2)) if request.is_json else 2

    def _do_fetch():
        try:
            from data_fetcher import fetch_all_investors

            _set_task(running=True, message="Fetching 13F filings from SEC EDGAR...")
            fetch_all_investors(num_quarters=quarters)
            _set_task(running=False, message="Fetch complete!", done=True)
        except Exception as e:
            _set_task(running=False, error=str(e), done=True)

    thread = threading.Thread(target=_do_fetch, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/fetch-status")
def api_fetch_status():
    with _task_lock:
        return jsonify(dict(_task_state))


@app.route("/api/fetch-reset", methods=["POST"])
def api_fetch_reset():
    _set_task()
    return jsonify({"status": "reset"})


# ─── Template Filters ────────────────────────────────────────────────────────


@app.template_filter("currency")
def currency_filter(value):
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


@app.template_filter("pct")
def pct_filter(value):
    try:
        return f"{float(value):,.1f}%"
    except (ValueError, TypeError):
        return "0.0%"


@app.template_filter("big_number")
def big_number_filter(value):
    try:
        v = float(value)
        if v >= 1_000_000:
            return f"${v / 1_000_000:,.1f}T"
        if v >= 1_000:
            return f"${v / 1_000:,.1f}B"
        return f"${v:,.1f}M"
    except (ValueError, TypeError):
        return "$0"


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
