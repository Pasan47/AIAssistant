"""LangGraph assembly.

 START -> guard_input -> supervisor -> { retrieval | research(RLM) | (direct) } -> response
       -> validation -> memory_update -> END
 A blocked request short-circuits guard_input -> blocked_response -> END.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.memory import memory_update
from app.agents.research_agent import research_agent
from app.agents.response_agent import response_agent
from app.agents.retrieval_agent import retrieval_agent
from app.agents.runtime import agent_node
from app.agents.state import AgentState
from app.agents.supervisor import supervisor
from app.agents.validation import validation
from app.config import settings
from app.context import emit
from app.security import screen_user_message

REFUSAL = (f"I'm sorry, I can't help with that request. I'm {settings.bank_name}'s internal knowledge assistant and can only "
           "answer questions about company documents and approved enterprise data.")


@agent_node("guard_input", "Validating request & screening for prompt injection", fallback={"blocked": True, "final": REFUSAL})
async def guard_input(state: dict) -> dict:
    verdict = screen_user_message(state["question"])
    await emit("validation", stage="input", ok=verdict.allowed, category=verdict.category, detail=verdict.reason)
    if not verdict.allowed:
        return {"blocked": True, "final": REFUSAL, "validation": {"ok": False, "problems": [verdict.category]}}
    return {"messages": [HumanMessage(content=state["question"])]}  # blocked text never enters memory/history


@agent_node("blocked_response", "Refusing unsafe request")
async def blocked_response(state: dict) -> dict:
    await emit("final", answer=state["final"], sources=[], validation=state.get("validation", {}), errors=[])
    return {"messages": []}


def _after_guard(state: dict) -> str:
    return "blocked_response" if state.get("blocked") else "supervisor"


def _after_supervisor(state: dict) -> str:
    return {"research": "research", "retrieval": "retrieval"}.get(state["plan"].get("route"), "response")


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [("guard_input", guard_input), ("blocked_response", blocked_response), ("supervisor", supervisor),
                     ("retrieval", retrieval_agent), ("research", research_agent), ("response", response_agent),
                     ("validation", validation), ("memory_update", memory_update)]:
        g.add_node(name, fn)
    g.add_edge(START, "guard_input")
    g.add_conditional_edges("guard_input", _after_guard, {"blocked_response": "blocked_response", "supervisor": "supervisor"})
    g.add_conditional_edges("supervisor", _after_supervisor, {"retrieval": "retrieval", "research": "research", "response": "response"})
    g.add_edge("retrieval", "response")
    g.add_edge("research", "response")
    g.add_edge("response", "validation")
    g.add_edge("validation", "memory_update")
    g.add_edge("memory_update", END)
    g.add_edge("blocked_response", END)
    return g.compile(checkpointer=MemorySaver())  # session-level persistence (assumption.docx)
