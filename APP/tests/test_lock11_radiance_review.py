"""Searing Halo observes native turn-boundary repeat-save provenance."""
import pytest
from tests.test_lock9_radiance_review import table, checked, add_hook, OWNER, FOE, P
from tests.r10_fixup_support import cast_sender, commit
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn


@pytest.mark.parametrize('when', ['start', 'end'])
@pytest.mark.parametrize('kind,penalty,expected', [
    ('Undead', False, 'ADVANTAGE'), (None, False, 'NORMAL'),
    ('Undead', True, 'NORMAL'), (None, True, 'DISADVANTAGE')])
def test_native_repeat_fear_save_retains_source_and_uncancelled_modes(monkeypatch, tmp_path, when, kind, penalty, expected):
    service, ui, mid = table(tmp_path, [P + 'searing_halo'], kind=kind)
    commit(cast_sender(service, ui, mid, 'Searing Halo'))
    seen = []
    def observe(engine, target, ability, dc, source, context):
        if source == 'test:original_fear':
            seen.append(context)
    add_hook(monkeypatch, 'save_mode', observe)
    def fear(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            a = engine.state.actors[OWNER]
            engine._apply_condition(a, 'condition:typed.frightened', 'test:original_fear', FOE,
                expires_on='UNTIL_REMOVED', data={'repeat_save': {'ability': 'WIS', 'dc': 100, 'when': when}})
            if penalty:
                engine._apply_condition(a, 'condition:typed.review_save_penalty', 'test:penalty', FOE,
                    expires_on='UNTIL_REMOVED', data={'rule': {'save_mode': {'WIS': 'DISADVANTAGE'}}})
    add_hook(monkeypatch, 'event', fear)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert act(ui, mid, 'end')['status'] == 'COMMITTED'
    if when == 'start':
        turn(ui, mid, OWNER)
    e = checked(tmp_path, mid)
    saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.source_definition_id == 'test:original_fear']
    assert saves and all(ev.payload['mode'] == expected for ev in saves)
    assert seen and all(c['source_actor_id'] == FOE and c['named'] == ['frightened'] for c in seen)
    assert all(c['save_modes'] == (['DISADVANTAGE'] if penalty else []) for c in seen)
