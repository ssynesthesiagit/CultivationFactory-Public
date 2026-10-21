"""Temporary diagnostics for the two remaining Hearthfire failures (not committed)."""
from combat.gate2_runtime_models import Position
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t14_hearthfire_light import night_sighted_bundle, scene


def hearth_state(e):
    from combat.asset_anchor_runtime import legal_placement
    rows = [a for a in e.action_catalog.values() if a is not None and a.display_name == 'Kindled Hearth']
    cands = [(c.source_definition_id, c.destination and (c.destination.x, c.destination.y, c.destination.z))
             for c in e.legal_candidates()
             if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Kindled Hearth']
    return rows, cands, legal_placement(e, (Position(x=5, y=6, z=0),), 5)


def test_diag_light_candidate(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=night_sighted_bundle(tmp_path),
        owner_pb=6, battlefield=scene(tmp_path), foe_position={'x': 10, 'y': 6}, seed='HEARTH-LIGHT')
    e = reload(tmp_path, mid)
    rows, cands, legal = hearth_state(e)
    passive = len([r for r in getattr(e, 'typed_passive_rows', {}).get(OWNER, ()) if r.get('block') == 'qi_hearthfire'])
    owned = [a.source_definition_id for a in rows if a.source_definition_id in e.state.actors[OWNER].action_ids]
    assert rows, f"catalog_missing passive={passive}"
    assert owned, f"not_in_action_ids sources={[a.source_definition_id for a in rows]} passive={passive}"
    assert legal, f"legal_placement_false vol0={e.grid.volume_legal(Position(x=5,y=6,z=0))}"
    assert cands, f"no_candidate rows={len(rows)} owned={len(owned)} legal={legal}"
    settle(table, mid, candidate(combat, mid, 'Kindled Hearth', at=(5, 6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients': [OWNER, ALLY]})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    rows, cands, legal = hearth_state(e)
    assert any(c[1] and c[1][:2] == (3, 2) for c in cands), f"second_missing cands={cands} legal={legal} hp={e.state.actors[OWNER].current_hp}"
