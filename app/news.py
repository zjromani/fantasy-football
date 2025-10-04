"""
Fantasy news integration module.

Fetches real-time fantasy football news from multiple sources:
- ESPN RSS feeds (injuries, breaking news)
- Web scraping (RotoBaller, etc.) with respectful caching
- Extensible adapter pattern for adding more sources
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
import xml.etree.ElementTree as ET
import json
import hashlib
from pathlib import Path

import httpx


@dataclass
class NewsItem:
    """A single news item with source attribution."""
    title: str
    description: str
    link: str
    published: datetime
    source: str
    category: str = "general"  # injury, transaction, breakout, general
    player_mentioned: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "published": self.published.isoformat(),
            "source": self.source,
            "category": self.category,
            "player_mentioned": self.player_mentioned,
        }


class NewsCache:
    """Simple file-based cache for news items."""

    def __init__(self, cache_dir: str = ".cache/news"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, source: str) -> str:
        return hashlib.md5(source.encode()).hexdigest()

    def get(self, source: str, max_age_minutes: int = 30) -> Optional[List[dict]]:
        """Get cached news if not expired."""
        cache_file = self.cache_dir / f"{self._cache_key(source)}.json"
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(data["cached_at"])
            if datetime.utcnow() - cached_at > timedelta(minutes=max_age_minutes):
                return None
            return data["items"]
        except Exception:
            return None

    def set(self, source: str, items: List[dict]) -> None:
        """Cache news items."""
        cache_file = self.cache_dir / f"{self._cache_key(source)}.json"
        data = {
            "cached_at": datetime.utcnow().isoformat(),
            "items": items,
        }
        cache_file.write_text(json.dumps(data, indent=2))


class ESPNNewsFetcher:
    """Fetch news from ESPN's public RSS feeds."""

    RSS_URLS = {
        "nfl": "https://www.espn.com/espn/rss/nfl/news",
        "fantasy": "https://www.espn.com/espn/rss/fantasy/news",
    }

    def fetch(self, feed: str = "fantasy", limit: int = 20) -> List[NewsItem]:
        """Fetch news from ESPN RSS feed."""
        url = self.RSS_URLS.get(feed, self.RSS_URLS["fantasy"])

        try:
            response = httpx.get(url, timeout=10, follow_redirects=True)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            items: List[NewsItem] = []

            for item in root.findall(".//item")[:limit]:
                title = item.findtext("title", "")
                description = item.findtext("description", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")

                # Parse date (ESPN uses RFC 822 format)
                try:
                    published = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                except Exception:
                    published = datetime.utcnow()

                # Categorize based on title keywords
                category = self._categorize(title + " " + description)
                player = self._extract_player_name(title)

                items.append(NewsItem(
                    title=title,
                    description=description,
                    link=link,
                    published=published,
                    source="ESPN",
                    category=category,
                    player_mentioned=player,
                ))

            return items
        except Exception as e:
            print(f"ESPN news fetch error: {e}")
            return []

    def _categorize(self, text: str) -> str:
        """Categorize news based on keywords."""
        text_lower = text.lower()
        if any(word in text_lower for word in ["injury", "injured", "out", "questionable", "doubtful"]):
            return "injury"
        if any(word in text_lower for word in ["trade", "waiver", "sign", "release", "cut"]):
            return "transaction"
        if any(word in text_lower for word in ["breakout", "emerging", "hot", "surge", "trending"]):
            return "breakout"
        return "general"

    def _extract_player_name(self, title: str) -> Optional[str]:
        """Extract player name from title (simple heuristic)."""
        # ESPN titles often start with player names
        # e.g., "Patrick Mahomes throws 3 TDs in win"
        words = title.split()
        if len(words) >= 2:
            # Check if first two words could be a name (capitalized)
            if words[0][0].isupper() and words[1][0].isupper():
                return f"{words[0]} {words[1]}"
        return None


class RotoBallerNewsFetcher:
    """Fetch news from RotoBaller (respectful scraping with caching)."""

    BASE_URL = "https://www.rotoballer.com/player-news/nfl"

    def fetch(self, limit: int = 15) -> List[NewsItem]:
        """
        Fetch recent news from RotoBaller.

        Note: This is a placeholder. In production, you'd want to:
        1. Check RotoBaller's robots.txt and terms of service
        2. Implement proper HTML parsing with BeautifulSoup
        3. Add rate limiting and User-Agent headers
        4. Consider using their API if available

        For now, returns empty list to avoid scraping issues.
        """
        # TODO: Implement respectful scraping or use official API
        return []


def fetch_all_news(max_age_minutes: int = 30, limit_per_source: int = 20) -> List[NewsItem]:
    """
    Fetch news from all sources with caching.

    Args:
        max_age_minutes: Use cached news if younger than this
        limit_per_source: Max items to fetch from each source

    Returns:
        List of news items sorted by published date (newest first)
    """
    cache = NewsCache()
    all_items: List[NewsItem] = []

    # ESPN Fantasy News
    espn_cached = cache.get("espn_fantasy", max_age_minutes)
    if espn_cached:
        all_items.extend([NewsItem(**item) for item in espn_cached])
    else:
        fetcher = ESPNNewsFetcher()
        espn_items = fetcher.fetch(feed="fantasy", limit=limit_per_source)
        all_items.extend(espn_items)
        cache.set("espn_fantasy", [item.to_dict() for item in espn_items])

    # ESPN NFL News
    espn_nfl_cached = cache.get("espn_nfl", max_age_minutes)
    if espn_nfl_cached:
        all_items.extend([NewsItem(**item) for item in espn_nfl_cached])
    else:
        fetcher = ESPNNewsFetcher()
        espn_nfl_items = fetcher.fetch(feed="nfl", limit=limit_per_source)
        all_items.extend(espn_nfl_items)
        cache.set("espn_nfl", [item.to_dict() for item in espn_nfl_items])

    # RotoBaller (disabled for now - see note above)
    # roto_cached = cache.get("rotoballer", max_age_minutes)
    # if roto_cached:
    #     all_items.extend([NewsItem(**item) for item in roto_cached])
    # else:
    #     fetcher = RotoBallerNewsFetcher()
    #     roto_items = fetcher.fetch(limit=limit_per_source)
    #     all_items.extend(roto_items)
    #     cache.set("rotoballer", [item.to_dict() for item in roto_items])

    # Sort by published date (newest first)
    all_items.sort(key=lambda x: x.published, reverse=True)

    return all_items


def get_injury_news(limit: int = 10) -> List[NewsItem]:
    """Get recent injury-related news."""
    all_news = fetch_all_news()
    injury_news = [item for item in all_news if item.category == "injury"]
    return injury_news[:limit]


def get_transaction_news(limit: int = 10) -> List[NewsItem]:
    """Get recent transaction news (trades, signings, cuts)."""
    all_news = fetch_all_news()
    transaction_news = [item for item in all_news if item.category == "transaction"]
    return transaction_news[:limit]


def get_breakout_news(limit: int = 10) -> List[NewsItem]:
    """Get breakout candidate and trending player news."""
    all_news = fetch_all_news()
    breakout_news = [item for item in all_news if item.category == "breakout"]
    return breakout_news[:limit]


def search_player_news(player_name: str, limit: int = 5) -> List[NewsItem]:
    """Search news mentioning a specific player."""
    all_news = fetch_all_news()
    player_lower = player_name.lower()

    matching_news = [
        item for item in all_news
        if player_lower in item.title.lower()
        or player_lower in item.description.lower()
        or (item.player_mentioned and player_lower in item.player_mentioned.lower())
    ]

    return matching_news[:limit]


__all__ = [
    "NewsItem",
    "fetch_all_news",
    "get_injury_news",
    "get_transaction_news",
    "get_breakout_news",
    "search_player_news",
]

