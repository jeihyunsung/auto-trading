"""Event data models for the streaming system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class EventType(str, Enum):
    """Types of market events from WebSocket."""

    PRICE_UPDATE = "price_update"
    TRADE = "trade"
    ORDERBOOK = "orderbook"


class TriggerType(str, Enum):
    """Types of trigger conditions that invoke LLM."""

    PRICE_SURGE = "price_surge"
    PRICE_DROP = "price_drop"
    VOLUME_SPIKE = "volume_spike"
    RSI_EXTREME = "rsi_extreme"
    SPREAD_ANOMALY = "spread_anomaly"
    MULTI_CONDITION = "multi_condition"


@dataclass
class MarketEvent:
    """Raw market event from WebSocket stream.

    Attributes:
        event_type: Type of market event.
        symbol: Trading pair (e.g., KRW-BTC).
        timestamp: Event timestamp.
        price: Current price (for ticker/trade events).
        prev_price: Previous price for change calculation.
        volume: 24h volume.
        trade_volume: Individual trade volume.
        change_rate: 24h change rate percentage.
        bid_price: Best bid price.
        ask_price: Best ask price.
        spread_pct: Bid-ask spread percentage.
    """

    event_type: EventType
    symbol: str
    timestamp: datetime
    price: float | None = None
    prev_price: float | None = None
    volume: float | None = None
    trade_volume: float | None = None
    change_rate: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    spread_pct: float | None = None


@dataclass
class TriggerEvent:
    """Trigger event that fires LLM decision.

    Created when rule-based conditions are met in Layer 1.
    Passed to Layer 2 (LLM) for trading decision.

    Attributes:
        trigger_type: Type of trigger condition.
        symbol: Trading pair.
        severity: Impact level (low/medium/high).
        value: Actual value that triggered.
        threshold: Threshold that was exceeded.
        description: Human-readable description.
        source_events: Original market events that caused trigger.
        timestamp: When trigger was created.
    """

    trigger_type: TriggerType
    symbol: str
    severity: Literal["low", "medium", "high"]
    value: float
    threshold: float
    description: str
    source_events: list[MarketEvent] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_anomaly_dict(self) -> dict:
        """Convert to state anomaly format for LangGraph compatibility.

        Returns:
            Dict matching the Anomaly TypedDict schema.
        """
        return {
            "type": self.trigger_type.value,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass
class EventBatch:
    """Batch of trigger events collected over a time window.

    Used by EventDispatcher to group events before LLM invocation.

    Attributes:
        events: List of trigger events in this batch.
        window_start: Start of collection window.
        window_end: End of collection window.
        symbol: Trading pair for this batch.
    """

    events: list[TriggerEvent]
    window_start: datetime
    window_end: datetime
    symbol: str

    @property
    def highest_severity(self) -> Literal["low", "medium", "high"]:
        """Get the highest severity level in the batch.

        Returns:
            Highest severity among all events.
        """
        severity_order = {"high": 3, "medium": 2, "low": 1}
        if not self.events:
            return "low"
        return max(
            self.events, key=lambda e: severity_order.get(e.severity, 0)
        ).severity

    @property
    def trigger_types(self) -> list[str]:
        """Get unique trigger types in this batch.

        Returns:
            List of trigger type values.
        """
        return list({e.trigger_type.value for e in self.events})

    @property
    def duration_seconds(self) -> float:
        """Get batch window duration in seconds.

        Returns:
            Duration from window_start to window_end.
        """
        return (self.window_end - self.window_start).total_seconds()
