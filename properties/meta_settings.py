"""Validation for production Meta integration configuration."""

import re
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

META_CALLBACK_PATH = "/accounts/social/meta/callback/"


def validate_meta_configuration(
    *,
    enabled: bool,
    app_id: str,
    app_secret: str,
    encryption_key: str,
    redirect_uri: str,
    graph_version: str = "v27.0",
) -> None:
    """Require and validate credentials only when the integration is enabled."""
    if not enabled:
        return

    values = {
        "META_APP_ID": app_id,
        "META_APP_SECRET": app_secret,
        "META_TOKEN_ENCRYPTION_KEY": encryption_key,
        "META_REDIRECT_URI": redirect_uri,
    }
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise ImproperlyConfigured(
            f"Meta integration is enabled but required settings are empty: {', '.join(missing)}."
        )

    try:
        Fernet(encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured("META_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc

    try:
        parsed = urlsplit(redirect_uri)
        valid_redirect = (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and bool(parsed.hostname)
            and parsed.port in (None, 443)
            and parsed.path == META_CALLBACK_PATH
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid_redirect = False
    if not valid_redirect:
        raise ImproperlyConfigured(
            "META_REDIRECT_URI must be HTTPS and use the Meta callback path."
        )

    if not re.fullmatch(r"v\d+\.\d+", graph_version):
        raise ImproperlyConfigured("META_GRAPH_VERSION must use the vN.N format.")
