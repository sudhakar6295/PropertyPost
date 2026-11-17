from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone

from properties.meta_client import MetaAPIError, MetaMediaPending
from properties.meta_tokens import encrypt_access_token
from properties.models import (
    AdvertDraft,
    OpenPlotListing,
    SocialAccountConnection,
    SocialPublicationAttempt,
)
from properties.social_publishing import SocialPublishingError, publish_approved_advert


class FakeMetaClient:
    def __init__(self, *, fail=None):
        self.fail = fail or {}
        self.calls = []

    def publish_facebook_photo(self, page_id, token, poster_url, message):
        self.calls.append(("facebook", page_id, token, poster_url, message))
        if "facebook" in self.fail:
            raise self.fail["facebook"]
        return "fb-post-1"

    def publish_instagram_photo(self, account_id, token, poster_url, caption, container_id=None):
        self.calls.append(("instagram", account_id, token, poster_url, caption, container_id))
        if "instagram" in self.fail:
            raise self.fail["instagram"]
        return "ig-post-1"


@pytest.fixture
def setup_social(django_user_model, settings):
    key = Fernet.generate_key().decode("ascii")
    settings.META_TOKEN_ENCRYPTION_KEY = key
    broker = django_user_model.objects.create_user(username="broker")
    other = django_user_model.objects.create_user(username="other")
    listing = OpenPlotListing.objects.create(
        broker=broker,
        title="Public listing",
        location="Hyderabad",
        landmark="Near public park",
        area="200.00",
        area_unit="sq_yd",
        total_price=500000,
        facing="east",
        approval_type="hmda",
        contact_number="+919876543210",
        status=OpenPlotListing.Status.APPROVED,
        publication_results={"facebook": "make-post-previous"},
    )
    AdvertDraft.objects.create(
        listing=listing,
        version_number=3,
        template="classic",
        poster_path="private/poster.png",
        headline="Approved public headline",
        caption="Approved public caption",
        hashtags=["#property"],
    )
    connection = SocialAccountConnection.objects.create(
        owner=broker,
        facebook_page_id="12345",
        page_name="Broker page",
        instagram_account_id="98765",
        instagram_username="broker_handle",
        encrypted_page_access_token=encrypt_access_token("decrypted-page-token"),
    )
    other_connection = SocialAccountConnection.objects.create(
        owner=other,
        facebook_page_id="12345",
        page_name="Other page",
        encrypted_page_access_token=encrypt_access_token("other-token"),
    )
    return broker, other, listing, connection, other_connection


def publish(broker, listing, connection, platforms, client):
    return publish_approved_advert(
        broker=broker,
        listing=listing,
        connection=connection,
        platforms=platforms,
        poster_url="https://cdn.example.test/signed/poster?sig=safe",
        client=client,
    )


@pytest.mark.django_db
def test_rejects_cross_broker_listing_or_connection(setup_social):
    broker, other, listing, connection, other_connection = setup_social
    with pytest.raises(SocialPublishingError) as exc:
        publish(other, listing, connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "not_authorized"
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, other_connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "not_authorized"
    assert not SocialPublicationAttempt.objects.exists()


@pytest.mark.django_db
def test_success_records_attempt_and_refuses_duplicate_target(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient()
    attempt = publish(broker, listing, connection, ["facebook"], client)[0]
    assert attempt.status == SocialPublicationAttempt.Status.SUCCEEDED
    assert attempt.external_post_id == "fb-post-1"
    assert attempt.advert_version_number == 3
    assert client.calls[0][2] == "decrypted-page-token"
    assert "Approved public headline" in client.calls[0][-1]
    assert listing.publication_results == {"facebook": "make-post-previous"}
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.PUBLISHED
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], client)
    assert exc.value.code == "publication_already_attempted"
    assert len(client.calls) == 1


@pytest.mark.django_db
def test_published_listing_can_publish_to_another_owned_page(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient()
    publish(broker, listing, connection, ["facebook"], client)
    second_connection = SocialAccountConnection.objects.create(
        owner=broker,
        facebook_page_id="22222",
        page_name="Second page",
        encrypted_page_access_token=connection.encrypted_page_access_token,
    )
    result = publish(broker, listing, second_connection, ["facebook"], client)
    assert result[0].status == SocialPublicationAttempt.Status.SUCCEEDED
    assert SocialPublicationAttempt.objects.count() == 2
    assert listing.publication_results == {"facebook": "make-post-previous"}


@pytest.mark.django_db
def test_partial_success_keeps_target_results_and_is_not_repeated(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient(fail={"instagram": MetaAPIError("meta_100")})
    attempts = publish(broker, listing, connection, ["facebook", "instagram"], client)
    assert [attempt.status for attempt in attempts] == [
        SocialPublicationAttempt.Status.SUCCEEDED,
        SocialPublicationAttempt.Status.FAILED,
    ]
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.FAILED
    assert listing.publication_results == {"facebook": "make-post-previous"}
    assert attempts[1].error_code == "meta_rejected"
    with pytest.raises(SocialPublishingError):
        publish(broker, listing, connection, ["facebook", "instagram"], client)


@pytest.mark.django_db
def test_meta_rejection_cannot_be_retried(setup_social):
    broker, _, listing, connection, _ = setup_social
    failing = FakeMetaClient(fail={"facebook": MetaAPIError("meta_100")})
    first = publish(broker, listing, connection, ["facebook"], failing)[0]
    assert first.status == SocialPublicationAttempt.Status.FAILED
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "publication_already_attempted"


@pytest.mark.django_db
def test_expired_token_requires_reconnect_and_records_safe_failure(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient(fail={"facebook": MetaAPIError("meta_190")})
    attempt = publish(broker, listing, connection, ["facebook"], client)[0]
    connection.refresh_from_db()
    assert connection.status == SocialAccountConnection.Status.RECONNECT_REQUIRED
    assert attempt.status == SocialPublicationAttempt.Status.FAILED
    assert attempt.error_code == "token_expired"
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "connection_unavailable"
    connection.status = SocialAccountConnection.Status.CONNECTED
    connection.encrypted_page_access_token = encrypt_access_token("new-page-token")
    connection.save()
    SocialAccountConnection.objects.filter(pk=connection.pk).update(
        updated_at=timezone.now() + timedelta(seconds=1)
    )
    retried = publish(broker, listing, connection, ["facebook"], FakeMetaClient())[0]
    assert retried.status == SocialPublicationAttempt.Status.SUCCEEDED


@pytest.mark.django_db
def test_unknown_outcome_is_uncertain_and_cannot_be_retried(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient(fail={"facebook": MetaAPIError("network_error")})
    attempt = publish(broker, listing, connection, ["facebook"], client)[0]
    assert attempt.status == SocialPublicationAttempt.Status.UNCERTAIN
    assert attempt.error_code == "publication_uncertain"
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "publication_already_attempted"


@pytest.mark.django_db
def test_unexpected_client_error_marks_uncertain_and_stops_remaining_targets(setup_social):
    broker, _, listing, connection, _ = setup_social
    client = FakeMetaClient(fail={"facebook": RuntimeError("secret token in raw error")})
    attempts = publish(broker, listing, connection, ["facebook", "instagram"], client)
    assert attempts[0].status == SocialPublicationAttempt.Status.UNCERTAIN
    assert attempts[0].error_code == "publication_uncertain"
    assert attempts[1].status == SocialPublicationAttempt.Status.FAILED
    assert attempts[1].error_code == "not_attempted"
    assert [call[0] for call in client.calls] == ["facebook"]
    assert "secret token" not in repr(attempts)
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.FAILED
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook", "instagram"], FakeMetaClient())
    assert exc.value.code == "publication_already_attempted"


@pytest.mark.django_db
def test_not_attempted_target_can_be_retried_without_repeating_uncertain_target(setup_social):
    broker, _, listing, connection, _ = setup_social
    first = FakeMetaClient(fail={"facebook": RuntimeError("unavailable")})
    attempts = publish(broker, listing, connection, ["facebook", "instagram"], first)
    facebook_attempt, instagram_attempt = attempts
    assert facebook_attempt.status == SocialPublicationAttempt.Status.UNCERTAIN
    assert instagram_attempt.error_code == "not_attempted"

    second = FakeMetaClient()
    retried = publish(broker, listing, connection, ["instagram"], second)
    assert len(retried) == 1
    assert retried[0].pk == instagram_attempt.pk
    assert retried[0].status == SocialPublicationAttempt.Status.SUCCEEDED
    assert [call[0] for call in second.calls] == ["instagram"]
    facebook_attempt.refresh_from_db()
    assert facebook_attempt.status == SocialPublicationAttempt.Status.UNCERTAIN
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.FAILED


@pytest.mark.django_db
def test_instagram_pending_saves_and_reuses_container_after_partial_facebook_success(setup_social):
    broker, _, listing, connection, _ = setup_social
    pending = FakeMetaClient(fail={"instagram": MetaMediaPending("97531")})
    first = publish(broker, listing, connection, ["facebook", "instagram"], pending)
    facebook_attempt, instagram_attempt = first
    assert facebook_attempt.status == SocialPublicationAttempt.Status.SUCCEEDED
    assert instagram_attempt.status == SocialPublicationAttempt.Status.FAILED
    assert instagram_attempt.error_code == "media_not_ready"
    assert instagram_attempt.instagram_container_id == "97531"

    resume = FakeMetaClient()
    second = publish(broker, listing, connection, ["instagram"], resume)
    assert second[0].status == SocialPublicationAttempt.Status.SUCCEEDED
    assert second[0].instagram_container_id == "97531"
    assert resume.calls[0][-1] == "97531"
    facebook_attempt.refresh_from_db()
    assert facebook_attempt.status == SocialPublicationAttempt.Status.SUCCEEDED
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.PUBLISHED


@pytest.mark.django_db
def test_uncertain_instagram_resume_cannot_issue_another_publish(setup_social):
    broker, _, listing, connection, _ = setup_social
    pending = FakeMetaClient(fail={"instagram": MetaMediaPending("97532")})
    publish(broker, listing, connection, ["instagram"], pending)

    uncertain = FakeMetaClient(fail={"instagram": MetaAPIError("network_error")})
    attempt = publish(broker, listing, connection, ["instagram"], uncertain)[0]
    assert uncertain.calls[0][-1] == "97532"
    assert attempt.status == SocialPublicationAttempt.Status.UNCERTAIN

    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["instagram"], FakeMetaClient())
    assert exc.value.code == "publication_already_attempted"


@pytest.mark.django_db
def test_failed_target_does_not_block_a_different_owned_target(setup_social):
    broker, _, listing, connection, _ = setup_social
    failed = FakeMetaClient(fail={"facebook": MetaAPIError("meta_100")})
    publish(broker, listing, connection, ["facebook"], failed)
    second = SocialAccountConnection.objects.create(
        owner=broker,
        facebook_page_id="22222",
        page_name="Second page",
        encrypted_page_access_token=connection.encrypted_page_access_token,
    )
    result = publish(broker, listing, second, ["facebook"], FakeMetaClient())
    assert result[0].status == SocialPublicationAttempt.Status.SUCCEEDED


@pytest.mark.django_db
def test_local_decrypt_failure_fails_listing_without_network_call(setup_social):
    broker, _, listing, connection, _ = setup_social
    connection.encrypted_page_access_token = "not-valid-ciphertext"
    connection.save(update_fields=["encrypted_page_access_token", "updated_at"])
    client = FakeMetaClient()
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], client)
    assert exc.value.code == "connection_unavailable"
    assert not client.calls
    listing.refresh_from_db()
    assert listing.status == OpenPlotListing.Status.FAILED
    attempt = SocialPublicationAttempt.objects.get()
    assert attempt.status == SocialPublicationAttempt.Status.FAILED
    assert attempt.error_code == "token_invalid"


@pytest.mark.django_db
def test_invalid_state_platform_and_missing_instagram_are_rejected(setup_social):
    broker, _, listing, connection, _ = setup_social
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["threads"], FakeMetaClient())
    assert exc.value.code == "invalid_platforms"
    connection.instagram_account_id = ""
    connection.save(update_fields=["instagram_account_id"])
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["instagram"], FakeMetaClient())
    assert exc.value.code == "instagram_unavailable"
    listing.status = OpenPlotListing.Status.DRAFT
    listing.save(update_fields=["status"])
    with pytest.raises(SocialPublishingError) as exc:
        publish(broker, listing, connection, ["facebook"], FakeMetaClient())
    assert exc.value.code == "advert_not_approved"
    assert not SocialPublicationAttempt.objects.exists()
