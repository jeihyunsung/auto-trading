"""Tests for Upbit adapter."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from trading.adapters.upbit import UpbitBrokerAdapter
from trading.core.models import OrderRequest, OrderSide, OrderStatus


class TestUpbitBrokerAdapter:
    """Tests for UpbitBrokerAdapter."""

    def test_paper_trading_initial_balance(self):
        """Test paper trading starts with default balance."""
        adapter = UpbitBrokerAdapter(paper_trading=True)

        assert adapter.is_paper_trading
        assert adapter.get_balance("KRW") == Decimal("1000000")
        assert adapter.get_balance("BTC") == Decimal("0")

    def test_paper_trading_buy_order(self):
        """Test paper trading buy order execution."""
        adapter = UpbitBrokerAdapter(paper_trading=True)

        # Mock get_current_price
        with patch.object(adapter, "get_current_price", return_value=50_000_000):
            request = OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                amount_krw=Decimal("100000"),
            )

            result = adapter.submit_order(request)

            assert result.status == OrderStatus.FILLED
            assert result.filled_quantity > 0
            assert result.average_price == Decimal("50000000")

            # Check balances updated
            krw = adapter.get_balance("KRW")
            btc = adapter.get_balance("BTC")

            assert krw < Decimal("1000000")  # Spent some KRW
            assert btc > Decimal("0")  # Got some BTC

    def test_paper_trading_sell_order(self):
        """Test paper trading sell order execution."""
        adapter = UpbitBrokerAdapter(paper_trading=True)

        # Give some BTC first
        adapter.set_paper_balance("BTC", Decimal("0.1"))

        with patch.object(adapter, "get_current_price", return_value=50_000_000):
            request = OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=Decimal("0.05"),
            )

            result = adapter.submit_order(request)

            assert result.status == OrderStatus.FILLED
            assert result.filled_quantity == Decimal("0.05")

            # Check balances updated
            btc = adapter.get_balance("BTC")
            assert btc < Decimal("0.1")

    def test_paper_trading_insufficient_balance(self):
        """Test paper trading rejects orders with insufficient balance."""
        adapter = UpbitBrokerAdapter(paper_trading=True)

        with patch.object(adapter, "get_current_price", return_value=50_000_000):
            # Try to buy more than available
            request = OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                amount_krw=Decimal("10000000"),  # 10M, only have 1M
            )

            result = adapter.submit_order(request)

            assert result.status == OrderStatus.REJECTED
            assert "Insufficient" in result.error_message

    def test_get_all_balances(self):
        """Test getting all balances."""
        adapter = UpbitBrokerAdapter(paper_trading=True)
        adapter.set_paper_balance("BTC", Decimal("0.5"))
        adapter.set_paper_balance("ETH", Decimal("1.0"))

        balances = adapter.get_all_balances()

        assert "KRW" in balances
        assert "BTC" in balances
        assert "ETH" in balances


class TestUpbitMarketData:
    """Tests for market data functions."""

    @patch("pyupbit.get_current_price")
    def test_get_current_price(self, mock_price):
        """Test getting current price."""
        mock_price.return_value = 50_000_000

        adapter = UpbitBrokerAdapter(paper_trading=True)
        price = adapter.get_current_price("KRW-BTC")

        assert price == 50_000_000
        mock_price.assert_called_once_with("KRW-BTC")

    @patch("pyupbit.get_ohlcv")
    def test_get_ohlcv(self, mock_ohlcv):
        """Test getting OHLCV data."""
        import pandas as pd
        from datetime import datetime

        # Create mock DataFrame
        mock_df = pd.DataFrame({
            "open": [50000000],
            "high": [51000000],
            "low": [49000000],
            "close": [50500000],
            "volume": [100.0],
        }, index=[pd.Timestamp(datetime.now())])

        mock_ohlcv.return_value = mock_df

        adapter = UpbitBrokerAdapter(paper_trading=True)
        ohlcv = adapter.get_ohlcv("KRW-BTC", count=1)

        assert len(ohlcv) == 1
        assert ohlcv[0].close == 50500000
