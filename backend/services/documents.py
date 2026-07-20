from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from pypdf import PdfReader

from ..config import UPLOAD_DIR
from ..database import connect, utc_now
from .embeddings import embedding_service, faiss_store
from .graph import graph_service


class DocumentService:
    async def upload_document(self, user_id: int, agent_id: int, filename: str, content: bytes) -> dict[str, Any]:
        await self._assert_agent_access(user_id, agent_id)
        safe_name = self._safe_filename(filename)
        file_type = Path(safe_name).suffix.lower().lstrip(".") or "txt"
        stored_dir = UPLOAD_DIR / f"user_{user_id}" / f"agent_{agent_id}"
        stored_dir.mkdir(parents=True, exist_ok=True)
        stored_path = stored_dir / safe_name
        stored_path.write_bytes(content)

        now = utc_now()
        db = await connect()
        try:
            cursor = await db.execute(
                """
                INSERT INTO documents (
                    agent_id, filename, file_type, status, stored_path, raw_text, summary,
                    chunk_count, entity_count, relationship_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '', '', 0, 0, 0, ?, ?)
                """,
                (agent_id, safe_name, file_type, "processing", str(stored_path), now, now),
            )
            document_id = cursor.lastrowid
            await db.commit()
        finally:
            await db.close()

        try:
            raw_text = self._extract_text(stored_path)
            cleaned = self._clean_text(raw_text)
            chunks = self._chunk_text(cleaned)
            embeddings = embedding_service.embed_texts(chunks)

            db = await connect()
            try:
                chunk_ids: list[int] = []
                for position, chunk in enumerate(chunks):
                    cursor = await db.execute(
                        """
                        INSERT INTO chunks (
                            document_id, agent_id, position, content, token_estimate, metadata_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            agent_id,
                            position,
                            chunk,
                            self._estimate_tokens(chunk),
                            json.dumps({"length": len(chunk)}),
                            now,
                        ),
                    )
                    chunk_ids.append(cursor.lastrowid)

                await db.commit()
            finally:
                await db.close()

            faiss_store.add(agent_id, chunk_ids, embeddings)
            graph = await graph_service.build_graph(user_id, agent_id, document_id, cleaned)

            summary = chunks[0][:260] + ("..." if chunks and len(chunks[0]) > 260 else "")
            db = await connect()
            try:
                await db.execute(
                    """
                    UPDATE documents
                    SET status = ?, raw_text = ?, summary = ?, chunk_count = ?, entity_count = ?,
                        relationship_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "ready",
                        cleaned,
                        summary,
                        len(chunks),
                        len(graph["entities"]),
                        len(graph["relationships"]),
                        utc_now(),
                        document_id,
                    ),
                )
                await db.commit()
            finally:
                await db.close()
        except Exception:
            db = await connect()
            try:
                await db.execute(
                    "UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
                    ("failed", utc_now(), document_id),
                )
                await db.commit()
            finally:
                await db.close()
            raise

        return {
            "id": document_id,
            "filename": safe_name,
            "status": "ready",
            "summary": summary,
            "chunk_count": len(chunks),
            "entity_count": len(graph["entities"]),
            "relationship_count": len(graph["relationships"]),
        }

    async def list_documents(self, user_id: int, agent_id: int) -> list[dict[str, Any]]:
        await self._assert_agent_access(user_id, agent_id)
        db = await connect()
        try:
            cursor = await db.execute(
                """
                SELECT id, filename, file_type, status, summary, chunk_count, entity_count,
                       relationship_count, created_at
                FROM documents
                WHERE agent_id = ?
                ORDER BY created_at DESC
                """,
                (agent_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

    async def delete_document(self, user_id: int, agent_id: int, document_id: int) -> None:
        await self._assert_agent_access(user_id, agent_id)
        db = await connect()
        try:
            cursor = await db.execute("SELECT stored_path FROM documents WHERE id = ? AND agent_id = ?", (document_id, agent_id))
            row = await cursor.fetchone()
            if not row:
                raise ValueError("Document not found.")
            
            path = Path(row["stored_path"])
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
            
            await db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            await db.commit()
        finally:
            await db.close()

    def _extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            document = DocxDocument(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        return path.read_text(encoding="utf-8", errors="ignore")

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned or "Document was uploaded but no readable text was extracted."

    def _chunk_text(self, text: str, size: int = 850, overlap: int = 140) -> list[str]:
        if len(text) <= size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            window = text[start:end]
            if end < len(text):
                split_at = max(window.rfind(". "), window.rfind(" "))
                if split_at > size * 0.55:
                    end = start + split_at + 1
                    window = text[start:end]
            chunks.append(window.strip())
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _safe_filename(self, filename: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "upload.txt"

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def _assert_agent_access(self, user_id: int, agent_id: int) -> None:
        db = await connect()
        try:
            cursor = await db.execute("SELECT id FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))
            row = await cursor.fetchone()
            if not row:
                raise ValueError("Agent not found for this user.")
        finally:
            await db.close()


document_service = DocumentService()
