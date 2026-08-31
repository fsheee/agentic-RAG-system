from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.agent.tools import db_tool, rag_tool
from app.core import _extract_text, get_llm
from app.guardrails import check_user_input

ROUTER_PROMPT = ChatPromptTemplate.from_template(
    """
You are a router for a healthcare assistant.

Classify the user's question into exactly one route:

- rag: answerable from hospital documents, policies, HR rules, visiting hours,
  procedures, general health questions, greetings, or anything else that is
  not application data.
- database: asks about doctors, their specializations, doctor schedules,
  appointments or other application records.

Reply with a single word: rag or database.

Question:
{question}
"""
)

ROUTES = ("rag", "database")


def route_question(question: str) -> str:
    """LLM-based routing. Falls back to 'rag' on unexpected output; the RAG
    prompt then answers off-scope questions with 'I don't know based on the
    provided documents.'"""
    response = get_llm().invoke(ROUTER_PROMPT.invoke({"question": question}))
    answer = _extract_text(response).strip().lower()

    for route in ROUTES:
        if route in answer:
            return route

    return "rag"


def guardrail_node(state: AgentState) -> dict:
    """User input trust boundary: reject prompt-injection attempts."""
    reason = check_user_input(state["question"])

    if reason:
        return {
            "answer": f"I can't process that request. {reason}",
            "route": "blocked",
            "error": reason,
            "sources": [],
            "documents": [],
        }

    return {"error": None}


def router_node(state: AgentState) -> dict:
    return {"route": route_question(state["question"])}


def rag_node(state: AgentState) -> dict:
    """RAG route: delegate to the shared Phase 1 core via the RAG tool."""
    result = rag_tool.search_knowledge_base(state["question"])

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "documents": result["documents"],
    }


def database_node(state: AgentState) -> dict:
    """Database route: structured data from Neon via the (safe) db tool."""
    doctors = db_tool.list_doctors()

    if not doctors:
        return {"answer": "No doctors are currently registered.", "sources": []}

    lines = [
        f"- {doctor['name']} ({doctor['specialization']})"
        for doctor in doctors
    ]

    return {
        "answer": "Registered doctors:\n" + "\n".join(lines),
        "sources": [],
    }


def validate_node(state: AgentState) -> dict:
    """Final check: an empty answer is a failure, not a success."""
    if state.get("error"):
        return {}

    if not state.get("answer") or not state["answer"].strip():
        return {
            "answer": "Sorry, I couldn't generate an answer right now.",
            "error": "Empty answer",
        }

    return {}


def _route_from(state: AgentState) -> str:
    if state.get("error"):
        return "validate"

    return state["route"] if state["route"] in ROUTES else "rag"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("guardrail", guardrail_node)
    graph.add_node("router", router_node)
    graph.add_node("rag", rag_node)
    graph.add_node("database", database_node)
    graph.add_node("validate", validate_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges(
        "guardrail",
        _route_from,
        {"validate": "validate", "rag": "router", "database": "router"},
    )
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {"rag": "rag", "database": "database"},
    )
    graph.add_edge("rag", "validate")
    graph.add_edge("database", "validate")
    graph.add_edge("validate", END)

    return graph.compile()


def run_agent(question: str) -> AgentState:
    """Invoke the compiled graph for a question and return the final state."""
    graph = build_graph()

    initial: AgentState = {
        "question": question,
        "route": "",
        "answer": "",
        "sources": [],
        "documents": [],
        "error": None,
    }

    return graph.invoke(initial)
