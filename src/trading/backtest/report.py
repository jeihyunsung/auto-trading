"""Backtest result reporting and visualization."""

import json
import logging
from datetime import datetime
from pathlib import Path

from trading.backtest.engine import BacktestResult, Trade, TradeType
from trading.backtest.metrics import PerformanceMetrics

logger = logging.getLogger(__name__)


class BacktestReporter:
    """Generate reports from backtest results."""

    def __init__(self, output_dir: Path | str | None = None):
        """Initialize reporter.

        Args:
            output_dir: Directory for output files.
        """
        if output_dir is None:
            self.output_dir = Path("backtest_results")
        elif isinstance(output_dir, str):
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        result: BacktestResult,
        metrics: PerformanceMetrics,
        filename_prefix: str | None = None,
    ) -> dict[str, Path]:
        """Generate full report from backtest result.

        Args:
            result: Backtest result.
            metrics: Performance metrics.
            filename_prefix: Optional prefix for output files.

        Returns:
            Dictionary of generated file paths.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = filename_prefix or f"backtest_{timestamp}"

        generated_files = {}

        # Generate summary report
        summary_path = self._generate_summary_report(result, metrics, prefix)
        generated_files["summary"] = summary_path

        # Generate trades CSV
        trades_path = self._generate_trades_csv(result, prefix)
        generated_files["trades"] = trades_path

        # Generate portfolio history CSV
        portfolio_path = self._generate_portfolio_csv(result, prefix)
        generated_files["portfolio"] = portfolio_path

        # Generate decisions JSON
        decisions_path = self._generate_decisions_json(result, prefix)
        generated_files["decisions"] = decisions_path

        # Generate JSON report
        json_path = self._generate_json_report(result, metrics, prefix)
        generated_files["json"] = json_path

        logger.info(f"Generated {len(generated_files)} report files in {self.output_dir}")
        return generated_files

    def _generate_summary_report(
        self,
        result: BacktestResult,
        metrics: PerformanceMetrics,
        prefix: str,
    ) -> Path:
        """Generate text summary report.

        Args:
            result: Backtest result.
            metrics: Performance metrics.
            prefix: Filename prefix.

        Returns:
            Path to generated file.
        """
        filepath = self.output_dir / f"{prefix}_summary.txt"

        content = f"""
{'=' * 70}
                      백테스트 결과 리포트
{'=' * 70}

📅 기간 정보
{'-' * 70}
  시작일:                 {result.start_date.strftime('%Y-%m-%d')}
  종료일:                 {result.end_date.strftime('%Y-%m-%d')}
  기간:                   {(result.end_date - result.start_date).days}일

💰 자본 정보
{'-' * 70}
  초기 자본:              {result.initial_capital:,.0f} KRW
  최종 자본:              {result.final_value:,.0f} KRW
  손익:                   {result.final_value - result.initial_capital:+,.0f} KRW

⚙️ 설정
{'-' * 70}
  수수료율:               {result.config.fee_rate * 100:.3f}%
  슬리피지:               {result.config.slippage_rate * 100:.2f}%
  LLM 사용:               {'예' if result.config.use_llm else '아니오 (규칙 기반)'}
  확신도 임계값:          {result.config.confidence_threshold:.1%}
  최대 포지션:            {result.config.max_position_pct:.0f}%

{metrics.summary()}

📋 거래 내역 요약
{'-' * 70}
  총 거래:                {result.num_trades}회
  매수:                   {result.num_buys}회
  매도:                   {result.num_sells}회

{'=' * 70}
        생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 70}
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Generated summary report: {filepath}")
        return filepath

    def _generate_trades_csv(self, result: BacktestResult, prefix: str) -> Path:
        """Generate trades CSV file.

        Args:
            result: Backtest result.
            prefix: Filename prefix.

        Returns:
            Path to generated file.
        """
        filepath = self.output_dir / f"{prefix}_trades.csv"

        headers = [
            "timestamp",
            "type",
            "price",
            "quantity",
            "value_krw",
            "fee",
            "confidence",
            "rationale",
        ]

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(",".join(headers) + "\n")

            for trade in result.trades:
                row = [
                    trade.timestamp.isoformat(),
                    trade.trade_type.value,
                    f"{trade.price:.0f}",
                    f"{trade.quantity:.8f}",
                    f"{trade.value_krw:.0f}",
                    f"{trade.fee:.0f}",
                    f"{trade.confidence:.2f}",
                    f'"{trade.rationale[:100]}"',
                ]
                f.write(",".join(row) + "\n")

        logger.info(f"Generated trades CSV: {filepath}")
        return filepath

    def _generate_portfolio_csv(self, result: BacktestResult, prefix: str) -> Path:
        """Generate portfolio history CSV file.

        Args:
            result: Backtest result.
            prefix: Filename prefix.

        Returns:
            Path to generated file.
        """
        filepath = self.output_dir / f"{prefix}_portfolio.csv"

        headers = [
            "timestamp",
            "cash_krw",
            "btc_quantity",
            "btc_price",
            "total_value_krw",
            "unrealized_pnl_pct",
        ]

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(",".join(headers) + "\n")

            for snapshot in result.portfolio_history:
                row = [
                    snapshot.timestamp.isoformat(),
                    f"{snapshot.cash_krw:.0f}",
                    f"{snapshot.btc_quantity:.8f}",
                    f"{snapshot.btc_price:.0f}",
                    f"{snapshot.total_value_krw:.0f}",
                    f"{snapshot.unrealized_pnl_pct:.2f}",
                ]
                f.write(",".join(row) + "\n")

        logger.info(f"Generated portfolio CSV: {filepath}")
        return filepath

    def _generate_decisions_json(self, result: BacktestResult, prefix: str) -> Path:
        """Generate decisions JSON file.

        Args:
            result: Backtest result.
            prefix: Filename prefix.

        Returns:
            Path to generated file.
        """
        filepath = self.output_dir / f"{prefix}_decisions.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.decisions, f, ensure_ascii=False, indent=2)

        logger.info(f"Generated decisions JSON: {filepath}")
        return filepath

    def _generate_json_report(
        self,
        result: BacktestResult,
        metrics: PerformanceMetrics,
        prefix: str,
    ) -> Path:
        """Generate JSON report with all data.

        Args:
            result: Backtest result.
            metrics: Performance metrics.
            prefix: Filename prefix.

        Returns:
            Path to generated file.
        """
        filepath = self.output_dir / f"{prefix}_report.json"

        report = {
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start": result.start_date.isoformat(),
                "end": result.end_date.isoformat(),
                "days": (result.end_date - result.start_date).days,
            },
            "config": {
                "initial_capital_krw": result.config.initial_capital_krw,
                "fee_rate": result.config.fee_rate,
                "slippage_rate": result.config.slippage_rate,
                "use_llm": result.config.use_llm,
                "confidence_threshold": result.config.confidence_threshold,
                "max_position_pct": result.config.max_position_pct,
            },
            "results": {
                "initial_capital": result.initial_capital,
                "final_value": result.final_value,
                "total_return_pct": result.total_return_pct,
                "num_trades": result.num_trades,
                "num_buys": result.num_buys,
                "num_sells": result.num_sells,
            },
            "metrics": metrics.to_dict(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Generated JSON report: {filepath}")
        return filepath

    def print_summary(self, result: BacktestResult, metrics: PerformanceMetrics) -> None:
        """Print summary to console.

        Args:
            result: Backtest result.
            metrics: Performance metrics.
        """
        print(f"\n{'=' * 60}")
        print("               백테스트 결과 요약")
        print(f"{'=' * 60}")
        print(f"  기간: {result.start_date.strftime('%Y-%m-%d')} ~ {result.end_date.strftime('%Y-%m-%d')}")
        print(f"  초기 자본: {result.initial_capital:,.0f} KRW")
        print(f"  최종 자본: {result.final_value:,.0f} KRW")
        print(f"  총 수익률: {metrics.total_return_pct:+.2f}%")
        print(f"  Buy & Hold: {metrics.buy_and_hold_return_pct:+.2f}%")
        print(f"  알파: {metrics.alpha_pct:+.2f}%")
        print(f"{'=' * 60}")
        print(f"  샤프 비율: {metrics.sharpe_ratio:.2f}")
        print(f"  최대 낙폭: {metrics.max_drawdown_pct:.2f}%")
        print(f"  승률: {metrics.win_rate_pct:.1f}%")
        print(f"  총 거래: {metrics.total_trades}회")
        print(f"{'=' * 60}\n")
