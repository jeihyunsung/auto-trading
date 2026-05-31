"""CoinMarketCap API provider for market data."""

import logging
from datetime import datetime

import requests

from trading.config import get_settings
from trading.core.models import CMCQuote, GlobalMetrics
from trading.utils.rate_limiter import CMC_RATE_LIMITER

logger = logging.getLogger(__name__)


class CoinMarketCapProvider:
    """Provider for CoinMarketCap market data."""

    BASE_URL = "https://pro-api.coinmarketcap.com"

    def __init__(self, api_key: str | None = None):
        """Initialize CoinMarketCap provider.

        Args:
            api_key: CMC API key (uses env if None).
        """
        settings = get_settings()
        self._api_key = api_key or settings.cmc_api_key

        if not self._api_key:
            logger.warning("CoinMarketCap API key not provided - CMC features disabled")

        self._session = requests.Session()
        self._session.headers.update({
            "X-CMC_PRO_API_KEY": self._api_key,
            "Accept": "application/json",
        })

    @property
    def is_available(self) -> bool:
        """Check if CMC API is available."""
        return bool(self._api_key)

    def _request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make API request to CoinMarketCap.

        Args:
            endpoint: API endpoint path.
            params: Query parameters.

        Returns:
            JSON response data.

        Raises:
            RuntimeError: If API call fails.
        """
        if not self._api_key:
            raise RuntimeError("CoinMarketCap API key not configured")

        CMC_RATE_LIMITER.acquire()

        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("status", {}).get("error_code", 0) != 0:
                error_msg = data.get("status", {}).get("error_message", "Unknown error")
                raise RuntimeError(f"CMC API error: {error_msg}")

            return data.get("data", {})

        except requests.RequestException as e:
            logger.error(f"CMC API request failed: {e}")
            raise RuntimeError(f"CMC API request failed: {e}") from e

    def get_quotes(self, symbols: list[str], convert: str = "USD") -> dict[str, CMCQuote]:
        """Get price quotes for symbols.

        Args:
            symbols: List of cryptocurrency symbols (e.g., ['BTC', 'ETH']).
            convert: Quote currency (default USD).

        Returns:
            Dictionary mapping symbol to CMCQuote.
        """
        params = {
            "symbol": ",".join(symbols),
            "convert": convert,
        }

        data = self._request("/v1/cryptocurrency/quotes/latest", params)

        quotes = {}
        for symbol in symbols:
            if symbol not in data:
                continue

            coin_data = data[symbol]
            quote_data = coin_data.get("quote", {}).get(convert, {})

            quotes[symbol] = CMCQuote(
                symbol=symbol,
                name=coin_data.get("name", ""),
                price_usd=quote_data.get("price", 0),
                volume_24h=quote_data.get("volume_24h", 0),
                percent_change_1h=quote_data.get("percent_change_1h", 0),
                percent_change_24h=quote_data.get("percent_change_24h", 0),
                percent_change_7d=quote_data.get("percent_change_7d", 0),
                market_cap=quote_data.get("market_cap", 0),
                last_updated=datetime.fromisoformat(
                    quote_data.get("last_updated", "").replace("Z", "+00:00")
                ) if quote_data.get("last_updated") else datetime.now(),
            )

        return quotes

    def get_btc_quote(self) -> CMCQuote | None:
        """Get Bitcoin quote (convenience method, kept for callers that still
        want BTC explicitly — backtests/dashboards).

        Returns:
            CMCQuote for BTC or None if not available.
        """
        quotes = self.get_quotes(["BTC"])
        return quotes.get("BTC")

    def get_asset_quote(self, symbol: str) -> CMCQuote | None:
        """Get quote for an arbitrary asset symbol.

        Args:
            symbol: Ticker (e.g., 'BTC', 'ETH', 'XRP').

        Returns:
            CMCQuote for the asset or None if not available.
        """
        quotes = self.get_quotes([symbol])
        return quotes.get(symbol)

    def get_global_metrics(self) -> GlobalMetrics:
        """Get global cryptocurrency market metrics.

        Returns:
            GlobalMetrics with market overview.
        """
        data = self._request("/v1/global-metrics/quotes/latest")

        quote = data.get("quote", {}).get("USD", {})

        return GlobalMetrics(
            total_market_cap_usd=quote.get("total_market_cap", 0),
            total_volume_24h_usd=quote.get("total_volume_24h", 0),
            btc_dominance=data.get("btc_dominance", 0),
            eth_dominance=data.get("eth_dominance", 0),
            active_cryptocurrencies=data.get("active_cryptocurrencies", 0),
            last_updated=datetime.fromisoformat(
                data.get("last_updated", "").replace("Z", "+00:00")
            ) if data.get("last_updated") else datetime.now(),
        )

    def get_gainers_losers(self, limit: int = 10) -> dict:
        """Get top gainers and losers (requires paid plan).

        Note: This endpoint may not be available on Basic plan.

        Args:
            limit: Number of results per category.

        Returns:
            Dictionary with 'gainers' and 'losers' lists.
        """
        try:
            params = {
                "limit": limit,
                "time_period": "24h",
                "sort": "percent_change_24h",
                "sort_dir": "desc",
            }

            data = self._request("/v1/cryptocurrency/trending/gainers-losers", params)
            return data

        except RuntimeError as e:
            logger.warning(f"Gainers/losers endpoint not available: {e}")
            return {"gainers": [], "losers": []}

    def check_credits(self) -> dict:
        """Check API credit usage.

        Returns:
            Dictionary with credit usage info.
        """
        try:
            data = self._request("/v1/key/info")
            return {
                "credits_used": data.get("usage", {}).get("current_month", {}).get("credits_used", 0),
                "credits_left": data.get("plan", {}).get("credit_limit_monthly", 0)
                - data.get("usage", {}).get("current_month", {}).get("credits_used", 0),
            }
        except RuntimeError:
            return {"credits_used": "unknown", "credits_left": "unknown"}
