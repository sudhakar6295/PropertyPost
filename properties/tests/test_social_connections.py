"""Persistence and token protection tests for broker-owned Meta connections."""

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings

from properties.meta_tokens import decrypt_access_token, encrypt_access_token
from properties.models import OpenPlotListing, SocialAccountConnection, SocialPublicationAttempt


@pytest.mark.django_db
def test_connections_are_isolated_by_owner(django_user_model):
    alice = django_user_model.objects.create_user(username="alice")
    bob = django_user_model.objects.create_user(username="bob")
    from cryptography.fernet import Fernet

    with override_settings(META_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")):
        alice_connection = SocialAccountConnection.objects.create(
            owner=alice,
            facebook_page_id="123456",
            page_name="Alice Page",
            encrypted_page_access_token=encrypt_access_token("secret-alice"),
        )
        bob_connection = SocialAccountConnection.objects.create(
            owner=bob,
            facebook_page_id="123456",
            page_name="Bob Page",
            encrypted_page_access_token=encrypt_access_token("secret-bob"),
        )

    assert list(alice.social_account_connections.all()) == [alice_connection]
    assert list(bob.social_account_connections.all()) == [bob_connection]
    assert alice_connection.owner_id != bob_connection.owner_id


@pytest.mark.django_db
def test_token_is_encrypted_at_rest_and_decrypts(django_user_model):
    from cryptography.fernet import Fernet

    user = django_user_model.objects.create_user(username="broker")
    token = "meta-page-secret-token"
    with override_settings(META_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")):
        ciphertext = encrypt_access_token(token)
        connection = SocialAccountConnection.objects.create(
            owner=user,
            facebook_page_id="123456",
            page_name="Broker Page",
            encrypted_page_access_token=ciphertext,
        )
        connection.refresh_from_db()
        assert connection.encrypted_page_access_token != token
        assert token not in connection.encrypted_page_access_token
        assert decrypt_access_token(connection.encrypted_page_access_token) == token
        assert token not in repr(connection)
        assert token not in str(connection)


def test_token_helpers_fail_closed_without_key(settings):
    settings.META_TOKEN_ENCRYPTION_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        encrypt_access_token("secret")
    with pytest.raises(ImproperlyConfigured):
        decrypt_access_token("ciphertext")


@pytest.mark.django_db
def test_owner_and_page_id_are_unique(django_user_model):
    from cryptography.fernet import Fernet

    user = django_user_model.objects.create_user(username="broker")
    key = Fernet.generate_key().decode("ascii")
    with override_settings(META_TOKEN_ENCRYPTION_KEY=key):
        fields = {
            "owner": user,
            "facebook_page_id": "123456",
            "page_name": "Broker Page",
            "encrypted_page_access_token": encrypt_access_token("secret"),
        }
        SocialAccountConnection.objects.create(**fields)
        with pytest.raises(IntegrityError), transaction.atomic():
            SocialAccountConnection.objects.create(**fields)


@pytest.mark.django_db
def test_disconnected_state_and_publication_owner_validation(django_user_model):
    from cryptography.fernet import Fernet

    owner = django_user_model.objects.create_user(username="owner")
    other = django_user_model.objects.create_user(username="other")
    key = Fernet.generate_key().decode("ascii")
    with override_settings(META_TOKEN_ENCRYPTION_KEY=key):
        connection = SocialAccountConnection.objects.create(
            owner=owner,
            facebook_page_id="123456",
            page_name="Owner Page",
            encrypted_page_access_token=encrypt_access_token("token-must-not-leak"),
        )
    connection.full_clean()
    disconnected = SocialAccountConnection.objects.create(
        owner=owner,
        facebook_page_id="654321",
        page_name="Disconnected Page",
        encrypted_page_access_token="",
        status=SocialAccountConnection.Status.DISCONNECTED,
    )
    disconnected.full_clean()
    with pytest.raises(ValidationError):
        SocialAccountConnection(
            owner=owner,
            facebook_page_id="654321",
            page_name="Missing token",
            status=SocialAccountConnection.Status.CONNECTED,
        ).full_clean()
    listing = OpenPlotListing.objects.create(
        broker=other,
        title="Test plot",
        location="Hyderabad",
        landmark="Near ORR",
        area="200.00",
        area_unit="sq_yd",
        total_price=100000,
        facing="east",
        approval_type="hmda",
        contact_number="+919876543210",
    )
    attempt = SocialPublicationAttempt(
        listing=listing,
        social_connection=connection,
        advert_version_number=1,
        platform=SocialPublicationAttempt.Platform.FACEBOOK,
        instagram_container_id="container-123",
    )
    assert attempt.instagram_container_id == "container-123"
    assert disconnected.status == SocialAccountConnection.Status.DISCONNECTED
    assert "token-must-not-leak" not in str(attempt)
    assert "token-must-not-leak" not in repr(attempt)
    with pytest.raises(ValidationError):
        attempt.full_clean()
