"""Flow Line Strike adds PB to real hits between represented formation Nodes."""
import itertools
import pytest

from combat.ext import formations as F
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, FOE, fixture, candidate
from tests.formation_support import settle, reload, turn

FLOW = 'tianxia.talent.formations.flow_line_strike'
COURT = 'tianxia.talent.formations.court_of_the_ninefold_array'


def setup(bundles):
    for b, bonus in zip(bundles, [100, -100, 0]):
        b['actor_template']['initiative_bonus'] = bonus
        b['actor_template']['maximum_hp'] = 500
        seal(b)
    bundles[2]['actor_template']['armor_class'] = 0
    seal(bundles[2])


@pytest.mark.parametrize('owns,court', [(True, True), (False, True), (True, False)])
def test_flow_line_hit_between_real_nodes_or_eye_only_control(tmp_path, owns, court):
    combat, table, mid = fixture(tmp_path, [*([FLOW] if owns else []), *([COURT] if court else [])],
        seed='AUTO30-SECOND-LINE', bundle_transform=setup)
    if court:
        settle(table, mid, candidate(combat, mid, 'Next Domain: layer Killing Line (Force)').candidate_id)
        settle(table, mid, candidate(combat, mid, 'Court of the Ninefold Array', at=(6, 6)).candidate_id)
        turn(table, mid, FOE)
        e = reload(tmp_path, mid)
        zone = F.arrays(e, OWNER)[0]
        nodes = [o for o in F.objects_of(e, zone) if o.component.get('role') == 'node']
        assert len(nodes) == 9
        midpoints = {((a.position.x + b.position.x)//2, (a.position.y + b.position.y)//2)
            for a,b in itertools.combinations(nodes,2)
            if (a.position.x+b.position.x)%2 == 0 and (a.position.y+b.position.y)%2 == 0}
        moves = [c for c in e.legal_candidates() if c.destination is not None and c.display_name.startswith('Move')
            and (c.destination.x,c.destination.y) in midpoints]
        assert moves, 'A real reachable point strictly between two Court Nodes'
        settle(table, mid, moves[0].candidate_id)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    else:
        settle(table, mid, candidate(combat, mid, 'Combat Array: Killing Line (Force)', at=(6,6)).candidate_id)
        assert not F.record(F.arrays(reload(tmp_path,mid), OWNER)[0]).get('nodes')
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Pulse: Killing Line', target=FOE).candidate_id)
    e = reload(tmp_path,mid)
    damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_ROLLED' and ev.actor_id == OWNER]
    assert damage
    assert damage[-1].payload['modifier'] == 2 + (4 if owns and court else 0)
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and FOE in ev.target_ids for ev in e.events)
