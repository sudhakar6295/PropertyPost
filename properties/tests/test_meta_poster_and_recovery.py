"""Signed poster formats and recovery of abandoned direct Meta requests."""

import time
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from properties.api_views import _poster_signature
from properties.broker_views import reconcile_stale_social_attempts
from properties.models import (
    AdvertDraft,
    OpenPlotListing,
    SocialAccountConnection,
    SocialPublicationAttempt,
)
from properties.services import object_store
from properties.tests.test_views import create_listing


@pytest.fixture
def approved_advert(django_user_model, settings):
    settings.AUTOMATION_HMAC_SECRET = "test-only-poster-secret"
    broker = django_user_model.objects.create_user(username="poster-broker")
    listing = create_listing("Poster plot", OpenPlotListing.Status.APPROVED, broker)
    advert = AdvertDraft.objects.create(
        listing=listing,
        template="minimal",
        poster_path=f"posters/{broker.pk}/{listing.public_id}/poster.png",
        headline="Poster plot",
        caption="Approved public advert",
        hashtags=["#land"],
    )
    image_bytes = BytesIO()
    Image.new("RGBA", (32, 24), (18, 90, 170, 255)).save(image_bytes, format="PNG")
    object_store().upload(advert.poster_path, image_bytes.getvalue(), "image/png")
    return listing, advert, image_bytes.getvalue()


def signed_poster_url(listing, *, image_format=None):
    expires = int(time.time()) + 600
    query = f"expires={expires}&signature={_poster_signature(listing.public_id, expires)}"
    if image_format:
        query += f"&format={image_format}"
    return f"{reverse('automation-poster', args=[listing.public_id])}?{query}"


def make_connection(listing):
    return SocialAccountConnection.objects.create(
        owner=listing.broker,
        facebook_page_id="1234567",
        page_name="Poster Realty",
        encrypted_page_access_token="test-ciphertext",
    )


def make_attempt(listing, advert, connection, *, status, error_code=""):
    return SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=connection,
        advert_version_number=advert.version_number,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        status=status,
        error_code=error_code,
        request_id=uuid4(),
    )


@pytest.mark.django_db
def test_signed_poster_preserves_original_png_response(client, approved_advert):
    listing, _advert, original_png = approved_advert
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])

    response = client.get(signed_poster_url(listing))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content == original_png


@pytest.mark.django_db
@pytest.mark.parametrize(
    "final_status", [OpenPlotListing.Status.FAILED, OpenPlotListing.Status.PUBLISHED]
)
def test_direct_jpeg_poster_remains_available_after_status_changes(
    client, approved_advert, final_status
):
    listing, advert, _original_png = approved_advert
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])
    connection = make_connection(listing)
    make_attempt(
        listing,
        advert,
        connection,
        status=SocialPublicationAttempt.Status.UNCERTAIN,
        error_code="publication_uncertain",
    )
    listing.status = final_status
    listing.save(update_fields=["status"])

    response = client.get(signed_poster_url(listing, image_format="jpeg"))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"
    with Image.open(BytesIO(response.content)) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (32, 24)
    # The original Make/PNG link retains its prior pending-only state guard.
    assert client.get(signed_poster_url(listing)).status_code == 409


@pytest.mark.django_db
def test_jpeg_conversion_rejects_invalid_or_oversized_posters(client, approved_advert, monkeypatch):
    listing, advert, _original_png = approved_advert
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])
    object_store().upload(advert.poster_path, b"not a png", "image/png")
    assert client.get(signed_poster_url(listing, image_format="jpeg")).status_code == 422

    image = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
    object_store().upload(advert.poster_path, image.getvalue(), "image/png")
    from properties import api_views

    monkeypatch.setattr(api_views, "MAX_SIGNED_POSTER_PIXELS", 100)
    assert client.get(signed_poster_url(listing, image_format="jpeg")).status_code == 422


def stale_pending_attempt(approved_advert):
    listing, advert, _png = approved_advert
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])
    connection = make_connection(listing)
    attempt = make_attempt(
        listing,
        advert,
        connection,
        status=SocialPublicationAttempt.Status.PENDING,
    )
    SocialPublicationAttempt.objects.filter(pk=attempt.pk).update(
        updated_at=timezone.now() - timedelta(seconds=120)
    )
    return listing, attempt


@pytest.mark.django_db
@pytest.mark.parametrize(
    "route_name",
    ["dashboard", "advert-preview", "published-result", "publication-status"],
)
def test_page_access_reconciles_stale_attempt_without_retry(client, approved_advert, route_name):
    listing, attempt = stale_pending_attempt(approved_advert)
    broker = listing.broker
    client.force_login(broker)
    if route_name == "dashboard":
        url = reverse(route_name)
    else:
        url = reverse(route_name, args=[listing.public_id])

    response = client.get(url)

    assert response.status_code == 200
    attempt.refresh_from_db()
    listing.refresh_from_db()
    assert attempt.status == SocialPublicationAttempt.Status.UNCERTAIN
    assert attempt.error_code == "worker_timeout"
    assert listing.status == OpenPlotListing.Status.FAILED
    if route_name == "publication-status":
        assert response.json()["status"] == OpenPlotListing.Status.FAILED


@pytest.mark.django_db
def test_recent_attempt_is_not_reconciled(client, approved_advert):
    listing, advert, _png = approved_advert
    listing.status = OpenPlotListing.Status.PUBLISHING
    listing.save(update_fields=["status"])
    connection = make_connection(listing)
    attempt = make_attempt(
        listing,
        advert,
        connection,
        status=SocialPublicationAttempt.Status.PENDING,
    )

    assert reconcile_stale_social_attempts(listing=listing) == 0
    attempt.refresh_from_db()
    listing.refresh_from_db()
    assert attempt.status == SocialPublicationAttempt.Status.PENDING
    assert listing.status == OpenPlotListing.Status.PUBLISHING


@pytest.mark.django_db
def test_stale_previous_version_does_not_fail_current_advert(approved_advert):
    listing, advert, _png = approved_advert
    connection = make_connection(listing)
    attempt = make_attempt(
        listing,
        advert,
        connection,
        status=SocialPublicationAttempt.Status.PENDING,
    )
    SocialPublicationAttempt.objects.filter(pk=attempt.pk).update(
        updated_at=timezone.now() - timedelta(seconds=120)
    )
    advert.version_number = 2
    advert.save(update_fields=["version_number"])

    assert reconcile_stale_social_attempts(listing=listing) == 1
    attempt.refresh_from_db()
    listing.refresh_from_db()
    assert attempt.status == SocialPublicationAttempt.Status.UNCERTAIN
    assert listing.status == OpenPlotListing.Status.APPROVED
