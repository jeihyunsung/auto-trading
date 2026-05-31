"""LLM-based trading decision agent."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

# Decision recording moved to ops_agent.py
from trading.config import get_settings
from trading.core.position_sizing import PositionSizer, PositionSizingConfig, get_position_sizer
from trading.core.time import KST
from trading.core.state import Decision, MultiTimeframeTrendData, TradingState
from trading.indicators.multi_timeframe import MultiTimeframeTrend, get_mtf_analyzer
from trading.llm.client import get_llm_client, get_response_cache
from trading.llm.prompts import DECISION_SYSTEM_PROMPT, DECISION_USER_PROMPT
from trading.llm.schemas import LLMDecisionOutput

if TYPE_CHECKING:
    from trading.core.hysteresis import HysteresisManager

logger = logging.getLogger(__name__)

# Module-level LLM error alerting (lazy import to avoid circular dependency)
_ops_agent_instance = None


def _get_ops_agent():
    """Get OpsAgent instance for alerting (lazy load)."""
    global _ops_agent_instance
    if _ops_agent_instance is None:
        from trading.agents.ops_agent import OpsAgent
        _ops_agent_instance = OpsAgent()
    return _ops_agent_instance


def _alert_llm_error(error_message: str, model_name: str = "unknown") -> None:
    """Send Slack alert for LLM error.

    Args:
        error_message: The error that occurred.
        model_name: Name of the LLM model that failed.
    """
    try:
        ops = _get_ops_agent()
        message = (
            f"⚠️ *LLM 응답 오류*\n"
            f"• 모델: {model_name}\n"
            f"• 오류: {error_message[:200]}\n"
            f"• Fallback: rule_based 로직으로 전환됨"
        )
        ops.send_slack_message(message, color="#ffcc00")
        logger.info(f"LLM error alert sent to Slack")
    except Exception as e:
        logger.warning(f"Failed to send LLM error alert: {e}")


@dataclass
class RapidMovement:
    """Rapid price movement detection result."""

    detected: bool
    direction: Literal["surge", "drop", "none"]
    change_pct: float
    timeframe: str  # e.g., "5min", "1h"
    description: str


def detect_rapid_movement(market: dict) -> RapidMovement:
    """Detect rapid price movements from market data.

    Args:
        market: Market data dict containing ohlcv and current_price.

    Returns:
        RapidMovement with detection results.
    """
    ohlcv = market.get("ohlcv", [])
    current_price = market.get("current_price", 0)

    if not ohlcv or len(ohlcv) < 10 or current_price <= 0:
        return RapidMovement(
            detected=False,
            direction="none",
            change_pct=0.0,
            timeframe="",
            description="Insufficient data",
        )

    # Get prices at different timeframes
    # Assuming 5-minute candles: 6 candles = 30min, 12 candles = 1h
    prices = [c.get("close", c["close"]) if isinstance(c, dict) else c.close for c in ohlcv]

    # Check 30-minute change (6 candles of 5-min)
    if len(prices) >= 6:
        price_30min_ago = prices[-6]
        change_30min = ((current_price - price_30min_ago) / price_30min_ago) * 100

        # Rapid drop: > 2% in 30 minutes
        if change_30min <= -2.0:
            return RapidMovement(
                detected=True,
                direction="drop",
                change_pct=change_30min,
                timeframe="30min",
                description=f"30분 내 {change_30min:.1f}% 급락",
            )

        # Rapid surge: > 2% in 30 minutes
        if change_30min >= 2.0:
            return RapidMovement(
                detected=True,
                direction="surge",
                change_pct=change_30min,
                timeframe="30min",
                description=f"30분 내 +{change_30min:.1f}% 급등",
            )

    # Check 1-hour change (12 candles of 5-min)
    if len(prices) >= 12:
        price_1h_ago = prices[-12]
        change_1h = ((current_price - price_1h_ago) / price_1h_ago) * 100

        # Rapid drop: > 3% in 1 hour
        if change_1h <= -3.0:
            return RapidMovement(
                detected=True,
                direction="drop",
                change_pct=change_1h,
                timeframe="1h",
                description=f"1시간 내 {change_1h:.1f}% 급락",
            )

        # Rapid surge: > 3% in 1 hour
        if change_1h >= 3.0:
            return RapidMovement(
                detected=True,
                direction="surge",
                change_pct=change_1h,
                timeframe="1h",
                description=f"1시간 내 +{change_1h:.1f}% 급등",
            )

    # Check recent momentum (last 3 candles = 15 min)
    if len(prices) >= 3:
        price_15min_ago = prices[-3]
        change_15min = ((current_price - price_15min_ago) / price_15min_ago) * 100

        # Very rapid drop: > 1.5% in 15 minutes
        if change_15min <= -1.5:
            return RapidMovement(
                detected=True,
                direction="drop",
                change_pct=change_15min,
                timeframe="15min",
                description=f"15분 내 {change_15min:.1f}% 급락",
            )

        # Very rapid surge: > 1.5% in 15 minutes
        if change_15min >= 1.5:
            return RapidMovement(
                detected=True,
                direction="surge",
                change_pct=change_15min,
                timeframe="15min",
                description=f"15분 내 +{change_15min:.1f}% 급등",
            )

    return RapidMovement(
        detected=False,
        direction="none",
        change_pct=0.0,
        timeframe="",
        description="No rapid movement detected",
    )


def cap_high_rsi_buy_confidence(
    action: str,
    confidence: float,
    rsi: float,
    threshold: float,
    cap: float,
) -> float:
    """Cap BUY confidence when RSI is already elevated.

    High-RSI BUY entries are structurally late — the trend has already moved.
    Without a cap, the LLM (potentially boosted by MTF +0.1 alignment bonus)
    can push confidence into the 0.7-0.8 PositionSizer tier (35% target),
    which then anchors Hysteresis at a high bar so the subsequent SELL is
    delayed. Capping at 0.65 keeps the entry in the 0.6-0.7 tier (25%
    target) and lets any future SELL at 0.80 pass Hysteresis.

    Only applies to BUY actions. SELL and HOLD pass through untouched.

    Args:
        action: BUY / SELL / HOLD.
        confidence: Current confidence (after any MTF adjustment).
        rsi: Current RSI value.
        threshold: RSI level above which the cap activates.
        cap: Maximum allowed confidence above threshold.

    Returns:
        Possibly-capped confidence value.
    """
    if action != "BUY":
        return confidence
    if rsi <= threshold:
        return confidence
    if confidence <= cap:
        return confidence
    logger.info(
        f"BUY confidence capped: RSI={rsi:.1f} > {threshold:.0f} → "
        f"{confidence:.2f} → {cap:.2f}"
    )
    return cap


def detect_stop_loss(
    portfolio: dict | None,
    threshold_pct: float,
) -> Decision | None:
    """Force a SELL when the open BTC position breaches the stop-loss threshold.

    Triggered before LLM/rule-based decision so that hysteresis cannot delay
    the exit. Observed live behaviour showed Hysteresis blocking SELL signals
    for hours after a high-confidence BUY, accumulating loss while the LLM
    repeatedly tried to cut. This guard short-circuits that path when the
    unrealized loss on the open position exceeds the configured threshold.

    Args:
        portfolio: Current portfolio dict with `unrealized_pnl` and `btc_balance`.
        threshold_pct: Stop-loss threshold (positive percent). 0 disables.

    Returns:
        Force-exit Decision or None.
    """
    if not portfolio or threshold_pct <= 0:
        return None
    btc = portfolio.get("btc_balance", 0) or 0
    if btc <= 0:
        return None  # No open position
    pnl = portfolio.get("unrealized_pnl", 0) or 0
    if pnl > -threshold_pct:
        return None  # Within tolerance
    exposure = portfolio.get("exposure_pct", 0) or 0
    return Decision(
        action="SELL",
        confidence=0.95,
        suggested_size_pct=100.0,
        target_position_pct=0.0,
        position_delta_pct=-exposure,
        rationale=(
            f"[stop_loss] Unrealized P&L {pnl:.2f}% breached threshold "
            f"-{threshold_pct:.2f}%. Force-exit all {exposure:.1f}% exposure "
            f"to prevent further loss."
        ),
        status="pending",
        bypass_hysteresis=True,
        decision_source="rapid_move",
    )


def detect_take_profit(
    portfolio: dict | None,
    threshold_pct: float,
    sell_fraction: float = 0.5,
) -> Decision | None:
    """Force a partial SELL when unrealized P&L exceeds the take-profit threshold.

    Mirror of `detect_stop_loss` on the upside. Locks in some profit
    automatically when the position runs in our favor by `threshold_pct`,
    without waiting for the LLM/Hysteresis chain to converge on a SELL.
    Live observation showed BUY→SELL transitions consistently lag the
    peak by ~4 hours due to Hysteresis anchoring on the BUY confidence;
    this guard short-circuits the upside lag specifically.

    Partial (default 50%) rather than full so the remaining position
    can still ride a real uptrend leg — the LLM still gets a chance to
    sell the rest when the trend reverses.

    Args:
        portfolio: Current portfolio dict with `unrealized_pnl` and `btc_balance`.
        threshold_pct: Take-profit threshold (positive percent). 0 disables.
        sell_fraction: Portion of current exposure to sell (0..1). Default 0.5.

    Returns:
        Force-exit Decision or None.
    """
    if not portfolio or threshold_pct <= 0:
        return None
    btc = portfolio.get("btc_balance", 0) or 0
    if btc <= 0:
        return None  # No open position
    pnl = portfolio.get("unrealized_pnl", 0) or 0
    if pnl < threshold_pct:
        return None  # Not enough profit yet
    exposure = portfolio.get("exposure_pct", 0) or 0
    delta_pct = exposure * max(0.0, min(1.0, sell_fraction))
    remaining_pct = exposure - delta_pct
    return Decision(
        action="SELL",
        confidence=0.90,
        suggested_size_pct=delta_pct,
        target_position_pct=remaining_pct,
        position_delta_pct=-delta_pct,
        rationale=(
            f"[take_profit] Unrealized P&L +{pnl:.2f}% breached threshold "
            f"+{threshold_pct:.2f}%. Selling {sell_fraction*100:.0f}% of "
            f"{exposure:.1f}% exposure to lock in profit; keeping "
            f"{remaining_pct:.1f}% for further upside."
        ),
        status="pending",
        bypass_hysteresis=True,
        decision_source="rapid_move",
    )


def check_mtf_trend_alignment(
    mtf_trends: MultiTimeframeTrendData | None,
    proposed_action: str,
) -> tuple[bool, float, str]:
    """Check if multi-timeframe trends align with proposed action.

    Args:
        mtf_trends: Multi-timeframe trend data from state.
        proposed_action: Proposed action ("BUY", "SELL", "HOLD").

    Returns:
        Tuple of (should_proceed, confidence_adjustment, reason).
    """
    if mtf_trends is None:
        return True, 0.0, "No MTF data available"

    if proposed_action == "HOLD":
        return True, 0.0, "HOLD action - no trend check needed"

    # Get trend alignment info
    aligned = mtf_trends.get("aligned", False)
    alignment_count = mtf_trends.get("alignment_count", 0)
    dominant_trend = mtf_trends.get("dominant_trend", "neutral")
    confidence_adj = mtf_trends.get("confidence_adjustment", 0.0)
    rapid_move = mtf_trends.get("rapid_move_detected", False)
    rapid_direction = mtf_trends.get("rapid_move_direction")
    trends = mtf_trends.get("trends", {})

    # Map action to required trend
    required_trend = "bullish" if proposed_action == "BUY" else "bearish"

    # Format trend summary for logging
    trend_summary = ", ".join(
        f"{tf}={t.get('trend', '?')[0].upper()}"
        for tf, t in sorted(trends.items())
    )

    # Rapid movement override - allow with relaxed requirements
    if rapid_move:
        if rapid_direction == required_trend:
            # Check short-term trends (5m, 1h) only
            short_trends = [
                trends.get("5m", {}).get("trend"),
                trends.get("1h", {}).get("trend"),
            ]
            short_aligned = sum(1 for t in short_trends if t == required_trend)
            if short_aligned >= 1:
                logger.info(
                    f"MTF: Rapid {rapid_direction} move with short-term confirmation [{trend_summary}]"
                )
                return True, 0.05, f"Rapid {required_trend} move confirmed"
            logger.warning(
                f"MTF: Rapid move but short-term trends don't confirm [{trend_summary}]"
            )
            return False, -0.1, f"Rapid move without short-term confirmation"
        else:
            logger.warning(
                f"MTF: Rapid move in opposite direction ({rapid_direction} vs {required_trend}) [{trend_summary}]"
            )
            return False, -0.15, f"Rapid move in opposite direction"

    # Normal mode - check trend alignment
    if dominant_trend == required_trend:
        if aligned:
            logger.info(
                f"MTF: Trends aligned for {proposed_action} ({alignment_count} TFs) [{trend_summary}]"
            )
            return True, confidence_adj, f"Trends aligned ({alignment_count} timeframes)"

        # Partial alignment - allow with lower confidence
        if alignment_count >= 2:
            logger.info(
                f"MTF: Partial alignment for {proposed_action} ({alignment_count} TFs) [{trend_summary}]"
            )
            return True, confidence_adj * 0.5, f"Partial alignment ({alignment_count} timeframes)"

        logger.warning(
            f"MTF: Insufficient alignment for {proposed_action} ({alignment_count} TFs) [{trend_summary}]"
        )
        return False, -0.1, f"Insufficient trend alignment ({alignment_count} TFs)"

    elif dominant_trend == "neutral":
        logger.info(f"MTF: Trends neutral, proceed with caution [{trend_summary}]")
        return True, -0.05, "Trends neutral - proceed with caution"

    else:
        # Trading against the dominant trend
        logger.warning(
            f"MTF: {proposed_action} against {dominant_trend} trend [{trend_summary}]"
        )
        return False, -0.15, f"{proposed_action} against {dominant_trend} trend"


# Module-level hysteresis manager (configured by entry points)
_hysteresis_manager: "HysteresisManager | None" = None


def set_hysteresis_manager(manager: "HysteresisManager | None") -> None:
    """Set the hysteresis manager for decision nodes.

    Args:
        manager: HysteresisManager instance or None to disable.
    """
    global _hysteresis_manager
    _hysteresis_manager = manager


def get_hysteresis_manager() -> "HysteresisManager | None":
    """Get the current hysteresis manager.

    Returns:
        Current HysteresisManager or None if not configured.
    """
    return _hysteresis_manager


class DecisionAgent:
    """Agent for generating trading decisions using LLM."""

    def __init__(self, default_confidence_threshold: float = 0.5):
        """Initialize decision agent.

        Args:
            default_confidence_threshold: Minimum confidence for non-HOLD actions.
        """
        self.confidence_threshold = default_confidence_threshold

    def decide(self, state: TradingState) -> Decision:
        """Generate trading decision based on current state.

        Args:
            state: Current trading state.

        Returns:
            Decision with action, confidence, and rationale.
        """
        # Check if we have required data
        market = state.get("market")
        indicators = state.get("indicators")
        portfolio = state.get("portfolio")
        risk = state.get("risk", {})

        if not all([market, indicators]):
            logger.warning("Missing required data for decision")
            return Decision(
                action="HOLD",
                confidence=0.0,
                suggested_size_pct=0.0,
                rationale="[rule_based] Insufficient data for decision",
                status="pending",
                decision_source="rule_based",
            )

        # Stop-loss and take-profit guards run BEFORE anything else: they
        # bypass LLM, MTF, and Hysteresis entirely so the exit cannot lag.
        # Stop-loss prevents loss compounding; take-profit locks in upside
        # before Hysteresis (anchored on the BUY confidence) delays the SELL.
        _s = get_settings()
        stop_loss_decision = detect_stop_loss(portfolio, _s.stop_loss_pct)
        if stop_loss_decision is not None:
            logger.warning(
                f"STOP-LOSS triggered: {stop_loss_decision['rationale']}"
            )
            return stop_loss_decision

        take_profit_decision = detect_take_profit(
            portfolio, _s.take_profit_pct, _s.take_profit_sell_fraction
        )
        if take_profit_decision is not None:
            logger.info(
                f"TAKE-PROFIT triggered: {take_profit_decision['rationale']}"
            )
            return take_profit_decision

        # Check for rapid price movements FIRST (override LLM if detected)
        rapid_move = detect_rapid_movement(market)
        if rapid_move.detected:
            rapid_decision = self._handle_rapid_movement(rapid_move, portfolio, indicators)
            if rapid_decision is not None:
                logger.info(f"Rapid movement override: {rapid_move.description} -> {rapid_decision['action']}")
                return rapid_decision

        # Get derivatives data
        derivatives = state.get("derivatives")

        # Try LLM decision
        try:
            llm = get_llm_client()
            if llm.is_available:
                return self._decide_with_llm(state, market, indicators, portfolio, risk)
        except Exception as e:
            logger.warning(f"LLM decision failed: {e}")
            # Send Slack alert for LLM error
            model_name = get_settings().openai_model
            _alert_llm_error(str(e), model_name)

        # Get MTF trends for rule-based decision
        mtf_trends = state.get("mtf_trends")

        # Fallback to rule-based decision
        return self._decide_rule_based(market, indicators, portfolio, risk, derivatives, mtf_trends)

    def _handle_rapid_movement(
        self,
        rapid_move: RapidMovement,
        portfolio: dict | None,
        indicators: dict,
    ) -> Decision | None:
        """Handle rapid price movement with immediate action.

        Args:
            rapid_move: Detected rapid movement.
            portfolio: Current portfolio state.
            indicators: Indicator signals.

        Returns:
            Decision to execute, or None to proceed with normal flow.
        """
        exposure = portfolio.get("exposure_pct", 0) if portfolio else 0
        krw_balance = portfolio.get("cash_krw", 0) if portfolio else 0
        btc_balance = portfolio.get("btc_balance", 0) if portfolio else 0

        # RAPID DROP: Sell immediately if we have BTC
        if rapid_move.direction == "drop":
            if btc_balance > 0 and exposure > 10:
                # More aggressive sell on larger drops
                confidence = min(0.95, 0.7 + abs(rapid_move.change_pct) * 0.05)
                size_pct = min(100.0, 30.0 + abs(rapid_move.change_pct) * 5)  # Larger drops = bigger sell

                logger.warning(
                    f"RAPID DROP DETECTED: {rapid_move.description}. "
                    f"Triggering immediate SELL (exposure={exposure:.1f}%)"
                )

                return Decision(
                    action="SELL",
                    confidence=confidence,
                    suggested_size_pct=size_pct,
                    rationale=f"[rapid_move] {rapid_move.description}. 손실 방지를 위해 즉시 매도. "
                              f"현재 노출도: {exposure:.0f}%",
                    status="pending",
                    bypass_hysteresis=True,  # Urgent: skip hysteresis check
                    decision_source="rapid_move",
                )
            else:
                logger.info(f"Rapid drop detected but no BTC to sell (exposure={exposure:.1f}%)")

        # RAPID SURGE: Buy immediately if we have cash
        elif rapid_move.direction == "surge":
            if krw_balance > 5000 and exposure < 80:
                # More aggressive buy on larger surges
                confidence = min(0.90, 0.65 + rapid_move.change_pct * 0.05)
                size_pct = min(20.0, 8.0 + rapid_move.change_pct * 2)  # Larger surges = bigger buy

                logger.info(
                    f"RAPID SURGE DETECTED: {rapid_move.description}. "
                    f"Triggering immediate BUY (cash={krw_balance:,.0f})"
                )

                return Decision(
                    action="BUY",
                    confidence=confidence,
                    suggested_size_pct=size_pct,
                    rationale=f"[rapid_move] {rapid_move.description}. 상승 추세 포착을 위해 즉시 매수. "
                              f"가용 현금: {krw_balance:,.0f} KRW",
                    status="pending",
                    bypass_hysteresis=True,  # Urgent: skip hysteresis check
                    decision_source="rapid_move",
                )
            else:
                logger.info(
                    f"Rapid surge detected but cannot buy "
                    f"(cash={krw_balance:,.0f}, exposure={exposure:.1f}%)"
                )

        return None

    def _decide_with_llm(
        self,
        state: TradingState,
        market: dict,
        indicators: dict,
        portfolio: dict | None,
        risk: dict,
    ) -> Decision:
        """Generate decision using LLM.

        Args:
            state: Full state.
            market: Market data.
            indicators: Indicator signals.
            portfolio: Portfolio state.
            risk: Risk state.

        Returns:
            Decision from LLM with position sizing applied.
        """
        llm = get_llm_client()
        exposure = portfolio.get("exposure_pct", 0) if portfolio else 0

        # Format anomalies
        anomalies = state.get("anomalies", [])
        anomaly_text = "None" if not anomalies else "\n".join(
            f"- {a['type']}: {a['description']} (severity: {a['severity']})"
            for a in anomalies
        )

        # Format recent decision history from hysteresis manager
        decision_history_text = self._format_decision_history()

        # Get derivatives data
        derivatives = state.get("derivatives") or {}

        # Get trend channel data
        trend_channel = state.get("trend_channel") or {}
        channel_slope_deg = trend_channel.get("slope_angle_deg", 0.0)
        channel_slope_dir = (
            "uptrend" if channel_slope_deg > 1 else
            "downtrend" if channel_slope_deg < -1 else
            "sideways"
        )

        # Get pattern analysis data
        pattern = state.get("pattern_analysis") or {}

        asset_symbol = get_settings().asset_symbol
        prompt = DECISION_USER_PROMPT.format(
            asset_symbol=asset_symbol,
            symbol=market.get("symbol", "KRW-BTC"),
            current_price=market.get("current_price", 0),
            change_24h=market.get("percent_change_24h", 0),
            volatility_level=market.get("volatility_level", "medium"),
            # Derivatives data
            oi_value=derivatives.get("open_interest_value", 0),
            oi_change_1h=derivatives.get("oi_change_pct_1h", 0),
            oi_change_24h=derivatives.get("oi_change_pct_24h", 0),
            oi_trend=derivatives.get("oi_trend", "unknown"),
            long_short_ratio=derivatives.get("long_short_ratio", 1.0),
            top_trader_ls=derivatives.get("top_trader_long_short_ratio", 1.0),
            position_bias=derivatives.get("position_bias", "unknown"),
            funding_rate=derivatives.get("funding_rate", 0),
            funding_signal=derivatives.get("funding_signal", "unknown"),
            trend=indicators.get("trend", "neutral"),
            momentum=indicators.get("momentum", "neutral"),
            rsi=indicators.get("signals", {}).get("rsi", 50),
            macd_histogram=indicators.get("signals", {}).get("macd_histogram", 0),
            # Trend channel data
            channel_slope_deg=channel_slope_deg,
            channel_slope_dir=channel_slope_dir,
            channel_position=trend_channel.get("position_in_channel", 0.5),
            channel_width=trend_channel.get("channel_width_pct", 0.0),
            breakout_risk=trend_channel.get("breakout_risk", "unknown"),
            support_levels=", ".join(
                f"{s:,.0f}" for s in trend_channel.get("support_levels", [])
            ) or "N/A",
            resistance_levels=", ".join(
                f"{r:,.0f}" for r in trend_channel.get("resistance_levels", [])
            ) or "N/A",
            # Pattern analysis data
            pattern_name=pattern.get("pattern", "none"),
            pattern_direction=pattern.get("direction", "neutral"),
            pattern_confidence=pattern.get("confidence", 0.0),
            pattern_description=pattern.get("description", "패턴 분석 없음"),
            krw_balance=portfolio.get("cash_krw", 0) if portfolio else 0,
            asset_balance=(
                portfolio.get(
                    "asset_balance", portfolio.get("btc_balance", 0)
                )
                if portfolio
                else 0
            ),
            exposure=portfolio.get("exposure_pct", 0) if portfolio else 0,
            unrealized_pnl=portfolio.get("unrealized_pnl", 0) if portfolio else 0,
            max_position=risk.get("position_limit_pct", 50),
            max_daily_loss=risk.get("max_loss_pct", 3),
            daily_pnl=risk.get("daily_loss_pct", 0),
            anomalies=anomaly_text,
            decision_history=decision_history_text,
        )

        # System prompt now carries {asset_symbol} placeholders for multi-asset
        # support; render before sending. Use str.replace instead of .format()
        # because the prompt body also contains illustrative `{실제값}` Korean
        # placeholders that aren't real template variables and would explode
        # .format(). Hash + cache_key include asset_symbol so an ETH/XRP bot
        # does not reuse a BTC-formatted cache row.
        system_prompt = DECISION_SYSTEM_PROMPT.replace("{asset_symbol}", asset_symbol)

        # Check cache for similar market state (only HOLD decisions are cached).
        # Cache key includes derivatives (funding/position_bias/oi_trend) so a
        # shift in futures sentiment invalidates an otherwise-identical RSI/trend
        # cache entry — the LLM may now reach a different conclusion.
        cache = get_response_cache()
        import hashlib
        sys_hash = hashlib.md5(system_prompt[:100].encode()).hexdigest()[:8]
        cache_key = cache.make_key(
            sys_hash,
            asset=asset_symbol,
            trend=indicators.get("trend", "neutral"),
            momentum=indicators.get("momentum", "neutral"),
            rsi=indicators.get("signals", {}).get("rsi", 50),
            exposure=round(exposure / 5) * 5,
            volatility=market.get("volatility_level", "medium"),
            funding_signal=derivatives.get("funding_signal", "neutral"),
            position_bias=derivatives.get("position_bias", "balanced"),
            oi_trend=derivatives.get("oi_trend", "stable"),
        )

        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("Using cached HOLD decision (market state similar to recent call)")
            return cached

        result = llm.invoke_json(system_prompt, prompt, LLMDecisionOutput)

        # Check MTF trend alignment BEFORE position sizing
        mtf_trends = state.get("mtf_trends")
        mtf_ok, mtf_conf_adj, mtf_reason = check_mtf_trend_alignment(mtf_trends, result.action)

        # Adjust confidence based on MTF analysis
        adjusted_confidence = min(1.0, max(0.0, result.confidence + mtf_conf_adj))

        # Cap BUY confidence when RSI is already elevated (applied AFTER MTF
        # bonus so the +0.1 alignment boost can't push the decision into a
        # higher sizing tier). See cap_high_rsi_buy_confidence docstring.
        _settings = get_settings()
        rsi_for_cap = indicators.get("signals", {}).get("rsi", 50)
        adjusted_confidence = cap_high_rsi_buy_confidence(
            result.action,
            adjusted_confidence,
            rsi_for_cap,
            _settings.buy_conf_cap_rsi_threshold,
            _settings.buy_conf_cap_value,
        )

        # Block trade if MTF trends don't align
        # Exception: Allow BUY/SELL with high confidence to enable aggressive trading
        MTF_OVERRIDE_CONFIDENCE = 0.65  # Lowered for more aggressive entry
        mtf_overridden = False
        if not mtf_ok and result.action != "HOLD":
            if result.confidence >= MTF_OVERRIDE_CONFIDENCE:
                logger.info(
                    f"MTF override: {result.action} allowed despite MTF ({mtf_reason}) "
                    f"due to high confidence ({result.confidence:.0%})"
                )
                mtf_overridden = True
                # Continue with action, don't block
            else:
                logger.warning(
                    f"LLM suggested {result.action} blocked by MTF: {mtf_reason}"
                )
                return Decision(
                    action="HOLD",
                    confidence=adjusted_confidence,
                    suggested_size_pct=0.0,
                    rationale=f"[llm] [MTF 차단] {result.rationale} | MTF: {mtf_reason}",
                    status="pending",
                    decision_source="llm",
                )

        # Determine signal direction from LLM action
        if result.action == "BUY":
            signal_direction: Literal["bullish", "bearish", "neutral"] = "bullish"
        elif result.action == "SELL":
            signal_direction = "bearish"
        else:
            signal_direction = "neutral"

        # Use position sizer to calculate target position and delta
        sizer = get_position_sizer()
        sizing_result = sizer.calculate(
            confidence=adjusted_confidence,
            signal_direction=signal_direction,
            current_exposure_pct=exposure,
        )

        # Determine final action based on position sizing
        # If LLM says BUY but position sizing says HOLD (delta too small), use HOLD
        final_action = result.action
        if result.action in ("BUY", "SELL") and not sizing_result.should_trade:
            final_action = "HOLD"
            logger.info(
                f"LLM suggested {result.action} but delta too small "
                f"({sizing_result.delta_pct:+.1f}% < min threshold). Using HOLD."
            )

        # Include MTF info in rationale
        if mtf_overridden:
            mtf_info = f"[MTF 무시: 고신뢰 {result.action}] {mtf_reason}"
        elif mtf_reason != "No MTF data available":
            mtf_info = f"MTF: {mtf_reason}"
        else:
            mtf_info = ""

        decision = Decision(
            action=final_action,
            confidence=adjusted_confidence,
            suggested_size_pct=abs(sizing_result.delta_pct),
            target_position_pct=sizing_result.target_position_pct,
            position_delta_pct=sizing_result.delta_pct,
            rationale=f"[llm] {result.rationale} | Position: {exposure:.1f}% → {sizing_result.target_position_pct:.1f}% (delta {sizing_result.delta_pct:+.1f}%) {mtf_info}",
            status="pending",
            decision_source="llm",
        )

        # Cache HOLD decisions to avoid redundant LLM calls when market is stable
        if final_action == "HOLD":
            cache.put(cache_key, decision)

        return decision

    def _format_decision_history(self) -> str:
        """Format recent decision history for LLM context.

        Returns:
            Formatted string of recent decisions, or "No previous decisions" if none.
        """
        manager = get_hysteresis_manager()
        if manager is None:
            return "No previous decisions (first cycle)"

        history_items = []

        # Add last trade action (BUY/SELL) if exists
        if manager.last_trade_action is not None:
            action = manager.last_trade_action["action"]
            confidence = manager.last_trade_action["confidence"]
            timestamp = manager.last_trade_action["timestamp"]
            rationale = manager.last_trade_action.get("rationale", "")[:100]
            history_items.append(
                f"- Last Trade: {action} ({confidence:.0%}) at {timestamp[:16]} - {rationale}"
            )

        # Add most recent decision if different from last trade
        if manager.previous is not None:
            if manager.last_trade_action is None or manager.previous != manager.last_trade_action:
                action = manager.previous["action"]
                confidence = manager.previous["confidence"]
                timestamp = manager.previous["timestamp"]
                rationale = manager.previous.get("rationale", "")[:100]
                history_items.append(
                    f"- Last Decision: {action} ({confidence:.0%}) at {timestamp[:16]} - {rationale}"
                )

        if not history_items:
            return "No previous decisions (first cycle)"

        return "\n".join(history_items)

    def _decide_rule_based(
        self,
        market: dict,
        indicators: dict,
        portfolio: dict | None,
        risk: dict,
        derivatives: dict | None = None,
        mtf_trends: MultiTimeframeTrendData | None = None,
    ) -> Decision:
        """Rule-based decision using target position sizing.

        Instead of simple BUY/SELL/HOLD, calculates target position based on
        confidence and determines action from position delta.

        Args:
            market: Market data.
            indicators: Indicator signals.
            portfolio: Portfolio state.
            risk: Risk state.
            derivatives: Binance Futures derivatives data.
            mtf_trends: Multi-timeframe trend data.

        Returns:
            Rule-based Decision with target position.
        """
        trend = indicators.get("trend", "neutral")
        momentum = indicators.get("momentum", "neutral")
        rsi = indicators.get("signals", {}).get("rsi", 50)
        price_change_24h = market.get("percent_change_24h", 0)

        # Get current position
        exposure = portfolio.get("exposure_pct", 0) if portfolio else 0

        # Count signals to determine direction and confidence
        bullish_signals = 0
        bearish_signals = 0
        max_signals = 6  # Maximum possible signals

        # Technical signals
        if trend == "bullish":
            bullish_signals += 1
        elif trend == "bearish":
            bearish_signals += 1

        if momentum == "oversold":
            bullish_signals += 1
        elif momentum == "overbought":
            bearish_signals += 1

        if rsi < 30:
            bullish_signals += 1
        elif rsi > 70:
            bearish_signals += 1

        # Derivatives signals (contrarian approach)
        if derivatives:
            position_bias = derivatives.get("position_bias")
            if position_bias == "short_heavy":
                bullish_signals += 1
            elif position_bias == "long_heavy":
                bearish_signals += 1

            funding_signal = derivatives.get("funding_signal")
            if funding_signal == "overheated_short":
                bullish_signals += 1
            elif funding_signal == "overheated_long":
                bearish_signals += 1

            oi_trend = derivatives.get("oi_trend")
            if oi_trend == "increasing" and price_change_24h > 0:
                bullish_signals += 1
            elif oi_trend == "increasing" and price_change_24h < 0:
                bearish_signals += 1

        # Determine direction and confidence
        total_signals = bullish_signals + bearish_signals

        if total_signals == 0:
            signal_direction: Literal["bullish", "bearish", "neutral"] = "neutral"
            confidence = 0.3
        elif bullish_signals > bearish_signals:
            signal_direction = "bullish"
            # Confidence based on signal strength (0.5 to 0.9)
            signal_ratio = bullish_signals / max(total_signals, 1)
            confidence = 0.5 + (signal_ratio * 0.4)
        elif bearish_signals > bullish_signals:
            signal_direction = "bearish"
            signal_ratio = bearish_signals / max(total_signals, 1)
            confidence = 0.5 + (signal_ratio * 0.4)
        else:
            signal_direction = "neutral"
            confidence = 0.4

        # Determine proposed action from signal direction
        if signal_direction == "bullish":
            proposed_action = "BUY"
        elif signal_direction == "bearish":
            proposed_action = "SELL"
        else:
            proposed_action = "HOLD"

        # Check MTF trend alignment
        mtf_ok, mtf_conf_adj, mtf_reason = check_mtf_trend_alignment(mtf_trends, proposed_action)

        # Adjust confidence based on MTF analysis
        adjusted_confidence = min(1.0, max(0.0, confidence + mtf_conf_adj))

        # Apply BUY confidence cap at high RSI (same policy as LLM path).
        _settings_rb = get_settings()
        adjusted_confidence = cap_high_rsi_buy_confidence(
            proposed_action,
            adjusted_confidence,
            rsi,
            _settings_rb.buy_conf_cap_rsi_threshold,
            _settings_rb.buy_conf_cap_value,
        )

        # Block trade if MTF trends don't align
        signal_summary = f"bullish={bullish_signals}, bearish={bearish_signals}"
        if not mtf_ok and proposed_action != "HOLD":
            logger.warning(
                f"Rule-based {proposed_action} blocked by MTF: {mtf_reason}"
            )
            return Decision(
                action="HOLD",
                confidence=adjusted_confidence,
                suggested_size_pct=0.0,
                rationale=f"[rule_based] [MTF 차단] {mtf_reason} [Signals: {signal_summary}, trend={trend}, RSI={rsi:.1f}]",
                status="pending",
                decision_source="rule_based",
            )

        # Use position sizer to calculate target position
        sizer = get_position_sizer()
        result = sizer.calculate(
            confidence=adjusted_confidence,
            signal_direction=signal_direction,
            current_exposure_pct=exposure,
        )

        # Build rationale
        mtf_info = f"MTF: {mtf_reason}" if mtf_reason != "No MTF data available" else ""
        rationale = (
            f"[rule_based] {result.rationale} "
            f"[Signals: {signal_summary}, trend={trend}, RSI={rsi:.1f}] {mtf_info}"
        )

        return Decision(
            action=result.action,
            confidence=adjusted_confidence,
            suggested_size_pct=abs(result.delta_pct),
            target_position_pct=result.target_position_pct,
            position_delta_pct=result.delta_pct,
            rationale=rationale,
            status="pending",
            decision_source="rule_based",
        )

def decision_agent_node(state: TradingState) -> dict:
    """LangGraph node function for decision agent.

    Args:
        state: Current trading state.

    Returns:
        State updates with decision.
    """
    agent = DecisionAgent()

    try:
        decision = agent.decide(state)

        # Apply hysteresis if manager is configured (unless bypassed)
        manager = get_hysteresis_manager()
        if manager is not None:
            # Check if this decision should bypass hysteresis (e.g., rapid movement)
            if decision.get("bypass_hysteresis", False):
                logger.info(
                    f"Hysteresis BYPASSED for urgent decision: {decision['action']} "
                    f"(reason: {decision.get('rationale', '')[:50]}...)"
                )
            else:
                # Note: We no longer immediately reset hysteresis when BTC=0
                # The post_trade_cooldown in HysteresisConfig handles preventing
                # too-quick re-entry after selling all holdings.
                # This prevents the "sell high, buy back too early" problem.
                cycle_count = state.get("cycle_count", 0)
                decision = manager.apply_hysteresis(decision, cycle_count)

        # Note: Decision recording moved to ops_agent (end of pipeline)
        # to capture final status (approved/rejected/executed)

        return {
            "decision": decision,
            "error": None,
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Decision agent failed: {e}")
        return {
            "decision": Decision(
                action="HOLD",
                confidence=0.0,
                suggested_size_pct=0.0,
                rationale=f"[rule_based] Decision error: {e}",
                status="rejected",
                decision_source="rule_based",
            ),
            "error": f"Decision agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
