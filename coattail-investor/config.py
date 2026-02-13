"""
Configuration for the Coattail Investor Research Tool.

Contains tracked investors, API settings, and application configuration.
"""

import os
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ─── SEC EDGAR Settings ─────────────────────────────────────────────────────

# REQUIRED: SEC mandates a User-Agent with contact info
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "CoattailInvestor/1.0 (coattail-investor@example.com)"
)

# Rate limiting: SEC allows max 10 req/sec; we use 0.15s minimum delay
SEC_REQUEST_DELAY = 0.15

# Base URLs
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
SEC_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# ─── Optional API Keys ──────────────────────────────────────────────────────

# For valuation data (yfinance is used by default—no key needed)
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

# ─── Tracked Investors ───────────────────────────────────────────────────────
#
# Each entry: {
#   "name": display name,
#   "entity": filing entity name,
#   "cik": SEC CIK number (zero-padded to 10 digits for API),
#   "category": investor style category,
#   "notes": any relevant notes,
# }

TRACKED_INVESTORS = [
    # ── Value / Buy-and-Hold Managers ────────────────────────────────────
    {
        "name": "Warren Buffett",
        "entity": "Berkshire Hathaway Inc",
        "cik": "0001067983",
        "category": "value",
        "notes": "Legendary value investor; very low turnover",
    },
    {
        "name": "Seth Klarman",
        "entity": "Baupost Group LLC",
        "cik": "0001061768",
        "category": "value",
        "notes": "Deep value; margin-of-safety focused",
    },
    {
        "name": "Howard Marks",
        "entity": "Oaktree Capital Management LP",
        "cik": "0001403528",
        "category": "value",
        "notes": "Distressed debt specialist; contrarian",
    },
    {
        "name": "Mohnish Pabrai",
        "entity": "Pabrai Investment Funds",
        "cik": "0001173334",
        "category": "value",
        "notes": "Concentrated value; Buffett disciple",
    },
    {
        "name": "Li Lu",
        "entity": "Himalaya Capital Management LLC",
        "cik": "0001709323",
        "category": "value",
        "notes": "Value-oriented; China expertise",
    },
    {
        "name": "Chuck Akre",
        "entity": "Akre Capital Management LLC",
        "cik": "0001112520",
        "category": "value",
        "notes": "Compounders; long-term quality growth",
    },
    # ── Activist / High-Conviction Managers ──────────────────────────────
    {
        "name": "Bill Ackman",
        "entity": "Pershing Square Capital Management LP",
        "cik": "0001336528",
        "category": "activist",
        "notes": "Concentrated activist; high conviction",
    },
    {
        "name": "David Einhorn",
        "entity": "Greenlight Capital Inc",
        "cik": "0001079114",
        "category": "activist",
        "notes": "Value with activist bent; notable short seller",
    },
    {
        "name": "Nelson Peltz",
        "entity": "Trian Fund Management LP",
        "cik": "0001345471",
        "category": "activist",
        "notes": "Operational activist; consumer/industrial focus",
    },
    {
        "name": "Dan Loeb",
        "entity": "Third Point LLC",
        "cik": "0001040273",
        "category": "activist",
        "notes": "Event-driven activist",
    },
    # ── Growth-Oriented Managers ─────────────────────────────────────────
    {
        "name": "Chase Coleman",
        "entity": "Tiger Global Management LLC",
        "cik": "0001167483",
        "category": "growth",
        "notes": "TMT growth; Tiger Cub",
    },
    {
        "name": "Brad Gerstner",
        "entity": "Altimeter Capital Management LP",
        "cik": "0001599738",
        "category": "growth",
        "notes": "Tech growth; internet/software focus",
    },
    {
        "name": "Stanley Druckenmiller",
        "entity": "Duquesne Family Office LLC",
        "cik": "0001536411",
        "category": "growth",
        "notes": "Macro-oriented; flexible style",
    },
    # ── Quantitative / Systematic ────────────────────────────────────────
    {
        "name": "Renaissance Technologies",
        "entity": "Renaissance Technologies LLC",
        "cik": "0001037389",
        "category": "quant",
        "notes": "Reference only — extremely high turnover; Medallion fund",
    },
]

# ─── Analysis Settings ───────────────────────────────────────────────────────

# Minimum number of investors holding a stock for it to be a "consensus" pick
CONSENSUS_MIN_HOLDERS = 3

# Threshold for significant position change (20%)
SIGNIFICANT_CHANGE_PCT = 0.20

# Number of top consensus picks to highlight
TOP_CONSENSUS_COUNT = 10

# Watchlist size
WATCHLIST_SIZE = 20

# Valuation traffic light thresholds (price change since filing quarter end)
VALUATION_GREEN_MAX = 0.10   # ≤10% move
VALUATION_YELLOW_MAX = 0.25  # 10-25% move
# >25% = RED

# ─── Portfolio Allocation Settings ───────────────────────────────────────────

# Maximum weight for any single position (percentage)
ALLOC_MAX_SINGLE_POSITION_PCT = 25.0

# Minimum dollar amount for a position to be included
ALLOC_MIN_POSITION_SIZE = 100.0

# Weighting strategy multipliers for the "conviction" strategy
# These tune how much each signal boosts/penalises the raw score weight
ALLOC_STRATEGY_WEIGHTS = {
    "direction_adding_boost": 1.25,
    "direction_reducing_penalty": 0.75,
    "valuation_green_boost": 1.10,
    "valuation_yellow_penalty": 0.90,
    "valuation_red_penalty": 0.70,
}

# ─── Filing Deadlines ───────────────────────────────────────────────────────
# 13F filings are due 45 days after quarter-end

QUARTER_DEADLINES = {
    "Q1": {"quarter_end": "03-31", "filing_deadline": "05-15"},
    "Q2": {"quarter_end": "06-30", "filing_deadline": "08-14"},
    "Q3": {"quarter_end": "09-30", "filing_deadline": "11-14"},
    "Q4": {"quarter_end": "12-31", "filing_deadline": "02-14"},
}

# ─── Logging ─────────────────────────────────────────────────────────────────

import logging

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)


def get_investor_by_name(name: str) -> dict | None:
    """Look up a tracked investor by name (case-insensitive partial match)."""
    name_lower = name.lower()
    for inv in TRACKED_INVESTORS:
        if name_lower in inv["name"].lower() or name_lower in inv["entity"].lower():
            return inv
    return None


def get_investors_by_category(category: str) -> list[dict]:
    """Get all tracked investors in a given category."""
    return [inv for inv in TRACKED_INVESTORS if inv["category"] == category]


def add_investor(name: str, entity: str, cik: str, category: str, notes: str = "") -> None:
    """Add a new investor to the tracking list (runtime only)."""
    cik_padded = cik.zfill(10)
    TRACKED_INVESTORS.append({
        "name": name,
        "entity": entity,
        "cik": cik_padded,
        "category": category,
        "notes": notes,
    })


def remove_investor(name: str) -> bool:
    """Remove an investor from the tracking list by name (runtime only)."""
    inv = get_investor_by_name(name)
    if inv:
        TRACKED_INVESTORS.remove(inv)
        return True
    return False
