from io import BytesIO
from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from properties.cloud import (
    GoogleDocumentStore,
    GoogleObjectStore,
    LocalDocumentStore,
    LocalObjectStore,
)
from properties.forms import PhotoForm


def image_upload(name="photo.png", mime="image/png", size=(12, 12)):
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type=mime)


def test_local_adapters_hold_only_paths_and_metadata():
    documents = LocalDocumentStore()
    objects = LocalObjectStore()
    objects.upload("originals/1/plot/photo.png", b"private bytes", "image/png")
    documents.put("listings", "plot", {"photos": [{"object_path": "originals/1/plot/photo.png"}]})
    assert documents.get("listings", "plot")["photos"][0]["object_path"]
    assert objects.download("originals/1/plot/photo.png") == b"private bytes"
    assert "private bytes" not in str(documents.documents)


def test_google_document_boundary_uses_named_collections_and_no_credentials_file():
    client = Mock()
    snapshot = client.collection.return_value.document.return_value.get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = {"status": "draft"}
    store = GoogleDocumentStore("project-id", client=client)
    store.put("generation_jobs", "job-1", {"status": "queued"})
    assert store.get("listings", "plot-1") == {"status": "draft"}
    client.collection.assert_any_call("generation_jobs")
    client.collection.assert_any_call("listings")
    with pytest.raises(ValueError):
        store.put("unknown", "x", {})
    with pytest.raises(ValueError):
        store.get("sites", "bad/path")


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
