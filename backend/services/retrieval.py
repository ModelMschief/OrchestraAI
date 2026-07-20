from __future__ import annotations

from typing import Any

from ..database import connect
from .embeddings import embedding_service, faiss_store


class RetrievalService:
    async def retrieve(self, agent_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        embeddings = embedding_service.embed_texts([query])
        if embeddings.size == 0:
            return []

        matches = faiss_store.search(agent_id, embeddings, top_k=top_k)
        if not matches:
            return []

        ids = [chunk_id for chunk_id, _ in matches]
        placeholders = ",".join(["?"] * len(ids))
        db = await connect()
        try:
            cursor = await db.execute(
                f"""
                SELECT
                    chunks.id,
                    chunks.content,
                    chunks.token_estimate,
                    documents.filename
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE chunks.id IN ({placeholders})
                """,
                ids,
            )
            rows = {row["id"]: dict(row) for row in await cursor.fetchall()}
        finally:
            await db.close()

        results: list[dict[str, Any]] = []
        for chunk_id, score in matches:
            row = rows.get(chunk_id)
            if not row:
                continue
            row["score"] = round(score, 4)
            results.append(row)
        return results


retrieval_service = RetrievalService()

