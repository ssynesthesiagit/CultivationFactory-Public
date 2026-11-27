"""Mantis Hooks must not consume a damage-roll benefit on a replaced hit."""
from combat.ext.music import FURY_DAMAGE
from tests.test_mgr_mantis_native import DECLINE, P, hit, native, settle
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, turn


def test_light_hit_leaves_real_fury_for_the_next_weapon_roll(tmp_path):
    combat, table, mid = native(tmp_path, friendly_ally=True, advance_owner=False,
        ally_talents=('tianxia.talent.music.soul_stirring_refrain',))
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Soul-Stirring Refrain: Fury', target=OWNER).candidate_id,
           picks={'choice:willing.consent': 'accept'})
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.music_fury'
               for c in engine.state.actors[OWNER].conditions.values())
    turn(table, mid, OWNER)
    hit(combat, table, mid, picks={**DECLINE,
        'choice:needle.mantis_hooks_light': 'light',
        'choice:needle.mantis_hooks': 'grapple'})
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.actor_id == OWNER and r.reason.startswith('DAMAGE:')]
    assert len(rolls) >= 2 and not rolls[0].dice and rolls[1].dice
    assert rolls[1].modifier == 10 + engine.state.actors[ALLY].proficiency_bonus
    assert engine.state.actors[OWNER].turn_flags.get(FURY_DAMAGE)
    assert any(c.condition_id.endswith('.grappled') for c in engine.state.actors[FOE].conditions.values())
