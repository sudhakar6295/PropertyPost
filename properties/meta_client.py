"""Small, bounded client for the Meta Graph API."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class MetaAPIError(Exception):
    """Safe API failure exposing only a stable error code."""

    def __init__(self, code: str = "meta_api_error") -> None:
        self.code = code if re.fullmatch(r"[a-z0-9_]{1,50}", code or "") else "meta_api_error"
        super().__init__(self.code)


class MetaMediaPending(Exception):
    """Instagram media container is still processing and can be safely resumed."""

    def __init__(self, container_id: str):
        if not isinstance(container_id, str) or not re.fullmatch(r"\d{1,100}", container_id):
            raise ValueError("Invalid Instagram container ID")
        self.container_id = container_id
        super().__init__("media_pending")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_request(request: Request, timeout: int):
    return build_opener(_NoRedirectHandler).open(request, timeout=timeout)


@dataclass(frozen=True)
class MetaPage:
    page_id: str
    page_name: str
    access_token: str = field(repr=False)
    instagram_account_id: str | None = None
    instagram_username: str | None = None


class MetaClient:
    AUTH_BASE = "https://www.facebook.com/"
    GRAPH_BASE = "https://graph.facebook.com/"
    TIMEOUT = 10
    INSTAGRAM_TIMEOUT = 5
    MAX_RESPONSE_BYTES = 1_000_000
    SCOPES = (
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_posts",
        "instagram_basic",
        "instagram_content_publish",
    )

    def __init__(self, app_id: str, app_secret: str, graph_version: str = "v27.0") -> None:
        if not re.fullmatch(r"v\d+\.\d+", graph_version):
            raise ValueError("Invalid Graph API version")
        self.app_id = app_id
        self.app_secret = app_secret
        self.graph_version = graph_version

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": ",".join(self.SCOPES),
                "response_type": "code",
            }
        )
        return f"{self.AUTH_BASE}{self.graph_version}/dialog/oauth?{query}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return self._request(
            "POST",
            "oauth/access_token",
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )

    def exchange_long_lived_token(self, short_token: str) -> dict:
        return self._request(
            "POST",
            "oauth/access_token",
            data={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_token,
            },
        )

    def list_pages(self, user_token: str) -> list[MetaPage]:
        fields = "id,name,access_token,instagram_business_account{id,username}"
        url = self._url("me/accounts")
        params: dict[str, str] | None = {"fields": fields, "limit": "100"}
        pages: list[MetaPage] = []
        seen: set[str] = set()
        for _ in range(20):
            payload = self._request("GET", url, params=params, token=user_token, absolute=True)
            data = payload.get("data")
            if not isinstance(data, list):
                raise MetaAPIError("malformed_response")
            for item in data:
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(k), str) and item[k] for k in ("id", "name", "access_token")
                ):
                    raise MetaAPIError("malformed_response")
                self._validate_id(item["id"])
                ig = item.get("instagram_business_account") or {}
                if not isinstance(ig, dict):
                    raise MetaAPIError("malformed_response")
                if ig.get("id") is not None:
                    self._validate_id(ig["id"])
                pages.append(
                    MetaPage(
                        item["id"],
                        item["name"],
                        item["access_token"],
                        ig.get("id"),
                        ig.get("username"),
                    )
                )
            paging = payload.get("paging") or {}
            next_url = paging.get("next") if isinstance(paging, dict) else None
            if not next_url:
                return pages
            if not isinstance(next_url, str):
                raise MetaAPIError("malformed_response")
            parsed = urlsplit(next_url)
            expected_path = f"/{self.graph_version}/me/accounts"
            cursors = parse_qs(parsed.query).get("after", [])
            if (
                parsed.scheme != "https"
                or parsed.netloc != "graph.facebook.com"
                or parsed.path != expected_path
                or len(cursors) != 1
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", cursors[0])
            ):
                raise MetaAPIError("malformed_response")
            cursor = cursors[0]
            if cursor in seen:
                raise MetaAPIError("pagination_loop")
            seen.add(cursor)
            params = {"fields": fields, "limit": "100", "after": cursor}
        raise MetaAPIError("pagination_limit")

    def publish_facebook_photo(
        self, page_id: str, page_token: str, poster_url: str, message: str
    ) -> str:
        self._validate_id(page_id)
        payload = self._request(
            "POST",
            f"{page_id}/photos",
            token=page_token,
            data={"url": poster_url, "caption": message},
        )
        value = payload.get("post_id") or payload.get("id")
        if not isinstance(value, str) or not value or len(value) > 100:
            raise MetaAPIError("malformed_response")
        return value

    def publish_instagram_photo(
        self,
        ig_account_id: str,
        page_token: str,
        poster_url: str,
        caption: str,
        container_id: str | None = None,
    ) -> str:
        self._validate_id(ig_account_id)
        if container_id is None:
            created = self._request(
                "POST",
                f"{ig_account_id}/media",
                token=page_token,
                data={"image_url": poster_url, "caption": caption},
                timeout=self.INSTAGRAM_TIMEOUT,
            )
            container_id = self._required_id(created)
        self._validate_container_id(container_id)
        # Three bounded checks keep request latency below the synchronous web budget.
        for attempt in range(3):
            status = self._request(
                "GET",
                container_id,
                token=page_token,
                params={"fields": "status_code"},
                timeout=self.INSTAGRAM_TIMEOUT,
            )
            if status.get("status_code") in {"FINISHED", "PUBLISHED"}:
                break
            if status.get("status_code") != "IN_PROGRESS":
                raise MetaAPIError("media_not_ready")
            if attempt < 2:
                time.sleep(2)
        else:
            raise MetaMediaPending(container_id)
        published = self._request(
            "POST",
            f"{ig_account_id}/media_publish",
            token=page_token,
            data={"creation_id": container_id},
            timeout=self.INSTAGRAM_TIMEOUT,
        )
        return self._required_id(published)

    @staticmethod
    def _required_id(payload: dict) -> str:
        value = payload.get("id")
        if not isinstance(value, str) or not value:
            raise MetaAPIError("malformed_response")
        return value

    def _url(self, path: str) -> str:
        return f"{self.GRAPH_BASE}{self.graph_version}/{path.lstrip('/')}"

    @staticmethod
    def _validate_id(value: object) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,32}", value):
            raise MetaAPIError("malformed_response")

    @staticmethod
    def _validate_container_id(value: object) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,100}", value):
            raise MetaAPIError("malformed_response")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        token: str | None = None,
        absolute: bool = False,
        timeout: int | None = None,
    ) -> dict:
        url = path if absolute else self._url(path)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        headers = {"Accept": "application/json"}
        body = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            body = urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with _open_request(request, timeout or self.TIMEOUT) as response:
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            try:
                raw_error = exc.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw_error) > self.MAX_RESPONSE_BYTES:
                    raise MetaAPIError("response_too_large") from None
                if 300 <= exc.code < 400:
                    raise MetaAPIError("redirect_blocked") from None
                safe_code = self._meta_error_code(raw_error)
                raise MetaAPIError(safe_code or "http_error") from None
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError):
            raise MetaAPIError("network_error") from None
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise MetaAPIError("response_too_large")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise MetaAPIError("malformed_response") from None
        if not isinstance(result, dict):
            raise MetaAPIError("malformed_response")
        safe_code = self._meta_error_code(raw)
        if safe_code:
            raise MetaAPIError(safe_code)
        return result

    @staticmethod
    def _meta_error_code(raw: bytes) -> str | None:
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return None
        code = str(error.get("code", ""))
        if not re.fullmatch(r"\d{1,6}", code):
            return "meta_api_error"
        return f"meta_{code}"
