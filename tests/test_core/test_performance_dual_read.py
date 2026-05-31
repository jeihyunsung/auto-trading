"""Phase 5 backward-compat tests: PortfolioSnapshot / TradeRecord /
IndicatorSnapshot must dual-read legacy `btc_*` JSONL rows from the BTC
live bot (logs/portfolio_snapshots.jsonl etc.) while also writing the
new asset_* keys.
"""

from datetime import datetime

import pytest

from trading.core.indicator_history import IndicatorSnapshot
from trading.core.performance import (
    LiveMetrics,
    PortfolioSnapshot,
    TradeRecord,
)


# ---------------------------------------------------------------------------
# PortfolioSnapshot
# ---------------------------------------------------------------------------


def test_portfolio_from_dict_reads_legacy_btc_keys():
    """Live bot's JSONL rows only have btc_* — must still load."""
    legacy_row = {
        "timestamp": "2026-05-23T23:08:37.025438+09:00",
        "total_value_krw": 1_000_000,
        "cash_krw": 699_669,
        "btc_balance": 0.00263,
        "btc_price": 114_875_000,
        "btc_value_krw": 302_120,
        "exposure_pct": 30.2,
        "cycle_count": 42,
    }
    snap = PortfolioSnapshot.from_dict(legacy_row)
    assert snap.asset_balance == 0.00263
    assert snap.asset_price == 114_875_000
    assert snap.asset_value_krw == 302_120
    assert snap.asset_symbol == "BTC"  # default for legacy rows


def test_portfolio_from_dict_prefers_new_asset_keys():
    """When both keys present (transitional rows), new key wins."""
    row = {
        "timestamp": "2026-05-31T00:00:00+09:00",
        "total_value_krw": 1_000_000,
        "cash_krw": 500_000,
        "asset_balance": 1.5,
        "btc_balance": 0.0001,  # stale legacy mirror
        "asset_price": 3_000_000,
        "btc_price": 100,  # stale
        "asset_value_krw": 4_500_000,
        "btc_value_krw": 0.01,
        "asset_symbol": "ETH",
        "exposure_pct": 50.0,
    }
    snap = PortfolioSnapshot.from_dict(row)
    assert snap.asset_balance == 1.5
    assert snap.asset_price == 3_000_000
    assert snap.asset_symbol == "ETH"


def test_portfolio_to_dict_writes_legacy_mirror():
    """to_dict must emit both new and legacy keys."""
    snap = PortfolioSnapshot(
        timestamp=datetime(2026, 5, 31),
        total_value_krw=1_000_000,
        cash_krw=500_000,
        asset_balance=0.5,
        asset_price=2_000_000,
        asset_value_krw=1_000_000,
        exposure_pct=100.0,
        asset_symbol="ETH",
    )
    d = snap.to_dict()
    assert d["asset_balance"] == 0.5
    assert d["btc_balance"] == 0.5  # mirror
    assert d["asset_price"] == 2_000_000
    assert d["btc_price"] == 2_000_000  # mirror
    assert d["asset_symbol"] == "ETH"


def test_portfolio_property_aliases_read_only():
    """`.btc_*` properties must reflect asset_* values."""
    snap = PortfolioSnapshot(
        timestamp=datetime.now(),
        total_value_krw=100,
        cash_krw=50,
        asset_balance=0.1,
        asset_price=500,
        asset_value_krw=50,
        exposure_pct=50.0,
    )
    assert snap.btc_balance == 0.1
    assert snap.btc_price == 500
    assert snap.btc_value_krw == 50


def test_portfolio_round_trip():
    """Save → load round-trip preserves data."""
    orig = PortfolioSnapshot(
        timestamp=datetime(2026, 5, 31, 12, 0),
        total_value_krw=1_234_567,
        cash_krw=600_000,
        asset_balance=0.00263,
        asset_price=114_875_000,
        asset_value_krw=302_120,
        exposure_pct=24.5,
        cycle_count=99,
        asset_symbol="BTC",
    )
    restored = PortfolioSnapshot.from_dict(orig.to_dict())
    assert restored.asset_balance == orig.asset_balance
    assert restored.asset_price == orig.asset_price
    assert restored.asset_symbol == orig.asset_symbol


# ---------------------------------------------------------------------------
# TradeRecord
# ---------------------------------------------------------------------------


def test_trade_from_dict_reads_legacy_btc_quantity():
    legacy = {
        "timestamp": "2026-05-25T12:00:00+09:00",
        "action": "BUY",
        "btc_quantity": 0.001,
        "price": 100_000_000,
        "amount_krw": 100_000,
        "fee_krw": 50,
        "confidence": 0.7,
    }
    tr = TradeRecord.from_dict(legacy)
    assert tr.asset_quantity == 0.001
    assert tr.asset_symbol == "BTC"
    assert tr.btc_quantity == 0.001  # alias


def test_trade_to_dict_mirrors_quantity():
    tr = TradeRecord(
        timestamp=datetime(2026, 5, 31),
        action="SELL",
        asset_quantity=0.5,
        asset_symbol="ETH",
        price=3_000_000,
        amount_krw=1_500_000,
        fee_krw=750,
        confidence=0.8,
        rationale="test",
    )
    d = tr.to_dict()
    assert d["asset_quantity"] == 0.5
    assert d["btc_quantity"] == 0.5  # mirror
    assert d["asset_symbol"] == "ETH"


# ---------------------------------------------------------------------------
# IndicatorSnapshot
# ---------------------------------------------------------------------------


def test_indicator_from_dict_reads_legacy_btc_price():
    legacy = {
        "timestamp": "2026-05-30T15:00:00+09:00",
        "btc_price": 113_252_000,
        "rsi": 84.85,
        "macd_line": 100.0,
        "macd_signal": 50.0,
        "macd_histogram": 50.0,
        "trend": "bullish",
        "momentum": "overbought",
        "volatility": "medium",
        "cycle_count": 100,
    }
    ind = IndicatorSnapshot.from_dict(legacy)
    assert ind.asset_price == 113_252_000
    assert ind.asset_symbol == "BTC"
    assert ind.btc_price == 113_252_000  # alias


def test_indicator_to_dict_mirrors():
    ind = IndicatorSnapshot(
        timestamp=datetime(2026, 5, 31),
        asset_price=3_000_000,
        asset_symbol="ETH",
        rsi=50.0,
        macd_line=0.0,
        macd_signal=0.0,
        macd_histogram=0.0,
        trend="neutral",
        momentum="neutral",
        volatility="medium",
        cycle_count=1,
    )
    d = ind.to_dict()
    assert d["asset_price"] == 3_000_000
    assert d["btc_price"] == 3_000_000  # mirror
    assert d["asset_symbol"] == "ETH"


# ---------------------------------------------------------------------------
# LiveMetrics
# ---------------------------------------------------------------------------


def test_live_metrics_btc_price_change_alias():
    """btc_price_change_pct property alias for asset_price_change_pct."""
    m = LiveMetrics(
        start_time=datetime(2026, 5, 1),
        end_time=datetime(2026, 5, 31),
        initial_value_krw=1_000_000,
        current_value_krw=1_050_000,
        total_return_pct=5.0,
        peak_value_krw=1_100_000,
        max_drawdown_pct=2.0,
        total_trades=10,
        buy_trades=5,
        sell_trades=5,
        total_fees_krw=500,
        win_rate_pct=60.0,
        avg_trade_size_krw=100_000,
        asset_price_change_pct=3.0,
        alpha_pct=2.0,
        sharpe_ratio=1.5,
        cycles_run=100,
        asset_symbol="ETH",
    )
    assert m.btc_price_change_pct == 3.0  # alias
    d = m.to_dict()
    assert d["asset_price_change_pct"] == 3.0
    assert d["btc_price_change_pct"] == 3.0  # legacy mirror
    assert d["asset_symbol"] == "ETH"
