"""RSS feed collector for crypto news."""

import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import feedparser

from trading.core.models import NewsArticle

if TYPE_CHECKING:
    from trading.core.news_filter import EventClassification, NewsEventFilter

logger = logging.getLogger(__name__)


class RSSNewsCollector:
    """Collector for crypto news from RSS feeds."""

    # Default RSS feed sources
    DEFAULT_FEEDS = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
        "Decrypt": "https://decrypt.co/feed",
        "TheBlock": "https://www.theblock.co/rss.xml",
    }

    # Keywords for BTC-related filtering (expanded to include market-moving crypto news)
    BTC_KEYWORDS = {
        # Direct BTC keywords
        "bitcoin",
        "btc",
        "satoshi",
        "lightning network",
        "halvening",
        "halving",
        # Market-wide events that affect BTC
        "crypto market",
        "cryptocurrency market",
        "digital asset",
        "crypto crash",
        "crypto surge",
        "crypto rally",
        # Institutional/regulatory (affects BTC price)
        "etf",
        "sec crypto",
        "crypto regulation",
        "fed rate",
        "interest rate",
        # Major entities that move BTC
        "microstrategy",
        "grayscale",
        "blackrock crypto",
        "fidelity crypto",
    }

    # High-impact keywords
    HIGH_IMPACT_KEYWORDS = {
        "etf",
        "sec",
        "regulation",
        "ban",
        "hack",
        "breach",
        "crash",
        "surge",
        "record",
        "all-time high",
        "ath",
        "federal reserve",
        "fed",
        "interest rate",
    }

    def __init__(self, feeds: dict[str, str] | None = None):
        """Initialize RSS collector.

        Args:
            feeds: Dictionary mapping source name to feed URL.
                   Uses DEFAULT_FEEDS if None.
        """
        self._feeds = feeds or self.DEFAULT_FEEDS.copy()

    def add_feed(self, name: str, url: str) -> None:
        """Add a new RSS feed source.

        Args:
            name: Source name.
            url: Feed URL.
        """
        self._feeds[name] = url

    def remove_feed(self, name: str) -> bool:
        """Remove an RSS feed source.

        Args:
            name: Source name.

        Returns:
            True if removed, False if not found.
        """
        if name in self._feeds:
            del self._feeds[name]
            return True
        return False

    def fetch_all(self, limit_per_source: int = 10) -> list[NewsArticle]:
        """Fetch articles from all configured feeds.

        Args:
            limit_per_source: Maximum articles per source.

        Returns:
            List of NewsArticle objects.
        """
        all_articles = []

        for source, url in self._feeds.items():
            try:
                articles = self._fetch_feed(source, url, limit_per_source)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"Failed to fetch feed {source}: {e}")

        # Sort by publish date (newest first)
        all_articles.sort(
            key=lambda a: a.published or datetime.min,
            reverse=True,
        )

        return all_articles

    def fetch_btc_news(self, limit: int = 20) -> list[NewsArticle]:
        """Fetch BTC-related news from all feeds.

        Args:
            limit: Maximum total articles to return.

        Returns:
            List of BTC-related NewsArticle objects.
        """
        all_articles = self.fetch_all(limit_per_source=20)

        btc_articles = [
            article for article in all_articles
            if self._is_btc_related(article)
        ]

        return btc_articles[:limit]

    def fetch_btc_news_filtered(
        self,
        limit: int = 20,
        event_filter: "NewsEventFilter | None" = None,
    ) -> list[tuple[NewsArticle, "EventClassification"]]:
        """Fetch BTC-related news with event filtering.

        Filters out non-actionable content like analysis, opinions,
        and educational content to focus on real market events.

        Args:
            limit: Maximum total articles to return.
            event_filter: Optional NewsEventFilter instance.

        Returns:
            List of (article, classification) tuples for actionable events.
        """
        if event_filter is None:
            from trading.core.news_filter import NewsEventFilter
            event_filter = NewsEventFilter()

        # Fetch more articles to account for filtering
        articles = self.fetch_btc_news(limit=limit * 2)

        # Apply event filter
        filtered = event_filter.filter_actionable(articles)

        return filtered[:limit]

    def _fetch_feed(
        self,
        source: str,
        url: str,
        limit: int,
    ) -> list[NewsArticle]:
        """Fetch articles from a single feed.

        Args:
            source: Source name.
            url: Feed URL.
            limit: Maximum articles to fetch.

        Returns:
            List of NewsArticle objects.
        """
        feed = feedparser.parse(url)

        if feed.bozo and feed.bozo_exception:
            logger.warning(f"Feed parse warning for {source}: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries[:limit]:
            try:
                # Parse publish date
                published = None
                if hasattr(entry, "published"):
                    try:
                        published = parsedate_to_datetime(entry.published)
                    except (ValueError, TypeError):
                        pass

                # Extract summary
                summary = None
                if hasattr(entry, "summary"):
                    # Clean HTML from summary
                    summary = re.sub(r"<[^>]+>", "", entry.summary)
                    summary = summary[:500] if len(summary) > 500 else summary

                articles.append(
                    NewsArticle(
                        title=entry.get("title", ""),
                        link=entry.get("link", ""),
                        source=source,
                        published=published,
                        summary=summary,
                    )
                )

            except Exception as e:
                logger.warning(f"Failed to parse entry from {source}: {e}")
                continue

        return articles

    def _is_btc_related(self, article: NewsArticle) -> bool:
        """Check if article is BTC-related.

        Args:
            article: NewsArticle to check.

        Returns:
            True if article is related to Bitcoin.
        """
        text = f"{article.title} {article.summary or ''}".lower()

        return any(keyword in text for keyword in self.BTC_KEYWORDS)

    def classify_impact(self, article: NewsArticle) -> str:
        """Classify potential market impact of an article.

        Args:
            article: NewsArticle to classify.

        Returns:
            Impact level: 'low', 'medium', or 'high'.
        """
        text = f"{article.title} {article.summary or ''}".lower()

        # Check for high-impact keywords
        high_impact_count = sum(
            1 for keyword in self.HIGH_IMPACT_KEYWORDS
            if keyword in text
        )

        if high_impact_count >= 2:
            return "high"
        elif high_impact_count >= 1:
            return "medium"
        return "low"

    def get_headlines(self, limit: int = 10) -> list[str]:
        """Get recent headlines only.

        Args:
            limit: Maximum headlines to return.

        Returns:
            List of headline strings.
        """
        articles = self.fetch_btc_news(limit=limit)
        return [article.title for article in articles]
