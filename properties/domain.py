"""Persistence-independent domain records for Open Plot / Land for Sale."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicOpenPlot:
    """Public details plus non-content identity and workflow metadata."""

    public_id: UUID
    status: str
    title: str
    location: str
    landmark: str
    area: Decimal
    area_unit: str
    total_price: int
    price_per_unit: Decimal | None
    facing: str
    road_width_ft: Decimal
    approval_type: str
    contact_number: str
    language: str


@dataclass(frozen=True, slots=True)
class PrivateOpenPlot:
    """Restricted details that must never enter a public representation."""

    listing_id: UUID
    owner_name: str
    owner_phone: str
    internal_notes: str
    negotiable_amount: int | None
