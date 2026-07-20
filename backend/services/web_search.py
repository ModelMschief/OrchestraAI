from __future__ import annotations

from html import unescape
from urllib.parse import parse_qs, urlparse
import logging

import httpx
from bs4 import BeautifulSoup

from .providers import provider_service

logger = logging.getLogger(__name__)


class WebSearchService:
    def should_search(self, query: str, top_score: float | None) -> bool:
        freshness_terms = ("latest", "today", "current", "recent", "news", "updated", "price", "competitor")
        if any(term in query.lower() for term in freshness_terms):
            return True
        return top_score is None or top_score < 0.34

    async def search_and_fetch(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        search_url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": "Mozilla/5.0 OrchestraAI/1.0"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(search_url, params={"q": query}, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            links: list[tuple[str, str]] = []
            for anchor in soup.select("a.result__a"):
                href = anchor.get("href", "")
                title = anchor.get_text(" ", strip=True)
                resolved = self._resolve_duckduckgo_link(href)
                if resolved and resolved.startswith("http"):
                    links.append((title, resolved))
                if len(links) >= max_results:
                    break

            pages: list[dict[str, str]] = []
            for title, url in links:
                try:
                    page = await client.get(url, headers=headers)
                    page.raise_for_status()
                    text = self._clean_page(page.text)
                    pages.append({"title": title, "url": url, "content": text[:2400]})
                except Exception:
                    continue
            return pages

    async def summarize(self, query: str, pages: list[dict[str, str]], providers: list[dict[str, str]]) -> str:
        if not pages:
            return ""

        provider = provider_service.choose_provider(providers, "web_summary")
        joined = "\n\n".join(
            f"TITLE: {page['title']}\nURL: {page['url']}\nCONTENT: {page['content']}" for page in pages
        )

        if provider:
            try:
                result = await provider_service.generate(
                    provider,
                    "Summarize web findings for an AI agent. Keep it concise and grounded in the supplied pages.",
                    f"Question: {query}\n\nPages:\n{joined}\n\nReturn a short synthesis with inline source mentions.",
                )
                if result.get("text"):
                    return result["text"]
            except Exception as e:
                logger.error(f"Web summary generation failed: {e}", exc_info=True)

        bullets = [f"- {page['title']}: {page['content'][:220]}..." for page in pages]
        return "\n".join(bullets)

    def _resolve_duckduckgo_link(self, href: str) -> str:
        if "uddg=" in href:
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            return unescape(query.get("uddg", [""])[0])
        return href

    def _clean_page(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        paragraphs = [node.get_text(" ", strip=True) for node in soup.select("p")[:12]]
        combined = " ".join(part for part in ([title] + paragraphs) if part)
        return " ".join(combined.split())


web_search_service = WebSearchService()

