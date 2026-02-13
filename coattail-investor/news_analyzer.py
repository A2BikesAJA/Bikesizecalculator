from __future__ import annotations

"""
AI News Analysis Module.

Searches for financial news relevant to each stock, performs sentiment
analysis, and classifies stories as growth opportunities or sell-off risks.
Uses free RSS/Atom feeds (no API key required) with built-in NLP-style
keyword sentiment scoring.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

# ─── Sentiment lexicons ──────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "beat", "beats", "exceeded", "surpass", "surpassed", "outperform",
    "outperformed", "upgrade", "upgraded", "upgrades", "buy", "bullish",
    "growth", "growing", "surging", "surge", "rally", "rallied", "soar",
    "soaring", "profit", "profits", "profitable", "gains", "gain",
    "record", "high", "strong", "strength", "positive", "optimistic",
    "upside", "raised", "raises", "boost", "boosted", "innovation",
    "innovative", "expand", "expanding", "expansion", "breakthrough",
    "revenue", "dividend", "acquisition", "partnership", "opportunity",
    "momentum", "recovery", "rebound", "accelerate", "accelerating",
    "impressive", "exceed", "exceeds", "overweight", "recommend",
    "success", "successful", "dominance", "dominant", "winner",
    "approval", "approved", "beat estimates", "tops expectations",
}

_NEGATIVE_WORDS = {
    "miss", "missed", "misses", "downgrade", "downgraded", "sell",
    "bearish", "decline", "declining", "loss", "losses", "crash",
    "crashed", "plunge", "plunged", "plunging", "drop", "dropped",
    "dropping", "fall", "falling", "fell", "weak", "weakness",
    "negative", "pessimistic", "downside", "cut", "cuts", "risk",
    "warning", "warned", "layoff", "layoffs", "lawsuit", "sued",
    "fraud", "investigation", "probe", "recall", "bankruptcy",
    "default", "debt", "underperform", "underweight", "concern",
    "troubled", "struggle", "struggling", "slump", "slumping",
    "disappointing", "disappointed", "shortfall", "below expectations",
    "recession", "inflation", "tariff", "tariffs", "sanction",
    "sanctions", "volatility", "uncertainty", "threat", "regulation",
    "fine", "penalty", "scandal", "overvalued", "bubble",
}

# ─── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class NewsArticle:
    """A single news article with sentiment analysis."""

    title: str = ""
    source: str = ""
    url: str = ""
    published: str = ""
    summary: str = ""
    sentiment_score: float = 0.0  # -1.0 to +1.0
    sentiment: str = "neutral"  # positive / negative / neutral
    impact: str = "neutral"  # growth_opportunity / sell_off_risk / neutral
    key_phrases: list[str] = field(default_factory=list)


@dataclass
class StockNewsAnalysis:
    """Aggregated news analysis for a single stock."""

    ticker: str = ""
    name: str = ""
    articles: list[NewsArticle] = field(default_factory=list)
    article_count: int = 0

    # Aggregate sentiment
    avg_sentiment: float = 0.0  # -1.0 to +1.0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0

    # Overall assessment
    news_signal: str = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL
    signal_strength: str = "LOW"  # HIGH / MEDIUM / LOW
    outlook: str = ""  # Human-readable summary

    # Impact classification
    growth_catalysts: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)

    error: str | None = None


# ─── News Fetching ───────────────────────────────────────────────────────────


def _fetch_google_news_rss(query: str, num_results: int = 10) -> list[dict]:
    """
    Fetch news articles from Google News RSS feed.
    """
    articles = []
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"

    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "CoattailInvestor/1.0 (news-analyzer)"
        })
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        for item in items[:num_results]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            description = item.findtext("description", "")

            # Clean HTML from description
            description = re.sub(r"<[^>]+>", "", description or "")

            articles.append({
                "title": title,
                "url": link,
                "published": pub_date,
                "source": source,
                "summary": description[:500],
            })

    except Exception as e:
        logger.warning(f"Google News RSS fetch failed for '{query}': {e}")

    return articles


def _fetch_yahoo_finance_rss(ticker: str) -> list[dict]:
    """
    Fetch news from Yahoo Finance RSS for a specific ticker.
    """
    articles = []
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "CoattailInvestor/1.0 (news-analyzer)"
        })
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        for item in items[:8]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            description = re.sub(r"<[^>]+>", "", description or "")

            articles.append({
                "title": title,
                "url": link,
                "published": pub_date,
                "source": "Yahoo Finance",
                "summary": description[:500],
            })

    except Exception as e:
        logger.warning(f"Yahoo Finance RSS fetch failed for {ticker}: {e}")

    return articles


# ─── Sentiment Analysis ─────────────────────────────────────────────────────


def _analyze_sentiment(text: str) -> tuple[float, str, list[str]]:
    """
    Analyze sentiment of text using keyword scoring.

    Returns:
        (score, label, key_phrases) where score is -1.0 to +1.0
    """
    if not text:
        return 0.0, "neutral", []

    text_lower = text.lower()
    words = set(re.findall(r"\b\w+\b", text_lower))

    pos_matches = words & _POSITIVE_WORDS
    neg_matches = words & _NEGATIVE_WORDS

    # Also check multi-word phrases
    for phrase in _POSITIVE_WORDS:
        if " " in phrase and phrase in text_lower:
            pos_matches.add(phrase)
    for phrase in _NEGATIVE_WORDS:
        if " " in phrase and phrase in text_lower:
            neg_matches.add(phrase)

    pos_count = len(pos_matches)
    neg_count = len(neg_matches)
    total = pos_count + neg_count

    if total == 0:
        return 0.0, "neutral", []

    score = (pos_count - neg_count) / total
    score = max(-1.0, min(1.0, score))

    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    key_phrases = sorted(pos_matches | neg_matches)
    return round(score, 3), label, key_phrases


def _classify_impact(
    article: NewsArticle,
) -> str:
    """Classify the likely market impact of a news article."""
    if article.sentiment_score > 0.3:
        return "growth_opportunity"
    elif article.sentiment_score < -0.3:
        return "sell_off_risk"
    return "neutral"


# ─── Main Analysis ───────────────────────────────────────────────────────────


def analyze_stock_news(
    ticker: str, name: str = "", max_articles: int = 15
) -> StockNewsAnalysis:
    """
    Fetch and analyze news for a single stock.

    Searches multiple sources, deduplicates, scores sentiment, and
    produces an aggregate outlook.
    """
    result = StockNewsAnalysis(ticker=ticker, name=name)

    try:
        # Fetch from multiple sources
        query = f"{ticker} stock"
        if name:
            query = f"{name} {ticker} stock"

        raw_articles = []
        raw_articles.extend(_fetch_google_news_rss(query, num_results=10))
        raw_articles.extend(_fetch_yahoo_finance_rss(ticker))

        # Deduplicate by title similarity
        seen_titles = set()
        unique_articles = []
        for art in raw_articles:
            title_key = art["title"][:60].lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_articles.append(art)

        # Analyze each article
        analyzed = []
        for art in unique_articles[:max_articles]:
            combined_text = f"{art['title']} {art['summary']}"
            score, sentiment, phrases = _analyze_sentiment(combined_text)

            article = NewsArticle(
                title=art["title"],
                source=art.get("source", ""),
                url=art.get("url", ""),
                published=art.get("published", ""),
                summary=art.get("summary", ""),
                sentiment_score=score,
                sentiment=sentiment,
                key_phrases=phrases,
            )
            article.impact = _classify_impact(article)
            analyzed.append(article)

        result.articles = analyzed
        result.article_count = len(analyzed)

        # Aggregate metrics
        if analyzed:
            scores = [a.sentiment_score for a in analyzed]
            result.avg_sentiment = round(sum(scores) / len(scores), 3)
            result.positive_count = sum(1 for a in analyzed if a.sentiment == "positive")
            result.negative_count = sum(1 for a in analyzed if a.sentiment == "negative")
            result.neutral_count = sum(1 for a in analyzed if a.sentiment == "neutral")

            # Overall signal
            if result.avg_sentiment > 0.15:
                result.news_signal = "BULLISH"
            elif result.avg_sentiment < -0.15:
                result.news_signal = "BEARISH"
            else:
                result.news_signal = "NEUTRAL"

            # Signal strength based on agreement
            total = len(analyzed)
            dominant = max(result.positive_count, result.negative_count, result.neutral_count)
            agreement_ratio = dominant / total if total > 0 else 0
            if agreement_ratio > 0.7 and total >= 3:
                result.signal_strength = "HIGH"
            elif agreement_ratio > 0.5:
                result.signal_strength = "MEDIUM"
            else:
                result.signal_strength = "LOW"

            # Extract catalysts and risks
            result.growth_catalysts = [
                a.title for a in analyzed if a.impact == "growth_opportunity"
            ][:5]
            result.risk_factors = [
                a.title for a in analyzed if a.impact == "sell_off_risk"
            ][:5]

            # Human-readable outlook
            result.outlook = _generate_outlook(result)

    except Exception as e:
        logger.error(f"News analysis failed for {ticker}: {e}")
        result.error = str(e)

    return result


def analyze_watchlist_news(
    watchlist: list[dict], max_articles_per_stock: int = 10
) -> list[dict]:
    """
    Analyze news for every stock in the watchlist.

    Returns the watchlist enriched with a 'news' key.
    """
    for i, item in enumerate(watchlist):
        ticker = item.get("ticker", "")
        if not ticker or len(ticker) > 5 or not ticker.isalpha():
            item["news"] = None
            continue

        logger.info(f"  [{i + 1}/{len(watchlist)}] Analyzing news for {ticker}...")
        news = analyze_stock_news(
            ticker, item.get("name", ""), max_articles=max_articles_per_stock
        )
        item["news"] = news

    return watchlist


def _generate_outlook(analysis: StockNewsAnalysis) -> str:
    """Generate a human-readable outlook summary."""
    parts = []

    if analysis.news_signal == "BULLISH":
        parts.append(f"News sentiment for {analysis.ticker} is predominantly positive")
        if analysis.positive_count > 0:
            parts.append(
                f"with {analysis.positive_count} of {analysis.article_count} "
                f"articles showing bullish signals"
            )
    elif analysis.news_signal == "BEARISH":
        parts.append(f"News sentiment for {analysis.ticker} is predominantly negative")
        if analysis.negative_count > 0:
            parts.append(
                f"with {analysis.negative_count} of {analysis.article_count} "
                f"articles showing bearish signals"
            )
    else:
        parts.append(f"News sentiment for {analysis.ticker} is mixed/neutral")
        parts.append(
            f"({analysis.positive_count} positive, {analysis.negative_count} negative, "
            f"{analysis.neutral_count} neutral out of {analysis.article_count} articles)"
        )

    if analysis.growth_catalysts:
        parts.append(f"Key growth catalysts identified: {len(analysis.growth_catalysts)}")

    if analysis.risk_factors:
        parts.append(f"Risk factors to monitor: {len(analysis.risk_factors)}")

    return ". ".join(parts) + "."
