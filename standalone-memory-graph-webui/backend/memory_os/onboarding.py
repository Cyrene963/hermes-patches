"""
Tenant onboarding — bootstrap a new tenant's memory system.

TenantOnboarding handles the initial setup required when a new user or
organisation is added to the memory system: creating the namespace,
directory tree, initial memory map, evidence store bank, and policy file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

from memory_os.tenant import MemoryTenant


class TenantOnboarding(ABC):
    """Bootstrap a new tenant's memory system.

    Subclass this and inject whatever services are needed to create the
    actual resources (database entries, filesystem directories, store
    initialisation, etc.).

    Usage::

        onboarding = MyTenantOnboarding(graph, evidence, rules)
        result = await onboarding.onboard(tenant)
        print(result["status"])  # "ok"
    """

    @abstractmethod
    async def onboard(self, tenant: MemoryTenant) -> Dict:
        """Perform full onboarding for *tenant*.

        The onboarding process should create:

        - A namespace entry in the graph / registry.
        - Any required directory trees or storage buckets.
        - An initial Memory Map (see :meth:`generate_boot_profile`).
        - An evidence store bank for the tenant.
        - A per-user MEMORY.md (or equivalent) with starter content.
        - A policy file with default permissions and rules.

        Args:
            tenant: The tenant to onboard.

        Returns:
            A dict describing the outcome, e.g.
            ``{"status": "ok", "namespace": "user:alice", "resources_created": [...]}``.
        """
        ...

    @abstractmethod
    async def generate_boot_profile(self, tenant: MemoryTenant) -> str:
        """Generate the initial Memory Map content for *tenant*.

        The boot profile is a human-readable (typically Markdown) document
        that describes the tenant's memory schema, default categories, and
        any seed data.

        Args:
            tenant: The tenant to generate the profile for.

        Returns:
            The Memory Map content as a string.
        """
        ...
