import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from properties.meta_client import (
    MetaAPIError,
    MetaClient,
    MetaMediaPending,
    MetaPage,
    _NoRedirectHandler,
)


class FakeResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size=-1):
        return self.raw


def test_authorization_url_requests_least_scopes():
    client = MetaClient("app", "secret")
    parsed = urlparse(client.authorization_url("nonce", "https://example.test/callback"))
    params = parse_qs(parsed.query)
    assert set(params["scope"][0].split(",")) == set(client.SCOPES)
    assert params["state"] == ["nonce"]
    assert "business_management" not in params["scope"][0]


def test_exchange_sends_secret_in_post_body(monkeypatch):
    seen = []

    def fake_open(request, timeout):
        seen.append((request, timeout))
        return FakeResponse({"access_token": "short"})

    monkeypatch.setattr("properties.meta_client._open_request", fake_open)
    result = MetaClient("app", "secret").exchange_code("code", "https://example.test/cb")
    request, timeout = seen[0]
    assert result["access_token"] == "short"
    assert request.method == "POST"
    assert b"secret" not in request.full_url.encode()
    assert timeout == MetaClient.TIMEOUT


def test_list_pages_discovers_linked_instagram_account(monkeypatch):
    monkeypatch.setattr(
        "properties.meta_client._open_request",
        lambda *_a, **_k: FakeResponse(
            {
                "data": [
                    {
                        "id": "1",
                        "name": "Page",
                        "access_token": "page-token",
                        "instagram_business_account": {"id": "2", "username": "handle"},
                    },
                ]
            }
        ),
    )
    assert MetaClient("a", "s").list_pages("user-token") == [
        MetaPage("1", "Page", "page-token", "2", "handle")
    ]


def test_page_access_token_is_not_in_repr():
    assert "hidden" not in repr(MetaPage("1", "Page", "hidden"))


def test_pagination_uses_only_validated_cursor_and_bearer_header(monkeypatch):
    requests = []
    responses = [
        {
            "data": [],
            "paging": {
                "next": "https://graph.facebook.com/v27.0/me/accounts?access_token=leak&after=abc_123"
            },
        },
        {"data": [{"id": "2", "name": "Page", "access_token": "page-token"}]},
    ]

    def fake_open(request, *_args, **_kwargs):
        requests.append(request)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("properties.meta_client._open_request", fake_open)
    assert len(MetaClient("a", "s").list_pages("user-token")) == 1
    assert "leak" not in requests[1].full_url
    assert "after=abc_123" in requests[1].full_url
    assert requests[1].get_header("Authorization") == "Bearer user-token"


def test_page_pagination_rejects_untrusted_url(monkeypatch):
    monkeypatch.setattr(
        "properties.meta_client._open_request",
        lambda *_a, **_k: FakeResponse(
            {"data": [], "paging": {"next": "https://evil.test/?access_token=secret"}}
        ),
    )
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").list_pages("secret")
    assert exc.value.code == "malformed_response"
    assert "secret" not in str(exc.value)


def test_facebook_photo_publish_uses_bearer_and_returns_id(monkeypatch):
    seen = []

    def fake_open(request, *_args, **_kwargs):
        seen.append(request)
        return FakeResponse({"id": "post1"})

    monkeypatch.setattr("properties.meta_client._open_request", fake_open)
    assert (
        MetaClient("a", "s").publish_facebook_photo(
            "1", "page-secret", "https://img.test/a.jpg", "caption"
        )
        == "post1"
    )
    assert seen[0].get_header("Authorization") == "Bearer page-secret"
    assert "page-secret" not in seen[0].full_url


def test_facebook_photo_prefers_post_id(monkeypatch):
    monkeypatch.setattr(
        "properties.meta_client._open_request",
        lambda *_a, **_k: FakeResponse({"id": "photo1", "post_id": "page1_post1"}),
    )
    assert (
        MetaClient("a", "s").publish_facebook_photo(
            "1", "token", "https://img.test/a.jpg", "caption"
        )
        == "page1_post1"
    )


def test_instagram_photo_waits_for_finished_before_publish(monkeypatch):
    calls = []
    responses = [
        {"id": "123"},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "FINISHED"},
        {"id": "456"},
    ]

    def fake_open(request, *_args, **_kwargs):
        calls.append(request.full_url)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("properties.meta_client._open_request", fake_open)
    monkeypatch.setattr("properties.meta_client.time.sleep", lambda _delay: None)
    assert (
        MetaClient("a", "s").publish_instagram_photo(
            "2", "token", "https://img.test/a.jpg", "caption"
        )
        == "456"
    )
    assert calls[0].endswith("/2/media")
    assert calls[1].endswith("/123?fields=status_code")
    assert calls[2].endswith("/123?fields=status_code")
    assert calls[3].endswith("/2/media_publish")


def test_instagram_pending_media_is_not_published(monkeypatch):
    responses = [{"id": "123"}, *([{"status_code": "IN_PROGRESS"}] * 3)]
    monkeypatch.setattr(
        "properties.meta_client._open_request", lambda *_a, **_k: FakeResponse(responses.pop(0))
    )
    monkeypatch.setattr("properties.meta_client.time.sleep", lambda _delay: None)
    with pytest.raises(MetaMediaPending) as exc:
        MetaClient("a", "s").publish_instagram_photo(
            "2", "secret", "https://img.test/a.jpg", "caption"
        )
    assert exc.value.container_id == "123"
    assert "secret" not in str(exc.value)


def test_instagram_pending_container_resumes_without_creating_a_second(monkeypatch):
    urls = []
    responses = [
        {"id": "321"},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "FINISHED"},
        {"id": "654"},
    ]

    def fake_open(request, timeout):
        urls.append((request.full_url, timeout))
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("properties.meta_client._open_request", fake_open)
    monkeypatch.setattr("properties.meta_client.time.sleep", lambda _delay: None)
    client = MetaClient("a", "s")
    with pytest.raises(MetaMediaPending) as exc:
        client.publish_instagram_photo("2", "token", "https://img.test/a.jpg", "caption")
    assert exc.value.container_id == "321"
    assert (
        client.publish_instagram_photo(
            "2", "token", "https://img.test/a.jpg", "caption", container_id=exc.value.container_id
        )
        == "654"
    )
    assert sum(url.endswith("/2/media") for url, _ in urls) == 1
    assert sum(url.endswith("/2/media_publish") for url, _ in urls) == 1
    assert all(timeout == MetaClient.INSTAGRAM_TIMEOUT for _, timeout in urls)


def test_publish_rejects_non_numeric_target_ids(monkeypatch):
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").publish_facebook_photo(
            "bad/id", "token", "https://img.test/a.jpg", "caption"
        )
    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "payload", [[], {"error": {"message": "secret leaked", "code": 190}}, {"id": None}]
)
def test_malformed_or_api_errors_are_safe(monkeypatch, payload):
    monkeypatch.setattr(
        "properties.meta_client._open_request", lambda *_a, **_k: FakeResponse(payload)
    )
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").publish_facebook_photo("p", "secret", "https://img.test/a.jpg", "x")
    assert "secret" not in str(exc.value)
    assert "leaked" not in str(exc.value)


def test_facebook_photo_rejects_oversized_external_id(monkeypatch):
    monkeypatch.setattr(
        "properties.meta_client._open_request",
        lambda *_a, **_k: FakeResponse({"id": "x" * 101}),
    )
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").publish_facebook_photo(
            "1", "token", "https://img.test/a.jpg", "caption"
        )
    assert exc.value.code == "malformed_response"


def test_http_error_retains_only_sanitized_meta_code(monkeypatch):
    body = b'{"error":{"code":190,"message":"token secret was revoked"}}'

    def fail_request(request, _timeout):
        raise HTTPError(request.full_url, 400, "bad request", {}, BytesIO(body))

    monkeypatch.setattr("properties.meta_client._open_request", fail_request)
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").publish_facebook_photo(
            "1", "secret", "https://img.test/a.jpg", "caption"
        )
    assert exc.value.code == "meta_190"
    assert "secret" not in str(exc.value)
    assert "revoked" not in str(exc.value)


def test_redirects_are_refused():
    handler = _NoRedirectHandler()
    request = Request("https://graph.facebook.com/v27.0/me/accounts")
    assert (
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.test/collect")
        is None
    )


def test_redirect_http_error_has_safe_code(monkeypatch):
    def redirect(request, _timeout):
        raise HTTPError(
            request.full_url,
            302,
            "Found",
            {"Location": "https://evil.test/collect"},
            BytesIO(b"bearer secret"),
        )

    monkeypatch.setattr("properties.meta_client._open_request", redirect)
    with pytest.raises(MetaAPIError) as exc:
        MetaClient("a", "s").list_pages("secret")
    assert exc.value.code == "redirect_blocked"
    assert "secret" not in str(exc.value)
