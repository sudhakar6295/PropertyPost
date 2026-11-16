from django.views.generic import TemplateView

from .models import AdvertVersion, OpenPlotListing


class PropertyListView(TemplateView):
    template_name = "properties/property_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current = list(OpenPlotListing.objects.filter(status=OpenPlotListing.Status.PUBLISHED))
        # A broker may be drafting a revision while the earlier advert stays live.
        earlier = AdvertVersion.objects.exclude(
            listing__status=OpenPlotListing.Status.PUBLISHED
        ).order_by("listing_id", "-version_number")
        previous_public = []
        seen = set()
        for version in earlier:
            if (
                version.listing_id not in seen
                and version.publication_results
                and version.public_details
            ):
                previous_public.append(version.public_details)
                seen.add(version.listing_id)
        context["properties"] = current + previous_public
        return context
