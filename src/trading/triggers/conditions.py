"""Trigger condition definitions for Layer 1 filtering.

These thresholds determine when to invoke the LLM for trading decisions.
All evaluation happens without LLM cost.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class TriggerThresholds:
    """Configurable thresholds for trigger conditions.

    Reuses concepts from core/anomaly.py but tuned for real-time streaming.

    Attributes:
        price_surge_pct: 24h price surge threshold (default 5.0%).
        price_drop_pct: 24h price drop threshold (default -5.0%).
        price_change_1min_pct: 1-minute price change threshold (default 1.0%).
        price_change_5min_pct: 5-minute price change threshold (default 2.0%).
        volume_spike_multiplier: Volume spike vs average (default 3.0x).
        volume_spike_short_multiplier: Short-term volume spike (default 5.0x).
        rsi_oversold: RSI oversold level (default 30).
        rsi_overbought: RSI overbought level (default 70).
        rsi_extreme_oversold: RSI extreme oversold (default 20).
        rsi_extreme_overbought: RSI extreme overbought (default 80).
        spread_anomaly_pct: Unusual bid-ask spread (default 0.5%).
        volatility_spike_std: Volatility spike in std devs (default 2.0).
    """

    # 24h price thresholds (aligned with anomaly.py)
    price_surge_pct: float = 5.0
    price_drop_pct: float = -5.0

    # Short-term price thresholds (for real-time triggers)
    price_change_1min_pct: float = 1.0
    price_change_5min_pct: float = 2.0

    # Volume thresholds
    volume_spike_multiplier: float = 3.0
    volume_spike_short_multiplier: float = 5.0

    # RSI thresholds (aligned with momentum.py)
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    rsi_extreme_oversold: float = 20.0
    rsi_extreme_overbought: float = 80.0

    # Spread threshold
    spread_anomaly_pct: float = 0.5

    # Volatility (aligned with anomaly.py)
    volatility_spike_std: float = 2.0


@dataclass
class CooldownConfig:
    """Cooldown configuration to prevent LLM call spam.

    Attributes:
        min_interval_seconds: Minimum seconds between LLM calls (default 60).
        post_trade_cooldown_seconds: Extended cooldown after trade (default 300).
        repeat_trigger_multiplier: Multiplier for repeated same-type triggers (default 1.5).
        max_cooldown_seconds: Maximum cooldown cap (default 600).
    """

    min_interval_seconds: float = 60.0
    post_trade_cooldown_seconds: float = 300.0
    repeat_trigger_multiplier: float = 1.5
    max_cooldown_seconds: float = 600.0


@dataclass
class BatchConfig:
    """Event batching configuration.

    Attributes:
        batch_window_seconds: Window to collect events before LLM (default 10).
        min_events_to_trigger: Minimum events needed to trigger (default 1).
        max_events_before_force: Force trigger after this many events (default 5).
        immediate_trigger_severity: Severity that bypasses batching (default "high").
    """

    batch_window_seconds: float = 10.0
    min_events_to_trigger: int = 1
    max_events_before_force: int = 5
    immediate_trigger_severity: Literal["high"] = "high"
