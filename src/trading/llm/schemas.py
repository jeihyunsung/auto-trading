"""Pydantic schemas for LLM input/output."""

from typing import Literal

from pydantic import BaseModel, Field


class LLMDecisionInput(BaseModel):
    """Input data for LLM decision making."""

    # Market data
    symbol: str
    current_price: float
    change_24h: float
    volatility_level: Literal["low", "medium", "high"]

    # News context
    sentiment: float = Field(ge=-1.0, le=1.0)
    news_impact: Literal["low", "medium", "high"]
    news_summary: str

    # Technical indicators
    trend: Literal["bullish", "bearish", "neutral"]
    momentum: Literal["overbought", "oversold", "neutral"]
    rsi: float
    macd_histogram: float | None

    # Portfolio
    krw_balance: float
    btc_balance: float
    exposure: float
    unrealized_pnl: float

    # Risk constraints
    max_position: float
    max_daily_loss: float
    daily_pnl: float

    # Anomalies
    anomalies: str


class LLMDecisionOutput(BaseModel):
    """Output from LLM trading decision."""

    action: Literal["BUY", "SELL", "HOLD"] = Field(
        description="Trading action to take"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence level from 0 to 1"
    )
    rationale: str = Field(
        description="Explanation for the decision"
    )
    key_factors: list[str] = Field(
        description="Key factors influencing the decision"
    )


class NewsAnalysisOutput(BaseModel):
    """Output from news sentiment analysis."""

    sentiment: float = Field(
        ge=-1.0, le=1.0,
        description="Sentiment score from -1 (negative) to 1 (positive)"
    )
    impact: Literal["low", "medium", "high"] = Field(
        description="Potential market impact level"
    )
    summary: str = Field(
        description="Brief summary of news themes"
    )


class RiskValidationInput(BaseModel):
    """Input for risk validation."""

    # Proposed trade
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    suggested_size: float
    rationale: str

    # Portfolio
    krw_balance: float
    btc_balance: float
    current_exposure: float

    # Risk limits
    max_position: float
    max_daily_loss: float
    daily_pnl: float
    min_order: float
    kill_switch: bool

    # Market conditions
    volatility: Literal["low", "medium", "high"]
    anomaly_count: int


class RiskValidationOutput(BaseModel):
    """Output from risk validation."""

    approved: bool = Field(
        description="Whether the trade is approved"
    )
    adjusted_size_pct: float = Field(
        ge=0.0, le=100.0,
        description="Adjusted position size percentage"
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Reason for rejection if not approved"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Risk warnings to consider"
    )


class SupervisorOutput(BaseModel):
    """Output from supervisor routing decision."""

    next_agent: Literal[
        "market_agent",
        "news_agent",
        "indicator_agent",
        "analysis_agent",
        "risk_agent",
        "execution_agent",
        "FINISH",
    ] = Field(description="Next agent to invoke")
    reason: str = Field(description="Brief reason for selection")
