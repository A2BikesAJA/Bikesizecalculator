"""
Scenario Simulator for Coattail Investor Tool.

Projects likely returns for a given dollar investment over a multi-year
horizon using Monte Carlo simulation grounded in historical return
assumptions for coattail / consensus-pick strategies.

Historical context (used to calibrate assumptions):
  - Academic studies of 13F-based copycat strategies show annualized
    alpha of roughly 1-4% above the S&P 500 after the filing-delay lag.
  - Large-cap consensus picks tend to have lower volatility than the
    broad market (~14-18% annual vs ~16-20%).
  - The strategy's edge comes from stock selection, not market timing,
    so market-level drawdowns still apply.

The simulator uses these priors combined with user-tunable parameters to
run thousands of randomised paths and summarise the probability distribution
of outcomes.
"""

import logging
import math
import random
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Default Assumptions ─────────────────────────────────────────────────────
# These are the calibrated priors.  Users can override via CLI flags.

# Annualized return assumptions by scenario (nominal, before inflation)
SCENARIO_DEFAULTS = {
    "bull": {
        "label": "Bull Case",
        "annual_return": 0.16,      # 16% — strong market + alpha
        "annual_volatility": 0.16,
        "description": "Sustained bull market; consensus picks outperform",
    },
    "base": {
        "label": "Base Case",
        "annual_return": 0.11,      # 11% — historical equity avg + small alpha
        "annual_volatility": 0.18,
        "description": "Average market conditions; modest coattail alpha",
    },
    "bear": {
        "label": "Bear Case",
        "annual_return": 0.04,      # 4% — sluggish market, alpha compressed
        "annual_volatility": 0.22,
        "description": "Below-average market; limited alpha, higher vol",
    },
    "crash": {
        "label": "Severe Bear",
        "annual_return": -0.02,     # -2% — prolonged downturn
        "annual_volatility": 0.28,
        "description": "Extended downturn with elevated volatility",
    },
}

# Monte Carlo defaults
DEFAULT_SIMULATIONS = 10_000
DEFAULT_YEARS = 5
QUARTERLY_REBALANCE_DRAG = 0.001  # 0.1% per quarter for turnover/slippage


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class YearSnapshot:
    """Portfolio state at the end of a given year."""
    year: int
    starting_value: float
    ending_value: float
    annual_return_pct: float
    cumulative_return_pct: float


@dataclass
class ScenarioResult:
    """Result of a single deterministic scenario projection."""
    name: str
    label: str
    description: str
    initial_investment: float
    years: int
    annual_return: float
    annual_volatility: float
    final_value: float
    total_return_pct: float
    total_profit: float
    cagr: float
    yearly: list[YearSnapshot]


@dataclass
class MonteCarloResult:
    """Aggregated results of Monte Carlo simulation."""
    initial_investment: float
    years: int
    num_simulations: int
    annual_return: float
    annual_volatility: float
    # Percentile outcomes (final portfolio value)
    p5: float           # 5th percentile (worst realistic)
    p10: float
    p25: float
    p50: float          # median
    p75: float
    p90: float
    p95: float          # 95th percentile (best realistic)
    mean: float
    # Probability metrics
    prob_profit: float          # P(ending > starting)
    prob_double: float          # P(ending > 2x starting)
    prob_loss_10pct: float      # P(loss > 10%)
    prob_loss_25pct: float      # P(loss > 25%)
    # Year-by-year median path
    median_path: list[float]    # [year0_val, year1_val, ..., yearN_val]
    p25_path: list[float]
    p75_path: list[float]


@dataclass
class SimulationReport:
    """Complete simulation output combining scenarios + Monte Carlo."""
    initial_investment: float
    years: int
    scenarios: list[ScenarioResult]
    monte_carlo: MonteCarloResult


# ─── Deterministic Scenario Projections ──────────────────────────────────────


def project_scenario(
    initial: float,
    years: int,
    annual_return: float,
    annual_volatility: float,
    name: str = "custom",
    label: str = "Custom",
    description: str = "",
) -> ScenarioResult:
    """
    Project a deterministic compound-growth path for a single scenario.

    This is the "expected path" — no randomness, just compound growth at
    the assumed annual return with quarterly rebalance drag.
    """
    quarterly_return = (1 + annual_return) ** 0.25 - 1
    quarterly_drag = QUARTERLY_REBALANCE_DRAG

    value = initial
    yearly = []

    for yr in range(1, years + 1):
        start_val = value
        for _q in range(4):
            value *= (1 + quarterly_return - quarterly_drag)
        annual_ret = (value - start_val) / start_val * 100
        cum_ret = (value - initial) / initial * 100
        yearly.append(YearSnapshot(
            year=yr,
            starting_value=round(start_val, 2),
            ending_value=round(value, 2),
            annual_return_pct=round(annual_ret, 2),
            cumulative_return_pct=round(cum_ret, 2),
        ))

    total_return = (value - initial) / initial
    cagr = (value / initial) ** (1 / years) - 1 if years > 0 else 0

    return ScenarioResult(
        name=name,
        label=label,
        description=description,
        initial_investment=initial,
        years=years,
        annual_return=annual_return,
        annual_volatility=annual_volatility,
        final_value=round(value, 2),
        total_return_pct=round(total_return * 100, 2),
        total_profit=round(value - initial, 2),
        cagr=round(cagr * 100, 2),
        yearly=yearly,
    )


def project_all_scenarios(
    initial: float,
    years: int = DEFAULT_YEARS,
    custom_scenarios: dict | None = None,
) -> list[ScenarioResult]:
    """Run all predefined scenarios (bull, base, bear, crash)."""
    scenarios = custom_scenarios or SCENARIO_DEFAULTS
    results = []
    for name, params in scenarios.items():
        result = project_scenario(
            initial=initial,
            years=years,
            annual_return=params["annual_return"],
            annual_volatility=params["annual_volatility"],
            name=name,
            label=params["label"],
            description=params["description"],
        )
        results.append(result)
    return results


# ─── Monte Carlo Simulation ─────────────────────────────────────────────────


def run_monte_carlo(
    initial: float,
    years: int = DEFAULT_YEARS,
    annual_return: float = 0.11,
    annual_volatility: float = 0.18,
    num_simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
) -> MonteCarloResult:
    """
    Run a Monte Carlo simulation of portfolio growth.

    Uses geometric Brownian motion (log-normal returns) to model quarterly
    portfolio returns, incorporating rebalance drag.

    Args:
        initial:            Starting dollar amount.
        years:              Investment horizon.
        annual_return:      Expected annualized return (e.g. 0.11 = 11%).
        annual_volatility:  Annualized volatility (e.g. 0.18 = 18%).
        num_simulations:    Number of random paths to generate.
        seed:               Optional RNG seed for reproducibility.
    """
    if seed is not None:
        random.seed(seed)

    num_quarters = years * 4
    # Convert annual params to quarterly
    q_mu = (annual_return - 0.5 * annual_volatility ** 2) / 4
    q_sigma = annual_volatility / (4 ** 0.5)
    q_drag = QUARTERLY_REBALANCE_DRAG

    # Storage: all final values, and year-end values for path percentiles
    final_values = []
    # year_end_values[year_index] = list of values at that year-end across all sims
    year_end_values = [[] for _ in range(years + 1)]  # index 0 = start

    for _ in range(num_simulations):
        value = initial
        year_end_values[0].append(value)

        for yr in range(1, years + 1):
            for _q in range(4):
                # Log-normal quarterly return
                z = random.gauss(0, 1)
                q_return = math.exp(q_mu + q_sigma * z) - 1
                value *= (1 + q_return - q_drag)
                value = max(value, 0)  # floor at zero

            year_end_values[yr].append(value)

        final_values.append(value)

    # Sort for percentiles
    final_values.sort()

    def percentile(data, pct):
        idx = int(len(data) * pct / 100)
        idx = min(idx, len(data) - 1)
        return data[idx]

    # Compute paths at p25, p50, p75
    median_path = []
    p25_path = []
    p75_path = []
    for yr in range(years + 1):
        vals = sorted(year_end_values[yr])
        median_path.append(round(percentile(vals, 50), 2))
        p25_path.append(round(percentile(vals, 25), 2))
        p75_path.append(round(percentile(vals, 75), 2))

    # Probability metrics
    n = len(final_values)
    prob_profit = sum(1 for v in final_values if v > initial) / n
    prob_double = sum(1 for v in final_values if v > 2 * initial) / n
    prob_loss_10 = sum(1 for v in final_values if v < initial * 0.90) / n
    prob_loss_25 = sum(1 for v in final_values if v < initial * 0.75) / n
    mean_val = sum(final_values) / n

    return MonteCarloResult(
        initial_investment=initial,
        years=years,
        num_simulations=num_simulations,
        annual_return=annual_return,
        annual_volatility=annual_volatility,
        p5=round(percentile(final_values, 5), 2),
        p10=round(percentile(final_values, 10), 2),
        p25=round(percentile(final_values, 25), 2),
        p50=round(percentile(final_values, 50), 2),
        p75=round(percentile(final_values, 75), 2),
        p90=round(percentile(final_values, 90), 2),
        p95=round(percentile(final_values, 95), 2),
        mean=round(mean_val, 2),
        prob_profit=round(prob_profit * 100, 1),
        prob_double=round(prob_double * 100, 1),
        prob_loss_10pct=round(prob_loss_10 * 100, 1),
        prob_loss_25pct=round(prob_loss_25 * 100, 1),
        median_path=median_path,
        p25_path=p25_path,
        p75_path=p75_path,
    )


# ─── Full Simulation ────────────────────────────────────────────────────────


def run_full_simulation(
    initial: float,
    years: int = DEFAULT_YEARS,
    num_simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = 42,
) -> SimulationReport:
    """
    Run the complete simulation: deterministic scenarios + Monte Carlo.

    Args:
        initial:          Dollar amount to invest.
        years:            Investment horizon in years.
        num_simulations:  Number of Monte Carlo paths.
        seed:             RNG seed (42 for reproducibility by default).

    Returns:
        SimulationReport with all scenarios and Monte Carlo results.
    """
    logger.info(
        f"Running simulation: ${initial:,.0f} over {years} years "
        f"({num_simulations:,} Monte Carlo paths)"
    )

    # Deterministic scenarios
    scenarios = project_all_scenarios(initial, years)

    # Monte Carlo (uses base-case assumptions)
    base = SCENARIO_DEFAULTS["base"]
    mc = run_monte_carlo(
        initial=initial,
        years=years,
        annual_return=base["annual_return"],
        annual_volatility=base["annual_volatility"],
        num_simulations=num_simulations,
        seed=seed,
    )

    return SimulationReport(
        initial_investment=initial,
        years=years,
        scenarios=scenarios,
        monte_carlo=mc,
    )
