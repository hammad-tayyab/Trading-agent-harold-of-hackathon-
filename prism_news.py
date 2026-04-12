"""
prism_news.py
=============
This file acts as Harold's "eyes and ears" for the news. 
It connects to the PRISM API (a news service) to read the latest crypto headlines. 
It specifically searches for scary words (like "hack" or "bankruptcy") to warn the AI 
if it's a dangerous time to trade.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests


def _prism_base() -> str:
    return os.getenv("PRISM_API_BASE", "https://api.prismapi.ai").rstrip("/")


def _prism_key() -> str:
    return (os.getenv("PRISM_API_KEY") or "").strip()

# ─────────────────────────────────────────────────────────────────────────────
# RED FLAG DICTIONARIES
# These are words the AI actively scans for in news headlines. If it sees 
# these words, it knows the market might crash, and it will be extra cautious.
# ─────────────────────────────────────────────────────────────────────────────
NEGATIVE_KEYWORDS = frozenset(
    {
        "hack",
        "hacked",
        "hacking",
        "exploit",
        "exploited",
        "drain",
        "drained",
        "stolen",
        "ransomware",
        "security breach",
        "breach",
        "bankrupt",
        "bankruptcy",
        "insolvent",
        "insolvency",
        "default",
        "fraud",
        "fraudulent",
        "ponzi",
        "scam",
        "lawsuit",
        "indictment",
        "sec charges",
        "enforcement",
        "sanction",
        "sanctions",
        "seized",
        "seizure",
        "crackdown",
        "ban",
        "banned",
        "outlaw",
        "depeg",
        "de-peg",
        "depegged",
        "circuit breaker",
        "emergency",
        "halt",
        "paused",
        "freeze",
        "frozen",
        "collapse",
        "meltdown",
        "contagion",
    }
)

STRONG_NEGATIVE = frozenset(
    {
        "exploit",
        "exploited",
        "hack",
        "hacked",
        "drain",
        "drained",
        "bankrupt",
        "insolvent",
        "seized",
        "indictment",
        "security breach",
        "ransomware",
    }
)


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "HaroldTradingAgent/1.0"}
    key = _prism_key()
    if key:
        h["X-API-Key"] = key
    return h


def _article_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "headline", "summary", "description", "excerpt", "text", "content"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return " ".join(parts)


def _collect_news_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def fetch_prism_eth_sentiment(
    symbol: str = "ETH",
    *,
    timeout: float = 15,
) -> dict[str, Any] | None:
    url = f"{_prism_base()}/social/{symbol}/sentiment"
    r = requests.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


def fetch_prism_crypto_news(
    *,
    limit: int = 20,
    timeout: float = 15,
) -> list[dict[str, Any]]:
    r = requests.get(
        f"{_prism_base()}/news/crypto",
        headers=_headers(),
        params={"limit": limit},
        timeout=timeout,
    )
    r.raise_for_status()
    return _collect_news_items(r.json())


def fetch_trading_community_news_context(
    *,
    eth_symbol: str = "ETH",
    news_limit: int = 20,
    timeout: float = 15,
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    The main News Engine.
    
    1. It fetches social sentiment (how Twitter/Reddit feels about Ethereum).
    2. It fetches the top 20 latest crypto news articles.
    3. It scans everything for our red flag words.
    
    Finally, it hands back a simple summary to Harold, basically saying: 
    "It's safe to trade," or "WARNING: Bad news for traders!"
    """
    out: dict[str, Any] = {
        "source": "prism",
        "ok": False,
        "bad_news_for_traders": False,
        "headline_risk": "unknown",
        "eth_sentiment_score": None,
        "eth_sentiment_label": None,
        "articles_scanned": 0,
        "negative_headline_articles": 0,
        "strong_negative_articles": 0,
        "headline_hints": [],
        "summary_for_ai": "PRISM unavailable; treat news as unknown/neutral.",
    }

    sentiment: dict[str, Any] | None = None
    sentiment_ok = False
    try:
        sentiment = fetch_prism_eth_sentiment(eth_symbol, timeout=timeout)
        sentiment_ok = sentiment is not None
    except Exception as e:
        if log:
            log.warning("PRISM sentiment failed: %s", e)

    score: float | None = None
    label: str | None = None
    if sentiment:
        s = sentiment.get("sentiment_score")
        if isinstance(s, (int, float)):
            score = float(s)
            out["eth_sentiment_score"] = score
        lab = sentiment.get("sentiment_label")
        if isinstance(lab, str) and lab.strip():
            label = lab.strip()
            out["eth_sentiment_label"] = label

    news_items: list[dict[str, Any]] = []
    news_ok = False
    try:
        news_items = fetch_prism_crypto_news(limit=news_limit, timeout=timeout)
        news_ok = True
    except Exception as e:
        if log:
            log.warning("PRISM crypto news failed: %s", e)

    out["articles_scanned"] = len(news_items)
    out["ok"] = sentiment_ok or news_ok

    strong_articles = 0
    neg_articles = 0
    hints: list[str] = []

    for item in news_items:
        text = _article_text(item).lower()
        if not text:
            continue
        has_strong = any(tok in text for tok in STRONG_NEGATIVE)
        has_neg = has_strong or any(k in text for k in NEGATIVE_KEYWORDS)
        if not has_neg:
            continue
        neg_articles += 1
        if has_strong:
            strong_articles += 1
        title = str(item.get("title") or item.get("headline") or "")[:140].strip()
        if title and len(hints) < 4:
            hints.append(title)

    out["negative_headline_articles"] = neg_articles
    out["strong_negative_articles"] = strong_articles
    out["headline_hints"] = hints[:3]

    sentiment_bad = False
    if score is not None:
        if score <= -25:
            sentiment_bad = True
        elif score < 0 and label and "bear" in label.lower():
            sentiment_bad = True
    if label and label.lower() in ("bearish", "very bearish"):
        sentiment_bad = True

    headline_bad = strong_articles >= 1 or neg_articles >= 2
    out["bad_news_for_traders"] = bool(sentiment_bad or headline_bad)

    if not out["ok"]:
        out["headline_risk"] = "unknown"
    elif strong_articles >= 1:
        out["headline_risk"] = "high"
    elif neg_articles >= 2 or sentiment_bad:
        out["headline_risk"] = "elevated"
    elif neg_articles == 1 or (score is not None and score < 15):
        out["headline_risk"] = "moderate"
    else:
        out["headline_risk"] = "low"

    parts: list[str] = []
    if score is not None and label:
        parts.append(f"ETH social sentiment {score:.0f} ({label})")
    elif score is not None:
        parts.append(f"ETH social sentiment {score:.0f}")
    if strong_articles >= 1:
        parts.append("headlines include severe trader-negative themes")
    elif neg_articles >= 2:
        parts.append("multiple cautious/negative crypto headlines")
    elif neg_articles == 1:
        parts.append("one cautious headline flagged")
    elif news_ok and not news_items:
        parts.append("crypto news feed empty or key-limited")
    else:
        parts.append("no major headline red flags in scanned feed")

    line = "PRISM: " + "; ".join(parts) + "."
    if out["bad_news_for_traders"]:
        line += " bad_news_for_traders=TRUE — prefer defense over new risk."
    else:
        line += " bad_news_for_traders=FALSE."
    out["summary_for_ai"] = line

    return out
