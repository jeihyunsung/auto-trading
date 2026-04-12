"""Isolated mode balance tracker.

Tracks bot's own BTC holdings separately from user's existing positions.
This allows the bot to trade with limited capital without affecting
pre-existing holdings.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("data/isolated_state.json")


@dataclass
class IsolatedState:
    """State for isolated trading mode.

    Attributes:
        bot_btc_balance: BTC that the bot has purchased (can sell).
        krw_spent: Total KRW spent on purchases.
        krw_received: Total KRW received from sales.
        capital_limit: Maximum KRW the bot can use.
        trades: List of trade records.
        created_at: When isolated mode was started.
        updated_at: Last update timestamp.
    """

    bot_btc_balance: Decimal = Decimal("0")
    krw_spent: Decimal = Decimal("0")
    krw_received: Decimal = Decimal("0")
    capital_limit: Decimal = Decimal("10000")
    trades: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        """Initialize timestamps if not set."""
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def available_krw(self) -> Decimal:
        """KRW available for new purchases.

        Returns:
            Available capital (limit - spent + received).
        """
        return self.capital_limit - self.krw_spent + self.krw_received

    @property
    def net_pnl(self) -> Decimal:
        """Net profit/loss in KRW (excluding current BTC value).

        Returns:
            Net realized PnL.
        """
        return self.krw_received - self.krw_spent

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "bot_btc_balance": str(self.bot_btc_balance),
            "krw_spent": str(self.krw_spent),
            "krw_received": str(self.krw_received),
            "capital_limit": str(self.capital_limit),
            "trades": self.trades,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IsolatedState":
        """Create from dictionary.

        Args:
            data: Dictionary from JSON.

        Returns:
            IsolatedState instance.
        """
        return cls(
            bot_btc_balance=Decimal(data.get("bot_btc_balance", "0")),
            krw_spent=Decimal(data.get("krw_spent", "0")),
            krw_received=Decimal(data.get("krw_received", "0")),
            capital_limit=Decimal(data.get("capital_limit", "10000")),
            trades=data.get("trades", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class IsolatedTracker:
    """Tracks bot's own holdings in isolated mode.

    This class maintains a separate ledger of BTC that the bot
    has purchased, allowing it to only sell its own holdings
    while protecting user's pre-existing positions.

    Attributes:
        state_file: Path to state persistence file.
        state: Current isolated state.
    """

    def __init__(
        self,
        capital_limit: float = 10000.0,
        state_file: Path | None = None,
    ):
        """Initialize isolated tracker.

        Args:
            capital_limit: Maximum KRW to use.
            state_file: Path to state file. Uses default if None.
        """
        self.state_file = state_file or DEFAULT_STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing state or create new
        if self.state_file.exists():
            self.state = self._load_state()
            # Update capital limit if changed
            self.state.capital_limit = Decimal(str(capital_limit))
            logger.info(
                f"Loaded isolated state: BTC={self.state.bot_btc_balance}, "
                f"available={self.state.available_krw} KRW"
            )
        else:
            self.state = IsolatedState(
                capital_limit=Decimal(str(capital_limit))
            )
            self._save_state()
            logger.info(f"Created new isolated state with {capital_limit} KRW limit")

    def _load_state(self) -> IsolatedState:
        """Load state from file.

        Returns:
            Loaded state.
        """
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            return IsolatedState.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load isolated state: {e}. Creating new.")
            return IsolatedState()

    def _save_state(self) -> None:
        """Save state to file."""
        self.state.updated_at = datetime.now().isoformat()
        with open(self.state_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)

    def record_buy(
        self,
        btc_quantity: Decimal,
        krw_amount: Decimal,
        price: Decimal,
        order_id: str = "",
    ) -> bool:
        """Record a BTC purchase.

        Args:
            btc_quantity: Amount of BTC purchased.
            krw_amount: KRW spent (including fees).
            price: Execution price.
            order_id: Order ID for reference.

        Returns:
            True if recorded successfully, False if exceeds limit.
        """
        if krw_amount > self.state.available_krw:
            logger.warning(
                f"Buy rejected: {krw_amount} KRW exceeds available "
                f"{self.state.available_krw} KRW"
            )
            return False

        self.state.bot_btc_balance += btc_quantity
        self.state.krw_spent += krw_amount
        self.state.trades.append({
            "type": "BUY",
            "btc": str(btc_quantity),
            "krw": str(krw_amount),
            "price": str(price),
            "order_id": order_id,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_state()

        logger.info(
            f"Recorded BUY: {btc_quantity} BTC for {krw_amount} KRW. "
            f"Bot balance: {self.state.bot_btc_balance} BTC"
        )
        return True

    def record_sell(
        self,
        btc_quantity: Decimal,
        krw_amount: Decimal,
        price: Decimal,
        order_id: str = "",
    ) -> bool:
        """Record a BTC sale.

        Args:
            btc_quantity: Amount of BTC sold.
            krw_amount: KRW received (after fees).
            price: Execution price.
            order_id: Order ID for reference.

        Returns:
            True if recorded successfully, False if exceeds balance.
        """
        if btc_quantity > self.state.bot_btc_balance:
            logger.warning(
                f"Sell rejected: {btc_quantity} BTC exceeds bot balance "
                f"{self.state.bot_btc_balance} BTC"
            )
            return False

        self.state.bot_btc_balance -= btc_quantity
        self.state.krw_received += krw_amount
        self.state.trades.append({
            "type": "SELL",
            "btc": str(btc_quantity),
            "krw": str(krw_amount),
            "price": str(price),
            "order_id": order_id,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_state()

        logger.info(
            f"Recorded SELL: {btc_quantity} BTC for {krw_amount} KRW. "
            f"Bot balance: {self.state.bot_btc_balance} BTC"
        )
        return True

    def get_available_krw(self) -> Decimal:
        """Get KRW available for purchases.

        Returns:
            Available KRW within capital limit.
        """
        return self.state.available_krw

    def get_sellable_btc(self) -> Decimal:
        """Get BTC that bot can sell (its own holdings only).

        Returns:
            Bot's own BTC balance.
        """
        return self.state.bot_btc_balance

    def get_summary(self) -> dict:
        """Get summary of isolated trading state.

        Returns:
            Dictionary with key metrics.
        """
        return {
            "capital_limit": float(self.state.capital_limit),
            "available_krw": float(self.state.available_krw),
            "bot_btc_balance": float(self.state.bot_btc_balance),
            "krw_spent": float(self.state.krw_spent),
            "krw_received": float(self.state.krw_received),
            "net_pnl": float(self.state.net_pnl),
            "trade_count": len(self.state.trades),
        }

    def get_pnl_with_price(self, current_price: float) -> dict:
        """Calculate PnL based on current market price.

        Args:
            current_price: Current BTC price in KRW.

        Returns:
            Dictionary with PnL metrics:
            - invested_krw: Total KRW invested (spent on buys)
            - current_value_krw: Current total value (BTC value + received from sells)
            - btc_value_krw: Current BTC holdings value
            - bot_btc_balance: BTC quantity held
            - total_pnl_krw: Total profit/loss in KRW
            - total_return_pct: Total return percentage
        """
        btc_balance = float(self.state.bot_btc_balance)
        krw_spent = float(self.state.krw_spent)
        krw_received = float(self.state.krw_received)

        # Current BTC value at market price
        btc_value = btc_balance * current_price

        # Total current value = unrealized (BTC) + realized (sold proceeds)
        current_value = btc_value + krw_received

        # Total PnL
        total_pnl = current_value - krw_spent

        # Return percentage (avoid division by zero)
        if krw_spent > 0:
            total_return_pct = ((current_value / krw_spent) - 1) * 100
        else:
            total_return_pct = 0.0

        return {
            "invested_krw": krw_spent,
            "current_value_krw": current_value,
            "btc_value_krw": btc_value,
            "bot_btc_balance": btc_balance,
            "total_pnl_krw": total_pnl,
            "total_return_pct": total_return_pct,
            "trade_count": len(self.state.trades),
        }

    def reset(self) -> None:
        """Reset isolated state (for testing).

        Warning: This deletes all trade history!
        """
        self.state = IsolatedState(capital_limit=self.state.capital_limit)
        self._save_state()
        logger.warning("Isolated state has been reset!")


# Global tracker instance (lazy loaded)
_tracker: IsolatedTracker | None = None


def get_isolated_tracker(
    capital_limit: float = 10000.0,
    enabled: bool = True,
) -> IsolatedTracker | None:
    """Get isolated tracker instance (singleton).

    Args:
        capital_limit: Maximum KRW to use.
        enabled: Whether isolated mode is enabled.

    Returns:
        IsolatedTracker instance if enabled, None otherwise.
    """
    global _tracker
    if not enabled:
        return None
    if _tracker is None:
        _tracker = IsolatedTracker(capital_limit=capital_limit)
    return _tracker


def reset_isolated_tracker() -> None:
    """Reset the global tracker instance."""
    global _tracker
    _tracker = None
