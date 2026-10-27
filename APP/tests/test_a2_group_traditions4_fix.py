"""A2GTRA4r1 fix round: review findings 1-3, through CombatService, committed intents and cold reload.

  1. The Welcoming Ground ban and the Lost Trail no-approach bar ended at the *caster's* next turn because both
     named the engine's START_OF_TARGET_NEXT_TURN, which _expire_for_checkpoint sweeps at the applier's turn or
     the holder's, whichever is first (bug 3, tests/test_expiry_names.py). Each now rides the affected creature's
     own turn clock, and is proved at the intervening caster turn and again at the holder's next turn.
  2. Welcoming Ground's ban did not reach a generic *triggered* reaction: an ``ally_attacked`` bystander row runs
     _ally_row_ok / _can_trigger / _open, none of which the old hooks touched, so a welcomed spirit could still
     counterattack or penalise the attacker. Hostile rows are now refused at the general row_allowed seam while
     beneficial reactions stay available.
  3. Lost Trail silently narrowed "a creature you designate" to the walker's allies the target could perceive.
     Every active creature is offered to a player again; the automatic chooser merely prefers an ally.
"""
import copy

import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from test_riders_c8 import ROOT, ME, MIND_SPIKE, SPIRITUAL_SENSE, MK_ALL, MW_ALL, SW_ALL, bundle, held
from test_a2_group_traditions4 import ENEMY, ALLY, SECOND, act, advance, reload

WELCOMED = "condition:typed.welcoming_ground"
NO_APPROACH = "condition:typed.no_approach"
GROUND_AT = Position(x=6, y=6)


def prepare(tmp_path, *, control='MANUAL', spirit=True, dc=40, reactions=(), second_at=(9, 7)):
    """A Welcoming Ground table with the spirit's own hostile and beneficial ally reactions.

    ENEMY is the spirit on team:b; PARTNER is its team:b ally, so an ``ally_attacked`` row on ENEMY is the
    bystander reaction Welcoming Ground has to keep it from taking. ``reactions`` are the bundle's own
    ``typed_reactions`` rows, which gate2_engine rebuilds from the bundle on every load.
    """
    service = CombatService(ROOT, tmp_path)
    me = bundle([*MK_ALL, SPIRITUAL_SENSE], dc=dc, resonance=100)
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY, cl=5, dc=40)
    ally = bundle([MIND_SPIKE], actor_id=ALLY)
    partner = bundle([MIND_SPIKE], actor_id=SECOND, cl=5)
    for doc in (me, enemy, ally, partner):
        doc['actor_template']['maximum_hp'] = 1000
    enemy['actor_template']['creature_types'] = ['spirit' if spirit else 'humanoid']
    if dc == 1:
        enemy['actor_template']['saving_throws']['CHA'] = 100
    strike = copy.deepcopy(next(a for a in me['action_catalog'] if a['display_name'] == 'Mind Spike'))
    strike.update(source_definition_id=strike['source_definition_id'] + '.fix_r1_strike',
                  display_name='Test hostile strike', target_kind='HOSTILE_ENTITY', range_ft=60, costs=[])
    strike['parameters']['typed']['effects'] = [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
        'applies_to': 'target', 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['psychic'], 'applies_to': 'target'}]}]
    me['action_catalog'].append(strike)
    me['actor_template']['action_ids'].append(strike['source_definition_id'])
    if reactions:
        enemy['typed_reactions'] = list(reactions)
    session = service.persistence.create_match(
        match_seed='A2GTRA4R1', maximum_rounds=30, typed_bundles=(me, enemy, ally, partner),
        roster_setup={'primary_actor_ids': [ME, ENEMY, ALLY, SECOND],
                      'team_by_actor': {ME: 'team:a', ALLY: 'team:a', ENEMY: 'team:b', SECOND: 'team:b'},
                      'starting_positions': {ME: {'x': 6, 'y': 6}, ALLY: {'x': 7, 'y': 8},
                                             ENEMY: {'x': 11 if spirit else 8, 'y': 6},
                                             SECOND: {'x': second_at[0], 'y': second_at[1]}}})
    metadata = {'participant_control_modes': {ME: control, ENEMY: 'MANUAL', ALLY: 'MANUAL', SECOND: 'MANUAL'}}
    return service, session, metadata


def welcome_the_spirit(service, session, metadata):
    """ME lays a Welcoming Ground, the hostile spirit walks in and fails its Charisma save."""
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Sacred Ground: Welcoming Ground', destination=GROUND_AT)
    advance(service, session, metadata, ENEMY)
    events, _, _ = act(service, session, metadata, 'Move to 10,6')
    assert any(e.event_type == 'SAVE_ROLLED' for e in events)
    return reload(service, session)


def bloom(session, service, metadata):
    """The full printed Bloom setup, resolving on the hostile target's own turn."""
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Plant test spores', ENEMY)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Hallucinogenic Bloom')


# ------------------------------------------------------------------ finding 1: the ban lives on the holder's own turn
def test_welcoming_ground_ban_survives_the_casters_next_turn_and_ends_on_the_spirits(tmp_path):
    service, session, metadata = prepare(tmp_path, dc=40)
    session = welcome_the_spirit(service, session, metadata)
    spirit = session.engine.state.actors[ENEMY]
    [ban] = held(spirit, WELCOMED)
    # The printed duration is the spirit's own next turn, so the name is that turn's own counter
    # (START_OF_TURN_AT:<its id>:<its next turn>), which no other creature's turn can bring down early.
    assert ban.expires_on == f'START_OF_TURN_AT:{spirit.entity_id}:{int(spirit.turns_started) + 1}'
    assert ban.expires_on != 'START_OF_TARGET_NEXT_TURN'
    held_before = spirit.turns_started

    # The Ground's owner (the applier) takes a whole turn before the spirit does. Under START_OF_TARGET_NEXT_TURN
    # the engine swept the ban here; under the holder's own turn counter it is still in force.
    act(service, session, metadata, 'End turn')            # the spirit ends the turn it entered on
    advance(service, session, metadata, ME)
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], WELCOMED), 'the ban ended at the caster\'s turn, before the spirit\'s own next turn'

    # ...and the ban is still a live ban while it lasts: no hostile action is offered to the spirit on its next turn's
    # opening either, and it only falls at the start of the spirit's own next turn.
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ENEMY)
    session = reload(service, session)
    spirit = session.engine.state.actors[ENEMY]
    assert spirit.turns_started == held_before + 1, 'the spirit did not get exactly one more turn'
    assert not held(spirit, WELCOMED), 'the ban outlived the start of the spirit\'s own next turn'


def test_lost_trail_ban_survives_the_walkers_next_turn(tmp_path):
    from test_a2_group_traditions4 import setup as feature_setup

    service, session, metadata = feature_setup(tmp_path, MW_ALL)
    bloom(session, service, metadata)

    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('dreamwalker.bloom'):
            return ('lost_trail',)
        if context.reaction_source_id.endswith('dreamwalker.lost_trail_subject'):
            return (ME,)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    while session.engine.state.current_actor_id != ENEMY:  # the Bloom resolves on the target's own turn
        act(service, session, metadata, 'End turn', choose=choose)
    session = reload(service, session)
    target = session.engine.state.actors[ENEMY]
    [bar] = held(target, NO_APPROACH)
    assert bar.expires_on == f'START_OF_TURN_AT:{target.entity_id}:{int(target.turns_started) + 1}'
    assert bar.expires_on != 'START_OF_TARGET_NEXT_TURN'
    first = bar.instance_id

    act(service, session, metadata, 'End turn')            # the walker's turn comes before the target's next one
    advance(service, session, metadata, ME)
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], NO_APPROACH), 'Lost Trail ended at the walker\'s turn'
    assert first in session.engine.state.actors[ENEMY].conditions, 'the original bar ended at the walker\'s turn'
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ENEMY)
    session = reload(service, session)
    # The target starting its turn in the Bloom is a fresh printed save and may lay a fresh bar; the original one,
    # the one this round put on, must be gone exactly at the start of the target's own next turn.
    assert first not in session.engine.state.actors[ENEMY].conditions, 'the bar outlived the target\'s own next turn'


# ------------------------------------------------------------------ finding 2: hostile triggered reactions
# Costed bystander rows: the spirit spends its own Reaction, and the row is declared in the bundle's
# ``typed_reactions`` so gate2_engine rebuilds it on every load and the case survives a cold reload.
HOSTILE_ROW = {'feature_id': 'a2gtra4r1.hostile_retaliation', 'block': 'generic', 'kind': 'ally_attacked',
               'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
               'effects': [{'type': 'condition', 'condition': 'cursed', 'applies_to': 'attacker',
                            'duration': {'kind': 'scene'}, 'harmful': True}]}
BENEFICIAL_ROW = {'feature_id': 'a2gtra4r1.sheltering_spirit', 'block': 'generic', 'kind': 'ally_attacked',
                  'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                  'effects': [{'type': 'ac_bonus', 'applies_to': 'target', 'duration': 'triggering_attack', 'flat': 3}]}


def attacks_the_spirits_ally(service, session, metadata):
    """ME declares a committed typed attack on the spirit's team:b ally, on ME's own turn."""
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    events, _, _ = act(service, session, metadata, 'Test hostile strike', SECOND)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in events), 'the ally was never attacked'
    return any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == ENEMY for e in events)


# --------------------------------------------------- A2GTRA4r3 finding 1: a penalty's amount may be dice or a formula
# The ban asked "is this row hostile?" and answered from whichever single amount key the row happened to carry, so a
# penalty written the way the reaction engine actually reads one -- ``_generic_amount`` resolves flat, a ``formula``
# and a ``dice`` term, and _offer_ally_attacked then subtracts the result from the attacker's roll -- classified as
# zero and was admitted while the ban stood. Both rows below name a real penalty and no flat amount at all.
DICE_PENALTY_ROW = {'feature_id': 'a2gtra4r3.dice_penalty', 'block': 'generic', 'kind': 'ally_attacked',
                    'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                    'effects': [{'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': 0,
                                 'dice': {'count': 1, 'sides': 6}}]}
FORMULA_PENALTY_ROW = {'feature_id': 'a2gtra4r3.formula_penalty', 'block': 'generic', 'kind': 'ally_attacked',
                       'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                       'effects': [{'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': 0,
                                    'formula': 'pb'}]}
# The same encodings as a *benefit*: a die and a Proficiency Bonus both raise AC, and the ban must keep them.
DICE_BENEFIT_ROW = {'feature_id': 'a2gtra4r3.dice_benefit', 'block': 'generic', 'kind': 'ally_attacked',
                    'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                    'effects': [{'type': 'ac_bonus', 'applies_to': 'target', 'duration': 'triggering_attack',
                                 'dice': {'count': 1, 'sides': 6}}]}
FORMULA_BENEFIT_ROW = {'feature_id': 'a2gtra4r3.formula_benefit', 'block': 'generic', 'kind': 'ally_attacked',
                       'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                       'effects': [{'type': 'ac_bonus', 'applies_to': 'target', 'duration': 'triggering_attack',
                                    'formula': 'pb'}]}

# Native harm encodings that the shared effect contract must classify for every
# consumer: speed uses `amount`, and conditions are harmful without a lane flag.
AMOUNT_SPEED_PENALTY_ROW = {'feature_id': 'a2gtra4r5.amount_speed_penalty', 'block': 'generic',
                            'kind': 'ally_attacked', 'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30,
                            'melee': True, 'ranged': True,
                            'effects': [{'type': 'speed', 'applies_to': 'attacker', 'amount': -10}]}
UNFLAGGED_CONDITION_ROW = {'feature_id': 'a2gtra4r5.unflagged_condition', 'block': 'generic',
                           'kind': 'ally_attacked', 'costs': [], 'numbers': {'pb': 2}, 'range_ft': 30,
                           'melee': True, 'ranged': True,
                           'effects': [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'attacker',
                                        'duration': {'kind': 'scene'}}]}


@pytest.mark.parametrize('reaction,expected', [
    (AMOUNT_SPEED_PENALTY_ROW, 'speed_ft'), (UNFLAGGED_CONDITION_ROW, 'condition:typed.blinded')],
    ids=['native_amount_speed_penalty', 'unflagged_native_condition'])
def test_welcoming_ground_uses_shared_native_harm_contract(tmp_path, reaction, expected):
    """The no-Ground run proves each native row has its advertised effect; the ban then blocks it across reload."""
    service, session, metadata = prepare(tmp_path / 'control', dc=40, reactions=(reaction,))
    assert attacks_the_spirits_ally(service, session, metadata), 'control reaction did not resolve'
    session = reload(service, session)
    affected = session.engine.state.actors[ME]
    if expected == 'speed_ft':
        assert any(m.target_field == expected and m.value == -10 for m in affected.modifiers.values()), (
            'control did not apply the native amount speed penalty')
    else:
        assert any(c.condition_id == expected for c in affected.conditions.values()), (
            'control did not apply the unflagged condition')

    service, session, metadata = prepare(tmp_path / 'grounded', dc=40, reactions=(reaction,))
    session = welcome_the_spirit(service, session, metadata)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)
    assert attacks_the_spirits_ally(service, session, metadata) is False, (
        'Welcoming Ground admitted a harmful native effect')
    session = reload(service, session)
    spirit = session.engine.state.actors[ENEMY]
    affected = session.engine.state.actors[ME]
    assert held(spirit, WELCOMED)
    assert spirit.reaction_available
    assert not any((m.target_field == 'speed_ft' and m.value == -10) for m in affected.modifiers.values())
    assert not any(c.condition_id == 'condition:typed.blinded' for c in affected.conditions.values())


@pytest.mark.parametrize('reaction', [DICE_PENALTY_ROW, FORMULA_PENALTY_ROW], ids=['dice_penalty', 'formula_penalty'])
def test_welcoming_ground_bans_a_penalty_written_as_dice_or_a_formula(tmp_path, reaction):
    """A penalty stays a penalty however its amount is written.

    The control proves the engine reads this row as a penalty at all -- the reaction resolves *and* the attack it
    answers carries a real attack_penalty -- so the under-Ground run measures the ban rather than a row that never
    hurt anyone. Without the fix both rows slip through as "no flat amount, so not a penalty".
    """
    service, session, metadata = prepare(tmp_path / 'control', dc=40, reactions=(reaction,))
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    events, _, _ = act(service, session, metadata, 'Test hostile strike', SECOND)
    resolved = [e for e in events if e.event_type == 'REACTION_RESOLVED' and e.actor_id == ENEMY]
    assert resolved, 'the control never fired the row, so this measures nothing'
    assert int(resolved[0].payload.get('attack_penalty') or 0) > 0, (
        'the control row laid no penalty on the attacker, so it is not the penalty this case is about')

    service, session, metadata = prepare(tmp_path / 'grounded', dc=40, reactions=(reaction,))
    session = welcome_the_spirit(service, session, metadata)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)
    assert attacks_the_spirits_ally(service, session, metadata) is False, (
        'a welcomed spirit took a hostile triggered reaction on another actor\'s turn')
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], WELCOMED), 'the attack on the ally must not free the spirit'
    assert session.engine.state.actors[ENEMY].reaction_available, 'the banned row still spent the spirit\'s Reaction'


@pytest.mark.parametrize('reaction', [DICE_BENEFIT_ROW, FORMULA_BENEFIT_ROW], ids=['dice_benefit', 'formula_benefit'])
def test_welcoming_ground_keeps_a_benefit_written_as_dice_or_a_formula(tmp_path, reaction):
    """The other side of the same reading: dice and a formula as an AC *bonus* help, and stay available.

    Classifying by the engine's own amount bounds is what keeps this honest -- reading "a die is present, so it is
    hostile" would close these.
    """
    service, session, metadata = prepare(tmp_path / 'control', dc=40, reactions=(reaction,))
    assert attacks_the_spirits_ally(service, session, metadata), 'the control never fired the row, so this measures nothing'

    service, session, metadata = prepare(tmp_path / 'grounded', dc=40, reactions=(reaction,))
    session = welcome_the_spirit(service, session, metadata)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)
    assert attacks_the_spirits_ally(service, session, metadata) is True, (
        'the ban closed a beneficial reaction')
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)


@pytest.mark.parametrize('reaction,taken', [(HOSTILE_ROW, False), (BENEFICIAL_ROW, True)],
                         ids=['hostile', 'beneficial'])
def test_welcoming_ground_bans_only_the_hostile_triggered_reaction(tmp_path, reaction, taken):
    """The same bystander row, fired on another actor's turn, with and without the Ground.

    The control run (no Welcoming Ground, nothing wrong with the spirit) proves the row is admitted at all, so
    the under-Ground run measures the ban and not a row the engine would never have offered.
    """
    service, session, metadata = prepare(tmp_path / 'control', dc=40, reactions=(reaction,))
    assert attacks_the_spirits_ally(service, session, metadata), 'the control never fired the row, so this measures nothing'

    service, session, metadata = prepare(tmp_path / 'grounded', dc=40, reactions=(reaction,))
    session = welcome_the_spirit(service, session, metadata)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)

    fired = attacks_the_spirits_ally(service, session, metadata)
    assert fired is taken, (
        'a welcomed spirit took a hostile triggered reaction on another actor\'s turn' if not taken
        else 'the ban closed a beneficial reaction as well')
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], WELCOMED), 'the attack on the ally must not free the spirit'
    if not taken:
        # The refusal is a refusal to admit, not a silent spend: the spirit still has its Reaction.
        assert session.engine.state.actors[ENEMY].reaction_available, 'the banned row still spent the spirit\'s Reaction'



# ------------------------------------------------------------------ finding 3: "a creature you designate"
@pytest.mark.parametrize('designated,who', [(SECOND, 'an enemy'), (ME, 'the walker')])
def test_lost_trail_offers_every_creature_and_honours_the_designation(tmp_path, designated, who):
    from test_a2_group_traditions4 import setup as feature_setup

    service, session, metadata = feature_setup(tmp_path, MW_ALL)
    offered = []
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('dreamwalker.bloom'):
            return ('lost_trail',)
        if context.reaction_source_id.endswith('dreamwalker.bloom_spread'):
            return ()
        if context.reaction_source_id.endswith('dreamwalker.lost_trail_subject'):
            options = set(spec.option_ids)
            offered.append(options)
            # The affected creature is the one missing from its own menu, so only ENEMY's menu is answered;
            # the Bloom also touches the other two, whose bars are not what this case is about.
            return (designated,) if ENEMY not in options else (spec.option_ids[0],)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    bloom(session, service, metadata)
    while session.engine.state.current_actor_id != ENEMY:
        act(service, session, metadata, 'End turn', choose=choose)
    # "a creature you designate" names no alliance and no perception limit: every other active creature is offered.
    assert offered, 'no designation menu was offered'
    [enemys] = [menu for menu in offered if ENEMY not in menu]
    assert {ME, ALLY, SECOND} <= enemys, f'{who} was not on the designation menu: {enemys}'
    for menu in offered:  # every menu offers exactly the active creatures but the one it is put on
        assert len(menu) == 3, menu
    session = reload(service, session)
    target = session.engine.state.actors[ENEMY]
    [bar] = held(target, NO_APPROACH)
    assert bar.data['avoid'] == designated, 'the player\'s designation was not the one recorded'
    # ...and it is real movement law, not just stored data: no offered step ends nearer to that creature.
    anchor = session.engine.state.actors[designated]
    before = session.engine.grid.distance_ft(target.position, anchor.position)
    moves = [c for c in session.engine.legal_candidates() if c.destination is not None]
    assert moves, 'no movement was offered at all'
    for candidate in moves:
        assert session.engine.grid.distance_ft(candidate.destination, anchor.position) >= before, candidate.display_name
