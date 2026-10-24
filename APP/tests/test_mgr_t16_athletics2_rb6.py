"""Review fixes: unsourced Strong Lungs breath timing and non-Athletics water routes."""
from unittest.mock import patch
from tests import test_walkable_roofs as support
from tests.auto8f1_table_support import fixture, OWNER, candidate_id

LUNGS = 'TAL_ATHLETICS_STRONG_LUNGS'


def test_strong_lungs_alone_offers_no_timed_breath_hold(tmp_path):
    # Printed Strong Lungs gives no normal breath-holding base, so it times nothing.
    g = fixture(tmp_path, [LUNGS], seed='MGR-RB6-LUNGS-ONLY')
    assert 'hold your breath' not in str(g['menu']())


def _water_routes(tmp_path, terrain):
    original = support.roof_document

    def document(**kwargs):
        doc = original(**kwargs)
        doc.update(walls=[], objects=[], roofs={'enabled': False}, terrain=terrain)
        return doc

    with patch.object(support, 'roof_document', document):
        combat, _table, mid = support.roof_fight(tmp_path, owner_talents=[])
    engine = combat._load_session(mid).engine
    routes = sorted((c.destination.x, c.destination.y, c.destination.z, c.movement_cost_ft)
                    for c in engine.legal_candidates() if c.destination is not None)
    return engine.grid.terrain_spans.get('WATER'), routes


def test_non_athletics_walker_routes_unchanged_by_distant_water(tmp_path):
    # A plain walker with no Athletics talent must keep identical routes and costs
    # when water exists only far from its reach, versus the same map without water.
    (tmp_path / 'dry').mkdir()
    (tmp_path / 'wet').mkdir()
    dry_water, dry = _water_routes(tmp_path / 'dry', [])
    wet_water, wet = _water_routes(tmp_path / 'wet', [{'type': 'WATER', 'cells': [[0, 0]]}])
    assert dry_water is None
    assert wet_water, 'distant WATER region must survive map normalisation'
    assert wet == dry
