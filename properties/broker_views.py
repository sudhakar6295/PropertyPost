"""Authenticated, ownership scoped broker journey."""

import logging
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .captions import GeminiCaptionProvider, LocalCaptionProvider
from .forms import AdvertEditForm, GenerateForm, PhotoForm, PlotForm, PrivateDetailsForm
from .make_webhook import MakeWebhookError, trigger_generation
from .models import AdvertDraft, OpenPlotListing, OpenPlotPrivateDetails, PlotPhoto
from .posters import render_poster
from .repositories.django import _to_public_domain
from .serializers import serialize_public_details
from .services import object_store

logger = logging.getLogger(__name__)


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


@login_required
def dashboard(request):
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
                listing = public_form.save(commit=False)
                listing.broker = request.user
                if plot and listing.status != OpenPlotListing.Status.DRAFT:
                    listing.status = OpenPlotListing.Status.DRAFT
                listing.save()
                details = private_form.save(commit=False)
                details.listing = listing
                details.full_clean()
                details.save()
                if plot:
                    AdvertDraft.objects.filter(listing=listing).delete()
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
    if request.method == "POST" and plot.status in {
        OpenPlotListing.Status.PUBLISHING,
        OpenPlotListing.Status.PUBLISHED,
    }:
        return HttpResponseBadRequest("Published plots cannot be changed.")
    return save_plot(request, plot)


@login_required
def upload_photos(request, public_id):
    plot = owned_plot(request, public_id)
    if request.method == "POST" and plot.status in {
        OpenPlotListing.Status.PUBLISHING,
        OpenPlotListing.Status.PUBLISHED,
    }:
        return HttpResponseBadRequest("Published plots cannot be changed.")
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
        AdvertDraft.objects.filter(listing=plot).delete()
        plot.status = OpenPlotListing.Status.DRAFT
        plot.save(update_fields=["status", "updated_at"])
        return redirect("upload-photos", public_id=public_id)
    return render(request, "properties/photos.html", {"plot": plot, "form": form})


@login_required
@require_POST
def arrange_photos(request, public_id):
    plot = owned_plot(request, public_id)
    if plot.status in {OpenPlotListing.Status.PUBLISHING, OpenPlotListing.Status.PUBLISHED}:
        return HttpResponseBadRequest("Published plots cannot be changed.")
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
        AdvertDraft.objects.filter(listing=plot).delete()
        plot.status = OpenPlotListing.Status.DRAFT
        plot.save(update_fields=["status", "updated_at"])
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
    if request.method == "POST":
        if not hasattr(plot, "advert") or plot.status != OpenPlotListing.Status.REVIEW:
            return HttpResponseBadRequest("Generate an advert before approving it.")
        form = AdvertEditForm(request.POST, instance=plot.advert)
        if form.is_valid():
            advert = form.save(commit=False)
            advert.hashtags = form.cleaned_data["hashtags"]
            advert.save()
            plot.status = OpenPlotListing.Status.APPROVED
            plot.save(update_fields=["status", "updated_at"])
            return redirect("advert-preview", public_id=public_id)
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
def generate_advert(request, public_id):
    plot = owned_plot(request, public_id)
    if (
        settings.MAKE_WEBHOOK_URL
        and plot.status == OpenPlotListing.Status.REVIEW
        and hasattr(plot, "advert")
    ):
        return redirect("review-details", public_id=public_id)
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
        elif make_enabled:
            request_id = uuid4()
            plot.status = OpenPlotListing.Status.GENERATING
            plot.save(update_fields=["status", "updated_at"])
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
                    },
                    status=202,
                )
        else:
            plot.status = OpenPlotListing.Status.GENERATING
            plot.save(update_fields=["status", "updated_at"])
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
                        "poster_path": path,
                        "headline": caption.headline,
                        "caption": caption.caption,
                        "hashtags": list(caption.hashtags),
                    },
                )
            except Exception:
                plot.status = OpenPlotListing.Status.FAILED
                plot.save(update_fields=["status", "updated_at"])
                form.add_error(None, "Could not make the advert. Please try again.")
            else:
                plot.status = OpenPlotListing.Status.REVIEW
                plot.save(update_fields=["status", "updated_at"])
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
        },
    )


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
    if plot.status not in {
        OpenPlotListing.Status.APPROVED,
        OpenPlotListing.Status.PUBLISHING,
        OpenPlotListing.Status.PUBLISHED,
    }:
        return redirect("review-details", public_id=public_id)
    return render(
        request,
        "properties/advert_preview.html" if hasattr(plot, "advert") else "properties/preview.html",
        {"plot": plot},
    )


@login_required
@require_POST
def publish_plot(request, public_id):
    plot = owned_plot(request, public_id)
    if not hasattr(plot, "advert") or plot.status not in {
        OpenPlotListing.Status.APPROVED,
        OpenPlotListing.Status.PUBLISHED,
    }:
        return HttpResponseBadRequest("Review and approve the details before publishing.")
    plot.status = OpenPlotListing.Status.PUBLISHED
    plot.save(update_fields=["status", "updated_at"])
    return redirect("published-result", public_id=public_id)


@login_required
def published_result(request, public_id):
    plot = owned_plot(request, public_id)
    if plot.status != OpenPlotListing.Status.PUBLISHED:
        return redirect("advert-preview", public_id=public_id)
    return render(request, "properties/published.html", {"plot": plot})
