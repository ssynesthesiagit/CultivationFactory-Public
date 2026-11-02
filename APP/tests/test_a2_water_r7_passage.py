"""A2WATER: the shared creature-passage seam composes with other abilities.

These table/session/cold-reload cases cover independent grants and per-owner
Court entry. The declined continuous-transit regression lives beside Scarlet
Mist's service tests in test_auto80_blood.py.

* F1: a Water Court grant states its own cost and scope together, so it can no
  longer narrow an independent unrestricted grant such as Liquid Body's.
* F3: crossing only Court A leaves Court B's round use available; a later
  crossing through B's distinct row applies B's mark.
"""
import json

import pytest

from combat.gate2_runtime_models import Position
from tests.h1_support import ROOT, sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle, turn
from tests.test_a2_water import footwork_fixture
from tests.test_auto38_water import soaked

OWNER_B = 'actor:factory.worker2-owner-b'
FOE_B = 'actor:factory.worker2-foe-b'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
FOOTWORK = 'insight.tide-court-footwork'
CROSSED = "passes through"


def _crossing_notices(engine):
    """The recorded crossing notices a creature's passage produced."""
    return [v for v in engine.events
            if v.event_type == 'CONDITION_APPLIED' and CROSSED in str(v.payload.get('log', ''))]


def test_water_court_does_not_narrow_another_abilities_unrestricted_grant(tmp_path):
    """F1: Liquid Body keeps its whole-footprint grant while an ally is also in a Court.

    The Large hostile straddles the Court, so its second column lies outside it.
    Before the fix the Court's scoped grant was applied to the combined
    permission and removed that column from legal movement, so the ally could
    not cross a creature it was already entitled to cross.
    """
    combat, table, mid = footwork_fixture(tmp_path, ally_start=(31, 15), foe_start=(27, 15),
                                          large_foe=True, liquid_body=True)
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide', target=OWNER).candidate_id,
           {'choice:needle.water_tide_footwork': [ALLY]})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fixture Liquid Body', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER)
    court = {(cell.x, cell.y) for cell in zone.affected_cells}
    footprint = set(engine._actor_cells(engine.state.actors[FOE]))
    assert footprint & court and footprint - court, 'the fixture needs a hostile straddling the Court'

    destination = Position(x=25, y=15, z=0)
    moves = [c for c in engine.legal_candidates()
             if c.kind.value == 'MOVE' and c.destination == destination]
    assert moves, 'Liquid Body grants the whole hostile, so the far side stays reachable'
    # The per-cell cost is still applied: crossing the creature is difficult terrain.
    assert moves[0].movement_cost_ft == 40, moves[0].movement_cost_ft

    settle(table, mid, moves[0].candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].position == destination


def test_crossing_one_court_leaves_another_owners_round_benefit_unspent(tmp_path):
    """F3: entering only Court A's voxels must not spend Court B's round use.

    Both Courts touch the first Large hostile, but the ally enters only A's
    covered voxel. It later crosses a separate Large hostile inside B's Court.
    The separate placements keep each route within its own transit grant.
    """
    combat, table, mid = _two_owner_fixture(tmp_path)
    _cast_court(table, mid, combat, OWNER, [ALLY])
    _cast_court(table, mid, combat, OWNER_B, [ALLY])
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    zone_a = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER)
    zone_b = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER_B)
    court_a = {(cell.x, cell.y) for cell in zone_a.affected_cells}
    court_b = {(cell.x, cell.y) for cell in zone_b.affected_cells}
    footprint = set(engine._actor_cells(engine.state.actors[FOE]))
    footprint_b = set(engine._actor_cells(engine.state.actors[FOE_B]))
    a_crossed = {(27, 15)} & footprint
    b_crossed = {(33, 20), (34, 20)} & footprint_b
    assert a_crossed == {(27, 15)}
    assert a_crossed <= court_a and not a_crossed & court_b, (a_crossed, sorted(court_a), sorted(court_b))
    assert b_crossed == {(33, 20), (34, 20)}
    assert b_crossed <= court_b and not b_crossed & court_a, (b_crossed, sorted(court_a), sorted(court_b))
    assert footprint & court_b, 'Court B must still intersect the hostile to be a granting owner'

    a_route = [Position(x=x, y=y) for x, y in [(31, 14), (30, 14), (29, 14),
                                                   (28, 14), (27, 15), (27, 14)]]
    assert ({(p.x, p.y) for p in a_route} & footprint) == a_crossed
    _route(table, combat, mid, ALLY, a_route)

    engine = reload(tmp_path, mid)
    key = 'once_per_round:water_tide_footwork'
    assert engine.state.actors[OWNER].turn_flags.get(key) == engine.state.round_number
    assert key not in engine.state.actors[OWNER_B].turn_flags, "Court B's round benefit was spent by Court A's crossing"
    receipts = [v for v in engine.events if v.event_type == 'PASSIVE_TRIGGERED'
                and v.source_definition_id == FOOTWORK]
    assert [r.actor_id for r in receipts] == [OWNER], [r.actor_id for r in receipts]
    # Go around the first hostile and cross the separate B-owned hostile.
    b_route = [Position(x=x, y=y) for x, y in [(27, 14), (27, 13), (28, 13), (29, 13),
                                                   (30, 14), (31, 15), (32, 16), (32, 17),
                                                   (32, 18), (32, 19), (32, 20), (33, 20),
                                                   (34, 20), (35, 20)]]
    interior = {(p.x, p.y) for p in b_route[1:-1]}
    assert interior & court_b and b_crossed <= interior
    assert interior & footprint_b == b_crossed
    assert not interior & footprint
    _route(table, combat, mid, ALLY, b_route)
    engine = reload(tmp_path, mid)
    receipts = [v for v in engine.events if v.event_type == 'PASSIVE_TRIGGERED'
                and v.source_definition_id == FOOTWORK]
    assert [r.actor_id for r in receipts] == [OWNER, OWNER_B], [r.actor_id for r in receipts]
    assert engine.state.actors[OWNER_B].turn_flags.get(key) == engine.state.round_number


def _route(table, combat, mid, actor, path):
    """Commit an explicit route through the table, declining unrelated reactions."""
    menu = table.state(mid)['menu']
    waypoints = [point.model_dump(mode='json') for point in path]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], actor, waypoints)
    answers = []
    for _ in range(20):
        result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
                                        menu['state_version'], actor, waypoints, reactions=answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    raise AssertionError('movement did not commit after resolving its reactions')


def _cast_court(table, mid, combat, owner, recipients):
    turn(table, mid, owner)
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide', target=owner).candidate_id,
           {'choice:needle.water_tide_footwork': recipients})


def _two_owner_fixture(tmp_path):
    """Two Court owners over one Large hostile, plus the ally selected into both.

    The Courts are the same 60 ft emanation cast from opposite sides of a tall
    map, so Court A reaches the hostile's lower row and Court B its upper row.
    """
    import zipfile
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.cw2_service_support import add_action, seal

    ids = [OWNER, OWNER_B, ALLY, FOE, FOE_B]
    starts = {OWNER: (26, 4), OWNER_B: (28, 27), ALLY: (31, 14),
              FOE: (27, 15), FOE_B: (33, 20)}
    documents = {}
    for aid in ids:
        doc = sheet([COURT] if aid in (OWNER, OWNER_B) else [], cl=15)
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        if aid == ALLY:
            doc['ability_scores_and_statistics']['speed']['walking_ft'] = 120
        if aid in (OWNER, OWNER_B):
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = ['insight.tide-court-footwork']
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        documents[aid] = doc
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Water footwork hall', 'width_squares': 40, 'height_squares': 32,
                               'walls': [{'shape': 'rect', 'points': [[0, 0], [40, 2]]},
                                         {'shape': 'rect', 'points': [[0, 30], [40, 32]]}],
                               'starts': {'team1': [list(starts[a]) for a in (OWNER, OWNER_B, ALLY)],
                                           'team2': [list(starts[a]) for a in (FOE, FOE_B)]}})
    bundles = [compile_character(documents[aid], actor_id=aid, reaction_plan={'ask': True}) for aid in ids]
    for foe_id in (FOE, FOE_B):
        foe = next(b for b in bundles if b['actor_id'] == foe_id)
        add_action(foe, 'Prepare Large hostile', [{'type': 'size_change', 'size': 'Large',
            'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}], target='SELF')
        seal(foe)
    arena = combat.factory_arenas(include_retired=True)['battlefield:map.water-footwork-hall']
    positions = {aid: {'x': starts[aid][0], 'y': starts[aid][1]} for aid in ids}
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: 'team:factory', OWNER_B: 'team:factory', ALLY: 'team:factory',
         FOE: 'team:opponents', FOE_B: 'team:opponents'},
        positions, arena, [OWNER, OWNER_B, ALLY], [FOE, FOE_B],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='A2WATER-TWOCOURT',
        display_name='A2WATER two Court owners', maximum_rounds=20)['match_id']
    table = TabletopService(combat, tmp_path)
    for foe_id in (FOE, FOE_B):
        turn(table, mid, foe_id)
        settle(table, mid, candidate(combat, mid, 'Prepare Large hostile').candidate_id)
    grown = reload(tmp_path, mid)
    assert grown._footprint(grown.state.actors[FOE]).width_cells == 2
    assert grown._footprint(grown.state.actors[FOE_B]).width_cells == 2
    return combat, table, mid
