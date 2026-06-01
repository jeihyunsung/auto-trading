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


class TestReversalAnchorDecay:
    """[#h5] — stale BUY/SELL anchor confidence must decay so that LLM
    moderate SELL recommendations can eventually pass even when their
    confidence is at or below the original entry conf.
    """

    def _make_decision(
        self,
        action: str = "HOLD",
        confidence: float = 0.5,
        size: float = 0.0,
    ) -> Decision:
        return Decision(
            action=action,
            confidence=confidence,
            suggested_size_pct=size,
            rationale="t",
            status="pending",
        )

    def _seed_last_trade(
        self,
        manager: HysteresisManager,
        action: str,
        confidence: float,
        when: datetime,
    ) -> None:
        manager.last_trade_action = {
            "action": action,
            "confidence": confidence,
            "size": 5.0,
            "timestamp": when.isoformat(),
            "rationale": "seeded",
        }
        # Also seed `previous` so reversal branch picks it up.
        manager.previous = manager.last_trade_action.copy()

    def test_reversal_anchor_decay_allows_stale_buy_to_sell(self):
        """24h-old BUY conf=0.65 should let SELL conf=0.65 through.

        After grace (6h), 18h of decay at 0.02/h = 0.36 drop, but floored
        at 0.55. With anchor at 0.55 and SELL at 0.65, delta=+0.10 which
        is above the streaming reversal threshold of 0.15? No — still
        below. Use a longer elapsed and stronger SELL.
        """
        config = HysteresisConfig.streaming()
        manager = HysteresisManager(config)

        base = datetime(2026, 5, 30, 20, 9, 0)
        self._seed_last_trade(manager, "BUY", confidence=0.65, when=base)

        # 18h later: past the 15min post-trade cooldown and well past the
        # 6h grace, anchor decays from 0.65 toward floor 0.55.
        later = base + timedelta(hours=18)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.75, size=5.0),
            cycle_count=10,
            simulated_time=later,
        )
        assert result["action"] == "SELL", (
            f"Expected stale anchor decay to allow SELL through; got HOLD. "
            f"Rationale: {result.get('rationale','')}"
        )

    def test_recent_buy_still_blocks_moderate_sell(self):
        """Within the 6h grace, anchor is unchanged so SELL conf 0.60 vs
        anchor 0.65 (delta -0.05) must remain blocked."""
        config = HysteresisConfig.streaming()
        manager = HysteresisManager(config)

        base = datetime(2026, 5, 30, 20, 9, 0)
        self._seed_last_trade(manager, "BUY", confidence=0.65, when=base)

        # 2h after entry — well past post-trade cooldown (15min) but
        # before the 6h decay grace.
        later = base + timedelta(hours=2)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.60, size=5.0),
            cycle_count=5,
            simulated_time=later,
        )
        assert result["action"] == "HOLD", (
            "SELL conf below recent BUY anchor must stay blocked while "
            "the anchor is still fresh"
        )

    def test_anchor_decay_respects_floor(self):
        """Anchor floor (0.55) must clamp the decay so a very weak SELL
        still cannot reverse a fresh trade purely by passage of time."""
        config = HysteresisConfig.streaming()
        manager = HysteresisManager(config)

        base = datetime(2026, 5, 30, 20, 9, 0)
        self._seed_last_trade(manager, "BUY", confidence=0.65, when=base)

        # 100 hours later — decay would be 0.65 - 0.02*94 = ... below
        # floor, so anchor is clamped at 0.55. SELL at 0.50 has delta
        # = -0.05, must stay blocked.
        later = base + timedelta(hours=100)
        result = manager.apply_hysteresis(
            self._make_decision(action="SELL", confidence=0.50, size=5.0),
            cycle_count=5,
            simulated_time=later,
        )
        assert result["action"] == "HOLD", (
            "Anchor floor must keep extremely weak SELLs blocked"
        )

    def test_anchor_decay_does_not_affect_same_direction(self):
        """Decay should only relax reversal anchor. A BUY following an
        old BUY should still be governed by same_direction_cooldown_buy,
        not by anchor decay."""
        config = HysteresisConfig.streaming()
        manager = HysteresisManager(config)

        base = datetime(2026, 5, 30, 20, 9, 0)
        self._seed_last_trade(manager, "BUY", confidence=0.65, when=base)

        # 18h later (past decay grace, well past 15min same-dir cooldown)
        later = base + timedelta(hours=18)

        # BUY -> BUY is not a reversal, so anchor decay path doesn't fire.
        # Same-direction cooldown of 15min is already expired, so a
        # moderately confident BUY should pass.
        result = manager.apply_hysteresis(
            self._make_decision(action="BUY", confidence=0.70, size=5.0),
            cycle_count=5,
            simulated_time=later,
        )
        assert result["action"] == "BUY", (
            "Same-direction BUY past cooldown should pass independently "
            "of anchor decay"
        )
