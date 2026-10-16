"""Exact roof intersections and presentation-only geometry reuse, no live service."""
from fractions import Fraction
from random import Random
from types import SimpleNamespace

from combat import terrain_occlusion, spatial_areas
from combat.gate2_runtime_models import Position
from combat.read_queries import presentation_pass, file_snapshot


def test_editable_rules_are_read_once_per_presentation_and_refreshed_afterwards():
    engine = SimpleNamespace(state=SimpleNamespace(state_version=1,event_sequence=1))
    reads = []
    def read():
        reads.append(1)
        return len(reads)
    assert file_snapshot(('fixture_rules',),read) == 1
    with presentation_pass(engine):
        assert file_snapshot(('fixture_rules',),read) == 2
        assert file_snapshot(('fixture_rules',),read) == 2
        assert file_snapshot(('other_fixture_rules',),read) == 3
    with presentation_pass(engine):
        assert file_snapshot(('fixture_rules',),read) == 4
    assert file_snapshot(('fixture_rules',),read) == 5


def scan_roofs(roofs, start, end):
    """Previous tile-scan oracle, independent of the new plane/lookup algorithm."""
    dz = (end.z - start.z) * 5
    if not dz:
        return True
    for (x, y), top in roofs.items():
        n, d = top - start.z * 5, dz
        if d < 0:
            n, d = -n, -d
        if not 0 <= n < d or (n == 0 and dz > 0):
            continue
        px = (2 * start.x + 1) * d + 2 * (end.x - start.x) * n
        py = (2 * start.y + 1) * d + 2 * (end.y - start.y) * n
        if 2*x*d <= px <= (2*x+2)*d and 2*y*d <= py <= (2*y+2)*d:
            return False
    return True


def test_roof_planes_match_tile_scan_at_seams_endpoints_and_fractional_surfaces():
    random = Random(7125)
    roofs = {(x,y): (10,17,25)[(x+y)%3] for x in range(-2,9) for y in range(-2,9)
             if random.randrange(4)}
    grid = SimpleNamespace(roof_tops=roofs)
    points = [SimpleNamespace(x=x,y=y,z=z) for x,y,z in (
        (0,0,0), (0,0,2), (0,0,8), (2,2,Fraction(17,5)),
        (-1,0,Fraction(1,2)), (8,8,5), (3,3,2))]
    for start in points:
        for end in points:
            assert terrain_occlusion.roofs_visible(grid,start,end) == scan_roofs(roofs,start,end)
    for _ in range(600):
        start = SimpleNamespace(x=random.randrange(-3,11),y=random.randrange(-3,11),z=Fraction(random.randrange(50),5))
        end = SimpleNamespace(x=random.randrange(-3,11),y=random.randrange(-3,11),z=Fraction(random.randrange(50),5))
        assert terrain_occlusion.roofs_visible(grid,start,end) == scan_roofs(roofs,start,end)


def test_roof_intersection_lookups_are_bounded_by_levels_not_tile_count():
    class Counted(dict):
        calls = 0
        def get(self,*args):
            self.calls += 1
            return super().get(*args)
    roofs = Counted({(x,y):10 for x in range(50) for y in range(50)})
    grid = SimpleNamespace(roof_tops=roofs)
    start,end = Position(x=70,y=70,z=8),Position(x=60,y=60)
    assert terrain_occlusion.roofs_visible(grid,start,end)
    assert roofs.calls <= 4


def test_integer_segment_supercover_preserves_exact_slabs_and_bounds_work(monkeypatch):
    random = Random(3051)
    cells = {(x,y) for x in range(-2,22) for y in range(-2,22)}
    grid = SimpleNamespace(roof_tops={}, blocked=cells, opaque=set(),
        terrain_spans={'BLOCKED': {cell: [(0, 5 + (cell[0]%4)*5)] for cell in cells}},
        terrain_heights={}, occluder_spans={})
    for _ in range(300):
        start,end = [SimpleNamespace(x=random.randrange(-4,25),y=random.randrange(-4,25),
                                     z=Fraction(random.randrange(50),5)) for _ in range(2)]
        expected = not any(terrain_occlusion.cell_span_hit(start,end,cell,bottom,top)
                           for cell in cells for bottom,top in grid.terrain_spans['BLOCKED'][cell])
        assert terrain_occlusion.segment_clear(grid,start,end,physical=True) == expected
        assert terrain_occlusion.segment_clear(grid,start,end) == expected
    calls = []
    original = terrain_occlusion.cell_span_hit
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(terrain_occlusion,'cell_span_hit',counted)
    assert terrain_occlusion.segment_clear(grid,Position(x=0,y=0,z=20),Position(x=20,y=20,z=20),physical=True)
    assert len(calls) <= 61


def test_segment_cache_is_read_only_scoped_and_does_not_consume_dynamic_obscurement(monkeypatch):
    grid = SimpleNamespace(roof_tops={},blocked=set(),opaque=set(),terrain_spans={},terrain_heights={},occluder_spans={})
    engine = SimpleNamespace(grid=grid,state=SimpleNamespace(state_version=1,event_sequence=1))
    start,end = Position(x=0,y=0),Position(x=2,y=0)
    calls = []
    original = terrain_occlusion._segment_clear
    def counted(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(terrain_occlusion,'_segment_clear',counted)
    assert terrain_occlusion.segment_clear(grid,start,end)
    assert terrain_occlusion.segment_clear(grid,start,end)
    assert len(calls) == 2
    with presentation_pass(engine):
        assert terrain_occlusion.segment_clear(grid,start,end)
        assert terrain_occlusion.segment_clear(grid,start,end)
        assert len(calls) == 3
        assert not terrain_occlusion.segment_clear(grid,start,end,obscured_cells=iter([(1,0)]))
        assert not terrain_occlusion.segment_clear(grid,start,end,obscured_cells=iter([(1,0)]))
        assert len(calls) == 5
    grid.blocked.add((1,0))
    assert not terrain_occlusion.segment_clear(grid,start,end)
    assert len(calls) == 6


def test_zone_membership_cache_is_scoped_and_distinguishes_projected_positions(monkeypatch):
    actor = SimpleNamespace(position=Position(x=0,y=0))
    calls = []
    def volume(actor,at):
        p = at or actor.position
        return ((p.x,p.y,p.z),)
    engine = SimpleNamespace(_actor_volume=volume,state=SimpleNamespace(state_version=1,event_sequence=1))
    def contains(engine,positions,zone):
        calls.append(positions)
        return bool(positions)
    monkeypatch.setattr(spatial_areas,'positions_inside_zone',contains)
    zone = object()
    with presentation_pass(engine):
        assert spatial_areas.zone_contains(engine,actor,zone)
        assert spatial_areas.zone_contains(engine,actor,zone)
        assert spatial_areas.zone_contains(engine,SimpleNamespace(position=actor.position),zone)
        assert spatial_areas.zone_contains(engine,actor,zone,at=Position(x=1,y=0))
        assert len(calls) == 2
    assert spatial_areas.zone_contains(engine,actor,zone)
    assert len(calls) == 3
