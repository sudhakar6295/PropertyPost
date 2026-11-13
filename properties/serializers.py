"""Explicit allow-list serializers for public and private property details."""

from typing import Any

from .domain import PrivateOpenPlot, PublicOpenPlot

PUBLIC_DETAIL_FIELDS = frozenset(
    {
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
    }
)

PRIVATE_DETAIL_FIELDS = frozenset(
    {"owner_name", "owner_phone", "internal_notes", "negotiable_amount"}
)


def serialize_public_details(plot: PublicOpenPlot) -> dict[str, Any]:
    """Serialize only the approved public field allow-list."""
    return {
        "title": plot.title,
        "location": plot.location,
        "landmark": plot.landmark,
        "area": str(plot.area),
        "area_unit": plot.area_unit,
        "total_price": plot.total_price,
        "price_per_unit": str(plot.price_per_unit) if plot.price_per_unit is not None else None,
        "facing": plot.facing,
        "road_width_ft": str(plot.road_width_ft),
        "approval_type": plot.approval_type,
        "contact_number": plot.contact_number,
        "language": plot.language,
    }


def serialize_private_details(plot: PrivateOpenPlot) -> dict[str, Any]:
    """Serialize restricted fields for private storage only."""
    return {
        "owner_name": plot.owner_name,
        "owner_phone": plot.owner_phone,
        "internal_notes": plot.internal_notes,
        "negotiable_amount": plot.negotiable_amount,
    }
