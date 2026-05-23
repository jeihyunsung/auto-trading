"""Backtesting engine for strategy simulation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Callable

from trading.agents.decision_agent import DecisionAgent
from trading.agents.indicator_agent import IndicatorAgent
from trading.backtest.data import HistoricalDataPoint
from trading.core.hysteresis import HysteresisConfig, HysteresisManager
from trading.core.state import Decision, IndicatorSignals, MarketData, TradingState
from trading.indicators.volatility import get_volatility_level

logger = logging.getLogger(__name__)


class TradeType(Enum):
    """Trade type enumeration."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Trade:
    """Represents a single trade in backtest.

    Attributes:
        timestamp: Trade execution time.
        trade_type: BUY or SELL.
        price: Execution price.
        quantity: BTC quantity.
        value_krw: Trade value in KRW.
        fee: Trading fee.
        confidence: Decision confidence.
        rationale: Decision rationale.
    """

    timestamp: datetime
    trade_type: TradeType
    price: float
    quantity: float
    value_krw: float
    fee: float
    confidence: float
    rationale: str


@dataclass
class PortfolioSnapshot:
    """Portfolio state at a point in time.

    Attributes:
        timestamp: Snapshot time.
        cash_krw: Cash balance in KRW.
        btc_quantity: BTC holdings.
        btc_price: Current BTC price.
        total_value_krw: Total portfolio value in KRW.
        unrealized_pnl_pct: Unrealized P&L percentage.
    """

    timestamp: datetime
    cash_krw: float
    btc_quantity: float
    btc_price: float
    total_value_krw: float
    unrealized_pnl_pct: float


@dataclass
class BacktestConfig:
    """Backtest configuration.

    Attributes:
        initial_capital_krw: Starting capital in KRW.
        fee_rate: Trading fee rate (e.g., 0.0005 for 0.05%).
        slippage_rate: Simulated slippage rate.
        use_llm: Whether to use LLM for decisions (expensive).
        use_hysteresis: Whether to apply hysteresis to prevent oscillation.
        confidence_threshold: Minimum confidence for execution.
        max_position_pct: Maximum position as % of portfolio.
    """

    initial_capital_krw: float = 10_000_000
    fee_rate: float = 0.0005
    slippage_rate: float = 0.001
    use_llm: bool = False
    use_hysteresis: bool = False
    confidence_threshold: float = 0.5
    max_position_pct: float = 50.0


@dataclass
class BacktestResult:
    """Backtest result summary.

    Attributes:
        config: Backtest configuration used.
        start_date: Backtest start date.
        end_date: Backtest end date.
        initial_capital: Starting capital.
        final_value: Ending portfolio value.
        trades: List of all trades.
        portfolio_history: Portfolio snapshots over time.
        decisions: All decisions made (including HOLD).
    """

    config: BacktestConfig
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_value: float
    trades: list[Trade] = field(default_factory=list)
    portfolio_history: list[PortfolioSnapshot] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        """Calculate total return percentage."""
        return ((self.final_value - self.initial_capital) / self.initial_capital) * 100

    @property
    def num_trades(self) -> int:
        """Total number of trades."""
        return len(self.trades)

    @property
    def num_buys(self) -> int:
        """Number of buy trades."""
        return len([t for t in self.trades if t.trade_type == TradeType.BUY])

    @property
    def num_sells(self) -> int:
        """Number of sell trades."""
        return len([t for t in self.trades if t.trade_type == TradeType.SELL])


class BacktestEngine:
    """Engine for running backtests on trading strategies."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        derivatives_by_ts: dict | None = None,
    ):
        """Initialize backtest engine.

        Args:
            config: Backtest configuration.
            derivatives_by_ts: Optional pre-loaded historical derivatives data,
                keyed by datetime. See backtest.derivatives_loader.
                If provided, each cycle's TradingState gets the nearest past
                snapshot — closes the "all-zero derivatives" gap that makes
                LLM decisions overly conservative in backtests.
        """
        self.config = config or BacktestConfig()
        self.indicator_agent = IndicatorAgent()
        self.decision_agent = DecisionAgent()
        self._derivatives_by_ts = derivatives_by_ts or {}

        # Hysteresis manager (optional)
        self._hysteresis: HysteresisManager | None = None
        if self.config.use_hysteresis:
            # Use faster decay for backtest (simulated time passes quickly)
            hysteresis_config = HysteresisConfig(
                hold_to_action_delta=0.15,
                action_to_hold_delta=0.20,
                action_reversal_delta=0.35,
                decay_factor_per_hour=0.1,
                emergency_override_confidence=0.90,
            )
            self._hysteresis = HysteresisManager(hysteresis_config)

        # Portfolio state
        self._cash_krw = 0.0
        self._btc_quantity = 0.0
        self._avg_entry_price = 0.0
        self._cycle_count = 0

    def run(
        self,
        data_points: list[HistoricalDataPoint],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            data_points: Historical data points to backtest.
            progress_callback: Optional callback for progress updates.

        Returns:
            BacktestResult with performance data.
        """
        if not data_points:
            raise ValueError("No data points provided for backtesting")

        logger.info(f"Starting backtest with {len(data_points)} data points")
        logger.info(f"Config: initial_capital={self.config.initial_capital_krw:,.0f} KRW")
        logger.info(f"Hysteresis: {'enabled' if self.config.use_hysteresis else 'disabled'}")

        # Initialize portfolio
        self._cash_krw = self.config.initial_capital_krw
        self._btc_quantity = 0.0
        self._avg_entry_price = 0.0
        self._cycle_count = 0

        # Reset hysteresis if enabled
        if self._hysteresis:
            self._hysteresis.reset()

        # Result containers
        trades: list[Trade] = []
        portfolio_history: list[PortfolioSnapshot] = []
        decisions: list[dict] = []

        start_date = data_points[0].timestamp
        end_date = data_points[-1].timestamp

        for i, data_point in enumerate(data_points):
            if progress_callback:
                progress_callback(i + 1, len(data_points))

            self._cycle_count += 1

            # Build state for this data point
            state = self._build_state(data_point)

            # Get raw decision
            raw_decision = self._get_decision(state)

            # Apply hysteresis if enabled (with simulated time for backtest)
            if self._hysteresis:
                decision = self._hysteresis.apply_hysteresis(
                    raw_decision,
                    self._cycle_count,
                    simulated_time=data_point.timestamp,
                )
                hysteresis_applied = decision.get("action") != raw_decision.get("action")
            else:
                decision = raw_decision
                hysteresis_applied = False

            decisions.append({
                "timestamp": data_point.timestamp.isoformat(),
                "action": decision.get("action"),
                "confidence": decision.get("confidence"),
                "rationale": decision.get("rationale"),
                "price": data_point.current_price,
                "raw_action": raw_decision.get("action") if hysteresis_applied else None,
                "hysteresis_applied": hysteresis_applied,
            })

            # Execute trade if conditions met
            trade = self._execute_decision(decision, data_point)
            if trade:
                trades.append(trade)

            # Record portfolio snapshot
            snapshot = self._get_portfolio_snapshot(data_point)
            portfolio_history.append(snapshot)

        # Calculate final value
        final_value = self._calculate_portfolio_value(data_points[-1].current_price)

        result = BacktestResult(
            config=self.config,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital_krw,
            final_value=final_value,
            trades=trades,
            portfolio_history=portfolio_history,
            decisions=decisions,
        )

        logger.info(f"Backtest complete: {result.total_return_pct:+.2f}% return")
        logger.info(f"Total trades: {result.num_trades} ({result.num_buys} buys, {result.num_sells} sells)")

        # Log hysteresis stats if enabled
        if self._hysteresis:
            stats = self._hysteresis.stats.to_dict()
            logger.info(
                f"Hysteresis stats: {stats['decisions_overridden']} overridden "
                f"({stats['override_rate_pct']:.1f}%), "
                f"{stats['reversals_blocked']} reversals blocked"
            )

        return result

    def _build_state(self, data_point: HistoricalDataPoint) -> TradingState:
        """Build TradingState from historical data point.

        Args:
            data_point: Historical data point.

        Returns:
            TradingState for decision making.
        """
        # Calculate indicators
        indicators = self.indicator_agent.calculate([
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in data_point.ohlcv
        ])

        # Calculate volatility
        volatility = get_volatility_level(data_point.ohlcv)

        # Build market data
        market_data = MarketData(
            symbol="KRW-BTC",
            current_price=data_point.current_price,
            ohlcv=[
                {
                    "timestamp": c.timestamp.isoformat(),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in data_point.ohlcv
            ],
            orderbook=None,
            volatility_level=volatility,
            percent_change_1h=0.0,
            percent_change_24h=data_point.change_24h_pct,
        )

        # Build portfolio state
        total_value = self._calculate_portfolio_value(data_point.current_price)
        btc_value = self._btc_quantity * data_point.current_price
        exposure = (btc_value / total_value * 100) if total_value > 0 else 0

        # Calculate unrealized P&L
        if self._btc_quantity > 0 and self._avg_entry_price > 0:
            unrealized_pnl = ((data_point.current_price - self._avg_entry_price) / self._avg_entry_price) * 100
        else:
            unrealized_pnl = 0.0

        # Look up the nearest past derivatives snapshot (if loaded)
        derivatives = None
        if self._derivatives_by_ts:
            from trading.backtest.derivatives_loader import lookup_nearest_past
            derivatives = lookup_nearest_past(
                self._derivatives_by_ts, data_point.timestamp
            )

        state: TradingState = {
            "market": market_data,
            "indicators": indicators,
            "derivatives": derivatives,
            "portfolio": {
                "cash_krw": self._cash_krw,
                "btc_balance": self._btc_quantity,
                "avg_entry_price": self._avg_entry_price,
                "unrealized_pnl": unrealized_pnl,
                "exposure_pct": exposure,
            },
            "risk": {
                "position_limit_pct": self.config.max_position_pct,
                "max_loss_pct": 3.0,
                "daily_loss_pct": 0.0,
                "is_kill_switch_on": False,
            },
            "anomalies": [],
            "decision": None,
            "error": None,
            "last_updated": data_point.timestamp.isoformat(),
        }

        return state

    def _get_decision(self, state: TradingState) -> Decision:
        """Get trading decision for current state.

        Args:
            state: Current trading state.

        Returns:
            Decision dict.
        """
        if self.config.use_llm:
            return self.decision_agent.decide(state)
        else:
            # Use backtest-specific rule-based decision (less strict)
            return self._decide_rule_based_backtest(state)

    def _decide_rule_based_backtest(self, state: TradingState) -> Decision:
        """Backtest-optimized rule-based decision.

        Less strict than production - requires only 2 signals instead of 3.

        Args:
            state: Current trading state.

        Returns:
            Decision dict.
        """
        indicators = state.get("indicators", {})
        market = state.get("market", {})

        trend = indicators.get("trend", "neutral")
        momentum = indicators.get("momentum", "neutral")
        rsi = indicators.get("signals", {}).get("rsi", 50)
        volatility = indicators.get("volatility", "medium")

        bullish_signals = 0
        bearish_signals = 0

        # Trend signal
        if trend == "bullish":
            bullish_signals += 1
        elif trend == "bearish":
            bearish_signals += 1

        # Momentum signal
        if momentum == "oversold":
            bullish_signals += 1
        elif momentum == "overbought":
            bearish_signals += 1

        # RSI extremes (stronger weight)
        if rsi <= 25:
            bullish_signals += 2  # Very oversold
        elif rsi <= 35:
            bullish_signals += 1
        elif rsi >= 75:
            bearish_signals += 2  # Very overbought
        elif rsi >= 65:
            bearish_signals += 1

        # Decision with lower threshold (2 signals instead of 3)
        if bullish_signals >= 2 and bullish_signals > bearish_signals:
            confidence = min(1.0, bullish_signals / 4)
            return Decision(
                action="BUY",
                confidence=confidence,
                suggested_size_pct=self._calculate_backtest_size(confidence, volatility),
                rationale=f"Bullish: trend={trend}, momentum={momentum}, RSI={rsi:.1f}",
                status="pending",
            )

        if bearish_signals >= 2 and bearish_signals > bullish_signals:
            confidence = min(1.0, bearish_signals / 4)
            return Decision(
                action="SELL",
                confidence=confidence,
                suggested_size_pct=self._calculate_backtest_size(confidence, volatility),
                rationale=f"Bearish: trend={trend}, momentum={momentum}, RSI={rsi:.1f}",
                status="pending",
            )

        return Decision(
            action="HOLD",
            confidence=0.3,
            suggested_size_pct=0.0,
            rationale=f"Neutral: bullish={bullish_signals}, bearish={bearish_signals}, RSI={rsi:.1f}",
            status="pending",
        )

    def _calculate_backtest_size(self, confidence: float, volatility: str) -> float:
        """Calculate position size for backtest.

        Args:
            confidence: Decision confidence.
            volatility: Volatility level.

        Returns:
            Position size percentage.
        """
        base_size = confidence * 15  # More aggressive for backtest

        if volatility == "high":
            base_size *= 0.5
        elif volatility == "low":
            base_size *= 1.2

        return min(20.0, max(0.0, base_size))

    def _execute_decision(
        self,
        decision: Decision,
        data_point: HistoricalDataPoint,
    ) -> Trade | None:
        """Execute trading decision.

        Args:
            decision: Trading decision.
            data_point: Current data point.

        Returns:
            Trade if executed, None otherwise.
        """
        action = decision.get("action")
        confidence = decision.get("confidence", 0)

        # Skip if confidence too low
        if confidence < self.config.confidence_threshold:
            return None

        # Skip HOLD actions
        if action == "HOLD":
            return None

        size_pct = decision.get("suggested_size_pct", 0)
        if size_pct <= 0:
            return None

        # Apply slippage
        price = data_point.current_price
        if action == "BUY":
            price *= (1 + self.config.slippage_rate)
        else:
            price *= (1 - self.config.slippage_rate)

        if action == "BUY":
            return self._execute_buy(price, size_pct, confidence, decision, data_point)
        elif action == "SELL":
            return self._execute_sell(price, size_pct, confidence, decision, data_point)

        return None

    def _execute_buy(
        self,
        price: float,
        size_pct: float,
        confidence: float,
        decision: Decision,
        data_point: HistoricalDataPoint,
    ) -> Trade | None:
        """Execute buy order.

        Args:
            price: Execution price.
            size_pct: Size as percentage of cash.
            confidence: Decision confidence.
            decision: Original decision.
            data_point: Current data point.

        Returns:
            Trade if executed, None otherwise.
        """
        # Calculate order value
        order_value = self._cash_krw * (size_pct / 100)
        fee = order_value * self.config.fee_rate
        net_value = order_value - fee

        if net_value <= 0:
            return None

        # Calculate quantity
        quantity = net_value / price

        # Update portfolio
        old_total_btc_value = self._btc_quantity * self._avg_entry_price
        new_btc_value = quantity * price

        self._cash_krw -= order_value
        self._btc_quantity += quantity

        # Update average entry price
        if self._btc_quantity > 0:
            self._avg_entry_price = (old_total_btc_value + new_btc_value) / self._btc_quantity

        return Trade(
            timestamp=data_point.timestamp,
            trade_type=TradeType.BUY,
            price=price,
            quantity=quantity,
            value_krw=order_value,
            fee=fee,
            confidence=confidence,
            rationale=decision.get("rationale", ""),
        )

    def _execute_sell(
        self,
        price: float,
        size_pct: float,
        confidence: float,
        decision: Decision,
        data_point: HistoricalDataPoint,
    ) -> Trade | None:
        """Execute sell order.

        Args:
            price: Execution price.
            size_pct: Size as percentage of BTC holdings.
            confidence: Decision confidence.
            decision: Original decision.
            data_point: Current data point.

        Returns:
            Trade if executed, None otherwise.
        """
        if self._btc_quantity <= 0:
            return None

        # Calculate quantity to sell
        quantity = self._btc_quantity * (size_pct / 100)
        gross_value = quantity * price
        fee = gross_value * self.config.fee_rate
        net_value = gross_value - fee

        if net_value <= 0:
            return None

        # Update portfolio
        self._btc_quantity -= quantity
        self._cash_krw += net_value

        # Reset average entry if fully sold
        if self._btc_quantity <= 0:
            self._btc_quantity = 0
            self._avg_entry_price = 0

        return Trade(
            timestamp=data_point.timestamp,
            trade_type=TradeType.SELL,
            price=price,
            quantity=quantity,
            value_krw=gross_value,
            fee=fee,
            confidence=confidence,
            rationale=decision.get("rationale", ""),
        )

    def _calculate_portfolio_value(self, current_price: float) -> float:
        """Calculate total portfolio value.

        Args:
            current_price: Current BTC price.

        Returns:
            Total portfolio value in KRW.
        """
        btc_value = self._btc_quantity * current_price
        return self._cash_krw + btc_value

    def _get_portfolio_snapshot(self, data_point: HistoricalDataPoint) -> PortfolioSnapshot:
        """Get current portfolio snapshot.

        Args:
            data_point: Current data point.

        Returns:
            PortfolioSnapshot.
        """
        total_value = self._calculate_portfolio_value(data_point.current_price)

        if self._btc_quantity > 0 and self._avg_entry_price > 0:
            unrealized_pnl = ((data_point.current_price - self._avg_entry_price) / self._avg_entry_price) * 100
        else:
            unrealized_pnl = 0.0

        return PortfolioSnapshot(
            timestamp=data_point.timestamp,
            cash_krw=self._cash_krw,
            btc_quantity=self._btc_quantity,
            btc_price=data_point.current_price,
            total_value_krw=total_value,
            unrealized_pnl_pct=unrealized_pnl,
        )
