from __future__ import annotations

import json
import re
import logging
from collections import Counter
from typing import Any

from ..database import connect, utc_now
from .providers import provider_service

logger = logging.getLogger(__name__)


class GraphService:
    async def build_graph(self, user_id: int, agent_id: int, document_id: int, text: str) -> dict[str, Any]:
        entities, relationships = await self._extract_with_provider(user_id, text)
        if not entities:
            entities, relationships = self._fallback_graph(text)

        db = await connect()
        try:
            await db.execute("DELETE FROM entities WHERE document_id = ?", (document_id,))
            await db.execute("DELETE FROM relationships WHERE document_id = ?", (document_id,))
            now = utc_now()
            for entity in entities:
                await db.execute(
                    """
                    INSERT INTO entities (agent_id, document_id, name, entity_type, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        document_id,
                        entity["name"],
                        entity["type"],
                        json.dumps(entity.get("metadata", {})),
                        now,
                    ),
                )

            for relation in relationships:
                await db.execute(
                    """
                    INSERT INTO relationships (
                        agent_id, document_id, source_entity, target_entity, relation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        document_id,
                        relation["source"],
                        relation["target"],
                        relation["relation"],
                        json.dumps(relation.get("metadata", {})),
                        now,
                    ),
                )
            await db.commit()
        finally:
            await db.close()

        return {"entities": entities, "relationships": relationships}

    async def list_graph(self, agent_id: int) -> dict[str, Any]:
        db = await connect()
        try:
            entity_cursor = await db.execute(
                "SELECT name, entity_type FROM entities WHERE agent_id = ? ORDER BY id DESC LIMIT 24",
                (agent_id,),
            )
            relation_cursor = await db.execute(
                """
                SELECT source_entity, target_entity, relation
                FROM relationships
                WHERE agent_id = ?
                ORDER BY id DESC
                LIMIT 24
                """,
                (agent_id,),
            )
            entities = [dict(row) for row in await entity_cursor.fetchall()]
            relationships = [dict(row) for row in await relation_cursor.fetchall()]
            return {"entities": entities, "relationships": relationships}
        finally:
            await db.close()

    async def _extract_with_provider(self, user_id: int, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        providers = await provider_service.get_active_providers(user_id)
        provider = provider_service.choose_provider(providers, "graph")
        if not provider:
            return [], []

        prompt = (
            "Extract up to 10 important entities and up to 12 meaningful relationships from the text. "
            "Return JSON only with this shape: "
            '{"entities":[{"name":"", "type":""}], "relationships":[{"source":"", "target":"", "relation":""}]}. '
            "Prefer product, feature, company, person, topic, system, or document concepts. "
            "Do not include duplicate entities."
            "\n\nTEXT:\n"
            f"{text[:7000]}"
        )

        try:
            result = await provider_service.generate(
                provider,
                "You extract concise knowledge graphs from documents. Return only valid JSON.",
                prompt,
            )
        except Exception as e:
            logger.error(f"Graph extraction failed during provider generation: {e}", exc_info=True)
            return [], []

        payload = provider_service.parse_json_fragment(result.get("text", ""))
        if not payload:
            return [], []

        entities = []
        relationships = []
        seen_entities: set[str] = set()
        for entity in payload.get("entities", []):
            name = str(entity.get("name", "")).strip()
            if not name or name.lower() in seen_entities:
                continue
            seen_entities.add(name.lower())
            entities.append({"name": name, "type": str(entity.get("type", "concept")).strip() or "concept"})

        for relation in payload.get("relationships", []):
            source = str(relation.get("source", "")).strip()
            target = str(relation.get("target", "")).strip()
            label = str(relation.get("relation", "")).strip() or "related_to"
            if not source or not target or source == target:
                continue
            relationships.append({"source": source, "target": target, "relation": label})

        return entities[:10], relationships[:12]

    def _fallback_graph(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        candidates = re.findall(
            r"\b(?:[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+|[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,2}|[A-Z]{2,})\b",
            text,
        )
        keyword_candidates = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{6,}\b", text)
        counts = Counter(candidate.strip() for candidate in candidates if len(candidate.strip()) > 2)
        for keyword in keyword_candidates:
            if keyword.lower() not in {"through", "grounded", "context", "documents", "uploaded"}:
                counts[keyword] += 1
        entities = [{"name": name, "type": "concept"} for name, _ in counts.most_common(8)]
        relationships = []
        for first, second in zip(entities, entities[1:]):
            relationships.append(
                {"source": first["name"], "target": second["name"], "relation": "related_to"}
            )
        return entities, relationships


graph_service = GraphService()
