from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.agent.tools import booking_tool, db_tool, rag_tool
from app.core import _extract_text, get_llm
from app.guardrails import check_user_input

ROUTER_PROMPT = ChatPromptTemplate.from_template(
    """
You are a router for a healthcare assistant.

Classify the user's question into exactly one route:

- rag: answerable from hospital documents, policies, HR rules, visiting hours,

  procedures, general health questions, greetings, or anything else that is
  not application data.
- database: asks about doctors, their specializations, consultation fees,
  doctor schedules, or viewing existing appointments.
- booking: the user wants to book, cancel, or reschedule an appointment.

Reply with a single word: rag, database, or booking.

Question:
{question}
"""
)

ROUTES = ("rag", "database", "booking")


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
    # A pending booking confirmation must not be re-routed by the LLM —
    # a bare "yes"/"no" would otherwise end up somewhere else.
    if booking_tool.is_awaiting_confirmation():
        return {"route": "booking"}

    return {"route": route_question(state["question"])}


def rag_node(state: AgentState) -> dict:
    """RAG route: delegate to the shared Phase 1 core via the RAG tool."""
    result = rag_tool.search_knowledge_base(state["question"])

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "documents": result["documents"],
    }


def booking_node(state: AgentState) -> dict:
    """Booking route: cancel/reschedule actions, else the multi-step
    booking workflow (parse -> availability -> confirmation -> book)."""
    action = booking_tool.handle_appointment_action(state["question"])

    answer = action if action is not None else booking_tool.run_booking(
        state["question"]
    )

    return {"answer": answer, "sources": [], "documents": []}


# Questions about money route to the fee tool inside the database node.
FEE_KEYWORDS = ("fee", "fees", "charge", "charges", "cost", "price")

# Questions about viewing appointments inside the database node.
APPOINTMENT_LIST_KEYWORDS = ("my appointment", "my appointments", "show appointment")


def database_node(state: AgentState) -> dict:
    """Database route: structured data from Neon via the (safe) db tool."""
    question = state["question"].lower()

    # The router sometimes sends cancel/reschedule here; the action tool
    # returns None for non-action questions.
    action = booking_tool.handle_appointment_action(state["question"])
    if action is not None:
        return {"answer": action, "sources": []}

    if any(keyword in question for keyword in APPOINTMENT_LIST_KEYWORDS):
        return {"answer": booking_tool.list_appointments(), "sources": []}

    if any(word in question for word in FEE_KEYWORDS):
        return _fees_answer()

    # A specific doctor mentioned by name -> their details.
    details = db_tool.doctor_details(state["question"])
    if details is not None:
        return {"answer": details, "sources": []}

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


def _fees_answer() -> dict:
    fees = db_tool.get_consultation_fees()

    if not fees:
        return {"answer": "No doctors are currently registered.", "sources": []}

    lines = []
    for fee in fees:
        if fee["consultation_fee"] is None:
            lines.append(f"- {fee['name']} ({fee['specialization']}): fee not set")
        else:
            lines.append(
                f"- {fee['name']} ({fee['specialization']}): PKR {fee['consultation_fee']}"
            )

    return {
        "answer": "Consultation fees:\n" + "\n".join(lines),
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
    graph.add_node("booking", booking_node)
    graph.add_node("validate", validate_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges(
        "guardrail",
        _route_from,
        {"validate": "validate", "rag": "router", "database": "router", "booking": "router"},
    )
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {"rag": "rag", "database": "database", "booking": "booking"},
    )
    graph.add_edge("rag", "validate")
    graph.add_edge("database", "validate")
    graph.add_edge("booking", "validate")
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

