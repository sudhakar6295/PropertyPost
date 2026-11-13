from django.urls import path

from .views import PropertyListView

app_name = "properties"

urlpatterns = [path("", PropertyListView.as_view(), name="list")]
