"""Root URL configuration for PropertyPost."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from properties import api_views, broker_views, social_publish_views, social_views

from .health import health, ready

urlpatterns = [
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),
    path(
        "api/v1/listings/<uuid:public_id>/automation-input/",
        api_views.automation_input,
        name="automation-input",
    ),
    path(
        "api/v1/listings/<uuid:public_id>/generation-result/",
        api_views.generation_result,
        name="generation-result",
    ),
    path(
        "api/v1/listings/<uuid:public_id>/publication-result/",
        api_views.publication_result,
        name="publication-result",
    ),
    path(
        "api/v1/listings/<uuid:public_id>/images/<int:photo_id>/",
        api_views.signed_image,
        name="automation-image",
    ),
    path(
        "api/v1/listings/<uuid:public_id>/poster/",
        api_views.signed_poster,
        name="automation-poster",
    ),
    path("admin/", admin.site.urls),
    path("login/", broker_views.broker_login, name="broker-login"),
    path("logout/", broker_views.broker_logout, name="broker-logout"),
    path("dashboard/", broker_views.dashboard, name="dashboard"),
    path("accounts/social/", social_views.social_accounts, name="social-accounts"),
    path("accounts/social/meta/connect/", social_views.meta_connect, name="meta-connect"),
    path("accounts/social/meta/callback/", social_views.meta_callback, name="meta-callback"),
    path(
        "accounts/social/<int:account_id>/disconnect/",
        social_views.meta_disconnect,
        name="meta-disconnect",
    ),
    path("plots/add/", broker_views.add_plot, name="add-plot"),
    path("plots/<uuid:public_id>/edit/", broker_views.edit_plot, name="edit-plot"),
    path("plots/<uuid:public_id>/photos/", broker_views.upload_photos, name="upload-photos"),
    path(
        "plots/<uuid:public_id>/photos/order/", broker_views.arrange_photos, name="arrange-photos"
    ),
    path(
        "plots/<uuid:public_id>/photos/<int:photo_id>/",
        broker_views.private_photo,
        name="private-photo",
    ),
    path("plots/<uuid:public_id>/review/", broker_views.review_details, name="review-details"),
    path(
        "plots/<uuid:public_id>/revise/",
        broker_views.revise_published_advert,
        name="revise-published-advert",
    ),
    path("plots/<uuid:public_id>/history/", broker_views.advert_history, name="advert-history"),
    path(
        "plots/<uuid:public_id>/history/<int:version_number>/poster/",
        broker_views.version_poster,
        name="version-poster",
    ),
    path("plots/<uuid:public_id>/generate/", broker_views.generate_advert, name="generate-advert"),
    path(
        "plots/<uuid:public_id>/generation-status/",
        broker_views.generation_status,
        name="generation-status",
    ),
    path("plots/<uuid:public_id>/poster/", broker_views.private_poster, name="private-poster"),
    path("plots/<uuid:public_id>/preview/", broker_views.advert_preview, name="advert-preview"),
    path("plots/<uuid:public_id>/publish/", broker_views.publish_plot, name="publish-plot"),
    path(
        "plots/<uuid:public_id>/publish/meta/",
        social_publish_views.publish_social,
        name="publish-social",
    ),
    path(
        "plots/<uuid:public_id>/published/",
        broker_views.published_result,
        name="published-result",
    ),
    path(
        "plots/<uuid:public_id>/publication-status/",
        broker_views.publication_status,
        name="publication-status",
    ),
    path("", include("properties.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
