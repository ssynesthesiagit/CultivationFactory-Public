"""Printed Hidden Eye mechanics through service execute_intent, commit and cold replay.

Scenario actions are sealed in genesis; no live engine state/method is patched.
"""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from combat import senses, stealth
from combat.ext.eye_common import FOCUS
from combat.ext.eye_coordination import COOP_STEALTH_TAG
from combat.ext.mind_hidden_eye import ANALYZED, PATIENT_EYE_ANALYZED
from combat.ext.riders14_research import KNOWN
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload

BASE = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
LURKER = "TAL_THE_HIDDEN_EYE_LURKER"
WIND = "TAL_THE_HIDDEN_EYE_WIND_READER"
TRUE = "TAL_THE_HIDDEN_EYE_TRUE_SIGHT"
FOLK = "TAL_THE_HIDDEN_EYE_FOLKLORIST"
COOP = "TAL_THE_HIDDEN_EYE_COOPERATIVE_STEALTH"
SWEEP = "TAL_THE_HIDDEN_EYE_THOUSAND_LANTERN_SWEEP"
EXAM = "TAL_THE_HIDDEN_EYE_PHYSICAL_EXAMINATION"
PATIENT = "TAL_THE_HIDDEN_EYE_HEAVEN_KEEPS_NO_SECRET_FROM_THE_PATIENT_EYE"
PICK = "choice:needle.eye_lurker"


def seal_action(bundle, label, effects, *, costs=(), numbers=None, target_kind='SELF'):
    row = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
    row.update(source_definition_id=f"test:eye.{bundle['actor_id']}.{label}", display_name=label,
               economy='NONE', target_kind=target_kind, costs=list(costs), range_ft=60 if target_kind != 'SELF' else None)
    row['parameters'] = {'typed': {'effects': effects, 'numbers': numbers or {'cl': 15, 'pb': 5},
                                  'duration': {'kind': 'instant'}, 'riders': []}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(row['source_definition_id'])


def seal(bundles):
    for b in bundles:
        # Actual Hide is allowed by an actual Invisible condition, with a known
        # large skill bonus; its total is rolled/evented, never assigned afterward.
        seal_action(b, 'Conceal', [{'type': 'condition', 'condition': 'invisible', 'applies_to': 'self',
                                 'expires_on': 'UNTIL_REMOVED'}, {'type': 'hide', 'bonus': 30}])
        seal_action(b, 'Forced Conceal', [{'type': 'condition', 'condition': 'hidden',
            'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}, {'type': 'condition',
            'condition': 'invisible', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}])
        seal_action(b, 'Spend Focus', [], costs=[(FOCUS, 1)])
        seal_action(b, 'Search Again', [{'type': 'search', 'bonus': 0}])
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def do(combat, table, mid, name, *, target=None, **kwargs):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, **kwargs)


def do_ai(combat, table, mid, name, actor=OWNER):
    """One action taken by the computer-controlled ``actor``; every other creature stays manual."""
    cid = candidate(combat, mid, name).candidate_id
    real = combat.controller
    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = SelectedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    try:
        return settle(table, mid, cid, auto=True)
    finally:
        combat.controller = real
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')


def checks(engine):
    return [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == FOE
            and e.payload.get('check') == 'Perception']


@pytest.mark.parametrize('owned,accept,ai,focused', [
    (True, True, False, True), (True, False, False, True), (True, True, True, True),
    (False, True, False, True), (True, True, False, False),
], ids=['human-use', 'human-decline', 'computer-use', 'unowned', 'no-focus'])
def test_lurker_optional_reaction_and_focus_are_paid_only_when_used(tmp_path, owned, accept, ai, focused):
    combat, table, mid = fixture(tmp_path, [BASE, *([LURKER] if owned else [])], bundle_transform=seal)
    do(combat, table, mid, 'Conceal')
    if not focused:
        do(combat, table, mid, 'Spend Focus')
    before = reload(tmp_path, mid).state.actors[OWNER].resources[FOCUS]
    turn(table, mid, FOE)
    if ai:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = do(combat, table, mid, 'Search Again', picks={PICK: 'lurker' if accept else None})
    e = reload(tmp_path, mid)
    used = owned and accept and focused
    assert checks(e)[-1].payload['actor']['mode'] == ('DISADVANTAGE' if used else 'NORMAL')
    assert e.state.actors[OWNER].resources[FOCUS] == before - int(used)
    assert e.state.actors[OWNER].reaction_available is (not used)
    assert e.state.actors[ALLY].resources[FOCUS] == 1 and e.state.actors[ALLY].reaction_available
    assert stealth.hidden(e.state.actors[OWNER])
    assert len([p for p in prompts if p['context']['reaction_source_id'] == PICK]) == int(owned and focused and not ai)
    if prompts:
        assert 'Martial Focus' in str(prompts) and 'Reaction' in str(prompts)
    # Another check before the owner's next turn cannot spend a second Reaction.
    do(combat, table, mid, 'Search Again', picks={PICK: 'lurker'})
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[FOCUS] == before - int(owned and focused and (accept or not used))
    if used:
        assert checks(e)[-1].payload['actor']['mode'] == 'NORMAL'


def test_lurker_single_check_sweep_uses_target_specific_view_and_preserves_other_targets(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, LURKER], foe_sheet=sheet([BASE, SWEEP], cl=15),
                                 bundle_transform=seal)
    do(combat, table, mid, 'Conceal')
    turn(table, mid, ALLY)
    do(combat, table, mid, 'Conceal')
    turn(table, mid, FOE)
    prompts = do(combat, table, mid, 'Thousand-Lantern Sweep', picks={PICK: 'lurker'})
    e = reload(tmp_path, mid)
    rows = [r for r in checks(e) if r.payload.get('same_search')]
    assert {r.target_ids[0]: r.payload['actor']['mode'] for r in rows} == {OWNER: 'DISADVANTAGE', ALLY: 'NORMAL'}
    assert len({tuple(r.payload['actor']['dice']) for r in rows}) == 1
    assert len([p for p in prompts if p['context']['reaction_source_id'] == PICK]) == 1
    assert e.state.actors[OWNER].resources[FOCUS] == 0 and not e.state.actors[OWNER].reaction_available


def test_lurker_is_not_offered_when_a_sense_finds_without_a_roll(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, LURKER], foe_sheet=sheet([BASE, TRUE], cl=15), bundle_transform=seal)
    do(combat, table, mid, 'Forced Conceal')
    turn(table, mid, FOE)
    assert not do(combat, table, mid, 'Search Again')
    e = reload(tmp_path, mid)
    assert checks(e)[-1].payload.get('by_sense')
    assert not stealth.hidden(e.state.actors[OWNER])
    assert e.state.actors[OWNER].resources[FOCUS] == 1 and e.state.actors[OWNER].reaction_available


def wind_setup(*, poison=False):
    def transform(bundles):
        owner = bundles[0]
        # A real Wind Sign Shroud supplies the existing one-shot weather penalty.
        seal_action(owner, 'Wind Shroud', [{'type': 'weather_cloud_shroud', 'sign': 'wind', 'persistent': True}],
                    numbers={'cl': 15, 'pb': 5, 'save_dc': -100}, target_kind='ANY_CREATURE')
        if poison:
            seal_action(owner, 'Poison', [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'self',
                                        'expires_on': 'UNTIL_REMOVED'}])
        seal_action(owner, 'Advantage', [{'type': 'advantage', 'applies_to': 'self', 'on': 'next attack roll'}])
        seal_action(owner, 'Spend Focus', [], costs=[(FOCUS, 1)])
        # This sealed ranged weapon uses the shipped typed attack resolver.
        action = copy.deepcopy(next(a for a in owner['action_catalog'] if a['resolution_kind'] == 'TYPED'))
        action.update(source_definition_id='test:eye.ranged_weapon', display_name='Ranged Test Weapon',
                      economy='ACTION', target_kind='HOSTILE_ENTITY', costs=[], range_ft=60)
        action['parameters'] = {'typed': {'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'count': 1,
            'damage': {'count': 1, 'sides': 4}, 'damage_types': ['piercing']}],
            'weapon': {'name': 'Scenario bow', 'damage': {'count': 1, 'sides': 4}}, 'range_ft': 60,
            'numbers': {'cl': 15, 'pb': 5, 'attack_bonus': 20}, 'riders': []}}
        owner['action_catalog'].append(action)
        owner['actor_template']['action_ids'].append(action['source_definition_id'])
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    return transform


@pytest.mark.parametrize('owned,focused,poison,mode', [
    (True, True, False, 'NORMAL'), (False, True, False, 'DISADVANTAGE'),
    (True, False, False, 'DISADVANTAGE'), (True, True, True, 'DISADVANTAGE'),
], ids=['weather-removed', 'unowned', 'no-focus', 'unrelated-penalty-remains'])
def test_wind_reader_removes_only_weather_disadvantage(tmp_path, owned, focused, poison, mode):
    combat, table, mid = fixture(tmp_path, [BASE, *([WIND] if owned else [])],
                                 bundle_transform=wind_setup(poison=poison))
    do(combat, table, mid, 'Wind Shroud', target=OWNER)
    e = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.weather_ranged' for c in e.state.actors[OWNER].conditions.values())
    if poison:
        do(combat, table, mid, 'Poison')
    if not focused:
        do(combat, table, mid, 'Spend Focus')
    do(combat, table, mid, 'Ranged Test Weapon')
    e = reload(tmp_path, mid)
    attack = next(r for r in reversed(e.events) if r.event_type == 'ATTACK_ROLLED' and r.actor_id == OWNER)
    assert attack.payload['mode'] == mode
    assert ('DISADVANTAGE:weather' in attack.payload.get('attack_mode_removed', [])) is (owned and focused)
    # The successful-save Wind marker is consumed by the attempt, even when ignored.
    assert not any(c.condition_id == 'condition:typed.weather_ranged' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('focused', [True, False])
def test_true_sight_live_focus_and_invisible_target_through_cold_service(tmp_path, focused):
    combat, table, mid = fixture(tmp_path, [BASE, TRUE], bundle_transform=seal)
    if not focused:
        do(combat, table, mid, 'Spend Focus')
    turn(table, mid, FOE)
    do(combat, table, mid, 'Forced Conceal')
    e = reload(tmp_path, mid)
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert ('truesight' in senses.of(e, owner)) is focused
    assert senses.perceives(e, owner, foe) is focused
    if focused:
        assert senses.of(e, owner)['truesight']['range_ft'] == 120
    turn(table, mid, OWNER)
    do(combat, table, mid, 'Search Again')
    e = reload(tmp_path, mid)
    row = next(r for r in reversed(e.events) if r.event_type == 'CHECK_ROLLED' and r.actor_id == OWNER)
    assert bool(row.payload.get('by_sense')) is focused


def test_cooperative_stealth_computer_selects_allies_and_never_enemy(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, COOP], bundle_transform=seal, extra_allies=1)
    do_ai(combat, table, mid, 'Conceal')
    e = reload(tmp_path, mid)
    total = e.state.actors[OWNER].conditions[stealth.hidden(e.state.actors[OWNER])].data['stealth_total']
    recipients = [a for a in e.state.actors.values() if any(c.condition_id == COOP_STEALTH_TAG for c in a.conditions.values())]
    assert {a.entity_id for a in recipients} == {ALLY, 'actor:factory.worker2-ally3'}
    assert all(a.team_id == e.state.actors[OWNER].team_id for a in recipients)
    assert not any(c.condition_id == COOP_STEALTH_TAG for c in e.state.actors[FOE].conditions.values())
    turn(table, mid, ALLY)
    e = reload(tmp_path, mid)
    # Actual concealment is still required; a cooperative tag grants no plain-view Hide.
    assert not any(a.display_name == 'Hide' for c in e.legal_candidates()
                   if (a := e.action_catalog.get(c.source_definition_id)))
    do(combat, table, mid, 'Conceal')
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].conditions[stealth.hidden(e.state.actors[ALLY])].data['stealth_total'] == total
    assert not any(c.condition_id == COOP_STEALTH_TAG for c in e.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('high', [False, True], ids=['ordinary-success', 'dc-plus-five'])
def test_folklorist_selects_one_extra_characteristic_only_at_printed_margin(tmp_path, high):
    def transform(bundles):
        # Seal the actual skill component; no die or handler replacement.
        for row in bundles[0]['typed_passives']:
            if row.get('kind') == 'analysis_limits':
                row['mods']['INT'] = 2 if high else 1
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [BASE, FOLK], cl=5, seed='A2-FOLKLORIST', bundle_transform=transform)
    prompts = do(combat, table, mid, 'Analyze', picks={'choice:needle.eye_approach': 'Investigation',
        'choice:needle.eye_learn': ['Armor Class', 'Walking Speed'] if high else ['Armor Class']})
    e = reload(tmp_path, mid)
    check = next(r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.actor_id == OWNER and 'Analyze' in str(r.payload))
    margin = check.payload['actor']['total'] - check.payload['dc']
    assert margin == (5 if high else 4)
    known = [c for c in e.state.actors[OWNER].conditions.values() if c.condition_id == KNOWN]
    assert len(known) == 1 + int(high)
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.eye_learn')
    assert menu['choice']['maximum'] == menu['choice']['minimum'] == 1 + int(high)


@pytest.mark.parametrize('hp,expected', [(100, 'Normal'), (90, 'Normal'), (89, 'Fair'),
                                       (30, 'Fair'), (29, 'Poor'), (1, 'Poor'), (0, 'Weak')])
def test_physical_examination_updates_printed_health_band_after_committed_damage(tmp_path, hp, expected):
    foe = sheet([], cl=5)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 100
    def transform(bundles):
        owner = bundles[0]
        for row in owner['typed_passives']:
            if row.get('kind') == 'analysis_limits':
                row['mods']['WIS'] = 40
        seal_action(owner, 'Scenario Damage', [{'type': 'damage', 'flat': 100-hp,
                    'damage_types': ['force'], 'applies_to': 'target'}], target_kind='HOSTILE_ENTITY')
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    combat, table, mid = fixture(tmp_path, [BASE, 'TAL_THE_HIDDEN_EYE_PHYSICAL_EXAMINATION'],
                                 cl=5, foe_sheet=foe, bundle_transform=transform)
    do(combat, table, mid, 'Analyze', picks={'choice:needle.eye_approach': 'Medicine',
                                         'choice:needle.eye_learn': ['Armor Class']})
    do(combat, table, mid, 'Scenario Damage', target=FOE)
    e = reload(tmp_path, mid)
    assert e.state.actors[FOE].current_hp == hp
    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)
    actor = next(a for a in cold['presentation']['actors'] if a['entity_id'] == FOE)
    text = str(actor['conditions'])
    assert f'physical condition is {expected}' in text
    assert 'health band, not exact Hit Points' in text


@pytest.mark.parametrize('owned,expected', [(True, 'ADVANTAGE'), (False, 'NORMAL')])
def test_wind_reader_removes_weather_before_advantage_cancellation(tmp_path, owned, expected):
    combat, table, mid = fixture(tmp_path, [BASE, *([WIND] if owned else [])], bundle_transform=wind_setup())
    do(combat, table, mid, 'Wind Shroud', target=OWNER)
    do(combat, table, mid, 'Advantage')
    do(combat, table, mid, 'Ranged Test Weapon')
    e = reload(tmp_path, mid)
    row = next(r for r in reversed(e.events) if r.event_type == 'ATTACK_ROLLED' and r.actor_id == OWNER)
    assert row.payload['mode'] == expected


def test_true_sight_does_not_reveal_an_invisible_creature_through_solid_cover(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, TRUE], bundle_transform=seal,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 5}, FOE: {'x': 14, 'y': 6}})
    turn(table, mid, FOE)
    do(combat, table, mid, 'Forced Conceal')
    e = reload(tmp_path, mid)
    assert senses.of(e, e.state.actors[OWNER])['truesight']['range_ft'] == 120
    assert not senses.perceives(e, e.state.actors[OWNER], e.state.actors[FOE])
    assert not senses.finds(e, e.state.actors[OWNER], e.state.actors[FOE])


def presented(combat, tmp_path, mid, entity):
    """The cold table's own actor card, rebuilt from the saved fight."""
    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)
    actor = next(a for a in cold['presentation']['actors'] if a['entity_id'] == entity)
    return str(actor['conditions'])


def end_owner_turn(table, mid):
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])


def test_physical_examination_reads_the_patient_eye_record_and_ends_with_it(tmp_path):
    """Finding 1: the Inheritance files its own Analyzed record, and the reading follows the relationship.

    Heaven Keeps No Secret from the Patient Eye Analyzes its target "even if it would normally be
    protected from Analyze", so it never writes the ordinary Analyze mark. A Physical Examination owner
    must therefore earn the health band from the Inheritance's record as well, and the band ends with
    that record's own minute.
    """
    foe = sheet([], cl=5)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 100

    def transform(bundles):
        seal_action(bundles[0], 'Scenario Damage', [{'type': 'damage', 'flat': 40,
                    'damage_types': ['force'], 'applies_to': 'target'}], target_kind='HOSTILE_ENTITY')

    combat, table, mid = fixture(tmp_path, [BASE, EXAM, PATIENT], cl=5, foe_sheet=foe,
                                 bundle_transform=transform)
    do(combat, table, mid, 'Heaven Keeps No Secret from the Patient Eye', target=FOE)
    do(combat, table, mid, 'Scenario Damage', target=FOE)
    e = reload(tmp_path, mid)
    marks = [c.condition_id for c in e.state.actors[FOE].conditions.values()]
    # The Inheritance's own record is what stands there: no ordinary Analyze mark was ever written.
    assert PATIENT_EYE_ANALYZED in marks and ANALYZED not in marks
    assert e.state.actors[FOE].current_hp == 60
    text = presented(combat, tmp_path, mid, FOE)
    assert 'physical condition is Fair' in text
    assert 'health band, not exact Hit Points' in text
    # The reading ends with the record that carries it: the Inheritance lasts one minute.
    for _ in range(14):
        if not any(c.condition_id == PATIENT_EYE_ANALYZED
                   for c in reload(tmp_path, mid).state.actors[FOE].conditions.values()):
            break
        end_owner_turn(table, mid)
    else:
        raise AssertionError('the Inheritance record never expired')
    assert 'physical condition is' not in presented(combat, tmp_path, mid, FOE)


@pytest.mark.parametrize('action_name', ['Search Again', 'Thousand-Lantern Sweep'])
def test_lurker_prompt_names_the_triggering_action_and_hidden_creature_on_an_ai_searchers_turn(tmp_path, action_name):
    """Finding 2: the question names the action that is actually resolving now and the creature it lands on.

    The searcher acts on the computer's own turn while the hidden Lurker owner stays a manual player, so
    this is a player choice made during an AI turn. Search and the Thousand-Lantern Sweep are different
    actions at this checkpoint and must not present the same generic moment.
    """
    combat, table, mid = fixture(tmp_path, [BASE, LURKER], foe_sheet=sheet([BASE, SWEEP], cl=15),
                                 bundle_transform=seal)
    do(combat, table, mid, 'Conceal')
    turn(table, mid, FOE)
    assert combat._load_session(mid).engine.typed_control_modes[OWNER] == 'MANUAL'
    prompts = do_ai(combat, table, mid, action_name, actor=FOE)
    e = reload(tmp_path, mid)
    searcher, hidden = e.state.actors[FOE], e.state.actors[OWNER]
    asked = [p for p in prompts if p['context']['reaction_source_id'] == PICK]
    assert len(asked) == 1, prompts
    p = asked[0]
    assert p['action'] == action_name
    assert p['trigger_actor'] == searcher.display_name
    assert p['affected'] == hidden.display_name and p['by'] == hidden.display_name
    # Newcomer-readable: the action and the hidden creature are named in the question itself.
    assert action_name in p['moment'] and searcher.display_name in p['moment']
    assert 'to search for you' in p['moment']
    # The owner's decision was the player's: it stayed manual and was answered, then paid for.
    assert combat._load_session(mid).engine.typed_control_modes[OWNER] == 'MANUAL'
    assert e.state.actors[OWNER].resources[FOCUS] == 0 and not e.state.actors[OWNER].reaction_available
    assert checks(e)[-1].payload['actor']['mode'] == 'DISADVANTAGE'


# ---------------------------------------------------------- r3 review: the shared Reaction contract
# "Lurker works when Reactions are prohibited" and "Lurker's Reaction is invisible to reaction-use
# responders" (A2THEHIDDEr2 review findings 1 and 2). Both were a hand-rolled gate and a hand-rolled
# spend standing in for combat/typed_reactions.py's public admission and lifecycle.
COUNTERMEASURE = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"
CC_KEY = f"reaction:typed.{COUNTERMEASURE}"
FOCUS_DENIAL = "Suppress Reactions"


def deny_seal(evidence, *, on=''):
    """The stock seal plus one sealed action that prints a Reaction prohibition, so the denial is a real
    committed condition and not an engine flag the fixture reaches behind the service."""
    def transform(bundles):
        seal(bundles)
        for bundle in bundles:
            if bundle['actor_id'] != FOE:
                continue
            seal_action(bundle, FOCUS_DENIAL, [{'type': 'reaction_denied', 'applies_to': 'target',
                                                'on': on, 'evidence': evidence,
                                                'expires_on': 'UNTIL_REMOVED'}], target_kind='HOSTILE_ENTITY')
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    return transform


@pytest.mark.parametrize('barrier', ['cannot_take_reactions', 'cannot_react_against_searcher'])
def test_lurker_is_not_offered_or_paid_when_the_searcher_prohibits_reactions(tmp_path, barrier):
    """Finding 1: a prohibition the old economy-flag check never read.

    Both lines are printed prohibitions placed by the searcher itself, on the hidden creature: the ordinary
    "cannot take Reactions" and the subject-specific "cannot take Reactions against you". A Hidden Eye owner
    barred from Reactions may not be asked, may not be paid and may not impose Disadvantage.
    """
    evidence = ('The target cannot take Reactions against you.' if barrier == 'cannot_react_against_searcher'
                else 'The target cannot take Reactions.')
    combat, table, mid = fixture(tmp_path, [BASE, LURKER],
                                 bundle_transform=deny_seal(evidence, on='against you' if 'against' in evidence else ''))
    # The prohibition lands while the owner is still visible (a hidden creature cannot be named as a
    # target), and the owner hides afterwards, so the search really does find a hidden barred creature.
    turn(table, mid, FOE)
    do(combat, table, mid, FOCUS_DENIAL, target=OWNER)
    turn(table, mid, OWNER)
    do(combat, table, mid, 'Conceal')
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER]
    prompts = do(combat, table, mid, 'Search Again', picks={PICK: 'lurker'})
    e = reload(tmp_path, mid)
    holder = e.state.actors[OWNER]
    assert not [p for p in prompts if p['context']['reaction_source_id'] == PICK], prompts
    assert checks(e)[-1].payload['actor']['mode'] == 'NORMAL'
    # No payment and no reaction spent: the offer never happened.
    assert holder.resources[FOCUS] == before.resources[FOCUS] and holder.reaction_available
    assert stealth.hidden(holder)
    assert any(c.condition_id.endswith('reaction_denied') or c.condition_id.endswith('no_reactions_against')
               for c in holder.conditions.values())


def test_lurker_reaction_is_published_to_a_qualifying_reaction_used_responder(tmp_path):
    """Finding 2: Lurker's accepted use is a real Reaction use that other abilities can answer.

    Charged Countermeasure answers "a creature within 60 feet uses a reaction". Its player is asked mid-action
    (the pause/resume the outer Search action owns), so this also shows Lurker is not paid twice when that
    nested prompt interrupts it, and that the whole thing survives a cold reload.
    """
    combat, table, mid = fixture(tmp_path, [BASE, LURKER],
                                 foe_sheet=sheet([COUNTERMEASURE], cl=15), bundle_transform=seal)
    do(combat, table, mid, 'Conceal')
    turn(table, mid, ALLY)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER]
    prompts = do(combat, table, mid, 'Search Again', picks={PICK: 'lurker', CC_KEY: 'use'})
    e = reload(tmp_path, mid)
    holder, foe = e.state.actors[OWNER], e.state.actors[FOE]
    # The Lurker question was asked and answered exactly once, and the responder was offered its own.
    assert len([p for p in prompts if p['context']['reaction_source_id'] == PICK]) == 1
    assert len([p for p in prompts if p['context']['reaction_source_id'] == CC_KEY]) == 1, prompts
    # The native window and the reaction-use moment were published for Lurker itself.
    assert [x for x in e.events if x.event_type == 'REACTION_WINDOW_OPENED'
            and x.actor_id == OWNER and x.source_definition_id == LURKER]
    # The responder fired: it answered with its own Reaction and asked the triggering creature for a save.
    assert [x for x in e.events if x.event_type == 'REACTION_RESOLVED'
            and x.actor_id == FOE and x.source_definition_id == COUNTERMEASURE]
    assert any(x.event_type == 'SAVE_ROLLED' and x.actor_id == OWNER
               for x in e.events), 'the answered reaction\'s creature made no save'
    # Lurker worked, and was paid for exactly once through the shared lifecycle.
    assert checks(e)[-1].payload['actor']['mode'] == 'DISADVANTAGE'
    assert holder.resources[FOCUS] == before.resources[FOCUS] - 1 and not holder.reaction_available
    assert not foe.reaction_available
