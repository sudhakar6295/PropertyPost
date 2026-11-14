"""Complete local broker flow and cross-broker access checks."""

from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.urls import reverse
from PIL import Image

from properties.models import OpenPlotListing
from propertypost.logging import SafeJsonFormatter


@pytest.mark.django_db
def test_local_journey(client, django_user_model, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    broker = django_user_model.objects.create_user(username="alice", password="StrongPass123!")
    assert client.get(reverse("dashboard")).status_code == 302
    assert client.get(reverse("broker-login")).status_code == 200
    response = client.post(
        reverse("broker-login"), {"username": "alice", "password": "StrongPass123!"}
    )
    assert response.status_code == 302
    assert client.get(reverse("dashboard")).status_code == 200
    data = {
        "public-title": "East-facing plot",
        "public-location": "Hyderabad",
        "public-landmark": "Near ORR",
        "public-area": "267.00",
        "public-area_unit": "sq_yd",
        "public-total_price": "4800000",
        "public-price_per_unit": "17977.53",
        "public-facing": "east",
        "public-road_width_ft": "30.00",
        "public-approval_type": "hmda",
        "public-contact_number": "+919876543210",
        "public-language": "te",
        "private-owner_name": "Owner Alice",
        "private-owner_phone": "+919800000000",
        "private-internal_notes": "Do not share",
        "private-negotiable_amount": "4500000",
    }
    response = client.post(reverse("add-plot"), data)
    plot = OpenPlotListing.objects.get(broker=broker)
    assert response.status_code == 302
    assert response.url == reverse("upload-photos", args=[plot.public_id])
    assert client.get(response.url).status_code == 200
    image_bytes = BytesIO()
    Image.new("RGB", (24, 24), "green").save(image_bytes, format="PNG")
    upload = SimpleUploadedFile("plot.png", image_bytes.getvalue(), content_type="image/png")
    assert client.post(response.url, {"image": upload, "caption": "Road view"}).status_code == 302
    assert plot.photos.count() == 1
    photo = plot.photos.first()
    assert photo.is_main
    assert photo.object_path.startswith(f"originals/{broker.pk}/{plot.public_id}/")
    assert client.get(reverse("private-photo", args=[plot.public_id, photo.pk])).status_code == 200
    order_url = reverse("arrange-photos", args=[plot.public_id])
    assert (
        client.post(order_url, {"photo_order": [photo.pk], "main_photo": photo.pk}).status_code
        == 302
    )
    assert client.get(reverse("edit-plot", args=[plot.public_id])).status_code == 200
    review_url = reverse("review-details", args=[plot.public_id])
    details = client.get(review_url)
    assert details.status_code == 200
    assert b"Shown in your advert" in details.content
    assert b"Private notes" in details.content
    assert client.post(reverse("publish-plot", args=[plot.public_id])).status_code == 400
    generation = client.post(
        reverse("generate-advert", args=[plot.public_id]), {"template": "classic"}
    )
    assert generation.status_code == 302
    assert OpenPlotListing.objects.get(pk=plot.pk).status == OpenPlotListing.Status.REVIEW
    review = client.get(review_url)
    assert b"Shown in your advert" in review.content
    assert b"Private notes" in review.content
    advert = plot.advert
    assert (
        client.post(
            review_url,
            {
                "headline": "Edited headline",
                "caption": advert.caption,
                "hashtags_text": "#OpenPlot #LandForSale",
            },
        ).status_code
        == 302
    )
    preview = client.get(reverse("advert-preview", args=[plot.public_id]))
    assert OpenPlotListing.objects.get(pk=plot.pk).status == OpenPlotListing.Status.APPROVED
    assert preview.status_code == 200
    assert b"Owner Alice" not in preview.content
    assert b"Do not share" not in preview.content
    assert client.post(reverse("publish-plot", args=[plot.public_id])).status_code == 302
    assert client.get(reverse("published-result", args=[plot.public_id])).status_code == 200
    assert b"East-facing plot" in client.get(reverse("properties:list")).content


@pytest.mark.django_db
def test_other_broker_cannot_access_any_plot_step(client, django_user_model):
    django_user_model.objects.create_user(username="alice", password="StrongPass123!")
    django_user_model.objects.create_user(username="bob", password="StrongPass123!")
    client.login(username="alice", password="StrongPass123!")
    from properties.tests.test_views import create_listing

    owner = django_user_model.objects.get(username="alice")
    plot = create_listing("Alice's plot", OpenPlotListing.Status.APPROVED, owner)
    client.logout()
    client.login(username="bob", password="StrongPass123!")
    for name in (
        "edit-plot",
        "upload-photos",
        "review-details",
        "advert-preview",
        "published-result",
    ):
        assert client.get(reverse(name, args=[plot.public_id])).status_code == 404
    assert client.post(reverse("publish-plot", args=[plot.public_id])).status_code == 404
    assert client.post(reverse("arrange-photos", args=[plot.public_id])).status_code == 404
    assert b"Alice&#x27;s plot" not in client.get(reverse("dashboard")).content


@pytest.mark.django_db
def test_generation_without_main_photo_explains_how_to_continue(client, django_user_model):
    broker = django_user_model.objects.create_user(username="alice", password="StrongPass123!")
    client.force_login(broker)
    from properties.tests.test_views import create_listing

    plot = create_listing("East-facing plot", OpenPlotListing.Status.DRAFT, broker)

    response = client.get(reverse("generate-advert", args=[plot.public_id]))

    assert response.status_code == 200
    assert b"Add a main photo to continue" in response.content
    assert reverse("upload-photos", args=[plot.public_id]).encode() in response.content
    assert b"disabled" in response.content


@pytest.mark.django_db
def test_plot_database_error_is_safe_and_preserves_form_values(client, django_user_model, caplog):
    django_user_model.objects.create_user(username="alice", password="StrongPass123!")
    client.login(username="alice", password="StrongPass123!")
    data = {
        "public-title": "East-facing plot",
        "public-location": "Hyderabad",
        "public-landmark": "Near ORR",
        "public-area": "267.00",
        "public-area_unit": "sq_yd",
        "public-total_price": "4800000",
        "public-price_per_unit": "17977.53",
        "public-facing": "east",
        "public-road_width_ft": "30.00",
        "public-approval_type": "hmda",
        "public-contact_number": "+919876543210",
        "public-language": "te",
        "private-owner_name": "Owner Alice",
        "private-owner_phone": "+919800000000",
        "private-internal_notes": "Never put this in logs",
        "private-negotiable_amount": "4500000",
    }
    with patch(
        "properties.broker_views.OpenPlotListing.save",
        side_effect=OperationalError("private sql error"),
    ):
        response = client.post(reverse("add-plot"), data)

    assert response.status_code == 503
    assert b"We couldn't save this plot just now" in response.content
    assert b"East-facing plot" in response.content
    assert b"Never put this in logs" not in caplog.text
    assert "private sql error" not in caplog.text
    record = next(record for record in caplog.records if record.msg == "Plot save failed")
    safe_log = SafeJsonFormatter().format(record)
    assert '"exception_type": "OperationalError"' in safe_log
    assert "private sql error" not in safe_log
    assert "Never put this in logs" not in safe_log
