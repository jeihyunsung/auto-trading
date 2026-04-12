"""LangGraph builder for trading system."""

from langgraph.graph import END, StateGraph

from trading.core.state import TradingState, create_initial_state
from trading.graph.edges import (
    route_after_decision,
    route_after_execution,
    route_after_risk,
    route_from_supervisor,
)
from trading.graph.nodes import (
    decision_agent_node,
    execution_agent_node,
    indicator_agent_node,
    market_agent_node,
    news_agent_node,
    ops_agent_node,
    risk_agent_node,
    supervisor_node,
)


def build_trading_graph() -> StateGraph:
    """Build the complete trading graph.

    Returns:
        Compiled StateGraph ready for execution.
    """
    # Create graph with state schema
    graph = StateGraph(TradingState)

    # Add all nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("market_agent", market_agent_node)
    graph.add_node("news_agent", news_agent_node)
    graph.add_node("indicator_agent", indicator_agent_node)
    graph.add_node("decision_agent", decision_agent_node)
    graph.add_node("risk_agent", risk_agent_node)
    graph.add_node("execution_agent", execution_agent_node)
    graph.add_node("ops_agent", ops_agent_node)

    # Set entry point
    graph.set_entry_point("supervisor")

    # Add conditional edges from supervisor
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "market_agent": "market_agent",
            "news_agent": "news_agent",
            "indicator_agent": "indicator_agent",
            "decision_agent": "decision_agent",
            "risk_agent": "risk_agent",
            "execution_agent": "execution_agent",
            "ops_agent": "ops_agent",
            "FINISH": END,
        },
    )

    # After data collection, go back to supervisor
    graph.add_edge("market_agent", "supervisor")
    graph.add_edge("news_agent", "supervisor")
    graph.add_edge("indicator_agent", "supervisor")

    # After decision, route based on action
    graph.add_conditional_edges(
        "decision_agent",
        route_after_decision,
        {
            "risk_agent": "risk_agent",
            "ops_agent": "ops_agent",
            "FINISH": END,
        },
    )

    # After risk validation, route based on approval
    graph.add_conditional_edges(
        "risk_agent",
        route_after_risk,
        {
            "execution_agent": "execution_agent",
            "ops_agent": "ops_agent",
            "FINISH": END,
        },
    )

    # After execution, always go to ops for logging
    graph.add_conditional_edges(
        "execution_agent",
        route_after_execution,
        {
            "ops_agent": "ops_agent",
            "FINISH": END,
        },
    )

    # Ops is the final node before END
    graph.add_edge("ops_agent", END)

    return graph.compile()


def build_simple_pipeline() -> StateGraph:
    """Build a simpler linear pipeline (for testing).

    Returns:
        Compiled StateGraph with linear flow.
    """
    graph = StateGraph(TradingState)

    # Add nodes
    graph.add_node("market", market_agent_node)
    graph.add_node("news", news_agent_node)
    graph.add_node("indicators", indicator_agent_node)
    graph.add_node("decision", decision_agent_node)
    graph.add_node("risk", risk_agent_node)
    graph.add_node("execution", execution_agent_node)
    graph.add_node("ops", ops_agent_node)

    # Linear flow
    graph.set_entry_point("market")
    graph.add_edge("market", "news")
    graph.add_edge("news", "indicators")
    graph.add_edge("indicators", "decision")

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
trading_graph = build_trading_graph()
simple_pipeline = build_simple_pipeline()
