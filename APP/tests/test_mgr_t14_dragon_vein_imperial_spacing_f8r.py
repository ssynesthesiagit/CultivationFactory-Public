"""Sol F8R regression: Imperial Dragon Vein is offered only when five Imperial Anchors can be placed.

Printed rule (Imperial Dragon Vein): five Imperial Anchors, each on a stable unoccupied space and each at least
15 feet from every other Imperial Anchor. A cluster of five legal cells that cannot be spaced 15 feet apart must
not be offered as an action, and the resolver must not offer a first anchor that leaves no legal set.
Synthetic in-memory engine only; no live server, no fight save.
"""
from types import SimpleNamespace

from combat.ext import dragon_vein_geomancer as dv
from combat.ext import grid_radius_cache
from combat.ext import placed as placed_mod
from combat.gate2_runtime_models import Position


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

    def _start_concentration(self, *args, **kwargs):
        self.events.append(('concentration', args))


def owner_actor():
    return SimpleNamespace(entity_id='owner', actor_id='owner', owner_id='owner', team_id='team:a',
                           position=Position(x=50, y=50, z=0), turn_flags={}, resources={}, conditions={},
                           display_name='owner', active=True)


def use_cells(monkeypatch, cells):
    monkeypatch.setattr(grid_radius_cache, 'cells_in_radius',
                        lambda grid, c, r: [Position(x=x, y=y, z=0) for x, y in cells])
    monkeypatch.setattr(dv, 'stable', lambda e, p: True)
    monkeypatch.setattr(dv, 'kit', lambda e, a: {'owned': [dv.IMPERIAL], 'numbers': {'pb': 2, 'cl': 3}})


def gate(monkeypatch, cells, center=(0, 0)):
    use_cells(monkeypatch, cells)
    eng = Engine()
    owner = owner_actor()
    eng.state.actors['owner'] = owner
    action = SimpleNamespace(parameters={'geomancy': 'imperial'})
    candidate = SimpleNamespace(destination=Position(x=center[0], y=center[1], z=0))
    return dv.candidates(eng, owner, candidate, action)


def test_five_cells_all_within_15_feet_are_not_offered(monkeypatch):
    # A 3x3 block: every pair is 5-10 feet apart, so no five anchors can be placed 15 feet apart.
    block = [(x, y) for x in range(3) for y in range(3)]
    assert gate(monkeypatch, block) is False


def test_five_spaced_cells_are_offered(monkeypatch):
    spaced = [(0, 0), (3, 0), (6, 0), (9, 0), (12, 0)]
    assert gate(monkeypatch, spaced) is True


def test_extra_clustered_cells_do_not_hide_a_legal_set(monkeypatch):
    spaced = [(0, 0), (3, 0), (6, 0), (9, 0), (12, 0)]
    assert gate(monkeypatch, spaced + [(1, 0), (2, 0)]) is True


def test_resolver_never_offers_a_first_anchor_that_leaves_no_legal_set(monkeypatch):
    # Only (0,0),(3,0),(6,0),(9,0),(12,0) form a legal five. Choosing (1,0) first would be a dead end.
    use_cells(monkeypatch, [(0, 0), (1, 0), (3, 0), (6, 0), (9, 0), (12, 0)])
    offered = []

    def fake_choose(ctx, suffix, options, **kwargs):
        offered.append(sorted((p.x, p.y) for p in options.values()))
        # Always take the lowest offered space, so the chosen set is the legal one.
        return [min(options, key=lambda k: (options[k].x, options[k].y))]

    monkeypatch.setattr(dv, 'choose', fake_choose)
    monkeypatch.setattr(dv, 'store', lambda *a, **k: None)
    monkeypatch.setattr(placed_mod, 'place', lambda engine, owner, **kw: SimpleNamespace(zone_id='zone:imperial'))
    eng = Engine()
    owner = owner_actor()
    eng.state.actors['owner'] = owner
    ctx = SimpleNamespace(engine=eng, actor=owner, source='source',
                          intent=SimpleNamespace(destination=Position(x=0, y=0, z=0)),
                          action=SimpleNamespace(source_definition_id='src'),
                          numbers={'cl': 3, 'pb': 2})
    dv.imperial(ctx)
    assert offered[0] == [(0, 0), (3, 0), (6, 0), (9, 0), (12, 0)]
    anchors = sorted((o.position.x, o.position.y) for o in eng.state.objects.values()
                     if o.object_kind == 'imperial_vein_anchor')
    assert anchors == [(0, 0), (3, 0), (6, 0), (9, 0), (12, 0)]
