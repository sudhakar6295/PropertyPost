"""Advert language is selected when generation starts and saved with its result."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from properties.models import OpenPlotListing, PlotPhoto
from properties.tests.test_automation_api import signed_request
from properties.tests.test_views import create_listing


@pytest.mark.django_db
def test_make_generation_uses_selected_language_and_persists_it(
    client, django_user_model, settings
):
    settings.MAKE_WEBHOOK_URL = "https://hook.example.invalid/token"
    settings.AUTOMATION_HMAC_SECRET = "test-only-automation-secret"
    broker = django_user_model.objects.create_user(
        username="language-broker", password="testpass123"
    )
    client.force_login(broker)
    listing = create_listing("Language test", OpenPlotListing.Status.DRAFT, broker)
    PlotPhoto.objects.create(listing=listing, object_path="originals/test/photo.jpg", is_main=True)

    with patch("properties.broker_views.trigger_generation"):
        response = client.post(
            reverse("generate-advert", args=[listing.public_id]),
            {"template": "minimal", "language": "hi"},
        )
    assert response.status_code == 202
    listing.refresh_from_db()
    assert listing.language == "hi"

    input_response = signed_request(
        client, "GET", reverse("automation-input", args=[listing.public_id])
    )
    assert input_response.status_code == 200
    assert input_response.json()["public_details"]["language"] == "hi"

    with (
        patch("properties.api_views.render_poster", return_value=b"poster"),
        patch("properties.api_views.object_store"),
    ):
        result = signed_request(
            client,
            "POST",
            reverse("generation-result", args=[listing.public_id]),
            {
                "request_id": str(listing.generation_request_id),
                "status": "succeeded",
                "headline": "Plot for sale",
                "caption": "Call for details",
                "hashtags": ["#Land"],
                "template": "minimal",
            },
        )
    assert result.status_code == 200
    assert listing.advert.language == "hi"
