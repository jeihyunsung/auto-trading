"""Performance tracking for live/paper trading.

Tracks portfolio snapshots, calculates metrics, and generates reports.
"""

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""

    timestamp: datetime
    total_value_krw: float
    cash_krw: float
    btc_balance: float
    btc_price: float
    btc_value_krw: float
    exposure_pct: float
    cycle_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_value_krw": self.total_value_krw,
            "cash_krw": self.cash_krw,
            "btc_balance": self.btc_balance,
            "btc_price": self.btc_price,
            "btc_value_krw": self.btc_value_krw,
            "exposure_pct": self.exposure_pct,
            "cycle_count": self.cycle_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PortfolioSnapshot":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            total_value_krw=data["total_value_krw"],
            cash_krw=data["cash_krw"],
            btc_balance=data["btc_balance"],
            btc_price=data["btc_price"],
            btc_value_krw=data["btc_value_krw"],
            exposure_pct=data["exposure_pct"],
            cycle_count=data.get("cycle_count", 0),
        )


@dataclass
class TradeRecord:
    """Record of an executed trade."""

    timestamp: datetime
    action: Literal["BUY", "SELL"]
    btc_quantity: float
    price: float
    amount_krw: float
    fee_krw: float
    confidence: float
    rationale: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "btc_quantity": self.btc_quantity,
            "price": self.price,
            "amount_krw": self.amount_krw,
            "fee_krw": self.fee_krw,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TradeRecord":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            action=data["action"],
            btc_quantity=data["btc_quantity"],
            price=data["price"],
            amount_krw=data["amount_krw"],
            fee_krw=data["fee_krw"],
            confidence=data["confidence"],
            rationale=data.get("rationale", ""),
        )


@dataclass
class LiveMetrics:
    """Live trading performance metrics."""

    start_time: datetime
    end_time: datetime
    initial_value_krw: float
    current_value_krw: float
    total_return_pct: float
    peak_value_krw: float
    max_drawdown_pct: float
    total_trades: int
    buy_trades: int
    sell_trades: int
    total_fees_krw: float
    win_rate_pct: float
    avg_trade_size_krw: float
    btc_price_change_pct: float  # Buy & Hold benchmark
    alpha_pct: float  # Excess return over B&H
    sharpe_ratio: float
    cycles_run: int

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": (self.end_time - self.start_time).total_seconds() / 3600,
            "initial_value_krw": round(self.initial_value_krw),
            "current_value_krw": round(self.current_value_krw),
            "total_return_pct": round(self.total_return_pct, 2),
            "peak_value_krw": round(self.peak_value_krw),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_trades": self.total_trades,
            "buy_trades": self.buy_trades,
            "sell_trades": self.sell_trades,
            "total_fees_krw": round(self.total_fees_krw),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "avg_trade_size_krw": round(self.avg_trade_size_krw),
            "btc_price_change_pct": round(self.btc_price_change_pct, 2),
            "alpha_pct": round(self.alpha_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "cycles_run": self.cycles_run,
        }


@dataclass
class PerformanceConfig:
    """Configuration for performance tracking."""

    snapshot_interval_minutes: int = 5
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    snapshot_file: str = "portfolio_snapshots.jsonl"
    metrics_file: str = "performance_metrics.json"
    report_file: str = "daily_report_{date}.md"


class PerformanceTracker:
    """Tracks live trading performance.

    Features:
    - Periodic portfolio snapshots
    - Trade recording
    - Metrics calculation
    - Report generation
    """

    def __init__(self, config: PerformanceConfig | None = None):
        """Initialize performance tracker.

        Args:
            config: Tracker configuration.
        """
        self.config = config or PerformanceConfig()
        self._snapshots: list[PortfolioSnapshot] = []
        self._trades: list[TradeRecord] = []
        self._start_time: datetime | None = None
        self._initial_value: float | None = None
        self._initial_btc_price: float | None = None
        self._peak_value: float = 0.0
        self._last_snapshot_time: datetime | None = None

        # Ensure log directory exists
        self.config.log_dir.mkdir(parents=True, exist_ok=True)

        # Load existing data if available
        self._load_existing_data()

    def _load_existing_data(self) -> None:
        """Load existing snapshots and trades from files."""
        snapshot_path = self.config.log_dir / self.config.snapshot_file

        if snapshot_path.exists():
            try:
                with open(snapshot_path) as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            snapshot = PortfolioSnapshot.from_dict(data)
                            self._snapshots.append(snapshot)

                if self._snapshots:
                    self._start_time = self._snapshots[0].timestamp
                    self._initial_value = self._snapshots[0].total_value_krw
                    self._initial_btc_price = self._snapshots[0].btc_price
                    self._peak_value = max(s.total_value_krw for s in self._snapshots)
                    self._last_snapshot_time = self._snapshots[-1].timestamp
                    logger.info(
                        f"Loaded {len(self._snapshots)} existing snapshots "
                        f"from {self._start_time}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load snapshots: {e}")

    def start(
        self,
        initial_value_krw: float,
        btc_price: float,
        start_time: datetime | None = None,
    ) -> None:
        """Start tracking (or continue from loaded state).

        Args:
            initial_value_krw: Starting portfolio value.
            btc_price: Starting BTC price.
            start_time: Start timestamp.
        """
        if self._start_time is None:
            self._start_time = start_time or datetime.now()
            self._initial_value = initial_value_krw
            self._initial_btc_price = btc_price
            self._peak_value = initial_value_krw
            logger.info(
                f"Performance tracking started: "
                f"initial_value={initial_value_krw:,.0f} KRW, "
                f"btc_price={btc_price:,.0f}"
            )
        else:
            logger.info(
                f"Continuing performance tracking from {self._start_time}, "
                f"{len(self._snapshots)} snapshots loaded"
            )

    def record_snapshot(
        self,
        total_value_krw: float,
        cash_krw: float,
        btc_balance: float,
        btc_price: float,
        cycle_count: int = 0,
        current_time: datetime | None = None,
        force: bool = False,
    ) -> bool:
        """Record portfolio snapshot.

        Args:
            total_value_krw: Total portfolio value.
            cash_krw: Cash balance.
            btc_balance: BTC balance.
            btc_price: Current BTC price.
            cycle_count: Current trading cycle.
            current_time: Timestamp (defaults to now).
            force: Force snapshot regardless of interval.

        Returns:
            True if snapshot was recorded.
        """
        now = current_time or datetime.now()

        # Check interval
        if not force and self._last_snapshot_time:
            elapsed = (now - self._last_snapshot_time).total_seconds() / 60
            if elapsed < self.config.snapshot_interval_minutes:
                return False

        btc_value = btc_balance * btc_price
        exposure = (btc_value / total_value_krw * 100) if total_value_krw > 0 else 0

        snapshot = PortfolioSnapshot(
            timestamp=now,
            total_value_krw=total_value_krw,
            cash_krw=cash_krw,
            btc_balance=btc_balance,
            btc_price=btc_price,
            btc_value_krw=btc_value,
            exposure_pct=exposure,
            cycle_count=cycle_count,
        )

        self._snapshots.append(snapshot)
        self._last_snapshot_time = now

        # Update peak
        if total_value_krw > self._peak_value:
            self._peak_value = total_value_krw

        # Persist to file
        self._append_snapshot_to_file(snapshot)

        logger.debug(
            f"Snapshot recorded: value={total_value_krw:,.0f}, "
            f"exposure={exposure:.1f}%"
        )
        return True

    def record_trade(
        self,
        action: Literal["BUY", "SELL"],
        btc_quantity: float,
        price: float,
        amount_krw: float,
        fee_krw: float,
        confidence: float,
        rationale: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Record an executed trade.

        Args:
            action: Trade action (BUY/SELL).
            btc_quantity: BTC quantity traded.
            price: Execution price.
            amount_krw: KRW amount.
            fee_krw: Fee paid.
            confidence: Decision confidence.
            rationale: Decision rationale.
            timestamp: Trade timestamp.
        """
        trade = TradeRecord(
            timestamp=timestamp or datetime.now(),
            action=action,
            btc_quantity=btc_quantity,
            price=price,
            amount_krw=amount_krw,
            fee_krw=fee_krw,
            confidence=confidence,
            rationale=rationale,
        )
        self._trades.append(trade)
        logger.info(
            f"Trade recorded: {action} {btc_quantity:.6f} BTC "
            f"@ {price:,.0f} ({amount_krw:,.0f} KRW)"
        )

    def get_metrics(self, current_time: datetime | None = None) -> LiveMetrics | None:
        """Calculate current performance metrics.

        Args:
            current_time: Current time for calculations.

        Returns:
            LiveMetrics or None if not enough data.
        """
        if not self._snapshots or self._initial_value is None:
            return None

        now = current_time or datetime.now()
        latest = self._snapshots[-1]

        # Total return
        total_return = (
            (latest.total_value_krw - self._initial_value) / self._initial_value * 100
        )

        # Max drawdown
        max_dd = self._calculate_max_drawdown()

        # Trade stats
        buy_trades = [t for t in self._trades if t.action == "BUY"]
        sell_trades = [t for t in self._trades if t.action == "SELL"]
        total_fees = sum(t.fee_krw for t in self._trades)

        # Win rate (simplified: compare sell price to preceding buy)
        win_rate = self._calculate_win_rate()

        # Average trade size
        avg_size = (
            sum(t.amount_krw for t in self._trades) / len(self._trades)
            if self._trades
            else 0
        )

        # BTC price change (benchmark)
        btc_change = 0.0
        if self._initial_btc_price and self._initial_btc_price > 0:
            btc_change = (
                (latest.btc_price - self._initial_btc_price)
                / self._initial_btc_price
                * 100
            )

        # Alpha
        alpha = total_return - btc_change

        # Sharpe ratio (simplified daily calculation)
        sharpe = self._calculate_sharpe_ratio()

        return LiveMetrics(
            start_time=self._start_time or now,
            end_time=now,
            initial_value_krw=self._initial_value,
            current_value_krw=latest.total_value_krw,
            total_return_pct=total_return,
            peak_value_krw=self._peak_value,
            max_drawdown_pct=max_dd,
            total_trades=len(self._trades),
            buy_trades=len(buy_trades),
            sell_trades=len(sell_trades),
            total_fees_krw=total_fees,
            win_rate_pct=win_rate,
            avg_trade_size_krw=avg_size,
            btc_price_change_pct=btc_change,
            alpha_pct=alpha,
            sharpe_ratio=sharpe,
            cycles_run=latest.cycle_count,
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from snapshots."""
        if not self._snapshots:
            return 0.0

        peak = self._snapshots[0].total_value_krw
        max_dd = 0.0

        for snapshot in self._snapshots:
            if snapshot.total_value_krw > peak:
                peak = snapshot.total_value_krw
            else:
                dd = (peak - snapshot.total_value_krw) / peak * 100
                max_dd = max(max_dd, dd)

        return max_dd

    def _calculate_win_rate(self) -> float:
        """Calculate win rate from trades."""
        if not self._trades:
            return 0.0

        # Pair buys with sells (FIFO)
        buys = [t for t in self._trades if t.action == "BUY"]
        sells = [t for t in self._trades if t.action == "SELL"]

        if not buys or not sells:
            return 0.0

        wins = 0
        total_pairs = 0
        buy_queue = list(buys)

        for sell in sells:
            if buy_queue:
                buy = buy_queue.pop(0)
                if sell.price > buy.price:
                    wins += 1
                total_pairs += 1

        return (wins / total_pairs * 100) if total_pairs > 0 else 0.0

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.035) -> float:
        """Calculate Sharpe ratio from snapshots."""
        if len(self._snapshots) < 2:
            return 0.0

        # Calculate returns
        returns = []
        for i in range(1, len(self._snapshots)):
            prev = self._snapshots[i - 1].total_value_krw
            curr = self._snapshots[i].total_value_krw
            if prev > 0:
                returns.append((curr - prev) / prev)

        if not returns:
            return 0.0

        # Mean and std
        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)

        if std == 0:
            return 0.0

        # Annualize (assuming 5-minute intervals, ~105,120 periods/year)
        periods_per_year = 365 * 24 * 60 / self.config.snapshot_interval_minutes
        annualized_return = mean_return * periods_per_year
        annualized_std = std * math.sqrt(periods_per_year)

        return (annualized_return - risk_free_rate) / annualized_std

    def _append_snapshot_to_file(self, snapshot: PortfolioSnapshot) -> None:
        """Append snapshot to JSONL file."""
        path = self.config.log_dir / self.config.snapshot_file
        try:
            with open(path, "a") as f:
                f.write(json.dumps(snapshot.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to write snapshot: {e}")

    def save_metrics(self, metrics: LiveMetrics | None = None) -> None:
        """Save current metrics to JSON file.

        Args:
            metrics: Metrics to save (calculates if None).
        """
        if metrics is None:
            metrics = self.get_metrics()

        if metrics is None:
            return

        path = self.config.log_dir / self.config.metrics_file
        try:
            with open(path, "w") as f:
                json.dump(metrics.to_dict(), f, indent=2)
            logger.info(f"Metrics saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def generate_report(
        self,
        date: datetime | None = None,
        metrics: LiveMetrics | None = None,
    ) -> str:
        """Generate daily performance report.

        Args:
            date: Report date.
            metrics: Metrics to use (calculates if None).

        Returns:
            Markdown report string.
        """
        if metrics is None:
            metrics = self.get_metrics()

        if metrics is None:
            return "# Performance Report\n\nNo data available."

        report_date = date or datetime.now()
        duration_hours = (metrics.end_time - metrics.start_time).total_seconds() / 3600

        # Get recent trades
        recent_trades = self._trades[-10:] if self._trades else []

        report = f"""# Daily Performance Report

**Date**: {report_date.strftime('%Y-%m-%d %H:%M')}
**Duration**: {duration_hours:.1f} hours ({metrics.cycles_run} cycles)

---

## Portfolio Summary

| Metric | Value |
|--------|-------|
| Initial Value | {metrics.initial_value_krw:,.0f} KRW |
| Current Value | {metrics.current_value_krw:,.0f} KRW |
| **Total Return** | **{metrics.total_return_pct:+.2f}%** |
| Peak Value | {metrics.peak_value_krw:,.0f} KRW |
| Max Drawdown | {metrics.max_drawdown_pct:.2f}% |

---

## Benchmark Comparison

| Metric | Strategy | Buy & Hold | Difference |
|--------|----------|------------|------------|
| Return | {metrics.total_return_pct:+.2f}% | {metrics.btc_price_change_pct:+.2f}% | **{metrics.alpha_pct:+.2f}%** |

---

## Trading Activity

| Metric | Value |
|--------|-------|
| Total Trades | {metrics.total_trades} |
| Buy Orders | {metrics.buy_trades} |
| Sell Orders | {metrics.sell_trades} |
| Total Fees | {metrics.total_fees_krw:,.0f} KRW |
| Avg Trade Size | {metrics.avg_trade_size_krw:,.0f} KRW |
| Win Rate | {metrics.win_rate_pct:.1f}% |

---

## Risk Metrics

| Metric | Value |
|--------|-------|
| Sharpe Ratio | {metrics.sharpe_ratio:.2f} |
| Max Drawdown | {metrics.max_drawdown_pct:.2f}% |

---

## Recent Trades

"""
        if recent_trades:
            report += "| Time | Action | Quantity | Price | Amount |\n"
            report += "|------|--------|----------|-------|--------|\n"
            for trade in recent_trades:
                report += (
                    f"| {trade.timestamp.strftime('%m-%d %H:%M')} "
                    f"| {trade.action} "
                    f"| {trade.btc_quantity:.6f} "
                    f"| {trade.price:,.0f} "
                    f"| {trade.amount_krw:,.0f} |\n"
                )
        else:
            report += "*No trades executed*\n"

        report += f"""
---

*Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        return report

    def save_report(self, date: datetime | None = None) -> Path:
        """Save daily report to file.

        Args:
            date: Report date.

        Returns:
            Path to saved report.
        """
        report_date = date or datetime.now()
        filename = self.config.report_file.format(
            date=report_date.strftime("%Y%m%d")
        )
        path = self.config.log_dir / filename

        report = self.generate_report(date=report_date)

        with open(path, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info(f"Report saved to {path}")
        return path

    def get_summary(self) -> str:
        """Get brief performance summary for logging.

        Returns:
            One-line summary string.
        """
        metrics = self.get_metrics()
        if metrics is None:
            return "No performance data"

        return (
            f"Return: {metrics.total_return_pct:+.2f}% | "
            f"Alpha: {metrics.alpha_pct:+.2f}% | "
            f"MDD: {metrics.max_drawdown_pct:.2f}% | "
            f"Trades: {metrics.total_trades} | "
            f"Win: {metrics.win_rate_pct:.0f}%"
        )


# Module-level singleton
_tracker: PerformanceTracker | None = None


def set_performance_tracker(tracker: PerformanceTracker | None) -> None:
    """Set global performance tracker.

    Args:
        tracker: Tracker instance or None to disable.
    """
    global _tracker
    _tracker = tracker


def get_performance_tracker() -> PerformanceTracker | None:
    """Get global performance tracker.

    Returns:
        Current tracker or None.
    """
    return _tracker
