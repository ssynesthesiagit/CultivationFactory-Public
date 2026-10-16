"""F4R line findings: native acquisition/commit/reload plus general seam guards."""
from types import SimpleNamespace

import pytest

from tests.test_mgr_spirit_bow_native import (
    O, F, X, QI, setup, bound_bow, fight, commit, option, native_option, cold,
)


@pytest.mark.parametrize('hp', [1, 10000])
def test_nonblocking_object_stops_only_when_it_survives_native(tmp_path, hp):
    objects = [
        {'name': 'Near unattended object', 'kind': 'custom', 'material': 'wood',
         'size': 'small', 'x': 7, 'y': 6, 'ac': 10, 'hp': hp,
         'blocks': False, 'unattended': True},
        {'name': 'Far unattended object', 'kind': 'custom', 'material': 'wood',
         'size': 'small', 'x': 9, 'y': 6, 'ac': 10, 'hp': 1,
         'blocks': False, 'unattended': True},
    ]
    c, t, j = setup(tmp_path, objects=objects,
                    positions={O: {'x': 3, 'y': 6}, F: {'x': 5, 'y': 6}, X: {'x': 12, 'y': 6}})
    mid = fight(c, t, j)
    before = cold(c, mid)
    commit(t, mid, option(t, mid, 'Piercing Shot: Force', at=(20, 6)))
    after = cold(c, mid)
    near = next(o for o in after.state.objects.values() if o.position.x == 7)
    far = next(o for o in after.state.objects.values() if o.position.x == 9)
    assert near.current_hp < hp
    assert near.destroyed == (hp == 1)
    assert far.destroyed == (hp == 1)
    assert after.state.actors[F].current_hp < before.state.actors[F].current_hp
    assert (after.state.actors[X].current_hp < before.state.actors[X].current_hp) == (hp == 1)
    assert after.state.actors[O].resources[QI] == 96


def test_remote_emitter_survives_but_colocated_object_is_hit_native(tmp_path):
    from combat.ext.hand_occupancy import weapon_grips

    other = {'name': 'Separate object at the origin', 'kind': 'custom', 'material': 'wood',
             'size': 'small', 'x': 9, 'y': 6, 'ac': 10, 'hp': 1,
             'blocks': False, 'unattended': True}
    c, t, j, real = bound_bow(tmp_path, objects=[other])
    mid = fight(c, t, j)
    commit(t, mid, option(t, mid, 'Manifest Bound Spirit Bow', at=(9, 6)))
    before = cold(c, mid)
    bow = next(o for o in before.state.objects.values() if (o.component or {}).get('real_bow') == real)
    neighbor = next(o for o in before.state.objects.values() if o.object_id != bow.object_id)
    assert bow.current_hp > 0 and bow.position == neighbor.position
    commit(t, mid, native_option(c, mid, 'Piercing Shot: Force', at=(20, 6), remote=True))
    after = cold(c, mid)
    assert after.state.objects[bow.object_id].current_hp == bow.current_hp
    assert not after.state.objects[bow.object_id].destroyed
    assert after.state.objects[neighbor.object_id].destroyed
    assert after.state.actors[F].current_hp < before.state.actors[F].current_hp
    assert after.state.actors[O].position == before.state.actors[O].position
    assert after.state.actors[O].resources[QI] == before.state.actors[O].resources[QI] - 5
    assert any(e.payload.get('effect_origin', {}).get('object_id') == bow.object_id for e in after.events)
    # A surviving physical bow must remain usable after cold reload.
    from tests.test_mgr_spirit_bow_native import next_turn
    next_turn(t, mid)
    commit(t, mid, option(t, mid, 'Call Bound Spirit Bow'))
    called = cold(c, mid)
    assert real in weapon_grips(called, called.state.actors[O])
    assert called.state.objects[bow.object_id].current_hp == bow.current_hp


def test_origin_object_identity_binds_and_revalidates_without_changing_ordinary_origins(monkeypatch):
    from combat import ext
    from combat.action_geometry import activate, origins, valid

    actor = SimpleNamespace(entity_id='actor:origin')
    action = SimpleNamespace(source_definition_id='source:origin')
    engine = SimpleNamespace(grid=SimpleNamespace(in_bounds=lambda p: True),
                             state=SimpleNamespace(objects={
                                 'object:a': SimpleNamespace(destroyed=False),
                                 'object:b': SimpleNamespace(destroyed=False)}))
    row = {'id': 'origin', 'label': 'Emitting item', 'position': {'x': 1, 'y': 2}}
    monkeypatch.setattr(ext, 'run_strict', lambda *args: [[dict(row)]])
    assert origins(engine, actor, action) == [row]
    row['object_id'] = 'object:a'
    bound = origins(engine, actor, action)[0]
    assert bound['object_id'] == 'object:a'
    with activate(engine, actor, action.source_definition_id, bound):
        assert valid(engine, actor, action)
        row['object_id'] = 'object:b'
        assert not valid(engine, actor, action)
    for invalid in ('', 1, 'object:missing'):
        row['object_id'] = invalid
        with pytest.raises(ValueError):
            origins(engine, actor, action)
    row['object_id'] = 'object:a'
    engine.state.objects['object:a'].destroyed = True
    with pytest.raises(ValueError, match='intact'):
        origins(engine, actor, action)


@pytest.mark.parametrize('policy', [None, False, True])
@pytest.mark.parametrize('destroyed', [False, True])
def test_ordered_line_survival_policy_is_opt_in(monkeypatch, policy, destroyed):
    """General effect contract: other sources keep their geometry-only policy."""
    from combat import typed_executor as te
    from combat.action_geometry import activate
    from combat.ext import objects, piercing_areas
    from combat.gate2_runtime_models import Position

    actor = SimpleNamespace(entity_id='actor:shooter', position=Position(x=1, y=1))
    near = SimpleNamespace(object_id='object:near', position=Position(x=2, y=1),
                           current_hp=100, ac=10, destroyed=False)
    far = SimpleNamespace(object_id='object:far', position=Position(x=3, y=1),
                          current_hp=100, ac=10, destroyed=False)
    engine = SimpleNamespace(state=SimpleNamespace(actors={}, objects={near.object_id: near, far.object_id: far}),
                             grid=SimpleNamespace(distance_ft=lambda p, q: abs(q.x - p.x) * 5))
    ctx = SimpleNamespace(engine=engine, actor=actor, source='source:line',
                          damage_cache={}, destination=Position(x=5, y=1), targets=[],
                          typed={'area': {'shape': 'line'}})
    save = {'on_fail': [{'type': 'damage', 'damage_types': ['FORCE']}], 'on_success': []}
    row = {'effects': [save]}
    if policy is not None:
        row['stop_on_surviving_object'] = policy
    monkeypatch.setattr(te, 'in_area', lambda *args: True)
    monkeypatch.setattr(te, '_damage_roll', lambda *args: (10, 'FORCE'))
    monkeypatch.setattr(objects, 'area_reaches', lambda *args: True)
    # Real target_cells reads the object's native occupied footprint.
    monkeypatch.setattr(__import__('combat.object_geometry', fromlist=['target_cells']),
                        'target_cells', lambda e, o: [o.position])
    hits = []
    def deal(e, a, obj, *args, **kwargs):
        hits.append(obj.object_id)
        return {'destroyed': destroyed}
    monkeypatch.setattr(objects, 'deal', deal)
    piercing_areas.piercing_area(ctx, row)
    assert hits == (['object:near'] if policy and not destroyed else ['object:near', 'object:far'])
    # Exact identity exclusion works independently of the survival policy.
    hits.clear()
    with activate(engine, actor, ctx.source, {'position': {'x': 2, 'y': 1}, 'object_id': near.object_id}):
        piercing_areas.piercing_area(ctx, row)
    assert hits == ['object:far']
