from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .auth import create_session, get_current_user, get_api_user, hash_password, revoke_session, verify_password
from .config import BASE_DIR
from .database import connect, init_db, utc_now
from .schemas import AgentCreate, ChatRequest, LoginRequest, ProviderCreate, SignupRequest, ExternalChatRequest, ExternalChatResponse
from .services.analytics import analytics_service
from .services.chat import chat_service
from .services.documents import document_service
from .services.graph import graph_service
from .services.providers import provider_service


app = FastAPI(title="OrchestraAI MVP", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/signup")
async def signup(payload: SignupRequest) -> dict:
    email = payload.email.strip().lower()
    db = await connect()
    try:
        existing_cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
        if await existing_cursor.fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

        api_key = "sk-orc-" + secrets.token_hex(16)
        now = utc_now()
        cursor = await db.execute(
            "INSERT INTO users (name, email, password_hash, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (payload.name.strip(), email, hash_password(payload.password), api_key, now),
        )
        user_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    token = await create_session(user_id)
    return {
        "token": token,
        "user": {"id": user_id, "name": payload.name.strip(), "email": email, "api_key": api_key},
    }


@app.post("/api/auth/login")
async def login(payload: LoginRequest) -> dict:
    email = payload.email.strip().lower()
    db = await connect()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        user = dict(row)
    finally:
        await db.close()

    token = await create_session(user["id"])
    return {
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
    }


@app.post("/api/auth/logout")
async def logout(
    user: dict = Depends(get_current_user),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    if token:
        await revoke_session(token)
    return {"status": "logged_out"}


@app.get("/api/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    db = await connect()
    try:
        cursor = await db.execute("SELECT api_key FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        api_key = row["api_key"] if row and row["api_key"] else ""
        if not api_key:
            api_key = "sk-orc-" + secrets.token_hex(16)
            await db.execute("UPDATE users SET api_key = ? WHERE id = ?", (api_key, user_id))
            await db.commit()
    finally:
        await db.close()
    return {"id": user["id"], "name": user["name"], "email": user["email"], "api_key": api_key}


@app.get("/api/bootstrap")
async def bootstrap(user: dict = Depends(get_current_user)) -> dict:
    user_id = int(user["id"])
    
    db = await connect()
    try:
        cursor = await db.execute("SELECT api_key FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        api_key = row["api_key"] if row and row["api_key"] else ""
        if not api_key:
            api_key = "sk-orc-" + secrets.token_hex(16)
            await db.execute("UPDATE users SET api_key = ? WHERE id = ?", (api_key, user_id))
            await db.commit()
    finally:
        await db.close()

    providers = await provider_service.list_providers(user_id)
    agents = await list_agents(user)
    overview = await analytics_service.overview(user_id)
    usage = await analytics_service.usage(user_id)
    return {
        "user": {"id": user["id"], "name": user["name"], "email": user["email"], "api_key": api_key},
        "overview": overview,
        "providers": providers,
        "agents": agents,
        "usage": usage,
    }


@app.get("/api/providers")
async def list_providers_endpoint(user: dict = Depends(get_current_user)) -> list[dict]:
    return await provider_service.list_providers(int(user["id"]))


@app.post("/api/providers")
async def create_provider(payload: ProviderCreate, user: dict = Depends(get_current_user)) -> dict:
    return await provider_service.create_provider(int(user["id"]), payload)


@app.get("/api/agents")
async def list_agents(user: dict = Depends(get_current_user)) -> list[dict]:
    user_id = int(user["id"])
    db = await connect()
    try:
        cursor = await db.execute(
            """
            SELECT
                agents.*,
                COALESCE(documents.total_documents, 0) AS document_count,
                COALESCE(chunks.total_chunks, 0) AS chunk_count,
                COALESCE(messages.total_messages, 0) AS message_count
            FROM agents
            LEFT JOIN (
                SELECT agent_id, COUNT(*) AS total_documents
                FROM documents
                GROUP BY agent_id
            ) AS documents ON documents.agent_id = agents.id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) AS total_chunks
                FROM chunks
                GROUP BY agent_id
            ) AS chunks ON chunks.agent_id = agents.id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) AS total_messages
                FROM messages
                GROUP BY agent_id
            ) AS messages ON messages.agent_id = agents.id
            WHERE agents.user_id = ?
            ORDER BY agents.updated_at DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [{**dict(row), "allow_web_search": bool(row["allow_web_search"])} for row in rows]
    finally:
        await db.close()


@app.post("/api/agents")
async def create_agent(payload: AgentCreate, user: dict = Depends(get_current_user)) -> dict:
    now = utc_now()
    db = await connect()
    try:
        cursor = await db.execute(
            """
            INSERT INTO agents (
                user_id, name, tagline, system_prompt, optimization_mode, status,
                allow_web_search, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user["id"]),
                payload.name.strip(),
                payload.tagline.strip(),
                payload.system_prompt.strip(),
                payload.optimization_mode.strip() or "balanced",
                "Active",
                1 if payload.allow_web_search else 0,
                now,
                now,
            ),
        )
        agent_id = cursor.lastrowid
        await db.commit()
        cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, int(user["id"])))
        row = await cursor.fetchone()
        return {**dict(row), "allow_web_search": bool(row["allow_web_search"])}
    finally:
        await db.close()


@app.get("/api/agents/{agent_id}/workspace")
async def agent_workspace(agent_id: int, user: dict = Depends(get_current_user)) -> dict:
    agent = await get_owned_agent(int(user["id"]), agent_id)
    documents = await document_service.list_documents(int(user["id"]), agent_id)
    graph = await graph_service.list_graph(agent_id)
    messages = await chat_service.list_messages(int(user["id"]), agent_id)
    return {
        "agent": {**agent, "allow_web_search": bool(agent["allow_web_search"])},
        "documents": documents,
        "graph": graph,
        "messages": messages,
    }


@app.post("/api/agents/{agent_id}/documents")
async def upload_document(agent_id: int, file: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        return await document_service.upload_document(int(user["id"]), agent_id, file.filename or "upload.txt", content)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/agents/{agent_id}/documents/{document_id}")
async def delete_document(
    agent_id: int, document_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    try:
        await document_service.delete_document(int(user["id"]), agent_id, document_id)
        return {"status": "deleted"}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.post("/api/agents/{agent_id}/chat")
async def chat_with_agent(agent_id: int, payload: ChatRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        return await chat_service.chat(int(user["id"]), agent_id, payload.message.strip())
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/external/chat")
async def external_chat(payload: ExternalChatRequest, api_user: dict = Depends(get_api_user)) -> dict:
    try:
        return await chat_service.chat_external(
            user_id=int(api_user["id"]),
            agent_id=payload.agent_id,
            customer_id=payload.customer_id,
            session_id=payload.session_id,
            message=payload.content.strip()
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/usage")
async def usage(user: dict = Depends(get_current_user)) -> dict:
    return await analytics_service.usage(int(user["id"]))


async def get_owned_agent(user_id: int, agent_id: int) -> dict:
    db = await connect()
    try:
        cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found.")
        return dict(row)
    finally:
        await db.close()


def frontend_file(path: str) -> FileResponse:
    target = BASE_DIR / path
    if not target.exists():
        raise HTTPException(status_code=404)
    return FileResponse(target)


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return frontend_file("index.html")


@app.get("/styles.css", include_in_schema=False)
async def styles() -> FileResponse:
    return frontend_file("styles.css")


@app.get("/app.js", include_in_schema=False)
async def script() -> FileResponse:
    return frontend_file("app.js")


@app.get("/README.md", include_in_schema=False)
async def readme() -> FileResponse:
    return frontend_file("README.md")
