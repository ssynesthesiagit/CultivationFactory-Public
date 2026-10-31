"""Reaction effects added so every reaction whose trigger runs also does something (owner 2026-09-26, R6: "i want all the
reactions usable"): negating an attack, moving as a reaction, deciding a roll's outcome, a rolled die on a pending roll,
countering a technique, holding a creature at 1 HP, taking an ally's damage, half the triggering damage.
"""

from pathlib import Path

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position

ROOT = Path(__file__).resolve().parents[1]
REACTOR = "actor:factory.r6"
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": []},
}


def _engine(rows: list[dict]) -> Gate2Engine:
    bundle = compile_character(SHEET, actor_id=REACTOR, typed_authority={"mechanics": {}})
    engine = Gate2Engine(ROOT, match_seed="R6", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, LEE, AN], "team_by_actor": {REACTOR: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_reaction_rows[REACTOR] = rows
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE}
    for actor_id, x in ((REACTOR, 5), (LEE, 6), (AN, 9)):
        engine.state.actors[actor_id].position = Position(x=x, y=6)
    return engine


def _row(kind: str, effects: list, **extra) -> dict:
    return {"block": "generic", "feature_id": f"TEST_{kind.upper()}", "name": f"Test {kind}", "kind": kind, "costs": [],
            "numbers": {"pb": 4, "cl": 10, "key_mod": 2, "attack_bonus": 40, "save_dc": 15}, "effects": effects, **extra}


def _typed_action(engine: Gate2Engine, actor_id: str, effects: list, target_kind: str = "HOSTILE_ENTITY", save_dc: int = 99) -> ActionDefinition:
    action = ActionDefinition(source_definition_id=f"action:typed.r6.{actor_id[-6:]}", display_name="R6 test", owner_id=actor_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=target_kind, range_ft=500,
                              parameters={"typed": {"effects": effects, "numbers": {"pb": 4, "save_dc": save_dc, "attack_bonus": 5, "cl": 10},
                                                    "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    actor = engine.state.actors[actor_id]
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return action


def _use(engine: Gate2Engine, actor_id: str, action: ActionDefinition, target_id: str) -> None:
    engine.state.current_actor_id = actor_id
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id and c.target_ids == (target_id,))
    engine.execute_intent(ActionIntent(intent_id="r6", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids))


def test_a_negated_attack_is_never_rolled():
    engine = _engine([_row("ally_attacked", [{"type": "negate_attack", "chance_d20": 1, "evidence": "negate it"}])])
    attack = [{"type": "attack", "attack_kind": "cultivation", "count": 1, "on_hit": [{"type": "damage", "dice": {"count": 2, "sides": 6}}], "on_miss": []}]
    _use(engine, AN, _typed_action(engine, AN, attack), LEE)
    ally = engine.state.actors[LEE]
    assert ally.current_hp == ally.maximum_hp
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == AN for e in engine.events)
    assert not engine.state.actors[REACTOR].reaction_available
    engine = _engine([_row("ally_attacked", [{"type": "negate_attack", "chance_d20": 21}])])  # never succeeds
    _use(engine, AN, _typed_action(engine, AN, attack), LEE)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == AN for e in engine.events)


def test_a_reaction_move_closes_on_the_triggering_creature():
    engine = _engine([])
    me, foe = engine.state.actors[REACTOR], engine.state.actors[AN]
    row = _row("moved", [{"type": "reaction_move", "direction": "toward", "distance_ft": "half_speed"}])
    before = engine.grid.distance_ft(me.position, foe.position)
    typed_reactions._run_generic_effects(engine, me, foe, row, row["effects"])
    assert engine.grid.distance_ft(me.position, foe.position) < before  # around the ally in the way, 15 ft at most


def test_a_set_outcome_overrides_a_failed_save():
    engine = _engine([])
    engine._typed_roll_outcome = {LEE: "success"}
    save = [{"type": "save", "ability": "dex", "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}], "on_success": []}]
    _use(engine, AN, _typed_action(engine, AN, save), LEE)  # DC 99: the roll fails
    assert not any(c.condition_id.endswith(".prone") for c in engine.state.actors[LEE].conditions.values())


def test_a_countered_technique_does_nothing():
    engine = _engine([_row("technique_used", [{"type": "counter_technique", "contest": "check"}], range_ft=60)])
    blast = [{"type": "damage", "dice": {"count": 3, "sides": 6}, "applies_to": "target"}]
    _use(engine, AN, _typed_action(engine, AN, blast, save_dc=14), LEE)  # the counter's d20+40 beats DC 14
    assert engine.state.actors[LEE].current_hp == engine.state.actors[LEE].maximum_hp
    assert not engine.state.actors[REACTOR].reaction_available


def test_hold_at_1hp_and_taking_an_allys_damage():
    engine = _engine([_row("ally_drop_to_zero", [{"type": "hold_at_1hp", "keep": 1}], range_ft=30)])
    ally = engine.state.actors[LEE]
    ally.current_hp = 8
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[AN], 20, 0, AN) == 7  # ends at 1 HP
    engine = _engine([_row("ally_damaged", [{"type": "redirect_damage_to_self"}], range_ft=60)])
    me = engine.state.actors[REACTOR]
    assert typed_reactions._offer_ally_damaged(engine, engine.state.actors[LEE], engine.state.actors[AN], 9, 0, AN) == 0
    assert me.current_hp == me.maximum_hp - 9


def test_a_rolled_die_and_half_the_triggering_damage():
    engine = _engine([_row("creature_d20", [{"type": "roll_die", "die": 6}], range_ft=60)])
    shaped = typed_reactions.on_d20_pending(engine, engine.state.actors[AN], "attack")
    assert -6 <= shaped["bonus"] <= -1  # subtracted from an enemy's roll
    engine = _engine([])
    engine._typed_trigger_damage = 30
    me = engine.state.actors[REACTOR]
    action = _typed_action(engine, REACTOR, [])
    ctx = typed_executor.Context(engine, me, action, None, action.parameters["typed"], [], None, {})
    assert ctx.formula("half_trigger_damage") == 15
