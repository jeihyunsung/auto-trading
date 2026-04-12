"""Event dispatcher with cooldown and batching for cost optimization."""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from trading.events.models import EventBatch, TriggerEvent
from trading.triggers.conditions import BatchConfig, CooldownConfig

logger = logging.getLogger(__name__)


class EventDispatcher:
    """Dispatches trigger events to LLM with cooldown and batching.

    This is the key cost optimization layer:
    - Batches events over a configurable window
    - Enforces cooldown between LLM calls
    - Prioritizes high-severity events

    Attributes:
        cooldown: Cooldown configuration.
        batch: Batch configuration.
    """

    def __init__(
        self,
        on_dispatch: Callable[[EventBatch], Awaitable[None]],
        cooldown_config: CooldownConfig | None = None,
        batch_config: BatchConfig | None = None,
    ):
        """Initialize event dispatcher.

        Args:
            on_dispatch: Async callback when batch is ready for LLM.
            cooldown_config: Cooldown settings.
            batch_config: Batching settings.
        """
        self.on_dispatch = on_dispatch
        self.cooldown = cooldown_config or CooldownConfig()
        self.batch = batch_config or BatchConfig()

        # Per-symbol event buffers
        self._buffers: dict[str, list[TriggerEvent]] = defaultdict(list)
        self._buffer_start: dict[str, datetime] = {}

        # Cooldown state
        self._last_dispatch: dict[str, datetime] = {}
        self._last_trigger_types: dict[str, str] = {}

        # Background tasks for batch timers
        self._batch_tasks: dict[str, asyncio.Task] = {}

        # Statistics
        self._stats = {
            "events_submitted": 0,
            "events_dispatched": 0,
            "events_skipped_cooldown": 0,
            "batches_dispatched": 0,
            "immediate_dispatches": 0,
        }

    @property
    def stats(self) -> dict:
        """Get dispatcher statistics."""
        return self._stats.copy()

    async def submit(self, event: TriggerEvent) -> None:
        """Submit a trigger event for batching and dispatch.

        Args:
            event: Trigger event to process.
        """
        self._stats["events_submitted"] += 1
        symbol = event.symbol

        # Check for immediate dispatch (high severity bypasses batching)
        if event.severity == self.batch.immediate_trigger_severity:
            if self._can_dispatch(symbol, event):
                await self._dispatch_immediate(event)
                return
            else:
                logger.debug(f"High severity event skipped due to cooldown: {symbol}")
                self._stats["events_skipped_cooldown"] += 1
                return

        # Add to buffer
        if symbol not in self._buffer_start:
            self._buffer_start[symbol] = datetime.now()
            self._start_batch_timer(symbol)

        self._buffers[symbol].append(event)

        # Force dispatch if buffer is full
        if len(self._buffers[symbol]) >= self.batch.max_events_before_force:
            await self._flush_buffer(symbol)

    def _can_dispatch(self, symbol: str, event: TriggerEvent) -> bool:
        """Check if dispatch is allowed (cooldown check).

        Args:
            symbol: Trading pair.
            event: Event to check.

        Returns:
            True if dispatch is allowed.
        """
        last = self._last_dispatch.get(symbol)
        if last is None:
            return True

        # Calculate effective cooldown
        cooldown = self.cooldown.min_interval_seconds

        # Increase cooldown for repeated same-type triggers
        last_type = self._last_trigger_types.get(symbol)
        if last_type == event.trigger_type.value:
            cooldown *= self.cooldown.repeat_trigger_multiplier

        cooldown = min(cooldown, self.cooldown.max_cooldown_seconds)

        elapsed = (datetime.now() - last).total_seconds()
        return elapsed >= cooldown

    async def _dispatch_immediate(self, event: TriggerEvent) -> None:
        """Dispatch a single high-priority event immediately.

        Args:
            event: High-severity trigger event.
        """
        self._stats["immediate_dispatches"] += 1
        batch = EventBatch(
            events=[event],
            window_start=event.timestamp,
            window_end=datetime.now(),
            symbol=event.symbol,
        )
        await self._do_dispatch(batch)

    def _start_batch_timer(self, symbol: str) -> None:
        """Start a timer to flush the batch after the window.

        Args:
            symbol: Trading pair to start timer for.
        """
        if symbol in self._batch_tasks and not self._batch_tasks[symbol].done():
            return

        async def timer():
            await asyncio.sleep(self.batch.batch_window_seconds)
            await self._flush_buffer(symbol)

        self._batch_tasks[symbol] = asyncio.create_task(timer())

    async def _flush_buffer(self, symbol: str) -> None:
        """Flush the event buffer and dispatch if conditions are met.

        Args:
            symbol: Trading pair to flush buffer for.
        """
        # Cancel any pending timer
        if symbol in self._batch_tasks:
            task = self._batch_tasks.pop(symbol)
            if not task.done():
                task.cancel()

        events = self._buffers.pop(symbol, [])
        start = self._buffer_start.pop(symbol, datetime.now())

        if not events:
            return

        if len(events) < self.batch.min_events_to_trigger:
            logger.debug(
                f"Batch discarded: only {len(events)} events "
                f"(min: {self.batch.min_events_to_trigger})"
            )
            return

        # Check cooldown before dispatching
        highest_event = max(
            events, key=lambda e: {"high": 3, "medium": 2, "low": 1}.get(e.severity, 0)
        )
        if not self._can_dispatch(symbol, highest_event):
            logger.debug(f"Batch skipped due to cooldown for {symbol}")
            self._stats["events_skipped_cooldown"] += len(events)
            return

        batch = EventBatch(
            events=events,
            window_start=start,
            window_end=datetime.now(),
            symbol=symbol,
        )
        await self._do_dispatch(batch)

    async def _do_dispatch(self, batch: EventBatch) -> None:
        """Execute the dispatch callback.

        Args:
            batch: Event batch to dispatch.
        """
        try:
            logger.info(
                f"Dispatching batch: {len(batch.events)} events, "
                f"severity={batch.highest_severity}, symbol={batch.symbol}, "
                f"types={batch.trigger_types}"
            )

            # Update state
            self._last_dispatch[batch.symbol] = datetime.now()
            if batch.events:
                self._last_trigger_types[batch.symbol] = batch.events[0].trigger_type.value

            # Update stats
            self._stats["batches_dispatched"] += 1
            self._stats["events_dispatched"] += len(batch.events)

            # Call the handler
            await self.on_dispatch(batch)

        except Exception as e:
            logger.error(f"Dispatch callback failed: {e}")

    def set_post_trade_cooldown(self, symbol: str) -> None:
        """Set extended cooldown after trade execution.

        Call this after a trade is executed to prevent
        over-trading in volatile conditions.

        Args:
            symbol: Trading pair that was traded.
        """
        # Set last dispatch to a future-adjusted time to extend cooldown
        extra_cooldown = (
            self.cooldown.post_trade_cooldown_seconds
            - self.cooldown.min_interval_seconds
        )
        self._last_dispatch[symbol] = datetime.now() + timedelta(seconds=extra_cooldown)
        logger.info(
            f"Post-trade cooldown set for {symbol}: "
            f"{self.cooldown.post_trade_cooldown_seconds}s"
        )

    def get_cooldown_remaining(self, symbol: str) -> float:
        """Get remaining cooldown time for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            Seconds remaining in cooldown, or 0 if ready.
        """
        last = self._last_dispatch.get(symbol)
        if last is None:
            return 0.0

        elapsed = (datetime.now() - last).total_seconds()
        remaining = self.cooldown.min_interval_seconds - elapsed
        return max(0.0, remaining)

    def reset(self, symbol: str | None = None) -> None:
        """Reset dispatcher state.

        Args:
            symbol: Reset only this symbol. If None, reset all.
        """
        if symbol is None:
            self._buffers.clear()
            self._buffer_start.clear()
            self._last_dispatch.clear()
            self._last_trigger_types.clear()
            for task in self._batch_tasks.values():
                task.cancel()
            self._batch_tasks.clear()
        else:
            self._buffers.pop(symbol, None)
            self._buffer_start.pop(symbol, None)
            self._last_dispatch.pop(symbol, None)
            self._last_trigger_types.pop(symbol, None)
            if symbol in self._batch_tasks:
                self._batch_tasks[symbol].cancel()
                del self._batch_tasks[symbol]
