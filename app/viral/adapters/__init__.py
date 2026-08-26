"""Source adapters for the Viral Idea Finder.

Each adapter normalizes content from an external source into
ViralContentItem-compatible dicts.
"""

from app.viral.adapters.base import SourceAdapter, NormalizedItem
from app.viral.adapters.rss import RSSAdapter
from app.viral.adapters.jina import JinaAdapter

ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {
    "rss": RSSAdapter,
    "jina": JinaAdapter,
}


def get_adapter(source: str) -> SourceAdapter:
    """Return an adapter instance for the given source name."""
    cls = ADAPTER_REGISTRY.get(source)
    if cls is None:
        raise ValueError(f"Unknown source adapter: {source!r}")
    return cls()


def list_sources() -> list[str]:
    """Return all registered source names."""
    return list(ADAPTER_REGISTRY.keys())
