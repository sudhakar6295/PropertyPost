"""Fail-closed validation for enabled production Meta configuration."""

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from properties.meta_settings import validate_meta_configuration

VALID_SETTINGS = {
    "enabled": True,
    "app_id": "app-id",
    "app_secret": "app-secret",
    "encryption_key": Fernet.generate_key().decode("ascii"),
    "redirect_uri": "https://example.com/accounts/social/meta/callback/",
    "graph_version": "v27.0",
}


def test_disabled_meta_configuration_keeps_credentials_optional():
    validate_meta_configuration(
        enabled=False, app_id="", app_secret="", encryption_key="", redirect_uri=""
    )


def test_enabled_meta_configuration_accepts_valid_settings():
    validate_meta_configuration(**VALID_SETTINGS)


@pytest.mark.parametrize(
    "field",
    ["app_id", "app_secret", "encryption_key", "redirect_uri"],
)
def test_enabled_meta_configuration_requires_each_setting(field):
    values = VALID_SETTINGS | {field: ""}
    with pytest.raises(ImproperlyConfigured):
        validate_meta_configuration(**values)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://example.com/accounts/social/meta/callback/",
        "https://example.com/wrong/path/",
        "https:///accounts/social/meta/callback/",
        "https://example.com:invalid/accounts/social/meta/callback/",
        "https://user:password@example.com/accounts/social/meta/callback/",
        "https://example.com/accounts/social/meta/callback/?code=secret",
        "https://example.com/accounts/social/meta/callback/#fragment",
    ],
)
def test_enabled_meta_configuration_rejects_unsafe_redirect(redirect_uri):
    with pytest.raises(ImproperlyConfigured):
        validate_meta_configuration(**(VALID_SETTINGS | {"redirect_uri": redirect_uri}))


def test_enabled_meta_configuration_rejects_invalid_fernet_key_without_echoing_it():
    secret = "invalid-secret-value"
    with pytest.raises(ImproperlyConfigured) as error:
        validate_meta_configuration(**(VALID_SETTINGS | {"encryption_key": secret}))
    assert secret not in str(error.value)


@pytest.mark.parametrize("graph_version", ["27.0", "v27", "latest"])
def test_enabled_meta_configuration_rejects_invalid_graph_version(graph_version):
    with pytest.raises(ImproperlyConfigured):
        validate_meta_configuration(**(VALID_SETTINGS | {"graph_version": graph_version}))
