"""Command-line interface for backtesting."""

import argparse
import logging
import sys
from datetime import datetime

from trading.backtest.data import HistoricalDataLoader
from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.metrics import PerformanceMetrics
from trading.backtest.report import BacktestReporter
from trading.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def progress_bar(current: int, total: int, width: int = 50) -> None:
    """Display progress bar.

    Args:
        current: Current progress.
        total: Total items.
        width: Bar width.
    """
    progress = current / total
    filled = int(width * progress)
    bar = "█" * filled + "░" * (width - filled)
    percent = progress * 100
    print(f"\r  진행률: [{bar}] {percent:.1f}% ({current}/{total})", end="", flush=True)

    if current == total:
        print()  # New line at completion


def main() -> None:
    """Main entry point for backtest CLI."""
    parser = argparse.ArgumentParser(
        description="Auto Trading Bot 백테스팅 도구",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Data options
    default_symbol = get_settings().upbit_symbol
    parser.add_argument(
        "--symbol",
        type=str,
        default=default_symbol,
        help="거래쌍 심볼 (기본값은 TRADING_ASSET 환경변수에서 derive)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="백테스트 기간 (일)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="day",
        choices=["minute1", "minute5", "minute15", "minute60", "minute240", "day"],
        help="캔들 간격",
    )

    # Config options
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000_000,
        help="초기 자본 (KRW)",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.0005,
        help="거래 수수료율 (0.0005 = 0.05%)",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.001,
        help="슬리피지율 (0.001 = 0.1%)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="LLM 사용 (비용 발생, 기본값: 규칙 기반)",
    )
    parser.add_argument(
        "--hysteresis",
        action="store_true",
        help="Hysteresis 적용 (액션 진동 방지)",
    )
    parser.add_argument(
        "--load-derivatives",
        action="store_true",
        help=(
            "Binance Futures 과거 OI/L_S/funding 데이터를 자산 심볼에 맞게 "
            "로드. 미설정 시 derivatives=None (BTC 데이터로 fallback되던 "
            "기존 버그 회피)."
        ),
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.5,
        help="최소 확신도 임계값",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=50.0,
        help="최대 포지션 비율 (%)",
    )

    # Output options
    parser.add_argument(
        "--output-dir",
        type=str,
        default="backtest_results",
        help="결과 출력 디렉토리",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="리포트 파일 생성 안함",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="간략한 출력",
    )

    args = parser.parse_args()

    # Configure logging
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    print("\n" + "=" * 60)
    print("          Auto Trading Bot 백테스팅")
    print("=" * 60 + "\n")

    # Load data
    print(f"📥 데이터 로딩 중... ({args.symbol}, {args.days}일, {args.interval})")
    loader = HistoricalDataLoader()

    df = loader.load_extended_ohlcv(
        symbol=args.symbol,
        days=args.days,
        interval=args.interval,
    )

    if df.empty:
        print("❌ 데이터를 가져올 수 없습니다.")
        sys.exit(1)

    print(f"  ✅ {len(df)}개 캔들 로드 완료")
    print(f"  📅 기간: {df.index.min().strftime('%Y-%m-%d')} ~ {df.index.max().strftime('%Y-%m-%d')}")

    # Prepare data points
    print("\n📊 데이터 준비 중...")
    data_points = loader.prepare_backtest_data(df, lookback_period=50)

    if not data_points:
        print("❌ 백테스트 데이터가 부족합니다.")
        sys.exit(1)

    print(f"  ✅ {len(data_points)}개 데이터 포인트 준비 완료")

    # Configure engine
    config = BacktestConfig(
        initial_capital_krw=args.capital,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage,
        use_llm=args.use_llm,
        use_hysteresis=args.hysteresis,
        confidence_threshold=args.confidence_threshold,
        max_position_pct=args.max_position,
        symbol=args.symbol,
    )

    # Pre-load derivatives history for the asset (Binance Futures public API).
    # Without this, derivatives=None for every cycle.
    derivatives_by_ts: dict | None = None
    if args.load_derivatives:
        from trading.backtest.derivatives_loader import load_historical_derivatives
        from trading.config import get_settings as _gs
        settings = _gs()
        futures_symbol = settings.binance_futures_symbol
        start_ts = df.index.min().to_pydatetime()
        end_ts = df.index.max().to_pydatetime()
        print(f"\n📡 Binance Futures derivatives 로드 중... ({futures_symbol})")
        derivatives_by_ts = load_historical_derivatives(
            start_ts, end_ts, period="1h", symbol=futures_symbol
        )
        print(f"  ✅ {len(derivatives_by_ts)}개 스냅샷 로드 완료")

    print("\n⚙️ 설정:")
    print(f"  초기 자본: {config.initial_capital_krw:,.0f} KRW")
    print(f"  수수료율: {config.fee_rate * 100:.3f}%")
    print(f"  슬리피지: {config.slippage_rate * 100:.2f}%")
    print(f"  LLM 사용: {'예' if config.use_llm else '아니오 (규칙 기반)'}")
    print(f"  Hysteresis: {'예' if config.use_hysteresis else '아니오'}")
    print(f"  확신도 임계값: {config.confidence_threshold:.0%}")
    print(f"  최대 포지션: {config.max_position_pct:.0f}%")

    # Run backtest
    print("\n🚀 백테스트 실행 중...")
    engine = BacktestEngine(config, derivatives_by_ts=derivatives_by_ts)
    result = engine.run(data_points, progress_callback=progress_bar)

    # Calculate metrics
    print("\n📈 성과 지표 계산 중...")
    metrics = PerformanceMetrics.from_backtest_result(result)

    # Print summary
    reporter = BacktestReporter(output_dir=args.output_dir)
    reporter.print_summary(result, metrics)

    # Generate reports
    if not args.no_report:
        print("📝 리포트 생성 중...")
        files = reporter.generate_report(result, metrics)

        print("\n📁 생성된 파일:")
        for name, path in files.items():
            print(f"  - {name}: {path}")

    # Print detailed metrics
    if not args.quiet:
        print(metrics.summary())

    print("\n✅ 백테스트 완료!\n")


if __name__ == "__main__":
    main()
