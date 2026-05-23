"""Historical derivatives data loader for backtesting.

Fetches OI / L_S / top trader L_S / funding rate time series from
Binance Futures public API and indexes them by timestamp so the backtest
engine can look up the nearest snapshot for each candle.
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

from trading.adapters.binance_futures import BinanceFuturesDataProvider
from trading.core.state import DerivativesData

logger = logging.getLogger(__name__)


def _classify_oi_trend(
    change_1h: float, change_24h: float
) -> Literal["increasing", "decreasing", "stable"]:
    if change_1h > 2 or change_24h > 5:
        return "increasing"
    if change_1h < -2 or change_24h < -5:
        return "decreasing"
    return "stable"


def _classify_position_bias(
    global_ratio: float, top_ratio: float
) -> Literal["long_heavy", "short_heavy", "balanced"]:
    avg = (global_ratio + top_ratio) / 2
    if avg > 1.5:
        return "long_heavy"
    if avg < 0.67:
        return "short_heavy"
    return "balanced"


def _classify_funding(rate: float) -> Literal["overheated_long", "overheated_short", "neutral"]:
    if rate > 0.001:
        return "overheated_long"
    if rate < -0.0005:
        return "overheated_short"
    return "neutral"


def load_historical_derivatives(
    start: datetime,
    end: datetime,
    period: str = "1h",
    provider: BinanceFuturesDataProvider | None = None,
) -> dict[datetime, DerivativesData]:
    """Fetch derivatives time series and return a timestamp-indexed dict.

    Args:
        start: Window start (inclusive).
        end: Window end (inclusive).
        period: OI/L_S sampling period.
        provider: Optional provider (creates new instance if None).

    Returns:
        Dict {timestamp -> DerivativesData} sorted by timestamp.
        Empty dict if all fetches fail.
    """
    provider = provider or BinanceFuturesDataProvider()
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    logger.info(
        f"Fetching Binance Futures derivatives history "
        f"{start.isoformat()} → {end.isoformat()} (period={period})"
    )

    try:
        oi_records = provider.get_historical_oi(start_ms, end_ms, period)
        ls_records = provider.get_historical_long_short(start_ms, end_ms, period)
        top_records = provider.get_historical_top_trader(start_ms, end_ms, period)
        funding_records = provider.get_historical_funding(start_ms, end_ms)
    except Exception as e:
        logger.warning(f"Failed to fetch derivatives history: {e}")
        return {}

    logger.info(
        f"  OI: {len(oi_records)} records, "
        f"L/S: {len(ls_records)}, Top: {len(top_records)}, "
        f"Funding: {len(funding_records)}"
    )

    # Index OI by timestamp (used as the master index)
    oi_by_ts: dict[int, dict] = {int(r["timestamp"]): r for r in oi_records}
    ls_by_ts: dict[int, dict] = {int(r["timestamp"]): r for r in ls_records}
    top_by_ts: dict[int, dict] = {int(r["timestamp"]): r for r in top_records}

    # Funding rate is sparse (every 8h). Build sorted list for nearest-past lookup.
    funding_sorted = sorted(
        funding_records,
        key=lambda r: int(r.get("fundingTime", 0)),
    )

    def _funding_at(ts_ms: int) -> float:
        """Find most recent funding rate at or before ts_ms."""
        if not funding_sorted:
            return 0.0
        # Linear scan from end (small list, simpler than bisect)
        for record in reversed(funding_sorted):
            if int(record.get("fundingTime", 0)) <= ts_ms:
                return float(record.get("fundingRate", 0))
        return float(funding_sorted[0].get("fundingRate", 0))

    # Convert OI records to running 1h/24h change calc by walking sorted timestamps
    sorted_ts = sorted(oi_by_ts.keys())
    indexed: dict[datetime, DerivativesData] = {}

    for i, ts in enumerate(sorted_ts):
        oi_record = oi_by_ts[ts]
        oi_value = float(oi_record.get("sumOpenInterest", 0))
        oi_value_usd = float(oi_record.get("sumOpenInterestValue", 0))

        # 1h change (previous record assumed to be ~1h apart for period="1h")
        if i >= 1:
            prev_oi = float(oi_by_ts[sorted_ts[i - 1]].get("sumOpenInterest", oi_value))
            oi_change_1h = ((oi_value - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0.0
        else:
            oi_change_1h = 0.0

        # 24h change (24 records back for period="1h")
        if i >= 24:
            old_oi = float(oi_by_ts[sorted_ts[i - 24]].get("sumOpenInterest", oi_value))
            oi_change_24h = ((oi_value - old_oi) / old_oi * 100) if old_oi > 0 else 0.0
        else:
            oi_change_24h = 0.0

        ls = ls_by_ts.get(ts, {})
        long_short = float(ls.get("longShortRatio", 1.0))

        top = top_by_ts.get(ts, {})
        top_ls = float(top.get("longShortRatio", 1.0))

        funding_rate = _funding_at(ts)
        next_funding = ts + 8 * 3600 * 1000  # +8h estimate

        snapshot: DerivativesData = {
            "open_interest": oi_value,
            "open_interest_value": oi_value_usd,
            "oi_change_pct_1h": oi_change_1h,
            "oi_change_pct_24h": oi_change_24h,
            "long_short_ratio": long_short,
            "top_trader_long_short_ratio": top_ls,
            "funding_rate": funding_rate,
            "next_funding_time": datetime.fromtimestamp(next_funding / 1000).isoformat(),
            "oi_trend": _classify_oi_trend(oi_change_1h, oi_change_24h),
            "position_bias": _classify_position_bias(long_short, top_ls),
            "funding_signal": _classify_funding(funding_rate),
        }
        indexed[datetime.fromtimestamp(ts / 1000)] = snapshot

    return indexed


def lookup_nearest_past(
    derivatives_by_ts: dict[datetime, DerivativesData],
    target: datetime,
) -> DerivativesData | None:
    """Return derivatives snapshot at or before `target` (nearest past).

    Args:
        derivatives_by_ts: Index returned by load_historical_derivatives.
        target: Backtest candle timestamp.

    Returns:
        Nearest past snapshot or None if no record at/before target.
    """
    if not derivatives_by_ts:
        return None
    candidates = [ts for ts in derivatives_by_ts if ts <= target]
    if not candidates:
        # All records are in the future — use earliest available as fallback
        return derivatives_by_ts[min(derivatives_by_ts.keys())]
    nearest = max(candidates)
    # Skip if too stale (> 2h gap)
    if (target - nearest) > timedelta(hours=2):
        return None
    return derivatives_by_ts[nearest]
