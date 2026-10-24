"""Supported saves made at a standing zone's turn start still settle their Dew (no action completes there)."""
import pytest

from tests.cw2_service_support import add_action
from tests.test_a2_foundations3 import pool
from tests.test_spirit_dew_maintenance import WAR
from tests.test_spirit_dew_protection import AEGIS
from tests.test_spirit_dew_review_boundaries import _supporter
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


def _zone(name, effects):
    # A foe's standing area that delivers its effects when a creature starts its turn inside it.
    # Triggers belong on the zone spec (zones.py reads them from there), not on the effect row.
    spec = {'name': name, 'shape': 'sphere', 'size_ft': 30, 'centered_on_self': True,
            'duration': {'kind': 'until_removed'},
            'triggers': [{'on': ['start'], 'effects': effects}]}
    return [{'type': 'zone'}], {'zone_spec': spec}


@pytest.mark.parametrize('kind', ['concentration', 'fear'])
def test_zone_turn_start_support_settles_dew_after_commit_and_reload(tmp_path, kind):
    def prepare(bundles):
        bundles[1]['actor_template']['saving_throws']['CON' if kind == 'concentration' else 'WIS'] = 100
        if kind == 'concentration':
            add_action(bundles[0], 'Prepare Concentration support', [
                {'type': 'advantage', 'on': 'the next Concentration saving throw',
                 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
            effects, typed = _zone('Cold field', [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])
        else:
            effects, typed = _zone('Dread field', [{'type': 'save', 'ability': 'WIS', 'applies_to': 'target',
                'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                             'duration': {'kind': 'until_end_of_your_next_turn'}}], 'on_success': []}])
        add_action(bundles[2], typed['zone_spec']['name'], effects, target='SELF', typed=typed)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=_supporter(AEGIS),
        ally_talents=[WAR], bundle_transform=prepare, named=True, seed=f'DEW-ZONE-{kind.upper()}')
    if kind == 'concentration':
        settle(table, mid, candidate(combat, mid, 'Prepare Concentration support', target=ALLY).candidate_id, choices={})
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'War Song').candidate_id)
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Cold field', target=None).candidate_id)
    else:
        settle(table, mid, candidate(combat, mid, 'Radiant Aegis of the Heart', target=ALLY).candidate_id, choices={})
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Dread field', target=None).candidate_id)
    # ALLY's turn begins inside the zone: the zone's save or Concentration check is supported, and the
    # settled receipt must reach the owner in the same committed transaction.
    turn(table, mid, ALLY)
    committed = reload(tmp_path, mid)
    assert committed.state.actors[OWNER].resources.get(pool('spirit'), 0) == 1
    if kind == 'concentration':
        assert committed.state.actors[ALLY].concentration is not None
    saved = next(e for e in reversed(committed.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE' and saved.payload['success'] is True
    # Only the protection route's receipt is queued; a second cold load must not award it again.
    assert reload(tmp_path, mid).state.actors[OWNER].resources.get(pool('spirit'), 0) == 1
