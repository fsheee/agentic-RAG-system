from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from sqlmodel import Session

from app.agent.state import AgentState
from app.agent.tools import booking_tool, db_tool, rag_tool
from app.core import _extract_text, get_llm
from app.db import get_engine
from app.guardrails import check_user_input
from app.schema import Role, User

# Backend role policy (checked in Python, never by the LLM):
# - RAG answers come from hospital documents: staff only.
# - Booking and appointment data: patients (their own) and admins.
RAG_ROLES = {Role.admin, Role.hr, Role.employee, Role.doctor}
APPOINTMENT_ROLES = {Role.admin, Role.patient}

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
    """RAG route: staff only. Delegate to the shared Phase 1 core."""
    role = state.get("user_role")
    if role is not None and role not in {r.value for r in RAG_ROLES}:
        return {
            "answer": (
                "The knowledge base assistant is available to hospital "
                "staff only. If you have a medical concern, please contact "
                "the hospital directly."
            ),
            "sources": [],
            "documents": [],
        }

    result = rag_tool.search_knowledge_base(state["question"])

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "documents": result["documents"],
    }


def _appointment_user(state: AgentState) -> tuple[User | None, bool]:
    """Load the requesting user for appointment scoping. Returns
    (user, denied): user is None when the agent runs unauthenticated
    (legacy/tests); denied is True when the role may not touch
    appointments at all."""
    user_id = state.get("user_id")
    role = state.get("user_role")
    if user_id is None or role is None:
        return None, False
    if Role(role) not in APPOINTMENT_ROLES:
        return None, True

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
    return user, False


def _denied_answer() -> dict:
    return {
        "answer": (
            "Appointments can only be viewed or managed by patients "
            "(their own) or administrators."
        ),
        "sources": [],
        "documents": [],
    }


def booking_node(state: AgentState) -> dict:
    """Booking route: cancel/reschedule actions, else the multi-step
    booking workflow (parse -> availability -> confirmation -> book)."""
    user, denied = _appointment_user(state)
    if denied:
        return _denied_answer()

    action = booking_tool.handle_appointment_action(state["question"], user)

    answer = (
        action
        if action is not None
        else booking_tool.run_booking(state["question"], user)
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
    user, denied = _appointment_user(state)
    if denied:
        return _denied_answer()

    action = booking_tool.handle_appointment_action(state["question"], user)
    if action is not None:
        return {"answer": action, "sources": []}

    if any(keyword in question for keyword in APPOINTMENT_LIST_KEYWORDS):
        return {"answer": booking_tool.list_appointments(user), "sources": []}

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


def run_agent(question: str, user: User | None = None) -> AgentState:
    """Invoke the compiled graph for a question and return the final state.

    `user` carries the authenticated identity (None keeps the legacy
    unauthenticated behavior used by direct module calls and tests).
    """
    graph = build_graph()

    initial: AgentState = {
        "question": question,
        "route": "",
        "answer": "",
        "sources": [],
        "documents": [],
        "error": None,
        "user_id": user.id if user else None,
        "user_role": user.role.value if user else None,
    }

    return graph.invoke(initial)

