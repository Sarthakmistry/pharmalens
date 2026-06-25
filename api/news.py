"""
api/news.py
Lightweight BioSpace article reader — fetches the site's news sitemap (sanctioned by
robots.txt) to discover articles relevant to tracked companies, and fetches individual
article pages on demand. No LLM extraction, no GCS, no wiki — purely a read + cache
layer for the frontend's News section and the Q&A agent's article context.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
COMPANIES: dict = json.loads((BASE_DIR / "reference" / "companies.json").read_text())

NEWS_SITEMAP_URL = "https://www.biospace.com/news-sitemap-content.xml"
ARTICLE_DOMAIN = "https://www.biospace.com/"
_NS = {"n": "http://www.sitemaps.org/schemas/sitemap/0.9", "news": "http://www.google.com/schemas/sitemap-news/0.9"}

_ARTICLES_CACHE_TTL = 900   # 15 min
_ARTICLE_CACHE_TTL = 3600   # 1 hour
_articles_cache: tuple[float, list[dict]] | None = None
_article_cache: dict[str, tuple[float, dict]] = {}

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PharmaLensBot/1.0)"}


def _matching_companies(text: str) -> list[str]:
    """Return company slugs whose alias appears in the given text (case-insensitive)."""
    lowered = text.lower()
    matches = []
    for slug, meta in COMPANIES.items():
        for alias in meta.get("aliases", []):
            if alias.lower() in lowered:
                matches.append(slug)
                break
    return matches


def get_relevant_articles() -> list[dict]:
    """Fetch BioSpace's news sitemap, filter to articles mentioning a tracked company.
    Cached for _ARTICLES_CACHE_TTL — this is polled on every sidebar load, and the
    sitemap only updates a handful of times per hour."""
    global _articles_cache
    if _articles_cache and time.time() - _articles_cache[0] < _ARTICLES_CACHE_TTL:
        return _articles_cache[1]

    resp = requests.get(NEWS_SITEMAP_URL, headers=_REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    results = []
    for url_el in root.findall("n:url", _NS):
        loc = url_el.findtext("n:loc", default="", namespaces=_NS)
        news_el = url_el.find("news:news", _NS)
        if news_el is None or not loc:
            continue
        title = news_el.findtext("news:title", default="", namespaces=_NS)
        keywords = news_el.findtext("news:keywords", default="", namespaces=_NS)
        pub_date = news_el.findtext("news:publication_date", default="", namespaces=_NS)

        companies = _matching_companies(f"{title} {keywords}")
        if not companies:
            continue

        results.append({
            "title": title,
            "url": loc,
            "published_date": pub_date,
            "companies": companies,
        })

    results.sort(key=lambda a: a["published_date"], reverse=True)
    _articles_cache = (time.time(), results)
    return results


def get_article(url: str) -> dict:
    """Fetch and parse a single BioSpace article. Raises ValueError if the URL isn't
    on biospace.com — this is a server-side fetch of a client-supplied URL, so the
    domain is pinned to close off SSRF to arbitrary hosts."""
    if not url.startswith(ARTICLE_DOMAIN):
        raise ValueError(f"URL must be on {ARTICLE_DOMAIN}")

    cached = _article_cache.get(url)
    if cached and time.time() - cached[0] < _ARTICLE_CACHE_TTL:
        return cached[1]

    resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else url

    date_meta = soup.find("meta", attrs={"property": "article:published_time"})
    published_date = date_meta.get("content", "") if date_meta else ""

    body_el = soup.find("div", class_="Page-articleBody")
    paragraphs = []
    if body_el:
        for p in body_el.find_all("p"):
            text = p.get_text(strip=True)
            # Skip the podcast-links paragraph and other empty/anchor-only blocks.
            if not text or re.match(r"^(>?Listen on\b)", text):
                continue
            paragraphs.append(text)

    result = {
        "title": title,
        "published_date": published_date,
        "body_text": "\n\n".join(paragraphs),
        "url": url,
    }
    _article_cache[url] = (time.time(), result)
    return result
