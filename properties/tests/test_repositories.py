from collections.abc import Mapping
from typing import Any

from properties.firestore import private_document_path, public_document_path
from properties.repositories.firestore import (
    FirestorePrivateOpenPlotRepository,
    FirestorePublicOpenPlotRepository,
)
from properties.tests.test_serialization import PLOT_ID, make_private_plot, make_public_plot


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def get_document(self, path: str) -> Mapping[str, Any] | None:
        return self.documents.get(path)

    def set_document(self, path: str, document: Mapping[str, Any]) -> None:
        self.documents[path] = dict(document)

    def query_documents(
        self, collection: str, *, field: str, operator: str, value: object
    ) -> list[Mapping[str, Any]]:
        assert operator == "=="
        results = []
        for path, document in self.documents.items():
            if path.startswith(f"{collection}/") and document.get(field) == value:
                results.append({**document, "document_id": path.split("/", maxsplit=1)[1]})
        return results


def test_firestore_repositories_round_trip_through_separate_paths():
    store = InMemoryDocumentStore()
    public_repository = FirestorePublicOpenPlotRepository(store)
    private_repository = FirestorePrivateOpenPlotRepository(store)
    public = make_public_plot()
    private = make_private_plot()

    public_repository.save(public)
    private_repository.save(private)

    assert set(store.documents) == {
        public_document_path(PLOT_ID),
        private_document_path(PLOT_ID),
    }
    assert public_repository.get(PLOT_ID) == public
    assert private_repository.get(PLOT_ID) == private
    assert public_repository.list_published() == [public]
