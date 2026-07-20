from __future__ import annotations

import json
import logging
from typing import Any

from ..database import connect, utc_now
from .embeddings import embedding_service
from .graph import graph_service
from .providers import provider_service
from .retrieval import retrieval_service
from .web_search import web_search_service

logger = logging.getLogger(__name__)


class ChatService:
    async def chat(self, user_id: int, agent_id: int, message: str) -> dict[str, Any]:
        agent = await self._get_agent(user_id, agent_id)
        if not agent:
            raise ValueError("Agent not found.")

        providers = await provider_service.get_active_providers(user_id)
        retrieved = await retrieval_service.retrieve(agent_id, message, top_k=5)
        top_score = retrieved[0]["score"] if retrieved else None
        needs_web = bool(agent["allow_web_search"]) and web_search_service.should_search(message, top_score)
        pages = await web_search_service.search_and_fetch(message) if needs_web else []
        web_summary = await web_search_service.summarize(message, pages, providers) if pages else ""

        local_context = "\n\n".join(
            f"[{item['filename']}] (score {item['score']}): {item['content']}" for item in retrieved
        )
        web_context = "\n\n".join(f"[{page['title']}] {page['url']}\n{page['content']}" for page in pages)

        selected_provider = provider_service.choose_provider(providers, "final_answer")
        runtime = {
            "query": message,
            "local_chunk_count": len(retrieved),
            "top_score": top_score,
            "used_web_search": bool(pages),
            "web_result_count": len(pages),
            "embedding_mode": "fallback-hash" if embedding_service.using_fallback else "sentence-transformers",
            "optimization_notes": [
                "Only top-ranked local chunks were packed into the prompt.",
                "Web search triggered only after freshness heuristics or low retrieval confidence.",
                "Document and web context were deduplicated before final synthesis.",
            ],
        }

        prompt = (
            f"Agent name: {agent['name']}\n"
            f"Agent system goal: {agent['system_prompt']}\n\n"
            "LOCAL KNOWLEDGE:\n"
            f"{local_context or 'No strong local knowledge matched the question.'}\n\n"
            "WEB CONTEXT:\n"
            f"{web_context or 'No external pages were needed.'}\n\n"
            "WEB SUMMARY:\n"
            f"{web_summary or 'No external summary available.'}\n\n"
            f"USER QUESTION:\n{message}\n\n"
            "Answer clearly, prefer uploaded knowledge first, and add a short Sources section."
        )

        provider_name = None
        model_name = None
        token_estimate = self._estimate_tokens(prompt)
        if selected_provider:
            provider_name = selected_provider["provider_type"]
            try:
                result = await provider_service.generate(
                    selected_provider,
                    "You are OrchestraAI's runtime response engine. Ground answers in provided context and include sources.",
                    prompt,
                )
                answer = result.get("text", "").strip() or self._fallback_answer(local_context, web_summary, message)
                model_name = result.get("model")
                usage = result.get("usage") or {}
                token_estimate = int(usage.get("total_tokens") or usage.get("totalTokenCount") or token_estimate)
            except Exception as error:
                logger.error(f"Provider generation failed during chat: {error}", exc_info=True)
                answer = self._fallback_answer(local_context, web_summary, message)
                runtime["provider_error"] = str(error)
        else:
            answer = self._fallback_answer(local_context, web_summary, message)

        runtime["selected_provider"] = provider_name
        runtime["selected_model"] = model_name

        sources = [
            {"type": "document", "label": item["filename"], "score": item["score"]} for item in retrieved
        ] + [{"type": "web", "label": page["title"], "url": page["url"]} for page in pages]

        conversation_id = await self._ensure_conversation(agent_id, agent["name"])
        await self._save_message(conversation_id, agent_id, "user", message, [], {}, self._estimate_tokens(message))
        await self._save_message(conversation_id, agent_id, "assistant", answer, sources, runtime, token_estimate)

        return {
            "answer": answer,
            "sources": sources,
            "runtime": runtime,
            "provider": provider_name,
            "model": model_name,
        }

    async def list_messages(self, user_id: int, agent_id: int, limit: int = 16) -> list[dict[str, Any]]:
        agent = await self._get_agent(user_id, agent_id)
        if not agent:
            return []
        db = await connect()
        try:
            cursor = await db.execute(
                """
                SELECT id, role, content, sources_json, runtime_json, tokens_estimate, created_at
                FROM messages
                WHERE agent_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (agent_id, limit),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()

        messages = []
        for row in reversed(rows):
            messages.append(
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "sources": json.loads(row["sources_json"] or "[]"),
                    "runtime": json.loads(row["runtime_json"] or "{}"),
                    "tokens_estimate": row["tokens_estimate"],
                    "created_at": row["created_at"],
                }
            )
        return messages

    async def latest_runtime(self, user_id: int) -> dict[str, Any] | None:
        db = await connect()
        try:
            cursor = await db.execute(
                """
                SELECT messages.content, messages.runtime_json
                FROM messages
                JOIN agents ON agents.id = messages.agent_id
                WHERE role = 'assistant'
                  AND agents.user_id = ?
                ORDER BY messages.id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            runtime = json.loads(row["runtime_json"] or "{}")
            runtime["answer_preview"] = row["content"][:240]
            return runtime
        finally:
            await db.close()

    async def _get_agent(self, user_id: int, agent_id: int) -> dict[str, Any] | None:
        db = await connect()
        try:
            cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def _ensure_conversation(self, agent_id: int, agent_name: str) -> int:
        db = await connect()
        try:
            cursor = await db.execute(
                "SELECT id FROM conversations WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
                (agent_id,),
            )
            row = await cursor.fetchone()
            if row:
                return int(row["id"])

            now = utc_now()
            cursor = await db.execute(
                """
                INSERT INTO conversations (agent_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (agent_id, f"{agent_name} session", now, now),
            )
            await db.commit()
            return int(cursor.lastrowid)
        finally:
            await db.close()

    async def _save_message(
        self,
        conversation_id: int,
        agent_id: int,
        role: str,
        content: str,
        sources: list[dict[str, Any]],
        runtime: dict[str, Any],
        tokens_estimate: int,
    ) -> int:
        db = await connect()
        try:
            now = utc_now()
            cursor = await db.execute(
                """
                INSERT INTO messages (
                    conversation_id, agent_id, role, content, sources_json, runtime_json,
                    tokens_estimate, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    agent_id,
                    role,
                    content,
                    json.dumps(sources),
                    json.dumps(runtime),
                    tokens_estimate,
                    now,
                ),
            )
            msg_id = cursor.lastrowid
            await db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            await db.commit()
            return int(msg_id)
        finally:
            await db.close()

    def _fallback_answer(self, local_context: str, web_summary: str, message: str) -> str:
        sections = [
            "OrchestraAI runtime fallback summary",
            f"Question: {message}",
        ]
        if local_context:
            sections.append(f"Local knowledge:\n{local_context[:900]}")
        if web_summary:
            sections.append(f"Web findings:\n{web_summary[:700]}")
        sections.append("Sources: use the attached document and web references listed in the runtime trace.")
        return "\n\n".join(sections)

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def chat_external(self, user_id: int, agent_id: int, customer_id: str, session_id: str, message: str) -> dict[str, Any]:
        agent = await self._get_agent(user_id, agent_id)
        if not agent:
            raise ValueError("Agent not found or access denied.")
        conversation_id = await self._ensure_external_conversation(agent_id, agent["name"], customer_id, session_id)

        providers = await provider_service.get_active_providers(user_id)
        retrieved = await retrieval_service.retrieve(agent_id, message, top_k=5)
        top_score = retrieved[0]["score"] if retrieved else None
        needs_web = bool(agent["allow_web_search"]) and web_search_service.should_search(message, top_score)
        pages = await web_search_service.search_and_fetch(message) if needs_web else []
        web_summary = await web_search_service.summarize(message, pages, providers) if pages else ""

        local_context = "\n\n".join(
            f"[{item['filename']}] (score {item['score']}): {item['content']}" for item in retrieved
        )
        web_context = "\n\n".join(f"[{page['title']}] {page['url']}\n{page['content']}" for page in pages)

        graph = await graph_service.list_graph(agent_id)
        graph_context = ""
        if graph and graph.get("relationships"):
            graph_context = "\n".join([f"- {r['source_entity']} -> {r['relation']} -> {r['target_entity']}" for r in graph["relationships"]])

        summary, unsummarized_messages = await self._get_memory(conversation_id)
        history_text = "\n".join(f"{msg['role'].upper()}: {msg['content']}" for msg in unsummarized_messages)

        prompt = (
            f"Agent name: {agent['name']}\n"
            f"Agent system goal: {agent['system_prompt']}\n\n"
            "LOCAL KNOWLEDGE:\n"
            f"{local_context or 'No strong local knowledge matched the question.'}\n\n"
            "KNOWLEDGE GRAPH RELATIONSHIPS:\n"
            f"{graph_context or 'No graph relationships available.'}\n\n"
            "WEB CONTEXT:\n"
            f"{web_context or 'No external pages were needed.'}\n\n"
            "WEB SUMMARY:\n"
            f"{web_summary or 'No external summary available.'}\n\n"
            "CONVERSATION SUMMARY:\n"
            f"{summary or 'No previous summary.'}\n\n"
            "RECENT CONVERSATION HISTORY:\n"
            f"{history_text or 'No recent messages.'}\n\n"
            f"USER QUESTION:\n{message}\n\n"
            "Answer clearly, prefer uploaded knowledge first, and add a short Sources section."
        )

        selected_provider = provider_service.choose_provider(providers, "final_answer")
        runtime = {
            "query": message,
            "local_chunk_count": len(retrieved),
            "top_score": top_score,
            "used_web_search": bool(pages),
            "web_result_count": len(pages),
            "embedding_mode": "fallback-hash" if embedding_service.using_fallback else "sentence-transformers",
            "optimization_notes": [
                "Only top-ranked local chunks were packed into the prompt.",
                "Web search triggered only after freshness heuristics or low retrieval confidence.",
                "Knowledge graph injected into prompt.",
                "Conversation history was injected into prompt.",
            ],
        }

        provider_name = None
        model_name = None
        token_estimate = self._estimate_tokens(prompt)
        answer = ""

        if selected_provider:
            provider_name = selected_provider["provider_type"]
            try:
                result = await provider_service.generate(
                    selected_provider,
                    "You are OrchestraAI's runtime response engine. Ground answers in provided context and include sources.",
                    prompt,
                )
                answer = result.get("text", "").strip() or self._fallback_answer(local_context, web_summary, message)
                model_name = result.get("model")
                usage = result.get("usage") or {}
                token_estimate = int(usage.get("total_tokens") or usage.get("totalTokenCount") or token_estimate)
            except Exception as error:
                logger.error(f"Provider generation failed during chat: {error}", exc_info=True)
                answer = self._fallback_answer(local_context, web_summary, message)
                runtime["provider_error"] = str(error)
        else:
            answer = self._fallback_answer(local_context, web_summary, message)

        runtime["selected_provider"] = provider_name
        runtime["selected_model"] = model_name

        sources = [
            {"type": "document", "label": item["filename"], "score": item["score"]} for item in retrieved
        ] + [{"type": "web", "label": page["title"], "url": page["url"]} for page in pages]

        user_msg_id = await self._save_message(conversation_id, agent_id, "user", message, [], {}, self._estimate_tokens(message))
        asst_msg_id = await self._save_message(conversation_id, agent_id, "assistant", answer, sources, runtime, token_estimate)

        unsummarized_messages.append({"role": "user", "content": message, "id": user_msg_id})
        unsummarized_messages.append({"role": "assistant", "content": answer, "id": asst_msg_id})

        if len(unsummarized_messages) > 6:
            await self._summarize_conversation(conversation_id, summary, unsummarized_messages, providers)

        return {
            "answer": answer,
            "session_id": session_id,
            "customer_id": customer_id
        }

    async def _get_agent_by_id(self, agent_id: int) -> dict[str, Any] | None:
        db = await connect()
        try:
            cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def _ensure_external_conversation(self, agent_id: int, agent_name: str, customer_id: str, session_id: str) -> int:
        db = await connect()
        try:
            cursor = await db.execute(
                "SELECT id FROM conversations WHERE agent_id = ? AND customer_id = ? AND external_session_id = ? ORDER BY id DESC LIMIT 1",
                (agent_id, customer_id, session_id),
            )
            row = await cursor.fetchone()
            if row:
                return int(row["id"])

            now = utc_now()
            cursor = await db.execute(
                """
                INSERT INTO conversations (agent_id, title, customer_id, external_session_id, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (agent_id, f"{agent_name} external session", customer_id, session_id, "", now, now),
            )
            await db.commit()
            return int(cursor.lastrowid)
        finally:
            await db.close()

    async def _get_memory(self, conversation_id: int) -> tuple[str, list[dict[str, Any]]]:
        db = await connect()
        try:
            cursor = await db.execute("SELECT summary FROM conversations WHERE id = ?", (conversation_id,))
            row = await cursor.fetchone()
            summary = row["summary"] if row else ""

            cursor = await db.execute(
                "SELECT id, role, content FROM messages WHERE conversation_id = ? AND is_summarized = 0 ORDER BY id ASC",
                (conversation_id,)
            )
            messages = [dict(r) for r in await cursor.fetchall()]
            return summary, messages
        finally:
            await db.close()

    async def _summarize_conversation(self, conversation_id: int, old_summary: str, unsummarized_messages: list[dict[str, Any]], providers: list[dict[str, Any]]) -> None:
        provider = provider_service.choose_provider(providers, "final_answer")
        if not provider:
            return

        history_text = "\n".join(f"{msg['role'].upper()}: {msg['content']}" for msg in unsummarized_messages[:-2])
        prompt = (
            "Summarize the following conversation history. Combine it with the old summary into a single, cohesive new summary that captures the essence of the user's intent and the assistant's responses so far.\n\n"
            f"OLD SUMMARY:\n{old_summary or 'None'}\n\n"
            f"RECENT MESSAGES TO SUMMARIZE:\n{history_text}\n\n"
            "Respond only with the new summary."
        )

        try:
            result = await provider_service.generate(
                provider,
                "You are a helpful assistant that summarizes conversation history for memory optimization.",
                prompt,
            )
            new_summary = result.get("text", "").strip()
            if not new_summary:
                return

            msg_ids_to_mark = [msg["id"] for msg in unsummarized_messages[:-2] if msg.get("id")]

            db = await connect()
            try:
                await db.execute("UPDATE conversations SET summary = ?, updated_at = ? WHERE id = ?", (new_summary, utc_now(), conversation_id))
                if msg_ids_to_mark:
                    placeholders = ",".join("?" for _ in msg_ids_to_mark)
                    await db.execute(f"UPDATE messages SET is_summarized = 1 WHERE id IN ({placeholders})", tuple(msg_ids_to_mark))
                await db.commit()
            finally:
                await db.close()
        except Exception as error:
            logger.error(f"Failed to summarize conversation {conversation_id}: {error}", exc_info=True)


chat_service = ChatService()
