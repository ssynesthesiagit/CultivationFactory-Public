"""Regression tests for the Sol review findings on the Dragon-Vein Geomancer branch.

Each test drives one plug-in function with a minimal in-memory engine and
monkeypatches only the spatial/state helpers it does not own. No live server,
fight save, or external process is used.
"""
from types import SimpleNamespace

import pytest

from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.motion import TerrainExemption


class Grid:
    def distance_ft(self, a, b):
        return 5*max(abs(a.x-b.x), abs(a.y-b.y))

    def in_bounds(self, cell):
        return True


class Engine:
    def __init__(self):
        self.grid = Grid()
        self.state = SimpleNamespace(objects={}, zones={}, actors={}, round_number=1, event_sequence=0,
                                     current_actor_id=None)
        self.events = []

    def _update_object(self, obj, source, owner):
        self.state.objects[obj.object_id] = obj

    def _append_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def actor(eid, x=0, y=0, flags=None):
    return SimpleNamespace(entity_id=eid, actor_id=eid, owner_id=eid, position=Position(x=x, y=y, z=0),
                           turn_flags=flags if flags is not None else {}, resources={}, conditions={},
                           display_name=eid, active=True)


def anchor(oid, owner, x, y, *, block, destroyed=False):
    return RuntimeObjectState(object_id=oid, object_kind='vein_anchor', position=Position(x=x, y=y, z=0),
                              unattended=True, flammable=False, owner_id=owner, ac=14, current_hp=6, maximum_hp=6,
                              damage_immunities=('POISON','PSYCHIC'), destroyed=destroyed, suppressed=False,
                              component={'name':'Vein Anchor','size':'tiny','blocks':False,'created_by':dv.READ,
                                         BLOCK_KEY: block})


BLOCK_KEY = dv.BLOCK
SOURCE = SimpleNamespace(source_definition_id='src')


def kit_for(pb=1, cl=3, owned=(dv.READ, dv.CIRCUIT)):
    return {'owned': list(owned), 'numbers': {'pb': pb, 'cl': cl}}


def test_ordinary_anchor_cap_ignores_imperial_anchors(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    eng.state.actors['owner'] = owner
    eng.state.zones['zone:field'] = SimpleNamespace(zone_id='zone:field', active=True, owner_id='owner', trigger_profile={})
    field_block = {'mode':'earth','created_sequence':1,'end_round':99,'field_id':'zone:field','support':{}}
    eng.state.objects['imperial'] = anchor('imperial','owner',9,9,block=field_block)
    monkeypatch.setattr(dv,'kit',lambda e,a: kit_for(pb=1))
    monkeypatch.setattr(dv,'stable',lambda e,p: True)
    monkeypatch.setattr(dv,'choose',lambda *a,**k: ['earth'])
    ctx = SimpleNamespace(engine=eng, actor=owner, source=SOURCE, numbers={'pb':1,'cl':3},
                          intent=SimpleNamespace(destination=Position(x=1,y=0,z=0)))
    dv.command(ctx, {'command':'place'})
    assert eng.state.objects['imperial'].destroyed is False
    ordinary = [o for o in eng.state.objects.values() if not o.destroyed and o.object_id != 'imperial']
    assert len(ordinary) == 1


def test_imperial_center_without_stable_support_is_a_legal_candidate(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    eng.state.actors['owner'] = owner
    center = Position(x=13,y=13,z=0)
    support = {(x,y) for x in range(11,16) for y in range(11,16) if (x,y) != (13,13)}
    monkeypatch.setattr(dv,'kit',lambda e,a: kit_for(cl=18,owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv,'stable',lambda e,p: (p.x,p.y) in support)
    from combat.ext import grid_radius_cache
    monkeypatch.setattr(grid_radius_cache,'cells_in_radius',
        lambda grid,c,r: [Position(x=x,y=y,z=0) for x in range(c.x-r,c.x+r+1) for y in range(c.y-r,c.y+r+1)])
    action = SimpleNamespace(parameters={'geomancy':'imperial'})
    candidate = SimpleNamespace(destination=center)
    assert dv.candidates(eng, owner, candidate, action) is True


def test_imperial_anchors_end_with_their_field(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    eng.state.actors['owner'] = owner
    field_block = {'mode':'earth','created_sequence':1,'end_round':99,'field_id':'zone:field','support':{}}
    eng.state.objects['imperial'] = anchor('imperial','owner',9,9,block=field_block)
    eng.state.zones['zone:field'] = SimpleNamespace(zone_id='zone:field', active=False, owner_id='owner')
    monkeypatch.setattr(dv,'kit',lambda e,a: kit_for())
    assert dv.anchors(eng, owner) == []
    assert dv.anchors(eng, owner, active=False) == []


def test_increase_momentum_adds_five_feet_once(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    owner.conditions['c1'] = SimpleNamespace(condition_id='condition:typed.geomancy_momentum', instance_id='c1')
    ctx = SimpleNamespace(engine=eng, actor=owner, source=SOURCE)
    assert dv.momentum_bonus(ctx, owner, {}) == 5
    assert not dv.momentum_bonus(ctx, owner, {})
    assert 'c1' not in owner.conditions


def test_water_circuit_moves_each_creature_once_per_turn(monkeypatch):
    eng = Engine()
    subject = actor('ally',1,0)
    eng.state.actors.update({'ally':subject,'g1':actor('g1'),'g2':actor('g2')})
    stores = {'g1':{'allies':['ally']}, 'g2':{'allies':['ally']}}
    water = lambda eid: RuntimeObjectState(object_id='w'+eid, object_kind='vein_anchor',
        position=Position(x=0,y=0,z=0), unattended=True, flammable=False, owner_id=eid, ac=14,
        current_hp=6, maximum_hp=6, damage_immunities=(), destroyed=False, suppressed=False,
        component={BLOCK_KEY:{'mode':'water','created_sequence':1,'end_round':9,'support':{}}})
    eng.state.objects.update({'ww1':water('g1'),'ww2':water('g2')})
    monkeypatch.setattr(dv,'kit',lambda e,a: kit_for())
    monkeypatch.setattr(dv,'state',lambda a: stores.get(a.entity_id, {}))
    monkeypatch.setattr(dv,'store',lambda e,a,d: stores.__setitem__(a.entity_id,d))
    monkeypatch.setattr(dv,'gravity',lambda *a,**k: None)
    monkeypatch.setattr(dv,'context',lambda *a,**k: None)
    monkeypatch.setattr(dv,'covers',lambda e,o,obj,cell: cell.x == 1)
    monkeypatch.setattr(dv,'modes',lambda e,o,obj: ('water',))
    moved = []
    monkeypatch.setattr(dv,'move_ally',lambda ctx,target,feet,label,**k: moved.append((target.entity_id,label)))
    ev = {'actor_id':'ally','payload':{'path':[{'x':0,'y':0,'z':0}]}}
    dv.entered(eng,'MOVEMENT_COMMITTED',ev)
    assert moved == [('ally','Water Circuit')]
