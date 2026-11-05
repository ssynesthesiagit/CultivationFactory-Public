"""Public synthetic regressions for Background route identity, not book fidelity."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from canonical_catalog import service as canonical_catalog
from non_sphere_authority.background_route_links import BACKGROUND_ROUTE_IDS, ROUTE_TARGETS, SOURCE_SHA256
from non_sphere_authority.service import NonSphereAuthorityService
from tools.validate_background_route_links import validate_source_evidence


@pytest.fixture
def route_context(tmp_path, monkeypatch):
    # Build all inputs here; never load the private catalog, book or a database.
    context = object.__new__(NonSphereAuthorityService)
    context.root = tmp_path
    context.backgrounds = {
        background_id: {
            "background_sphere_talent_routes": {"route_bullets": ["Duplicate — presentation!"] * len(route_ids)},
            "origin_insight": {"suggested_options": ["Synthetic Insight"]},
            "ability_score_grants": {"modes": [{"increases": [2]}]},
            "blockers": [],
        }
        for background_id, route_ids in BACKGROUND_ROUTE_IDS.items()
    }
    context.cat2_background_routes = [
        {
            "background_route_record_id": route_id,
            "canonical_sphere_id": None,
            "canonical_sphere_name": "Identical display name",
            "display_name": "Identical talent (Identical display name)",
            "source_text": "Duplicate — presentation!",
            "record_commitment_sha256": hashlib.sha256(route_id.encode()).hexdigest(),
        }
        for route_id in ROUTE_TARGETS
    ]

    class SyntheticCatalog:
        def __init__(self, root):
            assert root == tmp_path

        def resolve_sphere_id(self, value):
            # No name/alias repair may enter this boundary.
            assert value in {target[0] for target in ROUTE_TARGETS.values()}
            return value

    monkeypatch.setattr(canonical_catalog, "CanonicalCatalogAuthorityService", SyntheticCatalog)
    return context


def test_all_ordered_routes_use_ids_despite_duplicate_names_and_rewritten_bullets(route_context):
    context = route_context
    before = deepcopy((context.backgrounds, context.cat2_background_routes))
    authority = context._build_background_route_authority()
    relationships = [
        [background_id, option["background_route_record_id"], option["canonical_sphere_id"],
         option["background_sphere_choice_id"], option["background_talent_choice_id"]]
        for background_id, row in authority.items()
        for option in row["route_options"]
    ]
    # Captured from the original 112 ordered choices / 77 distinct routes,
    # independently of these authored ID maps. No protected source text.
    assert len(relationships) == 112
    assert len({row[1] for row in relationships}) == 77
    encoded = json.dumps(relationships, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == "422a3915cf169c6f4cfc97c54ad1b87d75c6c52bc67f85cf158aa8902ebb4743"
    assert (context.backgrounds, context.cat2_background_routes) == before

    for background in context.backgrounds.values():
        background["background_sphere_talent_routes"]["route_bullets"] = ["Rewritten punctuation: '…'?!"]
    for route in context.cat2_background_routes:
        route.update(display_name="Another duplicate name", canonical_sphere_name="Renamed Sphere",
                     source_text="Rewritten evidence")
    rewritten = context._build_background_route_authority()
    assert [
        [background_id, option["background_route_record_id"], option["canonical_sphere_id"],
         option["background_sphere_choice_id"], option["background_talent_choice_id"]]
        for background_id, row in rewritten.items()
        for option in row["route_options"]
    ] == relationships


@pytest.mark.parametrize("corruption", ["missing_route", "missing_id", "duplicate_route", "unknown_background", "wrong_sphere"])
def test_invalid_route_identity_is_rejected_before_projection(route_context, corruption):
    context = route_context
    if corruption == "missing_route":
        context.cat2_background_routes.pop()
    elif corruption == "missing_id":
        context.cat2_background_routes[0].pop("background_route_record_id")
    elif corruption == "duplicate_route":
        context.cat2_background_routes.append(deepcopy(context.cat2_background_routes[0]))
    elif corruption == "unknown_background":
        context.backgrounds["untrusted.background"] = context.backgrounds.pop(next(iter(context.backgrounds)))
    else:
        context.cat2_background_routes[0]["canonical_sphere_id"] = "tianxia.sphere.not_the_reviewed_target"
    with pytest.raises(FoundryError) as error:
        context._build_background_route_authority()
    assert error.value.code == (
        "NS1R_BACKGROUND_ROUTE_CANONICAL_SPHERE_INVALID" if corruption == "wrong_sphere"
        else "NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS"
    )


def test_release_check_rejects_unreviewed_source_bytes(tmp_path: Path):
    name = next(iter(SOURCE_SHA256))
    source = tmp_path / name
    source.parent.mkdir(parents=True)
    source.write_text('{"untrusted": "self-consistent replacement"}')
    with pytest.raises(ValueError, match="source changed; review its ID links"):
        validate_source_evidence(tmp_path)
