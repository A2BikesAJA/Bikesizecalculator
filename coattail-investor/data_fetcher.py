"""
SEC EDGAR Data Fetcher for 13F filings.

Handles fetching, parsing, and caching of institutional investor holdings data
from the SEC EDGAR system.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from config import (
    CACHE_DIR,
    DATA_DIR,
    SEC_ARCHIVES_URL,
    SEC_COMPANY_TICKERS_URL,
    SEC_REQUEST_DELAY,
    SEC_SUBMISSIONS_URL,
    SEC_USER_AGENT,
    TRACKED_INVESTORS,
)

logger = logging.getLogger(__name__)

# ─── Rate-Limited Session ────────────────────────────────────────────────────


class SECSession:
    """HTTP session with SEC-compliant rate limiting and headers."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0.0

    def get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request."""
        elapsed = time.time() - self._last_request_time
        if elapsed < SEC_REQUEST_DELAY:
            time.sleep(SEC_REQUEST_DELAY - elapsed)

        logger.debug(f"GET {url}")
        self._last_request_time = time.time()
        response = self.session.get(url, timeout=30, **kwargs)
        response.raise_for_status()
        return response


_session = SECSession()

# ─── CUSIP-to-Ticker Mapping ────────────────────────────────────────────────

_ticker_map_cache: dict | None = None


def _load_sec_company_tickers() -> dict[str, dict]:
    """Load the SEC company tickers JSON for CIK/ticker lookups."""
    cache_file = CACHE_DIR / "company_tickers.json"
    # Refresh if older than 7 days
    if cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < 7:
            with open(cache_file) as f:
                return json.load(f)

    logger.info("Fetching SEC company tickers mapping...")
    try:
        resp = _session.get(SEC_COMPANY_TICKERS_URL)
        data = resp.json()
        with open(cache_file, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        logger.warning(f"Failed to fetch company tickers: {e}")
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return {}


def _build_cusip_ticker_map() -> dict[str, str]:
    """
    Build a local CUSIP-to-ticker mapping from cached filing data.
    This grows over time as more filings are parsed.
    """
    map_file = CACHE_DIR / "cusip_ticker_map.json"
    if map_file.exists():
        with open(map_file) as f:
            return json.load(f)
    return {}


def _save_cusip_ticker_map(mapping: dict[str, str]) -> None:
    map_file = CACHE_DIR / "cusip_ticker_map.json"
    with open(map_file, "w") as f:
        json.dump(mapping, f, indent=2)


def _get_ticker_for_cusip(cusip: str, issuer_name: str = "") -> str:
    """Attempt to resolve a CUSIP to a ticker symbol."""
    mapping = _build_cusip_ticker_map()
    if cusip in mapping:
        return mapping[cusip]

    # Try to match by issuer name against SEC tickers
    tickers_data = _load_sec_company_tickers()
    if issuer_name:
        name_lower = issuer_name.lower()
        for _key, entry in tickers_data.items():
            if entry.get("title", "").lower() == name_lower:
                ticker = entry.get("ticker", "")
                if ticker:
                    mapping[cusip] = ticker
                    _save_cusip_ticker_map(mapping)
                    return ticker

    # Return CUSIP as fallback
    return cusip


# ─── Filing Discovery ───────────────────────────────────────────────────────


def fetch_submissions(cik: str) -> dict:
    """Fetch the submissions JSON for a given CIK from EDGAR."""
    cache_file = CACHE_DIR / f"submissions_{cik}.json"

    # Cache for 1 day
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            with open(cache_file) as f:
                return json.load(f)

    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    logger.info(f"Fetching submissions for CIK {cik}...")
    resp = _session.get(url)
    data = resp.json()

    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)

    return data


def find_13f_filings(cik: str, count: int = 10) -> list[dict]:
    """
    Find the most recent 13F-HR filings for a given CIK.

    Returns a list of dicts with keys: accessionNumber, filingDate, primaryDocument, form.
    """
    submissions = fetch_submissions(cik)
    recent = submissions.get("filings", {}).get("recent", {})

    if not recent:
        logger.warning(f"No recent filings found for CIK {cik}")
        return []

    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings_13f = []
    seen_quarters = set()

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            filing_date = filing_dates[i]
            accession = accession_numbers[i]
            quarter = _filing_date_to_quarter(filing_date)

            # For amendments, only keep the most recent per quarter
            if form == "13F-HR/A":
                if quarter in seen_quarters:
                    continue
            # If we already have an amendment for this quarter, skip the original
            if quarter in seen_quarters and form == "13F-HR":
                continue

            seen_quarters.add(quarter)
            filings_13f.append({
                "accessionNumber": accession,
                "filingDate": filing_date,
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "form": form,
                "quarter": quarter,
            })

            if len(filings_13f) >= count:
                break

    return filings_13f


def _filing_date_to_quarter(filing_date: str) -> str:
    """Convert a filing date to the quarter it reports on.

    13F filings are due 45 days after quarter-end, so a filing date
    roughly maps back to the preceding quarter-end.
    """
    dt = datetime.strptime(filing_date, "%Y-%m-%d")
    year = dt.year
    month = dt.month

    if month <= 2 or (month == 3 and dt.day <= 15):
        # Q4 of previous year (filed by Feb 14)
        return f"{year - 1}-Q4"
    elif month <= 5 or (month == 6 and dt.day <= 15):
        # Q1 (filed by May 15)
        return f"{year}-Q1"
    elif month <= 8 or (month == 9 and dt.day <= 15):
        # Q2 (filed by Aug 14)
        return f"{year}-Q2"
    else:
        # Q3 (filed by Nov 14)
        return f"{year}-Q3"


# ─── Filing Parsing ─────────────────────────────────────────────────────────


def fetch_filing_index(cik: str, accession_number: str) -> str:
    """Fetch the filing index page to find the information table document."""
    accession_clean = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/"
    resp = _session.get(url)
    return resp.text, url


def find_infotable_url(index_html: str, base_url: str) -> str | None:
    """Parse a filing index page to find the information table XML document."""
    soup = BeautifulSoup(index_html, "html.parser")

    # Look for links to the information table
    for a_tag in soup.find_all("a"):
        href = a_tag.get("href", "")
        text = a_tag.get_text("", strip=True).lower()
        href_lower = href.lower()

        # Common patterns for the 13F information table
        if any(pattern in href_lower for pattern in [
            "infotable", "information_table", "13f_infotable",
            "13finfotable", "info_table",
        ]):
            if href.startswith("http"):
                return href
            return base_url + href.split("/")[-1]

        if "information table" in text and href.endswith(".xml"):
            if href.startswith("http"):
                return href
            return base_url + href.split("/")[-1]

    # Fallback: look at the table of filing documents
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        for cell in cells:
            cell_text = cell.get_text("", strip=True).lower()
            if "information table" in cell_text or "infotable" in cell_text:
                link = row.find("a")
                if link:
                    href = link.get("href", "")
                    if href.startswith("http"):
                        return href
                    return base_url + href.split("/")[-1]

    # Last resort: look for any XML file that might be the info table
    for a_tag in soup.find_all("a"):
        href = a_tag.get("href", "")
        if href.endswith(".xml") and "primary" not in href.lower():
            if href.startswith("http"):
                return href
            return base_url + href.split("/")[-1]

    return None


def parse_13f_xml(xml_content: str) -> list[dict]:
    """
    Parse a 13F information table XML document and extract holdings.

    Returns a list of holdings dicts with keys:
    - nameOfIssuer, titleOfClass, cusip, value (in thousands),
    - shares, shareType, putCall, investmentDiscretion, votingAuthSole,
    - votingAuthShared, votingAuthNone
    """
    holdings = []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        # Try cleaning up common XML issues
        xml_content = xml_content.strip()
        if not xml_content.startswith("<?xml"):
            xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error(f"Failed to parse 13F XML: {e}")
            return _parse_13f_html_fallback(xml_content)

    # Handle various XML namespace patterns used in 13F filings
    namespaces = {
        "ns": "http://www.sec.gov/document/thirteenf/informationtable",
        "ns2": "http://www.sec.gov/document/thirteenf-2/informationtable",
    }

    info_entries = []
    for ns_prefix, ns_uri in namespaces.items():
        info_entries = root.findall(f".//{{{ns_uri}}}infoTable")
        if info_entries:
            break

    # Try without namespace
    if not info_entries:
        info_entries = root.findall(".//infoTable")

    # Try finding any element that looks like an entry
    if not info_entries:
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag.lower() == "infotable":
                info_entries.append(elem)

    for entry in info_entries:
        holding = _extract_holding_from_xml_entry(entry)
        if holding:
            holdings.append(holding)

    if not holdings:
        logger.warning("No holdings found in XML, trying HTML fallback")
        return _parse_13f_html_fallback(xml_content)

    return holdings


def _extract_holding_from_xml_entry(entry: ET.Element) -> dict | None:
    """Extract a single holding from an infoTable XML entry."""

    def get_text(parent: ET.Element, tag_name: str) -> str:
        """Find element by local name, ignoring namespace."""
        for elem in parent.iter():
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_tag.lower() == tag_name.lower():
                return (elem.text or "").strip()
        return ""

    def get_nested_text(parent: ET.Element, parent_tag: str, child_tag: str) -> str:
        for elem in parent.iter():
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_tag.lower() == parent_tag.lower():
                return get_text(elem, child_tag)
        return ""

    name = get_text(entry, "nameOfIssuer")
    if not name:
        return None

    value_str = get_text(entry, "value")
    shares_str = get_nested_text(entry, "shrsOrPrnAmt", "sshPrnamt")
    share_type = get_nested_text(entry, "shrsOrPrnAmt", "sshPrnamtType")

    try:
        value = int(value_str) if value_str else 0
    except ValueError:
        value = 0

    try:
        shares = int(shares_str) if shares_str else 0
    except ValueError:
        shares = 0

    return {
        "nameOfIssuer": name,
        "titleOfClass": get_text(entry, "titleOfClass"),
        "cusip": get_text(entry, "cusip"),
        "value": value,  # in thousands of USD
        "shares": shares,
        "shareType": share_type,
        "putCall": get_text(entry, "putCall"),
        "investmentDiscretion": get_text(entry, "investmentDiscretion"),
        "votingAuthSole": get_text(entry, "Sole") or get_text(entry, "sole"),
        "votingAuthShared": get_text(entry, "Shared") or get_text(entry, "shared"),
        "votingAuthNone": get_text(entry, "None") or get_text(entry, "none"),
    }


def _parse_13f_html_fallback(content: str) -> list[dict]:
    """Fallback parser for 13F filings that are HTML instead of XML."""
    holdings = []
    soup = BeautifulSoup(content, "html.parser")

    # Look for table rows with holding data
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[1:]:  # Skip header row
            cells = row.find_all(["td", "th"])
            if len(cells) >= 4:
                texts = [c.get_text("", strip=True) for c in cells]
                # Try to identify which columns are which
                name = texts[0] if texts[0] else ""
                if not name or name.lower() in ("name of issuer", ""):
                    continue

                cusip = ""
                value = 0
                shares = 0

                for t in texts[1:]:
                    # CUSIP is typically 9 chars alphanumeric
                    if len(t) == 9 and t.isalnum():
                        cusip = t
                    elif t.replace(",", "").replace(".", "").isdigit():
                        num = int(t.replace(",", "").split(".")[0])
                        if value == 0:
                            value = num
                        elif shares == 0:
                            shares = num

                if name:
                    holdings.append({
                        "nameOfIssuer": name,
                        "titleOfClass": texts[1] if len(texts) > 1 else "",
                        "cusip": cusip,
                        "value": value,
                        "shares": shares,
                        "shareType": "SH",
                        "putCall": "",
                        "investmentDiscretion": "",
                        "votingAuthSole": "",
                        "votingAuthShared": "",
                        "votingAuthNone": "",
                    })

    return holdings


# ─── High-Level Fetch Functions ──────────────────────────────────────────────


def fetch_holdings_for_investor(
    investor: dict, num_quarters: int = 4
) -> list[dict]:
    """
    Fetch 13F holdings for a tracked investor across recent quarters.

    Returns a list of quarterly filing dicts, each containing:
    - investor_name, cik, filing_date, quarter, holdings (list)
    """
    cik = investor["cik"]
    name = investor["name"]
    cache_file = DATA_DIR / f"holdings_{cik}.json"

    # Check cache (refresh if older than 12 hours)
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 12:
            logger.info(f"Using cached holdings for {name}")
            with open(cache_file) as f:
                return json.load(f)

    logger.info(f"Fetching 13F filings for {name} (CIK: {cik})...")

    try:
        filings = find_13f_filings(cik, count=num_quarters)
    except requests.HTTPError as e:
        logger.error(f"Failed to fetch submissions for {name}: {e}")
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return []

    quarterly_holdings = []

    for filing in filings:
        accession = filing["accessionNumber"]
        quarter = filing["quarter"]

        logger.info(f"  Parsing {filing['form']} for {quarter} (filed {filing['filingDate']})...")

        try:
            index_html, base_url = fetch_filing_index(cik, accession)
            infotable_url = find_infotable_url(index_html, base_url)

            if not infotable_url:
                logger.warning(f"  Could not find info table for {name} {quarter}")
                continue

            resp = _session.get(infotable_url)
            holdings = parse_13f_xml(resp.text)

            if not holdings:
                logger.warning(f"  No holdings parsed for {name} {quarter}")
                continue

            # Resolve tickers for holdings
            for h in holdings:
                h["ticker"] = _get_ticker_for_cusip(h["cusip"], h["nameOfIssuer"])

            total_value = sum(h["value"] for h in holdings)
            for h in holdings:
                h["portfolioWeight"] = (h["value"] / total_value * 100) if total_value > 0 else 0

            quarterly_holdings.append({
                "investor_name": name,
                "cik": cik,
                "filing_date": filing["filingDate"],
                "quarter": quarter,
                "form": filing["form"],
                "total_value_thousands": total_value,
                "num_holdings": len(holdings),
                "holdings": holdings,
            })

        except Exception as e:
            logger.error(f"  Error parsing filing for {name} {quarter}: {e}")
            continue

    # Cache results
    if quarterly_holdings:
        with open(cache_file, "w") as f:
            json.dump(quarterly_holdings, f, indent=2)

    return quarterly_holdings


def fetch_all_investors(num_quarters: int = 2) -> dict[str, list[dict]]:
    """
    Fetch holdings for all tracked investors.

    Returns a dict mapping investor name to list of quarterly holdings.
    """
    all_data = {}
    total = len(TRACKED_INVESTORS)

    for i, investor in enumerate(TRACKED_INVESTORS):
        logger.info(f"[{i + 1}/{total}] Fetching {investor['name']}...")
        try:
            holdings = fetch_holdings_for_investor(investor, num_quarters)
            all_data[investor["name"]] = holdings
        except Exception as e:
            logger.error(f"Failed to fetch {investor['name']}: {e}")
            all_data[investor["name"]] = []

    # Save aggregate data
    summary_file = DATA_DIR / "all_holdings_summary.json"
    summary = {}
    for name, quarters in all_data.items():
        summary[name] = {
            "quarters_available": len(quarters),
            "latest_quarter": quarters[0]["quarter"] if quarters else "N/A",
            "latest_filing_date": quarters[0]["filing_date"] if quarters else "N/A",
            "latest_num_holdings": quarters[0]["num_holdings"] if quarters else 0,
        }

    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    return all_data


def get_filing_status() -> list[dict]:
    """Check which tracked investors have filed for the most recent quarter."""
    now = datetime.now()
    year = now.year
    month = now.month

    # Determine the most recent expected quarter
    if month <= 2:
        expected_quarter = f"{year - 1}-Q3"
        next_quarter = f"{year - 1}-Q4"
    elif month <= 5:
        expected_quarter = f"{year - 1}-Q4"
        next_quarter = f"{year}-Q1"
    elif month <= 8:
        expected_quarter = f"{year}-Q1"
        next_quarter = f"{year}-Q2"
    elif month <= 11:
        expected_quarter = f"{year}-Q2"
        next_quarter = f"{year}-Q3"
    else:
        expected_quarter = f"{year}-Q3"
        next_quarter = f"{year}-Q4"

    statuses = []
    for investor in TRACKED_INVESTORS:
        cache_file = DATA_DIR / f"holdings_{investor['cik']}.json"
        latest_quarter = "N/A"
        filing_date = "N/A"

        if cache_file.exists():
            with open(cache_file) as f:
                data = json.load(f)
                if data:
                    latest_quarter = data[0].get("quarter", "N/A")
                    filing_date = data[0].get("filing_date", "N/A")

        has_filed = latest_quarter == expected_quarter or latest_quarter == next_quarter

        statuses.append({
            "name": investor["name"],
            "entity": investor["entity"],
            "cik": investor["cik"],
            "latest_quarter": latest_quarter,
            "filing_date": filing_date,
            "has_filed": has_filed,
            "expected_quarter": expected_quarter,
        })

    return statuses
