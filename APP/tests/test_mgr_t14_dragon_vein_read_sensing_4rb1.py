"""Regression tests for Read the Dragon Vein (CL3) sensing, Sol review 4RB1 blocking finding.

The printed feature senses terrain and structure within 60 feet while the creature touches a stable surface.
Each test drives the plug-in's own functions with in-memory state; no live server or external process is used.
"""
from types import SimpleNamespace

from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_runtime_models import Position, RuntimeObjectState


class Grid:
    def __init__(self):
        self.material_regions = {}
        self.qi_hazard = set()

    def distance_ft(self, a, b):
        return 5 * max(abs(a.x - b.x), abs(a.y - b.y))

    def in_bounds(self, cell):
        return True


class Engine:
    def __init__(self):
        self.grid = Grid()
        self.state = SimpleNamespace(objects={}, zones={}, actors={}, round_number=1, event_sequence=0,
                                     current_actor_id=None)
        self.events = []

    def _update_object(self, obj, source, owner=None):
        self.state.objects[obj.object_id] = obj

    def _append_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def creature(eid, x=0, y=0):
    return SimpleNamespace(entity_id=eid, actor_id=eid, owner_id=eid, team_id='team:a',
                           position=Position(x=x, y=y, z=0), turn_flags={}, resources={}, conditions={},
                           display_name=eid, active=True)


def structure(oid, x, y, hp=20, max_hp=20):
    return RuntimeObjectState(object_id=oid, object_kind='wall', position=Position(x=x, y=y, z=0),
                              unattended=True, flammable=False, current_hp=hp, maximum_hp=max_hp,
                              destroyed=False, component={'name': 'Pillar', 'structure': True})


def logs(engine):
    return [kwargs['payload']['log'] for _, kwargs in engine.events if 'log' in kwargs.get('payload', {})]


def setup(monkeypatch, stores=None):
    stores = {} if stores is None else stores
    monkeypatch.setattr(dv, 'state', lambda a: stores.get(a.entity_id, {}))
    monkeypatch.setattr(dv, 'store', lambda e, a, d: stores.__setitem__(a.entity_id, dict(d)))
    monkeypatch.setattr(dv, 'stable', lambda e, p: True)
    from combat.ext import placed
    monkeypatch.setattr(placed, 'of', lambda engine, tag=None, owner_id=None: [])
    return stores


def run(engine, actor, command='sense'):
    ctx = SimpleNamespace(engine=engine, actor=actor, source=dv.READ, targets=[], intent=None)
    dv.command(ctx, {'type': 'dragon_vein_command', 'command': command})


def test_read_the_dragon_vein_reports_features_within_60_feet_by_direction(monkeypatch):
    setup(monkeypatch)
    engine = Engine()
    hero = creature('hero', 10, 10)
    engine.state.actors['hero'] = hero
    engine.grid.material_regions[(10, 6)] = [{'material': 'cave', 'terrain_type': 'OPEN', 'sealed': False, 'bottom': 0, 'top': None}]
    engine.grid.material_regions[(4, 10)] = [{'material': 'water', 'terrain_type': 'OPEN', 'sealed': False, 'bottom': 0, 'top': None}]
    engine.grid.qi_hazard.add((12, 12))
    engine.state.objects['pillar'] = structure('pillar', 8, 10, hp=5)
    engine.state.objects['far'] = structure('far', 10, 30)  # 100 feet south: outside 60 feet
    run(engine, hero)
    texts = logs(engine)
    assert any('Hollow or tunnel to the N' in t for t in texts)
    assert any('Underground water to the W' in t for t in texts)
    assert any('Significant unusual spiritual pressure to the SE' in t for t in texts)
    assert any('Major structural weakness to the W' in t for t in texts)
    assert not any('to the S.' in t for t in texts)


def test_read_the_dragon_vein_requires_touching_stable_ground(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(dv, 'stable', lambda e, p: False)
    engine = Engine()
    hero = creature('hero')
    engine.state.actors['hero'] = hero
    try:
        run(engine, hero)
    except ValueError as exc:
        assert 'stable surface' in str(exc)
    else:
        raise AssertionError('sensing must need stable ground')


def test_read_the_dragon_vein_with_nothing_nearby_says_so(monkeypatch):
    setup(monkeypatch)
    engine = Engine()
    hero = creature('hero')
    engine.state.actors['hero'] = hero
    run(engine, hero)
    assert logs(engine) == ['Read the Dragon Vein: nothing unusual within 60 feet.']


def test_read_the_dragon_vein_is_a_published_action_with_its_sensing_label(monkeypatch):
    from combat import subpath_acquisition
    from pathlib import Path
    monkeypatch.setattr(subpath_acquisition, 'acquired_features',
                        lambda sheet, root, include_unavailable=True: {dv.READ: {'cl': 3}})
    info = {'owner_sheet': {}, 'owned_ids': [dv.READ], 'numbers': {'pb': 2, 'cl': 3, 'qi': 3},
            'actor_id': 'hero', 'short': 'hero'}
    actions = dv.compile_actions(info)
    labels = [a.display_name for a in actions]
    assert any(label.startswith('Read the Dragon Vein - sense') for label in labels)
    sense = next(a for a in actions if a.parameters['geomancy'] == 'sense')
    assert sense.parameters['typed']['effects'][0]['command'] == 'sense'
