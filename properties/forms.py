"""Broker forms with the public/private boundary visible in the interface."""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from .captions import validate_caption
from .models import AdvertDraft, OpenPlotListing, OpenPlotPrivateDetails, PlotPhoto
from .posters import TEMPLATES

COUNTRY_CODES = (
    ("+91", "🇮🇳 India +91"),
    ("+971", "🇦🇪 UAE +971"),
    ("+44", "🇬🇧 UK +44"),
    ("+1", "🇺🇸 USA/Canada +1"),
)
LOCAL_PHONE_LENGTHS = {"+91": 10, "+971": 9, "+44": 10, "+1": 10}


def _phone_parts(number: str) -> tuple[str, str]:
    for code, _ in sorted(COUNTRY_CODES, key=lambda item: len(item[0]), reverse=True):
        if number.startswith(code):
            return code, number[len(code) :]
    return "+91", number


def _international_phone(raw: str, country_code: str) -> str:
    value = "".join(character for character in raw if character not in " ()-.")
    if value.startswith("+"):
        number = value  # Accept existing E.164 values from older forms.
    elif value.isdecimal():
        number = f"{country_code}{value}"
    else:
        raise ValidationError("Enter a valid phone number using digits only.")
    if not number[1:].isdecimal() or not 8 <= len(number[1:]) <= 15:
        raise ValidationError("Enter a valid phone number for the selected country.")
    code, local = _phone_parts(number)
    if code not in LOCAL_PHONE_LENGTHS or len(local) != LOCAL_PHONE_LENGTHS[code]:
        raise ValidationError("Enter a valid phone number for the selected country.")
    return number


class BootstrapFormMixin:
    def style_fields(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


class PlotForm(BootstrapFormMixin, forms.ModelForm):
    contact_number = forms.CharField(label="Number shown to buyers", max_length=20)
    contact_country_code = forms.ChoiceField(
        choices=COUNTRY_CODES, label="Country code", initial="+91", required=False
    )

    class Meta:
        model = OpenPlotListing
        fields = (
            "title",
            "location",
            "landmark",
            "area",
            "area_unit",
            "total_price",
            "facing",
            "road_width_ft",
            "approval_type",
            "contact_number",
            "language",
        )
        labels = {
            "road_width_ft": "Road width (feet)",
            "total_price": "Total price (₹)",
            "contact_number": "Number shown to buyers",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.contact_number:
            country, local = _phone_parts(self.instance.contact_number)
            self.initial["contact_country_code"] = country
            self.initial["contact_number"] = local
        self.fields["contact_number"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel-national", "placeholder": "98765 43210"}
        )
        self.fields["road_width_ft"].required = False
        self.fields["language"].required = False
        self.style_fields()

    def clean(self):
        cleaned = super().clean()
        cleaned["language"] = (
            cleaned.get("language") or self.instance.language or OpenPlotListing.Language.ENGLISH
        )
        if cleaned.get("contact_number"):
            try:
                cleaned["contact_number"] = _international_phone(
                    cleaned["contact_number"], cleaned.get("contact_country_code") or "+91"
                )
            except ValidationError as exc:
                self.add_error("contact_number", exc)
        area = cleaned.get("area")
        total = cleaned.get("total_price")
        if area and total:
            self.instance.price_per_unit = (Decimal(total) / area).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return cleaned


class PrivateDetailsForm(BootstrapFormMixin, forms.ModelForm):
    owner_phone = forms.CharField(label="Owner phone", max_length=20)
    owner_country_code = forms.ChoiceField(
        choices=COUNTRY_CODES, label="Country code", initial="+91", required=False
    )

    class Meta:
        model = OpenPlotPrivateDetails
        fields = ("owner_name", "owner_phone", "internal_notes", "negotiable_amount")
        labels = {"negotiable_amount": "Lowest acceptable amount (₹, optional)"}
        widgets = {"internal_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.owner_phone:
            country, local = _phone_parts(self.instance.owner_phone)
            self.initial["owner_country_code"] = country
            self.initial["owner_phone"] = local
        self.fields["owner_phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel-national", "placeholder": "98765 43210"}
        )
        self.style_fields()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("owner_phone"):
            try:
                cleaned["owner_phone"] = _international_phone(
                    cleaned["owner_phone"], cleaned.get("owner_country_code") or "+91"
                )
            except ValidationError as exc:
                self.add_error("owner_phone", exc)
        return cleaned


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
    language = forms.ChoiceField(
        choices=OpenPlotListing.Language.choices,
        label="Advert language",
        initial=OpenPlotListing.Language.ENGLISH,
        required=False,
    )
    logo = forms.FileField(required=False, help_text="Optional PNG or JPEG logo, up to 1 MB")

    def clean_language(self):
        return self.cleaned_data["language"] or OpenPlotListing.Language.ENGLISH

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


class PublicationForm(BootstrapFormMixin, forms.Form):
    platform = forms.ChoiceField(
        label="Where should we post?",
        choices=(
            ("facebook", "Facebook"),
            ("instagram", "Instagram"),
            ("all", "Facebook and Instagram"),
        ),
    )

    @property
    def platforms(self) -> list[str]:
        return {
            "facebook": ["facebook"],
            "instagram": ["instagram"],
            "all": ["facebook", "instagram"],
        }[self.cleaned_data["platform"]]
