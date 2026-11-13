"""Firestore document paths and deterministic document mapping."""

from typing import Any

from .domain import PrivateOpenPlot, PublicOpenPlot
from .serializers import serialize_private_details, serialize_public_details

SCHEMA_VERSION = 1
CATEGORY = "open_plot_land_for_sale"
PUBLIC_COLLECTION = "open_plot_public"
PRIVATE_COLLECTION = "open_plot_private"


def public_document_path(public_id: object) -> str:
    return f"{PUBLIC_COLLECTION}/{public_id}"


def private_document_path(public_id: object) -> str:
    return f"{PRIVATE_COLLECTION}/{public_id}"


def to_public_document(plot: PublicOpenPlot) -> dict[str, Any]:
    """Build the independently readable public Firestore document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "category": CATEGORY,
        "status": plot.status,
        "public_details": serialize_public_details(plot),
    }


def to_private_document(plot: PrivateOpenPlot) -> dict[str, Any]:
    """Build the access-restricted private Firestore document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "category": CATEGORY,
        "private_details": serialize_private_details(plot),
    }
