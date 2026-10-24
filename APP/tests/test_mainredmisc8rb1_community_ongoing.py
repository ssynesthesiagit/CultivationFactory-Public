"""MAINREDMISC8RB1: Community keeps a recurring tick's origin when it moves half the damage to another Aegis bearer.

The moved part is the same delivery as the packet it came from, so it stays "ongoing" and cannot be answered as a fresh
blow (Take the Blow shares already do this in combat/ext/damage_sharing.py). Self-contained harness.
"""

from combat import pending_damage
from combat.ext import protection
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet

ME, ALLY, FOE = "actor:factory.rb1_me", "actor:factory.rb1_ally", "actor:factory.rb1_foe"
PR = "tianxia.talent.protection."
AEGIS_BASE = ("PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS", "PROTECTION_BASE_WARD", "PROTECTION_BASE_SUCCOR")
SCOUR = "SAND_BASE_SCOURING_HAND"
AXE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}


def bundle(*mids, cl=15, dc=16, actor_id=ME, score=14, kit=None):
    return compile_character(sheet(list(mids), cl=cl, dc=dc, score=score, kit=kit), actor_id=actor_id)


def turn(engine, actor_id):
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def use(engine, name, *, target=None):
    actor_id = engine.state.current_actor_id
    rows = [c for c in engine.legal_candidates() if (c.display_name == name or c.display_name.startswith(name + " at "))
            and (target is None or target in (c.target_ids or ()))]
    assert rows, f"{name!r} is not legal here"
    c = rows[0]
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id,
                                       target_ids=c.target_ids or ((target,) if target else ()), destination=c.destination))


def protect_community():
    me_bundle = bundle(*AEGIS_BASE, PR + "community", cl=15, dc=16)
    foe = bundle(SCOUR, actor_id=FOE, cl=5, kit=AXE)
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    bundles = [me_bundle, foe, ally]
    ids = [b["actor_id"] for b in bundles]
    teams = {ME: "team:a", FOE: "team:b", ALLY: "team:a"}
    spots = {ME: (3, 6), FOE: (4, 7), ALLY: (3, 7)}
    engine = Gate4ControllerEngine(ROOT, match_seed="RB1", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": {i: teams[i] for i in ids},
        "starting_positions": {i: {"x": spots[i][0], "y": spots[i][1]} for i in ids}})
    turn(engine, ME)
    return engine


def test_community_keeps_recurring_damage_ongoing_when_it_moves_to_another_bearer():
    engine = protect_community()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]

    use(engine, "Aegis: Armored Aegis (Persistent)", target=ALLY)
    me.action_available = True
    use(engine, "Aegis: Armored Aegis (Persistent)", target=ME)
    ally.current_hp = 10
    before = len(engine.events)
    with pending_damage.scope(engine, ally, 16, "SLASHING", "test:tick", FOE, damage_origin="ongoing"):
        left = protection.community(engine, ally, 16, "test:tick", FOE)
    assert left == 8
    moved = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert moved, "half the tick really moved to the other bearer"
    assert all(e.payload.get("damage_origin") == "ongoing" for e in moved), \
        "the transferred part still carries the recurring origin"
