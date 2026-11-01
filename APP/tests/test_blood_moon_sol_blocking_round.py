"""Regression tests for the Sol F4R blocking findings (each fails without its fix).

No model, network, or live server. Pure hook and helper checks with fake engines.
"""
from types import SimpleNamespace as NS

import pytest

from combat.ext import mgr_reserve_blood_moon_execution_saber_cultivator_write_the_first_sentence as blood
from combat.ext import ability_source
from combat import activation_settlement


def _cond(condition_id, **data):
    return NS(condition_id=condition_id, data=data)


def _actor(entity_id, conditions=(), hp=10):
    return NS(entity_id=entity_id, display_name=entity_id, current_hp=hp, resources={},
              conditions={i: c for i, c in enumerate(conditions)})


@pytest.fixture
def owned_all(monkeypatch):
    monkeypatch.setattr(blood, 'owned', lambda engine, actor, tier=3: True)
    monkeypatch.setattr(activation_settlement, 'path_numbers', lambda info, path: {'cl': 18})


def test_bound_saber_attacks_offered_without_a_carried_saber(owned_all):
    # Blocking 1: a Blood-Moon owner with no carried saber still gets the printed 30 ft and 60 ft bound-saber attacks.
    info = {'owned_ids': [blood.ROWS[k] for k in (3, 10, 18)], 'short': 'owner', 'actor_id': 'owner',
            'numbers': {'attack_bonus': 4, 'cl': 18, 'save_dc': 14}, 'actions': []}
    actions = blood.actions(info)
    ten = [a for a in actions if '.bound_saber_10' in a.source_definition_id]
    eighteen = [a for a in actions if '.bound_saber_18' in a.source_definition_id]
    assert ten and ten[0].range_ft == 30 and ten[0].costs == ((blood.QI, 5),)
    assert eighteen and eighteen[0].range_ft == 60 and eighteen[0].costs == ((blood.QI, 8),)
    # The delivered execution rider is attached to each bound attack.
    for a in (*ten, *eighteen):
        on_hit = a.parameters['typed']['effects'][0]['on_hit']
        assert any(e.get('type') == 'blood_moon_execution' for e in on_hit)


def test_hit_points_and_cultivation_points_readings_are_checked(monkeypatch):
    # Blocking 3: HP and CP readings are concealed from a lower-CL reader unless the source check succeeds.
    calls = []
    monkeypatch.setattr(ability_source, 'cultivation_check', lambda *a, **k: calls.append(a) or False)
    published = []
    monkeypatch.setattr(blood, 'publish', lambda ctx, details: published.append(details))
    target = _actor('foe', hp=7)
    engine = NS(typed_bundle_documents=({'actor_id': 'foe', 'cl': 12},), state=NS(actors={'foe': target}))
    ctx = NS(engine=engine, actor=_actor('owner'), target=target, numbers={'cl': 6, 'save_dc': 14}, source='src')
    answer = blood.authority_reading(ctx)
    assert blood.know(ctx, 'current_hit_points', answer) is False
    assert calls, 'the authority check must run for a higher-CL target'
    assert published[-1]['answer'] == 'The answer is concealed.'


def test_severed_system_passive_rows_are_hidden_and_restored(monkeypatch):
    # Blocking 2: passive benefits of a severed Sphere stop feeding consumers, and return when the severance ends.
    sphere_row = {'block': 'sphere_x', 'kind': 'bonus', 'source': 'src:x'}
    other_row = {'block': 'other', 'kind': 'bonus'}
    actor = _actor('owner')
    engine = NS(typed_bundle_documents=({'actor_id': 'owner', 'typed_passives': [sphere_row, other_row]},),
                typed_passive_rows={'owner': [dict(sphere_row), dict(other_row)]},
                state=NS(actors={'owner': actor}))
    blood.sever_passive_rows(engine, 'EVENT', {})
    assert engine.typed_passive_rows['owner'] == [sphere_row, other_row]
    actor.conditions[0] = _cond(blood.STATE, kind='system', source_ids=['sphere_x'])
    blood.sever_passive_rows(engine, 'EVENT', {})
    assert engine.typed_passive_rows['owner'] == [other_row]
    actor.conditions.clear()
    blood.sever_passive_rows(engine, 'EVENT', {})
    rows = engine.typed_passive_rows['owner']
    assert len(rows) == 2 and sphere_row in rows and other_row in rows


def test_severed_source_refuses_its_non_action_and_action_candidates():
    # Blocking 2: a severed Sphere refuses actions it delivers, not only the action it first named.
    actor = _actor('owner', [_cond(blood.STATE, kind='system', source_ids=['sphere_x'])])
    action = NS(source_definition_id='action:other', parameters={'typed': {'sphere': 'sphere_x'}})
    assert blood.suppressed(NS(), actor, None, action) is False
    clean = NS(source_definition_id='action:other', parameters={'typed': {'sphere': 'sphere_y'}})
    assert blood.suppressed(NS(), actor, None, clean) is None


def test_vessel_transfer_picks_nearest_surviving_vessel(monkeypatch):
    # Blocking 2: Sever Soul from Vessel hands control to the nearest living vessel, not a dead or distant one.
    target = _actor('target')
    near, far, dead = _actor('near'), _actor('far'), _actor('dead', hp=0)
    engine = NS(state=NS(actors={a.entity_id: a for a in (target, near, far, dead)}))
    distances = {'near': 10, 'far': 40, 'dead': 1}
    dist = lambda eng, a, b: distances[b.entity_id]
    assert blood.vessel_heir(engine, target, dist).entity_id == 'near'
