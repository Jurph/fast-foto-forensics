"""Tests for normalized search providers."""

from __future__ import annotations

import json

import httpx
import pytest

from fast_foto_forensics.search import (
    DuckDuckGoSearchProvider,
    SearchProviderError,
    StaticSearchProvider,
)


def test_static_search_provider_normalizes_hits() -> None:
    """Static fixtures should come back as normalized search hits."""
    provider = StaticSearchProvider(
        fixtures={
            "WRT54G release date": [
                {
                    "title": "Linksys WRT54G specifications",
                    "snippet": "The WRT54G launched in the early 2000s.",
                    "url": "https://example.com/wrt54g",
                }
            ]
        }
    )

    hits = provider.search("WRT54G release date")

    assert hits[0].provider == "static"
    assert hits[0].query == "WRT54G release date"
    assert hits[0].title == "Linksys WRT54G specifications"


def test_duckduckgo_provider_uses_transport_and_normalizes_results() -> None:
    """The live provider should normalize Instant Answer payloads through an injectable client."""
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        payload = {
            "AbstractText": "The Linksys WRT54G is a wireless router series.",
            "AbstractURL": "https://duckduckgo.com/WRT54G",
            "RelatedTopics": [
                {
                    "Text": "WRT54G hardware revisions and model history",
                    "FirstURL": "https://duckduckgo.com/WRT54G_history",
                }
            ],
        }
        return httpx.Response(200, text=json.dumps(payload))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DuckDuckGoSearchProvider(client=client)

    hits = provider.search("WRT54G release date")

    assert "api.duckduckgo.com" in seen_urls[0]
    assert hits[0].provider == "duckduckgo"
    assert hits[0].title == "WRT54G release date"
    assert hits[1].snippet == "WRT54G hardware revisions and model history"


def test_duckduckgo_provider_flattens_nested_topics_and_skips_blank_rows() -> None:
    """Nested topic payloads should be flattened into normalized hits while ignoring junk."""

    def handler(_request: httpx.Request) -> httpx.Response:
        payload = {
            "AbstractText": "",
            "AbstractURL": "",
            "RelatedTopics": [
                {"Name": "ignored group header only"},
                {
                    "Name": "Hardware revisions",
                    "Topics": [
                        {
                            "Text": "WRT54G hardware revisions and board history",
                            "FirstURL": "https://duckduckgo.com/WRT54G_history",
                        },
                        {
                            "Text": "   ",
                            "FirstURL": "https://duckduckgo.com/blank_text",
                        },
                    ],
                },
                {
                    "Text": "OpenWrt support matrix for WRT54G",
                    "FirstURL": "https://duckduckgo.com/OpenWrt_WRT54G",
                },
                "not-a-dict",
            ],
        }
        return httpx.Response(200, text=json.dumps(payload))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DuckDuckGoSearchProvider(client=client)

    hits = provider.search("WRT54G firmware")

    assert len(hits) == 2
    assert hits[0].url == "https://duckduckgo.com/WRT54G_history"
    assert hits[1].snippet == "OpenWrt support matrix for WRT54G"


def test_duckduckgo_provider_raises_clear_error_on_invalid_json() -> None:
    """Invalid provider payloads should raise a predictable provider error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json-at-all")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DuckDuckGoSearchProvider(client=client)

    with pytest.raises(SearchProviderError, match="duckduckgo"):
        provider.search("WRT54G release date")
