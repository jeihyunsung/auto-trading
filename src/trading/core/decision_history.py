"""Decision history recording for dashboard.

Records all trading decisions (including HOLD) to JSONL files for
dashboard visualization and historical analysis.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DecisionRecord:
    """Record of a trading decision."""

    timestamp: datetime
    action: str  # BUY, SELL, HOLD
    confidence: float
    rationale: str
    status: str  # pending, approved, rejected, executed
    market_price: float
    was_executed: bool
    original_action: str | None  # If modified by hysteresis
    cycle_count: int

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "status": self.status,
            "market_price": self.market_price,
            "was_executed": self.was_executed,
            "original_action": self.original_action,
            "cycle_count": self.cycle_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionRecord":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            action=data["action"],
            confidence=data["confidence"],
            rationale=data["rationale"],
            status=data["status"],
            market_price=data["market_price"],
            was_executed=data["was_executed"],
            original_action=data.get("original_action"),
            cycle_count=data["cycle_count"],
        )


class DecisionHistoryWriter:
    """Append-only writer for decision history.

    Writes decisions to daily JSONL files (decisions_YYYYMMDD.jsonl).
    Includes deduplication to reduce log noise from repeated similar decisions,
    with periodic recording to ensure dashboard shows recent state.
    """

    def __init__(
        self,
        log_dir: Path,
        skip_duplicate_non_executed: bool = True,
        min_record_interval_minutes: int = 30,
    ):
        """Initialize writer.

        Args:
            log_dir: Directory to store decision files.
            skip_duplicate_non_executed: Skip logging if same action/status as previous
                and not executed. Reduces noise from repeated HOLD or rejected decisions.
            min_record_interval_minutes: Even if duplicate, record at least once per
                this interval to keep dashboard updated. Default 30 minutes.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.skip_duplicate_non_executed = skip_duplicate_non_executed
        self.min_record_interval = timedelta(minutes=min_record_interval_minutes)
        self._last_recorded: DecisionRecord | None = None
        self._last_recorded_time: datetime | None = None
        self._skipped_count: int = 0

    def _get_file_path(self, dt: datetime) -> Path:
        """Get file path for given datetime."""
        return self.log_dir / f"decisions_{dt.strftime('%Y%m%d')}.jsonl"

    def _is_duplicate(self, decision: DecisionRecord) -> bool:
        """Check if decision is a duplicate of the last recorded one.

        A decision is considered duplicate if:
        - Same action as previous (e.g., consecutive HOLDs)
        - Not executed (no actual trade happened)
        - Same status (e.g., both rejected or both pending)
        - Less than min_record_interval since last record

        Executed decisions are never considered duplicates.
        Even duplicates are recorded periodically to keep dashboard updated.

        Args:
            decision: Decision to check.

        Returns:
            True if this is a duplicate that should be skipped.
        """
        if not self.skip_duplicate_non_executed:
            return False

        # Always record executed decisions
        if decision.was_executed:
            return False

        # No previous decision - not a duplicate
        if self._last_recorded is None:
            return False

        # Check time since last record - force record if interval exceeded
        if self._last_recorded_time is not None:
            time_since_last = decision.timestamp - self._last_recorded_time
            if time_since_last >= self.min_record_interval:
                logger.debug(
                    f"Recording periodic update after {time_since_last.total_seconds() / 60:.1f} min"
                )
                return False

        # Different action - not a duplicate
        if decision.action != self._last_recorded.action:
            return False

        # Same action, both not executed - check status
        # Allow logging if status changed (e.g., pending -> rejected)
        if decision.status != self._last_recorded.status:
            return False

        # Same action, same status, both not executed, within interval - duplicate
        return True

    def record(self, decision: DecisionRecord) -> bool:
        """Append decision to daily file.

        Args:
            decision: Decision record to write.

        Returns:
            True if recorded, False if skipped as duplicate.
        """
        # Check for duplicates
        if self._is_duplicate(decision):
            self._skipped_count += 1
            if self._skipped_count % 10 == 0:
                logger.debug(
                    f"Skipped {self._skipped_count} duplicate decisions "
                    f"(last: {decision.action})"
                )
            return False

        path = self._get_file_path(decision.timestamp)
        try:
            with open(path, "a") as f:
                f.write(json.dumps(decision.to_dict()) + "\n")

            # Update last recorded
            self._last_recorded = decision
            self._last_recorded_time = decision.timestamp

            # Log if we were skipping duplicates
            if self._skipped_count > 0:
                logger.debug(
                    f"Decision recorded after {self._skipped_count} skipped: "
                    f"{decision.action} ({decision.confidence:.0%})"
                )
                self._skipped_count = 0
            else:
                logger.debug(f"Decision recorded: {decision.action} ({decision.confidence:.0%})")

            return True

        except Exception as e:
            logger.error(f"Failed to write decision: {e}")
            return False


# Module-level singleton
_writer: DecisionHistoryWriter | None = None


def get_decision_writer() -> DecisionHistoryWriter | None:
    """Get global decision history writer.

    Returns:
        DecisionHistoryWriter if initialized, None otherwise.
    """
    return _writer


def set_decision_writer(writer: DecisionHistoryWriter | None) -> None:
    """Set global decision history writer.

    Args:
        writer: Writer instance or None to disable.
    """
    global _writer
    _writer = writer
