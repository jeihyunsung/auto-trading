"""Technical indicator calculation agent."""

import logging
from datetime import datetime

from trading.config import get_settings
from trading.core.time import KST
from trading.core.indicator_history import IndicatorSnapshot, get_indicator_writer
from trading.core.models import OHLCV
from trading.core.state import IndicatorSignals, TrendChannelData, TradingState
from trading.indicators.momentum import (
    calculate_obv,
    calculate_obv_change_pct,
    calculate_rsi,
    get_momentum_signal,
)
from trading.indicators.trend import calculate_macd, get_trend_signal
from trading.indicators.trend_channel import calculate_trend_channel
from trading.indicators.volatility import calculate_bollinger_bands, get_volatility_level

logger = logging.getLogger(__name__)


class IndicatorAgent:
    """Agent for calculating technical indicators."""

    def calculate(self, ohlcv_data: list[dict]) -> IndicatorSignals:
        """Calculate indicators from OHLCV data.

        Args:
            ohlcv_data: List of OHLCV dicts from market data.

        Returns:
            IndicatorSignals with calculated values.
        """
        if not ohlcv_data:
            return self._empty_signals()

        # Convert dict to OHLCV objects
        ohlcv = [
            OHLCV(
                timestamp=datetime.fromisoformat(c["timestamp"]) if isinstance(c["timestamp"], str) else c["timestamp"],
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=c["volume"],
            )
            for c in ohlcv_data
        ]

        logger.info(f"Calculating indicators from {len(ohlcv)} candles")

        # Calculate signals
        settings = get_settings()
        trend = get_trend_signal(ohlcv, mode=settings.trend_mode)
        momentum = get_momentum_signal(ohlcv)
        volatility = get_volatility_level(ohlcv)

        # Calculate specific indicator values
        rsi_values = calculate_rsi(ohlcv)
        macd_data = calculate_macd(ohlcv)

        current_rsi = rsi_values[-1] if rsi_values and rsi_values[-1] is not None else 50.0
        current_macd_hist = macd_data["histogram"][-1] if macd_data["histogram"] and macd_data["histogram"][-1] is not None else 0.0

        # Calculate Bollinger Bands
        bb_data = calculate_bollinger_bands(ohlcv)
        bb_upper = bb_data["upper"][-1] if bb_data["upper"] and bb_data["upper"][-1] is not None else 0.0
        bb_middle = bb_data["middle"][-1] if bb_data["middle"] and bb_data["middle"][-1] is not None else 0.0
        bb_lower = bb_data["lower"][-1] if bb_data["lower"] and bb_data["lower"][-1] is not None else 0.0
        bb_width = ((bb_upper - bb_lower) / bb_middle * 100) if bb_middle > 0 else 0.0

        # Calculate OBV
        obv_values = calculate_obv(ohlcv)
        current_obv = obv_values[-1] if obv_values and obv_values[-1] is not None else 0.0
        obv_change_pct = calculate_obv_change_pct(ohlcv)

        return IndicatorSignals(
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            signals={
                "rsi": current_rsi,
                "macd_histogram": current_macd_hist,
                "macd_line": macd_data["macd"][-1] if macd_data["macd"] and macd_data["macd"][-1] is not None else 0.0,
                "macd_signal": macd_data["signal"][-1] if macd_data["signal"] and macd_data["signal"][-1] is not None else 0.0,
                "bb_upper": bb_upper,
                "bb_middle": bb_middle,
                "bb_lower": bb_lower,
                "bb_width": bb_width,
                "obv": current_obv,
                "obv_change_pct": obv_change_pct,
            },
        )

    def _empty_signals(self) -> IndicatorSignals:
        """Return empty/neutral signals when no data available."""
        return IndicatorSignals(
            trend="neutral",
            momentum="neutral",
            volatility="medium",
            signals={
                "rsi": 50.0,
                "macd_histogram": 0.0,
                "macd_line": 0.0,
                "macd_signal": 0.0,
                "bb_upper": 0.0,
                "bb_middle": 0.0,
                "bb_lower": 0.0,
                "bb_width": 0.0,
                "obv": 0.0,
                "obv_change_pct": 0.0,
            },
        )


def indicator_agent_node(state: TradingState) -> dict:
    """LangGraph node function for indicator agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with indicator signals.
    """
    agent = IndicatorAgent()

    try:
        # Get OHLCV from market data
        market = state.get("market")
        if not market:
            logger.warning("No market data available for indicator calculation")
            return {
                "indicators": agent._empty_signals(),
                "error": "No market data for indicators",
                "last_updated": datetime.now(KST).isoformat(),
            }

        ohlcv_data = market.get("ohlcv", [])
        indicators = agent.calculate(ohlcv_data)

        # Calculate trend channel (no LLM cost)
        trend_channel_data: TrendChannelData | None = None
        try:
            ohlcv_objects = [
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
            channel = calculate_trend_channel(ohlcv_objects)
            if channel:
                trend_channel_data = TrendChannelData(
                    slope=channel.slope,
                    slope_angle_deg=channel.slope_angle_deg,
                    channel_width_pct=channel.channel_width_pct,
                    position_in_channel=channel.position_in_channel,
                    breakout_risk=channel.breakout_risk,
                    support_levels=channel.support_levels,
                    resistance_levels=channel.resistance_levels,
                    r_squared=channel.r_squared,
                    upper_band=channel.upper_band,
                    lower_band=channel.lower_band,
                    midline=channel.midline,
                )
                logger.info(
                    f"Trend channel: slope={channel.slope_angle_deg:.1f}°, "
                    f"position={channel.position_in_channel:.0%}, "
                    f"breakout_risk={channel.breakout_risk}"
                )
        except Exception as e:
            logger.warning(f"Trend channel calculation failed: {e}")

        # Record indicator snapshot for dashboard
        writer = get_indicator_writer()
        if writer:
            signals = indicators.get("signals", {})
            writer.record(IndicatorSnapshot(
                timestamp=datetime.now(KST),
                btc_price=market.get("current_price", 0),
                rsi=signals.get("rsi", 50.0),
                macd_line=signals.get("macd_line", 0.0),
                macd_signal=signals.get("macd_signal", 0.0),
                macd_histogram=signals.get("macd_histogram", 0.0),
                trend=indicators.get("trend", "neutral"),
                momentum=indicators.get("momentum", "neutral"),
                volatility=indicators.get("volatility", "medium"),
                cycle_count=state.get("cycle_count", 0),
                bb_upper=signals.get("bb_upper", 0.0),
                bb_middle=signals.get("bb_middle", 0.0),
                bb_lower=signals.get("bb_lower", 0.0),
                bb_width=signals.get("bb_width", 0.0),
                obv=signals.get("obv", 0.0),
                obv_change_pct=signals.get("obv_change_pct", 0.0),
            ))

        return {
            "indicators": indicators,
            "trend_channel": trend_channel_data,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Indicator agent failed: {e}")
        return {
            "indicators": agent._empty_signals(),
            "trend_channel": None,
            "error": f"Indicator agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
