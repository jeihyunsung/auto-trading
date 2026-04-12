"""Tests for decision hysteresis."""

from datetime import datetime, timedelta

import pytest

from trading.core.hysteresis import (
    HysteresisConfig,
    HysteresisManager,
    HysteresisStats,
)
from trading.core.state import Decision


class TestHysteresisStats:
    """Test HysteresisStats dataclass."""

    def test_to_dict_empty(self):
        """Empty stats should return zeros."""
        stats = HysteresisStats()
        result = stats.to_dict()

        assert result["total_decisions"] == 0
        assert result["decisions_overridden"] == 0
        assert result["override_rate_pct"] == 0
        assert result["action_changes"] == 0
        assert result["reversals_blocked"] == 0

    def test_to_dict_with_data(self):
        """Stats with data should calculate override rate."""
        stats = HysteresisStats(
            total_decisions=10,
            decisions_overridden=3,
            action_changes=7,
            reversals_blocked=1,
        )
        result = stats.to_dict()

        assert result["total_decisions"] == 10
        assert result["decisions_overridden"] == 3
        assert result["override_rate_pct"] == 30.0
        assert result["action_changes"] == 7
        assert result["reversals_blocked"] == 1


class TestHysteresisConfig:
    """Test HysteresisConfig dataclass."""

    def test_default_values(self):
        """Default config should have expected values."""
        config = HysteresisConfig()

        assert config.hold_to_action_delta == 0.15
        assert config.action_to_hold_delta == 0.20
        assert config.action_reversal_delta == 0.35
        assert config.min_hold_duration == timedelta(minutes=5)
        assert config.decay_factor_per_hour == 0.1
        assert config.emergency_override_confidence == 0.90

    def test_custom_values(self):
        """Custom config should override defaults."""
        config = HysteresisConfig(
            action_reversal_delta=0.5,
            emergency_override_confidence=0.95,
        )

        assert config.action_reversal_delta == 0.5
        assert config.emergency_override_confidence == 0.95


class TestHysteresisManager:
    """Test HysteresisManager class."""

    def _make_decision(
        self,
        action: str = "HOLD",
        confidence: float = 0.5,
        size: float = 0.0,
    ) -> Decision:
        """Helper to create Decision objects."""
        return Decision(
            action=action,
            confidence=confidence,
            suggested_size_pct=size,
            rationale="Test decision",
            status="pending",
        )

    def test_first_decision_no_hysteresis(self):
        """First decision should be accepted as-is."""
        manager = HysteresisManager()
        decision = self._make_decision(action="BUY", confidence=0.6, size=5.0)

        result = manager.apply_hysteresis(decision, cycle_count=1)

        assert result["action"] == "BUY"
        assert result["confidence"] == 0.6
        assert manager.previous is not None
        assert manager.previous["action"] == "BUY"
        assert manager.stats.total_decisions == 1
        assert manager.stats.decisions_overridden == 0

    def test_same_action_always_accepted(self):
        """Same action with different confidence should update."""
        manager = HysteresisManager()

        # First decision
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.6, size=5.0),
            cycle_count=1,
        )

        # Same action, lower confidence
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.4, size=3.0),
            cycle_count=2,
        )

        assert result["action"] == "BUY"
        assert result["confidence"] == 0.4
        assert manager.previous["confidence"] == 0.4
        assert manager.stats.decisions_overridden == 0

    def test_hold_to_buy_requires_delta(self):
        """HOLD->BUY needs hold_to_action_delta."""
        config = HysteresisConfig(hold_to_action_delta=0.15)
        manager = HysteresisManager(config)

        # Set previous as HOLD with 0.5 confidence
        manager.apply_hysteresis(
            self._make_decision(action="HOLD", confidence=0.5),
            cycle_count=1,
        )

        # Try BUY with 0.6 confidence (delta=0.1, below 0.15)
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.6, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "HOLD"  # Blocked
        assert "[Hysteresis]" in result["rationale"]
        assert manager.stats.decisions_overridden == 1

        # Try BUY with 0.7 confidence (delta=0.2, above 0.15)
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.7, size=5.0),
            cycle_count=3,
        )
        assert result["action"] == "BUY"  # Allowed
        assert manager.stats.action_changes == 1

    def test_buy_to_hold_requires_delta(self):
        """BUY->HOLD needs action_to_hold_delta."""
        config = HysteresisConfig(action_to_hold_delta=0.20)
        manager = HysteresisManager(config)

        # Set previous as BUY with 0.6 confidence
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.6, size=5.0),
            cycle_count=1,
        )

        # Try HOLD with 0.7 confidence (delta=0.1, below 0.20)
        result = manager.apply_hysteresis(
            self._make_decision(action="HOLD", confidence=0.7),
            cycle_count=2,
        )
        assert result["action"] == "BUY"  # Blocked
        assert manager.stats.decisions_overridden == 1

        # Try HOLD with 0.85 confidence (delta=0.25, above 0.20)
        result = manager.apply_hysteresis(
            self._make_decision(action="HOLD", confidence=0.85),
            cycle_count=3,
        )
        assert result["action"] == "HOLD"  # Allowed

    def test_buy_to_sell_requires_highest_delta(self):
        """BUY->SELL reversal needs action_reversal_delta."""
        config = HysteresisConfig(action_reversal_delta=0.35)
        manager = HysteresisManager(config)

        # Set previous as BUY with 0.5 confidence
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.5, size=5.0),
            cycle_count=1,
        )

        # Try SELL with 0.75 confidence (delta=0.25, below 0.35)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.75, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "BUY"  # Blocked
        assert manager.stats.reversals_blocked == 1

        # Try SELL with 0.9 confidence (delta=0.4, above 0.35)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.9, size=5.0),
            cycle_count=3,
        )
        assert result["action"] == "SELL"  # Allowed
        assert manager.stats.action_changes == 1

    def test_sell_to_buy_requires_highest_delta(self):
        """SELL->BUY reversal also needs action_reversal_delta."""
        config = HysteresisConfig(action_reversal_delta=0.35)
        manager = HysteresisManager(config)

        # Set previous as SELL
        manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.5, size=5.0),
            cycle_count=1,
        )

        # Try BUY with insufficient delta
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.7, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "SELL"  # Blocked
        assert manager.stats.reversals_blocked == 1

    def test_emergency_override(self):
        """Confidence >= emergency threshold should bypass hysteresis."""
        config = HysteresisConfig(
            action_reversal_delta=0.35,
            emergency_override_confidence=0.90,
        )
        manager = HysteresisManager(config)

        # Set previous as BUY with 0.8 confidence
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.8, size=5.0),
            cycle_count=1,
        )

        # Try SELL with 0.92 confidence (emergency override)
        # Delta is only 0.12, but confidence >= 0.90
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.92, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "SELL"  # Emergency override
        assert manager.stats.action_changes == 1

    def test_time_decay_reduces_threshold(self):
        """Threshold should decay after min_hold_duration."""
        config = HysteresisConfig(
            action_reversal_delta=0.35,
            min_hold_duration=timedelta(minutes=5),
            decay_factor_per_hour=0.1,
        )
        manager = HysteresisManager(config)

        # Set previous decision
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.5, size=5.0),
            cycle_count=1,
        )

        # Manually set old timestamp (2 hours ago)
        old_timestamp = (datetime.now() - timedelta(hours=2)).isoformat()
        manager.previous["timestamp"] = old_timestamp

        # Required delta should be reduced: 0.35 * (1 - 0.1*2) = 0.28
        # Try SELL with 0.8 confidence (delta=0.3, above 0.28)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.8, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "SELL"  # Allowed due to time decay

    def test_time_decay_caps_at_50_percent(self):
        """Time decay should not reduce threshold below 50%."""
        config = HysteresisConfig(
            action_reversal_delta=0.40,
            min_hold_duration=timedelta(minutes=5),
            decay_factor_per_hour=0.1,
        )
        manager = HysteresisManager(config)

        # Set previous decision
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.5, size=5.0),
            cycle_count=1,
        )

        # Set very old timestamp (10 hours ago)
        # Decay would be 100% but caps at 50%, so threshold = 0.40 * 0.5 = 0.20
        old_timestamp = (datetime.now() - timedelta(hours=10)).isoformat()
        manager.previous["timestamp"] = old_timestamp

        # Try SELL with 0.65 confidence (delta=0.15, below 0.20)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.65, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "BUY"  # Still blocked (50% decay cap)

        # Try SELL with 0.75 confidence (delta=0.25, above 0.20)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.75, size=5.0),
            cycle_count=3,
        )
        assert result["action"] == "SELL"  # Allowed

    def test_no_decay_within_min_hold_duration(self):
        """No time decay within min_hold_duration."""
        config = HysteresisConfig(
            action_reversal_delta=0.35,
            min_hold_duration=timedelta(minutes=5),
            decay_factor_per_hour=0.5,  # High decay rate
        )
        manager = HysteresisManager(config)

        # Set previous decision
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.5, size=5.0),
            cycle_count=1,
        )

        # Set timestamp 2 minutes ago (within min_hold_duration)
        recent_timestamp = (datetime.now() - timedelta(minutes=2)).isoformat()
        manager.previous["timestamp"] = recent_timestamp

        # Try SELL with 0.8 confidence (delta=0.3, below 0.35)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.8, size=5.0),
            cycle_count=2,
        )
        assert result["action"] == "BUY"  # Blocked (no decay applied)

    def test_stats_tracking(self):
        """Stats should accurately track overrides and changes."""
        manager = HysteresisManager()

        # First decision
        manager.apply_hysteresis(
            self._make_decision(action="HOLD", confidence=0.5),
            cycle_count=1,
        )

        # Blocked change
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.55, size=5.0),
            cycle_count=2,
        )

        # Allowed change
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.75, size=5.0),
            cycle_count=3,
        )

        assert manager.stats.total_decisions == 3
        assert manager.stats.decisions_overridden == 1
        assert manager.stats.action_changes == 1

    def test_reset_clears_history_keeps_stats(self):
        """Reset should clear previous decision but keep stats."""
        manager = HysteresisManager()
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.6, size=5.0),
            cycle_count=1,
        )

        assert manager.previous is not None
        old_total = manager.stats.total_decisions

        manager.reset()

        assert manager.previous is None
        assert manager.stats.total_decisions == old_total  # Stats preserved

    def test_blocked_decision_preserves_confidence(self):
        """Blocked decision should preserve original confidence."""
        manager = HysteresisManager()

        # Set HOLD
        manager.apply_hysteresis(
            self._make_decision(action="HOLD", confidence=0.3),
            cycle_count=1,
        )

        # Try BUY (blocked)
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.35, size=5.0),
            cycle_count=2,
        )

        assert result["action"] == "HOLD"
        assert result["confidence"] == 0.35  # Original confidence preserved
        assert result["suggested_size_pct"] == 0.0  # Size reset for HOLD

    def test_action_duration_tracking(self):
        """Action durations should be tracked on changes."""
        manager = HysteresisManager()

        # Set BUY
        manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.6, size=5.0),
            cycle_count=1,
        )

        # Set old timestamp
        old_timestamp = (datetime.now() - timedelta(seconds=120)).isoformat()
        manager.previous["timestamp"] = old_timestamp

        # Change to SELL (with high confidence to pass)
        manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.95, size=5.0),
            cycle_count=2,
        )

        assert "BUY" in manager.stats.action_durations
        assert len(manager.stats.action_durations["BUY"]) == 1
        assert manager.stats.action_durations["BUY"][0] >= 120


class TestHysteresisIntegration:
    """Integration tests with decision agent module."""

    def test_manager_getter_setter(self):
        """Test module-level getter/setter for hysteresis manager."""
        from trading.agents.decision_agent import (
            get_hysteresis_manager,
            set_hysteresis_manager,
        )

        # Initially None
        original = get_hysteresis_manager()

        try:
            # Set a manager
            manager = HysteresisManager()
            set_hysteresis_manager(manager)
            assert get_hysteresis_manager() is manager

            # Clear manager
            set_hysteresis_manager(None)
            assert get_hysteresis_manager() is None
        finally:
            # Restore original state
            set_hysteresis_manager(original)
