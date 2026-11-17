"""Broker-authorized direct Meta publication of an approved advert."""

import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .api_views import _poster_signature
from .broker_views import owned_plot
from .forms import PublicationForm
from .meta_client import MetaClient
from .models import OpenPlotListing, SocialAccountConnection
from .social_publishing import SocialPublishingError, publish_approved_advert


def _meta_publish_configured():
    callback = urlsplit(getattr(settings, "META_REDIRECT_URI", ""))
    return bool(
        getattr(settings, "META_MULTI_TENANT_ENABLED", False)
        and getattr(settings, "META_APP_ID", "")
        and getattr(settings, "META_APP_SECRET", "")
        and getattr(settings, "META_TOKEN_ENCRYPTION_KEY", "")
        and callback.scheme == "https"
        and callback.netloc
        and not callback.username
        and not callback.password
        and settings.AUTOMATION_HMAC_SECRET
    )


ERROR_MESSAGES = {
    "connection_unavailable": "Reconnect this Meta Page before publishing.",
    "reconnect_required": "Reconnect this Meta Page before retrying the target.",
    "instagram_unavailable": "This Page has no linked Instagram account available for publishing.",
    "publication_already_attempted": "This target already has a recorded attempt for this advert.",
    "safe_retry_required": (
        "This attempt cannot be retried safely. Contact support before trying again."
    ),
    "advert_not_approved": "Review and approve the advert before publishing.",
    "invalid_platforms": "Choose Facebook, Instagram, or both.",
    "invalid_poster_url": "The poster could not be prepared. Please try again.",
    "not_authorized": "That Page is not available for this broker account.",
}


@login_required
@require_POST
def publish_social(request, public_id):
    if not _meta_publish_configured():
        return HttpResponseBadRequest("Direct Meta publishing is not enabled.")

    listing = owned_plot(request, public_id)
    form = PublicationForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Choose Facebook, Instagram, or both.")
    if not hasattr(listing, "advert") or listing.status not in {
        OpenPlotListing.Status.APPROVED,
        OpenPlotListing.Status.PUBLISHED,
        OpenPlotListing.Status.FAILED,
    }:
        return HttpResponseBadRequest("Review and approve the advert before publishing.")

    try:
        connection_id = int(request.POST.get("connection", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Choose a connected Facebook Page.")
    connection = get_object_or_404(
        SocialAccountConnection,
        pk=connection_id,
        owner=request.user,
        status=SocialAccountConnection.Status.CONNECTED,
    )

    expires = int(time.time()) + min(max(int(settings.AUTOMATION_IMAGE_TTL_SECONDS), 60), 3600)
    poster_path = reverse("automation-poster", args=[listing.public_id])
    signature = _poster_signature(listing.public_id, expires)
    callback = urlsplit(settings.META_REDIRECT_URI)
    poster_url = (
        f"https://{callback.netloc}{poster_path}?expires={expires}"
        f"&signature={signature}&format=jpeg"
    )
    already_posted = set((listing.publication_results or {}).keys())
    if already_posted.intersection(form.platforms):
        messages.error(
            request,
            "One or more selected platforms already have a post. Choose another platform.",
        )
        return redirect("advert-preview", public_id=listing.public_id)
    try:
        client = MetaClient(
            app_id=settings.META_APP_ID,
            app_secret=settings.META_APP_SECRET,
            graph_version=settings.META_GRAPH_VERSION,
        )
        publish_approved_advert(
            broker=request.user,
            listing=listing,
            connection=connection,
            platforms=form.platforms,
            poster_url=poster_url,
            client=client,
        )
    except SocialPublishingError as exc:
        safe_message = ERROR_MESSAGES.get(exc.code, "Meta could not publish this advert.")
        messages.error(request, safe_message)
        return redirect("advert-preview", public_id=listing.public_id)
    except ValueError:
        messages.error(
            request,
            "Meta publishing is not configured correctly. Please contact support.",
        )
        return redirect("advert-preview", public_id=listing.public_id)

    return redirect("published-result", public_id=listing.public_id)
