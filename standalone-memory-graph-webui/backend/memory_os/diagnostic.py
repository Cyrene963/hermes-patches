"""
Diagnostic checks for a tenant's memory namespace.

MemoryDiagnostic inspects the memory graph for common quality issues such as
stale nodes, orphaned facts, duplicates, and missing evidence.  Concrete
implementations should inject a graph backend (e.g. FalkorDB, NetworkX) via
the constructor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from memory_os.tenant import MemoryTenant


class MemoryDiagnostic(ABC):
    """Runs diagnostic checks on a tenant's memory namespace.

    Subclass this and inject your graph backend to provide real diagnostics.

    Usage::

        class FalkorDiagnostic(MemoryDiagnostic):
            def __init__(self, graph_client):
                self._graph = graph_client

            async def run_diagnostic(self, tenant):
                # query the graph for quality issues
                ...

        diag = FalkorDiagnostic(client)
        report = await diag.run_diagnostic(tenant)
    """

    @abstractmethod
    async def run_diagnostic(self, tenant: MemoryTenant) -> Dict:
        """Run a full diagnostic sweep on *tenant*'s memory namespace.

        The returned dict should include at least the following keys (values
        are lists of affected node/fact IDs unless otherwise noted):

        - ``stale_nodes``: Facts whose ``valid_to`` is in the past.
        - ``crowded_nodes``: Subjects with an unusually high number of facts.
        - ``orphans``: Facts with no incoming/outgoing edges.
        - ``duplicate_current``: Multiple "current" facts for the same
          (subject, predicate) pair.
        - ``facts_without_evidence``: Current facts that have an empty
          ``evidence_ids`` list.
        - ``low_confidence``: Current facts with confidence < 0.4.
        - ``pending_reviews``: Facts in "pending" review state.

        Args:
            tenant: The tenant to diagnose.

        Returns:
            A dict of diagnostic categories to lists of affected items.
        """
        ...

    @abstractmethod
    async def known_gaps(self, tenant: MemoryTenant) -> List[dict]:
        """Identify knowledge gaps in *tenant*'s memory.

        A knowledge gap is something the system should know but doesn't —
        e.g. a person's age when their birthday is recorded, or a project's
        status when the last update was months ago.

        Args:
            tenant: The tenant to inspect.

        Returns:
            A list of dicts describing each gap, e.g.
            ``[{"subject": "alice", "predicate": "age", "reason": "no fact found"}]``.
        """
        ...
