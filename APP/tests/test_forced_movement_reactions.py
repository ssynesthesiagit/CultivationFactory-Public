"""Reactions to being pushed or pulled (owner 2026-09-26, R2: "forced movement will be something important to be able to do
like the throws and pushes"). Before a typed push or pull moves a creature, its own forced_moved reaction and an ally's
ally_forced_moved reaction may answer; "reduce that movement by 10 feet" shortens it, down to none. An ally about to gain
a condition (knocked Prone) can be answered by ally_condition_gained.
"""

from pathlib import Path

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import Position

ROOT = Path(__file__).resolve().parents[1]
REACTOR = "actor:factory.pushed"
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
    engine = Gate2Engine(ROOT, match_seed="PUSHED", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, LEE, AN], "team_by_actor": {REACTOR: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_reaction_rows[REACTOR] = rows
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE}
    for actor_id, x in ((AN, 4), (REACTOR, 5), (LEE, 5)):
        engine.state.actors[actor_id].position = Position(x=x, y=6 if actor_id != LEE else 7)
    return engine


def _row(kind: str, **extra) -> dict:
    return {"block": "generic", "feature_id": f"TEST_{kind.upper()}", "name": kind, "kind": kind, "costs": [], "numbers": {"pb": 4},
            "effects": [{"type": "forced_movement", "distance_ft": 10, "flat": 0, "applies_to": "self",
                         "evidence": "reduce that movement by 10 feet"}], **extra}


def _push(engine: Gate2Engine, target_id: str, feet: int) -> None:
    pusher = engine.state.actors[AN]
    action = next(engine.action_catalog[a] for a in pusher.action_ids)
    ctx = typed_executor.Context(engine, pusher, action, None, {"numbers": {}, "effects": []}, [], None, {})
    typed_executor._push(ctx, engine.state.actors[target_id], feet, pull=False)


def test_your_own_reaction_shortens_a_push_to_nothing():
    engine = _engine([_row("forced_moved")])
    me = engine.state.actors[REACTOR]
    _push(engine, REACTOR, 10)
    assert (me.position.x, me.position.y) == (5, 6) and not me.reaction_available  # 10 ft reduced by 10: no move
    engine = _engine([])
    _push(engine, REACTOR, 10)
    assert engine.state.actors[REACTOR].position.x == 7  # no reaction: pushed 10 ft away from the pusher


def test_an_ally_in_range_shortens_the_push_on_its_ally():
    engine = _engine([_row("ally_forced_moved", range_ft=10)])
    ally = engine.state.actors[LEE]
    start = ally.position.x
    _push(engine, LEE, 15)
    assert ally.position.x == start + 1 and not engine.state.actors[REACTOR].reaction_available  # 15 ft - 10 ft = 5 ft
    far = _engine([_row("ally_forced_moved", range_ft=5)])
    far.state.actors[REACTOR].position = Position(x=12, y=6)
    _push(far, LEE, 15)
    assert far.state.actors[REACTOR].reaction_available  # out of its range: no answer


def test_an_ally_about_to_be_knocked_prone_can_be_answered():
    row = {**_row("ally_condition_gained", conditions=["prone"]),
           "effects": [{"type": "temp_hp", "flat": 4, "applies_to": "target", "evidence": "the ally gains 4 temporary HP"}]}
    engine = _engine([row])
    ally = engine.state.actors[LEE]
    from combat import typed_reactions

    typed_reactions.offer_condition_gained(engine, ally, engine.state.actors[AN], "frightened")
    assert engine.state.actors[REACTOR].reaction_available  # not the named condition
    typed_reactions.offer_condition_gained(engine, ally, engine.state.actors[AN], "prone")
    assert not engine.state.actors[REACTOR].reaction_available and ally.temporary_hp == 4
