"""
Memory inventory — self-awareness of what the agent remembers.

MemoryInventory lets the agent (or a human operator) query the memory graph
to understand what facts are stored, how recently they were updated, and how
a particular fact has evolved over time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from memory_os.tenant import MemoryTenant


class MemoryInventory(ABC):
    """Provides self-awareness of what the agent remembers.

    Subclass this and inject your graph backend.

    Usage::

        class FalkorInventory(MemoryInventory):
            def __init__(self, graph_client):
                self._graph = graph_client

        inv = FalkorInventory(client)
        summary = await inv.memory_inventory(tenant, entity="alice")
    """

    @abstractmethod
    async def memory_inventory(self, tenant: MemoryTenant, entity: Optional[str] = None) -> Dict:
        """Return a summary of what the agent knows.

        If *entity* is provided, the summary is scoped to that subject.
        Otherwise it covers the entire tenant namespace.

        The returned dict should include at minimum:

        - ``total_facts``: int
        - ``by_status``: dict mapping status -> count
        - ``by_subject_type``: dict mapping subject_type -> count
        - ``subjects``: list of subject names (if entity is None)

        Args:
            tenant: The tenant whose memory to inventory.
            entity: Optional subject name to scope the inventory to.

        Returns:
            A dict summarising the memory contents.
        """
        ...

    @abstractmethod
    async def recent_updates(self, tenant: MemoryTenant, days: int = 7) -> List[dict]:
        """Return facts that were created or updated in the last *days* days.

        Args:
            tenant: The tenant whose memory to inspect.
            days: Number of days to look back.

        Returns:
            A list of dicts representing recently changed facts.
        """
        ...

    @abstractmethod
    async def fact_history(self, tenant: MemoryTenant, subject: str, predicate: Optional[str] = None) -> List[dict]:
        """Return the full history of facts for a (subject, predicate) pair.

        If *predicate* is None, returns all facts for the subject.

        Args:
            tenant: The tenant whose memory to inspect.
            subject: The subject name.
            predicate: Optional predicate to filter by.

        Returns:
            A list of dicts ordered by ``valid_from``, each representing a
            historical version of the fact.
        """
        ...
