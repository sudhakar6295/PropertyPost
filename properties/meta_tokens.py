"""Encryption helpers for Meta Page access tokens."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    key = getattr(settings, "META_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured("META_TOKEN_ENCRYPTION_KEY is required to use Meta tokens.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured("META_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def encrypt_access_token(token: str) -> str:
    if not token:
        raise ValueError("Access token cannot be empty.")
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_access_token(encrypted_token: str) -> str:
    try:
        return _fernet().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as exc:
        raise ValueError("Encrypted access token is invalid.") from exc
