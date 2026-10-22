"""C16 granted movement uses native OAs, checkpoints, geometry and saved receipts."""
import pytest

from combat import ext, granted_movement
from combat.ext import granted_moves
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from tests import lock8_support as S
from tests.h1_support import ROOT, script
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, ALLY, RIGHT, PROJECTS

PATROL = "GUARDIAN_BASE_PATROL_PRACTICE"
INTERPOSE = "GUARDIAN_CORE_INTERPOSE"
MERCIFUL = "TAL_IRON_FIST_MERCIFUL_HAND"


def request(engine):
    c = next(iter(engine.legal_candidates()))
    return ActionIntent(intent_id="grant-proof", decision_id=c.decision_id, candidate_id=c.candidate_id,
                        state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination)


@pytest.mark.parametrize("source,provokes,exempt,attacks", [(PATROL, True, (), 1), (INTERPOSE, False, (), 0),
                                                          (MERCIFUL, True, (S.FOE,), 0)])
def test_grant_provokes_or_explicitly_exempts_without_spending_ordinary_movement(source, provokes, exempt, attacks):
    # Interpose is a C16-generated core reaction, so compile its Guardian owner.
    e = S.fight(S.bundle(PATROL if source == INTERPOSE else source), foe_at=(4, 6))
    actor = e.state.actors[S.ME]
    intent = request(e)
    actor.movement_remaining_ft = 0
    script(e, [12] * 40)
    start = len(e.events)
    spent = e.grant_movement(actor, (actor.position, Position(x=2, y=6)), source,
                             feet=5, intent=intent, provokes=provokes, ignore_oa_from=exempt)
    assert spent == 5 and actor.position == Position(x=2, y=6) and actor.movement_remaining_ft == 0
    assert len([ev for ev in e.events[start:] if ev.event_type == "ATTACK_ROLLED" and ev.actor_id == S.FOE]) == attacks
    receipt = next(ev for ev in reversed(e.events) if ev.event_type == "MOVEMENT_COMMITTED")
    assert receipt.source_definition_id == source
    assert receipt.payload["cost_ft"] == 0 and receipt.payload["granted_cost_ft"] == 5


def test_grant_terrain_cost_and_speed_zero():
    e = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"), foe_at=(10, 6))
    actor = e.state.actors[S.ME]
    intent = request(e)
    e.grid.base_movement_cost[(2, 6)] = 2
    path = (actor.position, Position(x=2, y=6))
    before = actor.movement_remaining_ft
    assert e.grant_movement(actor, path, PATROL, feet=10, intent=intent) == 10
    assert actor.movement_remaining_ft == before
    e._apply_condition(actor, "condition:typed.pinned", "test:pin", S.FOE, expires_on="UNTIL_REMOVED")
    assert granted_movement.candidates(e, actor, 10, intent, PATROL) == {}
    assert e.grant_movement(actor, (actor.position, Position(x=1, y=6)), PATROL, feet=5, intent=intent) == 0
    assert actor.position == Position(x=2, y=6)


def test_partial_grant_returns_only_committed_distance(monkeypatch):
    e = S.fight(S.bundle(PATROL), foe_at=(10, 6))
    actor = e.state.actors[S.ME]
    intent = request(e)
    before = actor.movement_remaining_ft
    install(monkeypatch, "movement_step", lambda *args: {"stop": True, "source_id": "test:root",
                                                        "label": "Roots stop further movement."})
    assert e.grant_movement(actor, (actor.position, Position(x=2, y=6), Position(x=1, y=6)),
                             PATROL, feet=10, intent=intent) == 5
    assert actor.position == Position(x=2, y=6) and actor.movement_remaining_ft == before


def test_grant_uses_whole_path_fear_and_current_sight():
    e = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"), foe_at=(6, 6))
    actor, source = e.state.actors[S.ME], e.state.actors[S.FOE]
    intent = request(e)
    e._apply_condition(actor, "condition:typed.frightened", "test:fear", S.FOE, expires_on="UNTIL_REMOVED")
    path = (actor.position, Position(x=2, y=6), actor.position)
    with pytest.raises(ValueError, match="Frightened"):
        e.grant_movement(actor, path, PATROL, feet=10, intent=intent)
    e._apply_condition(source, "condition:typed.invisible", "test:vanish", S.FOE, expires_on="UNTIL_REMOVED")
    assert e.grant_movement(actor, path, PATROL, feet=10, intent=intent, provokes=False) == 10


@pytest.mark.parametrize("path,feet", [((Position(x=3, y=6), Position(x=1, y=6)), 10),
                                     ((Position(x=3, y=6), Position(x=2, y=6)), 0)])
def test_invalid_route_or_budget_rejected_before_mutation(path, feet):
    e = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"), foe_at=(10, 6))
    actor = e.state.actors[S.ME]
    intent = request(e)
    before = e.state.model_dump(mode="json")
    with pytest.raises(ValueError):
        e.grant_movement(actor, path, PATROL, feet=feet, intent=intent)
    assert e.state.model_dump(mode="json") == before


def test_oa_interruption_returns_actual_spend_before_rejected_step(monkeypatch):
    e = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"), foe_at=(4, 6))
    actor = e.state.actors[S.ME]
    intent = request(e)
    def stop(engine, event_type, kwargs):
        if event_type == "REACTION_WINDOW_OPENED" and kwargs.get("payload", {}).get("checkpoint") == "LEAVE_REACH":
            engine._apply_condition(actor, "condition:typed.pinned", "test:root", S.FOE, expires_on="UNTIL_REMOVED")
    install(monkeypatch, "event", stop)
    assert e.grant_movement(actor, (actor.position, Position(x=2, y=6)), PATROL, feet=5, intent=intent) == 0
    assert actor.position == Position(x=3, y=6)
    receipt = next(ev for ev in reversed(e.events) if ev.event_type == "MOVEMENT_COMMITTED")
    assert receipt.payload["granted_cost_ft"] == 0 and receipt.payload["interrupted"]


@pytest.mark.parametrize("use", [True, False])
@pytest.mark.parametrize("mover", [LEFT, ALLY])
@pytest.mark.parametrize("native_oa", [False, True])
def test_patrol_grant_oa_pause_commit_reload_and_replay(monkeypatch, tmp_path, use, mover, native_oa):
    from combat.tabletop import ButtonStore
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["right"], {"mode": "ask"}, {"opportunity_attack"})
    combat, table, mid = table_fight(tmp_path, [PATROL], ally_talents=[])
    if native_oa:
        # Exercise the native legacy resolver with its actual melee profile,
        # while keeping the accepted Table fixture's actor identities/roster.
        from combat.gate2_runtime_content import BASIC_MELEE, AN
        monkeypatch.setitem(BASIC_MELEE, RIGHT, BASIC_MELEE[AN])
    def grant(engine):
        actor = engine.state.actors[mover]
        assert engine._active_intent.actor_id == LEFT
        if native_oa:
            engine.typed_actor_ids.remove(RIGHT)
        try:
            spent = granted_moves.commit(engine, actor, (actor.position, Position(x=2, y=actor.position.y)), PATROL,
                                         budget_ft=5, provokes=True)
        finally:
            if native_oa:
                engine.typed_actor_ids.add(RIGHT)
        assert spent == 5
    on_hold(monkeypatch, grant)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    def send(answers=()):
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert paused['reaction']['by'] == ('Left' if mover == LEFT else 'Ally')
    assert 'd20' not in paused['reaction']['moment']
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    response = {**paused["reaction"]["context"], "selection": "USE" if use else "DECLINE", "option_ids": []}
    answers = [response]
    for _ in range(12):
        result = send(answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        # A landed opportunity attack can expose the defender's own optional
        # defenses. Preserve the OA answer and decline those unrelated choices.
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
    else:
        pytest.fail('opportunity attack did not finish after its follow-up choices')
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[mover].position == Position(x=2, y=4 if mover == LEFT else 5)
    assert loaded.engine.state.actors[mover].movement_remaining_ft == before["actors"][mover]["movement_remaining_ft"]
    assert loaded.engine.state.actors[RIGHT].reaction_available is not use
    attacks = [ev for ev in loaded.engine.events if ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == RIGHT]
    assert bool(attacks) is use
    assert all(ev.target_ids == (mover,) for ev in attacks)
    assert getattr(loaded.engine, '_reaction_trigger', None) is None
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize('checkpoint', ['LEAVE_REACH', 'TYPED:LEAVE_REACH@7'])
def test_nested_grant_trigger_restores_owner_and_preserves_answer_binding(checkpoint):
    from combat.reaction_trigger import trigger_scope, contextual_request
    from types import SimpleNamespace
    e = SimpleNamespace()
    request = dict(checkpoint=checkpoint, reactor_id='guard', reaction_source_id='oa',
                   attacking_actor_id='owner', protected_target_id='owner')
    with trigger_scope(e, 'LEAVE_REACH', actor_id='outer', target_id='outer', source_id=PATROL, roll_kind=''):
        assert contextual_request(e, request)['attacking_actor_id'] == 'outer'
        with pytest.raises(RuntimeError):
            with trigger_scope(e, 'LEAVE_REACH', actor_id='inner', target_id='inner', source_id=INTERPOSE, roll_kind=''):
                result = contextual_request(e, request)
                assert result['attacking_actor_id'] == result['protected_target_id'] == 'inner'
                assert all(result[k] == request[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
                raise RuntimeError('pause')
        assert contextual_request(e, request)['attacking_actor_id'] == 'outer'
    assert contextual_request(e, request) is request
