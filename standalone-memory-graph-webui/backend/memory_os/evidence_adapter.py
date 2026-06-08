"""
Abstract adapter for raw evidence storage.

Evidence stores (e.g. Hindsight, vector databases, file-based archives) hold
unstructured or semi-structured evidence that supports the canonical facts in
the memory graph.  This module defines the interface that any concrete evidence
backend must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class EvidenceStoreAdapter(ABC):
    """Abstract interface for raw evidence storage.

    Concrete implementations should subclass this and provide real storage
    backends (Hindsight, Chroma, local filesystem, etc.).

    All methods that touch storage are async to allow non-blocking I/O in
    frameworks like FastAPI or asyncio-based agents.

    Usage::

        class MyHindsightAdapter(EvidenceStoreAdapter):
            async def recall(self, store_id, query, max_results=10):
                ...

        adapter = MyHindsightAdapter(config)
        results = await adapter.recall("user_alice_evidence", "exam score")
    """

    @abstractmethod
    async def recall(self, store_id: str, query: str, max_results: int = 10) -> List[dict]:
        """Search the evidence store for items matching *query*.

        Args:
            store_id: Identifier for the tenant's evidence store.
            query: Natural-language or keyword query.
            max_results: Maximum number of results to return.

        Returns:
            A list of evidence items (dicts with at least ``content`` and
            ``metadata`` keys).  Returns an empty list if nothing matches.
        """
        ...

    @abstractmethod
    async def retain(self, store_id: str, content: str, metadata: Optional[dict] = None) -> bool:
        """Store a new piece of evidence.

        Args:
            store_id: Identifier for the tenant's evidence store.
            content: The evidence text/content to store.
            metadata: Optional metadata dict (e.g. source, timestamp, tags).

        Returns:
            True if the evidence was stored successfully, False otherwise.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether the evidence store backend is reachable and healthy.

        Returns:
            True if the backend is healthy, False otherwise.
        """
        ...
