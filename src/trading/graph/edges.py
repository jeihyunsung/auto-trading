"""Conditional routing functions for LangGraph."""

from typing import Literal

from trading.core.state import TradingState


def route_from_supervisor(
    state: TradingState,
) -> Literal[
    "market_agent",
    "news_agent",
    "indicator_agent",
    "decision_agent",
    "risk_agent",
    "execution_agent",
    "ops_agent",
    "FINISH",
]:
    """Route from supervisor to next agent.

    Args:
        state: Current trading state.

    Returns:
        Next node name.
    """
    current_step = state.get("current_step", "").lower()

    # Map step names to node names
    step_map = {
        "market_agent": "market_agent",
        "news_agent": "news_agent",
        "indicator_agent": "indicator_agent",
        "decision_agent": "decision_agent",
        "analysis_agent": "decision_agent",  # Alias
        "risk_agent": "risk_agent",
        "execution_agent": "execution_agent",
        "ops_agent": "ops_agent",
        "finish": "FINISH",
    }

    return step_map.get(current_step, "FINISH")


def route_by_market_condition(
    state: TradingState,
) -> Literal["normal", "volatile", "emergency"]:
    """Route based on market conditions.

    Args:
        state: Current trading state.

    Returns:
        Market condition category.
    """
    anomalies = state.get("anomalies", [])
    market = state.get("market", {})

    # Check for emergency conditions
    high_severity = any(a.get("severity") == "high" for a in anomalies)
    if high_severity:
        return "emergency"

    # Check volatility
    volatility = market.get("volatility_level", "medium")
    if volatility == "high":
        return "volatile"

    return "normal"


def should_continue_cycle(state: TradingState) -> Literal["continue", "finish"]:
    """Determine if the trading cycle should continue.

    Args:
        state: Current trading state.

    Returns:
        'continue' or 'finish'.
    """
    # Check kill switch
    risk = state.get("risk", {})
    if risk.get("is_kill_switch_on"):
        return "finish"

    # Check if we have a final decision
    decision = state.get("decision")
    if decision:
        status = decision.get("status", "")
        if status in ("executed", "rejected"):
            return "finish"

    # Check for errors
    error = state.get("error")
    if error:
        return "finish"

    # Check cycle count to prevent infinite loops
    cycle = state.get("cycle_count", 0)
    if cycle >= 10:  # Max 10 iterations per cycle
        return "finish"

    return "continue"


def route_after_decision(
    state: TradingState,
) -> Literal["risk_agent", "ops_agent", "FINISH"]:
    """Route after decision agent.

    Args:
        state: Current trading state.

    Returns:
        Next node name.
    """
    decision = state.get("decision")

    if not decision:
        return "FINISH"

    action = decision.get("action", "HOLD")

    # HOLD doesn't need risk validation
    if action == "HOLD":
        return "ops_agent"

    # BUY/SELL needs risk validation
    return "risk_agent"


def route_after_risk(
    state: TradingState,
) -> Literal["execution_agent", "ops_agent", "FINISH"]:
    """Route after risk agent.

    Args:
        state: Current trading state.

    Returns:
        Next node name.
    """
    decision = state.get("decision")

    if not decision:
        return "FINISH"

    status = decision.get("status", "")

    if status == "approved":
        return "execution_agent"
    elif status == "rejected":
        return "ops_agent"

    return "FINISH"


def route_after_execution(state: TradingState) -> Literal["ops_agent", "FINISH"]:
    """Route after execution agent.

    Args:
        state: Current trading state.

    Returns:
        Next node name.
    """
    # Always go to ops for alerts/logging
    return "ops_agent"
