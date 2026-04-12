"""Pytest configuration and fixtures."""

import os
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_upbit():
    """Mock pyupbit Upbit client."""
    mock = MagicMock()
    mock.get_balances.return_value = [
        {"currency": "KRW", "balance": "1000000", "avg_buy_price": "0"},
        {"currency": "BTC", "balance": "0.1", "avg_buy_price": "50000000"},
    ]
    return mock


@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("UPBIT_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("UPBIT_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("CMC_API_KEY", "test-cmc-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TRADING_MODE", "paper")
