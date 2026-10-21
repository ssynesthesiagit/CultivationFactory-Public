"""Public synthetic regressions for the F14R lead-queue findings."""
from types import SimpleNamespace

import pytest

from combat.ext import furnace_runtime as runtime
from tests.test_second_furnace_native import (
    game, fight, turn, play, engine, choose_seed, verify, OWNER, f,
)


def _admit(cold, jid, declare, kind, value, scope):
    declare(kind, value, scope)
    state = cold().journey_state(jid)
    return cold().journey_act(jid, state['revision'], OWNER,
        'furnace_environment' if kind == 'furnace_environment' else 'furnace_cost_profile',
        {'scope': scope})


@pytest.mark.parametrize('object_source', [False, True])
def test_overdraw_commits_and_replays_an_internal_save_without_a_creature_owner(tmp_path, monkeypatch, object_source):
    objects = ([{'kind': 'statue', 'x': 5, 'y': 6, 'name': 'Heart seal',
                 'material': 'stone', 'size': 'small', 'ac': 12, 'hp': 200, 'blocks': False}]
               if object_source else [])
    cold, jid, declare, state = game(tmp_path, monkeypatch, cl=3,
        seed='f15-internal-save-' + str(object_source), objects=objects)
    profile = {'source_rule': 'A heart seal tests a Qi activation.',
        'source_cl': 3, 'subject': OWNER, 'activation_save': 1,
        'save_ability': 'WIS', 'save_dc': 50, 'on_fail_condition': 'frightened'}
    if object_source:
        from combat.ext.objects import object_id
        profile['source_object_id'] = object_id(state['battlefield']['map_objects'][0])
    _admit(cold, jid, declare, 'furnace_environment', profile, 'internal-save')
    mid = fight(cold, jid)
    turn(cold, tmp_path, mid, OWNER)
    play(cold, tmp_path, mid, 'Force Mantle', select=choose_seed)
    saved = engine(cold, mid)
    actor = saved.state.actors[OWNER]
    assert actor.resources[f.CORRUPTION] == 1
    assert actor.resources[f.DEVIL] == 2
    assert any(e.event_type == 'SAVE_ROLLED' and e.source_definition_id == profile['source_rule']
               for e in saved.events)
    held = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.frightened')
    assert held.source_actor_id == ''  # Never invent the current actor as an object's caster.
    assert held.source_definition_id == profile['source_rule']
    verify(cold, mid)


@pytest.mark.parametrize('object_id', ['', 'object:seal'])
def test_internal_save_producer_normalizes_missing_creature_attribution(object_id):
    """The public save boundary gets text, retaining object identity in the spec."""
    held = SimpleNamespace(condition_id=runtime.INTERFERENCE, instance_id='seal',
        source_definition_id='rule:heart-seal', data={
            'activation_save': 1, 'save_ability': 'WIS', 'save_dc': 50, 'source_cl': 3,
            'source_object_id': object_id})
    actor = SimpleNamespace(conditions={'seal': held}, turn_flags={})
    calls = []
    ctx = SimpleNamespace(actor=actor, action=SimpleNamespace(source_definition_id='qi:activation'),
        engine=SimpleNamespace(state=SimpleNamespace(objects={object_id: object()}, actors={}),
            _roll_save=lambda *args, **kwargs: calls.append(kwargs['roll_context'])))
    # Only acquisition/classification is stubbed; the actual producer builds the save context.
    from unittest.mock import patch
    with patch.object(runtime, 'acquired', return_value=True), patch.object(runtime, 'source_profile', return_value={'ordinary_qi': True}):
        runtime.admitted_internal_response(ctx)
    assert calls[0]['source_actor_id'] == ''
    assert calls[0]['spec']['source_object_id'] == object_id


def _resources(cold, jid, **values):
    service = cold()
    session = service.journeys.load(jid)
    actor = session.state['actors'][OWNER]
    actor['resources'].update({getattr(runtime, key): value for key, value in values.items()})
    service.journeys.save(session)


def _payments(cold, jid):
    menu = cold().journey_menu(jid, OWNER)
    return menu, {r['payload']['payment']: r for r in menu['options'] if r['kind'] == 'furnace_engine'}


def test_journey_seed_core_split_uses_shared_settlement_and_survives_reload(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='f15-mixed-payment')
    _resources(cold, jid, QI=1, DEVIL=3, CORRUPTION=0)
    menu, payments = _payments(cold, jid)
    assert set(payments) == {'seed:core:3'}
    option = payments['seed:core:3']
    cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    state = cold().journey_state(jid)
    actor = state['actors'][OWNER]
    assert actor['resources'][f.QI] == 0
    assert actor['resources'][f.DEVIL] == 2
    assert actor['resources'][f.CORRUPTION] == 1
    assert actor['source_states'][f.PARENT]['engine']['corruption_gained'] == 1
    assert actor['source_states'][f.PARENT]['core_motion_pending'] == 1
    assert actor['source_states'][f.PARENT]['seed_reinforcement_pending'] == 1
    receipt = next(e for e in state['events'] if e['kind'] == 'ALTERNATIVE_PAYMENT_COMMITTED')
    assert receipt['covered'][f.QI] == 7
    assert receipt['resources_paid'] == {f.QI: 1, f.DEVIL: 3}
    # Both earned benefits remain reachable; settling one does not drop the other.
    for kind in ('furnace_core_motion', 'furnace_seed_reinforcement'):
        menu = cold().journey_menu(jid, OWNER)
        option = next(r for r in menu['options'] if r['kind'] == kind and r['payload'] == {'benefit': 'temp_hp'})
        cold().journey_act(jid, menu['revision'], OWNER, kind, option['payload'])
    assert cold().journey_state(jid)['actors'][OWNER]['encounter_snapshot']['temporary_hp'] == 8
    assert not _payments(cold, jid)[1]  # Once per scene, even after a cold reload.


@pytest.mark.parametrize('classification,expected', [
    ({'cannot_further_reduce': 1}, {'ordinary', 'core:1', 'core:2'}),
    ({'secret_law': 1}, {'ordinary', 'seed'}),
    ({'another_creature': 1}, {'ordinary'}),
])
def test_journey_payments_obey_shared_source_eligibility(tmp_path, monkeypatch, classification, expected):
    cold, jid, declare, state = game(tmp_path, monkeypatch, cl=18, seed='f15-eligibility-' + str(classification))
    _resources(cold, jid, QI=8, DEVIL=2, CORRUPTION=0)
    action = next(a for a in state['actors'][OWNER]['bundle']['action_catalog']
                  if a.get('parameters', {}).get('typed', {}).get('source') == runtime.ENGINE)
    _admit(cold, jid, declare, 'cost_profile', {
        'source_rule': action['source_definition_id'],
        'quotation': 'This native test source imposes the declared payment restriction.',
        'classification': classification}, 'cost-restriction')
    menu, payments = _payments(cold, jid)
    assert set(payments) == expected
    if 'seed' not in expected:
        before = cold().journey_state(jid)
        with pytest.raises(ValueError, match='unavailable'):
            cold().journey_act(jid, menu['revision'], OWNER, 'furnace_engine', {'payment': 'seed'})
        assert cold().journey_state(jid) == before


def test_seed_cultivation_advantage_reaches_the_native_contest_and_is_consumed(tmp_path, monkeypatch):
    """Use real saved reinforcement, then the native contest resolver (no scripted dice)."""
    from combat.typed_executor import resolve_opposed_check
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=3, seed='f15-cultivation-check')
    mid = fight(cold, jid)
    turn(cold, tmp_path, mid, OWNER)
    play(cold, tmp_path, mid, 'Force Mantle', select=lambda p:
        'Advantage' if 'seed_reinforcement' in p['context']['checkpoint'] else choose_seed(p))
    saved = engine(cold, mid)
    actor = saved.state.actors[OWNER]
    assert runtime.condition(actor, 'condition:typed.second_furnace_advantage')
    ctx = runtime.context(saved, actor)
    result = resolve_opposed_check(ctx, actor, {'kind': 'cultivation'}, {'kind': 'dc', 'dc': 10})
    assert len(result.actor.dice) == 2
    assert not runtime.condition(actor, 'condition:typed.second_furnace_advantage')


def test_armament_route_seam_is_documented():
    from pathlib import Path
    contract = (Path(__file__).resolve().parents[1] / 'combat/ext/__init__.py').read_text()
    assert 'armament_route_allowed(engine, owner, start, end, source) -> bool | None' in contract
    assert 'None preserves ordinary route rules' in contract
