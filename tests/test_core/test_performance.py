"""Tests for performance tracking module."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trading.core.performance import (
    LiveMetrics,
    PerformanceConfig,
    PerformanceTracker,
    PortfolioSnapshot,
    TradeRecord,
    get_performance_tracker,
    set_performance_tracker,
)


class TestPerformanceConfig:
    """Tests for PerformanceConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PerformanceConfig()

        assert config.snapshot_interval_minutes == 5
        assert config.log_dir == Path("logs")
        assert config.snapshot_file == "portfolio_snapshots.jsonl"

    def test_custom_config(self):
        """Test custom configuration."""
        config = PerformanceConfig(
            snapshot_interval_minutes=10,
            log_dir=Path("/tmp/logs"),
        )

        assert config.snapshot_interval_minutes == 10
        assert config.log_dir == Path("/tmp/logs")


class TestPortfolioSnapshot:
    """Tests for PortfolioSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test snapshot creation."""
        now = datetime.now()
        snapshot = PortfolioSnapshot(
            timestamp=now,
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            btc_value_krw=5_000_000,
            exposure_pct=50.0,
            cycle_count=10,
        )

        assert snapshot.timestamp == now
        assert snapshot.total_value_krw == 10_000_000
        assert snapshot.cash_krw == 5_000_000
        assert snapshot.btc_balance == 0.05
        assert snapshot.btc_price == 100_000_000
        assert snapshot.btc_value_krw == 5_000_000
        assert snapshot.exposure_pct == 50.0
        assert snapshot.cycle_count == 10

    def test_snapshot_to_dict(self):
        """Test snapshot serialization."""
        now = datetime.now()
        snapshot = PortfolioSnapshot(
            timestamp=now,
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            btc_value_krw=5_000_000,
            exposure_pct=50.0,
            cycle_count=10,
        )

        d = snapshot.to_dict()
        assert d["timestamp"] == now.isoformat()
        assert d["total_value_krw"] == 10_000_000
        assert d["btc_balance"] == 0.05
        assert d["btc_value_krw"] == 5_000_000
        assert d["exposure_pct"] == 50.0

    def test_snapshot_from_dict(self):
        """Test snapshot deserialization."""
        now = datetime.now()
        data = {
            "timestamp": now.isoformat(),
            "total_value_krw": 10_000_000,
            "cash_krw": 5_000_000,
            "btc_balance": 0.05,
            "btc_price": 100_000_000,
            "btc_value_krw": 5_000_000,
            "exposure_pct": 50.0,
            "cycle_count": 10,
        }

        snapshot = PortfolioSnapshot.from_dict(data)
        assert snapshot.total_value_krw == 10_000_000
        assert snapshot.cycle_count == 10


class TestTradeRecord:
    """Tests for TradeRecord dataclass."""

    def test_trade_record_creation(self):
        """Test trade record creation."""
        now = datetime.now()
        trade = TradeRecord(
            timestamp=now,
            action="BUY",
            btc_quantity=0.01,
            price=100_000_000,
            amount_krw=1_000_000,
            fee_krw=500,
            confidence=0.75,
            rationale="Test buy",
        )

        assert trade.timestamp == now
        assert trade.action == "BUY"
        assert trade.btc_quantity == 0.01
        assert trade.price == 100_000_000
        assert trade.amount_krw == 1_000_000
        assert trade.fee_krw == 500
        assert trade.confidence == 0.75
        assert trade.rationale == "Test buy"

    def test_trade_record_to_dict(self):
        """Test trade record serialization."""
        now = datetime.now()
        trade = TradeRecord(
            timestamp=now,
            action="SELL",
            btc_quantity=0.02,
            price=105_000_000,
            amount_krw=2_100_000,
            fee_krw=1050,
            confidence=0.8,
            rationale="Test sell",
        )

        d = trade.to_dict()
        assert d["timestamp"] == now.isoformat()
        assert d["action"] == "SELL"
        assert d["btc_quantity"] == 0.02


class TestLiveMetrics:
    """Tests for LiveMetrics dataclass."""

    def test_live_metrics_creation(self):
        """Test live metrics creation."""
        now = datetime.now()
        metrics = LiveMetrics(
            start_time=now - timedelta(hours=24),
            end_time=now,
            initial_value_krw=10_000_000,
            current_value_krw=10_500_000,
            total_return_pct=5.0,
            peak_value_krw=10_600_000,
            max_drawdown_pct=2.0,
            total_trades=10,
            buy_trades=5,
            sell_trades=5,
            total_fees_krw=5000,
            win_rate_pct=60.0,
            avg_trade_size_krw=1_000_000,
            btc_price_change_pct=3.0,
            alpha_pct=2.0,
            sharpe_ratio=1.5,
            cycles_run=100,
        )

        assert metrics.total_return_pct == 5.0
        assert metrics.max_drawdown_pct == 2.0
        assert metrics.sharpe_ratio == 1.5
        assert metrics.alpha_pct == 2.0
        assert metrics.win_rate_pct == 60.0
        assert metrics.total_trades == 10

    def test_live_metrics_to_dict(self):
        """Test live metrics serialization."""
        now = datetime.now()
        metrics = LiveMetrics(
            start_time=now - timedelta(hours=24),
            end_time=now,
            initial_value_krw=10_000_000,
            current_value_krw=10_500_000,
            total_return_pct=5.0,
            peak_value_krw=10_600_000,
            max_drawdown_pct=2.0,
            total_trades=10,
            buy_trades=5,
            sell_trades=5,
            total_fees_krw=5000,
            win_rate_pct=60.0,
            avg_trade_size_krw=1_000_000,
            btc_price_change_pct=3.0,
            alpha_pct=2.0,
            sharpe_ratio=1.5,
            cycles_run=100,
        )

        d = metrics.to_dict()
        assert d["total_return_pct"] == 5.0
        assert d["total_trades"] == 10
        assert d["duration_hours"] == pytest.approx(24.0, rel=0.01)


class TestPerformanceTracker:
    """Tests for PerformanceTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create tracker with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PerformanceConfig(
                snapshot_interval_minutes=1,
                log_dir=Path(tmpdir),
            )
            tracker = PerformanceTracker(config)
            yield tracker

    def test_start_tracking(self, tracker):
        """Test starting performance tracking."""
        tracker.start(
            initial_value_krw=10_000_000,
            btc_price=100_000_000,
        )

        assert tracker._start_time is not None
        assert tracker._initial_value == 10_000_000
        assert tracker._initial_btc_price == 100_000_000

    def test_record_snapshot(self, tracker):
        """Test recording portfolio snapshot."""
        tracker.start(10_000_000, 100_000_000)

        recorded = tracker.record_snapshot(
            total_value_krw=10_500_000,
            cash_krw=5_000_000,
            btc_balance=0.055,
            btc_price=100_000_000,
            cycle_count=1,
            force=True,
        )

        assert recorded is True
        assert len(tracker._snapshots) == 1
        assert tracker._snapshots[0].total_value_krw == 10_500_000

    def test_record_snapshot_respects_interval(self, tracker):
        """Test that snapshot respects interval without force."""
        tracker.start(10_000_000, 100_000_000)

        # First snapshot
        tracker.record_snapshot(
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            cycle_count=1,
            force=True,
        )

        # Second snapshot immediately (should be skipped without force)
        recorded = tracker.record_snapshot(
            total_value_krw=10_100_000,
            cash_krw=5_000_000,
            btc_balance=0.051,
            btc_price=100_000_000,
            cycle_count=2,
            force=False,
        )

        assert recorded is False
        assert len(tracker._snapshots) == 1

    def test_record_trade(self, tracker):
        """Test recording a trade."""
        tracker.start(10_000_000, 100_000_000)

        tracker.record_trade(
            action="BUY",
            btc_quantity=0.01,
            price=100_000_000,
            amount_krw=1_000_000,
            fee_krw=500,
            confidence=0.75,
            rationale="Test buy",
        )

        assert len(tracker._trades) == 1
        assert tracker._trades[0].action == "BUY"
        assert tracker._trades[0].btc_quantity == 0.01

    def test_get_metrics_no_snapshots(self, tracker):
        """Test get_metrics returns None with no data."""
        tracker.start(10_000_000, 100_000_000)
        metrics = tracker.get_metrics()
        assert metrics is None

    def test_get_metrics_with_data(self, tracker):
        """Test get_metrics calculation."""
        now = datetime.now()
        tracker.start(10_000_000, 100_000_000, start_time=now)

        # Add snapshots showing 5% gain
        tracker.record_snapshot(
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            cycle_count=1,
            current_time=now,
            force=True,
        )

        tracker.record_snapshot(
            total_value_krw=10_500_000,
            cash_krw=5_250_000,
            btc_balance=0.05,
            btc_price=105_000_000,
            cycle_count=2,
            current_time=now + timedelta(hours=24),
            force=True,
        )

        metrics = tracker.get_metrics(current_time=now + timedelta(hours=24))

        assert metrics is not None
        assert metrics.total_return_pct == pytest.approx(5.0, rel=0.01)
        assert metrics.total_trades == 0
        duration_hours = (metrics.end_time - metrics.start_time).total_seconds() / 3600
        assert duration_hours == pytest.approx(24.0, rel=0.01)

    def test_max_drawdown_calculation(self, tracker):
        """Test max drawdown calculation."""
        now = datetime.now()
        tracker.start(10_000_000, 100_000_000, start_time=now)

        # Peak at 11M, then drop to 9.5M (13.6% drawdown from peak)
        snapshots = [
            (10_000_000, 0),
            (11_000_000, 1),  # Peak
            (10_000_000, 2),
            (9_500_000, 3),  # Trough
            (10_200_000, 4),
        ]

        for value, hours in snapshots:
            tracker.record_snapshot(
                total_value_krw=value,
                cash_krw=value // 2,
                btc_balance=0.05,
                btc_price=100_000_000,
                cycle_count=hours + 1,
                current_time=now + timedelta(hours=hours),
                force=True,
            )

        metrics = tracker.get_metrics(current_time=now + timedelta(hours=4))

        # Max drawdown: (11M - 9.5M) / 11M = 13.6%
        assert metrics is not None
        assert metrics.max_drawdown_pct == pytest.approx(13.6, rel=0.1)

    def test_win_rate_calculation(self, tracker):
        """Test win rate calculation."""
        tracker.start(10_000_000, 100_000_000)

        # 2 winning trades, 1 losing trade
        trades = [
            ("BUY", 100_000_000),
            ("SELL", 105_000_000),  # Win
            ("BUY", 105_000_000),
            ("SELL", 103_000_000),  # Loss
            ("BUY", 103_000_000),
            ("SELL", 110_000_000),  # Win
        ]

        for action, price in trades:
            tracker.record_trade(
                action=action,
                btc_quantity=0.01,
                price=price,
                amount_krw=price * 0.01,
                fee_krw=500,
                confidence=0.7,
                rationale="Test",
            )

        # Need snapshots for metrics
        tracker.record_snapshot(
            total_value_krw=10_000_000,
            cash_krw=10_000_000,
            btc_balance=0,
            btc_price=100_000_000,
            force=True,
        )

        metrics = tracker.get_metrics()

        assert metrics is not None
        assert metrics.total_trades == 6
        # Win rate based on sell price > buy price pairs: 2/3 = 66.7%
        assert metrics.win_rate_pct == pytest.approx(66.7, rel=0.1)

    def test_get_summary(self, tracker):
        """Test get_summary returns string."""
        tracker.start(10_000_000, 100_000_000)
        tracker.record_snapshot(
            total_value_krw=10_500_000,
            cash_krw=5_000_000,
            btc_balance=0.055,
            btc_price=100_000_000,
            force=True,
        )

        summary = tracker.get_summary()

        assert isinstance(summary, str)
        assert "Return:" in summary
        assert "Alpha:" in summary

    def test_save_metrics(self, tracker):
        """Test saving metrics to file."""
        tracker.start(10_000_000, 100_000_000)
        tracker.record_snapshot(
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            force=True,
        )

        tracker.save_metrics()

        # Check metrics JSON file was created
        metrics_path = tracker.config.log_dir / tracker.config.metrics_file
        assert metrics_path.exists()

        # Verify content
        with open(metrics_path) as f:
            data = json.load(f)
            assert data["total_return_pct"] == 0.0

    def test_snapshot_file_created(self, tracker):
        """Test that snapshot file is created on record."""
        tracker.start(10_000_000, 100_000_000)
        tracker.record_snapshot(
            total_value_krw=10_000_000,
            cash_krw=5_000_000,
            btc_balance=0.05,
            btc_price=100_000_000,
            force=True,
        )

        # Check JSONL file was created
        snapshot_path = tracker.config.log_dir / tracker.config.snapshot_file
        assert snapshot_path.exists()

        # Verify content
        with open(snapshot_path) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["total_value_krw"] == 10_000_000

    def test_save_report(self, tracker):
        """Test saving report to file."""
        now = datetime.now()
        tracker.start(10_000_000, 100_000_000, start_time=now)
        tracker.record_snapshot(
            total_value_krw=10_500_000,
            cash_krw=5_000_000,
            btc_balance=0.055,
            btc_price=100_000_000,
            current_time=now + timedelta(hours=1),
            force=True,
        )

        path = tracker.save_report()

        assert path.exists()
        content = path.read_text()
        assert "Daily Performance Report" in content
        assert "Total Return" in content

    def test_generate_report(self, tracker):
        """Test report generation."""
        now = datetime.now()
        tracker.start(10_000_000, 100_000_000, start_time=now)

        tracker.record_snapshot(
            total_value_krw=10_500_000,
            cash_krw=5_000_000,
            btc_balance=0.055,
            btc_price=100_000_000,
            current_time=now + timedelta(hours=1),
            force=True,
        )

        tracker.record_trade(
            action="BUY",
            btc_quantity=0.01,
            price=100_000_000,
            amount_krw=1_000_000,
            fee_krw=500,
            confidence=0.8,
            rationale="Strong bullish signal",
        )

        report = tracker.generate_report()

        assert "# Daily Performance Report" in report
        assert "Total Return" in report
        assert "BUY" in report

    def test_generate_report_no_data(self, tracker):
        """Test report generation with no data."""
        report = tracker.generate_report()
        assert "No data available" in report


class TestModuleSingleton:
    """Tests for module-level singleton."""

    def test_set_and_get_performance_tracker(self):
        """Test setting and getting tracker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PerformanceConfig(log_dir=Path(tmpdir))
            tracker = PerformanceTracker(config)

            set_performance_tracker(tracker)
            assert get_performance_tracker() is tracker

            # Cleanup
            set_performance_tracker(None)

    def test_get_tracker_returns_none_when_not_set(self):
        """Test getting tracker when not set."""
        set_performance_tracker(None)
        assert get_performance_tracker() is None
