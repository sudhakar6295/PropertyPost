import pytest
from django.contrib.auth import get_user_model

from properties.domain import PrivateOpenPlot
from properties.models import OpenPlotListing, OpenPlotPrivateDetails
from properties.repositories.django import (
    DjangoPrivateOpenPlotRepository,
    DjangoPublicOpenPlotRepository,
)
from properties.tests.test_serialization import PLOT_ID, make_private_plot, make_public_plot


@pytest.mark.django_db
def test_mysql_repositories_keep_public_and_private_fields_separate():
    broker = get_user_model().objects.create_user(username="broker")
    public = make_public_plot()
    listing = OpenPlotListing.objects.create(
        public_id=PLOT_ID,
        broker=broker,
        status=public.status,
        title=public.title,
        location=public.location,
        landmark=public.landmark,
        area=public.area,
        area_unit=public.area_unit,
        total_price=public.total_price,
        price_per_unit=public.price_per_unit,
        facing=public.facing,
        road_width_ft=public.road_width_ft,
        approval_type=public.approval_type,
        contact_number=public.contact_number,
        language=public.language,
    )
    private = make_private_plot()
    OpenPlotPrivateDetails.objects.create(
        listing=listing,
        owner_name=private.owner_name,
        owner_phone=private.owner_phone,
        internal_notes=private.internal_notes,
        negotiable_amount=private.negotiable_amount,
    )

    public_repository = DjangoPublicOpenPlotRepository()
    private_repository = DjangoPrivateOpenPlotRepository()

    assert public_repository.get(PLOT_ID) == public
    assert public_repository.list_published() == [public]
    assert private_repository.get(PLOT_ID) == private
    updated = PrivateOpenPlot(
        listing_id=PLOT_ID,
        owner_name="Owner updated",
        owner_phone=private.owner_phone,
        internal_notes=private.internal_notes,
        negotiable_amount=4_500_000,
    )
    private_repository.save(updated)
    assert private_repository.get(PLOT_ID) == updated
