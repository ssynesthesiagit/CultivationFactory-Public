"""Zero-HP sanctuary outcome is committed before reentrant recovery."""
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import OWNER, ALLY, FOE, turn, candidate, settle, reload


def test_overlapping_welcome_fields_cannot_heal_after_stable_is_applied(tmp_path):
    combat, table, mid = fight(tmp_path)
    # Create two overlapping fields, both protecting the same recipient.
    cast(combat, table, mid, 'temp_hp')
    settle(table, mid, candidate(reload(tmp_path, mid), mid, 'Flame That Welcomes All').candidate_id,
           choices={'choice:needle.welcome_recipients': [ALLY],
                    'choice:needle.homefire_recovery': 'temp_hp'})
    turn(table, mid, FOE)
    settle(table, mid, candidate(reload(tmp_path, mid), mid, 'Drop to zero', target=ALLY).candidate_id,
           choices={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': None,
                    'choice:needle.homefire_recovery': 'hit_points'})
    ally = reload(tmp_path, mid).state.actors[ALLY]
    assert ally.current_hp == 0
    assert ally.life_state == 'STABLE'
