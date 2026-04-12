"""Upbit broker adapter using pyupbit."""

import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pyupbit

from trading.adapters.broker import BrokerAdapter
from trading.config import get_settings
from trading.core.models import (
    MarketSnapshot,
    OHLCV,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading.utils.rate_limiter import UPBIT_RATE_LIMITER

logger = logging.getLogger(__name__)


class UpbitBrokerAdapter(BrokerAdapter):
    """Upbit exchange adapter with paper trading support."""

    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        paper_trading: bool | None = None,
    ):
        """Initialize Upbit adapter.

        Args:
            access_key: Upbit API access key (uses env if None).
            secret_key: Upbit API secret key (uses env if None).
            paper_trading: Enable paper trading mode (uses config if None).
        """
        settings = get_settings()

        self._access_key = access_key or settings.upbit_access_key
        self._secret_key = secret_key or settings.upbit_secret_key
        self._paper_trading = paper_trading if paper_trading is not None else settings.is_paper_trading

        # Initialize authenticated client if keys provided
        if self._access_key and self._secret_key:
            self._client = pyupbit.Upbit(self._access_key, self._secret_key)
        else:
            self._client = None
            logger.warning("Upbit API keys not provided - authenticated operations disabled")

        # Paper trading state
        self._paper_balances: dict[str, Decimal] = {
            "KRW": Decimal("1000000"),  # 1M KRW starting balance
            "BTC": Decimal("0"),
        }
        self._paper_orders: dict[str, OrderResult] = {}

    @property
    def is_paper_trading(self) -> bool:
        """Check if in paper trading mode."""
        return self._paper_trading

    def get_balance(self, currency: str) -> Decimal:
        """Get balance for a specific currency."""
        if self._paper_trading:
            return self._paper_balances.get(currency, Decimal("0"))

        UPBIT_RATE_LIMITER.acquire()
        if self._client is None:
            raise RuntimeError("Upbit client not initialized - API keys required")

        balance = self._client.get_balance(currency)
        return Decimal(str(balance)) if balance else Decimal("0")

    def get_all_balances(self) -> dict[str, Decimal]:
        """Get all balances."""
        if self._paper_trading:
            return self._paper_balances.copy()

        UPBIT_RATE_LIMITER.acquire()
        if self._client is None:
            raise RuntimeError("Upbit client not initialized - API keys required")

        balances = self._client.get_balances()

        # Handle unexpected API responses
        if balances is None:
            logger.warning("get_balances returned None")
            return {}

        if isinstance(balances, dict) and "error" in balances:
            logger.warning(f"get_balances error: {balances}")
            return {}

        if not isinstance(balances, list):
            logger.warning(f"get_balances unexpected type: {type(balances)}")
            return {}

        return {
            b["currency"]: Decimal(str(b["balance"]))
            for b in balances
            if isinstance(b, dict) and "balance" in b and float(b["balance"]) > 0
        }

    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        UPBIT_RATE_LIMITER.acquire()
        price = pyupbit.get_current_price(symbol)
        if price is None:
            raise ValueError(f"Failed to get price for {symbol}")
        return float(price)

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "minute1",
        count: int = 200,
    ) -> list[OHLCV]:
        """Get OHLCV candle data."""
        UPBIT_RATE_LIMITER.acquire()
        df = pyupbit.get_ohlcv(symbol, interval=interval, count=count)

        if df is None or df.empty:
            return []

        candles = []
        for idx, row in df.iterrows():
            candles.append(
                OHLCV(
                    timestamp=idx.to_pydatetime(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return candles

    def get_orderbook(self, symbol: str) -> dict:
        """Get orderbook for a symbol."""
        UPBIT_RATE_LIMITER.acquire()
        orderbooks = pyupbit.get_orderbook(symbol)

        if not orderbooks:
            return {"bids": [], "asks": []}

        ob = orderbooks[0] if isinstance(orderbooks, list) else orderbooks
        return {
            "bids": ob.get("orderbook_units", [])[:10],
            "asks": ob.get("orderbook_units", [])[:10],
            "timestamp": ob.get("timestamp"),
        }

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        """Get complete market snapshot."""
        price = self.get_current_price(symbol)
        orderbook = self.get_orderbook(symbol)
        # Use 5-minute candles for balanced reaction with less noise
        # 100 candles = 500 minutes = ~8.3 hours of data
        ohlcv = self.get_ohlcv(symbol, interval="minute5", count=100)

        # Calculate 24h change from daily candles
        daily = self.get_ohlcv(symbol, interval="day", count=2)
        change_24h = None
        if len(daily) >= 2:
            prev_close = daily[-2].close
            if prev_close > 0:
                change_24h = ((price - prev_close) / prev_close) * 100

        # Extract bid/ask from orderbook
        bid_price = None
        ask_price = None
        if orderbook.get("bids"):
            bid_price = orderbook["bids"][0].get("bid_price")
        if orderbook.get("asks"):
            ask_price = orderbook["asks"][0].get("ask_price")

        return MarketSnapshot(
            symbol=symbol,
            current_price=price,
            bid_price=bid_price,
            ask_price=ask_price,
            change_24h_pct=change_24h,
            ohlcv=ohlcv,
        )

    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order."""
        if self._paper_trading:
            return self._submit_paper_order(request)

        return self._submit_live_order(request)

    def _submit_paper_order(self, request: OrderRequest) -> OrderResult:
        """Simulate order execution for paper trading."""
        order_id = f"paper-{uuid.uuid4().hex[:8]}"
        current_price = Decimal(str(self.get_current_price(request.symbol)))

        try:
            if request.side == OrderSide.BUY:
                # Calculate order amount
                if request.amount_krw:
                    order_amount = request.amount_krw
                elif request.quantity:
                    order_amount = request.quantity * current_price
                else:
                    raise ValueError("BUY order requires amount_krw or quantity")

                # Check balance
                krw_balance = self._paper_balances.get("KRW", Decimal("0"))
                if order_amount > krw_balance:
                    return OrderResult(
                        order_id=order_id,
                        symbol=request.symbol,
                        side=request.side,
                        status=OrderStatus.REJECTED,
                        error_message=f"Insufficient KRW balance: {krw_balance} < {order_amount}",
                    )

                # Execute paper order
                filled_qty = order_amount / current_price
                fee = order_amount * Decimal("0.0005")  # 0.05% fee

                self._paper_balances["KRW"] -= order_amount + fee
                currency = request.symbol.split("-")[1]
                self._paper_balances[currency] = self._paper_balances.get(
                    currency, Decimal("0")
                ) + filled_qty

                result = OrderResult(
                    order_id=order_id,
                    symbol=request.symbol,
                    side=request.side,
                    status=OrderStatus.FILLED,
                    requested_quantity=request.quantity,
                    filled_quantity=filled_qty,
                    average_price=current_price,
                    fee=fee,
                )

            else:  # SELL
                if not request.quantity:
                    raise ValueError("SELL order requires quantity")

                currency = request.symbol.split("-")[1]
                balance = self._paper_balances.get(currency, Decimal("0"))

                if request.quantity > balance:
                    return OrderResult(
                        order_id=order_id,
                        symbol=request.symbol,
                        side=request.side,
                        status=OrderStatus.REJECTED,
                        error_message=f"Insufficient {currency} balance: {balance} < {request.quantity}",
                    )

                # Execute paper order
                order_amount = request.quantity * current_price
                fee = order_amount * Decimal("0.0005")

                self._paper_balances[currency] -= request.quantity
                self._paper_balances["KRW"] = self._paper_balances.get(
                    "KRW", Decimal("0")
                ) + order_amount - fee

                result = OrderResult(
                    order_id=order_id,
                    symbol=request.symbol,
                    side=request.side,
                    status=OrderStatus.FILLED,
                    requested_quantity=request.quantity,
                    filled_quantity=request.quantity,
                    average_price=current_price,
                    fee=fee,
                )

            self._paper_orders[order_id] = result
            logger.info(f"Paper order executed: {result}")
            return result

        except Exception as e:
            logger.error(f"Paper order failed: {e}")
            return OrderResult(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )

    def _submit_live_order(self, request: OrderRequest) -> OrderResult:
        """Submit live order to Upbit."""
        UPBIT_RATE_LIMITER.acquire()

        if self._client is None:
            raise RuntimeError("Upbit client not initialized - API keys required")

        try:
            if request.side == OrderSide.BUY:
                if request.order_type == OrderType.MARKET:
                    if request.amount_krw:
                        response = self._client.buy_market_order(
                            request.symbol, float(request.amount_krw)
                        )
                    else:
                        raise ValueError("Market BUY requires amount_krw")
                else:
                    response = self._client.buy_limit_order(
                        request.symbol, float(request.price), float(request.quantity)
                    )
            else:  # SELL
                if request.order_type == OrderType.MARKET:
                    response = self._client.sell_market_order(
                        request.symbol, float(request.quantity)
                    )
                else:
                    response = self._client.sell_limit_order(
                        request.symbol, float(request.price), float(request.quantity)
                    )

            if response is None:
                return OrderResult(
                    order_id="",
                    symbol=request.symbol,
                    side=request.side,
                    status=OrderStatus.FAILED,
                    error_message="No response from Upbit API",
                )

            # Handle error response
            if "error" in response:
                return OrderResult(
                    order_id="",
                    symbol=request.symbol,
                    side=request.side,
                    status=OrderStatus.REJECTED,
                    error_message=response["error"].get("message", str(response)),
                )

            order_id = response.get("uuid", "")

            # For market orders, wait briefly and check if filled
            if request.order_type == OrderType.MARKET and order_id:
                time.sleep(0.5)  # Wait for order to fill
                filled_result = self.get_order_status(order_id)
                if filled_result.status == OrderStatus.FILLED:
                    return filled_result

            return OrderResult(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                status=OrderStatus.SUBMITTED,
                requested_quantity=request.quantity,
            )

        except Exception as e:
            logger.error(f"Live order failed: {e}")
            return OrderResult(
                order_id="",
                symbol=request.symbol,
                side=request.side,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if self._paper_trading:
            if order_id in self._paper_orders:
                self._paper_orders[order_id].status = OrderStatus.CANCELLED
                return True
            return False

        UPBIT_RATE_LIMITER.acquire()
        if self._client is None:
            raise RuntimeError("Upbit client not initialized")

        response = self._client.cancel_order(order_id)
        return response is not None and "error" not in response

    def get_order_status(self, order_id: str) -> OrderResult:
        """Get status of an order."""
        if self._paper_trading:
            if order_id in self._paper_orders:
                return self._paper_orders[order_id]
            return OrderResult(
                order_id=order_id,
                symbol="",
                side=OrderSide.BUY,
                status=OrderStatus.FAILED,
                error_message="Order not found",
            )

        UPBIT_RATE_LIMITER.acquire()
        if self._client is None:
            raise RuntimeError("Upbit client not initialized")

        response = self._client.get_order(order_id)
        if response is None or "error" in response:
            return OrderResult(
                order_id=order_id,
                symbol="",
                side=OrderSide.BUY,
                status=OrderStatus.FAILED,
                error_message="Failed to get order status",
            )

        # Map Upbit status to our status
        upbit_state = response.get("state", "")
        executed_volume = Decimal(response.get("executed_volume", "0"))
        trades_count = response.get("trades_count", 0)

        # For market orders, check if actually filled even if state is "cancel"
        if executed_volume > 0 and trades_count > 0:
            status = OrderStatus.FILLED
        else:
            status_map = {
                "wait": OrderStatus.PENDING,
                "watch": OrderStatus.PENDING,
                "done": OrderStatus.FILLED,
                "cancel": OrderStatus.CANCELLED,
            }
            status = status_map.get(upbit_state, OrderStatus.FAILED)

        # Extract price and fee from trades if available
        trades = response.get("trades", [])
        avg_price = None
        if trades:
            # Calculate weighted average price
            total_funds = sum(Decimal(t.get("funds", "0")) for t in trades)
            total_volume = sum(Decimal(t.get("volume", "0")) for t in trades)
            if total_volume > 0:
                avg_price = total_funds / total_volume

        paid_fee = Decimal(response.get("paid_fee", "0"))

        return OrderResult(
            order_id=order_id,
            symbol=response.get("market", ""),
            side=OrderSide.BUY if response.get("side") == "bid" else OrderSide.SELL,
            status=status,
            filled_quantity=executed_volume,
            average_price=avg_price,
            fee=paid_fee,
        )

    def set_paper_balance(self, currency: str, amount: Decimal) -> None:
        """Set paper trading balance (for testing).

        Args:
            currency: Currency code.
            amount: Balance amount.
        """
        if not self._paper_trading:
            raise RuntimeError("Can only set balance in paper trading mode")
        self._paper_balances[currency] = amount


# Module-level singleton for shared broker instance
_broker: UpbitBrokerAdapter | None = None


def set_broker(broker: UpbitBrokerAdapter | None) -> None:
    """Set global broker instance.

    Args:
        broker: Broker instance or None to clear.
    """
    global _broker
    _broker = broker


def get_broker() -> UpbitBrokerAdapter:
    """Get global broker instance (creates if not exists).

    Returns:
        Shared broker instance.
    """
    global _broker
    if _broker is None:
        _broker = UpbitBrokerAdapter()
    return _broker
