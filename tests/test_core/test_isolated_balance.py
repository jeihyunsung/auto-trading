"""Tests for IsolatedBalance asset-agnostic refactor.

Focuses on backward compatibility: BTC live bot's existing JSON must
load and round-trip without losing balance or symbol context.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from trading.core.isolated_balance import IsolatedBalance, IsolatedBalanceTracker


# ---------------------------------------------------------------------------
# IsolatedBalance dataclass — dual-read + legacy mirror
# ---------------------------------------------------------------------------


def test_from_dict_reads_legacy_btc_key():
    """Live BTC bot's JSON only has 'btc' key — must still load."""
    legacy = {
        "krw": "699669.66",
        "btc": "0.00263",
        "initial_capital": "1000000.0",
    }
    bal = IsolatedBalance.from_dict(legacy)
    assert bal.asset_balance == Decimal("0.00263")
    assert bal.asset_symbol == "BTC"  # default for legacy files
    assert bal.krw == Decimal("699669.66")


def test_from_dict_prefers_new_asset_balance_key():
    """When both keys present (transition state), new key wins."""
    data = {
        "krw": "100000",
        "asset_balance": "1.5",
        "btc": "0.0001",  # stale mirror
        "asset_symbol": "ETH",
        "initial_capital": "100000",
    }
    bal = IsolatedBalance.from_dict(data)
    assert bal.asset_balance == Decimal("1.5")
    assert bal.asset_symbol == "ETH"


def test_to_dict_writes_legacy_mirror():
    """to_dict must emit both new and legacy keys for backward compat."""
    bal = IsolatedBalance(
        krw=Decimal("100000"),
        asset_balance=Decimal("0.5"),
        asset_symbol="ETH",
        initial_capital=Decimal("100000"),
    )
    d = bal.to_dict()
    assert d["asset_balance"] == "0.5"
    assert d["btc"] == "0.5"  # legacy mirror tracks asset_balance
    assert d["asset_symbol"] == "ETH"


def test_round_trip_preserves_balance():
    """Save → load round-trip must not lose precision or symbol."""
    original = IsolatedBalance(
        krw=Decimal("699669.66"),
        asset_balance=Decimal("0.00263"),
        asset_symbol="BTC",
        initial_capital=Decimal("1000000.0"),
    )
    restored = IsolatedBalance.from_dict(original.to_dict())
    assert restored.asset_balance == original.asset_balance
    assert restored.asset_symbol == original.asset_symbol
    assert restored.krw == original.krw


def test_legacy_btc_property_is_alias():
    """`.btc` property must reflect asset_balance both ways."""
    bal = IsolatedBalance(
        krw=Decimal("0"),
        asset_balance=Decimal("0.1"),
        initial_capital=Decimal("0"),
    )
    assert bal.btc == Decimal("0.1")
    bal.btc = Decimal("0.2")
    assert bal.asset_balance == Decimal("0.2")


# ---------------------------------------------------------------------------
# IsolatedBalanceTracker — file path, asset routing, legacy kwargs
# ---------------------------------------------------------------------------


def test_tracker_loads_btc_live_state_file(tmp_path):
    """Replay the actual logs/isolated_balance.json schema."""
    state_file = tmp_path / "isolated_balance.json"
    state_file.write_text(json.dumps({
        "krw": "699669.66",
        "btc": "0.00263",
        "initial_capital": "1000000.0",
        "total_invested": "300180.24",
        "total_fees": "150.09",
        "created_at": "2026-05-23T23:08:37.025438+09:00",
        "last_updated": "2026-05-24T06:15:09.142465+09:00",
        "daily_start_value": "1000000.0",
        "daily_start_date": "2026-05-24",
    }))
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=1_000_000,
        state_file=state_file,
        asset_symbol="BTC",
    )
    assert tracker.get_asset_balance() == Decimal("0.00263")
    assert tracker.get_btc_balance() == Decimal("0.00263")  # legacy alias
    assert tracker.asset_symbol == "BTC"


def test_tracker_rejects_asset_mismatch(tmp_path):
    """ETH tracker pointed at a BTC state file must refuse to start."""
    state_file = tmp_path / "isolated_balance.json"
    state_file.write_text(json.dumps({
        "krw": "100000",
        "btc": "0.01",
        "initial_capital": "100000",
    }))
    with pytest.raises(RuntimeError, match="BTC.*ETH"):
        IsolatedBalanceTracker(
            initial_capital_krw=100_000,
            state_file=state_file,
            asset_symbol="ETH",
        )


def test_get_balances_uses_asset_symbol_key(tmp_path):
    """get_balances() must key by the tracker's asset, not literal 'BTC'."""
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=tmp_path / "state.json",
        asset_symbol="XRP",
    )
    balances = tracker.get_balances()
    assert "XRP" in balances
    assert "BTC" not in balances
    assert balances["KRW"] == Decimal("100000")


def test_record_buy_accepts_legacy_btc_received_kwarg(tmp_path):
    """Phase 2 must not break callers still using btc_received=."""
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=tmp_path / "state.json",
        asset_symbol="ETH",
    )
    ok = tracker.record_buy(
        krw_spent=Decimal("10000"),
        btc_received=Decimal("0.005"),  # legacy kwarg
        fee_krw=Decimal("5"),
    )
    assert ok is True
    assert tracker.get_asset_balance() == Decimal("0.005")


def test_record_buy_accepts_new_asset_received_kwarg(tmp_path):
    """New asset_received= path also works."""
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=tmp_path / "state.json",
        asset_symbol="ETH",
    )
    ok = tracker.record_buy(
        krw_spent=Decimal("10000"),
        asset_received=Decimal("0.005"),
        fee_krw=Decimal("5"),
    )
    assert ok is True
    assert tracker.get_asset_balance() == Decimal("0.005")


def test_record_sell_accepts_legacy_btc_sold_kwarg(tmp_path):
    """SELL legacy kwarg too."""
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=tmp_path / "state.json",
        asset_symbol="ETH",
    )
    tracker.record_buy(
        krw_spent=Decimal("10000"),
        asset_received=Decimal("0.005"),
        fee_krw=Decimal("5"),
    )
    ok = tracker.record_sell(
        btc_sold=Decimal("0.002"),  # legacy
        krw_received=Decimal("5000"),
        fee_krw=Decimal("3"),
    )
    assert ok is True
    assert tracker.get_asset_balance() == Decimal("0.003")


def test_portfolio_value_legacy_btc_price_kwarg(tmp_path):
    """get_portfolio_value must accept btc_price= for now."""
    tracker = IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=tmp_path / "state.json",
        asset_symbol="ETH",
    )
    tracker.record_buy(
        krw_spent=Decimal("10000"),
        asset_received=Decimal("0.01"),
        fee_krw=Decimal("0"),
    )
    pv_legacy = tracker.get_portfolio_value(btc_price=3_000_000)
    pv_new = tracker.get_portfolio_value(asset_price=3_000_000)
    assert pv_legacy["total_value_krw"] == pv_new["total_value_krw"]
    # Both new and legacy keys present
    assert pv_legacy["asset_balance"] == pv_legacy["btc_balance"]
    assert pv_legacy["asset_value_krw"] == pv_legacy["btc_value_krw"]
    assert pv_legacy["asset_symbol"] == "ETH"


def test_new_state_file_has_asset_symbol(tmp_path):
    """Fresh ETH tracker must persist asset_symbol so reload doesn't drift."""
    state_file = tmp_path / "state.json"
    IsolatedBalanceTracker(
        initial_capital_krw=100_000,
        state_file=state_file,
        asset_symbol="XRP",
    )
    data = json.loads(state_file.read_text())
    assert data["asset_symbol"] == "XRP"
    assert data["asset_balance"] == "0"
    assert data["btc"] == "0"  # legacy mirror present
