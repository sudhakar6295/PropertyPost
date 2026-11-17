"""Broker-scoped, idempotent publication of an approved advert to Meta."""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone

from .meta_client import MetaAPIError, MetaClient, MetaMediaPending
from .meta_tokens import decrypt_access_token
from .models import (
    AdvertDraft,
    OpenPlotListing,
    SocialAccountConnection,
    SocialPublicationAttempt,
)


class SocialPublishingError(Exception):
    """Safe, stable publication failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def publish_approved_advert(
    *,
    broker,
    listing: OpenPlotListing,
    connection: SocialAccountConnection,
    platforms: list[str],
    poster_url: str,
    client: MetaClient,
) -> list[SocialPublicationAttempt]:
    """Publish an approved listing advert, recording one durable result per target."""
    allowed = {
        SocialPublicationAttempt.Platform.FACEBOOK,
        SocialPublicationAttempt.Platform.INSTAGRAM,
    }
    if not platforms or len(set(platforms)) != len(platforms) or not set(platforms) <= allowed:
        raise SocialPublishingError("invalid_platforms")
    if not isinstance(poster_url, str) or not poster_url.startswith("https://"):
        raise SocialPublishingError("invalid_poster_url")

    with transaction.atomic():
        locked_listing = OpenPlotListing.objects.select_for_update().get(pk=listing.pk)
        locked_connection = SocialAccountConnection.objects.select_for_update().get(
            pk=connection.pk
        )
        if locked_listing.broker_id != broker.pk or locked_connection.owner_id != broker.pk:
            raise SocialPublishingError("not_authorized")
        if locked_connection.status != SocialAccountConnection.Status.CONNECTED:
            raise SocialPublishingError("connection_unavailable")
        if not locked_connection.encrypted_page_access_token:
            raise SocialPublishingError("connection_unavailable")
        if locked_listing.status not in {
            OpenPlotListing.Status.APPROVED,
            OpenPlotListing.Status.PUBLISHED,
            OpenPlotListing.Status.FAILED,
        }:
            raise SocialPublishingError("advert_not_approved")
        advert = AdvertDraft.objects.filter(listing=locked_listing).first()
        if advert is None:
            raise SocialPublishingError("advert_not_approved")
        version_number = advert.version_number
        if "instagram" in platforms and not locked_connection.instagram_account_id:
            raise SocialPublishingError("instagram_unavailable")

        attempts = []
        for platform in platforms:
            existing = (
                SocialPublicationAttempt.objects.select_for_update()
                .filter(
                    listing=locked_listing,
                    social_connection=locked_connection,
                    advert_version_number=version_number,
                    platform=platform,
                )
                .first()
            )
            if existing:
                if (
                    existing.status != SocialPublicationAttempt.Status.FAILED
                    or existing.error_code
                    not in {
                        "token_invalid",
                        "token_expired",
                        "not_attempted",
                        "media_not_ready",
                    }
                ):
                    raise SocialPublishingError("publication_already_attempted")
                if existing.error_code == "media_not_ready" and (
                    platform != SocialPublicationAttempt.Platform.INSTAGRAM
                    or not existing.instagram_container_id
                ):
                    raise SocialPublishingError("publication_already_attempted")
                if existing.error_code not in {"not_attempted", "media_not_ready"} and (
                    locked_connection.updated_at <= existing.updated_at
                ):
                    raise SocialPublishingError("reconnect_required")
                existing.status = SocialPublicationAttempt.Status.PENDING
                existing.error_code = ""
                existing.external_post_id = ""
                existing.save(
                    update_fields=["status", "error_code", "external_post_id", "updated_at"]
                )
                attempts.append(existing)
            else:
                try:
                    with transaction.atomic():
                        attempts.append(
                            SocialPublicationAttempt.objects.create(
                                listing=locked_listing,
                                social_connection=locked_connection,
                                advert_version_number=version_number,
                                platform=platform,
                            )
                        )
                except IntegrityError as exc:
                    raise SocialPublishingError("publication_already_attempted") from exc
        locked_listing.status = OpenPlotListing.Status.PUBLISHING
        locked_listing.publication_platforms = list(platforms)
        locked_listing.save(update_fields=["status", "publication_platforms", "updated_at"])
        token_ciphertext = locked_connection.encrypted_page_access_token
        page_id = locked_connection.facebook_page_id
        instagram_id = locked_connection.instagram_account_id
        headline, caption, hashtags = advert.headline, advert.caption, list(advert.hashtags or [])

    try:
        page_token = decrypt_access_token(token_ciphertext)
    except (ValueError, TypeError, ImproperlyConfigured):
        _mark_reconnect(locked_connection.pk)
        _finish_attempts(attempts, error_code="token_invalid", uncertain=False)
        _update_listing_state(locked_listing.pk, version_number)
        raise SocialPublishingError("connection_unavailable") from None

    message = "\n\n".join(part for part in (headline, caption, " ".join(hashtags)) if part)
    for index, attempt in enumerate(attempts):
        try:
            if attempt.platform == SocialPublicationAttempt.Platform.FACEBOOK:
                external_id = client.publish_facebook_photo(
                    page_id, page_token, poster_url, message
                )
            else:
                external_id = client.publish_instagram_photo(
                    instagram_id,
                    page_token,
                    poster_url,
                    message,
                    container_id=attempt.instagram_container_id or None,
                )
            if not isinstance(external_id, str) or not external_id or len(external_id) > 100:
                _finish_attempts([attempt], error_code="invalid_meta_response", uncertain=True)
                continue
        except MetaMediaPending as exc:
            SocialPublicationAttempt.objects.filter(pk=attempt.pk).update(
                status=SocialPublicationAttempt.Status.FAILED,
                error_code="media_not_ready",
                instagram_container_id=exc.container_id,
                updated_at=timezone.now(),
            )
        except MetaAPIError as exc:
            expired = exc.code == "meta_190"
            uncertain = not exc.code.startswith("meta_")
            error_code = (
                "token_expired"
                if expired
                else ("publication_uncertain" if uncertain else "meta_rejected")
            )
            _finish_attempts([attempt], error_code=error_code, uncertain=uncertain)
            if expired:
                _mark_reconnect(locked_connection.pk)
                _finish_attempts(attempts[index + 1 :], error_code="token_expired", uncertain=False)
                break
        except Exception:
            # The request may have reached Meta; record uncertainty and never retry automatically.
            _finish_attempts([attempt], error_code="publication_uncertain", uncertain=True)
            _finish_attempts(attempts[index + 1 :], error_code="not_attempted", uncertain=False)
            break
        else:
            _mark_succeeded(attempt, external_id)

    _update_listing_state(locked_listing.pk, version_number)
    return list(
        SocialPublicationAttempt.objects.filter(
            pk__in=[attempt.pk for attempt in attempts]
        ).order_by("created_at", "pk")
    )


def _finish_attempts(attempts, *, error_code: str, uncertain: bool) -> None:
    status = (
        SocialPublicationAttempt.Status.UNCERTAIN
        if uncertain
        else SocialPublicationAttempt.Status.FAILED
    )
    SocialPublicationAttempt.objects.filter(pk__in=[item.pk for item in attempts]).update(
        status=status, error_code=error_code, updated_at=timezone.now()
    )


def _mark_succeeded(attempt, external_id: str) -> None:
    SocialPublicationAttempt.objects.filter(pk=attempt.pk).update(
        status=SocialPublicationAttempt.Status.SUCCEEDED,
        external_post_id=external_id,
        error_code="",
        updated_at=timezone.now(),
    )


def _mark_reconnect(connection_id) -> None:
    SocialAccountConnection.objects.filter(pk=connection_id).update(
        status=SocialAccountConnection.Status.RECONNECT_REQUIRED, updated_at=timezone.now()
    )


def _update_listing_state(listing_id, version_number) -> None:
    attempts = list(
        SocialPublicationAttempt.objects.filter(
            listing_id=listing_id,
            advert_version_number=version_number,
        ).values_list("status", flat=True)
    )
    if not attempts:
        return
    if any(status == SocialPublicationAttempt.Status.PENDING for status in attempts):
        status = OpenPlotListing.Status.PUBLISHING
    elif any(
        status
        in {SocialPublicationAttempt.Status.UNCERTAIN, SocialPublicationAttempt.Status.FAILED}
        for status in attempts
    ):
        status = OpenPlotListing.Status.FAILED
    elif all(status == SocialPublicationAttempt.Status.SUCCEEDED for status in attempts):
        status = OpenPlotListing.Status.PUBLISHED
    else:
        status = OpenPlotListing.Status.PUBLISHING
    OpenPlotListing.objects.filter(pk=listing_id).update(status=status, updated_at=timezone.now())
