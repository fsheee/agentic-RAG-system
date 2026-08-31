from fastapi import FastAPI
from pydantic import BaseModel, Field

from app import core


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
    """Single RAG endpoint. All generation logic lives in core.ask()."""
    result = core.ask(request.question)

    return AskResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
    )
