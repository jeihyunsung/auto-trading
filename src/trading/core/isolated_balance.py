"""Isolated balance tracking for independent bot operation.

This module provides balance tracking that is isolated from the user's
existing holdings, allowing the bot to operate with a dedicated budget.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class IsolatedBalance:
    """Isolated balance state for bot operation.

    Attributes:
        krw: Available KRW balance for the bot.
        btc: BTC balance acquired by the bot.
        initial_capital: Starting capital in KRW.
        total_invested: Total KRW invested in BTC.
        total_fees: Total fees paid.
        created_at: When isolated tracking started.
        last_updated: Last update timestamp.
    """

    krw: Decimal
    btc: Decimal
    initial_capital: Decimal
    total_invested: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "krw": str(self.krw),
            "btc": str(self.btc),
            "initial_capital": str(self.initial_capital),
            "total_invested": str(self.total_invested),
            "total_fees": str(self.total_fees),
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IsolatedBalance":
        """Create from dictionary."""
        return cls(
            krw=Decimal(data["krw"]),
            btc=Decimal(data["btc"]),
            initial_capital=Decimal(data["initial_capital"]),
            total_invested=Decimal(data.get("total_invested", "0")),
            total_fees=Decimal(data.get("total_fees", "0")),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_updated=data.get("last_updated", datetime.now().isoformat()),
        )


class IsolatedBalanceTracker:
    """Tracks bot's isolated balance separate from exchange account.

    This allows the bot to operate with a dedicated budget without
    being affected by existing holdings on the exchange.
    """

    def __init__(
        self,
        initial_capital_krw: float | None = None,
        state_file: Path | None = None,
    ):
        """Initialize isolated balance tracker.

        Args:
            initial_capital_krw: Starting capital (uses config if None).
            state_file: File to persist state (uses default if None).
        """
        settings = get_settings()
        self._initial_capital = Decimal(
            str(initial_capital_krw or settings.isolated_capital_krw)
        )
        self._state_file = state_file or settings.log_dir / "isolated_balance.json"
        self._balance: IsolatedBalance | None = None

        # Load or create initial state
        self._load_or_create()

    def _load_or_create(self) -> None:
        """Load existing state or create new one."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                self._balance = IsolatedBalance.from_dict(data)
                logger.info(
                    f"Loaded isolated balance: KRW={self._balance.krw:,.0f}, "
                    f"BTC={self._balance.btc:.8f}"
                )
                return
            except Exception as e:
                logger.warning(f"Failed to load isolated balance: {e}")

        # Create new state
        self._balance = IsolatedBalance(
            krw=self._initial_capital,
            btc=Decimal("0"),
            initial_capital=self._initial_capital,
        )
        self._save()
        logger.info(f"Created new isolated balance with {self._initial_capital:,.0f} KRW")

    def _save(self) -> None:
        """Persist state to file."""
        if self._balance is None:
            return

        self._balance.last_updated = datetime.now().isoformat()
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self._state_file, "w") as f:
            json.dump(self._balance.to_dict(), f, indent=2)

    @property
    def balance(self) -> IsolatedBalance:
        """Get current balance state."""
        if self._balance is None:
            self._load_or_create()
        return self._balance  # type: ignore

    def get_balances(self) -> dict[str, Decimal]:
        """Get balances in broker-compatible format.

        Returns:
            Dict with KRW and BTC balances.
        """
        return {
            "KRW": self.balance.krw,
            "BTC": self.balance.btc,
        }

    def get_krw_balance(self) -> Decimal:
        """Get available KRW balance."""
        return self.balance.krw

    def get_btc_balance(self) -> Decimal:
        """Get BTC balance."""
        return self.balance.btc

    def record_buy(
        self,
        krw_spent: Decimal,
        btc_received: Decimal,
        fee_krw: Decimal,
    ) -> bool:
        """Record a BUY transaction.

        Args:
            krw_spent: KRW amount spent (before fees).
            btc_received: BTC amount received.
            fee_krw: Fee paid in KRW.

        Returns:
            True if recorded successfully, False if insufficient balance.
        """
        total_cost = krw_spent + fee_krw

        if total_cost > self.balance.krw:
            logger.warning(
                f"Insufficient isolated KRW: {self.balance.krw:,.0f} < {total_cost:,.0f}"
            )
            return False

        self._balance.krw -= total_cost
        self._balance.btc += btc_received
        self._balance.total_invested += krw_spent
        self._balance.total_fees += fee_krw
        self._save()

        logger.info(
            f"Isolated BUY: -{krw_spent:,.0f} KRW, +{btc_received:.8f} BTC, "
            f"fee={fee_krw:,.0f} KRW"
        )
        return True

    def record_sell(
        self,
        btc_sold: Decimal,
        krw_received: Decimal,
        fee_krw: Decimal,
    ) -> bool:
        """Record a SELL transaction.

        Args:
            btc_sold: BTC amount sold.
            krw_received: KRW amount received (after fees).
            fee_krw: Fee paid in KRW.

        Returns:
            True if recorded successfully, False if insufficient balance.
        """
        if btc_sold > self.balance.btc:
            logger.warning(
                f"Insufficient isolated BTC: {self.balance.btc:.8f} < {btc_sold:.8f}"
            )
            return False

        # Reduce total_invested proportionally to BTC sold
        # This maintains correct average cost basis for remaining BTC
        if self._balance.btc > 0 and self._balance.total_invested > 0:
            sell_ratio = btc_sold / self._balance.btc
            invested_reduction = self._balance.total_invested * sell_ratio
            self._balance.total_invested -= invested_reduction

        self._balance.btc -= btc_sold
        self._balance.krw += krw_received
        self._balance.total_fees += fee_krw
        self._save()

        logger.info(
            f"Isolated SELL: -{btc_sold:.8f} BTC, +{krw_received:,.0f} KRW, "
            f"fee={fee_krw:,.0f} KRW"
        )
        return True

    def get_portfolio_value(self, btc_price: float) -> dict:
        """Calculate current portfolio value.

        Args:
            btc_price: Current BTC price in KRW.

        Returns:
            Dict with portfolio metrics.
        """
        btc_value = float(self.balance.btc) * btc_price
        total_value = float(self.balance.krw) + btc_value
        initial = float(self.balance.initial_capital)
        total_invested = float(self.balance.total_invested)

        # Unrealized P&L: BTC position only (current value vs invested amount)
        # This measures gain/loss on the BTC you hold, not including cash
        if total_invested > 0 and self.balance.btc > 0:
            unrealized_pnl_pct = ((btc_value / total_invested) - 1) * 100
        else:
            unrealized_pnl_pct = 0.0

        return {
            "krw_balance": float(self.balance.krw),
            "btc_balance": float(self.balance.btc),
            "btc_value_krw": btc_value,
            "total_value_krw": total_value,
            "initial_capital_krw": initial,
            "total_invested_krw": total_invested,
            "pnl_krw": total_value - initial,
            "pnl_pct": ((total_value / initial) - 1) * 100 if initial > 0 else 0,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "exposure_pct": (btc_value / total_value * 100) if total_value > 0 else 0,
            "total_fees_krw": float(self.balance.total_fees),
        }

    def reset(self, new_capital: Decimal | None = None) -> None:
        """Reset to initial state.

        Args:
            new_capital: New initial capital (uses current if None).
        """
        capital = new_capital or self._initial_capital
        self._balance = IsolatedBalance(
            krw=capital,
            btc=Decimal("0"),
            initial_capital=capital,
        )
        self._save()
        logger.info(f"Isolated balance reset to {capital:,.0f} KRW")

    def adjust_capital(self, target_capital: float) -> None:
        """Adjust capital to target amount while preserving current holdings.

        Args:
            target_capital: Target initial capital in KRW.
        """
        target = Decimal(str(target_capital))
        current = self._balance.initial_capital
        diff = target - current

        if diff == 0:
            return

        # Adjust KRW balance by the difference
        new_krw = self._balance.krw + diff
        if new_krw < 0:
            logger.warning(
                f"Cannot reduce capital by {-diff:,.0f} KRW. "
                f"Current KRW balance is only {self._balance.krw:,.0f}"
            )
            return

        self._balance.krw = new_krw
        self._balance.initial_capital = target
        self._save()

        action = "Added" if diff > 0 else "Reduced"
        logger.info(
            f"{action} {abs(diff):,.0f} KRW capital. "
            f"New initial_capital={self._balance.initial_capital:,.0f}, "
            f"KRW={self._balance.krw:,.0f}"
        )

    def get_stats(self) -> dict:
        """Get statistics summary.

        Returns:
            Dict with balance statistics.
        """
        return {
            "krw": float(self.balance.krw),
            "btc": float(self.balance.btc),
            "initial_capital": float(self.balance.initial_capital),
            "total_invested": float(self.balance.total_invested),
            "total_fees": float(self.balance.total_fees),
            "created_at": self.balance.created_at,
            "last_updated": self.balance.last_updated,
        }


# Module-level singleton
_isolated_tracker: IsolatedBalanceTracker | None = None


def get_isolated_tracker() -> IsolatedBalanceTracker | None:
    """Get global isolated tracker instance.

    Returns:
        IsolatedBalanceTracker if isolated mode enabled, None otherwise.
    """
    return _isolated_tracker


def set_isolated_tracker(tracker: IsolatedBalanceTracker | None) -> None:
    """Set global isolated tracker instance.

    Args:
        tracker: Tracker instance or None to disable.
    """
    global _isolated_tracker
    _isolated_tracker = tracker


def init_isolated_tracker_if_enabled() -> IsolatedBalanceTracker | None:
    """Initialize isolated tracker if isolated mode is enabled in settings.

    Returns:
        IsolatedBalanceTracker if enabled, None otherwise.
    """
    settings = get_settings()
    if not settings.isolated_mode:
        return None

    tracker = IsolatedBalanceTracker(
        initial_capital_krw=settings.isolated_capital_krw
    )
    set_isolated_tracker(tracker)
    return tracker
