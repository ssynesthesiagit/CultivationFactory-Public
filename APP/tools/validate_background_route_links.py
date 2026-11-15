"""Catalog release check for the reviewed Background -> CAT2 route foreign keys.

Run from APP: python -m tools.validate_background_route_links
The source files are evidence, not an alternative name/prose-based route resolver.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from non_sphere_authority.background_route_links import (
    BACKGROUND_ROUTE_IDS, ROUTE_TARGETS, SOURCE_SHA256, validated_route_records,
)


def validate_source_evidence(root: Path) -> dict[str, int]:
    """Check the reviewed source release before accepting its authored links."""
    for name, expected in SOURCE_SHA256.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Background route source changed; review its ID links: {name}")
    backgrounds = {
        row["background_id"]: row
        for row in json.loads((root / "non_sphere_authority/authority/Background_Core_Authority_v1.json").read_text())["backgrounds"]
    }
    routes = json.loads((root / "catalog_authority/cat1/data/background_origin_talent_routes.v1.json").read_text())["records"]
    validated_route_records(backgrounds, routes)
    spheres = {
        row["canonical_sphere_id"]
        for row in json.loads((root / "catalog_authority/cat1/data/canonical_spheres.v1.json").read_text())["records"]
    }
    if any(sphere_id not in spheres for sphere_id, _ in ROUTE_TARGETS.values()):
        raise ValueError("A Background route target is not a canonical Sphere ID.")
    for background_id, route_ids in BACKGROUND_ROUTE_IDS.items():
        if len(route_ids) != len(backgrounds[background_id]["background_sphere_talent_routes"]["route_bullets"]):
            raise ValueError(f"Background route evidence is incomplete: {background_id}")
    return {"backgrounds": len(backgrounds), "routes": len(routes),
            "choices": sum(map(len, BACKGROUND_ROUTE_IDS.values())),
            "explicit_missing_sphere_targets": sum(row.get("canonical_sphere_id") is None for row in routes)}


if __name__ == "__main__":
    print(json.dumps({"result": "PASS", **validate_source_evidence(Path(__file__).resolve().parents[1])}, sort_keys=True))
