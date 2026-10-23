"""Sol review F15 regressions for the Orbiting Shield Warden lane.

F15-1: a real bound Shield's Guard protection ends when the Shield leaves the
protected creature's 5-foot reach, and when the Warden enters Assault Mode.
Both cases use real table commits and a cold replay.

F15-2: Sheltered Heaven's 10-foot start-of-turn movement offers every legal
destination, including one beyond the first 16 sorted squares.
"""
from combat.ext import orbiting_shield_warden as w
from combat.ext import needle, rider_choices
from combat.gate2_runtime_models import Position
from tests import r1i_service_support as s
from tests.test_mgr_t14_warden_review_f9 import advance, bound_fight, commit, fresh, options


def _select(prompt, ids):
    if any(i.startswith('cell:') for i in ids):
        return ['cell:4,5,0'] if 'cell:4,5,0' in ids else []
    if s.OWNER in ids:
        return [s.OWNER]
    return None


def _guarded_bound_fight(tmp_path):
    combat, table, mid, state, item = bound_fight(tmp_path)
    commit(table, mid, s.candidate(table, mid, 'Release bound Shield'), _select)
    commit(table, mid, table.state(mid)['menu']['end_turn'], _select)
    engine = fresh(combat, mid)
    owner = engine.state.actors[s.OWNER]
    real = next(o for o in w.shields(engine, owner) if not o.component[w.TAG]['projected'])
    assert any(o.object_id == real.object_id for _, held in w.protection(engine, owner) for o in held)
    advance(table, mid, s.OWNER)
    return combat, table, mid, owner, real.object_id


def test_f15_bound_guard_ends_when_protected_creature_leaves_shield_reach(tmp_path):
    combat, table, mid, owner, oid = _guarded_bound_fight(tmp_path)
    def far(prompt, ids):
        # Move the actual Shield to a square more than 5 feet from its protected creature.
        far_cells = [i for i in ids if i.startswith('cell:') and int(i.split(':')[1].split(',')[0]) >= 8 and i.endswith(',0')]
        if far_cells:
            return [far_cells[0]]
        return _select(prompt, ids)
    commit(table, mid, s.candidate(table, mid, 'Move Shields'), far)
    engine = fresh(combat, mid)
    real = engine.state.objects[oid]
    assert engine.grid.distance_ft(real.position, engine.state.actors[s.OWNER].position) > 5
    assert real.component[w.TAG]['protected'] == ''
    assert not any(o.object_id == oid for _, held in w.protection(engine, engine.state.actors[s.OWNER]) for o in held)


def test_f15_bound_guard_ends_when_warden_enters_assault_mode(tmp_path):
    combat, table, mid, owner, oid = _guarded_bound_fight(tmp_path)
    commit(table, mid, s.candidate(table, mid, 'Constellation Movement'),
           lambda p, ids: ['assault'] if 'assault' in ids else _select(p, ids))
    engine = fresh(combat, mid)
    real = engine.state.objects[oid]
    assert real.component[w.TAG]['mode'] == 'assault'
    assert real.component[w.TAG]['protected'] == ''
    assert not any(o.object_id == oid for _, held in w.protection(engine, engine.state.actors[s.OWNER]) for o in held)


def test_f15_sheltered_movement_offers_destination_beyond_first_sixteen(monkeypatch):
    # An open 5-foot grid around (10,10): a 10-foot step reaches 25 squares, including (12,10).
    cells = {}
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            cost = 5 * max(abs(dx), abs(dy))
            cells[Position(x=10 + dx, y=10 + dy, z=0)] = cost
    class Grid:
        square_size_ft = 5
        def distance_ft(self, a, b):
            return 5 * max(abs(a.x - b.x), abs(a.y - b.y))
    engine = type('E', (), {'grid': Grid()})()
    capped, _ = needle.cell_options(engine, None, cells)
    full, labels = needle.cell_options(engine, None, cells, cap=None)
    assert len(cells) == 25 and len(capped) == 16
    assert len(full) == 25
    assert 'cell:12,10,0' in full and 'cell:12,10,0' not in capped
    assert labels['cell:10,10,0'].endswith('stay where you are')


def test_f15_shelter_step_requests_uncapped_destinations(monkeypatch):
    seen = {}
    def record(engine, mover, key, name, subject, feet, source, intent=None, **kw):
        seen.update(kw)
        seen['cap_arg'] = kw.get('cap', 'missing')
        return False
    monkeypatch.setattr(rider_choices, 'step', record)
    engine = type('E', (), {})()
    target = type('T', (), {'entity_id': 'x'})()
    monkeypatch.setattr(w, 'sheltered', lambda e, t: ['zone'])
    w.shelter_step(engine, target)
    assert seen['cap_arg'] is None
