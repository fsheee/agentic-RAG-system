import os

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent import run_agent
from app.appointment_routes import router as appointment_router
from app.auth_routes import get_optional_user, router as auth_router
from app.crud import (
    append_message,
    create_conversation,
    get_conversation_for_user,
    get_recent_messages,
)
from app.db import get_session
from app.schema import User


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional so existing clients keep working. Supplying one continues
    # that conversation; the caller must own it.
    #
    # ge=1 rejects 0 and negatives as malformed input (422). Without it a
    # `conversation_id: 0` reaches the anonymous check below, where `0 is
    # not None` is true and the caller is told "Sign in to use conversation
    # history" — which reads like a permissions problem rather than a bad
    # id. Real ids start at 1, so anything lower is a request error.
    conversation_id: int | None = Field(default=None, ge=1)


class Source(BaseModel):
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    # None when the caller is anonymous (no memory is kept).
    conversation_id: int | None = None


app = FastAPI(title="Agentic RAG API")

# Real origins only: browsers reject a wildcard combined with
# allow_credentials, and the frontend authenticates with a bearer token
# sent from an explicit origin. Comma-separated, no spaces needed.
# e.g. ALLOWED_ORIGINS=http://localhost:3000,https://app.example.com
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    session: Session = Depends(get_session),
) -> AskResponse:
    """
    Agent endpoint: guardrail -> router -> RAG/database/general -> validate.
    The RAG route itself lives in core.ask() via the agent's rag tool.

    Authentication is optional. Anonymous callers get public hospital
    information only; a valid token widens access to what the caller's
    role may read. Identity and role come from the JWT, never the request
    body, and are enforced in the graph nodes and the Qdrant retrieval
    filter — never by the LLM.

    Conversation memory is for authenticated callers only. A conversation
    must have an owner for "a user reads only their own conversations" to
    mean anything, so anonymous callers get no history and nothing is
    persisted for them.
    """
    conversation = None

    if user is None:
        if request.conversation_id is not None:
            # Never load or write history without an identity to scope it to.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Sign in to use conversation history.",
            )
    elif request.conversation_id is None:
        conversation = create_conversation(session, user.id, title=request.question)
    else:
        # Ownership-checked: another user's id resolves to None. 404 rather
        # than 403 so the response does not confirm that the row exists.
        conversation = get_conversation_for_user(
            session, request.conversation_id, user.id
        )
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    history = None
    if conversation is not None:
        # Windowed in the query; core.format_history caps the rendered size.
        history = [
            {"role": message.role, "content": message.content}
            for message in get_recent_messages(session, conversation.id)
        ]

    state = run_agent(
        request.question,
        user,
        history=history,
        conversation_id=conversation.id if conversation else None,
    )

    if conversation is not None:
        append_message(session, conversation.id, "user", request.question)
        append_message(session, conversation.id, "assistant", state["answer"])

    return AskResponse(
        answer=state["answer"],
        sources=[Source(**s) for s in state["sources"]],
        conversation_id=conversation.id if conversation else None,
    )
