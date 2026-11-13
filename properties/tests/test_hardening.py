from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from properties.cloud import LocalFileObjectStore
from properties.forms import PhotoForm
from properties.models import OpenPlotListing
from properties.tests.test_views import create_listing


def test_health_and_readiness(client, db):
    assert client.get(reverse("health")).json() == {"status": "ok"}
    assert client.get(reverse("ready")).json() == {"status": "ready"}


def test_local_object_store_confines_paths(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    store = LocalFileObjectStore()
    store.upload("originals/plot.png", b"bytes", "image/png")
    assert store.download("originals/plot.png") == b"bytes"
    with pytest.raises(ValueError):
        store.upload("../outside.png", b"bad", "image/png")


def test_upload_rejects_excessive_dimensions():
    output = BytesIO()
    Image.new("RGB", (7000, 6000), "white").save(output, "PNG")
    file = SimpleUploadedFile("huge.png", output.getvalue(), content_type="image/png")
    assert not PhotoForm(files={"image": file}).is_valid()


@pytest.mark.django_db
def test_published_plot_rejects_edits_and_photo_changes(client, django_user_model):
    broker = django_user_model.objects.create_user(username="broker", password="StrongPass123!")
    plot = create_listing("Published", OpenPlotListing.Status.PUBLISHED, broker)
    client.force_login(broker)
    assert client.post(reverse("edit-plot", args=[plot.public_id]), {}).status_code == 400
    assert client.post(reverse("upload-photos", args=[plot.public_id]), {}).status_code == 400
    assert client.post(reverse("arrange-photos", args=[plot.public_id]), {}).status_code == 400
