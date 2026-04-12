"""Multi-timeframe trend analysis.

Analyzes trends across multiple timeframes to confirm trading signals
and reduce false positives from short-term noise.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from trading.core.models import OHLCV
from trading.indicators.trend import calculate_ema, calculate_macd

logger = logging.getLogger(__name__)

TrendDirection = Literal["bullish", "bearish", "neutral"]


@dataclass
class TimeframeTrend:
    """Trend analysis for a single timeframe."""

    timeframe: str  # "5m", "1h", "4h", "1d"
    trend: TrendDirection
    strength: float  # 0.0 to 1.0
    ema_short: float | None
    ema_long: float | None
    price_vs_ema: float  # % above/below EMA


@dataclass
class MultiTimeframeTrend:
    """Aggregated multi-timeframe trend analysis."""

    trends: dict[str, TimeframeTrend]  # timeframe -> trend
    aligned: bool  # Are trends aligned?
    alignment_count: int  # How many timeframes agree
    dominant_trend: TrendDirection  # Overall trend direction
    confidence_adjustment: float  # Adjustment to apply to confidence
    rapid_move_detected: bool  # Short-term rapid movement
    rapid_move_direction: TrendDirection | None  # Direction of rapid move

    def to_dict(self) -> dict:
        """Convert to dictionary for state."""
        return {
            "trends": {
                tf: {
                    "timeframe": t.timeframe,
                    "trend": t.trend,
                    "strength": t.strength,
                    "ema_short": t.ema_short,
                    "ema_long": t.ema_long,
                    "price_vs_ema": t.price_vs_ema,
                }
                for tf, t in self.trends.items()
            },
            "aligned": self.aligned,
            "alignment_count": self.alignment_count,
            "dominant_trend": self.dominant_trend,
            "confidence_adjustment": self.confidence_adjustment,
            "rapid_move_detected": self.rapid_move_detected,
            "rapid_move_direction": self.rapid_move_direction,
        }


class MultiTimeframeAnalyzer:
    """Analyzes trends across multiple timeframes."""

    # Timeframe configurations (aggressive: shorter EMAs for faster response)
    TIMEFRAME_CONFIG = {
        "5m": {"ema_short": 3, "ema_long": 12, "min_candles": 20},   # 15분 / 60분
        "1h": {"ema_short": 5, "ema_long": 13, "min_candles": 20},   # 5시간 / 13시간
        "4h": {"ema_short": 5, "ema_long": 13, "min_candles": 20},   # 20시간 / 52시간
        "1d": {"ema_short": 3, "ema_long": 12, "min_candles": 20},   # 3일 / 12일
    }

    # Rapid movement thresholds
    RAPID_MOVE_THRESHOLD_PCT = 2.0  # 2% move
    RAPID_MOVE_CANDLES = 3  # Within 3 candles (15 min for 5m candles)

    def __init__(
        self,
        alignment_threshold: int = 1,  # Aggressive: 1 timeframe enough for entry
        confidence_bonus: float = 0.1,
        confidence_penalty: float = 0.10,  # Reduced penalty for faster entry
    ):
        """Initialize analyzer.

        Args:
            alignment_threshold: Minimum timeframes that must agree (out of 4).
            confidence_bonus: Confidence boost when all timeframes align.
            confidence_penalty: Confidence reduction when trends conflict.
        """
        self.alignment_threshold = alignment_threshold
        self.confidence_bonus = confidence_bonus
        self.confidence_penalty = confidence_penalty

    def analyze_timeframe(
        self,
        timeframe: str,
        ohlcv: list[OHLCV],
    ) -> TimeframeTrend | None:
        """Analyze trend for a single timeframe.

        Args:
            timeframe: Timeframe identifier (e.g., "5m", "1h").
            ohlcv: OHLCV data for this timeframe.

        Returns:
            TimeframeTrend or None if insufficient data.
        """
        config = self.TIMEFRAME_CONFIG.get(timeframe)
        if not config:
            logger.warning(f"Unknown timeframe: {timeframe}")
            return None

        if len(ohlcv) < config["min_candles"]:
            logger.debug(
                f"{timeframe}: Insufficient data ({len(ohlcv)} < {config['min_candles']})"
            )
            return None

        # Calculate EMAs
        ema_short = calculate_ema(ohlcv, config["ema_short"])
        ema_long = calculate_ema(ohlcv, config["ema_long"])

        current_price = ohlcv[-1].close
        ema_s = ema_short[-1]
        ema_l = ema_long[-1]

        if ema_s is None or ema_l is None:
            return None

        # Calculate price vs EMA percentage
        price_vs_ema = ((current_price / ema_l) - 1) * 100

        # Determine trend and strength
        bullish_signals = 0
        bearish_signals = 0
        total_signals = 3

        # 1. Short EMA vs Long EMA
        if ema_s > ema_l:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # 2. Price vs Short EMA
        if current_price > ema_s:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # 3. Price vs Long EMA
        if current_price > ema_l:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # Determine trend
        if bullish_signals >= 2:
            trend: TrendDirection = "bullish"
            strength = bullish_signals / total_signals
        elif bearish_signals >= 2:
            trend = "bearish"
            strength = bearish_signals / total_signals
        else:
            trend = "neutral"
            strength = 0.5

        return TimeframeTrend(
            timeframe=timeframe,
            trend=trend,
            strength=strength,
            ema_short=ema_s,
            ema_long=ema_l,
            price_vs_ema=price_vs_ema,
        )

    def detect_rapid_move(
        self,
        ohlcv_5m: list[OHLCV],
    ) -> tuple[bool, TrendDirection | None]:
        """Detect rapid price movement in short timeframe.

        Args:
            ohlcv_5m: 5-minute OHLCV data.

        Returns:
            Tuple of (detected, direction).
        """
        if len(ohlcv_5m) < self.RAPID_MOVE_CANDLES + 1:
            return False, None

        # Get price change over recent candles
        recent_close = ohlcv_5m[-1].close
        past_close = ohlcv_5m[-(self.RAPID_MOVE_CANDLES + 1)].close

        if past_close <= 0:
            return False, None

        change_pct = ((recent_close / past_close) - 1) * 100

        if abs(change_pct) >= self.RAPID_MOVE_THRESHOLD_PCT:
            direction: TrendDirection = "bullish" if change_pct > 0 else "bearish"
            logger.info(
                f"Rapid move detected: {change_pct:+.2f}% in {self.RAPID_MOVE_CANDLES} candles"
            )
            return True, direction

        return False, None

    def analyze(
        self,
        ohlcv_5m: list[OHLCV] | None = None,
        ohlcv_1h: list[OHLCV] | None = None,
        ohlcv_4h: list[OHLCV] | None = None,
        ohlcv_1d: list[OHLCV] | None = None,
    ) -> MultiTimeframeTrend:
        """Analyze trends across all timeframes.

        Args:
            ohlcv_5m: 5-minute candles.
            ohlcv_1h: 1-hour candles.
            ohlcv_4h: 4-hour candles.
            ohlcv_1d: Daily candles.

        Returns:
            MultiTimeframeTrend with aggregated analysis.
        """
        trends: dict[str, TimeframeTrend] = {}

        # Analyze each timeframe
        if ohlcv_5m:
            trend = self.analyze_timeframe("5m", ohlcv_5m)
            if trend:
                trends["5m"] = trend

        if ohlcv_1h:
            trend = self.analyze_timeframe("1h", ohlcv_1h)
            if trend:
                trends["1h"] = trend

        if ohlcv_4h:
            trend = self.analyze_timeframe("4h", ohlcv_4h)
            if trend:
                trends["4h"] = trend

        if ohlcv_1d:
            trend = self.analyze_timeframe("1d", ohlcv_1d)
            if trend:
                trends["1d"] = trend

        # Detect rapid movement
        rapid_detected, rapid_direction = False, None
        if ohlcv_5m:
            rapid_detected, rapid_direction = self.detect_rapid_move(ohlcv_5m)

        # Count trend alignment
        bullish_count = sum(1 for t in trends.values() if t.trend == "bullish")
        bearish_count = sum(1 for t in trends.values() if t.trend == "bearish")
        total_trends = len(trends)

        # Determine dominant trend
        if bullish_count > bearish_count:
            dominant: TrendDirection = "bullish"
            alignment_count = bullish_count
        elif bearish_count > bullish_count:
            dominant = "bearish"
            alignment_count = bearish_count
        else:
            # Tie-breaker: prioritize mid-term timeframes (1h, 4h) for better signal
            mid_term_bullish = sum(
                1 for tf in ["1h", "4h"]
                if tf in trends and trends[tf].trend == "bullish"
            )
            mid_term_bearish = sum(
                1 for tf in ["1h", "4h"]
                if tf in trends and trends[tf].trend == "bearish"
            )

            if mid_term_bullish > mid_term_bearish:
                dominant = "bullish"
                alignment_count = bullish_count  # Still 2, but dominant is bullish
                logger.info(f"Tie-breaker: mid-term (1h,4h) favors bullish ({mid_term_bullish} vs {mid_term_bearish})")
            elif mid_term_bearish > mid_term_bullish:
                dominant = "bearish"
                alignment_count = bearish_count
                logger.info(f"Tie-breaker: mid-term (1h,4h) favors bearish ({mid_term_bearish} vs {mid_term_bullish})")
            else:
                dominant = "neutral"
                alignment_count = 0

        # Check alignment
        aligned = alignment_count >= self.alignment_threshold

        # Calculate confidence adjustment
        if total_trends == 0:
            confidence_adjustment = 0.0
        elif aligned and alignment_count == total_trends:
            # All timeframes agree - bonus
            confidence_adjustment = self.confidence_bonus
        elif aligned:
            # Most timeframes agree - small bonus
            confidence_adjustment = self.confidence_bonus * 0.5
        elif alignment_count < 2:
            # Strong disagreement - penalty
            confidence_adjustment = -self.confidence_penalty
        else:
            # Partial disagreement - small penalty
            confidence_adjustment = -self.confidence_penalty * 0.5

        # Log analysis (Bu=bullish, Be=bearish, N=neutral)
        trend_summary = ", ".join(
            f"{tf}={'Bu' if t.trend == 'bullish' else 'Be' if t.trend == 'bearish' else 'N'}"
            for tf, t in sorted(trends.items())
        )
        logger.info(
            f"MTF Analysis: [{trend_summary}] -> {dominant} "
            f"({alignment_count}/{total_trends} aligned, adj={confidence_adjustment:+.2f})"
        )

        return MultiTimeframeTrend(
            trends=trends,
            aligned=aligned,
            alignment_count=alignment_count,
            dominant_trend=dominant,
            confidence_adjustment=confidence_adjustment,
            rapid_move_detected=rapid_detected,
            rapid_move_direction=rapid_direction,
        )

    def should_trade(
        self,
        mtf: MultiTimeframeTrend,
        proposed_action: str,
    ) -> tuple[bool, str]:
        """Determine if trade should proceed based on MTF analysis.

        Args:
            mtf: Multi-timeframe trend analysis.
            proposed_action: Proposed action ("BUY", "SELL", "HOLD").

        Returns:
            Tuple of (should_trade, reason).
        """
        if proposed_action == "HOLD":
            return True, "HOLD action - no trend check needed"

        # Map action to required trend
        required_trend: TrendDirection = "bullish" if proposed_action == "BUY" else "bearish"

        # Rapid move override - allow trading with relaxed requirements
        if mtf.rapid_move_detected:
            if mtf.rapid_move_direction == required_trend:
                # Rapid move in same direction - check short-term trends only
                short_trends = [
                    mtf.trends.get("5m"),
                    mtf.trends.get("1h"),
                ]
                short_aligned = sum(
                    1 for t in short_trends if t and t.trend == required_trend
                )
                if short_aligned >= 1:
                    return True, f"Rapid {required_trend} move with short-term confirmation"
                return False, f"Rapid move but short-term trends don't confirm"
            else:
                # Rapid move in opposite direction
                return False, f"Rapid move in opposite direction ({mtf.rapid_move_direction})"

        # Normal mode - require trend alignment
        if mtf.dominant_trend == required_trend and mtf.aligned:
            return True, f"Trends aligned ({mtf.alignment_count} timeframes confirm {required_trend})"

        if mtf.dominant_trend == required_trend and not mtf.aligned:
            # Partial alignment - allow with warning
            if mtf.alignment_count >= 2:
                return True, f"Partial alignment ({mtf.alignment_count} timeframes), proceed with caution"
            return False, f"Insufficient trend alignment ({mtf.alignment_count} timeframes)"

        if mtf.dominant_trend != required_trend:
            if mtf.dominant_trend == "neutral":
                return False, "Trends neutral - waiting for clearer direction"
            return False, f"Trend conflict: {proposed_action} against {mtf.dominant_trend} trend"

        return False, "Unknown trend state"


# Module-level singleton
_analyzer: MultiTimeframeAnalyzer | None = None


def get_mtf_analyzer() -> MultiTimeframeAnalyzer:
    """Get global multi-timeframe analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = MultiTimeframeAnalyzer()
    return _analyzer
