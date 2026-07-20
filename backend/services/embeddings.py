from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
try:
    import faiss
except Exception:  # pragma: no cover - optional runtime dependency
    faiss = None

from ..config import EMBEDDING_DIMENSION, EMBEDDING_MODEL, VECTOR_DIR

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - handled by runtime fallback
    SentenceTransformer = None


class EmbeddingService:
    def __init__(self) -> None:
        self._model = None
        self._using_fallback = False

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback

    def _load_model(self) -> None:
        if self._model is not None or self._using_fallback:
            return

        if SentenceTransformer is None:
            self._using_fallback = True
            return

        try:
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        except Exception:
            self._using_fallback = True

    def embed_texts(self, texts: Iterable[str]) -> np.ndarray:
        items = [text.strip() for text in texts if text and text.strip()]
        if not items:
            return np.zeros((0, EMBEDDING_DIMENSION), dtype=np.float32)

        self._load_model()
        if self._model is not None:
            vectors = self._model.encode(items, convert_to_numpy=True, normalize_embeddings=True)
            return np.asarray(vectors, dtype=np.float32)

        return self._fallback_embed(items)

    def _fallback_embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), EMBEDDING_DIMENSION), dtype=np.float32)
        for row_index, text in enumerate(texts):
            tokens = [token for token in text.lower().split() if token]
            if not tokens:
                continue

            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                for offset in range(0, len(digest), 2):
                    bucket = int.from_bytes(digest[offset : offset + 2], "little") % EMBEDDING_DIMENSION
                    vectors[row_index, bucket] += 1.0

            norm = np.linalg.norm(vectors[row_index])
            if norm:
                vectors[row_index] /= norm

        self._using_fallback = True
        return vectors


class FaissStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _index_path(self, agent_id: int) -> Path:
        return self.base_dir / f"agent_{agent_id}.index"

    def _meta_path(self, agent_id: int) -> Path:
        return self.base_dir / f"agent_{agent_id}.json"

    def _matrix_path(self, agent_id: int) -> Path:
        return self.base_dir / f"agent_{agent_id}.npy"

    @property
    def faiss_ready(self) -> bool:
        return faiss is not None and hasattr(faiss, "IndexFlatIP") and hasattr(faiss, "write_index")

    def _create_index(self, dimension: int):
        if not self.faiss_ready:
            raise RuntimeError("FAISS backend is unavailable in this environment.")
        return faiss.IndexFlatIP(dimension)

    def _load_index(self, agent_id: int, dimension: int):
        index_path = self._index_path(agent_id)
        if index_path.exists():
            return faiss.read_index(str(index_path))
        return self._create_index(dimension)

    def _load_meta(self, agent_id: int) -> dict:
        meta_path = self._meta_path(agent_id)
        if not meta_path.exists():
            return {"dimension": EMBEDDING_DIMENSION, "chunk_ids": []}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def add(self, agent_id: int, chunk_ids: list[int], embeddings: np.ndarray) -> None:
        if embeddings.size == 0 or not chunk_ids:
            return

        dimension = embeddings.shape[1]
        meta = self._load_meta(agent_id)
        meta["dimension"] = dimension
        meta.setdefault("chunk_ids", [])
        meta["chunk_ids"].extend(chunk_ids)
        if self.faiss_ready:
            index = self._load_index(agent_id, dimension)
            index.add(embeddings.astype(np.float32))
            faiss.write_index(index, str(self._index_path(agent_id)))
        else:
            matrix_path = self._matrix_path(agent_id)
            if matrix_path.exists():
                existing = np.load(matrix_path)
                combined = np.vstack([existing, embeddings.astype(np.float32)])
            else:
                combined = embeddings.astype(np.float32)
            np.save(matrix_path, combined)
        self._meta_path(agent_id).write_text(json.dumps(meta), encoding="utf-8")

    def search(self, agent_id: int, query_embedding: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
        meta = self._load_meta(agent_id)
        chunk_ids: list[int] = meta.get("chunk_ids", [])
        if not chunk_ids:
            return []

        if self.faiss_ready:
            index_path = self._index_path(agent_id)
            if not index_path.exists():
                return []

            index = faiss.read_index(str(index_path))
            if index.ntotal == 0:
                return []

            scores, ids = index.search(query_embedding.astype(np.float32), top_k)
            matches: list[tuple[int, float]] = []
            for vector_position, score in zip(ids[0], scores[0]):
                if int(vector_position) == -1:
                    continue
                if vector_position >= len(chunk_ids):
                    continue
                matches.append((int(chunk_ids[vector_position]), float(score)))
            return matches

        matrix_path = self._matrix_path(agent_id)
        if not matrix_path.exists():
            return []

        matrix = np.load(matrix_path)
        if matrix.size == 0:
            return []

        scores = np.dot(matrix, query_embedding[0])
        order = np.argsort(scores)[::-1][:top_k]
        matches = []
        for position in order:
            if position >= len(chunk_ids):
                continue
            matches.append((int(chunk_ids[position]), float(scores[position])))
        return matches


embedding_service = EmbeddingService()
faiss_store = FaissStore(VECTOR_DIR)
