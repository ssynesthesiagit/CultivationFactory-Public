"""Formula Intensification movement keeps fear and unknown blockers private."""
import pytest
from combat import ext
from combat.gate5_service import CombatServiceError
from combat.gate2_runtime_models import Position
from tests.test_lock8_alchemy_table import fight, reload_checked, OWNER, FOE, INTENSIFY
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

NAME = 'Field Formula: Numbing Smoke + Formula Intensification: Move Self'
BLOCKER = 'actor:factory.bbbbbbbb'


def options(result):
    assert result['status'] == 'REACTION_REQUIRED'
    return {row['id'] for row in result['reaction']['choice']['options']}


def test_frightened_granted_move_refuses_closer_destination_and_reloads(monkeypatch, tmp_path):
    service, ui, mid = fight(monkeypatch, tmp_path, INTENSIFY, foe_hp=60)
    def afraid(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            engine._apply_condition(engine.state.actors[OWNER], 'condition:typed.frightened',
                'test:fear', FOE, expires_on='UNTIL_REMOVED')
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), afraid])
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(service, ui, mid, NAME, at=(6,4))
    paused = send(); offered = options(paused)
    assert 'cell:4,4' not in offered and 'cell:3,3' in offered
    # A forged closer response cannot choose a destination the legal menu excludes.
    with pytest.raises(CombatServiceError, match='completed intent was rejected'):
        send([{**paused['reaction']['context'], 'selection': 'USE', 'option_ids': ['cell:4,4']}])
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    commit(send, lambda prompt: ('cell:3,3', True))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].position == Position(x=3,y=3)
    assert e.state.actors[OWNER].movement_remaining_ft == before['actors'][OWNER]['movement_remaining_ft']


def test_granted_menu_does_not_reveal_hidden_blocker_but_contact_persists(monkeypatch, tmp_path):
    service, ui, mid = fight(monkeypatch, tmp_path, INTENSIFY, foe_hp=60, blocker=True)
    def conceal_then_move(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != OWNER:
            return
        target = engine.state.actors[BLOCKER]
        if not any(c.condition_id == 'condition:typed.hidden' for c in target.conditions.values()):
            engine._apply_condition(target, 'condition:typed.hidden', 'test:hide', BLOCKER, expires_on='UNTIL_REMOVED')
        elif target.position != Position(x=3,y=5):
            origin = target.position
            target.position = Position(x=3,y=5)
            engine._append_event('MOVEMENT_COMMITTED', 'test:hidden_move', actor_id=BLOCKER,
                payload={'destination': target.position.model_dump(mode='json'),
                         'path': [origin.model_dump(mode='json'), target.position.model_dump(mode='json')], 'cost_ft': 0})
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), conceal_then_move])
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    from tests.r10_fixup_support import table_probe_copy
    with table_probe_copy(service, tmp_path) as (probe_service, probe_ui, _):
        empty = options(cast_sender(probe_service, probe_ui, mid, NAME, at=(6,4))())
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    send = cast_sender(service, ui, mid, NAME, at=(6,4))
    blocked = options(send())
    assert blocked == empty and 'cell:3,5' in blocked
    before = service._load_session(mid).engine.state.actors[OWNER]
    origin, movement = before.position, before.movement_remaining_ft
    commit(send, lambda prompt: ('cell:3,5', True))
    e = reload_checked(tmp_path, mid); actor = e.state.actors[OWNER]
    assert actor.position == origin and actor.movement_remaining_ft == movement
    assert e.state.observations[actor.team_id][BLOCKER] == Position(x=3,y=5)
    assert any(ev.event_type == 'TARGETS_OBSERVED' and ev.payload.get('contacted_cells') for ev in e.events)
    assert not any(c.destination == Position(x=3,y=5) for c in e._movement_candidates(actor))
