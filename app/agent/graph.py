from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    defer,
    diagnose,
    escalate,
    executor,
    planner,
    policy_gate,
    route_after_diagnose,
    route_after_policy,
    route_after_verify,
    triage,
    verifier,
    write_off,
)
from app.agent.state import AgentState


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("triage", triage)
    g.add_node("diagnose", diagnose)
    g.add_node("policy_gate", policy_gate)
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("verifier", verifier)
    g.add_node("escalate", escalate)
    g.add_node("write_off", write_off)
    g.add_node("defer", defer)

    g.set_entry_point("triage")
    g.add_edge("triage", "diagnose")
    g.add_conditional_edges("diagnose", route_after_diagnose, {"policy_gate": "policy_gate"})
    g.add_conditional_edges(
        "policy_gate",
        route_after_policy,
        {"planner": "planner", "escalate": "escalate", "write_off": "write_off", "defer": "defer"},
    )
    g.add_edge("planner", "executor")
    g.add_edge("executor", "verifier")
    g.add_conditional_edges(
        "verifier",
        route_after_verify,
        {"write_off": "write_off", "__end__": END},
    )
    g.add_edge("escalate", END)
    g.add_edge("write_off", END)
    return g.compile()


def run_case(app, case_id: int, round_no: int = 0, human_approved: bool = False) -> dict:
    from app.db import SessionLocal
    from app.agent.nodes import _base_state, _load_case

    with SessionLocal() as db:
        case, customer = _load_case(db, case_id)
        state = _base_state(case, customer)
    state["round_no"] = round_no
    state["human_approved"] = human_approved
    final = app.invoke(state, config={"recursion_limit": 30})
    return {k: final.get(k) for k in ("case_id", "cause", "confidence", "action", "recovered", "stop_reason")}
