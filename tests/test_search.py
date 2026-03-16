"""Tests for normalized search providers."""

from __future__ import annotations

import json

import httpx
import pytest

from fast_foto_forensics.search import (
    DDGSSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProviderError,
    SearXNGSearchProvider,
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


def test_searxng_provider_normalizes_json_results() -> None:
    """SearXNG JSON responses should normalize into SearchHit objects."""

    def handler(_request: httpx.Request) -> httpx.Response:
        payload = {
            "results": [
                {
                    "title": "TP-Link OC200 Datasheet",
                    "content": "The OC200 is a cloud controller for Omada access points.",
                    "url": "https://example.com/oc200",
                },
                {
                    "title": "TP-Link OC200 Review",
                    "content": "A compact hardware controller.",
                    "url": "https://example.com/oc200-review",
                },
            ]
        }
        return httpx.Response(200, text=json.dumps(payload))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SearXNGSearchProvider(instance_url="http://fake-searxng:8888")

    import unittest.mock as mock

    with mock.patch("fast_foto_forensics.search.httpx.Client", return_value=client):
        hits = provider.search("TP-Link OC200 datasheet")

    assert len(hits) == 2
    assert hits[0].provider == "searxng"
    assert hits[0].title == "TP-Link OC200 Datasheet"
    assert hits[0].url == "https://example.com/oc200"
    assert hits[1].snippet == "A compact hardware controller."


def test_ddgs_provider_normalizes_results() -> None:
    """DDGS web search results should normalize into SearchHit objects."""
    import unittest.mock as mock

    fake_results = [
        {
            "title": "OC200 | Omada Hardware Controller | TP-Link",
            "body": "Industry-leading hardware design with a powerful chipset.",
            "href": "https://www.tp-link.com/us/business-networking/oc200/",
        },
        {
            "title": "TP-Link OC200 Review",
            "body": "A compact hardware controller for Omada access points.",
            "href": "https://example.com/oc200-review",
        },
    ]

    mock_ddgs_instance = mock.MagicMock()
    mock_ddgs_instance.__enter__ = mock.Mock(return_value=mock_ddgs_instance)
    mock_ddgs_instance.__exit__ = mock.Mock(return_value=False)
    mock_ddgs_instance.text.return_value = fake_results

    # Test directly by mocking the ddgs import
    provider = DDGSSearchProvider(max_results=5)
    with mock.patch.dict("sys.modules", {"ddgs": mock.MagicMock()}):
        import sys

        mock_ddgs_module = sys.modules["ddgs"]
        mock_ddgs_module.DDGS.return_value = mock_ddgs_instance

        hits = provider.search("TP-Link OC200 datasheet")

    assert len(hits) == 2
    assert hits[0].provider == "ddgs"
    assert hits[0].title == "OC200 | Omada Hardware Controller | TP-Link"
    assert hits[0].url == "https://www.tp-link.com/us/business-networking/oc200/"
    assert hits[1].snippet == "A compact hardware controller for Omada access points."


def test_ddgs_provider_raises_on_missing_package() -> None:
    """DDGS should raise SearchProviderError when ddgs is not installed."""
    import unittest.mock as mock

    provider = DDGSSearchProvider()
    with mock.patch.dict("sys.modules", {"ddgs": None}):
        with pytest.raises(SearchProviderError, match="ddgs"):
            provider.search("test query")


def test_searxng_provider_raises_on_connection_error() -> None:
    """SearXNG should raise SearchProviderError when the instance is unreachable."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    import unittest.mock as mock

    provider = SearXNGSearchProvider(instance_url="http://fake-searxng:8888")
    with mock.patch("fast_foto_forensics.search.httpx.Client", return_value=client):
        with pytest.raises(SearchProviderError, match="SearXNG"):
            provider.search("test query")
