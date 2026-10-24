"""Content hash record for catalog supplement packs (CAICLANLOCK1).

Each supplement pack (background/origin and every owner-authored Subpath pack) has a
content hash computed from its projected records and its declared sources. The
checked-in record `supplement_pack_hashes.json` maps pack_id -> pack_version -> hash.
A content change without a pack_version bump fails the CI guard, which tells the
author to bump the pack_version and regenerate the record with this module:

    python -m catalog.supplement_hashes --factory-root <Factory> --owner-root <APP> --write

The core pack is covered by its pinned pack hashes (CORE_PACK_VERSION_HASH_CONFLICT).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from catalog.service import BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION, CoreCatalogImporter, supplement_content_hash

RECORD_PATH = Path(__file__).with_name("supplement_pack_hashes.json")


def current_supplement_hashes(factory_root: Path, owner_root: Path) -> dict[str, dict[str, str]]:
    """pack_id -> {pack_version: content_hash} computed from the sources as they are now."""
    importer = CoreCatalogImporter(factory_root, owner_root=owner_root)
    packs: dict[str, dict[str, str]] = {}
    background = list(importer.iter_background_records())
    packs.setdefault(BACKGROUND_PACK_ID, {})[BACKGROUND_PACK_VERSION] = supplement_content_hash(
        importer.background_source_inventory_hash(), background)
    for item in importer.owner_subpath_supplements():
        packs.setdefault(item["pack_id"], {})[item["pack_version"]] = supplement_content_hash(
            item["source_hash"], item["projections"])
    return packs


def load_record(path: Path = RECORD_PATH) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))["packs"]


def version_problems(current: dict[str, dict[str, str]], recorded: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Every pack whose content differs from its recorded hash for the same pack_version."""
    problems: list[dict[str, Any]] = []
    for pack_id, versions in sorted(current.items()):
        for version, digest in sorted(versions.items()):
            known = recorded.get(pack_id, {})
            if version not in known:
                problems.append({"pack_id": pack_id, "pack_version": version, "current": digest,
                                 "recorded": None,
                                 "message": f"{pack_id} {version} has no checked-in content hash: bump the pack_version and regenerate catalog/supplement_pack_hashes.json."})
            elif known[version] != digest:
                problems.append({"pack_id": pack_id, "pack_version": version, "current": digest,
                                 "recorded": known[version],
                                 "message": f"{pack_id} {version} content changed without a version bump: bump the pack_version and regenerate catalog/supplement_pack_hashes.json."})
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--factory-root", type=Path, required=True)
    parser.add_argument("--owner-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="write the checked-in record")
    args = parser.parse_args()
    packs = current_supplement_hashes(args.factory_root, args.owner_root)
    if args.write:
        RECORD_PATH.write_text(json.dumps({"packs": packs}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"packs": packs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
