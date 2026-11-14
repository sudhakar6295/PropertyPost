"""Make.com request safety and payload contract tests."""

import json
from unittest.mock import Mock, patch

import pytest

from properties.make_webhook import MakeWebhookError, trigger_generation


def test_generation_event_sends_listing_reference_without_property_details():
    response = Mock(status=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    with patch("properties.make_webhook.urlopen", return_value=response) as send:
        trigger_generation(
            "https://hook.example.invalid/token",
            listing_id="b9f79a82-9653-4520-a48b-ec7d2779cd25",
            request_id="60c926ed-4bd8-40a8-bafb-4ac7ed96c769",
            template="classic",
            automation_input_url="https://propertypost.example.invalid/api/v1/input/",
            generation_result_url="https://propertypost.example.invalid/api/v1/result/",
        )

    request = send.call_args.args[0]
    payload = json.loads(request.data)
    assert payload == {
        "event": "propertypost.generation.requested",
        "request_id": "60c926ed-4bd8-40a8-bafb-4ac7ed96c769",
        "listing_id": "b9f79a82-9653-4520-a48b-ec7d2779cd25",
        "template": "classic",
        "automation_input_url": "https://propertypost.example.invalid/api/v1/input/",
        "generation_result_url": "https://propertypost.example.invalid/api/v1/result/",
    }
    assert "private_details" not in payload
    assert "internal_notes" not in payload
    assert request.get_method() == "POST"


def test_webhook_rejects_non_https_url():
    with pytest.raises(MakeWebhookError, match="HTTPS"):
        trigger_generation(
            "http://hook.example.invalid/token",
            listing_id="b9f79a82-9653-4520-a48b-ec7d2779cd25",
            request_id="60c926ed-4bd8-40a8-bafb-4ac7ed96c769",
            template="classic",
            automation_input_url="https://propertypost.example.invalid/api/v1/input/",
            generation_result_url="https://propertypost.example.invalid/api/v1/result/",
        )
