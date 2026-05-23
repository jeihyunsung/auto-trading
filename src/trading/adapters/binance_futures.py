"""Binance Futures public data provider (no API key required).

Provides derivatives market data for sentiment analysis:
- Open Interest (OI): Total outstanding futures contracts
- Long/Short Ratio: Position distribution among traders
- Funding Rate: Periodic fee between longs and shorts (8h intervals)
- Top Trader Positions: Positions of top traders by volume
"""

import logging
from datetime import datetime
from typing import Literal

import requests

from trading.core.models import DerivativesSnapshot
from trading.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Binance has 1200 requests/min limit for public endpoints
BINANCE_RATE_LIMITER = RateLimiter(max_calls=10, period_seconds=1.0)

BASE_URL = "https://fapi.binance.com"


class BinanceFuturesDataProvider:
    """Provider for Binance Futures public market data.

    All endpoints are public and do not require API keys.
    Data is used for market sentiment analysis in trading decisions.
    """

    def __init__(self, symbol: str = "BTCUSDT"):
        """Initialize provider.

        Args:
            symbol: Futures symbol (default BTCUSDT for BTC perpetual).
        """
        self.symbol = symbol
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
        })

    @property
    def is_available(self) -> bool:
        """Check if Binance API is accessible."""
        try:
            BINANCE_RATE_LIMITER.acquire()
            resp = self._session.get(f"{BASE_URL}/fapi/v1/ping", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_open_interest(self) -> dict:
        """Get current open interest.

        Returns:
            Dict with openInterest, symbol, time.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/fapi/v1/openInterest",
            params={"symbol": self.symbol},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_open_interest_history(self, period: str = "1h", limit: int = 24) -> list:
        """Get OI history for change calculation.

        Args:
            period: "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"
            limit: Number of records.

        Returns:
            List of OI records.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/futures/data/openInterestHist",
            params={"symbol": self.symbol, "period": period, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_long_short_ratio(self, period: str = "1h") -> dict:
        """Get global long/short account ratio.

        Args:
            period: "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"

        Returns:
            Dict with longShortRatio, longAccount, shortAccount.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/futures/data/globalLongShortAccountRatio",
            params={"symbol": self.symbol, "period": period, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    def get_top_trader_long_short_ratio(self, period: str = "1h") -> dict:
        """Get top trader long/short position ratio.

        Args:
            period: "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"

        Returns:
            Dict with longShortRatio, longAccount, shortAccount.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/futures/data/topLongShortPositionRatio",
            params={"symbol": self.symbol, "period": period, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    def get_funding_rate(self) -> dict:
        """Get current funding rate.

        Returns:
            Dict with fundingRate, fundingTime, symbol.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/fapi/v1/fundingRate",
            params={"symbol": self.symbol, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    def get_historical_oi(
        self,
        start_ms: int,
        end_ms: int,
        period: str = "1h",
    ) -> list[dict]:
        """Fetch open interest history for a time window.

        Args:
            start_ms: Window start (epoch ms).
            end_ms: Window end (epoch ms).
            period: Candle period (5m/15m/30m/1h/2h/4h/6h/12h/1d).

        Returns:
            List of records: [{"sumOpenInterest", "sumOpenInterestValue", "timestamp"}, ...]
        """
        return self._fetch_paginated(
            f"{BASE_URL}/futures/data/openInterestHist",
            start_ms,
            end_ms,
            period,
        )

    def get_historical_long_short(
        self,
        start_ms: int,
        end_ms: int,
        period: str = "1h",
    ) -> list[dict]:
        """Fetch global long/short account ratio history.

        Returns:
            List of {"longShortRatio", "longAccount", "shortAccount", "timestamp"}.
        """
        return self._fetch_paginated(
            f"{BASE_URL}/futures/data/globalLongShortAccountRatio",
            start_ms,
            end_ms,
            period,
        )

    def get_historical_top_trader(
        self,
        start_ms: int,
        end_ms: int,
        period: str = "1h",
    ) -> list[dict]:
        """Fetch top trader long/short position ratio history."""
        return self._fetch_paginated(
            f"{BASE_URL}/futures/data/topLongShortPositionRatio",
            start_ms,
            end_ms,
            period,
        )

    def get_historical_funding(
        self,
        start_ms: int,
        end_ms: int,
    ) -> list[dict]:
        """Fetch funding rate history (Binance posts every 8h).

        Returns:
            List of {"fundingRate", "fundingTime", ...}.
        """
        all_records: list[dict] = []
        cursor = start_ms
        while cursor < end_ms:
            BINANCE_RATE_LIMITER.acquire()
            resp = self._session.get(
                f"{BASE_URL}/fapi/v1/fundingRate",
                params={
                    "symbol": self.symbol,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                timeout=10,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_records.extend(batch)
            last_ts = int(batch[-1].get("fundingTime", cursor))
            if last_ts <= cursor or len(batch) < 1000:
                break
            cursor = last_ts + 1
        return all_records

    def _fetch_paginated(
        self,
        url: str,
        start_ms: int,
        end_ms: int,
        period: str,
    ) -> list[dict]:
        """Paginate /futures/data/* endpoints (max 500 per call)."""
        all_records: list[dict] = []
        cursor = start_ms
        while cursor < end_ms:
            BINANCE_RATE_LIMITER.acquire()
            resp = self._session.get(
                url,
                params={
                    "symbol": self.symbol,
                    "period": period,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 500,
                },
                timeout=10,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_records.extend(batch)
            # Records have "timestamp" (ms). Advance past the last one.
            last_ts = int(batch[-1].get("timestamp", cursor))
            if last_ts <= cursor or len(batch) < 500:
                break
            cursor = last_ts + 1
        return all_records

    def get_mark_price(self) -> dict:
        """Get mark price and funding rate info.

        Returns:
            Dict with markPrice, indexPrice, estimatedSettlePrice, etc.
        """
        BINANCE_RATE_LIMITER.acquire()
        resp = self._session.get(
            f"{BASE_URL}/fapi/v1/premiumIndex",
            params={"symbol": self.symbol},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_derivatives_snapshot(self) -> DerivativesSnapshot | None:
        """Get complete derivatives data snapshot.

        Returns:
            DerivativesSnapshot with all indicators, or None on error.
        """
        try:
            # Fetch all data
            oi_current = self.get_open_interest()
            mark_price_data = self.get_mark_price()
            oi_history = self.get_open_interest_history(period="1h", limit=24)
            ls_ratio = self.get_long_short_ratio()
            top_trader = self.get_top_trader_long_short_ratio()
            funding = self.get_funding_rate()

            # Parse current OI
            oi = float(oi_current.get("openInterest", 0))

            # Get mark price for OI value calculation
            mark_price = float(mark_price_data.get("markPrice", 0))
            oi_value = oi * mark_price

            # Calculate OI changes
            oi_change_1h = 0.0
            oi_change_24h = 0.0

            if oi_history and len(oi_history) >= 2:
                # Most recent is last in the list
                oi_1h_ago = float(oi_history[-2].get("sumOpenInterest", oi))
                if oi_1h_ago > 0:
                    oi_change_1h = ((oi - oi_1h_ago) / oi_1h_ago) * 100

            if oi_history and len(oi_history) >= 24:
                oi_24h_ago = float(oi_history[0].get("sumOpenInterest", oi))
                if oi_24h_ago > 0:
                    oi_change_24h = ((oi - oi_24h_ago) / oi_24h_ago) * 100

            # Long/Short ratio
            long_short = float(ls_ratio.get("longShortRatio", 1.0))
            long_pct = float(ls_ratio.get("longAccount", 0.5)) * 100
            short_pct = float(ls_ratio.get("shortAccount", 0.5)) * 100

            # Top trader ratio
            top_ls = float(top_trader.get("longShortRatio", 1.0))
            top_long_pct = float(top_trader.get("longAccount", 0.5)) * 100
            top_short_pct = float(top_trader.get("shortAccount", 0.5)) * 100

            # Funding rate
            funding_rate = float(funding.get("fundingRate", 0))
            funding_time_ms = int(funding.get("fundingTime", 0))
            funding_time = (
                datetime.fromtimestamp(funding_time_ms / 1000)
                if funding_time_ms > 0
                else datetime.now()
            )

            # Derive signals
            oi_trend = self._classify_oi_trend(oi_change_1h, oi_change_24h)
            position_bias = self._classify_position_bias(long_short, top_ls)
            funding_signal = self._classify_funding(funding_rate)

            return DerivativesSnapshot(
                open_interest=oi,
                open_interest_value=oi_value,
                oi_change_pct_1h=oi_change_1h,
                oi_change_pct_24h=oi_change_24h,
                long_short_ratio=long_short,
                long_account_pct=long_pct,
                short_account_pct=short_pct,
                top_trader_long_short_ratio=top_ls,
                top_trader_long_pct=top_long_pct,
                top_trader_short_pct=top_short_pct,
                funding_rate=funding_rate,
                next_funding_time=funding_time,
                oi_trend=oi_trend,
                position_bias=position_bias,
                funding_signal=funding_signal,
            )

        except Exception as e:
            logger.warning(f"Failed to get derivatives snapshot: {e}")
            return None

    def _classify_oi_trend(
        self, change_1h: float, change_24h: float
    ) -> Literal["increasing", "decreasing", "stable"]:
        """Classify OI trend based on changes.

        Args:
            change_1h: 1-hour OI change percentage.
            change_24h: 24-hour OI change percentage.

        Returns:
            OI trend classification.
        """
        if change_1h > 2 or change_24h > 5:
            return "increasing"
        elif change_1h < -2 or change_24h < -5:
            return "decreasing"
        return "stable"

    def _classify_position_bias(
        self, global_ratio: float, top_ratio: float
    ) -> Literal["long_heavy", "short_heavy", "balanced"]:
        """Classify market position bias.

        Args:
            global_ratio: Global long/short ratio.
            top_ratio: Top trader long/short ratio.

        Returns:
            Position bias classification.
        """
        avg_ratio = (global_ratio + top_ratio) / 2
        if avg_ratio > 1.5:
            return "long_heavy"
        elif avg_ratio < 0.67:
            return "short_heavy"
        return "balanced"

    def _classify_funding(
        self, rate: float
    ) -> Literal["overheated_long", "overheated_short", "neutral"]:
        """Classify funding rate signal.

        Args:
            rate: Current funding rate.

        Returns:
            Funding signal classification.
        """
        if rate > 0.001:  # > 0.1%
            return "overheated_long"
        elif rate < -0.0005:  # < -0.05%
            return "overheated_short"
        return "neutral"


# Module-level singleton
_provider: BinanceFuturesDataProvider | None = None


def get_binance_futures_provider() -> BinanceFuturesDataProvider:
    """Get global Binance Futures provider instance.

    Returns:
        Singleton BinanceFuturesDataProvider instance.
    """
    global _provider
    if _provider is None:
        _provider = BinanceFuturesDataProvider()
    return _provider


def set_binance_futures_provider(provider: BinanceFuturesDataProvider | None) -> None:
    """Set global Binance Futures provider instance.

    Args:
        provider: Provider instance or None to clear.
    """
    global _provider
    _provider = provider
