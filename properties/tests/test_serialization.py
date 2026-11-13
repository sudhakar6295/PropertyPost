import json
from decimal import Decimal
from uuid import UUID

from properties.domain import PrivateOpenPlot, PublicOpenPlot
from properties.firestore import (
    private_document_path,
    public_document_path,
    to_private_document,
    to_public_document,
)
from properties.serializers import PRIVATE_DETAIL_FIELDS, PUBLIC_DETAIL_FIELDS

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


def test_firestore_uses_separate_public_and_private_documents():
    public_document = to_public_document(make_public_plot())
    private_document = to_private_document(make_private_plot())

    assert public_document_path(PLOT_ID) == f"open_plot_public/{PLOT_ID}"
    assert private_document_path(PLOT_ID) == f"open_plot_private/{PLOT_ID}"
    assert set(public_document["public_details"]) == PUBLIC_DETAIL_FIELDS
    assert set(private_document["private_details"]) == PRIVATE_DETAIL_FIELDS
    assert "private_details" not in public_document
    assert "public_details" not in private_document


def test_private_values_never_appear_in_public_serialization():
    serialized = json.dumps(to_public_document(make_public_plot()))

    for private_value in (
        "Private Owner",
        "+919800000000",
        "Never publish this note",
        "4500000",
    ):
        assert private_value not in serialized
