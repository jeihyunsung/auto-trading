"""Conditional routing functions for LangGraph."""

from typing import Literal

from trading.core.state import TradingState


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
