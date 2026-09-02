from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.agent import run_agent


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class Source(BaseModel):
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


app = FastAPI(title="Agentic RAG API")


@app.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest) -> AskResponse:
    """
    Agent endpoint: guardrail -> router -> RAG/database/general -> validate.
    The RAG route itself lives in core.ask() via the agent's rag tool.
    """
    state = run_agent(request.question)

    return AskResponse(
        answer=state["answer"],
        sources=[Source(**s) for s in state["sources"]],
    )
