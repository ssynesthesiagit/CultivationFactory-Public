"""Wind Lash Lift through native actions, table commits and cold replay."""
import pytest

from combat import flight
from combat.ext.next_jump import RECEIPT
from combat.tabletop import TabletopError
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, resolve, reload, turn
from tests.hunt15_support import action_sender

LIFT = "Wind Lash: Lift"


def setup(tmp_path, *, ask=True, allied=False, score=24, hit=True, roof=False,
          roof_height_ft=15, roof_recipient_x=1):
    arena_edit = None
    positions = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}}
    if roof:
        from combat.gate5_service import CombatService
        from tests.h1_support import ROOT
        from tests.test_walkable_roofs import roof_document
        maps = CombatService(ROOT, tmp_path)
        saved = maps.tabletop_maps.save(roof_document(roof_height_ft=roof_height_ft))
        arena = maps.factory_arenas(include_retired=True)["battlefield:map." + saved["map_id"]]
        def arena_edit(current):
            current.clear()
            current.update(arena)
        positions = {LEFT: {"x": 1, "y": 3}, RIGHT: {"x": roof_recipient_x, "y": 2}}
    combat, table, mid = fight(tmp_path, ["AIR_BASE_WIND_LASH"], spheres=["tianxia.sphere.air"], right_score=score,
                 left_attack_bonus=100 if hit else -100, reaction_ask=ask,
                 right_team="team:factory" if allied else "team:opponents",
                 extra_witness=allied,
                 positions=positions, arena_edit=arena_edit)
    if not ask:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    return combat, table, mid


def held(engine):
    return [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == RECEIPT]


def cast(combat, table, mid, *, willing=True, ai=False):
    return resolve(action_sender(combat, table, mid, LIFT, ai=ai, target_id=RIGHT),
                   {"choice:willing.consent": ["accept" if willing else "refuse"]})


def jump(combat, table, mid, *, height, run=False, land=False):
    from combat.falling import supported
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    rows = [c for c in engine.legal_candidates()
            if c.metadata.get("movement_mode") == "jump" and c.destination.z == height
            and (not run or any(a.z == b.z == 0 for a, b in zip(c.canonical_path, c.canonical_path[1:])))
            and (not land or supported(engine, actor, c.destination))]
    assert rows, (height, [(c.display_name, c.metadata) for c in engine.legal_candidates() if c.kind == "MOVE"])
    route = min(rows, key=lambda c: c.movement_cost_ft)
    menu = table.state(mid)
    resolve(lambda answers: table.act(mid, route.candidate_id, menu["menu"]["decision_id"],
            menu["menu"]["state_version"], menu["last_sequence"], answers))
    return route


def test_manual_hit_preview_reload_then_exactly_one_jump(tmp_path):
    combat, table, mid = setup(tmp_path, roof=True)
    _, prompts = cast(combat, table, mid)
    consent = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent")
    assert consent["context"]["reactor_id"] == RIGHT
    engine = reload(combat, mid)
    assert len(held(engine)) == 1
    receipt = held(engine)[0]
    assert receipt.source_actor_id == LEFT
    assert receipt.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert flight.jump_score(engine, engine.state.actors[RIGHT]) == (24, 5)
    assert all(type(v) in (int, str) for v in receipt.data.values())
    turn(table, mid, RIGHT)
    before = reload(combat, mid)
    for _ in range(2):
        table.state(mid)
        before.legal_candidates()
    assert len(held(reload(combat, mid))) == 1
    route = jump(combat, table, mid, height=3, run=True, land=True)
    engine = reload(combat, mid)
    committed = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
                 and e.actor_id == RIGHT and e.payload.get("movement_mode") == "jump"][-1]
    assert max(p.get("z", 0) for p in committed.payload["path"]) == 3
    assert committed.payload["cost_ft"] == route.movement_cost_ft
    assert not held(engine)
    assert flight.jump_score(engine, engine.state.actors[RIGHT]) == (24, 0)
    resolve(lambda answers: act(table, mid, "end", answers))
    turn(table, mid, RIGHT)
    jump(combat, table, mid, height=4)
    assert len([e for e in reload(combat, mid).events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("reason") == "NEXT_JUMP_COMMITTED"]) == 1


@pytest.mark.parametrize("ai_source", [False, True])
def test_automatic_allied_recipient_accepts_native_hit(tmp_path, ai_source):
    combat, table, mid = setup(tmp_path, ask=False, allied=True)
    _, prompts = cast(combat, table, mid, ai=ai_source)
    assert not any(p["context"]["reaction_source_id"] == "choice:willing.consent" for p in prompts)
    assert len(held(reload(combat, mid))) == 1
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")
    turn(table, mid, RIGHT)
    jump(combat, table, mid, height=3, run=True)
    assert not held(reload(combat, mid))


@pytest.mark.parametrize("ask,willing,hit", [(True, False, True), (False, False, True), (True, True, False)])
def test_refusal_or_miss_never_prepares_jump(tmp_path, ask, willing, hit):
    combat, table, mid = setup(tmp_path, ask=ask, hit=hit)
    _, prompts = cast(combat, table, mid, willing=willing)
    if not ask:
        assert not any(p["context"]["reaction_source_id"] == "choice:willing.consent" for p in prompts)
    assert not held(reload(combat, mid))


def test_source_next_turn_expiry_not_recipient_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    assert held(reload(combat, mid))
    turn(table, mid, LEFT)
    assert not held(reload(combat, mid))


def test_manual_recipient_is_asked_on_ai_source_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    _, prompts = cast(combat, table, mid, ai=True)
    consent = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent")
    assert consent["context"]["reactor_id"] == RIGHT
    assert len(held(reload(combat, mid))) == 1
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    turn(table, mid, RIGHT)
    jump(combat, table, mid, height=3, run=True)
    assert not held(reload(combat, mid))


def test_manual_willingness_on_own_turn_self_hit_and_standing_jump(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert not any(c.metadata.get("movement_mode") == "jump" and len(c.canonical_path) == 2
                   for c in engine.legal_candidates())
    _, prompts = resolve(action_sender(combat, table, mid, LIFT, target_id=LEFT),
                         {"choice:willing.consent": ["accept"]})
    assert any(p["context"]["reactor_id"] == LEFT and
               p["context"]["reaction_source_id"] == "choice:willing.consent" for p in prompts)
    engine = reload(combat, mid)
    assert flight.jump_score(engine, engine.state.actors[LEFT]) == (14, 5)
    standing = next(c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "jump"
                    and len(c.canonical_path) == 2 and c.destination.z == 1)
    state = table.state(mid)
    resolve(lambda answers: table.act(mid, standing.candidate_id, state["menu"]["decision_id"],
            state["menu"]["state_version"], state["last_sequence"], answers))
    engine = reload(combat, mid)
    assert flight.jump_score(engine, engine.state.actors[LEFT]) == (14, 0)
    assert not any(c.condition_id == RECEIPT for c in engine.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO", "API_AUTO"])
def test_strength_24_lift_adds_full_five_feet_to_standing_jump_and_cold_reloads(tmp_path, control):
    combat, table, mid = setup(tmp_path, score=24, roof=True, roof_height_ft=10, roof_recipient_x=3)
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert flight.jump_steps(engine, actor, (actor.position,)) == 1
    _, prompts = cast(combat, table, mid)
    assert any(p["context"]["reactor_id"] == RIGHT and
               p["context"]["reaction_source_id"] == "choice:willing.consent" for p in prompts)
    turn(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode=control)
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == RIGHT
                   for e in engine.events)
    assert flight.jump_steps(engine, actor, (actor.position,)) == 2
    standing = next(c for c in engine.legal_candidates()
                    if c.metadata.get("movement_mode") == "jump" and len(c.canonical_path) == 4
                    and c.destination.x == actor.position.x + 1 and c.destination.y == actor.position.y
                    and c.destination.z == actor.position.z + 2)
    # Two vertical steps followed by one level supported landing, no run-up.
    assert all(p.x == actor.position.x and p.y == actor.position.y
               for p in standing.canonical_path[:3])
    assert len(held(reload(combat, mid))) == 1  # Quotes never consume it.
    # All seats receive the route. Hand AI seats back to the player to commit
    # the same native candidate through the manual table transaction.
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")
    state = table.state(mid)
    resolve(lambda answers: table.act(mid, standing.candidate_id, state["menu"]["decision_id"],
            state["menu"]["state_version"], state["last_sequence"], answers))
    engine = reload(combat, mid)
    committed = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
                 and e.actor_id == RIGHT and e.payload.get("movement_mode") == "jump"][-1]
    assert committed.payload["path"] == [p.model_dump(mode="json") for p in standing.canonical_path]
    assert committed.payload["cost_ft"] == 15  # Ten feet up, five feet onto the roof.
    assert engine.state.actors[RIGHT].position == standing.destination
    assert not held(engine)
    assert flight.jump_score(engine, engine.state.actors[RIGHT]) == (24, 0)
    assert len([e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("reason") == "NEXT_JUMP_COMMITTED"]) == 1


def test_rejected_route_and_uncommitted_choice_preserve_receipt(tmp_path):
    combat, table, mid = setup(tmp_path)
    state = table.state(mid)
    result = act(table, mid, LIFT, target_id=RIGHT)
    assert result["status"] == "REACTION_REQUIRED"
    assert not held(reload(combat, mid))
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    state = table.state(mid)
    before = reload(combat, mid).state.model_dump(mode="json")
    actor = reload(combat, mid).state.actors[RIGHT]
    with pytest.raises(TabletopError):
        table.preview_move_path(mid, decision_id=state["menu"]["decision_id"],
            state_version=state["menu"]["state_version"], actor_id=RIGHT,
            waypoints=[{"x": actor.position.x, "y": actor.position.y, "z": z} for z in range(5)],
            movement_mode="jump")
    assert reload(combat, mid).state.model_dump(mode="json") == before
    assert held(reload(combat, mid))


def test_accepted_jump_runup_stopped_before_takeoff_keeps_receipt(tmp_path, monkeypatch):
    from combat import ext
    combat, table, mid = setup(tmp_path)
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    # A deterministic stop subscriber exercises the documented native reaction
    # boundary. Lift itself still comes from a real compiled attack/hit/consent.
    def stop(engine, mover, previous, nxt, intent):
        if mover.entity_id == RIGHT and nxt.z > previous.z:
            return {"stop": True, "source_id": "test:takeoff_stop", "label": "The ascent is blocked."}
    subscribers = list(ext._HOOKS.get("movement_attempt", []))
    monkeypatch.setitem(ext._HOOKS, "movement_attempt", subscribers + [stop])
    jump(combat, table, mid, height=3, run=True)
    engine = reload(combat, mid)
    movement = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == RIGHT][-1]
    assert movement.payload["interrupted"] and movement.payload["cost_ft"] >= 10
    assert max(p.get("z", 0) for p in movement.payload["path"]) == 0
    assert held(engine)
    monkeypatch.setitem(ext._HOOKS, "movement_attempt", subscribers)
    jump(combat, table, mid, height=1)
    assert not held(reload(combat, mid))


def test_jump_down_spends_only_when_leaving_roof_support(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_walkable_roofs import roof_document, route

    maps = CombatService(ROOT, tmp_path)
    saved = maps.tabletop_maps.save(roof_document(roof_height_ft=15))
    arena = maps.factory_arenas(include_retired=True)["battlefield:map." + saved["map_id"]]
    def authored_arena(current):
        current.clear()
        current.update(arena)
    combat, table, mid = fight(tmp_path, ["AIR_BASE_WIND_LASH"], left_attack_bonus=100,
        right_score=24, arena_edit=authored_arena,
        positions={LEFT: {"x": 7, "y": 3, "z": 3}, RIGHT: {"x": 6, "y": 3, "z": 3}})
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    def stop(engine, mover, previous, nxt, intent):
        if mover.entity_id == RIGHT and nxt.x == 3:
            return {"stop": True, "source_id": "test:edge_stop", "label": "The edge step is blocked."}
    subscribers = list(ext._HOOKS.get("movement_attempt", []))
    monkeypatch.setitem(ext._HOOKS, "movement_attempt", subscribers + [stop])
    route(combat, table, mid, [(6, 3, 3), (5, 3, 3), (4, 3, 3), (3, 3, 3)], mode="jump_down")
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].position.x == 4
    assert engine.state.actors[RIGHT].position.z == 3
    assert held(engine)
    monkeypatch.setitem(ext._HOOKS, "movement_attempt", subscribers)
    route(combat, table, mid, [(4, 3, 3), (3, 3, 3)], mode="jump_down")
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].position.z == 0
    assert not held(engine)
