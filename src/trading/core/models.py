"""Core domain models using Pydantic."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """Order side: buy or sell."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type: market or limit."""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    """Order execution status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


class OrderRequest(BaseModel):
    """Request to place an order."""

    symbol: str = Field(description="Trading pair (e.g., 'KRW-BTC')")
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal | None = Field(default=None, description="Quantity to trade")
    price: Decimal | None = Field(default=None, description="Limit price (for limit orders)")
    amount_krw: Decimal | None = Field(default=None, description="KRW amount (for market buy)")

    def model_post_init(self, __context) -> None:
        """Validate order parameters."""
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders require a price")
        if self.side == OrderSide.BUY and self.quantity is None and self.amount_krw is None:
            raise ValueError("Buy orders require either quantity or amount_krw")
        if self.side == OrderSide.SELL and self.quantity is None:
            raise ValueError("Sell orders require quantity")


class OrderResult(BaseModel):
    """Result of an order execution."""

    order_id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    requested_quantity: Decimal | None = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Decimal | None = None
    fee: Decimal = Decimal("0")
    timestamp: datetime = Field(default_factory=datetime.now)
    error_message: str | None = None


class OHLCV(BaseModel):
    """OHLCV candle data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketSnapshot(BaseModel):
    """Current market state snapshot."""

    symbol: str
    current_price: float
    bid_price: float | None = None
    ask_price: float | None = None
    volume_24h: float | None = None
    change_24h_pct: float | None = None
    ohlcv: list[OHLCV] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class CMCQuote(BaseModel):
    """CoinMarketCap quote data."""

    symbol: str
    name: str
    price_usd: float
    volume_24h: float
    percent_change_1h: float
    percent_change_24h: float
    percent_change_7d: float
    market_cap: float
    last_updated: datetime


class GlobalMetrics(BaseModel):
    """CoinMarketCap global market metrics."""

    total_market_cap_usd: float
    total_volume_24h_usd: float
    btc_dominance: float
    eth_dominance: float
    active_cryptocurrencies: int
    last_updated: datetime


class MarketAnomaly(BaseModel):
    """Detected market anomaly."""

    anomaly_type: Literal["price_surge", "price_drop", "volume_spike", "volatility_spike"]
    severity: Literal["low", "medium", "high"]
    symbol: str
    value: float
    threshold: float
    description: str
    timestamp: datetime = Field(default_factory=datetime.now)


class DerivativesSnapshot(BaseModel):
    """Binance Futures derivatives data snapshot.

    Provides market sentiment indicators from futures market:
    - Open Interest (OI): Total outstanding contracts
    - Long/Short Ratio: Position distribution
    - Funding Rate: Periodic fee between longs and shorts
    """

    # Open Interest
    open_interest: float = Field(description="Total OI in contracts")
    open_interest_value: float = Field(default=0, description="OI value in USDT")
    oi_change_pct_1h: float = Field(default=0, description="OI change % (1 hour)")
    oi_change_pct_24h: float = Field(default=0, description="OI change % (24 hours)")

    # Long/Short Ratio (Global)
    long_short_ratio: float = Field(description="Long accounts / Short accounts")
    long_account_pct: float = Field(default=50, description="% of accounts long")
    short_account_pct: float = Field(default=50, description="% of accounts short")

    # Top Trader Positions
    top_trader_long_short_ratio: float = Field(default=1.0, description="Top trader L/S ratio")
    top_trader_long_pct: float = Field(default=50, description="Top trader % long")
    top_trader_short_pct: float = Field(default=50, description="Top trader % short")

    # Funding Rate
    funding_rate: float = Field(description="Current funding rate (8h)")
    next_funding_time: datetime = Field(default_factory=datetime.now, description="Next funding timestamp")

    # Derived signals
    oi_trend: Literal["increasing", "decreasing", "stable"] = Field(default="stable")
    position_bias: Literal["long_heavy", "short_heavy", "balanced"] = Field(default="balanced")
    funding_signal: Literal["overheated_long", "overheated_short", "neutral"] = Field(default="neutral")
