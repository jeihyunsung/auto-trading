"""Tests for news event filtering and classification."""

from dataclasses import dataclass
from datetime import datetime

import pytest

from trading.core.news_filter import (
    ACTIONABLE_EVENTS,
    EventClassification,
    EventType,
    NewsEventFilter,
)


@dataclass
class MockNewsArticle:
    """Mock news article for testing."""

    title: str
    link: str = "https://example.com/news"
    source: str = "TestSource"
    published: datetime | None = None
    summary: str | None = None


class TestEventType:
    """Tests for EventType enum."""

    def test_actionable_events(self):
        """Verify actionable event types."""
        assert EventType.BREAKING in ACTIONABLE_EVENTS
        assert EventType.REGULATORY in ACTIONABLE_EVENTS
        assert EventType.LISTING in ACTIONABLE_EVENTS
        assert EventType.SECURITY in ACTIONABLE_EVENTS
        assert EventType.PARTNERSHIP in ACTIONABLE_EVENTS
        assert EventType.ETF in ACTIONABLE_EVENTS
        assert EventType.UNKNOWN in ACTIONABLE_EVENTS

    def test_non_actionable_events(self):
        """Verify non-actionable event types."""
        assert EventType.ANALYSIS not in ACTIONABLE_EVENTS
        assert EventType.EDUCATIONAL not in ACTIONABLE_EVENTS
        assert EventType.PREDICTION not in ACTIONABLE_EVENTS
        assert EventType.REHASH not in ACTIONABLE_EVENTS


class TestNewsEventFilter:
    """Tests for NewsEventFilter class."""

    @pytest.fixture
    def filter(self):
        """Create a filter instance."""
        return NewsEventFilter()

    # --- ETF Events ---
    @pytest.mark.parametrize(
        "title",
        [
            "Bitcoin ETF Approved by SEC",
            "Spot ETF Filing Submitted",
            "ETF Decision Expected This Week",
            "BlackRock Bitcoin ETF Gets Green Light",
        ],
    )
    def test_etf_classification(self, filter, title):
        """Test ETF event classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.ETF
        assert result.is_actionable is True
        assert result.confidence > 0.5

    # --- Regulatory Events ---
    @pytest.mark.parametrize(
        "title",
        [
            "SEC Files Lawsuit Against Crypto Exchange",
            "New Crypto Regulations Announced",
            "Government to Ban Bitcoin Mining",  # \bban\b pattern
            "Treasury Department Issues New Guidance",
            "Congress Passes Crypto Legislation",
        ],
    )
    def test_regulatory_classification(self, filter, title):
        """Test regulatory event classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.REGULATORY
        assert result.is_actionable is True

    # --- Security Events ---
    @pytest.mark.parametrize(
        "title",
        [
            "Major Exchange Hacked, $100M Stolen",
            "Security Breach at DeFi Protocol",
            "Exploit Drains Liquidity Pool",
            "Wallet Vulnerability Discovered",
            "Rug Pull: Users Lose Millions",
        ],
    )
    def test_security_classification(self, filter, title):
        """Test security event classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.SECURITY
        assert result.is_actionable is True

    # --- Listing Events ---
    @pytest.mark.parametrize(
        "title",
        [
            "Coinbase Adds Bitcoin Trading Pairs",
            "Token Listed on Binance",
            "Exchange Delists Controversial Coin",
            "New Listing Announcement",
        ],
    )
    def test_listing_classification(self, filter, title):
        """Test listing event classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.LISTING
        assert result.is_actionable is True

    # --- Partnership Events ---
    @pytest.mark.parametrize(
        "title",
        [
            "Microsoft Bitcoin Partnership Announced",  # microsoft.bitcoin pattern
            "Major Bank Adopts Cryptocurrency",
            "Institutional Investment in Bitcoin",
            "PayPal Bitcoin Integration Goes Live",
        ],
    )
    def test_partnership_classification(self, filter, title):
        """Test partnership event classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.PARTNERSHIP
        assert result.is_actionable is True

    # --- Breaking News ---
    @pytest.mark.parametrize(
        "title",
        [
            "BREAKING: Bitcoin Hits New Record",
            "Just In: Major Announcement",
            "URGENT: Market Flash Crash",
            "Alert: Price Movement",  # Avoid "regulatory" keyword
        ],
    )
    def test_breaking_classification(self, filter, title):
        """Test breaking news classification."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.BREAKING
        assert result.is_actionable is True

    # --- Analysis (Non-Actionable) ---
    @pytest.mark.parametrize(
        "title",
        [
            "Opinion: Why Bitcoin Will Succeed",
            "Analysis: Market Trends Explained",
            "Here's Why Bitcoin is Important",
            "Deep Dive into Crypto Markets",
            "The Case for Bitcoin Investment",
        ],
    )
    def test_analysis_filtered(self, filter, title):
        """Test analysis content is filtered out."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.ANALYSIS
        assert result.is_actionable is False

    # --- Predictions (Non-Actionable) ---
    @pytest.mark.parametrize(
        "title",
        [
            "Bitcoin Could Reach $100k by 2025",
            "Analyst Predicts Bull Run",
            "Price Target: $500k",
            "Bitcoin Expected to Surge",
            "Bullish on BTC: Forecast",
        ],
    )
    def test_prediction_filtered(self, filter, title):
        """Test prediction content is filtered out."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.PREDICTION
        assert result.is_actionable is False

    # --- Educational (Non-Actionable) ---
    @pytest.mark.parametrize(
        "title",
        [
            "How to Buy Bitcoin: Complete Guide",
            "Bitcoin 101: Beginner's Tutorial",
            "What is Blockchain Technology?",
            "Learn About Cryptocurrency",
            "Step by Step: Setting Up a Wallet",
        ],
    )
    def test_educational_filtered(self, filter, title):
        """Test educational content is filtered out."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.EDUCATIONAL
        assert result.is_actionable is False

    # --- Rehash (Non-Actionable) ---
    @pytest.mark.parametrize(
        "title",
        [
            "Looking Back: Bitcoin's Journey",
            "10 Years Ago: Bitcoin Launch",
            "Throwback: Historic Moments",
            "On This Day in Crypto History",
            "Anniversary of Bitcoin Whitepaper",
        ],
    )
    def test_rehash_filtered(self, filter, title):
        """Test rehash content is filtered out."""
        article = MockNewsArticle(title=title)
        result = filter.classify(article)

        assert result.event_type == EventType.REHASH
        assert result.is_actionable is False

    # --- Unknown (Default Actionable) ---
    def test_unknown_defaults_to_actionable(self, filter):
        """Test that unknown content defaults to actionable."""
        article = MockNewsArticle(title="Random neutral headline about crypto")
        result = filter.classify(article)

        assert result.event_type == EventType.UNKNOWN
        assert result.is_actionable is True
        assert result.confidence == 0.5

    # --- Filter Priority ---
    def test_exclusion_patterns_take_priority(self, filter):
        """Test that exclusion patterns override event patterns."""
        # This title has both ETF (event) and prediction (exclude) keywords
        article = MockNewsArticle(title="ETF Could Reach New Heights by 2025")
        result = filter.classify(article)

        # Should be filtered as prediction due to priority
        assert result.is_actionable is False

    def test_summary_included_in_classification(self, filter):
        """Test that summary is also analyzed for classification."""
        article = MockNewsArticle(
            title="News Update",
            summary="SEC announces new regulatory framework for cryptocurrency",
        )
        result = filter.classify(article)

        assert result.event_type == EventType.REGULATORY
        assert result.is_actionable is True

    # --- Filter Actionable Method ---
    def test_filter_actionable_returns_only_actionable(self, filter):
        """Test filter_actionable method."""
        articles = [
            MockNewsArticle(title="Bitcoin ETF Approved"),  # Actionable
            MockNewsArticle(title="How to Buy Bitcoin"),  # Not actionable
            MockNewsArticle(title="Exchange Hacked"),  # Actionable
            MockNewsArticle(title="Bitcoin Prediction: $100k"),  # Not actionable
        ]

        results = filter.filter_actionable(articles)

        assert len(results) == 2
        assert all(r[1].is_actionable for r in results)

    # --- Content Hash ---
    def test_content_hash_generation(self, filter):
        """Test content hash generation."""
        article = MockNewsArticle(title="Bitcoin ETF Approved by SEC")
        hash1 = filter.generate_content_hash(article)

        assert len(hash1) == 16
        assert hash1.isalnum()

    def test_content_hash_deterministic(self, filter):
        """Test that same title produces same hash."""
        article1 = MockNewsArticle(title="Bitcoin ETF Approved by SEC")
        article2 = MockNewsArticle(title="Bitcoin ETF Approved by SEC")

        assert filter.generate_content_hash(article1) == filter.generate_content_hash(
            article2
        )

    def test_content_hash_different_for_different_titles(self, filter):
        """Test that different titles produce different hashes."""
        article1 = MockNewsArticle(title="Bitcoin ETF Approved")
        article2 = MockNewsArticle(title="Ethereum Price Drops")

        assert filter.generate_content_hash(article1) != filter.generate_content_hash(
            article2
        )

    def test_content_hash_ignores_word_order(self, filter):
        """Test that word order doesn't affect hash (sorted words)."""
        article1 = MockNewsArticle(title="Bitcoin ETF Approved")
        article2 = MockNewsArticle(title="ETF Bitcoin Approved")

        # Same words, different order should produce same hash
        assert filter.generate_content_hash(article1) == filter.generate_content_hash(
            article2
        )

    # --- Recent Event Check ---
    def test_is_recent_event_with_recent_article(self, filter):
        """Test is_recent_event with recent article."""
        now = datetime.now()
        article = MockNewsArticle(title="Test", published=now)

        assert filter.is_recent_event(article, max_age_hours=24.0, current_time=now)

    def test_is_recent_event_with_old_article(self, filter):
        """Test is_recent_event with old article."""
        from datetime import timedelta

        now = datetime.now()
        old_time = now - timedelta(hours=48)
        article = MockNewsArticle(title="Test", published=old_time)

        assert not filter.is_recent_event(
            article, max_age_hours=24.0, current_time=now
        )

    def test_is_recent_event_without_date(self, filter):
        """Test is_recent_event assumes recent when no date."""
        article = MockNewsArticle(title="Test", published=None)

        assert filter.is_recent_event(article, max_age_hours=24.0)


class TestEventClassification:
    """Tests for EventClassification dataclass."""

    def test_event_classification_creation(self):
        """Test EventClassification creation."""
        classification = EventClassification(
            event_type=EventType.ETF,
            is_actionable=True,
            confidence=0.85,
            matched_patterns=[r"\betf\b", r"etf.approv"],
        )

        assert classification.event_type == EventType.ETF
        assert classification.is_actionable is True
        assert classification.confidence == 0.85
        assert len(classification.matched_patterns) == 2
