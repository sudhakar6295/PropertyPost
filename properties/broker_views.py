"""Authenticated, ownership scoped broker journey."""

import logging
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .advert_versions import archive_current, finish_job, next_version_number
from .api_views import _poster_signature
from .captions import GeminiCaptionProvider, LocalCaptionProvider
from .forms import (
    AdvertEditForm,
    GenerateForm,
    PhotoForm,
    PlotForm,
    PrivateDetailsForm,
    PublicationForm,
)
from .make_webhook import MakeWebhookError, trigger_generation, trigger_publication
from .models import (
    AdvertDraft,
    AdvertVersion,
    AutomationJob,
    OpenPlotListing,
    OpenPlotPrivateDetails,
    PlotPhoto,
    SocialAccountConnection,
    SocialPublicationAttempt,
)
from .posters import render_poster
from .repositories.django import _to_public_domain
from .serializers import serialize_public_details
from .services import object_store

logger = logging.getLogger(__name__)
SOCIAL_ATTEMPT_STALE_AFTER = timedelta(seconds=90)


def reconcile_stale_social_attempts(*, broker=None, listing=None):
    """Mark timed-out direct Meta calls uncertain without enabling a retry."""
    cutoff = timezone.now() - SOCIAL_ATTEMPT_STALE_AFTER
    stale = SocialPublicationAttempt.objects.filter(
        status=SocialPublicationAttempt.Status.PENDING,
        updated_at__lt=cutoff,
    )
    if broker is not None:
        stale = stale.filter(listing__broker=broker)
    if listing is not None:
        stale = stale.filter(listing=listing)
    listing_ids = list(
        stale.order_by().values_list("listing_id", flat=True).distinct().order_by("listing_id")
    )
    if not listing_ids:
        return 0

    reconciled = 0
    with transaction.atomic():
        locked_listings = {
            item.pk: item
            for item in OpenPlotListing.objects.select_for_update()
            .filter(pk__in=listing_ids)
            .order_by("pk")
        }
        locked_attempts = list(stale.select_for_update().order_by("listing_id", "pk"))
        changed_listings = set()
        for attempt in locked_attempts:
            if (
                attempt.status != SocialPublicationAttempt.Status.PENDING
                or attempt.updated_at >= cutoff
            ):
                continue
            listing_obj = locked_listings.get(attempt.listing_id)
            if listing_obj is None:
                continue
            attempt.status = SocialPublicationAttempt.Status.UNCERTAIN
            attempt.error_code = "worker_timeout"
            attempt.save(update_fields=["status", "error_code", "updated_at"])
            reconciled += 1
            advert = getattr(listing_obj, "advert", None)
            if advert is not None and advert.version_number == attempt.advert_version_number:
                changed_listings.add(listing_obj.pk)

        for listing_id in changed_listings:
            listing_obj = locked_listings[listing_id]
            listing_obj.status = OpenPlotListing.Status.FAILED
            listing_obj.save(update_fields=["status", "updated_at"])
    return reconciled


def broker_login(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    error = None
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user is not None and user.is_active:
            login(request, user)
            return redirect("dashboard")
        error = "Those sign-in details did not match. Please try again."
    return render(request, "properties/login.html", {"error": error})


@require_POST
def broker_logout(request):
    logout(request)
    return redirect("broker-login")


def owned_plot(request, public_id):
    return get_object_or_404(OpenPlotListing, public_id=public_id, broker=request.user)


def invalidate_advert(listing):
    """Start a new draft while preserving the advert that was already shown or posted."""
    archive_current(listing)
    AdvertDraft.objects.filter(listing=listing).delete()
    AutomationJob.objects.filter(listing=listing, status=AutomationJob.Status.PENDING).update(
        status=AutomationJob.Status.FAILED,
        completed_at=timezone.now(),
        error_code="listing_changed",
    )
    listing.status = OpenPlotListing.Status.DRAFT
    listing.generation_request_id = None
    listing.publication_request_id = None
    listing.publication_platforms = []
    listing.publication_results = {}
    listing.save(
        update_fields=[
            "status",
            "generation_request_id",
            "publication_request_id",
            "publication_platforms",
            "publication_results",
            "updated_at",
        ]
    )


@login_required
def dashboard(request):
    reconcile_stale_social_attempts(broker=request.user)
    listings = OpenPlotListing.objects.filter(broker=request.user).order_by("-updated_at")
    return render(request, "properties/dashboard.html", {"listings": listings})


def save_plot(request, plot=None):
    private = OpenPlotPrivateDetails.objects.filter(listing=plot).first() if plot else None
    public_form = PlotForm(request.POST or None, instance=plot, prefix="public")
    private_form = PrivateDetailsForm(request.POST or None, instance=private, prefix="private")
    if request.method == "POST" and public_form.is_valid() and private_form.is_valid():
        amount = private_form.cleaned_data.get("negotiable_amount")
        if amount is not None and amount > public_form.cleaned_data["total_price"]:
            private_form.add_error(
                "negotiable_amount", "This must be no more than the total price."
            )
    if request.method == "POST" and public_form.is_valid() and private_form.is_valid():
        try:
            with transaction.atomic():
                if plot and public_form.has_changed():
                    archive_current(
                        OpenPlotListing.objects.select_for_update().get(
                            pk=plot.pk, broker=request.user
                        )
                    )
                listing = public_form.save(commit=False)
                listing.broker = request.user
                listing.save()
                details = private_form.save(commit=False)
                details.listing = listing
                details.full_clean()
                details.save()
                if plot and public_form.has_changed():
                    invalidate_advert(listing)
        except DatabaseError as exc:
            logger.error(
                "Plot save failed",
                extra={"event": "plot_save_failed", "exception_type": type(exc).__name__},
            )
            public_form.add_error(
                None,
                "We couldn't save this plot just now. Your details are still on this page; "
                "please try again shortly.",
            )
            return render(
                request,
                "properties/plot_form.html",
                {"plot": plot, "public_form": public_form, "private_form": private_form},
                status=503,
            )
        return redirect("upload-photos", public_id=listing.public_id)
    return render(
        request,
        "properties/plot_form.html",
        {
            "plot": plot,
            "public_form": public_form,
            "private_form": private_form,
        },
    )


@login_required
def add_plot(request):
    return save_plot(request)


@login_required
def edit_plot(request, public_id):
    plot = owned_plot(request, public_id)
    if request.method == "POST" and plot.status == OpenPlotListing.Status.PUBLISHING:
        return HttpResponseBadRequest("Wait until posting finishes before changing this plot.")
    return save_plot(request, plot)


@login_required
def upload_photos(request, public_id):
    plot = owned_plot(request, public_id)
    if request.method == "POST" and plot.status == OpenPlotListing.Status.PUBLISHING:
        return HttpResponseBadRequest("Wait until posting finishes before changing photos.")
    form = PhotoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        photo = form.save(commit=False)
        photo.listing = plot
        uploaded = form.cleaned_data["image"]
        suffix = Path(uploaded.name).suffix.lower()
        photo.object_path = f"originals/{request.user.pk}/{plot.public_id}/{uuid4()}{suffix}"
        photo.content_type = uploaded.content_type
        photo.size_bytes = uploaded.size
        photo.sort_order = plot.photos.count()
        photo.is_main = not plot.photos.exists()
        object_store().upload(photo.object_path, uploaded.read(), photo.content_type)
        photo.image = ""
        photo.save()
        with transaction.atomic():
            invalidate_advert(plot)
        return redirect("upload-photos", public_id=public_id)
    return render(request, "properties/photos.html", {"plot": plot, "form": form})


@login_required
@require_POST
def arrange_photos(request, public_id):
    plot = owned_plot(request, public_id)
    if plot.status == OpenPlotListing.Status.PUBLISHING:
        return HttpResponseBadRequest("Wait until posting finishes before changing photos.")
    ids = list(plot.photos.values_list("pk", flat=True))
    try:
        ordered = [int(value) for value in request.POST.getlist("photo_order")]
        main_id = int(request.POST.get("main_photo", ""))
    except ValueError:
        return HttpResponseBadRequest("Choose a main photo and order.")
    if len(ids) != len(ordered) or set(ids) != set(ordered) or main_id not in ids:
        return HttpResponseBadRequest("Invalid photo selection.")
    with transaction.atomic():
        for position, photo_id in enumerate(ordered):
            plot.photos.filter(pk=photo_id).update(sort_order=position, is_main=photo_id == main_id)
        invalidate_advert(plot)
    return redirect("upload-photos", public_id=public_id)


@login_required
def private_photo(request, public_id, photo_id):
    plot = owned_plot(request, public_id)
    photo = get_object_or_404(PlotPhoto, pk=photo_id, listing=plot)
    response = HttpResponse(
        object_store().download(photo.object_path), content_type=photo.content_type
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def review_details(request, public_id):
    plot = owned_plot(request, public_id)
    if (
        request.method == "GET"
        and hasattr(plot, "advert")
        and plot.status
        in {
            OpenPlotListing.Status.APPROVED,
            OpenPlotListing.Status.PUBLISHING,
            OpenPlotListing.Status.PUBLISHED,
        }
    ):
        return redirect("advert-preview", public_id=public_id)
    if request.method == "POST":
        if not hasattr(plot, "advert") or plot.status != OpenPlotListing.Status.REVIEW:
            return HttpResponseBadRequest("Generate an advert before approving it.")
        form = AdvertEditForm(request.POST, instance=plot.advert)
        if form.is_valid():
            advert = form.save(commit=False)
            advert.hashtags = form.cleaned_data["hashtags"]
            advert.save()
            plot.status = (
                OpenPlotListing.Status.REVIEW
                if request.POST.get("intent") == "save"
                else OpenPlotListing.Status.APPROVED
            )
            plot.save(update_fields=["status", "updated_at"])
            return redirect(
                "review-details"
                if plot.status == OpenPlotListing.Status.REVIEW
                else "advert-preview",
                public_id=public_id,
            )
    else:
        form = AdvertEditForm(instance=plot.advert) if hasattr(plot, "advert") else None
    return render(
        request,
        "properties/advert_review.html" if form else "properties/details_review.html",
        {
            "plot": plot,
            "private": OpenPlotPrivateDetails.objects.filter(listing=plot).first(),
            "advert_form": form,
        },
    )


@login_required
@require_POST
def revise_published_advert(request, public_id):
    plot = owned_plot(request, public_id)
    with transaction.atomic():
        plot = OpenPlotListing.objects.select_for_update().get(pk=plot.pk, broker=request.user)
        if plot.status != OpenPlotListing.Status.PUBLISHED or not hasattr(plot, "advert"):
            return HttpResponseBadRequest("Only a published advert can be revised here.")
        archive_current(plot)
        advert = plot.advert
        advert.version_number = next_version_number(plot)
        advert.save(update_fields=["version_number", "updated_at"])
        plot.status = OpenPlotListing.Status.REVIEW
        plot.publication_request_id = None
        plot.publication_platforms = []
        plot.publication_results = {}
        plot.save(
            update_fields=[
                "status",
                "publication_request_id",
                "publication_platforms",
                "publication_results",
                "updated_at",
            ]
        )
    return redirect("review-details", public_id=public_id)


@login_required
def advert_history(request, public_id):
    plot = owned_plot(request, public_id)
    return render(
        request,
        "properties/advert_history.html",
        {
            "plot": plot,
            "versions": plot.advert_versions.all(),
            "current": AdvertDraft.objects.filter(listing=plot).first(),
        },
    )


@login_required
def version_poster(request, public_id, version_number):
    plot = owned_plot(request, public_id)
    version = get_object_or_404(AdvertVersion, listing=plot, version_number=version_number)
    response = HttpResponse(object_store().download(version.poster_path), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def expire_generation(listing):
    """Release a broker from a Make request that never sent a callback."""
    if listing.status != OpenPlotListing.Status.GENERATING:
        return listing
    with transaction.atomic():
        listing = OpenPlotListing.objects.select_for_update().get(pk=listing.pk)
        job = AutomationJob.objects.filter(
            listing=listing,
            kind=AutomationJob.Kind.GENERATION,
            request_id=listing.generation_request_id,
            status=AutomationJob.Status.PENDING,
        ).first()
        if job and job.requested_at <= timezone.now() - timedelta(
            seconds=settings.MAKE_JOB_TIMEOUT_SECONDS
        ):
            listing.status = OpenPlotListing.Status.FAILED
            listing.save(update_fields=["status", "updated_at"])
            finish_job(
                listing,
                AutomationJob.Kind.GENERATION,
                job.request_id,
                succeeded=False,
                error_code="callback_timeout",
            )
    return listing


@login_required
def generate_advert(request, public_id):
    plot = expire_generation(owned_plot(request, public_id))
    form = GenerateForm(request.POST or None, request.FILES or None)
    has_main_photo = plot.photos.filter(is_main=True).exists()
    make_enabled = bool(settings.MAKE_WEBHOOK_URL)
    if make_enabled:
        form.fields.pop("logo", None)
    if request.method == "POST" and form.is_valid():
        photo = plot.photos.filter(is_main=True).first()
        if photo is None:
            form.add_error(None, "Choose a main photo first.")
        elif plot.status == OpenPlotListing.Status.GENERATING:
            form.add_error(None, "This advert is already being created. Please wait.")
        elif plot.status in {OpenPlotListing.Status.PUBLISHING, OpenPlotListing.Status.PUBLISHED}:
            return HttpResponseBadRequest("Publishing or published adverts cannot be regenerated.")
        elif plot.status == OpenPlotListing.Status.FAILED and plot.publication_request_id:
            return redirect("advert-preview", public_id=public_id)
        elif not make_enabled and not settings.DEBUG:
            form.add_error(
                None,
                "Posting automation is not configured. Please contact your administrator.",
            )
        elif make_enabled:
            request_id = uuid4()
            with transaction.atomic():
                plot = OpenPlotListing.objects.select_for_update().get(
                    pk=plot.pk, broker=request.user
                )
                if plot.status == OpenPlotListing.Status.GENERATING:
                    form.add_error(None, "This advert is already being created. Please wait.")
                    return render(
                        request,
                        "properties/generate.html",
                        {
                            "plot": plot,
                            "form": form,
                            "has_main_photo": has_main_photo,
                            "make_enabled": make_enabled,
                            "request_pending": True,
                            "generation_status_url": reverse(
                                "generation-status", args=[plot.public_id]
                            ),
                        },
                    )
                if plot.status in {
                    OpenPlotListing.Status.PUBLISHING,
                    OpenPlotListing.Status.PUBLISHED,
                }:
                    return HttpResponseBadRequest(
                        "Publishing or published adverts cannot be regenerated."
                    )
                archive_current(plot)
                AdvertDraft.objects.filter(listing=plot).delete()
                plot.status = OpenPlotListing.Status.GENERATING
                plot.language = form.cleaned_data["language"]
                plot.generation_request_id = request_id
                plot.publication_request_id = None
                plot.publication_platforms = []
                plot.publication_results = {}
                plot.save(
                    update_fields=[
                        "status",
                        "language",
                        "generation_request_id",
                        "publication_request_id",
                        "publication_platforms",
                        "publication_results",
                        "updated_at",
                    ]
                )
                AutomationJob.objects.create(
                    listing=plot, kind=AutomationJob.Kind.GENERATION, request_id=request_id
                )
            try:
                trigger_generation(
                    settings.MAKE_WEBHOOK_URL,
                    listing_id=str(plot.public_id),
                    request_id=str(request_id),
                    template=form.cleaned_data["template"],
                    automation_input_url=request.build_absolute_uri(
                        reverse("automation-input", args=[plot.public_id])
                    ),
                    generation_result_url=request.build_absolute_uri(
                        reverse("generation-result", args=[plot.public_id])
                    ),
                )
            except MakeWebhookError as exc:
                logger.error(
                    "Make generation trigger failed",
                    extra={
                        "event": "make_generation_trigger_failed",
                        "exception_type": type(exc).__name__,
                    },
                )
                plot.refresh_from_db(fields=["status"])
                if plot.status == OpenPlotListing.Status.GENERATING:
                    plot.status = OpenPlotListing.Status.FAILED
                    plot.save(update_fields=["status", "updated_at"])
                    finish_job(
                        plot,
                        AutomationJob.Kind.GENERATION,
                        request_id,
                        succeeded=False,
                        error_code="trigger_failed",
                    )
                form.add_error(None, "Could not send the advert request. Please try again.")
            else:
                return render(
                    request,
                    "properties/generate.html",
                    {
                        "plot": plot,
                        "form": form,
                        "has_main_photo": has_main_photo,
                        "make_enabled": make_enabled,
                        "request_sent": True,
                        "request_pending": True,
                        "generation_status_url": reverse(
                            "generation-status", args=[plot.public_id]
                        ),
                    },
                    status=202,
                )
        else:
            with transaction.atomic():
                plot = OpenPlotListing.objects.select_for_update().get(
                    pk=plot.pk, broker=request.user
                )
                if plot.status == OpenPlotListing.Status.GENERATING:
                    form.add_error(None, "This advert is already being created. Please wait.")
                    return render(
                        request,
                        "properties/generate.html",
                        {
                            "plot": plot,
                            "form": form,
                            "has_main_photo": has_main_photo,
                            "make_enabled": make_enabled,
                            "request_pending": True,
                            "generation_status_url": reverse(
                                "generation-status", args=[plot.public_id]
                            ),
                        },
                    )
                if plot.status in {
                    OpenPlotListing.Status.PUBLISHING,
                    OpenPlotListing.Status.PUBLISHED,
                }:
                    return HttpResponseBadRequest(
                        "Publishing or published adverts cannot be regenerated."
                    )
                archive_current(plot)
                AdvertDraft.objects.filter(listing=plot).delete()
                plot.status = OpenPlotListing.Status.GENERATING
                plot.language = form.cleaned_data["language"]
                plot.generation_request_id = uuid4()
                plot.publication_request_id = None
                plot.publication_platforms = []
                plot.publication_results = {}
                plot.save(
                    update_fields=[
                        "status",
                        "language",
                        "generation_request_id",
                        "publication_request_id",
                        "publication_platforms",
                        "publication_results",
                        "updated_at",
                    ]
                )
                AutomationJob.objects.create(
                    listing=plot,
                    kind=AutomationJob.Kind.GENERATION,
                    request_id=plot.generation_request_id,
                )
            try:
                details = serialize_public_details(_to_public_domain(plot))
                logo = form.cleaned_data["logo"]
                poster = render_poster(
                    object_store().download(photo.object_path),
                    details,
                    form.cleaned_data["template"],
                    logo.read() if logo else None,
                )
                provider = (
                    GeminiCaptionProvider(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
                    if settings.CAPTION_ADAPTER == "gemini"
                    else LocalCaptionProvider()
                )
                caption = provider.generate(details)
                path = f"posters/{request.user.pk}/{plot.public_id}/{uuid4()}.png"
                object_store().upload(path, poster, "image/png")
                AdvertDraft.objects.update_or_create(
                    listing=plot,
                    defaults={
                        "template": form.cleaned_data["template"],
                        "language": plot.language,
                        "version_number": next_version_number(plot),
                        "poster_path": path,
                        "headline": caption.headline,
                        "caption": caption.caption,
                        "hashtags": list(caption.hashtags),
                    },
                )
            except Exception:
                plot.status = OpenPlotListing.Status.FAILED
                plot.save(update_fields=["status", "updated_at"])
                finish_job(
                    plot,
                    AutomationJob.Kind.GENERATION,
                    plot.generation_request_id,
                    succeeded=False,
                    error_code="generation_failed",
                )
                form.add_error(None, "Could not make the advert. Please try again.")
            else:
                plot.status = OpenPlotListing.Status.REVIEW
                plot.save(update_fields=["status", "updated_at"])
                finish_job(
                    plot, AutomationJob.Kind.GENERATION, plot.generation_request_id, succeeded=True
                )
                return redirect("review-details", public_id=public_id)
    return render(
        request,
        "properties/generate.html",
        {
            "plot": plot,
            "form": form,
            "has_main_photo": has_main_photo,
            "make_enabled": make_enabled,
            "request_pending": plot.status == OpenPlotListing.Status.GENERATING,
            "generation_status_url": reverse("generation-status", args=[plot.public_id]),
        },
    )


@login_required
@require_GET
def generation_status(request, public_id):
    plot = expire_generation(owned_plot(request, public_id))
    response = {"status": plot.status}
    if plot.status == OpenPlotListing.Status.REVIEW and hasattr(plot, "advert"):
        response["next_url"] = reverse("review-details", args=[plot.public_id])
    elif plot.status == OpenPlotListing.Status.FAILED:
        response["retry_url"] = reverse("generate-advert", args=[plot.public_id])
    return JsonResponse(response)


@login_required
def private_poster(request, public_id):
    plot = owned_plot(request, public_id)
    advert = get_object_or_404(AdvertDraft, listing=plot)
    response = HttpResponse(object_store().download(advert.poster_path), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def advert_preview(request, public_id):
    plot = owned_plot(request, public_id)
    reconcile_stale_social_attempts(listing=plot)
    plot.refresh_from_db(fields=["status"])
    social_mode = bool(getattr(settings, "META_MULTI_TENANT_ENABLED", False))
    has_social_attempts = SocialPublicationAttempt.objects.filter(listing=plot).exists()
    callback = urlsplit(getattr(settings, "META_REDIRECT_URI", ""))
    social_ready = bool(
        social_mode
        and settings.META_APP_ID
        and settings.META_APP_SECRET
        and settings.META_TOKEN_ENCRYPTION_KEY
        and callback.scheme == "https"
        and callback.netloc
        and not callback.username
        and not callback.password
        and settings.AUTOMATION_HMAC_SECRET
    )
    if plot.status not in {
        OpenPlotListing.Status.APPROVED,
        OpenPlotListing.Status.PUBLISHING,
        OpenPlotListing.Status.PUBLISHED,
    } and not (
        plot.status == OpenPlotListing.Status.FAILED
        and (plot.publication_request_id is not None or has_social_attempts)
    ):
        return redirect("review-details", public_id=public_id)
    attempts = (
        list(
            SocialPublicationAttempt.objects.filter(
                listing=plot, advert_version_number=plot.advert.version_number
            )
            .select_related("social_connection")
            .order_by("-created_at", "-pk")
        )
        if hasattr(plot, "advert")
        else []
    )
    make_published = set((plot.publication_results or {}).keys())
    publish_options = []
    connected_pages = SocialAccountConnection.objects.filter(
        owner=request.user, status=SocialAccountConnection.Status.CONNECTED
    ).order_by("page_name", "pk")
    if plot.status == OpenPlotListing.Status.FAILED:
        retryable = {
            attempt.pk
            for attempt in attempts
            if attempt.status == SocialPublicationAttempt.Status.FAILED
            and (
                attempt.error_code in {"token_invalid", "token_expired", "not_attempted"}
                or (
                    attempt.error_code == "media_not_ready"
                    and attempt.platform == SocialPublicationAttempt.Platform.INSTAGRAM
                    and attempt.instagram_container_id
                )
            )
        }
        for attempt in attempts:
            if (
                attempt.pk in retryable
                and attempt.social_connection.status == SocialAccountConnection.Status.CONNECTED
                and attempt.platform not in make_published
                and (
                    attempt.error_code in {"not_attempted", "media_not_ready"}
                    or (
                        attempt.error_code in {"token_invalid", "token_expired"}
                        and attempt.social_connection.updated_at > attempt.updated_at
                    )
                )
            ):
                publish_options.append(
                    {
                        "connection": attempt.social_connection,
                        "platforms": [
                            {
                                "value": attempt.platform,
                                "label": attempt.get_platform_display(),
                            }
                        ],
                    }
                )
    elif plot.status in {OpenPlotListing.Status.APPROVED, OpenPlotListing.Status.PUBLISHED}:
        for connection in connected_pages:
            prior = {
                attempt.platform
                for attempt in attempts
                if attempt.social_connection_id == connection.pk
            }
            choices = []
            if "facebook" not in prior | make_published:
                choices.append({"value": "facebook", "label": "Facebook"})
            if connection.instagram_account_id and "instagram" not in prior | make_published:
                choices.append({"value": "instagram", "label": "Instagram"})
            if len(choices) == 2:
                choices.append({"value": "all", "label": "Facebook and Instagram"})
            if choices:
                publish_options.append({"connection": connection, "platforms": choices})
    return render(
        request,
        "properties/advert_preview.html" if hasattr(plot, "advert") else "properties/preview.html",
        {
            "plot": plot,
            "publication_enabled": (
                not social_mode
                and settings.MAKE_PUBLICATION_ENABLED
                and bool(settings.MAKE_PUBLICATION_WEBHOOK_URL)
            ),
            "social_publication_enabled": social_ready,
            "social_publication_unavailable": social_mode and not social_ready,
            "social_publish_options": publish_options,
            "social_connections_need_attention": SocialAccountConnection.objects.filter(
                owner=request.user
            ).exclude(status=SocialAccountConnection.Status.CONNECTED),
            "social_publication_attempts": attempts,
            "can_social_publish": bool(publish_options),
            "publication_form": PublicationForm(
                initial={"platform": "all" if plot.publication_results else "facebook"}
            ),
        },
    )


@login_required
@require_POST
def publish_plot(request, public_id):
    plot = owned_plot(request, public_id)
    if getattr(settings, "META_MULTI_TENANT_ENABLED", False):
        return HttpResponseBadRequest("Use your connected Meta Page to publish this advert.")
    if not settings.MAKE_PUBLICATION_ENABLED:
        return HttpResponseBadRequest("Facebook posting is not ready yet.")
    if not settings.MAKE_PUBLICATION_WEBHOOK_URL:
        return HttpResponseBadRequest("Facebook posting automation is not configured yet.")
    form = PublicationForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Choose Facebook, Instagram, or both.")
    requested_platforms = form.platforms
    request_id = uuid4()
    with transaction.atomic():
        plot = OpenPlotListing.objects.select_for_update().get(pk=plot.pk, broker=request.user)
        approved_for_retry = (
            plot.status == OpenPlotListing.Status.FAILED and plot.publication_request_id is not None
        )
        if not hasattr(plot, "advert") or (
            plot.status != OpenPlotListing.Status.APPROVED and not approved_for_retry
        ):
            return HttpResponseBadRequest("Review and approve the details before publishing.")
        already_published = dict(plot.publication_results)
        pending_platforms = [
            platform for platform in requested_platforms if platform not in already_published
        ]
        if not pending_platforms:
            plot.status = OpenPlotListing.Status.PUBLISHED
            plot.publication_platforms = requested_platforms
            plot.save(update_fields=["status", "publication_platforms", "updated_at"])
            return redirect("published-result", public_id=public_id)
        plot.status = OpenPlotListing.Status.PUBLISHING
        plot.publication_request_id = request_id
        plot.publication_platforms = requested_platforms
        plot.save(
            update_fields=[
                "status",
                "publication_request_id",
                "publication_platforms",
                "updated_at",
            ]
        )
        AutomationJob.objects.create(
            listing=plot, kind=AutomationJob.Kind.PUBLICATION, request_id=request_id
        )
    expires = int(time.time()) + settings.AUTOMATION_IMAGE_TTL_SECONDS
    poster_path = reverse("automation-poster", args=[plot.public_id])
    poster_signature = _poster_signature(plot.public_id, expires)
    poster_url = request.build_absolute_uri(
        f"{poster_path}?expires={expires}&signature={poster_signature}"
    )
    callback_url = request.build_absolute_uri(reverse("publication-result", args=[plot.public_id]))
    try:
        trigger_publication(
            settings.MAKE_PUBLICATION_WEBHOOK_URL,
            listing_id=str(plot.public_id),
            request_id=str(request_id),
            headline=plot.advert.headline,
            caption=plot.advert.caption,
            hashtags=list(plot.advert.hashtags),
            platforms=pending_platforms,
            already_published=already_published,
            poster_url=poster_url,
            publication_result_url=callback_url,
        )
    except MakeWebhookError as exc:
        logger.error(
            "Make publication trigger failed",
            extra={
                "event": "make_publication_trigger_failed",
                "exception_type": type(exc).__name__,
            },
        )
        plot.refresh_from_db(fields=["status"])
        if plot.status == OpenPlotListing.Status.PUBLISHING:
            plot.status = OpenPlotListing.Status.FAILED
            plot.save(update_fields=["status", "updated_at"])
            finish_job(
                plot,
                AutomationJob.Kind.PUBLICATION,
                request_id,
                succeeded=False,
                error_code="trigger_failed",
            )
        return HttpResponse("Could not send the publication request. Please try again.", status=503)
    return redirect("published-result", public_id=public_id)


@login_required
def published_result(request, public_id):
    plot = owned_plot(request, public_id)
    reconcile_stale_social_attempts(listing=plot)
    plot.refresh_from_db(fields=["status"])
    social_attempts = SocialPublicationAttempt.objects.filter(listing=plot)
    if plot.status not in {
        OpenPlotListing.Status.PUBLISHED,
        OpenPlotListing.Status.PUBLISHING,
    } and not (plot.status == OpenPlotListing.Status.FAILED and social_attempts.exists()):
        return redirect("advert-preview", public_id=public_id)
    return render(
        request,
        "properties/published.html",
        {
            "plot": plot,
            "publication_status_url": reverse("publication-status", args=[plot.public_id]),
            "social_publication_attempts": social_attempts.select_related(
                "social_connection"
            ).order_by("-created_at", "-pk"),
            "social_connections_need_attention": SocialAccountConnection.objects.filter(
                owner=request.user
            ).exclude(status=SocialAccountConnection.Status.CONNECTED),
        },
    )


@login_required
@require_GET
def publication_status(request, public_id):
    plot = owned_plot(request, public_id)
    reconcile_stale_social_attempts(listing=plot)
    plot.refresh_from_db(fields=["status"])
    job = (
        AutomationJob.objects.filter(listing=plot, kind=AutomationJob.Kind.PUBLICATION)
        .order_by("-requested_at")
        .first()
    )
    unconfirmed = bool(
        plot.status == OpenPlotListing.Status.PUBLISHING
        and job
        and job.requested_at
        <= timezone.now() - timedelta(seconds=settings.MAKE_JOB_TIMEOUT_SECONDS)
    )
    return JsonResponse(
        {
            "status": plot.status,
            "unconfirmed": unconfirmed,
            "publication_results": plot.publication_results,
            "next_url": (
                reverse("advert-preview", args=[plot.public_id])
                if plot.status == OpenPlotListing.Status.FAILED
                else reverse("published-result", args=[plot.public_id])
            ),
        }
    )
