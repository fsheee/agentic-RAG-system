from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.appointment_routes import router as appointment_router
from app.auth_routes import get_optional_user, router as auth_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(appointment_router)


@app.post("/ask", response_model=AskResponse)
def ask_question(
    request: AskRequest,
    user: User | None = Depends(get_optional_user),
) -> AskResponse:
    """
    Agent endpoint: guardrail -> router -> RAG/database/general -> validate.
    The RAG route itself lives in core.ask() via the agent's rag tool.

    Authentication is optional. Anonymous callers get public hospital
    information only; a valid token widens access to what the caller's
    role may read. Identity and role come from the JWT, never the request
    body, and are enforced in the graph nodes and the Qdrant retrieval
    filter — never by the LLM.
    """
    state = run_agent(request.question, user)

    return AskResponse(
        answer=state["answer"],
        sources=[Source(**s) for s in state["sources"]],
    )
