"""Regression channel and support/resistance analysis.

Provides trend channel fitting using linear regression, support/resistance
level detection, and breakout risk assessment. All computations are pure
math — no LLM calls required.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from trading.core.models import OHLCV

logger = logging.getLogger(__name__)


@dataclass
class TrendChannelResult:
    """Result of trend channel analysis."""

    slope: float  # Channel slope (positive = uptrend)
    slope_angle_deg: float  # Slope angle in degrees
    channel_width_pct: float  # Channel width as % of price
    position_in_channel: float  # 0.0 = lower band, 1.0 = upper band
    breakout_risk: str  # "high", "medium", "low"
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    r_squared: float = 0.0  # Goodness of fit (0-1)
    upper_band: float = 0.0  # Current upper channel boundary
    lower_band: float = 0.0  # Current lower channel boundary
    midline: float = 0.0  # Current regression line value


def calculate_trend_channel(
    ohlcv: list[OHLCV],
    lookback: int = 50,
) -> TrendChannelResult | None:
    """Calculate linear regression trend channel.

    Args:
        ohlcv: List of OHLCV candles (oldest first).
        lookback: Number of candles to use for regression.

    Returns:
        TrendChannelResult or None if insufficient data.
    """
    if len(ohlcv) < max(20, lookback // 2):
        return None

    candles = ohlcv[-lookback:]
    closes = np.array([c.close for c in candles], dtype=np.float64)
    highs = np.array([c.high for c in candles], dtype=np.float64)
    lows = np.array([c.low for c in candles], dtype=np.float64)
    n = len(closes)
    x = np.arange(n, dtype=np.float64)

    # Linear regression on close prices
    slope, intercept = np.polyfit(x, closes, 1)
    regression_line = slope * x + intercept

    # Calculate residuals for channel width
    residuals = closes - regression_line
    std_dev = np.std(residuals)

    # Upper/lower bands at 2 standard deviations
    upper_band = regression_line + 2 * std_dev
    lower_band = regression_line - 2 * std_dev

    # R-squared
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((closes - np.mean(closes)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Current values (last point)
    current_midline = regression_line[-1]
    current_upper = upper_band[-1]
    current_lower = lower_band[-1]
    current_price = closes[-1]

    # Channel width as % of midline
    channel_width_pct = (
        (current_upper - current_lower) / current_midline * 100
        if current_midline > 0
        else 0.0
    )

    # Position in channel (0 = lower, 1 = upper)
    channel_range = current_upper - current_lower
    if channel_range > 0:
        position = (current_price - current_lower) / channel_range
        position = max(0.0, min(1.0, position))
    else:
        position = 0.5

    # Slope angle in degrees (normalized by price level)
    slope_pct_per_bar = slope / current_midline * 100 if current_midline > 0 else 0.0
    slope_angle = np.degrees(np.arctan(slope_pct_per_bar))

    # Breakout risk assessment
    breakout_risk = _assess_breakout_risk(position, channel_width_pct, r_squared)

    # Support and resistance levels
    support_levels = _find_support_levels(lows, lookback=min(30, n))
    resistance_levels = _find_resistance_levels(highs, lookback=min(30, n))

    return TrendChannelResult(
        slope=slope,
        slope_angle_deg=slope_angle,
        channel_width_pct=channel_width_pct,
        position_in_channel=position,
        breakout_risk=breakout_risk,
        support_levels=support_levels[:3],  # Top 3
        resistance_levels=resistance_levels[:3],
        r_squared=r_squared,
        upper_band=current_upper,
        lower_band=current_lower,
        midline=current_midline,
    )


def _assess_breakout_risk(
    position: float,
    channel_width_pct: float,
    r_squared: float,
) -> str:
    """Assess risk of channel breakout.

    Args:
        position: Current position in channel (0-1).
        channel_width_pct: Channel width as % of price.
        r_squared: Regression goodness of fit.

    Returns:
        "high", "medium", or "low".
    """
    # Tight channel + price near edge = high breakout risk
    near_edge = position > 0.9 or position < 0.1
    tight_channel = channel_width_pct < 3.0
    weak_trend = r_squared < 0.3

    if near_edge and (tight_channel or weak_trend):
        return "high"
    if near_edge or tight_channel:
        return "medium"
    return "low"


def _find_support_levels(
    lows: np.ndarray,
    lookback: int = 30,
) -> list[float]:
    """Find recent support levels from local minima.

    Args:
        lows: Array of low prices.
        lookback: Number of bars to search.

    Returns:
        List of support prices sorted by recency.
    """
    data = lows[-lookback:]
    if len(data) < 5:
        return []

    supports = []
    for i in range(2, len(data) - 2):
        if data[i] <= data[i - 1] and data[i] <= data[i - 2] and \
           data[i] <= data[i + 1] and data[i] <= data[i + 2]:
            supports.append(float(data[i]))

    # Return unique levels sorted by recency (last found first)
    return list(dict.fromkeys(reversed(supports)))


def _find_resistance_levels(
    highs: np.ndarray,
    lookback: int = 30,
) -> list[float]:
    """Find recent resistance levels from local maxima.

    Args:
        highs: Array of high prices.
        lookback: Number of bars to search.

    Returns:
        List of resistance prices sorted by recency.
    """
    data = highs[-lookback:]
    if len(data) < 5:
        return []

    resistances = []
    for i in range(2, len(data) - 2):
        if data[i] >= data[i - 1] and data[i] >= data[i - 2] and \
           data[i] >= data[i + 1] and data[i] >= data[i + 2]:
            resistances.append(float(data[i]))

    return list(dict.fromkeys(reversed(resistances)))
