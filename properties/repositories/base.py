"""Persistence-independent repository contracts."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from properties.domain import PrivateOpenPlot, PublicOpenPlot


class PublicOpenPlotRepository(Protocol):
    def get(self, public_id: UUID) -> PublicOpenPlot | None: ...

    def list_published(self) -> Sequence[PublicOpenPlot]: ...

    def save(self, plot: PublicOpenPlot) -> None: ...


class PrivateOpenPlotRepository(Protocol):
    def get(self, listing_id: UUID) -> PrivateOpenPlot | None: ...

    def save(self, details: PrivateOpenPlot) -> None: ...
