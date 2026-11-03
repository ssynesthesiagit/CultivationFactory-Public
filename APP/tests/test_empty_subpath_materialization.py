from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from character_creation.response_materialization import CanonicalSelectionIntent
from character_creation.delegated_choice_authority import catalog_stage2_selections
from character_creation.service import CharacterCreationExecutionService


PATH_ID = "tianxia.path.qi_cultivation"
BACKGROUND_ID = "tianxia.background.test"
BACKGROUND_SPHERE_ID = "tianxia.background_sphere.test"
BACKGROUND_TALENT_ID = "tianxia.background_talent.test"
BACKGROUND_CANONICAL_SPHERE_ID = "tianxia.sphere.background.test"
BACKGROUND_CANONICAL_TALENT_ID = "tianxia.talent.background.test"
ORIGIN_ID = "tianxia.origin_insight.test"
SPHERE_ID = "tianxia.sphere.test"
FREE_TALENT_ID = "tianxia.talent.free.test"
SUBPATH_ID = "tianxia.subpath.test"


def _record(record_id: str, content_type: str, kinds: list[str], channels: list[str], **authority):
    return {
        "record_id": record_id,
        "content_type": content_type,
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "allowed_kinds": kinds,
                    "allowed_channels": channels,
                    **authority,
                }
            }
        },
    }


def _materializer(monkeypatch, *, target_cl: int, select_subpath: bool):
    feature_ids = [f"tianxia.path.qi_cultivation.feature.cl{cl}" for cl in range(1, target_cl + 1)]
    records = {
        PATH_ID: _record(
            PATH_ID,
            "path",
            ["path_acquisition"],
            ["path-selection"],
            progression_by_cl={
                str(cl): {"feature_record_ids": [feature_ids[cl - 1]]}
                for cl in range(1, target_cl + 1)
            },
        ),
        BACKGROUND_ID: _record(BACKGROUND_ID, "background", ["background_acquisition"], ["background-selection"]),
        BACKGROUND_SPHERE_ID: _record(
            BACKGROUND_SPHERE_ID, "background_sphere", ["background_sphere_acquisition"], ["background-grant"]
        ),
        BACKGROUND_TALENT_ID: _record(
            BACKGROUND_TALENT_ID, "background_talent", ["background_talent_acquisition"], ["background-grant"]
        ),
        BACKGROUND_CANONICAL_SPHERE_ID: _record(BACKGROUND_CANONICAL_SPHERE_ID, "sphere", ["background_sphere_acquisition"], ["background-grant"]),
        BACKGROUND_CANONICAL_TALENT_ID: _record(BACKGROUND_CANONICAL_TALENT_ID, "talent", ["background_talent_acquisition"], ["background-grant"], owning_canonical_sphere_id=BACKGROUND_CANONICAL_SPHERE_ID),
        ORIGIN_ID: _record(ORIGIN_ID, "cultivation_insight", ["origin_insight_acquisition"], ["origin-selection"]),
        SPHERE_ID: _record(SPHERE_ID, "sphere", ["ai_bootstrap_sphere_acquisition"], ["ai-bootstrap-cl1-sphere"]),
        FREE_TALENT_ID: _record(
            FREE_TALENT_ID,
            "talent",
            ["ai_bootstrap_talent_acquisition"],
            ["ai-bootstrap-free-cl1-talent"],
            owning_canonical_sphere_id=SPHERE_ID,
        ),
    }
    for cl, feature_id in enumerate(feature_ids, 1):
        records[feature_id] = _record(
            feature_id,
            "path_feature",
            ["level_advance"],
            ["level-advance"],
            feature_kind="subpath_selection" if cl == 3 else "path_feature",
        )
    ordinary_ids = [f"tianxia.talent.ordinary.cl{cl}" for cl in range(1, target_cl + 1)]
    for ordinary_id in ordinary_ids:
        records[ordinary_id] = _record(
            ordinary_id,
            "talent",
            ["level_talent_acquisition"],
            ["ai-bootstrap-free-cl1-talent", "level-choice"],
            minimum_cl=1,
        )
    for target in ("method", "foundation", "manuals", "equipment", "forged_techniques"):
        record_id = f"tianxia.c1a.none.{target}"
        records[record_id] = _record(record_id, "typed_none", ["typed_none"], ["typed-none"])
    if select_subpath:
        records[SUBPATH_ID] = {
            **_record(SUBPATH_ID, "subpath", ["subpath_acquisition"], ["subpath-selection"]),
            "owning_path_id": PATH_ID,
            "parent_path_id": PATH_ID,
            "legality": {"minimum_cl": 3},
        }

    class _Projects:
        def project_lock_proof(self, _conn, _project_id):
            return None

        def _resolve_locked_record_after_proof(self, _conn, _project_id, record_id, **_kwargs):
            return records.get(record_id)

    class _Database:
        settings = SimpleNamespace(
            root_dir=Path("."),
            vendor_dir=Path(__file__).resolve().parent / "fixtures" / "absent-vendor",
        )

        def connection(self):
            return nullcontext(object())

    class _Authority:
        path_profiles = {PATH_ID: {"features": []}}

        def __init__(self, _db):
            pass

    class _Catalog:
        def __init__(self, _root):
            pass

        def resolve_sphere_id(self, _display_name):
            return None

    monkeypatch.setattr("character_creation.service.NonSphereAuthorityService", _Authority)
    monkeypatch.setattr("character_creation.service.CanonicalCatalogAuthorityService", _Catalog)
    service = object.__new__(CharacterCreationExecutionService)
    service.db = _Database()
    service.projects = _Projects()
    service._locked_records_for_project = lambda _project_id: dict(records)
    project = {
        "project_id": "project-empty-subpath",
        "user_locks": [
            {"field": "target_cl", "value": target_cl},
            {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
        ],
    }
    envelope = {
        "allowed_choice_ids_by_slot": {
            "path_choice": [PATH_ID],
            "advancement_skeleton": ordinary_ids,
        },
        "choices_by_slot": {"path_choice": {PATH_ID: {"choice_id": PATH_ID}}},
        "owner_locks": {"by_slot": {}},
        "background_package_linkage": {
            BACKGROUND_ID: [{
                "background_sphere_choice_id": BACKGROUND_SPHERE_ID,
                "background_talent_choice_id": BACKGROUND_TALENT_ID,
                "canonical_sphere_id": BACKGROUND_CANONICAL_SPHERE_ID,
                "canonical_talent_id": BACKGROUND_CANONICAL_TALENT_ID,
            }],
        },
        "ordinary_talent_count": target_cl,
        "advancement_choice_milestones": [],
    }
    selected = {
        "path_choice": [PATH_ID],
        "background_choice": [BACKGROUND_ID],
        "background_sphere_choice": [BACKGROUND_SPHERE_ID],
        "background_talent_choice": [BACKGROUND_TALENT_ID],
        "origin_insight_choice": [ORIGIN_ID],
    }
    if select_subpath:
        selected["subpath_choice"] = [SUBPATH_ID]
    # These are exact fixture selections, not legacy aliases. Mirror the
    # production frozen envelope's allowed IDs and corresponding source rows
    # so unrelated ASI/Subpath tests reach their intended boundary.
    for slot, identities in selected.items():
        envelope["allowed_choice_ids_by_slot"][slot] = list(identities)
        envelope["choices_by_slot"][slot] = {identity: {"choice_id": identity} for identity in identities}
    envelope["typed_choice_authority_by_slot"] = {"background_choice": {"background_package_linkage": envelope["background_package_linkage"]}}
    envelope["choices_by_slot"]["background_sphere_choice"][BACKGROUND_SPHERE_ID]["canonical_sphere_id"] = BACKGROUND_CANONICAL_SPHERE_ID
    envelope["choices_by_slot"]["background_talent_choice"][BACKGROUND_TALENT_ID]["canonical_talent_id"] = BACKGROUND_CANONICAL_TALENT_ID
    envelope["choices_by_slot"]["sphere_priorities"] = {
        identity: {"choice_id": identity, "canonical_sphere_id": identity}
        for identity in (SPHERE_ID, BACKGROUND_CANONICAL_SPHERE_ID)
    }
    intent = CanonicalSelectionIntent.from_document(
        {
            "selected_by_slot": selected,
            "bounded_choices": {
                "ability_scores": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "path_progression_by_cl": {str(cl): PATH_ID for cl in range(1, target_cl + 1)},
            },
            "acquisition_intent": {
                "sphere_free_talent_pairs": [{"sphere_id": SPHERE_ID, "talent_id": FREE_TALENT_ID}],
                "ordinary_talent_ids": ordinary_ids,
                "insight_occurrences": [],
            },
        }
    )
    run = {
        "project_id": project["project_id"],
        "request": {"delegated_choice_envelope": envelope},
    }
    return service, run, project, intent


def test_cl1_empty_subpath_does_not_emit_typed_none_sentinel(monkeypatch):
    service, run, project, intent = _materializer(monkeypatch, target_cl=1, select_subpath=False)

    rows = service._derive_stage2_rows_from_frozen_authority(run, project, intent)

    typed_none_ids = {row["record_id"] for row in rows if row["kind"] == "typed_none"}
    assert typed_none_ids == {
        "tianxia.c1a.none.method",
        "tianxia.c1a.none.foundation",
        "tianxia.c1a.none.manuals",
        "tianxia.c1a.none.equipment",
        "tianxia.c1a.none.forged_techniques",
    }
    assert "tianxia.c1a.none.subpaths" not in typed_none_ids
    assert not any(row["kind"] == "subpath_acquisition" for row in rows)


def test_semantic_pair_uses_frozen_route_kinds_and_is_counted_as_catalog_grant(monkeypatch):
    service, run, project, intent = _materializer(monkeypatch, target_cl=1, select_subpath=False)

    rows = service._derive_stage2_rows_from_frozen_authority(run, project, intent)

    pair_rows = {
        row["record_id"]: row
        for row in rows
        if row["record_id"] in {SPHERE_ID, FREE_TALENT_ID}
    }
    assert pair_rows[SPHERE_ID]["kind"] == "ai_bootstrap_sphere_acquisition"
    assert pair_rows[SPHERE_ID]["acquisition_channel"] == "ai-bootstrap-cl1-sphere"
    assert pair_rows[FREE_TALENT_ID]["kind"] == "ai_bootstrap_talent_acquisition"
    assert pair_rows[FREE_TALENT_ID]["acquisition_channel"] == "ai-bootstrap-free-cl1-talent"

    plan = {
        "stage2_proposal": {"choices": rows},
        "canonical_selection_intent": intent.as_dict(),
    }
    selections = catalog_stage2_selections(plan)
    assert selections["sphere_ids"] == [SPHERE_ID]
    assert selections["free_sphere_talent_ids"] == [FREE_TALENT_ID]


def test_cl3_selected_subpath_still_materializes_at_path_milestone(monkeypatch):
    service, run, project, intent = _materializer(monkeypatch, target_cl=3, select_subpath=True)

    rows = service._derive_stage2_rows_from_frozen_authority(run, project, intent)

    assert [row["record_id"] for row in rows if row["kind"] == "subpath_acquisition"] == [SUBPATH_ID]
    assert [row["effective_cl"] for row in rows if row["kind"] == "subpath_acquisition"] == [3]
