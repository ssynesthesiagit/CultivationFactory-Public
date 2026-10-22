"""Skip tests that need the original printed rules text on the public tree.

``tools/public_test_export.py`` replaces printed rules prose with pseudowords in
the published snapshot and leaves ``PUBLIC_TEST_FILES.json`` at the checkout
root. ``combat/factory_compiler.py`` compiles a typed reaction only while its
printed trigger still classifies, so reactions such as Marrow Pack Guard and
Golden Sea Guard are absent there. Tests that read those compiled reactions use
``requires_private_prose``; the same tests run in the full checkout.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IN_PUBLIC_SNAPSHOT = (ROOT / "PUBLIC_TEST_FILES.json").is_file()

requires_private_prose = pytest.mark.skipif(
    IN_PUBLIC_SNAPSHOT,
    reason="the published snapshot replaces printed rules text with pseudowords, "
           "so the reaction does not compile there (combat/factory_compiler.py:2017)",
)
