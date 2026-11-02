"""The combat moments R3-R5 add for the trigger readings (owner 2026-09-26: "i want all the reactions usable"): other
creatures' actions, reactions and rolls; turn starts and initiative; moving into range or out of reach; grapples; an ally
about to drop to 0; one effect damaging several creatures; your own Dodge and named follow-ups.
"""

from pathlib import Path

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import Position

ROOT = Path(__file__).resolve().parents[1]
REACTOR = "actor:factory.moments"
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": []},
}
TEMP = [{"type": "temp_hp", "flat": 3, "applies_to": "self", "evidence": "gain 3 temporary Hit Points"}]


def _engine(rows: list[dict]) -> Gate2Engine:
    bundle = compile_character(SHEET, actor_id=REACTOR, typed_authority={"mechanics": {}})
    engine = Gate2Engine(ROOT, match_seed="MOMENTS", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, LEE, AN], "team_by_actor": {REACTOR: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_reaction_rows[REACTOR] = rows
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE}
    for actor_id, x, y in ((REACTOR, 5, 6), (LEE, 6, 6), (AN, 9, 6)):
        engine.state.actors[actor_id].position = Position(x=x, y=y)
    return engine


def _row(kind: str, effects=None, **extra) -> dict:
    return {"block": "generic", "feature_id": f"TEST_{kind.upper()}", "name": f"Test {kind}", "kind": kind, "costs": [],
            "numbers": {"pb": 4}, "effects": effects if effects is not None else list(TEMP), **extra}


def _fired(engine: Gate2Engine) -> bool:
    return engine.state.actors[REACTOR].temporary_hp == 3


def test_a_pending_roll_is_hindered_for_an_enemy_and_helped_for_an_ally():
    penalty = [{"type": "attack_modifier", "flat": 2, "applies_to": "target", "evidence": "the roll takes a -2 penalty"}]
    engine = _engine([_row("creature_d20", penalty, range_ft=60, rolls=["attack"])])
    shaped = typed_reactions.on_d20_pending(engine, engine.state.actors[AN], "attack")
    assert shaped["bonus"] == -2 and not engine.state.actors[REACTOR].reaction_available
    engine = _engine([_row("creature_d20", penalty, range_ft=60, rolls=["save"])])
    assert typed_reactions.on_d20_pending(engine, engine.state.actors[AN], "attack")["bonus"] == 0  # not a save
    boon = [{"type": "attack_modifier", "flat": 2, "applies_to": "ally"}, {"type": "advantage", "applies_to": "ally"}]
    engine = _engine([_row("creature_d20", boon, range_ft=30, allies_only=True, rolls=["save"])])
    assert typed_reactions.on_d20_pending(engine, engine.state.actors[AN], "save")["bonus"] == 0  # an enemy's save: not for it
    shaped = typed_reactions.on_d20_pending(engine, engine.state.actors[LEE], "save")
    assert shaped == {"bonus": 2, "modes": ["ADVANTAGE"]}


def test_after_a_roll_naturals_and_failures_are_moments():
    engine = _engine([_row("creature_nat", range_ft=60, natural=[20])])
    typed_reactions.after_d20(engine, engine.state.actors[AN], "attack", success=True, natural=1, other=None)
    assert not _fired(engine)
    typed_reactions.after_d20(engine, engine.state.actors[AN], "attack", success=True, natural=20, other=None)
    assert _fired(engine)
    engine = _engine([_row("own_d20_fail")])
    typed_reactions.after_d20(engine, engine.state.actors[REACTOR], "save", success=False, natural=5, other=engine.state.actors[AN])
    assert _fired(engine)


def test_turn_starts_and_initiative():
    engine = _engine([_row("creature_turn_start", range_ft=60)])
    typed_reactions.on_turn_start(engine, engine.state.actors[LEE])
    assert not _fired(engine)  # an ally's turn: not the enemy the reading names
    typed_reactions.on_turn_start(engine, engine.state.actors[AN])
    assert _fired(engine)
    engine = _engine([_row("initiative")])
    first = engine.state.actors[engine.state.current_actor_id]
    engine.state.round_number, engine.state.current_slot_index, first.turns_started = 1, 0, 1
    typed_reactions.on_turn_start(engine, first)
    assert _fired(engine)


def test_an_enemy_entering_range_and_leaving_reach():
    engine = _engine([_row("enters_range", range_ft=10)])
    foe = engine.state.actors[AN]
    typed_reactions.on_moved_geometry(engine, foe, Position(x=9, y=6), Position(x=7, y=6))  # 20 ft -> 10 ft from the reactor
    assert _fired(engine)
    engine = _engine([_row("leaves_reach")])
    typed_reactions.on_moved_geometry(engine, engine.state.actors[AN], Position(x=6, y=7), Position(x=9, y=7))
    assert _fired(engine)  # from 5 ft (adjacent) to 20 ft


def test_actions_and_reactions_of_other_creatures():
    engine = _engine([_row("creature_acted", range_ft=60, economies=["BONUS_ACTION"])])
    typed_reactions.on_action_completed(engine, engine.state.actors[AN], "ACTION", "action:x")
    assert not _fired(engine)
    typed_reactions.on_action_completed(engine, engine.state.actors[AN], "BONUS_ACTION", "action:x")
    assert _fired(engine)
    engine = _engine([_row("reaction_used", range_ft=60)])
    typed_reactions._open(engine, {"feature_id": "FOE_REACTION"}, engine.state.actors[AN], (), "ATTACK_DECLARED")
    assert _fired(engine)


def test_an_ally_about_to_drop_to_zero_can_be_saved():
    heal = [{"type": "damage_modifier", "flat": 10, "applies_to": "ally", "evidence": "reduce the damage by 10"}]
    engine = _engine([_row("ally_drop_to_zero", heal, range_ft=30)])
    ally = engine.state.actors[LEE]
    ally.current_hp = 8
    left = typed_reactions._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[AN], 12, 0, AN)
    assert left == 2 and not engine.state.actors[REACTOR].reaction_available


def test_grapples_and_named_follow_ups():
    engine = _engine([_row("grapple_failed")])
    typed_reactions.on_grapple_outcome(engine, engine.state.actors[AN], engine.state.actors[REACTOR], grabbed=False)
    assert _fired(engine)
    engine = _engine([_row("ally_grapple_succeeded")])
    typed_reactions.on_grapple_outcome(engine, engine.state.actors[LEE], engine.state.actors[AN], grabbed=True)
    assert _fired(engine)
    counter = _row("attacked", [], name="Counterstrike")
    follow = _row("own_ability", source_name="Counterstrike", free=True)
    engine = _engine([counter, follow])
    typed_reactions._run_generic_effects(engine, engine.state.actors[REACTOR], engine.state.actors[AN], counter, [])
    assert _fired(engine) and engine.state.actors[REACTOR].reaction_available  # the follow-up rides it
