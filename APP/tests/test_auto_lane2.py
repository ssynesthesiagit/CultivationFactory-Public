"""Automation push 2026-09-29, lane 2: combat abilities that were RIDERS_ONLY (a fight showed only the GM's text) typed and run.

Overrides live in authority/typed_mechanics/reviewed_final.d/auto_lane2.json; plug-ins in combat/ext/ (hold_still.py, ...).
Every test compiles a real character with the ability and runs it through the engine, and reads what the printed text says
happens; each fails on the typing the authority carried before (no effects: the ability was a GM line).
"""

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

import combat.factory_compiler as factory_compiler
from combat import ext, motion
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.lane2"
ALLY = "actor:factory.lane2ally"
FOCUS = "resource:core.martial_focus"
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=4)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def _mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))


def _sheet(sphere, talents, *, cl=10, dc=16, path="Body Refining", extra_spheres=(), owned_extra=()):
    spheres = [sphere, *extra_spheres] if sphere else list(extra_spheres)
    bases = [key for key, mech in _mechanics().items() if mech.get("sphere_id") in spheres and mech.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": path, "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [KIT],
        "spheres_and_talents": {"sphere_record_ids": spheres, "learned_talent_record_ids": [*talents, *owned_extra],
                                "automatic_sphere_component_record_ids": bases},
    }


def _bundle(sphere, talents, **kw):
    return compile_character(_sheet(sphere, talents, **kw), actor_id=ME)


def _rows(bundle):
    return {row["display_name"]: row for row in bundle["action_catalog"]}


def _engine(bundle, *, foe_at=(4, 6), ally=False):
    bundles, teams, places = (bundle,), {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    roster = [ME, AN]
    if ally:  # a friend standing beside the user (no talents of its own)
        bundles += (compile_character(_sheet(None, []), actor_id=ALLY),)
        roster.append(ALLY)
        teams[ALLY], places[ALLY] = "team:a", {"x": 2, "y": 6}
    engine = Gate4ControllerEngine(ROOT, match_seed="LANE2", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": roster, "team_by_actor": teams, "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50  # every attack hits
    _ready(engine)
    return engine


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def _legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _use(engine, name, target=AN):
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not a legal action; legal: {sorted(_legal(engine))}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids or ((target,) if target else ()), destination=candidate.destination))
    return engine.events[before:]


def _me(engine):
    return engine.state.actors[ME]


def _foe(engine):
    return engine.state.actors[AN]


def _payloads(events, event_type):
    return [getattr(e, "payload", None) or {} for e in events if e.event_type == event_type]


def _conditions(actor):
    return {c.condition_id.removeprefix("condition:") for c in actor.conditions.values()}


def _walk(engine, cells):
    """The user's own walk, as the table logs one (gate2_engine._resolve_movement)."""
    engine._append_event("MOVEMENT_COMMITTED", "test:walk", actor_id=ME,
                         payload={"destination": {"x": 3 + cells, "y": 6}, "path": [{"x": 3 + i, "y": 6} for i in range(cells + 1)],
                                  "cost_ft": 5 * cells})


# --------------------------------------------------------------------------------------------------- Lotus Step


def test_lotus_step_ignores_difficult_terrain_and_provokes_nothing():
    """"Until the end of your turn: ignore nonmagical difficult terrain; ... do not provoke opportunity attacks": a Bonus Action
    for 1 CP that did nothing (RIDERS_ONLY)."""
    engine = _engine(_bundle("tianxia.sphere.flowers", ["TAL_FLOWERS_LOTUS_STEP"]))
    me = _me(engine)
    assert not motion.ignores_difficult(engine, me) and not me.turn_flags.get("disengaged")
    stamina = next(key for key in me.resources if key.endswith("core.stamina"))
    before = me.resources[stamina]
    _use(engine, "Lotus Step", target=None)
    assert me.resources[stamina] == before - 1
    assert "typed.ignore_difficult" in _conditions(me) and motion.ignores_difficult(engine, me)
    assert me.turn_flags.get("disengaged")
    engine._expire_for_checkpoint("END_OF_TURN", ME)  # "until the end of your turn"
    assert "typed.ignore_difficult" not in _conditions(me) and not motion.ignores_difficult(engine, me)


# ----------------------------------------------------------------------------------- Shift Position, Rest Hold


def test_shift_position_regains_martial_focus_only_after_holding_still():
    """"If you move no more than 5 feet during your turn, you may regain Martial Focus as a Bonus Action": a GM line."""
    engine = _engine(_bundle("tianxia.sphere.sniper", ["TAL_SNIPER_SHIFT_POSITION"]))
    me = _me(engine)
    me.resources[FOCUS] = 0
    assert "Shift Position" in _legal(engine)
    _walk(engine, 1)  # 5 feet: still inside the limit
    assert "Shift Position" in _legal(engine)
    _walk(engine, 1)  # 10 feet in all
    assert "Shift Position" not in _legal(engine)


def test_shift_position_gains_focus_and_keeps_the_turn_inside_the_limit():
    engine = _engine(_bundle("tianxia.sphere.sniper", ["TAL_SNIPER_SHIFT_POSITION"]))
    me = _me(engine)
    me.resources[FOCUS] = 0
    _walk(engine, 1)
    me.movement_remaining_ft = 25
    _use(engine, "Shift Position", target=None)
    assert me.resources[FOCUS] == 1
    assert me.movement_remaining_ft == 0  # 5 of the allowed 5 feet are gone


def test_shift_position_ignores_a_push():
    """A push is not "you move": only the user's own movement counts against the limit."""
    engine = _engine(_bundle("tianxia.sphere.sniper", ["TAL_SNIPER_SHIFT_POSITION"]))
    _me(engine).resources[FOCUS] = 0
    engine._append_event("MOVEMENT_COMMITTED", "test:push", actor_id=ME,
                         payload={"destination": {"x": 9, "y": 6}, "path": [{"x": 3, "y": 6}, {"x": 9, "y": 6}], "cost_ft": 0, "forced": True})
    assert "Shift Position" in _legal(engine)


def _grapple(engine):
    engine._apply_condition(_foe(engine), "condition:typed.grappled", "test:grapple", ME, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 12, "reach_ft": 5})


def test_rest_hold_needs_a_grapple_then_stops_speed_and_gives_half_cover():
    """"While grappling one creature, use a Bonus Action and reduce your Speed to 0 ... Regain Martial Focus ... the Grappled
    creature grants you Half Cover against attacks made by creatures other than itself"."""
    engine = _engine(_bundle("tianxia.sphere.wrestling", ["TAL_WRESTLING_REST_HOLD"]))
    me = _me(engine)
    me.resources[FOCUS] = 0
    assert "Rest Hold" not in _legal(engine)  # nobody in its grip
    _grapple(engine)
    assert "Rest Hold" in _legal(engine)
    _use(engine, "Rest Hold", target=None)
    assert me.resources[FOCUS] == 1
    assert "typed.rest_hold" in _conditions(me)
    assert me.movement_remaining_ft == 0 and engine._effective_speed(me) == 0
    third = SimpleNamespace(entity_id="actor:someone.else")
    assert [bonus for bonus in ext.run("cover", engine, third, me) if bonus] == [2]  # Half Cover against anyone else ...
    assert not any(ext.run("cover", engine, _foe(engine), me))  # ... but not the held creature
    assert "Rest Hold" not in _legal(engine)  # already holding

    # the hold ends with the grapple, and with the start of the user's next turn
    engine._remove_condition(_foe(engine), "condition:typed.grappled", "test")
    assert not any(ext.run("cover", engine, third, me))


# -------------------------------------------------------------------------------------- Stone Womb Preservation

SHELL = "typed.stone_shell"


def _womb(*, incapacitated=True):
    engine = _engine(_bundle("tianxia.sphere.source", ["tianxia.talent.source.stone_womb_preservation"]), ally=True)
    ally = engine.state.actors[ALLY]
    if incapacitated:
        engine._apply_condition(ally, "condition:typed.incapacitated", "test:incapacitate", AN, expires_on="UNTIL_REMOVED")
    return engine, ally


def _womb_numbers(engine):
    row = next(r for r in engine.action_catalog.values() if r.display_name == "Stone Womb Preservation")
    numbers = row.parameters["typed"]["numbers"]
    return 10 + int(numbers["key_mod"]) + int(numbers["pb"])


def _hit(engine, target, amount, kind="SLASHING"):
    engine._commit_damage(target, amount, kind, "test:blow", AN, None, reaction_depth=0)


def _resistances(actor):
    return {m.value for m in actor.modifiers.values() if m.target_field == "damage_resistance"}


def test_stone_womb_shells_an_incapacitated_ally_with_resistance_and_no_movement():
    """"Touch a willing ... Incapacitated creature ... encased ... Resistance to all damage ... cannot move or take actions":
    an Action that did nothing (RIDERS_ONLY, no effects)."""
    engine, ally = _womb(incapacitated=False)
    assert "Stone Womb Preservation" not in _legal(engine)  # nothing it may touch: the ally is up and well
    engine._apply_condition(ally, "condition:typed.incapacitated", "test:incapacitate", AN, expires_on="UNTIL_REMOVED")
    stamina = next(key for key in _me(engine).resources if key.endswith("core.stamina"))
    before = _me(engine).resources[stamina]
    _use(engine, "Stone Womb Preservation", target=ALLY)
    assert _me(engine).resources[stamina] == before - 4  # "spend 4 CP"
    assert SHELL in _conditions(ally)
    assert {"SLASHING", "FIRE", "PSYCHIC", "FORCE"} <= _resistances(ally)  # "all damage"
    assert engine._effective_speed(ally) == 0
    assert "Stone Womb Preservation" not in _legal(engine)  # one shell is enough
    hp = ally.current_hp
    _hit(engine, ally, 10)
    assert ally.current_hp == hp - 5  # Resistance halves it


def test_stone_womb_breaks_at_ten_plus_key_modifier_plus_pb():
    engine, ally = _womb()
    limit = _womb_numbers(engine)
    _use(engine, "Stone Womb Preservation", target=ALLY)
    _hit(engine, ally, 2 * (limit - 1) - 1)  # what the shell takes after Resistance is one short of the number
    assert SHELL in _conditions(ally) and _resistances(ally)
    _hit(engine, ally, 4)  # the next blow (2 after Resistance) reaches it
    assert SHELL not in _conditions(ally) and not _resistances(ally)
    assert any(p.get("reason") == "BROKEN" for p in _payloads(engine.events, "MODIFIER_REMOVED"))


def test_stone_womb_ends_when_the_target_regains_hit_points():
    engine, ally = _womb()
    _use(engine, "Stone Womb Preservation", target=ALLY)
    _hit(engine, ally, 10)
    before, ally.current_hp = ally.current_hp, ally.current_hp + 3
    engine._append_event("HEALING_APPLIED", "test:heal", actor_id=ME, target_ids=(ALLY,), payload={"offered": 3, "before": before, "after": ally.current_hp})
    assert SHELL not in _conditions(ally) and not _resistances(ally)


def test_stone_womb_can_be_dismissed_and_ends_at_the_casters_next_turn():
    engine, ally = _womb()
    assert "Dismiss Stone Womb" not in _legal(engine)
    _use(engine, "Stone Womb Preservation", target=ALLY)
    assert "Dismiss Stone Womb" in _legal(engine)
    _use(engine, "Dismiss Stone Womb", target=None)
    assert SHELL not in _conditions(ally) and not _resistances(ally)
    assert "Dismiss Stone Womb" not in _legal(engine)

    _ready(engine)
    _use(engine, "Stone Womb Preservation", target=ALLY)
    engine._expire_for_checkpoint("START_OF_TURN", ME)  # "until the start of your next turn"
    assert SHELL not in _conditions(ally) and not _resistances(ally)


# ------------------------------------------------------------------------------- Silken Whip, Paper Dragon (Qi subpaths)

QI = "resource:core.qi"
WHIP_ID = "tianxia.subpath.qi.iron_cloth_cultivator.feature.silken_whip"
DRAGON_ID = "tianxia.subpath.qi.paper_cultivator.feature.paper_dragon"


def _feature_bundle(feature_id, *, cl=10):
    sheet = _sheet(None, [], cl=cl, path="Qi Cultivation")
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"], "path_feature_record_ids": [feature_id]}
    sheet["ability_scores_and_statistics"]["primary_resource"] = {"name": "Qi", "maximum": 60}
    return compile_character(sheet, actor_id=ME)


def test_silken_whip_is_infused_once_then_strikes_at_fifteen_feet():
    """"Infuse Cloth (Bonus Action, 1 Qi): the selected cloth becomes a Silken Whip ... Reach 15 feet, 1d8 Bludgeoning, Slashing,
    or Force, Cultivation Attack Modifier; one at a time": the whole feature was a GM line (RIDERS_ONLY)."""
    engine = _engine(_feature_bundle(WHIP_ID), foe_at=(6, 6))  # three squares: 15 feet
    me, foe = _me(engine), _foe(engine)
    assert "Silken Whip" in _legal(engine) and "Silken Whip Attack" not in _legal(engine)  # no whip yet
    qi = me.resources[QI]
    _use(engine, "Silken Whip", target=None)
    assert me.resources[QI] == qi - 1
    assert "typed.silken_whip" in _conditions(me)
    _ready(engine)
    assert "Silken Whip" not in _legal(engine)  # "one Silken Whip at a time"
    hp = foe.current_hp
    events = _use(engine, "Silken Whip Attack")
    hit = _payloads(events, "DAMAGE_COMMITTED")
    assert hit and hit[0]["damage_type"] in {"BLUDGEONING", "SLASHING", "FORCE"}
    assert foe.current_hp < hp
    assert 1 + 3 <= hit[0]["rolled_or_pending_damage"] <= 8 + 3  # 1d8 + the key ability modifier (+3)


def test_silken_whip_reach_is_fifteen_feet_not_more():
    engine = _engine(_feature_bundle(WHIP_ID), foe_at=(7, 6))  # 20 feet
    _use(engine, "Silken Whip", target=None)
    _ready(engine)
    assert not [c for c in engine.legal_candidates() if c.display_name == "Silken Whip Attack" and AN in (c.target_ids or ())]


def test_paper_dragon_is_summoned_with_its_printed_statistics():
    """"Create a Large Paper Dragon ... AC 14 + PB, Hit Points 5 x CL, Resistance B/P/S, Vulnerability Fire, Immunity Poison and
    Psychic, Paper Bite: 2d8 + key modifier, reach 10 feet": a GM line, no dragon on the map."""
    from combat import summons

    engine = _engine(_feature_bundle(DRAGON_ID))
    me = _me(engine)
    assert not [d for d in summons.owned_by(engine, ME, "paper_dragon") if d.active]
    qi = me.resources[QI]
    _use(engine, "Paper Dragon", target=None)
    assert me.resources[QI] == qi - 5
    [dragon] = [d for d in summons.owned_by(engine, ME, "paper_dragon") if d.active]
    assert dragon.team_id == me.team_id and dragon.armor_class == 14 + 4 and dragon.maximum_hp == 5 * 10
    assert me.concentration is not None
    bite = next(row for row in engine.action_catalog.values() if row.owner_id == dragon.entity_id and row.display_name == "Paper Bite")
    assert bite.range_ft == 10
    typed = bite.parameters["typed"]
    assert typed["weapon"]["damage"] == {"count": 2, "sides": 8, "modifier": 3} and typed["weapon"]["damage_types"] == ["SLASHING", "FORCE"]

    def defence(kind):
        return {kind_name for row in engine.typed_passive_rows.get(dragon.entity_id, []) if row.get("kind") == kind
                for kind_name in row.get("damage_types") or []}
    assert defence("resistance") == {"BLUDGEONING", "PIERCING", "SLASHING"} and defence("vulnerability") == {"FIRE"}
    assert defence("immunity") == {"POISON", "PSYCHIC"}


def test_paper_dragon_bite_grows_to_3d8_at_cl17():
    from combat import summons

    engine = _engine(_feature_bundle(DRAGON_ID, cl=17))
    _use(engine, "Paper Dragon", target=None)
    [dragon] = [d for d in summons.owned_by(engine, ME, "paper_dragon") if d.active]
    bite = next(row for row in engine.action_catalog.values() if row.owner_id == dragon.entity_id and row.display_name == "Paper Bite")
    assert bite.parameters["typed"]["weapon"]["damage"]["count"] == 3


# ---------------------------------------------------------------------------------------- not fight mechanics

OUTSIDE = ["TAL_BERSERKER_RIFT_STRIKE", "tianxia.talent.illusion.mirage",
           "tianxia.talent.poison.valley_of_poisonous_immortals", "tianxia.talent.stars.celestial_observatory",
           "tianxia.talent.thread.hidden_fiber", "tianxia.talent.karma.witness_seal"]


@pytest.mark.parametrize("mechanic_id", OUTSIDE)
def test_travel_downtime_and_scene_abilities_are_listed_as_outside_fights(mechanic_id):
    """Rift Strike (100 miles per CL), Mirage (a 24-hour terrain illusion that creates no Cover or hazard), the 30-day
    Valley and Observatory projects, Hidden Fiber and Witness Seal have nothing the fight runs: the sheet files them
    under "outside fights" (combat/rules/feature_status.d/auto_lane2.json), not under "not automated yet"."""
    mechanic = _mechanics()[mechanic_id]
    bundle = _bundle(mechanic["sphere_id"], [mechanic_id], cl=15)
    skipped = bundle["diagnostics"]["skipped"]
    assert mechanic["name"] in skipped["outside"], skipped
    assert all(mechanic["name"] not in skipped[kind] for kind in ("passive", "reaction", "not_typed")), skipped
