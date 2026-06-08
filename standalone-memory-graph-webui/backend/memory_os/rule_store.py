"""
Abstract adapter for per-user rule storage.

Rules govern how the memory system behaves for a given tenant — what it
remembers, how it prioritises facts, what it suppresses, etc.  This module
defines the interface that any concrete rule backend must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class RuleStoreAdapter(ABC):
    """Abstract interface for per-user rule storage.

    Rules are stored as opaque strings (typically Markdown or YAML).  The
    adapter is responsible for persistence; the caller is responsible for
    parsing.

    Usage::

        class MyRuleStore(RuleStoreAdapter):
            def load_rules(self, store_id):
                ...

        store = MyRuleStore(config)
        rules_text = store.load_rules("user_alice_rules")
    """

    @abstractmethod
    def load_rules(self, store_id: str) -> str:
        """Load the rules for the given *store_id*.

        Args:
            store_id: Identifier for the tenant's rule store.

        Returns:
            The rules as a string.  Returns an empty string if no rules
            have been saved yet.
        """
        ...

    @abstractmethod
    def save_rules(self, store_id: str, rules: str) -> bool:
        """Persist the given *rules* string for *store_id*.

        Args:
            store_id: Identifier for the tenant's rule store.
            rules: The rules content to save.

        Returns:
            True if the rules were saved successfully, False otherwise.
        """
        ...
