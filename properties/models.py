"""Open Plot / Land for Sale models with a strict public/private boundary."""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .validators import phone_number_validator


class OpenPlotListing(models.Model):
    """Public listing data and workflow metadata for an open plot."""

    class AreaUnit(models.TextChoices):
        SQ_FT = "sq_ft", "Square feet"
        SQ_YD = "sq_yd", "Square yards"
        ACRE = "acre", "Acres"
        CENT = "cent", "Cents"
        GUNTA = "gunta", "Guntas"

    class Facing(models.TextChoices):
        NORTH = "north", "North"
        SOUTH = "south", "South"
        EAST = "east", "East"
        WEST = "west", "West"
        NORTH_EAST = "north_east", "North-East"
        NORTH_WEST = "north_west", "North-West"
        SOUTH_EAST = "south_east", "South-East"
        SOUTH_WEST = "south_west", "South-West"

    class ApprovalType(models.TextChoices):
        DTCP = "dtcp", "DTCP"
        HMDA = "hmda", "HMDA"
        RERA = "rera", "RERA"
        PANCHAYAT = "panchayat", "Panchayat"
        UNAPPROVED = "unapproved", "Unapproved"
        OTHER = "other", "Other"

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        HINDI = "hi", "Hindi"
        TELUGU = "te", "Telugu"
        TAMIL = "ta", "Tamil"
        KANNADA = "kn", "Kannada"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        GENERATING = "generating", "Generating"
        REVIEW = "review", "Review"
        APPROVED = "approved", "Approved"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="plots", null=True
    )
    title = models.CharField(max_length=160)
    location = models.CharField(max_length=180)
    landmark = models.CharField(max_length=180)
    area = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    area_unit = models.CharField(max_length=8, choices=AreaUnit.choices)
    total_price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    price_per_unit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    facing = models.CharField(max_length=16, choices=Facing.choices)
    road_width_ft = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    approval_type = models.CharField(max_length=16, choices=ApprovalType.choices)
    contact_number = models.CharField(max_length=16, validators=[phone_number_validator])
    language = models.CharField(max_length=2, choices=Language.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "open plot listing"
        verbose_name_plural = "open plot listings"

    def __str__(self) -> str:
        return self.title


class OpenPlotPrivateDetails(models.Model):
    """Restricted owner and negotiation data stored outside the public listing."""

    listing = models.OneToOneField(
        OpenPlotListing,
        on_delete=models.CASCADE,
        related_name="private_details",
    )
    owner_name = models.CharField(max_length=160)
    owner_phone = models.CharField(max_length=16, validators=[phone_number_validator])
    internal_notes = models.TextField(blank=True)
    negotiable_amount = models.PositiveBigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "open plot private details"
        verbose_name_plural = "open plot private details"

    def __str__(self) -> str:
        return f"Private details for {self.listing}"

    def clean(self) -> None:
        super().clean()
        if (
            self.negotiable_amount is not None
            and self.listing_id is not None
            and self.negotiable_amount > self.listing.total_price
        ):
            raise ValidationError(
                {"negotiable_amount": "Negotiable amount cannot exceed the total price."}
            )


class PlotPhoto(models.Model):
    listing = models.ForeignKey(OpenPlotListing, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="plots/%Y/%m/")
    object_path = models.CharField(max_length=300, blank=True)
    content_type = models.CharField(max_length=32, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    is_main = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    caption = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "uploaded_at", "pk"]

    def __str__(self) -> str:
        return self.caption or str(self.listing)


class AdvertDraft(models.Model):
    listing = models.OneToOneField(OpenPlotListing, on_delete=models.CASCADE, related_name="advert")
    template = models.CharField(max_length=16)
    poster_path = models.CharField(max_length=300)
    headline = models.CharField(max_length=100)
    caption = models.TextField(max_length=1000)
    hashtags = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.headline


class AutomationReceipt(models.Model):
    class Kind(models.TextChoices):
        GENERATION = "generation", "Generation"
        PUBLICATION = "publication", "Publication"

    listing = models.ForeignKey(
        OpenPlotListing, on_delete=models.CASCADE, related_name="automation_receipts"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    request_id = models.UUIDField()
    body_sha256 = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("listing", "kind", "request_id"), name="unique_automation_receipt"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.request_id}"
