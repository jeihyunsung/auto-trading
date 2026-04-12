"""Performance metrics calculation for backtesting."""

import math
from dataclasses import dataclass
from datetime import timedelta

from trading.backtest.engine import BacktestResult, PortfolioSnapshot, Trade, TradeType


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for backtest results.

    Attributes:
        total_return_pct: Total return percentage.
        annualized_return_pct: Annualized return percentage.
        sharpe_ratio: Risk-adjusted return (Sharpe Ratio).
        sortino_ratio: Downside risk-adjusted return.
        max_drawdown_pct: Maximum drawdown percentage.
        max_drawdown_duration_days: Duration of max drawdown.
        win_rate_pct: Percentage of winning trades.
        profit_factor: Gross profit / Gross loss.
        avg_win_pct: Average winning trade percentage.
        avg_loss_pct: Average losing trade percentage.
        total_trades: Total number of trades.
        avg_holding_period_hours: Average holding period.
        volatility_pct: Portfolio volatility (annualized).
        calmar_ratio: Return / Max Drawdown.
        buy_and_hold_return_pct: Buy and hold benchmark return.
        alpha_pct: Excess return over buy and hold.
    """

    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    win_rate_pct: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    total_trades: int
    avg_holding_period_hours: float
    volatility_pct: float
    calmar_ratio: float
    buy_and_hold_return_pct: float
    alpha_pct: float

    @classmethod
    def from_backtest_result(
        cls,
        result: BacktestResult,
        risk_free_rate: float = 0.035,
    ) -> "PerformanceMetrics":
        """Calculate metrics from backtest result.

        Args:
            result: Backtest result.
            risk_free_rate: Annual risk-free rate for Sharpe calculation.

        Returns:
            PerformanceMetrics instance.
        """
        # Basic returns
        total_return = result.total_return_pct

        # Calculate period in years
        period_days = (result.end_date - result.start_date).days
        period_years = period_days / 365 if period_days > 0 else 1

        # Annualized return
        if period_years > 0 and total_return > -100:
            annualized_return = ((1 + total_return / 100) ** (1 / period_years) - 1) * 100
        else:
            annualized_return = total_return

        # Calculate daily returns
        daily_returns = cls._calculate_daily_returns(result.portfolio_history)

        # Volatility (annualized)
        if daily_returns:
            volatility = cls._calculate_volatility(daily_returns) * math.sqrt(365) * 100
        else:
            volatility = 0.0

        # Sharpe Ratio
        sharpe = cls._calculate_sharpe_ratio(
            annualized_return / 100,
            volatility / 100,
            risk_free_rate,
        )

        # Sortino Ratio
        sortino = cls._calculate_sortino_ratio(
            daily_returns,
            annualized_return / 100,
            risk_free_rate,
        )

        # Max Drawdown
        max_dd, max_dd_duration = cls._calculate_max_drawdown(result.portfolio_history)

        # Trade analysis
        trade_stats = cls._analyze_trades(result.trades, result.portfolio_history)

        # Buy and hold benchmark
        if result.portfolio_history:
            first_price = result.portfolio_history[0].btc_price
            last_price = result.portfolio_history[-1].btc_price
            buy_hold_return = ((last_price - first_price) / first_price) * 100
        else:
            buy_hold_return = 0.0

        # Alpha (excess return over benchmark)
        alpha = total_return - buy_hold_return

        # Calmar Ratio
        calmar = annualized_return / abs(max_dd) if max_dd != 0 else 0.0

        return cls(
            total_return_pct=total_return,
            annualized_return_pct=annualized_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            max_drawdown_duration_days=max_dd_duration,
            win_rate_pct=trade_stats["win_rate"],
            profit_factor=trade_stats["profit_factor"],
            avg_win_pct=trade_stats["avg_win"],
            avg_loss_pct=trade_stats["avg_loss"],
            total_trades=len(result.trades),
            avg_holding_period_hours=trade_stats["avg_holding_hours"],
            volatility_pct=volatility,
            calmar_ratio=calmar,
            buy_and_hold_return_pct=buy_hold_return,
            alpha_pct=alpha,
        )

    @staticmethod
    def _calculate_daily_returns(
        portfolio_history: list[PortfolioSnapshot],
    ) -> list[float]:
        """Calculate daily returns from portfolio history.

        Args:
            portfolio_history: List of portfolio snapshots.

        Returns:
            List of daily return percentages.
        """
        if len(portfolio_history) < 2:
            return []

        returns = []
        for i in range(1, len(portfolio_history)):
            prev_value = portfolio_history[i - 1].total_value_krw
            curr_value = portfolio_history[i].total_value_krw

            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)

        return returns

    @staticmethod
    def _calculate_volatility(returns: list[float]) -> float:
        """Calculate standard deviation of returns.

        Args:
            returns: List of returns.

        Returns:
            Standard deviation.
        """
        if len(returns) < 2:
            return 0.0

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(variance)

    @staticmethod
    def _calculate_sharpe_ratio(
        annualized_return: float,
        volatility: float,
        risk_free_rate: float,
    ) -> float:
        """Calculate Sharpe Ratio.

        Args:
            annualized_return: Annualized return (decimal).
            volatility: Annualized volatility (decimal).
            risk_free_rate: Risk-free rate (decimal).

        Returns:
            Sharpe Ratio.
        """
        if volatility == 0:
            return 0.0
        return (annualized_return - risk_free_rate) / volatility

    @staticmethod
    def _calculate_sortino_ratio(
        daily_returns: list[float],
        annualized_return: float,
        risk_free_rate: float,
    ) -> float:
        """Calculate Sortino Ratio (uses downside deviation).

        Args:
            daily_returns: List of daily returns.
            annualized_return: Annualized return (decimal).
            risk_free_rate: Risk-free rate (decimal).

        Returns:
            Sortino Ratio.
        """
        if not daily_returns:
            return 0.0

        # Calculate downside deviation (only negative returns)
        negative_returns = [r for r in daily_returns if r < 0]

        if not negative_returns:
            return float("inf") if annualized_return > risk_free_rate else 0.0

        downside_variance = sum(r ** 2 for r in negative_returns) / len(negative_returns)
        downside_deviation = math.sqrt(downside_variance) * math.sqrt(365)

        if downside_deviation == 0:
            return 0.0

        return (annualized_return - risk_free_rate) / downside_deviation

    @staticmethod
    def _calculate_max_drawdown(
        portfolio_history: list[PortfolioSnapshot],
    ) -> tuple[float, float]:
        """Calculate maximum drawdown and its duration.

        Args:
            portfolio_history: List of portfolio snapshots.

        Returns:
            Tuple of (max_drawdown_pct, duration_days).
        """
        if not portfolio_history:
            return 0.0, 0.0

        peak = portfolio_history[0].total_value_krw
        max_drawdown = 0.0
        max_dd_duration = 0.0

        current_dd_start = None
        peak_timestamp = portfolio_history[0].timestamp

        for snapshot in portfolio_history:
            if snapshot.total_value_krw > peak:
                # New peak
                peak = snapshot.total_value_krw
                peak_timestamp = snapshot.timestamp
                current_dd_start = None
            else:
                # In drawdown
                drawdown = (peak - snapshot.total_value_krw) / peak * 100

                if drawdown > max_drawdown:
                    max_drawdown = drawdown

                    if current_dd_start is None:
                        current_dd_start = peak_timestamp

                    duration = (snapshot.timestamp - current_dd_start).days
                    max_dd_duration = max(max_dd_duration, duration)

        return max_drawdown, max_dd_duration

    @staticmethod
    def _analyze_trades(
        trades: list[Trade],
        portfolio_history: list[PortfolioSnapshot],
    ) -> dict:
        """Analyze trade performance.

        Args:
            trades: List of trades.
            portfolio_history: Portfolio history.

        Returns:
            Dictionary with trade statistics.
        """
        if not trades:
            return {
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_holding_hours": 0.0,
            }

        # Pair trades to calculate P&L
        trade_pnls = []
        buy_trades = []

        for trade in trades:
            if trade.trade_type == TradeType.BUY:
                buy_trades.append(trade)
            elif trade.trade_type == TradeType.SELL and buy_trades:
                # Match with oldest buy (FIFO)
                buy_trade = buy_trades.pop(0)

                # Calculate P&L percentage
                pnl_pct = ((trade.price - buy_trade.price) / buy_trade.price) * 100
                holding_hours = (trade.timestamp - buy_trade.timestamp).total_seconds() / 3600

                trade_pnls.append({
                    "pnl_pct": pnl_pct,
                    "holding_hours": holding_hours,
                })

        if not trade_pnls:
            return {
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_holding_hours": 0.0,
            }

        # Calculate statistics
        wins = [t for t in trade_pnls if t["pnl_pct"] > 0]
        losses = [t for t in trade_pnls if t["pnl_pct"] <= 0]

        win_rate = (len(wins) / len(trade_pnls)) * 100 if trade_pnls else 0.0

        gross_profit = sum(t["pnl_pct"] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0

        avg_holding = sum(t["holding_hours"] for t in trade_pnls) / len(trade_pnls)

        return {
            "win_rate": win_rate,
            "profit_factor": profit_factor if profit_factor != float("inf") else 999.9,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_holding_hours": avg_holding,
        }

    def to_dict(self) -> dict:
        """Convert metrics to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "max_drawdown_duration_days": round(self.max_drawdown_duration_days, 1),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "profit_factor": round(self.profit_factor, 2),
            "avg_win_pct": round(self.avg_win_pct, 2),
            "avg_loss_pct": round(self.avg_loss_pct, 2),
            "total_trades": self.total_trades,
            "avg_holding_period_hours": round(self.avg_holding_period_hours, 1),
            "volatility_pct": round(self.volatility_pct, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "buy_and_hold_return_pct": round(self.buy_and_hold_return_pct, 2),
            "alpha_pct": round(self.alpha_pct, 2),
        }

    def summary(self) -> str:
        """Generate human-readable summary.

        Returns:
            Formatted summary string.
        """
        return f"""
═══════════════════════════════════════════════════════════════
                     백테스트 성과 요약
═══════════════════════════════════════════════════════════════

📈 수익률 지표
───────────────────────────────────────────────────────────────
  총 수익률:              {self.total_return_pct:+.2f}%
  연환산 수익률:          {self.annualized_return_pct:+.2f}%
  Buy & Hold 수익률:      {self.buy_and_hold_return_pct:+.2f}%
  알파 (초과수익):        {self.alpha_pct:+.2f}%

📊 리스크 지표
───────────────────────────────────────────────────────────────
  샤프 비율:              {self.sharpe_ratio:.2f}
  소르티노 비율:          {self.sortino_ratio:.2f}
  칼마 비율:              {self.calmar_ratio:.2f}
  최대 낙폭 (MDD):        {self.max_drawdown_pct:.2f}%
  MDD 지속기간:           {self.max_drawdown_duration_days:.0f}일
  변동성 (연환산):        {self.volatility_pct:.2f}%

🎯 거래 성과
───────────────────────────────────────────────────────────────
  총 거래 횟수:           {self.total_trades}회
  승률:                   {self.win_rate_pct:.1f}%
  손익비 (Profit Factor): {self.profit_factor:.2f}
  평균 수익 거래:         {self.avg_win_pct:+.2f}%
  평균 손실 거래:         {self.avg_loss_pct:.2f}%
  평균 보유 기간:         {self.avg_holding_period_hours:.1f}시간

═══════════════════════════════════════════════════════════════
"""
