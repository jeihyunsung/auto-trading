"""Risk validation agent."""

import logging
from datetime import datetime
from decimal import Decimal

from trading.adapters.upbit import UpbitBrokerAdapter, get_broker
from trading.core.time import KST
from trading.config import get_settings
from trading.core.isolated_balance import get_isolated_tracker
from trading.core.state import Decision, Portfolio, TradingState
from trading.risk.limits import PortfolioState, RiskManager
from trading.risk.validator import DecisionValidator

logger = logging.getLogger(__name__)


class RiskAgent:
    """Agent for validating trading decisions against risk rules."""

    def __init__(
        self,
        broker: UpbitBrokerAdapter | None = None,
        risk_manager: RiskManager | None = None,
        validator: DecisionValidator | None = None,
    ):
        """Initialize risk agent.

        Args:
            broker: Broker adapter for balance checks.
            risk_manager: Risk manager instance.
            validator: Decision validator instance.
        """
        self.broker = broker or get_broker()
        self.risk_manager = risk_manager or RiskManager()
        self.validator = validator or DecisionValidator(self.risk_manager)

    def get_portfolio_state(self, market_price: float) -> PortfolioState:
        """Get current portfolio state.

        Uses isolated balance if isolated mode is enabled, otherwise
        uses actual exchange balance.

        Args:
            market_price: Current BTC price in KRW.

        Returns:
            PortfolioState for risk calculations.
        """
        # Check if isolated mode is enabled
        isolated_tracker = get_isolated_tracker()
        if isolated_tracker is not None:
            # Use isolated balance for risk calculations
            portfolio = isolated_tracker.get_portfolio_value(market_price)
            logger.debug(
                f"Using isolated balance: KRW={portfolio['krw_balance']:,.0f}, "
                f"BTC={portfolio['btc_balance']:.8f}, exposure={portfolio['exposure_pct']:.1f}%"
            )
            # Use tracker's midnight-rebased daily P&L (not cumulative pnl_pct)
            # so the RiskManager's daily loss limit only triggers on today's
            # drawdown, not multi-day cumulative loss.
            return PortfolioState(
                total_value_krw=portfolio["total_value_krw"],
                cash_krw=portfolio["krw_balance"],
                btc_value_krw=portfolio["btc_value_krw"],
                daily_pnl_pct=portfolio.get("daily_pnl_pct", 0.0),
                unrealized_pnl_pct=portfolio.get("unrealized_pnl_pct", 0.0),
            )

        # Use actual exchange balance
        balances = self.broker.get_all_balances()
        krw = float(balances.get("KRW", Decimal("0")))
        btc = float(balances.get("BTC", Decimal("0")))
        btc_value = btc * market_price
        total = krw + btc_value

        # TODO: Calculate actual daily P&L from trade history
        daily_pnl = 0.0  # Placeholder

        return PortfolioState(
            total_value_krw=total,
            cash_krw=krw,
            btc_value_krw=btc_value,
            daily_pnl_pct=daily_pnl,
            unrealized_pnl_pct=0.0,  # Placeholder
        )

    def validate(self, state: TradingState) -> Decision:
        """Validate decision in state.

        Args:
            state: Current trading state.

        Returns:
            Updated Decision with approval status.
        """
        decision = state.get("decision")
        if not decision:
            logger.warning("No decision to validate")
            return Decision(
                action="HOLD",
                confidence=0.0,
                suggested_size_pct=0.0,
                rationale="No decision provided",
                status="rejected",
            )

        # Get market price
        market = state.get("market", {})
        market_price = market.get("current_price", 0)

        if market_price <= 0:
            logger.warning("Invalid market price for validation")
            decision["status"] = "rejected"
            return decision

        # Get portfolio state
        portfolio_state = self.get_portfolio_state(market_price)

        # Get volatility and anomalies
        volatility = market.get("volatility_level", "medium")
        anomalies = state.get("anomalies", [])

        # Validate
        result = self.validator.validate(
            decision=decision,
            portfolio=portfolio_state,
            volatility=volatility,
            anomaly_count=len(anomalies),
        )

        # Update decision
        if result.approved:
            decision["status"] = "approved"
            decision["suggested_size_pct"] = result.adjusted_size_pct

            # Also update position_delta_pct if present (for target position sizing)
            original_delta = decision.get("position_delta_pct")
            if original_delta is not None:
                # Preserve the sign (direction) but use adjusted magnitude
                adjusted_delta = result.adjusted_size_pct if original_delta >= 0 else -result.adjusted_size_pct
                decision["position_delta_pct"] = adjusted_delta

            if result.warnings:
                decision["rationale"] += f" | Warnings: {'; '.join(result.warnings)}"
        else:
            decision["status"] = "rejected"
            decision["rationale"] += f" | Rejected: {result.rejection_reason}"

        logger.info(
            f"Risk validation: {decision['action']} -> {decision['status']} "
            f"(size={result.adjusted_size_pct:.1f}%)"
        )

        return decision

    def get_portfolio_for_state(self, market_price: float) -> Portfolio:
        """Get Portfolio dict for state.

        Args:
            market_price: Current BTC price.

        Returns:
            Portfolio TypedDict.
        """
        ps = self.get_portfolio_state(market_price)

        btc_balance = ps.btc_value_krw / market_price if market_price > 0 else 0

        return Portfolio(
            cash_krw=ps.cash_krw,
            btc_balance=btc_balance,
            avg_entry_price=0.0,  # TODO: Track from trade history
            unrealized_pnl=ps.unrealized_pnl_pct,
            exposure_pct=ps.exposure_pct,
        )


def risk_agent_node(state: TradingState) -> dict:
    """LangGraph node function for risk agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with validated decision and portfolio.
    """
    agent = RiskAgent()

    try:
        # Get market price for portfolio calculation
        market = state.get("market", {})
        market_price = market.get("current_price", 0)

        # Get portfolio state
        if market_price > 0:
            portfolio = agent.get_portfolio_for_state(market_price)
        else:
            portfolio = None

        # Validate decision
        decision = agent.validate(state)

        return {
            "decision": decision,
            "portfolio": portfolio,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Risk agent failed: {e}")
        decision = state.get("decision")
        if decision:
            decision["status"] = "rejected"
            decision["rationale"] += f" | Risk error: {e}"

        return {
            "decision": decision,
            "error": f"Risk agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
