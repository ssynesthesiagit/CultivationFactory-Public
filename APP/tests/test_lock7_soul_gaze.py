"""Neutral targeting and explicit spiritual concealment at the saved table boundary."""
import pytest

from combat import ext
from combat.recipients import allowed
from tests.hunt15_support import ALLY, LEFT, RIGHT, act, action_sender, fight, reload, turn
from tests.test_lock_choices import install
from tests.test_lock5_recipients import pair_engine

SOUL_GAZE = 'tianxia.path.spirit_awakening.feature.soul_gaze'


def test_compile_action_composes_two_subscribers_without_mutating_inputs(monkeypatch):
    from combat.factory_compiler import compile_character
    from combat.ext.spirit_awakening import soul_gaze_target_kind
    from tests.h1_support import sheet
    originals = []
    observed = []
    def first(action, info):
        replacement = soul_gaze_target_kind(action, info)
        if replacement is not None:
            originals.append((action, action.model_dump(mode='json')))
        return replacement
    def second(action, info):
        if (action.parameters.get('typed') or {}).get('source') == SOUL_GAZE:
            observed.append(action.target_kind)
            return action.model_copy(update={'costs': (('resource:core.resonance', 2),)})
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'compile_action', [first, second])
    compiled = compile_character(sheet([SOUL_GAZE], primary='Resonance'), actor_id=LEFT)
    gaze = next(a for a in compiled['action_catalog'] if a['display_name'] == 'Soul Gaze')
    assert observed == ['ANY_CREATURE'] and gaze['target_kind'] == 'ANY_CREATURE'
    assert list(gaze['costs'][0]) == ['resource:core.resonance', 2]
    assert originals and all(a.model_dump(mode='json') == before for a, before in originals)
    assert originals[0][0].target_kind == 'ALLY_OR_SELF'


def test_compile_transform_none_and_empty_are_identity(monkeypatch):
    ext.effects()
    action = object()
    for subscribers in ([], [lambda value: None, lambda value: None]):
        monkeypatch.setitem(ext._HOOKS, 'compile_action', subscribers)
        assert ext.transform('compile_action', action) is action


@pytest.mark.parametrize('ai', [False, True])
def test_charm_does_not_classify_a_diagnosis_as_an_attack(monkeypatch, tmp_path, ai):
    def charm(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == LEFT:
            engine._apply_condition(engine.state.actors[LEFT], 'condition:typed.charmed', 'test:charm', RIGHT,
                                    expires_on='UNTIL_REMOVED')
    install(monkeypatch, 'event', charm)
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary='Resonance')
    turn(table, mid, LEFT)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[LEFT].resources['resource:core.resonance']
    assert action_sender(combat, table, mid, 'Soul Gaze', ai=ai, target_id=RIGHT)([])['status'] == 'COMMITTED'
    assert reload(combat, mid).state.actors[LEFT].resources['resource:core.resonance'] == before - 1
    assert any('Soul Gaze on Visiting Fighter:' in row['summary'] for row in table.events(mid, 0)['events'])


@pytest.mark.parametrize('ai', [False, True])
def test_explicit_source_concealment_blocks_the_unseen_mark_exception(monkeypatch, tmp_path, ai):
    def conceal(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == LEFT:
            engine._apply_condition(engine.state.actors[ALLY], 'condition:test.spiritual_barrier',
                'test:printed-spiritual-barrier', ALLY, expires_on='UNTIL_REMOVED',
                data={'total_spiritual_concealment': 1, 'label': 'Spirit concealed by a barrier'})
    install(monkeypatch, 'event', conceal)
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary='Resonance', ally=[], target='ALLY_OR_SELF',
        effects=[{'type': 'condition', 'condition': 'invisible', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'},
                 {'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    turn(table, mid, LEFT)
    assert action_sender(combat, table, mid, 'Test setup', ai=ai, target_id=ALLY)([])['status'] == 'COMMITTED'
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    def offers_ally():
        return any(ALLY in o['target_ids'] for g in table.state(mid)['menu']['actions']
                   if g['label'] == 'Soul Gaze' for o in g['options'])
    assert offers_ally()  # ordinary Invisible is not total spiritual concealment
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    barrier = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == 'condition:test.spiritual_barrier')
    assert type(barrier.data['total_spiritual_concealment']) is int
    assert not offers_ally()


def test_target_eligibility_is_strict_and_cannot_override_another_veto(monkeypatch):
    engine, actor, action = pair_engine()
    target = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    install(monkeypatch, 'target_eligibility', lambda *a: {'allow': True})
    with pytest.raises(ValueError, match='target_eligibility'):
        allowed(engine, actor, target, action)
    monkeypatch.setitem(ext._HOOKS, 'target_eligibility', [lambda *a: True, lambda *a: False])
    assert not allowed(engine, actor, target, action)


def test_table_revalidates_eligibility_before_spending(monkeypatch, tmp_path):
    def hide(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == LEFT:
            engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible',
                'test:conceal-target', RIGHT, expires_on='UNTIL_REMOVED')
    install(monkeypatch, 'event', hide)
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary='Resonance')
    turn(table, mid, LEFT)
    state = table.state(mid)
    candidate = next(o for g in state['menu']['actions'] if g['label'] == 'Soul Gaze'
                     for o in g['options'] if RIGHT in o['target_ids'])
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    fresh = table.state(mid)
    assert not any(RIGHT in o['target_ids'] for g in fresh['menu']['actions']
                   if g['label'] == 'Soul Gaze' for o in g['options'])
    before = reload(combat, mid).state.model_dump(mode='json')
    from combat.tabletop import TabletopError
    with pytest.raises(TabletopError, match='no longer legal'):
        table.act(mid, candidate['candidate_id'], fresh['menu']['decision_id'], fresh['menu']['state_version'], fresh['last_sequence'])
    assert reload(combat, mid).state.model_dump(mode='json') == before
