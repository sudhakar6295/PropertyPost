"""Authenticated broker views for connecting and managing Meta Pages."""

import time
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.test import Client, override_settings
from django.urls import reverse

from properties.meta_client import MetaPage
from properties.meta_tokens import decrypt_access_token
from properties.models import SocialAccountConnection

META_SETTINGS = {
    "META_APP_ID": "test-app-id",
    "META_APP_SECRET": "test-app-secret",
    "META_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
    "META_GRAPH_VERSION": "v27.0",
    "META_REDIRECT_URI": "https://propertypost.example/accounts/social/meta/callback/",
    "META_MULTI_TENANT_ENABLED": True,
}


@pytest.fixture
def broker(django_user_model):
    return django_user_model.objects.create_user(username="broker", password="secret")


@pytest.mark.django_db
def test_social_pages_require_login(broker):
    client = Client()
    for route in ("social-accounts", "meta-connect", "meta-callback"):
        response = client.get(reverse(route))
        assert response.status_code == 302
        assert response.url.startswith(reverse("broker-login"))


@pytest.mark.django_db
def test_missing_meta_config_shows_unavailable_and_connect_is_safe(broker, settings):
    settings.META_APP_ID = ""
    client = Client()
    client.force_login(broker)
    response = client.get(reverse("social-accounts"))
    assert response.status_code == 200
    assert b"not available" in response.content
    assert client.get(reverse("meta-connect")).status_code == 302


@pytest.mark.django_db
@override_settings(**META_SETTINGS)
def test_connect_uses_random_session_state_and_fixed_redirect_uri(broker):
    client = Client()
    client.force_login(broker)
    with patch("properties.social_views._client") as make_client:
        make_client.return_value.authorization_url.return_value = "https://facebook.example/oauth"
        with override_settings(ALLOWED_HOSTS=["testserver", "attacker.example"]):
            response = client.get(reverse("meta-connect"), HTTP_HOST="attacker.example")
    assert response.status_code == 302
    assert response.url == "https://facebook.example/oauth"
    args = make_client.return_value.authorization_url.call_args.kwargs
    assert args["redirect_uri"] == META_SETTINGS["META_REDIRECT_URI"]
    assert args["state"]
    session = client.session
    assert session["meta_oauth_state"] == args["state"]
    assert session["meta_oauth_user_id"] == str(broker.pk)


@pytest.mark.django_db
@override_settings(**META_SETTINGS)
def test_callback_rejects_expired_state_and_state_is_one_use(broker):
    client = Client()
    client.force_login(broker)
    session = client.session
    session.update(
        {
            "meta_oauth_state": "expected",
            "meta_oauth_state_expiry": int(time.time()) - 1,
            "meta_oauth_user_id": str(broker.pk),
        }
    )
    session.save()
    with patch("properties.social_views._client") as make_client:
        response = client.get(reverse("meta-callback"), {"state": "expected", "code": "one"})
        assert response.status_code == 302
        make_client.assert_not_called()
    assert "meta_oauth_state" not in client.session


@pytest.mark.django_db
@override_settings(**META_SETTINGS)
def test_callback_saves_only_authenticated_owner_pages_and_never_renders_token(
    broker, django_user_model
):
    other = django_user_model.objects.create_user(username="other")
    client = Client()
    client.force_login(broker)
    session = client.session
    session.update(
        {
            "meta_oauth_state": "valid",
            "meta_oauth_state_expiry": int(time.time()) + 120,
            "meta_oauth_user_id": str(broker.pk),
        }
    )
    session.save()
    page = MetaPage("12345", "Broker Page", "page-secret", "888", "broker_ig")
    with patch("properties.social_views._client") as make_client:
        mock = make_client.return_value
        mock.exchange_code.return_value = {"access_token": "short-secret"}
        mock.exchange_long_lived_token.return_value = {"access_token": "long-secret"}
        mock.list_pages.return_value = [page]
        response = client.get(reverse("meta-callback"), {"state": "valid", "code": "auth-code"})
    assert response.status_code == 302
    mock.exchange_code.assert_called_once_with("auth-code", META_SETTINGS["META_REDIRECT_URI"])
    account = SocialAccountConnection.objects.get(owner=broker, facebook_page_id="12345")
    assert account.page_name == "Broker Page"
    assert decrypt_access_token(account.encrypted_page_access_token) == "page-secret"
    assert not SocialAccountConnection.objects.filter(owner=other).exists()
    response = client.get(reverse("social-accounts"))
    assert b"Broker Page" in response.content
    assert b"broker_ig" in response.content
    for secret in (b"page-secret", b"short-secret", b"long-secret"):
        assert secret not in response.content
    assert "meta_oauth_state" not in client.session
    replay = client.get(reverse("meta-callback"), {"state": "valid", "code": "auth-code"})
    assert replay.status_code == 302
    assert SocialAccountConnection.objects.filter(owner=broker).count() == 1


@pytest.mark.django_db
@override_settings(**META_SETTINGS)
def test_callback_rejects_cross_user_session(broker, django_user_model):
    other = django_user_model.objects.create_user(username="other")
    client = Client()
    client.force_login(broker)
    session = client.session
    session.update(
        {
            "meta_oauth_state": "valid",
            "meta_oauth_state_expiry": int(time.time()) + 120,
            "meta_oauth_user_id": str(other.pk),
        }
    )
    session.save()
    with patch("properties.social_views._client") as make_client:
        client.get(reverse("meta-callback"), {"state": "valid", "code": "auth-code"})
        make_client.assert_not_called()
    assert not SocialAccountConnection.objects.exists()


@pytest.mark.django_db
@override_settings(**META_SETTINGS)
def test_disconnect_requires_csrf_post_and_is_owner_scoped(broker, django_user_model):
    other = django_user_model.objects.create_user(username="other")
    from properties.meta_tokens import encrypt_access_token

    account = SocialAccountConnection.objects.create(
        owner=broker,
        facebook_page_id="12345",
        page_name="Broker Page",
        encrypted_page_access_token=encrypt_access_token("secret"),
    )
    foreign = SocialAccountConnection.objects.create(
        owner=other,
        facebook_page_id="67890",
        page_name="Other Page",
        encrypted_page_access_token=encrypt_access_token("other-secret"),
    )
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(broker)
    url = reverse("meta-disconnect", args=[account.pk])
    assert csrf_client.post(url).status_code == 403
    csrf_client.get(reverse("social-accounts"))
    token = csrf_client.cookies["csrftoken"].value
    assert csrf_client.post(url, HTTP_X_CSRFTOKEN=token).status_code == 302
    account.refresh_from_db()
    foreign.refresh_from_db()
    assert account.encrypted_page_access_token == ""
    assert account.status == SocialAccountConnection.Status.DISCONNECTED
    assert foreign.encrypted_page_access_token != ""
    assert Client().post(reverse("meta-disconnect", args=[foreign.pk])).status_code == 302
