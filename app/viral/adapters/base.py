"""Base source adapter interface for the Viral Idea Finder.

New sources are added by subclassing ``SourceAdapter`` and implementing
``search`` and ``normalize``.  Register the new adapter in
``app/viral/adapters/__init__.py``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedItem:
    """A content item normalized to the internal format.

    Every adapter must produce objects matching this shape so the
    downstream scoring and clustering stages work uniformly.
    """

    source: str
    source_url: str
    title: str
    description: str = ""
    author: str | None = None
    published_at: datetime | None = None
    topic: str | None = None
    language: str | None = None
    engagement: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(abc.ABC):
    """Abstract base for content source adapters."""

    source_name: str = "unknown"

    @abc.abstractmethod
    async def search(self, query: str, max_items: int = 20) -> list[NormalizedItem]:
        """Search the source and return normalized content items."""

    @abc.abstractmethod
    async def collect(self, url: str) -> NormalizedItem | None:
        """Fetch and normalize a single URL from the source."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name!r}>"
