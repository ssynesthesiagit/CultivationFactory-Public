"""Native acquired-character AI option-depth and knowledge regression.

The observer uses the public hook and returns no spec. Outside the fixture its
ContextVar is None, so it is inert; it never replaces engine functions/state.
"""
from contextvars import ContextVar

import pytest

from combat.ext import hook
from tests.test_a2_foundations_two import use
from tests.test_a2_foundations3 import add_action
from tests.test_mgr_t14_heavenly_rejection import fixed, RID
from tests.test_mgr_t14_heavenly_source import acquired_fight, ordered_rolls, OWNER, POOL
from tests.worker2_support import FOE, turn, reload

_CAPTURE = ContextVar('heavenly_ai_choice_observation', default=None)


@hook('choice_options', priority=-10)
def observe_rejection_choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    capture = _CAPTURE.get()
    if capture is not None and reactor_id == OWNER and choice_id in {RID, RID + '_timing'}:
        capture.append({'choice_id': choice_id, 'options': tuple(context.get('needle_options') or ()),
                        'automatic': context.get('automatic')})
    return None


@pytest.fixture
def observed(monkeypatch):
    ordered_rolls(monkeypatch)
    records = []
    token = _CAPTURE.set(records)
    try:
        yield records
    finally:
        _CAPTURE.reset(token)


@pytest.mark.parametrize('case,stage,expression,natural,dc,automatic,options', [
    ('success', 'Perfected', 'jade_gold_guard', 20, 14, False, {'use', 'base'}),
    ('hidden_failure', 'Perfected', 'jade_gold_guard', 20, 30, False, {'use', 'base'}),
    ('unrescuable', 'Perfected', 'jade_gold_guard', 8, 30, True, {'use', 'base'}),
    ('marrow', 'Refined', 'heaven_rejecting_marrow', 8, 14, True, {'wait', 'use'}),
])
def test_native_automatic_rejection_preserves_legal_menu_and_own_information(
        tmp_path, monkeypatch, observed, case, stage, expression, natural, dc, automatic, options):
    fixed(monkeypatch, natural)
    def delivery(bundles):
        add_action(bundles[2], 'Constitution ordeal', [{'type': 'save', 'ability': 'CON',
            'applies_to': 'target', 'on_fail': [{'type': 'condition', 'condition': 'poisoned',
                'expires_on': 'END_OF_HOLDER_NEXT_TURN', 'applies_to': 'target'}],
            'on_success': []}], economy='NONE', dc=dc)
    combat, table, mid = acquired_fight(tmp_path, stage=stage, expression=expression, delivery=delivery)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER, choices={
        'choice:needle.foundation_combat': None})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Constitution ordeal', OWNER, choices={})
    assert not prompts
    engine = reload(tmp_path, mid)
    choice_id = RID + '_timing' if case == 'marrow' else RID
    windows = [row for row in observed if row['choice_id'] == choice_id]
    assert windows, 'The automatic seat must receive its legal Rejection window.'
    assert all(set(row['options']) == options for row in windows)
    assert all(row['automatic'] is automatic for row in windows)
    assert engine.state.actors[OWNER].reaction_available
    if case in {'success', 'hidden_failure'}:
        # Identical own high roll => identical default, despite a different
        # undeclared opposing DC. All options remain available to model seats.
        assert engine.state.actors[OWNER].resources[POOL] == 1
