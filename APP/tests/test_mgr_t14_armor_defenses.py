"""Actual native damage, critical, collision and maintenance transactions."""
import pytest

from combat.factory_compiler import compile_character
from combat.tabletop import normalize_map, to_battlefield
from combat.ext.equipment_armor import PADDED_ROUND_FLAG
from tests.test_mgr_t14_fitted_armor import command, fight, sheet, support, ACTOR, LAMELLAR
from tests.test_mgr_t14_armor_consumers import finish

DAMAGE = "action:test.mgr-t14.bludgeoning"
STRIKE = "action:test.mgr-t14.critical-strike"
HELMET_POOL = "resource:equipment.helmet_discipline"


def attacker_turn(combat, table, mid):
    from tests.test_lock2_persistence import act
    while combat._load_session(mid).engine.state.current_actor_id != support.ATTACKER:
        assert act(table, mid, "end")["status"] == "COMMITTED"


def damage_action(bundle):
    if bundle["actor_id"] != support.ATTACKER:
        return
    support._bundle_action(bundle, DAMAGE, "Supernatural Bludgeoning blast", {"typed": {
        "numbers": {}, "mundane": False, "duration": {"kind": "instant"}, "riders": [],
        "effects": [{"type": "damage", "applies_to": "target", "flat": 20, "damage_types": ["bludgeoning"]}]}},
        target_kind="HOSTILE_ENTITY", range_ft=60)
    support._seal(bundle)


@pytest.mark.parametrize("case", ["use", "decline", "untrained", "unowned", "ai", "own_turn"])
def test_padded_ordinary_optional_proficient_damage_and_round_use(tmp_path, case):
    doc = sheet([] if case == "unowned" else ["padded_layers"], proficiency=() if case == "untrained" else ("medium",))
    def prepare(bundle):
        damage_action(bundle)
        if case == "own_turn" and bundle["actor_id"] == ACTOR:
            support._bundle_action(bundle, DAMAGE + ".self", "Bludgeoning recoil", {"typed": {
                "numbers": {}, "riders": [], "duration": {"kind": "instant"}, "effects": [
                    {"type": "damage", "applies_to": "self", "flat": 20, "damage_types": ["bludgeoning"]},
                    {"type": "damage", "applies_to": "self", "flat": 20, "damage_types": ["bludgeoning"]}]}},
                target_kind="SELF", range_ft=None)
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=prepare)
    if case == "ai":
        attacker_turn(combat, table, mid)
        combat.set_controller_mode(mid, actor_id=ACTOR, controller_mode="LOCAL_AUTO")
    source = DAMAGE + ".self" if case == "own_turn" else DAMAGE
    prompts = support._commit(combat, table, mid, source,
        actor=ACTOR if case == "own_turn" else support.ATTACKER,
        answer=lambda p: None if case == "decline" else ["use"])
    engine = support._reload(tmp_path, mid)
    packets = support._packets(engine, source)
    pb = engine.state.actors[ACTOR].proficiency_bonus
    eligible = case not in {"decline", "untrained", "unowned"}
    assert packets[0].payload["hp_damage"] == 20 - pb * int(eligible)
    assert not packets[0].payload.get("source_flags"), "Cultivation bludgeoning is not automatically a collision"
    if case == "own_turn":
        assert packets[1].payload["hp_damage"] == 20
    assert len(prompts) == int(case in {"use", "decline", "own_turn"})
    if prompts:
        assert "Padded Layers" in str(prompts) and engine.state.actors[ACTOR].display_name in str(prompts)
    assert (engine.state.actors[ACTOR].turn_flags.get(PADDED_ROUND_FLAG) == engine.state.round_number) is eligible
    from combat.pending_damage import packet_scratch
    assert packet_scratch(engine) is None


def brute_sheet():
    doc = support._sheet([])
    doc["equipment"] = [{"starting_kit": {"items": []}}]
    doc["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.brute"],
        "automatic_sphere_component_record_ids": ["BRUTE_BASE_BRUTAL_SHOVE"], "learned_talent_record_ids": ["TAL_BRUTE_HAMMER"]}
    for stat in doc["ability_scores_and_statistics"]["abilities"]:
        if stat["ability"] == "STR":
            stat.update(score=30, modifier=10)
    doc["ability_scores_and_statistics"]["skills"] = [{"skill": "Athletics", "bonus": 30}]
    return doc


@pytest.mark.parametrize("obstacle", ["surface", "object", "creature", "diagonal_creature", "boundary"])
def test_padded_collision_provenance_from_real_brutal_shove_and_hammer(tmp_path, obstacle):
    doc = sheet(["padded_layers"])
    extra = []
    arena = to_battlefield(normalize_map({"display_name": "Collision yard", "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "rect", "points": [[5, 6], [6, 7]], "filled": True}] if obstacle == "surface" else [],
        "objects": [{"id": 1, "kind": "wall_section", "x": 5, "y": 6}] if obstacle == "object" else [],
        "starts": {"team1": [[4, 6]], "team2": [[3, 6], [5, 6]]}}))
    if obstacle == "creature":
        extra = [(compile_character(support._sheet([]), actor_id="actor:factory.blocker"), (5, 6))]
    if obstacle == "diagonal_creature":
        extra = [(compile_character(support._sheet([]), actor_id="actor:factory.blocker"), (5, 4))]
    attacker_position, defender_position = ((3, 3), (4, 4)) if obstacle == "diagonal_creature" else (
        ((1, 6), (0, 6)) if obstacle == "boundary" else ((3, 6), (4, 6)))
    combat, table, mid = fight(tmp_path, doc, attacker_sheet=brute_sheet(), attacker_position=attacker_position,
                             defender_position=defender_position, arena=arena, extra=extra)
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == support.ATTACKER and (a.parameters.get("typed") or {}).get("source") == "BRUTE_BASE_BRUTAL_SHOVE")
    def answer(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        return ["use"] if "padded_layers" in prompt["context"]["reaction_source_id"] else ["push"] if "push" in ids else ids[:1]
    prompts = support._commit(combat, table, mid, source, answer=answer, max_steps=20)
    cold = support._reload(tmp_path, mid)
    damage = next(e for e in support._packets(cold, source) if ACTOR in e.target_ids)
    roll = next(r for r in cold.rolls if r.reason == "HAMMER_IMPACT_COLLISION")
    pb = cold.state.actors[ACTOR].proficiency_bonus
    multiplier = 1 if "creature" in obstacle or obstacle == "boundary" else 2
    assert damage.payload["hp_damage"] == max(0, roll.total - multiplier * pb)
    expected_flag = "collision_with_creature" if "creature" in obstacle else "collision_unclassified" if obstacle == "boundary" else "collision_with_object_or_surface"
    assert damage.payload["source_flags"] == [expected_flag]
    assert cold.state.actors[ACTOR].position.x == defender_position[0]
    assert cold.state.actors[ACTOR].turn_flags[PADDED_ROUND_FLAG] == cold.state.round_number
    assert any("Padded Layers" in str(p) for p in prompts)
    assert getattr(cold, "_physical_collision", None) is None


def critical_action(bundle):
    if bundle["actor_id"] != support.ATTACKER:
        return
    # Fixture attacker has a sealed broad critical range; the actual seeded d20,
    # critical cancellation and native damage dice still execute and replay.
    bundle["typed_passives"].append({"feature_id": "test:wide-critical-range", "block": "critical_range", "lowest": 2})
    support._bundle_action(bundle, STRIKE, "Critical test strike", {"typed": {
        "numbers": {"attack_bonus": 100}, "effects": [{"type": "attack", "attack_kind": "weapon", "on_hit": [
            {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["slashing"]}]}],
        "riders": [], "duration": {"kind": "instant"}}}, target_kind="HOSTILE_ENTITY", range_ft=60)
    support._seal(bundle)


def strike(combat, table, mid, *, use=True):
    for _ in range(4):
        before = len(combat._load_session(mid).engine.events)
        prompts = support._commit(combat, table, mid, STRIKE, answer=lambda p: ["protected"] if use else None)
        engine = support._reload(table.userdata_root if hasattr(table, "userdata_root") else combat.userdata_root, mid)
        rolled = [e for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == STRIKE]
        if rolled:
            return prompts, engine, rolled[-1]
    raise AssertionError("The seeded native attacker missed four consecutive attempts")


def helmet_sheet(*, trained=True, protected=True):
    doc = sheet(["helmet_discipline", "sleep_in_armor"], proficiency=("medium",) if trained else ())
    if protected:
        doc["equipment"][0]["head_protection"] = {"armor_key": LAMELLAR, "kind": "helmet"}
    return doc


def test_helmet_long_rest_receipt_across_fights_and_cold_reload(tmp_path):
    doc = helmet_sheet()
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    prompts, used, rolled = strike(combat, table, mid)
    assert len(prompts) == 1 and not rolled.payload["critical"] and len(rolled.payload["dice"]) == 1
    assert used.state.actors[ACTOR].resources[HELMET_POOL] == 0
    with pytest.raises(ValueError, match="active fight"):
        fight(tmp_path, doc, prepare=critical_action)
    finish(combat, table, mid)
    combat, table, mid2 = fight(tmp_path, doc, prepare=critical_action)
    prompts, spent, rolled = strike(combat, table, mid2)
    assert not prompts and rolled.payload["critical"] and len(rolled.payload["dice"]) == 2
    assert spent.state.actors[ACTOR].resources[HELMET_POOL] == 0
    with pytest.raises(ValueError, match="active fight"):
        command(tmp_path, doc, "rest.start", kind="long_rest")
    finish(combat, table, mid2)
    command(tmp_path, doc, "rest.start", kind="short_rest")
    command(tmp_path, doc, "time.advance", seconds=3600, observation="light")
    combat, table, mid3 = fight(tmp_path, doc, prepare=critical_action)
    assert combat._load_session(mid3).engine.state.actors[ACTOR].resources[HELMET_POOL] == 0
    finish(combat, table, mid3)
    command(tmp_path, doc, "rest.start", kind="long_rest")
    command(tmp_path, doc, "time.advance", seconds=28800, observation="sleep")
    combat, table, mid4 = fight(tmp_path, doc, prepare=critical_action)
    prompts, refreshed, rolled = strike(combat, table, mid4)
    assert len(prompts) == 1 and not rolled.payload["critical"]
    assert refreshed.state.actors[ACTOR].resources[HELMET_POOL] == 0


@pytest.mark.parametrize("case", ["untrained", "unprotected", "decline", "ai"])
def test_helmet_source_eligibility_and_optional_use(tmp_path, case):
    doc = helmet_sheet(trained=case != "untrained", protected=case != "unprotected")
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    if case == "ai":
        attacker_turn(combat, table, mid)
        combat.set_controller_mode(mid, actor_id=ACTOR, controller_mode="LOCAL_AUTO")
    prompts, engine, rolled = strike(combat, table, mid, use=case != "decline")
    used = case == "ai"
    assert rolled.payload["critical"] is (not used)
    assert engine.state.actors[ACTOR].resources[HELMET_POOL] == int(not used)
    assert len(prompts) == int(case == "decline")


@pytest.mark.parametrize("purpose", ["clean", "oil", "relace", "patch", "seal", "dry", "safely remove"])
def test_field_maintenance_actual_qualified_check(tmp_path, purpose):
    doc = sheet(["field_maintenance"])
    doc["equipment"][0]["armor_checks"] = [{"request_id": "task", "purpose": purpose,
        "item_key": LAMELLAR, "ability": "INT", "dc": 15, "economy": "ACTION"}]
    combat, table, mid = fight(tmp_path, doc)
    source = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == ACTOR and a.source_definition_id.endswith("armor_check.task"))
    support._commit(combat, table, mid, source, actor=ACTOR)
    engine = support._reload(tmp_path, mid)
    roll = next(r for r in engine.rolls if r.reason == "CHECK:" + source)
    assert roll.actor_id == ACTOR and roll.mode == "ADVANTAGE" and len(roll.dice) == 2
    receipt = next(e for e in engine.events if e.source_definition_id == source and "item_key" in e.payload)
    assert receipt.payload["purpose"] == purpose and receipt.payload["success"] == int(roll.total >= 15)
    assert not engine.state.actors[ACTOR].action_available


@pytest.mark.parametrize("case", ["unowned", "untrained"])
def test_field_maintenance_is_contextual_not_a_global_advantage(tmp_path, case):
    doc = sheet([] if case == "unowned" else ["field_maintenance"], proficiency=() if case == "untrained" else ("medium",))
    doc["equipment"][0]["armor_checks"] = [{"request_id": "task", "purpose": "clean", "item_key": LAMELLAR,
                                           "ability": "INT", "dc": 15, "economy": "ACTION"}]
    combat, table, mid = fight(tmp_path, doc)
    source = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == ACTOR and a.source_definition_id.endswith("armor_check.task"))
    support._commit(combat, table, mid, source, actor=ACTOR)
    engine = support._reload(tmp_path, mid)
    assert next(r for r in engine.rolls if r.reason == "CHECK:" + source).mode == "NORMAL"


def test_helmet_cannot_recharge_by_resting_a_dead_native_actor(tmp_path):
    doc = helmet_sheet()
    def fatal(bundle):
        damage_action(bundle)
        if bundle["actor_id"] == support.ATTACKER:
            next(a for a in bundle["action_catalog"] if a["source_definition_id"] == DAMAGE)["parameters"]["typed"]["effects"][0]["flat"] = 1000
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=fatal)
    support._commit(combat, table, mid, DAMAGE)
    finish(combat, table, mid)
    assert support._reload(tmp_path, mid).state.actors[ACTOR].current_hp == 0
    from services.factory_dm_v0.gameplay.models import EngineError
    with pytest.raises(EngineError, match="ACTOR_CANNOT_ACT"):
        command(tmp_path, doc, "rest.start", kind="long_rest")
