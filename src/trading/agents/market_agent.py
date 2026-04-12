"""Market data collection agent."""

import logging
from datetime import datetime, timedelta, timezone

# Korea Standard Time (UTC+9)
KST = timezone(timedelta(hours=9))

from trading.adapters.binance_futures import get_binance_futures_provider
from trading.adapters.coinmarketcap import CoinMarketCapProvider
from trading.adapters.upbit import UpbitBrokerAdapter
from trading.core.anomaly import MarketAnomalyDetector
from trading.core.isolated_balance import get_isolated_tracker
from trading.core.models import OHLCV
from trading.core.state import (
    DerivativesData,
    MarketData,
    MultiTimeframeOHLCV,
    MultiTimeframeTrendData,
    TradingState,
)
from trading.indicators.multi_timeframe import get_mtf_analyzer
from trading.indicators.volatility import get_volatility_level

logger = logging.getLogger(__name__)


class MarketAgent:
    """Agent for collecting market data."""

    def __init__(
        self,
        broker: UpbitBrokerAdapter | None = None,
        cmc: CoinMarketCapProvider | None = None,
        anomaly_detector: MarketAnomalyDetector | None = None,
    ):
        """Initialize market agent.

        Args:
            broker: Upbit broker adapter.
            cmc: CoinMarketCap provider.
            anomaly_detector: Anomaly detector.
        """
        self.broker = broker or UpbitBrokerAdapter()
        self.cmc = cmc or CoinMarketCapProvider()
        self.anomaly_detector = anomaly_detector or MarketAnomalyDetector()
        self.binance_futures = get_binance_futures_provider()

    def collect(self, symbol: str = "KRW-BTC") -> MarketData:
        """Collect market data for symbol.

        Args:
            symbol: Trading pair (default KRW-BTC).

        Returns:
            MarketData with current market state.
        """
        logger.info(f"Collecting market data for {symbol}")

        # Get market snapshot from Upbit
        snapshot = self.broker.get_market_snapshot(symbol)

        # Get CMC data for additional context
        percent_change_1h = 0.0
        percent_change_24h = snapshot.change_24h_pct or 0.0

        if self.cmc.is_available:
            try:
                btc_quote = self.cmc.get_btc_quote()
                if btc_quote:
                    percent_change_1h = btc_quote.percent_change_1h
                    # Use CMC 24h change if Upbit's is not available
                    if percent_change_24h == 0.0:
                        percent_change_24h = btc_quote.percent_change_24h
            except Exception as e:
                logger.warning(f"CMC data collection failed: {e}")

        # Calculate volatility level from OHLCV
        volatility_level = get_volatility_level(snapshot.ohlcv) if snapshot.ohlcv else "medium"

        # Build orderbook dict
        orderbook = None
        try:
            orderbook = self.broker.get_orderbook(symbol)
        except Exception as e:
            logger.warning(f"Orderbook fetch failed: {e}")

        return MarketData(
            symbol=symbol,
            current_price=snapshot.current_price,
            ohlcv=[
                {
                    "timestamp": c.timestamp.isoformat(),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in snapshot.ohlcv
            ],
            orderbook=orderbook,
            volatility_level=volatility_level,
            percent_change_1h=percent_change_1h,
            percent_change_24h=percent_change_24h,
        )

    def detect_anomalies(self, symbol: str = "KRW-BTC") -> list[dict]:
        """Detect market anomalies.

        Args:
            symbol: Trading pair.

        Returns:
            List of anomaly dicts.
        """
        snapshot = self.broker.get_market_snapshot(symbol)
        anomalies = self.anomaly_detector.detect(snapshot)

        return [
            {
                "type": a.anomaly_type,
                "severity": a.severity,
                "description": a.description,
            }
            for a in anomalies
        ]

    def collect_portfolio(self, symbol: str = "KRW-BTC") -> dict:
        """Collect current portfolio state.

        Uses isolated balance tracker if available (isolated mode),
        otherwise falls back to actual Upbit account balance.

        Args:
            symbol: Trading pair for price reference.

        Returns:
            Portfolio dict with cash_krw, btc_balance, exposure_pct, etc.
        """
        try:
            # Get current price for calculations
            snapshot = self.broker.get_market_snapshot(symbol)
            current_price = snapshot.current_price

            # Check if isolated mode is active
            isolated_tracker = get_isolated_tracker()

            if isolated_tracker:
                # Use isolated balance (bot's dedicated capital)
                portfolio_data = isolated_tracker.get_portfolio_value(current_price)
                portfolio = {
                    "cash_krw": portfolio_data["krw_balance"],
                    "btc_balance": portfolio_data["btc_balance"],
                    "btc_value_krw": portfolio_data["btc_value_krw"],
                    "total_value_krw": portfolio_data["total_value_krw"],
                    "total_invested_krw": portfolio_data["total_invested_krw"],
                    "exposure_pct": portfolio_data["exposure_pct"],
                    "unrealized_pnl": portfolio_data["unrealized_pnl_pct"],
                    "total_pnl": portfolio_data["pnl_pct"],
                }
                logger.info(
                    f"Portfolio (isolated): KRW={portfolio['cash_krw']:,.0f}, "
                    f"BTC={portfolio['btc_balance']:.8f}, "
                    f"Exposure={portfolio['exposure_pct']:.1f}%, "
                    f"Unrealized P&L={portfolio['unrealized_pnl']:+.2f}%"
                )
            else:
                # Fallback to actual Upbit balance
                balances = self.broker.get_all_balances()
                krw = float(balances.get("KRW", 0))
                btc = float(balances.get("BTC", 0))

                btc_value = btc * current_price
                total_value = krw + btc_value
                exposure_pct = (btc_value / total_value * 100) if total_value > 0 else 0

                portfolio = {
                    "cash_krw": krw,
                    "btc_balance": btc,
                    "btc_value_krw": btc_value,
                    "total_value_krw": total_value,
                    "exposure_pct": exposure_pct,
                    "unrealized_pnl": 0.0,
                }
                logger.info(
                    f"Portfolio: KRW={krw:,.0f}, BTC={btc:.8f}, "
                    f"Exposure={exposure_pct:.1f}%"
                )

            return portfolio

        except Exception as e:
            logger.warning(f"Portfolio collection failed: {e}")
            return {
                "cash_krw": 0,
                "btc_balance": 0,
                "exposure_pct": 0,
            }

    def collect_derivatives(self) -> DerivativesData | None:
        """Collect Binance Futures derivatives data.

        Returns:
            DerivativesData dict or None if collection fails.
        """
        try:
            snapshot = self.binance_futures.get_derivatives_snapshot()
            if snapshot is None:
                return None

            derivatives_data: DerivativesData = {
                "open_interest": snapshot.open_interest,
                "open_interest_value": snapshot.open_interest_value,
                "oi_change_pct_1h": snapshot.oi_change_pct_1h,
                "oi_change_pct_24h": snapshot.oi_change_pct_24h,
                "long_short_ratio": snapshot.long_short_ratio,
                "top_trader_long_short_ratio": snapshot.top_trader_long_short_ratio,
                "funding_rate": snapshot.funding_rate,
                "next_funding_time": snapshot.next_funding_time.isoformat(),
                "oi_trend": snapshot.oi_trend,
                "position_bias": snapshot.position_bias,
                "funding_signal": snapshot.funding_signal,
            }

            logger.info(
                f"Derivatives: OI={snapshot.open_interest:,.0f} "
                f"({snapshot.oi_change_pct_1h:+.1f}% 1h), "
                f"L/S={snapshot.long_short_ratio:.2f}, "
                f"Funding={snapshot.funding_rate:.4%}, "
                f"Signal={snapshot.funding_signal}"
            )

            return derivatives_data

        except Exception as e:
            logger.warning(f"Derivatives data collection failed: {e}")
            return None

    def collect_multi_timeframe_ohlcv(
        self,
        symbol: str = "KRW-BTC",
    ) -> MultiTimeframeOHLCV:
        """Collect OHLCV data for multiple timeframes.

        Args:
            symbol: Trading pair.

        Returns:
            MultiTimeframeOHLCV with data for all timeframes.
        """
        mtf_ohlcv: MultiTimeframeOHLCV = {}

        # Timeframe configurations: (interval, count)
        # Upbit intervals: minutes1, minutes3, minutes5, minutes15, minutes30,
        #                  minutes60, minutes240, day, week, month
        timeframes = {
            "5m": ("minute5", 24),    # 2 hours of 5-min candles
            "1h": ("minute60", 24),   # 24 hours of hourly candles
            "4h": ("minute240", 42),  # ~1 week of 4-hour candles
            "1d": ("day", 30),        # 30 days of daily candles
        }

        for tf_name, (interval, count) in timeframes.items():
            try:
                ohlcv_list = self.broker.get_ohlcv(symbol, interval=interval, count=count)
                if ohlcv_list:
                    mtf_ohlcv[f"ohlcv_{tf_name}"] = [
                        {
                            "timestamp": c.timestamp.isoformat(),
                            "open": c.open,
                            "high": c.high,
                            "low": c.low,
                            "close": c.close,
                            "volume": c.volume,
                        }
                        for c in ohlcv_list
                    ]
            except Exception as e:
                logger.warning(f"Failed to collect {tf_name} OHLCV: {e}")

        return mtf_ohlcv

    def analyze_multi_timeframe_trends(
        self,
        mtf_ohlcv: MultiTimeframeOHLCV,
    ) -> MultiTimeframeTrendData | None:
        """Analyze trends across multiple timeframes.

        Args:
            mtf_ohlcv: Multi-timeframe OHLCV data.

        Returns:
            MultiTimeframeTrendData or None if analysis fails.
        """
        try:
            analyzer = get_mtf_analyzer()

            # Convert dict OHLCV to OHLCV objects for each timeframe
            def to_ohlcv_list(ohlcv_dicts: list[dict] | None) -> list[OHLCV] | None:
                if not ohlcv_dicts:
                    return None
                return [
                    OHLCV(
                        timestamp=datetime.fromisoformat(c["timestamp"]) if isinstance(c["timestamp"], str) else c["timestamp"],
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c["volume"],
                    )
                    for c in ohlcv_dicts
                ]

            ohlcv_5m = to_ohlcv_list(mtf_ohlcv.get("ohlcv_5m"))
            ohlcv_1h = to_ohlcv_list(mtf_ohlcv.get("ohlcv_1h"))
            ohlcv_4h = to_ohlcv_list(mtf_ohlcv.get("ohlcv_4h"))
            ohlcv_1d = to_ohlcv_list(mtf_ohlcv.get("ohlcv_1d"))

            # Analyze trends
            mtf_result = analyzer.analyze(
                ohlcv_5m=ohlcv_5m,
                ohlcv_1h=ohlcv_1h,
                ohlcv_4h=ohlcv_4h,
                ohlcv_1d=ohlcv_1d,
            )

            return mtf_result.to_dict()

        except Exception as e:
            logger.warning(f"Multi-timeframe trend analysis failed: {e}")
            return None


def market_agent_node(state: TradingState) -> dict:
    """LangGraph node function for market agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with market data, derivatives, portfolio, anomalies, and MTF trends.
    """
    agent = MarketAgent()

    try:
        market_data = agent.collect()
        anomalies = agent.detect_anomalies()
        derivatives_data = agent.collect_derivatives()
        portfolio_data = agent.collect_portfolio()

        # Collect multi-timeframe data and analyze trends
        mtf_ohlcv = agent.collect_multi_timeframe_ohlcv()
        mtf_trends = agent.analyze_multi_timeframe_trends(mtf_ohlcv)

        return {
            "market": market_data,
            "derivatives": derivatives_data,
            "portfolio": portfolio_data,
            "mtf_ohlcv": mtf_ohlcv,
            "mtf_trends": mtf_trends,
            "anomalies": state.get("anomalies", []) + anomalies,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Market agent failed: {e}")
        return {
            "error": f"Market agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
