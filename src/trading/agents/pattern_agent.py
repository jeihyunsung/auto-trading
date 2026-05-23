"""Chart pattern recognition agent using LLM vision.

Generates candlestick chart images from OHLCV data and uses GPT-4o vision
to detect chart patterns (Double Bottom/Top, H&S, Triangle, etc.).

Cost-optimized: Only triggers when market conditions warrant analysis
(price change > 1% or Bollinger Band breakout).
"""

import io
import logging
from base64 import b64encode
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from trading.core.models import OHLCV
from trading.core.state import TradingState
from trading.core.time import KST
from trading.indicators.trend_channel import (
    TrendChannelResult,
    calculate_trend_channel,
)

logger = logging.getLogger(__name__)


class PatternOutput(BaseModel):
    """Structured output from chart pattern analysis."""

    pattern: str = Field(
        description="Detected pattern name: double_bottom, double_top, "
        "head_and_shoulders, inverse_head_and_shoulders, "
        "ascending_triangle, descending_triangle, symmetrical_triangle, "
        "rising_wedge, falling_wedge, v_reversal, none"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Pattern detection confidence",
    )
    direction: Literal["bullish", "bearish", "neutral"] = Field(
        description="Expected price direction from pattern",
    )
    description: str = Field(
        description="Brief description of the pattern and its implications (Korean)",
    )


# Pattern analysis prompts
PATTERN_SYSTEM_PROMPT = """You are an expert technical chart analyst specializing in candlestick patterns.
Analyze the provided BTC chart image and identify any recognizable chart patterns.

## Detectable Patterns
- double_bottom: Two similar lows with resistance between (bullish reversal)
- double_top: Two similar highs with support between (bearish reversal)
- head_and_shoulders: Three peaks, middle highest (bearish reversal)
- inverse_head_and_shoulders: Three troughs, middle lowest (bullish reversal)
- ascending_triangle: Flat resistance + rising support (bullish continuation)
- descending_triangle: Flat support + falling resistance (bearish continuation)
- symmetrical_triangle: Converging support and resistance (breakout pending)
- rising_wedge: Rising support and resistance converging (bearish reversal)
- falling_wedge: Falling support and resistance converging (bullish reversal)
- v_reversal: Sharp V-shaped reversal (direction depends on context)
- none: No clear pattern detected

## Rules
- Report the MOST prominent pattern only
- Confidence should reflect how clearly the pattern is formed
- If pattern is incomplete/forming, use lower confidence (0.3-0.5)
- If no clear pattern, return "none" with confidence 0.0

## Response Language
Write the description in Korean (한국어).

Return JSON: {"pattern": str, "confidence": float, "direction": str, "description": str}
"""

PATTERN_USER_PROMPT = """Analyze this BTC candlestick chart for chart patterns.

Additional context:
- Trend channel slope: {slope_direction}
- Channel position: {position_in_channel:.0%} (0%=lower band, 100%=upper band)
- Channel width: {channel_width:.1f}%
- Support levels: {supports}
- Resistance levels: {resistances}

Identify the most prominent chart pattern and its trading implication."""


def should_analyze_pattern(state: TradingState) -> bool:
    """Determine if pattern analysis should run this cycle.

    Triggers on significant price movement or Bollinger Band breakout
    to avoid unnecessary LLM vision API costs.

    Args:
        state: Current trading state.

    Returns:
        True if pattern analysis should be triggered.
    """
    market = state.get("market")
    indicators = state.get("indicators")

    if not market:
        return False

    # Trigger 1: Significant price change (>1% in 1h or >2% in 24h)
    change_24h = abs(market.get("percent_change_24h", 0))
    change_1h = abs(market.get("percent_change_1h", 0))
    if change_1h >= 1.0 or change_24h >= 2.0:
        logger.info(
            f"Pattern trigger: price change (1h={change_1h:.1f}%, 24h={change_24h:.1f}%)"
        )
        return True

    # Trigger 2: High volatility
    if market.get("volatility_level") == "high":
        logger.info("Pattern trigger: high volatility")
        return True

    # Trigger 3: Bollinger Band breakout
    if indicators:
        signals = indicators.get("signals", {})
        current_price = market.get("current_price", 0)
        bb_upper = signals.get("bb_upper", 0)
        bb_lower = signals.get("bb_lower", 0)

        if current_price > 0 and bb_upper > 0:
            if current_price > bb_upper or current_price < bb_lower:
                logger.info("Pattern trigger: Bollinger Band breakout")
                return True

    logger.debug("Pattern analysis skipped - no trigger conditions met")
    return False


def generate_chart_image(ohlcv: list[OHLCV], lookback: int = 60) -> bytes | None:
    """Generate a candlestick chart image from OHLCV data.

    Args:
        ohlcv: List of OHLCV candles.
        lookback: Number of candles to display.

    Returns:
        PNG image bytes, or None if generation fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        logger.warning("matplotlib not available - chart generation disabled")
        return None

    candles = ohlcv[-lookback:]
    if len(candles) < 10:
        return None

    fig, ax = plt.subplots(figsize=(12, 6))

    # Draw candlesticks
    for i, c in enumerate(candles):
        color = "#26a69a" if c.close >= c.open else "#ef5350"
        body_bottom = min(c.open, c.close)
        body_height = abs(c.close - c.open)

        # Wick
        ax.plot([i, i], [c.low, c.high], color=color, linewidth=0.8)
        # Body
        ax.bar(i, body_height, bottom=body_bottom, width=0.6, color=color, edgecolor=color)

    # Add support/resistance lines from trend channel
    channel = calculate_trend_channel(candles)
    if channel:
        n = len(candles)
        x = list(range(n))

        # Regression channel
        slope = channel.slope
        intercept = channel.midline - slope * (n - 1)
        midline = [slope * xi + intercept for xi in x]
        std = (channel.upper_band - channel.midline) / 2

        ax.plot(x, midline, color="blue", linewidth=1, linestyle="--", alpha=0.7)
        ax.plot(x, [m + 2 * std for m in midline], color="gray", linewidth=0.8, linestyle=":", alpha=0.5)
        ax.plot(x, [m - 2 * std for m in midline], color="gray", linewidth=0.8, linestyle=":", alpha=0.5)

        # Support/resistance horizontal lines
        for s in channel.support_levels[:2]:
            ax.axhline(y=s, color="#4caf50", linewidth=0.8, linestyle="-.", alpha=0.5)
        for r in channel.resistance_levels[:2]:
            ax.axhline(y=r, color="#f44336", linewidth=0.8, linestyle="-.", alpha=0.5)

    ax.set_title("BTC/KRW", fontsize=14)
    ax.set_ylabel("Price (KRW)")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    # Save to bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


class PatternAgent:
    """Agent for chart pattern recognition using LLM vision."""

    def analyze(self, state: TradingState) -> dict | None:
        """Analyze chart patterns from OHLCV data.

        Args:
            state: Current trading state.

        Returns:
            Pattern analysis dict, or None if analysis is skipped.
        """
        market = state.get("market")
        if not market:
            return None

        ohlcv_data = market.get("ohlcv", [])
        if not ohlcv_data or len(ohlcv_data) < 20:
            return None

        # Convert to OHLCV objects
        ohlcv = [
            OHLCV(
                timestamp=datetime.fromisoformat(c["timestamp"])
                if isinstance(c["timestamp"], str)
                else c["timestamp"],
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=c["volume"],
            )
            for c in ohlcv_data
        ]

        # Calculate trend channel for context
        channel = calculate_trend_channel(ohlcv)

        # Try vision-based analysis first
        pattern = self._analyze_with_vision(ohlcv, channel)
        if pattern is not None:
            return pattern

        # Fallback: rule-based pattern detection
        return self._analyze_rule_based(ohlcv, channel)

    def _analyze_with_vision(
        self,
        ohlcv: list[OHLCV],
        channel: TrendChannelResult | None,
    ) -> dict | None:
        """Analyze chart using LLM vision API.

        Args:
            ohlcv: OHLCV candle data.
            channel: Trend channel result for context.

        Returns:
            Pattern analysis dict or None if vision unavailable.
        """
        from trading.config import get_settings
        from trading.llm.client import get_llm_client

        settings = get_settings()
        vision_model = settings.openai_model_vision

        # Generate chart image
        image_bytes = generate_chart_image(ohlcv)
        if image_bytes is None:
            return None

        # Prepare context from trend channel
        if channel:
            slope_dir = "upward" if channel.slope > 0 else "downward" if channel.slope < 0 else "flat"
            supports = ", ".join(f"{s:,.0f}" for s in channel.support_levels) or "none"
            resistances = ", ".join(f"{r:,.0f}" for r in channel.resistance_levels) or "none"
            prompt = PATTERN_USER_PROMPT.format(
                slope_direction=slope_dir,
                position_in_channel=channel.position_in_channel,
                channel_width=channel.channel_width_pct,
                supports=supports,
                resistances=resistances,
            )
        else:
            prompt = "Analyze this BTC candlestick chart for chart patterns."

        try:
            llm = get_llm_client()
            if not llm.is_available:
                return None

            # Use vision model for chart analysis
            image_b64 = b64encode(image_bytes).decode("utf-8")

            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI

            vision_client = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=vision_model,
                temperature=0.1,
            )

            messages = [
                SystemMessage(content=PATTERN_SYSTEM_PROMPT),
                HumanMessage(content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "low",  # Cost optimization
                        },
                    },
                ]),
            ]

            response = vision_client.invoke(messages)

            # Parse JSON from response (handles markdown fenced blocks)
            from trading.llm.client import LLMClient
            result = LLMClient._parse_json_response(response.content, PatternOutput)

            logger.info(
                f"Pattern detected: {result.pattern} "
                f"(confidence={result.confidence:.0%}, direction={result.direction})"
            )

            return {
                "pattern": result.pattern,
                "confidence": result.confidence,
                "direction": result.direction,
                "description": result.description,
                "source": "vision",
            }

        except Exception as e:
            logger.warning(f"Vision pattern analysis failed: {e}")
            return None

    def _analyze_rule_based(
        self,
        ohlcv: list[OHLCV],
        channel: TrendChannelResult | None,
    ) -> dict:
        """Rule-based pattern detection as fallback.

        Detects simple patterns without LLM.

        Args:
            ohlcv: OHLCV candle data.
            channel: Trend channel result.

        Returns:
            Pattern analysis dict.
        """
        if len(ohlcv) < 20:
            return _no_pattern()

        closes = [c.close for c in ohlcv[-30:]]
        highs = [c.high for c in ohlcv[-30:]]
        lows = [c.low for c in ohlcv[-30:]]

        # V-reversal detection: sharp drop followed by sharp recovery
        if len(closes) >= 10:
            mid = len(closes) // 2
            first_half_change = (closes[mid] - closes[0]) / closes[0] * 100
            second_half_change = (closes[-1] - closes[mid]) / closes[mid] * 100

            if first_half_change < -3.0 and second_half_change > 2.0:
                return {
                    "pattern": "v_reversal",
                    "confidence": min(0.7, abs(second_half_change) / 5),
                    "direction": "bullish",
                    "description": f"V자 반등 패턴: {first_half_change:.1f}% 하락 후 {second_half_change:.1f}% 반등",
                    "source": "rule_based",
                }

            if first_half_change > 3.0 and second_half_change < -2.0:
                return {
                    "pattern": "v_reversal",
                    "confidence": min(0.7, abs(second_half_change) / 5),
                    "direction": "bearish",
                    "description": f"역 V자 패턴: {first_half_change:.1f}% 상승 후 {second_half_change:.1f}% 하락",
                    "source": "rule_based",
                }

        # Double bottom/top detection
        if len(lows) >= 20:
            pattern = _detect_double_pattern(closes, highs, lows)
            if pattern is not None:
                return pattern

        return _no_pattern()


def _detect_double_pattern(
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> dict | None:
    """Detect double bottom or double top patterns.

    Args:
        closes: Close prices.
        highs: High prices.
        lows: Low prices.

    Returns:
        Pattern dict or None.
    """
    n = len(lows)
    half = n // 2

    # Find lowest points in each half
    first_low = min(lows[:half])
    second_low = min(lows[half:])

    # Double bottom: two similar lows with price currently above both
    if first_low > 0:
        low_diff_pct = abs(first_low - second_low) / first_low * 100
        if low_diff_pct < 2.0 and closes[-1] > max(first_low, second_low) * 1.01:
            return {
                "pattern": "double_bottom",
                "confidence": max(0.3, 0.6 - low_diff_pct / 5),
                "direction": "bullish",
                "description": f"이중 바닥 패턴 감지: 저점 {first_low:,.0f} / {second_low:,.0f} (차이 {low_diff_pct:.1f}%)",
                "source": "rule_based",
            }

    # Find highest points in each half
    first_high = max(highs[:half])
    second_high = max(highs[half:])

    # Double top: two similar highs with price currently below both
    if first_high > 0:
        high_diff_pct = abs(first_high - second_high) / first_high * 100
        if high_diff_pct < 2.0 and closes[-1] < min(first_high, second_high) * 0.99:
            return {
                "pattern": "double_top",
                "confidence": max(0.3, 0.6 - high_diff_pct / 5),
                "direction": "bearish",
                "description": f"이중 천정 패턴 감지: 고점 {first_high:,.0f} / {second_high:,.0f} (차이 {high_diff_pct:.1f}%)",
                "source": "rule_based",
            }

    return None


def _no_pattern() -> dict:
    """Return empty pattern result."""
    return {
        "pattern": "none",
        "confidence": 0.0,
        "direction": "neutral",
        "description": "명확한 차트 패턴이 감지되지 않음",
        "source": "rule_based",
    }


def pattern_agent_node(state: TradingState) -> dict:
    """LangGraph node function for pattern agent.

    Only runs when trigger conditions are met to save LLM costs.

    Args:
        state: Current trading state.

    Returns:
        State updates with pattern analysis.
    """
    # Check if pattern analysis should run this cycle
    if not should_analyze_pattern(state):
        return {
            "pattern_analysis": _no_pattern(),
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    agent = PatternAgent()

    try:
        result = agent.analyze(state)

        return {
            "pattern_analysis": result or _no_pattern(),
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Pattern agent failed: {e}")
        return {
            "pattern_analysis": _no_pattern(),
            "error": f"Pattern agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
