"""LangGraph builder for trading system."""

from langgraph.graph import END, StateGraph

from trading.core.state import TradingState
from trading.graph.edges import (
    route_after_decision,
    route_after_risk,
)
from trading.graph.nodes import (
    decision_agent_node,
    execution_agent_node,
    indicator_agent_node,
    market_agent_node,
    ops_agent_node,
    pattern_agent_node,
    risk_agent_node,
)


def build_simple_pipeline() -> StateGraph:
    """Build a simpler linear pipeline (for testing).

    Returns:
        Compiled StateGraph with linear flow.
    """
    graph = StateGraph(TradingState)

    # Add nodes
    graph.add_node("market", market_agent_node)
    graph.add_node("indicators", indicator_agent_node)
    graph.add_node("pattern", pattern_agent_node)
    graph.add_node("decision", decision_agent_node)
    graph.add_node("risk", risk_agent_node)
    graph.add_node("execution", execution_agent_node)
    graph.add_node("ops", ops_agent_node)

    # Linear flow: market → indicators → pattern → decision
    graph.set_entry_point("market")
    graph.add_edge("market", "indicators")
    graph.add_edge("indicators", "pattern")
    graph.add_edge("pattern", "decision")

    # Conditional after decision
    graph.add_conditional_edges(
        "decision",
        route_after_decision,
        {
            "risk_agent": "risk",
            "ops_agent": "ops",
            "FINISH": END,
        },
    )

    graph.add_conditional_edges(
        "risk",
        route_after_risk,
        {
            "execution_agent": "execution",
            "ops_agent": "ops",
            "FINISH": END,
        },
    )

    graph.add_edge("execution", "ops")
    graph.add_edge("ops", END)

    return graph.compile()


# Create graph instance
simple_pipeline = build_simple_pipeline()
