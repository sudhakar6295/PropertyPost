import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from django.urls import reverse

from properties.api_views import _image_signature
from properties.models import AutomationReceipt, OpenPlotListing, OpenPlotPrivateDetails, PlotPhoto
from properties.services import object_store
from properties.tests.test_views import create_listing

SECRET = "test-only-automation-secret"


def signed_request(client, method, path, payload=None, timestamp=None, secret=SECRET):
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    signed = b"\n".join((method.encode(), path.encode(), timestamp.encode(), body))
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return client.generic(
        method,
        path,
        data=body,
        content_type="application/json",
        HTTP_X_PROPERTYPOST_TIMESTAMP=timestamp,
        HTTP_X_PROPERTYPOST_SIGNATURE=signature,
    )


@pytest.fixture
def listing(django_user_model, settings):
    settings.AUTOMATION_HMAC_SECRET = SECRET
    broker = django_user_model.objects.create_user(username="api-broker")
    plot = create_listing("Public plot", OpenPlotListing.Status.GENERATING, broker)
    OpenPlotPrivateDetails.objects.create(
        listing=plot,
        owner_name="Secret owner",
        owner_phone="+919800000000",
        internal_notes="Secret terms",
        negotiable_amount=4000000,
    )
    photo = PlotPhoto.objects.create(
        listing=plot,
        object_path="originals/test/photo.png",
        content_type="image/png",
        size_bytes=5,
        is_main=True,
    )
    object_store().upload(photo.object_path, b"photo", "image/png")
    return plot


@pytest.mark.django_db
def test_input_is_signed_public_only_and_images_expire(client, listing):
    path = reverse("automation-input", args=[listing.public_id])
    assert client.get(path).status_code == 401
    response = signed_request(client, "GET", path)
    assert response.status_code == 200
    data = response.json()
    assert data["public_details"]["title"] == "Public plot"
    assert len(data["images"]) == 1
    assert "Secret owner" not in response.content.decode()
    assert "Secret terms" not in response.content.decode()
    assert "negotiable_amount" not in response.content.decode()
    image_url = data["images"][0]["url"]
    from urllib.parse import urlsplit

    parsed = urlsplit(image_url)
    assert client.get(parsed.path + "?" + parsed.query).content == b"photo"
    assert client.get(parsed.path).status_code == 403
    expired_at = int(time.time()) - 1
    expired_image = (
        f"{parsed.path}?expires={expired_at}&signature="
        f"{_image_signature(listing.public_id, listing.photos.first().pk, expired_at)}"
    )
    assert client.get(expired_image).status_code == 403
    expired = signed_request(client, "GET", path, timestamp=int(time.time()) - 301)
    assert expired.status_code == 401
    assert signed_request(client, "GET", path, secret="wrong").status_code == 401


@pytest.mark.django_db
def test_automation_input_only_serves_a_pending_generation(client, listing):
    listing.status = OpenPlotListing.Status.DRAFT
    listing.save(update_fields=["status"])
    path = reverse("automation-input", args=[listing.public_id])

    response = signed_request(client, "GET", path)

    assert response.status_code == 409
    assert response.json() == {"error": "Listing is not awaiting generation"}


@pytest.mark.django_db
def test_generation_callback_is_validated_and_idempotent(client, listing):
    path = reverse("generation-result", args=[listing.public_id])
    payload = {
        "request_id": str(uuid4()),
        "status": "succeeded",
        "headline": "A plot",
        "caption": "Good location",
        "hashtags": ["#Land"],
        "poster_path": f"posters/{listing.broker_id}/{listing.public_id}/poster.png",
    }
    unsigned = client.post(path, data=json.dumps(payload), content_type="application/json")
    assert unsigned.status_code == 401
    expired = signed_request(client, "POST", path, payload, timestamp=int(time.time()) - 301)
    assert expired.status_code == 401
    first = signed_request(client, "POST", path, payload)
    assert first.status_code == 200
    assert signed_request(client, "POST", path, payload).json() == first.json()
    assert AutomationReceipt.objects.filter(listing=listing).count() == 1
    assert OpenPlotListing.objects.get(pk=listing.pk).status == OpenPlotListing.Status.REVIEW
    changed = signed_request(client, "POST", path, {**payload, "headline": "Changed"})
    assert changed.status_code == 409


@pytest.mark.django_db
def test_publication_retry_does_not_create_second_post(client, listing):
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])
    path = reverse("publication-result", args=[listing.public_id])
    payload = {"request_id": str(uuid4()), "status": "succeeded", "external_post_id": "post-42"}
    first = signed_request(client, "POST", path, payload)
    assert first.status_code == 200
    assert signed_request(client, "POST", path, payload).json() == first.json()
    assert AutomationReceipt.objects.filter(listing=listing, kind="publication").count() == 1
    assert OpenPlotListing.objects.get(pk=listing.pk).status == OpenPlotListing.Status.PUBLISHED
    second_post = signed_request(client, "POST", path, {**payload, "request_id": str(uuid4())})
    assert second_post.status_code == 409


@pytest.mark.django_db
def test_failed_callback_changes_status_once(client, listing):
    path = reverse("generation-result", args=[listing.public_id])
    payload = {"request_id": str(uuid4()), "status": "failed", "error": "Provider unavailable"}
    assert signed_request(client, "POST", path, payload).json()["status"] == "failed"
    assert signed_request(client, "POST", path, payload).json()["status"] == "failed"
    assert OpenPlotListing.objects.get(pk=listing.pk).status == OpenPlotListing.Status.FAILED
    assert AutomationReceipt.objects.filter(listing=listing).count() == 1
