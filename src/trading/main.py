"""Main entry point for the trading bot."""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from trading.adapters.upbit import get_broker
from trading.agents.decision_agent import set_hysteresis_manager
from trading.config import get_settings
from trading.core.decision_history import DecisionHistoryWriter, set_decision_writer
from trading.core.derivatives_history import DerivativesHistoryWriter, set_derivatives_writer
from trading.core.hysteresis import HysteresisConfig, HysteresisManager
from trading.core.indicator_history import IndicatorHistoryWriter, set_indicator_writer
from trading.core.isolated_balance import (
    IsolatedBalanceTracker,
    get_isolated_tracker,
    set_isolated_tracker,
)
from trading.core.news_memory import NewsMemory, NewsMemoryConfig, set_news_memory
from trading.core.performance import (
    PerformanceConfig,
    PerformanceTracker,
    get_performance_tracker,
    set_performance_tracker,
)
from trading.core.state import create_initial_state
from trading.graph.builder import simple_pipeline, trading_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def run_single_cycle(use_supervisor: bool = True) -> dict:
    """Run a single trading cycle.

    Args:
        use_supervisor: Use supervisor graph (True) or simple pipeline (False).

    Returns:
        Final state after cycle completion.
    """
    logger.info("=" * 60)
    logger.info(f"Starting trading cycle at {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Create initial state
    state = create_initial_state()

    # Select graph
    graph = trading_graph if use_supervisor else simple_pipeline

    # Run graph
    try:
        final_state = graph.invoke(state)

        # Log results
        decision = final_state.get("decision")
        if decision:
            logger.info(
                f"Decision: {decision.get('action')} "
                f"(confidence={decision.get('confidence', 0):.2f}, "
                f"status={decision.get('status')})"
            )
            logger.info(f"Rationale: {decision.get('rationale', 'N/A')}")
        else:
            logger.info("No decision generated this cycle")

        # Log errors if any
        error = final_state.get("error")
        if error:
            logger.error(f"Cycle error: {error}")

        return final_state

    except Exception as e:
        logger.exception(f"Cycle failed with exception: {e}")
        return {"error": str(e)}


def run_continuous(
    interval_seconds: int = 300,
    use_supervisor: bool = True,
    max_cycles: int | None = None,
    hysteresis_config: HysteresisConfig | None = None,
    news_memory_enabled: bool = True,
    performance_tracking: bool = True,
) -> None:
    """Run trading bot continuously.

    Args:
        interval_seconds: Seconds between cycles (default 5 minutes).
        use_supervisor: Use supervisor graph.
        max_cycles: Maximum cycles to run (None for infinite).
        hysteresis_config: Optional hysteresis configuration. None to disable.
        news_memory_enabled: Enable news memory system.
        performance_tracking: Enable performance tracking.
    """
    settings = get_settings()

    # Initialize hysteresis manager
    hysteresis: HysteresisManager | None = None
    if hysteresis_config is not None:
        hysteresis = HysteresisManager(hysteresis_config)
        set_hysteresis_manager(hysteresis)

    # Initialize news memory
    news_memory: NewsMemory | None = None
    if news_memory_enabled and settings.news_memory_enabled:
        news_memory = NewsMemory(
            NewsMemoryConfig(
                ttl=timedelta(hours=settings.news_memory_ttl_hours),
                decay_half_life=timedelta(hours=settings.news_decay_half_life_hours),
            )
        )
        set_news_memory(news_memory)

    # Initialize performance tracker (uses shared broker)
    tracker: PerformanceTracker | None = None
    broker = get_broker()  # Shared broker instance for all agents
    if performance_tracking:
        tracker = PerformanceTracker(
            PerformanceConfig(
                snapshot_interval_minutes=max(1, interval_seconds // 60),
                log_dir=settings.log_dir,
            )
        )
        set_performance_tracker(tracker)

    # Initialize isolated balance tracker if enabled
    isolated_tracker: IsolatedBalanceTracker | None = None
    if settings.isolated_mode:
        isolated_tracker = IsolatedBalanceTracker(
            initial_capital_krw=settings.isolated_capital_krw,
            state_file=settings.log_dir / "isolated_balance.json",
        )
        set_isolated_tracker(isolated_tracker)

    # Initialize history writers for dashboard
    decision_writer = DecisionHistoryWriter(settings.log_dir)
    set_decision_writer(decision_writer)

    derivatives_writer = DerivativesHistoryWriter(settings.log_dir)
    set_derivatives_writer(derivatives_writer)

    indicator_writer = IndicatorHistoryWriter(settings.log_dir)
    set_indicator_writer(indicator_writer)

    logger.info("=" * 60)
    logger.info("Starting Auto Trading Bot")
    logger.info(f"Mode: {settings.trading_mode}")
    logger.info(f"Interval: {interval_seconds} seconds")
    logger.info(f"Max cycles: {max_cycles or 'unlimited'}")
    if hysteresis:
        logger.info(
            f"Hysteresis: enabled (reversal_delta={hysteresis.config.action_reversal_delta})"
        )
    else:
        logger.info("Hysteresis: disabled")
    if news_memory:
        logger.info(
            f"News memory: enabled (ttl={settings.news_memory_ttl_hours}h, "
            f"decay={settings.news_decay_half_life_hours}h)"
        )
    else:
        logger.info("News memory: disabled")
    if tracker:
        logger.info("Performance tracking: enabled")
    else:
        logger.info("Performance tracking: disabled")
    if isolated_tracker:
        logger.info(
            f"Isolated mode: enabled (capital={settings.isolated_capital_krw:,.0f} KRW)"
        )
    else:
        logger.info("Isolated mode: disabled")
    logger.info("=" * 60)

    # Validate API keys
    missing = settings.validate_api_keys()
    if missing:
        logger.warning(f"Missing API keys: {missing}")
        if "OPENAI_API_KEY" in missing:
            logger.warning("LLM features will be disabled")

    cycle_count = 0

    try:
        while max_cycles is None or cycle_count < max_cycles:
            cycle_count += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"Cycle {cycle_count}")
            logger.info(f"{'='*60}\n")

            start_time = time.time()
            final_state = run_single_cycle(use_supervisor)

            # Record portfolio snapshot for performance tracking
            if tracker and broker:
                market = final_state.get("market", {})
                btc_price = market.get("current_price", 0)

                if btc_price > 0:
                    balances = broker.get_all_balances()
                    krw = float(balances.get("KRW", 0))
                    btc = float(balances.get("BTC", 0))
                    btc_value = btc * btc_price
                    total_value = krw + btc_value

                    # Start tracking on first valid price
                    if tracker._start_time is None:
                        tracker.start(total_value, btc_price)

                    tracker.record_snapshot(
                        total_value_krw=total_value,
                        cash_krw=krw,
                        btc_balance=btc,
                        btc_price=btc_price,
                        cycle_count=cycle_count,
                        force=True,  # Record every cycle
                    )

            # Log stats periodically
            if cycle_count % 10 == 0:
                if hysteresis:
                    logger.info(f"Hysteresis stats: {hysteresis.stats.to_dict()}")
                if news_memory:
                    logger.info(f"News memory stats: {news_memory.get_stats()}")
                if tracker:
                    logger.info(f"Performance: {tracker.get_summary()}")

            # Check if kill switch was triggered
            risk = final_state.get("risk", {})
            if risk.get("is_kill_switch_on"):
                logger.critical("Kill switch activated - stopping bot")
                break

            # Wait for next cycle
            elapsed = time.time() - start_time
            sleep_time = max(0, interval_seconds - elapsed)

            if max_cycles is None or cycle_count < max_cycles:
                logger.info(f"Next cycle in {sleep_time:.0f} seconds...")
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
    finally:
        # Log final stats and cleanup
        if hysteresis:
            logger.info(f"Final hysteresis stats: {hysteresis.stats.to_dict()}")
        if news_memory:
            logger.info(f"Final news memory stats: {news_memory.get_stats()}")

        # Generate performance report
        if tracker:
            logger.info(f"Final performance: {tracker.get_summary()}")
            tracker.save_metrics()
            report_path = tracker.save_report()
            logger.info(f"Performance report saved to: {report_path}")

        # Log isolated balance stats
        if isolated_tracker:
            logger.info(f"Final isolated balance: {isolated_tracker.get_stats()}")

        set_hysteresis_manager(None)
        set_news_memory(None)
        set_performance_tracker(None)
        set_isolated_tracker(None)
        set_decision_writer(None)
        set_derivatives_writer(None)
        set_indicator_writer(None)

    logger.info("Trading bot stopped")


def validate_config() -> bool:
    """Validate configuration before starting.

    Returns:
        True if configuration is valid.
    """
    settings = get_settings()

    logger.info("Validating configuration...")
    logger.info(f"  Trading mode: {settings.trading_mode}")
    logger.info(f"  Max daily loss: {settings.max_daily_loss_pct}%")
    logger.info(f"  Max position: {settings.max_position_pct}%")
    logger.info(f"  LLM model: {settings.openai_model}")

    missing = settings.validate_api_keys()

    if "UPBIT_ACCESS_KEY" in missing or "UPBIT_SECRET_KEY" in missing:
        logger.error("Upbit API keys are required")
        return False

    if not settings.is_paper_trading and "OPENAI_API_KEY" in missing:
        logger.error("OpenAI API key is required for live trading")
        return False

    logger.info("Configuration OK")
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="LLM-based Auto Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["single", "continuous"],
        default="single",
        help="Run mode: single cycle or continuous",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval between cycles in seconds (default: 300)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Maximum number of cycles (default: unlimited)",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use simple pipeline instead of supervisor graph",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate configuration, don't run",
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        help="Use event-driven streaming mode instead of polling",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=60.0,
        help="Cooldown between LLM calls in streaming mode (default: 60)",
    )
    parser.add_argument(
        "--no-hysteresis",
        action="store_true",
        help="Disable decision hysteresis",
    )
    parser.add_argument(
        "--hysteresis-reversal-delta",
        type=float,
        default=0.35,
        help="Confidence delta required for BUY<->SELL reversal (default: 0.35)",
    )
    parser.add_argument(
        "--no-news-memory",
        action="store_true",
        help="Disable news memory system",
    )
    parser.add_argument(
        "--no-news-filter",
        action="store_true",
        help="Disable news event filtering",
    )
    parser.add_argument(
        "--no-performance",
        action="store_true",
        help="Disable performance tracking",
    )

    args = parser.parse_args()

    # Validate configuration
    if not validate_config():
        sys.exit(1)

    if args.validate_only:
        logger.info("Configuration validation complete")
        sys.exit(0)

    # Build hysteresis config
    hysteresis_config: HysteresisConfig | None = None
    if not args.no_hysteresis:
        hysteresis_config = HysteresisConfig(
            action_reversal_delta=args.hysteresis_reversal_delta,
        )

    # Check for streaming mode
    news_memory_enabled = not args.no_news_memory

    if args.streaming:
        logger.info("Starting in event-driven streaming mode...")
        from trading.main_async import run_bot

        settings = get_settings()

        # Initialize isolated balance tracker if enabled (IMPORTANT: must be before run_bot)
        if settings.isolated_mode:
            isolated_tracker = IsolatedBalanceTracker(
                initial_capital_krw=settings.isolated_capital_krw,
                state_file=settings.log_dir / "isolated_balance.json",
            )
            set_isolated_tracker(isolated_tracker)
            logger.info(
                f"Isolated mode: enabled (capital={settings.isolated_capital_krw:,.0f} KRW)"
            )

        asyncio.run(
            run_bot(
                symbols=settings.streaming_symbols,
                cooldown_seconds=args.cooldown,
                batch_window_seconds=settings.event_batch_window_seconds,
                hysteresis_config=hysteresis_config,
                news_memory_enabled=news_memory_enabled,
                performance_tracking=not args.no_performance,
            )
        )
        return

    # Run polling mode

    if args.mode == "single":
        # For single mode, optionally apply hysteresis and news memory
        settings = get_settings()
        if hysteresis_config is not None:
            hysteresis = HysteresisManager(hysteresis_config)
            set_hysteresis_manager(hysteresis)
        news_memory: NewsMemory | None = None
        if news_memory_enabled and settings.news_memory_enabled:
            news_memory = NewsMemory(
                NewsMemoryConfig(
                    ttl=timedelta(hours=settings.news_memory_ttl_hours),
                    decay_half_life=timedelta(hours=settings.news_decay_half_life_hours),
                )
            )
            set_news_memory(news_memory)
        try:
            run_single_cycle(use_supervisor=not args.simple)
        finally:
            set_hysteresis_manager(None)
            set_news_memory(None)
    else:
        run_continuous(
            interval_seconds=args.interval,
            use_supervisor=not args.simple,
            max_cycles=args.max_cycles,
            hysteresis_config=hysteresis_config,
            news_memory_enabled=news_memory_enabled,
            performance_tracking=not args.no_performance,
        )


if __name__ == "__main__":
    main()
