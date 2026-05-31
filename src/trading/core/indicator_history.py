"""Indicator history recording for dashboard charts.

Records indicator snapshots (RSI, MACD, etc.) to JSONL files for
time-series visualization in the dashboard.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class IndicatorSnapshot:
    """Point-in-time indicator values. Asset-agnostic with BTC backward compat."""

    timestamp: datetime
    asset_price: float
    rsi: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    trend: str  # bullish, bearish, neutral
    momentum: str  # overbought, oversold, neutral
    volatility: str  # low, medium, high
    cycle_count: int
    asset_symbol: str = "BTC"

    # Bollinger Bands (default 0.0 for backward compatibility)
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0  # (upper - lower) / middle * 100

    # On-Balance Volume (default 0.0 for backward compatibility)
    obv: float = 0.0
    obv_change_pct: float = 0.0  # OBV change % over recent periods

    @property
    def btc_price(self) -> float:
        """Legacy alias for asset_price."""
        return self.asset_price

    def to_dict(self) -> dict:
        """Convert to dictionary. Writes both new + legacy keys."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "asset_price": self.asset_price,
            "asset_symbol": self.asset_symbol,
            "btc_price": self.asset_price,  # legacy mirror
            "rsi": self.rsi,
            "macd_line": self.macd_line,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "trend": self.trend,
            "momentum": self.momentum,
            "volatility": self.volatility,
            "cycle_count": self.cycle_count,
            "bb_upper": self.bb_upper,
            "bb_middle": self.bb_middle,
            "bb_lower": self.bb_lower,
            "bb_width": self.bb_width,
            "obv": self.obv,
            "obv_change_pct": self.obv_change_pct,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IndicatorSnapshot":
        """Dual-read: asset_price preferred, falls back to legacy btc_price."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            asset_price=data.get("asset_price", data.get("btc_price", 0.0)),
            asset_symbol=data.get("asset_symbol", "BTC"),
            rsi=data["rsi"],
            macd_line=data["macd_line"],
            macd_signal=data["macd_signal"],
            macd_histogram=data["macd_histogram"],
            trend=data["trend"],
            momentum=data["momentum"],
            volatility=data["volatility"],
            cycle_count=data["cycle_count"],
            # New fields with defaults for backward compatibility
            bb_upper=data.get("bb_upper", 0.0),
            bb_middle=data.get("bb_middle", 0.0),
            bb_lower=data.get("bb_lower", 0.0),
            bb_width=data.get("bb_width", 0.0),
            obv=data.get("obv", 0.0),
            obv_change_pct=data.get("obv_change_pct", 0.0),
        )


class IndicatorHistoryWriter:
    """Append-only writer for indicator history.

    Writes indicator snapshots to daily JSONL files (indicators_YYYYMMDD.jsonl).
    """

    def __init__(self, log_dir: Path):
        """Initialize writer.

        Args:
            log_dir: Directory to store indicator files.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, dt: datetime) -> Path:
        """Get file path for given datetime."""
        return self.log_dir / f"indicators_{dt.strftime('%Y%m%d')}.jsonl"

    def record(self, snapshot: IndicatorSnapshot) -> None:
        """Append indicator snapshot to daily file.

        Args:
            snapshot: Indicator snapshot to write.
        """
        path = self._get_file_path(snapshot.timestamp)
        try:
            with open(path, "a") as f:
                f.write(json.dumps(snapshot.to_dict()) + "\n")
            logger.debug(f"Indicator snapshot recorded: RSI={snapshot.rsi:.1f}")
        except Exception as e:
            logger.error(f"Failed to write indicator snapshot: {e}")


# Module-level singleton
_writer: IndicatorHistoryWriter | None = None


def get_indicator_writer() -> IndicatorHistoryWriter | None:
    """Get global indicator history writer.

    Returns:
        IndicatorHistoryWriter if initialized, None otherwise.
    """
    return _writer


def set_indicator_writer(writer: IndicatorHistoryWriter | None) -> None:
    """Set global indicator history writer.

    Args:
        writer: Writer instance or None to disable.
    """
    global _writer
    _writer = writer
