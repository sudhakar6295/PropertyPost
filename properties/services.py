"""Configured persistence and private media services."""

from functools import lru_cache

from django.conf import settings

from .cloud import GoogleObjectStore, LocalFileObjectStore


@lru_cache(maxsize=1)
def object_store():
    if settings.OBJECT_ADAPTER == "google":
        return GoogleObjectStore(settings.GCS_PRIVATE_BUCKET, settings.GOOGLE_CLOUD_PROJECT)
    return LocalFileObjectStore()
