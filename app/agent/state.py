from typing import TypedDict


class AgentState(TypedDict):
    question: str
    route: str
    answer: str
    sources: list[dict]
    documents: list
    error: str | None
    # Authenticated user context (None when the agent runs without auth,
    # e.g. direct module use in tests). Role checks happen in Python here,
    # never in the LLM.
    user_id: int | None
    user_role: str | None
