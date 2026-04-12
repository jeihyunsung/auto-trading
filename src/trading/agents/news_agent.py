"""News collection and analysis agent."""

import logging
from datetime import datetime, timedelta, timezone

# Korea Standard Time (UTC+9)
KST = timezone(timedelta(hours=9))

from trading.adapters.rss_collector import RSSNewsCollector
from trading.config import get_settings
from trading.core.news_filter import EventClassification, NewsEventFilter
from trading.core.news_memory import get_news_memory
from trading.core.state import NewsContext, NewsItem, TradingState
from trading.llm.client import get_llm_client
from trading.llm.prompts import NEWS_ANALYSIS_SYSTEM_PROMPT, NEWS_ANALYSIS_USER_PROMPT
from trading.llm.schemas import NewsAnalysisOutput

logger = logging.getLogger(__name__)

# Global news collection flag
_news_enabled: bool = True


def set_news_enabled(enabled: bool) -> None:
    """Set whether news collection is enabled.

    Args:
        enabled: True to enable news collection, False to disable.
    """
    global _news_enabled
    _news_enabled = enabled
    logger.info(f"News collection {'enabled' if enabled else 'disabled'}")


def is_news_enabled() -> bool:
    """Check if news collection is enabled.

    Returns:
        True if news collection is enabled.
    """
    return _news_enabled


class NewsAgent:
    """Agent for collecting and analyzing news.

    Supports two modes:
    1. Simple mode: Collects all BTC news without filtering
    2. Filtered mode: Filters out non-actionable news (analysis, opinions, etc.)
       and integrates with news memory system for time-decay weighting
    """

    # Sentiment blending weights
    # Reduced to give less weight to news sentiment in trading decisions
    # Only breaking news/events should have significant impact
    CURRENT_SENTIMENT_WEIGHT = 0.7
    MEMORY_SENTIMENT_WEIGHT = 0.3

    # Maximum absolute sentiment value (caps extreme sentiment)
    MAX_SENTIMENT_MAGNITUDE = 0.5

    # Freshness thresholds (hours)
    FRESH_NEWS_THRESHOLD_HOURS = 2.0  # News older than this gets reduced impact
    STALE_NEWS_THRESHOLD_HOURS = 6.0  # News older than this is considered stale

    def __init__(
        self,
        rss_collector: RSSNewsCollector | None = None,
        event_filter: NewsEventFilter | None = None,
        use_llm: bool = True,
        use_filtering: bool | None = None,
        use_memory: bool | None = None,
    ):
        """Initialize news agent.

        Args:
            rss_collector: RSS collector instance.
            event_filter: Event filter for classifying news.
            use_llm: Whether to use LLM for analysis.
            use_filtering: Enable event-based filtering. Defaults to settings.
            use_memory: Enable news memory system. Defaults to settings.
        """
        self.rss = rss_collector or RSSNewsCollector()
        self._filter = event_filter or NewsEventFilter()
        self.use_llm = use_llm

        # Load settings for defaults
        settings = get_settings()
        self.use_filtering = (
            use_filtering if use_filtering is not None
            else settings.news_filter_enabled
        )
        self.use_memory = (
            use_memory if use_memory is not None
            else settings.news_memory_enabled
        )

    def collect_and_analyze(self, limit: int = 10) -> NewsContext:
        """Collect news and perform sentiment analysis.

        When filtering is enabled, filters out non-actionable content
        (analysis, opinions, predictions, educational content).

        When memory is enabled, integrates with news memory system
        for time-decay weighted sentiment calculation.

        Args:
            limit: Maximum news articles to analyze.

        Returns:
            NewsContext with analysis results.
        """
        logger.info(
            f"Collecting news (limit={limit}, "
            f"filtering={self.use_filtering}, memory={self.use_memory})"
        )

        # Collect news with or without filtering
        if self.use_filtering:
            filtered_articles = self.rss.fetch_btc_news_filtered(
                limit=limit, event_filter=self._filter
            )
            articles = [a for a, _ in filtered_articles]
            classifications = {a.title: c for a, c in filtered_articles}
        else:
            articles = self.rss.fetch_btc_news(limit=limit)
            classifications = {}

        headlines = [a.title for a in articles]

        # Convert to NewsItem format
        news_items: list[NewsItem] = [
            NewsItem(
                title=a.title,
                source=a.source,
                published=a.published.isoformat() if a.published else None,
            )
            for a in articles
        ]

        if not headlines:
            return NewsContext(
                headlines=[],
                articles=[],
                sentiment=0.0,
                impact="low",
                summary="No recent actionable news available.",
            )

        # Calculate news freshness weight
        freshness_weight, newest_age_hours = self._calculate_freshness_weight(articles)

        if newest_age_hours >= self.STALE_NEWS_THRESHOLD_HOURS:
            logger.warning(
                f"News is stale: newest article is {newest_age_hours:.1f}h old. "
                f"Reducing impact weight to {freshness_weight:.2f}"
            )
        elif newest_age_hours > self.FRESH_NEWS_THRESHOLD_HOURS:
            logger.info(
                f"News freshness: {newest_age_hours:.1f}h old, weight={freshness_weight:.2f}"
            )

        # Analyze current batch sentiment
        if self.use_llm:
            analysis = self._analyze_with_llm(headlines)
        else:
            analysis = self._analyze_simple(articles)

        # Apply freshness weight to sentiment (reduce impact of stale news)
        raw_sentiment = analysis["sentiment"]
        current_sentiment = raw_sentiment * freshness_weight
        current_impact = analysis["impact"]

        # Downgrade impact if news is stale
        if freshness_weight < 0.5 and current_impact == "high":
            current_impact = "medium"
            logger.info("Downgraded impact from high to medium due to stale news")

        # Cap sentiment to reduce extreme news impact
        current_sentiment = max(
            -self.MAX_SENTIMENT_MAGNITUDE,
            min(self.MAX_SENTIMENT_MAGNITUDE, current_sentiment)
        )

        # Integrate with memory system
        memory = get_news_memory() if self.use_memory else None
        memorized_articles = []
        memory_stats = None

        if memory is not None:
            now = datetime.now(KST)

            # Add articles to memory
            for article in articles:
                classification = classifications.get(article.title)
                if classification is None:
                    # Generate classification if not already done
                    classification = self._filter.classify(article)

                # Use current analysis for this article's sentiment/impact
                article_impact = self.rss.classify_impact(article)

                memory.add(
                    article=article,
                    classification=classification,
                    sentiment=current_sentiment,
                    impact=article_impact,
                    current_time=now,
                )

            # Get weighted sentiment from memory
            memory_sentiment, total_weight = memory.get_weighted_sentiment(now)
            memory_impact = memory.get_highest_impact(now)

            # Blend current and memory sentiment
            if total_weight > 0:
                blended_sentiment = (
                    current_sentiment * self.CURRENT_SENTIMENT_WEIGHT
                    + memory_sentiment * self.MEMORY_SENTIMENT_WEIGHT
                )
                # Cap blended sentiment as well
                blended_sentiment = max(
                    -self.MAX_SENTIMENT_MAGNITUDE,
                    min(self.MAX_SENTIMENT_MAGNITUDE, blended_sentiment)
                )
                logger.debug(
                    f"Sentiment blending: current={current_sentiment:.2f}, "
                    f"memory={memory_sentiment:.2f}, blended={blended_sentiment:.2f}"
                )
            else:
                blended_sentiment = current_sentiment

            # Use highest impact from recent memory
            final_impact = self._get_higher_impact(current_impact, memory_impact)

            # Get memory state for context
            memorized_articles = memory.get_all_items(now)
            memory_stats = memory.get_stats(now)

            logger.info(
                f"News memory: {memory_stats['total_items']} items, "
                f"{memory_stats['actionable_items']} actionable, "
                f"blended_sentiment={blended_sentiment:.2f}"
            )
        else:
            blended_sentiment = current_sentiment
            final_impact = current_impact

        # Build summary with freshness info
        summary = analysis["summary"]
        if newest_age_hours < float("inf"):
            if freshness_weight < 1.0:
                summary += f" [News age: {newest_age_hours:.1f}h, weight: {freshness_weight:.0%}]"
        if memory is not None and memory_stats:
            summary += f" (Memory: {memory_stats['total_items']} items)"

        return NewsContext(
            headlines=headlines[:10],
            articles=news_items[:10],
            sentiment=blended_sentiment,
            impact=final_impact,
            summary=summary,
            memorized_articles=memorized_articles,
            memory_stats=memory_stats,
        )

    def _get_higher_impact(self, impact1: str, impact2: str) -> str:
        """Return the higher of two impact levels.

        Args:
            impact1: First impact level.
            impact2: Second impact level.

        Returns:
            Higher impact level.
        """
        priority = {"high": 3, "medium": 2, "low": 1}
        if priority.get(impact1, 0) >= priority.get(impact2, 0):
            return impact1
        return impact2

    def _calculate_freshness_weight(self, articles: list) -> tuple[float, float]:
        """Calculate freshness weight based on newest article age.

        If the newest article is old, reduce its influence on decisions.

        Args:
            articles: List of NewsArticle objects.

        Returns:
            Tuple of (freshness_weight, newest_age_hours).
            freshness_weight: 1.0 for fresh news, decreasing for stale news.
        """
        from datetime import timezone

        if not articles:
            return 0.0, float("inf")

        now_utc = datetime.now(timezone.utc)
        newest_age_hours = float("inf")

        for article in articles:
            if article.published:
                try:
                    pub_dt = article.published
                    # Ensure timezone-aware comparison (assume UTC if naive)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    age_hours = (now_utc - pub_dt).total_seconds() / 3600
                    newest_age_hours = min(newest_age_hours, age_hours)
                except (ValueError, TypeError):
                    continue

        if newest_age_hours == float("inf"):
            return 0.5, newest_age_hours  # No valid timestamps, use half weight

        # Calculate freshness weight
        if newest_age_hours <= self.FRESH_NEWS_THRESHOLD_HOURS:
            # Fresh news - full weight
            weight = 1.0
        elif newest_age_hours >= self.STALE_NEWS_THRESHOLD_HOURS:
            # Stale news - minimum weight
            weight = 0.3
        else:
            # Linear decay between thresholds
            range_hours = self.STALE_NEWS_THRESHOLD_HOURS - self.FRESH_NEWS_THRESHOLD_HOURS
            decay = (newest_age_hours - self.FRESH_NEWS_THRESHOLD_HOURS) / range_hours
            weight = 1.0 - (0.7 * decay)  # Decays from 1.0 to 0.3

        return weight, newest_age_hours

    def _analyze_with_llm(self, headlines: list[str]) -> dict:
        """Analyze news with LLM.

        Args:
            headlines: List of headlines.

        Returns:
            Analysis dict with sentiment, impact, summary.
        """
        try:
            llm = get_llm_client()
            if not llm.is_available:
                return self._analyze_simple_headlines(headlines)

            headlines_text = "\n".join(f"- {h}" for h in headlines[:10])
            prompt = NEWS_ANALYSIS_USER_PROMPT.format(headlines=headlines_text)

            result = llm.invoke_json(
                NEWS_ANALYSIS_SYSTEM_PROMPT,
                prompt,
                NewsAnalysisOutput,
            )

            return {
                "sentiment": result.sentiment,
                "impact": result.impact,
                "summary": result.summary,
            }

        except Exception as e:
            logger.warning(f"LLM news analysis failed: {e}")
            return self._analyze_simple_headlines(headlines)

    def _analyze_simple(self, articles: list) -> dict:
        """Simple rule-based analysis without LLM.

        Args:
            articles: List of NewsArticle objects.

        Returns:
            Analysis dict.
        """
        headlines = [a.title for a in articles]
        return self._analyze_simple_headlines(headlines)

    def _analyze_simple_headlines(self, headlines: list[str]) -> dict:
        """Simple keyword-based analysis.

        Args:
            headlines: List of headline strings.

        Returns:
            Analysis dict.
        """
        # Simple keyword-based sentiment
        positive_keywords = {
            "surge", "rally", "gain", "rise", "bull", "approve", "adopt",
            "breakthrough", "record", "high", "growth", "positive", "upgrade",
        }
        negative_keywords = {
            "crash", "drop", "fall", "bear", "reject", "ban", "hack",
            "breach", "concern", "fear", "decline", "sell", "warning",
        }
        high_impact_keywords = {
            "etf", "sec", "regulation", "fed", "rate", "institutional",
            "government", "ban", "hack", "billion",
        }

        text = " ".join(headlines).lower()

        # Count keywords
        pos_count = sum(1 for k in positive_keywords if k in text)
        neg_count = sum(1 for k in negative_keywords if k in text)
        impact_count = sum(1 for k in high_impact_keywords if k in text)

        # Calculate sentiment (-1 to 1)
        total = pos_count + neg_count
        if total > 0:
            sentiment = (pos_count - neg_count) / total
        else:
            sentiment = 0.0

        # Determine impact
        if impact_count >= 2:
            impact = "high"
        elif impact_count >= 1:
            impact = "medium"
        else:
            impact = "low"

        # Generate simple summary
        summary = f"{len(headlines)} recent headlines. "
        if sentiment > 0.3:
            summary += "Overall sentiment is positive."
        elif sentiment < -0.3:
            summary += "Overall sentiment is negative."
        else:
            summary += "Sentiment is mixed/neutral."

        return {
            "sentiment": sentiment,
            "impact": impact,
            "summary": summary,
        }

    def get_headlines_only(self, limit: int = 5) -> list[str]:
        """Get recent headlines without analysis.

        Args:
            limit: Maximum headlines.

        Returns:
            List of headline strings.
        """
        return self.rss.get_headlines(limit=limit)


def news_agent_node(state: TradingState) -> dict:
    """LangGraph node function for news agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with news context.
    """
    # Check if news collection is disabled
    if not _news_enabled:
        logger.info("News collection disabled - returning neutral context")
        return {
            "news": NewsContext(
                headlines=[],
                articles=[],
                sentiment=0.0,
                impact="low",
                summary="News collection disabled - using technical analysis only.",
            ),
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    agent = NewsAgent()

    try:
        news_context = agent.collect_and_analyze()

        return {
            "news": news_context,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"News agent failed: {e}")
        return {
            "news": NewsContext(
                headlines=[],
                articles=[],
                sentiment=0.0,
                impact="low",
                summary=f"News collection failed: {e}",
            ),
            "error": f"News agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
