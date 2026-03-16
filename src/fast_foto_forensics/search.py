"""Normalized search providers for evidence enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from fast_foto_forensics.models import SearchHit


class SearchProviderError(RuntimeError):
    """Raised when a live search provider fails predictably."""


class SearchProvider(Protocol):
    """Protocol for pluggable search providers."""

    def search(self, query: str) -> list[SearchHit]:
        """Return normalized hits for the given query."""


@dataclass(slots=True)
class StaticSearchProvider:
    """Fixture-backed search provider for tests and demos."""

    fixtures: dict[str, list[dict[str, str]]]

    def search(self, query: str) -> list[SearchHit]:
        rows = self.fixtures.get(query, [])
        return [
            SearchHit(
                hit_id=f"static-{index:03d}",
                provider="static",
                query=query,
                title=row["title"],
                snippet=row["snippet"],
                url=row["url"],
            )
            for index, row in enumerate(rows)
        ]


@dataclass(slots=True)
class DuckDuckGoSearchProvider:
    """DuckDuckGo Instant Answer adapter."""

    client: httpx.Client | None = None
    proxy_url: str | None = None

    def _client(self) -> httpx.Client:
        if self.client is not None:
            return self.client
        return httpx.Client(proxy=self.proxy_url, timeout=10.0)

    def _related_topic_rows(self, rows: list[Any]) -> list[dict[str, str]]:
        """Flatten nested DuckDuckGo topic rows into simple text/url pairs."""
        flattened: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = row.get("Text")
            url = row.get("FirstURL")
            if isinstance(text, str) and isinstance(url, str):
                flattened.append({"Text": text, "FirstURL": url})
                continue
            topics = row.get("Topics")
            if isinstance(topics, list):
                flattened.extend(self._related_topic_rows(topics))
        return flattened

    def _topic_hit(
        self,
        query: str,
        index: int,
        topic_text: str,
        topic_url: str,
    ) -> SearchHit | None:
        """Build a normalized hit from one topic row, skipping unusable rows."""
        snippet = topic_text.strip()
        url = topic_url.strip()
        if not snippet or not url:
            return None
        return SearchHit(
            hit_id=f"duckduckgo-{index:03d}",
            provider="duckduckgo",
            query=query,
            title=query,
            snippet=snippet,
            url=url,
        )

    def search(self, query: str) -> list[SearchHit]:
        client = self._client()
        try:
            response = client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError(
                f"duckduckgo search failed for query {query!r}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SearchProviderError(
                f"duckduckgo search failed for query {query!r}: payload was not an object"
            )

        hits: list[SearchHit] = []
        abstract_text = payload.get("AbstractText", "").strip()
        abstract_url = payload.get("AbstractURL", "").strip()
        if abstract_text and abstract_url:
            hits.append(
                SearchHit(
                    hit_id="duckduckgo-000",
                    provider="duckduckgo",
                    query=query,
                    title=query,
                    snippet=abstract_text,
                    url=abstract_url,
                )
            )

        related_topics = payload.get("RelatedTopics", [])
        if not isinstance(related_topics, list):
            related_topics = []
        start_index = len(hits)
        for offset, topic in enumerate(self._related_topic_rows(related_topics), start=1):
            hit = self._topic_hit(
                query=query,
                index=start_index + offset,
                topic_text=topic["Text"],
                topic_url=topic["FirstURL"],
            )
            if hit is not None:
                hits.append(hit)
        return hits


@dataclass(slots=True)
class SearXNGSearchProvider:
    """Search via a SearXNG instance (local or remote).

    SearXNG is a self-hosted metasearch engine with a JSON API.
    Run locally: docker run -p 8888:8888 searxng/searxng
    No API key required.
    """

    instance_url: str = "http://localhost:8888"
    proxy_url: str | None = None
    max_results: int = 5

    def search(self, query: str) -> list[SearchHit]:
        client = httpx.Client(proxy=self.proxy_url, timeout=15.0, follow_redirects=True)
        try:
            response = client.get(
                f"{self.instance_url.rstrip('/')}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError(
                f"SearXNG search failed for query {query!r}: {exc}"
            ) from exc

        hits: list[SearchHit] = []
        for index, result in enumerate(payload.get("results", [])[: self.max_results]):
            title = result.get("title", "").strip()
            snippet = result.get("content", "").strip()
            url = result.get("url", "").strip()
            if not url:
                continue
            hits.append(
                SearchHit(
                    hit_id=f"searxng-{index:03d}",
                    provider="searxng",
                    query=query,
                    title=title or query,
                    snippet=snippet,
                    url=url,
                )
            )
        return hits


