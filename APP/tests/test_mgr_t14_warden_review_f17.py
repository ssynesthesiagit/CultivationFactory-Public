"""Sol review F17 regressions for the Orbiting Shield Warden lane.

F17-1: a Shield already fallen is not dropped to the ground a second time from a stale copy.
F17-2: Bound Mode without an actual bound Shield raises a clear ValueError, not StopIteration.
F17-3: a Shield Prison whose condition was refused places no anchor and does not crash.
"""
from types import SimpleNamespace

from combat.ext import orbiting_shield_warden as w
from combat.ext import passive_rows
from combat.gate2_runtime_models import Position, RuntimeObjectState

OWNER = 'actor:f17.owner'


def _engine(objects=None, actors=None, rows=None):
    engine = SimpleNamespace(state=SimpleNamespace(objects=objects or {}, actors=actors or {}),
                             typed_passive_rows=rows or {}, grid=None)
    engine._update_object = lambda obj, source, owner: engine.state.objects.__setitem__(obj.object_id, obj)
    return engine


def _shield(**tag):
    return RuntimeObjectState(object_id='object:f17.shield', object_kind='QI_CONSTRUCT', owner_id=OWNER,
                              position=Position(x=1, y=1, z=0), unattended=True,
                              component={w.TAG: {'owner': OWNER, 'projected': 0, 'location': 'floating',
                                                 'protected': '', **tag}})


def test_f17_fallen_bound_shield_is_not_dropped_twice_from_stale_copy(monkeypatch):
    owner = SimpleNamespace(entity_id=OWNER, conditions={})
    shield = _shield()
    engine = _engine(objects={shield.object_id: shield}, actors={OWNER: owner})
    monkeypatch.setattr(w, 'bound_shield', lambda actor: {'inventory_owner': OWNER} if actor is owner else None)
    drops = []
    monkeypatch.setattr(w, 'drop_bound', lambda e, o, bond, point, source: drops.append(point))
    w.destroy(engine, shield, 'test')
    w.destroy(engine, shield, 'test')  # the caller still holds the pre-destroy copy
    assert len(drops) == 1
    assert engine.state.objects[shield.object_id].component[w.TAG]['location'] == 'fallen'


def test_f17_bound_mode_without_actual_shield_raises_clear_error():
    owner = SimpleNamespace(entity_id=OWNER, conditions={}, turn_flags={}, turns_started=0)
    engine = _engine(actors={OWNER: owner}, rows={OWNER: [{'block': w.TAG, 'feature_id': w.RAISE}]})
    ctx = SimpleNamespace(engine=engine, actor=owner, typed={'source': w.RAISE}, source='test')
    try:
        w.command(ctx, {'command': 'bound_mode'})
    except ValueError as exc:
        assert 'bound Shield' in str(exc)
    else:
        raise AssertionError('bound_mode without a bound Shield must refuse with ValueError')


def test_f17_refused_prison_places_no_anchor(monkeypatch):
    owner = SimpleNamespace(entity_id=OWNER, conditions={})
    target = SimpleNamespace(entity_id='actor:f17.target', conditions={}, position=Position(x=3, y=3, z=0))
    engine = _engine(actors={OWNER: owner}, rows={OWNER: [{'block': w.TAG, 'feature_id': w.NINE}]})
    engine._apply_condition = lambda *a, **k: None  # the prison is refused
    monkeypatch.setattr(passive_rows, 'known_level', lambda e, t: None)
    ctx = SimpleNamespace(engine=engine, actor=owner, target=target, source='test',
                          numbers={'cl': 18, 'save_dc': 15, 'pb': 4}, origin_save={'ability': 'WIS'})
    assert w.prison_result(ctx, {'success': False}) is None
    assert not target.conditions
