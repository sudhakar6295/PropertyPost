"""Versioned, HMAC protected automation boundary."""

import hashlib
import hmac
import json
import time
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .captions import validate_caption
from .models import AdvertDraft, AutomationReceipt, OpenPlotListing, PlotPhoto
from .repositories.django import _to_public_domain
from .serializers import serialize_public_details
from .services import object_store


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _mac(message: bytes) -> str:
    return hmac.new(settings.AUTOMATION_HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()


def _authenticated(request) -> bool:
    if not settings.AUTOMATION_HMAC_SECRET:
        return False
    timestamp = request.headers.get("X-PropertyPost-Timestamp", "")
    signature = request.headers.get("X-PropertyPost-Signature", "")
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - sent_at) > settings.AUTOMATION_MAX_SKEW_SECONDS:
        return False
    signed = b"\n".join(
        (request.method.encode(), request.path.encode(), timestamp.encode(), request.body)
    )
    return hmac.compare_digest(signature, _mac(signed))


def _image_signature(public_id, photo_id, expires):
    return _mac(f"image\n{public_id}\n{photo_id}\n{expires}".encode())


@csrf_exempt
def automation_input(request, public_id):
    if request.method != "GET":
        return _error("GET required", 405)
    if not _authenticated(request):
        return _error("Invalid or expired signature", 401)
    listing = get_object_or_404(OpenPlotListing, public_id=public_id)
    if listing.broker_id is None:
        return _error("Listing has no owner", 403)
    if listing.status != OpenPlotListing.Status.GENERATING:
        return _error("Listing is not awaiting generation", 409)
    expires = int(time.time()) + settings.AUTOMATION_IMAGE_TTL_SECONDS
    images = []
    for photo in listing.photos.all():
        path = reverse("automation-image", args=[public_id, photo.pk])
        signature = _image_signature(public_id, photo.pk, expires)
        images.append(
            {
                "url": request.build_absolute_uri(
                    f"{path}?expires={expires}&signature={signature}"
                ),
                "is_main": photo.is_main,
                "sort_order": photo.sort_order,
                "content_type": photo.content_type,
            }
        )
    return JsonResponse(
        {
            "id": str(public_id),
            "status": listing.status,
            "public_details": serialize_public_details(_to_public_domain(listing)),
            "images": images,
        }
    )


def signed_image(request, public_id, photo_id):
    if request.method != "GET" or not settings.AUTOMATION_HMAC_SECRET:
        return _error("Unavailable", 403)
    try:
        expires = int(request.GET.get("expires", ""))
    except ValueError:
        return _error("Invalid image link", 403)
    if expires < int(time.time()) or expires > int(time.time()) + 3600:
        return _error("Expired image link", 403)
    if not hmac.compare_digest(
        request.GET.get("signature", ""), _image_signature(public_id, photo_id, expires)
    ):
        return _error("Invalid image link", 403)
    photo = get_object_or_404(PlotPhoto, pk=photo_id, listing__public_id=public_id)
    response = HttpResponse(
        object_store().download(photo.object_path), content_type=photo.content_type
    )
    response["Cache-Control"] = "private, max-age=60"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _payload(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        request_id = UUID(data["request_id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None, None
    return data, request_id


def _callback(request, public_id, kind):
    if request.method != "POST":
        return _error("POST required", 405)
    if not _authenticated(request):
        return _error("Invalid or expired signature", 401)
    data, request_id = _payload(request)
    if data is None:
        return _error("Invalid JSON or request_id", 400)
    listing = get_object_or_404(OpenPlotListing, public_id=public_id)
    digest = hashlib.sha256(request.body).hexdigest()
    with transaction.atomic():
        listing = OpenPlotListing.objects.select_for_update().get(pk=listing.pk)
        previous = AutomationReceipt.objects.filter(
            listing=listing, kind=kind, request_id=request_id
        ).first()
        if previous:
            if previous.body_sha256 != digest:
                return _error("request_id already used with different content", 409)
            return JsonResponse(previous.response)
        if kind == AutomationReceipt.Kind.GENERATION:
            result = _generation(listing, data)
        else:
            result = _publication(listing, data)
        if isinstance(result, JsonResponse):
            return result
        AutomationReceipt.objects.create(
            listing=listing, kind=kind, request_id=request_id, body_sha256=digest, response=result
        )
    return JsonResponse(result)


def _generation(listing, data):
    if set(data) == {"request_id", "status", "error"} and data["status"] == "failed":
        if listing.status != OpenPlotListing.Status.GENERATING:
            return _error("Listing is not awaiting a generation result", 409)
        if not isinstance(data["error"], str) or len(data["error"]) > 300:
            return _error("Invalid error message", 400)
        listing.status = OpenPlotListing.Status.FAILED
        listing.save(update_fields=["status", "updated_at"])
        return {"request_id": data["request_id"], "status": "failed"}
    if set(data) != {"request_id", "status", "headline", "caption", "hashtags", "poster_path"}:
        return _error("Invalid generation result fields", 400)
    if listing.status != OpenPlotListing.Status.GENERATING or data["status"] != "succeeded":
        return _error("Listing is not awaiting a generation result", 409)
    try:
        caption = validate_caption({key: data[key] for key in ("headline", "caption", "hashtags")})
    except ValueError:
        return _error("Invalid caption", 400)
    path = data["poster_path"]
    if (
        not isinstance(path, str)
        or not path.startswith(f"posters/{listing.broker_id}/{listing.public_id}/")
        or not path.endswith(".png")
        or ".." in path
    ):
        return _error("Invalid poster path", 400)
    AdvertDraft.objects.update_or_create(
        listing=listing,
        defaults={
            "template": "external",
            "poster_path": path,
            "headline": caption.headline,
            "caption": caption.caption,
            "hashtags": list(caption.hashtags),
        },
    )
    listing.status = OpenPlotListing.Status.REVIEW
    listing.save(update_fields=["status", "updated_at"])
    return {"request_id": data["request_id"], "status": "review"}


def _publication(listing, data):
    if set(data) == {"request_id", "status", "error"} and data["status"] == "failed":
        if listing.status != OpenPlotListing.Status.PUBLISHING:
            return _error("Listing is not awaiting a publication result", 409)
        if not isinstance(data["error"], str) or len(data["error"]) > 300:
            return _error("Invalid error message", 400)
        listing.status = OpenPlotListing.Status.FAILED
        listing.save(update_fields=["status", "updated_at"])
        return {"request_id": data["request_id"], "status": "failed"}
    if set(data) != {"request_id", "status", "external_post_id"}:
        return _error("Invalid publication result fields", 400)
    if listing.status != OpenPlotListing.Status.PUBLISHING or data["status"] != "succeeded":
        return _error("Listing is not awaiting a publication result", 409)
    post_id = data["external_post_id"]
    if not isinstance(post_id, str) or not post_id.strip() or len(post_id) > 200:
        return _error("Invalid external post ID", 400)
    listing.status = OpenPlotListing.Status.PUBLISHED
    listing.save(update_fields=["status", "updated_at"])
    return {"request_id": data["request_id"], "status": "published", "external_post_id": post_id}


@csrf_exempt
def generation_result(request, public_id):
    return _callback(request, public_id, AutomationReceipt.Kind.GENERATION)


@csrf_exempt
def publication_result(request, public_id):
    return _callback(request, public_id, AutomationReceipt.Kind.PUBLICATION)
