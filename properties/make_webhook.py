"""Minimal, privacy-conscious outbound Make.com webhook client."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class MakeWebhookError(Exception):
    """Raised when Make.com does not accept an automation event."""


def trigger_generation(
    webhook_url: str,
    *,
    listing_id: str,
    request_id: str,
    template: str,
    automation_input_url: str,
    generation_result_url: str,
) -> None:
    """Notify Make with identifiers and API links only; Make fetches public details separately."""
    parsed_url = urlsplit(webhook_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise MakeWebhookError("Make.com webhook must use HTTPS.")
    event = {
        "event": "propertypost.generation.requested",
        "request_id": request_id,
        "listing_id": listing_id,
        "template": template,
        "automation_input_url": automation_input_url,
        "generation_result_url": generation_result_url,
    }
    request = Request(
        webhook_url,
        data=json.dumps(event, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise MakeWebhookError("Make.com did not accept the request.")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MakeWebhookError("Make.com could not be reached.") from exc
