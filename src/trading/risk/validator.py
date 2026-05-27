"""LLM decision validator."""

import logging
from dataclasses import dataclass
from typing import Literal

from trading.core.state import Decision
from trading.llm.client import get_llm_client
from trading.llm.prompts import RISK_VALIDATION_SYSTEM_PROMPT, RISK_VALIDATION_USER_PROMPT
from trading.llm.schemas import RiskValidationInput, RiskValidationOutput
from trading.risk.limits import PortfolioState, RiskLimits, RiskManager

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of decision validation."""

    approved: bool
    adjusted_size_pct: float
    rejection_reason: str | None
    warnings: list[str]
    rule_checks: dict[str, bool]


class DecisionValidator:
    """Validator for LLM trading decisions."""

    # Minimum confidence required for different actions
    MIN_CONFIDENCE = {
        "BUY": 0.6,
        "SELL": 0.6,
        "HOLD": 0.0,
    }

    def __init__(
        self,
        risk_manager: RiskManager | None = None,
        use_llm_validation: bool = False,
    ):
        """Initialize validator.

        Args:
            risk_manager: RiskManager instance (creates new if None).
            use_llm_validation: Whether to use LLM for additional validation.
        """
        self.risk_manager = risk_manager or RiskManager()
        self.use_llm_validation = use_llm_validation

    def validate(
        self,
        decision: Decision,
        portfolio: PortfolioState,
        volatility: Literal["low", "medium", "high"] = "medium",
        anomaly_count: int = 0,
    ) -> ValidationResult:
        """Validate a trading decision.

        Args:
            decision: The decision to validate.
            portfolio: Current portfolio state.
            volatility: Current market volatility level.
            anomaly_count: Number of detected anomalies.

        Returns:
            ValidationResult with approval status and adjustments.
        """
        rule_checks = {}
        warnings = []
        rejection_reason = None

        # Urgent-exit detection: stop-loss / rapid_movement set
        # bypass_hysteresis=True. For these, max_single_trade_pct (10%)
        # would force-fragment the exit into multiple cycles — observed
        # as the 5/27 stop-loss firing 4 times instead of once. Skip
        # adjust_trade_size and the volatility 50% cut so the urgent
        # decision goes through at the requested size, capped only by
        # available holdings/cash.
        is_urgent = bool(decision.get("bypass_hysteresis", False))

        # Check 1: Kill switch
        if self.risk_manager.is_kill_switch_on:
            return ValidationResult(
                approved=False,
                adjusted_size_pct=0.0,
                rejection_reason="Kill switch is active",
                warnings=[],
                rule_checks={"kill_switch": False},
            )
        rule_checks["kill_switch"] = True

        # Check 2: HOLD is always valid
        if decision["action"] == "HOLD":
            return ValidationResult(
                approved=True,
                adjusted_size_pct=0.0,
                rejection_reason=None,
                warnings=[],
                rule_checks=rule_checks,
            )

        # Check 3: Confidence threshold
        min_conf = self.MIN_CONFIDENCE[decision["action"]]
        if decision["confidence"] < min_conf:
            rule_checks["confidence"] = False
            rejection_reason = f"Confidence too low: {decision['confidence']:.2f} < {min_conf}"
        else:
            rule_checks["confidence"] = True

        # Check 4: Daily loss limit (only blocks BUY, allows SELL for stop-loss)
        ok, msg = self.risk_manager.check_daily_loss_limit(portfolio)
        if not ok:
            if decision["action"] == "BUY":
                rule_checks["daily_loss"] = False
                rejection_reason = rejection_reason or f"{msg} - BUY blocked, SELL allowed for stop-loss"
            else:
                # Allow SELL even when daily loss breached (for stop-loss)
                rule_checks["daily_loss"] = True
                warnings.append(f"{msg} - SELL allowed for stop-loss")
        else:
            rule_checks["daily_loss"] = True

        # Check 5: Position limit
        requested_size = decision["suggested_size_pct"]
        change_pct = requested_size if decision["action"] == "BUY" else -requested_size
        ok, msg = self.risk_manager.check_position_limit(portfolio, change_pct)
        rule_checks["position_limit"] = ok
        if not ok:
            warnings.append(msg)

        # Adjust size — urgent exits skip max_single_trade_pct cap so the
        # full position can be unwound in a single order. Still respect
        # available holdings / cash as hard caps.
        if is_urgent:
            if decision["action"] == "SELL":
                # Cap by current exposure (cannot sell more than we hold)
                adjusted_size = min(requested_size, portfolio.exposure_pct)
            else:  # BUY (rapid_movement)
                cash_pct = (
                    (portfolio.cash_krw / portfolio.total_value_krw * 100)
                    if portfolio.total_value_krw > 0 else 0
                )
                # Also respect overall position limit (max_position_pct)
                position_room = (
                    self.risk_manager.limits.max_position_pct - portfolio.exposure_pct
                )
                adjusted_size = min(requested_size, cash_pct, max(0, position_room))
            logger.info(
                f"Urgent exit: size {requested_size:.1f}% → {adjusted_size:.1f}% "
                f"(skipping max_single_trade_pct={self.risk_manager.limits.max_single_trade_pct}%)"
            )
        else:
            adjusted_size = self.risk_manager.adjust_trade_size(
                portfolio, decision["action"], requested_size
            )

        # Debug logging for size adjustment
        logger.debug(
            f"Size adjustment: requested={requested_size:.2f}%, adjusted={adjusted_size:.2f}%, "
            f"exposure={portfolio.exposure_pct:.2f}%, cash={portfolio.cash_krw:,.0f}, "
            f"total={portfolio.total_value_krw:,.0f}"
        )

        # Check if size was reduced to 0 due to position limit
        if adjusted_size == 0 and requested_size > 0:
            max_position = self.risk_manager.limits.max_position_pct
            if decision["action"] == "BUY" and portfolio.exposure_pct >= max_position:
                rejection_reason = (
                    f"Position limit reached: exposure={portfolio.exposure_pct:.1f}% >= "
                    f"max={max_position}%. Cannot increase BTC position."
                )
                rule_checks["position_limit"] = False
                logger.info(rejection_reason)
            elif decision["action"] == "SELL" and portfolio.btc_value_krw <= 0:
                rejection_reason = "No BTC holdings to sell"
                rule_checks["holdings"] = False
                logger.info(rejection_reason)

        if adjusted_size < requested_size:
            warnings.append(
                f"Size adjusted from {requested_size:.1f}% to {adjusted_size:.1f}%"
            )

        # Check 6: Minimum order
        # For SELL, calculate based on BTC value; for BUY, based on total/cash
        if decision["action"] == "SELL":
            trade_amount = (adjusted_size / 100) * portfolio.btc_value_krw
            # If partial sell is below minimum but total BTC value is above minimum,
            # approve anyway - execution will sell full amount
            min_order = self.risk_manager.limits.min_order_krw
            if trade_amount < min_order and portfolio.btc_value_krw >= min_order:
                ok = True
                msg = None
                warnings.append(
                    f"Partial sell {trade_amount:,.0f} KRW < min {min_order:,.0f} KRW, "
                    f"will sell full amount ({portfolio.btc_value_krw:,.0f} KRW)"
                )
            else:
                ok, msg = self.risk_manager.check_minimum_order(trade_amount)
        else:
            trade_amount = (adjusted_size / 100) * portfolio.total_value_krw
            ok, msg = self.risk_manager.check_minimum_order(trade_amount)

        rule_checks["min_order"] = ok
        if not ok and rejection_reason is None:
            # Only use min_order rejection if no other reason was identified
            rejection_reason = msg
            logger.warning(
                f"Order rejected: trade_amount={trade_amount:,.0f}, "
                f"adjusted_size={adjusted_size:.2f}%, exposure={portfolio.exposure_pct:.2f}%"
            )

        # Check 7: High volatility caution (skipped for urgent exits —
        # halving a stop-loss size during a volatile drop is the opposite
        # of what we want; better to fully exit at once)
        if volatility == "high" and not is_urgent:
            adjusted_size = adjusted_size * 0.5  # Reduce size in high volatility
            warnings.append("Size reduced 50% due to high volatility")
        rule_checks["volatility_check"] = True

        # Check 8: Anomaly caution
        if anomaly_count >= 2:
            warnings.append(f"{anomaly_count} anomalies detected - proceed with caution")
        rule_checks["anomaly_check"] = True

        # Determine approval
        critical_checks = ["kill_switch", "confidence", "daily_loss", "min_order"]
        approved = all(rule_checks.get(c, True) for c in critical_checks)

        # Optional: LLM validation for additional checks
        if approved and self.use_llm_validation:
            llm_result = self._validate_with_llm(
                decision, portfolio, volatility, anomaly_count
            )
            if llm_result:
                if not llm_result.approved:
                    approved = False
                    rejection_reason = llm_result.rejection_reason
                warnings.extend(llm_result.warnings)
                if llm_result.adjusted_size_pct < adjusted_size:
                    adjusted_size = llm_result.adjusted_size_pct

        return ValidationResult(
            approved=approved,
            adjusted_size_pct=adjusted_size,
            rejection_reason=rejection_reason,
            warnings=warnings,
            rule_checks=rule_checks,
        )

    def _validate_with_llm(
        self,
        decision: Decision,
        portfolio: PortfolioState,
        volatility: str,
        anomaly_count: int,
    ) -> RiskValidationOutput | None:
        """Use LLM for additional validation.

        Args:
            decision: Decision to validate.
            portfolio: Portfolio state.
            volatility: Volatility level.
            anomaly_count: Number of anomalies.

        Returns:
            RiskValidationOutput or None if LLM unavailable.
        """
        try:
            llm = get_llm_client()
            if not llm.is_available:
                return None

            prompt = RISK_VALIDATION_USER_PROMPT.format(
                action=decision["action"],
                confidence=decision["confidence"],
                suggested_size=decision["suggested_size_pct"],
                rationale=decision["rationale"],
                krw_balance=portfolio.cash_krw,
                btc_balance=portfolio.btc_value_krw / portfolio.total_value_krw if portfolio.total_value_krw > 0 else 0,
                current_exposure=portfolio.exposure_pct,
                max_position=self.risk_manager.limits.max_position_pct,
                max_daily_loss=self.risk_manager.limits.max_daily_loss_pct,
                daily_pnl=portfolio.daily_pnl_pct,
                min_order=self.risk_manager.limits.min_order_krw,
                kill_switch="OFF" if not self.risk_manager.is_kill_switch_on else "ON",
                volatility=volatility,
                anomaly_count=anomaly_count,
            )

            return llm.invoke_json(
                RISK_VALIDATION_SYSTEM_PROMPT,
                prompt,
                RiskValidationOutput,
            )

        except Exception as e:
            logger.warning(f"LLM validation failed: {e}")
            return None

    def quick_validate(
        self,
        action: Literal["BUY", "SELL", "HOLD"],
        confidence: float,
        portfolio: PortfolioState,
    ) -> bool:
        """Quick validation without full decision object.

        Args:
            action: Proposed action.
            confidence: Confidence level.
            portfolio: Portfolio state.

        Returns:
            True if trade is likely valid.
        """
        if self.risk_manager.is_kill_switch_on:
            return False

        if action == "HOLD":
            return True

        if confidence < self.MIN_CONFIDENCE[action]:
            return False

        ok, _ = self.risk_manager.check_daily_loss_limit(portfolio)
        return ok
