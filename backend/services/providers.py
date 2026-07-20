from __future__ import annotations

import json
import re
import logging
from typing import Any

import asyncio
import httpx

from ..database import connect, utc_now
from ..schemas import ProviderCreate

logger = logging.getLogger(__name__)


class ProviderService:
    async def list_providers(self, user_id: int) -> list[dict[str, Any]]:
        db = await connect()
        try:
            cursor = await db.execute("SELECT * FROM providers WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
            rows = await cursor.fetchall()
            return [self._row_to_provider(row) for row in rows]
        finally:
            await db.close()

    async def get_active_providers(self, user_id: int) -> list[dict[str, Any]]:
        db = await connect()
        try:
            cursor = await db.execute(
                "SELECT * FROM providers WHERE user_id = ? AND status = 'validated' ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_provider(row, include_secret=True) for row in rows]
        finally:
            await db.close()

    async def create_provider(self, user_id: int, payload: ProviderCreate) -> dict[str, Any]:
        validation = await self.validate_provider(payload.provider_type, payload.api_key, payload.default_model)
        now = utc_now()

        db = await connect()
        try:
            cursor = await db.execute(
                """
                INSERT INTO providers (
                    user_id, provider_type, api_key, masked_key, status, default_model,
                    models_json, capabilities_json, last_error, last_validated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    payload.provider_type,
                    payload.api_key.strip(),
                    self.mask_key(payload.api_key),
                    validation["status"],
                    validation.get("default_model"),
                    json.dumps(validation.get("models", [])),
                    json.dumps(validation.get("capabilities", [])),
                    validation.get("last_error"),
                    now if validation["status"] == "validated" else None,
                    now,
                    now,
                ),
            )
            provider_id = cursor.lastrowid
            await db.commit()
        finally:
            await db.close()

        created = {
            "id": provider_id,
            "provider_type": payload.provider_type,
            "masked_key": self.mask_key(payload.api_key),
            **validation,
            "last_validated_at": now if validation["status"] == "validated" else None,
        }
        return created

    async def validate_provider(self, provider_type: str, api_key: str, requested_model: str | None) -> dict[str, Any]:
        if provider_type == "openai":
            return await self._validate_openai(api_key, requested_model)
        if provider_type == "gemini":
            return await self._validate_gemini(api_key, requested_model)
        if provider_type == "groq":
            return await self._validate_groq(api_key, requested_model)
        return {
            "status": "invalid",
            "default_model": requested_model,
            "models": [],
            "capabilities": [],
            "last_error": "Unsupported provider type.",
        }

    async def _validate_openai(self, api_key: str, requested_model: str | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.openai.com/v1/models", headers=headers)

        if response.status_code >= 400:
            return {
                "status": "invalid",
                "default_model": requested_model,
                "models": [],
                "capabilities": [],
                "last_error": self._safe_error(response),
            }

        data = response.json().get("data", [])
        models = sorted({item["id"] for item in data if item["id"].startswith(("gpt", "o"))})[:24]
        return {
            "status": "validated",
            "default_model": requested_model or self._pick_openai_model(models),
            "models": models,
            "capabilities": ["chat", "reasoning", "document extraction", "json output"],
            "last_error": None,
        }

    async def _validate_gemini(self, api_key: str, requested_model: str | None) -> dict[str, Any]:
        headers = {"x-goog-api-key": api_key.strip()}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers)

        if response.status_code >= 400:
            return {
                "status": "invalid",
                "default_model": requested_model,
                "models": [],
                "capabilities": [],
                "last_error": self._safe_error(response),
            }

        raw_models = response.json().get("models", [])
        models = []
        for item in raw_models:
            supported = item.get("supportedGenerationMethods") or item.get("supported_actions") or []
            if "generateContent" in supported or "GenerateContent" in supported:
                models.append(item["name"])

        models = sorted(set(models))[:24]
        return {
            "status": "validated",
            "default_model": requested_model or self._pick_gemini_model(models),
            "models": models,
            "capabilities": ["chat", "summarization", "long context", "web synthesis"],
            "last_error": None,
        }

    async def _validate_groq(self, api_key: str, requested_model: str | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.groq.com/openai/v1/models", headers=headers)

        if response.status_code >= 400:
            return {
                "status": "invalid",
                "default_model": requested_model,
                "models": [],
                "capabilities": [],
                "last_error": self._safe_error(response),
            }

        data = response.json().get("data", [])
        models = sorted(
            {
                item["id"]
                for item in data
                if item.get("active", True)
                and not str(item.get("id", "")).startswith(("whisper", "playai", "distil-whisper", "llama-guard"))
            }
        )[:32]
        return {
            "status": "validated",
            "default_model": requested_model or self._pick_groq_model(models),
            "models": models,
            "capabilities": ["chat", "fast inference", "responses api", "cost-aware routing"],
            "last_error": None,
        }

    async def generate(
        self,
        provider: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        provider_type = provider["provider_type"]
        selected_model = model or provider.get("default_model")
        if provider_type == "openai":
            return await self._generate_openai(provider["api_key"], selected_model, system_prompt, user_prompt)
        if provider_type == "gemini":
            return await self._generate_gemini(provider["api_key"], selected_model, system_prompt, user_prompt)
        if provider_type == "groq":
            return await self._generate_groq(provider["api_key"], selected_model, system_prompt, user_prompt)
        raise RuntimeError(f"Unsupported provider for generation: {provider_type}")

    async def _generate_openai(
        self,
        api_key: str,
        model: str | None,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await self._post_with_retry(client, "https://api.openai.com/v1/chat/completions", headers, payload)
        
        data = response.json()
        return {
            "text": data["choices"][0]["message"]["content"],
            "model": data.get("model", payload["model"]),
            "usage": data.get("usage", {}),
        }

    async def _generate_gemini(
        self,
        api_key: str,
        model: str | None,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        selected_model = model or "models/gemini-2.0-flash"
        if not selected_model.startswith("models/"):
            selected_model = f"models/{selected_model}"

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200},
        }
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/{selected_model}:generateContent"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await self._post_with_retry(client, url, headers, payload)
        data = response.json()
        text_parts: list[str] = []
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])
        return {
            "text": "\n".join(text_parts).strip(),
            "model": selected_model,
            "usage": data.get("usageMetadata", {}),
        }

    async def _generate_groq(
        self,
        api_key: str,
        model: str | None,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model or "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await self._post_with_retry(client, "https://api.groq.com/openai/v1/chat/completions", headers, payload)
        
        data = response.json()
        return {
            "text": data["choices"][0]["message"]["content"],
            "model": data.get("model", payload["model"]),
            "usage": data.get("usage", {}),
        }

    async def _post_with_retry(self, client: httpx.AsyncClient, url: str, headers: dict, payload: dict, retries: int = 3) -> httpx.Response:
        for attempt in range(retries):
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 429:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt + 2) # Exponential backoff starting at 3 seconds
                    continue
            response.raise_for_status()
            return response
        raise RuntimeError("Max retries exceeded")

    def choose_provider(self, providers: list[dict[str, Any]], use_case: str) -> dict[str, Any] | None:
        if not providers:
            return None

        priorities = {
            "graph": ["openai", "gemini", "groq"],
            "web_summary": ["gemini", "groq", "openai"],
            "final_answer": ["openai", "groq", "gemini"],
        }.get(use_case, ["openai", "groq", "gemini"])

        for provider_type in priorities:
            for provider in providers:
                if provider["provider_type"] == provider_type:
                    return provider
        return providers[0]

    def mask_key(self, api_key: str) -> str:
        key = api_key.strip()
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"

    def _row_to_provider(self, row: Any, include_secret: bool = False) -> dict[str, Any]:
        provider = {
            "id": row["id"],
            "provider_type": row["provider_type"],
            "masked_key": row["masked_key"],
            "status": row["status"],
            "default_model": row["default_model"],
            "models": json.loads(row["models_json"] or "[]"),
            "capabilities": json.loads(row["capabilities_json"] or "[]"),
            "last_error": row["last_error"],
            "last_validated_at": row["last_validated_at"],
        }
        if include_secret:
            provider["api_key"] = row["api_key"]
        return provider

    def _pick_openai_model(self, models: list[str]) -> str:
        preferred = ("gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini", "gpt-5")
        return self._pick_preferred(models, preferred, "gpt-4.1-mini")

    def _pick_gemini_model(self, models: list[str]) -> str:
        preferred = ("models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-1.5-flash")
        return self._pick_preferred(models, preferred, "models/gemini-2.0-flash")

    def _pick_groq_model(self, models: list[str]) -> str:
        preferred = (
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
        )
        return self._pick_preferred(models, preferred, "llama-3.1-8b-instant")

    def _pick_preferred(self, models: list[str], preferred: tuple[str, ...], fallback: str) -> str:
        for wanted in preferred:
            for model in models:
                if model == wanted:
                    return model
        return models[0] if models else fallback

    def _safe_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception as e:
            logger.error(f"Failed to parse provider response JSON: {e}", exc_info=True)
            return f"{response.status_code} {response.text[:180]}"
        detail = payload.get("error")
        if isinstance(detail, dict):
            return detail.get("message", str(detail))
        return str(detail or payload)[:180]

    def _extract_openai_output(self, payload: dict[str, Any]) -> str:
        if payload.get("output_text"):
            return payload["output_text"].strip()

        chunks: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def parse_json_fragment(self, text: str) -> dict[str, Any] | None:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON fragment: {e}")
            return None


provider_service = ProviderService()
