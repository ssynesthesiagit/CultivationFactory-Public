"""Review round 1 (A2BLACKSMIr0 findings 1 and 2).

Finding 1: a Steady Hammer Expertise selection is settled by the check that actually
rolled with the Advantage, for either side of an opposed check. The selection is matched
by the identity recorded when it was made -- subject skill, source and intent -- plus the
roll's own applied mode, because check producers spell out different things in a roll
reason and an opposed check's reason carries the action id, not a skill.

Finding 2: a Blacksmith choice names the action that asked and the creature it lands on,
on the chooser's own turn and on another creature's.

Every case drives the real CombatService/TabletopService, answers the choice through the
table transport and cold-reloads the saved fight; only attack d20s are controlled.
"""
import pytest
from combat.ext.blacksmith_forge import held_condition
from tests.worker2_support import fixture, turn, reload, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import seal, press
from tests.test_a2_blacksmith_second_pass import setup, declare, die, execute

QUENCH = 'tianxia.talent.blacksmith.quench_against_the_grain'
STEADY = 'tianxia.talent.blacksmith.steady_hammer_breathing'
USED = 'condition:typed.blacksmith_steady_expertise_used'
STEADY_CHOICE = 'choice:needle.blacksmith_steady'
QUENCH_CHOICE = 'choice:needle.blacksmith_quench'

SMITH = {'kind': 'check', 'ability': 'INT', 'skill': "Smith's Tools"}
OTHER = {'kind': 'check', 'ability': 'WIS', 'skill': 'Perception'}


def contests(rank=2):
    """Opposed checks that put the smith's own tools check on either side of the contest.

    ``contest_against`` is the engine's ordinary opposed-check producer, so both rows go
    through the same resolve_opposed_check a printed contest does.
    """
    def build(bundles):
        setup(rank=rank)(bundles)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        ally = next(b for b in bundles if b['actor_id'] == ALLY)
        seal(owner, 'Smith contest acting',
             [{'type': 'contest_against', 'applies_to': 'target', 'harmful': True,
               'actor_check': dict(SMITH), 'target_check': dict(OTHER)}], target='ANY_CREATURE')
        seal(ally, 'Smith contest defending',
             [{'type': 'contest_against', 'applies_to': 'target', 'harmful': True,
               'actor_check': dict(OTHER), 'target_check': dict(SMITH)}], target='ANY_CREATURE')
    return build


def names(combat, mid):
    return {a.entity_id: a.display_name for a in combat._load_session(mid).engine.state.actors.values()}


def distinct_names(combat, mid):
    """The fixture's creature names, asserted to actually tell the creatures apart.

    An unnamed sheet compiles to one shared placeholder for every actor, so a name
    comparison passes even when the identities are reversed. Any test that asks which
    creature a prompt names must start from names that differ.
    """
    who = names(combat, mid)
    picked = [who[OWNER], who[ALLY], who[FOE]]
    assert len(set(picked)) == 3, f"fixture creatures are not distinguishable: {picked}"
    return who


def prompt_for(prompts, reaction_source_id):
    """The rendered table prompt for one choice, or None when it was never raised."""
    for prompt in prompts or ():
        if prompt['context']['reaction_source_id'] == reaction_source_id:
            return prompt
    return None


def last_check_rolls(engine, contest):
    """CHECK_ROLLED receipts for one contested action."""
    return [x for x in engine.events if x.event_type == 'CHECK_ROLLED'
            and contest.replace(' ', '_') in x.source_definition_id]


def smith_side(roll_event):
    """Whichever side of the opposed check was rolled by the smith."""
    return next((r for r in (roll_event.payload.get('actor'), roll_event.payload.get('target'))
                 if r and r['actor_id'] == OWNER), None)


# --------------------------------------------------------------------------------------
# Finding 1 -- the selection is spent by the die that carried it, on either side.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('contest,target,turn_actor', [
    ('Smith contest acting', FOE, None),
    ('Smith contest defending', OWNER, ALLY),
])
def test_opposed_check_spends_expertise_on_either_side(tmp_path, contest, target, turn_actor):
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests())
    if turn_actor:
        turn(table, mid, turn_actor)
    prompts = press(combat, table, mid, contest, target, picks={STEADY_CHOICE: ['advantage']})

    # The choice is genuinely put, on the side that owns the tools check.
    prompt = prompt_for(prompts, STEADY_CHOICE)
    assert prompt is not None and prompt['reactor']

    e = reload(tmp_path, mid)
    assert held_condition(e.state.actors[OWNER], USED) is not None
    rolled = last_check_rolls(e, contest)
    assert rolled, 'the opposed check must have produced a CHECK_ROLLED receipt'
    # An opposed check's reason names the action, never a skill: the trap this fixes.
    assert rolled[-1].payload['actor']['reason'] == f"CHECK:{rolled[-1].source_definition_id}"
    side = smith_side(rolled[-1])
    assert side is not None and side['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('contest,target,turn_actor', [
    ('Smith contest acting', FOE, None),
    ('Smith contest defending', OWNER, ALLY),
])
def test_opposed_check_expertise_is_not_offered_twice(tmp_path, contest, target, turn_actor):
    """The printed benefit is once per short rest, so the second contest offers nothing."""
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests())
    if turn_actor:
        turn(table, mid, turn_actor)
    press(combat, table, mid, contest, target, picks={STEADY_CHOICE: ['advantage']})
    assert held_condition(reload(tmp_path, mid).state.actors[OWNER], USED) is not None

    if turn_actor:
        turn(table, mid, turn_actor)
    second = press(combat, table, mid, contest, target, picks={STEADY_CHOICE: ['advantage']})

    assert prompt_for(second, STEADY_CHOICE) is None
    e = reload(tmp_path, mid)
    side = smith_side(last_check_rolls(e, contest)[-1])
    assert side is not None and side['mode'] == 'NORMAL'


def test_opposed_check_decline_spends_nothing(tmp_path):
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests())
    press(combat, table, mid, 'Smith contest acting', FOE, picks={STEADY_CHOICE: None})
    e = reload(tmp_path, mid)
    assert held_condition(e.state.actors[OWNER], USED) is None
    side = smith_side(last_check_rolls(e, 'Smith contest acting')[-1])
    assert side is not None and side['mode'] == 'NORMAL'


@pytest.mark.parametrize('opposed', [False, True], ids=['ordinary', 'opposed'])
def test_canceled_expertise_advantage_spends_use_after_completed_check(tmp_path, monkeypatch, opposed):
    """A chosen Advantage cancels existing Disadvantage but still consumes its use."""
    from combat import ext

    build = contests() if opposed else setup(rank=2)
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=build)
    monkeypatch.setitem(ext._HOOKS, 'skill_check_mode', [*ext._HOOKS.get('skill_check_mode', []),
        lambda ctx, actor, ability, skill: 'DISADVANTAGE'])

    if opposed:
        action, target = 'Smith contest acting', FOE
    else:
        action, target = 'Smith check', OWNER
    first = press(combat, table, mid, action, target, picks={STEADY_CHOICE: ['advantage']})
    assert prompt_for(first, STEADY_CHOICE) is not None
    e = reload(tmp_path, mid)
    assert held_condition(e.state.actors[OWNER], USED) is not None
    first_roll = ([smith_side(last_check_rolls(e, action)[-1])] if opposed else
                  [x.payload['actor'] for x in e.events if x.event_type == 'CHECK_ROLLED'][-1:])[0]
    assert first_roll is not None and first_roll['mode'] == 'NORMAL'

    second = press(combat, table, mid, action, target, picks={STEADY_CHOICE: ['advantage']})
    assert prompt_for(second, STEADY_CHOICE) is None
    e = reload(tmp_path, mid)
    second_roll = ([smith_side(last_check_rolls(e, action)[-1])] if opposed else
                   [x.payload['actor'] for x in e.events if x.event_type == 'CHECK_ROLLED'][-1:])[0]
    assert second_roll is not None and second_roll['mode'] == 'DISADVANTAGE'


def test_unrelated_contested_check_never_offers_expertise(tmp_path):
    """A check that is not the smith's own tools offers nothing and consumes nothing."""
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests())
    prompts = press(combat, table, mid, 'Other check', FOE)
    assert prompt_for(prompts, STEADY_CHOICE) is None
    assert held_condition(reload(tmp_path, mid).state.actors[OWNER], USED) is None


# --------------------------------------------------------------------------------------
# Finding 2 -- the rendered table prompt names the action and the creature.
# --------------------------------------------------------------------------------------

def test_quench_weapon_prompt_names_attacker_and_target(monkeypatch, tmp_path):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(3), named=True)
    declare(combat, table, mid, 'weapon')
    prompts = press(combat, table, mid, 'Sword', FOE, picks={QUENCH_CHOICE: ['quench']})

    prompt = prompt_for(prompts, QUENCH_CHOICE)
    who = distinct_names(combat, mid)
    assert prompt is not None
    assert prompt['action'] == 'Sword'
    assert prompt['trigger_actor'] == who[OWNER]
    assert prompt['affected'] == who[FOE]
    assert prompt['by'] == who[FOE]
    # The question a player actually reads names the smith and the creature it concerns.
    assert who[OWNER] in prompt['moment'] and who[FOE] in prompt['moment']


def test_quench_armor_prompt_names_the_striker_and_the_wearer(monkeypatch, tmp_path):
    """Answered on another creature's turn: the striker triggered it, the smith is affected.

    FOE strikes OWNER here, so OWNER is the creature the correction concerns and FOE is
    the one whose action asked for it. Naming the wearer as the striker would read as if
    the smith had struck itself.
    """
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(6), named=True)
    declare(combat, table, mid, 'armor or shield')
    turn(table, mid, FOE)
    prompts = press(combat, table, mid, 'Sword', OWNER, picks={QUENCH_CHOICE: ['quench']})

    prompt = prompt_for(prompts, QUENCH_CHOICE)
    who = distinct_names(combat, mid)
    assert prompt is not None
    assert prompt['action'] == 'Sword'
    assert prompt['trigger_actor'] == who[FOE]
    assert prompt['affected'] == who[OWNER]
    assert prompt['reactor'] == who[OWNER]
    assert who[FOE] in prompt['moment'] and who[OWNER] in prompt['moment']


def test_quench_ai_answers_the_same_way_through_direct_session_execution(monkeypatch, tmp_path):
    """A computer-controlled smith, driven by a direct session intent, still gets the correction.

    Uses the real session execute_intent path rather than a table submission, so the AI's
    own decision is exercised end to end and cold-reloaded.
    """
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(3), ask=False)
    declare(combat, table, mid, 'weapon')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    execute(combat, mid, 'Sword', FOE)
    e = reload(tmp_path, mid)
    assert e.state.actors[FOE].current_hp < before
    assert [x for x in e.events if x.source_definition_id == QUENCH and x.event_type == 'REACTION_RESOLVED']


def test_steady_prompt_names_the_checking_creature(tmp_path):
    """On the smith's own turn it is both: the smith's action asked and the smith is checked."""
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests(), named=True)
    prompts = press(combat, table, mid, 'Smith contest acting', FOE, picks={STEADY_CHOICE: ['advantage']})

    prompt = prompt_for(prompts, STEADY_CHOICE)
    who = distinct_names(combat, mid)
    assert prompt is not None
    assert prompt['action'] == 'Smith contest acting'
    assert prompt['trigger_actor'] == who[OWNER]
    assert prompt['affected'] == who[OWNER]
    assert prompt['reactor'] == who[OWNER]
    # The opponent is neither the creature acting nor the creature checked.
    assert who[FOE] not in (prompt['trigger_actor'], prompt['affected'])


def test_steady_prompt_names_the_defender_on_another_creatures_turn(tmp_path):
    """ALLY's contest asked for the check; the smith's own sheet is the creature checked.

    This is the defending side of an opposed check, so the check subject is OWNER while
    the action belongs to ALLY. Reading the action's owner as the actor is what keeps the
    table from telling the smith it used ALLY's contest on itself.
    """
    combat, table, mid = fixture(tmp_path, [STEADY], bundle_transform=contests(), named=True)
    turn(table, mid, ALLY)
    prompts = press(combat, table, mid, 'Smith contest defending', OWNER,
                    picks={STEADY_CHOICE: ['advantage']})

    prompt = prompt_for(prompts, STEADY_CHOICE)
    who = distinct_names(combat, mid)
    assert prompt is not None
    assert prompt['action'] == 'Smith contest defending'
    assert prompt['trigger_actor'] == who[ALLY]
    assert prompt['affected'] == who[OWNER]
    assert prompt['reactor'] == who[OWNER]
    # The rendered question says who acted and who is checked, as two different creatures.
    assert who[ALLY] in prompt['moment'] and who[OWNER] in prompt['moment']
