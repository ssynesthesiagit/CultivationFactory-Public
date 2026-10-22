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
    return SimpleNamespace(entity_id=eid, actor_id=eid, owner_id=eid, team_id='team:a',
                           position=Position(x=x, y=y, z=0),
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


# --- Sol review 4F2 finding 3: a legality gate fails closed --------------------------------
def test_candidate_gate_error_vetoes_the_choice(monkeypatch):
    from combat import ext
    ext._load()
    def broken(*args, **kwargs):
        raise RuntimeError('gate cannot decide')
    monkeypatch.setitem(ext._HOOKS, 'candidate_allowed', [broken])
    assert ext.any_false('candidate_allowed', Engine(), None, None, None) is True
    assert ext.run('candidate_allowed', Engine(), None, None, None) == [False]


def test_candidate_gate_without_an_action_is_inert():
    eng = Engine()
    owner = actor('owner')
    assert dv.candidates(eng, owner, SimpleNamespace(destination=None), None) is None


# --- CL14 Carry a Traveler ----------------------------------------------------------------
def test_passage_carries_a_willing_traveler(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    traveler = actor('ally', 1, 0)
    eng.state.actors.update({'owner': owner, 'ally': traveler})
    owner.resources = {dv.QI: 4}
    owner.turn_flags = {}
    second = anchor('a2', 'owner', 10, 0, block={'mode': 'earth', 'created_sequence': 2, 'end_round': 99, 'support': {}})
    first = anchor('a1', 'owner', 0, 0, block={'mode': 'earth', 'created_sequence': 1, 'end_round': 99, 'support': {}})
    destination = Position(x=10, y=1, z=0)
    landing = Position(x=11, y=1, z=0)
    monkeypatch.setattr(dv, 'passage_routes', lambda e, o: {'route': (first, second, destination)})
    monkeypatch.setattr(dv, 'province', lambda e, o: None)
    monkeypatch.setattr(dv, 'traveler_cells', lambda e, o, t, p: {'landing': landing})
    def pick(ctx, suffix, options, **kwargs):
        return {'passage': ['route'], 'passage_traveler': ['ally'],
                'passage_traveler_consent': ['ally'], 'passage_traveler_destination': ['landing']}[suffix]
    monkeypatch.setattr(dv, 'choose', pick)
    monkeypatch.setattr('combat.typed_executor.teleport_subject',
                        lambda ctx, subject, cell, **kw: setattr(subject, 'position', cell))
    spent = []
    eng._spend_resource = lambda actor_, resource, amount, source: (spent.append(amount),
                                                                   actor_.resources.__setitem__(resource, actor_.resources[resource] - amount))
    ctx = SimpleNamespace(engine=eng, actor=owner, source='source')
    dv.passage(ctx)
    assert owner.position == destination
    assert traveler.position == landing
    assert spent == [4]
    assert owner.resources[dv.QI] == 0
    assert owner.turn_flags['geomancy_passage'] is True


# --- CL18 Seal the Roads ------------------------------------------------------------------
def test_seal_the_roads_stops_a_hostile_teleport(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    foe = actor('foe', 5, 0)
    eng.state.actors.update({'owner': owner, 'foe': foe})
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'province', lambda e, o: SimpleNamespace(zone_id='field'))
    monkeypatch.setattr(dv, 'in_province', lambda e, o, p: True)
    monkeypatch.setattr(dv, 'context', lambda e, o, s, t=(): SimpleNamespace(numbers={'save_dc': 18}))
    monkeypatch.setattr('combat.relations.relation', lambda e, a, b: 'ENEMY')
    class Fail:
        total = 1
    eng._roll_save = lambda *a, **k: Fail()
    ctx = SimpleNamespace(engine=eng, actor=foe)
    assert dv.seal_roads(ctx, foe, Position(x=1, y=0, z=0), Position(x=2, y=0, z=0)) is False


def test_seal_the_roads_leaves_the_owners_own_forced_teleport_alone(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    foe = actor('foe', 5, 0)
    eng.state.actors.update({'owner': owner, 'foe': foe})
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'province', lambda e, o: SimpleNamespace(zone_id='field'))
    monkeypatch.setattr(dv, 'in_province', lambda e, o, p: True)
    monkeypatch.setattr('combat.relations.relation', lambda e, a, b: 'ENEMY')
    ctx = SimpleNamespace(engine=eng, actor=owner)
    assert dv.seal_roads(ctx, foe, Position(x=1, y=0, z=0), Position(x=2, y=0, z=0)) is None


# --- CL18 Imperial Geomantic Command ------------------------------------------------------
def test_imperial_command_dispatches_the_two_chosen_commands(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    calls = []
    monkeypatch.setattr(dv, 'choose', lambda ctx, suffix, options, **kw: ['harden', 'repair'])
    monkeypatch.setattr(dv, 'pick_ally', lambda ctx, suffix, **kw: owner)
    monkeypatch.setattr(dv, '_harden', lambda ctx, ally: calls.append(('harden', ally.entity_id)))
    monkeypatch.setattr(dv, 'repair', lambda ctx, dice: calls.append(('repair', dice)))
    dv.imperial_command(SimpleNamespace(engine=eng, actor=owner, source='source', numbers={}))
    assert calls == [('harden', 'owner'), ('repair', 3)]


def test_harden_the_mountain_adds_ac_and_advantage_on_the_next_forced_save(monkeypatch):
    eng = Engine()
    subject = actor('ally')
    subject.conditions['h1'] = SimpleNamespace(condition_id=dv.HARDEN, instance_id='h1')
    monkeypatch.setattr(dv, 'benefits', lambda e, a: [])
    assert dv.metal(eng, subject) == 2
    ctx = SimpleNamespace(engine=eng, actor=actor('owner'))
    assert dv.earth_save(ctx, subject, 'STR', {'forced_movement'}) == {'modes': ['ADVANTAGE']}
    assert 'h1' not in subject.conditions
    assert dv.earth_save(ctx, subject, 'STR', {'forced_movement'}) is None


# --- CL18 Imperial Dispersal --------------------------------------------------------------
def test_imperial_field_end_runs_exactly_one_dispersal(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    eng.state.actors['owner'] = owner
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'state', lambda a: {'field_id': 'zone:field'})
    monkeypatch.setattr(dv, 'store', lambda e, a, d: None)
    seen = []
    monkeypatch.setattr(dv, 'dispersal', lambda e, o: seen.append(o.entity_id))
    dv.field_ended(eng, 'ZONE_REMOVED', {'payload': {'zone_id': 'zone:field'}})
    dv.field_ended(eng, 'ZONE_REMOVED', {'payload': {'zone_id': 'another'}})
    assert seen == ['owner']
