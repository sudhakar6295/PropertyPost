"""Firestore adapters implemented against a small, replaceable document-store port."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from properties.domain import PrivateOpenPlot, PublicOpenPlot
from properties.firestore import (
    PUBLIC_COLLECTION,
    private_document_path,
    public_document_path,
    to_private_document,
    to_public_document,
)


class FirestoreDocumentStore(Protocol):
    """Minimal adapter API to be implemented with any Firestore client library."""

    def get_document(self, path: str) -> Mapping[str, Any] | None: ...

    def set_document(self, path: str, document: Mapping[str, Any]) -> None: ...

    def query_documents(
        self, collection: str, *, field: str, operator: str, value: object
    ) -> Sequence[Mapping[str, Any]]: ...


def _public_from_document(public_id: UUID, document: Mapping[str, Any]) -> PublicOpenPlot:
    details = document["public_details"]
    return PublicOpenPlot(
        public_id=public_id,
        status=str(document["status"]),
        title=str(details["title"]),
        location=str(details["location"]),
        landmark=str(details["landmark"]),
        area=Decimal(str(details["area"])),
        area_unit=str(details["area_unit"]),
        total_price=int(details["total_price"]),
        price_per_unit=(
            Decimal(str(details["price_per_unit"]))
            if details.get("price_per_unit") is not None
            else None
        ),
        facing=str(details["facing"]),
        road_width_ft=Decimal(str(details["road_width_ft"])),
        approval_type=str(details["approval_type"]),
        contact_number=str(details["contact_number"]),
        language=str(details["language"]),
    )


class FirestorePublicOpenPlotRepository:
    def __init__(self, store: FirestoreDocumentStore) -> None:
        self.store = store

    def get(self, public_id: UUID) -> PublicOpenPlot | None:
        document = self.store.get_document(public_document_path(public_id))
        return _public_from_document(public_id, document) if document else None

    def list_published(self) -> list[PublicOpenPlot]:
        documents = self.store.query_documents(
            PUBLIC_COLLECTION,
            field="status",
            operator="==",
            value="published",
        )
        return [
            _public_from_document(UUID(str(document["document_id"])), document)
            for document in documents
        ]

    def save(self, plot: PublicOpenPlot) -> None:
        self.store.set_document(public_document_path(plot.public_id), to_public_document(plot))


class FirestorePrivateOpenPlotRepository:
    def __init__(self, store: FirestoreDocumentStore) -> None:
        self.store = store

    def get(self, listing_id: UUID) -> PrivateOpenPlot | None:
        document = self.store.get_document(private_document_path(listing_id))
        if document is None:
            return None
        details = document["private_details"]
        return PrivateOpenPlot(
            listing_id=listing_id,
            owner_name=str(details["owner_name"]),
            owner_phone=str(details["owner_phone"]),
            internal_notes=str(details["internal_notes"]),
            negotiable_amount=(
                int(details["negotiable_amount"])
                if details.get("negotiable_amount") is not None
                else None
            ),
        )

    def save(self, details: PrivateOpenPlot) -> None:
        self.store.set_document(
            private_document_path(details.listing_id), to_private_document(details)
        )
