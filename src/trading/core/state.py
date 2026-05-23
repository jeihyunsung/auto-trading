"""LangGraph state schema definitions."""

from datetime import datetime
from operator import add
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


class MarketData(TypedDict):
    """Market data state."""

    symbol: str
    current_price: float
    ohlcv: list[dict]
    orderbook: dict | None
    volatility_level: Literal["low", "medium", "high"]
    percent_change_1h: float
    percent_change_24h: float


class PatternAnalysis(TypedDict, total=False):
    """Chart pattern analysis result."""

    pattern: str  # Pattern name (e.g., "double_bottom", "none")
    confidence: float  # 0.0-1.0
    direction: Literal["bullish", "bearish", "neutral"]
    description: str  # Korean description
    source: Literal["vision", "rule_based"]  # How pattern was detected


class TrendChannelData(TypedDict, total=False):
    """Trend channel analysis data."""

    slope: float  # Positive = uptrend
    slope_angle_deg: float
    channel_width_pct: float  # Channel width as % of price
    position_in_channel: float  # 0.0 = lower, 1.0 = upper
    breakout_risk: Literal["high", "medium", "low"]
    support_levels: list[float]
    resistance_levels: list[float]
    r_squared: float  # Regression fit quality
    upper_band: float
    lower_band: float
    midline: float


class IndicatorSignals(TypedDict):
    """Technical indicator signals."""

    trend: Literal["bullish", "bearish", "neutral"]
    momentum: Literal["overbought", "oversold", "neutral"]
    volatility: Literal["low", "medium", "high"]
    signals: dict[str, float]  # RSI, MACD, etc.


class Portfolio(TypedDict):
    """Current portfolio state."""

    cash_krw: float
    btc_balance: float
    avg_entry_price: float
    unrealized_pnl: float
    exposure_pct: float


class RiskState(TypedDict):
    """Risk management state."""

    daily_loss_pct: float
    max_loss_pct: float
    position_limit_pct: float
    is_kill_switch_on: bool


class Decision(TypedDict, total=False):
    """Trading decision."""

    # Required fields
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    suggested_size_pct: float
    rationale: str
    status: Literal["pending", "approved", "rejected", "executed"]

    # Target position based sizing (optional)
    target_position_pct: float  # Target BTC exposure % (0-100)
    position_delta_pct: float  # Change needed: target - current (positive=buy, negative=sell)

    # Optional fields
    original_action: Literal["BUY", "SELL", "HOLD"] | None  # Original action before hysteresis
    bypass_hysteresis: bool  # True to skip hysteresis check (e.g., rapid movement)
    decision_source: Literal["llm", "rule_based", "rapid_move"]  # How the decision was made


class DecisionHistory(TypedDict):
    """Previous decision tracking for hysteresis.

    Used to prevent frequent decision oscillations by requiring
    higher confidence delta to change actions.
    """

    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    timestamp: str  # ISO format
    rationale: str
    cycle_count: int


class Anomaly(TypedDict):
    """Market anomaly."""

    type: str
    severity: Literal["low", "medium", "high"]
    description: str


class DerivativesData(TypedDict, total=False):
    """Binance Futures derivatives data for market sentiment.

    All fields optional since data collection may fail.
    """

    # Open Interest
    open_interest: float  # Total OI in contracts
    open_interest_value: float  # OI value in USDT
    oi_change_pct_1h: float  # OI change % (1 hour)
    oi_change_pct_24h: float  # OI change % (24 hours)

    # Long/Short Ratio
    long_short_ratio: float  # Global long/short ratio
    top_trader_long_short_ratio: float  # Top trader L/S ratio

    # Funding Rate
    funding_rate: float  # Current funding rate (8h)
    next_funding_time: str  # ISO timestamp

    # Derived signals
    oi_trend: Literal["increasing", "decreasing", "stable"]
    position_bias: Literal["long_heavy", "short_heavy", "balanced"]
    funding_signal: Literal["overheated_long", "overheated_short", "neutral"]


class TimeframeTrendData(TypedDict, total=False):
    """Trend data for a single timeframe."""

    timeframe: str  # "5m", "1h", "4h", "1d"
    trend: Literal["bullish", "bearish", "neutral"]
    strength: float  # 0.0 to 1.0
    ema_short: float | None
    ema_long: float | None
    price_vs_ema: float  # % above/below EMA


class MultiTimeframeTrendData(TypedDict, total=False):
    """Multi-timeframe trend analysis data.

    Aggregates trend signals across multiple timeframes to confirm
    trading signals and reduce false positives.
    """

    trends: dict[str, TimeframeTrendData]  # timeframe -> trend data
    aligned: bool  # Are trends aligned?
    alignment_count: int  # How many timeframes agree
    dominant_trend: Literal["bullish", "bearish", "neutral"]
    confidence_adjustment: float  # Adjustment to apply to confidence
    rapid_move_detected: bool  # Short-term rapid movement
    rapid_move_direction: Literal["bullish", "bearish", "neutral"] | None


class MultiTimeframeOHLCV(TypedDict, total=False):
    """OHLCV data for multiple timeframes."""

    ohlcv_5m: list[dict]  # 5-minute candles
    ohlcv_1h: list[dict]  # 1-hour candles
    ohlcv_4h: list[dict]  # 4-hour candles
    ohlcv_1d: list[dict]  # Daily candles


class TradingState(TypedDict):
    """Complete LangGraph state for trading system."""

    # Market data
    market: MarketData | None
    indicators: IndicatorSignals | None
    portfolio: Portfolio | None
    derivatives: DerivativesData | None  # Binance Futures data
    mtf_ohlcv: MultiTimeframeOHLCV | None  # Multi-timeframe OHLCV data
    mtf_trends: MultiTimeframeTrendData | None  # Multi-timeframe trend analysis

    # QuantAgent-style analysis
    pattern_analysis: PatternAnalysis | None  # Chart pattern recognition
    trend_channel: TrendChannelData | None  # Regression channel analysis

    # Risk and decision
    risk: RiskState
    decision: Decision | None
    anomalies: list[Anomaly]

    # Metadata
    messages: Annotated[list, add]  # Agent conversation history
    error: str | None
    cycle_count: int
    last_updated: str  # ISO timestamp


def create_initial_state() -> TradingState:
    """Create initial trading state with defaults."""
    return TradingState(
        market=None,
        indicators=None,
        portfolio=None,
        derivatives=None,
        mtf_ohlcv=None,
        mtf_trends=None,
        pattern_analysis=None,
        trend_channel=None,
        risk=RiskState(
            daily_loss_pct=0.0,
            max_loss_pct=3.0,
            position_limit_pct=50.0,
            is_kill_switch_on=False,
        ),
        decision=None,
        anomalies=[],
        messages=[],
        error=None,
        cycle_count=0,
        last_updated=datetime.now().isoformat(),
    )


class LLMDecisionOutput(BaseModel):
    """Output schema for LLM decision."""

    action: Literal["BUY", "SELL", "HOLD"] = Field(description="Trading action")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level 0-1")
    size_pct: float = Field(
        ge=0.0, le=100.0, description="Suggested position size as % of available capital"
    )
    rationale: str = Field(description="Explanation for the decision")
