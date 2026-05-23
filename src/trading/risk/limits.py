"""Risk limits and position sizing."""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from trading.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration."""

    max_daily_loss_pct: float = 3.0
    max_position_pct: float = 50.0
    min_order_krw: float = 5000.0
    max_single_trade_pct: float = 10.0  # Max % of portfolio per trade
    max_trades_per_day: int = 20  # Max BUY trades per day. SELL is always allowed.

    @classmethod
    def from_settings(cls) -> "RiskLimits":
        """Create RiskLimits from settings."""
        settings = get_settings()
        return cls(
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_position_pct=settings.max_position_pct,
            min_order_krw=settings.min_order_krw,
            max_trades_per_day=settings.max_trades_per_day,
        )


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations."""

    total_value_krw: float
    cash_krw: float
    btc_value_krw: float
    daily_pnl_pct: float
    unrealized_pnl_pct: float

    @property
    def exposure_pct(self) -> float:
        """Get current BTC exposure percentage."""
        if self.total_value_krw == 0:
            return 0.0
        return (self.btc_value_krw / self.total_value_krw) * 100


class RiskManager:
    """Manager for risk limit enforcement."""

    def __init__(self, limits: RiskLimits | None = None):
        """Initialize risk manager.

        Args:
            limits: Risk limits configuration (uses defaults if None).
        """
        self.limits = limits or RiskLimits.from_settings()
        self._kill_switch = False
        self._daily_trades: list[dict] = []

    @property
    def is_kill_switch_on(self) -> bool:
        """Check if kill switch is activated."""
        return self._kill_switch

    def activate_kill_switch(self, reason: str) -> None:
        """Activate kill switch to halt all trading.

        Args:
            reason: Reason for activation.
        """
        self._kill_switch = True
        logger.warning(f"Kill switch activated: {reason}")

    def deactivate_kill_switch(self) -> None:
        """Deactivate kill switch."""
        self._kill_switch = False
        logger.info("Kill switch deactivated")

    def get_buy_count_today(self, when: datetime | None = None) -> int:
        """Return executed BUY count for the given day (default: today).

        Reads from the trade log JSONL (logs/trades_YYYYMMDD.jsonl) so the
        count survives process restarts and works across separately-created
        RiskManager instances (RiskAgent re-instantiates per cycle).
        """
        import json

        day = (when or datetime.now()).date()
        settings = get_settings()
        log_file = settings.log_dir / f"trades_{day.strftime('%Y%m%d')}.jsonl"
        if not log_file.exists():
            return 0
        count = 0
        try:
            with open(log_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    decision = entry.get("decision") or {}
                    result = entry.get("result") or {}
                    # Count only successfully filled BUY orders. Rejected /
                    # failed orders do not consume the daily quota.
                    if decision.get("action") == "BUY" and result.get("status") == "filled":
                        count += 1
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to read trade log for daily cap: {e}")
            return 0
        return count

    def check_daily_trade_cap(
        self,
        action: Literal["BUY", "SELL", "HOLD"],
        when: datetime | None = None,
    ) -> tuple[bool, str]:
        """Check if daily BUY cap has been reached.

        SELL is always allowed (stop-loss exemption) — passing SELL or HOLD
        always returns OK. Only BUY is rate-limited per day.

        Args:
            action: Proposed action.
            when: Timestamp (defaults to now).

        Returns:
            Tuple of (is_ok, message).
        """
        if action != "BUY":
            return True, "Non-BUY action exempt from daily trade cap"
        count = self.get_buy_count_today(when)
        if count >= self.limits.max_trades_per_day:
            return (
                False,
                f"Daily BUY cap reached: {count}/{self.limits.max_trades_per_day}",
            )
        return True, f"Daily BUY count: {count}/{self.limits.max_trades_per_day}"

    def check_daily_loss_limit(self, portfolio: PortfolioState) -> tuple[bool, str]:
        """Check if daily loss limit is breached.

        Args:
            portfolio: Current portfolio state.

        Returns:
            Tuple of (is_ok, message).
        """
        if portfolio.daily_pnl_pct <= -self.limits.max_daily_loss_pct:
            return False, f"Daily loss limit breached: {portfolio.daily_pnl_pct:.2f}%"
        return True, "Daily loss within limits"

    def check_position_limit(
        self,
        portfolio: PortfolioState,
        proposed_change_pct: float,
    ) -> tuple[bool, str]:
        """Check if position limit would be breached.

        Args:
            portfolio: Current portfolio state.
            proposed_change_pct: Proposed change in exposure (positive=buy, negative=sell).

        Returns:
            Tuple of (is_ok, message).
        """
        new_exposure = portfolio.exposure_pct + proposed_change_pct

        if new_exposure > self.limits.max_position_pct:
            return False, f"Position limit would be breached: {new_exposure:.1f}% > {self.limits.max_position_pct}%"

        if new_exposure < 0:
            return False, "Cannot have negative exposure"

        return True, "Position within limits"

    def check_minimum_order(self, order_krw: float) -> tuple[bool, str]:
        """Check if order meets minimum size.

        Args:
            order_krw: Order amount in KRW.

        Returns:
            Tuple of (is_ok, message).
        """
        if order_krw < self.limits.min_order_krw:
            return False, f"Order too small: {order_krw:,.0f} < {self.limits.min_order_krw:,.0f} KRW"
        return True, "Order size OK"

    def calculate_max_buy_amount(self, portfolio: PortfolioState) -> float:
        """Calculate maximum BUY amount allowed.

        Args:
            portfolio: Current portfolio state.

        Returns:
            Maximum KRW amount that can be used for buying.
        """
        # Maximum based on position limit
        max_exposure_increase = self.limits.max_position_pct - portfolio.exposure_pct
        max_from_position = (max_exposure_increase / 100) * portfolio.total_value_krw

        # Maximum based on single trade limit
        max_from_trade_limit = (self.limits.max_single_trade_pct / 100) * portfolio.total_value_krw

        # Maximum based on available cash
        max_from_cash = portfolio.cash_krw

        return max(0, min(max_from_position, max_from_trade_limit, max_from_cash))

    def calculate_max_sell_amount(self, portfolio: PortfolioState) -> float:
        """Calculate maximum SELL amount allowed.

        Args:
            portfolio: Current portfolio state.

        Returns:
            Maximum KRW equivalent that can be sold.
        """
        # Maximum based on single trade limit
        max_from_trade_limit = (self.limits.max_single_trade_pct / 100) * portfolio.total_value_krw

        # Maximum based on holdings
        max_from_holdings = portfolio.btc_value_krw

        return max(0, min(max_from_trade_limit, max_from_holdings))

    def validate_trade(
        self,
        portfolio: PortfolioState,
        action: Literal["BUY", "SELL", "HOLD"],
        amount_krw: float,
    ) -> tuple[bool, list[str]]:
        """Validate a proposed trade against all risk rules.

        Args:
            portfolio: Current portfolio state.
            action: Proposed action.
            amount_krw: Trade amount in KRW.

        Returns:
            Tuple of (is_valid, list of issues).
        """
        issues = []

        # Check kill switch
        if self._kill_switch:
            issues.append("Kill switch is active - all trading halted")
            return False, issues

        # HOLD is always valid
        if action == "HOLD":
            return True, []

        # Check daily loss
        ok, msg = self.check_daily_loss_limit(portfolio)
        if not ok:
            issues.append(msg)

        # Check daily BUY cap (SELL is always exempt for stop-loss safety)
        ok, msg = self.check_daily_trade_cap(action)
        if not ok:
            issues.append(msg)

        # Check minimum order
        ok, msg = self.check_minimum_order(amount_krw)
        if not ok:
            issues.append(msg)

        # Calculate exposure change
        if action == "BUY":
            change_pct = (amount_krw / portfolio.total_value_krw) * 100 if portfolio.total_value_krw > 0 else 0
            max_amount = self.calculate_max_buy_amount(portfolio)
            if amount_krw > max_amount:
                issues.append(f"BUY amount exceeds limit: {amount_krw:,.0f} > {max_amount:,.0f} KRW")
        else:  # SELL
            change_pct = -(amount_krw / portfolio.total_value_krw) * 100 if portfolio.total_value_krw > 0 else 0
            max_amount = self.calculate_max_sell_amount(portfolio)
            if amount_krw > max_amount:
                issues.append(f"SELL amount exceeds holdings: {amount_krw:,.0f} > {max_amount:,.0f} KRW")

        # Check position limit
        ok, msg = self.check_position_limit(portfolio, change_pct)
        if not ok:
            issues.append(msg)

        return len(issues) == 0, issues

    def adjust_trade_size(
        self,
        portfolio: PortfolioState,
        action: Literal["BUY", "SELL"],
        requested_pct: float,
    ) -> float:
        """Adjust trade size to comply with risk limits.

        Args:
            portfolio: Current portfolio state.
            action: Trade action.
            requested_pct: Requested trade size as % of portfolio.

        Returns:
            Adjusted trade size percentage.
        """
        if action == "BUY":
            max_amount = self.calculate_max_buy_amount(portfolio)
            # Debug: breakdown of max buy calculation
            max_exposure_increase = self.limits.max_position_pct - portfolio.exposure_pct
            max_from_position = (max_exposure_increase / 100) * portfolio.total_value_krw
            max_from_trade = (self.limits.max_single_trade_pct / 100) * portfolio.total_value_krw
            logger.debug(
                f"BUY limits: max_exposure_increase={max_exposure_increase:.2f}%, "
                f"max_from_position={max_from_position:,.0f}, max_from_trade={max_from_trade:,.0f}, "
                f"cash={portfolio.cash_krw:,.0f}, final_max={max_amount:,.0f}"
            )
        else:
            max_amount = self.calculate_max_sell_amount(portfolio)

        max_pct = (max_amount / portfolio.total_value_krw) * 100 if portfolio.total_value_krw > 0 else 0

        # Also limit by single trade limit
        max_pct = min(max_pct, self.limits.max_single_trade_pct)

        logger.debug(
            f"adjust_trade_size: action={action}, requested={requested_pct:.2f}%, "
            f"max_pct={max_pct:.2f}%, result={min(requested_pct, max_pct):.2f}%"
        )

        return min(requested_pct, max_pct)
