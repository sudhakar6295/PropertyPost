"""Broker UI and ownership checks for direct Meta advert publishing."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from properties.meta_tokens import encrypt_access_token
from properties.models import (
    AdvertDraft,
    OpenPlotListing,
    SocialAccountConnection,
    SocialPublicationAttempt,
)


@pytest.fixture
def listing(django_user_model):
    broker = django_user_model.objects.create_user(username="publisher", password="secret")
    listing = OpenPlotListing.objects.create(
        broker=broker,
        title="Greenview plot",
        location="Hyderabad",
        landmark="Near park",
        area="240.00",
        area_unit=OpenPlotListing.AreaUnit.SQ_YD,
        total_price=4000000,
        facing=OpenPlotListing.Facing.EAST,
        approval_type=OpenPlotListing.ApprovalType.HMDA,
        contact_number="+919876543210",
        status=OpenPlotListing.Status.APPROVED,
    )
    AdvertDraft.objects.create(
        listing=listing,
        version_number=1,
        template="classic",
        poster_path="posters/greenview.png",
        headline="Greenview plot",
        caption="A plot near the park",
        hashtags=["#property"],
    )
    return listing


@pytest.fixture
def page(listing, settings):
    settings.META_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
    return SocialAccountConnection.objects.create(
        owner=listing.broker,
        facebook_page_id="123456",
        page_name="Greenview Realty",
        instagram_account_id="98765",
        instagram_username="greenview_realty",
        encrypted_page_access_token=encrypt_access_token("page-secret-token"),
    )


@pytest.fixture
def meta_settings(settings):
    settings.META_MULTI_TENANT_ENABLED = True
    settings.META_APP_ID = "test-app"
    settings.META_APP_SECRET = "test-secret"
    settings.META_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
    settings.META_GRAPH_VERSION = "v27.0"
    settings.META_REDIRECT_URI = "https://propertypost.example/accounts/social/meta/callback/"
    settings.AUTOMATION_HMAC_SECRET = "test-hmac-secret"
    settings.AUTOMATION_IMAGE_TTL_SECONDS = 600


@pytest.mark.django_db
def test_direct_publishing_requires_login_and_post(listing, page, meta_settings):
    url = reverse("publish-social", args=[listing.public_id])
    assert Client().post(url, {"connection": page.pk, "platform": "facebook"}).status_code == 302
    client = Client()
    client.force_login(listing.broker)
    assert client.get(url).status_code == 405


@pytest.mark.django_db
def test_legacy_make_publisher_refuses_when_multi_tenant_enabled(listing, meta_settings):
    client = Client()
    client.force_login(listing.broker)
    with patch("properties.broker_views.trigger_publication") as trigger:
        response = client.post(
            reverse("publish-plot", args=[listing.public_id]), {"platform": "facebook"}
        )
    assert response.status_code == 400
    trigger.assert_not_called()


@pytest.mark.django_db
def test_preview_offers_only_owned_pages_and_does_not_render_tokens(
    listing, page, django_user_model, meta_settings
):
    other = django_user_model.objects.create_user(username="other")
    other_page = SocialAccountConnection.objects.create(
        owner=other,
        facebook_page_id="654321",
        page_name="Private Other Page",
        encrypted_page_access_token="other-ciphertext",
    )
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("advert-preview", args=[listing.public_id]))
    assert response.status_code == 200
    assert b"Greenview Realty" in response.content
    assert b"Private Other Page" not in response.content
    assert page.encrypted_page_access_token.encode() not in response.content
    assert other_page.encrypted_page_access_token.encode() not in response.content
    assert reverse("publish-social", args=[listing.public_id]).encode() in response.content


@pytest.mark.django_db
def test_publish_social_passes_owned_page_and_signed_poster_url(listing, page, meta_settings):
    client = Client()
    client.force_login(listing.broker)
    with patch("properties.social_publish_views.publish_approved_advert") as publish:
        with override_settings(ALLOWED_HOSTS=["testserver", "attacker.example"]):
            response = client.post(
                reverse("publish-social", args=[listing.public_id]),
                {"connection": page.pk, "platform": "all"},
                HTTP_HOST="attacker.example",
            )
    assert response.status_code == 302
    assert response.url == reverse("published-result", args=[listing.public_id])
    kwargs = publish.call_args.kwargs
    assert kwargs["broker"] == listing.broker
    assert kwargs["listing"].pk == listing.pk
    assert kwargs["connection"].pk == page.pk
    assert kwargs["platforms"] == ["facebook", "instagram"]
    assert kwargs["poster_url"].startswith("https://propertypost.example/api/v1/listings/")
    assert "expires=" in kwargs["poster_url"] and "signature=" in kwargs["poster_url"]
    assert "format=jpeg" in kwargs["poster_url"]
    assert "page-secret-token" not in kwargs["poster_url"]


@pytest.mark.django_db
def test_publish_social_cannot_use_another_brokers_listing_or_page(
    listing, django_user_model, meta_settings
):
    owner = listing.broker
    other = django_user_model.objects.create_user(username="other")
    foreign_listing = OpenPlotListing.objects.create(
        broker=other,
        title="Other plot",
        location="Hyderabad",
        landmark="Near road",
        area="100.00",
        area_unit=OpenPlotListing.AreaUnit.SQ_YD,
        total_price=1000000,
        facing=OpenPlotListing.Facing.NORTH,
        approval_type=OpenPlotListing.ApprovalType.HMDA,
        contact_number="+919876543211",
        status=OpenPlotListing.Status.APPROVED,
    )
    foreign_page = SocialAccountConnection.objects.create(
        owner=other,
        facebook_page_id="654321",
        page_name="Other Page",
        encrypted_page_access_token="ciphertext",
    )
    client = Client()
    client.force_login(owner)
    foreign_listing_response = client.post(
        reverse("publish-social", args=[foreign_listing.public_id]),
        {"connection": foreign_page.pk, "platform": "facebook"},
    )
    assert foreign_listing_response.status_code == 404
    own_page_response = client.post(
        reverse("publish-social", args=[listing.public_id]),
        {"connection": foreign_page.pk, "platform": "facebook"},
    )
    assert own_page_response.status_code == 404


@pytest.mark.django_db
def test_publish_social_is_csrf_protected(listing, page, meta_settings):
    client = Client(enforce_csrf_checks=True)
    client.force_login(listing.broker)
    client.get(reverse("advert-preview", args=[listing.public_id]))
    response = client.post(
        reverse("publish-social", args=[listing.public_id]),
        {"connection": page.pk, "platform": "facebook"},
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_uncertain_result_is_explained_and_reconnect_is_linked(listing, page, meta_settings):
    page.status = SocialAccountConnection.Status.RECONNECT_REQUIRED
    page.save(update_fields=["status"])
    attempt = SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=page,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        status=SocialPublicationAttempt.Status.UNCERTAIN,
        error_code="publication_uncertain",
        request_id=uuid4(),
    )
    listing.status = OpenPlotListing.Status.FAILED
    listing.save(update_fields=["status"])
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("published-result", args=[listing.public_id]))
    assert response.status_code == 200
    assert b"Check this Page before taking another step" in response.content
    assert b"Manage social accounts" in response.content
    assert b"page-secret-token" not in response.content
    assert attempt.error_code.encode() not in response.content


@pytest.mark.django_db
def test_published_preview_offers_only_unattempted_platforms(listing, page, meta_settings):
    listing.status = OpenPlotListing.Status.PUBLISHED
    listing.save(update_fields=["status"])
    SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=page,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        status=SocialPublicationAttempt.Status.SUCCEEDED,
        external_post_id="fb-post-1",
        request_id=uuid4(),
    )
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("advert-preview", args=[listing.public_id]))
    assert response.status_code == 200
    assert b'value="instagram"' in response.content
    assert b'value="facebook"' not in response.content
    assert b'value="all"' not in response.content


@pytest.mark.django_db
def test_uncertain_failed_target_is_not_offered_for_retry(listing, page, meta_settings):
    listing.status = OpenPlotListing.Status.FAILED
    listing.save(update_fields=["status"])
    SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=page,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        status=SocialPublicationAttempt.Status.UNCERTAIN,
        error_code="publication_uncertain",
        request_id=uuid4(),
    )
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("advert-preview", args=[listing.public_id]))
    assert response.status_code == 200
    assert b"No failed target is currently safe to retry" in response.content
    assert b"Retry this target" not in response.content
    assert b"Check uncertain posts on the Page" in response.content


@pytest.mark.django_db
def test_expired_token_target_is_retryable_only_after_reconnect(listing, page, meta_settings):
    listing.status = OpenPlotListing.Status.FAILED
    listing.save(update_fields=["status"])
    attempt = SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=page,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        status=SocialPublicationAttempt.Status.FAILED,
        error_code="token_expired",
        request_id=uuid4(),
    )
    SocialPublicationAttempt.objects.filter(pk=attempt.pk).update(
        updated_at=timezone.now() - timedelta(minutes=1)
    )
    page.save(update_fields=["page_name", "updated_at"])
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("advert-preview", args=[listing.public_id]))
    assert response.status_code == 200
    assert b"Retry this target" in response.content


@pytest.mark.django_db
def test_incomplete_meta_config_shows_one_unavailable_notice(
    listing, page, meta_settings, settings
):
    settings.META_REDIRECT_URI = ""
    client = Client()
    client.force_login(listing.broker)
    response = client.get(reverse("advert-preview", args=[listing.public_id]))
    assert response.status_code == 200
    assert response.content.count(b"Direct Meta publishing is not available right now") == 1
    assert b"Post from this Page" not in response.content


@pytest.mark.django_db
def test_instagram_media_not_ready_attempt_can_be_safely_retried(listing, page, meta_settings):
    listing.status = OpenPlotListing.Status.FAILED
    listing.save(update_fields=["status"])
    SocialPublicationAttempt.objects.create(
        listing=listing,
        social_connection=page,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.INSTAGRAM,
        status=SocialPublicationAttempt.Status.FAILED,
        error_code="media_not_ready",
        instagram_container_id="987654321",
        request_id=uuid4(),
    )
    client = Client()
    client.force_login(listing.broker)

    response = client.get(reverse("advert-preview", args=[listing.public_id]))

    assert response.status_code == 200
    assert b"Instagram is still processing this media" in response.content
    assert b"Retry this target" in response.content
    assert b'value="instagram"' in response.content
    assert b"987654321" not in response.content
