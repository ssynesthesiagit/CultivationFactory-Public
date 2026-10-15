"""Phoenix source-family regression checks; no live providers or browser.

Engine cases isolate rule ordering. The table/journey case commits native
Method access, AP advancement and Rare Inheritance acquisition, collects the
authenticated five-row progression, then uses ordinary compiled attacks,
committed resource gains and a fresh service/replay load. Combat scalar stats
remain fixture inputs; no ownership or trigger receipts are invented.
"""
import json
import zipfile

import pytest

from combat import typed_executor as te
from combat.ext.states import context
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, ActionIntent
from tests.test_riders_c7 import (
    PHOENIX, EMBERS, ME, FOE, STAMINA, _phoenix, _poison_save,
    hostile_packet, answers, turn, bundle, fight, use, unarmed, sheet,
)


def earn(engine, actor, count):
    """Use actual committed hostile packets, never resource-gain injection."""
    for _ in range(count):
        hostile_packet(engine, actor.entity_id, int(actor.proficiency_bonus), "SLASHING", attacker_id=FOE)
        engine.state.round_number += 1


def save_effect(engine, *, dc=0, on_success=(), on_fail=(), ability="con", categories=(), also_source=False):
    foe, owner = engine.state.actors[FOE], engine.state.actors[ME]
    action = ActionDefinition(source_definition_id="test:phoenix-save", display_name="Testing shock",
                              owner_id=FOE, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    candidate = next(iter(engine.legal_candidates()))
    intent = ActionIntent(intent_id=f"test-{len(engine.events)}", actor_id=FOE, decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version, target_ids=(ME,))
    typed = {"source": action.source_definition_id, "numbers": {"save_dc": dc}}
    if also_source:
        typed["area"] = {"shape": "sphere", "size_ft": 20, "include_self": True, "harmful_recipient_override": "all"}
    ctx = te.Context(engine, foe, action, intent, typed, [owner, foe] if also_source else [owner], None if also_source else owner)
    engine._active_intent = intent
    try:
        te.run_effects(ctx, [{"type": "save", "ability": ability, "save_categories": list(categories),
                             "on_success": list(on_success), "on_fail": list(on_fail)}])
    finally:
        engine._active_intent = None


def test_failed_save_generates_only_after_its_new_condition_is_applied():
    engine, owner, foe = _phoenix(["cinder_blood"])
    save_effect(engine, dc=100, on_fail=[{"type": "condition", "condition": "poisoned", "applies_to": "target"}])
    assert owner.resources[EMBERS] == 1
    events = engine.events
    applied = next(e.sequence for e in events if e.event_type == "CONDITION_APPLIED" and e.source_definition_id == "test:phoenix-save")
    gained = next(e.sequence for e in events if e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == EMBERS)
    assert applied < gained
    assert owner.turn_flags["_round_phoenix_qualifying_event"] >= applied


def test_existing_condition_does_not_stand_in_for_new_failed_save_condition():
    engine, owner, foe = _phoenix(["cinder_blood"])
    engine._apply_condition(owner, "condition:typed.poisoned", "test:old", FOE, expires_on="UNTIL_REMOVED")
    # A failure branch names Poisoned but does not apply it to this subject.
    save_effect(engine, dc=100, on_fail=[{"type": "condition", "condition": "poisoned", "applies_to": "self"}])
    assert owner.resources[EMBERS] == 0


def test_ash_success_movement_waits_until_success_damage_has_resolved():
    engine, owner, foe = _phoenix(["cinder_blood", "ash_shedding_reversal"], picks={"ash_shedding_step": ["cell:2,6"]})
    earn(engine, owner, 2)
    # Fixed failed first die and successful reroll through the normal rewrite.
    from tests.h1_support import script
    script(engine, [1, 20, *([8] * 40)])
    start = len(engine.events)
    save_effect(engine, dc=12, on_success=[{"type": "damage", "flat": 3, "damage_types": ["force"], "applies_to": "target"}])
    events = engine.events[start:]
    assert any(e.event_type == "D20_REWRITTEN" for e in events)
    damage = next(e.sequence for e in events if e.event_type == "DAMAGE_COMMITTED")
    movement = next(e.sequence for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME)
    assert damage < movement
    assert owner.resources[EMBERS] == 0


def test_ash_does_not_move_when_the_success_result_still_incapacitates():
    engine, owner, foe = _phoenix(["cinder_blood", "ash_shedding_reversal"])
    earn(engine, owner, 2)
    from tests.h1_support import script
    script(engine, [1, 20, *([8] * 40)])
    start = len(engine.events)
    save_effect(engine, dc=12, on_success=[{"type": "condition", "condition": "incapacitated", "applies_to": "target"}])
    assert any(e.event_type == "D20_REWRITTEN" for e in engine.events[start:])
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME for e in engine.events[start:])


def test_ash_movement_waits_for_every_recipient_of_the_same_save_effect():
    engine, owner, foe = _phoenix(["cinder_blood", "ash_shedding_reversal"], picks={"ash_shedding_step": ["cell:2,6"]})
    earn(engine, owner, 2)
    from tests.h1_support import script
    script(engine, [1, 20, *([8] * 40)])
    start = len(engine.events)
    damage = {"type": "damage", "flat": 3, "damage_types": ["force"], "applies_to": "target"}
    save_effect(engine, dc=12, on_success=[damage], on_fail=[damage], also_source=True)
    events = engine.events[start:]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert {t for e in packets for t in e.target_ids} == {ME, FOE}
    moved = next(e.sequence for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME)
    assert max(e.sequence for e in packets) < moved


def test_flame_wing_critical_hit_keeps_two_bonus_dice_and_consumes_one_charge():
    from tests.test_riders_c7 import end_turns_until
    from tests.h1_support import script
    engine, owner, foe = _phoenix(["cinder_blood", "flame_wing_rush"], picks={"flame_wing_move": None})
    earn(engine, owner, 1)
    end_turns_until(engine, ME)
    charge = next(c for c in owner.conditions.values() if c.condition_id == "condition:typed.flame_wing_charge")
    assert charge.data["source_cl"] == 18
    script(engine, [20, *([8] * 100)])
    start = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    rolls = engine.rolls[start:]
    assert any(r.expression.startswith("2d8") for r in rolls)
    assert not any(r.expression.startswith("4d8") for r in rolls)
    assert not any(c.condition_id == "condition:typed.flame_wing_charge" for c in owner.conditions.values())


def test_character_without_phoenix_keeps_its_original_bundle_profile():
    compiled = bundle([])
    assert "phoenix_body_cl" not in compiled and "phoenix_body_profile" not in compiled
    assert EMBERS not in compiled["actor_template"].get("resources", {})


@pytest.mark.parametrize("category", ["death_save", "training", "breakthrough", "hidden_injury_repair", "cannot_reroll"])
def test_ash_absolute_exclusions_do_not_spend(category):
    engine, owner, foe = _phoenix(["cinder_blood", "ash_shedding_reversal", "furnace_without_fuel"])
    earn(engine, owner, 3)
    start = len(engine.events)
    save_effect(engine, dc=100, categories=[category], on_fail=[{"type": "condition", "condition": "petrified", "applies_to": "target"}])
    assert owner.resources[EMBERS] == 3
    assert not any(e.event_type == "D20_REWRITTEN" for e in engine.events[start:])


def test_furnace_records_pre_immunity_damage_and_shares_the_round_limit():
    engine, owner, foe = _phoenix(["cinder_blood", "furnace_without_fuel"])
    hp = owner.current_hp
    hostile_packet(engine, ME, int(owner.proficiency_bonus) - 1, "FIRE", attacker_id=FOE)
    assert owner.current_hp == hp and owner.resources[EMBERS] == 0
    hostile_packet(engine, ME, int(owner.proficiency_bonus), "FIRE", attacker_id=FOE)
    assert owner.current_hp == hp and owner.resources[EMBERS] == 1
    hostile_packet(engine, ME, 20, "SLASHING", attacker_id=FOE)
    assert owner.resources[EMBERS] == 1


def test_furnace_still_observes_fire_when_immunity_is_bypassed_and_temp_hp_takes_it(monkeypatch):
    from combat import ext
    ext.effects()
    def bypass(engine, kind, typed, source_actor_id, target):
        return str(kind).upper() == "FIRE"
    monkeypatch.setitem(ext._HOOKS, "immunity_as_resistance", [*ext._HOOKS.get("immunity_as_resistance", ()), bypass])
    engine, owner, foe = _phoenix(["cinder_blood", "furnace_without_fuel"])
    owner.temporary_hp = 100
    hp = owner.current_hp
    hostile_packet(engine, ME, int(owner.proficiency_bonus), "FIRE", attacker_id=FOE)
    assert owner.current_hp == hp
    assert owner.resources[EMBERS] == 1


@pytest.mark.parametrize("controller", [ME, FOE])
def test_controlled_creature_does_not_farm_embers_after_team_change(controller):
    engine, owner, foe = _phoenix(["cinder_blood", "furnace_without_fuel"])
    foe.summon = {"owner": controller, "group": "test:controlled"}
    hostile_packet(engine, ME, 20, "FIRE", attacker_id=FOE)
    hostile_packet(engine, ME, 20, "SLASHING", attacker_id=FOE)
    assert owner.resources[EMBERS] == 0


def test_rebirth_does_not_replace_instant_death_or_spend_costs():
    engine, owner, foe = _phoenix(["cinder_blood", "rebirth_from_cinders"])
    earn(engine, owner, 3)
    owner.current_hp = 1
    before = owner.resources[STAMINA]
    hostile_packet(engine, ME, owner.maximum_hp + 1, "SLASHING", attacker_id=FOE)
    assert owner.current_hp == 0 and owner.resources[STAMINA] == before
    assert owner.resources[EMBERS] == 0  # The defeat also ends the scene, expiring its pool.


def test_rebirth_sets_half_hp_before_its_secondary_effects_and_is_not_healing():
    engine, owner, foe = _phoenix(["cinder_blood", "rebirth_from_cinders"], picks={"rebirth_move": None})
    earn(engine, owner, 3)
    owner.current_hp = 5
    start = len(engine.events)
    hostile_packet(engine, ME, 20, "SLASHING", attacker_id=FOE)
    events = engine.events[start:]
    assert owner.current_hp == owner.maximum_hp // 2
    replacement = next(e.sequence for e in events if e.event_type == "HIT_POINTS_REPLACED")
    burst = next(e.sequence for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME)
    assert replacement < burst
    assert not any(e.event_type == "HEALING_APPLIED" and e.source_definition_id == PHOENIX + "rebirth_from_cinders" for e in events)


def test_explicit_body_level_does_not_inherit_total_character_level():
    doc = sheet([PHOENIX + k for k in ["cinder_blood", "flame_wing_rush", "furnace_without_fuel", "rebirth_from_cinders"]], cl=20)
    doc["path_and_subpath"]["paths"] = [{"path_id": "tianxia.path.body_refining", "effective_cl": 3}]
    compiled = compile_character(doc, actor_id=ME)
    assert compiled["phoenix_body_cl"] == 3
    features = {r["feature_id"] for r in compiled["typed_passives"] + compiled["typed_reactions"]}
    assert PHOENIX + "cinder_blood" in features
    assert not any(PHOENIX + name in features for name in ["flame_wing_rush", "furnace_without_fuel", "rebirth_from_cinders"])


def acquired_phoenix_features(catalog_environment):
    """Real committed access/AP acquisition, not an invented ownership receipt.

    The public NonSphereAuthority service owns the issuance, allocation and
    restricted selection; its authenticated progression supplies combat IDs.
    """
    from character_builder import CharacterBuilderService
    from non_sphere_authority import NonSphereAuthorityService
    db = catalog_environment["db"]
    body, parent = "tianxia.path.body_refining", PHOENIX.removesuffix(".feature.")
    created = CharacterBuilderService(db).create_project(
        working_name="Phoenix native acquisition", concept="Committed Rare Inheritance progression to Body CL18.",
        target_cl=18, power_band="standard", source_reference=None, creation_mode="detailed", ability_scores={},
        selections={"path_choice": [body]})
    pid = created["project_id"]
    service = NonSphereAuthorityService(db)
    access = service.commit_authority_event(pid, "method_access", {"method_id": "METHOD-002"}, idempotency_key="phoenix-method-access")
    service.set_primary_method(pid, "METHOD-002", access_source_records=[access["evidence_id"]])
    state = service.get_state(pid)
    initial = next(p["attainment"] for p in state["paths"] if p["path_id"] == body)
    points = 18 - initial
    award = service.commit_authority_event(pid, "ap_award", {"method_id": "METHOD-002", "target_cl": 18},
        amount_awarded=points * service.method_burden_multiplier(service.methods["METHOD-002"]), idempotency_key="phoenix-ap-award")
    service.allocate_advancement(pid, {body: points}, evidence_id=award["evidence_id"], idempotency_key="phoenix-body-18")
    inheritance = service.commit_authority_event(pid, "subpath_access", {"selection_id": parent, "path_id": body}, idempotency_key="phoenix-inheritance")
    service.select_subpath(pid, body, parent, access_source_records=[inheritance["evidence_id"]])
    cold = NonSphereAuthorityService(db)
    selected = next(p for p in cold.get_state(pid)["paths"] if p["path_id"] == body)
    assert selected["attainment"] == 18 and selected["subpath_or_tradition_id"] == parent
    assert selected["subpath_or_tradition_acquisition_provenance"]["recorded"] is True
    record = cold.project_locked_subpath_catalog_record(parent)
    rows = record["compatibility"]["factory"]["stage2_authority"]["feature_progression"]
    ids = [r["canonical_id"] for r in rows if r["granted_at_cl"] <= selected["attainment"]]
    assert set(ids) == {PHOENIX + name for name in ["cinder_blood", "ash_shedding_reversal", "flame_wing_rush", "furnace_without_fuel", "rebirth_from_cinders"]}
    return {"feature_ids": ids, "body_cl": selected["attainment"], "subpath_id": selected["subpath_or_tradition_id"]}


def test_table_actual_hostile_hit_produces_ember_across_cold_reload(tmp_path, monkeypatch, catalog_environment):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet as portable_sheet
    from tests.test_hidden_targeting import turn as table_turn
    from tests.r10_fixup_support import cast_sender, commit
    owner_id, foe_id = "actor:factory.aaaaaaaa", "actor:factory.ffffffff"
    acquired = acquired_phoenix_features(catalog_environment)
    for pid, features in [("aaaaaaaa", acquired["feature_ids"]), ("ffffffff", [])]:
        doc = portable_sheet(features + ["TAL_IRON_FIST_IRON_FIST_TRAINING"], cl=18, score=22, primary="Stamina")
        doc["identity"]["proficiency_bonus"] = 6
        if pid == "aaaaaaaa":
            doc["path_and_subpath"]["paths"] = [{"path_id": "tianxia.path.body_refining", "effective_cl": acquired["body_cl"],
                                                  "subpath_or_tradition_id": acquired["subpath_id"]}]
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Phoenix native yard", "width_squares": 8, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    import combat.journey as journey_module
    monkeypatch.setattr(journey_module.secrets, "token_hex", lambda count: "a" * (2 * count))
    journey = service.create_journey(project_ids=["aaaaaaaa", "ffffffff"], arena_id="battlefield:map.phoenix-native-yard",
        positions={owner_id: {"x": 3, "y": 4}, foe_id: {"x": 4, "y": 4}},
        base_paces={owner_id: 1000, foe_id: 1000}, control_modes={owner_id: "MANUAL", foe_id: "MANUAL"})
    jid = journey["journey_id"]
    mid = service.journey_start_combat(jid, journey["revision"], {owner_id: "team:a", foe_id: "team:b"}, maximum_rounds=6)["match_id"]
    table = TabletopService(service, tmp_path)
    for _ in range(6):
        table_turn(table, mid, foe_id)
        engine = service._load_session(mid).engine
        attack = next(a.display_name for a in engine.action_catalog.values() if a.owner_id == foe_id and a.economy.value == "ACTION"
                      and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed" for e in a.parameters.get("typed", {}).get("effects", [])))
        commit(cast_sender(service, table, mid, attack, target=owner_id), lambda prompt: (None, bool(prompt.get("choice"))))
        cold = CombatService(ROOT, tmp_path)._load_session(mid)
        assert cold.verify()["status"] == cold.mechanical.replay()["status"] == "PASS"
        if cold.engine.state.actors[owner_id].resources[EMBERS]:
            assert cold.engine.state.actors[owner_id].turn_flags["_round_phoenix_qualifying_event"] > 0
            break
        commit(cast_sender(service, table, mid, "End turn"))
    else:
        pytest.fail("Native attacks never produced one qualifying hostile packet")
    for _ in range(20):
        cold = CombatService(ROOT, tmp_path)._load_session(mid)
        if cold.engine.state.terminal_result is not None:
            break
        commit(cast_sender(service, table, mid, "End turn"))
    assert cold.engine.state.terminal_result is not None
    assert cold.engine.state.actors[owner_id].resources[EMBERS] > 0
    journey = service.journey_state(jid)
    resumed = service.journey_resume(jid, journey["revision"], effect_resolutions={
        owner_id: "The encounter's turn-bound effects have ended.", foe_id: "The encounter's turn-bound effects have ended."})
    assert resumed["actors"][owner_id]["resources"][EMBERS] > 0
    before = json.dumps(CombatService(ROOT, tmp_path).journey_state(jid), sort_keys=True)
    with pytest.raises(ValueError):
        service.journey_act(jid, resumed["revision"], foe_id, "phoenix_scene_boundary", {"confirm_scene_ended": 1})
    assert json.dumps(CombatService(ROOT, tmp_path).journey_state(jid), sort_keys=True) == before
    ended = service.journey_act(jid, resumed["revision"], owner_id, "phoenix_scene_boundary", {"confirm_scene_ended": 1})
    assert ended["actors"][owner_id]["resources"][EMBERS] == 0
    assert CombatService(ROOT, tmp_path).journey_state(jid)["actors"][owner_id]["resources"][EMBERS] == 0
