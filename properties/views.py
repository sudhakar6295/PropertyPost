from django.views.generic import TemplateView

from .models import OpenPlotListing


class PropertyListView(TemplateView):
    template_name = "properties/property_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["properties"] = OpenPlotListing.objects.filter(
            status=OpenPlotListing.Status.PUBLISHED
        )
        return context
