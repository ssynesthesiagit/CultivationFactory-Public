"""AUTO125, and the AUTO125r1f1 review fixes: the Radiance printed clauses that were still GM text.

Every clause is driven through the real table or the real compiled fight, so a clause that exists in JSON but
never reaches the engine fails here:

  Scour the Unclean       "Failed Save: ... The target also cannot regain HP until the end of your next turn."
                          on the paid 3 CP rider that actually runs, on a real hit, with the save really rolled.
  Radiant Exorcism Palm   "Failure: The target becomes Dawnmarked until the end of your next turn" -- only when the
                          printed Cultivation Check FAILS.
  Heaven-Reading Dawnbeam "Failure: ... apply Dawnmark until the start of your next turn if the target is a creature"
                          -- likewise only on a failed check.
  Heavenly Radiance       "When the transformation ends, gain 1 level of Exhaustion unless you ended the encounter
                          with at least half your maximum CP remaining." The printed 1-minute clock is what ends it,
                          and the reserve excuses it only once the encounter is over, compared without rounding.
  Expose False Form       "the target has Disadvantage on Dexterity (Stealth) checks relying on visual concealment" --
                          a Hide check, not every Stealth check.
"""
import json

import pytest

import combat.ability_checks as ability_checks
import combat.factory_compiler as compiler
from combat import typed_executor
from combat.ext.effect_durations import parse_round, sweep
from combat.ext.forged_exhaustion import level as exhaustion_level
from combat.factory_compiler import RESOURCE_IDS
from combat.typed_executor import bears_mark
from tests.cw2_service_support import add_action, seal
from tests.worker2_flow import reload, settle, turn
from tests.worker2_support import FOE, OWNER, fixture

P = 'tianxia.talent.radiance.'
CP = RESOURCE_IDS['qi']
HEAVENLY_FORM = 'condition:typed.radiance_heavenly_flight'
EXPOSED_CHECK = 'condition:typed.check_against'


def mech(key):
    """The generated authority row, read back out of the rebuilt file the compiler pins."""
    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())['mechanics'][key]


def pick(combat, mid, prefix, *, target=None):
    """The candidate whose published name starts with ``prefix`` (a talent prints several sub-abilities)."""
    engine = combat._load_session(mid).engine
    for row in engine.legal_candidates():
        name = getattr(engine.action_catalog.get(row.source_definition_id), 'display_name', None) or ''
        if (name == prefix or name.startswith(prefix + ':')) and (target is None or row.target_ids == (target,)):
            return row
    raise AssertionError(f'no legal candidate for {prefix!r} (target={target})')


def no_candidate(combat, mid, prefix):
    engine = combat._load_session(mid).engine
    for row in engine.legal_candidates():
        name = getattr(engine.action_catalog.get(row.source_definition_id), 'display_name', None) or ''
        if name == prefix or name.startswith(prefix + ':'):
            return False
    return True


def next_owner_turn(table, mid):
    """Play the round out and hand the owner its next turn (turn() alone is a no-op on its own turn)."""
    from tests.test_r9i_karma_persistence import end_turn

    assert table.state(mid)['menu']['actor_id'] == OWNER, 'the owner must be acting before the round is played out'
    end_turn(table, mid)
    turn(table, mid, OWNER)


def _foe_save_dc(bundle, dc):
    """The foe's own Cultivation Save DC -- the DC a check made against it is resolved from."""
    touched = 0
    for row in bundle['action_catalog']:
        numbers = (((row.get('parameters') or {}).get('typed') or {}).get('numbers') or {})
        if numbers:
            numbers['save_dc'] = dc
            touched += 1
    assert touched, 'the foe bundle carries no compiled numbers to set a Save DC on'
    bundle['actor_template']['armor_class'] = 1  # its own Armor Class, so a real attack really lands
    seal(bundle)


def _owner_cp(bundle, current, maximum):
    for row in bundle['actor_template']['resources']:
        if row['resource_id'] == CP:
            row['initial'], row['maximum'] = current, maximum
    seal(bundle)


# ---------------------------------------------------------------------------------- Scour the Unclean
def _scour_target(bundles, save_fails):
    _foe_save_dc(bundles[2], 16)
    bundles[2]['actor_template']['saving_throws']['WIS'] = -20 if save_fails else 40
    bundles[2]['actor_template']['creature_types'] = ['Undead']
    seal(bundles[2])
    add_action(bundles[0], 'Prepare Dawnmark', [{'type': 'mark', 'mark': 'Dawnmark',
        'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}}])
    add_action(bundles[0], 'Restore HP', [{'type': 'healing', 'applies_to': 'target', 'flat': 1}])


@pytest.mark.parametrize('save_fails', [True, False])
def test_scour_the_unclean_paid_rider_blocks_healing_only_when_the_save_fails(tmp_path, save_fails):
    """"Failed Save: ... The target also cannot regain HP until the end of your next turn."

    The clause rides the printed Wisdom save on the paid 3 CP rider, so it is driven through that rider on a real
    Radiance Strike that really hits; a foe's hopeless Wisdom makes the save fail and a brilliant one make it
    succeed. Nothing but a failure may carry the block."""
    def prepare(bundles):
        _scour_target(bundles, save_fails)

    combat, table, mid = fixture(tmp_path, ['RADIANCE_BASE_STRIKE', 'RADIANCE_TAL_SCOUR_THE_UNCLEAN'],
                                 seed='AUTO125-SCOUR', bundle_transform=prepare)
    row = mech('RADIANCE_TAL_SCOUR_THE_UNCLEAN')['modifier']
    assert [e for e in row['effects'] if e['type'] == 'save'], 'the printed Wisdom save must still be typed'
    heal = [n for e in row['effects'] for n in e.get('on_fail') or [] if n['type'] == 'healing_reduction']
    assert heal, 'the failed save must carry the cannot-regain-HP clause'
    assert not [n for e in row['effects'] for n in e.get('on_success') or [] if n['type'] == 'healing_reduction']
    assert heal[0]['duration'] == {'kind': 'until_end_of_your_next_turn'}, \
        '"until the end of your next turn" is a turn edge the engine ends; nothing here is an expiry token'

    before = reload(tmp_path, mid).state.actors[OWNER].resources[CP]
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'Prepare Dawnmark', target=FOE).candidate_id)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Dawnmark')
    settle(table, mid, pick(combat, mid, 'Radiance Strike + Scour the Unclean', target=FOE).candidate_id)
    owner, foe = reload(tmp_path, mid).state.actors[OWNER], reload(tmp_path, mid).state.actors[FOE]
    assert owner.resources[CP] == before - 3, 'paying 3 CP is what turns the rider on'
    held = [m for m in foe.modifiers.values() if m.target_field == 'healing_reduction']
    assert bool(held) is save_fails, f'a failed save is {save_fails}'
    engine = combat._load_session(mid).engine
    assert typed_executor.stored_healing_reductions(engine, foe, 10) == (0 if save_fails else 10), \
        'the printed clause is a real block on regaining HP, or nothing at all'
    assert foe.maximum_hp - foe.current_hp >= 1
    hp = foe.current_hp
    settle(table, mid, pick(combat, mid, 'Restore HP', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp == hp + (0 if save_fails else 1)


def test_scour_the_uncleans_healing_block_ends_exactly_at_the_end_of_your_next_turn(tmp_path):
    """"until the end of your next turn": still blocked while that turn is played, gone when it ends."""
    def prepare(bundles):
        _scour_target(bundles, True)

    combat, table, mid = fixture(tmp_path, ['RADIANCE_BASE_STRIKE', 'RADIANCE_TAL_SCOUR_THE_UNCLEAN'],
                                 seed='AUTO125-SCOUR-EXPIRY', bundle_transform=prepare)
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'Prepare Dawnmark', target=FOE).candidate_id)
    settle(table, mid, pick(combat, mid, 'Radiance Strike + Scour the Unclean', target=FOE).candidate_id)
    held = [m for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values()
            if m.target_field == 'healing_reduction']
    assert len(held) == 1 and held[0].expires_on.startswith('END_OF_SOURCE_TURN_AT:'), \
        'the counted source-turn clock, so the engine ends it rather than nothing doing'
    assert int(held[0].expires_on.rsplit(':', 1)[1]) == reload(tmp_path, mid).state.actors[OWNER].turns_started + 1, \
        'the end of your NEXT turn, not this one'

    blocked = lambda: bool([m for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values()
                            if m.target_field == 'healing_reduction'])
    next_owner_turn(table, mid)   # the caster's next turn: the block outlives the turn it was put on, as printed
    assert blocked(), 'the block ended with the turn it was put on'
    next_owner_turn(table, mid)   # and it ends with that next turn, so the turn after it is clear
    assert not blocked(), "the end of the caster's next turn ends the block"
    hp = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, pick(combat, mid, 'Restore HP', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp == hp + 1


# ---------------------------------------------------------------------------------- Palm and Dawnbeam
@pytest.mark.parametrize('host_dc', [5, 30])
def test_palm_leaves_the_unrecorded_effect_check_and_scoped_save_with_the_gm(tmp_path, host_dc):
    def prepare(bundles):
        _foe_save_dc(bundles[2], host_dc)
    combat, table, mid = fixture(tmp_path, [P + 'purifying_radiance', P + 'radiant_exorcism_palm'],
        seed='AUTO125-PALM-MANUAL', foe_position={'x': 4, 'y': 7}, bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Radiant Exorcism Palm', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Dawnmark')
    assert not any(c.data.get('rule', {}).get('save_mode') for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.event_type == 'CHECK_ROLLED' for e in engine.events)
    riders = [str(e.payload) for e in engine.events if e.event_type == 'GM_RIDER']
    assert any("afflicting effect's Save DC" in r for r in riders)

@pytest.mark.parametrize('talent', ['heaven_reading_dawnbeam'])
@pytest.mark.parametrize('save_dc,marked', [(30, True), (5, False)])
def test_palm_and_dawnbeam_dawnmark_only_a_failed_cultivation_check(tmp_path, talent, save_dc, marked):
    """"Failure: The target becomes Dawnmarked ..." -- a failed Cultivation Check, not every use.

    The DC the table resolves is the target's own Cultivation Save DC, so the test moves that DC rather than the
    die: hopeless (30) always fails the check, trivial (5) always passes it."""
    def prepare(bundles):
        _foe_save_dc(bundles[2], save_dc)

    prefix = 'Radiant Exorcism Palm' if talent.endswith('palm') else 'Heaven-Reading Dawnbeam'
    combat, table, mid = fixture(tmp_path, [P + 'purifying_radiance', P + talent] if talent.endswith('palm')
                                 else [P + talent], seed='AUTO125-CHECK',
                                 foe_position={'x': 4, 'y': 7},  # the Palm is a Touch: the target is in reach
                                 bundle_transform=prepare)
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, prefix, target=FOE).candidate_id)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Dawnmark') is marked, \
        f'Save DC {save_dc}: a Cultivation Check is {"a failure" if marked else "a success"}'


@pytest.mark.parametrize('talent,prefix', [('radiant_exorcism_palm', 'Radiant Exorcism Palm'),
                                          ('heaven_reading_dawnbeam', 'Heaven-Reading Dawnbeam')])
def test_palm_and_dawnbeam_do_nothing_for_a_character_that_does_not_own_them(tmp_path, talent, prefix):
    """Inert without the talent: such a character has neither action at all, so nothing can mark or check."""
    combat, table, mid = fixture(tmp_path, [P + 'mercy_of_morning'], seed='AUTO125-NOT-OWNED',
                                 foe_position={'x': 4, 'y': 7})
    assert no_candidate(combat, mid, prefix), f'{prefix} must not appear without its talent'
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    foe = reload(tmp_path, mid).state.actors[FOE]
    assert not bears_mark(foe, OWNER, 'Dawnmark')
    assert not any(c.condition_id.startswith('condition:typed.radiance') for c in foe.conditions.values())


# ---------------------------------------------------------------------------------- Heavenly Radiance
def _form_setup(bundles, cp=None):
    add_action(bundles[0], 'The transformation ends', [{'type': 'remove_condition', 'applies_to': 'self',
        'condition': 'radiance_heavenly_flight', 'evidence': 'the transformation ends'}])
    if cp:
        _owner_cp(bundles[0], *cp)


def _end_the_encounter(bundles):
    add_action(bundles[0], 'End the encounter', [{'type': 'damage', 'applies_to': 'target',
        'flat': 400, 'damage_types': ['radiant'], 'evidence': 'a decisive blow'}])
    _foe_save_dc(bundles[2], 16)


def _form_running(combat, mid):
    return any(c.condition_id == HEAVENLY_FORM
               for c in combat._load_session(mid).engine.state.actors[OWNER].conditions.values())


def test_heavenly_radiance_natural_minute_costs_exactly_one_level_of_exhaustion(tmp_path):
    """The printed form lasts one minute: when its own clock runs out the transformation ends and the cost lands.

    This is the real timed expiry (combat/ext/effect_durations.sweep at a turn boundary), not a synthetic removal,
    and it survives a table commit and reload. The foe stands well outside Solar Aura's 20 feet, so this plays out
    the minute instead of winning the fight in six rounds."""
    combat, table, mid = fixture(tmp_path, [P + 'heavenly_radiance'], seed='AUTO125-MINUTE',
                                 foe_position={'x': 12, 'y': 12}, bundle_transform=_form_setup)
    settle(table, mid, pick(combat, mid, 'Heavenly Radiance').candidate_id)
    assert _form_running(combat, mid), 'the form must be running'
    assert exhaustion_level(reload(tmp_path, mid).state.actors[OWNER]) == 0, \
        'the cost lands when the transformation ends, not when it starts'

    for _ in range(13):      # a minute is ten rounds, played out on the clock, not by removing anything
        if not _form_running(combat, mid):
            break
        next_owner_turn(table, mid)
    assert not _form_running(combat, mid), 'the form must have ended on its own clock within a minute of play'
    engine = reload(tmp_path, mid)
    assert exhaustion_level(engine.state.actors[OWNER]) == 1, 'one level of Exhaustion for the ending transformation'
    applied = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED'
               and (e.payload or {}).get('condition_id') == 'condition:typed.exhaustion']
    assert len(applied) == 1, f'the cost is granted once, not once per thing that notices the form end ({len(applied)})'
    assert all('combat/ext/' not in row['summary'] for row in table.events(mid, 0)['events'])


@pytest.mark.parametrize('reserve,maximum,ended,exhausted', [
    (50, 100, True, 0),    # exactly half of the maximum, and the encounter is over: no cost
    (49, 100, True, 1),    # a point under half: the cost
    (50, 101, True, 1),    # half of 101 is 50.5, so 50 is under it (maximum // 2 would call it half)
    (50, 100, False, 1),   # the same reserve is no excuse while the encounter is still going
])
def test_heavenly_radiance_exempts_only_an_encounter_ended_with_the_reserve(tmp_path, reserve, maximum, ended, exhausted):
    """"unless you ended the encounter with at least half your maximum CP remaining": both halves of that are real
    tests -- the encounter has to be over, and the reserve has to be at least half, compared by doubling."""
    def prepare(bundles):
        # The form costs 15 CP, so the sheet starts 15 higher and the creature holds exactly `reserve` in the form.
        _form_setup(bundles, cp=(reserve + 15, maximum))
        if ended:
            _end_the_encounter(bundles)

    combat, table, mid = fixture(tmp_path, [P + 'heavenly_radiance'], seed='AUTO125-EXEMPT',
                                 bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Heavenly Radiance').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[CP] == reserve and owner.resource_maximums[CP] == maximum, \
        f'the test must set the reserve it means ({owner.resources[CP]} of {owner.resource_maximums[CP]})'
    turn(table, mid, OWNER)
    if ended:
        settle(table, mid, pick(combat, mid, 'End the encounter', target=FOE).candidate_id)
        assert reload(tmp_path, mid).state.terminal_result is not None, 'the encounter must really be over'
    else:
        settle(table, mid, pick(combat, mid, 'The transformation ends', target=OWNER).candidate_id)
    engine = combat._load_session(mid).engine
    holder = engine.state.actors[OWNER]
    if ended:
        form = next(c for c in holder.conditions.values() if c.condition_id == HEAVENLY_FORM)
        receipt = holder.turn_flags['_round_radiance_encounter_end']
        assert receipt == {'instance': form.instance_id, 'current': reserve, 'maximum': maximum}
        # Finished tables cannot advance turns. Advance only the reloaded clock
        # to the form's due boundary and use the normal expiry lifecycle seam.
        engine.state.round_number, engine.state.current_slot_index = parse_round(form.expires_on)
        holder.resources[CP] = 0 if exhausted == 0 else maximum
        sweep(engine, holder, 'TEST_POST_ENCOUNTER_CLOCK')
    assert not any(c.condition_id == HEAVENLY_FORM for c in holder.conditions.values())
    assert exhaustion_level(holder) == exhausted, \
        f'{reserve} of {maximum} maximum CP, the encounter over: {ended}'
    if not ended:
        assert exhaustion_level(reload(tmp_path, mid).state.actors[OWNER]) == exhausted


def test_heavenly_radiance_leaves_no_exhaustion_when_the_form_never_ran(tmp_path):
    """The cost belongs to ending the transformation; nothing else on this character produces Exhaustion."""
    combat, table, mid = fixture(tmp_path, [P + 'heavenly_radiance'], seed='AUTO125-NOFORM',
                                 bundle_transform=lambda b: _form_setup(b))
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'The transformation ends', target=OWNER).candidate_id)
    assert exhaustion_level(reload(tmp_path, mid).state.actors[OWNER]) == 0


def test_heavenly_radiance_costs_exhaustion_while_the_encounter_is_still_going(tmp_path):
    """A healthy Cultivation Point pool is not an excuse by itself: the printed words are about ending the encounter."""
    combat, table, mid = fixture(tmp_path, [P + 'heavenly_radiance'], seed='AUTO125-MIDFIGHT',
                                 bundle_transform=_form_setup)
    settle(table, mid, pick(combat, mid, 'Heavenly Radiance').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert 2 * owner.resources[CP] >= owner.resource_maximums[CP], 'the test must hold at least half the maximum'
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'The transformation ends', target=OWNER).candidate_id)
    assert not any(c.condition_id == HEAVENLY_FORM for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    assert exhaustion_level(reload(tmp_path, mid).state.actors[OWNER]) == 1


# ---------------------------------------------------------------------------------- Expose False Form
def test_expose_penalises_only_stealth_checks_that_rely_on_being_unseen(tmp_path):
    """"Dexterity (Stealth) checks relying on visual concealment": a Hide check is one; a Stealth check made for
    any other reason is not, and the same condition says so by which check reads it."""
    combat, table, mid = fixture(tmp_path, [P + 'expose_false_form'], seed='AUTO125-EXPOSE', bundle_transform=lambda b: (
        add_action(b[0], 'Prepare Dawnmark', [{'type': 'mark', 'mark': 'Dawnmark', 'applies_to': 'target',
                                              'duration': {'kind': 'until_start_of_your_next_turn'}}])))
    turn(table, mid, OWNER)
    settle(table, mid, pick(combat, mid, 'Prepare Dawnmark', target=FOE).candidate_id,
           {'choice:needle.radiance_expose': 'pay'})
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    exposed = [c for c in foe.conditions.values() if c.condition_id == EXPOSED_CHECK]
    assert len(exposed) == 1, 'paying 1 CP exposes the marked creature'
    assert exposed[0].data['rule']['check_against']['against'] == [ability_checks.VISUAL_CONCEALMENT]
    assert ability_checks.hide_check_mode(engine, foe) == 'DISADVANTAGE', \
        'a Hide check relies on being unseen, so the printed penalty reaches it'
    assert typed_executor.check_mode(foe, 'DEX', 'Stealth', engine=engine) == 'NORMAL', \
        'a Stealth check made for any other reason is not one relying on visual concealment'
    assert typed_executor.check_mode(foe, 'DEX', 'Acrobatics', engine=engine,
        hazards=(ability_checks.VISUAL_CONCEALMENT,)) == 'NORMAL'


@pytest.mark.parametrize('visual,mode', [(True, 'DISADVANTAGE'), (False, 'NORMAL')])
def test_expose_scopes_actual_table_checks_and_survives_reload(tmp_path, visual, mode):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare Dawnmark', [{'type': 'mark', 'mark': 'Dawnmark',
            'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}}])
        add_action(bundles[2], 'Stealth contest', [{'type': 'contest_against',
            'actor_check': {'kind': 'check', 'ability': 'DEX', 'skill': 'Stealth',
                            'hazards': ['visual_concealment'] if visual else ['sound']},
            'target_check': {'kind': 'check', 'ability': 'WIS', 'skill': 'Perception'},
            'on_success': [], 'on_fail': []}])
    combat, table, mid = fixture(tmp_path, [P + 'expose_false_form'], seed='AUTO125-VISUAL',
                                 bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Prepare Dawnmark', target=FOE).candidate_id,
           {'choice:needle.radiance_expose': 'pay'})
    turn(table, mid, FOE)
    settle(table, mid, pick(combat, mid, 'Stealth contest', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and e.payload.get('roll_kind') == 'opposed_check']
    assert checks[-1].payload['actor']['mode'] == mode
