"""Versioned source and causal calculator checks, not complete/model acceptance."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.core import FoundryError, canonical_json
from contracts.canonical import canonical_record_hash
from character_creation.path_attainment import native_path_progressions
from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
from character_creation.creative_controller.linear_walk import commit_option
from non_sphere_authority.foundation_mechanics import (
    INITIAL_FOUNDATION_MECHANICS_POLICY, FOUNDATION_MECHANICS_PACK_VERSION,
    foundation_initial_stage_contract, initial_foundation_record_version,
    installed_foundation_state, resolve_initial_foundation_mechanics,
    validate_foundation_initial_stage,
    verified_foundation_records,
)
from non_sphere_authority.service import NonSphereAuthorityService
from projector.foundation_mechanics import (
    project_initial_foundation_mechanics,
    validate_initial_foundation_mechanics,
)
from projector.service import _stage_aware_diagnostics
from projector.v3_bridge import _validate_binding
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_initial_method_versions import _initial_method_events
from tests.test_rec1_p1cr5_owner_authority import _private_scope
from tests.test_dcc_linear_walk import _fixture


def test_stage_choice_is_frozen_and_never_defaults_to_the_highest_alternative():
    request, envelope = _fixture()
    request["server_owned_authority"] = {"initial_foundation_mechanics_policy": deepcopy(INITIAL_FOUNDATION_MECHANICS_POLICY)}
    request["bounded_choice_contract"]["fields"]["foundation_initial_stage"] = foundation_initial_stage_contract()
    identity = "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
    state = CommittedState().with_slot("foundation_choice", [identity])
    menu = build_step_menu(request, envelope, state, step_id="foundation_initial_stage")
    assert {option.choice_ids for option in menu.options} == {("Awakened",), ("Unstable",)}
    with pytest.raises(FoundryError) as caught:
        validate_foundation_initial_stage(request, {"foundation_choice": [identity]}, {})
    assert caught.value.code == "CG1_FOUNDATION_INITIAL_STAGE_REQUIRED"
    option = next(option for option in menu.options if option.choice_ids == ("Unstable",))
    committed = commit_option(menu, option.option_id, state)
    assert committed.bounded["foundation_initial_stage"] == "Unstable"
    validate_foundation_initial_stage(request, {"foundation_choice": [identity]}, dict(committed.bounded))
    assert build_step_menu(request, envelope, committed, step_id="foundation_initial_stage") is None
    with pytest.raises(FoundryError):
        validate_foundation_initial_stage(request, {"foundation_choice": [identity]}, {"foundation_initial_stage": "Perfected"})
    historical = deepcopy(request)
    historical["server_owned_authority"].pop("initial_foundation_mechanics_policy")
    assert initial_foundation_record_version(historical) is None
    request["server_owned_authority"]["initial_foundation_mechanics_policy"]["refill_current"] = True
    with pytest.raises(FoundryError):
        initial_foundation_record_version(request)


def test_old_requests_do_not_gain_a_skipped_stage_descriptor_or_changed_event_details():
    from character_creation.creative_controller.linear_walk import _step_descriptors
    from stage2.service import _canonical_event_details
    request, envelope = _fixture()
    state = CommittedState().with_slot("foundation_choice", ["foundation.quiet"])
    assert all(row[0] != "foundation_initial_stage" for row in _step_descriptors(request, envelope, state))
    assert _canonical_event_details("foundation_acquisition", {}) == {}
    assert _canonical_event_details("foundation_acquisition", {"stage": "Unstable"}) == {"stage": "Unstable"}


def test_installed_foundation_state_is_stable_across_rule_order_and_json_round_trip():
    source = verified_foundation_records()["heaven_devouring_shedding_womb_v0_2B"]
    mechanics = resolve_initial_foundation_mechanics(
        source,
        ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"],
        stage="Awakened",
    )
    assert list(mechanics["initial_state"]["resource"]["rules"]) == [
        "Maximum", "Starting Amount", "How You Gain It", "Generation Timing",
        "Generation Limit", "Expiration", "Same-Event Rule",
        "Anti-Farming and Counterplay", "Features That Spend It",
    ]
    source_ordered = installed_foundation_state(mechanics, source["foundation_id"], "captured-foundation-event")
    assert [row["name"] for row in source_ordered["resource"]["rule_descriptions"]] == sorted(mechanics["initial_state"]["resource"]["rules"])

    reordered = deepcopy(mechanics)
    rules = reordered["initial_state"]["resource"]["rules"]
    reordered["initial_state"]["resource"]["rules"] = dict(reversed(list(rules.items())))
    canonicalized = json.loads(canonical_json(reordered))

    assert installed_foundation_state(reordered, source["foundation_id"], "captured-foundation-event") == source_ordered
    assert installed_foundation_state(canonicalized, source["foundation_id"], "captured-foundation-event") == source_ordered


@pytest.fixture
def foundation_project(catalog_environment):
    return _real_creation_intent(catalog_environment)


def _diagnostic_reduced(*required_nodes):
    return SimpleNamespace(
        typed_choice_snapshot={},
        validation_profile={"required_semantic_nodes": list(required_nodes)},
        event_ids=[],
        provenance={},
        capability_coverage=[],
    )


def _foundation_diagnostic_ledger(foundation):
    return {
        "readiness": {
            "active_profile": "ADVANCEMENT_READY",
            "advancement": "ADVANCEMENT_READY",
        },
        "typed_none": {
            "equipment": {"state": "none"},
            "forged_techniques": {"state": "none"},
        },
        "method": {"state": "acquired", "record_id": "METHOD-083"},
        "foundation": foundation,
        "training_sources": ["sealed-training-source"],
        "character": {"title": None, "title_status": "OPTIONAL_OMITTED_BY_OWNER"},
        "later_stage_readiness": {
            stage: {"status": "NOT_ATTEMPTED"}
            for stage in ("character_sheet", "gm_screen", "combat")
        },
    }


def test_stage_aware_diagnostics_accepts_authenticated_active_foundation(foundation_project):
    creator, project, run, intent, _ = foundation_project
    paths = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
    stage2, events, state = _initial_method_events(
        creator, project, run, intent, "METHOD-083", paths,
    )
    proposal = {
        "project_id": project["project_id"],
        "proposal_id": "foundation-diagnostics.active",
        "expected_project_revision": project["revision"],
        "idempotency_key": "foundation-diagnostics-active",
        "created_at": "2026-09-07T00:00:00+00:00",
    }
    record_cache = {}
    with _private_scope(stage2, run["request"], run["run_id"], set(paths)), creator.db.connection() as conn:
        record = stage2._resolve_record_after_proof(conn, project["project_id"], "heaven_devouring_shedding_womb_v0_2B")
        stage2._assert_record_after_proof(conn, project["project_id"], record)
        path_records = [stage2._resolve_record_after_proof(conn, project["project_id"], path) for path in paths]
        for cl in range(2, 6):
            entries = native_path_progressions(path_records, cl)
            feature = path_records[0]["compatibility"]["factory"]["stage2_authority"]["progression_by_cl"][str(cl)]["feature_record_ids"][0]
            channel = events[-1]["legal_channel"] if cl == 2 else level_channel
            choices = [{
                "kind": "level_advance",
                "record_id": feature,
                "effective_cl": cl,
                "acquisition_channel": channel,
                "parameters": {"native_path_progressions": entries},
            }]
            level_channel = channel
            if cl == 5:
                choices.append({
                    "kind": "foundation_acquisition",
                    "record_id": "heaven_devouring_shedding_womb_v0_2B",
                    "effective_cl": 5,
                    "acquisition_channel": "foundation-selection",
                    "parameters": {"stage": "Awakened"},
                })
            for choice in choices:
                event, state, blockers = stage2._choice_event(
                    conn=conn,
                    row=proposal,
                    project=project,
                    state=state,
                    choice=choice,
                    index=len(events),
                    sequence=len(events) + 1,
                    previous_hash=events[-1]["event_hash"],
                    generic_prefix=events,
                    record_cache=record_cache,
                )
                assert not blockers, canonical_json({"choice": choice, "blockers": blockers})
                assert event is not None
                events.append(event)
    packet_by_event = {
        event["event_id"]: f"sealed-packet-{index}"
        for index, event in enumerate(events)
    }
    foundation = project_initial_foundation_mechanics(record, events, packet_by_event)
    assert foundation["state"] == "active"
    assert _stage_aware_diagnostics(
        _foundation_diagnostic_ledger(foundation),
        {"schema_version": "TianxiaFoundry.RulesSelectionPackets.v2", "packets": [], "owner_selections": {}},
        _diagnostic_reduced("typed_none"),
    ) == []


def _modern_foundation_projection_fixture():
    source_hash = "a" * 64
    mechanics = {
        "schema": "TianxiaFoundry.InitialFoundationMechanics.v1",
        "foundation_id": "foundation.fixture",
        "source_record_sha256": source_hash,
    }
    return {
        "state": "active",
        "status": "unstable",
        "record_id": "foundation.fixture",
        "event_id": "event.foundation.fixture",
        "acquisition_event_id": "event.foundation.fixture",
        "source_packet_ids": ["packet.foundation.fixture"],
        "mechanical_projection": True,
        "mechanics_schema": "TianxiaFoundry.InitialFoundationMechanics.v1",
        "source_record_sha256": source_hash,
        "mechanics": mechanics,
        "resource": {"initial_current": 0, "current": 0, "maximum": 1},
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda projection: {"state": "active", "record_id": projection["record_id"]},
        lambda projection: {**projection, "mechanics_schema": "forged.v1"},
        lambda projection: {**projection, "source_packet_ids": []},
        lambda projection: {**projection, "source_record_sha256": "b" * 64},
    ],
    ids=["bare-active", "tampered-version", "missing-packet", "tampered-source"],
)
def test_stage_aware_diagnostics_rejects_unauthenticated_active_foundation(mutation):
    projection = mutation(_modern_foundation_projection_fixture())
    diagnostics = _stage_aware_diagnostics(
        _foundation_diagnostic_ledger(projection),
        {"schema_version": "TianxiaFoundry.RulesSelectionPackets.v2", "packets": [], "owner_selections": {}},
        _diagnostic_reduced("typed_none"),
    )
    assert [finding["pointer"] for finding in diagnostics] == ["/semantic/typed_none"]


def test_stage_aware_diagnostics_preserves_legacy_foundation_and_spent_modern_state():
    legacy = {"state": "acquired", "record_id": "foundation.legacy"}
    packets = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "packets": [],
        "owner_selections": {},
    }
    assert _stage_aware_diagnostics(
        _foundation_diagnostic_ledger(legacy), packets, _diagnostic_reduced("typed_none"),
    ) == []

    modern = _modern_foundation_projection_fixture()
    before = deepcopy(modern)
    assert _stage_aware_diagnostics(
        _foundation_diagnostic_ledger(modern), packets, _diagnostic_reduced("typed_none"),
    ) == []
    assert modern == before


def _character_sheet_readiness_snapshot(foundation):
    explicit_none = {
        name: {"state": "none", "source_backed": True}
        for name in ("manuals", "equipment", "forged_techniques")
    }
    if foundation.get("state") == "none":
        explicit_none["foundation"] = {"state": "none", "source_backed": True}
    return {
        "selected_record_sections": {},
        "method": {"state": "acquired", "record_id": "METHOD-083"},
        "foundation": foundation,
        "identity": {"cultivation_level": 5},
        "explicit_none_systems": explicit_none,
        "later_stage_status": {
            stage: {"status": "NOT_ATTEMPTED"}
            for stage in ("gm_screen", "combat")
        },
    }


def test_character_sheet_readiness_accepts_active_foundation_without_refilling_current():
    from character_sheet.service import CharacterSheetService

    modern = _modern_foundation_projection_fixture()
    modern["resource"]["current"] = 0
    before = deepcopy(modern)
    CharacterSheetService._validate_snapshot(_character_sheet_readiness_snapshot(modern), set(), {})
    assert modern == before

    CharacterSheetService._validate_snapshot(
        _character_sheet_readiness_snapshot({"state": "acquired", "record_id": "foundation.legacy"}),
        set(), {},
    )
    CharacterSheetService._validate_snapshot(
        _character_sheet_readiness_snapshot({"state": "none"}), set(), {},
    )
    with pytest.raises(FoundryError) as raised:
        CharacterSheetService._validate_snapshot(
            _character_sheet_readiness_snapshot({"state": "active", "record_id": "foundation.spoof"}),
            set(), {},
        )
    assert raised.value.code == "CHARACTER_SHEET_BUILD_BLOCKED"
    assert raised.value.details["diagnostics"] == [
        {"code": "CHARACTER_SHEET_TYPED_NONE_INVALID", "system": "foundation"},
    ]


def test_foundation_profile_consumers_preserve_modern_projection_and_display_binding():
    from character_sheet.service import CharacterSheetService
    from factory_authoring.command5_profile import CharacterGMCommand5Profile

    selected = _modern_foundation_projection_fixture()
    selected.update({"record_hash": "f" * 64, "display_name": "Fixture Foundation"})
    source = {"path": "foundations.json", "anchor": "foundation:foundation.fixture", "sha256": "b" * 64}
    card = {
        "record_id": selected["record_id"],
        "record_hash": selected["record_hash"],
        "display_name": selected["display_name"],
        "full_description": "The complete sealed Foundation description.",
        "full_description_source": "locked_typed_catalog_record",
        "source": source,
        "source_packet_ids": selected["source_packet_ids"],
    }
    enriched = CharacterSheetService._enrich_selected_record_display(
        selected, {selected["record_id"]: card}, surface="Foundation",
    )
    assert enriched["full_description"] == card["full_description"]
    assert enriched["source"] == source

    snapshot = {"foundation": selected, "explicit_none_systems": {"foundation": {"state": "none"}}}
    assert CharacterGMCommand5Profile._typed_none(snapshot, "foundation") == selected
    snapshot_with_display = {
        **selected,
        "full_description": card["full_description"],
        "full_description_source": card["full_description_source"],
        "source": source,
        "source_packet_ids": selected["source_packet_ids"],
    }
    merged = CharacterGMCommand5Profile._merge_snapshot_display_fields(
        selected, snapshot_with_display, name="foundation",
    )
    assert merged["full_description"] == card["full_description"]


@pytest.mark.parametrize("identity,target_cl", [
    ("heaven_devouring_shedding_womb_v0_2B", 20),
    ("karma_knot_root_v0_2B", 9),
    ("FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", 5),
])
def test_real_causal_calculators_apply_initial_source_once_without_refill(foundation_project, identity, target_cl, tmp_path):
    # This deliberately exercises a bounded event prefix and later level
    # calculations. Ordinary training/milestone completion is tested by the
    # complete creator pipeline and actual Granite acceptance, not this test.
    creator, project, run, intent, _ = foundation_project
    paths = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
    stage2, events, state = _initial_method_events(creator, project, run, intent, "METHOD-083", paths)
    project_id = project["project_id"]
    proposal = {"project_id": project_id, "proposal_id": f"foundation-calculators.{identity}", "expected_project_revision": project["revision"], "idempotency_key": identity, "created_at": "2026-09-07T00:00:00+00:00"}
    record_cache = {}
    initial_stage = "Unstable" if identity == "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR" else "Awakened"
    with _private_scope(stage2, run["request"], run["run_id"], set(paths)), creator.db.connection() as conn:
        before = tuple(conn.execute("SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?", (project_id, identity)).fetchone())
        record = stage2._resolve_record_after_proof(conn, project_id, identity)
        assert record["content_binding"]["pack_version"] == FOUNDATION_MECHANICS_PACK_VERSION
        stage2._assert_record_after_proof(conn, project_id, record)
        # Ordinary snapshot assertion cannot independently promote a supplied
        # new version. The private creation scope is what authorizes it.
        with pytest.raises(FoundryError):
            creator.projects._assert_snapshot_record(conn, project_id, record)
        path_records = [stage2._resolve_record_after_proof(conn, project_id, path) for path in paths]
        for cl in range(2, target_cl + 1):
            entries = native_path_progressions(path_records, cl)
            feature = path_records[0]["compatibility"]["factory"]["stage2_authority"]["progression_by_cl"][str(cl)]["feature_record_ids"][0]
            choices = [{"kind": "level_advance", "record_id": feature, "effective_cl": cl, "acquisition_channel": events[-1]["legal_channel"] if cl == 2 else level_channel, "parameters": {"native_path_progressions": entries}}]
            level_channel = choices[0]["acquisition_channel"]
            if cl == 5:
                choices.append({"kind": "foundation_acquisition", "record_id": identity, "effective_cl": 5, "acquisition_channel": "foundation-selection", "parameters": {"stage": initial_stage}})
            for choice in choices:
                event, next_state, blockers = stage2._choice_event(conn=conn, row=proposal, project=project, state=state, choice=choice, index=len(events), sequence=len(events)+1, previous_hash=events[-1]["event_hash"], generic_prefix=events, record_cache=record_cache)
                assert not blockers, canonical_json({"choice": choice, "blockers": blockers})
                assert event is not None
                events.append(event)
                state = next_state
        assert tuple(conn.execute("SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?", (project_id, identity)).fetchone()) == before
        assert canonical_json(creator.projects._resolve_event_bound_foundation_after_proof(conn, project_id, identity, [event["content_binding"] for event in events if event["subject"]["record_id"] == identity])) == canonical_json(record)
        changed = deepcopy(next(event["content_binding"] for event in events if event["subject"]["record_id"] == identity))
        changed["pack_version"] = "99.0"
        with pytest.raises(FoundryError):
            creator.projects._resolve_event_bound_foundation_after_proof(conn, project_id, identity, [changed])
    # Retain the real calculator evidence even if a later independent boundary
    # fails, so failures can be diagnosed without regenerating the event chain.
    (tmp_path / "foundation-causal-evidence.json").write_text(canonical_json({
        "record": record, "project": project, "events": events, "state": state,
        "snapshot_before": before, "target_cl": target_cl,
    }), encoding="utf-8")
    acquisition = next(event for event in events if event["advancement"]["kind"] == "foundation_acquisition")
    _validate_binding(acquisition, record, project, locked_records={identity: record})
    validated = validate_initial_foundation_mechanics(record, events)
    assert validated["resource"]["current"] == 0
    assert validated["resource"]["maximum"] == 1
    assert validated["stage"] == initial_stage
    level_gains = sum(event["advancement"]["calculation"]["outputs"]["hp_after"]["last_gain"] for event in events if event["advancement"]["kind"] == "level_advance")
    pb = 2 + (target_cl - 1) // 4
    expected_hp = pb if identity.startswith("heaven_devouring") else 0
    assert state["hp"]["total"] == level_gains + expected_hp
    assert state["hp"]["foundation_delta"] == expected_hp
    body, spirit = (state["resources"][f"tianxia.resource.{name}"] for name in ("stamina", "resonance"))
    assert body["method_delta"] == -pb and spirit["method_delta"] == pb
    assert body["foundation_delta"] == 0
    assert spirit["foundation_delta"] == (pb if identity.startswith("karma_knot") else 0)
    # Build state has no spending events: every pool ends as full as its
    # maximum, and no event ever raised a pool by more than its maximum rose.
    assert all(resource["current"] == resource["maximum"] for resource in state["resources"].values())
    replayed, rows, _ = stage2._rows(events, project_id)
    assert replayed["hp"] == state["hp"]
    assert replayed["resources"] == state["resources"]
    assert len(rows) == target_cl
    for row in rows:
        hp = row["hp"]
        assert hp["total"] == hp["prior_total"] + hp["level_formula_gain"] + hp["retroactive_con_adjustment"] + hp.get("foundation_adjustment", 0)
    assert sum(row["hp"].get("foundation_adjustment", 0) for row in rows) == expected_hp
    assert rows[4]["hp"]["foundation_adjustment"] == (3 if expected_hp else 0)
    assert sum(component["value"] for component in rows[4]["hp"]["authority_components"] if component.get("role") == "foundation_hp") == (3 if expected_hp else 0)
    tampered = deepcopy(events)
    next(event for event in tampered if event["advancement"]["kind"] == "foundation_acquisition")["advancement"]["calculation"]["outputs"]["initial_foundation_mechanics"]["initial_state"]["resource"]["initial_current"] = 1
    with pytest.raises(FoundryError):
        validate_initial_foundation_mechanics(record, tampered)
    # A pool raised beyond its maximum's growth is a refill and is rejected.
    refilled = deepcopy(events)
    later = next(
        event for event in refilled
        if event["sequence"] >= acquisition["sequence"]
        and (event["advancement"].get("calculation") or {}).get("outputs", {}).get("resources_after")
    )
    pool = next(iter(later["advancement"]["calculation"]["outputs"]["resources_after"].values()))
    pool["current"] = pool["maximum"] + 1
    with pytest.raises(FoundryError) as refill_error:
        validate_initial_foundation_mechanics(record, refilled)
    assert refill_error.value.details["reason"] == "pool_source_contribution_or_refill"


def test_installed_foundation_binding_requires_exact_locked_source_and_supported_version(catalog_environment):
    authority = NonSphereAuthorityService(catalog_environment["db"])
    for identity in verified_foundation_records():
        record = authority.project_locked_foundation_catalog_record(identity, mechanical=True)
        event = {"event_id": "binding-check", "content_binding": {
            **record["content_binding"], "record_hash": record["record_hash"],
        }}
        project = {"content_lock": {"packs": []}}
        _validate_binding(event, record, project, locked_records={identity: record})
        with pytest.raises(FoundryError, match="authenticated locked-record"):
            _validate_binding(event, record, project, locked_records={})
        for field, value in (
            ("pack_version", "99.0"), ("minimum_cl", 1), ("refill_current", True),
            ("publication", "draft"), ("authority_complete", False),
            ("allowed_channels", ["owner-invented-grant"]), ("rule_id", "unproven.rule"),
            ("selected_authority", False),
        ):
            changed = deepcopy(record)
            if field == "pack_version":
                changed["content_binding"][field] = value
            elif field == "publication":
                changed["publication"]["status"] = value
            elif field == "selected_authority":
                changed["selected_authority"] = value
                changed["compatibility"]["factory"]["raw_projection"]["selected_authority"] = value
            elif field in {"minimum_cl", "authority_complete", "allowed_channels", "rule_id"}:
                changed["compatibility"]["factory"]["stage2_authority"][field] = value
            else:
                changed["compatibility"]["factory"]["stage2_authority"]["initial_foundation_mechanics"][field] = value
            changed["record_hash"] = canonical_record_hash(changed)
            forged = {"event_id": "binding-check", "content_binding": {
                **changed["content_binding"], "record_hash": changed["record_hash"],
            }}
            with pytest.raises(FoundryError):
                _validate_binding(forged, changed, project, locked_records={identity: changed})


def test_foundation_stage_schema_extension_is_version_specific():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/Advancement_Event_v3.schema.json").read_text())
    # Isolate the new version branch; the causal integration test exercises
    # the complete canonical event schema as well as source validation.
    validator = Draft202012Validator({"allOf": schema["allOf"]})
    event = {"content_binding": {"pack_id": "tianxia.non_sphere.authority", "pack_version": FOUNDATION_MECHANICS_PACK_VERSION}, "advancement": {"kind": "foundation_acquisition", "target_cl": 5, "details": {"stage": "Unstable"}, "calculation": {"outputs": {"initial_foundation_mechanics": {}, "hp_after": {}, "resources_after": {}}}}}
    assert not list(validator.iter_errors(event))
    for change in ("legacy", "early", "invented_stage", "foreign_field", "missing_outputs"):
        candidate = deepcopy(event)
        if change == "legacy":
            candidate["content_binding"]["pack_version"] = "P2A"
        elif change == "early":
            candidate["advancement"]["target_cl"] = 1
        elif change == "invented_stage":
            candidate["advancement"]["details"]["stage"] = "Perfected"
        elif change == "foreign_field":
            candidate["advancement"]["details"]["amount"] = 1
        else:
            candidate["advancement"]["calculation"]["outputs"] = {}
        assert list(validator.iter_errors(candidate)), change
    legacy = deepcopy(event)
    legacy["content_binding"]["pack_version"] = "P2A"
    legacy["advancement"]["details"] = {}
    legacy["advancement"]["target_cl"] = 1
    assert not list(validator.iter_errors(legacy))
