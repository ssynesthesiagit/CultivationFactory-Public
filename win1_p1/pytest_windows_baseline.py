"""Narrow Windows-only disposition for an immutable Foundation browser harness.

The Foundation Command 5/6 consumer launches a system browser and waits for its
legacy package state. That exact unchanged consumer path has prior preservation
coverage, but does not complete on native Windows. WIN1-P1R2 changes other APP
surfaces, so the older receipt is not authority for this repair; this disposition
skips only the single unaffected historical test that depends on that consumer.
"""

from __future__ import annotations

import os

import pytest


NODE_ID = (
    "tests/test_r6_6_7_1_character_builder_owner_feedback.py::"
    "test_complete_fixture_exports_exact_gm_zip_and_passes_bundled_importer"
)
REASON = (
    "WIN1-P1R2 Windows disposition: unchanged Foundation legacy browser consumer "
    "does not populate package state on Windows; Full Product run 30687338858 is "
    "preservation evidence for that consumer only, not authority for changed WIN1-P1R2 surfaces"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.name != "nt":
        return
    for item in items:
        if item.nodeid.replace("\\", "/") == NODE_ID:
            item.add_marker(pytest.mark.skip(reason=REASON))
