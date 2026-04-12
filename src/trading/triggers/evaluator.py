"""Rule-based trigger evaluation (Layer 1 - no LLM cost).

This module evaluates market events against trigger conditions.
Only triggers that pass these rules will invoke the LLM in Layer 2.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque

from trading.events.models import EventType, MarketEvent, TriggerEvent, TriggerType
from trading.triggers.conditions import TriggerThresholds

logger = logging.getLogger(__name__)


@dataclass
class PriceWindow:
    """Sliding window for price history tracking.

    Attributes:
        prices: Deque of (timestamp, price) tuples.
        window_seconds: Time window size in seconds.
    """

    prices: Deque[tuple[datetime, float]] = field(
        default_factory=lambda: deque(maxlen=1000)
    )
    window_seconds: int = 60

    def add(self, timestamp: datetime, price: float) -> None:
        """Add price point and clean old entries.

        Args:
            timestamp: Price timestamp.
            price: Price value.
        """
        self.prices.append((timestamp, price))
        cutoff = timestamp - timedelta(seconds=self.window_seconds)
        while self.prices and self.prices[0][0] < cutoff:
            self.prices.popleft()

    def get_change_pct(self) -> float | None:
        """Calculate percentage change over window.

        Returns:
            Percentage change or None if insufficient data.
        """
        if len(self.prices) < 2:
            return None
        oldest_price = self.prices[0][1]
        newest_price = self.prices[-1][1]
        if oldest_price == 0:
            return None
        return ((newest_price - oldest_price) / oldest_price) * 100


class TriggerEvaluator:
    """Evaluates market events against trigger conditions.

    This is the Layer 1 filter - runs continuously without LLM cost.
    Only triggers that pass these rules will invoke the LLM.
    """

    def __init__(self, thresholds: TriggerThresholds | None = None):
        """Initialize trigger evaluator.

        Args:
            thresholds: Custom thresholds (uses defaults if None).
        """
        self.thresholds = thresholds or TriggerThresholds()

        # Price windows for different timeframes (per symbol)
        self._price_windows: dict[str, dict[int, PriceWindow]] = {}

        # Volume baseline tracking (per symbol)
        self._volume_baseline: dict[str, float] = {}
        self._volume_samples: dict[str, Deque[float]] = {}

    def evaluate(self, event: MarketEvent) -> list[TriggerEvent]:
        """Evaluate market event against all trigger conditions.

        Args:
            event: Incoming market event from WebSocket.

        Returns:
            List of triggered conditions (empty if no triggers).
        """
        triggers: list[TriggerEvent] = []

        if event.event_type == EventType.PRICE_UPDATE:
            triggers.extend(self._evaluate_price_triggers(event))

        if event.event_type == EventType.TRADE:
            triggers.extend(self._evaluate_volume_triggers(event))

        if event.event_type == EventType.ORDERBOOK:
            triggers.extend(self._evaluate_spread_triggers(event))

        return triggers

    def _evaluate_price_triggers(self, event: MarketEvent) -> list[TriggerEvent]:
        """Check price-based trigger conditions.

        Args:
            event: Market event with price data.

        Returns:
            List of price-related triggers.
        """
        triggers = []
        symbol = event.symbol

        if event.price is None:
            return triggers

        # Initialize price windows if needed
        if symbol not in self._price_windows:
            self._price_windows[symbol] = {
                60: PriceWindow(window_seconds=60),
                300: PriceWindow(window_seconds=300),
            }

        # Update all windows
        for window in self._price_windows[symbol].values():
            window.add(event.timestamp, event.price)

        # Check 1-minute change
        change_1m = self._price_windows[symbol][60].get_change_pct()
        if change_1m is not None:
            if change_1m >= self.thresholds.price_change_1min_pct:
                triggers.append(
                    TriggerEvent(
                        trigger_type=TriggerType.PRICE_SURGE,
                        symbol=symbol,
                        severity="medium",
                        value=change_1m,
                        threshold=self.thresholds.price_change_1min_pct,
                        description=f"1분간 {change_1m:.2f}% 급등",
                        source_events=[event],
                    )
                )
            elif change_1m <= -self.thresholds.price_change_1min_pct:
                triggers.append(
                    TriggerEvent(
                        trigger_type=TriggerType.PRICE_DROP,
                        symbol=symbol,
                        severity="medium",
                        value=change_1m,
                        threshold=-self.thresholds.price_change_1min_pct,
                        description=f"1분간 {abs(change_1m):.2f}% 급락",
                        source_events=[event],
                    )
                )

        # Check 5-minute change
        change_5m = self._price_windows[symbol][300].get_change_pct()
        if change_5m is not None:
            threshold = self.thresholds.price_change_5min_pct
            if abs(change_5m) >= threshold:
                severity = (
                    "high"
                    if abs(change_5m) >= self.thresholds.price_surge_pct
                    else "medium"
                )
                trigger_type = (
                    TriggerType.PRICE_SURGE if change_5m > 0 else TriggerType.PRICE_DROP
                )
                direction = "급등" if change_5m > 0 else "급락"
                triggers.append(
                    TriggerEvent(
                        trigger_type=trigger_type,
                        symbol=symbol,
                        severity=severity,
                        value=change_5m,
                        threshold=threshold,
                        description=f"5분간 {abs(change_5m):.2f}% {direction}",
                        source_events=[event],
                    )
                )

        # Check 24h change from event data
        if event.change_rate is not None:
            if event.change_rate >= self.thresholds.price_surge_pct:
                triggers.append(
                    TriggerEvent(
                        trigger_type=TriggerType.PRICE_SURGE,
                        symbol=symbol,
                        severity="high",
                        value=event.change_rate,
                        threshold=self.thresholds.price_surge_pct,
                        description=f"24시간 {event.change_rate:.2f}% 급등",
                        source_events=[event],
                    )
                )
            elif event.change_rate <= self.thresholds.price_drop_pct:
                triggers.append(
                    TriggerEvent(
                        trigger_type=TriggerType.PRICE_DROP,
                        symbol=symbol,
                        severity="high",
                        value=event.change_rate,
                        threshold=self.thresholds.price_drop_pct,
                        description=f"24시간 {abs(event.change_rate):.2f}% 급락",
                        source_events=[event],
                    )
                )

        return triggers

    def _evaluate_volume_triggers(self, event: MarketEvent) -> list[TriggerEvent]:
        """Check volume-based trigger conditions.

        Args:
            event: Market event with trade volume data.

        Returns:
            List of volume-related triggers.
        """
        triggers = []
        symbol = event.symbol

        if event.trade_volume is None:
            return triggers

        # Initialize volume tracking
        if symbol not in self._volume_samples:
            self._volume_samples[symbol] = deque(maxlen=100)
            self._volume_baseline[symbol] = 0.0

        # Update baseline
        self._volume_samples[symbol].append(event.trade_volume)
        samples = self._volume_samples[symbol]

        if len(samples) >= 10:
            self._volume_baseline[symbol] = sum(samples) / len(samples)
            baseline = self._volume_baseline[symbol]

            # Check for spike
            if baseline > 0:
                ratio = event.trade_volume / baseline
                threshold = self.thresholds.volume_spike_short_multiplier

                if ratio >= threshold:
                    severity = "high" if ratio >= 10 else "medium"
                    triggers.append(
                        TriggerEvent(
                            trigger_type=TriggerType.VOLUME_SPIKE,
                            symbol=symbol,
                            severity=severity,
                            value=ratio,
                            threshold=threshold,
                            description=f"거래량 평균 대비 {ratio:.1f}배 급증",
                            source_events=[event],
                        )
                    )

        return triggers

    def _evaluate_spread_triggers(self, event: MarketEvent) -> list[TriggerEvent]:
        """Check spread-based trigger conditions.

        Args:
            event: Market event with orderbook data.

        Returns:
            List of spread-related triggers.
        """
        triggers = []

        if event.spread_pct is None:
            return triggers

        threshold = self.thresholds.spread_anomaly_pct
        if event.spread_pct >= threshold:
            triggers.append(
                TriggerEvent(
                    trigger_type=TriggerType.SPREAD_ANOMALY,
                    symbol=event.symbol,
                    severity="medium",
                    value=event.spread_pct,
                    threshold=threshold,
                    description=f"호가 스프레드 {event.spread_pct:.3f}%로 확대",
                    source_events=[event],
                )
            )

        return triggers

    def evaluate_rsi(self, symbol: str, rsi_value: float) -> TriggerEvent | None:
        """Evaluate RSI for extreme conditions.

        RSI is calculated externally (from existing indicators module)
        and fed into the evaluator periodically.

        Args:
            symbol: Trading pair.
            rsi_value: Current RSI value (0-100).

        Returns:
            TriggerEvent if RSI is extreme, else None.
        """
        if rsi_value <= self.thresholds.rsi_extreme_oversold:
            return TriggerEvent(
                trigger_type=TriggerType.RSI_EXTREME,
                symbol=symbol,
                severity="high",
                value=rsi_value,
                threshold=self.thresholds.rsi_extreme_oversold,
                description=f"RSI 극단적 과매도 ({rsi_value:.1f})",
            )
        elif rsi_value >= self.thresholds.rsi_extreme_overbought:
            return TriggerEvent(
                trigger_type=TriggerType.RSI_EXTREME,
                symbol=symbol,
                severity="high",
                value=rsi_value,
                threshold=self.thresholds.rsi_extreme_overbought,
                description=f"RSI 극단적 과매수 ({rsi_value:.1f})",
            )
        elif rsi_value <= self.thresholds.rsi_oversold:
            return TriggerEvent(
                trigger_type=TriggerType.RSI_EXTREME,
                symbol=symbol,
                severity="medium",
                value=rsi_value,
                threshold=self.thresholds.rsi_oversold,
                description=f"RSI 과매도 ({rsi_value:.1f})",
            )
        elif rsi_value >= self.thresholds.rsi_overbought:
            return TriggerEvent(
                trigger_type=TriggerType.RSI_EXTREME,
                symbol=symbol,
                severity="medium",
                value=rsi_value,
                threshold=self.thresholds.rsi_overbought,
                description=f"RSI 과매수 ({rsi_value:.1f})",
            )
        return None

    def reset(self, symbol: str | None = None) -> None:
        """Reset evaluator state.

        Args:
            symbol: Reset only this symbol's state. If None, reset all.
        """
        if symbol is None:
            self._price_windows.clear()
            self._volume_baseline.clear()
            self._volume_samples.clear()
        else:
            self._price_windows.pop(symbol, None)
            self._volume_baseline.pop(symbol, None)
            self._volume_samples.pop(symbol, None)
