"""The broker form derives public prices and formats phones safely."""

from decimal import Decimal

import pytest

from properties.forms import GenerateForm, PlotForm, PrivateDetailsForm
from properties.models import OpenPlotListing, OpenPlotPrivateDetails
from properties.repositories.django import _to_public_domain
from properties.serializers import serialize_public_details


def public_data(**overrides):
    data = {
        "title": "Corner plot",
        "location": "Hyderabad",
        "landmark": "Near the school",
        "area": "200",
        "area_unit": "sq_yd",
        "total_price": "3000000",
        "facing": "east",
        "approval_type": "hmda",
        "contact_country_code": "+91",
        "contact_number": "98765 43210",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_plot_form_calculates_unit_price_and_accepts_unknown_road_width():
    form = PlotForm(data=public_data())
    assert form.is_valid(), form.errors
    assert form.instance.price_per_unit == Decimal("15000.00")
    assert form.instance.road_width_ft is None
    assert form.instance.contact_number == "+919876543210"
    assert form.instance.language == OpenPlotListing.Language.ENGLISH
    assert "price_per_unit" not in form.fields


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    (
        "title",
        "location",
        "landmark",
        "area",
        "area_unit",
        "total_price",
        "facing",
        "approval_type",
    ),
)
def test_required_plot_fields_reject_blank_values(field):
    form = PlotForm(data=public_data(**{field: ""}))
    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.django_db
def test_country_selector_applies_to_public_and_private_numbers():
    public_form = PlotForm(
        data=public_data(contact_country_code="+971", contact_number="501234567")
    )
    private_form = PrivateDetailsForm(
        data={"owner_name": "Owner", "owner_country_code": "+44", "owner_phone": "7700 900123"}
    )
    assert public_form.is_valid(), public_form.errors
    assert private_form.is_valid(), private_form.errors
    assert public_form.instance.contact_number == "+971501234567"
    assert private_form.instance.owner_phone == "+447700900123"


@pytest.mark.django_db
def test_country_selector_rejects_short_local_numbers():
    form = PlotForm(data=public_data(contact_number="123456"))
    assert not form.is_valid()
    assert "contact_number" in form.errors


@pytest.mark.django_db
def test_edit_phone_inputs_show_local_digits_beside_saved_country():
    listing = OpenPlotListing(contact_number="+971501234567")
    details = OpenPlotPrivateDetails(owner_phone="+919800000000")
    public_form = PlotForm(instance=listing)
    private_form = PrivateDetailsForm(instance=details)
    assert public_form["contact_number"].value() == "501234567"
    assert public_form["contact_country_code"].value() == "+971"
    assert private_form["owner_phone"].value() == "9800000000"


@pytest.mark.django_db
def test_optional_road_width_serializes_as_null_without_private_details():
    form = PlotForm(data=public_data())
    assert form.is_valid(), form.errors
    listing = form.instance
    payload = serialize_public_details(_to_public_domain(listing))
    assert payload["road_width_ft"] is None
    assert "owner_phone" not in payload


def test_generation_language_defaults_to_english_and_validates_choices():
    default = GenerateForm(data={"template": "classic"})
    assert default.is_valid(), default.errors
    assert default.cleaned_data["language"] == "en"
    telugu = GenerateForm(data={"template": "classic", "language": "te"})
    assert telugu.is_valid(), telugu.errors
    assert telugu.cleaned_data["language"] == "te"
    invalid = GenerateForm(data={"template": "classic", "language": "xx"})
    assert not invalid.is_valid()
    assert "language" in invalid.errors
