"""News event classification and filtering.

Filters out non-actionable news (analysis, opinions, educational content)
to focus on real-time market events that may impact trading decisions.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.adapters.rss_collector import NewsArticle

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """News event type classification."""

    # Actionable events
    BREAKING = "breaking"
    REGULATORY = "regulatory"
    LISTING = "listing"
    SECURITY = "security"
    PARTNERSHIP = "partnership"
    ETF = "etf"

    # Non-actionable content (to filter out)
    ANALYSIS = "analysis"
    EDUCATIONAL = "educational"
    PREDICTION = "prediction"
    REHASH = "rehash"
    UNKNOWN = "unknown"


# Actionable event types that should be included in decisions
# STRICT MODE: Only include clearly identified breaking news/events
# UNKNOWN is excluded to filter out general analysis articles
ACTIONABLE_EVENTS = {
    EventType.BREAKING,
    EventType.REGULATORY,
    EventType.LISTING,
    EventType.SECURITY,
    EventType.PARTNERSHIP,
    EventType.ETF,
    # EventType.UNKNOWN excluded - if we can't identify it as an event, skip it
}


@dataclass
class EventClassification:
    """Result of news event classification."""

    event_type: EventType
    is_actionable: bool
    confidence: float
    matched_patterns: list[str]


class NewsEventFilter:
    """Classifies and filters news by event type.

    Uses keyword patterns to identify event types and filter out
    non-actionable content like analysis, opinions, and educational content.
    """

    # Patterns for actionable events (INCLUDE)
    EVENT_PATTERNS: dict[EventType, set[str]] = {
        EventType.ETF: {
            r"\betf\b",
            r"exchange.traded.fund",
            r"spot.etf",
            r"etf.approv",
            r"etf.reject",
            r"etf.fil",
            r"etf.decision",
            r"bitcoin.etf",
        },
        EventType.REGULATORY: {
            r"\bsec\b",
            r"securities.commission",
            r"regulat",
            r"\bban\b",
            r"banned",
            r"banning",
            r"legal",
            r"legislation",
            r"congress",
            r"senate",
            r"lawmaker",
            r"cftc",
            r"fincen",
            r"treasury",
            r"enforcement",
            r"lawsuit",
            r"indictment",
            r"compliance",
        },
        EventType.LISTING: {
            r"list(?:ed|ing)\s+(?:on|at)",
            r"delist",
            r"add(?:ed|ing|s)?\s+(?:to|on)",
            r"trading.pair",
            r"coinbase.add",
            r"binance.list",
            r"kraken.add",
            r"new.listing",
        },
        EventType.SECURITY: {
            r"\bhack\b",
            r"hacked",
            r"hacking",
            r"breach",
            r"exploit",
            r"stolen",
            r"theft",
            r"vulnerability",
            r"attack",
            r"compromised",
            r"security.incident",
            r"drained",
            r"rug.?pull",
        },
        EventType.PARTNERSHIP: {
            r"partner(?:ship|ed|ing)",
            r"collaborat",
            r"integrat",
            r"adopt(?:s|ed|ion)",
            r"alliance",
            r"deal.with",
            r"agreement",
            r"microsoft.bitcoin",
            r"google.bitcoin",
            r"amazon.bitcoin",
            r"visa.bitcoin",
            r"mastercard.bitcoin",
            r"paypal.bitcoin",
            r"institutional",
            r"major.investment",
        },
        EventType.BREAKING: {
            r"breaking:",
            r"breaking\s+news",
            r"just.in:",
            r"urgent:",
            r"flash:",
            r"happening.now",
            r"live:",
            r"alert:",
        },
    }

    # Patterns for non-actionable content (EXCLUDE)
    # Enhanced to filter out analysis, predictions, opinions, and historical content
    EXCLUDE_PATTERNS: dict[EventType, set[str]] = {
        EventType.ANALYSIS: {
            r"opinion:",
            r"analysis:",
            r"why.bitcoin",
            r"here.?s.why",
            r"explained",
            r"understanding",
            r"perspective",
            r"viewpoint",
            r"commentary",
            r"insight:",
            r"deep.dive",
            r"breakdown",
            r"what.it.means",
            r"the.case.for",
            r"the.case.against",
            # Additional analysis patterns
            r"analyst.says",
            r"analysts.say",
            r"expert.says",
            r"experts.say",
            r"according.to.analyst",
            r"market.watch",
            r"technical.analysis",
            r"chart.analysis",
            r"price.analysis",
            r"weekly.analysis",
            r"daily.analysis",
            r"review:",
            r"report:",
            r"research:",
            r"study.shows",
            r"data.shows",
            r"survey",
            r"poll",
        },
        EventType.PREDICTION: {
            r"could.reach",
            r"might.hit",
            r"will.reach",
            r"predict",
            r"forecast",
            r"outlook",
            r"target.price",
            r"price.target",
            r"expected.to",
            r"likely.to",
            r"bullish.on",
            r"bearish.on",
            r"\$\d+k",  # Price targets like $100k
            r"by.20\d\d",  # Time predictions
            # Additional prediction patterns
            r"could.hit",
            r"could.drop",
            r"could.surge",
            r"may.reach",
            r"set.to",
            r"poised.to",
            r"headed.for",
            r"heading.to",
            r"on.track.to",
            r"eyes.\$",
            r"targets.\$",
            r"if.bitcoin",
            r"when.bitcoin",
            r"next.bull",
            r"next.bear",
            r"price.prediction",
            r"where.bitcoin",
        },
        EventType.EDUCATIONAL: {
            r"how.to",
            r"guide:",
            r"tutorial",
            r"beginner",
            r"what.is",
            r"\b101\b",
            r"introduction.to",
            r"learn.about",
            r"tips.for",
            r"basics.of",
            r"everything.you.need",
            r"complete.guide",
            r"step.by.step",
        },
        EventType.REHASH: {
            r"look(?:ing)?.back",
            r"anniversary",
            r"years?.ago",
            r"history.of",
            r"remember.when",
            r"revisit",
            r"throwback",
            r"flashback",
            r"on.this.day",
            r"recap",
            # Additional rehash patterns
            r"in.review",
            r"week.in.review",
            r"month.in.review",
            r"year.in.review",
            r"what.happened",
            r"this.week",
            r"last.week",
            r"past.week",
            r"previously",
        },
    }

    def __init__(self):
        """Initialize filter with compiled patterns."""
        self._compiled_event: dict[EventType, list[re.Pattern]] = {}
        self._compiled_exclude: dict[EventType, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        for event_type, patterns in self.EVENT_PATTERNS.items():
            self._compiled_event[event_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        for event_type, patterns in self.EXCLUDE_PATTERNS.items():
            self._compiled_exclude[event_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def classify(self, article: "NewsArticle") -> EventClassification:
        """Classify a news article by event type.

        Args:
            article: News article to classify.

        Returns:
            EventClassification with type, actionability, and confidence.
        """
        text = f"{article.title} {article.summary or ''}".lower()
        matched_event: list[tuple[EventType, str]] = []
        matched_exclude: list[tuple[EventType, str]] = []

        # Check exclusion patterns first (higher priority)
        for event_type, patterns in self._compiled_exclude.items():
            for pattern in patterns:
                if pattern.search(text):
                    matched_exclude.append((event_type, pattern.pattern))

        # If exclusion patterns matched, filter out this article
        if matched_exclude:
            primary_type = matched_exclude[0][0]
            return EventClassification(
                event_type=primary_type,
                is_actionable=False,
                confidence=min(0.9, 0.7 + 0.05 * len(matched_exclude)),
                matched_patterns=[m[1] for m in matched_exclude[:3]],
            )

        # Check event patterns
        for event_type, patterns in self._compiled_event.items():
            for pattern in patterns:
                if pattern.search(text):
                    matched_event.append((event_type, pattern.pattern))

        if not matched_event:
            return EventClassification(
                event_type=EventType.UNKNOWN,
                is_actionable=False,  # STRICT: Unknown news is not actionable
                confidence=0.5,
                matched_patterns=[],
            )

        # Use the first (highest priority) match
        primary_type = matched_event[0][0]
        return EventClassification(
            event_type=primary_type,
            is_actionable=primary_type in ACTIONABLE_EVENTS,
            confidence=min(0.95, 0.6 + 0.1 * len(matched_event)),
            matched_patterns=[m[1] for m in matched_event[:3]],
        )

    def filter_actionable(
        self, articles: list["NewsArticle"]
    ) -> list[tuple["NewsArticle", EventClassification]]:
        """Filter articles to only actionable events.

        Args:
            articles: List of news articles to filter.

        Returns:
            List of (article, classification) tuples for actionable events.
        """
        results: list[tuple["NewsArticle", EventClassification]] = []
        filtered_count = 0

        for article in articles:
            classification = self.classify(article)
            if classification.is_actionable:
                results.append((article, classification))
            else:
                filtered_count += 1
                logger.debug(
                    f"Filtered non-event: {article.title[:60]}... "
                    f"(type={classification.event_type.value})"
                )

        if filtered_count > 0:
            logger.info(
                f"News filter: {len(results)} actionable, "
                f"{filtered_count} filtered out"
            )

        return results

    @staticmethod
    def generate_content_hash(article: "NewsArticle") -> str:
        """Generate hash for duplicate detection.

        Uses normalized title words to detect similar articles about the same event.

        Args:
            article: News article.

        Returns:
            16-character hash string.
        """
        # Normalize: lowercase, remove punctuation, sort words
        normalized = re.sub(r"[^\w\s]", "", article.title.lower())
        words = sorted(normalized.split())[:10]  # First 10 sorted words
        content = " ".join(words)
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def is_recent_event(
        self,
        article: "NewsArticle",
        max_age_hours: float = 24.0,
        current_time: datetime | None = None,
    ) -> bool:
        """Check if article is about a recent event.

        Args:
            article: News article to check.
            max_age_hours: Maximum age in hours.
            current_time: Current time (for testing).

        Returns:
            True if article is recent enough.
        """
        if article.published is None:
            return True  # Assume recent if no date

        now = current_time or datetime.now()
        try:
            # Handle various date formats
            if isinstance(article.published, datetime):
                pub_time = article.published
            else:
                pub_time = datetime.fromisoformat(
                    article.published.replace("Z", "+00:00")
                )
                # Make naive for comparison if needed
                if pub_time.tzinfo is not None:
                    pub_time = pub_time.replace(tzinfo=None)

            age_hours = (now - pub_time).total_seconds() / 3600
            return age_hours <= max_age_hours
        except (ValueError, TypeError):
            return True  # Assume recent if date parsing fails
