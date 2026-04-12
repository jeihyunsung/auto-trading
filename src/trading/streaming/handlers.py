"""WebSocket message handlers for different event types."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from trading.events.models import EventType, MarketEvent

logger = logging.getLogger(__name__)


class MessageHandler(Protocol):
    """Protocol for message handlers."""

    def handle(self, message: dict) -> MarketEvent | None:
        """Handle incoming WebSocket message.

        Args:
            message: Raw WebSocket message dict.

        Returns:
            MarketEvent if successfully parsed, else None.
        """
        ...


@dataclass
class TickerState:
    """Cached ticker state for change detection.

    Attributes:
        price: Last known price.
        volume_24h: 24h trading volume.
        change_rate: 24h change rate.
        timestamp: State timestamp.
    """

    price: float
    volume_24h: float
    change_rate: float
    timestamp: datetime


class TickerHandler:
    """Handler for ticker (price) messages from Upbit WebSocket.

    Parses real-time ticker data and creates MarketEvents.
    """

    def __init__(self):
        """Initialize ticker handler with state cache."""
        self._state_cache: dict[str, TickerState] = {}

    def handle(self, message: dict) -> MarketEvent | None:
        """Process ticker message and create MarketEvent.

        Args:
            message: Raw WebSocket ticker message.

        Returns:
            MarketEvent with price data, or None on parse failure.
        """
        try:
            symbol = message.get("code", "")
            if not symbol:
                return None

            price = float(message.get("trade_price", 0))
            volume = float(message.get("acc_trade_volume_24h", 0))
            # Upbit returns change rate as decimal (e.g., 0.05 for 5%)
            change_rate = float(message.get("signed_change_rate", 0)) * 100

            # Get previous state for change detection
            prev_state = self._state_cache.get(symbol)
            prev_price = prev_state.price if prev_state else None

            # Update cache
            now = datetime.now()
            new_state = TickerState(
                price=price,
                volume_24h=volume,
                change_rate=change_rate,
                timestamp=now,
            )
            self._state_cache[symbol] = new_state

            return MarketEvent(
                event_type=EventType.PRICE_UPDATE,
                symbol=symbol,
                price=price,
                prev_price=prev_price,
                volume=volume,
                change_rate=change_rate,
                timestamp=now,
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse ticker message: {e}")
            return None

    def get_cached_price(self, symbol: str) -> float | None:
        """Get last known price for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            Last price or None if not cached.
        """
        state = self._state_cache.get(symbol)
        return state.price if state else None


class TradeHandler:
    """Handler for trade (transaction) messages from Upbit WebSocket.

    Tracks individual trades for volume analysis.
    """

    def __init__(self):
        """Initialize trade handler."""
        pass

    def handle(self, message: dict) -> MarketEvent | None:
        """Process trade message and create MarketEvent.

        Args:
            message: Raw WebSocket trade message.

        Returns:
            MarketEvent with trade data, or None on parse failure.
        """
        try:
            symbol = message.get("code", "")
            if not symbol:
                return None

            price = float(message.get("trade_price", 0))
            volume = float(message.get("trade_volume", 0))

            return MarketEvent(
                event_type=EventType.TRADE,
                symbol=symbol,
                price=price,
                trade_volume=volume,
                timestamp=datetime.now(),
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse trade message: {e}")
            return None


class OrderbookHandler:
    """Handler for orderbook messages from Upbit WebSocket.

    Tracks bid/ask spread for liquidity analysis.
    """

    def __init__(self):
        """Initialize orderbook handler."""
        pass

    def handle(self, message: dict) -> MarketEvent | None:
        """Process orderbook message and create MarketEvent.

        Args:
            message: Raw WebSocket orderbook message.

        Returns:
            MarketEvent with orderbook data, or None on parse failure.
        """
        try:
            symbol = message.get("code", "")
            if not symbol:
                return None

            units = message.get("orderbook_units", [])
            if not units:
                return None

            # Get best bid/ask from first unit
            best_bid = float(units[0].get("bid_price", 0))
            best_ask = float(units[0].get("ask_price", 0))

            # Calculate spread percentage
            spread_pct = 0.0
            if best_bid > 0:
                spread_pct = ((best_ask - best_bid) / best_bid) * 100

            return MarketEvent(
                event_type=EventType.ORDERBOOK,
                symbol=symbol,
                bid_price=best_bid,
                ask_price=best_ask,
                spread_pct=spread_pct,
                timestamp=datetime.now(),
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse orderbook message: {e}")
            return None


class MessageRouter:
    """Routes WebSocket messages to appropriate handlers.

    Centralizes message routing logic for the streaming system.
    """

    def __init__(self):
        """Initialize message router with all handlers."""
        self.ticker_handler = TickerHandler()
        self.trade_handler = TradeHandler()
        self.orderbook_handler = OrderbookHandler()

        self._handlers = {
            "ticker": self.ticker_handler,
            "trade": self.trade_handler,
            "orderbook": self.orderbook_handler,
        }

    def route(self, message: dict) -> MarketEvent | None:
        """Route message to appropriate handler.

        Args:
            message: Raw WebSocket message with _stream_type field.

        Returns:
            MarketEvent from handler, or None if no handler matches.
        """
        stream_type = message.get("_stream_type", "")
        handler = self._handlers.get(stream_type)

        if handler is None:
            # Try to infer from message content
            if "trade_price" in message and "trade_volume" in message:
                handler = self.trade_handler
            elif "orderbook_units" in message:
                handler = self.orderbook_handler
            elif "trade_price" in message:
                handler = self.ticker_handler

        if handler:
            return handler.handle(message)

        return None
