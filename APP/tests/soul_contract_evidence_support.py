"""Inert autouse seam kept for public CI.

The original implementation hashed changed files against a hard-coded fork-point
commit with ``git diff``/``git rev-parse`` and asserted the source tree was
clean, so lane tooling could record source identity and reject mid-run edits.
That is historical/checkpoint evidence collection, not behaviour the public
regressions exercise, and public CI does not contain that commit or history (the
test standard forbids repository-history reads). The fixture below is therefore
intentionally synthetic: it preserves the autouse contract that the importing
regression modules relied on while reading no repository state. Lane tooling
may swap in a real implementation into this seam without editing the public
tests. The historical archived-base comparison itself moved out of the public
suite (see test_mgr_soul_contract_checks.py).
"""
import pytest


@pytest.fixture(scope='module', autouse=True)
def source_checkpoint():
    """Inert for public CI; reads no repository history."""
    yield
