"""Django ORM implementation of the replaceable repository contracts."""

from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

from properties.domain import PrivateOpenPlot, PublicOpenPlot
from properties.models import OpenPlotListing, OpenPlotPrivateDetails


def _to_public_domain(listing: OpenPlotListing) -> PublicOpenPlot:
    return PublicOpenPlot(
        public_id=listing.public_id,
        status=listing.status,
        title=listing.title,
        location=listing.location,
        landmark=listing.landmark,
        area=listing.area,
        area_unit=listing.area_unit,
        total_price=listing.total_price,
        price_per_unit=listing.price_per_unit,
        facing=listing.facing,
        road_width_ft=listing.road_width_ft,
        approval_type=listing.approval_type,
        contact_number=listing.contact_number,
        language=listing.language,
    )


class DjangoPublicOpenPlotRepository:
    """Reads and writes only the public listing table."""

    public_fields = (
        "public_id",
        "status",
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

    def get(self, public_id: UUID) -> PublicOpenPlot | None:
        listing = (
            OpenPlotListing.objects.only(*self.public_fields).filter(public_id=public_id).first()
        )
        return _to_public_domain(listing) if listing else None

    def list_published(self) -> list[PublicOpenPlot]:
        listings = OpenPlotListing.objects.filter(status=OpenPlotListing.Status.PUBLISHED).only(
            *self.public_fields
        )
        return [_to_public_domain(listing) for listing in listings]

    def save(self, plot: PublicOpenPlot) -> None:
        listing = OpenPlotListing.objects.filter(public_id=plot.public_id).first()
        if listing is None:
            raise ImproperlyConfigured(
                "Create plots through the broker workflow to assign ownership."
            )
        for field, value in {
            "status": plot.status,
            "title": plot.title,
            "location": plot.location,
            "landmark": plot.landmark,
            "area": plot.area,
            "area_unit": plot.area_unit,
            "total_price": plot.total_price,
            "price_per_unit": plot.price_per_unit,
            "facing": plot.facing,
            "road_width_ft": plot.road_width_ft,
            "approval_type": plot.approval_type,
            "contact_number": plot.contact_number,
            "language": plot.language,
        }.items():
            setattr(listing, field, value)
        listing.full_clean()
        listing.save()


class DjangoPrivateOpenPlotRepository:
    """Reads and writes only the restricted details table."""

    def get(self, listing_id: UUID) -> PrivateOpenPlot | None:
        details = (
            OpenPlotPrivateDetails.objects.select_related("listing")
            .filter(listing__public_id=listing_id)
            .first()
        )
        if details is None:
            return None
        return PrivateOpenPlot(
            listing_id=details.listing.public_id,
            owner_name=details.owner_name,
            owner_phone=details.owner_phone,
            internal_notes=details.internal_notes,
            negotiable_amount=details.negotiable_amount,
        )

    def save(self, details: PrivateOpenPlot) -> None:
        listing = OpenPlotListing.objects.get(public_id=details.listing_id)
        stored = OpenPlotPrivateDetails.objects.filter(listing=listing).first()
        if stored is None:
            stored = OpenPlotPrivateDetails(listing=listing)
        stored.owner_name = details.owner_name
        stored.owner_phone = details.owner_phone
        stored.internal_notes = details.internal_notes
        stored.negotiable_amount = details.negotiable_amount
        stored.full_clean()
        stored.save()
