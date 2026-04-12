"""Volatility indicators: ATR, Bollinger Bands."""

import pandas as pd
import pandas_ta as ta

from trading.core.models import OHLCV
from trading.indicators.trend import _ohlcv_to_dataframe


def calculate_atr(ohlcv: list[OHLCV], period: int = 14) -> list[float | None]:
    """Calculate Average True Range.

    Args:
        ohlcv: List of OHLCV candles.
        period: ATR period (default 14).

    Returns:
        List of ATR values (None for insufficient data).
    """
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)

    df = _ohlcv_to_dataframe(ohlcv)
    atr = ta.atr(df["high"], df["low"], df["close"], length=period)

    return [None if pd.isna(v) else float(v) for v in atr]


def calculate_bollinger_bands(
    ohlcv: list[OHLCV],
    period: int = 20,
    std_dev: float = 2.0,
) -> dict[str, list[float | None]]:
    """Calculate Bollinger Bands.

    Args:
        ohlcv: List of OHLCV candles.
        period: Moving average period (default 20).
        std_dev: Standard deviation multiplier (default 2.0).

    Returns:
        Dictionary with 'upper', 'middle', 'lower', and 'width' lists.
    """
    if len(ohlcv) < period:
        empty = [None] * len(ohlcv)
        return {"upper": empty, "middle": empty, "lower": empty, "width": empty}

    df = _ohlcv_to_dataframe(ohlcv)
    bbands = ta.bbands(df["close"], length=period, std=std_dev)

    if bbands is None or bbands.empty:
        empty = [None] * len(ohlcv)
        return {"upper": empty, "middle": empty, "lower": empty, "width": empty}

    # Find column names dynamically (pandas_ta version compatibility)
    cols = bbands.columns.tolist()
    upper_col = next((c for c in cols if c.startswith("BBU_")), None)
    middle_col = next((c for c in cols if c.startswith("BBM_")), None)
    lower_col = next((c for c in cols if c.startswith("BBL_")), None)
    width_col = next((c for c in cols if c.startswith("BBB_")), None)

    if not all([upper_col, middle_col, lower_col]):
        empty = [None] * len(ohlcv)
        return {"upper": empty, "middle": empty, "lower": empty, "width": empty}

    result = {
        "upper": [None if pd.isna(v) else float(v) for v in bbands[upper_col]],
        "middle": [None if pd.isna(v) else float(v) for v in bbands[middle_col]],
        "lower": [None if pd.isna(v) else float(v) for v in bbands[lower_col]],
        "width": [None] * len(ohlcv),  # default
    }

    if width_col:
        result["width"] = [None if pd.isna(v) else float(v) for v in bbands[width_col]]

    return result


def get_volatility_level(ohlcv: list[OHLCV]) -> str:
    """Get volatility level based on ATR and BB width.

    Args:
        ohlcv: List of OHLCV candles.

    Returns:
        Volatility level: 'low', 'medium', or 'high'.
    """
    if len(ohlcv) < 30:
        return "medium"

    current_price = ohlcv[-1].close
    if current_price == 0:
        return "medium"

    # Calculate ATR percentage
    atr = calculate_atr(ohlcv)
    current_atr = atr[-1]

    if current_atr is None:
        return "medium"

    atr_pct = (current_atr / current_price) * 100

    # Calculate BB width percentage
    bbands = calculate_bollinger_bands(ohlcv)
    bb_width = bbands["width"][-1]

    # Determine volatility level
    # ATR > 3% or BB width > 10% = high volatility
    # ATR > 1.5% or BB width > 5% = medium volatility
    # Otherwise = low volatility

    if atr_pct >= 3.0 or (bb_width is not None and bb_width >= 10.0):
        return "high"
    elif atr_pct >= 1.5 or (bb_width is not None and bb_width >= 5.0):
        return "medium"
    return "low"


def get_bb_position(ohlcv: list[OHLCV]) -> str | None:
    """Get price position relative to Bollinger Bands.

    Args:
        ohlcv: List of OHLCV candles.

    Returns:
        Position: 'above_upper', 'above_middle', 'below_middle', 'below_lower', or None.
    """
    if len(ohlcv) < 20:
        return None

    current_price = ohlcv[-1].close
    bbands = calculate_bollinger_bands(ohlcv)

    upper = bbands["upper"][-1]
    middle = bbands["middle"][-1]
    lower = bbands["lower"][-1]

    if upper is None or middle is None or lower is None:
        return None

    if current_price >= upper:
        return "above_upper"
    elif current_price >= middle:
        return "above_middle"
    elif current_price >= lower:
        return "below_middle"
    else:
        return "below_lower"


def calculate_historical_volatility(
    ohlcv: list[OHLCV],
    period: int = 20,
    annualize: bool = True,
) -> float | None:
    """Calculate historical volatility (standard deviation of returns).

    Args:
        ohlcv: List of OHLCV candles.
        period: Lookback period (default 20).
        annualize: Whether to annualize the result (default True).

    Returns:
        Historical volatility as percentage, or None if insufficient data.
    """
    if len(ohlcv) < period + 1:
        return None

    # Calculate log returns
    closes = [c.close for c in ohlcv[-(period + 1):]]
    returns = []

    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

    if len(returns) < period:
        return None

    # Calculate standard deviation
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = variance ** 0.5

    # Annualize if requested (assuming daily candles, 365 trading days for crypto)
    if annualize:
        std_dev *= (365 ** 0.5)

    return std_dev * 100  # Return as percentage
