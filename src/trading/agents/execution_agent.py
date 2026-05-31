"""Order execution agent."""

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading.adapters.upbit import UpbitBrokerAdapter, get_broker
from trading.config import get_settings
from trading.core.time import KST
from trading.core.isolated_balance import get_isolated_tracker
from trading.core.models import OrderRequest, OrderResult, OrderSide, OrderStatus
from trading.core.performance import get_performance_tracker
from trading.core.state import Decision, TradingState

logger = logging.getLogger(__name__)


class ExecutionAgent:
    """Agent for executing trading orders."""

    def __init__(
        self,
        broker: UpbitBrokerAdapter | None = None,
        log_dir: Path | None = None,
        asset_symbol: str | None = None,
        upbit_symbol: str | None = None,
    ):
        """Initialize execution agent.

        Args:
            broker: Broker adapter for order execution.
            log_dir: Directory for trade logs (defaults to settings.asset_log_dir
                so ETH/XRP bots write to per-asset subdirectories).
            asset_symbol: Ticker held by the bot (default settings.asset_symbol).
            upbit_symbol: Upbit market symbol (default settings.upbit_symbol).
        """
        settings = get_settings()
        self.broker = broker or get_broker()
        self.asset_symbol = asset_symbol or settings.asset_symbol
        self.upbit_symbol = upbit_symbol or settings.upbit_symbol
        self.log_dir = log_dir or settings.asset_log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, decision: Decision, market_price: float) -> OrderResult | None:
        """Execute trading decision.

        Args:
            decision: Approved trading decision.
            market_price: Current market price.

        Returns:
            OrderResult if executed, None if skipped.
        """
        # Only execute approved decisions
        if decision.get("status") != "approved":
            logger.info(f"Skipping non-approved decision: {decision.get('status')}")
            return None

        action = decision.get("action")
        if action == "HOLD":
            logger.info("Action is HOLD - no execution needed")
            return None

        # Use position_delta_pct if available (target position based sizing)
        # Otherwise fall back to suggested_size_pct (legacy)
        position_delta_pct = decision.get("position_delta_pct")
        if position_delta_pct is not None:
            # Position delta: positive=buy, negative=sell
            # Use absolute value as the size to trade
            size_pct = abs(position_delta_pct)
            logger.info(
                f"Using position delta: {position_delta_pct:+.1f}% "
                f"(target: {decision.get('target_position_pct', 0):.1f}%)"
            )
        else:
            size_pct = decision.get("suggested_size_pct", 0)

        if size_pct <= 0:
            logger.warning("Size percentage is 0 - no execution")
            return None

        # Check if isolated mode is enabled
        isolated_tracker = get_isolated_tracker()

        # In isolated mode, the broker balance is irrelevant for sizing —
        # we use the tracker's virtual balance instead. Skip the API call.
        if isolated_tracker is None:
            balances = self.broker.get_all_balances()
            krw = balances.get("KRW", Decimal("0"))
            asset_held = balances.get(self.asset_symbol, Decimal("0"))
        else:
            krw = Decimal("0")
            asset_held = Decimal("0")

        # Build order request
        symbol = self.upbit_symbol

        if action == "BUY":
            if isolated_tracker is not None:
                # Isolated mode: use only available capital from tracker.
                # get_balances() returns the asset key dynamically
                # ({'KRW', 'ETH'} for ETH bot, {'KRW', 'BTC'} for BTC bot).
                isolated_balances = isolated_tracker.get_balances()
                available_krw = float(isolated_balances.get("KRW", Decimal("0")))
                isolated_asset = float(
                    isolated_balances.get(self.asset_symbol, Decimal("0"))
                )

                # Calculate total portfolio value for correct size calculation
                total_portfolio = available_krw + (isolated_asset * market_price)

                # size_pct is percentage of TOTAL portfolio, not just KRW
                amount_krw = total_portfolio * (size_pct / 100)

                # Cap at available KRW
                if amount_krw > available_krw:
                    amount_krw = available_krw

                if amount_krw < 5000:
                    logger.warning(
                        f"Isolated mode: Insufficient funds. "
                        f"Calculated: {amount_krw:,.0f} KRW, available: {available_krw:,.0f} KRW, "
                        f"need 5000 KRW minimum"
                    )
                    return None

                logger.info(
                    f"Isolated BUY: using {amount_krw:,.0f} KRW "
                    f"({size_pct:.1f}% of portfolio {total_portfolio:,.0f} KRW)"
                )
            else:
                # Normal mode: use percentage of total KRW
                amount_krw = float(krw) * (size_pct / 100)

            request = OrderRequest(
                symbol=symbol,
                side=OrderSide.BUY,
                amount_krw=Decimal(str(amount_krw)),
            )

        elif action == "SELL":
            min_order_krw = 5000  # Upbit minimum order amount

            if isolated_tracker is not None:
                # Isolated mode: only sell bot's own holdings
                isolated_balances = isolated_tracker.get_balances()
                available_krw = float(isolated_balances.get("KRW", Decimal("0")))
                sellable_asset = float(
                    isolated_balances.get(self.asset_symbol, Decimal("0"))
                )

                if sellable_asset <= 0:
                    logger.warning(
                        f"Isolated mode: No {self.asset_symbol} to sell "
                        f"(bot has not purchased any)"
                    )
                    return None

                # Calculate total portfolio value for position-based sizing
                total_portfolio = available_krw + (sellable_asset * market_price)

                # size_pct is percentage of TOTAL portfolio delta to reduce
                # Convert to asset quantity
                sell_value_krw = total_portfolio * (size_pct / 100)
                sell_qty = sell_value_krw / market_price if market_price > 0 else 0

                # Cap at sellable amount
                if sell_qty > sellable_asset:
                    sell_qty = sellable_asset
                    sell_value_krw = sell_qty * market_price

                total_value_krw = sellable_asset * market_price

                # Check minimum order amount
                if sell_value_krw < min_order_krw:
                    if total_value_krw >= min_order_krw:
                        # Sell all if total is above minimum
                        sell_qty = sellable_asset
                        logger.info(
                            f"Isolated SELL: full amount {sell_qty:.8f} "
                            f"{self.asset_symbol} (partial {sell_value_krw:,.0f} "
                            f"KRW < min {min_order_krw} KRW)"
                        )
                    else:
                        logger.warning(
                            f"Cannot sell: total {total_value_krw:,.0f} KRW < min {min_order_krw} KRW"
                        )
                        return None
                else:
                    logger.info(
                        f"Isolated SELL: {sell_qty:.8f} {self.asset_symbol} "
                        f"({sell_value_krw:,.0f} KRW) "
                        f"({size_pct:.1f}% of portfolio {total_portfolio:,.0f} KRW)"
                    )
            else:
                # Normal mode: use percentage of total portfolio value
                asset_balance = float(asset_held)
                krw_balance = float(krw)
                total_portfolio = krw_balance + (asset_balance * market_price)

                # size_pct is percentage of portfolio delta to reduce
                sell_value_krw = total_portfolio * (size_pct / 100)
                sell_qty = sell_value_krw / market_price if market_price > 0 else 0

                # Cap at available holdings
                if sell_qty > asset_balance:
                    sell_qty = asset_balance

            request = OrderRequest(
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=Decimal(str(sell_qty)),
            )

        else:
            logger.warning(f"Unknown action: {action}")
            return None

        # Execute order
        logger.info(f"Executing {action} order: {request}")
        result = self.broker.submit_order(request)

        # Log trade
        self._log_trade(decision, request, result)

        # Record to isolated tracker for any partial-or-full fill. Skipping
        # PARTIALLY_FILLED would leak the actual Upbit-side balance change.
        if (
            isolated_tracker is not None
            and result.filled_quantity > 0
            and result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        ):
            self._record_to_isolated_tracker(action, result, isolated_tracker)

        return result

    def _record_to_isolated_tracker(
        self,
        action: str,
        result: OrderResult,
        tracker,
    ) -> None:
        """Record trade to isolated tracker.

        Args:
            action: BUY or SELL.
            result: Executed order result.
            tracker: IsolatedBalanceTracker instance.
        """
        # Guard: missing average_price would create a zero-cost-basis entry
        # that permanently breaks P&L tracking. Skip and alert instead.
        if result.average_price is None or result.average_price <= 0:
            logger.error(
                f"Isolated tracker NOT updated: {action} result has no "
                f"average_price (order_id={result.order_id}, "
                f"filled_qty={result.filled_quantity}). "
                f"Tracker now diverges from real exchange balance — investigate."
            )
            return

        avg_price = result.average_price
        filled_qty = result.filled_quantity
        fee = result.fee

        if action == "BUY":
            # KRW spent = qty * price (fee is separate)
            krw_spent = filled_qty * avg_price
            ok = tracker.record_buy(
                krw_spent=krw_spent,
                asset_received=filled_qty,
                fee_krw=fee,
            )
            if not ok:
                logger.error(
                    f"Isolated tracker BUY record FAILED (insufficient tracker KRW). "
                    f"Real Upbit balance changed but tracker diverges. "
                    f"krw_spent={krw_spent}, asset_received={filled_qty}, fee={fee}"
                )
        elif action == "SELL":
            # KRW received = (qty * price) - fee
            krw_received = (filled_qty * avg_price) - fee
            ok = tracker.record_sell(
                asset_sold=filled_qty,
                krw_received=krw_received,
                fee_krw=fee,
            )
            if not ok:
                logger.error(
                    f"Isolated tracker SELL record FAILED (insufficient tracker "
                    f"{self.asset_symbol}). Real Upbit balance changed but "
                    f"tracker diverges. "
                    f"asset_sold={filled_qty}, krw_received={krw_received}, fee={fee}"
                )

    def _log_trade(
        self,
        decision: Decision,
        request: OrderRequest,
        result: OrderResult,
    ) -> None:
        """Log trade to file and performance tracker.

        Args:
            decision: The decision that triggered the trade.
            request: Order request.
            result: Order result.
        """
        now = datetime.now(KST)
        log_entry = {
            "timestamp": now.isoformat(),
            "decision": {
                "action": decision.get("action"),
                "confidence": decision.get("confidence"),
                "size_pct": decision.get("suggested_size_pct"),
                "target_position_pct": decision.get("target_position_pct"),
                "position_delta_pct": decision.get("position_delta_pct"),
                "rationale": decision.get("rationale"),
            },
            "order": {
                "symbol": request.symbol,
                "side": request.side.value,
                "amount_krw": float(request.amount_krw) if request.amount_krw else None,
                "quantity": float(request.quantity) if request.quantity else None,
            },
            "result": {
                "order_id": result.order_id,
                "status": result.status.value,
                "filled_quantity": float(result.filled_quantity),
                "average_price": float(result.average_price) if result.average_price else None,
                "fee": float(result.fee),
                "error": result.error_message,
            },
        }

        # Write to daily log file
        log_file = self.log_dir / f"trades_{now.strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        logger.info(f"Trade logged to {log_file}")

        # Record to performance tracker if available
        tracker = get_performance_tracker()
        if tracker and result.status == OrderStatus.FILLED:
            action = decision.get("action")
            if action in ("BUY", "SELL"):
                # Calculate amount_krw for the trade
                avg_price = float(result.average_price) if result.average_price else 0
                filled_qty = float(result.filled_quantity)
                amount_krw = filled_qty * avg_price

                tracker.record_trade(
                    action=action,
                    btc_quantity=filled_qty,
                    price=avg_price,
                    amount_krw=amount_krw,
                    fee_krw=float(result.fee),
                    confidence=decision.get("confidence", 0),
                    rationale=decision.get("rationale", ""),
                    timestamp=now,
                )


def execution_agent_node(state: TradingState) -> dict:
    """LangGraph node function for execution agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with execution result.
    """
    agent = ExecutionAgent()

    try:
        decision = state.get("decision")
        if not decision:
            return {
                "error": "No decision to execute",
                "last_updated": datetime.now(KST).isoformat(),
            }

        market = state.get("market", {})
        market_price = market.get("current_price", 0)

        result = agent.execute(decision, market_price)

        # Update decision status
        if result:
            if result.status == OrderStatus.FILLED:
                decision["status"] = "executed"
            elif result.status in (OrderStatus.REJECTED, OrderStatus.FAILED):
                decision["status"] = "rejected"
                decision["rationale"] += f" | Execution failed: {result.error_message}"

        return {
            "decision": decision,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Execution agent failed: {e}")

        decision = state.get("decision")
        if decision:
            decision["status"] = "rejected"

        return {
            "decision": decision,
            "error": f"Execution error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
