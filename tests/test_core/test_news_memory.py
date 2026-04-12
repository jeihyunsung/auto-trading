"""Tests for news memory system with TTL and time decay."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from trading.core.news_filter import EventClassification, EventType
from trading.core.news_memory import (
    MemorizedNews,
    NewsMemory,
    NewsMemoryConfig,
    get_news_memory,
    set_news_memory,
)


@dataclass
class MockNewsArticle:
    """Mock news article for testing."""

    title: str
    link: str = "https://example.com/news"
    source: str = "TestSource"
    published: datetime | None = None
    summary: str | None = None


def make_classification(
    event_type: EventType = EventType.BREAKING,
    is_actionable: bool = True,
) -> EventClassification:
    """Create a mock classification."""
    return EventClassification(
        event_type=event_type,
        is_actionable=is_actionable,
        confidence=0.8,
        matched_patterns=["test_pattern"],
    )


class TestNewsMemoryConfig:
    """Tests for NewsMemoryConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = NewsMemoryConfig()

        assert config.ttl == timedelta(hours=4)
        assert config.decay_half_life == timedelta(hours=1)
        assert config.max_items == 100

    def test_custom_config(self):
        """Test custom configuration."""
        config = NewsMemoryConfig(
            ttl=timedelta(hours=2),
            decay_half_life=timedelta(minutes=30),
            max_items=50,
        )

        assert config.ttl == timedelta(hours=2)
        assert config.decay_half_life == timedelta(minutes=30)
        assert config.max_items == 50


class TestNewsMemory:
    """Tests for NewsMemory class."""

    @pytest.fixture
    def memory(self):
        """Create a memory instance with default config."""
        return NewsMemory()

    @pytest.fixture
    def short_ttl_memory(self):
        """Create a memory instance with short TTL for testing."""
        return NewsMemory(
            NewsMemoryConfig(
                ttl=timedelta(minutes=10),
                decay_half_life=timedelta(minutes=5),
                max_items=10,
            )
        )

    # --- Basic Add/Get Operations ---
    def test_add_article(self, memory):
        """Test adding an article to memory."""
        article = MockNewsArticle(title="Test News", published=datetime.now())
        classification = make_classification()

        result = memory.add(article, classification, sentiment=0.5, impact="medium")

        assert result is True

    def test_add_returns_false_for_duplicate(self, memory):
        """Test that duplicate articles are rejected."""
        article = MockNewsArticle(title="Test News")
        classification = make_classification()
        now = datetime.now()

        memory.add(article, classification, 0.5, "medium", current_time=now)
        result = memory.add(article, classification, 0.5, "medium", current_time=now)

        assert result is False

    def test_duplicate_detection_tracks_count(self, memory):
        """Test that duplicate detection is tracked in stats."""
        article = MockNewsArticle(title="Test News")
        classification = make_classification()
        now = datetime.now()

        memory.add(article, classification, 0.5, "medium", current_time=now)
        memory.add(article, classification, 0.5, "medium", current_time=now)
        memory.add(article, classification, 0.5, "medium", current_time=now)

        stats = memory.get_stats(now)
        assert stats["duplicates_blocked"] == 2

    def test_get_all_items(self, memory):
        """Test retrieving all items from memory."""
        now = datetime.now()
        classification = make_classification()

        memory.add(
            MockNewsArticle(title="News 1"),
            classification,
            0.5,
            "medium",
            current_time=now,
        )
        memory.add(
            MockNewsArticle(title="News 2"),
            classification,
            0.3,
            "high",
            current_time=now,
        )

        items = memory.get_all_items(now)

        assert len(items) == 2
        assert items[0]["title"] == "News 1"
        assert items[1]["title"] == "News 2"

    # --- TTL Expiration ---
    def test_ttl_expiration(self, short_ttl_memory):
        """Test that items expire after TTL."""
        memory = short_ttl_memory
        classification = make_classification()

        # Add article at t=0
        t0 = datetime.now()
        memory.add(
            MockNewsArticle(title="Old News"),
            classification,
            0.5,
            "medium",
            current_time=t0,
        )

        # Verify it exists
        assert len(memory.get_all_items(t0)) == 1

        # Move time forward past TTL (10 minutes + 1 second)
        t1 = t0 + timedelta(minutes=11)
        items = memory.get_all_items(t1)

        assert len(items) == 0

    def test_partial_ttl_expiration(self, short_ttl_memory):
        """Test that only expired items are removed."""
        memory = short_ttl_memory
        classification = make_classification()

        t0 = datetime.now()

        # Add old article
        memory.add(
            MockNewsArticle(title="Old News"),
            classification,
            0.5,
            "medium",
            current_time=t0,
        )

        # Add new article 5 minutes later
        t1 = t0 + timedelta(minutes=5)
        memory.add(
            MockNewsArticle(title="New News"),
            classification,
            0.5,
            "medium",
            current_time=t1,
        )

        # Check at t=11 min (old expired, new still valid)
        t2 = t0 + timedelta(minutes=11)
        items = memory.get_all_items(t2)

        assert len(items) == 1
        assert items[0]["title"] == "New News"

    # --- Max Items Limit ---
    def test_max_items_limit(self, short_ttl_memory):
        """Test that max items limit is enforced."""
        memory = short_ttl_memory  # max_items=10
        classification = make_classification()
        now = datetime.now()

        # Add 15 articles
        for i in range(15):
            memory.add(
                MockNewsArticle(title=f"News {i}"),
                classification,
                0.5,
                "medium",
                current_time=now,
            )

        items = memory.get_all_items(now)
        assert len(items) == 10

    # --- Time Decay Weight ---
    def test_decay_weight_at_t0(self, memory):
        """Test decay weight at collection time is 1.0."""
        now = datetime.now()
        weight = memory._calculate_decay_weight(now, now)

        assert weight == pytest.approx(1.0)

    def test_decay_weight_at_half_life(self, memory):
        """Test decay weight at half-life is 0.5."""
        now = datetime.now()
        half_life_ago = now - memory.config.decay_half_life
        weight = memory._calculate_decay_weight(half_life_ago, now)

        assert weight == pytest.approx(0.5, rel=0.01)

    def test_decay_weight_at_two_half_lives(self, memory):
        """Test decay weight at 2x half-life is 0.25."""
        now = datetime.now()
        two_half_lives_ago = now - (memory.config.decay_half_life * 2)
        weight = memory._calculate_decay_weight(two_half_lives_ago, now)

        assert weight == pytest.approx(0.25, rel=0.01)

    # --- Weighted Sentiment ---
    def test_weighted_sentiment_empty_memory(self, memory):
        """Test weighted sentiment with empty memory."""
        sentiment, weight = memory.get_weighted_sentiment()

        assert sentiment == 0.0
        assert weight == 0.0

    def test_weighted_sentiment_single_item(self, memory):
        """Test weighted sentiment with single item."""
        now = datetime.now()
        classification = make_classification()

        memory.add(
            MockNewsArticle(title="Positive News"),
            classification,
            sentiment=0.8,
            impact="high",
            current_time=now,
        )

        sentiment, weight = memory.get_weighted_sentiment(now)

        assert sentiment == pytest.approx(0.8, rel=0.01)
        assert weight == pytest.approx(1.0, rel=0.01)

    def test_weighted_sentiment_multiple_items(self, memory):
        """Test weighted sentiment with multiple items at different ages."""
        now = datetime.now()
        classification = make_classification()
        half_life = memory.config.decay_half_life

        # Add article at t=0 with sentiment 0.8
        memory.add(
            MockNewsArticle(title="Recent News"),
            classification,
            sentiment=0.8,
            impact="high",
            current_time=now,
        )

        # Add article at t=-half_life with sentiment -0.4
        old_time = now - half_life
        memory.add(
            MockNewsArticle(title="Old News"),
            classification,
            sentiment=-0.4,
            impact="medium",
            current_time=old_time,
        )

        sentiment, total_weight = memory.get_weighted_sentiment(now)

        # Recent: weight=1.0, sentiment=0.8 -> contribution=0.8
        # Old: weight=0.5, sentiment=-0.4 -> contribution=-0.2
        # Total weight: 1.5, weighted sum: 0.6
        # Weighted avg: 0.6 / 1.5 = 0.4
        assert sentiment == pytest.approx(0.4, rel=0.05)
        assert total_weight == pytest.approx(1.5, rel=0.05)

    def test_weighted_sentiment_ignores_non_actionable(self, memory):
        """Test that non-actionable items don't affect sentiment."""
        now = datetime.now()
        actionable = make_classification(is_actionable=True)
        non_actionable = make_classification(is_actionable=False)

        memory.add(
            MockNewsArticle(title="Event News"),
            actionable,
            sentiment=0.8,
            impact="high",
            current_time=now,
        )
        memory.add(
            MockNewsArticle(title="Analysis"),
            non_actionable,
            sentiment=-0.5,
            impact="low",
            current_time=now,
        )

        sentiment, _ = memory.get_weighted_sentiment(now)

        # Only actionable item should be considered
        assert sentiment == pytest.approx(0.8, rel=0.01)

    # --- Highest Impact ---
    def test_get_highest_impact_empty_memory(self, memory):
        """Test highest impact with empty memory."""
        impact = memory.get_highest_impact()
        assert impact == "low"

    def test_get_highest_impact(self, memory):
        """Test highest impact from recent news."""
        now = datetime.now()
        classification = make_classification()

        memory.add(
            MockNewsArticle(title="Low Impact"),
            classification,
            0.5,
            "low",
            current_time=now,
        )
        memory.add(
            MockNewsArticle(title="High Impact"),
            classification,
            0.5,
            "high",
            current_time=now,
        )

        impact = memory.get_highest_impact(now)
        assert impact == "high"

    def test_get_highest_impact_ignores_old_items(self, memory):
        """Test that old items don't affect highest impact."""
        now = datetime.now()
        classification = make_classification()
        half_life = memory.config.decay_half_life

        # Add high impact item outside decay window
        old_time = now - (half_life * 2)
        memory.add(
            MockNewsArticle(title="Old High Impact"),
            classification,
            0.5,
            "high",
            current_time=old_time,
        )

        # Add low impact item within decay window
        memory.add(
            MockNewsArticle(title="Recent Low"),
            classification,
            0.5,
            "low",
            current_time=now,
        )

        impact = memory.get_highest_impact(now)
        assert impact == "low"

    # --- Statistics ---
    def test_get_stats(self, memory):
        """Test memory statistics."""
        now = datetime.now()
        classification = make_classification(event_type=EventType.ETF)

        memory.add(
            MockNewsArticle(title="ETF News 1"),
            classification,
            0.5,
            "medium",
            current_time=now,
        )
        memory.add(
            MockNewsArticle(title="ETF News 2"),
            classification,
            0.3,
            "high",
            current_time=now,
        )

        stats = memory.get_stats(now)

        assert stats["total_items"] == 2
        assert stats["actionable_items"] == 2
        assert stats["items_by_type"]["etf"] == 2
        assert stats["duplicates_blocked"] == 0

    def test_get_stats_empty_memory(self, memory):
        """Test stats with empty memory."""
        stats = memory.get_stats()

        assert stats["total_items"] == 0
        assert stats["actionable_items"] == 0
        assert stats["items_by_type"] == {}

    # --- Clear ---
    def test_clear(self, memory):
        """Test clearing memory."""
        now = datetime.now()
        classification = make_classification()

        memory.add(
            MockNewsArticle(title="News"),
            classification,
            0.5,
            "medium",
            current_time=now,
        )

        memory.clear()

        assert len(memory.get_all_items(now)) == 0


class TestMemorizedNews:
    """Tests for MemorizedNews dataclass."""

    def test_to_state_dict(self):
        """Test conversion to state dict format."""
        now = datetime.now()
        item = MemorizedNews(
            title="Test News",
            source="TestSource",
            published=now,
            collected_at=now,
            event_type="etf",
            is_actionable=True,
            content_hash="abc123",
            initial_sentiment=0.5,
            initial_impact="high",
        )

        state_dict = item.to_state_dict()

        assert state_dict["title"] == "Test News"
        assert state_dict["source"] == "TestSource"
        assert state_dict["event_type"] == "etf"
        assert state_dict["is_actionable"] is True
        assert state_dict["initial_sentiment"] == 0.5


class TestModuleSingleton:
    """Tests for module-level singleton pattern."""

    def test_set_and_get_news_memory(self):
        """Test setting and getting global news memory."""
        memory = NewsMemory()

        set_news_memory(memory)
        retrieved = get_news_memory()

        assert retrieved is memory

        # Cleanup
        set_news_memory(None)

    def test_get_news_memory_returns_none_when_not_set(self):
        """Test that get returns None when not configured."""
        set_news_memory(None)

        assert get_news_memory() is None
