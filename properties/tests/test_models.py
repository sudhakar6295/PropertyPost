from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from properties.models import OpenPlotListing, OpenPlotPrivateDetails


def make_listing(**overrides):
    values = {
        "title": "East-facing plot",
        "location": "Shamshabad, Hyderabad",
        "landmark": "Near ORR Exit 15",
        "area": Decimal("267.00"),
        "area_unit": OpenPlotListing.AreaUnit.SQ_YD,
        "total_price": 4_800_000,
        "price_per_unit": Decimal("17977.53"),
        "facing": OpenPlotListing.Facing.EAST,
        "road_width_ft": Decimal("30.00"),
        "approval_type": OpenPlotListing.ApprovalType.HMDA,
        "contact_number": "+919876543210",
        "language": OpenPlotListing.Language.TELUGU,
        "status": OpenPlotListing.Status.DRAFT,
    }
    values.update(overrides)
    return OpenPlotListing(**values)


@pytest.mark.django_db
def test_open_plot_accepts_valid_public_details(django_user_model):
    broker = django_user_model.objects.create_user(username="broker")
    make_listing(broker=broker).full_clean()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("area", Decimal("0")),
        ("total_price", 0),
        ("price_per_unit", Decimal("-1")),
        ("road_width_ft", Decimal("0")),
        ("contact_number", "9876543210"),
        ("area_unit", "hectare"),
        ("facing", "up"),
        ("approval_type", "unknown"),
        ("language", "xx"),
        ("status", "unknown"),
    ],
)
@pytest.mark.django_db
def test_open_plot_rejects_invalid_public_details(field, value, django_user_model):
    broker = django_user_model.objects.create_user(username="broker")
    with pytest.raises(ValidationError):
        make_listing(broker=broker, **{field: value}).full_clean()


def test_statuses_match_the_required_workflow():
    assert {value for value, _ in OpenPlotListing.Status.choices} == {
        "draft",
        "ready",
        "generating",
        "review",
        "approved",
        "publishing",
        "published",
        "failed",
    }


@pytest.mark.django_db
def test_private_details_are_stored_separately_and_negotiation_is_validated(django_user_model):
    broker = django_user_model.objects.create_user(username="broker")
    listing = make_listing(broker=broker)
    listing.full_clean()
    listing.save()
    public_field_names = {field.name for field in OpenPlotListing._meta.get_fields()}
    private_field_names = {field.name for field in OpenPlotPrivateDetails._meta.get_fields()}

    assert {"owner_name", "owner_phone", "internal_notes", "negotiable_amount"}.isdisjoint(
        public_field_names
    )
    assert {"owner_name", "owner_phone", "internal_notes", "negotiable_amount"} <= (
        private_field_names
    )

    private = OpenPlotPrivateDetails(
        listing=listing,
        owner_name="Owner",
        owner_phone="+919800000000",
        internal_notes="Restricted note",
        negotiable_amount=listing.total_price + 1,
    )
    with pytest.raises(ValidationError, match="cannot exceed"):
        private.full_clean()
