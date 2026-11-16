"""Advert history and durable Make request state."""

from django.utils import timezone

from .models import AdvertDraft, AdvertVersion, AutomationJob
from .repositories.django import _to_public_domain
from .serializers import serialize_public_details


def archive_current(listing):
    """Keep the current advert and published post IDs before changing it."""
    advert = AdvertDraft.objects.filter(listing=listing).first()
    if advert is None:
        return None
    version, _ = AdvertVersion.objects.get_or_create(
        listing=listing,
        version_number=advert.version_number,
        defaults={
            "template": advert.template,
            "poster_path": advert.poster_path,
            "headline": advert.headline,
            "caption": advert.caption,
            "hashtags": list(advert.hashtags),
            "public_details": serialize_public_details(_to_public_domain(listing)),
            "publication_results": dict(listing.publication_results),
        },
    )
    return version


def next_version_number(listing):
    latest = (
        AdvertVersion.objects.filter(listing=listing)
        .order_by("-version_number")
        .values_list("version_number", flat=True)
        .first()
    )
    return (latest or 0) + 1


def finish_job(listing, kind, request_id, *, succeeded, error_code=""):
    AutomationJob.objects.filter(
        listing=listing, kind=kind, request_id=request_id, status=AutomationJob.Status.PENDING
    ).update(
        status=AutomationJob.Status.SUCCEEDED if succeeded else AutomationJob.Status.FAILED,
        completed_at=timezone.now(),
        error_code=error_code,
    )
