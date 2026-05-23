"""Async main entry point with event-driven architecture.

This module provides an alternative to the polling-based main.py,
using WebSocket streams and rule-based triggers to minimize LLM costs.
"""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from decimal import Decimal

from trading.adapters.upbit import UpbitBrokerAdapter, get_broker
from trading.agents.decision_agent import set_hysteresis_manager
from trading.config import get_settings
from trading.core.decision_history import DecisionHistoryWriter, set_decision_writer
from trading.core.derivatives_history import DerivativesHistoryWriter, set_derivatives_writer
from trading.core.indicator_history import IndicatorHistoryWriter, set_indicator_writer
from trading.core.isolated_balance import (
    IsolatedBalanceTracker,
    get_isolated_tracker,
    set_isolated_tracker,
)
from trading.core.hysteresis import HysteresisConfig, HysteresisManager
from trading.core.performance import (
    PerformanceConfig,
    PerformanceTracker,
    set_performance_tracker,
)
from trading.core.state import create_initial_state
from trading.events.dispatcher import EventDispatcher
from trading.events.models import EventBatch, MarketEvent
from trading.graph.builder import simple_pipeline
from trading.streaming.connection import StreamConfig, StreamType, UpbitStreamManager
from trading.streaming.handlers import MessageRouter
from trading.triggers.conditions import BatchConfig, CooldownConfig, TriggerThresholds
from trading.triggers.evaluator import TriggerEvaluator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class EventDrivenTradingBot:
    """Event-driven trading bot with two-layer architecture.

    Layer 1: Real-time monitoring via WebSocket (no LLM cost)
    Layer 2: LLM decision-making (only when triggered)

    Attributes:
        symbols: Trading pairs to monitor.
        evaluator: Rule-based trigger evaluator.
        dispatcher: Event batching and cooldown manager.
    """

    def __init__(
        self,
        symbols: list[str],
        thresholds: TriggerThresholds | None = None,
        cooldown: CooldownConfig | None = None,
        batch: BatchConfig | None = None,
        hysteresis_config: HysteresisConfig | None = None,
        performance_tracking: bool = True,
    ):
        """Initialize event-driven trading bot.

        Args:
            symbols: Trading pairs to monitor (e.g., ["KRW-BTC"]).
            thresholds: Trigger thresholds configuration.
            cooldown: Cooldown configuration.
            batch: Batch configuration.
            hysteresis_config: Optional hysteresis configuration. None to disable.
            performance_tracking: Enable performance tracking.
        """
        self.symbols = symbols

        # Layer 1 components
        self.evaluator = TriggerEvaluator(thresholds)
        self.message_router = MessageRouter()

        # Layer 2 dispatcher
        self.dispatcher = EventDispatcher(
            on_dispatch=self._on_batch_ready,
            cooldown_config=cooldown,
            batch_config=batch,
        )

        # Initialize hysteresis manager
        self._hysteresis: HysteresisManager | None = None
        if hysteresis_config is not None:
            self._hysteresis = HysteresisManager(hysteresis_config)

        # Initialize performance tracker
        self._tracker: PerformanceTracker | None = None
        self._performance_tracking = performance_tracking
        self._broker: UpbitBrokerAdapter | None = None

        # WebSocket manager (initialized on start)
        self._stream_manager: UpbitStreamManager | None = None
        self._running = False

        # Statistics
        self._stats = {
            "events_received": 0,
            "triggers_fired": 0,
            "llm_calls": 0,
            "trades_executed": 0,
            "start_time": None,
            "last_llm_call": None,
        }

    @property
    def stats(self) -> dict:
        """Get bot statistics."""
        stats = self._stats.copy()
        if stats["start_time"]:
            stats["uptime_seconds"] = (
                datetime.now() - stats["start_time"]
            ).total_seconds()
        if stats["events_received"] > 0:
            stats["trigger_rate_pct"] = (
                stats["triggers_fired"] / stats["events_received"] * 100
            )
        return stats

    async def start(self) -> None:
        """Start the event-driven trading bot."""
        self._running = True
        self._stats["start_time"] = datetime.now()
        settings = get_settings()

        # Configure global hysteresis manager
        if self._hysteresis is not None:
            set_hysteresis_manager(self._hysteresis)

        # Configure performance tracker
        # Always use shared broker instance
        self._broker = get_broker()

        if self._performance_tracking:
            self._tracker = PerformanceTracker(
                PerformanceConfig(
                    snapshot_interval_minutes=1,
                    log_dir=settings.log_dir,
                )
            )
            set_performance_tracker(self._tracker)

            # Initialize tracker with current portfolio state
            balances = self._broker.get_all_balances()
            krw = float(balances.get("KRW", 0))
            btc = float(balances.get("BTC", 0))
            # Use placeholder price until we get real price from WebSocket
            initial_value = krw + btc * 100_000_000  # Placeholder
            self._tracker.start(initial_value, 100_000_000)

        # Configure history writers for dashboard
        decision_writer = DecisionHistoryWriter(settings.log_dir)
        set_decision_writer(decision_writer)
        indicator_writer = IndicatorHistoryWriter(settings.log_dir)
        set_indicator_writer(indicator_writer)
        derivatives_writer = DerivativesHistoryWriter(settings.log_dir)
        set_derivatives_writer(derivatives_writer)

        logger.info("=" * 60)
        logger.info("Starting Event-Driven Trading Bot")
        logger.info(f"Monitoring symbols: {self.symbols}")
        logger.info(f"Cooldown: {self.dispatcher.cooldown.min_interval_seconds}s")
        logger.info(f"Batch window: {self.dispatcher.batch.batch_window_seconds}s")
        if self._hysteresis:
            logger.info(
                f"Hysteresis: enabled (reversal_delta={self._hysteresis.config.action_reversal_delta})"
            )
        else:
            logger.info("Hysteresis: disabled")
        if self._tracker:
            logger.info("Performance tracking: enabled")
        else:
            logger.info("Performance tracking: disabled")
        # Log isolated mode status
        tracker = get_isolated_tracker()
        if tracker is not None:
            stats = tracker.get_stats()
            logger.info(
                f"Isolated mode: enabled (capital {stats['initial_capital']:,.0f} KRW, "
                f"KRW={stats['krw']:,.0f}, BTC={stats['btc']:.8f})"
            )
        else:
            logger.info("Isolated mode: disabled")
        logger.info("=" * 60)

        # Create WebSocket stream configurations
        configs = [
            StreamConfig(StreamType.TICKER, self.symbols),
            StreamConfig(StreamType.TRADE, self.symbols),
        ]

        # Initialize and start stream manager
        self._stream_manager = UpbitStreamManager(
            configs=configs,
            on_message=self._handle_message,
            on_error=self._handle_error,
        )

        try:
            await self._stream_manager.start()
        except Exception as e:
            logger.error(f"Stream manager failed: {e}")
            raise

    async def stop(self) -> None:
        """Stop the trading bot gracefully."""
        logger.info("Stopping trading bot...")
        self._running = False

        if self._stream_manager:
            await self._stream_manager.stop()

        # Cleanup hysteresis manager
        set_hysteresis_manager(None)

        # Generate performance report
        if self._tracker:
            logger.info(f"Final performance: {self._tracker.get_summary()}")
            self._tracker.save_metrics()
            report_path = self._tracker.save_report()
            logger.info(f"Performance report saved to: {report_path}")

        # Cleanup performance tracker
        set_performance_tracker(None)

        # Cleanup history writers
        set_decision_writer(None)
        set_indicator_writer(None)
        set_derivatives_writer(None)

        self._log_final_stats()
        logger.info("Trading bot stopped")

    def _handle_message(self, message: dict) -> None:
        """Handle incoming WebSocket message (Layer 1).

        This runs synchronously in the event loop.
        Processes messages through rule-based triggers without LLM cost.

        Args:
            message: Raw WebSocket message.
        """
        self._stats["events_received"] += 1

        # Route message to appropriate handler
        event = self.message_router.route(message)
        if event is None:
            return

        # Evaluate trigger conditions (rule-based, no LLM)
        triggers = self.evaluator.evaluate(event)

        # Submit triggers to dispatcher
        for trigger in triggers:
            self._stats["triggers_fired"] += 1
            logger.debug(
                f"Trigger: {trigger.trigger_type.value} "
                f"({trigger.severity}) - {trigger.description}"
            )
            # Schedule async submission
            asyncio.create_task(self.dispatcher.submit(trigger))

    def _handle_error(self, error: Exception) -> None:
        """Handle stream errors.

        Args:
            error: Exception from stream.
        """
        logger.error(f"Stream error: {error}")

    async def _on_batch_ready(self, batch: EventBatch) -> None:
        """Handle batched events - invoke LLM decision (Layer 2).

        This is the only place where LLM is called, triggered by
        the dispatcher after cooldown and batching.

        Args:
            batch: Batch of trigger events.
        """
        self._stats["llm_calls"] += 1
        self._stats["last_llm_call"] = datetime.now()

        logger.info(
            f"LLM Decision triggered: {len(batch.events)} events, "
            f"types={batch.trigger_types}, severity={batch.highest_severity}"
        )

        try:
            # Create state with trigger events as anomalies
            state = create_initial_state()
            state["anomalies"] = [e.to_anomaly_dict() for e in batch.events]

            # Run the existing LangGraph pipeline
            final_state = simple_pipeline.invoke(state)

            # Log decision
            decision = final_state.get("decision")
            if decision:
                action = decision.get("action", "UNKNOWN")
                confidence = decision.get("confidence", 0)
                status = decision.get("status", "unknown")

                logger.info(
                    f"Decision: {action} "
                    f"(confidence={confidence:.2f}, status={status})"
                )

                # Set post-trade cooldown if executed
                if status == "executed":
                    self._stats["trades_executed"] += 1
                    self.dispatcher.set_post_trade_cooldown(batch.symbol)
                    logger.info(f"Trade executed for {batch.symbol}")

            # Record portfolio snapshot for performance tracking
            if self._tracker and self._broker:
                market = final_state.get("market") or {}
                btc_price = market.get("current_price", 0)

                if btc_price > 0:
                    balances = self._broker.get_all_balances()
                    krw = float(balances.get("KRW", 0))
                    btc = float(balances.get("BTC", 0))
                    btc_value = btc * btc_price
                    total_value = krw + btc_value

                    self._tracker.record_snapshot(
                        total_value_krw=total_value,
                        cash_krw=krw,
                        btc_balance=btc,
                        btc_price=btc_price,
                        cycle_count=self._stats["llm_calls"],
                    )

            # Log any errors
            error = final_state.get("error")
            if error:
                logger.warning(f"Cycle error: {error}")

        except Exception as e:
            logger.exception(f"LLM decision failed: {e}")

    def _log_final_stats(self) -> None:
        """Log final bot statistics."""
        stats = self.stats

        logger.info("=" * 60)
        logger.info("Bot Statistics")
        logger.info("-" * 60)
        logger.info(f"  Uptime: {stats.get('uptime_seconds', 0):.0f} seconds")
        logger.info(f"  Events received: {stats['events_received']}")
        logger.info(f"  Triggers fired: {stats['triggers_fired']}")
        logger.info(f"  LLM calls: {stats['llm_calls']}")
        logger.info(f"  Trades executed: {stats['trades_executed']}")

        if stats["events_received"] > 0:
            logger.info(f"  Trigger rate: {stats.get('trigger_rate_pct', 0):.2f}%")

        if self._stream_manager:
            logger.info("-" * 60)
            logger.info("Stream Statistics:")
            for stream_type, stream_stats in self._stream_manager.stats.items():
                logger.info(
                    f"  {stream_type.value}: "
                    f"{stream_stats.messages_received} msgs, "
                    f"{stream_stats.reconnect_count} reconnects"
                )

        # Log hysteresis statistics
        if self._hysteresis:
            logger.info("-" * 60)
            logger.info("Hysteresis Statistics:")
            for key, value in self._hysteresis.stats.to_dict().items():
                if isinstance(value, float):
                    logger.info(f"  {key}: {value:.2f}")
                else:
                    logger.info(f"  {key}: {value}")

        # Log isolated mode statistics
        isolated_tracker = get_isolated_tracker()
        if isolated_tracker is not None:
            logger.info("-" * 60)
            logger.info("Isolated Mode Statistics:")
            for key, value in isolated_tracker.get_stats().items():
                if isinstance(value, float):
                    logger.info(f"  {key}: {value:.2f}")
                else:
                    logger.info(f"  {key}: {value}")

        logger.info("=" * 60)


async def run_bot(
    symbols: list[str],
    cooldown_seconds: float = 60.0,
    batch_window_seconds: float = 10.0,
    hysteresis_config: HysteresisConfig | None = None,
    performance_tracking: bool = True,
) -> None:
    """Run the event-driven trading bot.

    Args:
        symbols: Trading pairs to monitor.
        cooldown_seconds: Minimum seconds between LLM calls.
        batch_window_seconds: Seconds to batch events.
        hysteresis_config: Optional hysteresis configuration. None to disable.
        performance_tracking: Enable performance tracking.
    """
    settings = get_settings()

    # Validate configuration
    missing = settings.validate_api_keys()
    if missing:
        logger.warning(f"Missing API keys: {missing}")
        if "UPBIT_ACCESS_KEY" in missing or "UPBIT_SECRET_KEY" in missing:
            logger.error("Upbit API keys are required")
            return

    # Create bot instance
    bot = EventDrivenTradingBot(
        symbols=symbols,
        thresholds=TriggerThresholds(),
        cooldown=CooldownConfig(min_interval_seconds=cooldown_seconds),
        batch=BatchConfig(batch_window_seconds=batch_window_seconds),
        hysteresis_config=hysteresis_config,
        performance_tracking=performance_tracking,
    )

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start bot and wait for shutdown
    try:
        await bot.start()
        await shutdown_event.wait()
    finally:
        await bot.stop()


def _get_hysteresis_config(
    enabled: bool, mode: str
) -> HysteresisConfig | None:
    """Get hysteresis config based on settings.

    Args:
        enabled: Whether hysteresis is enabled.
        mode: Hysteresis mode preset.

    Returns:
        HysteresisConfig or None if disabled.
    """
    if not enabled:
        return None

    if mode == "streaming":
        return HysteresisConfig.streaming()
    elif mode == "daily":
        return HysteresisConfig.backtest_daily()
    elif mode == "conservative":
        return HysteresisConfig.conservative()
    else:
        return HysteresisConfig.streaming()


def main() -> None:
    """Main entry point with CLI arguments."""
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Event-Driven Auto Trading Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["KRW-BTC"],
        help="Trading pairs to monitor",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=60.0,
        help="Minimum seconds between LLM calls",
    )
    parser.add_argument(
        "--batch-window",
        type=float,
        default=10.0,
        help="Seconds to batch events before LLM decision",
    )
    parser.add_argument(
        "--hysteresis",
        action="store_true",
        default=None,
        help="Enable hysteresis (oscillation prevention)",
    )
    parser.add_argument(
        "--no-hysteresis",
        action="store_true",
        help="Disable hysteresis",
    )
    parser.add_argument(
        "--hysteresis-mode",
        choices=["streaming", "daily", "conservative"],
        default=None,
        help="Hysteresis preset mode",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        default=None,
        help="Enable isolated mode (trade with limited capital, protect existing holdings)",
    )
    parser.add_argument(
        "--no-isolated",
        action="store_true",
        help="Disable isolated mode",
    )
    parser.add_argument(
        "--isolated-capital",
        type=float,
        default=None,
        help="Initial capital for isolated mode (auto-adjusts if different from saved)",
    )
    parser.add_argument(
        "--reset-isolated",
        action="store_true",
        help="Reset isolated balance to initial state (clears all holdings)",
    )

    args = parser.parse_args()

    # Update log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Determine hysteresis settings (CLI overrides config)
    hysteresis_enabled = settings.hysteresis_enabled
    hysteresis_mode = settings.hysteresis_mode

    if args.hysteresis:
        hysteresis_enabled = True
    elif args.no_hysteresis:
        hysteresis_enabled = False

    if args.hysteresis_mode:
        hysteresis_mode = args.hysteresis_mode

    hysteresis_config = _get_hysteresis_config(hysteresis_enabled, hysteresis_mode)

    # Determine isolated mode settings (CLI overrides config)
    isolated_enabled = settings.isolated_mode
    isolated_capital = settings.isolated_capital_krw

    if args.isolated:
        isolated_enabled = True
    elif args.no_isolated:
        isolated_enabled = False

    if args.isolated_capital is not None:
        isolated_capital = args.isolated_capital
        isolated_enabled = True  # Specifying capital implies enabling

    # Configure global isolated mode
    if isolated_enabled:
        tracker = IsolatedBalanceTracker(initial_capital_krw=isolated_capital)

        # Handle reset
        if args.reset_isolated:
            tracker.reset(Decimal(str(isolated_capital)))
        else:
            # Auto-adjust capital if different from saved state
            tracker.adjust_capital(isolated_capital)

        set_isolated_tracker(tracker)
        logger.info(f"Isolated mode configured: {isolated_capital:,.0f} KRW")

    # Run the bot
    asyncio.run(
        run_bot(
            symbols=args.symbols,
            cooldown_seconds=args.cooldown,
            batch_window_seconds=args.batch_window,
            hysteresis_config=hysteresis_config,
        )
    )


if __name__ == "__main__":
    main()
