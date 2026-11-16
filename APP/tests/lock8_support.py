"""Shared compiled-character harness for isolated lock8 regressions."""
from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet
ME, ALLY, FOE = "actor:factory.c4_me", "actor:factory.c4_ally", "actor:factory.c4_foe"
FAIL, PASS = 50, -40

def bundle(*mids, cl=15, dc=16, actor_id=ME, score=14, kit=None):
    return compile_character(sheet(list(mids), cl=cl, dc=dc, score=score, kit=kit), actor_id=actor_id)

def fight(me, *, foe=None, ally=None, me_at=(3, 6), foe_at=(6, 6), ally_at=(3, 8), seed="C4"):
    foe = foe or bundle("SAND_BASE_SCOURING_HAND", actor_id=FOE, cl=5)
    bundles = [me, foe] + ([ally] if ally else [])
    ids = [b["actor_id"] for b in bundles]
    teams = {ME: "team:a", FOE: "team:b", ALLY: "team:a"}
    spots = {ME: me_at, FOE: foe_at, ALLY: ally_at}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": {i: teams[i] for i in ids},
        "starting_positions": {i: {"x": spots[i][0], "y": spots[i][1]} for i in ids}})
    turn(engine, ME)
    return engine

def turn(engine, actor_id):
    """Make it ``actor_id``'s turn, fresh economy."""
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor

def legal(engine):
    return {c.display_name for c in engine.legal_candidates()}

def use(engine, name, *, target=None, at=None, actor_id=None):
    actor_id = actor_id or engine.state.current_actor_id
    rows = [c for c in engine.legal_candidates() if (c.display_name == name or c.display_name.startswith(name + " at "))
            and (target is None or target in (c.target_ids or ()))
            and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert rows, f"{name!r} is not legal here; legal: {sorted({n.split(' at ')[0] for n in legal(engine)})[:60]}"
    c = rows[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id,
                                       target_ids=c.target_ids or ((target,) if target else ()), destination=c.destination))
    return engine.events[before:]

def held(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{name}"]

def payloads(events, kind):
    return [e.payload or {} for e in events if e.event_type == kind]

def ctx_of(engine, user_id, target_id, source, *, dc=16, pb=4, cl=15):
    """A typed context of ``source`` (a compiled action of ``user_id``) aimed at ``target_id``."""
    user, target = engine.state.actors[user_id], engine.state.actors[target_id]
    action = engine.action_catalog[source]
    typed = {**action.parameters["typed"], "numbers": {**action.parameters["typed"]["numbers"], "save_dc": dc, "pb": pb, "cl": cl}}
    return typed_executor.Context(engine, user, action, None, typed, [target], target, {})

def action_id(engine, owner, name):
    """The compiled action named ``name`` (or its first option, "Scouring Hand: ...")."""
    ids = engine.state.actors[owner].action_ids
    return next((a for a in ids if engine.action_catalog[a].display_name == name), None) or \
        next(a for a in ids if engine.action_catalog[a].display_name.startswith(name + ":"))
