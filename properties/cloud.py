"""Cloud service adapters; Google clients use Application Default Credentials."""

from pathlib import Path

from django.conf import settings
from google.cloud import storage


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
