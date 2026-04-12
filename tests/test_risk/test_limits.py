"""Tests for risk limits and management."""

import pytest

from trading.risk.limits import PortfolioState, RiskLimits, RiskManager


class TestRiskLimits:
    """Tests for RiskLimits configuration."""

    def test_default_limits(self):
        """Test default risk limits."""
        limits = RiskLimits()

        assert limits.max_daily_loss_pct == 3.0
        assert limits.max_position_pct == 50.0
        assert limits.min_order_krw == 5000.0

    def test_custom_limits(self):
        """Test custom risk limits."""
        limits = RiskLimits(
            max_daily_loss_pct=5.0,
            max_position_pct=30.0,
            min_order_krw=10000.0,
        )

        assert limits.max_daily_loss_pct == 5.0
        assert limits.max_position_pct == 30.0
        assert limits.min_order_krw == 10000.0


class TestPortfolioState:
    """Tests for PortfolioState."""

    def test_exposure_calculation(self):
        """Test exposure percentage calculation."""
        state = PortfolioState(
            total_value_krw=1_000_000,
            cash_krw=500_000,
            btc_value_krw=500_000,
            daily_pnl_pct=0.0,
            unrealized_pnl_pct=0.0,
        )

        assert state.exposure_pct == 50.0

    def test_zero_total_value(self):
        """Test exposure with zero total value."""
        state = PortfolioState(
            total_value_krw=0,
            cash_krw=0,
            btc_value_krw=0,
            daily_pnl_pct=0.0,
            unrealized_pnl_pct=0.0,
        )

        assert state.exposure_pct == 0.0


class TestRiskManager:
    """Tests for RiskManager."""

    @pytest.fixture
    def risk_manager(self):
        """Create risk manager with default limits."""
        return RiskManager()

    @pytest.fixture
    def portfolio(self):
        """Create sample portfolio state."""
        return PortfolioState(
            total_value_krw=1_000_000,
            cash_krw=600_000,
            btc_value_krw=400_000,
            daily_pnl_pct=-1.0,
            unrealized_pnl_pct=5.0,
        )

    def test_daily_loss_within_limit(self, risk_manager, portfolio):
        """Test daily loss check passes within limit."""
        ok, msg = risk_manager.check_daily_loss_limit(portfolio)

        assert ok is True

    def test_daily_loss_breached(self, risk_manager):
        """Test daily loss check fails when breached."""
        portfolio = PortfolioState(
            total_value_krw=1_000_000,
            cash_krw=500_000,
            btc_value_krw=500_000,
            daily_pnl_pct=-4.0,  # Exceeds 3% limit
            unrealized_pnl_pct=0.0,
        )

        ok, msg = risk_manager.check_daily_loss_limit(portfolio)

        assert ok is False
        assert "Daily loss limit breached" in msg

    def test_position_limit_ok(self, risk_manager, portfolio):
        """Test position limit check passes."""
        # 40% exposure + 5% increase = 45% < 50% limit
        ok, msg = risk_manager.check_position_limit(portfolio, 5.0)

        assert ok is True

    def test_position_limit_breached(self, risk_manager, portfolio):
        """Test position limit check fails when breached."""
        # 40% exposure + 20% increase = 60% > 50% limit
        ok, msg = risk_manager.check_position_limit(portfolio, 20.0)

        assert ok is False
        assert "Position limit would be breached" in msg

    def test_minimum_order_ok(self, risk_manager):
        """Test minimum order check passes."""
        ok, msg = risk_manager.check_minimum_order(10_000)

        assert ok is True

    def test_minimum_order_too_small(self, risk_manager):
        """Test minimum order check fails for small orders."""
        ok, msg = risk_manager.check_minimum_order(1_000)

        assert ok is False
        assert "Order too small" in msg

    def test_calculate_max_buy(self, risk_manager, portfolio):
        """Test max buy amount calculation."""
        max_buy = risk_manager.calculate_max_buy_amount(portfolio)

        # Max position is 50%, current is 40%, can increase by 10%
        # But limited by single trade limit (10%)
        assert max_buy <= 100_000  # 10% of 1M

    def test_kill_switch(self, risk_manager):
        """Test kill switch activation."""
        assert not risk_manager.is_kill_switch_on

        risk_manager.activate_kill_switch("Test reason")

        assert risk_manager.is_kill_switch_on

        risk_manager.deactivate_kill_switch()

        assert not risk_manager.is_kill_switch_on

    def test_validate_trade_with_kill_switch(self, risk_manager, portfolio):
        """Test trade validation fails when kill switch is on."""
        risk_manager.activate_kill_switch("Test")

        valid, issues = risk_manager.validate_trade(portfolio, "BUY", 50_000)

        assert valid is False
        assert any("Kill switch" in issue for issue in issues)

    def test_validate_hold_always_valid(self, risk_manager, portfolio):
        """Test HOLD action is always valid."""
        valid, issues = risk_manager.validate_trade(portfolio, "HOLD", 0)

        assert valid is True
        assert len(issues) == 0

    def test_adjust_trade_size(self, risk_manager, portfolio):
        """Test trade size adjustment."""
        # Request 20% but max allowed is 10%
        adjusted = risk_manager.adjust_trade_size(portfolio, "BUY", 20.0)

        assert adjusted <= 10.0
