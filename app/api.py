from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.auth_routes import get_current_user, router as auth_router
from app.schema import User


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class Source(BaseModel):
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


app = FastAPI(title="Agentic RAG API")
app.include_router(auth_router)


@app.post("/ask", response_model=AskResponse)
def ask_question(
    request: AskRequest,
    user: User = Depends(get_current_user),
) -> AskResponse:
    """
    Agent endpoint: guardrail -> router -> RAG/database/general -> validate.
    The RAG route itself lives in core.ask() via the agent's rag tool.
    Identity and role come from the JWT; role checks are enforced in the
    graph nodes, never by the LLM.
    """
    state = run_agent(request.question, user)

    return AskResponse(
        answer=state["answer"],
        sources=[Source(**s) for s in state["sources"]],
    )
