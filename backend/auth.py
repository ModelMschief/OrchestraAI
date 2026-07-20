from __future__ import annotations

import hashlib
import secrets

from fastapi import Header, HTTPException

from .database import connect, utc_now


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, hash_hex = stored_hash.split(":", 1)
    except ValueError:
        return False
    derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return secrets.compare_digest(derived.hex(), hash_hex)


async def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    db = await connect()
    try:
        await db.execute(
            "INSERT INTO sessions (token, user_id, created_at, last_used_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now),
        )
        await db.commit()
    finally:
        await db.close()
    return token


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    db = await connect()
    try:
        cursor = await db.execute(
            """
            SELECT users.id, users.name, users.email, sessions.token
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        await db.execute("UPDATE sessions SET last_used_at = ? WHERE token = ?", (utc_now(), token))
        await db.commit()
        return dict(row)
    finally:
        await db.close()


async def get_api_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="API authentication required.")
    api_key = authorization.split(" ", 1)[1].strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="API authentication required.")

    db = await connect()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE api_key = ?", (api_key,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return dict(row)
    finally:
        await db.close()


async def revoke_session(token: str) -> None:
    db = await connect()
    try:
        await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await db.commit()
    finally:
        await db.close()
