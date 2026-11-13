"""Cloud service adapters; Google clients use Application Default Credentials."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from google.cloud import firestore, storage

COLLECTIONS = frozenset(
    {"users", "sites", "listings", "listing_private", "generation_jobs", "publication_jobs"}
)


class GoogleDocumentStore:
    def __init__(self, project_id: str, database: str = "(default)", client=None):
        self.client = client or firestore.Client(project=project_id, database=database)

    def _reference(self, collection: str, document_id: str):
        if collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if not document_id or "/" in document_id:
            raise ValueError("Invalid document ID")
        return self.client.collection(collection).document(document_id)

    def get(self, collection: str, document_id: str) -> dict[str, Any] | None:
        snapshot = self._reference(collection, document_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def put(self, collection: str, document_id: str, data: Mapping[str, Any]) -> None:
        self._reference(collection, document_id).set(dict(data))

    def query(self, collection: str, field: str, value: object) -> list[dict[str, Any]]:
        if collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        results = (
            self.client.collection(collection)
            .where(filter=firestore.FieldFilter(field, "==", value))
            .stream()
        )
        return [{"document_id": snap.id, **snap.to_dict()} for snap in results]


class LocalDocumentStore:
    def __init__(self):
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, collection: str, document_id: str) -> dict[str, Any] | None:
        return self.documents.get((collection, document_id))

    def put(self, collection: str, document_id: str, data: Mapping[str, Any]) -> None:
        self.documents[(collection, document_id)] = dict(data)

    def query(self, collection: str, field: str, value: object) -> list[dict[str, Any]]:
        return [
            {"document_id": document_id, **data}
            for (name, document_id), data in self.documents.items()
            if name == collection and data.get(field) == value
        ]


class GoogleObjectStore:
    """Private GCS objects; never creates public ACLs or returns public URLs."""

    def __init__(self, bucket_name: str, project_id: str, client=None):
        self.bucket = (client or storage.Client(project=project_id)).bucket(bucket_name)

    def upload(self, path: str, content: bytes, content_type: str) -> None:
        self.bucket.blob(path).upload_from_string(content, content_type=content_type)

    def download(self, path: str) -> bytes:
        return self.bucket.blob(path).download_as_bytes()


class LocalObjectStore:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def upload(self, path: str, content: bytes, content_type: str) -> None:
        self.objects[path] = (content, content_type)

    def download(self, path: str) -> bytes:
        return self.objects[path][0]


class LocalFileObjectStore:
    """Persistent local private files with paths confined to MEDIA_ROOT."""

    def _path(self, path: str) -> Path:
        root = Path(settings.MEDIA_ROOT).resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("Invalid object path")
        return target

    def upload(self, path: str, content: bytes, content_type: str) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def download(self, path: str) -> bytes:
        return self._path(path).read_bytes()
