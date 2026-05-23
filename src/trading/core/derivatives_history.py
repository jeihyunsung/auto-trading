"""Derivatives history recording for dashboard charts.

Records Binance Futures derivatives data (OI, L/S ratio, funding rate) to JSONL
files for time-series visualization in the dashboard.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trading.core.time import KST

logger = logging.getLogger(__name__)


@dataclass
class DerivativesSnapshot:
    """Point-in-time derivatives data values."""

    timestamp: datetime
    cycle_count: int

    # Open Interest
    open_interest: float  # Total OI in contracts
    open_interest_value: float  # OI value in USDT
    oi_change_pct_1h: float  # OI change % (1 hour)
    oi_change_pct_24h: float  # OI change % (24 hours)

    # Long/Short Ratio
    long_short_ratio: float  # Global long/short ratio
    top_trader_long_short_ratio: float  # Top trader L/S ratio

    # Funding Rate
    funding_rate: float  # Current funding rate (8h)

    # Derived signals
    oi_trend: str  # increasing, decreasing, stable
    position_bias: str  # long_heavy, short_heavy, balanced
    funding_signal: str  # overheated_long, overheated_short, neutral

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "cycle_count": self.cycle_count,
            "open_interest": self.open_interest,
            "open_interest_value": self.open_interest_value,
            "oi_change_pct_1h": self.oi_change_pct_1h,
            "oi_change_pct_24h": self.oi_change_pct_24h,
            "long_short_ratio": self.long_short_ratio,
            "top_trader_long_short_ratio": self.top_trader_long_short_ratio,
            "funding_rate": self.funding_rate,
            "oi_trend": self.oi_trend,
            "position_bias": self.position_bias,
            "funding_signal": self.funding_signal,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DerivativesSnapshot":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            cycle_count=data.get("cycle_count", 0),
            open_interest=data.get("open_interest", 0),
            open_interest_value=data.get("open_interest_value", 0),
            oi_change_pct_1h=data.get("oi_change_pct_1h", 0),
            oi_change_pct_24h=data.get("oi_change_pct_24h", 0),
            long_short_ratio=data.get("long_short_ratio", 1.0),
            top_trader_long_short_ratio=data.get("top_trader_long_short_ratio", 1.0),
            funding_rate=data.get("funding_rate", 0),
            oi_trend=data.get("oi_trend", "stable"),
            position_bias=data.get("position_bias", "balanced"),
            funding_signal=data.get("funding_signal", "neutral"),
        )


class DerivativesHistoryWriter:
    """Append-only writer for derivatives history.

    Writes derivatives snapshots to daily JSONL files (derivatives_YYYYMMDD.jsonl).
    """

    def __init__(self, log_dir: Path):
        """Initialize writer.

        Args:
            log_dir: Directory to store derivatives files.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, dt: datetime) -> Path:
        """Get file path for given datetime."""
        return self.log_dir / f"derivatives_{dt.strftime('%Y%m%d')}.jsonl"

    def record(self, snapshot: DerivativesSnapshot) -> None:
        """Append derivatives snapshot to daily file.

        Args:
            snapshot: Derivatives snapshot to write.
        """
        path = self._get_file_path(snapshot.timestamp)
        try:
            with open(path, "a") as f:
                f.write(json.dumps(snapshot.to_dict()) + "\n")
            logger.debug(
                f"Derivatives snapshot recorded: OI={snapshot.open_interest:,.0f}, "
                f"L/S={snapshot.long_short_ratio:.2f}"
            )
        except Exception as e:
            logger.error(f"Failed to write derivatives snapshot: {e}")

    def record_from_state(self, derivatives_data: dict, cycle_count: int) -> None:
        """Record derivatives from state dict.

        Args:
            derivatives_data: Derivatives data from TradingState.
            cycle_count: Current trading cycle number.
        """
        if not derivatives_data:
            return

        snapshot = DerivativesSnapshot(
            timestamp=datetime.now(KST),
            cycle_count=cycle_count,
            open_interest=derivatives_data.get("open_interest", 0),
            open_interest_value=derivatives_data.get("open_interest_value", 0),
            oi_change_pct_1h=derivatives_data.get("oi_change_pct_1h", 0),
            oi_change_pct_24h=derivatives_data.get("oi_change_pct_24h", 0),
            long_short_ratio=derivatives_data.get("long_short_ratio", 1.0),
            top_trader_long_short_ratio=derivatives_data.get("top_trader_long_short_ratio", 1.0),
            funding_rate=derivatives_data.get("funding_rate", 0),
            oi_trend=derivatives_data.get("oi_trend", "stable"),
            position_bias=derivatives_data.get("position_bias", "balanced"),
            funding_signal=derivatives_data.get("funding_signal", "neutral"),
        )
        self.record(snapshot)


# Module-level singleton
_writer: DerivativesHistoryWriter | None = None


def get_derivatives_writer() -> DerivativesHistoryWriter | None:
    """Get global derivatives history writer.

    Returns:
        DerivativesHistoryWriter if initialized, None otherwise.
    """
    return _writer


def set_derivatives_writer(writer: DerivativesHistoryWriter | None) -> None:
    """Set global derivatives history writer.

    Args:
        writer: Writer instance or None to disable.
    """
    global _writer
    _writer = writer
