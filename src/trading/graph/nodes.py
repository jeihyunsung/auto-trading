"""LangGraph node functions for the trading system."""

from trading.agents.decision_agent import decision_agent_node
from trading.agents.execution_agent import execution_agent_node
from trading.agents.indicator_agent import indicator_agent_node
from trading.agents.market_agent import market_agent_node
from trading.agents.news_agent import news_agent_node
from trading.agents.ops_agent import ops_agent_node
from trading.agents.risk_agent import risk_agent_node
from trading.core.state import TradingState
from trading.llm.client import get_llm_client
from trading.llm.prompts import SUPERVISOR_SYSTEM_PROMPT, SUPERVISOR_USER_PROMPT

# Re-export all agent nodes
__all__ = [
    "market_agent_node",
    "news_agent_node",
    "indicator_agent_node",
    "decision_agent_node",
    "risk_agent_node",
    "execution_agent_node",
    "ops_agent_node",
    "supervisor_node",
]


def supervisor_node(state: TradingState) -> dict:
    """Supervisor node that decides which agent to run next.

    Args:
        state: Current trading state.

    Returns:
        State update with next step.
    """
    # Check for errors first - stop the cycle on any error
    error = state.get("error")
    if error:
        return {"current_step": "FINISH"}

    # Check kill switch
    risk = state.get("risk", {})
    if risk.get("is_kill_switch_on"):
        return {"current_step": "FINISH"}

    # Format state for supervisor
    market = state.get("market")
    news = state.get("news")
    indicators = state.get("indicators")
    portfolio = state.get("portfolio")
    decision = state.get("decision")
    anomalies = state.get("anomalies", [])

    # Determine statuses
    market_status = "available" if market else "missing"
    news_status = "available" if news else "missing"
    indicator_status = "available" if indicators else "missing"
    portfolio_status = "available" if portfolio else "missing"

    # Decision status
    if not decision:
        decision_status = "not generated"
    else:
        decision_status = f"{decision.get('action', 'unknown')} - {decision.get('status', 'unknown')}"

    # Anomaly info
    high_severity = sum(1 for a in anomalies if a.get("severity") == "high")
    anomaly_severity = f"{high_severity} high severity" if high_severity else "none critical"

    # Try LLM supervisor
    try:
        llm = get_llm_client()
        if llm.is_available:
            prompt = SUPERVISOR_USER_PROMPT.format(
                market_status=market_status,
                news_status=news_status,
                indicator_status=indicator_status,
                portfolio_status=portfolio_status,
                decision_status=decision_status,
                anomaly_count=len(anomalies),
                anomaly_severity=anomaly_severity,
                kill_switch="ON" if risk.get("is_kill_switch_on") else "OFF",
            )

            response = llm.invoke(SUPERVISOR_SYSTEM_PROMPT, prompt)
            next_step = response.strip().lower()

            # Validate response
            valid_steps = {
                "market_agent", "news_agent", "indicator_agent",
                "analysis_agent", "decision_agent", "risk_agent", "execution_agent", "finish"
            }

            if next_step in valid_steps:
                # Map analysis_agent to decision_agent
                if next_step == "analysis_agent":
                    next_step = "decision_agent"

                # Safety check: decision_agent requires market and indicators
                if next_step == "decision_agent":
                    if not market:
                        return {"current_step": "market_agent"}
                    if not indicators:
                        return {"current_step": "indicator_agent"}

                return {"current_step": next_step}

    except Exception:
        pass  # Fall through to rule-based

    # Rule-based supervisor fallback
    return _rule_based_supervisor(state)


def _rule_based_supervisor(state: TradingState) -> dict:
    """Rule-based supervisor when LLM is unavailable.

    Args:
        state: Current trading state.

    Returns:
        State update with next step.
    """
    market = state.get("market")
    news = state.get("news")
    indicators = state.get("indicators")
    decision = state.get("decision")
    anomalies = state.get("anomalies", [])
    error = state.get("error")
    completed_agents = state.get("completed_agents", set())

    # If there's an error, finish the cycle
    if error:
        return {"current_step": "FINISH"}

    # Step 1: Collect market data
    if not market and "market_agent" not in completed_agents:
        return {"current_step": "market_agent", "completed_agents": completed_agents | {"market_agent"}}

    # Step 2: Collect news
    if not news:
        return {"current_step": "news_agent"}

    # Step 3: Calculate indicators
    if not indicators:
        return {"current_step": "indicator_agent"}

    # Step 4: Check for high severity anomalies - need immediate decision
    high_severity = any(a.get("severity") == "high" for a in anomalies)

    # Step 5: Generate decision if needed
    if not decision:
        return {"current_step": "decision_agent"}

    # Step 6: Validate decision with risk agent
    if decision.get("status") == "pending":
        return {"current_step": "risk_agent"}

    # Step 7: Execute if approved
    if decision.get("status") == "approved":
        return {"current_step": "execution_agent"}

    # Step 8: Finish (rejected, executed, or hold)
    return {"current_step": "FINISH"}
