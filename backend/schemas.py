from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class AuthResponse(BaseModel):
    token: str
    user: dict[str, str | int]


class ProviderCreate(BaseModel):
    provider_type: str = Field(pattern="^(openai|gemini|groq)$")
    api_key: str = Field(min_length=10)
    default_model: str | None = None


class ProviderRead(BaseModel):
    id: int
    provider_type: str
    masked_key: str
    status: str
    default_model: str | None
    models: list[str]
    capabilities: list[str]
    last_error: str | None = None
    last_validated_at: str | None = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    tagline: str = Field(default="", max_length=240)
    system_prompt: str = Field(default="", max_length=4000)
    optimization_mode: str = Field(default="balanced")
    allow_web_search: bool = True


class AgentRead(BaseModel):
    id: int
    name: str
    tagline: str
    system_prompt: str
    optimization_mode: str
    allow_web_search: bool
    status: str
    created_at: str
    updated_at: str
    document_count: int = 0
    chunk_count: int = 0
    message_count: int = 0


class DocumentRead(BaseModel):
    id: int
    filename: str
    file_type: str
    status: str
    summary: str
    chunk_count: int
    entity_count: int
    relationship_count: int
    created_at: str


class MessageRead(BaseModel):
    id: int
    role: str
    content: str
    sources: list[dict[str, Any]]
    runtime: dict[str, Any]
    tokens_estimate: int
    created_at: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    runtime: dict[str, Any]
    provider: str | None = None
    model: str | None = None


class ExternalChatRequest(BaseModel):
    agent_id: int
    customer_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=2, max_length=4000)


class ExternalChatResponse(BaseModel):
    answer: str
    session_id: str
    customer_id: str
