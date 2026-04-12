"""Read historical data for dashboard.

Reads decision history, indicator history, and portfolio snapshots
from JSONL files for dashboard visualization.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading.core.decision_history import DecisionRecord
from trading.core.derivatives_history import DerivativesSnapshot
from trading.core.indicator_history import IndicatorSnapshot

logger = logging.getLogger(__name__)

# Korea Standard Time (UTC+9)
KST = timezone(timedelta(hours=9))


def normalize_timestamp(dt: datetime) -> datetime:
    """Normalize timestamp to aware datetime for comparison.

    Args:
        dt: datetime object (naive or aware).

    Returns:
        Aware datetime in KST.
    """
    if dt.tzinfo is None:
        # Naive datetime assumed to be UTC, convert to KST
        return dt.replace(tzinfo=timezone.utc).astimezone(KST)
    return dt.astimezone(KST)


class HistoryReader:
    """Read historical decisions, indicators, and portfolio snapshots."""

    def __init__(self, log_dir: Path | str | None = None):
        """Initialize reader.

        Args:
            log_dir: Directory containing log files.
        """
        self.log_dir = Path(log_dir) if log_dir else Path("logs")

    def get_decisions(self, days: int = 7) -> list[DecisionRecord]:
        """Load decisions from multiple daily files.

        Args:
            days: Number of days to look back.

        Returns:
            List of DecisionRecord sorted by timestamp (newest first).
        """
        records: list[DecisionRecord] = []
        today = datetime.now(KST).date()  # Use KST for file naming

        for i in range(days):
            date = today - timedelta(days=i)
            path = self.log_dir / f"decisions_{date.strftime('%Y%m%d')}.jsonl"
            if path.exists():
                try:
                    with open(path) as f:
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                records.append(DecisionRecord.from_dict(data))
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")

        return sorted(records, key=lambda r: normalize_timestamp(r.timestamp), reverse=True)

    def get_indicators(self, days: int = 7) -> list[IndicatorSnapshot]:
        """Load indicators from multiple daily files.

        Args:
            days: Number of days to look back.

        Returns:
            List of IndicatorSnapshot sorted by timestamp (oldest first for charts).
        """
        snapshots: list[IndicatorSnapshot] = []
        today = datetime.now(KST).date()  # Use KST for file naming

        for i in range(days):
            date = today - timedelta(days=i)
            path = self.log_dir / f"indicators_{date.strftime('%Y%m%d')}.jsonl"
            if path.exists():
                try:
                    with open(path) as f:
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                snapshots.append(IndicatorSnapshot.from_dict(data))
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")

        return sorted(snapshots, key=lambda s: normalize_timestamp(s.timestamp))

    def get_portfolio_snapshots(self, hours: int = 24) -> list[dict]:
        """Load recent portfolio snapshots.

        Args:
            hours: Number of hours to look back.

        Returns:
            List of portfolio snapshot dicts sorted by timestamp.
        """
        path = self.log_dir / "portfolio_snapshots.jsonl"
        if not path.exists():
            return []

        cutoff = datetime.now(KST) - timedelta(hours=hours)
        snapshots: list[dict] = []

        try:
            with open(path) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        ts = datetime.fromisoformat(data["timestamp"])
                        ts_normalized = normalize_timestamp(ts)
                        if ts_normalized >= cutoff:
                            data["timestamp"] = ts_normalized
                            snapshots.append(data)
        except Exception as e:
            logger.warning(f"Failed to read portfolio snapshots: {e}")

        return sorted(snapshots, key=lambda s: s["timestamp"])

    def get_trades(self, days: int = 7) -> list[dict]:
        """Load trade records from daily trade files.

        Args:
            days: Number of days to look back.

        Returns:
            List of trade dicts sorted by timestamp (newest first).
        """
        trades: list[dict] = []
        today = datetime.now(KST).date()  # Use KST for file naming

        for i in range(days):
            date = today - timedelta(days=i)
            path = self.log_dir / f"trades_{date.strftime('%Y%m%d')}.jsonl"
            if path.exists():
                try:
                    with open(path) as f:
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                trades.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")

        return sorted(trades, key=lambda t: t.get("timestamp", ""), reverse=True)

    def get_latest_portfolio(self) -> dict | None:
        """Get the most recent portfolio snapshot.

        Returns:
            Latest portfolio snapshot dict or None.
        """
        snapshots = self.get_portfolio_snapshots(hours=24)
        return snapshots[-1] if snapshots else None

    def get_isolated_balance(self) -> dict | None:
        """Read isolated balance state.

        Returns:
            Isolated balance dict or None.
        """
        path = self.log_dir / "isolated_balance.json"
        if not path.exists():
            return None

        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read isolated balance: {e}")
            return None

    def get_derivatives(self, days: int = 7) -> list[DerivativesSnapshot]:
        """Load derivatives data from multiple daily files.

        Args:
            days: Number of days to look back.

        Returns:
            List of DerivativesSnapshot sorted by timestamp (oldest first for charts).
        """
        snapshots: list[DerivativesSnapshot] = []
        today = datetime.now(KST).date()  # Use KST for file naming

        for i in range(days):
            date = today - timedelta(days=i)
            path = self.log_dir / f"derivatives_{date.strftime('%Y%m%d')}.jsonl"
            if path.exists():
                try:
                    with open(path) as f:
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                snapshots.append(DerivativesSnapshot.from_dict(data))
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")

        return sorted(snapshots, key=lambda s: normalize_timestamp(s.timestamp))

    def get_latest_derivatives(self) -> DerivativesSnapshot | None:
        """Get the most recent derivatives snapshot.

        Returns:
            Latest DerivativesSnapshot or None.
        """
        snapshots = self.get_derivatives(days=1)
        return snapshots[-1] if snapshots else None
