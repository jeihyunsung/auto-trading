"""Upbit WebSocket connection manager with reconnection logic."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class StreamType(str, Enum):
    """Upbit WebSocket stream types."""

    TICKER = "ticker"
    ORDERBOOK = "orderbook"
    TRADE = "trade"


@dataclass
class StreamConfig:
    """Configuration for a WebSocket stream.

    Attributes:
        stream_type: Type of data to stream.
        symbols: Trading pairs to subscribe (e.g., ["KRW-BTC"]).
        reconnect_delay: Initial reconnect delay in seconds.
        max_reconnect_attempts: Maximum reconnection attempts.
    """

    stream_type: StreamType
    symbols: list[str]
    reconnect_delay: float = 5.0
    max_reconnect_attempts: int = 10


@dataclass
class StreamStats:
    """Statistics for streaming connection.

    Attributes:
        messages_received: Total messages received.
        reconnect_count: Number of reconnections.
        last_message_time: Timestamp of last message.
        errors: List of recent errors.
    """

    messages_received: int = 0
    reconnect_count: int = 0
    last_message_time: float | None = None
    errors: list[str] = field(default_factory=list)


class UpbitStreamManager:
    """Manages Upbit WebSocket connections with auto-reconnect.

    Uses websockets library directly for async support,
    as pyupbit's WebSocketManager is blocking.
    """

    UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"

    def __init__(
        self,
        configs: list[StreamConfig],
        on_message: Callable[[dict], None],
        on_error: Callable[[Exception], None] | None = None,
    ):
        """Initialize WebSocket manager.

        Args:
            configs: List of stream configurations.
            on_message: Async callback for incoming messages.
            on_error: Optional error callback.
        """
        self.configs = configs
        self.on_message = on_message
        self.on_error = on_error or self._default_error_handler

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._stats: dict[StreamType, StreamStats] = {
            config.stream_type: StreamStats() for config in configs
        }

    @property
    def stats(self) -> dict[StreamType, StreamStats]:
        """Get connection statistics."""
        return self._stats

    async def start(self) -> None:
        """Start all WebSocket connections."""
        self._running = True
        logger.info("Starting Upbit WebSocket streams...")

        for config in self.configs:
            task = asyncio.create_task(
                self._run_stream(config), name=f"stream_{config.stream_type.value}"
            )
            self._tasks.append(task)

        logger.info(f"Started {len(self._tasks)} WebSocket streams")

    async def stop(self) -> None:
        """Stop all WebSocket connections gracefully."""
        logger.info("Stopping WebSocket streams...")
        self._running = False

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        logger.info("WebSocket streams stopped")

    async def _run_stream(self, config: StreamConfig) -> None:
        """Run a single WebSocket stream with reconnection.

        Args:
            config: Stream configuration.
        """
        stats = self._stats[config.stream_type]
        reconnect_delay = config.reconnect_delay

        while self._running:
            try:
                await self._connect_and_listen(config)
                reconnect_delay = config.reconnect_delay  # Reset on success

            except ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                stats.errors.append(f"Connection closed: {e}")

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                stats.errors.append(str(e))
                self.on_error(e)

            if not self._running:
                break

            # Reconnect with exponential backoff
            stats.reconnect_count += 1
            if stats.reconnect_count > config.max_reconnect_attempts:
                logger.error(
                    f"Max reconnect attempts reached for {config.stream_type}"
                )
                break

            delay = min(reconnect_delay, 60.0)
            logger.info(
                f"Reconnecting {config.stream_type} in {delay:.1f}s "
                f"(attempt {stats.reconnect_count})"
            )
            await asyncio.sleep(delay)
            reconnect_delay *= 2  # Exponential backoff

    async def _connect_and_listen(self, config: StreamConfig) -> None:
        """Connect to WebSocket and listen for messages.

        Args:
            config: Stream configuration.
        """
        stats = self._stats[config.stream_type]

        async with websockets.connect(
            self.UPBIT_WS_URL,
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            # Send subscription request
            subscribe_msg = self._build_subscribe_message(config)
            await ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to {config.stream_type}: {config.symbols}")

            # Listen for messages
            async for message in ws:
                if not self._running:
                    break

                try:
                    data = json.loads(message)
                    stats.messages_received += 1
                    stats.last_message_time = asyncio.get_event_loop().time()

                    # Add stream type for handler routing
                    data["_stream_type"] = config.stream_type.value
                    self.on_message(data)

                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse message: {e}")

    def _build_subscribe_message(self, config: StreamConfig) -> list[dict]:
        """Build Upbit WebSocket subscription message.

        Args:
            config: Stream configuration.

        Returns:
            Subscription message list.
        """
        return [
            {"ticket": str(uuid.uuid4())},
            {
                "type": config.stream_type.value,
                "codes": config.symbols,
                "isOnlyRealtime": True,
            },
            {"format": "DEFAULT"},
        ]

    def _default_error_handler(self, error: Exception) -> None:
        """Default error handler."""
        logger.error(f"Stream error: {error}")

    def get_stats_summary(self) -> dict:
        """Get summary of all stream statistics.

        Returns:
            Dict with stats per stream type.
        """
        return {
            stream_type.value: {
                "messages": stats.messages_received,
                "reconnects": stats.reconnect_count,
                "errors": len(stats.errors),
            }
            for stream_type, stats in self._stats.items()
        }
