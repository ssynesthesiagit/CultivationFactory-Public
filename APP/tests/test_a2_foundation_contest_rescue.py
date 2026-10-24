"""Imperial Shoulder-Gate and No-Beginning Guard rescue a failed opposed check (contest) too.

Printed: "when you fail a Strength or Constitution save/check/contest against ... pressure, ... add 2 x PB + your key
ability modifier to the roll and re-evaluate." A contest names its pressure in the check spec's ``hazards`` (a save
names it in ``named``), so the rescue must read both. Pressure outside the printed list leaves the failed roll alone.
"""
import pytest
from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_a2_r11_foundations import _fight, _typed_action
from tests.worker2_support import FOE, OWNER, candidate, reload, settle, turn

TYRANT = ('heaven_tyrant_body_v0_2D', 'Tyrant Form Pulse', 'imperial_shoulder_gate', 'forced_movement')
ORIGIN = ('innate_sacred_body_dao_embryo_v0_2B', 'Origin Bell Tone', 'no_beginning_guard', 'gravity_pressure')
OATH = ('iron_oath_skin_v0_2B', 'Guarding Iron', 'stand_fast_witness', 'frightened')


def _contest(tmp_path, family, hazard):
    foundation, pool, gate, _ = family

    def natural(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        face = 5 if actor_id == OWNER else 15
        if reason.startswith('CHECK:'):
            return roll.model_copy(update={'dice': (face,), 'natural_result': face, 'total': face + modifier})
        return roll

    original = DeterministicRollAuthority.raw_d20
    DeterministicRollAuthority.raw_d20 = natural
    try:
        shove = _typed_action('Shove contest', FOE, [{
            'type': 'contest_against', 'actor_check': {'ability': 'STR', 'hazards': [hazard]},
            'target_check': {'ability': 'STR', 'hazards': [hazard]}, 'on_fail': [],
            'on_success': [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}]}], economy='ACTION')
        combat, table, mid = _fight(tmp_path, foundation, pool, held=1, foe_actions=[shove])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Shove contest', target=OWNER).candidate_id,
               choices={'choice:needle.foundation_combat': 'use'})
        engine = reload(tmp_path, mid)
    finally:
        DeterministicRollAuthority.raw_d20 = original
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.source_definition_id.endswith('.' + gate)]
    prone = any(c.condition_id == 'condition:typed.prone' for c in engine.state.actors[OWNER].conditions.values())
    return len(spent), prone


@pytest.mark.parametrize('family', [TYRANT, ORIGIN], ids=['tyrant', 'origin'])
def test_failed_contest_against_printed_pressure_is_rescued(tmp_path, family):
    spent, prone = _contest(tmp_path, family, family[3])
    assert spent == 1 and not prone


@pytest.mark.parametrize('family', [TYRANT, ORIGIN], ids=['tyrant', 'origin'])
def test_failed_contest_against_other_pressure_is_not_rescued(tmp_path, family):
    spent, prone = _contest(tmp_path, family, 'frightened')
    assert spent == 0 and prone


def test_stand_fast_witness_does_not_rescue_failed_contest_with_oath_pressure(tmp_path):
    """Printed rider: Stand Fast Witness rescues a failed SAVE; physical contests stay out of automation."""
    spent, _ = _contest(tmp_path, OATH, OATH[3])
    assert spent == 0
