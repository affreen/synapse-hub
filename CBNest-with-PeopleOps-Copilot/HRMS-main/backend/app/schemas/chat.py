from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)


class ChatMessageCreate(BaseModel):
    role: str = Field(min_length=3, max_length=20)
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Request body for POST /chat/policy, /chat/sql, /chat/actions, /chat/router."""

    message: str = Field(min_length=1, max_length=2000)
    # Echoed back by the frontend when the user is replying yes/no to a
    # previously returned requires_confirmation action (Human-in-the-Loop).
    pending_action: dict | None = None

