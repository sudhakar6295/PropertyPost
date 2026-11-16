"""Saved advert revisions survive navigation and protect earlier publications."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from properties.models import (
    AdvertDraft,
    AdvertVersion,
    AutomationJob,
    OpenPlotListing,
    OpenPlotPrivateDetails,
)
from properties.tests.test_views import create_listing


@pytest.fixture
def published_plot(django_user_model):
    broker = django_user_model.objects.create_user(username="owner", password="testpass123")
    plot = create_listing("Saved plot", OpenPlotListing.Status.PUBLISHED, broker)
    plot.publication_results = {"facebook": "fb-old-123"}
    plot.publication_platforms = ["facebook"]
    plot.save(update_fields=["publication_results", "publication_platforms"])
    OpenPlotPrivateDetails.objects.create(
        listing=plot,
        owner_name="Private owner",
        owner_phone="+919800000000",
        internal_notes="Keep private",
    )
    AdvertDraft.objects.create(
        listing=plot,
        template="minimal",
        poster_path="posters/owner/old.png",
        headline="Original headline",
        caption="Original advert text",
        hashtags=["#Land"],
    )
    return plot


@pytest.mark.django_db
def test_published_revision_saves_history_and_broker_edits(client, published_plot):
    plot = published_plot
    client.force_login(plot.broker)
    response = client.post(reverse("revise-published-advert", args=[plot.public_id]))
    assert response.status_code == 302
    plot.refresh_from_db()
    assert plot.status == OpenPlotListing.Status.REVIEW
    assert plot.publication_results == {}
    old = AdvertVersion.objects.get(listing=plot, version_number=1)
    assert old.headline == "Original headline"
    assert old.publication_results == {"facebook": "fb-old-123"}
    assert plot.advert.version_number == 2
    assert b"Saved plot" in client.get(reverse("properties:list")).content

    review_url = reverse("review-details", args=[plot.public_id])
    changed = {
        "headline": "Revised headline",
        "caption": "Revised advert text",
        "hashtags_text": "#Land #Sale",
    }
    assert client.post(review_url, {**changed, "intent": "save"}).status_code == 302
    assert OpenPlotListing.objects.get(pk=plot.pk).status == OpenPlotListing.Status.REVIEW
    assert b"Revised headline" in client.get(review_url).content
    assert client.post(review_url, {**changed, "intent": "approve"}).status_code == 302
    assert OpenPlotListing.objects.get(pk=plot.pk).status == OpenPlotListing.Status.APPROVED
    history = client.get(reverse("advert-history", args=[plot.public_id]))
    assert b"Original headline" in history.content
    assert b"Revised headline" in history.content
    assert b"fb-old-123" in history.content
    assert b"Keep private" not in history.content


@pytest.mark.django_db
def test_public_listing_edit_preserves_published_version(client, published_plot):
    plot = published_plot
    client.force_login(plot.broker)
    data = {
        "public-title": "Updated plot",
        "public-location": plot.location,
        "public-landmark": plot.landmark,
        "public-area": str(plot.area),
        "public-area_unit": plot.area_unit,
        "public-total_price": str(plot.total_price),
        "public-price_per_unit": str(plot.price_per_unit),
        "public-facing": plot.facing,
        "public-road_width_ft": str(plot.road_width_ft),
        "public-approval_type": plot.approval_type,
        "public-contact_number": plot.contact_number,
        "public-language": plot.language,
        "private-owner_name": "Private owner",
        "private-owner_phone": "+919800000000",
        "private-internal_notes": "Keep private",
        "private-negotiable_amount": "",
    }
    assert client.post(reverse("edit-plot", args=[plot.public_id]), data).status_code == 302
    plot.refresh_from_db()
    assert plot.status == OpenPlotListing.Status.DRAFT
    assert plot.publication_results == {}
    assert not AdvertDraft.objects.filter(listing=plot).exists()
    saved = AdvertVersion.objects.get(listing=plot)
    assert saved.publication_results["facebook"] == "fb-old-123"
    assert saved.public_details["title"] == "Saved plot"
    public_page = client.get(reverse("properties:list"))
    assert b"Saved plot" in public_page.content
    assert b"Updated plot" not in public_page.content
    assert b"Private owner" not in public_page.content


@pytest.mark.django_db
def test_other_broker_cannot_open_advert_history_or_poster(
    client, published_plot, django_user_model
):
    plot = published_plot
    client.force_login(plot.broker)
    client.post(reverse("revise-published-advert", args=[plot.public_id]))
    other = django_user_model.objects.create_user(username="other", password="testpass123")
    client.force_login(other)
    assert client.get(reverse("advert-history", args=[plot.public_id])).status_code == 404
    assert client.get(reverse("version-poster", args=[plot.public_id, 1])).status_code == 404
    assert client.post(reverse("revise-published-advert", args=[plot.public_id])).status_code == 404


@pytest.mark.django_db
def test_make_generation_attempt_is_saved_for_retry(client, django_user_model, settings):
    from properties.models import PlotPhoto

    settings.MAKE_WEBHOOK_URL = "https://hook.example.invalid/example"
    broker = django_user_model.objects.create_user(username="maker", password="testpass123")
    plot = create_listing("A plot", OpenPlotListing.Status.DRAFT, broker)
    PlotPhoto.objects.create(
        listing=plot,
        object_path="originals/maker/photo.jpg",
        content_type="image/jpeg",
        size_bytes=100,
        is_main=True,
    )
    client.force_login(broker)
    with patch("properties.broker_views.trigger_generation"):
        assert (
            client.post(
                reverse("generate-advert", args=[plot.public_id]), {"template": "minimal"}
            ).status_code
            == 202
        )
    plot.refresh_from_db()
    job = AutomationJob.objects.get(request_id=plot.generation_request_id)
    assert job.status == AutomationJob.Status.PENDING
    assert job.listing_id == plot.pk
    assert client.get(reverse("generate-advert", args=[plot.public_id])).status_code == 200


@pytest.mark.django_db
def test_publication_status_survives_refresh_and_is_owner_scoped(
    client, published_plot, django_user_model
):
    plot = published_plot
    plot.status = OpenPlotListing.Status.PUBLISHING
    plot.save(update_fields=["status"])
    client.force_login(plot.broker)
    url = reverse("publication-status", args=[plot.public_id])
    first = client.get(url)
    assert first.json()["status"] == "publishing"
    plot.status = OpenPlotListing.Status.PUBLISHED
    plot.save(update_fields=["status"])
    assert client.get(url).json()["publication_results"] == {"facebook": "fb-old-123"}
    other = django_user_model.objects.create_user(username="outsider", password="testpass123")
    client.force_login(other)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_expired_generation_can_be_retried_after_reopening(client, django_user_model, settings):
    settings.MAKE_JOB_TIMEOUT_SECONDS = 60
    broker = django_user_model.objects.create_user(username="retry", password="testpass123")
    plot = create_listing("Retry plot", OpenPlotListing.Status.GENERATING, broker)
    plot.generation_request_id = uuid4()
    plot.save(update_fields=["generation_request_id"])
    job = AutomationJob.objects.create(
        listing=plot,
        kind=AutomationJob.Kind.GENERATION,
        request_id=plot.generation_request_id,
    )
    AutomationJob.objects.filter(pk=job.pk).update(
        requested_at=timezone.now() - timedelta(minutes=2)
    )
    client.force_login(broker)
    result = client.get(reverse("generation-status", args=[plot.public_id]))
    assert result.json()["status"] == "failed"
    assert result.json()["retry_url"] == reverse("generate-advert", args=[plot.public_id])
    job.refresh_from_db()
    assert job.status == AutomationJob.Status.FAILED
    assert job.error_code == "callback_timeout"
