"""Caption providers receive an allow-listed public document only."""

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.request import Request, urlopen

from .serializers import PUBLIC_DETAIL_FIELDS


@dataclass(frozen=True)
class Caption:
    headline: str
    caption: str
    hashtags: tuple[str, ...]


def validate_caption(value: object) -> Caption:
    if not isinstance(value, dict) or set(value) != {"headline", "caption", "hashtags"}:
        raise ValueError("Caption JSON must contain headline, caption and hashtags only.")
    headline, body, tags = value["headline"], value["caption"], value["hashtags"]
    if not isinstance(headline, str) or not headline.strip() or len(headline) > 100:
        raise ValueError("Headline must be 1 to 100 characters.")
    if not isinstance(body, str) or not body.strip() or len(body) > 1000:
        raise ValueError("Caption must be 1 to 1000 characters.")
    if (
        not isinstance(tags, list)
        or len(tags) > 8
        or any(
            not isinstance(tag, str)
            or not tag.startswith("#")
            or len(tag) > 40
            or not tag[1:].replace("_", "").isalnum()
            for tag in tags
        )
    ):
        raise ValueError("Use up to eight simple hashtags.")
    return Caption(headline.strip(), body.strip(), tuple(tags))


def approved_public_details(details: dict) -> dict:
    if set(details) != PUBLIC_DETAIL_FIELDS:
        raise ValueError("Caption input must contain exactly the approved public fields.")
    return {key: details[key] for key in sorted(PUBLIC_DETAIL_FIELDS)}


class CaptionProvider(Protocol):
    def generate(self, public_details: dict) -> Caption: ...


class LocalCaptionProvider:
    def generate(self, public_details: dict) -> Caption:
        details = approved_public_details(public_details)
        location = details["location"]
        headline = f"Open plot for sale in {location}"[:100]
        body = (
            f"{details['area']} {details['area_unit']} open plot in {location}, "
            f"near {details['landmark']}. Price: ₹{details['total_price']}. "
            f"Call {details['contact_number']} for details."
        )
        return validate_caption(
            {
                "headline": headline,
                "caption": body[:1000],
                "hashtags": ["#OpenPlot", "#LandForSale"],
            }
        )


class GeminiCaptionProvider:
    def __init__(self, api_key: str, model: str, transport=None):
        if not api_key:
            raise ValueError("Gemini API key is required.")
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._request

    def _request(self, payload: dict) -> dict:
        request = Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def generate(self, public_details: dict) -> Caption:
        details = approved_public_details(public_details)
        schema = {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "caption": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["headline", "caption", "hashtags"],
        }
        payload = {
            "model": self.model,
            "input": "Write an accurate property advert. Do not invent facts. Public details: "
            + json.dumps(details, ensure_ascii=False),
            "response_format": {"type": "text", "mime_type": "application/json", "schema": schema},
        }
        response = self.transport(payload)
        return validate_caption(json.loads(response["output_text"]))
