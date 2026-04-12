"""Market anomaly detection."""

import logging
from datetime import datetime
from typing import Literal

from trading.core.models import MarketAnomaly, MarketSnapshot

logger = logging.getLogger(__name__)


class MarketAnomalyDetector:
    """Detector for market anomalies like sudden price/volume changes."""

    def __init__(
        self,
        price_surge_threshold: float = 5.0,
        price_drop_threshold: float = -5.0,
        volume_spike_multiplier: float = 3.0,
        volatility_spike_threshold: float = 2.0,
    ):
        """Initialize anomaly detector.

        Args:
            price_surge_threshold: % change to trigger price surge (default 5%).
            price_drop_threshold: % change to trigger price drop (default -5%).
            volume_spike_multiplier: Volume must be N times average to trigger.
            volatility_spike_threshold: Std dev multiplier for volatility spike.
        """
        self.price_surge_threshold = price_surge_threshold
        self.price_drop_threshold = price_drop_threshold
        self.volume_spike_multiplier = volume_spike_multiplier
        self.volatility_spike_threshold = volatility_spike_threshold

        # Cache for baseline calculations
        self._volume_cache: dict[str, list[float]] = {}

    def detect(self, snapshot: MarketSnapshot) -> list[MarketAnomaly]:
        """Detect anomalies in market snapshot.

        Args:
            snapshot: Current market snapshot.

        Returns:
            List of detected anomalies.
        """
        anomalies = []

        # Check price surge/drop
        if snapshot.change_24h_pct is not None:
            price_anomaly = self._check_price_change(
                snapshot.symbol, snapshot.change_24h_pct
            )
            if price_anomaly:
                anomalies.append(price_anomaly)

        # Check volume spike
        if snapshot.ohlcv:
            volume_anomaly = self._check_volume_spike(
                snapshot.symbol, snapshot.ohlcv
            )
            if volume_anomaly:
                anomalies.append(volume_anomaly)

            volatility_anomaly = self._check_volatility(
                snapshot.symbol, snapshot.ohlcv
            )
            if volatility_anomaly:
                anomalies.append(volatility_anomaly)

        return anomalies

    def _check_price_change(
        self,
        symbol: str,
        change_pct: float,
    ) -> MarketAnomaly | None:
        """Check for significant price changes.

        Args:
            symbol: Trading pair.
            change_pct: 24h price change percentage.

        Returns:
            MarketAnomaly if detected, else None.
        """
        if change_pct >= self.price_surge_threshold:
            severity = self._classify_severity(change_pct, [5, 10, 15])
            return MarketAnomaly(
                anomaly_type="price_surge",
                severity=severity,
                symbol=symbol,
                value=change_pct,
                threshold=self.price_surge_threshold,
                description=f"{symbol} price surged {change_pct:.2f}% in 24h",
            )

        if change_pct <= self.price_drop_threshold:
            severity = self._classify_severity(abs(change_pct), [5, 10, 15])
            return MarketAnomaly(
                anomaly_type="price_drop",
                severity=severity,
                symbol=symbol,
                value=change_pct,
                threshold=self.price_drop_threshold,
                description=f"{symbol} price dropped {change_pct:.2f}% in 24h",
            )

        return None

    def _check_volume_spike(
        self,
        symbol: str,
        ohlcv: list,
    ) -> MarketAnomaly | None:
        """Check for volume spikes.

        Args:
            symbol: Trading pair.
            ohlcv: List of OHLCV candles.

        Returns:
            MarketAnomaly if detected, else None.
        """
        if len(ohlcv) < 20:
            return None

        # Calculate average volume (excluding last candle)
        volumes = [candle.volume for candle in ohlcv[:-1]]
        avg_volume = sum(volumes) / len(volumes)

        if avg_volume == 0:
            return None

        # Check current volume
        current_volume = ohlcv[-1].volume
        volume_ratio = current_volume / avg_volume

        if volume_ratio >= self.volume_spike_multiplier:
            severity = self._classify_severity(volume_ratio, [3, 5, 10])
            return MarketAnomaly(
                anomaly_type="volume_spike",
                severity=severity,
                symbol=symbol,
                value=volume_ratio,
                threshold=self.volume_spike_multiplier,
                description=f"{symbol} volume is {volume_ratio:.1f}x average",
            )

        return None

    def _check_volatility(
        self,
        symbol: str,
        ohlcv: list,
    ) -> MarketAnomaly | None:
        """Check for volatility spikes.

        Args:
            symbol: Trading pair.
            ohlcv: List of OHLCV candles.

        Returns:
            MarketAnomaly if detected, else None.
        """
        if len(ohlcv) < 20:
            return None

        # Calculate intra-candle volatility (high-low range)
        ranges = [(c.high - c.low) / c.close * 100 for c in ohlcv[:-1] if c.close > 0]

        if not ranges:
            return None

        avg_range = sum(ranges) / len(ranges)
        std_range = (sum((r - avg_range) ** 2 for r in ranges) / len(ranges)) ** 0.5

        if std_range == 0:
            return None

        # Check current candle volatility
        current = ohlcv[-1]
        if current.close == 0:
            return None

        current_range = (current.high - current.low) / current.close * 100
        z_score = (current_range - avg_range) / std_range

        if z_score >= self.volatility_spike_threshold:
            severity = self._classify_severity(z_score, [2, 3, 4])
            return MarketAnomaly(
                anomaly_type="volatility_spike",
                severity=severity,
                symbol=symbol,
                value=z_score,
                threshold=self.volatility_spike_threshold,
                description=f"{symbol} volatility is {z_score:.1f} std devs above normal",
            )

        return None

    def _classify_severity(
        self,
        value: float,
        thresholds: list[float],
    ) -> Literal["low", "medium", "high"]:
        """Classify severity based on thresholds.

        Args:
            value: The value to classify.
            thresholds: List of [low, medium, high] thresholds.

        Returns:
            Severity level.
        """
        if value >= thresholds[2]:
            return "high"
        elif value >= thresholds[1]:
            return "medium"
        return "low"

    def get_severity_score(self, anomalies: list[MarketAnomaly]) -> int:
        """Calculate combined severity score from anomalies.

        Args:
            anomalies: List of detected anomalies.

        Returns:
            Score from 0-10 indicating overall anomaly severity.
        """
        if not anomalies:
            return 0

        severity_points = {"low": 1, "medium": 3, "high": 5}
        total = sum(severity_points.get(a.severity, 0) for a in anomalies)

        return min(10, total)
