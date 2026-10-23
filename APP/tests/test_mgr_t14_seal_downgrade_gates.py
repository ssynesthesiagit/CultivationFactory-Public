"""Seal teleport and form gates must honor the active forced-downgrade scope (4F14R blockers).

Unit-level: stub engine/actors from the floor58 file; no live models, no service load.
"""
from types import SimpleNamespace

from combat.ext.qi_sealing_chains import MARK, seal_form, seal_teleport
from tests.test_mgr_t14_cultivator_of_seals_floor58 import _Actor, _Cond, _Engine


def _core(scope_kind, *, downgrade=None, until=0):
    data = {'grade': 'core', 'scope': {'kind': scope_kind, 'value': ''}, 'break_successes': 1}
    if downgrade:
        data.update(downgrade_scope={'kind': downgrade, 'value': ''}, downgraded_until_turn=until)
    return _Cond({'seal_feature': MARK, **data}, instance_id='core', source_actor_id='actor:src')


def _target(cond, turns_started):
    foe = _Actor('actor:foe', turns_started=turns_started)
    foe.conditions = {'core': cond}
    return foe, SimpleNamespace(engine=_Engine([foe]), actor=foe, source='src', typed={})


def test_downgraded_meridian_scope_lets_teleport_through_during_the_window():
    # Stored Core scope blocks teleportation, but the placer picked a Sphere scope for
    # the window that began at turn 0 and runs until the target's turn 3 starts.
    cond = _core('teleportation', downgrade='sphere', until=3)
    foe, ctx = _target(cond, turns_started=2)
    assert seal_teleport(ctx, None, None) is None
    # The window closes at the target's next turn: Core teleport block returns.
    foe.turns_started = 3
    assert seal_teleport(ctx, None, None) is False


def test_core_teleport_scope_still_blocks_without_a_downgrade():
    foe, ctx = _target(_core('teleportation'), turns_started=2)
    assert seal_teleport(ctx, None, None) is False


def test_downgraded_meridian_scope_lets_incorporeal_and_possession_through_during_the_window():
    cond = _core('incorporeal', downgrade='sphere', until=3)
    foe, ctx = _target(cond, turns_started=2)
    assert seal_form(ctx, foe, {'condition': 'incorporeal'}) is None
    cond.data['scope'] = {'kind': 'possession', 'value': ''}
    assert seal_form(ctx, foe, {'condition': 'possessing'}) is None
    foe.turns_started = 3
    assert seal_form(ctx, foe, {'condition': 'incorporeal'}) is False
    assert seal_form(ctx, foe, {'condition': 'possessing'}) is False


def test_core_form_scope_still_blocks_without_a_downgrade():
    foe, ctx = _target(_core('incorporeal'), turns_started=2)
    assert seal_form(ctx, foe, {'condition': 'incorporeal'}) is False


def test_door_gate_refusal_at_the_real_operation_gate_keeps_free_interaction(monkeypatch, tmp_path):
    # Addendum Q3: refuse at object_operation_gate itself (not by patching change_door);
    # the free object interaction must stay unclaimed and the door must stay shut.
    from combat import ext
    from combat.ext.door_interaction import FLAG
    from tests.test_door_interaction import DOOR, ME, setup as door_setup
    from combat.tabletop_service import TabletopService

    service, session = door_setup(tmp_path)
    table = TabletopService(service, tmp_path)
    menu = table.state(session.match_id)['menu']
    action = next(row for row in menu['actions'] if row['source_definition_id'] == 'system:door.open.free')
    original = ext.run_strict

    def refuse(name, *args):
        if name == 'object_operation_gate':
            return [False]
        return original(name, *args)

    monkeypatch.setattr(ext, 'run_strict', refuse)
    result = table.act(session.match_id, action['options'][0]['candidate_id'],
                       menu['decision_id'], menu['state_version'], 0, [])
    assert result['status'] == 'COMMITTED'
    loaded = service._load_session(session.match_id).engine
    actor = loaded.state.actors[ME]
    assert actor.action_available and FLAG not in actor.turn_flags
    assert loaded.state.objects[DOOR].component['door_open'] == 0
