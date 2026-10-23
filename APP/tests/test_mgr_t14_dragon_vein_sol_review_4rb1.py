"""Regression tests for Sol review 4RB1 findings on the Dragon-Vein Geomancer branch.

Each test drives one plug-in function with the in-memory engine from the
earlier review-fix file and monkeypatches only spatial, relation and
persistence helpers. No live server or external process is used.
"""
from types import SimpleNamespace

from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_runtime_models import Position, RuntimeObjectState


class Grid:
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


def actor(eid, x=0, y=0):
    return SimpleNamespace(entity_id=eid, actor_id=eid, owner_id=eid, team_id='team:a',
                           position=Position(x=x, y=y, z=0), turn_flags={}, resources={}, conditions={},
                           display_name=eid, active=True)


def kit_for(owned=(dv.READ, dv.CIRCUIT), pb=1, cl=3):
    return {'owned': list(owned), 'numbers': {'pb': pb, 'cl': cl}}


def field_anchor(oid, owner, x, y, field_id, mode='earth'):
    block = {'mode': mode, 'created_sequence': 1, 'end_round': 99, 'field_id': field_id, 'support': {}}
    return RuntimeObjectState(object_id=oid, object_kind='vein_anchor', position=Position(x=x, y=y, z=0),
                              unattended=True, flammable=False, owner_id=owner, ac=14, current_hp=6,
                              maximum_hp=6, damage_immunities=('POISON', 'PSYCHIC'), destroyed=False,
                              suppressed=False, component={'name': 'Vein Anchor', 'size': 'tiny', 'blocks': False,
                                                           'created_by': dv.IMPERIAL, dv.BLOCK: block})


def dict_state(monkeypatch, stores):
    monkeypatch.setattr(dv, 'state', lambda a: stores.get(a.entity_id, {}))
    monkeypatch.setattr(dv, 'store', lambda e, a, d: stores.__setitem__(a.entity_id, dict(d)))


# --- Finding 1: Dispersal resolves against the field that just ended ----------------------
def test_dispersal_benevolent_road_moves_allies_inside_the_ended_field(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    ally = actor('ally', 6, 6)
    eng.state.actors.update({'owner': owner, 'ally': ally})
    # The field's zone is already inactive when ZONE_REMOVED dispatches.
    eng.state.zones['zone:field'] = SimpleNamespace(zone_id='zone:field', active=False, owner_id='owner',
                                                    center=Position(x=5, y=5, z=0), trigger_profile={})
    anchor_obj = field_anchor('imp', 'owner', 9, 9, 'zone:field')
    eng.state.objects['imp'] = anchor_obj
    stores = {'owner': {'field_id': 'zone:field'}}
    dict_state(monkeypatch, stores)
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'context', lambda e, o, s, t=(): SimpleNamespace(engine=e, actor=o))
    monkeypatch.setattr(dv, 'choose', lambda ctx, suffix, options, **kw: ['benevolent'])
    monkeypatch.setattr('combat.relations.relation', lambda e, a, b: 'ALLY' if b.entity_id == 'ally' else 'SELF')
    moved = []
    monkeypatch.setattr(dv, 'move_ally', lambda ctx, target, feet, label, **k: moved.append((target.entity_id, feet, label)))
    dv.field_ended(eng, 'ZONE_REMOVED', {'payload': {'zone_id': 'zone:field'}})
    assert moved == [('ally', 10, 'Benevolent Road')]


def test_dispersal_retires_the_field_anchors_and_clears_the_geometry_marker(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    eng.state.actors['owner'] = owner
    eng.state.zones['zone:field'] = SimpleNamespace(zone_id='zone:field', active=False, owner_id='owner',
                                                    center=Position(x=5, y=5, z=0), trigger_profile={})
    eng.state.objects['imp'] = field_anchor('imp', 'owner', 9, 9, 'zone:field')
    stores = {'owner': {'field_id': 'zone:field'}}
    dict_state(monkeypatch, stores)
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'dispersal', lambda e, o: None)
    dv.field_ended(eng, 'ZONE_REMOVED', {'payload': {'zone_id': 'zone:field'}})
    assert eng.state.objects['imp'].destroyed is True
    assert stores['owner'].get('dispersing') is None


# --- Finding 5: every square entered on the path is judged, not just the endpoints --------
def test_water_circuit_triggers_when_the_creature_passes_through_the_area(monkeypatch):
    eng = Engine()
    subject = actor('ally', 0, 0)
    eng.state.actors.update({'ally': subject, 'g1': actor('g1')})
    stores = {'g1': {'allies': ['ally']}}
    dict_state(monkeypatch, stores)
    eng.state.objects['w'] = RuntimeObjectState(object_id='w', object_kind='vein_anchor',
        position=Position(x=0, y=0, z=0), unattended=True, flammable=False, owner_id='g1', ac=14,
        current_hp=6, maximum_hp=6, damage_immunities=(), destroyed=False, suppressed=False,
        component={dv.BLOCK: {'mode': 'water', 'created_sequence': 1, 'end_round': 9, 'support': {}}})
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for())
    monkeypatch.setattr(dv, 'gravity', lambda *a, **k: None)
    monkeypatch.setattr(dv, 'gravity_field_save', lambda *a, **k: None)
    monkeypatch.setattr(dv, 'context', lambda *a, **k: None)
    monkeypatch.setattr(dv, 'anchors', lambda e, o: [eng.state.objects['w']])
    monkeypatch.setattr(dv, 'covers', lambda e, o, obj, cell: cell.x == 1)
    monkeypatch.setattr(dv, 'modes', lambda e, o, obj: ('water',))
    moved = []
    monkeypatch.setattr(dv, 'move_ally', lambda ctx, target, feet, label, **k: moved.append((target.entity_id, label)))
    # (0,0) -> (1,0) -> (2,0): the middle square is inside the area, the final square is outside it.
    ev = {'actor_id': 'ally', 'payload': {'path': [{'x': 0, 'y': 0, 'z': 0}, {'x': 1, 'y': 0, 'z': 0}, {'x': 2, 'y': 0, 'z': 0}]}}
    dv.entered(eng, 'MOVEMENT_COMMITTED', ev)
    assert moved == [('ally', 'Water Circuit')]


# --- Finding 6: Increase Momentum applies only to a Qi-powered forced movement -----------
def test_increase_momentum_ignores_a_mundane_push_and_keeps_the_benefit(monkeypatch):
    eng = Engine()
    owner = actor('owner')
    owner.conditions['c1'] = SimpleNamespace(condition_id='condition:typed.geomancy_momentum', instance_id='c1')
    mundane = SimpleNamespace(engine=eng, actor=owner, source='weapon', typed={'source': 'weapon.mundane'},
                              action=SimpleNamespace(costs=()))
    assert dv.momentum_bonus(mundane, owner, {}) is None
    assert 'c1' in owner.conditions
    qi = SimpleNamespace(engine=eng, actor=owner, source='qi', typed={'source': dv.PREFIX + 'ley_line_circuit'},
                         action=SimpleNamespace(costs=((dv.QI, 1),)))
    assert dv.momentum_bonus(qi, owner, {}) == 5
    assert 'c1' not in owner.conditions


# --- Finding 7: Dragon Quake offers the printed damage choice ----------------------------
def test_dragon_quake_uses_the_chosen_damage_type(monkeypatch):
    eng = Engine()
    owner = actor('owner', 0, 0)
    foe = actor('foe', 5, 0)
    eng.state.actors.update({'owner': owner, 'foe': foe})
    monkeypatch.setattr(dv, 'kit', lambda e, a: kit_for(owned=(dv.IMPERIAL,)))
    monkeypatch.setattr(dv, 'context', lambda e, o, s, t=(): SimpleNamespace(engine=e, actor=o, numbers={'save_dc': 15}))
    answers = {'imperial_dispersal': ['quake'], 'quake_damage': ['bludgeoning'], 'quake_targets': ['foe']}
    monkeypatch.setattr(dv, 'choose', lambda ctx, suffix, options, **kw: answers[suffix])
    monkeypatch.setattr(dv, 'hostiles_in_claimed', lambda e, o: [foe])
    applied = []
    monkeypatch.setattr(dv, 'apply', lambda ctx, target, rows: applied.append(rows))
    dv.dispersal(eng, owner)
    damage = applied[0][0]['on_fail'][0]
    assert damage['damage_types'] == ['bludgeoning']
    assert applied[0][0]['on_success'][0]['damage_types'] == ['bludgeoning']
