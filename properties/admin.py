from django.contrib import admin

from .models import OpenPlotListing, OpenPlotPrivateDetails


@admin.register(OpenPlotListing)
class OpenPlotListingAdmin(admin.ModelAdmin):
    list_display = ("title", "location", "area", "area_unit", "total_price", "status")
    list_filter = ("status", "area_unit", "facing", "approval_type", "language")
    search_fields = ("title", "location", "landmark", "contact_number")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(OpenPlotPrivateDetails)
class OpenPlotPrivateDetailsAdmin(admin.ModelAdmin):
    list_display = ("listing", "owner_name", "updated_at")
    search_fields = ("owner_name", "owner_phone", "listing__title")
    readonly_fields = ("created_at", "updated_at")
