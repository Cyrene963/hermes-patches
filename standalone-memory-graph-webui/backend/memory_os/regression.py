"""
Regression test runner for memory systems.

RegressionTestRunner executes a suite of tests against a tenant's memory
namespace to verify that the graph, evidence store, and rule store are
all functioning correctly together.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

from memory_os.tenant import MemoryTenant


class RegressionTestRunner(ABC):
    """Runs memory system regression tests.

    Subclass this and inject your graph backend, evidence adapter, and rule
    store to provide real regression tests.

    The returned dict should include at minimum:

    - ``pass_rate``: float (0.0–1.0) — fraction of tests that passed.
    - ``graph_hit_rate``: float — how often the graph answered without
      falling back to the evidence store.
    - ``hindsight_fallback_rate``: float — how often the system fell back
      to the evidence store.
    - ``unknown_correct_rate``: float — how often the system correctly
      said "I don't know" instead of hallucinating.
    - ``write_success_rate``: float — fraction of writes that succeeded.
    - ``total_tests``: int
    - ``passed``: int
    - ``failed``: int
    - ``details``: list of per-test result dicts.

    Usage::

        runner = MyRegressionRunner(graph, evidence, rules)
        report = await runner.run_tests(tenant)
        print(f"Pass rate: {report['pass_rate']:.0%}")
    """

    @abstractmethod
    async def run_tests(self, tenant: MemoryTenant) -> Dict:
        """Execute the full regression suite for *tenant*.

        Args:
            tenant: The tenant to test against.

        Returns:
            A dict of test metrics (see class docstring for expected keys).
        """
        ...
