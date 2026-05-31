"""Phase 6 — LLM prompt + schema asset-symbol substitution.

The prompts now carry {asset_symbol} placeholders so an ETH/XRP bot does
not present itself to gpt-5-nano as a "BTC trading decision agent". The
SYSTEM prompts use str.replace() (not .format()) because their body
contains illustrative `{실제값}` Korean placeholders that aren't
template variables.
"""

import pytest

from trading.llm.prompts import (
    DECISION_SYSTEM_PROMPT,
    DECISION_USER_PROMPT,
    RISK_VALIDATION_SYSTEM_PROMPT,
    RISK_VALIDATION_USER_PROMPT,
)
from trading.llm.schemas import RiskValidationInput


@pytest.mark.parametrize("symbol", ["BTC", "ETH", "XRP"])
def test_decision_system_prompt_substitutes_asset_symbol(symbol):
    """System prompt must self-identify by the asset symbol."""
    rendered = DECISION_SYSTEM_PROMPT.replace("{asset_symbol}", symbol)
    assert f"You are a {symbol} trading decision agent." in rendered
    rapid = next(
        line for line in rendered.split("\n") if "consider SELL immediately" in line
    )
    assert symbol in rapid


@pytest.mark.parametrize("symbol", ["BTC", "ETH", "XRP"])
def test_risk_validation_system_prompt_substitutes(symbol):
    rendered = RISK_VALIDATION_SYSTEM_PROMPT.replace("{asset_symbol}", symbol)
    assert f"Risk Manager for a {symbol} trading system" in rendered


def test_decision_user_prompt_renders_asset_balance_line():
    """Portfolio section must show the asset ticker, not always 'BTC'."""
    rendered = DECISION_USER_PROMPT.format(
        asset_symbol="ETH",
        symbol="KRW-ETH",
        current_price=3_000_000,
        change_24h=1.5,
        volatility_level="medium",
        oi_value=0,
        oi_change_1h=0,
        oi_change_24h=0,
        oi_trend="stable",
        long_short_ratio=1.0,
        top_trader_ls=1.0,
        position_bias="balanced",
        funding_rate=0.0001,
        funding_signal="neutral",
        trend="bullish",
        momentum="neutral",
        rsi=55,
        macd_histogram=10,
        channel_slope_deg=2.0,
        channel_slope_dir="up",
        channel_position=0.5,
        channel_width=2.0,
        breakout_risk="low",
        support_levels="2,900,000",
        resistance_levels="3,100,000",
        pattern_name="none",
        pattern_direction="neutral",
        pattern_confidence=0.0,
        pattern_description="none",
        krw_balance=500_000,
        asset_balance=0.05,
        exposure=30,
        unrealized_pnl=1.5,
        max_position=50,
        max_daily_loss=3,
        daily_pnl=0.2,
        anomalies="None",
        decision_history="No recent",
    )
    assert "ETH Balance: 0.05000000" in rendered
    assert "Symbol: KRW-ETH" in rendered


def test_risk_validation_user_prompt_renders_asset_balance_line():
    rendered = RISK_VALIDATION_USER_PROMPT.format(
        asset_symbol="XRP",
        action="SELL",
        confidence=0.8,
        suggested_size=15,
        rationale="test",
        krw_balance=300_000,
        asset_balance=200.0,
        current_exposure=40,
        max_position=50,
        max_daily_loss=3,
        daily_pnl=0,
        min_order=5000,
        kill_switch="OFF",
        volatility="medium",
        anomaly_count=0,
    )
    assert "XRP Balance: 200.00000000" in rendered


def test_risk_validation_input_accepts_legacy_btc_balance_kwarg():
    """Pydantic alias must accept old btc_balance= construction."""
    obj = RiskValidationInput(
        action="BUY",
        confidence=0.7,
        suggested_size=10,
        rationale="test",
        krw_balance=1_000_000,
        btc_balance=0.001,  # legacy
        current_exposure=10,
        max_position=50,
        max_daily_loss=3,
        daily_pnl=0,
        min_order=5000,
        kill_switch=False,
        volatility="medium",
        anomaly_count=0,
    )
    assert obj.asset_balance == 0.001
    assert obj.asset_symbol == "BTC"  # default


def test_risk_validation_input_accepts_new_asset_balance_kwarg():
    """New explicit asset_balance + asset_symbol path."""
    obj = RiskValidationInput(
        action="BUY",
        confidence=0.7,
        suggested_size=10,
        rationale="test",
        krw_balance=1_000_000,
        asset_balance=0.5,
        asset_symbol="ETH",
        current_exposure=30,
        max_position=50,
        max_daily_loss=3,
        daily_pnl=0,
        min_order=5000,
        kill_switch=False,
        volatility="medium",
        anomaly_count=0,
    )
    assert obj.asset_balance == 0.5
    assert obj.asset_symbol == "ETH"
