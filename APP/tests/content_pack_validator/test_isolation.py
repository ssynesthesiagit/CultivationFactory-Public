from __future__ import annotations

import json
from pathlib import Path


ALLOWED_PREFIXES = (
    "tools/content_pack_validator/",
    "schemas/content_pack_candidate/",
    "tests/content_pack_validator/",
    "docs/content_pack_validator/",
    "fixtures/content_pack_validator/",
)
ALLOWED_EXACT = {"tools/__init__.py"}
INVENTORY_PATH = "docs/content_pack_validator/CPK1_EXACT_CHANGED_FILE_INVENTORY.json"


def test_all_overlay_source_files_stay_in_isolated_paths(overlay_root: Path) -> None:
    """Audit the declared CPK-1 payload, not unrelated files in the merged Factory tree."""

    inventory = json.loads((overlay_root / INVENTORY_PATH).read_text(encoding="utf-8"))
    declared = sorted(inventory["paths"])
    assert len(declared) == inventory["file_count"] == 258
    assert len(declared) == len(set(declared))
    assert all(path in ALLOWED_EXACT or path.startswith(ALLOWED_PREFIXES) for path in declared)
    assert all((overlay_root / path).is_file() for path in declared)

    actual = sorted(
        path.relative_to(overlay_root).as_posix()
        for prefix in ALLOWED_PREFIXES
        for path in (overlay_root / prefix).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts
    )
    actual.extend(path for path in sorted(ALLOWED_EXACT) if (overlay_root / path).is_file())
    assert sorted(actual) == declared
