"""AUTO137: Yin's header lines are no longer shown to the GM as rule reminders.

Seven Yin rows carried a rider that only restated the printed header ("Cost: 3 CP",
"Duration: 1 minute. ... Use Limit: Once per Long Rest."). The table already charges that
cost and honours that duration and use limit from typed data, so those lines were noise
shown to the GM. This drops them, keeps every line that is still the GM's work, and proves
at table level that the printed cost is still actually paid after the reminder is gone.

AUTO137r1: dropping the reminder must also leave the ability's *effects* alone. Supplying
riders only still marks a mechanic reviewed_final, and a reviewed_final mechanic is what its
reviewer wrote: the builder's duplicate-removal pass
(``factory_authoring.typed_structure.drop_restated_parser_rows``) deliberately skips it. The
Quiet After Speech row therefore kept the parser's restated second copy of a disadvantage
that a typed row already states, and that copy carried no duration of its own, so it would
have outlived the correctly timed one. The reviewed entry now pins the effects it keeps.
"""

from __future__ import annotations

import json
from pathlib import Path

import combat.factory_compiler as compiler
from tests.worker2_support import OWNER, candidate, fixture, settle

# The rows whose redundant header line was dropped, with the cost the printed text demands.
DROPPED = {
    'TAL_YIN_BLACK_MOON_READS_THE_FLAME': None,
    'TAL_YIN_MOONLIT_PRESERVATION': 2,
    'TAL_YIN_NO_DAWN_REPEATS_ITSELF': 8,
    'TAL_YIN_SEAL_THE_REPETITION': 3,
    'TAL_YIN_SOVEREIGN_YIN_INCARNATION': 15,
    'TAL_YIN_THE_QUIET_AFTER_SPEECH': 1,
    'TAL_YIN_THE_STILL_CORPSE_REMEMBERS': 10,
}

# This lane's reviewed overrides; each is keyed by ability id and may supply effects.
REVIEWED_OVERRIDES = (Path(compiler.TYPED_AUTHORITY).parent
                      / 'typed_mechanics/reviewed_final.d/auto137_yin_riders.json')


def _authority() -> dict:
    return json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding='utf-8'))['mechanics']


def _overrides() -> dict:
    return json.loads(REVIEWED_OVERRIDES.read_text(encoding='utf-8'))['mechanics']


def _is_header_reminder(line: str) -> bool:
    lowered = line.lower().lstrip()
    return (lowered.startswith(('cost:', 'time:'))
            or (lowered.startswith('duration:') and 'use limit' in lowered))


def test_no_yin_row_shows_the_table_its_own_printed_header_as_a_gm_reminder():
    """The header the table already runs must not also reach the GM as an untyped line."""
    mechanics = _authority()
    offenders = [(key, line) for key in DROPPED for line in mechanics[key]['riders'] if _is_header_reminder(line)]
    assert offenders == []


def test_the_printed_cost_duration_and_use_limit_are_still_typed_for_each_dropped_row():
    """Dropping the reminder must not drop the rule: the typed header fields still carry it."""
    mechanics = _authority()
    for key, cost in DROPPED.items():
        # A row printing "Cost: None" legitimately carries an empty cost list.
        expected = [] if cost is None else [[{'resource': 'cp', 'amount': cost, 'amount_formula': None}]]
        assert mechanics[key]['cost'] == expected, key
    sovereign = mechanics['TAL_YIN_SOVEREIGN_YIN_INCARNATION']
    assert sovereign['duration'] == {'kind': 'minutes', 'amount': 1, 'concentration': False}
    assert sovereign['use_limit'] == 'once_per_long_rest'


def test_the_lines_still_left_to_the_gm_are_the_real_untyped_ones():
    """Only genuinely untyped work stays; dropping a header must not empty a row that needs the GM."""
    mechanics = _authority()
    assert mechanics['TAL_YIN_NO_DAWN_REPEATS_ITSELF']['riders'] == [
        'On a failed save, the repeated ability fails to activate, but the target does not spend CP, '
        'spell slots, charges, or limited uses for the failed attempt. The action used to attempt it '
        'is still spent.',
        'On a successful save, the ability functions normally, but the target gains a Waning Mark after '
        'it resolves and cannot benefit from Advantage until the start of its next turn.',
        'This does not prevent basic weapon attacks unless the attack is part of a named technique or '
        'special action.',
    ]
    assert mechanics['TAL_YIN_SEAL_THE_REPETITION']['riders'] == [
        'On a failed save, the target cannot use the same named spell, sphere talent, forged technique, '
        'monster action, or cultivation ability again until the end of its next turn.',
        'On a successful save, the target can repeat the ability, but if it does so before the end of '
        'its next turn, it gains a Waning Mark immediately after the repeated ability resolves.',
    ]
    assert mechanics['TAL_YIN_SOVEREIGN_YIN_INCARNATION']['riders'][0] == 'Your Mark Limit doubles.'


def test_the_printed_cp_cost_is_still_paid_by_the_table(tmp_path):
    """Sovereign Yin Incarnation prints "Cost: 15 CP"; the table charges exactly that with no
    reminder line to back it up, so removing the line changed no gameplay."""
    combat, table, mid = fixture(tmp_path, ['TAL_YIN_SOVEREIGN_YIN_INCARNATION'], cl=15, seed='YIN-AUTO137')
    before = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Sovereign Yin Incarnation', target=None).candidate_id)
    after = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    assert (before, before - after) == (100, 15)


def test_a_rider_only_cleanup_never_changed_what_an_ability_does():
    """Every row this lane marked reviewed keeps exactly the effects its override pins.

    Supplying riders alone still marks a mechanic reviewed_final, and a reviewed_final
    mechanic is what its reviewer wrote: the builder's duplicate-removal pass
    (``drop_restated_parser_rows``) skips it, so a parser row that a typed row already states
    survives and runs a second time. Where that could happen the override must name the
    effects it keeps, and the generated record must match it row for row.
    """
    mechanics, overrides = _authority(), _overrides()
    pinned = {key: final['effects'] for key, final in overrides.items() if 'effects' in final}
    assert 'TAL_YIN_THE_QUIET_AFTER_SPEECH' in pinned, 'the one row whose parser duplicate came back must pin its effects'
    from combat.ext.effect_durations import kind_of

    def lifetimes(rows):  # the authority anchors each duration dict; the override keeps the plain name
        return [{**row, 'duration': kind_of(row['duration'])} if 'duration' in row else row for row in rows]
    for key, effects in pinned.items():
        assert lifetimes(mechanics[key]['effects']) == lifetimes(effects), key


def test_the_quiet_after_speech_keeps_one_disadvantage_that_ends_at_the_start_of_the_targets_next_turn():
    """The printed rule is a single disadvantage, for the start of the target's next turn.

    The restated parser copy that came back with the header cleanup carried no duration of
    its own, so ``typed_executor`` gave it the ``END_OF_HOLDER_NEXT_TURN`` fallback: a second
    disadvantage condition that outlived the correctly timed one, and whose check label
    still quoted the unautomated "more than 30 feet away" rider as if the table ran it.
    """
    effects = _authority()['TAL_YIN_THE_QUIET_AFTER_SPEECH']['effects']
    disadvantages = [effect for effect in effects if effect['type'] == 'disadvantage']
    assert len(disadvantages) == 1, 'the disadvantage the parser restated must not run beside the typed one'
    from combat.ext.effect_durations import kind_of
    assert kind_of(disadvantages[0]['duration']) == 'until_start_of_next_turn'
    assert disadvantages[0]['on'] == 'Charisma checks relying on speech'
    # The mark is still spent and nothing else was added or lost in the cleanup.
    assert [effect['type'] for effect in effects] == ['disadvantage', 'spend_mark']


def test_no_yin_row_left_reviewed_carries_a_parser_copy_of_a_row_a_typed_row_already_states():
    """Marking a row reviewed skips the builder's duplicate pass, so re-check every row.

    A second row of a type another row already states is the shape the pass removes: run
    twice, each with its own condition and its own expiry.
    """
    mechanics = _authority()
    for key in {*DROPPED, *_overrides()}:
        effects = mechanics[key]['effects']
        types = [effect['type'] for effect in effects]
        assert not [name for name in set(types) if types.count(name) > 1], key
        assert not [effect for effect in effects if effect.get('origin') == 'parser'], key