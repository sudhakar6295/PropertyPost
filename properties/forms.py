"""Broker forms with the public/private boundary visible in the interface."""

from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from .captions import validate_caption
from .models import AdvertDraft, OpenPlotListing, OpenPlotPrivateDetails, PlotPhoto
from .posters import TEMPLATES


class BootstrapFormMixin:
    def style_fields(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


class PlotForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = OpenPlotListing
        fields = (
            "title",
            "location",
            "landmark",
            "area",
            "area_unit",
            "total_price",
            "price_per_unit",
            "facing",
            "road_width_ft",
            "approval_type",
            "contact_number",
            "language",
        )
        labels = {
            "road_width_ft": "Road width (feet)",
            "total_price": "Total price (₹)",
            "price_per_unit": "Price per area unit (₹, optional)",
            "contact_number": "Number shown to buyers",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class PrivateDetailsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = OpenPlotPrivateDetails
        fields = ("owner_name", "owner_phone", "internal_notes", "negotiable_amount")
        labels = {"negotiable_amount": "Lowest acceptable amount (₹, optional)"}
        widgets = {"internal_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class PhotoForm(BootstrapFormMixin, forms.ModelForm):
    image = forms.FileField()

    class Meta:
        model = PlotPhoto
        fields = ("image", "caption")

    def __init__(self, *args, **kwargs):
        files = kwargs.get("files") or (args[1] if len(args) > 1 else None)
        uploaded = (files or {}).get("image")
        self.uploaded_mime = uploaded.content_type if uploaded else None
        super().__init__(*args, **kwargs)
        self.fields["image"].widget.attrs["accept"] = "image/jpeg,image/png,image/webp"
        self.style_fields()

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > 5 * 1024 * 1024:
            raise ValidationError("Choose a photo smaller than 5 MB.")
        extension = Path(image.name).suffix.lower()
        expected = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        if extension not in expected or self.uploaded_mime != expected[extension]:
            raise ValidationError("The photo name and type must both be JPG, PNG, or WebP.")
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationError("Choose a JPG, PNG, or WebP photo.")
        image.seek(0)
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(image) as decoded:
                if decoded.width * decoded.height > 40_000_000:
                    raise ValidationError("Photo dimensions are too large.")
                if (
                    decoded.format
                    != {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[extension]
                ):
                    raise ValidationError("The photo content does not match its file type.")
                decoded.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValidationError("This photo could not be read.") from exc
        finally:
            image.seek(0)
        return image


class GenerateForm(forms.Form):
    template = forms.ChoiceField(choices=[(name, name.title()) for name in TEMPLATES])
    logo = forms.FileField(required=False, help_text="Optional PNG or JPEG logo, up to 1 MB")

    def clean_logo(self):
        logo = self.cleaned_data["logo"]
        if logo and logo.size > 1024 * 1024:
            raise ValidationError("Choose a logo smaller than 1 MB.")
        if logo:
            from PIL import Image, UnidentifiedImageError

            if logo.content_type not in {"image/png", "image/jpeg"}:
                raise ValidationError("Choose a PNG or JPEG logo.")
            try:
                with Image.open(logo) as decoded:
                    if decoded.format not in {"PNG", "JPEG"} or (
                        decoded.width * decoded.height > 4_000_000
                    ):
                        raise ValidationError("Choose a smaller PNG or JPEG logo.")
                    decoded.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValidationError("This logo could not be read.") from exc
            finally:
                logo.seek(0)
        return logo


class AdvertEditForm(BootstrapFormMixin, forms.ModelForm):
    hashtags_text = forms.CharField(label="Hashtags", help_text="Separate with spaces")

    class Meta:
        model = AdvertDraft
        fields = ("headline", "caption")
        widgets = {"caption": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["hashtags_text"].initial = " ".join(self.instance.hashtags)
        self.style_fields()

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            try:
                caption = validate_caption(
                    {
                        "headline": cleaned["headline"],
                        "caption": cleaned["caption"],
                        "hashtags": cleaned["hashtags_text"].split(),
                    }
                )
                cleaned["hashtags"] = list(caption.hashtags)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        return cleaned
