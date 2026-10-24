"""Rider lane C7 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones
left"): Body Refining Subpath features whose printed lines were GM riders. Every test compiles a real character owning the
feature and runs the engine (or the table); each fails on the typing the authority carried before this lane.

Typed overrides: authority/typed_mechanics/reviewed_final.d/riders_c7.json (and in-place edits of the entries other lanes own);
feature blocks: combat/rules/feature_blocks.d/riders_c7.json; plug-ins: see each group's comment.
"""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path

import pytest

from tests.h1_support import script

import combat.factory_compiler as factory_compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop import normalize_map, to_battlefield

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("C7_OLD_AUTHORITY"):  # proof runs only: compile against the authority before this lane
    factory_compiler.TYPED_AUTHORITY = Path(os.environ["C7_OLD_AUTHORITY"])
ME = "actor:factory.c7"
FOE = "actor:factory.c7foe"
IRON_FIST = {"sphere_record_ids": ["tianxia.sphere.iron_fist"], "automatic_sphere_component_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]}
STAMINA = "resource:core.stamina"
THUNDER = "resource:named.thunder_charge"
ADAMANT = "tianxia.subpath.body.adamant_thunderbolt_body.feature."


# ------------------------------------------------------------------------------------------------------------ harness
@lru_cache(maxsize=2)
def _authority(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def mechanics():
    return _authority(str(factory_compiler.TYPED_AUTHORITY))


def sheet(ids=(), *, cl=18, dc=50, mods=None, items=(), spheres=None, stamina=60, name="C7 Cultivator"):
    scores = {a: 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    scores.update(mods or {})
    return {
        "identity": {"display_name": name, "proficiency_bonus": 6 if cl >= 17 else 5 if cl >= 13 else 4 if cl >= 9 else 3 if cl >= 5 else 2,
                     "cultivation_level": cl, "path": "Body Refining", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * v, "modifier": v} for a, v in scores.items()],
            "primary_resource": {"name": "Stamina", "maximum": stamina}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 120}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "path_and_subpath": {"path_feature_record_ids": list(ids)},
        "spheres_and_talents": copy.deepcopy(spheres if spheres is not None else IRON_FIST),
        "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
    }


def bundle(ids=(), actor_id=ME, **kw):
    return compile_character(sheet(ids, **kw), actor_id=actor_id)


def fight(me, *, foe=None, me_at=(3, 6), foe_at=(4, 6), objects=(), seed="C7", width=20, height=14):
    """A Gate4 engine on a width x height yard: ``me`` (a bundle) against the native foe or a typed ``foe`` bundle."""
    from combat.gate2_runtime_content import AN

    foe_id = foe["actor_id"] if foe else AN
    document = normalize_map({"display_name": "C7 yard", "width_squares": width, "height_squares": height, "objects": list(objects),
                              "starts": {"team1": [list(me_at)], "team2": [list(foe_at)]}})
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(me, *([foe] if foe else [])), battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": [ME, foe_id], "team_by_actor": {ME: "team:a", foe_id: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, foe_id: {"x": foe_at[0], "y": foe_at[1]}}})
    turn(engine, ME)
    other = engine.state.actors[foe_id]
    other.maximum_hp = other.current_hp = 1000
    return engine


def foe_id(engine):
    return next(a for a in engine.state.actors if a != ME)


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def legal(engine):
    return {c.display_name.split(" — Hits allies too:")[0].split(" at ")[0] for c in engine.legal_candidates()}


def use(engine, name, *, target=None, at=None, actor_id=ME):
    matches = [c for c in engine.legal_candidates() if (c.display_name.split(" — Hits allies too:")[0] == name or c.display_name.startswith(name + " at ")) and c.actor_id == actor_id
               and (target is None or target in (c.target_ids or ()))
               and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert matches, f"{name!r} (target={target}, at={at}) is not legal; legal: {sorted(legal(engine))}"
    candidate = matches[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c7-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[start:]


def unarmed(engine, actor_id=ME):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == actor_id and a.economy.value == "ACTION"
                and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                        for e in (a.parameters.get("typed") or {}).get("effects") or [] if isinstance(e, dict)))


def answers(engine, selections=None):
    """Answer every extension choice: the listed option ids for a reaction source ending with a key, else the first ones."""
    selections = selections or {}

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:max(1, spec["minimum_selections"])])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    engine.set_reaction_provider(provider)


def payloads(events, kind):
    return [e.payload or {} for e in events if e.event_type == kind]


def riders(mid):
    return mechanics()[mid].get("riders") or []


# ------------------------------------------------------------------------------- Group 01: Adamant Thunderbolt Body
# plug-ins: combat/ext/path_leap.py (move_to_aim), combat/ext/pool_spend.py (spend_pool_scaled),
# combat/ext/path_riders.py (path_next_unarmed_damage), combat/ext/thunder_charges.py (melee_miss_charge)

def _descent(charges=5, objects=(), foe_at=(10, 6)):
    engine = fight(bundle([ADAMANT + "adamantine_descent"]), foe_at=foe_at, objects=objects)
    me = engine.state.actors[ME]
    engine._gain_resource(me, THUNDER, charges, "test")
    return engine, me


def test_adamantine_descent_moves_physically_to_the_square_and_strikes_around_where_it_lands():
    engine, me = _descent()
    before = len(engine.rolls)
    events = use(engine, "Adamantine Descent", at=(9, 6))
    assert (me.position.x, me.position.y) == (9, 6)
    moves = [p for p in payloads(events, "MOVEMENT_COMMITTED") if p.get("without_provoking")]
    assert len(moves) >= 5 and not any(e.event_type.startswith("TELEPORT") for e in events)  # a route, square by square
    assert me.resources[STAMINA] == 53 and me.resources[THUNDER] == 0  # 7 Stamina and every Charge
    damage = [r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]
    assert damage and damage[0].expression.startswith("13d10")  # 8d10 + 1d10 for each of the 5 Charges spent
    foe = engine.state.actors[foe_id(engine)]
    assert foe.current_hp < 1000 and any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert {"FORCE", "SLASHING", "THUNDER"} <= resisted and "PSYCHIC" not in resisted
    assert any(c.condition_id == "condition:typed.path_next_unarmed_damage" for c in me.conditions.values())
    assert not payloads(events, "GM_RIDER")  # no GM line left


def test_adamantine_descent_needs_three_charges():
    engine, _me = _descent(charges=2)
    assert "Adamantine Descent" not in legal(engine)


def test_adamantine_descent_next_unarmed_strike_adds_4d8_force_once():
    engine, me = _descent(foe_at=(10, 6))
    use(engine, "Adamantine Descent", at=(9, 6))
    turn(engine, ME)
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    foe.position = Position(x=10, y=6)  # the failed save pushed it 20 feet: bring it back into reach
    events = use(engine, unarmed(engine), target=foe.entity_id)
    force = [p for p in payloads(events, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() == "FORCE"]
    assert force, "the pending 4d8 Force did not land on the next unarmed hit"
    assert not any(c.condition_id == "condition:typed.path_next_unarmed_damage" for c in me.conditions.values())
    me.action_available = True
    again = use(engine, unarmed(engine), target=foe.entity_id)
    assert not [p for p in payloads(again, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() == "FORCE"]


def test_adamantine_descent_objects_near_the_landing_take_double():
    objects = [{"id": 1, "kind": "crate", "x": 9, "y": 8, "hp": 999}, {"id": 2, "kind": "crate", "x": 1, "y": 1, "hp": 999}]
    engine, _me = _descent(objects=objects)
    before = len(engine.rolls)
    events = use(engine, "Adamantine Descent", at=(9, 6))
    rolled = next(r.total for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    lost = {(p.get("object") or {}).get("object_id"): p for p in payloads(events, "OBJECT_UPDATED")}
    assert "object:map.1" in lost and "object:map.2" not in lost
    near = engine.state.objects["object:map.1"]
    assert near.maximum_hp - near.current_hp == 2 * rolled


def _typed_foe():
    return bundle([], actor_id=FOE, name="C7 Foe")


def test_body_of_the_unbroken_bolt_gains_a_charge_when_a_melee_attack_misses_once_per_round():
    engine = fight(bundle([ADAMANT + "body_of_the_unbroken_bolt"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    me.armor_class = 99
    turn(engine, FOE)
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[THUNDER] == 1
    engine.state.actors[FOE].action_available = True
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[THUNDER] == 1  # one normal Charge per round


def test_body_of_the_unbroken_bolt_keeps_no_gm_miss_line():
    assert not any("Miss-to-Charge" in line for line in riders(ADAMANT + "body_of_the_unbroken_bolt"))
    engine = fight(bundle([ADAMANT + "body_of_the_unbroken_bolt"]), foe=_typed_foe())
    turn(engine, ME)
    events = engine.events[-20:]
    assert not any("Miss-to-Charge" in str(p.get("rider")) for p in payloads(events, "GM_RIDER"))


def test_heaven_breaking_knuckle_end_defense_is_no_longer_a_gm_line():
    assert riders(ADAMANT + "heaven_breaking_knuckle") == []
    fail = next(e for e in mechanics()[ADAMANT + "heaven_breaking_knuckle"]["effects"][0]["effects"] if e.get("type") == "save")
    assert any(row.get("end_defense") for row in fail["on_fail"])  # the fifth result is a real option the player picks


def test_adamantine_descent_state_survives_a_table_commit_and_reload(monkeypatch, tmp_path):
    import zipfile

    from combat import ext
    from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
    from combat.tabletop_service import TabletopService

    actors = [FACTORY_ACTOR_PREFIX + side for side in ("left", "right")]
    for side, ids in (("left", [ADAMANT + "adamantine_descent"]), ("right", [])):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet(ids, name=side.title())))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "C7 yard", "width_squares": 20, "height_squares": 14, "walls": [],
                               "starts": {"team1": [[3, 6]], "team2": [[12, 6]]}})
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[actors[1]], control_modes={a: "MANUAL" for a in actors},
                                      arena_id="battlefield:map.c7-yard", match_seed="C7-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    ext.effects()

    def charge(fight_, event_type, kwargs):
        if event_type == "HOLD_POSITION_COMMITTED":
            fight_._gain_resource(fight_.state.actors[kwargs["actor_id"]], THUNDER, 4, "test:charge")
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), charge])
    state = table.state(mid)
    menu = state["menu"]
    owner = menu["actor_id"]
    if owner != actors[0]:  # the right side acted first: pass its turn
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
        state = table.state(mid)
        menu = state["menu"]
        owner = menu["actor_id"]
    hold = next(g for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    assert table.act(mid, hold["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"].startswith("Adamantine Descent") and "object" not in g["label"])
    option = next(o for o in group["options"] if "11,6" in o.get("label", "") or o.get("destination") == {"x": 11, "y": 6})
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    loaded = combat._load_session(mid).engine
    me = loaded.state.actors[owner]
    assert (me.position.x, me.position.y) == (11, 6) and me.resources[THUNDER] == 0
    held = [c for c in me.conditions.values() if c.condition_id == "condition:typed.path_next_unarmed_damage"]
    assert len(held) == 1 and held[0].data["dice"] == {"count": 4, "sides": 8} and held[0].data["damage_type"] == "force"


# ------------------------------------------------------------------------------- Group 02: Black Thorn Demon Body
# plug-ins: combat/ext/black_thorn_demon_body.py (Briar hooks, Forest of Impalement, Spine damage), combat/ext/reach_bonus.py;
# data: resource_definitions.jsonl (printed Demon Spine record), trigger_readings.jsonl (Crown's trigger)
THORN = "tianxia.subpath.body.black_thorn_demon_body.feature."
SPINE = "resource:named.demon_spine"
BRIAR_STATE = "condition:typed.state.calamity_briar_incarnation"


def _briar_fight(foe_at=(4, 6), foe=None):
    engine = fight(bundle([THORN + "calamity_briar_incarnation"]), foe_at=foe_at, foe=foe)
    return engine, engine.state.actors[ME]


def test_demon_spines_have_the_printed_maximum():
    engine, me = _briar_fight()
    assert engine.state.actors[ME].resource_maximums[SPINE] == 6  # Proficiency Bonus at CL18 (was 99)


def test_calamity_briar_is_a_self_transformation_with_spines_to_maximum_and_resistance():
    engine, me = _briar_fight()
    foe = engine.state.actors[foe_id(engine)]
    events = use(engine, "Calamity Briar Incarnation")
    assert any(c.condition_id == BRIAR_STATE for c in me.conditions.values())
    assert me.resources[SPINE] == 9  # PB + 3 during Incarnation
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert {"PIERCING", "SLASHING", "FORCE", "COLD"} <= resisted and not resisted & {"FIRE", "PSYCHIC"}
    assert foe.current_hp == 1000 and not foe.conditions  # the old typing hit, restrained and pushed the foe on activation
    riders_left = " ".join(str(p.get("rider")) for p in payloads(events, "GM_RIDER"))
    assert "Forest of Impalement" not in riders_left and "reach +10" not in riders_left.lower()


def test_calamity_briar_unarmed_strikes_use_a_d12_reach_15_feet_and_add_4d8_once_per_turn():
    engine, me = _briar_fight(foe_at=(7, 6))
    use(engine, "Calamity Briar Incarnation")
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    assert unarmed(engine) + " (extended reach)" in legal(engine)  # 15 feet away
    before = len(engine.rolls)
    use(engine, unarmed(engine) + " (extended reach)", target=foe.entity_id)
    rolled = [r.expression for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]
    assert rolled[0].startswith("1d12") and any(e.startswith("4d8") for e in rolled)
    me.action_available = True
    before = len(engine.rolls)
    use(engine, unarmed(engine) + " (extended reach)", target=foe.entity_id)
    assert not any(r.expression.startswith("4d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))  # once per turn


def test_calamity_briar_grows_a_spine_each_turn_and_offers_forest_of_impalement_only_while_on():
    engine, me = _briar_fight()
    assert "Forest of Impalement" not in legal(engine)
    use(engine, "Calamity Briar Incarnation")
    engine._spend_resource(me, SPINE, 3, "test")
    turn(engine, ME)
    assert me.resources[SPINE] == 7  # PB + 3 maximum, spend 3, then regain 1
    assert "Forest of Impalement" in legal(engine)


def test_forest_of_impalement_restrains_bleeds_and_leaves_hostile_difficult_thorns_around_you():
    engine, me = _briar_fight(foe_at=(7, 6))
    use(engine, "Calamity Briar Incarnation")
    foe = engine.state.actors[foe_id(engine)]
    events = use(engine, "Forest of Impalement")
    assert me.resources[SPINE] == 5  # PB + 3 maximum, Forest spends 4
    assert [p for p in payloads(events, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() == "PIERCING"]
    held = {c.condition_id: c for c in foe.conditions.values()}
    assert "condition:typed.restrained" in held and held["condition:typed.restrained"].data["repeat_save"]["ability"] == "DEX"
    assert "condition:typed.bleeding" in held
    zone = next(z for z in engine.state.zones.values() if z.source_definition_id.endswith("forest_of_impalement"))
    assert zone.trigger_profile["follows_owner"] and zone.trigger_profile["difficult"] == "hostile"


def test_crown_of_black_thorns_reach_needs_a_spine_and_your_own_turn():
    engine = fight(bundle([THORN + "crown_of_black_thorns"]), foe_at=(5, 6))
    me = engine.state.actors[ME]
    name = unarmed(engine) + " (extended reach)"
    assert name not in legal(engine)
    engine._gain_resource(me, SPINE, 1, "test")
    assert name in legal(engine)


def test_crown_of_black_thorns_spends_a_spine_when_a_foe_enters_reach_and_its_thorns_ignore_piercing_resistance():
    engine = fight(bundle([THORN + "crown_of_black_thorns"]), foe=_typed_foe(), foe_at=(9, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._gain_resource(me, SPINE, 2, "test")
    engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", "PIERCING", "SELF", expires_on=None)
    answers(engine)
    turn(engine, FOE)
    before = len(engine.rolls)
    events = use(engine, "Move to 4,6", actor_id=FOE)
    assert me.resources[SPINE] == 1
    rolled = next(r.total for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    taken = [p for p in payloads(events, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() == "PIERCING"]
    assert taken and int(taken[0].get("hp_damage", 0)) + int(taken[0].get("temporary_hp_absorbed", 0)) == rolled  # not halved
    assert any(c.condition_id == "condition:typed.bleeding" for c in foe.conditions.values())


def test_crown_of_black_thorns_immune_to_bleeding():
    engine = fight(bundle([THORN + "crown_of_black_thorns"]), foe=_typed_foe())
    from combat import typed_executor
    assert typed_executor.condition_immune(engine, engine.state.actors[ME], "bleeding")


def test_thorn_flesh_armory_asks_before_spending_a_spine():
    engine = fight(bundle([THORN + "thorn_flesh_armory"]))
    me = engine.state.actors[ME]
    engine._gain_resource(me, SPINE, 2, "test")
    engine.state.actors[foe_id(engine)].armor_class = -50
    answers(engine, {"thorn_flesh_armory": None})
    use(engine, unarmed(engine), target=foe_id(engine))
    assert me.resources[SPINE] == 2  # declined: nothing spent
    turn(engine, ME)
    answers(engine, {"thorn_flesh_armory": ["spend"]})
    use(engine, unarmed(engine), target=foe_id(engine))
    assert me.resources[SPINE] == 1


# ------------------------------------------------------------------------------------------------- Group 03: Bojutsu
# plug-in: combat/ext/bojutsu.py (barrier_cover, barrier_opportunity_hit)
BOJUTSU = "tianxia.subpath.body.bojutsu.feature."
STAFF_ITEM = "tianxia.mortal.weapon.gun"
BOW_ITEM = "tianxia.mortal.weapon.dan_gong"


def _barrier_fight(foe_items=(BOW_ITEM,), foe_at=(10, 6)):
    me = bundle([BOJUTSU + "staff_form", BOJUTSU + "heavenly_staff_barrier"], items=(STAFF_ITEM,), spheres={})
    foe = bundle([], actor_id=FOE, name="C7 Archer", items=foe_items, spheres={})
    engine = fight(me, foe=foe, foe_at=foe_at)
    use(engine, "Heavenly Staff Barrier")
    return engine


def _weapon_attack(engine, actor_id, words):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == actor_id and a.economy.value == "ACTION"
                and (a.parameters.get("typed") or {}).get("weapon") and any(w in a.display_name.lower() for w in words)
                and "#" not in a.source_definition_id)


def test_heavenly_staff_barrier_gives_half_cover_against_a_ranged_weapon_attack():
    engine = _barrier_fight()
    turn(engine, FOE)
    events = use(engine, _weapon_attack(engine, FOE, ("bow", "gong")), target=ME, actor_id=FOE)
    rolled = payloads(events, "ATTACK_ROLLED")
    assert rolled and rolled[0]["cover_bonus"] == 2


def test_heavenly_staff_barrier_opportunity_hit_sets_speed_zero_for_the_turn():
    engine = _barrier_fight(foe_items=(), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.armor_class = -50
    answers(engine)
    turn(engine, FOE)
    use(engine, "Move to 8,6", actor_id=FOE)
    assert engine._effective_speed(foe) == 0


# ------------------------------------------------------------------------------------------- shared test helpers (2)
def force_d20(engine, low, high):
    """Every d20 lands in low..high (rerolled from the seeded stream until it does; tests/test_sysv2_objects.py)."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        while True:
            roll = original(**kwargs)
            if low <= int(roll.natural_result) <= high:
                return roll
    engine.roller.d20 = d20


def end_turns_until(engine, actor_id):
    """End turns with real End-turn intents until ``actor_id``'s turn starts (its start-of-turn choices reach the provider)."""
    for _ in range(8):
        current = engine.state.current_actor_id
        candidate = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        engine.execute_intent(ActionIntent(intent_id=f"c7-end-{len(engine.events)}", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=current, target_ids=candidate.target_ids, destination=candidate.destination))
        if engine.state.current_actor_id == actor_id:
            actor = engine.state.actors[actor_id]
            actor.action_available = actor.bonus_action_available = actor.reaction_available = True
            return actor
    raise AssertionError("turn never came round")


def reloaded_state(engine):
    """The fight state as a saved fight stores it (JSON) and reads it back: stored data must be plain ints/strings."""
    from combat.gate2_runtime_models import MatchState

    text = json.dumps(engine.state.model_dump(mode="json", by_alias=True))
    return MatchState.model_validate(json.loads(text))


def hostile_packet(engine, target_id, amount, damage_type, attacker_id=None):
    """Commit one hostile damage packet with an active intent, as the typed damage path does (tests/test_riders_lane13.py)."""
    attacker_id = attacker_id or foe_id(engine)
    candidate = next(iter(engine.legal_candidates()))
    intent = ActionIntent(intent_id=f"packet-{len(engine.events)}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=attacker_id, target_ids=(target_id,))
    engine._typed_pending_damage_type = damage_type
    engine._active_intent = intent
    start = len(engine.events)
    try:
        engine._commit_damage(engine.state.actors[target_id], amount, damage_type, source_definition_id="test:hostile",
                              source_actor_id=attacker_id, intent=intent, reaction_depth=0)
    finally:
        engine._active_intent = None
    return engine.events[start:]


# ------------------------------------------------------------------------------------------------ Group 04: Bone Monarch
# plug-in: combat/ext/bone_monarch.py; split: splits.json unbroken_bones (#bones, #marrow_memory); summons.json Bone Strike types
BONE = "tianxia.subpath.body.bone_monarch.feature."


@pytest.mark.parametrize("damage_type,dice", [("FIRE", "1d8"), ("SLASHING", "2d8")])
def test_bone_armor_rolls_1d8_against_non_physical_damage_and_2d8_against_physical(damage_type, dice):
    engine = fight(bundle([BONE + "bone_armor"]), foe=_typed_foe())
    answers(engine)
    before = len(engine.rolls)
    hostile_packet(engine, ME, 30, damage_type)
    rolled = [r.expression for r in engine.rolls[before:]]
    assert any(expr.startswith(dice) for expr in rolled), rolled
    assert engine.state.actors[ME].resources[STAMINA] == 59


def test_sovereign_reconstruction_cocoons_then_emerges_at_half_hit_points_with_a_burst():
    engine = fight(bundle([BONE + "sovereign_reconstruction"]), foe=_typed_foe(), foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine)
    hostile_packet(engine, ME, 500, "SLASHING")
    assert me.active and me.current_hp == 1 and me.resources[STAMINA] == 52
    assert me.temporary_hp == 90 and any(c.condition_id == "condition:typed.bone_cocoon" for c in me.conditions.values())
    from combat import ext
    assert me.armor_class + sum(ext.run("ac", engine, me)) == 50  # the cocoon's AC: the Cultivation Save DC
    assert not (legal(engine) - {"End turn"}) or "End turn" in legal(engine)
    state = reloaded_state(engine)
    assert any(c.condition_id == "condition:typed.bone_cocoon" and c.data["ac"] == 50 for c in state.actors[ME].conditions.values())
    engine._apply_condition(me, "condition:typed.prone", "test", FOE, expires_on="UNTIL_REMOVED")
    turn(engine, ME)
    assert me.current_hp == 60 and me.temporary_hp == 0
    assert not any(c.condition_id in ("condition:typed.bone_cocoon", "condition:typed.prone") for c in me.conditions.values())
    assert foe.current_hp < 1000 and any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values())


def test_sovereign_reconstruction_broken_cocoon_leaves_you_down():
    engine = fight(bundle([BONE + "sovereign_reconstruction"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine)
    hostile_packet(engine, ME, 500, "FIRE")
    assert me.current_hp == 1 and me.temporary_hp == 90
    hostile_packet(engine, ME, 200, "FIRE")
    assert not me.active or me.current_hp == 0


def test_marrow_memory_keeps_you_at_1_hp_once_per_scene():
    engine = fight(bundle([BONE + "unbroken_bones"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine)
    hostile_packet(engine, ME, 500, "FIRE")
    assert me.active and me.current_hp == 1 and me.resources[STAMINA] == 56
    hostile_packet(engine, ME, 50, "FIRE")
    assert not me.active or me.current_hp == 0


def test_unbroken_bones_turns_a_critical_hit_into_a_normal_hit_and_resists_prone_saves():
    engine = fight(bundle([BONE + "unbroken_bones"]), foe=_typed_foe())
    force_d20(engine, 20, 20)
    turn(engine, FOE)
    before = len(engine.rolls)
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    damage = next(r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    normal = sum(damage.dice[:len(damage.dice) // 2]) + damage.modifier
    first = payloads(events, "DAMAGE_COMMITTED")[0]
    assert int(first["rolled_or_pending_damage"]) == damage.total and int(first["reduced_to"]) == normal
    assert any(p.get("critical_turned_normal") for p in payloads(events, "PASSIVE_TRIGGERED"))
    from combat import typed_executor
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, engine.state.actors[FOE], action, None, {"numbers": {"pb": 4, "save_dc": 16}},
                                 [engine.state.actors[ME]], engine.state.actors[ME], {})
    typed_executor.block_save(ctx, {"type": "save", "ability": "dex", "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}], "on_success": []})
    assert next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED").payload.get("mode") == "ADVANTAGE"


def test_marrow_regeneration_ends_a_bleeding_after_healing():
    engine = fight(bundle([BONE + "marrow_regeneration"]))
    me = engine.state.actors[ME]
    me.current_hp = 40
    engine._apply_condition(me, "condition:typed.bleeding", "test:bleed", foe_id(engine), expires_on="UNTIL_REMOVED")
    answers(engine)
    use(engine, "Marrow Regeneration")
    assert me.current_hp > 40 and not any(c.condition_id == "condition:typed.bleeding" for c in me.conditions.values())
    assert not riders(BONE + "marrow_regeneration")[0].startswith("The old typing")


def test_bone_guard_riders_are_the_summon_and_its_strike_can_bludgeon():
    assert riders(BONE + "bone_guard_manifestation") == []
    b = bundle([BONE + "bone_guard_manifestation"])
    strike = next(a for s in b["summons"] for a in s["action_catalog"] if a["display_name"] == "Bone Strike")
    assert "BLUDGEONING" in (strike["parameters"]["typed"].get("weapon") or {}).get("damage_types", [])


# ------------------------------------------------------------------------------------------------ Group 05: Drunken Fist
# plug-ins: combat/ext/d20_rewrite_rules.py (Empty Cup move + reach recheck), combat/ext/drunken_fist.py (free stand),
# combat/ext/path_riders.py (Staggering Blow paid hit, path_results name)
DRUNK = "tianxia.subpath.body.drunken_fist.feature."


@pytest.mark.parametrize("where,misses", [("cell:1,6", True), ("stay", False)])
def test_empty_cup_moves_you_and_the_rerolled_attack_misses_if_it_cannot_reach(where, misses):
    engine = fight(bundle([DRUNK + "empty_cup"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    me.armor_class = 1
    force_d20(engine, 15, 15)
    answers(engine, {"empty_cup_move": [where], "empty_cup_posture": None})
    turn(engine, FOE)
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[STAMINA] == 58
    damaged = [p for p in payloads(events, "DAMAGE_COMMITTED") if int(p.get("hp_damage", 0)) > 0]
    if misses:
        assert (me.position.x, me.position.y) == (1, 6) and not damaged
    else:
        assert (me.position.x, me.position.y) == (3, 6) and damaged


def test_falling_fist_strikes_unarmed_when_knocked_prone():
    engine = fight(bundle([DRUNK + "falling_fist"]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    answers(engine)
    turn(engine, FOE)
    from combat import typed_executor
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE)
    ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 6, "save_dc": 16}}, [me], me, {})
    start = len(engine.events)
    typed_executor.run_effects(ctx, [{"type": "condition", "condition": "prone", "applies_to": "target"}])
    strikes = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    assert strikes
    damage = [r for r in engine.rolls if str(r.reason).startswith("DAMAGE") and r.actor_id == ME]
    assert damage and damage[-1].expression.startswith("2d6")  # the Iron Fist unarmed strike, not a 1d4 stand-in


def test_heavenly_drunk_stands_from_prone_for_free():
    engine = fight(bundle([DRUNK + "heavenly_drunk"]))
    me = engine.state.actors[ME]
    use(engine, "Heavenly Drunk")
    engine._apply_condition(me, "condition:typed.prone", "test", foe_id(engine), expires_on="STAND_UP")
    turn(engine, ME)
    assert not any(c.condition_id == "condition:typed.prone" for c in me.conditions.values())
    assert me.movement_remaining_ft == engine._effective_speed(me)


@pytest.mark.parametrize("use_it", [True, False])
def test_staggering_blow_is_a_paid_unarmed_hit_rider_with_a_failed_save_menu(use_it):
    engine = fight(bundle([DRUNK + "staggering_blow"]))
    me = engine.state.actors[ME]
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    answers(engine, {"path_hit." + DRUNK + "staggering_blow": ["Use Staggering Blow"] if use_it else None,
                     "path_results.staggering_blow": ["Knock Prone"]})
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=foe.entity_id)
    prone = any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values())
    assert prone == use_it and me.resources[STAMINA] == (59 if use_it else 60)


def test_swaying_step_modifies_the_body_refining_stomping_step():
    assert riders(DRUNK + "swaying_step") == []
    b = bundle([DRUNK + "swaying_step", "tianxia.path.body_refining.feature.stomping_step"])
    assert "Stomping Step + Swaying Step: Stand from Prone" in {a["display_name"] for a in b["action_catalog"]}


# ------------------------------------------------------------------------------------------ Group 06: Eight Gates
# plug-in: combat/ext/eight_gates.py (the Gate state and every Gate's benefits)
GATES = "tianxia.subpath.body.eight_gates_of_the_heaven_defying_body.feature."
ALL_GATES = [GATES + k for k in ("first_and_second_gates", "third_and_fourth_gates", "fifth_gate_gate_of_thunder",
                                 "sixth_and_seventh_gates", "eighth_gate_heaven_defying_gate")]


def _gates(count, *, foe_at=(4, 6), foe=None):
    engine = fight(bundle(ALL_GATES), foe_at=foe_at, foe=foe)
    me = engine.state.actors[ME]
    assert engine._effective_speed(me) == 30  # nothing is on until the Gates open (the old typing gave +10 always)
    answers(engine, {"eight_gates": [str(count)]})
    use(engine, "Open the Gates")
    return engine, me


def test_opening_eight_gates_costs_stamina_and_turns_on_every_gate():
    engine, me = _gates(8)
    from combat import ext
    assert me.resources[STAMINA] == 52
    assert engine._effective_speed(me) == 80  # (30 + 10) doubled
    assert sum(ext.run("ac", engine, me)) == 2
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert "FIRE" in resisted and "FORCE" not in resisted and "PSYCHIC" not in resisted
    me.bonus_action_available = True
    assert "Open the Gates" not in legal(engine) and "Close the Gates" in legal(engine)


def test_gate_damage_at_the_start_of_the_turn_ignores_temporary_hit_points():
    engine, me = _gates(8)
    engine._grant_temp_hp(me, 50, "test", ME)
    before = len(engine.rolls)
    turn(engine, ME)
    gate = next(r for r in engine.rolls[before:] if "gates" in str(r.reason))
    assert gate.expression.startswith("8d6")
    assert me.temporary_hp == 50 and me.current_hp == 120 - gate.total


def test_gate_of_blood_and_gate_of_thunder_with_five_gates_open():
    engine, me = _gates(5)
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=foe.entity_id)
    flat = [p for p in payloads(events, "DAMAGE_COMMITTED")]
    assert len(flat) >= 2  # the strike and the Gate of Blood's Proficiency Bonus
    assert "Gate of Thunder: extra unarmed strike" in legal(engine)
    use(engine, "Gate of Thunder: extra unarmed strike", target=foe.entity_id)
    assert "Gate of Thunder: extra unarmed strike" not in legal(engine)


def test_closing_the_gates_ends_them_for_the_scene():
    engine, me = _gates(2)
    me.bonus_action_available = True
    use(engine, "Close the Gates")
    assert engine._effective_speed(me) == 30
    turn(engine, ME)
    assert "Open the Gates" not in legal(engine)


def test_eighth_gate_collapse_closes_the_gates_when_gate_damage_drops_you():
    engine, me = _gates(8)
    me.current_hp = 3
    turn(engine, ME)
    assert me.current_hp == 0 and "closed" in next(c for c in me.conditions.values() if c.condition_id == "condition:typed.eight_gates").data


# ------------------------------------------------------------------------------------- Group 07: Five-Viscera Immortal Furnace
# plug-in: combat/ext/organ_furnaces.py (the Organ Furnace state, Inner Cosmos, Refine the Impure)
VISCERA = "tianxia.subpath.body.five_viscera_immortal_furnace.feature."
STAMINA_GUARD = "tianxia.path.body_refining.feature.stamina_guard"


def _furnace_fight(ids, *, foe=None, foe_at=(4, 6), picks=None):
    engine = fight(bundle([VISCERA + k for k in ids] + [STAMINA_GUARD]), foe=foe, foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME]


def test_heart_furnace_is_on_before_any_choice_and_adds_pb_once_per_turn():
    engine, me = _furnace_fight(["five_viscera_circuit"])
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=foe.entity_id)
    fire = [p for p in payloads(events, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() in ("FIRE", "RADIANT")]
    assert fire and int(fire[0]["rolled_or_pending_damage"]) == 6
    me.action_available = True
    again = use(engine, unarmed(engine), target=foe.entity_id)
    assert not [p for p in payloads(again, "DAMAGE_COMMITTED") if str(p.get("damage_type")).upper() in ("FIRE", "RADIANT")]


def test_lung_furnace_chosen_at_turn_start_adds_ac_against_ranged_attacks():
    engine, me = _furnace_fight(["five_viscera_circuit"], foe=bundle([], actor_id=FOE, items=(BOW_ITEM,), spheres={}), foe_at=(10, 6),
                                picks={"organ_furnaces": ["lung"]})
    end_turns_until(engine, ME)
    assert next(c for c in me.conditions.values() if c.condition_id == "condition:typed.organ_furnaces").data["active"] == ["lung"]
    turn(engine, FOE)
    events = use(engine, _weapon_attack(engine, FOE, ("bow",)), target=ME, actor_id=FOE)
    assert payloads(events, "ATTACK_ROLLED")[0]["target_ac"] == me.armor_class + 1


def test_liver_heals_after_spending_stamina_and_twin_circulation_swaps_a_furnace():
    engine, me = _furnace_fight(["five_viscera_circuit", "twin_furnace_circulation", "refine_the_impure"],
                                picks={"organ_furnaces": ["liver", "heart"], "furnace_swap": ["heart>spleen"], "kidney_step": None})
    end_turns_until(engine, ME)
    me.current_hp = 50
    use(engine, "Refine the Impure")
    assert me.current_hp == 56 and me.resources[STAMINA] == 58  # Liver: Proficiency Bonus
    assert set(next(c for c in me.conditions.values() if c.condition_id == "condition:typed.organ_furnaces").data["active"]) == {"liver", "spleen"}


def test_spleen_gives_temporary_hp_after_stamina_guard_without_eating_the_packet():
    engine, me = _furnace_fight(["fivefold_organ_harmony"], foe=_typed_foe())
    hostile_packet(engine, ME, 30, "SLASHING")
    assert me.temporary_hp == 6


def test_inner_cosmos_improves_the_heart_and_refine_costs_nothing():
    engine, me = _furnace_fight(["five_viscera_circuit", "refine_the_impure", "inner_cosmos_furnace"], picks={"kidney_step": None})
    use(engine, "Inner Cosmos Furnace")
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=foe.entity_id)
    assert any(r.expression.startswith("3d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    me.bonus_action_available = True
    stamina = me.resources[STAMINA]
    use(engine, "Refine the Impure (Inner Cosmos: no Stamina)")
    assert me.resources[STAMINA] == stamina


@pytest.mark.parametrize("dc,ends", [(1, True), (99, False)])
def test_refine_the_impure_repeats_a_poisoned_save_with_advantage(dc, ends):
    engine, me = _furnace_fight(["refine_the_impure"])
    engine._apply_condition(me, "condition:typed.poisoned", "test:poison", foe_id(engine), expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": dc}})
    events = use(engine, "Refine the Impure")
    assert [p for p in payloads(events, "SAVE_ROLLED")][0].get("mode") == "ADVANTAGE"
    poisoned = any(c.condition_id == "condition:typed.poisoned" for c in me.conditions.values())
    assert not poisoned  # ended, or suppressed until the start of the next turn
    turn(engine, ME)
    assert any(c.condition_id == "condition:typed.poisoned" for c in me.conditions.values()) == (not ends)


# ----------------------------------------------------------------------------------------------- Group 08: Flesh Crucible
# plug-in: combat/ext/flesh_crucible.py; seam: typed_executor.size_width + ext hook size_steps
CRUCIBLE = "tianxia.subpath.body.flesh_crucible.feature."


def _huge(engine, actor_id):
    engine.actor_footprints[actor_id] = engine._footprint(actor_id).model_copy(update={
        "width_cells": 3, "height_cells": 3, "occupied_relative_cells": tuple(Position(x=x, y=y) for x in range(3) for y in range(3))})


def _grapple(engine, target_id):
    events = use(engine, "Grapple", target=target_id)
    return bool(payloads(events, "SAVE_ROLLED"))


@pytest.mark.parametrize("ids,uses,grapples", [
    ([], [], False),                                                   # a Huge foe is two sizes larger: no Grapple
    (["titan_s_frame"], ["Titan's Frame"], True),                     # counts one size larger
])
def test_titans_frame_counts_one_size_larger_for_grappling(ids, uses, grapples):
    engine = fight(bundle([CRUCIBLE + k for k in ids]), foe_at=(4, 6))
    _huge(engine, foe_id(engine))
    for name in uses:
        use(engine, name)
    me = engine.state.actors[ME]
    me.action_available = True
    assert _grapple(engine, foe_id(engine)) == grapples


def test_titans_frame_strength_saves_iron_fist_d10_and_hit_choice():
    engine = fight(bundle([CRUCIBLE + "titan_s_frame"]), foe_at=(4, 6))
    me = engine.state.actors[ME]
    use(engine, "Titan's Frame")
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    answers(engine, {"titan_frame_hit": ["push"]})
    before = len(engine.rolls)
    distance_before = engine._distance_actor_to_actor(me, foe)
    position_before = foe.position
    use(engine, unarmed(engine), target=foe.entity_id)
    damage = next(r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    assert damage.expression.startswith("2d6")  # the CL18 Iron Fist 2d6 is larger than 1d10: kept
    # Native forced movement uses the enlarged creature's whole footprint;
    # an equally valid diagonal destination need not share its anchor row.
    assert engine._distance_actor_to_actor(me, foe) == distance_before + 5
    assert engine.grid.distance_ft(position_before, foe.position) == 5
    from combat import typed_executor
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    typed_executor.block_save(ctx, {"type": "save", "ability": "str", "on_fail": [], "on_success": []})
    assert next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED").payload.get("mode") == "ADVANTAGE"


def test_mountain_demon_might_starts_titans_frame_and_adds_reach_and_temporary_hp():
    engine = fight(bundle([CRUCIBLE + "mountain_demon_might", CRUCIBLE + "titan_s_frame"]), foe_at=(6, 6))
    me = engine.state.actors[ME]
    use(engine, "Mountain-Demon Might")
    held = {c.condition_id for c in me.conditions.values()}
    assert {"condition:typed.state.mountain_demon_might", "condition:typed.state.titan_s_frame"} <= held
    assert me.temporary_hp == 36 and me.resources[STAMINA] == 55
    assert unarmed(engine) + " (extended reach)" in legal(engine)


def test_crushing_grip_crushes_a_grappled_creature_at_the_start_of_the_turn():
    engine = fight(bundle([CRUCIBLE + "crushing_grip"]), foe_at=(4, 6))
    me = engine.state.actors[ME]
    foe = engine.state.actors[foe_id(engine)]
    engine._apply_condition(foe, "condition:typed.grappled", "test:grab", ME, expires_on="UNTIL_REMOVED", data={"escape_dc": 15, "reach_ft": 5})
    answers(engine, {"crushing_grip": [foe.entity_id]})
    end_turns_until(engine, ME)
    assert foe.current_hp < 1000 and me.resources[STAMINA] == 59
    assert any(c.condition_id == "condition:typed.grappled" for c in foe.conditions.values())


def test_world_shaking_stomp_deals_its_10d6():
    engine = fight(bundle([CRUCIBLE + "world_shaking_stomp"]), foe_at=(5, 6))
    before = len(engine.rolls)
    use(engine, "World-Shaking Stomp", at=(5, 6))
    assert any(r.expression.startswith("10d6") for r in engine.rolls[before:])
    assert engine.state.actors[foe_id(engine)].current_hp < 1000


# ------------------------------------------------------------------------------------------------------ Group 09: Goruden
# plug-in: combat/ext/goruden.py; seam: typed_reactions soak_dice/soak_total (Stamina Guard dice); Golden Aura is a typed zone
GOLD = "tianxia.subpath.body.goruden.feature."


def test_gilded_guard_rolls_2d8_per_stamina_and_gives_temporary_hp_if_damage_remains():
    engine = fight(bundle([GOLD + "gilded_bones", STAMINA_GUARD]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine, {"gilded_guard": ["gilded"]})
    before = len(engine.rolls)
    hostile_packet(engine, ME, 200, "SLASHING")
    soak = next(r for r in engine.rolls[before:] if "DAMAGE_SOAK" in str(r.reason))
    count, sides = soak.expression.split("+")[0].split("d")
    assert sides == "8" and int(count) % 2 == 0
    assert me.temporary_hp == 6


def test_golden_sheen_gives_ac_and_poison_save_advantage_only_unarmored():
    engine = fight(bundle([GOLD + "golden_sheen"]))
    me = engine.state.actors[ME]
    from combat import ext, typed_executor
    assert sum(ext.run("ac", engine, me)) == 1
    ctx = typed_executor.Context(engine, engine.state.actors[foe_id(engine)], next(iter(engine.action_catalog.values())), None,
                                 {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    typed_executor.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target"}], "on_success": []})
    assert next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED").payload.get("mode") == "ADVANTAGE"


def test_golden_aura_follows_you_protects_you_and_tests_foes_starting_their_turn_in_it():
    engine = fight(bundle([GOLD + "golden_aura"]), foe=_typed_foe(), foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"golden_aura": ["No Reactions"]})
    use(engine, "Golden Aura")
    zone = next(z for z in engine.state.zones.values() if z.source_definition_id.endswith("golden_aura"))
    assert zone.trigger_profile["follows_owner"]
    assert "NECROTIC" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    end_turns_until(engine, FOE)
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values()) or not foe.reaction_available
    end_turns_until(engine, ME)
    assert me.temporary_hp == 6  # the first time it starts a turn there


def test_immortal_gold_statue_then_heals_and_starts_golden_aura():
    engine = fight(bundle([GOLD + "immortal_gold", GOLD + "golden_aura"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine)
    hostile_packet(engine, ME, 500, "FIRE")
    assert me.active and me.current_hp == 1 and any(c.condition_id == "condition:typed.golden_statue" for c in me.conditions.values())
    assert "FIRE" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    turn(engine, ME)
    assert me.current_hp == 31 and not any(c.condition_id == "condition:typed.golden_statue" for c in me.conditions.values())
    assert any(z.source_definition_id.endswith("golden_aura") and z.active for z in engine.state.zones.values())


def test_radiant_fist_once_per_turn_choice_on_an_unarmed_hit():
    engine = fight(bundle([GOLD + "radiant_fist"]))
    foe = engine.state.actors[foe_id(engine)]
    foe.armor_class = -50
    answers(engine, {"path_hit." + GOLD + "radiant_fist": ["Extra Radiant Damage"]})
    events = use(engine, unarmed(engine), target=foe.entity_id)
    assert any(str(p.get("damage_type")).upper() == "RADIANT" and int(p["rolled_or_pending_damage"]) == 6 for p in payloads(events, "DAMAGE_COMMITTED"))


# ------------------------------------------------------------------------------------- Group 10: Heaven-Answering Adaptive Body
# plug-in: combat/ext/adaptations.py (Damage/Affliction Adaptations, Flesh Remembers Pain gate, Return the Lesson)
ADAPT = "tianxia.subpath.body.heaven_answering_adaptive_body.feature."


def test_damage_adaptation_reduces_the_first_packet_and_gates_the_reaction():
    engine = fight(bundle([ADAPT + "flesh_remembers_pain"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine)
    hostile_packet(engine, ME, 20, "FIRE", attacker_id=FOE)
    assert me.current_hp == 100 and me.resources[STAMINA] == 60  # not adapted yet: no Reaction
    record = next(c for c in me.conditions.values() if c.condition_id == "condition:typed.adaptations")
    assert record.data["damage"] == [{"type": "FIRE", "by": FOE}]
    hostile_packet(engine, ME, 20, "FIRE", attacker_id=FOE)
    assert me.current_hp == 96 and me.resources[STAMINA] == 59  # 20 halved by Resistance, then -6 at the flat-reduction step
    hostile_packet(engine, ME, 20, "FIRE", attacker_id=FOE)
    assert me.current_hp == 76  # both once per round


def test_ten_thousand_answers_turns_an_adaptation_into_resistance():
    engine = fight(bundle([ADAPT + "flesh_remembers_pain", ADAPT + "ten_thousand_answers"]), foe=_typed_foe())
    me = engine.state.actors[ME]
    answers(engine, {"flesh_remembers_pain": None})
    hostile_packet(engine, ME, 20, "COLD", attacker_id=FOE)
    assert "COLD" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}


def test_affliction_adaptation_adds_pb_to_saves_ending_it():
    engine = fight(bundle([ADAPT + "meridians_remember_affliction"]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    from combat import typed_executor
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE)
    ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 6, "save_dc": 50}}, [me], me, {})
    typed_executor.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target",
                                                                                   "repeat_save": {"ability": "CON", "when": "end"}}], "on_success": []})
    record = next(c for c in me.conditions.values() if c.condition_id == "condition:typed.adaptations")
    assert record.data["afflictions"][0]["condition"] == "poisoned"
    start = len(engine.events)
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    bonus = [e for e in engine.events[start:] if e.event_type == "D20_REWRITTEN" and (e.payload or {}).get("operation") == "bonus"]
    assert bonus and bonus[0].payload["bonus"] == 6


def test_return_the_lesson_answers_the_creature_that_taught_it():
    engine = fight(bundle([ADAPT + "flesh_remembers_pain", ADAPT + "return_the_lesson"]), foe=_typed_foe(), foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"flesh_remembers_pain": None, "return_lesson": ["push"]})
    hostile_packet(engine, ME, 10, "FIRE", attacker_id=FOE)
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    assert (foe.position.x, foe.position.y) == (6, 6) and me.resources[STAMINA] == 59


# ------------------------------------------------------------------------------------------- Group 11: Heaven-Binding Chain Body
# plug-ins: combat/ext/chain_tethers.py, combat/ext/integrated_weapons.py, combat/ext/reach_bonus.py (group match)
CHAIN = "tianxia.subpath.body.heaven_binding_chain_body.feature."
WHIP = "tianxia.mortal.weapon.jie_bian"


def _chain_fight(ids, foe_at=(4, 6)):
    engine = fight(bundle([CHAIN + k for k in ids], items=(WHIP,)), foe=_typed_foe(), foe_at=foe_at)
    engine.state.actors[FOE].armor_class = -50
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _tether(engine):
    answers(engine, {"meridian_tether": ["tether"], "drag_the_heavens": ["Pull 20 Feet"]})
    use(engine, unarmed(engine), target=FOE)


def test_meridian_tether_on_an_unarmed_hit_limits_the_targets_moves_to_20_feet():
    engine, me, foe = _chain_fight(["chain_body_integration"])
    _tether(engine)
    assert me.resources[STAMINA] == 59 and any(c.condition_id == "condition:typed.meridian_tether" for c in foe.conditions.values())
    turn(engine, FOE)
    far = {c.destination.x for c in engine.legal_candidates() if getattr(c.kind, "value", c.kind) == "MOVE" and c.actor_id == FOE}
    assert far and max(far) <= 3 + 4  # nothing more than 20 feet (4 squares) from the owner at x=3


def test_chain_body_integration_constitution_variant_and_on_turn_reach():
    engine, me, foe = _chain_fight(["chain_body_integration"], foe_at=(5, 6))
    names = legal(engine)
    assert any(n.endswith("(Constitution)") for n in names)
    foe.position = Position(x=6, y=6)  # 15 feet: beyond the whip's base reach
    assert any("(extended reach)" in n for n in legal(engine))


def test_drag_the_heavens_needs_a_tether_and_pulls_on_a_failed_save():
    engine, me, foe = _chain_fight(["chain_body_integration", "drag_the_heavens"], foe_at=(4, 6))
    assert "Drag the Heavens" not in legal(engine)
    _tether(engine)
    foe.position = Position(x=7, y=6)
    me.bonus_action_available = True
    use(engine, "Drag the Heavens", target=FOE)
    assert foe.position.x < 7


def test_thousand_link_adds_2d8_against_a_tethered_creature_and_makes_its_ground_difficult():
    engine, me, foe = _chain_fight(["chain_body_integration", "thousand_link_meridian_network"])
    before = len(engine.rolls)
    _tether(engine)
    assert not any(r.expression.startswith("2d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))  # not yet Tethered when hit
    end_turns_until(engine, ME)
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    from combat import zones
    assert (4, 6) in zones.difficult_cells(engine, foe) and (4, 6) not in zones.difficult_cells(engine, me)


def test_heaven_binding_prison_restrains_and_keeps_them_inside():
    engine, me, foe = _chain_fight(["heaven_binding_prison"], foe_at=(8, 6))
    use(engine, "Heaven-Binding Prison", at=(8, 6))
    held = {c.condition_id: c for c in foe.conditions.values()}
    assert "condition:typed.restrained" in held and "condition:typed.prison_tether" in held
    assert held["condition:typed.restrained"].data["repeat_save"]["ability"] == "STR"


# ------------------------------------------------------------------------------------------- Group 12: Heaven-Devouring Maw
# plug-in: combat/ext/devouring_maw.py (typed Devoured Essence record and every Maw spend)
MAW = "tianxia.subpath.body.heaven_devouring_maw_body.feature."
ESSENCE = "resource:named.devoured_essence"


def _maw(ids, foe_at=(4, 6), picks=None):
    engine = fight(bundle([MAW + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    engine.state.actors[FOE].armor_class = -50
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _essence(engine, me, *kinds):
    from combat.ext import devouring_maw
    for kind in kinds:
        devouring_maw.gain(engine, me, kind, "test", normal=False)


def test_swallow_hostile_power_answers_valid_types_and_stores_their_essence():
    engine, me, foe = _maw(["swallow_hostile_power"])
    hostile_packet(engine, ME, 12, "SLASHING", attacker_id=FOE)
    assert me.resources[STAMINA] == 60  # Slashing is not a valid stored type
    hostile_packet(engine, ME, 30, "FIRE", attacker_id=FOE)
    assert me.resources[STAMINA] == 59 and me.resources[ESSENCE] == 1
    from combat.ext.devouring_maw import stored
    assert stored(me) == ["FIRE"]


def test_maw_strike_spends_an_essence_for_damage_of_its_type():
    engine, me, foe = _maw(["swallow_hostile_power"], picks={"maw_type": ["COLD"]})
    _essence(engine, me, "COLD")
    events = use(engine, unarmed(engine), target=FOE)
    assert me.resources[ESSENCE] == 0
    assert any(str(p.get("damage_type")).upper() == "COLD" for p in payloads(events, "DAMAGE_COMMITTED"))


def test_feast_upon_protection_sets_aside_temporary_hp_until_the_owners_next_turn():
    engine, me, foe = _maw(["feast_upon_protection"], picks={"maw_types": ["spend"], "feast_protection": ["temp_hp"]})
    _essence(engine, me, "FIRE", "FIRE", "ACID")
    engine._grant_temp_hp(foe, 15, "test", FOE)
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    aside = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.feast_set_aside").data["temp_hp"]
    assert me.resources[ESSENCE] == 0 and foe.temporary_hp == 0 and aside > 0  # what the strike itself left is set aside
    end_turns_until(engine, ME)
    assert foe.temporary_hp == aside


def test_regurgitate_calamity_spends_essence_of_one_type_for_3d8_each():
    engine, me, foe = _maw(["regurgitate_calamity"], foe_at=(8, 6), picks={"regurgitate": ["FIRE:2"]})
    assert "Regurgitate Calamity: One Creature" not in legal(engine)  # nothing stored
    _essence(engine, me, "FIRE", "FIRE")
    before = len(engine.rolls)
    use(engine, "Regurgitate Calamity: One Creature", target=FOE)
    assert me.resources[ESSENCE] == 0
    assert any(r.expression.startswith("6d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))


def test_devour_heaven_and_earth_makes_maw_strike_6d8():
    engine, me, foe = _maw(["swallow_hostile_power", "devour_heaven_and_earth"], picks={"maw_type": ["COLD"], "maw_types": None})
    use(engine, "Devour Heaven and Earth")
    _essence(engine, me, "COLD")
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("6d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))


# ------------------------------------------------------------------------------------------- Group 13: Heaven-Thunder Drum Body
# plug-ins: combat/ext/subpath_pools.py (Body Beat gains, maximum), combat/ext/drum_body.py, path_riders paid hits, pool_spend
DRUM = "tianxia.subpath.body.heaven_thunder_drum_body.feature."
BEAT = "resource:named.body_beat"


def _drum(ids, foe_at=(4, 6), picks=None, beats=0):
    engine = fight(bundle([DRUM + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me = engine.state.actors[ME]
    if beats:
        engine._gain_resource(me, BEAT, beats, "test")
    engine.state.actors[FOE].armor_class = -50
    return engine, me, engine.state.actors[FOE]


def test_body_beats_come_from_hostile_damage_once_a_round_up_to_proficiency_bonus():
    engine, me, foe = _drum(["bone_drum_strike"])
    hostile_packet(engine, ME, 5, "FIRE", attacker_id=FOE)
    hostile_packet(engine, ME, 5, "FIRE", attacker_id=FOE)
    assert me.resources[BEAT] == 1
    from combat.ext.subpath_pools import maximum
    assert maximum(engine, me, BEAT) == 6


def test_bone_drum_strike_spends_a_beat_for_thunder_and_a_choice():
    engine, me, foe = _drum(["bone_drum_strike"], picks={"path_hit." + DRUM + "bone_drum_strike": ["Push 5 Feet"]}, beats=1)
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[BEAT] == 0 and (foe.position.x, foe.position.y) == (5, 6)
    assert any(r.expression.startswith("3d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))


def test_counter_resonance_bursts_when_it_stops_the_damage():
    engine, me, foe = _drum(["counter_resonance"], beats=1)
    hostile_packet(engine, ME, 3, "FIRE", attacker_id=FOE)
    assert me.resources[BEAT] == 0 and me.resources[STAMINA] == 58
    assert foe.current_hp < 1000  # 2d8 Thunder (the save is against DC 50)


def test_internal_echo_detonates_on_the_targets_next_action():
    engine, me, foe = _drum(["internal_echo"], picks={"path_hit." + DRUM + "internal_echo": ["Use Internal Echo"]}, beats=2)
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert any(c.condition_id == "condition:typed.echoing" for c in foe.conditions.values())
    turn(engine, FOE)
    hp = foe.current_hp
    before = len(engine.rolls)
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert any(r.expression.startswith("3d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    assert foe.current_hp < hp and not any(c.condition_id == "condition:typed.echoing" for c in foe.conditions.values())


def test_world_shaking_cadence_spends_every_beat_for_8d8_plus_1d8_each():
    engine, me, foe = _drum(["world_shaking_cadence"], beats=2)
    assert "World-Shaking Cadence" not in legal(engine)
    engine._gain_resource(me, BEAT, 3, "test")
    before = len(engine.rolls)
    use(engine, "World-Shaking Cadence")
    assert me.resources[BEAT] == 0
    assert any(r.expression.startswith("13d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))


# ------------------------------------------------------------------------------------------- Group 14: Hundred-Beast Scripture
# plug-in: combat/ext/beast_aspects.py (known and active Aspects, their benefits, Beast King's Technique, Sovereign)
BEAST = "tianxia.subpath.body.hundred_beast_scripture.feature."


def _beasts(ids, *, picks=None, foe=None, foe_at=(4, 6), items=(), cl=18):
    engine = fight(bundle([BEAST + k for k in ids], items=items, cl=cl), foe=foe, foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[foe_id(engine)]


def _aspects(engine, actor_id=ME):
    from combat.ext.beast_aspects import active

    return active(engine, engine.state.actors[actor_id])


def test_beast_aspects_are_chosen_at_the_start_of_the_turn_and_tiger_adds_pb_once_per_turn():
    engine, me, foe = _beasts(["beast_scripture_initiate", "paired_beast_body"], picks={"beast_aspects": ["Tiger", "Ox"]})
    end_turns_until(engine, ME)
    assert _aspects(engine) == ["Tiger", "Ox"]
    foe.armor_class = -50
    strike = next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == unarmed(engine))

    def packets(events):  # the strike's own packets (Iron Fist's once-a-turn Open the Gate has a source of its own)
        return [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]
    first = packets(use(engine, unarmed(engine), target=foe.entity_id))
    me.action_available = True
    second = packets(use(engine, unarmed(engine), target=foe.entity_id))
    assert len(first) == 2 and first[1]["rolled_or_pending_damage"] == 6 and len(second) == 1  # + Proficiency Bonus, once per turn


def test_turtle_aspect_adds_ac_and_reduces_the_first_physical_packet_each_round():
    engine, me, foe = _beasts(["beast_scripture_initiate"], picks={"beast_aspects": ["Turtle"]}, foe=_typed_foe())
    use(engine, "Choose Beast Aspects: Turtle")
    end_turns_until(engine, ME)
    assert _aspects(engine) == ["Turtle"]
    hp = me.current_hp
    hostile_packet(engine, ME, 10, "SLASHING", attacker_id=FOE)
    assert hp - me.current_hp == 4  # 10 - Proficiency Bonus 6
    hostile_packet(engine, ME, 10, "SLASHING", attacker_id=FOE)
    assert hp - me.current_hp == 14  # only the first packet of the round
    turn(engine, FOE)
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert payloads(events, "ATTACK_ROLLED")[0]["target_ac"] == me.armor_class + 1


def test_serpent_aspect_reaches_10_feet_on_its_own_turn_and_crane_adds_speed():
    engine, me, _foe = _beasts(["beast_scripture_initiate", "paired_beast_body"], picks={"beast_aspects": ["Crane", "Serpent"]}, foe_at=(5, 6))
    end_turns_until(engine, ME)
    assert any(name.endswith("(extended reach)") for name in legal(engine))
    assert engine._effective_speed(me) == 40


def test_ox_aspect_counts_one_size_larger_for_grappling():
    engine, me, foe = _beasts(["beast_scripture_initiate"], picks={"beast_aspects": ["Ox"]})
    use(engine, "Choose Beast Aspects: Ox")
    end_turns_until(engine, ME)
    _huge(engine, foe.entity_id)
    assert _grapple(engine, foe.entity_id)


def test_known_aspects_are_a_standing_record_the_turn_start_choice_offers():
    engine, me, _foe = _beasts(["beast_scripture_initiate"], picks={"beast_aspects": ["Falcon"]}, items=("tianxia.mortal.weapon.bi_shou",))
    use(engine, "Choose Beast Aspects: Falcon")
    from combat.ext.beast_aspects import known

    assert known(engine, me) == ["Crane", "Serpent", "Falcon"]  # Falcon replaced the one chosen longest ago
    assert not any("(Falcon range)" in name for name in legal(engine))
    end_turns_until(engine, ME)
    assert _aspects(engine) == ["Falcon"]
    falcon = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name.endswith("(Falcon range)"))
    assert falcon.range_ft == 120 and falcon.parameters["typed"]["range_ft"] == 120  # 20/60 doubled, no long-range Disadvantage


def test_beast_kings_technique_spends_stamina_for_the_chosen_aspects_effect_once_per_turn():
    engine, me, foe = _beasts(["beast_scripture_initiate", "beast_king_s_technique"], picks={"beast_aspects": ["Ox"], "beast_king": ["Ox"],
                                                                                            "beast_king_ox": ["Knock Prone"]})
    use(engine, "Choose Beast Aspects: Ox")
    end_turns_until(engine, ME)
    foe.armor_class = -50
    stamina = me.resources[STAMINA]
    use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[STAMINA] == stamina - 1
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())  # Strength save against DC 50 failed
    me.action_available = True
    use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[STAMINA] == stamina - 1  # once per turn


def test_beast_kings_wolf_gives_an_ally_advantage_until_the_end_of_that_allys_next_turn():
    from combat.ext.effect_durations import token

    engine = _trio(bundle([BEAST + "beast_scripture_initiate", BEAST + "beast_king_s_technique"]), foe_at=(4, 6), ally_at=(6, 6))
    answers(engine, {"beast_aspects": ["Wolf"], "beast_king": ["Wolf"], "beast_wolf": [ALLY], "beast_king_wolf_move": None})
    use(engine, "Choose Beast Aspects: Wolf")
    end_turns_until(engine, ME)
    me, ally, foe = (engine.state.actors[k] for k in (ME, ALLY, FOE))
    foe.armor_class = -50
    use(engine, unarmed(engine), target=FOE)
    granted = [m for m in ally.modifiers.values() if m.target_field == "attack_mode_vs" and m.value == f"ADVANTAGE:{FOE}"]
    assert len(granted) == 1
    assert granted[0].expires_on == token("end", ALLY, int(ally.turns_started) + 1)  # "before the end of that ally's next turn"


def test_sovereign_makes_every_aspect_active_with_a_d12_fist_3d8_once_and_two_beast_kings():
    engine, me, foe = _beasts(["beast_scripture_initiate", "chimera_meridian_network", "beast_king_s_technique", "sovereign_of_ten_thousand_beasts"],
                              picks={"beast_king_move": None}, cl=5)  # Iron Fist's die is 1d8 at CL5 (2d6 at CL18 beats 1d12)
    end_turns_until(engine, ME)
    stamina = me.resources[STAMINA]
    use(engine, "Sovereign of Ten Thousand Beasts")
    assert me.resources[STAMINA] == stamina - 7 and len(_aspects(engine)) == 8
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=foe.entity_id)
    rolls = [r.expression for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]
    assert any(e.startswith("1d12") for e in rolls) and sum(e.startswith("3d8") for e in rolls) == 1
    me.action_available = True
    use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[STAMINA] == stamina - 7 - 2  # Beast King twice this turn (Tiger, then Crane), never a third time


def test_chimera_replaces_one_active_aspect_when_a_hostile_creature_ends_its_turn():
    engine, me, _foe = _beasts(["beast_scripture_initiate", "chimera_meridian_network"],
                               picks={"beast_aspects": ["Tiger", "Crane", "Wolf"], "chimera_swap": ["Wolf>Ox"]}, foe=_typed_foe())
    end_turns_until(engine, ME)
    assert _aspects(engine) == ["Tiger", "Crane", "Wolf"]
    start = len(engine.events)
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)  # the foe's turn ended: Wolf was replaced by Ox until the owner's own turn start chose again
    swapped = [p for p in payloads(engine.events[start:], "CONDITION_APPLIED") if str(p.get("condition_id")).endswith("beast_aspect_ox")]
    ended = [p for p in payloads(engine.events[start:], "CONDITION_REMOVED") if str(p.get("condition_id")).endswith("beast_aspect_wolf")]
    assert len(swapped) == 1 and ended


# ------------------------------------------------------------------------------------ Group 15: Hundred-Hand Battle Mandala
# plug-ins: combat/ext/hundred_hands.py (Battle Hands, Weapon Forms, the five features), combat/ext/grapple_attempts.py (shared),
# integrated_weapons.py group "one_handed_melee"; factory_compiler resource ``max_if_owned``
MANDALA = "tianxia.subpath.body.hundred_hand_battle_mandala.feature."
HANDS = "resource:named.battle_hand"
JIAN, GUN = "tianxia.mortal.weapon.jian", "tianxia.mortal.weapon.gun"


def _mandala(ids, *, picks=None, foe=None, foe_at=(4, 6), items=(JIAN, GUN)):
    made = sheet([MANDALA + k for k in ids], items=items)
    made["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]  # Body Refining's simple and martial weapons
    engine = fight(compile_character(made, actor_id=ME), foe=foe, foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[foe_id(engine)]


def _named_attack(engine, words, actor_id=ME):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == actor_id and a.economy.value == "ACTION"
                and (a.parameters.get("typed") or {}).get("weapon") and any(w in a.display_name.lower() for w in words)
                and "#" not in a.source_definition_id and "(" not in a.display_name.split(")", 1)[-1])


def test_battle_hands_are_proficiency_bonus_and_refresh_at_the_start_of_the_turn():
    engine, me, _foe = _mandala(["four_hand_sequence"])
    assert me.resources[HANDS] == 6 and me.resource_maximums[HANDS] == 6
    engine._spend_resource(me, HANDS, 4, "test")
    end_turns_until(engine, ME)
    assert me.resources[HANDS] == 6


def test_four_hand_sequence_spends_a_hand_after_a_hit_for_pb_damage_once_per_turn():
    engine, me, foe = _mandala(["four_hand_sequence"], picks={"four_hand_sequence": ["damage"]})
    foe.armor_class = -50
    first = use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[HANDS] == 5
    assert any(int(p.get("rolled_or_pending_damage") or 0) == 6 for p in payloads(first, "DAMAGE_COMMITTED"))
    me.action_available = True
    use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[HANDS] == 5  # once per turn


def _force_next_d20(engine, value):
    """Only the next raw d20 draw lands on ``value``; a rewrite applied to it afterwards is kept."""
    original = engine.roller.raw_d20

    def raw_d20(**kwargs):
        while True:
            roll = original(**kwargs)
            if int(roll.natural_result) == value:
                del engine.roller.raw_d20
                return roll
    engine.roller.raw_d20 = raw_d20


def test_four_hand_sequence_adds_pb_to_a_missed_attack_roll():
    engine, me, foe = _mandala(["four_hand_sequence"])
    _force_next_d20(engine, 10)
    bonus = next(a for a in engine.action_catalog.values() if a.display_name == unarmed(engine)).parameters["typed"]["numbers"]["attack_bonus"]
    foe.armor_class = 10 + bonus + 3  # misses by 3; + Proficiency Bonus 6 hits
    events = use(engine, unarmed(engine), target=foe.entity_id)
    assert payloads(events, "D20_REWRITTEN") and me.resources[HANDS] == 5
    assert payloads(events, "DAMAGE_COMMITTED")


def test_weapon_wheel_constitution_variant_and_advantage_for_a_different_form():
    engine, me, foe = _mandala(["weapon_wheel_body"], items=(JIAN, GUN))
    names = legal(engine)
    assert "Jian (Straight Sword) attack (Constitution)" in names and "Gun (Staff) attack (Constitution)" not in names  # one-handed only
    foe.armor_class = -50
    use(engine, unarmed(engine), target=foe.entity_id)
    me.action_available = True
    events = use(engine, "Jian (Straight Sword) attack", target=foe.entity_id)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 2  # Advantage: the Blade Form after the Unarmed one


def test_eight_limb_spends_two_hands_for_an_attack_with_another_form_then_a_completion():
    engine, me, foe = _mandala(["eight_limb_battle_pattern"], picks={"eight_limb_completion": ["prone|" + FOE]}, foe=_typed_foe())
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=FOE)
    rolled = payloads(events, "ATTACK_ROLLED")
    # With both weapons readied, only the one-handed Jian is usable. The
    # granted menu must not charge Hands for an impossible two-handed strike.
    assert len(rolled) == 2 and "weapon.jian" in rolled[1]["reason"] and me.resources[HANDS] == 4
    use(engine, "Stow Jian (Straight Sword) (frees 1 hand; no Action)")
    me.action_available = True
    use(engine, "Gun (Staff) attack", target=FOE)  # third Form: Polearm, with two hands now available
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())


def test_circle_of_uncounted_arms_deflecting_hand_turns_a_hit_into_a_miss():
    engine, me, foe = _mandala(["circle_of_uncounted_arms"], picks={"circle_of_uncounted_arms": ["deflect"]}, foe=_typed_foe())
    turn(engine, FOE)
    force_d20(engine, 10, 10)
    bonus = next(a for a in engine.action_catalog.values() if a.display_name == unarmed(engine, FOE)).parameters["typed"]["numbers"]["attack_bonus"]
    me.armor_class = 10 + bonus - 1  # the attack would hit by 1
    hp = me.current_hp
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.current_hp == hp and me.resources[HANDS] == 4 and not me.reaction_available


def test_thousand_hand_incarnation_doubles_hands_adds_reach_and_5d8_force_on_the_third_hit():
    engine, me, foe = _mandala(["four_hand_sequence", "thousand_hand_incarnation"], picks={"four_hand_sequence": None}, foe_at=(5, 6))
    use(engine, "Thousand-Hand Incarnation")
    assert me.resources[HANDS] == 12
    assert any(name.endswith("(extended reach)") for name in legal(engine))
    foe.position = Position(x=4, y=6)
    foe.armor_class = -50
    before = len(engine.rolls)
    for _ in range(3):
        me.action_available = True
        use(engine, unarmed(engine), target=foe.entity_id)
    force = [r for r in engine.rolls[before:] if r.expression.startswith("5d8")]
    assert len(force) == 1


def test_mandala_completion_after_four_hands_spent_this_turn():
    engine, me, foe = _mandala(["four_hand_sequence", "thousand_hand_incarnation"], picks={"four_hand_sequence": None,
                                                                                           "mandala_completion": ["guard"]})
    use(engine, "Thousand-Hand Incarnation")
    engine._spend_resource(me, HANDS, 4, "test:spent")
    foe.armor_class = -50
    ac = [m for m in me.modifiers.values() if m.target_field == "armor_class"]
    use(engine, unarmed(engine), target=foe.entity_id)
    assert len([m for m in me.modifiers.values() if m.target_field == "armor_class" and m.value == 3]) == 1 + len([m for m in ac if m.value == 3])


# ------------------------------------------------------------------------------------------------ Group 16: Hundred-Venom Body
# plug-in: combat/ext/hundred_venom.py (Venom Furnace, Sovereign Venoms, Swallow the Poison, Poisoned Body, Myriad-Venom);
# typed_reactions seam ``immunity_as_resistance``; path_riders unarmed_types ``add``
VENOM = "tianxia.subpath.body.hundred_venom_body.feature."


def _venom(ids, *, picks=None, foe=None, foe_at=(4, 6)):
    engine = fight(bundle([VENOM + k for k in ids]), foe=foe, foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[foe_id(engine)]


def _venom_names(target):
    return sorted((c.data or {}).get("venom") for c in target.conditions.values() if c.condition_id == "condition:typed.sovereign_venom")


def test_venom_furnace_is_a_paid_hit_rider_2d6_poison_and_a_poisoning_save():
    engine, me, foe = _venom(["venom_furnace"], picks={"path_hit." + VENOM + "venom_furnace": ["Use Venom Furnace"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=foe.entity_id)
    assert me.resources[STAMINA] == 59
    assert any(r.expression.startswith("2d6") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    assert any(c.condition_id.endswith("poisoned") for c in foe.conditions.values())  # DC 50
    assert not any(a.display_name.endswith("Venom Furnace") for a in engine.action_catalog.values() if a.owner_id == ME)  # no pre-paid variant


def test_three_sovereign_venoms_on_a_failed_save_and_blood_venom_at_its_turn_start():
    engine, me, foe = _venom(["venom_furnace", "three_sovereign_venoms"], picks={"path_hit." + VENOM + "venom_furnace": ["Use Venom Furnace"],
                                                                                 "sovereign_venom": ["blood"]}, foe=_typed_foe())
    foe.armor_class = -50
    use(engine, unarmed(engine), target=FOE)
    assert _venom_names(foe) == ["blood"]
    hp = foe.current_hp
    before = len(engine.rolls)
    end_turns_until(engine, FOE)
    assert foe.current_hp < hp and any(r.expression.startswith("2d6") for r in engine.rolls[before:])
    assert not any(c.condition_id == "condition:typed.blood_venom" for c in foe.conditions.values())


def test_a_new_sovereign_venom_replaces_the_old_one():
    engine, me, foe = _venom(["venom_furnace", "three_sovereign_venoms"], picks={"path_hit." + VENOM + "venom_furnace": ["Use Venom Furnace"],
                                                                                 "sovereign_venom": ["nerve"]}, foe=_typed_foe())
    foe.armor_class = -50
    use(engine, unarmed(engine), target=FOE)
    assert _venom_names(foe) == ["nerve"] and any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    from combat.ext.effect_durations import token
    venom_rows = [row for row in (*foe.conditions.values(), *foe.modifiers.values()) if row.source_definition_id == VENOM + "three_sovereign_venoms"]
    assert len(venom_rows) == 3  # the Venom, no Reactions, Disadvantage on its next attack roll
    assert {c.expires_on for c in venom_rows} == {token("end", ME, int(me.turns_started) + 1)}  # until the end of YOUR next turn
    answers(engine, {"path_hit." + VENOM + "venom_furnace": ["Use Venom Furnace"], "sovereign_venom": ["marrow"], "marrow_venom": ["Dexterity"]})
    end_turns_until(engine, ME)
    assert _venom_names(foe) == ["nerve"]  # until the end of your next turn
    use(engine, unarmed(engine), target=FOE)
    assert _venom_names(foe) == ["marrow"] and not any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert engine._effective_speed(foe) == 15  # 30 - 15


def test_swallow_the_poison_reduces_poison_damage_and_stores_the_adaptation_at_zero():
    engine, me, _foe = _venom(["swallow_the_poison", "venom_furnace"])
    hp = me.current_hp
    hostile_packet(engine, ME, 3, "POISON")
    assert me.current_hp == hp and me.resources[STAMINA] == 59  # 2d10 + 2 >= 3 (Resistance halves it first)
    assert any(c.condition_id == "condition:typed.venom_adaptation" for c in me.conditions.values())


def test_poisoned_body_poisoned_world_answers_a_hostile_hit_within_reach():
    engine, me, foe = _venom(["poisoned_body_poisoned_world", "three_sovereign_venoms"],
                             picks={"poisoned_body_poisoned_world": ["use"], "sovereign_venom": ["nerve"]}, foe=_typed_foe())
    turn(engine, FOE)
    me.armor_class = -50
    hp = foe.current_hp
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[STAMINA] == 59 and foe.current_hp < hp and _venom_names(foe) == ["nerve"]


def test_myriad_venom_poison_ignores_poison_immunity_and_venom_furnace_rolls_4d6():
    engine, me, foe = _venom(["venom_furnace", "three_sovereign_venoms", "poisoned_body_poisoned_world", "myriad_venom_immortal"],
                             picks={"path_hit." + VENOM + "venom_furnace": ["Use Venom Furnace"], "sovereign_venom": ["nerve", "blood"]},
                             foe=bundle([VENOM + "myriad_venom_immortal"], actor_id=FOE, name="Immune Foe"))
    foe.armor_class = -50
    hp = foe.current_hp
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("4d6") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    poison = [p for p in payloads(events, "DAMAGE_COMMITTED") if p.get("damage_type") == "POISON" and p.get("hp_damage")]
    assert poison and foe.current_hp < hp  # the Immune foe still takes the poison
    # "treats Poison Immunity as Resistance and then ignores it": the poison must land at full
    # damage, not halved by a shared gate that keeps every converted Immunity as Resistance.
    assert [int(p["reduced_to"]) for p in poison] == [int(p["rolled_or_pending_damage"]) for p in poison]
    assert _venom_names(foe) == ["blood", "nerve"]


def _poison_save(engine, dc, *, duration=None):
    """The foe forces a Constitution save whose failure Poisons (a typed save run by the foe)."""
    from combat import typed_executor as te
    from combat.ext.states import context

    ctx = context(engine, engine.state.actors[FOE], "test:venom_cloud", [engine.state.actors[ME]], {"save_dc": dc, "pb": 2, "cl": 1})
    candidate = next(iter(engine.legal_candidates()))
    ctx.intent = ActionIntent(intent_id=f"save-{len(engine.events)}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                              state_version=candidate.state_version, actor_id=FOE, target_ids=(ME,))
    engine._active_intent = ctx.intent  # the save happens inside a turn's action, where a player can be asked
    fail = {"type": "condition", "applies_to": "target", "condition": "poisoned", **({"duration": duration} if duration else {})}
    try:
        te.run_effects(ctx, [{"type": "save", "ability": "con", "on_fail": [fail], "on_success": []}])
    finally:
        engine._active_intent = None


def _swallow_row_types(engine):
    """The compiled Reaction: the reduction and the stored adaptation (the old typing also hit the attacker for PB Poison)."""
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get("feature_id") == VENOM + "swallow_the_poison")
    return [e.get("type") for e in row["effects"]]


def test_swallow_the_poison_adds_pb_to_a_failed_save_against_poison():
    engine, me, _foe = _venom(["swallow_the_poison"], foe=_typed_foe())
    assert _swallow_row_types(engine) == ["damage_modifier", "venom_adaptation"]
    _force_next_d20(engine, 10)
    _poison_save(engine, 16)  # 10 + 2 fails; + Proficiency Bonus 6 succeeds
    assert payloads(engine.events, "D20_REWRITTEN") and not me.reaction_available and me.resources[STAMINA] == 59
    assert not any(c.condition_id.endswith(".poisoned") for c in me.conditions.values())
    assert any(c.condition_id == "condition:typed.venom_adaptation" for c in me.conditions.values())


def test_swallow_the_poison_delays_poisoned_until_the_end_of_your_next_turn():
    engine, me, _foe = _venom(["swallow_the_poison"], foe=_typed_foe())
    assert _swallow_row_types(engine) == ["damage_modifier", "venom_adaptation"]
    _poison_save(engine, 50)
    assert not any(c.condition_id.endswith(".poisoned") for c in me.conditions.values()) and me.resources[STAMINA] == 59
    assert any(c.condition_id == "condition:typed.swallowed_poison" for c in me.conditions.values())
    end_turns_until(engine, ME)
    assert not any(c.condition_id.endswith(".poisoned") for c in me.conditions.values())
    end_turns_until(engine, FOE)  # the end of your next turn: it begins now, for its whole (unlimited) duration
    assert any(c.condition_id.endswith(".poisoned") for c in me.conditions.values())


# ------------------------------------------------------------------------------------------------------ Group 17: Iron Shirt
# plug-in: combat/ext/iron_shirt.py (Stamina Guard d12s, floor, maximum and Bell die; Iron Wall and Invincible Iron states)
SHIRT = "tianxia.subpath.body.iron_shirt.feature."


def _shirt(ids, *, picks=None, foe=None):
    engine = fight(bundle([SHIRT + k for k in ids] + [STAMINA_GUARD]), foe=foe)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME]


def _soaks(engine, start=0):
    return [p for p in payloads(engine.events[start:], "REACTION_RESOLVED") if p.get("checkpoint") == "DAMAGE_APPLICATION" and "spend" in p]


def test_iron_shirt_rolls_d12s_for_stamina_guard_and_gains_ac_when_it_stops_the_damage():
    engine, me = _shirt(["iron_shirt"])
    before = len(engine.rolls)
    hostile_packet(engine, ME, 8, "SLASHING")  # (seeded: the 2d12 stop all 8)
    assert me.current_hp == 120 and any(r.expression.startswith("2d12") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE_SOAK"))
    bonus = [m for m in me.modifiers.values() if m.source_definition_id == SHIRT + "iron_shirt" and m.target_field == "armor_class"]
    assert len(bonus) == 1 and bonus[0].value == 1


def test_iron_wall_resists_all_but_force_floors_stamina_guard_dice_and_forbids_dash():
    engine, me = _shirt(["iron_wall"])
    use(engine, "Iron Wall")
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert {"SLASHING", "FIRE", "POISON"} <= resisted and not {"FORCE", "PSYCHIC"} & resisted
    assert "Dash" not in legal(engine) and engine._effective_speed(me) == 20
    me.reaction_available = True
    start = len(engine.events)
    hostile_packet(engine, ME, 60, "FORCE")
    soak = _soaks(engine, start)[0]
    assert soak["reduction"] >= soak["spend"] * 6  # every die at least Proficiency Bonus


def test_bell_strike_answers_a_melee_miss_with_an_unarmed_strike_and_a_chosen_result():
    engine, me = _shirt(["bell_strike"], picks={"bell_strike": ["Stamina Guard die twice"]}, foe=_typed_foe())
    foe = engine.state.actors[FOE]
    turn(engine, FOE)
    me.armor_class, foe.armor_class = 99, -50
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")) == 2 and not me.reaction_available  # the miss, then Bell Strike's unarmed strike
    assert any(c.condition_id == "condition:typed.bell_strike_die" for c in me.conditions.values())


def test_invincible_iron_holds_at_one_hit_point_and_starts_iron_wall():
    engine, me = _shirt(["iron_wall", "invincible_iron"])
    me.current_hp = 5
    me.reaction_available = False  # Stamina Guard already spent
    hostile_packet(engine, ME, 40, "SLASHING")
    assert me.current_hp == 1 and me.resources[STAMINA] == 54
    from combat.ext.states import active

    assert active(engine, me, "iron_wall") and active(engine, me, "invincible_iron")
    assert me.resources["resource:uses.action:typed." + next(a for a in engine.action_catalog.values()
                                                             if a.display_name == "Iron Wall").source_definition_id.split("action:typed.", 1)[1]] == 1
    me.reaction_available = True
    start = len(engine.events)
    hostile_packet(engine, ME, 50, "FORCE")
    soak = _soaks(engine, start)[0]
    assert soak["reduction"] == soak["spend"] * 10  # Stamina Guard dice roll their maximum


# ---------------------------------------------------------------------------------------------------------- Group 18: Jigoku
# plug-in: combat/ext/jigoku.py (Eat the Flame, Pain Eater, Burning Brand, Hellwalker, Asura's Rage); Hell-Tempered's Fire
# Resistance: combat/rules/feature_blocks.d/riders_c7.json
JIGOKU = "tianxia.subpath.body.jigoku.feature."


def _jigoku(ids, *, picks=None, foe=None):
    engine = fight(bundle([JIGOKU + k for k in ids]), foe=foe or _typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _foe_deals(engine, amount, kind):
    """The typed foe deals one damage packet to the fighter (a typed damage effect, so damage_dealt answers it)."""
    from combat import typed_executor as te
    from combat.ext.states import context

    te.run_effects(context(engine, engine.state.actors[FOE], "test:foe_damage", [engine.state.actors[ME]], {"pb": 2, "cl": 1, "save_dc": 10}),
                   [{"type": "damage", "applies_to": "target", "flat": amount, "damage_types": [kind]}])


def test_hell_tempered_resists_fire_and_eats_the_flame_for_temporary_hit_points():
    engine, me, _foe = _jigoku(["hell_tempered"])
    hp = me.current_hp
    _foe_deals(engine, 10, "fire")
    assert hp - me.current_hp == 5  # Resistance
    assert me.temporary_hp == 5 and me.resources[STAMINA] == 59 and not me.reaction_available


def test_pain_eater_marks_the_attacker_and_the_next_unarmed_hit_spends_it():
    engine, me, foe = _jigoku(["pain_eater"], picks={"pain_eater_benefit": ["no_reactions"]})
    _foe_deals(engine, 5, "slashing")
    assert any(c.condition_id == "condition:typed.pain_eater_mark" for c in foe.conditions.values())
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=FOE)
    assert any(int(p.get("rolled_or_pending_damage") or 0) == 6 for p in payloads(events, "DAMAGE_COMMITTED"))
    assert not any(c.condition_id == "condition:typed.pain_eater_mark" for c in foe.conditions.values())
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_burning_brand_burns_at_the_start_of_each_turn_until_saved_or_put_out():
    engine, me, foe = _jigoku(["flame_fist"], picks={"path_hit." + JIGOKU + "flame_fist": ["Use Burning Brand"]})
    foe.armor_class = -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    burning = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.burning"]
    assert len(burning) == 1 and burning[0].data["brand_dice"] == 2 and burning[0].data["burn"] == 0  # CL18: 2d8
    before = len(engine.rolls)
    end_turns_until(engine, FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    assert "Extinguish flames" in legal(engine)


def test_hellwalker_start_of_turn_choice_beside_fire():
    from combat.gate2_runtime_models import ZoneState
    from combat.zones import KIND

    engine, me, _foe = _jigoku(["hellwalker"], picks={"hellwalker": ["temp_hp"]})
    engine.state.zones["zone:test.fire"] = ZoneState(zone_id="zone:test.fire", source_definition_id="test:fire_field", owner_id=FOE,
                                                     center=Position(x=2, y=6), radius_cells=0, affected_cells=(Position(x=2, y=6),),
                                                     concentration_link=False, created_round=1,
                                                     trigger_profile={"kind": KIND, "name": "Fire Field", "terrain": ["fire"]})
    end_turns_until(engine, ME)
    assert me.temporary_hp == 6


def test_asuras_rage_advantage_resistance_3d6_and_its_ending():
    engine, me, foe = _jigoku(["hell_tempered", "asura_s_rage"])
    use(engine, "Asura's Rage")
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert {"SLASHING", "PSYCHIC"} <= resisted and not {"FORCE", "RADIANT"} & resisted
    foe.armor_class = -50
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 2
    assert any(r.expression.startswith("3d6") for r in engine.rolls[before:])
    from combat.ext.states import PREFIX

    rage = next(c for c in me.conditions.values() if c.condition_id == PREFIX + "asura_s_rage")
    from combat.ext.effect_durations import token

    rage.expires_on = token("end", ME, me.turns_started)  # the minute is over at the end of this turn
    end_turns_until(engine, FOE)
    assert any(c.condition_id == "condition:typed.exhaustion" for c in me.conditions.values())
    assert any(c.condition_id == "condition:typed.eat_the_flame_spent" for c in me.conditions.values())


# --------------------------------------------------------------------------------------------------------- Group 19: Jujutsu
# plug-in: combat/ext/jujutsu.py (Redirect Force, Gentle Fist, Throw, Empty Body); Harmonious Body is lane H2's
JUJUTSU = "tianxia.subpath.body.jujutsu.feature."


def _jujutsu(ids, *, picks=None):
    engine = fight(bundle([JUJUTSU + k for k in ids]), foe=_typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _foe_misses_me(engine, me):
    turn(engine, FOE)
    me.armor_class = 99
    return use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)


def test_redirect_force_answers_a_melee_miss_with_the_chosen_redirection():
    engine, me, foe = _jujutsu(["redirect_force"], picks={"redirect_force": ["advantage"]})
    _foe_misses_me(engine, me)
    assert not me.reaction_available
    assert any(c.condition_id == "condition:typed.redirect_force_advantage" for c in foe.conditions.values())
    turn(engine, ME)
    events = use(engine, "Grapple", target=FOE)
    assert len(payloads(events, "SAVE_ROLLED")[0]["dice"]) == 2  # its save against your Grapple has Disadvantage
    assert not any(c.condition_id == "condition:typed.redirect_force_advantage" for c in foe.conditions.values())


def test_gentle_fist_deals_no_damage_and_imposes_two_effects_on_a_failed_save():
    engine, me, foe = _jujutsu(["gentle_fist"], picks={"gentle_fist": ["gentle"], "gentle_fist_effects": ["speed", "reactions"]})
    foe.armor_class = -50
    hp = foe.current_hp
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert foe.current_hp == hp and me.resources[STAMINA] == 59  # DC 50: failed
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert engine._effective_speed(foe) == 15


def test_throw_needs_your_grapple_and_throws_on_a_failed_save():
    engine, me, foe = _jujutsu(["throw"])
    assert "Throw" not in legal(engine)
    assert _grapple(engine, FOE)
    assert any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    me.bonus_action_available = True
    before = len(engine.rolls)
    use(engine, "Throw", target=FOE)
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert not any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    assert engine.grid.distance_ft(foe.position, me.position) > 5  # thrown to a chosen open space


def test_empty_body_redirect_force_without_the_reaction_and_opportunity_disadvantage():
    engine, me, foe = _jujutsu(["redirect_force", "empty_body"], picks={"redirect_force": ["advantage"], "empty_body_step": None,
                                                                        "empty_body_redirect": None})
    use(engine, "Empty Body")
    _foe_misses_me(engine, me)
    assert me.reaction_available  # Redirect Force without spending the Reaction
    assert any(c.condition_id == "condition:typed.redirect_force_advantage" for c in foe.conditions.values())
    from combat.ext.states import active

    assert active(engine, me, "empty_body")


# ---------------------------------------------------------------------------------------------------------- Group 20: Karate
# plug-in: combat/ext/karate.py (Focused Strike, Perfect Breath, Mushin); Precision Strike and Isshun Sengeki are typed
KARATE = "tianxia.subpath.body.karate.feature."


def _karate(ids, *, picks=None, foe=None):
    engine = fight(bundle([KARATE + k for k in ids] + ["tianxia.path.body_refining.feature.stomping_step"]), foe=foe or _typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_focused_strike_rolls_one_iron_fist_die_again_once_per_turn():
    engine, me, foe = _karate(["focused_strike"])
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert len([r for r in engine.rolls[before:] if str(r.reason).startswith("FOCUSED_STRIKE")]) == 1
    me.action_available = True
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert not [r for r in engine.rolls[before:] if str(r.reason).startswith("FOCUSED_STRIKE")]


def test_perfect_breath_after_stomping_step_ignores_one_disadvantage_and_adds_pb():
    engine, me, foe = _karate(["perfect_breath"], picks={"perfect_breath": ["guard"]})
    use(engine, "Stomping Step")
    engine._apply_condition(me, "condition:typed.poisoned", "test:poison", FOE, expires_on="UNTIL_REMOVED")
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 1  # Poisoned's Disadvantage ignored for this attack
    assert any(int(p.get("rolled_or_pending_damage") or 0) == 6 for p in payloads(events, "DAMAGE_COMMITTED"))
    assert any(c.condition_id == "condition:typed.perfect_breath_guard" for c in me.conditions.values())
    me.action_available = True
    again = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(again, "ATTACK_ROLLED")[0]["dice"]) == 2  # the next one has its Disadvantage again


def test_precision_strike_asks_the_area_and_the_leg_slows():
    engine, me, foe = _karate(["precision_strike"], picks={"path_hit." + KARATE + "precision_strike": ["Leg"]})
    foe.armor_class = -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 58 and engine._effective_speed(foe) == 20


def test_mushin_first_attack_of_the_first_round_has_advantage():
    engine, me, foe = _karate(["mushin"])
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 2
    me.action_available = True
    assert len(payloads(use(engine, unarmed(engine), target=FOE), "ATTACK_ROLLED")[0]["dice"]) == 1


def test_isshun_sengeki_is_one_unarmed_strike_with_10d10_force_and_a_failed_save_choice():
    engine, me, foe = _karate(["isshun_sengeki"], picks={"isshun_sengeki": ["Speed 0 until the start of its next turn"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    events = use(engine, "Isshun Sengeki", target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")) == 1 and me.resources[STAMINA] == 52
    assert any(r.expression.startswith("10d10") for r in engine.rolls[before:]) and any(r.expression.startswith("2d6") for r in engine.rolls[before:])
    assert engine._effective_speed(foe) == 0


# ---------------------------------------------------------------------------------------------------------- Group 21: Kensei
# plug-in: combat/ext/kensei.py (asked Blade Fist and Severing Palm, the stances, Sword Draws); integrated_weapons "blade"
KENSEI = "tianxia.subpath.body.kensei.feature."


def _kensei(ids, *, picks=None, items=(), dex=2):
    made = sheet([KENSEI + k for k in ids], items=items, mods={"DEX": dex})
    made["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]
    engine = fight(compile_character(made, actor_id=ME), foe=_typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_blade_fist_is_asked_on_the_hit_and_gives_dexterity_and_blade_variants():
    engine, me, foe = _kensei(["blade_fist"], picks={"blade_fist": ["reactions"]}, items=("tianxia.mortal.weapon.dao",), dex=4)
    names = legal(engine)
    assert {"Unarmed Strike (Iron Fist) (Dexterity)", "Dao (Saber / Broadsword) attack (Constitution)", "Dao (Saber / Broadsword) attack (Dexterity)"} <= names
    foe.armor_class = -50
    use(engine, unarmed(engine), target=FOE)
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_severing_palm_is_asked_and_arm_lasts_to_the_end_of_your_next_turn():
    assert riders(KENSEI + "severing_palm") == []  # no longer a description of an automatic 4-Stamina spend
    engine, me, foe = _kensei(["severing_palm"], picks={"severing_palm": ["arm"]})
    foe.armor_class = -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    arm = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.severing_arm"]
    assert me.resources[STAMINA] == 56 and len(arm) == 1
    assert arm[0].source_actor_id == ME and arm[0].expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"
    engine2, me2, foe2 = _kensei(["severing_palm"], picks={"severing_palm": None})
    foe2.armor_class = -50
    script(engine2, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine2, unarmed(engine2), target=FOE)
    assert me2.resources[STAMINA] == 60  # declined: no Stamina spent


def test_flowing_blade_stance_answers_a_melee_miss_with_a_reaction_attack():
    engine, me, foe = _kensei(["flowing_blade_stance"])
    use(engine, "Flowing Blade Stance")
    assert any(m.target_field == "armor_class" and m.value == 1 for m in me.modifiers.values())
    turn(engine, FOE)
    me.armor_class = 99
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")) == 2 and not me.reaction_available


def test_sword_draws_before_thought_is_chosen_at_the_first_turn():
    engine, me, foe = _kensei(["sword_draws_before_thought"])
    assert any(c.condition_id == "condition:typed.sword_draws_first_attack" for c in me.conditions.values())
    foe.armor_class = -50
    events = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 2


def test_sword_saint_reach_save_3d8_and_the_asked_result():
    engine, me, foe = _kensei(["sword_saint_incarnation"], picks={"sword_saint": ["Speed -10"]})
    foe.position = Position(x=5, y=6)  # 10 feet: beyond base reach, within Sword Saint reach
    use(engine, "Sword Saint Incarnation")
    assert any(name.endswith("(extended reach)") for name in legal(engine))
    hp = foe.current_hp
    before = len(engine.rolls)
    end_turns_until(engine, FOE)  # the foe starts its turn in your reach
    assert foe.current_hp < hp and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    assert engine._effective_speed(foe) == 20


# -------------------------------------------------------------------------------------------------------- Group 22: Kukishin
# plug-in: combat/ext/kukishin.py (Empty Strike damage, Phase Flesh, Hollow Step, Soul Severance, Hollow Immortal)
KUKISHIN = "tianxia.subpath.body.kukishin.feature."


def _kukishin(ids, *, picks=None):
    engine = fight(bundle([KUKISHIN + k for k in ids]), foe=_typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_empty_strike_adds_2d8_and_the_chosen_result():
    engine, me, foe = _kukishin(["empty_strike"], picks={"path_hit." + KUKISHIN + "empty_strike": ["No Reactions"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and any(r.expression.startswith("2d8") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_phase_flesh_halves_an_attacks_damage_without_hurting_you_and_eases_escapes():
    engine, me, foe = _kukishin(["phase_flesh"])
    turn(engine, FOE)
    me.armor_class = -50
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    soak = next(p for p in payloads(events, "REACTION_RESOLVED") if p.get("checkpoint") == "DAMAGE_APPLICATION")
    assert soak["pending_after"] == soak["pending_before"] // 2  # halved
    assert not [p for p in payloads(events, "DAMAGE_COMMITTED") if p.get("damage_type") == "FORCE"]  # no 2d10 Force on yourself
    assert me.resources[STAMINA] == 58 and any(c.condition_id == "condition:typed.phase_flesh" for c in me.conditions.values())
    from combat.ext.kukishin import phase_escape

    assert phase_escape(engine, me, {}) == "ADVANTAGE"


def test_hollow_step_invisible_then_the_first_attack_next_turn_has_advantage_and_2d8():
    engine, me, foe = _kukishin(["hollow_step"])
    use(engine, "Hollow Step")
    assert any(c.condition_id == "condition:typed.invisible" for c in me.conditions.values()) and me.resources[STAMINA] == 57
    end_turns_until(engine, ME)
    foe.armor_class = -50
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")[0]["dice"]) == 2 and any(r.expression.startswith("2d8") for r in engine.rolls[before:])
    me.action_available = True
    assert len(payloads(use(engine, unarmed(engine), target=FOE), "ATTACK_ROLLED")[0]["dice"]) == 1


def test_soul_severance_stuns_until_the_end_of_your_next_turn_once_a_fight():
    engine, me, foe = _kukishin(["soul_severance"], picks={"path_hit." + KUKISHIN + "soul_severance": ["Use Soul Severance"]})
    foe.armor_class = -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    stunned = [c for c in foe.conditions.values() if c.condition_id.endswith("stunned")]
    assert me.resources[STAMINA] == 55 and stunned and stunned[0].expires_on.endswith(f"{ME}:{me.turns_started + 1}")
    end_turns_until(engine, ME)
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 55  # once per fight


def test_empty_world_incarnation_resists_frees_hollow_step_and_refuses_a_grapple():
    engine = fight(bundle([KUKISHIN + "hollow_step", KUKISHIN + "hollow_immortal"]),
                   foe=bundle(["tianxia.path.body_refining.feature.iron_fist", "TAL_THE_HIDDEN_EYE_TRUE_SIGHT"], actor_id=FOE))
    answers(engine)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Hollow Immortal")
    assert me.resources[STAMINA] == 53
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert "SLASHING" in resisted and "FORCE" not in resisted
    me.bonus_action_available = True
    use(engine, "Hollow Step (Empty-World)")
    assert me.resources[STAMINA] == 53
    turn(engine, FOE)
    me.position, foe.position = Position(x=3, y=6), Position(x=4, y=6)  # restore melee reach after the chosen teleport
    from combat import senses
    assert senses.sees_hidden(engine, foe, me)  # True Sight makes this an actual Grapple attempt against Invisible
    use(engine, "Grapple", target=ME, actor_id=FOE)
    assert not any(c.condition_id.endswith(".grappled") for c in me.conditions.values())


# ---------------------------------------------------------------------------------------------------- Group 23: Mantis Style
# plug-in: combat/ext/mantis_style.py (Mantis Hooks, Joint Lock, Rapid Pincer, Eye of the Mantis); Death of a Thousand Cuts
MANTIS = "tianxia.subpath.body.mantis_style.feature."


def _mantis(ids, *, picks=None):
    engine = fight(bundle([MANTIS + k for k in ids]), foe=_typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _grappled_by_me(foe):
    return any(c.condition_id.endswith(".grappled") and c.source_actor_id == ME for c in foe.conditions.values())


def test_mantis_hooks_grapples_on_a_hit_and_the_light_blow_deals_only_the_modifier():
    engine, me, foe = _mantis(["mantis_hooks"], picks={"mantis_hooks": ["grapple"], "mantis_hooks_light": ["light"]})
    foe.armor_class = -50
    hp = foe.current_hp
    events = use(engine, unarmed(engine), target=FOE)
    strike = next(p for p in payloads(events, "DAMAGE_COMMITTED"))
    assert strike["reduced_to"] <= 2 and _grappled_by_me(foe)  # ability modifier 2; DC 50
    saves = payloads(events, "SAVE_ROLLED")
    assert saves and len(saves[-1]["dice"]) == 2  # the light blow: Disadvantage on the Grapple save


def test_joint_lock_needs_your_grapple_and_restrains_until_it_ends():
    engine, me, foe = _mantis(["joint_lock"])
    assert "Joint Lock" not in legal(engine)
    assert _grapple(engine, FOE) and _grappled_by_me(foe)
    me.bonus_action_available = True
    use(engine, "Joint Lock", target=FOE)
    assert me.resources[STAMINA] == 59 and any(c.condition_id == "condition:typed.restrained" for c in foe.conditions.values())
    use(engine, "Release grapple")
    assert not any(c.condition_id == "condition:typed.restrained" for c in foe.conditions.values())


def test_rapid_pincer_adds_one_unarmed_strike_once_per_turn():
    engine, me, foe = _mantis(["rapid_pincer"])
    foe.armor_class = -50
    events = use(engine, unarmed(engine) + " (Rapid Pincer)", target=FOE)
    assert len(payloads(events, "ATTACK_ROLLED")) == 2
    me.action_available = True
    assert unarmed(engine) + " (Rapid Pincer)" not in legal(engine)


def test_eye_of_the_mantis_reveals_the_target_and_gives_advantage_on_the_first_attack_each_turn():
    engine, me, foe = _mantis(["eye_of_the_mantis"])
    events = use(engine, "Eye of the Mantis", target=FOE)
    assert me.resources[STAMINA] == 57 and any("Eye of the Mantis on" in str(p.get("log")) for p in payloads(events, "PASSIVE_TRIGGERED"))
    foe.armor_class = -50
    first = use(engine, unarmed(engine), target=FOE)
    assert len(payloads(first, "ATTACK_ROLLED")[0]["dice"]) == 2
    me.action_available = True
    assert len(payloads(use(engine, unarmed(engine), target=FOE), "ATTACK_ROLLED")[0]["dice"]) == 1


def test_death_of_a_thousand_cuts_6d6_and_the_chosen_rider():
    engine, me, foe = _mantis(["death_of_a_thousand_cuts"], picks={"path_hit." + MANTIS + "death_of_a_thousand_cuts": ["Speed 0"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 56 and any(r.expression.startswith("6d6") for r in engine.rolls[before:])
    assert engine._effective_speed(foe) == 0


# ------------------------------------------------------------------------------------------ Group 24: Nine-Star Meridian Body
# plug-ins: combat/ext/nine_star.py (Star-Lit, Orbital, Constellation, Incarnation), combat/ext/subpath_pools.py (Celestial Marks)
NINE = "tianxia.subpath.body.nine_star_meridian_body.feature."
MARKS = "resource:named.celestial_mark"


def _nine(ids, *, picks=None, marks=None, foe_at=(4, 6)):
    engine = fight(bundle([NINE + k for k in ids] + [STAMINA_GUARD]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me = engine.state.actors[ME]
    if marks is not None:
        engine._gain_resource(me, MARKS, max(0, marks - me.resources[MARKS]), "test") if marks > me.resources[MARKS] else engine._spend_resource(me, MARKS, me.resources[MARKS] - marks, "test")
    return engine, me, engine.state.actors[FOE]


def test_celestial_marks_one_at_initiative_and_one_a_round_after_a_stamina_activation():
    engine, me, foe = _nine(["star_lit_acupoints", "nine_star_incarnation"])
    assert me.resources[MARKS] == 1 and me.resource_maximums[MARKS] == 6  # Initiative; maximum Proficiency Bonus
    hostile_packet(engine, ME, 10, "SLASHING")  # Stamina Guard spends Stamina: a Body Refining Path feature
    assert me.resources[MARKS] == 2
    me.reaction_available = True
    hostile_packet(engine, ME, 10, "SLASHING")
    assert me.resources[MARKS] == 2  # once per round


def test_star_lit_acupoints_spends_a_mark_for_1d8_and_ac_against_the_target():
    engine, me, foe = _nine(["star_lit_acupoints"], picks={"path_hit." + NINE + "star_lit_acupoints": ["+1 AC against it"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[MARKS] == 0 and any(r.expression.startswith("1d8") for r in engine.rolls[before:])
    assert any(c.condition_id == "condition:typed.ac_against" and c.data["against"] == FOE for c in me.conditions.values())


def test_orbital_body_reduces_the_hit_and_moves_you_afterward():
    engine, me, foe = _nine(["orbital_body"], picks={"orbital_body_move": ["cell:1,6"]})
    turn(engine, FOE)
    me.armor_class = -50
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[MARKS] == 0 and (me.position.x, me.position.y) == (1, 6)


def test_falling_star_descent_lands_and_crashes_down_on_the_creatures_around():
    engine, me, foe = _nine(["falling_star_descent"], marks=3, foe_at=(10, 6))
    before = len(engine.rolls)
    use(engine, "Falling-Star Descent", at=(9, 6))
    # 3 Marks spent; its 2 Stamina on a Subpath feature earn the round's Mark back once it resolves.
    assert (me.position.x, me.position.y) == (9, 6) and me.resources[MARKS] == 1 and me.resources[STAMINA] == 58
    assert any(r.expression.startswith("6d8") for r in engine.rolls[before:]) and any(c.condition_id.endswith("prone") for c in foe.conditions.values())


def test_constellation_circuit_maximum_initiative_three_and_the_overflow_benefit():
    engine, me, foe = _nine(["constellation_circuit"], picks={"constellation_overflow": ["temp_hp"]})
    assert me.resources[MARKS] == 3 and me.resource_maximums[MARKS] == 9
    engine._gain_resource(me, MARKS, 6, "test")
    hostile_packet(engine, ME, 10, "SLASHING")  # a Mark at maximum
    end_turns_until(engine, ME)
    assert me.temporary_hp == 6


def test_nine_star_incarnation_4d8_once_and_the_strength_save_push():
    engine, me, foe = _nine(["nine_star_incarnation"], marks=5, picks={"nine_star_pull": ["away"]})
    use(engine, "Nine-Star Incarnation")
    assert me.resources[MARKS] == 1 and me.resources[STAMINA] == 54  # 5 spent, then the round's Stamina Mark
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("4d8") for r in engine.rolls[before:]) and any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert engine.grid.distance_ft(me.position, foe.position) >= 20


# -------------------------------------------------------------------------------------------------------- Group 25: Oni Blood
# plug-in: combat/ext/oni_blood.py (Mask/Form states, Blood Hunger, Blood Drinker, Crimson Oni)
ONI = "tianxia.subpath.body.oni_blood.feature."


def _oni(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([ONI + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_oni_mask_1d6_once_per_turn_and_ends_for_free():
    engine, me, foe = _oni(["oni_mask"])
    use(engine, "Oni Mask")
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("1d6") for r in engine.rolls[before:])
    use(engine, "End Oni Mask")
    from combat.ext.states import active

    assert not active(engine, me, "oni_mask") and "End Oni Mask" not in legal(engine)


def test_blood_hunger_restrain_failure_keeps_moves_toward_the_foe():
    engine, me, foe = _oni(["oni_mask"], picks={"blood_hunger": ["restrain"]}, foe_at=(8, 6))
    use(engine, "Oni Mask")
    foe.current_hp = 400  # Bloodied (1000 maximum)
    me.saving_throws = {**me.saving_throws, "WIS": -30}  # the restraining save fails
    end_turns_until(engine, ME)
    assert any(c.condition_id == "condition:typed.blood_hunger" for c in me.conditions.values())
    moves = {c.destination.x for c in engine.legal_candidates() if getattr(c.kind, "value", c.kind) == "MOVE" and c.destination is not None and c.destination.y == 6}
    assert moves and min(moves) >= 3  # never ending farther from the foe (at x=8) than where it starts (x=3)


def _two_foe_fight(me_bundle):
    """A yard with two typed foes, so dropping one does not end the fight."""
    from combat.gate2_runtime_content import AN  # noqa: F401 -- same roster shape as fight()

    foe2 = "actor:factory.c7foe2"
    foes = (bundle([], actor_id=FOE, name="C7 Foe"), bundle([], actor_id=foe2, name="C7 Foe Two"))
    document = normalize_map({"display_name": "C7 yard", "width_squares": 20, "height_squares": 14, "objects": [],
                              "starts": {"team1": [[3, 6]], "team2": [[4, 6], [12, 12]]}})
    engine = Gate4ControllerEngine(ROOT, match_seed="C7", typed_bundles=(me_bundle, *foes), battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": [ME, FOE, foe2], "team_by_actor": {ME: "team:a", FOE: "team:b", foe2: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, foe2: {"x": 12, "y": 12}}})
    turn(engine, ME)
    for fid in (FOE, foe2):
        engine.state.actors[fid].maximum_hp = engine.state.actors[fid].current_hp = 1000
    return engine


def test_blood_drinker_temporary_hp_on_a_bloodied_foe_and_healing_on_the_drop():
    engine = _two_foe_fight(bundle([ONI + "oni_mask", ONI + "blood_drinker"]))
    answers(engine, {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Oni Mask")
    foe.armor_class, foe.current_hp = -50, 400
    use(engine, unarmed(engine), target=FOE)
    assert me.temporary_hp == 6
    me.current_hp, foe.current_hp = 100, 3
    turn(engine, ME)
    use(engine, unarmed(engine), target=FOE)
    assert foe.current_hp == 0 and me.current_hp == 108  # CON 2 + PB 6


def test_oni_form_takes_the_mask_2d6_reach_resistance_and_strength():
    # Oni Form is Large: place the target beyond its ordinary footprint reach.
    engine, me, foe = _oni(["oni_mask", "oni_form"], foe_at=(6, 6))
    use(engine, "Oni Form")
    from combat.ext.states import active

    assert active(engine, me, "oni_mask") and me.resources[STAMINA] == 54 and me.temporary_hp == 36
    assert {"COLD", "FIRE", "NECROTIC"} <= {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert any(name.endswith("(extended reach)") for name in legal(engine))
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine) + " (extended reach)", target=FOE)
    assert any(r.expression.startswith("2d6+0") for r in engine.rolls[before:] if "iron_fist_sphere:" not in str(r.reason))


def test_crimson_oni_replaces_the_drop_with_half_hit_points_and_the_form():
    engine, me, foe = _oni(["oni_form", "crimson_oni"])
    me.current_hp = 5
    me.reaction_available = False
    hostile_packet(engine, ME, 40, "SLASHING")
    from combat.ext.states import active

    assert me.current_hp == 60 and me.resources[STAMINA] == 54 and active(engine, me, "crimson_oni_form") and active(engine, me, "oni_form")


def test_demon_roar_bloodied_creatures_save_with_disadvantage():
    fail = mechanics()[ONI + "demon_roar"]["effects"][0]["on_fail"]
    assert any(row.get("repeat_save") for row in fail)  # Frightened repeats its save at the end of each turn
    engine, me, foe = _oni(["demon_roar"], foe_at=(5, 6))
    foe.current_hp = 400
    events = use(engine, "Demon Roar", at=(5, 6))
    # Owner precedence: unscoped harmful areas affect enemies only.
    # The Bloodied enemy still has Disadvantage; the owner makes no save.
    saves = {event.actor_id: event.payload for event in events if event.event_type == "SAVE_ROLLED"}
    assert len(saves[foe.entity_id]["dice"]) == 2 and me.entity_id not in saves
    assert me.resources[STAMINA] == 55


# ------------------------------------------------------------------------------------------- Group 26: Phoenix Rebirth Body
# plug-ins: combat/ext/phoenix_rebirth.py (Cinder Blood, Flame-Wing Rush, Rebirth from Cinders), subpath_pools (Rebirth Embers),
# d20_rewrite_rules (Ash-Shedding Reversal's step and Furnace's Paralyzed/Stunned/Petrified responses)
PHOENIX = "tianxia.subpath.body.phoenix_rebirth_body.feature."
EMBERS = "resource:named.rebirth_ember"


def _phoenix(ids, *, picks=None, embers=0):
    engine = fight(bundle([PHOENIX + k for k in ids]), foe=_typed_foe())
    answers(engine, picks or {})
    me = engine.state.actors[ME]
    if embers:
        engine._gain_resource(me, EMBERS, embers, "test")
    return engine, me, engine.state.actors[FOE]


def test_rebirth_embers_come_from_hostile_damage_of_at_least_pb_once_a_round():
    engine, me, foe = _phoenix(["cinder_blood"])
    assert me.resources[EMBERS] == 0 and me.resource_maximums[EMBERS] == 6
    hostile_packet(engine, ME, 5, "SLASHING", attacker_id=FOE)
    assert me.resources[EMBERS] == 0  # less than Proficiency Bonus
    hostile_packet(engine, ME, 8, "SLASHING", attacker_id=FOE)
    hostile_packet(engine, ME, 8, "SLASHING", attacker_id=FOE)
    assert me.resources[EMBERS] == 1  # once per round


def test_cinder_blood_heals_for_an_ember_and_flame_wing_rush_follows():
    engine, me, foe = _phoenix(["cinder_blood", "flame_wing_rush"], embers=2, picks={"cinder_blood": ["heal"], "flame_wing_move": None})
    me.current_hp = 50
    before = len(engine.rolls)
    end_turns_until(engine, ME)
    assert me.resources[EMBERS] == 1 and me.current_hp > 50 and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    foe.armor_class = -50
    start = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[start:])


def test_ash_shedding_reversal_rerolls_for_two_embers_and_steps_on_a_success():
    engine, me, foe = _phoenix(["ash_shedding_reversal"], embers=3, picks={"ash_shedding_step": ["cell:2,6"]})
    assert riders(PHOENIX + "ash_shedding_reversal") == []
    _force_next_d20(engine, 1)
    _poison_save(engine, 12)
    assert payloads(engine.events, "D20_REWRITTEN") and me.resources[EMBERS] == 1
    assert not any(c.condition_id.endswith(".poisoned") for c in me.conditions.values())  # (seeded) the reroll succeeds
    assert (me.position.x, me.position.y) == (2, 6)


def test_rebirth_from_cinders_rises_at_half_hit_points_and_bursts():
    engine, me, foe = _phoenix(["rebirth_from_cinders"], embers=4, picks={"rebirth_move": None})
    me.current_hp = 5
    engine._apply_condition(me, "condition:typed.poisoned", "test:poison", FOE, expires_on="UNTIL_REMOVED")
    hp = foe.current_hp
    hostile_packet(engine, ME, 40, "SLASHING", attacker_id=FOE)
    assert me.current_hp == 60 and me.resources[EMBERS] == 0 and me.resources[STAMINA] == 54
    assert not any(c.condition_id.endswith(".poisoned") for c in me.conditions.values()) and foe.current_hp < hp


# ------------------------------------------------------------------------------------ Group 27: Returning-Heaven Momentum Body
# plug-ins: combat/ext/momentum_body.py (Gather and Return, Store Movement, Heaven-Returning Impact), subpath_pools (Momentum);
# typed_executor seam forced_movement_bonus
RH = "tianxia.subpath.body.returning_heaven_momentum_body.feature."
MOMENTUM = "resource:named.momentum"


def _momentum(ids, *, picks=None, momentum=0, foe_at=(4, 6), foe=None):
    engine = fight(bundle([RH + k for k in ids] + [STAMINA_GUARD]), foe=foe or _typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me = engine.state.actors[ME]
    if momentum:
        engine._gain_resource(me, MOMENTUM, momentum, "test")
    return engine, me, engine.state.actors[FOE]


def test_momentum_from_a_20_foot_move_once_a_round_up_to_pb():
    engine, me, foe = _momentum(["gather_and_return"], foe_at=(12, 12))
    assert me.resources[MOMENTUM] == 0 and me.resource_maximums[MOMENTUM] == 6
    use(engine, "Move to 7,6")
    assert me.resources[MOMENTUM] == 1
    hostile_packet(engine, ME, 12, "SLASHING", attacker_id=FOE)
    assert me.resources[MOMENTUM] == 1  # once per round


def test_gather_and_return_spends_momentum_for_dice_and_the_next_push():
    engine, me, foe = _momentum(["gather_and_return"], momentum=2, picks={"gather_and_return": ["push"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[MOMENTUM] == 1 and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    assert (foe.position.x, foe.position.y) == (5, 6)


def test_store_the_collision_stores_a_push_and_gains_momentum():
    push_foe = bundle([], actor_id=FOE, name="C7 Foe")
    engine, me, foe = _momentum(["store_the_collision"], picks={"store_the_collision_move": ["store"]}, foe=push_foe)
    turn(engine, FOE)
    use(engine, "Shove: Push 5 ft", target=ME, actor_id=FOE)
    assert (me.position.x, me.position.y) == (3, 6) and me.resources[MOMENTUM] == 1 and me.resources[STAMINA] == 59 and not me.reaction_available


def test_avalanche_doubles_the_normal_grant_and_raises_the_maximum():
    engine, me, foe = _momentum(["gather_and_return", "avalanche_meridian_circuit"], foe_at=(12, 12))
    assert me.resource_maximums[MOMENTUM] == 9
    use(engine, "Move to 7,6")
    assert me.resources[MOMENTUM] == 2


def test_heaven_returning_impact_charges_down_the_line():
    engine, me, foe = _momentum(["heaven_returning_impact"], momentum=4, foe_at=(8, 7))
    before = len(engine.rolls)
    events = use(engine, "Heaven-Returning Impact", at=(9, 7))
    assert (me.position.x, me.position.y) == (9, 7) and me.resources[MOMENTUM] == 0 and me.resources[STAMINA] == 55
    rest = sum(p["amount"] for p in payloads(events, "RESOURCE_SPENT") if p["resource_id"] == MOMENTUM and p["remaining"] == 0 and p["amount"] != 3)
    # 6d10 + 1d10 per Momentum spent: the 3 of the cost and every one left (the charge's own 20+ feet earned one on the way)
    assert any(r.expression.startswith(f"{6 + 3 + rest}d10") for r in engine.rolls[before:]) and foe.current_hp < 1000
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())


# ---------------------------------------------------------------------------------------------------------- Group 28: Ryūjin
# plug-in: combat/ext/ryujin.py (Storm Step, the Ascendant Form's profiles and rider); object_damage blocks for the breath/roar
RYUJIN = "tianxia.subpath.body.ryujin.feature."


def _ryujin(ids, *, foe_at=(4, 6)):
    engine = fight(bundle([RYUJIN + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_dragons_breath_scales_with_cl():
    engine, me, foe = _ryujin(["dragon_s_breath"])
    before = len(engine.rolls)
    use(engine, "Dragon's Breath", at=(4, 6))
    assert any(r.expression.startswith("8d6") for r in engine.rolls[before:]) and foe.current_hp < 1000  # CL18


def test_ryujin_breath_commits_damage_type_before_any_save_and_has_no_stale_form_rider():
    engine, me, foe = _ryujin(["dragon_s_breath", "ryujin_ascendant_form"])
    answers(engine)
    form_events = use(engine, "Ryūjin Ascendant Form")
    assert not any("Fly Speed of 60 feet with Hover" in rider for rider in
                   mechanics()[RYUJIN + "ryujin_ascendant_form"].get("riders", []))
    assert not any("Fly Speed of 60 feet with Hover" in str(p.get("rider")) for p in payloads(form_events, "GM_RIDER"))
    requests = []
    def choose(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        requests.append((len(engine.rolls), request["reaction_source_id"], tuple(spec["option_ids"])))
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="USE", option_ids=("THUNDER",)), None
    engine.set_reaction_provider(choose)
    me.bonus_action_available = True
    before_breath = len(engine.rolls)
    use(engine, "Dragon's Breath (Ascendant)", at=(4, 6))
    assert requests and requests[0][0] == before_breath and "ryujin_damage" in requests[0][1]
    assert not any("Fly Speed of 60 feet with Hover" in str(p.get("rider")) for p in payloads(engine.events, "GM_RIDER"))
    assert any(r.expression.startswith("8d6") for r in engine.rolls)


def test_storm_step_teleports_beside_the_foe_and_bursts():
    engine, me, foe = _ryujin(["storm_step"], foe_at=(10, 6))
    before = len(engine.rolls)
    events = use(engine, "Storm Step", at=(9, 6))
    assert any(p.get("teleport") for p in payloads(events, "MOVEMENT_COMMITTED"))
    assert engine._distance_actor_to_actor(me, foe) <= 5 and any(r.expression.startswith("2d6") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())  # DC 50


def test_dragons_roar_stuns_until_the_start_of_your_next_turn():
    engine, me, foe = _ryujin(["dragon_s_roar"])
    use(engine, "Dragon's Roar", at=(4, 6))
    stunned = [c for c in foe.conditions.values() if c.condition_id.endswith("stunned")]
    assert stunned and stunned[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert not any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_ryujin_ascendant_form_profiles_rider_and_aura():
    engine, me, foe = _ryujin(["dragon_s_breath", "storm_step", "ryujin_ascendant_form"])
    use(engine, "Ryūjin Ascendant Form")
    me.bonus_action_available = True
    names = legal(engine)
    assert "Dragon's Breath (Ascendant)" in names and "Dragon's Breath" not in names and "Storm Step (Ascendant)" in names
    assert "LIGHTNING" in {m.value for m in me.modifiers.values() if m.target_field == "damage_immunity"}
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("3d6") for r in engine.rolls[before:])
    foe.position = Position(x=5, y=6)
    end_turns_until(engine, FOE)  # it starts its turn within 10 feet
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


# ------------------------------------------------------------------------------------------ Group 29: Seven-Coiled Serpent Spine
# plug-in: combat/ext/serpent_coils.py (the Coil record, upkeep and every Coil's benefits)
SERPENT = "tianxia.subpath.body.seven_coiled_serpent_spine.feature."
ALL_COILS = ["first_and_second_coils", "third_and_fourth_coils", "sixth_coil_crowned_serpent", "seventh_coil_heaven_swallowing_serpent"]


def _coils(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([SERPENT + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_coils_are_opened_at_turn_start_and_upkeep_is_paid_at_its_end():
    from combat.ext.serpent_coils import open_coils

    engine, me, foe = _coils(["first_and_second_coils", "third_and_fourth_coils"], picks={"serpent_coils": ["4"], "coil_upkeep": ["pay"]})
    end_turns_until(engine, ME)
    assert open_coils(me) == 4 and engine._effective_speed(me) == 40
    stamina = me.resources[STAMINA]
    end_turns_until(engine, FOE)
    assert me.resources[STAMINA] == stamina - 1 and open_coils(me) == 4


def test_declining_the_upkeep_closes_every_coil():
    from combat.ext.serpent_coils import open_coils

    engine, me, foe = _coils(["first_and_second_coils", "third_and_fourth_coils"], picks={"serpent_coils": ["4"], "coil_upkeep": None})
    end_turns_until(engine, ME)
    assert open_coils(me) == 4
    end_turns_until(engine, FOE)
    assert open_coils(me) == 0


def test_striking_serpent_2d8_against_a_grappled_foe_and_crushing_at_turn_start():
    engine, me, foe = _coils(["first_and_second_coils", "third_and_fourth_coils"], picks={"serpent_coils": ["4"], "coil_upkeep": ["pay"], "swift_serpent_step": None})
    end_turns_until(engine, ME)
    _huge(engine, FOE)  # two sizes larger: only Crushing Serpent's size lets the Grapple land
    assert _grapple(engine, FOE)
    assert any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    me.action_available = True
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:])
    hp = foe.current_hp
    end_turns_until(engine, ME)
    assert foe.current_hp == hp - 2  # CON modifier 2


def test_crowned_serpent_blindsight_reach_and_follow():
    from combat import senses

    engine, me, foe = _coils(ALL_COILS[:3], picks={"serpent_coils": ["6"], "coil_upkeep": ["pay"]}, foe_at=(6, 6))
    end_turns_until(engine, ME)
    assert senses.of(engine, me).get("blindsight", {}).get("range_ft") == 20
    foe.position = Position(x=5, y=6)  # 10 feet away: only the Crowned Serpent's reach gets there
    assert any(name.endswith("(extended reach)") for name in legal(engine))
    foe.position = Position(x=6, y=6)
    end_turns_until(engine, FOE)
    stamina = me.resources[STAMINA]
    use(engine, "Move to 7,6", actor_id=FOE)  # a hostile creature within 20 feet (Blindsight) moves
    assert me.resources[STAMINA] == stamina - 1 and me.position.x > 3


def test_seventh_coil_doubles_speed_resists_and_burns_at_the_turns_end():
    engine, me, foe = _coils(ALL_COILS, picks={"serpent_coils": ["7"], "coil_upkeep": ["pay"]})
    end_turns_until(engine, ME)
    assert engine._effective_speed(me) == 80  # (30 + 10) doubled
    assert {"SLASHING", "FORCE"} <= {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    hp, stamina = me.current_hp, me.resources[STAMINA]
    before = len(engine.rolls)
    end_turns_until(engine, FOE)
    burn = next(r for r in engine.rolls[before:] if "seventh_coil" in str(r.reason))
    assert me.current_hp == hp - burn.total and me.resources[STAMINA] == stamina - 2


# --------------------------------------------------------------------------------------------------------- Group 30: Shinobi
# plug-ins: combat/ext/shinobi.py (Assassination, Vanishing Flesh), combat/ext/tabik_ninpo.py (Pressure-Point Strike, now asked)
SHINOBI = "tianxia.subpath.body.shinobi.feature."


def _shinobi(ids, *, picks=None):
    engine = fight(bundle([SHINOBI + k for k in ids]), foe=_typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_pressure_point_strike_is_asked_and_its_result_chosen_after_the_failure():
    assert riders(SHINOBI + "pressure_point_strike") == []
    engine, me, foe = _shinobi(["pressure_point_strike"], picks={"pressure_point_strike": ["use"], "pressure_point_result": ["speed"]})
    foe.armor_class = -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and engine._effective_speed(foe) == 20
    engine2, me2, foe2 = _shinobi(["pressure_point_strike"], picks={"pressure_point_strike": None})
    foe2.armor_class = -50
    script(engine2, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine2, unarmed(engine2), target=FOE)
    assert me2.resources[STAMINA] == 60  # declined


def test_assassination_on_a_foe_that_has_not_acted_adds_2d8_plus_cl_and_a_choice():
    engine, me, foe = _shinobi(["assassination"], picks={"assassination": ["reactions"]})
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8+18") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    me.action_available = True
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert not any(r.expression.startswith("2d8+18") for r in engine.rolls[before:])  # once per turn


def test_vanishing_flesh_invisible_revealed_by_attacking_and_back_at_the_turns_end():
    engine, me, foe = _shinobi(["shadow_afterimage", "vanishing_flesh"])
    use(engine, "Vanishing Flesh")
    assert any(c.condition_id == "condition:typed.invisible" for c in me.conditions.values())
    assert any(getattr(a, "summon", None) for a in engine.state.actors.values())  # the free Shadow Afterimage
    foe.armor_class = -50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert not any(c.condition_id == "condition:typed.invisible" for c in me.conditions.values())
    assert any(r.expression.startswith("3d6") for r in engine.rolls[before:])
    end_turns_until(engine, FOE)
    assert any(c.condition_id == "condition:typed.invisible" for c in me.conditions.values())


# ------------------------------------------------------------------------------------------ Group 31: Sky-Treading Tendon School
# plug-in: combat/ext/sky_treading.py (Thousand-Mile Legs, Heaven-Kicking Leg, Pursuit Without Horizon, Body Crosses Heaven)
SKY = "tianxia.subpath.body.sky_treading_tendon_school.feature."


def _sky(ids, *, picks=None, me_at=(3, 6), foe_at=(8, 6), objects=()):
    engine = fight(bundle([k if k.startswith("tianxia.") else SKY + k for k in ids]), foe=_typed_foe(), me_at=me_at, foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_thousand_mile_legs_speed_stomping_step_and_the_strike_after_twenty_feet():
    engine, me, foe = _sky(["thousand_mile_legs", "tianxia.path.body_refining.feature.stomping_step"], picks={"thousand_mile_step": ["cell:6,5"]})
    assert engine._effective_speed(me) == 40
    use(engine, "Move to 7,6")  # 20 feet
    strike = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == unarmed(engine) and a.owner_id == ME)
    events = use(engine, unarmed(engine), target=FOE)
    packets = [p["hp_damage"] for e, p in zip(events, [e.payload or {} for e in events]) if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]
    assert len(packets) == 2 and packets[1] == 6  # + Proficiency Bonus
    assert (me.position.x, me.position.y) == (6, 5)  # then the asked 5-foot step
    me.action_available = True
    foe.position = Position(x=7, y=5)
    again = use(engine, unarmed(engine), target=FOE)
    assert len([e for e in again if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]) == 1  # once per turn
    use(engine, "Stomping Step")
    assert any(c.condition_id == "condition:typed.ignore_difficult" for c in me.conditions.values())


def test_heaven_kicking_leg_after_ten_feet_kicks_it_where_you_choose_and_takes_its_reactions():
    engine, me, foe = _sky(["heaven_kicking_leg"], foe_at=(6, 6), picks={"heaven_kicking_leg": ["use"], "heaven_kick_destination": ["cell:6,9"]})
    use(engine, "Move to 5,6")  # 10 feet
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and (foe.position.x, foe.position.y) == (6, 9)  # DC 50: failed
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    engine2, me2, foe2 = _sky(["heaven_kicking_leg"], foe_at=(4, 6), picks={"heaven_kicking_leg": ["use"]})
    use(engine2, unarmed(engine2), target=FOE)
    assert me2.resources[STAMINA] == 60 and (foe2.position.x, foe2.position.y) == (4, 6)  # no movement first: not offered


def test_pursuit_without_horizon_chases_a_foe_that_moves_ten_feet_and_strikes_it():
    engine, me, foe = _sky(["pursuit_without_horizon"], foe_at=(8, 6), picks={"pursuit_without_horizon": ["cell:9,6"]})
    end_turns_until(engine, FOE)
    events = use(engine, "Move to 10,6", actor_id=FOE)
    assert me.resources[STAMINA] == 58
    assert engine._distance_actor_to_actor(me, foe) <= 5  # moved up to its Speed, ending closer
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events)  # then the unarmed strike


def test_body_crosses_heaven_after_thirty_feet_hurls_it_into_a_pillar():
    pillar = [{"id": 1, "kind": "crate", "x": 9, "y": 3, "hp": 999, "blocks": True}]
    engine, me, foe = _sky(["body_crosses_heaven"], me_at=(2, 6), foe_at=(9, 6), objects=pillar,
                           picks={"body_crosses_heaven": ["use"], "crosses_heaven_direction": ["cell:9,0"]})
    use(engine, "Move to 8,6")  # 30 feet
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("4d8") for r in engine.rolls[before:])
    assert (foe.position.x, foe.position.y) == (9, 4) and any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    at = next(i for i, e in enumerate(events) if "slams into a solid surface" in str((e.payload or {}).get("log")))
    slam = next(e.payload for e in events[at:] if e.event_type == "DAMAGE_COMMITTED")
    assert slam["hp_damage"] == 6 and slam["damage_type"] == "BLUDGEONING"  # the collision: Proficiency Bonus Bludgeoning
    crate = engine.state.objects["object:map.1"]
    assert crate.maximum_hp - crate.current_hp == 6  # and the object it hit takes the same


# ------------------------------------------------------------------------------------------------ Group 32: Still-Water Draw Body
# plug-ins: combat/ext/still_water.py (First Cut, Empty-Scabbard Step, One Breath, Still-Water Posture, Heaven Divided),
# combat/ext/integrated_weapons.py ("choose": the Draw Weapon)
STILL = "tianxia.subpath.body.still_water_draw_body.feature."
DAO_ITEM = "tianxia.mortal.weapon.dao"
DAO = "Dao (Saber / Broadsword) attack (Constitution)"


def _still(ids, *, picks=None, me_at=(3, 6), foe_at=(4, 6), objects=(), items=(DAO_ITEM,)):
    engine = fight(bundle([k if k.startswith("tianxia.") else STILL + k for k in ["drawn_from_stillness", *ids]], items=items),
                   foe=_typed_foe(), me_at=me_at, foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_drawn_from_stillness_one_draw_weapon_and_first_cut():
    engine, me, foe = _still([], items=("tianxia.mortal.weapon.jian", DAO_ITEM), picks={"first_cut_move": ["cell:2,6"]})
    names = legal(engine)
    assert DAO in names and "Jian (Straight Sword) attack (Constitution)" not in names  # "Choose one Draw Blade"
    dao = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == DAO)
    events = use(engine, DAO, target=FOE)
    packets = [e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == dao]
    assert len(packets) == 2 and packets[1] == 6 and (me.position.x, me.position.y) == (2, 6)  # + PB, then the 5-foot move
    me.action_available = True
    foe.position = Position(x=3, y=6)
    again = use(engine, DAO, target=FOE)
    assert len([e for e in again if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == dao]) == 1  # not the first attack roll


def test_empty_scabbard_step_moves_out_of_reach_or_counters_a_miss():
    engine, me, foe = _still(["empty_scabbard_step"], picks={"empty_scabbard_step": ["cell:1,6"]})
    end_turns_until(engine, FOE)
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[STAMINA] == 59 and (me.position.x, me.position.y) == (1, 6)
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in events)  # out of its reach: it misses
    engine2, me2, foe2 = _still(["empty_scabbard_step"], picks={"empty_scabbard_step": ["cell:3,5"]})
    me2.armor_class = 100
    end_turns_until(engine2, FOE)
    events2 = use(engine2, unarmed(engine2, FOE), target=ME, actor_id=FOE)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in events2)  # still in reach: rolled, and missed
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events2)  # the Draw Weapon counter


def test_one_breath_three_horizons_spends_two_attacks_on_a_line_then_the_rest():
    assert riders(STILL + "one_breath_three_horizons") == []  # "replace two attacks with a line", its area and limit now run
    engine, me, foe = _still(["one_breath_three_horizons", "tianxia.path.body_refining.feature.extra_attack"],
                             picks={"attack_line_move": None, "first_cut_move": None})
    name = next(n for n in legal(engine) if n.startswith("One Breath, Three Horizons"))
    before = len(engine.rolls)
    events = use(engine, name, at=(8, 6))
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("4d8") for r in engine.rolls[before:])
    assert any(r.expression.startswith("2d10") for r in engine.rolls[before:])  # two of the Dao's d10s
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())  # DC 50
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]) == 2  # the other two of four attacks
    me.action_available = True
    assert not any(n.startswith("One Breath, Three Horizons") for n in legal(engine))  # once per turn


def test_still_water_posture_holds_still_then_strikes_with_advantage():
    engine, me, foe = _still(["moon_reflected_before_motion"], picks={"still_water_posture": ["enter"], "still_water_posture_move": None})
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    assert engine._effective_speed(me) == 0
    before = len(engine.rolls)
    use(engine, DAO, target=FOE)
    attack = next(r for r in engine.rolls[before:] if str(r.reason).startswith("ATTACK"))
    assert attack.mode == "ADVANTAGE" and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values()) and engine._effective_speed(me) == 30


def test_heaven_divided_before_sound_dashes_through_the_foe_on_the_line_and_stills_it():
    engine, me, foe = _still(["heaven_divided_before_sound"], foe_at=(6, 6), picks={"first_cut_move": None})
    before = len(engine.rolls)
    use(engine, "Heaven Divided Before Sound", at=(10, 6))
    assert me.resources[STAMINA] == 53 and (me.position.x, me.position.y) == (10, 6)  # through the hostile space
    assert any(r.expression.startswith("6d8") for r in engine.rolls[before:])
    assert any(c.condition_id == "condition:typed.heaven_divided_stilled" for c in foe.conditions.values())  # DC 50


def _heaven_line(objects):
    """The compiled action's effect aimed past a barrier (the table's aiming needs sight, which a barrier blocks)."""
    from combat import typed_executor as te

    engine, me, foe = _still(["heaven_divided_before_sound"], foe_at=(6, 9), objects=objects)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Heaven Divided Before Sound")
    typed = action.parameters["typed"]
    te.run_effects(te.Context(engine, me, action, None, typed, [], None, {"_checkpoint_aim": Position(x=10, y=6)}), typed["effects"])
    return engine, me


def test_heaven_divided_before_sound_cuts_a_barrier_on_the_line_or_stops_before_it():
    engine, me = _heaven_line([{"id": 1, "kind": "crate", "x": 8, "y": 6, "hp": 5, "ac": 1, "blocks": True}])
    assert engine.state.objects["object:map.1"].destroyed and (me.position.x, me.position.y) == (10, 6)
    engine2, me2 = _heaven_line([{"id": 1, "kind": "crate", "x": 8, "y": 6, "hp": 999, "ac": 1, "blocks": True}])
    assert (me2.position.x, me2.position.y) == (7, 6)  # it survived: end before it


# ------------------------------------------------------------------------------------------------------ Group 33: Stone Fist
# plug-in: combat/ext/stone_fist.py (Overwhelming Blow, Break the Guard, Heaven-Cracking Blow); object rows in
# combat/rules/feature_blocks.d/riders_c7.json (Breaking Fist, Earth-Shattering Fist)
STONE = "tianxia.subpath.body.stone_fist.feature."
OVERWHELM = "Strength save (choose the result on a failure)"


def _stone(ids, *, picks=None, foe_at=(4, 6), objects=()):
    engine = fight(bundle([STONE + k for k in ids]), foe=_typed_foe(), foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_breaking_fist_doubles_unarmed_damage_to_an_object():
    engine, me, foe = _stone(["breaking_fist"], foe_at=(10, 6), objects=[{"id": 1, "kind": "door", "x": 4, "y": 6, "hp": 999}])
    name = next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Attack an object") and "object:map.1" in (c.target_ids or ()))
    _force_next_d20(engine, 19)
    before = len(engine.rolls)
    events = use(engine, name, target="object:map.1")
    rolled = next(r.total for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE"))
    taken = next(e.payload["damage"]["taken"] for e in events if e.event_type == "OBJECT_UPDATED")
    assert taken == 2 * rolled


def test_overwhelming_blow_step_in_and_a_collision_with_a_wall():
    engine, me, foe = _stone(["overwhelming_blow"], picks={"feature.overwhelming_blow": [OVERWHELM], "path_results.overwhelming_blow": ["Push 5 Feet and Step In"]})
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and (foe.position.x, foe.position.y) == (5, 6) and (me.position.x, me.position.y) == (4, 6)
    engine2, me2, foe2 = _stone(["overwhelming_blow"], picks={"feature.overwhelming_blow": [OVERWHELM], "path_results.overwhelming_blow": ["Push 10 Feet"]},
                                objects=[{"id": 1, "kind": "door", "x": 5, "y": 6, "hp": 999}])
    script(engine2, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    events = use(engine2, unarmed(engine2), target=FOE)
    at = next(i for i, e in enumerate(events) if "slams into a solid surface" in str((e.payload or {}).get("log")))
    assert next(e.payload for e in events[at:] if e.event_type == "DAMAGE_COMMITTED")["hp_damage"] == 6


def test_overwhelming_blow_drives_the_target_into_another_creature():
    engine = _two_foe_fight(bundle([STONE + "overwhelming_blow"]))
    answers(engine, {"feature.overwhelming_blow": [OVERWHELM], "path_results.overwhelming_blow": ["Push 10 Feet"]})
    foe, other = engine.state.actors[FOE], engine.state.actors["actor:factory.c7foe2"]
    foe.armor_class = -50
    other.position = Position(x=5, y=6)
    hp = other.current_hp
    use(engine, unarmed(engine), target=FOE)
    assert other.current_hp == hp - 6  # its Dexterity save against DC 50 failed: both take it


def test_shattering_palm_break_the_guard_and_its_repeated_save():
    from combat.ext.stone_fist import GUARD_FLAG, PALM

    engine, me, foe = _stone(["shattering_palm"], picks={"feature.shattering_palm": ["Break the Guard"]})
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    guard = [m for m in foe.modifiers.values() if m.source_definition_id == PALM and m.target_field == "armor_class"]
    assert me.resources[STAMINA] == 57 and [m.value for m in guard] == [-2]
    foe.turn_flags[GUARD_FLAG]["dc"] = -50  # its repeated save at the end of its turn now succeeds
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    assert not [m for m in foe.modifiers.values() if m.source_definition_id == PALM]


def test_heaven_cracking_blow_pierces_resistance_hurls_and_is_once_per_scene():
    engine, me, foe = _stone(["heaven_cracking_blow"], picks={"feature.heaven_cracking_blow": ["Heaven-Cracking Blow (once per scene)"]})
    for kind in ("BLUDGEONING", "FORCE"):
        engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    big = next(r for r in engine.rolls[before:] if r.expression.startswith("10d10"))
    packet = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("rolled_or_pending_damage") == big.total)
    assert packet["hp_damage"] == big.total  # its Resistance did not halve it (same Source CL)
    assert me.resources[STAMINA] == 53 and (foe.position.x, foe.position.y) == (10, 6)  # DC 50: pushed 30 feet
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    foe.position = Position(x=4, y=6)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 53  # once per scene


def test_earth_shattering_fist_breaks_the_ground_and_doubles_against_objects():
    engine, me, foe = _stone(["earth_shattering_fist"], objects=[{"id": 1, "kind": "door", "x": 5, "y": 6, "hp": 999}])
    events = use(engine, "Earth-Shattering Fist", at=(4, 6))
    assert any(e.event_type == "ZONE_CREATED" for e in events)  # "The ground becomes difficult terrain"
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert any(e.event_type == "OBJECT_UPDATED" for e in events)


def test_body_crosses_heaven_a_creature_in_the_way_is_not_a_solid_surface():
    # Group 31 follow-up (fixed with Group 33): engine._actor_cells gives (x, y) pairs, so a creature was taken for a wall.
    engine = _two_foe_fight(bundle([SKY + "body_crosses_heaven"]))
    answers(engine, {"body_crosses_heaven": ["use"], "crosses_heaven_direction": ["cell:9,1"]})
    me, foe, other = engine.state.actors[ME], engine.state.actors[FOE], engine.state.actors["actor:factory.c7foe2"]
    foe.armor_class, foe.position, other.position, me.position = -50, Position(x=9, y=6), Position(x=9, y=4), Position(x=2, y=6)
    use(engine, "Move to 8,6")  # 30 feet
    hp = other.current_hp
    events = use(engine, unarmed(engine), target=FOE)
    assert (foe.position.x, foe.position.y) == (9, 5) and other.current_hp == hp
    assert not any("slams into a solid surface" in str((e.payload or {}).get("log")) for e in events)


# ------------------------------------------------------------------------------------------------------------ Group 34: Sumo
# plug-in: combat/ext/sumo.py (Rooted Stance's checks, size and 5-foot cut; Sumo Strike; Ring Breaker; Immovable God)
SUMO = "tianxia.subpath.body.sumo.feature."


def _sumo(ids, *, picks=None, foe_at=(4, 6), objects=(), foe_cl=18):
    engine = fight(bundle([SUMO + k for k in ids]), foe=bundle([], actor_id=FOE, name="C7 Foe", cl=foe_cl), foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def _shoved(engine, pusher, target, feet):
    """A typed push of ``feet`` from ``pusher``'s own unarmed strike's context."""
    from combat import typed_executor as te

    action = next(a for a in engine.action_catalog.values() if a.owner_id == pusher.entity_id and a.display_name == unarmed(engine, pusher.entity_id))
    te.run_effects(te.Context(engine, pusher, action, None, action.parameters["typed"], [target], target, {}),
                   [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


def test_rooted_stance_counts_larger_and_cuts_forced_movement_by_five():
    from combat import typed_executor as te

    assert not any("Reduce forced movement" in r or "Count as one size larger" in r for r in riders(SUMO + "rooted_stance"))
    engine, me, foe = _sumo(["rooted_stance"])
    use(engine, "Rooted Stance")
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {}, [me], me, {})
    assert te.size_width(ctx, me, "subject", {}) == 2  # Medium, counted one size larger
    _shoved(engine, foe, me, 10)
    assert (me.position.x, me.position.y) == (2, 6)  # 10 feet cut to 5


def test_sumo_strike_pushes_ten_feet_and_a_wall_collision_hurts_both():
    engine, me, foe = _sumo(["sumo_strike"], picks={"sumo_strike": ["Push it"]}, objects=[{"id": 1, "kind": "door", "x": 6, "y": 6, "hp": 999}])
    before = len(engine.rolls)
    events = use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and (foe.position.x, foe.position.y) == (5, 6)  # stopped by the door
    assert len([r for r in engine.rolls[before:] if r.expression.startswith("3d6")]) == 2  # CL18: 3d6 to it and to the door
    assert any(e.event_type == "OBJECT_UPDATED" for e in events)
    engine2, me2, foe2 = _sumo(["sumo_strike"], picks={"sumo_strike": ["Push it"]})
    use(engine2, unarmed(engine2), target=FOE)
    assert (foe2.position.x, foe2.position.y) == (6, 6)  # the full 10 feet, no save for a Medium target


def test_ring_breaker_chosen_distance_prone_and_step_in_without_collision_damage():
    engine, me, foe = _sumo(["ring_breaker"], picks={"ring_breaker_distance": ["15"], "ring_breaker_step": ["enter"]})
    before = len(engine.rolls)
    use(engine, "Ring Breaker", target=FOE)
    assert me.resources[STAMINA] == 57 and (foe.position.x, foe.position.y) == (7, 6) and (me.position.x, me.position.y) == (4, 6)
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert not any(r.expression.startswith("3d8") for r in engine.rolls[before:])  # 3d8 only on a collision


def test_ring_breaker_drives_the_target_into_another_creature():
    engine = _two_foe_fight(bundle([SUMO + "ring_breaker"]))
    answers(engine, {"ring_breaker_distance": ["20"], "ring_breaker_step": None})
    foe, other = engine.state.actors[FOE], engine.state.actors["actor:factory.c7foe2"]
    other.position = Position(x=6, y=6)
    hp = other.current_hp
    use(engine, "Ring Breaker", target=FOE)
    assert other.current_hp < hp and any(c.condition_id.endswith("prone") for c in other.conditions.values())  # DC 50 Dexterity save
    assert (foe.position.x, foe.position.y) == (5, 6)


def test_immovable_god_always_rooted_strikes_after_moving_and_ignores_a_lower_cl_push():
    engine, me, foe = _sumo(["rooted_stance", "immovable_god"], foe_at=(8, 6), foe_cl=5, picks={"immovable_god": [FOE]})
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    assert any(c.condition_id == "condition:typed.stance.rooted_stance" for c in me.conditions.values())  # no Bonus Action
    events = use(engine, "Move to 7,6")  # 20 feet: more than half its Speed, and the foe comes within reach
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events)
    assert any(c.condition_id == "condition:typed.stance.rooted_stance" for c in me.conditions.values())
    _shoved(engine, foe, me, 10)
    assert (me.position.x, me.position.y) == (7, 6)  # a CL5 source cannot move it


# ---------------------------------------------------------------------------------------------- Group 35: Sun-Piercing Bow Body
# plug-ins: combat/ext/sun_bow.py (Bow Body's close shots, Meridian Overdraw, Sky-Pinning Arrow), combat/ext/attack_lines.py
# (Sun-Chasing Line), combat/ext/integrated_weapons.py (the Constitution Bow); typed_executor hook close_ranged_ok
SUN = "tianxia.subpath.body.sun_piercing_bow_body.feature."
BOW_ITEM = "tianxia.mortal.weapon.gong_jian"
BOW_CON = "Gong Jian (Bow and Arrow) attack (Constitution)"


def _sun(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([k if k.startswith("tianxia.") else SUN + k for k in ids], items=(BOW_ITEM,)), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_bow_body_constitution_bow_without_close_range_disadvantage():
    engine, me, foe = _sun(["bow_body"])  # the foe stands within 5 feet
    before = len(engine.rolls)
    use(engine, BOW_CON, target=FOE)
    attack = next(r for r in engine.rolls[before:] if str(r.reason).startswith("ATTACK"))
    assert attack.mode == "NORMAL"


def test_meridian_overdraw_adds_dice_and_the_chosen_failed_save_result():
    engine, me, foe = _sun(["bow_body", "meridian_overdraw"], foe_at=(8, 6),
                           picks={"path_results.meridian_overdraw": ["Speed - 15 Feet"], "needle.meridian_overdraw": ["use"]})
    before = len(engine.rolls)
    use(engine, BOW_CON, target=FOE)
    assert me.resources[STAMINA] == 59 and any(r.expression.startswith("4d8") for r in engine.rolls[before:])  # CL18
    assert engine._effective_speed(foe) == 15
    me.action_available = True
    use(engine, BOW_CON, target=FOE)
    assert me.resources[STAMINA] == 59  # once per turn


def test_sky_pinning_arrow_is_a_bow_attack_that_pins_the_target():
    engine, me, foe = _sun(["bow_body", "sky_pinning_arrow"], foe_at=(8, 6))
    before = len(engine.rolls)
    use(engine, "Sky-Pinning Arrow (Gong Jian (Bow and Arrow), Constitution)", target=FOE)
    assert me.resources[STAMINA] == 57 and any(r.expression.startswith("5d8") for r in engine.rolls[before:])
    assert any(c.condition_id == "condition:typed.sky_pinned" for c in foe.conditions.values()) and engine._effective_speed(foe) == 0


def test_star_piercing_shot_line_ignores_piercing_and_force_resistance_once_per_scene():
    engine, me, foe = _sun(["star_piercing_shot"], foe_at=(6, 6))
    for kind in ("PIERCING", "FORCE"):
        engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    before = len(engine.rolls)
    events = use(engine, "Star-Piercing Shot", at=(12, 6))
    big = next(r for r in engine.rolls[before:] if r.expression.startswith("12d10"))
    packet = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("rolled_or_pending_damage") == big.total)
    assert packet["hp_damage"] == big.total and me.resources[STAMINA] == 52
    me.action_available = True
    assert "Star-Piercing Shot" not in legal(engine)  # once per scene


def test_sun_chasing_line_spends_one_attack_of_the_bow_attack_action():
    assert riders(SUN + "sun_chasing_line") == []  # "not an attack", its objects and its limit now run
    engine, me, foe = _sun(["bow_body", "sun_chasing_line", "tianxia.path.body_refining.feature.extra_attack"], foe_at=(8, 6))
    before = len(engine.rolls)
    events = use(engine, "Sun-Chasing Line (Gong Jian (Bow and Arrow))", at=(12, 6))
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("4d8") for r in engine.rolls[before:])
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]) == 3  # the other three of four attacks
    me.action_available = True
    assert not any(n.startswith("Sun-Chasing Line") for n in legal(engine))  # once per turn


# -------------------------------------------------------------------------------------- Group 36: Ten-Thousand Parasite Vessel
# plug-ins: combat/ext/parasite_vessel.py (Internal Brood, Infested and Gnawing, Brood Substitution, Sovereignty, Worm Demon Body),
# combat/ext/subpath_pools.py (Brood)
PARASITE = "tianxia.subpath.body.ten_thousand_parasite_vessel.feature."
BROOD = "resource:named.brood"
INFESTED = "condition:typed.infested"


def _parasite(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([PARASITE + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def _foe_save(engine, foe, me, ability, damage):
    """A hostile typed save against ``me`` from the foe's own unarmed strike's context: a failure deals ``damage`` Bludgeoning."""
    from combat import typed_executor as te

    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == unarmed(engine, FOE))
    row = {"type": "save", "ability": ability, "on_fail": [{"type": "damage", "applies_to": "target", "flat": damage, "damage_types": ["bludgeoning"]}], "on_success": []}
    typed = {**action.parameters["typed"], "effects": [row], "numbers": {**action.parameters["typed"]["numbers"], "save_dc": 50}}
    te.run_effects(te.Context(engine, foe, action, None, typed, [me], me, {}), [row])


def test_brood_is_gained_from_hostile_damage_once_a_round_up_to_pb():
    engine, me, foe = _parasite(["internal_brood"])
    assert engine.state.actors[ME].resource_maximums[BROOD] == 6
    _foe_save(engine, foe, me, "con", 5)
    _foe_save(engine, foe, me, "con", 5)
    assert me.resources[BROOD] == 1  # one a round


def test_internal_brood_heals_at_turn_start_and_infesting_strike_infests():
    engine, me, foe = _parasite(["internal_brood"], picks={"feature.internal_brood": ["Infesting Strike"], "needle.internal_brood": ["heal"]})
    engine._gain_resource(me, BROOD, 3, "test")
    me.current_hp = 50
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    assert me.current_hp > 50 and me.resources[BROOD] == 2
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[BROOD] == 1 and any(r.expression.startswith("1d8") for r in engine.rolls[before:])
    held = next(c for c in foe.conditions.values() if c.condition_id == INFESTED)
    assert held.data["owner"] == ME and held.data["kind"] in ("POISON", "NECROTIC")


def test_gnawing_infestation_bites_when_it_moves_fifteen_feet_and_sovereignty_pays_out():
    engine, me, foe = _parasite(["internal_brood", "gnawing_infestation", "parasite_sovereignty"],
                                picks={"feature.internal_brood": ["Infesting Strike"], "parasite_sovereignty": ["brood"]})
    engine._gain_resource(me, BROOD, 2, "test")
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    kind = next(c for c in foe.conditions.values() if c.condition_id == INFESTED).data["kind"]
    engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    end_turns_until(engine, FOE)
    me.reaction_available = False  # no Opportunity Attack as it walks off
    brood = me.resources[BROOD]
    before = len(engine.rolls)
    events = use(engine, "Move to 7,6", actor_id=FOE)  # 15 feet of willing movement
    gnaw = next(r for r in engine.rolls[before:] if r.expression.startswith("3d8"))
    packet = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("rolled_or_pending_damage") == gnaw.total)
    assert packet["hp_damage"] == gnaw.total  # Parasite Sovereignty: its Resistance is ignored
    assert not any(c.condition_id == INFESTED for c in foe.conditions.values())
    assert any(m.target_field == "healing_reduction" for m in foe.modifiers.values())
    assert me.resources[BROOD] == brood + 1  # the chosen benefit


def test_an_infestation_that_is_not_triggered_ends_on_a_repeated_save():
    engine, me, foe = _parasite(["internal_brood", "gnawing_infestation"], picks={"feature.internal_brood": ["Infesting Strike"]})
    engine._gain_resource(me, BROOD, 1, "test")
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    held = next(c for c in foe.conditions.values() if c.condition_id == INFESTED)
    held.data = {**held.data, "dc": -50}
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)  # the foe's turn ended without a trigger: its save succeeds
    assert not any(c.condition_id == INFESTED for c in foe.conditions.values())


def test_brood_substitution_on_a_failed_dexterity_save():
    quake = "tianxia.subpath.body.stone_fist.feature.earth_shattering_fist"
    engine = fight(bundle([PARASITE + "brood_substitution"]), foe=bundle([quake], actor_id=FOE, name="C7 Foe"))
    answers(engine, {"brood_substitution": ["use"], "brood_substitution_move": ["cell:1,6"]})
    me = engine.state.actors[ME]
    engine._gain_resource(me, BROOD, 2, "test")
    end_turns_until(engine, FOE)
    hp = me.current_hp
    before = len(engine.rolls)
    use(engine, "Earth-Shattering Fist", at=(3, 6), actor_id=FOE)  # DC 50 Dexterity save
    cut = next(r.total for r in engine.rolls[before:] if "brood_substitution" in str(r.reason))
    rolled = next(r.total for r in engine.rolls[before:] if r.expression.startswith("6d8"))
    assert hp - me.current_hp == max(0, rolled - cut) and not me.reaction_available
    assert me.resources[BROOD] == (1 if rolled > cut else 0)  # 2 spent; the damage that still landed earns one back
    assert (me.position.x, me.position.y) == (1, 6)
    assert any(z.trigger_profile.get("name") == "Swarm-Shell" for z in engine.state.zones.values())


def test_worm_demon_body_brood_tide_and_rising_from_zero():
    engine, me, foe = _parasite(["internal_brood", "gnawing_infestation", "ten_thousand_worm_demon_body"], picks={"internal_brood": ["heal"]})
    engine._gain_resource(me, BROOD, 6, "test")
    use(engine, "Ten-Thousand Worm Demon Body")
    assert "SLASHING" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    from combat.ext.subpath_pools import maximum
    assert maximum(engine, me, BROOD) == 9  # PB + 3 while it lasts
    before = len(engine.rolls)
    use(engine, "Brood Tide", at=(4, 6))
    assert me.resources[BROOD] == 3 and any(r.expression.startswith("8d8") for r in engine.rolls[before:])
    assert any(c.condition_id == INFESTED for c in foe.conditions.values()) and engine._effective_speed(foe) == 15
    end_turns_until(engine, FOE)
    me.current_hp = 1
    _foe_save(engine, foe, me, "con", 30)
    assert me.current_hp == 0 and me.life_state == "DYING"
    end_turns_until(engine, ME)  # + 1 Brood at the start of the turn, then Internal Brood raises it
    assert me.current_hp > 0 and me.resources[BROOD] == 0
    assert not any(c.condition_id.endswith(".ten_thousand_worm_demon_body") for c in me.conditions.values())


# ------------------------------------------------------------------------------------------ Group 37: Thousand-Eyed Calamity Body
# plug-in: combat/ext/calamity_eyes.py (Open Eyes, Too Many Open Eyes, Appraisal, Eye beneath the Skin, Read the Killing Line,
# Hundred Eyes Open, Thousand-Eyed Revelation and Calamity Gaze)
EYES = "tianxia.subpath.body.thousand_eyed_calamity_body.feature."
APPRAISED = "condition:typed.mark.appraised_target." + ME


def _eyes(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([EYES + k for k in ["calamity_appraisal", *ids]]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, {"open_eyes": ["4"], "calamity_appraisal": [FOE], **(picks or {})})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)  # the Eyes and the Appraisal are chosen at the start of the turn
    return engine, me, foe


def test_open_eyes_and_calamity_appraisal_add_pb_once_a_turn():
    from combat import senses

    engine, me, foe = _eyes([])
    assert senses.of(engine, me).get("blindsight", {}).get("range_ft") == 20  # 4 Eyes
    assert any(c.condition_id == APPRAISED for c in foe.conditions.values())
    assert any("Calamity Appraisal: C7 Foe" in str((e.payload or {}).get("log")) for e in engine.events)
    strike = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == unarmed(engine) and a.owner_id == ME)
    events = use(engine, unarmed(engine), target=FOE)
    packets = [e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]
    assert 6 in packets[1:]  # + PB
    me.action_available = True
    again = use(engine, unarmed(engine), target=FOE)
    assert len([e for e in again if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]) == 1  # once per turn


def test_three_open_eyes_deny_an_unseen_attacker_its_advantage():
    engine, me, foe = _eyes([])
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
    end_turns_until(engine, FOE)
    before = len(engine.rolls)
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert next(r for r in engine.rolls[before:] if str(r.reason).startswith("ATTACK")).mode == "NORMAL"


def test_too_many_open_eyes_burns_them_shut_on_a_failed_save_against_blinded():
    from combat import typed_executor as te
    from combat.ext.calamity_eyes import eyes

    engine, me, foe = _eyes([])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == unarmed(engine, FOE))
    row = {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "applies_to": "target", "condition": "blinded"}], "on_success": []}
    hp = me.current_hp
    before = len(engine.rolls)
    te.run_effects(te.Context(engine, foe, action, None, {**action.parameters["typed"], "effects": [row], "numbers": {"save_dc": 50}}, [me], me, {}), [row])
    burn = next(r for r in engine.rolls[before:] if "too_many_open_eyes" in str(r.reason))
    assert burn.expression.startswith("4d8") and me.current_hp == hp - burn.total and eyes(me) == 0  # 2d8 for each Eye past the second


def test_eye_beneath_the_skin_turns_a_hit_into_a_miss_and_appraises_the_attacker():
    engine, me, foe = _eyes(["eye_beneath_the_skin"], picks={"calamity_appraisal": None, "eye_beneath_move": ["cell:2,6"]})
    end_turns_until(engine, FOE)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == unarmed(engine, FOE))
    ac = me.armor_class + engine._ac_modifier(me)
    _force_next_d20(engine, max(2, min(19, ac - int(action.parameters["typed"]["numbers"]["attack_bonus"]))))
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert me.resources[STAMINA] == 59 and any(c.condition_id == APPRAISED for c in foe.conditions.values())
    assert (me.position.x, me.position.y) == (2, 6)
    assert not any(m.source_definition_id.endswith("eye_beneath_the_skin") and m.target_field == "armor_class" for m in me.modifiers.values())


def test_read_the_killing_line_denied_escape_on_an_appraised_target():
    engine, me, foe = _eyes(["read_the_killing_line"], picks={"read_the_killing_line": ["denied"]})
    use(engine, unarmed(engine), target=FOE)
    assert me.resources[STAMINA] == 59 and any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_hundred_eyes_open_answers_the_appraised_creature_moving():
    from combat import senses

    engine, me, foe = _eyes(["hundred_eyes_open"], picks={"hundred_eyes_open": ["disadvantage"]}, foe_at=(6, 6))
    assert senses.of(engine, me).get("blindsight", {}).get("range_ft") == 40
    end_turns_until(engine, FOE)
    use(engine, "Move to 8,6", actor_id=FOE)
    assert me.resources[STAMINA] == 59
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in foe.modifiers.values())


def test_thousand_eyed_revelation_calamity_gaze_and_its_4d8():
    engine, me, foe = _eyes(["thousand_eyed_revelation"], picks={"calamity_appraisal": None})
    use(engine, "Thousand-Eyed Revelation")
    before = len(engine.rolls)
    use(engine, "Calamity Gaze", at=(4, 6))
    assert any(r.expression.startswith("8d8") for r in engine.rolls[before:])
    mark = next(c for c in foe.conditions.values() if c.condition_id == APPRAISED)
    assert mark.data.get("gazed") and any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    from combat.ext.calamity_eyes import eyes
    assert eyes(me) == 6  # every Eye open
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("4d8") for r in engine.rolls[before:])


# ------------------------------------------------------------------------------------------ Group 38: Thousand-Fold Steel Body
# plug-in: combat/ext/steel_forms.py (Tempering Forms, Quench the Impact, Folded Edge, Ten Thousand Reforgings, Body Beyond the
# Hammer); combat/ext/integrated_weapons.py (group "melee": the Tempered Weapon)
STEEL = "tianxia.subpath.body.thousand_fold_steel_body.feature."


def _steel_bundle(ids, items=()):
    sh = sheet([STEEL + k for k in ids], items=items)
    sh["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]  # simple and martial weapons
    return compile_character(sh, actor_id=ME)


def _steel(ids, *, picks=None, foe=None, items=()):
    engine = fight(_steel_bundle(["body_forged_in_three_forms", *ids], items), foe=foe or _typed_foe())
    answers(engine, {"tempering_forms": ["edge"], **(picks or {})})
    me, other = engine.state.actors[ME], engine.state.actors[FOE]
    other.armor_class = -50
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)  # the Forms are chosen at the start of the turn
    return engine, me, other


def _quaking_foe():
    return bundle(["tianxia.subpath.body.stone_fist.feature.earth_shattering_fist"], actor_id=FOE, name="C7 Foe")


def test_tempering_forms_edge_adds_pb_and_one_tempered_weapon():
    from combat.ext.steel_forms import forms

    engine, me, foe = _steel([], items=("tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.gun"))
    assert forms(me) == ["edge"]
    names = legal(engine)
    assert "Dao (Saber / Broadsword) attack (Constitution)" in names and not any(n.startswith("Gun") and n.endswith("(Constitution)") for n in names)
    strike = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == unarmed(engine) and a.owner_id == ME)
    events = use(engine, unarmed(engine), target=FOE)
    packets = [e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]
    assert 6 in packets[1:]
    me.action_available = True
    again = use(engine, unarmed(engine), target=FOE)
    assert len([e for e in again if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike]) == 1  # once per turn


def test_spine_form_takes_pb_off_the_first_physical_packet_each_round():
    engine, me, foe = _steel([], picks={"tempering_forms": ["spine"]}, foe=_quaking_foe())
    end_turns_until(engine, FOE)
    hp = me.current_hp
    before = len(engine.rolls)
    use(engine, "Earth-Shattering Fist", at=(3, 6), actor_id=FOE)
    rolled = next(r.total for r in engine.rolls[before:] if r.expression.startswith("6d8"))
    assert hp - me.current_hp == max(0, rolled - 6)


def test_reed_form_steps_after_a_melee_attack_misses_you():
    engine, me, foe = _steel([], picks={"tempering_forms": ["reed"], "reed_form_move": ["cell:2,6"]})
    me.armor_class = 100
    end_turns_until(engine, FOE)
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert (me.position.x, me.position.y) == (2, 6)


def test_quench_the_impact_spine_quench_cuts_the_damage_and_changes_the_form():
    from combat.ext.steel_forms import forms

    engine, me, foe = _steel(["quench_the_impact"], picks={"quench_the_impact": ["spine"]}, foe=_quaking_foe())
    end_turns_until(engine, FOE)
    hp = me.current_hp
    before = len(engine.rolls)
    use(engine, "Earth-Shattering Fist", at=(3, 6), actor_id=FOE)
    rolled = next(r.total for r in engine.rolls[before:] if r.expression.startswith("6d8"))
    cut = next(r.total for r in engine.rolls[before:] if "quench_the_impact" in str(r.reason))
    assert hp - me.current_hp == max(0, rolled - cut) and me.resources[STAMINA] == 59 and not me.reaction_available
    assert forms(me) == ["spine"]


def test_folded_edge_lowers_the_targets_ac_while_edge_is_active():
    from combat.ext.steel_forms import AC_SOURCE

    engine, me, foe = _steel(["folded_edge_hidden_spine"], picks={"folded_edge": ["ac"]})
    use(engine, unarmed(engine), target=FOE)
    assert [m.value for m in foe.modifiers.values() if m.source_definition_id == AC_SOURCE] == [-1]


def test_body_beyond_the_hammer_all_forms_and_perfect_spine():
    from combat.ext.steel_forms import forms

    engine, me, foe = _steel(["ten_thousand_reforgings", "body_beyond_the_hammer"], picks={"body_beyond_the_hammer": ["spine"], "reed_form_move": None})
    assert forms(me) == ["edge", "spine", "reed"]
    use(engine, unarmed(engine), target=FOE)
    assert me.temporary_hp == 14  # 2 x 6 + 2
    _shoved(engine, foe, me, 10)
    assert (me.position.x, me.position.y) == (3, 6)  # cannot be pushed until its next turn


# ------------------------------------------------------------------------------------------ Group 39: Vermilion Gate Guardian Body
# plug-in: combat/ext/vermilion_gate.py (Guarded Threshold, Guardian at the Gate, Shelter, Twin Posts, Threshold Between Worlds,
# Heaven's Closed Gate)
GATE_IDS = "tianxia.subpath.body.vermilion_gate_guardian_body.feature."
ALLY = "actor:factory.c7ally"
LINE_PICKS = {"threshold_orientation": ["north_south"], "threshold_center": ["cell:4,6"]}


def _gate(ids, *, picks=None, foe_at=(6, 6), with_ally=False, walled=False):
    """``walled``: pillars close the ground past both ends of the line at x = 4, so a walk from east to west must cross it."""
    me_bundle = bundle([GATE_IDS + k for k in ["guardian_at_the_gate", *ids]])
    foe = bundle([], actor_id=FOE, name="C7 Foe")
    starts = {ME: (3, 6), FOE: foe_at, **({ALLY: (3, 4)} if with_ally else {})}
    bundles = (me_bundle, foe, *([bundle([], actor_id=ALLY, name="C7 Ally")] if with_ally else []))
    walls = [{"id": i + 1, "kind": "pillar", "x": 4, "y": y, "hp": 999, "blocks": True} for i, y in enumerate((3, 4, 8, 9))] if walled else []
    document = normalize_map({"display_name": "C7 yard", "width_squares": 20, "height_squares": 14, "objects": walls,
                              "starts": {"team1": [list(starts[ME])] + ([list(starts[ALLY])] if with_ally else []), "team2": [list(foe_at)]}})
    engine = Gate4ControllerEngine(ROOT, match_seed="C7", typed_bundles=bundles, battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": list(starts), "team_by_actor": {ME: "team:a", FOE: "team:b", **({ALLY: "team:a"} if with_ally else {})},
                                                 "starting_positions": {k: {"x": v[0], "y": v[1]} for k, v in starts.items()}})
    answers(engine, {**LINE_PICKS, **(picks or {})})
    turn(engine, ME)
    me, other = engine.state.actors[ME], engine.state.actors[FOE]
    other.maximum_hp = other.current_hp = 1000
    end_turns_until(engine, FOE)
    return engine, me, other


def test_guarded_threshold_is_placed_and_guardian_at_the_gate_stops_a_crossing():
    engine, me, foe = _gate([], walled=True)
    line = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("gate_threshold"))
    assert {(c.x, c.y) for c in line.affected_cells} == {(4, 5), (4, 6), (4, 7)} and line.trigger_profile["difficult"] == "hostile"
    foe.armor_class = -50
    use(engine, "Move to 3,5", actor_id=FOE)  # across the line
    assert foe.position.x >= 4  # stopped before it got across (on the line's own square at most)
    assert not me.reaction_available and any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert engine._effective_speed(foe) == 0


def test_a_missed_guardian_strike_lets_the_crossing_finish():
    engine, me, foe = _gate([], foe_at=(5, 6), walled=True)
    foe.armor_class = 100
    use(engine, "Move to 3,5", actor_id=FOE)
    assert (foe.position.x, foe.position.y) == (3, 5) and not me.reaction_available


def test_twin_guardian_posts_two_lines_and_an_extra_result():
    picks = {"threshold_orientation": ["north_south"], "threshold_center": ["cell:4,6"], "twin_guardian_posts": ["prone"]}
    engine, me, foe = _gate(["twin_guardian_posts"], picks=picks, foe_at=(5, 6), walled=True)
    assert len([z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("gate_threshold")]) == 2
    foe.armor_class = -50
    use(engine, "Move to 3,5", actor_id=FOE)
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())


def test_threshold_between_worlds_checks_teleports_and_gives_half_cover():
    from combat.ext.vermilion_gate import threshold_teleport

    engine, me, foe = _gate(["threshold_between_worlds"], foe_at=(8, 6))
    assert threshold_teleport(engine, foe, Position(x=8, y=6), Position(x=2, y=6)) is False  # its check against DC 50 fails
    assert engine._cover_bonus_actor_to_actor(foe, me) >= 2  # a ranged line across the threshold to a target within 5 feet of it


def test_shelter_behind_the_gate_cuts_a_push_on_an_ally_near_the_threshold():
    engine, me, foe = _gate(["shelter_behind_the_gate"], with_ally=True, foe_at=(4, 3))
    ally = engine.state.actors[ALLY]
    _shoved(engine, foe, ally, 20)  # pushed diagonally away from the foe, 20 feet cut to 5
    assert (ally.position.x, ally.position.y) == (2, 5) and me.resources[STAMINA] == 59


def test_heavens_closed_gate_stops_a_hostile_crossing_and_shelters_those_inside():
    engine, me, foe = _gate(["heaven_s_closed_gate"], foe_at=(12, 6))
    end_turns_until(engine, ME)
    use(engine, "Heaven's Closed Gate")
    posts = [o for o in engine.state.objects.values() if o.object_kind == "gate_post"]
    assert len(posts) == 4 and me.resources[STAMINA] == 53
    end_turns_until(engine, FOE)
    before = len(engine.rolls)
    use(engine, "Move to 7,6", actor_id=FOE)  # into the 30-foot circle
    assert foe.position.x >= 9 and any(r.expression.startswith("4d8") for r in engine.rolls[before:])  # held at the edge (DC 50)
    assert engine._effective_speed(foe) == 0
    assert engine._cover_bonus_actor_to_actor(foe, me) >= 5


# ------------------------------------------------------------------------------------------ Group 40: White Elephant Sovereign Body
# plug-in: combat/ext/elephant_sovereign.py (Sovereign Frame and Ivory Charge, Shelter Beneath the Tusks, The Body Remembers,
# Mountain-Walking Sovereign, World-Bearing Elephant King)
ELEPHANT = "tianxia.subpath.body.white_elephant_sovereign_body.feature."


def _elephant(ids, *, picks=None, foe_at=(4, 6)):
    engine = fight(bundle([ELEPHANT + k for k in ids]), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def _trio(me_bundle, *, me_at=(3, 6), ally_at=(5, 6), foe_at=(6, 6)):
    """Me, a typed ally and a typed foe."""
    starts = {ME: me_at, ALLY: ally_at, FOE: foe_at}
    document = normalize_map({"display_name": "C7 yard", "width_squares": 20, "height_squares": 14, "objects": [],
                              "starts": {"team1": [list(me_at), list(ally_at)], "team2": [list(foe_at)]}})
    engine = Gate4ControllerEngine(ROOT, match_seed="C7", typed_bundles=(me_bundle, bundle([], actor_id=ALLY, name="C7 Ally"), bundle([], actor_id=FOE, name="C7 Foe")),
                                   battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": [ME, ALLY, FOE], "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
                                                 "starting_positions": {k: {"x": v[0], "y": v[1]} for k, v in starts.items()}})
    turn(engine, ME)
    return engine


def test_sovereign_frame_counts_larger_and_ivory_charge_after_fifteen_feet():
    from combat import typed_executor as te

    engine, me, foe = _elephant(["sovereign_frame"], foe_at=(8, 6))
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {}, [me], me, {})
    assert te.size_width(ctx, me, "subject", {}) == 2
    use(engine, "Move to 7,6")  # 20 feet straight at it
    strike = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == unarmed(engine) and a.owner_id == ME)
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    events = use(engine, unarmed(engine), target=FOE)
    assert 6 in [e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike][1:]
    assert (foe.position.x, foe.position.y) == (10, 6)  # DC 50: pushed 10 feet


def test_shelter_beneath_the_tusks_takes_the_blow_for_an_ally():
    engine = _trio(bundle([ELEPHANT + "shelter_beneath_the_tusks"]))
    answers(engine, {"shelter_beneath_the_tusks": ["use"], "tusks_move": ["cell:5,5"], "tusks_option": ["target"]})  # beside both of them
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.armor_class = 0
    end_turns_until(engine, FOE)
    ally_hp, my_hp = ally.current_hp, me.current_hp
    _force_next_d20(engine, 19)
    use(engine, unarmed(engine, FOE), target=ALLY, actor_id=FOE)
    assert ally.current_hp == ally_hp and me.current_hp < my_hp and me.resources[STAMINA] == 59
    assert engine._distance_actor_to_actor(me, ally) <= 5  # it stepped in first


def test_the_body_remembers_the_creature_that_hurt_it():
    engine, me, foe = _elephant(["the_body_remembers"])
    end_turns_until(engine, FOE)
    me.armor_class = 0
    use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    assert any(c.condition_id == "condition:typed.mark.remembered." + ME for c in foe.conditions.values())
    end_turns_until(engine, ME)
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:])


def test_mountain_walking_sovereign_large_reach_speed_size_and_push():
    from combat import typed_executor as te

    engine, me, foe = _elephant(["mountain_walking_sovereign"], picks={"mountain_push": [FOE]}, foe_at=(8, 6))
    use(engine, "Mountain-Walking Sovereign")
    assert engine._effective_speed(me) == 25
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {}, [me], me, {})
    assert te.size_width(ctx, me, "subject", {}) == 4  # Large, and two more
    use(engine, "Move to 6,6")  # 15 feet; the Large footprint stops adjacent, then the free shove
    assert (foe.position.x, foe.position.y) == (9, 6)
    assert any(n.endswith("(extended reach)") for n in legal(engine))


def test_world_bearing_elephant_king_2d8_fists_4d8_and_anchored():
    engine, me, foe = _elephant(["world_bearing_elephant_king"])
    use(engine, "World-Bearing Elephant King")
    assert "SLASHING" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"} and engine._effective_speed(me) == 50
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") and "iron_fist" in str(r.reason) for r in engine.rolls[before:])
    assert any(r.expression.startswith("4d8") for r in engine.rolls[before:])
    before_push = me.position
    _shoved(engine, foe, me, 10)
    assert me.position == before_push  # a creature of its CL cannot push the grown footprint


# ------------------------------------------------------------------------------------------- Group 41: White Heron Crescent Body
# plug-ins: combat/ext/white_heron.py (Heron's Passing Cut, One-Legged Guard, Reaping Circle, White Wing, Moon over the Reed Sea),
# combat/ext/attack_lines.py (the sweep's Attack action), combat/ext/reach_bonus.py (+ the Constitution form's reach)
HERON = "tianxia.subpath.body.white_heron_crescent_body.feature."
JI = "tianxia.mortal.weapon.ji"
JI_CON = "Ji (Halberd) attack (Constitution)"


def _heron(ids, *, picks=None, foe_at=(4, 6)):
    sh = sheet([k if k.startswith("tianxia.path") else HERON + k for k in ["crescent_body_integration", *ids]], items=(JI,))
    sh["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]
    engine = fight(compile_character(sh, actor_id=ME), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_crescent_body_integration_reach_on_your_turn_and_herons_passing_cut():
    engine, me, foe = _heron([], picks={"herons_passing_cut": ["damage"]}, foe_at=(8, 6))
    use(engine, "Move to 5,6")  # 10 feet; the foe is 15 feet away
    before = len(engine.rolls)
    use(engine, JI_CON + " (extended reach)", target=FOE)
    assert me.resources[STAMINA] == 59 and any(r.expression.startswith("3d8") for r in engine.rolls[before:])  # CL18


def test_one_legged_guard_strikes_first_and_denies_the_attackers_reactions():
    engine, me, foe = _heron(["one_legged_guard"], picks={"one_legged_guard": ["deny"]})
    end_turns_until(engine, FOE)
    events = use(engine, unarmed(engine, FOE), target=ME, actor_id=FOE)
    first = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert first.actor_id == ME and me.resources[STAMINA] == 59  # before its attack
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_crescent_reaping_circle_sweeps_then_the_other_attacks():
    assert riders(HERON + "crescent_reaping_circle") == []
    engine, me, foe = _heron(["crescent_reaping_circle", "tianxia.path.body_refining.feature.extra_attack"],
                             picks={"reaping_circle_rider": ["deny"], "reaping_circle_move": None}, foe_at=(5, 6))
    before = len(engine.rolls)
    events = use(engine, "Crescent Reaping Circle (Ji (Halberd))")
    assert me.resources[STAMINA] == 58 and any(r.expression.startswith("3d8") for r in engine.rolls[before:])
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]) == 3


def test_white_wing_passes_through_the_foe_and_braces():
    engine, me, foe = _heron(["white_wing_crosses_the_reed_field"], picks={"white_wing_move": ["cell:5,6"], "white_wing_result": ["ac"]})
    use(engine, JI_CON, target=FOE)
    assert (me.position.x, me.position.y) == (5, 6)
    assert any(m.value == 2 and m.source_definition_id.endswith("white_wing_crosses_the_reed_field") for m in me.modifiers.values())


def test_moon_over_the_reed_sea_cuts_along_the_route_and_takes_the_stance():
    engine, me, foe = _heron(["moon_over_the_reed_sea"], picks={"moon_push_distance": ["10"]}, foe_at=(7, 6))
    before = len(engine.rolls)
    use(engine, "Moon over the Reed Sea", at=(12, 6))
    assert me.resources[STAMINA] == 53 and any(r.expression.startswith("10d8") for r in engine.rolls[before:])
    assert any(c.condition_id == "condition:typed.state.moon_reed_stance" for c in me.conditions.values())
    assert any(m.value == 2 and m.target_field == "armor_class" for m in me.modifiers.values())


# ------------------------------------------------------------------------------------------------------------ Group 42: Yamabushi
# plug-in: combat/ext/yamabushi.py (Waterfall Stance, Ascetic Body and Still as the Peak, Avatar of the Mountain); feature blocks in
# combat/rules/feature_blocks.d/riders_c7.json (Stone Skin's AC, Mountain's Wrath's objects)
YAMA = "tianxia.subpath.body.yamabushi.feature."


def _yama(ids, *, picks=None, foe_at=(4, 6), foe_cl=18, objects=()):
    engine = fight(bundle([YAMA + k for k in ids]), foe=bundle([], actor_id=FOE, name="C7 Foe", cl=foe_cl), foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def test_stone_skin_adds_one_ac_while_unarmored():
    document = sheet([YAMA + "stone_skin", "tianxia.path.body_refining.feature.unarmored_defense"])
    # Body Unarmored Defense is 10 + Constitution modifier + Proficiency Bonus.
    document["ability_scores_and_statistics"]["armor_class"] = {"base_value": 18, "value": 18}
    engine = fight(compile_character(document, actor_id=ME))
    me = engine.state.actors[ME]
    assert me.armor_class + engine._ac_modifier(me) == 19  # Unarmored Defense 18, plus Stone Skin 1


def test_waterfall_stance_saves_with_advantage_and_ends_when_unconscious():
    from combat import typed_executor as te

    engine, me, foe = _yama(["waterfall_stance"])
    use(engine, "Waterfall Stance")
    assert any(c.condition_id == "condition:typed.ignore_difficult" for c in me.conditions.values())
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == unarmed(engine, FOE))
    row = {"type": "save", "ability": "str", "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}], "on_success": []}
    before = len(engine.rolls)
    te.run_effects(te.Context(engine, foe, action, None, {**action.parameters["typed"], "effects": [row]}, [me], me, {}), [row])
    assert next(r for r in engine.rolls[before:] if str(r.reason).startswith("SAVE")).mode == "ADVANTAGE"
    engine._apply_condition(me, "condition:typed.unconscious", "test:ko", FOE, expires_on="UNTIL_REMOVED")
    assert not any(c.condition_id == "condition:typed.state.waterfall_stance" for c in me.conditions.values())


def test_mountains_wrath_breaks_the_ground_and_doubles_against_objects():
    engine, me, foe = _yama(["mountain_s_wrath"], objects=[{"id": 1, "kind": "door", "x": 5, "y": 6, "hp": 999}])
    events = use(engine, "Mountain's Wrath")
    assert any(e.event_type == "ZONE_CREATED" for e in events) and any(e.event_type == "OBJECT_UPDATED" for e in events)
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())


def test_ascetic_body_still_as_the_peak_takes_one_stamina_off():
    engine, me, foe = _yama(["ascetic_body", "waterfall_stance"])
    use(engine, "Waterfall Stance")  # it has not moved since its last turn
    assert me.resources[STAMINA] == 59  # 2 - 1


def test_avatar_of_the_mountain_holds_its_ground_and_strikes_harder():
    engine, me, foe = _yama(["avatar_of_the_mountain"], foe_cl=5)
    use(engine, "Avatar of the Mountain")
    assert engine._effective_speed(me) == 20 and "SLASHING" in {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    before = len(engine.rolls)
    use(engine, unarmed(engine), target=FOE)
    assert any(r.expression.startswith("2d8") for r in engine.rolls[before:])
    _shoved(engine, foe, me, 10)
    assert (me.position.x, me.position.y) == (3, 6)  # a CL5 source cannot move it


# ------------------------------------------------------------------------------------ Groups 31-42: what the fight stores
def test_groups_31_to_42_state_survives_a_saved_fight_round_trip():
    """Thresholds, Open Eyes, the Appraised mark, Tempering Forms and an Infestation are plain ints/strings/lists/dicts: a saved
    fight writes them as JSON and reads the same values back."""
    ids = ["tianxia.subpath.body.vermilion_gate_guardian_body.feature.guardian_at_the_gate",
           "tianxia.subpath.body.thousand_eyed_calamity_body.feature.calamity_appraisal",
           "tianxia.subpath.body.thousand_fold_steel_body.feature.body_forged_in_three_forms",
           PARASITE + "internal_brood", PARASITE + "gnawing_infestation"]
    engine = fight(bundle(ids), foe=_typed_foe(), foe_at=(6, 6))
    answers(engine, {"feature.internal_brood": ["Infesting Strike"], "open_eyes": ["4"], "calamity_appraisal": [FOE],
                     "tempering_forms": ["reed"], "threshold_orientation": ["north_south"], "threshold_center": ["cell:4,6"]})
    end_turns_until(engine, FOE)
    end_turns_until(engine, ME)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._gain_resource(me, BROOD, 1, "test")
    foe.position, foe.armor_class = Position(x=4, y=6), -50
    script(engine, [18, *([1] * 80)])  # deterministic failed rider save after the mastery-DC change
    use(engine, unarmed(engine), target=FOE)
    state = reloaded_state(engine)
    again_me, again_foe = state.actors[ME], state.actors[FOE]
    for key in ("_round_gate_thresholds", "_round_open_eyes"):
        assert again_me.turn_flags[key] == json.loads(json.dumps(me.turn_flags[key]))
    held = {c.condition_id: c.data for c in again_foe.conditions.values()}
    assert "condition:typed.mark.appraised_target." + ME in held and held[INFESTED]["owner"] == ME
    assert next(c.data["forms"] for c in again_me.conditions.values() if c.condition_id == "condition:typed.tempering_forms") == ["reed"]
