from typing import TypedDict


class AgentState(TypedDict):
    question: str
    route: str
    answer: str
    sources: list[dict]
    documents: list
    error: str | None
