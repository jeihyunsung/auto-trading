"""External system adapters (Upbit, CoinMarketCap, Binance, RSS)."""

from trading.adapters.broker import BrokerAdapter
from trading.adapters.upbit import UpbitBrokerAdapter
from trading.adapters.coinmarketcap import CoinMarketCapProvider
from trading.adapters.rss_collector import RSSNewsCollector
from trading.adapters.binance_futures import (
    BinanceFuturesDataProvider,
    get_binance_futures_provider,
)

__all__ = [
    "BrokerAdapter",
    "UpbitBrokerAdapter",
    "CoinMarketCapProvider",
    "RSSNewsCollector",
    "BinanceFuturesDataProvider",
    "get_binance_futures_provider",
]
