from decimal import Decimal

import pytest
from django.urls import reverse

from properties.models import OpenPlotListing, OpenPlotPrivateDetails


def create_listing(title, status, broker):
    return OpenPlotListing.objects.create(
        broker=broker,
        title=title,
        location="Shamshabad, Hyderabad",
        landmark="Near ORR Exit 15",
        area=Decimal("267.00"),
        area_unit=OpenPlotListing.AreaUnit.SQ_YD,
        total_price=4_800_000,
        price_per_unit=Decimal("17977.53"),
        facing=OpenPlotListing.Facing.EAST,
        road_width_ft=Decimal("30.00"),
        approval_type=OpenPlotListing.ApprovalType.HMDA,
        contact_number="+919876543210",
        language=OpenPlotListing.Language.TELUGU,
        status=status,
    )


@pytest.mark.django_db
def test_home_page_uses_bootstrap_and_only_shows_published_listings(client, django_user_model):
    broker = django_user_model.objects.create_user(username="broker", password="testpass123")
    published = create_listing("Published open plot", OpenPlotListing.Status.PUBLISHED, broker)
    create_listing("Hidden draft", OpenPlotListing.Status.DRAFT, broker)
    OpenPlotPrivateDetails.objects.create(
        listing=published,
        owner_name="Private Owner",
        owner_phone="+919800000000",
        internal_notes="Never expose this note",
        negotiable_amount=4_500_000,
    )

    response = client.get(reverse("properties:list"))

    assert response.status_code == 200
    assert b"bootstrap" in response.content.lower()
    assert b"Published open plot" in response.content
    assert b"Hidden draft" not in response.content
    assert b"Private Owner" not in response.content
    assert b"+919800000000" not in response.content
    assert b"Never expose this note" not in response.content
    assert b"4500000" not in response.content
