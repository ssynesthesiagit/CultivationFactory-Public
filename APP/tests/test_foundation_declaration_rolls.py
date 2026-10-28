"""The Perfected declarations give their Advantage on the listed saves and checks for the whole minute.

Perfected Heaven Tyrant Blood Declaration: Advantage on qualifying Strength or Constitution physical contests and on
resisting forced movement, Prone, Grappled, Restrained and body suppression. Perfected Imperishable Heaven Womb: Advantage on
saves and ability checks against drain, poison, necrotic source-corruption, possession pressure and body/source suppression.
"""
import pytest

from tests.test_a2_r11_foundations import _fight, _typed_action
from tests.worker2_support import FOE, OWNER, candidate, reload, settle, turn

TYRANT = ('heaven_tyrant_body_v0_2D', 'Tyrant Form Pulse', 'Perfected: Heaven Tyrant Blood Declaration', 'forced_movement')
WOMB = ('heaven_devouring_shedding_womb_v0_2B', 'Devoured Origin Spark', 'Perfected: Imperishable Heaven Womb', 'drain')


def _contest(tmp_path, family, hazard, declared=True):
    foundation, pool, declaration, _ = family
    shove = _typed_action('Shove contest', FOE, [{
        'type': 'contest_against', 'actor_check': {'ability': 'STR', 'hazards': [hazard]},
        'target_check': {'ability': 'STR', 'hazards': [hazard]}, 'on_success': [], 'on_fail': []}], economy='ACTION')
    combat, table, mid = _fight(tmp_path, foundation, pool, stage='Perfected', held=0, foe_actions=[shove])
    if declared:
        settle(table, mid, candidate(combat, mid, declaration).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Shove contest', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    return next(e.payload['target']['mode'] for e in engine.events if e.event_type == 'CHECK_ROLLED')


@pytest.mark.parametrize('family', [TYRANT, WOMB], ids=['tyrant', 'womb'])
def test_a_declared_minute_gives_advantage_on_the_listed_contest(tmp_path, family):
    assert _contest(tmp_path, family, family[3]) == 'ADVANTAGE'


@pytest.mark.parametrize('family', [TYRANT, WOMB], ids=['tyrant', 'womb'])
def test_without_the_declaration_the_same_contest_is_normal(tmp_path, family):
    assert _contest(tmp_path, family, family[3], declared=False) == 'NORMAL'


@pytest.mark.parametrize('family', [TYRANT, WOMB], ids=['tyrant', 'womb'])
def test_a_declared_minute_gives_no_advantage_against_unlisted_pressure(tmp_path, family):
    assert _contest(tmp_path, family, 'frightened') == 'NORMAL'

