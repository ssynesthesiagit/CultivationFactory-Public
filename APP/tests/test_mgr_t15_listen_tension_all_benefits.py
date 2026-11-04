"""Regression: Listen Through Tension requires exactly one printed benefit choice."""
from tests.mgr_t15_listen_fixture import *


def test_one_bonus_action_requires_one_benefit_and_grants_only_that_benefit(tmp_path):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check',))
    engine = cold(tmp_path, mid)
    table = TabletopService(CombatService(ROOT, table.combat.userdata_root), table.combat.userdata_root)
    assert len(grants(engine)) == 1
    grant = grants(engine)[0]
    assert grant.data['benefit'] == 'check'
    assert grant.expires_on == 'END_OF_MARKER_NEXT_TURN'
    reach(table, mid, F)
    reach(table, mid, P)
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), ('Perception', F))
    engine = cold(tmp_path, mid)
    rolls = [event for event in engine.events
             if event.event_type == 'CHECK_ROLLED' and event.actor_id == P]
    assert rolls[-1].payload['actor']['mode'] == 'ADVANTAGE'
    # The printed check is spent, so it grants no Advantage again. The spent
    # check stays as line-bound eligibility for the separate Invisible clause.
    assert not checks(engine)
    assert [c.data['line_id'] for c in receipts(engine)] == [grant.data['line_id']]
    assert receipts(engine)[0].expires_on == 'UNTIL_REMOVED'

