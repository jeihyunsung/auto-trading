"""Trend indicators: SMA, EMA, MACD."""

import pandas as pd
import pandas_ta as ta

from trading.core.models import OHLCV


def calculate_sma(ohlcv: list[OHLCV], period: int = 20) -> list[float | None]:
    """Calculate Simple Moving Average.

    Args:
        ohlcv: List of OHLCV candles.
        period: SMA period (default 20).

    Returns:
        List of SMA values (None for insufficient data).
    """
    if len(ohlcv) < period:
        return [None] * len(ohlcv)

    df = _ohlcv_to_dataframe(ohlcv)
    sma = ta.sma(df["close"], length=period)

    return [None if pd.isna(v) else float(v) for v in sma]


def calculate_ema(ohlcv: list[OHLCV], period: int = 20) -> list[float | None]:
    """Calculate Exponential Moving Average.

    Args:
        ohlcv: List of OHLCV candles.
        period: EMA period (default 20).

    Returns:
        List of EMA values (None for insufficient data).
    """
    if len(ohlcv) < period:
        return [None] * len(ohlcv)

    df = _ohlcv_to_dataframe(ohlcv)
    ema = ta.ema(df["close"], length=period)

    return [None if pd.isna(v) else float(v) for v in ema]


def calculate_macd(
    ohlcv: list[OHLCV],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float | None]]:
    """Calculate MACD (Moving Average Convergence Divergence).

    Args:
        ohlcv: List of OHLCV candles.
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal line period (default 9).

    Returns:
        Dictionary with 'macd', 'signal', and 'histogram' lists.
    """
    min_periods = slow + signal
    if len(ohlcv) < min_periods:
        empty = [None] * len(ohlcv)
        return {"macd": empty, "signal": empty, "histogram": empty}

    df = _ohlcv_to_dataframe(ohlcv)
    macd_df = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)

    if macd_df is None or macd_df.empty:
        empty = [None] * len(ohlcv)
        return {"macd": empty, "signal": empty, "histogram": empty}

    # Column names from pandas_ta
    macd_col = f"MACD_{fast}_{slow}_{signal}"
    signal_col = f"MACDs_{fast}_{slow}_{signal}"
    hist_col = f"MACDh_{fast}_{slow}_{signal}"

    return {
        "macd": [None if pd.isna(v) else float(v) for v in macd_df[macd_col]],
        "signal": [None if pd.isna(v) else float(v) for v in macd_df[signal_col]],
        "histogram": [None if pd.isna(v) else float(v) for v in macd_df[hist_col]],
    }


def get_trend_signal(
    ohlcv: list[OHLCV],
    mode: str = "normal",
) -> str:
    """Get trend signal based on multiple indicators.

    Uses EMA crossovers and MACD to detect trends with noise filtering.
    Supports different modes for various trading styles.

    Args:
        ohlcv: List of OHLCV candles.
        mode: Trend detection mode:
            - "fast": Short-term (EMA 5/10/20), 3/5 threshold, quick reaction
            - "normal": Medium-term (EMA 10/20/50), 4/6 threshold, balanced
            - "slow": Long-term (EMA 20/50/100), 4/6 threshold, stable

    Returns:
        Trend signal: 'bullish', 'bearish', or 'neutral'.
    """
    # Configure based on mode
    if mode == "fast":
        ema_short, ema_mid, ema_long = 5, 10, 20
        min_candles = 26  # MACD needs 26
        threshold = 3  # 3 out of 5
    elif mode == "slow":
        ema_short, ema_mid, ema_long = 20, 50, 100
        min_candles = 100
        threshold = 4  # 4 out of 6
    else:  # normal
        ema_short, ema_mid, ema_long = 10, 20, 50
        min_candles = 50
        threshold = 4  # 4 out of 6

    if len(ohlcv) < min_candles:
        return "neutral"

    current_price = ohlcv[-1].close

    # Calculate EMAs at configured timeframes
    ema_s = calculate_ema(ohlcv, ema_short)
    ema_m = calculate_ema(ohlcv, ema_mid)
    ema_l = calculate_ema(ohlcv, ema_long)

    # Calculate MACD (always 12/26/9 for consistency)
    macd = calculate_macd(ohlcv)

    # Count bullish/bearish signals
    bullish_signals = 0
    bearish_signals = 0

    # 1. Short EMA vs Mid EMA
    if ema_s[-1] is not None and ema_m[-1] is not None:
        if ema_s[-1] > ema_m[-1]:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # 2. Mid EMA vs Long EMA (skip in fast mode for quicker reaction)
    if mode != "fast" and ema_m[-1] is not None and ema_l[-1] is not None:
        if ema_m[-1] > ema_l[-1]:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # 3. Price vs Mid EMA
    if ema_m[-1] is not None:
        if current_price > ema_m[-1]:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # 4. Price vs Long EMA (skip in fast mode)
    if mode != "fast" and ema_l[-1] is not None:
        if current_price > ema_l[-1]:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # 5. MACD histogram
    if macd["histogram"][-1] is not None:
        if macd["histogram"][-1] > 0:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # 6. MACD crossover (skip in fast mode - histogram is enough)
    if mode != "fast" and macd["macd"][-1] is not None and macd["signal"][-1] is not None:
        if macd["macd"][-1] > macd["signal"][-1]:
            bullish_signals += 1
        else:
            bearish_signals += 1

    # Determine trend based on threshold
    # Fast mode: 5 signals, need 3
    # Normal/Slow mode: 6 signals, need 4
    total_signals = bullish_signals + bearish_signals

    if bullish_signals >= threshold and bullish_signals > bearish_signals:
        return "bullish"
    elif bearish_signals >= threshold and bearish_signals > bullish_signals:
        return "bearish"
    return "neutral"


def _ohlcv_to_dataframe(ohlcv: list[OHLCV]) -> pd.DataFrame:
    """Convert OHLCV list to pandas DataFrame.

    Args:
        ohlcv: List of OHLCV candles.

    Returns:
        DataFrame with OHLCV columns.
    """
    return pd.DataFrame(
        {
            "timestamp": [c.timestamp for c in ohlcv],
            "open": [c.open for c in ohlcv],
            "high": [c.high for c in ohlcv],
            "low": [c.low for c in ohlcv],
            "close": [c.close for c in ohlcv],
            "volume": [c.volume for c in ohlcv],
        }
    )
