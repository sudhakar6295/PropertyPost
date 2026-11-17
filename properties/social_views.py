"""Broker-owned Meta account connection flow."""

import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .meta_client import MetaAPIError, MetaClient
from .meta_tokens import encrypt_access_token
from .models import SocialAccountConnection

OAUTH_STATE_KEY = "meta_oauth_state"
OAUTH_STATE_EXPIRY_KEY = "meta_oauth_state_expiry"
OAUTH_USER_KEY = "meta_oauth_user_id"
OAUTH_STATE_TTL = 600


def _meta_configured():
    return bool(
        getattr(settings, "META_APP_ID", "")
        and getattr(settings, "META_APP_SECRET", "")
        and getattr(settings, "META_TOKEN_ENCRYPTION_KEY", "")
        and getattr(settings, "META_REDIRECT_URI", "")
        and getattr(settings, "META_MULTI_TENANT_ENABLED", False)
    )


def _client():
    return MetaClient(
        app_id=settings.META_APP_ID,
        app_secret=settings.META_APP_SECRET,
        graph_version=getattr(settings, "META_GRAPH_VERSION", "v27.0"),
    )


@login_required
@require_GET
def social_accounts(request):
    accounts = SocialAccountConnection.objects.filter(owner=request.user)
    return render(
        request,
        "properties/social_accounts.html",
        {"accounts": accounts, "meta_available": _meta_configured()},
    )


@login_required
@require_GET
def meta_connect(request):
    if not _meta_configured():
        messages.info(request, "Meta account connection is not available right now.")
        return redirect("social-accounts")
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_STATE_KEY] = state
    request.session[OAUTH_STATE_EXPIRY_KEY] = int(time.time()) + OAUTH_STATE_TTL
    request.session[OAUTH_USER_KEY] = str(request.user.pk)
    redirect_uri = settings.META_REDIRECT_URI
    try:
        return redirect(_client().authorization_url(state=state, redirect_uri=redirect_uri))
    except (ImproperlyConfigured, ValueError):
        messages.error(request, "Meta account connection could not be started. Please try again.")
        return redirect("social-accounts")


@login_required
@require_GET
def meta_callback(request):
    saved_state = request.session.pop(OAUTH_STATE_KEY, None)
    expiry = request.session.pop(OAUTH_STATE_EXPIRY_KEY, 0)
    user_id = request.session.pop(OAUTH_USER_KEY, None)
    if (
        not saved_state
        or not request.GET.get("state")
        or not secrets.compare_digest(saved_state, request.GET["state"])
        or not isinstance(expiry, int)
        or expiry < int(time.time())
        or user_id != str(request.user.pk)
        or not _meta_configured()
        or not request.GET.get("code")
    ):
        messages.error(request, "The Meta connection could not be verified. Please try again.")
        return redirect("social-accounts")

    redirect_uri = settings.META_REDIRECT_URI
    try:
        client = _client()
        short_token = client.exchange_code(request.GET["code"], redirect_uri)["access_token"]
        long_token = client.exchange_long_lived_token(short_token)["access_token"]
        pages = client.list_pages(long_token)
        encrypted_pages = [(page, encrypt_access_token(page.access_token)) for page in pages]
    except (MetaAPIError, ImproperlyConfigured, KeyError, TypeError, ValueError):
        messages.error(request, "Meta could not complete the connection. Please try again.")
        return redirect("social-accounts")

    with transaction.atomic():
        for page, ciphertext in encrypted_pages:
            SocialAccountConnection.objects.update_or_create(
                owner=request.user,
                facebook_page_id=page.page_id,
                defaults={
                    "page_name": page.page_name,
                    "instagram_account_id": page.instagram_account_id or "",
                    "instagram_username": page.instagram_username or "",
                    "encrypted_page_access_token": ciphertext,
                    "status": SocialAccountConnection.Status.CONNECTED,
                },
            )
    if encrypted_pages:
        messages.success(request, "Your Meta Pages are connected.")
    else:
        messages.info(request, "No Facebook Pages were available to connect.")
    return redirect("social-accounts")


@login_required
@require_POST
def meta_disconnect(request, account_id):
    account = get_object_or_404(SocialAccountConnection, pk=account_id, owner=request.user)
    account.encrypted_page_access_token = ""
    account.status = SocialAccountConnection.Status.DISCONNECTED
    account.save(update_fields=["encrypted_page_access_token", "status"])
    messages.success(request, "The Page was disconnected.")
    return redirect("social-accounts")
