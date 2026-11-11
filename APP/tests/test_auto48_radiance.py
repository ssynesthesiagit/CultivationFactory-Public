"""AUTO48 typed flight and paid Dawnmark check riders at the table boundary."""
import pytest
from combat.flight import profile
from tests.cw2_service_support import add_action, seal
from tests.worker2_flow import reload, settle, turn
from tests.worker2_support import OWNER, FOE, fixture, candidate

P = 'tianxia.talent.radiance.'
EXPOSED_CHECK = 'condition:typed.check_against'


@pytest.mark.parametrize('owned', [True, False])
def test_heavenly_flight_and_hover_persist_with_native_clock(tmp_path, owned):
    combat, table, mid = fixture(tmp_path, [P + 'heavenly_radiance'] if owned else [], seed='AUTO48-FLIGHT')
    if owned:
        settle(table, mid, candidate(combat, mid, 'Heavenly Radiance').candidate_id)
    e = reload(tmp_path, mid)
    assert profile(e, e.state.actors[OWNER]).speed_ft == (60 if owned else 0)
    assert profile(e, e.state.actors[OWNER]).hover == owned
    if not owned:
        return
    start = e.state.actors[OWNER].position
    move = next(c for c in e.legal_candidates() if c.destination and c.destination.z == 1
                and (c.destination.x, c.destination.y) == (start.x, start.y))
    settle(table, mid, move.candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].position.z == 1
    # The genuine one-minute activation supplies a recognized native clock.
    held = next(c for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values()
                if c.condition_id == 'condition:typed.radiance_heavenly_flight')
    assert held.expires_on.startswith('START_OF_SLOT_AT:')


@pytest.mark.parametrize('pay,early_remove', [(True, False), (False, False), (True, True)])
def test_expose_paid_stealth_penalty_tracks_the_mark_and_decline_is_inert(tmp_path, pay, early_remove):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare exposed target', [{'type': 'condition', 'condition': 'invisible',
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        add_action(bundles[0], 'Prepare Dawnmark', [{'type': 'mark', 'mark': 'Dawnmark',
            'applies_to': 'target', 'duration': {'kind': 'until_start_of_your_next_turn'}}])
        add_action(bundles[0], 'Remove prepared Dawnmark', [{'type': 'spend_mark', 'mark': 'Dawnmark', 'applies_to': 'target'}])
        add_action(bundles[2], 'Visual Stealth contest', [{'type': 'contest_against',
            'actor_check': {'ability': 'DEX', 'skill': 'Stealth', 'hazards': ['visual_concealment']},
            'target_check': {'ability': 'WIS'}}])
    combat, table, mid = fixture(tmp_path, [P + 'expose_false_form'], seed='AUTO48-EXPOSE', bundle_transform=prepare)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Prepare Dawnmark', target=FOE).candidate_id,
                     {'choice:needle.radiance_expose': 'pay' if pay else None})
    assert any('radiance_expose' in p['context']['reaction_source_id'] for p in prompts)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == before - int(pay)
    assert any(c.condition_id == EXPOSED_CHECK for c in e.state.actors[FOE].conditions.values()) == pay
    if early_remove:
        settle(table, mid, candidate(combat, mid, 'Remove prepared Dawnmark', target=FOE).candidate_id)
        assert not any(c.condition_id == EXPOSED_CHECK for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Visual Stealth contest', target=OWNER).candidate_id)
    roll = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'CHECK_ROLLED'
                and e.payload.get('roll_kind') == 'opposed_check')
    assert roll.payload['actor']['mode'] == ('DISADVANTAGE' if pay and not early_remove else 'NORMAL')
    turn(table, mid, OWNER)
    assert not any(c.condition_id == EXPOSED_CHECK for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
