"""Exercise the real automatic-art compiler with a frozen creation request.

The state snapshots isolate this event's boundary; the provider-free CL1/CL10
probes cover assembly and full public finalization. Negative record-reader
variants model inconsistent source data without mocking the trust validator.
"""
import json
from contextlib import nullcontext
from copy import deepcopy
from itertools import combinations, product

import pytest

from app.core import FoundryError, canonical_json
from contracts.canonical import ZERO_HASH
from project_store.service import ProjectStore
from recorded_art_authority import (
    MANUAL_ACCESS_MODE,
    MANUAL_CHANNEL,
    RECORDED_ART_CHANNEL,
    RECORDED_ART_CONSTRUCTION_KIND,
    manual_outcome,
)
from character_creation.constructed_arts.manual import (
    construct_lineage_manual_collection,
    manual_collection_band,
    roll_manual_collection_count,
    validate_manual_collection_roll,
)
from character_creation.response_materialization import CanonicalSelectionIntent, RESPONSE_SCHEMA
from character_creation.service import _provider_payload
from stage2.service import RulesCausalStage2Service, _state
from character_creation.constructed_arts.sources import installed_factory_root, published_block
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_rec1_p1cr5_owner_authority import _private_scope


class _ManualFlowGMConsumer:
    def verify(self, receipt):
        return {
            "verified": True,
            "source_sha256": receipt["sha256"],
            "service": "gm_consumer",
        }


def _manual_flow_pipeline(db):
    """Use real scratch services for the public acceptance route."""
    from character_sheet import CharacterSheetService
    from factory_authoring import FactoryAuthoringWorkspaceService
    from gm_export import GMCharacterExportService
    from portable_character import PortableCharacterPackageService
    from projector.service import ProjectionService
    from stage1.service import Stage1ClipboardService
    from stage2 import Stage2AdvancementService

    return {
        "stage1": Stage1ClipboardService(db),
        "stage2": Stage2AdvancementService(db),
        "projections": ProjectionService(db),
        "character_sheets": CharacterSheetService(db),
        "factory_authoring": FactoryAuthoringWorkspaceService(db),
        "gm_exports": GMCharacterExportService(db),
        "gm_consumer": _ManualFlowGMConsumer(),
        "portable_characters": PortableCharacterPackageService(db),
        "combat_readiness": None,
        "production_release": None,
    }


def _capture_manual_materialization(services, project_id):
    """Observe the real scratch artifacts before the GM export gate runs."""
    db = services["stage2"].db
    with db.connection() as conn:
        constructed_records = [
            json.loads(row["record_json"])
            for row in conn.execute(
                """
                SELECT record_json
                FROM project_locked_records
                WHERE project_id=? AND record_id LIKE 'tianxia.constructed.%'
                ORDER BY record_id
                """,
                (project_id,),
            )
        ]
        events = [
            json.loads(row["event_json"])
            for row in conn.execute(
                "SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no",
                (project_id,),
            )
        ]
    projection_path = services["projections"].artifact(
        project_id, "Character_Master_Ledger.json"
    )
    projection_ledger = json.loads(projection_path.read_text(encoding="utf-8"))
    stage2_ledger = None
    stage2_ledger_error = None
    try:
        stage2_ledger = services["stage2"].ledger(project_id)
    except Exception as exc:  # the projection above is the compiler output
        stage2_ledger_error = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "message": str(exc),
        }
    return {
        "constructed_records": constructed_records,
        "events": events,
        "stage2_ledger": stage2_ledger,
        "stage2_ledger_error": stage2_ledger_error,
        "projection_ledger": projection_ledger,
    }


def _art_choice(record_id, cl=1):
    return {
        "kind": RECORDED_ART_CONSTRUCTION_KIND,
        "effective_cl": cl,
        "record_id": record_id,
        "acquisition_channel": RECORDED_ART_CHANNEL,
        "parameters": {"study_ability": "INT", "outcome": manual_outcome()},
    }


def _compile(env, state, choice, *, trusted=True, index=1):
    service = env["stage2"]
    scope = _private_scope(service, env["run"]["request"], env["run"]["run_id"], {"tianxia.path.body_refining"}) if trusted else nullcontext()
    with scope, service.db.connection() as conn:
        return service._choice_event(
            conn=conn,
            row=env["proposal"],
            project=env["project"],
            state=deepcopy(state),
            choice=choice,
            index=index,
            sequence=index + 1,
            previous_hash=ZERO_HASH,
            generic_prefix=[],
        )


@pytest.fixture(scope="module")
def art_environment(catalog_environment):
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment, target_cl=10)
    records = creator._locked_records_for_project(run["project_id"])
    pair = intent.as_dict()["acquisition_intent"]["sphere_free_talent_pairs"][0]
    base_rows = [
        {"kind": "path_acquisition", "effective_cl": 1, "record_id": "tianxia.path.body_refining"},
        {"kind": "ai_bootstrap_sphere_acquisition", "effective_cl": 1, "record_id": pair["sphere_id"]},
        {"kind": "ai_bootstrap_talent_acquisition", "effective_cl": 1, "record_id": pair["talent_id"]},
    ]
    bundle, constructed_records = creator._manual_constructions(
        run, project, intent.as_dict(), base_rows, records, 10, intent_hash=intent.intent_hash,
    )
    store = ProjectStore(creator.db)
    with creator.db.transaction() as conn:
        store.insert_constructed_art_records(conn, run["project_id"], constructed_records)
    stage2 = RulesCausalStage2Service(creator.db)
    art_ids = [art["record_id"] for art in bundle["recorded_arts"]]
    created = stage2.create_proposal({
        "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
        "project_id": run["project_id"],
        "expected_project_revision": run["request"]["project_revision"],
        "expected_content_lock_hash": run["request"]["content_lock_hash"],
        "target_cl": 10,
        "idempotency_key": "constructed-art-boundary-tests",
        "choices": [_art_choice(art_ids[0])],
    })
    with creator.db.connection() as conn:
        proposal = stage2._proposal_row(conn, created["proposal_id"])
    initial = _state(run["project_id"])
    initial.update({
        "current_cl": 1,
        "completed_levels": [1],
        "pb": 2,
        "ability_scores": {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8},
        "ability_modifiers": {"STR": 2, "DEX": 2, "CON": 1, "INT": 1, "WIS": 0, "CHA": -1},
        "paths": ["tianxia.path.body_refining"],
    })
    env = {"stage2": stage2, "creator": creator, "intent_doc": intent.as_dict(), "intent_hash": intent.intent_hash, "base_rows": base_rows, "run": run, "project": project, "proposal": proposal, "bundle": bundle, "records": {record["record_id"]: record for record in constructed_records}, "art_ids": art_ids, "initial": initial}
    source_choice = {
        "kind": "training_source_access", "effective_cl": 1,
        "record_id": bundle["manual"]["record_id"],
        "acquisition_channel": MANUAL_CHANNEL,
        "parameters": {"access_mode": MANUAL_ACCESS_MODE},
    }
    event, _, blockers = _compile(env, initial, source_choice, index=0)
    assert blockers == []
    assert event is not None
    env["source_event"] = event
    env["ready"] = stage2._apply_event(deepcopy(initial), event)
    return env


def _assert_rejected(env, state, choice, code, **kwargs):
    event, reduced, blockers = _compile(env, state, choice, **kwargs)
    assert event is None
    assert reduced == state
    assert code in {blocker["code"] for blocker in blockers}


def test_automatic_art_requires_real_trusted_scope(art_environment):
    env = art_environment
    choice = _art_choice(env["art_ids"][0])
    _assert_rejected(env, env["ready"], choice, "RECORDED_ART_CONSTRUCTION_SCOPE_REQUIRED", trusted=False)
    request = env["run"]["request"]
    with pytest.raises(FoundryError):
        with env["stage2"]._trusted_character_creation_scope(
            run_id=env["run"]["run_id"], project_id=request["project_id"],
            starting_revision=request["project_revision"], content_lock_hash=request["content_lock_hash"],
            typed_choice_snapshot_sha256=request["typed_choice_snapshot"]["snapshot_sha256"],
            request_sha256=request["request_sha256"], authorized_delegated_path_ids={"tianxia.path.body_refining"},
            phase="scratch_compile", candidate_identity=None, _server_authority=object(),
        ):
            pytest.fail("A caller-created object must not authorize the private scope.")


@pytest.mark.parametrize("parent_access", [[], ["manual.unrelated"]])
def test_automatic_art_requires_prior_access_to_its_actual_parent(art_environment, parent_access):
    env = art_environment
    state = deepcopy(env["ready"])
    state["training_sources"] = parent_access
    _assert_rejected(env, state, _art_choice(env["art_ids"][0]), "RECORDED_ART_PARENT_MANUAL_ACCESS_REQUIRED")


def test_automatic_art_cannot_precede_its_level_advance(art_environment):
    env = art_environment
    state = deepcopy(env["ready"])
    state["current_cl"] = 0
    _assert_rejected(env, state, _art_choice(env["art_ids"][0]), "RECORDED_ART_BEFORE_LEVEL_ADVANCE")


def _change_read_record(monkeypatch, service, record_id, change):
    original = service._record

    def read(*args, **kwargs):
        record, issues = original(*args, **kwargs)
        if record is not None and record.get("record_id") == record_id:
            record = deepcopy(record)
            change(record)
        return record, issues

    monkeypatch.setattr(service, "_record", read)


def test_regular_art_cannot_claim_the_automatic_lane(art_environment, monkeypatch):
    env = art_environment
    art_id = env["art_ids"][0]
    _change_read_record(monkeypatch, env["stage2"], art_id, lambda record: record["content_binding"].update(pack_id="ordinary.test.pack"))
    event, reduced, blockers = _compile(env, env["ready"], _art_choice(art_id))
    assert event is None and reduced == env["ready"]
    assert any("authenticated Factory" in blocker.get("message", "") for blocker in blockers)


@pytest.mark.parametrize("field,code", [
    ("record_hash", "RECORDED_ART_COMPONENT_HASH_MISMATCH"),
    ("display_name", "RECORDED_ART_COMPONENT_NAME_MISMATCH"),
    ("access_category", "RECORDED_ART_DIFFICULTY_AUTHORITY_MISMATCH"),
    ("source_hash", "RECORDED_ART_QUOTE_SOURCE_MISMATCH"),
])
def test_automatic_art_binds_actual_component_authority(art_environment, monkeypatch, field, code):
    env = art_environment
    art_id = env["art_ids"][0]
    component_id = env["bundle"]["recorded_arts"][0]["source_record_id"]

    def change(record):
        if field == "access_category":
            authority = record["compatibility"]["factory"]["stage2_authority"]
            authority[field] = "Secret" if authority.get(field) != "Secret" else "Open"
        elif field == "source_hash":
            record["source"][field] = "0" * 64
        else:
            record[field] = "0" * 64 if field == "record_hash" else "A different published Talent"

    _change_read_record(monkeypatch, env["stage2"], component_id, change)
    _assert_rejected(env, env["ready"], _art_choice(art_id), code)


def test_automatic_art_dc_counts_same_level_then_resets_without_trained_cost(art_environment):
    env = art_environment
    service = env["stage2"]
    state = deepcopy(env["ready"])
    original_choices = deepcopy(state["creation_training_choices"])
    original_costs = deepcopy(state["trained_success_cost"])
    expected_prior_counts = [0, 1, 0]
    for index, (art_id, cl, prior_count) in enumerate(zip(env["art_ids"], [1, 1, 2], expected_prior_counts), start=1):
        if cl == 2:
            state["current_cl"] = 2
            state["completed_levels"] = [1, 2]
        event, _, blockers = _compile(env, state, _art_choice(art_id, cl), index=index)
        assert blockers == []
        assert event is not None
        outputs = event["advancement"]["calculation"]["outputs"]
        dc = outputs["learning_dc"]
        assert dc["prior_recorded_arts_this_cl"] == prior_count
        assert dc["computed_dc"] == 10 + dc["difficulty"] + 2 * prior_count
        assert outputs["outcome"] == manual_outcome()
        state = service._apply_event(state, event)
        assert state["creation_training_choices"] == original_choices
        assert state["trained_success_cost"] == original_costs
        assert state["recorded_arts"][-1]["learned_at_cl"] == cl
    assert len(state["recorded_arts"]) == 3


@pytest.mark.parametrize("cl,dice_count", [(1, 1), (5, 1), (6, 2), (10, 2), (11, 3), (15, 3), (16, 4), (20, 4)])
def test_manual_collection_policy_has_exact_owner_boundaries(cl, dice_count):
    band = manual_collection_band(cl)
    assert band["dice_count"] == dice_count
    minimum = roll_manual_collection_count(cl, seed=f"min:{cl}", dice_faces=[1] * dice_count)
    maximum = roll_manual_collection_count(cl, seed=f"max:{cl}", dice_faces=[6] * dice_count)
    assert minimum["total"] == dice_count
    assert maximum["total"] == dice_count * 6
    assert minimum["faces"] == [1] * dice_count
    assert maximum["faces"] == [6] * dice_count


def test_manual_collection_roll_is_replayable_and_tamper_evident():
    first = roll_manual_collection_count(20, seed="accepted-intent", dice_faces=[2, 4, 1, 6])
    second = roll_manual_collection_count(20, seed="accepted-intent", dice_faces=[2, 4, 1, 6])
    assert first == second
    tampered = deepcopy(first)
    tampered["faces"][0] = 3
    with pytest.raises(FoundryError):
        validate_manual_collection_roll(tampered, cl=20)
    tampered = deepcopy(first)
    tampered["policy_id"] = "other-policy"
    with pytest.raises(FoundryError):
        validate_manual_collection_roll(tampered, cl=20)


def test_manual_collection_constructs_distinct_parent_art_lineages_and_replays(art_environment):
    request = deepcopy(art_environment["bundle"]["manual"]["construction"]["request"])
    first = deepcopy(request["known_talents"][0])
    second = deepcopy(first)
    second.update({
        "talent_id": "tianxia.test.distinct_manual_talent",
        "display_name": "Distinct Manual Talent",
        "record_hash": "b" * 64,
        "published_text": first["published_text"] + "\nDistinct source-backed branch.",
        "source": {
            **first["source"],
            "source_id": "source.test.distinct_manual_talent",
            "anchor": first["source"]["anchor"] + ":distinct",
            "source_hash": "c" * 64,
        },
    })
    request["known_talents"] = [first, second]
    roll = roll_manual_collection_count(10, seed="collection", dice_faces=[1, 1])
    bundles = construct_lineage_manual_collection(
        request,
        roll=roll,
        source_talent_ids=[first["talent_id"], second["talent_id"]],
    )
    assert len(bundles) == 2
    assert len({bundle["manual"]["record_id"] for bundle in bundles}) == 2
    assert bundles[0]["recorded_arts"][0]["source_record_id"] != bundles[1]["recorded_arts"][0]["source_record_id"]
    assert all(
        art["parent_manual_record_id"] == bundle["manual"]["record_id"]
        for bundle in bundles
        for art in bundle["recorded_arts"]
    )
    replay = construct_lineage_manual_collection(
        request,
        roll=roll,
        source_talent_ids=[first["talent_id"], second["talent_id"]],
    )
    assert replay == bundles


def test_manual_collection_keeps_higher_printed_content_locked_and_rejects_wrong_legacy_identity(art_environment):
    request = deepcopy(art_environment["bundle"]["manual"]["construction"]["request"])
    request["cl"] = 1
    source = request["known_talents"][0]
    printed_contents = []
    for ordinal in range(3):
        content = deepcopy(source)
        content.update({
            "talent_id": f"tianxia.test.future_manual_talent_{ordinal}",
            "display_name": f"Future Manual Talent {ordinal}",
            "record_hash": f"{ordinal + 1}" * 64,
            "published_text": source["published_text"] + f"\nFuture printed branch {ordinal}.",
            "minimum_cl": 12,
            "source": {
                **source["source"],
                "source_id": f"source.test.future_manual_talent_{ordinal}",
                "anchor": source["source"]["anchor"] + f":future:{ordinal}",
                "source_hash": f"{ordinal + 4}" * 64,
            },
        })
        printed_contents.append(content)
    roll = roll_manual_collection_count(1, seed="chronology", dice_faces=[1])
    bundles = construct_lineage_manual_collection(request, roll=roll, manual_contents=[printed_contents])
    assert len(bundles) == 1
    assert {art["minimum_cl"] for art in bundles[0]["recorded_arts"]} == {12}
    # The owner can possess/read the book before its Realm/CL gate; the
    # separate Stage 2 learning event remains responsible for eligibility.
    with pytest.raises(FoundryError):
        construct_lineage_manual_collection(
            request,
            roll=roll,
            source_talent_ids=["tianxia.test.not_authenticated"],
        )


def test_service_manual_collection_uses_locked_contents_without_learning_every_book(art_environment):
    env = art_environment
    creator = env["creator"]
    locked = creator._locked_records_for_project(env["run"]["project_id"])
    factory_root = installed_factory_root(creator.db.settings.vendor_dir)
    grouped: dict[str, list[dict]] = {}
    for record_id, record in sorted(locked.items()):
        if not isinstance(record, dict) or record.get("content_type") != "talent":
            continue
        authority = (((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {})
        sphere_id = authority.get("sphere_id")
        source = record.get("source")
        if not isinstance(sphere_id, str) or not isinstance(source, dict) or not published_block(factory_root, source):
            continue
        grouped.setdefault(sphere_id, []).append({
            "record_id": record_id,
            "record_hash": record["record_hash"],
            "source": {key: source[key] for key in ("source_id", "path", "anchor", "source_hash")},
        })
    groups = [rows for rows in grouped.values() if len(rows) >= 3]
    assert len(groups) >= 2
    from character_creation.constructed_arts.manual import roll_manual_collection_count
    expected_roll = env["run"]["request"]["server_owned_authority"]["manual_collection"]["roll"]
    tuple_options = [
        list(content_tuple)
        for group in groups
        for content_tuple in combinations(group, 3)
    ]
    assert len(tuple_options) >= expected_roll["total"]
    content_groups = tuple_options[:expected_roll["total"]]
    assert len({tuple(sorted(row["record_id"] for row in rows)) for rows in content_groups}) == expected_roll["total"]
    authority = {
        "schema": "TianxiaFoundry.LineageManualCollection.v1",
        "policy_id": "TIANXIA.FACTORY.MARTIAL_MANUAL_COLLECTION.D6_BANDS.v1",
        "roll": expected_roll,
        "manuals": [
            {
                "collection_id": f"test.collection.{index}",
                "content_record_ids": [row["record_id"] for row in rows],
                "content_record_bindings": rows,
            }
            for index, rows in enumerate(content_groups)
        ],
    }
    intent_doc = deepcopy(env["intent_doc"])
    intent_doc["acquisition_intent"]["manual_collection"] = authority
    bundles, records, roll = creator._manual_collection_constructions(
        env["run"],
        env["project"],
        intent_doc,
        env["base_rows"],
        locked,
        10,
        intent_hash=env["intent_hash"],
    )
    assert roll == expected_roll
    assert len(bundles) == expected_roll["total"]
    assert len({bundle["manual"]["record_id"] for bundle in bundles}) == expected_roll["total"]
    assert all(bundle["manual"]["collection"]["learned_record_ids"] == [] for bundle in bundles)
    assert len(records) == expected_roll["total"] * 4
    # The printed contents are owned source metadata; this direct constructor
    # does not itself schedule any legal learning event.
    assert all(
        all(art["source_record_id"] in bundle["manual"]["collection"]["content_record_ids"] for art in bundle["recorded_arts"])
        for bundle in bundles
    )


def test_server_manual_collection_rejects_tampered_collection_id(catalog_environment):
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment, target_cl=1)
    canonical = creator._server_manual_collection_intent(
        run, project, intent, target_cl=1,
    ).as_dict()
    tampered = deepcopy(canonical)
    tampered["acquisition_intent"]["manual_collection"]["manuals"][0]["collection_id"] += ".tampered"
    with pytest.raises(FoundryError) as caught:
        creator._server_manual_collection_intent(
            run,
            project,
            CanonicalSelectionIntent.from_document(tampered),
            target_cl=1,
        )
    assert caught.value.code == "CG1_MANUAL_COLLECTION_AUTHORITY_TAMPERED"


def test_new_request_provider_omitted_collection_is_server_injected_and_materialized(catalog_environment):
    """Exercise response acceptance through scratch materialization without provider-owned bindings."""
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment, target_cl=1)
    pair = intent.as_dict()["acquisition_intent"]["sphere_free_talent_pairs"][0]
    base_rows = [
        {"kind": "path_acquisition", "effective_cl": 1, "record_id": "tianxia.path.body_refining"},
        {"kind": "ai_bootstrap_sphere_acquisition", "effective_cl": 1, "record_id": pair["sphere_id"]},
        {"kind": "ai_bootstrap_talent_acquisition", "effective_cl": 1, "record_id": pair["talent_id"]},
    ]
    env = {
        "creator": creator,
        "project": project,
        "run": run,
        "intent_doc": intent.as_dict(),
        "intent_hash": intent.intent_hash,
        "base_rows": base_rows,
    }
    creator = env["creator"]
    observation = {}
    original_normalize = creator._normalize_and_materialize_response

    def observe_normalization(run_doc, plan):
        result = original_normalize(run_doc, plan)
        normalized, canonical, materialized_stage2 = result
        observation["canonical_intent"] = (
            deepcopy(canonical.as_dict()) if canonical is not None else None
        )
        observation["normalized_plan"] = deepcopy(normalized)
        observation["materialized_stage2"] = deepcopy(materialized_stage2)
        return result

    creator._normalize_and_materialize_response = observe_normalization

    def observing_pipeline(db):
        services = _manual_flow_pipeline(db)
        gm_exports = services["gm_exports"]
        original_export = gm_exports.export

        def observe_export(project_id, *args, **kwargs):
            try:
                observation["scratch"] = _capture_manual_materialization(
                    services, project_id
                )
            except Exception as exc:  # preserve the compiler's own error
                observation["scratch_error"] = {
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                }
            return original_export(project_id, *args, **kwargs)

        gm_exports.export = observe_export
        return services

    creator.pipeline_factory = observing_pipeline
    public = creator.start(
        env["run"]["project_id"],
        execution_mode="MANUAL_CHAT",
        idempotency_key="manual-collection-public-flow",
    )
    retry = creator.start(
        env["run"]["project_id"],
        execution_mode="MANUAL_CHAT",
        idempotency_key="manual-collection-public-flow",
    )
    assert retry["run_id"] == public["run_id"]
    assert retry["request"] == public["request"]
    run = creator.get(public["run_id"])
    marker = run["request"]["server_owned_authority"]["manual_collection"]
    assert isinstance(marker.get("nonce"), str) and len(marker["nonce"]) >= 32
    assert marker["nonce"] not in canonical_json(_provider_payload(run, cue_limit=0, display_limit=0))
    assert marker["seed"] not in canonical_json(_provider_payload(run, cue_limit=0, display_limit=0))
    intent_doc = deepcopy(env["intent_doc"])
    provider_payload = _provider_payload(run, cue_limit=0, display_limit=0)
    response = deepcopy(provider_payload["response_contract"]["response_template"])
    response["schema"] = RESPONSE_SCHEMA
    response["request_sha256"] = run["request"]["request_sha256"]
    template_slots = response["selection_intent"]["by_slot"]
    for slot_id, values in {
        **(intent_doc.get("planning_preferences_by_slot") or {}),
        **(intent_doc.get("selected_by_slot") or {}),
    }.items():
        if isinstance(values, list) and values:
            template_slots[slot_id] = list(values)
    response["selection_intent"] = {"by_slot": template_slots}
    starting_contract = (
        (run["request"].get("bounded_choice_contract") or {})
        .get("starting_proficiency_choice_contract")
        or {}
    )
    # Use the sealed menu entries, rather than inventing proficiency values in
    # this provider-omitted integration response.  The production validator
    # must continue to reject absent or out-of-menu starting choices.
    for field, slot, count_key in (
        ("path_skill_choices_by_path_id", "path_choice", "required_count"),
        ("background_language_choices_by_background_id", "background_choice", "language_choice_count"),
        ("origin_skill_choices_by_origin_id", "origin_insight_choice", "required_count"),
    ):
        entries = (starting_contract.get("fields") or {}).get(field) or {}
        selected_ids = template_slots.get(slot) or []
        values = {}
        for choice_id in selected_ids:
            entry = entries.get(choice_id) if isinstance(entries, dict) else None
            allowed = entry.get("allowed_values") if isinstance(entry, dict) else None
            count = entry.get(count_key) if isinstance(entry, dict) else None
            if type(count) is int and count > 0 and isinstance(allowed, list):
                values[choice_id] = list(allowed[:count])
        response.setdefault("bounded_choices", {})[field] = values
    response_contract = provider_payload["response_contract"]
    method_pairs = response_contract.get("presented_legal_method_path_pairs") or []
    selected_paths = set(template_slots.get("path_choice") or [])
    method_id = next(
        pair["method_id"]
        for pair in method_pairs
        if isinstance(pair, dict)
        and pair.get("path_id") in selected_paths
        and isinstance(pair.get("method_id"), str)
    )
    template_slots["method_choice"] = [method_id]
    source_acquisition = intent_doc.get("acquisition_intent") or {}
    trained_spheres = {
        row.get("record_id")
        for row in source_acquisition.get("trained_choices") or []
        if isinstance(row, dict)
        and row.get("choice_type") == "new_sphere"
        and isinstance(row.get("record_id"), str)
    }
    # A Background already grants its canonical Sphere. Starting-route fixture
    # choices must not acquire it again through a different source record: the
    # automatic-component receipt correctly rejects conflicting authority.
    from creation_training_authority import canonical_background_package_ids
    background_spheres, _ = canonical_background_package_ids(
        template_slots, run["request"]["delegated_choice_envelope"]["typed_choice_authority_by_slot"])
    acquired_spheres = trained_spheres | background_spheres
    route_modules = provider_payload.get("sphere_route_modules") or []
    if route_modules:
        route = next(
            (
                candidate
                for candidate in route_modules
                if isinstance(candidate, dict)
                and isinstance(candidate.get("free_talent_pair"), dict)
                and candidate["free_talent_pair"].get("sphere_id") not in acquired_spheres
            )
        )
        pair = route.get("free_talent_pair") if isinstance(route, dict) else None
        assignments = route.get("ordinary_talent_ids_by_cl") if isinstance(route, dict) else None
        ordinary_ids = [
            assignments.get(str(cl))
            for cl in range(1, int(response_contract.get("ordinary_talent_array_length") or 0) + 1)
        ] if isinstance(assignments, dict) else []
        assert isinstance(pair, dict) and all(isinstance(value, str) for value in (pair.get("sphere_id"), pair.get("talent_id")))
        assert all(isinstance(value, str) and value.strip() for value in ordinary_ids)
        response["acquisition_intent"] = {
            "sphere_free_talent_pairs": [deepcopy(pair)],
            "ordinary_talent_ids": ordinary_ids,
            "insight_occurrences": [],
        }
        template_slots["advancement_skeleton"] = list(ordinary_ids)
    else:
        ordinary_by_cl = response_contract.get("presented_legal_ordinary_talent_ids_by_cl") or {}
        ordinary_ids = [
            (ordinary_by_cl.get(str(cl)) or [None])[0]
            for cl in range(1, int(response_contract.get("ordinary_talent_array_length") or 0) + 1)
        ]
        assert all(isinstance(value, str) and value.strip() for value in ordinary_ids)
        response["acquisition_intent"] = {
            "sphere_free_talent_pairs": deepcopy(response_contract.get("presented_legal_first_cycle_pairs") or []),
            "ordinary_talent_ids": ordinary_ids,
            "insight_occurrences": [],
        }
        template_slots["advancement_skeleton"] = list(ordinary_ids)
    if creator._creation_training_contract_active(env["run"]):
        response["acquisition_intent"]["trained_choices"] = deepcopy(source_acquisition.get("trained_choices") or [])
    if creator._explicit_forging_contract_active(env["run"]):
        response["acquisition_intent"]["forged_technique_concepts"] = deepcopy(source_acquisition.get("forged_technique_concepts") or [])
    advertised_bounded = set((run["request"].get("bounded_choice_contract") or {}).get("fields") or {})
    response["bounded_choices"].update({
        key: deepcopy(value)
        for key, value in (intent_doc.get("bounded_choices") or {}).items()
        if key in advertised_bounded
    })
    # Resolve each selected Path milestone from the provider contract using a
    # legal source-backed ASI option.  These values are response fixture data;
    # the production validator remains the authority for every bound.
    asi_by_milestone = (
        response["bounded_choices"].setdefault(
            "ability_score_changes_by_milestone_id", {}
        )
        if "ability_score_changes_by_milestone_id" in advertised_bounded
        else None
    )
    scores = deepcopy(response["bounded_choices"].get("ability_scores") or {})
    for milestone_id, milestone in sorted((response_contract.get("required_milestone_resolutions") or {}).items()):
        if milestone.get("path_id") not in set(template_slots.get("path_choice") or []):
            continue
        options = milestone.get("resolution_options") or {}
        asi = options.get("ability_score_change") if isinstance(options, dict) else None
        constraints = asi.get("constraints") if isinstance(asi, dict) else None
        if not isinstance(constraints, dict) or asi_by_milestone is None:
            continue
        abilities = [value for value in constraints.get("allowed_abilities") or scores if isinstance(value, str)]
        deltas = [value for value in constraints.get("allowed_deltas") or [] if type(value) is int and value > 0]
        budget = constraints.get("budget")
        cap = constraints.get("cap")
        choice = None
        if abilities and deltas and type(budget) is int and type(cap) is int:
            for size in range(1, len(abilities) + 1):
                for selected_abilities in combinations(abilities, size):
                    for selected_deltas in product(deltas, repeat=size):
                        candidate = dict(zip(selected_abilities, selected_deltas))
                        if sum(candidate.values()) == budget and all(
                            type(scores.get(ability)) is int and scores[ability] + delta <= cap
                            for ability, delta in candidate.items()
                        ):
                            choice = candidate
                            break
                    if choice is not None:
                        break
                if choice is not None:
                    break
        assert choice is not None, f"no legal ASI fixture choice for {milestone_id}"
        asi_by_milestone[milestone_id] = {"deltas": choice}
        for ability, delta in choice.items():
            scores[ability] += delta
    # Preserve every sealed owner-locked descriptive value from the response
    # contract.  Delegated fields use the project-owned descriptive inputs;
    # this fixture must not invent a competing name, title, or concept.
    descriptive = deepcopy(response.get("owner_descriptive_fields") or {})
    identity = descriptive.setdefault("identity", {})
    delegated_fields = (
        (run["request"].get("delegated_choice_envelope") or {}).get("delegated_fields")
        or {}
    )
    project_name = env["project"].get("working_name") or env["project"].get("name")
    project_concept = env["project"].get("concept")
    for field, container, key, fallback in (
        ("identity.name", identity, "name", project_name),
        ("identity.title", identity, "title", None),
        ("concept", descriptive, "concept", project_concept),
    ):
        authority = delegated_fields.get(field) if isinstance(delegated_fields, dict) else None
        if isinstance(authority, dict) and authority.get("state") == "owner_locked":
            locked = authority.get("owner_value")
            if isinstance(locked, str) and locked.strip():
                container[key] = locked
        elif field == "identity.title" and isinstance(authority, dict) and authority.get("state") == "delegated":
            # The sealed title contract has no owner value to copy in this
            # fixture.  Supply one concise answer for the delegated field;
            # name and concept above still come from their actual project
            # locks/inputs rather than test labels.
            container[key] = "A source-bound cultivation practitioner"
        elif not container.get(key) and isinstance(fallback, str) and fallback.strip():
            container[key] = fallback
    response["owner_descriptive_fields"] = descriptive
    assert "manual_collection" not in response["acquisition_intent"]

    submitted = creator.submit_manual(
        public["run_id"],
        response_text=canonical_json(response),
        request_sha256=run["request"]["request_sha256"],
    )
    blockers = submitted.get("blockers") or []
    if blockers:
        assert len(blockers) == 1, canonical_json(blockers)
        assert blockers[0].get("code") == "GM_CHARACTER_EXPORT_NOT_READY", canonical_json(blockers)
        assert submitted["status"] == "NEEDS_REVIEW"
        diagnostic = (submitted.get("validation") or {}).get("last_submission_error") or {}
        assert diagnostic.get("code") == "GM_CHARACTER_EXPORT_NOT_READY", canonical_json(diagnostic)
    else:
        assert submitted["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}

    canonical_intent = observation.get("canonical_intent")
    if not isinstance(canonical_intent, dict):
        parsed_plan = (submitted.get("response") or {}).get("parsed_plan")
        canonical_intent = parsed_plan.get("canonical_selection_intent") if isinstance(parsed_plan, dict) else None
    assert isinstance(canonical_intent, dict), canonical_json(observation)
    authority = canonical_intent["acquisition_intent"]["manual_collection"]
    server_marker = run["request"]["server_owned_authority"]["manual_collection"]
    assert authority["roll"] == server_marker["roll"]
    assert len(authority["manuals"]) == authority["roll"]["total"]

    scratch = observation.get("scratch")
    assert isinstance(scratch, dict), canonical_json(observation)
    assert "scratch_error" not in observation, canonical_json(observation)
    constructed_records = scratch["constructed_records"]
    manual_records = [
        row for row in constructed_records if row.get("content_type") == "manual"
    ]
    recorded_art_records = [
        row for row in constructed_records if row.get("content_type") == "recorded_art"
    ]
    assert len(manual_records) == authority["roll"]["total"]
    assert len(recorded_art_records) == authority["roll"]["total"] * 3
    assert all(
        row["compatibility"]["factory"]["stage2_authority"]["manual"]["collection"]["roll"]
        == server_marker["roll"]
        for row in manual_records
    )
    assert all("learned_at_cl" not in row for row in recorded_art_records)
    source_access_events = [
        event
        for event in scratch["events"]
        if (event.get("advancement") or {}).get("kind") == "training_source_access"
    ]
    source_access_manual_ids = [
        (event.get("subject") or {}).get("record_id")
        for event in source_access_events
    ]
    assert len([
        record_id
        for record_id in source_access_manual_ids
        if isinstance(record_id, str)
        and record_id.startswith("tianxia.constructed.manual.")
    ]) == authority["roll"]["total"]
    assert all(
        (event.get("advancement") or {}).get("kind") != RECORDED_ART_CONSTRUCTION_KIND
        for event in scratch["events"]
    )
    projection_ledger = scratch["projection_ledger"]
    assert isinstance(projection_ledger, dict)
    projected_sources = projection_ledger.get("training_sources") or []
    assert len([
        row
        for row in projected_sources
        if isinstance(row, dict)
        and row.get("source_id") in source_access_manual_ids
    ]) == authority["roll"]["total"]
    assert projection_ledger.get("recorded_arts") == []
    assert all(
        detail.get("state") == "locked"
        for row in projected_sources
        if isinstance(row, dict)
        for detail in (row.get("contents") or {}).get("recorded_art_details") or []
        if isinstance(detail, dict)
    )
    if scratch["stage2_ledger"] is not None:
        assert scratch["stage2_ledger"]["project_id"] == run["project_id"]
        assert scratch["stage2_ledger"]["rows"]

    compiled = submitted.get("dry_run") or {}
    compiled_artifacts = compiled.get("artifacts") if isinstance(compiled, dict) else None
    if isinstance(compiled_artifacts, dict):
        constructed_receipt = compiled_artifacts.get("constructed_arts")
        assert constructed_receipt is not None
        assert len(constructed_receipt["manuals"]) == authority["roll"]["total"]
        assert all("learned_at_cl" not in row for row in constructed_receipt["recorded_arts"])
        assert compiled_artifacts.get("ledger") is not None

    stable = creator._server_manual_collection_intent(
        run,
        env["project"],
        CanonicalSelectionIntent.from_document(deepcopy(canonical_intent)),
        target_cl=1,
    )
    assert stable.as_dict()["acquisition_intent"]["manual_collection"] == authority

    tampered_doc = deepcopy(canonical_intent)
    tampered_doc["acquisition_intent"]["manual_collection"]["manuals"][0]["collection_id"] += ".tampered"
    with pytest.raises(FoundryError) as tampered:
        creator._server_manual_collection_intent(
            run,
            env["project"],
            CanonicalSelectionIntent.from_document(tampered_doc),
            target_cl=1,
        )
    assert tampered.value.code == "CG1_MANUAL_COLLECTION_AUTHORITY_TAMPERED"

    legacy_run = deepcopy(run)
    legacy_run["request"]["server_owned_authority"].pop("manual_collection")
    locked = creator._locked_records_for_project(run["project_id"])
    legacy_bundles, _legacy_records, legacy_roll = creator._manual_collection_constructions(
        legacy_run,
        env["project"],
        intent_doc,
        env["base_rows"],
        locked,
        1,
        intent_hash=env["intent_hash"],
    )
    assert len(legacy_bundles) == 1
    assert legacy_roll is None
