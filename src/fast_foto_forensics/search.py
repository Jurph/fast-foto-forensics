"""Normalized search providers for evidence enrichment.

Architecture
------------
Every provider implements the ``SearchProvider`` protocol: a single
``.search(query) -> list[SearchHit]`` method.  The pipeline hands each
provider the same query string and merges the returned hits.

Adding a new provider
~~~~~~~~~~~~~~~~~~~~~
1. Create a ``@dataclass(slots=True)`` class with a ``search`` method.
2. Normalize every result into a ``SearchHit`` (see ``models.py``).
3. Assign a unique ``provider`` tag (e.g. ``"ddgs"``, ``"searxng"``).
4. Register the choice in ``cli.py`` ``--search-provider``.

Parallel / multi-provider queries (future)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The protocol is deliberately stateless so that providers can be fanned out
concurrently.  A future ``CompositeSearchProvider`` could accept a list of
providers and dispatch queries via ``concurrent.futures`` or ``asyncio``,
deduplicating hits by URL before returning a merged list.  Each provider
already tags its hits with a ``provider`` field, so downstream code can
weight or filter by source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from fast_foto_forensics.models import SearchHit

logger = logging.getLogger(__name__)


class SearchProviderError(RuntimeError):
    """Raised when a live search provider fails predictably."""


class SearchProvider(Protocol):
    """Protocol for pluggable search providers.

    Every concrete provider must expose a synchronous ``.search()`` method.
    For parallel fan-out, wrap multiple providers in a dispatcher that calls
    each one in its own thread/task and merges the ``SearchHit`` lists.
    """

    def search(self, query: str) -> list[SearchHit]:
        """Return normalized hits for the given query."""


# ---------------------------------------------------------------------------
# Static / fixture provider — useful for tests and offline demos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StaticSearchProvider:
    """Fixture-backed search provider for tests and demos.

    Keyed by exact query string.  In a parallel pipeline this could serve
    as a fast "cache tier" that short-circuits before hitting live providers.
    """

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


# ---------------------------------------------------------------------------
# DuckDuckGo Instant Answer API — knowledge-graph only, no web results
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DuckDuckGoSearchProvider:
    """DuckDuckGo Instant Answer adapter.

    Hits the ``api.duckduckgo.com`` JSON endpoint.  Good for well-known
    entities (Wikipedia summaries, etc.) but returns *zero* results for
    niche hardware queries.  Kept for completeness; prefer ``DDGSSearchProvider``
    for real web search.

    In a parallel pipeline, this provider is fast (~200ms) and could run
    alongside slower web-scraping providers to provide instant partial results.
    """

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


# ---------------------------------------------------------------------------
# SearXNG — self-hosted metasearch engine with a JSON API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SearXNGSearchProvider:
    """Search via a SearXNG instance (local or remote).

    SearXNG is a self-hosted metasearch engine that aggregates results from
    dozens of upstream engines (Google, Bing, Brave, etc.) and exposes them
    through a clean JSON API.  No API key required, but you need a running
    instance.

    In a parallel pipeline this is the heaviest provider (~2-5s) but returns
    the richest results.  A ``CompositeSearchProvider`` should fire this off
    early and let faster providers return partial results while it completes.
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


# ---------------------------------------------------------------------------
# DDGS — real DuckDuckGo web search via HTML scraping (default provider)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DDGSSearchProvider:
    """Web search via the ``ddgs`` package (DuckDuckGo HTML scraping).

    Unlike ``DuckDuckGoSearchProvider`` (which hits the Instant Answer API and
    returns only knowledge-graph results), this provider scrapes actual web
    search results.  No API key, no Docker, no browser required.

    The ``ddgs`` package handles anti-bot countermeasures internally and is
    actively maintained.  It's the best default for "just give me web results."

    Install: ``pip install ddgs``  (or ``pip install fast-foto-forensics[search_ddgs]``)

    Parallel pipeline notes
    ~~~~~~~~~~~~~~~~~~~~~~~
    - Typical latency: 500ms-2s per query.
    - Stateless and thread-safe — safe to call from multiple threads.
    - Rate limits are per-session; for high-throughput fan-out, consider
      adding a short delay between concurrent queries or rotating proxies.
    - The ``proxy`` field accepts SOCKS5 URLs (e.g. ``socks5://...``) which
      can help distribute load across exit nodes.
    """

    max_results: int = 5
    proxy: str | None = None

    def search(self, query: str) -> list[SearchHit]:
        try:
            from ddgs import DDGS  # type: ignore[import-untyped]
        except ImportError as exc:
            raise SearchProviderError(
                "ddgs package not installed. Install with: pip install ddgs"
            ) from exc

        try:
            with DDGS(proxy=self.proxy) as ddgs:
                raw = list(ddgs.text(query, max_results=self.max_results))
        except Exception as exc:
            raise SearchProviderError(
                f"DDGS web search failed for query {query!r}: {exc}"
            ) from exc

        hits: list[SearchHit] = []
        for index, row in enumerate(raw):
            title = (row.get("title") or "").strip()
            snippet = (row.get("body") or "").strip()
            url = (row.get("href") or "").strip()
            if not url:
                continue
            hits.append(
                SearchHit(
                    hit_id=f"ddgs-{index:03d}",
                    provider="ddgs",
                    query=query,
                    title=title or query,
                    snippet=snippet,
                    url=url,
                )
            )
        return hits
