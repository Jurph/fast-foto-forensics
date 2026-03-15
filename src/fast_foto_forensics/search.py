"""Normalized search providers for evidence enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from fast_foto_forensics.models import SearchHit


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

    def search(self, query: str) -> list[SearchHit]:
        client = self._client()
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

        for index, topic in enumerate(payload.get("RelatedTopics", []), start=1):
            if isinstance(topic, dict) and "Text" in topic and "FirstURL" in topic:
                hits.append(
                    SearchHit(
                        hit_id=f"duckduckgo-{index:03d}",
                        provider="duckduckgo",
                        query=query,
                        title=query,
                        snippet=topic["Text"].strip(),
                        url=topic["FirstURL"].strip(),
                    )
                )
        return hits
