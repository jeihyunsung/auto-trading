"""Position sizing based on confidence and market conditions.

Calculates target position percentage based on model confidence,
then determines the delta (change) needed from current position.
"""

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class PositionSizingConfig:
    """Configuration for position sizing.

    Attributes:
        max_position_pct: Maximum allowed position (default 50%).
        min_trade_delta_pct: Minimum position change to trigger trade (default 5%).
        confidence_thresholds: Confidence levels for position tiers.
        position_tiers: Position % for each confidence tier.
    """

    max_position_pct: float = 50.0
    min_trade_delta_pct: float = 5.0

    # Confidence thresholds (must be sorted ascending)
    # Below first threshold = 0% position
    confidence_thresholds: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8)

    # Position % for each tier (as fraction of max_position)
    # Tier 0: conf < 0.5 -> 0%
    # Tier 1: 0.5 <= conf < 0.6 -> 30% of max
    # Tier 2: 0.6 <= conf < 0.7 -> 50% of max
    # Tier 3: 0.7 <= conf < 0.8 -> 70% of max
    # Tier 4: conf >= 0.8 -> 100% of max
    position_tiers: tuple[float, ...] = (0.0, 0.3, 0.5, 0.7, 1.0)


@dataclass
class PositionSizingResult:
    """Result of position sizing calculation.

    Attributes:
        target_position_pct: Target BTC exposure percentage.
        current_position_pct: Current BTC exposure percentage.
        delta_pct: Position change needed (positive=buy, negative=sell).
        action: Recommended action based on delta.
        should_trade: Whether the delta exceeds min_trade_delta.
        rationale: Explanation of the calculation.
    """

    target_position_pct: float
    current_position_pct: float
    delta_pct: float
    action: Literal["BUY", "SELL", "HOLD"]
    should_trade: bool
    rationale: str


class PositionSizer:
    """Calculates target position based on confidence."""

    def __init__(self, config: PositionSizingConfig | None = None):
        """Initialize position sizer.

        Args:
            config: Position sizing configuration.
        """
        self.config = config or PositionSizingConfig()

    def calculate_target_position(
        self,
        confidence: float,
        signal_direction: Literal["bullish", "bearish", "neutral"],
        current_exposure_pct: float = 0.0,
    ) -> float:
        """Calculate target position percentage based on confidence.

        Args:
            confidence: Model confidence (0.0 to 1.0).
            signal_direction: Overall signal direction.
            current_exposure_pct: Current exposure for gradual reduction.

        Returns:
            Target position percentage (0 to max_position_pct).
        """
        # Bearish: Gradual reduction based on confidence
        # Higher confidence = more aggressive reduction
        if signal_direction == "bearish":
            # Confidence 0.5-0.6: Keep 70% of current position
            # Confidence 0.6-0.7: Keep 50% of current position
            # Confidence 0.7-0.8: Keep 30% of current position
            # Confidence 0.8+: Full exit (0%)
            if confidence >= 0.8:
                return 0.0
            elif confidence >= 0.7:
                target = current_exposure_pct * 0.3
            elif confidence >= 0.6:
                target = current_exposure_pct * 0.5
            else:
                target = current_exposure_pct * 0.7

            logger.debug(
                f"Bearish sizing: confidence={confidence:.2f}, "
                f"current={current_exposure_pct:.1f}%, target={target:.1f}%"
            )
            return target

        if signal_direction == "neutral" and confidence < 0.6:
            return 0.0

        # Find tier based on confidence
        tier = 0
        for i, threshold in enumerate(self.config.confidence_thresholds):
            if confidence >= threshold:
                tier = i + 1
            else:
                break

        # Get position fraction for this tier
        position_fraction = self.config.position_tiers[tier]

        # Calculate actual position percentage
        target = self.config.max_position_pct * position_fraction

        logger.debug(
            f"Position sizing: confidence={confidence:.2f}, direction={signal_direction}, "
            f"tier={tier}, target={target:.1f}%"
        )

        return target

    def calculate(
        self,
        confidence: float,
        signal_direction: Literal["bullish", "bearish", "neutral"],
        current_exposure_pct: float,
    ) -> PositionSizingResult:
        """Calculate position sizing with action recommendation.

        Args:
            confidence: Model confidence (0.0 to 1.0).
            signal_direction: Overall signal direction.
            current_exposure_pct: Current BTC exposure percentage.

        Returns:
            PositionSizingResult with target, delta, and action.
        """
        target = self.calculate_target_position(confidence, signal_direction, current_exposure_pct)
        delta = target - current_exposure_pct

        # Determine action
        if abs(delta) < self.config.min_trade_delta_pct:
            action: Literal["BUY", "SELL", "HOLD"] = "HOLD"
            should_trade = False
            rationale = (
                f"Position delta ({delta:+.1f}%) below threshold "
                f"({self.config.min_trade_delta_pct}%). Holding current position."
            )
        elif delta > 0:
            action = "BUY"
            should_trade = True
            rationale = (
                f"Target position {target:.1f}% > current {current_exposure_pct:.1f}%. "
                f"Buy {delta:.1f}% to reach target."
            )
        else:
            action = "SELL"
            should_trade = True
            rationale = (
                f"Target position {target:.1f}% < current {current_exposure_pct:.1f}%. "
                f"Sell {abs(delta):.1f}% to reach target."
            )

        logger.info(
            f"Position sizing: target={target:.1f}%, current={current_exposure_pct:.1f}%, "
            f"delta={delta:+.1f}%, action={action}, trade={should_trade}"
        )

        return PositionSizingResult(
            target_position_pct=target,
            current_position_pct=current_exposure_pct,
            delta_pct=delta,
            action=action,
            should_trade=should_trade,
            rationale=rationale,
        )


# Module-level default instance
_default_sizer: PositionSizer | None = None


def get_position_sizer() -> PositionSizer:
    """Get default position sizer instance."""
    global _default_sizer
    if _default_sizer is None:
        _default_sizer = PositionSizer()
    return _default_sizer


def set_position_sizer(sizer: PositionSizer | None) -> None:
    """Set default position sizer instance."""
    global _default_sizer
    _default_sizer = sizer
