"""Shelter the Weak's player-facing reminder must be readable without engine vocabulary.

Checklist 13: a player or GM who knows basic D&D has to be able to read the
correction and act on it. The printed owner rule (TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION)
says each chosen ally "gains Resistance to the first instance of damage it takes",
so the correction is written in the same ordinary terms.

The reminder is a locked-engine disclosure, not a repair: the native next-resistance
consumer is recorded as taking the protection before the ally's final immunity and
reductions, and treats separate damage parts separately. This lane states both in
plain language instead of leaving the GM with "packet" and "adjudicate".
"""
from tests.auto_worker1_support import ALLY, RIGHT, act, fight, reload, settle, turn
from tests.test_a2_guardian import ADAMANT, shelter_mods

# Engine vocabulary a newcomer cannot act on. The r2 review named these two words.
JARGON = ('packet', 'adjudicat')


def shelter_line(tmp_path):
    """Apply Shelter once through the real service path, then cold-reload the fight."""
    combat, table, match = fight(tmp_path, [ADAMANT], left_kit={'items': []}, right_kit={'items': []},
                                 reaction_ask=False, ally={}, prepare_target='SELF')
    # The incarnation itself commits through CombatService session execution.
    settle(lambda answers: act(table, match, 'Adamant Guardian Incarnation', answers))
    turn(table, match, RIGHT)
    combat.set_controller_mode(match, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    result = None
    while table.state(match)['menu']['actor_id'] == RIGHT:
        result = table.auto_step(match, table.state(match)['last_sequence'], [])
        if result['status'] == 'REACTION_REQUIRED':
            break
        assert result['status'] == 'COMMITTED', result
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['reaction'] == 'Adamant Guardian: Shelter the Weak'
    answer = {**prompt['context'], 'selection': 'USE',
              'option_ids': [prompt['choice']['options'][0]['id']]}
    result = table.auto_step(match, table.state(match)['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    # Cold reload: a fresh CombatService must rebuild the fight, replay it and still verify.
    fresh = reload(combat, match)
    assert len(shelter_mods(fresh.state.actors[ALLY])) == 13
    assert combat._load_session(match).verify()['status'] == 'PASS'
    # The line below is the rendered history entry the player and GM actually read.
    lines = [str(row.get('summary') or '') for row in table.events(match, 0)['events']
             if 'Shelter the Weak' in str(row.get('summary') or '')]
    assert len(lines) == 1, lines
    return lines[0]


def test_shelter_reminder_reads_as_ordinary_combat_language(tmp_path):
    line = shelter_line(tmp_path)
    # The printed promise survives the rewrite.
    assert 'Resistance to the first instance of damage it takes' in line, line
    # The zero-damage correction is stated as an instruction, in the GM's terms.
    assert 'If that attack dealt no damage, put the protection back' in line, line
    # The split-hit correction tells the GM what to do with each part.
    assert 'apply Resistance to every one of those parts' in line, line
    assert 'then remove the protection' in line, line
    # No unexplained engine vocabulary survives anywhere in the player-facing line.
    for word in JARGON:
        assert word not in line.lower(), (word, line)