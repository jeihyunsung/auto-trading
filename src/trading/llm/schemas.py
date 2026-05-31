"""Pydantic schemas for LLM input/output."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


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


class RiskValidationInput(BaseModel):
    """Input for risk validation."""

    # Proposed trade
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    suggested_size: float
    rationale: str

    # Portfolio
    krw_balance: float
    asset_balance: float = Field(
        validation_alias=AliasChoices("asset_balance", "btc_balance"),
        description="Held-asset balance (BTC/ETH/XRP). Accepts legacy "
                    "btc_balance key for backward compatibility.",
    )
    asset_symbol: str = "BTC"
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


