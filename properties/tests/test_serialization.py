import json
from decimal import Decimal
from uuid import UUID

from properties.domain import PrivateOpenPlot, PublicOpenPlot
from properties.serializers import serialize_private_details, serialize_public_details

PLOT_ID = UUID("2ed678c5-8b94-41d3-a803-2ffddb0cb485")


def make_public_plot() -> PublicOpenPlot:
    return PublicOpenPlot(
        public_id=PLOT_ID,
        status="published",
        title="East-facing plot",
        location="Shamshabad, Hyderabad",
        landmark="Near ORR Exit 15",
        area=Decimal("267.00"),
        area_unit="sq_yd",
        total_price=4_800_000,
        price_per_unit=Decimal("17977.53"),
        facing="east",
        road_width_ft=Decimal("30.00"),
        approval_type="hmda",
        contact_number="+919876543210",
        language="te",
    )


def make_private_plot() -> PrivateOpenPlot:
    return PrivateOpenPlot(
        listing_id=PLOT_ID,
        owner_name="Private Owner",
        owner_phone="+919800000000",
        internal_notes="Never publish this note",
        negotiable_amount=4_500_000,
    )


def test_public_and_private_serializers_use_disjoint_field_sets():
    public = serialize_public_details(make_public_plot())
    private = serialize_private_details(make_private_plot())
    assert set(public).isdisjoint(private)


def test_private_values_never_appear_in_public_serialization():
    serialized = json.dumps(serialize_public_details(make_public_plot()))

    for private_value in (
        "Private Owner",
        "+919800000000",
        "Never publish this note",
        "4500000",
    ):
        assert private_value not in serialized
