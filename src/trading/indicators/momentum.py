"""Momentum indicators: RSI, Stochastic, OBV."""

import pandas as pd
import pandas_ta as ta

from trading.core.models import OHLCV
from trading.indicators.trend import _ohlcv_to_dataframe


def calculate_obv(ohlcv: list[OHLCV]) -> list[float | None]:
    """Calculate On-Balance Volume.

    OBV accumulates volume based on price direction:
    - Close > Previous Close → +volume
    - Close < Previous Close → -volume
    - Close = Previous Close → 0

    Args:
        ohlcv: List of OHLCV candles.

    Returns:
        List of OBV values (None for insufficient data).
    """
    if len(ohlcv) < 2:
        return [None] * len(ohlcv)

    df = _ohlcv_to_dataframe(ohlcv)
    obv = ta.obv(df["close"], df["volume"])

    return [None if pd.isna(v) else float(v) for v in obv]


def calculate_obv_change_pct(ohlcv: list[OHLCV], period: int = 5) -> float:
    """Calculate OBV percentage change over period.

    Args:
        ohlcv: List of OHLCV candles.
        period: Number of periods to calculate change.

    Returns:
        OBV change percentage, or 0.0 if insufficient data.
    """
    obv_values = calculate_obv(ohlcv)

    if len(obv_values) < period + 1:
        return 0.0

    current_obv = obv_values[-1]
    past_obv = obv_values[-period - 1]

    if current_obv is None or past_obv is None or past_obv == 0:
        return 0.0

    return ((current_obv - past_obv) / abs(past_obv)) * 100


def calculate_rsi(ohlcv: list[OHLCV], period: int = 14) -> list[float | None]:
    """Calculate Relative Strength Index.

    Args:
        ohlcv: List of OHLCV candles.
        period: RSI period (default 14, standard).

    Returns:
        List of RSI values (0-100, None for insufficient data).
    """
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)

    df = _ohlcv_to_dataframe(ohlcv)
    rsi = ta.rsi(df["close"], length=period)

    return [None if pd.isna(v) else float(v) for v in rsi]


def calculate_stochastic(
    ohlcv: list[OHLCV],
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> dict[str, list[float | None]]:
    """Calculate Stochastic Oscillator.

    Args:
        ohlcv: List of OHLCV candles.
        k_period: %K period (default 14).
        d_period: %D period (default 3).
        smooth_k: %K smoothing (default 3).

    Returns:
        Dictionary with 'k' and 'd' lists.
    """
    min_periods = k_period + d_period
    if len(ohlcv) < min_periods:
        empty = [None] * len(ohlcv)
        return {"k": empty, "d": empty}

    df = _ohlcv_to_dataframe(ohlcv)
    stoch = ta.stoch(df["high"], df["low"], df["close"], k=k_period, d=d_period, smooth_k=smooth_k)

    if stoch is None or stoch.empty:
        empty = [None] * len(ohlcv)
        return {"k": empty, "d": empty}

    # Column names from pandas_ta
    k_col = f"STOCHk_{k_period}_{d_period}_{smooth_k}"
    d_col = f"STOCHd_{k_period}_{d_period}_{smooth_k}"

    return {
        "k": [None if pd.isna(v) else float(v) for v in stoch[k_col]],
        "d": [None if pd.isna(v) else float(v) for v in stoch[d_col]],
    }


def get_momentum_signal(ohlcv: list[OHLCV]) -> str:
    """Get momentum signal based on RSI and Stochastic.

    Args:
        ohlcv: List of OHLCV candles.

    Returns:
        Momentum signal: 'overbought', 'oversold', or 'neutral'.
    """
    if len(ohlcv) < 20:
        return "neutral"

    rsi = calculate_rsi(ohlcv)
    stoch = calculate_stochastic(ohlcv)

    current_rsi = rsi[-1]
    current_stoch_k = stoch["k"][-1]

    overbought_signals = 0
    oversold_signals = 0

    # RSI overbought/oversold
    if current_rsi is not None:
        if current_rsi >= 70:
            overbought_signals += 1
        elif current_rsi <= 30:
            oversold_signals += 1

    # Stochastic overbought/oversold
    if current_stoch_k is not None:
        if current_stoch_k >= 80:
            overbought_signals += 1
        elif current_stoch_k <= 20:
            oversold_signals += 1

    # Determine overall momentum
    if overbought_signals >= 1:
        return "overbought"
    elif oversold_signals >= 1:
        return "oversold"
    return "neutral"


def get_rsi_divergence(ohlcv: list[OHLCV], lookback: int = 10) -> str | None:
    """Detect RSI divergence.

    Args:
        ohlcv: List of OHLCV candles.
        lookback: Number of candles to look back for divergence.

    Returns:
        'bullish_divergence', 'bearish_divergence', or None.
    """
    if len(ohlcv) < lookback + 14:
        return None

    rsi = calculate_rsi(ohlcv)
    recent_rsi = rsi[-lookback:]
    recent_prices = [c.close for c in ohlcv[-lookback:]]

    # Check if we have valid data
    if any(r is None for r in recent_rsi):
        return None

    # Find local minima/maxima
    price_making_lower_low = min(recent_prices[-3:]) < min(recent_prices[:3])
    price_making_higher_high = max(recent_prices[-3:]) > max(recent_prices[:3])
    rsi_making_higher_low = min(recent_rsi[-3:]) > min(recent_rsi[:3])
    rsi_making_lower_high = max(recent_rsi[-3:]) < max(recent_rsi[:3])

    # Bullish divergence: price lower low, RSI higher low
    if price_making_lower_low and rsi_making_higher_low:
        return "bullish_divergence"

    # Bearish divergence: price higher high, RSI lower high
    if price_making_higher_high and rsi_making_lower_high:
        return "bearish_divergence"

    return None
