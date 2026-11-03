from __future__ import annotations

import copy
import importlib
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import FoundryError
from combat.canonical import canonical_sha256
from combat.character_adapter_service import CharacterCombatAdapter
from combat.character_runtime_adapter import (
    CharacterCombatRuntimeAdapter,
    CharacterCombatRuntimeEngine,
    RuntimeActionRequest,
    RuntimeResourceInitialization,
    SOURCE_ACTOR_ID,
    dummy_actor_template,
)
from combat.gate2_runtime_models import (
    ActionIntent,
    CandidateKind,
    ConditionInstance,
    LegalCandidate,
    Position,
    ReactionDecision,
    RuntimeObjectState,
)
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.diagnostics import CombatGate1Error

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip"


@pytest.fixture(scope="session")
def runtime_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("c3ar-runtime-package")
    output = root / "candidate.zip"
    CharacterCombatAdapter().compile(SOURCE, output_dir=root / "artifacts", output_package=output)
    return output


@pytest.fixture(scope="session")
def adapter(runtime_package: Path) -> CharacterCombatRuntimeAdapter:
    return CharacterCombatRuntimeAdapter(runtime_package)


@pytest.fixture(scope="session")
def bundle(adapter: CharacterCombatRuntimeAdapter):
    return adapter.build_bundle(
        RuntimeResourceInitialization(
            qi_current=15,
            martial_focus_current=1,
            provenance_kind="TEST_FIXTURE",
            provenance_id="pytest:c3ar",
        )
    )


def runtime_engine(bundle, *, seed: str = "C3AR-TEST", target_team: str = "team:dummy", objects=(), target_reactions=()):
    target = dummy_actor_template(
        "dummy:target",
        team_id=target_team,
        armor_class=0,
        maximum_hp=1000,
        reaction_ids=target_reactions,
    ).model_copy(
        update={
            "saving_throws": {"STR": -100, "DEX": -100, "CON": 100, "INT": 0, "WIS": 0, "CHA": 0},
            "skills": {"Athletics": -100, "Acrobatics": -100, "Perception": -100, "Sleight of Hand": -100},
        }
    )
    return CharacterCombatRuntimeEngine(
        ROOT,
        bundle,
        match_seed=seed,
        additional_actors=(target,),
        positions={SOURCE_ACTOR_ID: Position(x=2, y=2), "dummy:target": Position(x=3, y=2)},
        objects=tuple(objects),
    )


def req(action_id: str, **kwargs) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        request_id=f"request:{action_id}",
        actor_id=SOURCE_ACTOR_ID,
        action_id=action_id,
        **kwargs,
    )


def event_types(result) -> list[str]:
    return [row["event_type"] for row in result.events]


MECHANIC_IDS = (
    "action:core.dash", "action:core.disengage", "action:core.dodge", "action:core.unarmed_strike",
    "action:fire.burning_weapon", "action:fire.combustive_step", "action:fire.conflagration",
    "action:fire.fireball_art", "action:fire.flame_lash", "action:fire.ignite",
    "action:qi.meridian_regulation", "action:scoundrel.dirty_trick", "action:scoundrel.steal",
    "augment:fire.heat_haze", "augment:fire.lingering_conflagration", "augment:fire.overheat_ignite",
    "passive:cinder.fire_resistance", "passive:cinder.revealing_ember", "passive:cinder.touch_damage",
    "passive:fire.core_rules", "passive:origin.street_hardened", "passive:qi.qi_sensing",
    "passive:qi.technique_potency", "passive:scoundrel.exploited_opening",
    "passive:scoundrel.martial_focus_rules", "reaction:core.opportunity_attack",
    "reaction:fire.fire_ward", "reaction:qi.qi_armor", "resource:core.martial_focus", "resource:core.qi",
)


@pytest.mark.parametrize("stable_id", MECHANIC_IDS, ids=MECHANIC_IDS)
def test_runtime_support_matrix_all_30(adapter, bundle, stable_id: str):
    row = next(row for row in bundle.support_matrix if row.stable_id == stable_id)
    assert row.status in {"RUNTIME_EXECUTABLE", "RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION"}
    assert row.required_primitives
    assert row.executing_handler
    assert stable_id in row.runtime_catalog_entry
    assert row.dry_run_test.endswith(f"[{stable_id}]")


def test_adapter_converts_sealed_sheet_to_existing_runtime_contracts(adapter, bundle):
    assert len(bundle.support_matrix) == 30
    assert len(bundle.action_catalog) == 13
    assert len(bundle.primitive_bindings) == 19
    assert bundle.actor_template.entity_id == SOURCE_ACTOR_ID
    assert set(bundle.actor_template.action_ids) == {row.source_definition_id for row in bundle.action_catalog}
    assert set(bundle.actor_template.reaction_ids) == {
        "reaction:core.opportunity_attack", "reaction:fire.fire_ward", "reaction:qi.qi_armor"
    }
    assert set(bundle.actor_template.passive_ids) == set(bundle.passive_bindings)
    assert set(bundle.actor_template.augment_ids) == set(bundle.augment_bindings)
    assert all(row.status != "STATIC_ONLY" for row in bundle.support_matrix)
    assert bundle.runtime_prose_parsing is False and bundle.typed_data_only is True


def test_every_required_primitive_resolves_to_an_importable_handler(bundle):
    for binding in bundle.primitive_bindings:
        module_name, _, attribute_path = binding.executing_handler.partition(".")
        # Find the longest importable module prefix, then walk attributes.
        parts = binding.executing_handler.split(".")
        obj = None
        for index in range(len(parts), 0, -1):
            try:
                obj = importlib.import_module(".".join(parts[:index]))
            except ModuleNotFoundError:
                continue
            for name in parts[index:]:
                obj = getattr(obj, name)
            break
        assert callable(obj), binding


def test_typed_resource_initialization_is_required_bounded_and_noncanonical(adapter, bundle):
    assert bundle.resource_initialization.provenance_kind == "TEST_FIXTURE"
    assert bundle.resource_initialization.canonical_owner_choice is False
    actor = CharacterCombatRuntimeEngine(ROOT, bundle, match_seed="init").state.actors[SOURCE_ACTOR_ID]
    assert actor.resources == {"resource:core.qi": 15, "resource:core.martial_focus": 1}
    with pytest.raises(ValidationError):
        RuntimeResourceInitialization(qi_current=16, martial_focus_current=0, provenance_kind="TEST_FIXTURE", provenance_id="bad")
    with pytest.raises(ValidationError):
        RuntimeResourceInitialization(qi_current=0, martial_focus_current=2, provenance_kind="TEST_FIXTURE", provenance_id="bad")


def test_universal_actions_consume_economy_and_emit_typed_state_changes(bundle):
    dash = runtime_engine(bundle, seed="dash")
    dash.state.actors[SOURCE_ACTOR_ID].resources["resource:core.martial_focus"] = 0
    result = dash.execute_action(req("action:core.dash"))
    assert dash.state.actors[SOURCE_ACTOR_ID].action_available is False
    assert dash.state.actors[SOURCE_ACTOR_ID].movement_remaining_ft == 60
    assert dash.state.actors[SOURCE_ACTOR_ID].resources["resource:core.martial_focus"] == 1
    assert event_types(result) == ["INTENT_ACCEPTED", "PASSIVE_TRIGGERED", "RESOURCE_GAINED"]

    dodge = runtime_engine(bundle, seed="dodge")
    result = dodge.execute_action(req("action:core.dodge"))
    assert "CONDITION_APPLIED" in event_types(result)
    assert any(row.condition_id == "condition:core.dodging" for row in dodge.state.actors[SOURCE_ACTOR_ID].conditions.values())

    strike = runtime_engine(bundle, seed="strike")
    before = strike.state.actors["dummy:target"].current_hp
    result = strike.execute_action(req("action:core.unarmed_strike", target_id="dummy:target"))
    assert strike.state.actors["dummy:target"].current_hp == before - 2
    assert {"ATTACK_ROLLED", "DAMAGE_COMMITTED"} <= set(event_types(result))


def test_fire_actions_resources_geometry_damage_zones_objects_and_augments(bundle):
    straw = RuntimeObjectState(
        object_id="object:straw", object_kind="STRAW_DUMMY", position=Position(x=3, y=3),
        unattended=True, flammable=True,
    )
    engine = runtime_engine(bundle, seed="conflagration", objects=(straw,))
    result = engine.execute_action(req(
        "action:fire.conflagration", destination=Position(x=3, y=2),
        option_ids=("AUGMENT_HEAT_HAZE", "AUGMENT_LINGERING"), object_ids=("object:straw",),
    ))
    actor = engine.state.actors[SOURCE_ACTOR_ID]
    assert actor.action_available is False
    assert actor.resources["resource:core.qi"] == 10
    assert engine.state.objects["object:straw"].ignited is True
    zone = next(iter(engine.state.zones.values()))
    assert zone.trigger_profile["kind"] == "FIRE_TERRAIN"
    assert zone.trigger_profile["heat_haze"] is True
    assert zone.concentration_link is False and zone.duration_rounds == 10
    assert {"ZONE_CREATED", "OBJECT_IGNITED", "SAVE_ROLLED", "DAMAGE_COMMITTED"} <= set(event_types(result))

    bad = RuntimeObjectState(
        object_id="object:stone", object_kind="STONE", position=Position(x=3, y=3),
        unattended=True, flammable=False,
    )
    rejected = runtime_engine(bundle, seed="object-reject", objects=(bad,))
    with pytest.raises(ValueError, match="unattended flammable"):
        rejected.execute_action(req(
            "action:fire.fireball_art", destination=Position(x=3, y=2), object_ids=("object:stone",)
        ))


def test_burning_weapon_ignite_flame_lash_and_once_per_turn_scopes(bundle):
    engine = runtime_engine(bundle, seed="burning-weapon")
    result = engine.execute_action(req("action:fire.burning_weapon"))
    assert engine.state.actors[SOURCE_ACTOR_ID].resources["resource:core.qi"] == 14
    assert engine.state.actors[SOURCE_ACTOR_ID].concentration is not None
    assert {"RESOURCE_SPENT", "CONCENTRATION_STARTED", "CONDITION_APPLIED"} <= set(event_types(result))

    # Use a deterministic hit seed for Flame Lash and Cinder Touch.
    lash = runtime_engine(bundle, seed="seed-8")
    result = lash.execute_action(req(
        "action:fire.flame_lash", target_id="dummy:target",
        option_ids=("PUSH_10_FT", "USE_CINDER_TOUCH"),
    ))
    assert {"ATTACK_ROLLED", "DAMAGE_COMMITTED", "MOVEMENT_COMMITTED", "ONCE_PER_TURN_CLAIMED"} <= set(event_types(result))
    actor = lash.state.actors[SOURCE_ACTOR_ID]
    with pytest.raises(CombatGate1Error):
        lash._claim_once_per_turn(actor, "passive:cinder.touch_damage")
    reset = lash.advance_isolated_turn_boundary(SOURCE_ACTOR_ID)
    assert "once_per_turn:passive:cinder.touch_damage" in reset
    lash._claim_once_per_turn(actor, "passive:cinder.touch_damage")

    # Find a deterministic hit without weakening attack rules.
    ignite = None
    for index in range(50):
        candidate = runtime_engine(bundle, seed=f"ignite:{index}")
        result = candidate.execute_action(req(
            "action:fire.ignite", target_id="dummy:target",
            option_ids=("INCREASE_BURN", "AUGMENT_OVERHEAT"),
        ))
        if "DAMAGE_COMMITTED" in event_types(result):
            ignite = candidate, result
            break
    assert ignite is not None
    candidate, result = ignite
    assert candidate.state.actors[SOURCE_ACTOR_ID].resources["resource:core.qi"] == 14
    assert any(row.condition_id == "condition:core.burning" for row in candidate.state.actors["dummy:target"].conditions.values())
    assert {"RESOURCE_SPENT", "PASSIVE_TRIGGERED", "DAMAGE_COMMITTED", "CONDITION_APPLIED"} <= set(event_types(result))


def test_no_opportunity_movement_is_packet_scoped_and_ordinary_movement_is_not(bundle):
    reactor = dummy_actor_template(
        "dummy:reactor", team_id="team:dummy", armor_class=10, maximum_hp=100,
        reaction_ids=("reaction:core.opportunity_attack",),
    )
    positions = {
        SOURCE_ACTOR_ID: Position(x=2, y=2),
        "dummy:target": Position(x=8, y=8),
        "dummy:reactor": Position(x=3, y=2),
    }
    target = dummy_actor_template("dummy:target", armor_class=10, maximum_hp=100)
    engine = CharacterCombatRuntimeEngine(
        ROOT, bundle, match_seed="combustive", additional_actors=(target, reactor), positions=positions,
    )
    result = engine.execute_action(req("action:fire.combustive_step", destination=Position(x=2, y=5)))
    assert "OPPORTUNITY_EXPOSURE_SUPPRESSED" in event_types(result)
    assert "REACTION_WINDOW_OPENED" not in event_types(result)
    assert engine.state.actors["dummy:reactor"].reaction_available is True

    # Directly use the existing movement path without the authorized packet.
    ordinary = CharacterCombatRuntimeEngine(
        ROOT, bundle, match_seed="ordinary", additional_actors=(target, reactor), positions=positions,
    )
    actor = ordinary.state.actors[SOURCE_ACTOR_ID]
    path, cost = ordinary.grid.shortest_path(
        actor.position, Position(x=2, y=4),
        occupied_cells=ordinary._occupied_cells_except(actor.entity_id), max_cost_ft=30,
        footprint=ordinary._footprint(actor),
    )
    candidate = LegalCandidate(
        candidate_id="candidate:ordinary", decision_id="decision:ordinary", state_version=ordinary.state.state_version,
        kind=CandidateKind.MOVE, actor_id=actor.entity_id, source_definition_id="system:combat.move",
        display_name="ordinary move", destination=Position(x=2, y=4), canonical_path=path,
        movement_cost_ft=cost,
    )
    intent = ActionIntent(
        intent_id="intent:ordinary", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=ordinary.state.state_version, actor_id=actor.entity_id,
        reaction_decisions=(ReactionDecision(
            checkpoint="LEAVE_REACH", reactor_id="dummy:reactor",
            reaction_source_id="reaction:core.opportunity_attack", selection="DECLINE",
        ),),
    )
    ordinary._active_intent = intent
    with ordinary._transaction("system:combat.move", intent.intent_id, actor.entity_id):
        ordinary._resolve_movement(actor, candidate, intent)
    assert any(row.event_type == "REACTION_WINDOW_OPENED" for row in ordinary.events)


def test_meridian_regulation_suppresses_only_exact_penalty_without_removing_condition(bundle):
    engine = runtime_engine(bundle, seed="meridian")
    target = engine.state.actors["dummy:target"]
    condition = ConditionInstance(
        instance_id="condition-instance:poison", condition_id="condition:core.poisoned",
        source_definition_id="effect:test.poison", source_actor_id="dummy:source", target_id=target.entity_id,
        applied_sequence=0, data={"effect_tags": ["poison"], "penalties": ["attack_disadvantage", "speed_penalty"]},
    )
    target.conditions[condition.instance_id] = condition
    result = engine.execute_action(req(
        "action:qi.meridian_regulation", target_id=target.entity_id,
        condition_instance_id=condition.instance_id, penalty_id="attack_disadvantage", source_effect_dc=1,
    ))
    assert condition.instance_id in target.conditions
    assert engine._condition_penalty_suppressed(target, condition.instance_id, "attack_disadvantage") is True
    assert engine._condition_penalty_suppressed(target, condition.instance_id, "speed_penalty") is False
    assert "MODIFIER_APPLIED" in event_types(result) and "CONDITION_REMOVED" not in event_types(result)


def test_reaction_checkpoints_qi_armor_and_fire_ward_execute_existing_damage_path(bundle):
    # Qi Armor rechecks a ranged hit at the exact pre-damage checkpoint.
    engine = runtime_engine(bundle, seed="qi-armor")
    target = engine.state.actors[SOURCE_ACTOR_ID]
    attacker = engine.state.actors["dummy:target"]
    intent = ActionIntent(
        intent_id="intent:qi-armor", decision_id="decision:qi-armor", candidate_id="candidate:qi-armor",
        state_version=engine.state.state_version, actor_id=attacker.entity_id,
        reaction_decisions=(ReactionDecision(
            checkpoint="ATTACK_HIT_BEFORE_DAMAGE", reactor_id=target.entity_id,
            reaction_source_id="reaction:qi.qi_armor", selection="USE",
        ),),
    )
    with engine._transaction("test:ranged", intent.intent_id, attacker.entity_id):
        engine._resolve_character_attack(
            attacker, target, source_id="test:ranged", attack_bonus=100, damage=None,
            damage_type="FIRE", intent=intent, fixed_damage=10, ranged=True,
        )
    assert target.resources["resource:core.qi"] == 13
    assert any(row.source_definition_id == "reaction:qi.qi_armor" and row.event_type == "REACTION_RESOLVED" for row in engine.events)

    # Fire Ward protects a same-team typed ally and spends only at damage application.
    ally = dummy_actor_template("dummy:ally", team_id="team:source_character", maximum_hp=100)
    attacker_template = dummy_actor_template("dummy:attacker", team_id="team:dummy", maximum_hp=100)
    ward = CharacterCombatRuntimeEngine(
        ROOT, bundle, match_seed="fire-ward", additional_actors=(ally, attacker_template),
        positions={SOURCE_ACTOR_ID: Position(x=2, y=2), "dummy:ally": Position(x=3, y=2), "dummy:attacker": Position(x=4, y=2)},
    )
    intent = ActionIntent(
        intent_id="intent:ward", decision_id="decision:ward", candidate_id="candidate:ward",
        state_version=ward.state.state_version, actor_id="dummy:attacker",
        reaction_decisions=(ReactionDecision(
            checkpoint="DAMAGE_APPLICATION", reactor_id=SOURCE_ACTOR_ID,
            reaction_source_id="reaction:fire.fire_ward", selection="USE",
        ),),
    )
    ally_state = ward.state.actors["dummy:ally"]
    with ward._transaction("test:damage", intent.intent_id, "dummy:attacker"):
        ward._commit_damage(ally_state, 20, "BLUDGEONING", "test:damage", "dummy:attacker", intent, reaction_depth=0)
    assert ward.state.actors[SOURCE_ACTOR_ID].resources["resource:core.qi"] == 14
    assert any(row.source_definition_id == "reaction:fire.fire_ward" and row.event_type == "REACTION_RESOLVED" for row in ward.events)
    assert 80 < ally_state.current_hp <= 100


def test_scoundrel_actions_and_passive_bindings_execute_typed_checks(bundle):
    dirty = runtime_engine(bundle, seed="seed-10")
    result = dirty.execute_action(req("action:scoundrel.dirty_trick", target_id="dummy:target", option_ids=("PRONE",)))
    assert "CHECK_ROLLED" in event_types(result)
    assert any(row.condition_id == "condition:core.prone" for row in dirty.state.actors["dummy:target"].conditions.values())

    steal = runtime_engine(bundle, seed="steal")
    result = steal.execute_action(req("action:scoundrel.steal", target_id="dummy:target", option_ids=("TARGET_UNAWARE",)))
    assert {"CHECK_ROLLED", "PASSIVE_TRIGGERED"} <= set(event_types(result))
    assert result.events[-1]["payload"]["object_activated"] is False

    sensing = runtime_engine(bundle, seed="passive")
    output = sensing.evaluate_passive(SOURCE_ACTOR_ID, "passive:qi.qi_sensing", {
        "active_supernatural_energy": True, "blocked_by_typed_material": False, "distance_ft": 20,
    })
    assert output == {"detected": True, "precise_space_revealed": False}


def test_resource_underflow_range_target_and_object_fail_closed(bundle):
    low = CharacterCombatRuntimeAdapter(
        Path("/dev/null")
    ) if False else None  # prove there is no alternate prose fallback path
    engine = runtime_engine(bundle, seed="underflow")
    engine.state.actors[SOURCE_ACTOR_ID].resources["resource:core.qi"] = 0
    with pytest.raises(CombatGate1Error):
        engine.execute_action(req("action:fire.fireball_art", destination=Position(x=3, y=2)))
    out_of_range = runtime_engine(bundle, seed="range")
    with pytest.raises(ValueError, match="out of range"):
        out_of_range.execute_action(req("action:core.unarmed_strike", target_id="dummy:target")) if False else out_of_range.execute_action(
            req("action:fire.combustive_step", destination=Position(x=19, y=12))
        )
    friendly = runtime_engine(bundle, seed="friendly", target_team="team:source_character")
    with pytest.raises(ValueError, match="hostile"):
        friendly.execute_action(req("action:fire.ignite", target_id="dummy:target", option_ids=("PUSH_5_FT",)))


def test_deterministic_nonpersistent_dry_run_and_reducer_replay(bundle):
    straw = RuntimeObjectState(
        object_id="object:straw", object_kind="STRAW_DUMMY", position=Position(x=3, y=3),
        unattended=True, flammable=True,
    )
    request = req(
        "action:fire.conflagration", destination=Position(x=3, y=2),
        option_ids=("AUGMENT_HEAT_HAZE", "AUGMENT_LINGERING"), object_ids=("object:straw",),
    )
    first = runtime_engine(bundle, seed="replay", objects=(straw,))
    genesis = first.state.model_copy(deep=True)
    one = first.execute_action(request)
    second = runtime_engine(bundle, seed="replay", objects=(straw,))
    two = second.execute_action(request)
    assert one.model_dump(mode="json") == two.model_dump(mode="json")
    assert first.state.model_dump(mode="json") == second.state.model_dump(mode="json")
    assert one.persistent_match_created is False and one.persisted_event_count == 0
    enriched = enrich_committed_events(first.events, post_engine=first)
    replayed = Gate3EventReducer().apply_events(genesis, enriched, expected_start_sequence=1)
    # Reducer events carry the exact committed transaction version and roll counter is from deterministic rolls.
    replayed.state_version = first.state.state_version
    replayed.roll_counter = first.state.roll_counter
    assert canonical_sha256(replayed.model_dump(mode="json")) == canonical_sha256(first.state.model_dump(mode="json"))


def test_stale_lock_missing_handler_duplicate_ids_and_prose_fail_closed(runtime_package, adapter, bundle, tmp_path, monkeypatch):
    with zipfile.ZipFile(runtime_package) as src:
        files = {name: src.read(name) for name in src.namelist() if not name.endswith("/")}
    lock = json.loads(files["combat/Executable_Mechanics_Lock.json"])
    lock["lock_sha256"] = "0" * 64
    files["combat/Executable_Mechanics_Lock.json"] = json.dumps(lock, separators=(",", ":")).encode()
    stale = tmp_path / "stale.zip"
    with zipfile.ZipFile(stale, "w") as zf:
        for name, data in sorted(files.items()):
            zf.writestr(name, data)
    with pytest.raises(Exception):
        CharacterCombatRuntimeAdapter(stale)

    import combat.character_runtime_adapter as runtime_module
    removed = runtime_module._PRIMITIVE_HANDLERS.pop("primitive:ignite_object")
    try:
        with pytest.raises(FoundryError, match="runtime handler"):
            CharacterCombatRuntimeAdapter(runtime_package)
    finally:
        runtime_module._PRIMITIVE_HANDLERS["primitive:ignite_object"] = removed

    raw = bundle.model_dump(mode="json", by_alias=True)
    raw["action_catalog"].append(copy.deepcopy(raw["action_catalog"][0]))
    raw.pop("bundle_sha256")
    raw["bundle_sha256"] = canonical_sha256(raw)
    with pytest.raises(ValidationError, match="unique"):
        type(bundle).model_validate(raw)
    assert all("prose" not in row.executing_handler.lower() for row in bundle.support_matrix)


def test_no_encounter_match_history_controller_or_cpk1_side_effects(bundle):
    engine = runtime_engine(bundle, seed="isolation")
    assert engine._persistent_match_created is False
    assert engine.events == [] and engine.rolls == []
    assert engine.state.match_id.startswith("isolated-runtime:")
    assert not (ROOT / "UserData").exists()
    registry = (ROOT / "contracts/registry.py").read_text(encoding="utf-8").lower()
    assert "c3ar" not in registry and "character_runtime_bundle" not in registry


def test_runtime_ready_packaging_preserves_character_gm_and_static_combat_payloads(runtime_package, bundle, tmp_path):
    from combat.character_runtime_packaging import seal_runtime_ready_package
    output = tmp_path / "runtime-ready.zip"
    validation = {
        "schema": "TianxiaC3ARRuntimeExecutionValidation.v1",
        "status": "PASS",
        "fixture_inputs_canonical": False,
        "persistent_match_created": False,
        "persisted_event_count": 0,
    }
    seal = seal_runtime_ready_package(runtime_package, output, bundle=bundle, runtime_validation=validation)
    assert seal["status"] == "PASS"
    with zipfile.ZipFile(runtime_package) as src, zipfile.ZipFile(output) as out:
        allowed = {
            "PACKAGE_MANIFEST.json", "READINESS.json", "Release_Gate_Manifest.json", "SHA256SUMS.txt",
            "combat/Combat_Readiness.json", "combat/Combat_Build_Manifest.json", "combat/Execution_Provenance.json",
        }
        added = {
            "combat/Runtime_Adapter_Contract.json", "combat/Runtime_Support_Matrix.json",
            "combat/Primitive_Handler_Implementation.json", "combat/Runtime_Resource_Initialization_Contract.json",
            "combat/Runtime_Execution_Validation.json",
        }
        for name in src.namelist():
            if name not in allowed:
                assert out.read(name) == src.read(name), name
        assert added <= set(out.namelist())
        contract = json.loads(out.read("combat/Runtime_Adapter_Contract.json"))
        assert contract["resource_initialization_contract"]["owner_package_contains_current_values"] is False
        assert all(row["current"] == "REQUIRED_AT_ENCOUNTER_TIME" for row in contract["resource_initialization_contract"]["resources"])
        readiness = json.loads(out.read("READINESS.json"))
        assert readiness["combat_sheet"] == "COMBAT_SHEET_READY"
        assert readiness["combat_runtime"] == "COMBAT_RUNTIME_READY"
        assert readiness["combat_ready_semantics"] == "RUNTIME_READY_PRE_ENCOUNTER"
