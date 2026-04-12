"""Abstract broker adapter interface."""

from abc import ABC, abstractmethod
from decimal import Decimal

from trading.core.models import MarketSnapshot, OrderRequest, OrderResult, OHLCV


class BrokerAdapter(ABC):
    """Abstract base class for broker adapters."""

    @abstractmethod
    def get_balance(self, currency: str) -> Decimal:
        """Get balance for a specific currency.

        Args:
            currency: Currency code (e.g., 'KRW', 'BTC').

        Returns:
            Available balance.
        """
        ...

    @abstractmethod
    def get_all_balances(self) -> dict[str, Decimal]:
        """Get all balances.

        Returns:
            Dictionary mapping currency to balance.
        """
        ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol.

        Args:
            symbol: Trading pair (e.g., 'KRW-BTC').

        Returns:
            Current price.
        """
        ...

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "minute1",
        count: int = 200,
    ) -> list[OHLCV]:
        """Get OHLCV candle data.

        Args:
            symbol: Trading pair.
            interval: Candle interval (minute1, minute5, day, etc.).
            count: Number of candles.

        Returns:
            List of OHLCV candles.
        """
        ...

    @abstractmethod
    def get_orderbook(self, symbol: str) -> dict:
        """Get orderbook for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            Orderbook data with bids and asks.
        """
        ...

    @abstractmethod
    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        """Get complete market snapshot.

        Args:
            symbol: Trading pair.

        Returns:
            MarketSnapshot with current state.
        """
        ...

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order.

        Args:
            request: Order request details.

        Returns:
            Order result with status.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: ID of order to cancel.

        Returns:
            True if cancelled successfully.
        """
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResult:
        """Get status of an order.

        Args:
            order_id: Order ID.

        Returns:
            Current order status.
        """
        ...
