"""Decision hysteresis to prevent frequent action oscillations.

This module provides hysteresis logic that requires higher confidence
deltas to change trading actions, preventing BUY/SELL/HOLD oscillations
caused by small market fluctuations.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from trading.core.state import Decision, DecisionHistory

logger = logging.getLogger(__name__)


@dataclass
class HysteresisConfig:
    """Configuration for decision hysteresis thresholds.

    Attributes:
        hold_to_action_delta: Confidence delta required for HOLD -> BUY/SELL.
        action_to_hold_delta: Confidence delta required for BUY/SELL -> HOLD.
        action_reversal_delta: Confidence delta required for BUY <-> SELL.
        min_hold_duration: Minimum time before time decay starts.
        decay_factor_per_hour: Threshold reduction rate per hour after min_hold_duration.
        emergency_override_confidence: Confidence level that bypasses all hysteresis.
        post_trade_cooldown: Minimum time after a trade before allowing reversal.
    """

    hold_to_action_delta: float = 0.15
    action_to_hold_delta: float = 0.20
    action_reversal_delta: float = 0.35
    min_hold_duration: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    decay_factor_per_hour: float = 0.1
    emergency_override_confidence: float = 0.90
    post_trade_cooldown: timedelta = field(default_factory=lambda: timedelta(minutes=30))

    @classmethod
    def streaming(cls) -> "HysteresisConfig":
        """Create config optimized for WebSocket streaming mode.

        Lower thresholds for faster response to market events.
        Streaming mode already filters noise via trigger conditions.

        Returns:
            HysteresisConfig for streaming mode.
        """
        return cls(
            hold_to_action_delta=0.10,
            action_to_hold_delta=0.15,
            action_reversal_delta=0.25,
            min_hold_duration=timedelta(minutes=3),
            decay_factor_per_hour=0.15,
            emergency_override_confidence=0.85,
            post_trade_cooldown=timedelta(minutes=15),
        )

    @classmethod
    def backtest_daily(cls) -> "HysteresisConfig":
        """Create config optimized for daily interval backtesting.

        Standard thresholds for noise filtering on longer timeframes.

        Returns:
            HysteresisConfig for daily backtest.
        """
        return cls(
            hold_to_action_delta=0.15,
            action_to_hold_delta=0.20,
            action_reversal_delta=0.35,
            min_hold_duration=timedelta(minutes=5),
            decay_factor_per_hour=0.1,
            emergency_override_confidence=0.90,
            post_trade_cooldown=timedelta(minutes=30),
        )

    @classmethod
    def conservative(cls) -> "HysteresisConfig":
        """Create conservative config for high volatility markets.

        Higher thresholds to prevent frequent position changes.

        Returns:
            HysteresisConfig for conservative mode.
        """
        return cls(
            hold_to_action_delta=0.20,
            action_to_hold_delta=0.25,
            action_reversal_delta=0.45,
            min_hold_duration=timedelta(minutes=10),
            decay_factor_per_hour=0.05,
            emergency_override_confidence=0.95,
            post_trade_cooldown=timedelta(minutes=60),
        )


@dataclass
class HysteresisStats:
    """Statistics for hysteresis behavior tracking.

    Attributes:
        total_decisions: Total number of decisions processed.
        decisions_overridden: Number of decisions blocked by hysteresis.
        action_changes: Number of actual action changes allowed.
        reversals_blocked: Number of BUY<->SELL reversals blocked.
        last_action_change: Timestamp of last action change.
        action_durations: Duration history per action type.
    """

    total_decisions: int = 0
    decisions_overridden: int = 0
    action_changes: int = 0
    reversals_blocked: int = 0
    last_action_change: datetime | None = None
    action_durations: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging.

        Returns:
            Dictionary with key statistics.
        """
        return {
            "total_decisions": self.total_decisions,
            "decisions_overridden": self.decisions_overridden,
            "override_rate_pct": (
                self.decisions_overridden / self.total_decisions * 100
                if self.total_decisions > 0
                else 0
            ),
            "action_changes": self.action_changes,
            "reversals_blocked": self.reversals_blocked,
        }


class HysteresisManager:
    """Manages decision hysteresis to prevent oscillation.

    This class tracks previous decisions and applies threshold-based
    logic to prevent frequent action changes.

    Attributes:
        config: Hysteresis configuration.
        previous: Previous decision history.
        last_trade_action: Last non-HOLD action (BUY or SELL) for reversal checks.
        stats: Statistics tracker.
    """

    def __init__(self, config: HysteresisConfig | None = None):
        """Initialize hysteresis manager.

        Args:
            config: Optional configuration. Uses defaults if None.
        """
        self.config = config or HysteresisConfig()
        self.previous: DecisionHistory | None = None
        self.last_trade_action: DecisionHistory | None = None  # Tracks last BUY/SELL
        self.stats = HysteresisStats()

    def apply_hysteresis(
        self,
        new_decision: Decision,
        cycle_count: int,
        simulated_time: datetime | None = None,
    ) -> Decision:
        """Apply hysteresis to a new decision.

        Args:
            new_decision: The decision from DecisionAgent.
            cycle_count: Current cycle number.
            simulated_time: Optional simulated timestamp for backtesting.

        Returns:
            Modified decision (may be unchanged or overridden to previous action).
        """
        self.stats.total_decisions += 1
        current_time = simulated_time or datetime.now()

        new_action = new_decision["action"]
        new_confidence = new_decision["confidence"]

        # No previous decision - accept as-is
        if self.previous is None:
            self._update_history(new_decision, cycle_count, current_time)
            return new_decision

        prev_action = self.previous["action"]
        prev_confidence = self.previous["confidence"]

        # Same action - always accept, update confidence
        if new_action == prev_action:
            self._update_history(new_decision, cycle_count, current_time)
            return new_decision

        # Check for reversal against last trade action (BUY/SELL), not just previous
        # This prevents: BUY -> HOLD -> SELL from bypassing reversal check
        is_reversal = False
        reversal_ref_action = None
        reversal_ref_confidence = None

        if new_action in ("BUY", "SELL") and self.last_trade_action is not None:
            reversal_ref_action = self.last_trade_action["action"]
            reversal_ref_confidence = self.last_trade_action["confidence"]
            is_reversal = self._is_reversal(reversal_ref_action, new_action)

            # Check post-trade cooldown for reversals
            if is_reversal:
                last_trade_time = datetime.fromisoformat(self.last_trade_action["timestamp"])
                time_since_trade = current_time - last_trade_time

                if time_since_trade < self.config.post_trade_cooldown:
                    remaining = self.config.post_trade_cooldown - time_since_trade
                    logger.info(
                        f"Post-trade cooldown active: {reversal_ref_action} -> {new_action} blocked. "
                        f"Remaining: {remaining.total_seconds() / 60:.1f} min"
                    )
                    self.stats.decisions_overridden += 1
                    self.stats.reversals_blocked += 1

                    return Decision(
                        action="HOLD",
                        confidence=new_decision["confidence"],
                        suggested_size_pct=0.0,
                        rationale=(
                            f"[Cooldown] {new_action} blocked. "
                            f"Wait {remaining.total_seconds() / 60:.0f}min after {reversal_ref_action}. "
                            f"Original: {new_decision['rationale']}"
                        ),
                        status=new_decision["status"],
                        original_action=new_action,
                    )

        # Calculate required confidence delta
        if is_reversal:
            # For reversals, use last trade action as reference
            required_delta = self.config.action_reversal_delta
            ref_confidence = reversal_ref_confidence
            logger.debug(
                f"Reversal check: {reversal_ref_action} -> {new_action}, "
                f"using last trade confidence={ref_confidence:.2f}"
            )
        else:
            required_delta = self._calculate_required_delta(prev_action, new_action)
            ref_confidence = prev_confidence

        # Apply time decay
        required_delta = self._apply_time_decay(required_delta, current_time)

        # Check emergency override
        if new_confidence >= self.config.emergency_override_confidence:
            logger.info(
                f"Emergency override: {prev_action} -> {new_action} "
                f"(confidence={new_confidence:.2f})"
            )
            self.stats.action_changes += 1
            self._update_history(new_decision, cycle_count, current_time)
            return new_decision

        # Calculate effective delta against reference confidence
        confidence_delta = new_confidence - ref_confidence

        # Check if change is allowed
        if confidence_delta >= required_delta:
            logger.info(
                f"Hysteresis passed: {prev_action} -> {new_action} "
                f"(delta={confidence_delta:.2f} >= {required_delta:.2f})"
            )
            self.stats.action_changes += 1
            self._update_history(new_decision, cycle_count, current_time)
            return new_decision

        # Block the change - return modified decision with previous action
        block_reason = "reversal" if is_reversal else "threshold"
        logger.info(
            f"Hysteresis blocked ({block_reason}): {prev_action} -> {new_action} "
            f"(delta={confidence_delta:.2f} < {required_delta:.2f})"
        )
        self.stats.decisions_overridden += 1

        if is_reversal:
            self.stats.reversals_blocked += 1

        # Return HOLD decision when blocking action change
        # "Maintaining BUY" means "keep the bought position" = HOLD, not "buy more"
        # "Maintaining SELL" means "stay out of market" = HOLD, not "sell more"
        return Decision(
            action="HOLD",
            confidence=new_decision["confidence"],
            suggested_size_pct=0.0,
            rationale=(
                f"[Hysteresis] Maintaining position (was {prev_action}). "
                f"Original: {new_decision['rationale']}"
            ),
            status=new_decision["status"],
            original_action=new_action,  # Track what was originally proposed
        )

    def _calculate_required_delta(
        self,
        prev_action: Literal["BUY", "SELL", "HOLD"],
        new_action: Literal["BUY", "SELL", "HOLD"],
    ) -> float:
        """Calculate required confidence delta for action change.

        Args:
            prev_action: Previous action.
            new_action: New proposed action.

        Returns:
            Required confidence delta.
        """
        if self._is_reversal(prev_action, new_action):
            return self.config.action_reversal_delta
        elif prev_action == "HOLD":
            return self.config.hold_to_action_delta
        else:  # BUY/SELL -> HOLD
            return self.config.action_to_hold_delta

    def _is_reversal(
        self,
        action1: Literal["BUY", "SELL", "HOLD"],
        action2: Literal["BUY", "SELL", "HOLD"],
    ) -> bool:
        """Check if transition is a BUY<->SELL reversal.

        Args:
            action1: First action.
            action2: Second action.

        Returns:
            True if this is a reversal.
        """
        return (action1 == "BUY" and action2 == "SELL") or (
            action1 == "SELL" and action2 == "BUY"
        )

    def _apply_time_decay(
        self, required_delta: float, current_time: datetime
    ) -> float:
        """Reduce required delta based on time since last decision.

        Args:
            required_delta: Base required delta.
            current_time: Current timestamp (real or simulated).

        Returns:
            Time-decayed delta (minimum 50% of original).
        """
        if self.previous is None:
            return required_delta

        prev_time = datetime.fromisoformat(self.previous["timestamp"])
        elapsed = current_time - prev_time

        # No decay within minimum hold duration
        if elapsed < self.config.min_hold_duration:
            return required_delta

        # Calculate decay
        hours_elapsed = elapsed.total_seconds() / 3600
        decay = self.config.decay_factor_per_hour * hours_elapsed

        # Cap decay at 50% reduction
        return required_delta * max(0.5, 1.0 - decay)

    def _update_history(
        self,
        decision: Decision,
        cycle_count: int,
        current_time: datetime | None = None,
    ) -> None:
        """Update previous decision history.

        Args:
            decision: Decision to record.
            cycle_count: Current cycle number.
            current_time: Optional simulated timestamp for backtesting.
        """
        now = current_time or datetime.now()
        action = decision["action"]

        # Track duration of previous action
        if self.previous is not None and self.previous["action"] != action:
            prev_time = datetime.fromisoformat(self.previous["timestamp"])
            duration = (now - prev_time).total_seconds()
            prev_action = self.previous["action"]

            if prev_action not in self.stats.action_durations:
                self.stats.action_durations[prev_action] = []
            self.stats.action_durations[prev_action].append(duration)
            self.stats.last_action_change = now

        history = DecisionHistory(
            action=action,
            confidence=decision["confidence"],
            timestamp=now.isoformat(),
            rationale=decision["rationale"],
            cycle_count=cycle_count,
        )

        self.previous = history

        # Update last_trade_action only for BUY/SELL (not HOLD)
        # This ensures reversal checks work even after HOLD periods
        if action in ("BUY", "SELL"):
            self.last_trade_action = history
            logger.debug(f"Last trade action updated: {action} (confidence={decision['confidence']:.2f})")

    def reset(self) -> None:
        """Reset hysteresis state.

        Clears previous decision and last trade action but keeps stats for analysis.
        Use after manual intervention or system restart.
        """
        self.previous = None
        self.last_trade_action = None
        logger.info("Hysteresis state reset (stats preserved)")
