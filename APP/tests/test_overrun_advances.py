"""Advancing Brute contests through real table commits and cold replays; synthetic public characters only."""
import pytest

from combat.ext.brute_shove import RAM, LINE
from tests.cw2_service_support import seal
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn


def setup(tmp_path, talent, *, success=True, second=False, anchored=False):
    def prepare(bundles):
        for b in bundles:
            b['skills'] = {'Athletics': 100 if b['actor_id'] == OWNER else -100, 'Acrobatics': -100}
            if b['actor_id'] == FOE and not success or b['actor_id'] == ALLY and second:
                b['skills']['Athletics'] = 300
            seal(b)
    combat, table, mid = fixture(tmp_path, [talent, 'TAL_BRUTE_TAKEDOWN'], owner_speed=60,
        positions={OWNER: {'x': 3, 'y': 0}, FOE: {'x': 4, 'y': 0},
                   ALLY: {'x': 6 if second else 1, 'y': 0}},
        team_overrides={ALLY: 'team:opponents'} if second else None,
        foe_sheet=sheet(['TAL_BRUTE_SOVEREIGN_WEIGHT_INCARNATION']) if anchored else None,
        bundle_transform=prepare, named=True)
    if anchored:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Sovereign Weight Incarnation').candidate_id)
        turn(table, mid, OWNER)
    return combat, table, mid


def use(combat, table, mid, name, endpoint):
    return settle(table, mid, candidate(combat, mid, name).candidate_id, {
        'choice:needle.brute_advance_path': endpoint,
        'choice:needle.brutal_shove_result': 'prone',
        'choice:needle.brute_sovereign_move': 'stay',
        'choice:needle.advance_manhandle_when': 'apply',
    })


def checks(engine):
    return [event for event in engine.events if event.event_type == 'CHECK_ROLLED'
            and event.payload.get('contest') == 'overrun']


def test_ram_success_shoves_crosses_and_exempts_only_its_target(tmp_path):
    # A real Sovereign target elects to stay put when shoved, so exiting its reach
    # really would provoke without Ram's exemption; this is not an empty OA assertion.
    combat, table, mid = setup(tmp_path, RAM, anchored=True)
    before = reload(tmp_path, mid)
    ordinary = before.state.actors[OWNER].movement_remaining_ft
    prompts = use(combat, table, mid, 'Living Battering Ram', 'cell:7,0')
    e = reload(tmp_path, mid)
    assert (e.state.actors[OWNER].position.x, e.state.actors[OWNER].position.y) == (7, 0)
    assert e.state.actors[FOE].position.x == 4
    assert e.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values())
    assert len(checks(e)) == 1 and checks(e)[0].payload['success']
    assert e.state.actors[OWNER].movement_remaining_ft == ordinary
    assert not any(event.actor_id == FOE and 'OPPORTUNITY' in event.event_type for event in e.events)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.advance_manhandle' for p in prompts)
    from combat import ext
    # The exemption is over, and no turn-long named passage leaked from the advance.
    assert ext.any_false('opportunity_allowed', e, e.state.actors[FOE], e.state.actors[OWNER]) is False
    assert not any(c.condition_id == 'condition:typed.named_creature_passage'
                   for c in e.state.actors[OWNER].conditions.values())


def test_ram_failed_contest_stops_before_hostile_and_does_not_shove(tmp_path):
    combat, table, mid = setup(tmp_path, RAM, success=False)
    use(combat, table, mid, 'Living Battering Ram', 'cell:7,0')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].position.x == 3
    assert e.state.actors[FOE].position.x == 4
    assert e.state.actors[FOE].current_hp == 60
    assert len(checks(e)) == 1 and not checks(e)[0].payload['success']
    assert not any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values())


def test_line_breaker_shoves_first_then_stops_at_first_failed_overrun(tmp_path):
    # The first target stays in the path; the second wins. Each contest must occur
    # once, in route order, and no speculative query can spend a roll or Manhandle.
    combat, table, mid = setup(tmp_path, LINE, second=True, anchored=True)
    before = reload(tmp_path, mid)
    prompts = use(combat, table, mid, 'Fortress-Line Breaker', 'cell:9,0')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].position.x == 5
    assert [event.target_ids for event in checks(e)] == [(FOE,), (ALLY,)]
    assert [event.payload['success'] for event in checks(e)] == [True, False]
    assert e.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    assert e.state.actors[ALLY].current_hp == 60
    assert e.state.actors[OWNER].resources['resource:core.martial_focus'] == 0
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.advance_manhandle' for p in prompts) == 1


def test_nonowner_actions_do_not_gain_advancing_passage(tmp_path):
    combat, _, mid = fixture(tmp_path, [])
    e = reload(tmp_path, mid)
    from combat.ext.brute_shove import advancing_passage, advancing_protection, advancing_terrain
    mover, target = e.state.actors[OWNER], e.state.actors[FOE]
    assert advancing_passage(e, mover, target) is None
    assert advancing_protection(e, target, mover) is None
    assert advancing_terrain(e, mover) is None
    assert not any(any(row.get('type') == 'brute_advance' for row in
                       ((a.parameters or {}).get('typed') or {}).get('effects') or [])
                   for a in e.action_catalog.values())
