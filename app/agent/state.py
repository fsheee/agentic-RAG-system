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
    # Prior turns as [{"role", "content"}] dicts — plain data rather than
    # ORM objects, so this module never imports the database schema.
    # None means no memory (anonymous callers, CLI, tests).
    history: list[dict] | None
    # Which conversation this turn belongs to. None for anonymous and for
    # direct/CLI callers; used to scope pending booking state.
    conversation_id: int | None
