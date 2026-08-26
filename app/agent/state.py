from typing import TypedDict


class AgentState(TypedDict):
    question: str
    documents: list
    context: str
    answer: str
    employee_id: int | None