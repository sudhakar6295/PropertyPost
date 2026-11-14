from io import BytesIO
from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from properties.cloud import (
    GoogleObjectStore,
    LocalObjectStore,
)
from properties.forms import PhotoForm


def image_upload(name="photo.png", mime="image/png", size=(12, 12)):
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type=mime)


def test_local_object_store_persists_private_file_bytes():
    objects = LocalObjectStore()
    objects.upload("originals/1/plot/photo.png", b"private bytes", "image/png")
    assert objects.download("originals/1/plot/photo.png") == b"private bytes"


def test_google_object_boundary_never_sets_public_access():
    client = Mock()
    store = GoogleObjectStore("private-bucket", "project-id", client=client)
    store.upload("posters/plot/poster.png", b"image", "image/png")
    client.bucket.assert_called_once_with("private-bucket")
    blob = client.bucket.return_value.blob.return_value
    blob.upload_from_string.assert_called_once_with(b"image", content_type="image/png")
    assert not blob.make_public.called
    assert not blob.acl.save.called


@pytest.mark.parametrize(
    ("name", "mime"),
    [("photo.exe", "image/png"), ("photo.jpg", "image/png"), ("photo.png", "text/plain")],
)
def test_rejects_extension_or_mime_mismatch(name, mime):
    assert not PhotoForm(files={"image": image_upload(name, mime)}).is_valid()


def test_rejects_non_image_and_large_file():
    bogus = SimpleUploadedFile("photo.png", b"not an image", content_type="image/png")
    assert not PhotoForm(files={"image": bogus}).is_valid()
    large = SimpleUploadedFile("photo.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png")
    assert not PhotoForm(files={"image": large}).is_valid()
