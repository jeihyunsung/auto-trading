"""News memory system with TTL and time-based decay.

Manages short-term news memory to maintain context across trading cycles.
Recent news has higher influence through exponential time decay.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from trading.core.news_filter import EventClassification, NewsEventFilter
from trading.core.state import MemorizedNewsItem, NewsMemoryStats

if TYPE_CHECKING:
    from trading.adapters.rss_collector import NewsArticle

logger = logging.getLogger(__name__)


@dataclass
class NewsMemoryConfig:
    """Configuration for news memory.

    Attributes:
        ttl: Time-to-live for news items in memory.
        decay_half_life: Time for news influence to decay by 50%.
        max_items: Maximum items to keep in memory.
    """

    ttl: timedelta = field(default_factory=lambda: timedelta(hours=4))
    decay_half_life: timedelta = field(default_factory=lambda: timedelta(hours=1))
    max_items: int = 100


@dataclass
class MemorizedNews:
    """Internal representation of a memorized news item."""

    title: str
    source: str
    published: datetime | None
    collected_at: datetime
    event_type: str
    is_actionable: bool
    content_hash: str
    initial_sentiment: float
    initial_impact: str
    link: str = ""
    summary: str | None = None

    def to_state_dict(self) -> MemorizedNewsItem:
        """Convert to state TypedDict format."""
        return MemorizedNewsItem(
            title=self.title,
            source=self.source,
            published=self.published.isoformat() if self.published else None,
            collected_at=self.collected_at.isoformat(),
            event_type=self.event_type,
            is_actionable=self.is_actionable,
            content_hash=self.content_hash,
            initial_sentiment=self.initial_sentiment,
            initial_impact=self.initial_impact,
        )


class NewsMemory:
    """Manages short-term news memory with time decay.

    Features:
    - TTL-based automatic cleanup
    - Exponential time decay for sentiment weighting
    - Duplicate detection via content hash
    - Statistics tracking

    Attributes:
        config: Memory configuration.
    """

    def __init__(
        self,
        config: NewsMemoryConfig | None = None,
        event_filter: NewsEventFilter | None = None,
    ):
        """Initialize news memory.

        Args:
            config: Memory configuration.
            event_filter: Optional filter for hash generation.
        """
        self.config = config or NewsMemoryConfig()
        self._filter = event_filter or NewsEventFilter()
        self._items: list[MemorizedNews] = []
        self._seen_hashes: set[str] = set()
        self._duplicates_blocked: int = 0

    def add(
        self,
        article: "NewsArticle",
        classification: EventClassification,
        sentiment: float,
        impact: str,
        current_time: datetime | None = None,
    ) -> bool:
        """Add a news article to memory.

        Args:
            article: News article to add.
            classification: Event classification result.
            sentiment: Sentiment score (-1 to 1).
            impact: Impact level (low/medium/high).
            current_time: Current time (for testing).

        Returns:
            True if added, False if duplicate.
        """
        now = current_time or datetime.now()
        content_hash = self._filter.generate_content_hash(article)

        # Check for duplicate
        if content_hash in self._seen_hashes:
            self._duplicates_blocked += 1
            logger.debug(f"Blocked duplicate: {article.title[:50]}...")
            return False

        # Cleanup expired items first
        self._cleanup_expired(now)

        # Parse published date
        published_dt: datetime | None = None
        if article.published:
            try:
                if isinstance(article.published, datetime):
                    published_dt = article.published
                else:
                    published_dt = datetime.fromisoformat(
                        article.published.replace("Z", "+00:00")
                    )
                    if published_dt.tzinfo is not None:
                        published_dt = published_dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        item = MemorizedNews(
            title=article.title,
            source=article.source,
            published=published_dt,
            collected_at=now,
            event_type=classification.event_type.value,
            is_actionable=classification.is_actionable,
            content_hash=content_hash,
            initial_sentiment=sentiment,
            initial_impact=impact,
            link=article.link,
            summary=article.summary,
        )

        self._items.append(item)
        self._seen_hashes.add(content_hash)

        # Enforce max items limit
        if len(self._items) > self.config.max_items:
            removed = self._items.pop(0)
            self._seen_hashes.discard(removed.content_hash)
            logger.debug(f"Memory limit reached, removed oldest: {removed.title[:40]}...")

        logger.debug(
            f"Added to memory: {article.title[:50]}... "
            f"(type={classification.event_type.value}, "
            f"sentiment={sentiment:.2f})"
        )
        return True

    def get_weighted_sentiment(
        self, current_time: datetime | None = None
    ) -> tuple[float, float]:
        """Calculate time-weighted sentiment from memory.

        Recent news has higher weight via exponential decay.

        Args:
            current_time: Current time (for testing).

        Returns:
            Tuple of (weighted_sentiment, total_weight).
            Returns (0.0, 0.0) if no actionable items.
        """
        now = current_time or datetime.now()
        self._cleanup_expired(now)

        if not self._items:
            return 0.0, 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for item in self._items:
            if not item.is_actionable:
                continue
            weight = self._calculate_decay_weight(item.collected_at, now)
            weighted_sum += item.initial_sentiment * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, 0.0

        return weighted_sum / total_weight, total_weight

    def get_highest_impact(self, current_time: datetime | None = None) -> str:
        """Get highest impact level from recent news.

        Only considers items within the decay half-life.

        Args:
            current_time: Current time (for testing).

        Returns:
            Highest impact level ("low", "medium", or "high").
        """
        now = current_time or datetime.now()
        self._cleanup_expired(now)

        cutoff = now - self.config.decay_half_life
        impact_priority = {"high": 3, "medium": 2, "low": 1}
        highest = "low"

        for item in self._items:
            if not item.is_actionable or item.collected_at < cutoff:
                continue
            if impact_priority.get(item.initial_impact, 0) > impact_priority[highest]:
                highest = item.initial_impact

        return highest

    def get_all_items(
        self, current_time: datetime | None = None
    ) -> list[MemorizedNewsItem]:
        """Get all items in memory as state dicts.

        Args:
            current_time: Current time (for testing).

        Returns:
            List of MemorizedNewsItem dicts.
        """
        now = current_time or datetime.now()
        self._cleanup_expired(now)
        return [item.to_state_dict() for item in self._items]

    def get_stats(self, current_time: datetime | None = None) -> NewsMemoryStats:
        """Get memory statistics.

        Args:
            current_time: Current time (for testing).

        Returns:
            NewsMemoryStats dict.
        """
        now = current_time or datetime.now()
        self._cleanup_expired(now)

        if not self._items:
            return NewsMemoryStats(
                total_items=0,
                actionable_items=0,
                oldest_age_hours=0.0,
                newest_age_hours=0.0,
                items_by_type={},
                duplicates_blocked=self._duplicates_blocked,
            )

        items_by_type: dict[str, int] = {}
        actionable_count = 0

        for item in self._items:
            items_by_type[item.event_type] = items_by_type.get(item.event_type, 0) + 1
            if item.is_actionable:
                actionable_count += 1

        oldest = min(item.collected_at for item in self._items)
        newest = max(item.collected_at for item in self._items)

        return NewsMemoryStats(
            total_items=len(self._items),
            actionable_items=actionable_count,
            oldest_age_hours=round((now - oldest).total_seconds() / 3600, 2),
            newest_age_hours=round((now - newest).total_seconds() / 3600, 2),
            items_by_type=items_by_type,
            duplicates_blocked=self._duplicates_blocked,
        )

    def _calculate_decay_weight(self, collected_at: datetime, now: datetime) -> float:
        """Calculate exponential decay weight.

        Formula: weight = 0.5 ^ (age / half_life)

        Args:
            collected_at: When the news was collected.
            now: Current time.

        Returns:
            Weight between 0 and 1.
        """
        age_seconds = (now - collected_at).total_seconds()
        half_life_seconds = self.config.decay_half_life.total_seconds()

        if half_life_seconds <= 0:
            return 1.0

        return math.pow(0.5, age_seconds / half_life_seconds)

    def _cleanup_expired(self, now: datetime) -> int:
        """Remove items older than TTL.

        Args:
            now: Current time.

        Returns:
            Number of items removed.
        """
        cutoff = now - self.config.ttl
        original_count = len(self._items)

        self._items = [item for item in self._items if item.collected_at >= cutoff]
        current_hashes = {item.content_hash for item in self._items}
        self._seen_hashes = self._seen_hashes & current_hashes

        removed = original_count - len(self._items)
        if removed > 0:
            logger.debug(f"Cleaned up {removed} expired news items")
        return removed

    def clear(self) -> None:
        """Clear all items from memory."""
        self._items.clear()
        self._seen_hashes.clear()
        logger.info("News memory cleared")


# Module-level singleton (like HysteresisManager)
_news_memory: NewsMemory | None = None


def set_news_memory(memory: NewsMemory | None) -> None:
    """Set the global news memory instance.

    Args:
        memory: NewsMemory instance or None to disable.
    """
    global _news_memory
    _news_memory = memory


def get_news_memory() -> NewsMemory | None:
    """Get the global news memory instance.

    Returns:
        Current NewsMemory or None if not configured.
    """
    return _news_memory
