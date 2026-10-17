"""Monkey Style automation lane AUTO85 (2026-10-05): printed effects the table now resolves itself.

Each test is a table-level check against the printed text in
APP/authority/typed_mechanics/rules_text.json ("Monkey Style", the talents), through the real engine: movement through
creature spaces, Uncatchable's third choice, Laughing Trip's Disadvantage, and the printed "choose" lists of Impossible
Ape Reversal, Laughing Theft of Timing and Monkey Catches the Moon.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from combat import creature_passage, motion, typed_executor as te, typed_reactions as tr
from combat.ext import monkey
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from tests.test_auto_support import ME, _engine

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
M = 'TAL_MONKEY_STYLE_'
_spec = importlib.util.spec_from_file_location('review_sw_monkey', ROOT / 'tests/test_review_sw-monkey_style.py')
_review = importlib.util.module_from_spec(_spec)
sys.modules['review_sw_monkey'] = _review
_spec.loader.exec_module(_review)
compiled, cast, has, linked, moved = (_review.compiled, _review.cast, _review.has, _review.linked, _review.moved)
SHEET = _review.SHEET


def fight(key, cl=20, dc=50, extras=()):
    bundle = copy.deepcopy(compiled(key, cl, dc, extras))
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.stamina'] = 100
    me.resource_maximums['resource:core.stamina'] = 100
    open_table(engine)
    return bundle, engine, me, foe


def open_table(engine):
    """An open table: a question with nobody answering takes its printed default (the AI's own answer)."""
    if getattr(engine, '_active_intent', None) is None:
        engine._active_intent = ActionIntent(intent_id='auto85', decision_id='auto85', candidate_id='auto85',
                                             state_version=0, actor_id=ME, target_ids=(AN,))
        engine._gate4_reaction_cache = {}
    return engine


def answering(engine, answers, asked=None):
    """A table that answers one question per answer in ``answers`` (each a label, or a list of labels for a printed
    "choose two") and records what it was offered: ``(checkpoint, option ids, labels, the choice's own bounds)``. Anything it
    does not recognise is declined, so a test that expects a step to have happened cannot pass by accident."""
    answers = list(answers) if isinstance(answers, list) else [answers]
    state = {'index': 0}
    open_table(engine)

    def provider(request):
        options = list(request['legal_option_ids'])
        spec = request.get('extension_choice') or {}
        trigger = request.get('choice_trigger') or {}
        if asked is not None:
            asked.append((request.get('checkpoint'), options, str(trigger.get('prompt') or ''),
                          (int(spec.get('minimum_selections') or 0), int(spec.get('maximum_selections') or 0)),
                          dict(trigger.get('labels') or {})))
        answer = answers[min(state['index'], len(answers) - 1)]
        state['index'] += 1
        wanted = list(answer) if isinstance(answer, (list, tuple)) else [answer]
        labels = trigger.get('labels') or {}
        option_ids = tuple(option for option in options if option in wanted or labels.get(option) in wanted)
        selection = 'USE' if (option_ids or 'USE' in options) else 'DECLINE'
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                reaction_source_id=request['reaction_source_id'], selection=selection, option_ids=option_ids), None

    engine.set_reaction_provider(provider)
    return provider


CHECKPOINT, OPTIONS, PROMPT, BOUNDS, LABELS = range(5)


def questions(asked, word):
    """The asked rows whose checkpoint names ``word``."""
    return [row for row in asked if word in str(row[CHECKPOINT]).lower()]


def cell(x, y):
    from combat.gate2_runtime_models import Position

    return Position(x=x, y=y, z=0)


def links(actor):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.monkey_link']


# ------------------------------------------------------------------------- moving through creatures (the caper, the Court, the Great Sage)
def test_capering_footwork_passes_through_a_larger_creature_and_ignores_difficult_terrain():
    """"you ignore nonmagical difficult terrain; you may move through the spaces of creatures larger than you, treating
    hostile spaces as difficult terrain" -- the caper's own condition rule and the pass_through seam."""
    _, engine, me, foe = fight(M + 'CAPERING_FOOTWORK')
    assert creature_passage.permission(engine, me, foe) is None, 'ordinary movement already passed through a creature'
    assert not motion.ignores_difficult(engine, me)
    cast(engine, 'Capering Footwork')
    assert motion.ignores_difficult(engine, me), 'the caper printed no difficult-terrain ignore'
    foe.transformed_size_category = 'Large'  # the table reloads the fighter's own state for the next intent
    assert creature_passage.permission(engine, me, foe) == 'difficult'


def test_an_equal_sized_creature_is_not_a_caper_passage():
    _, engine, me, foe = fight(M + 'CAPERING_FOOTWORK')
    cast(engine, 'Capering Footwork')
    assert creature_passage.permission(engine, me, foe) is None, 'only creatures LARGER than you are passed through'
    foe.transformed_size_category = 'Large'
    assert creature_passage.permission(engine, me, foe) == 'difficult'


def test_court_and_great_sage_print_their_own_creature_space_movement():
    """"you may move through hostile spaces as difficult terrain" (Court) and "ability to move through hostile spaces
    without spending extra movement" (Great Sage)."""
    _, engine, me, foe = fight(M + 'COURT_OF_THE_LAUGHING_SAGE')
    assert creature_passage.permission(engine, me, foe) is None
    cast(engine, 'Court of the Laughing Sage')
    assert creature_passage.permission(engine, me, foe) == 'difficult'
    ally = me.model_copy(deep=True)
    ally.entity_id = 'auto85:ally'
    engine.state.actors[ally.entity_id] = ally
    assert creature_passage.permission(engine, ally, foe) is None, 'the printed line names hostile spaces only'


def test_great_sage_passes_through_hostile_spaces_at_no_cost():
    _, engine, me, foe = fight(M + 'GREAT_SAGE_EQUAL_TO_HEAVEN')
    cast(engine, 'Great Sage Equal to Heaven')
    assert creature_passage.permission(engine, me, foe) == 'free'


# ------------------------------------------------------------------------- Uncatchable's third printed choice
def test_uncatchable_offers_and_makes_its_melee_weapon_attack():
    """"choose one: move up to 15 feet without provoking opportunity attacks; make one melee weapon attack; create a
    Monkey Link" -- all three are the table's, and the attack really swings a real attack roll and deals damage."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'GREAT_SAGE_EQUAL_TO_HEAVEN')
    cast(engine, 'Great Sage Equal to Heaven')
    from tests.equipment_readiness import ready_weapon

    # The printed attack is the fighter's own readied weapon, so read the one the shared helper will pick: a weapon that is
    # not in hand is refused by the ordinary grip rule and no attack roll happens at all.
    ready_weapon(engine, 'Jian (Straight Sword) attack')
    asked = []
    answering(engine, f'Attack {foe.display_name} with your melee weapon', asked)
    before = len(engine.events)
    monkey._uncatchable(_ctx(engine, me, foe, 'Uncatchable'), me, foe)
    offered = [row[OPTIONS] for row in asked]
    read = ' '.join(label.lower() for label in asked[0][LABELS].values())
    assert all(word in read for word in ('link', 'melee weapon', '15 feet')), offered
    assert len(offered[0]) == 3, offered[0]
    swung = [event for event in engine.events[before:] if event.event_type == 'ATTACK_ROLLED'
             and event.actor_id == me.entity_id and foe.entity_id in (event.target_ids or ())]
    assert swung, 'the printed melee weapon attack was chosen but no attack roll was made'
    assert [event for event in engine.events[before:] if event.event_type == 'DAMAGE_COMMITTED'
            and event.actor_id == me.entity_id and foe.entity_id in (event.target_ids or ())], \
        'the printed melee weapon attack never reached the target'


def _ctx(engine, me, target, name):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id='reaction:typed.test', display_name=name, owner_id=me.entity_id,
                              economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='SELF')
    return te.Context(engine, me, action, None, {}, [target], target, {})


# ------------------------------------------------------------------------- Laughing Trip's Disadvantage
def test_laughing_trip_saves_with_disadvantage_after_moving_through_the_targets_space():
    """"If the attack was made after changing elevation or moving through the target's space, the target has Disadvantage
    on this saving throw." """
    _, engine, me, foe = fight(M + 'LAUGHING_TRIP', dc=1)
    linked(engine, me)
    cast(engine, 'Laughing Trip')
    assert 'NORMAL' in [roll.mode for roll in engine.rolls if roll.reason.startswith('SAVE')]
    engine.rolls.clear()
    engine.end_turn()
    engine.end_turn()
    cast(engine, 'Capering Footwork')          # "you may move through the spaces of creatures larger than you"
    open_table(engine)
    foe.transformed_size_category = 'Large'   # a two-square creature, so the step crosses both of its squares
    me.position = cell(3, 7)
    engine.move_path(me, [cell(x, 7) for x in (3, 4, 5, 6)], 'test', kind='granted', feet=15)
    assert (me.position.x, me.position.y) == (6, 7), 'the caper did not carry the fighter through the creature'
    foe.transformed_size_category = None
    foe.position = cell(5, 7)
    linked(engine, me)
    cast(engine, 'Laughing Trip')
    modes = [roll.mode for roll in engine.rolls if roll.reason.startswith('SAVE')]
    assert 'DISADVANTAGE' in modes, modes


# ------------------------------------------------------------------------- Impossible Ape Reversal
def test_ape_reversal_asks_for_two_of_its_six_printed_results():
    """"Failed Save: Choose two: ..." -- one question with six answers, bounded to two, and both chosen ones happen."""
    _, engine, me, foe = fight(M + 'IMPOSSIBLE_APE_REVERSAL', dc=50)
    asked = []
    answering(engine, [['the triggering creature falls Prone',
                        'create a Monkey Link that lasts until the end of your next turn']], asked)
    tr.on_attack_hit(engine, foe, me, {'range_ft': 5}, 20, 20, 10)
    offered = questions(asked, 'ape')
    assert offered, [row[CHECKPOINT] for row in asked]
    assert len(offered[0][OPTIONS]) == 6, offered[0][OPTIONS]
    assert offered[0][BOUNDS] == (2, 2), 'the printed "Choose two" is not the question\'s own bound'
    assert 'choose 2 of these 6 results' in offered[0][PROMPT].lower(), offered[0][PROMPT]
    assert has(foe, 'prone'), 'the printed Prone result did not happen'
    assert links(me), 'the printed Monkey Link result did not happen'


def test_ape_reversal_successful_save_offers_one_result():
    """"Successful Save: Choose one option instead." -- the same six results, bounded to exactly one, and only the one the
    owner picked happens."""
    _, engine, me, foe = fight(M + 'IMPOSSIBLE_APE_REVERSAL', dc=50)
    foe.saving_throws['WIS'] = 100
    asked = []
    answering(engine, ['the triggering creature falls Prone'], asked)
    tr.on_attack_hit(engine, foe, me, {'range_ft': 5}, 20, 20, 10)
    offered = questions(asked, 'ape')
    assert offered, asked
    assert offered[0][BOUNDS] == (1, 1), 'the printed "choose one option instead" is not the question\'s own bound'
    assert 'choose 1 of these 6 results' in offered[0][PROMPT].lower(), offered[0][PROMPT]
    assert has(foe, 'prone'), 'the successful-save branch ran no printed result'
    assert not links(me), 'the successful-save branch took a second printed result'


# ------------------------------------------------------------------------- Laughing Theft of Timing
def test_laughing_theft_of_timing_needs_a_creature_you_affected_with_a_trick_finish_or_feint():
    """"A creature you affected with a Monkey Style Trick, Finish, or feint this turn" -- the printed scope. An ordinary
    weapon attack of this fighter's own is none of those, so it never opens the reaction; a printed Trick does."""
    from combat import typed_reactions as reactions
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING')
    row = next(row for row in reactions._ordered_generic_rows(engine, me.entity_id, 'creature_d20')
               if row.get('feature_id') == M + 'LAUGHING_THEFT_OF_TIMING')
    assert not reactions._subject_ok(engine, me, foe, row), 'the theft answered a creature the fighter never touched'
    me.reaction_available = True   # test-only: each probe below asks "would this roll be penalised?" on its own
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] == 0
    cast(engine, 'Jian')   # a plain sword hit: no Trick, no Finish, no feint
    me.reaction_available = True
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] == 0, \
        'a plain weapon attack is not a Monkey Style Trick, Finish or feint'

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING', extras=(M + 'LAUGHING_TRIP',))
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    cast(engine, 'Laughing Trip')   # "Laughing Trip - Caper, Trick": a printed Trick that hit that creature
    me.reaction_available = True
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] < 0, 'the printed 1d6 penalty never reached the roll'


def test_a_monkey_link_finish_also_qualifies_the_creature_it_was_spent_on():
    """The printed scope names a Finish too, and a Finish rides an ordinary weapon's events, so what the fight records is
    the link the fighter spent against that creature. The Finishes go by their own option keys; the labels are what a
    player reads."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING')
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    cast(engine, 'Capering Footwork')
    asked = []
    answering(engine, 'tap', asked)
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] == 0, 'the fighter had not spent a Finish yet'
    from tests.equipment_readiness import ready_weapon

    ready_weapon(engine, 'Gun (Staff) attack')
    cast(engine, 'Gun (Staff) attack')
    assert monkey.FINISHED_ON + foe.entity_id in me.turn_flags, 'the base Finish left no record of the creature it hit'
    assert not links(me), 'the Tap Finish was not paid for'
    assert 'Tap Finish' in str(questions(asked, 'monkey_finish')[0][LABELS]), 'a player is not shown the printed label'
    me.reaction_available = True   # test-only: that staff hit already spent this fixture's Reaction
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] < 0, 'a printed Finish did not open the reaction'


@pytest.mark.parametrize('dc,owed', [(1, False), (200, False), (16, True)])
def test_laughing_theft_answers_only_when_its_own_penalty_made_the_roll_fail(dc, owed):
    """"If the triggering roll fails because of this penalty, choose one: ..." -- over one real penalised saving throw
    (Laughing Trip's Finish). The list is the reward for the penalty turning a success into a failure: a roll that
    succeeded anyway (dc 1) and a roll that failed anyway (dc 200) both get nothing, and only the roll the 1d6 broke
    (dc 16) is answered."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING', extras=(M + 'LAUGHING_TRIP',), dc=dc)
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    asked = []
    answering(engine, 'create a Monkey Link that lasts until the end of your next turn', asked)
    before = len(engine.events)
    cast(engine, 'Laughing Trip')
    rolled = [event for event in engine.events[before:] if event.event_type == 'SAVE_ROLLED' and event.actor_id == foe.entity_id]
    assert len(rolled) == 1, 'the printed Finish did not force its saving throw'
    penalty = [roll for roll in engine.rolls if roll.reason == f'REACTION:{M}LAUGHING_THEFT_OF_TIMING']
    assert len(penalty) == 1, penalty
    total, faced = int(rolled[0].payload['total']), int(rolled[0].payload['dc'])
    assert (total < faced <= total + penalty[0].total) is owed, (dc, total, faced, penalty[0].total)
    assert bool(questions(asked, 'theft')) is owed, (dc, asked)
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its pending state behind'
    if owed:
        assert links(me), 'the printed list was answered but its Monkey Link did not happen'
    else:
        assert len(links(me)) == 1, 'a roll the penalty did not break still produced a printed result'


# ------------------------------------------------------------------------- Laughing Theft of Timing: the roll it reserved
TRICK = M + 'LAUGHING_TRIP'
ENEMY = 'auto85:enemy'
SPHERE = 'tianxia.sphere.monkey_style'
EXTRA_ATTACK = 'tianxia.path.body_refining.feature.extra_attack'   # the sheet's own Extra Attack (attacks_by_cl)


def fighter(actor_id, talents=(), *, cl=20, dc=50):
    """One real compiled fighter for this test. Combat bakes action ids out of the sheet, so two owners of one sphere
    need two different sheets -- the Cultivation Level is what differs between them here."""
    from combat.factory_compiler import compile_character

    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.' + name, 'quantity': 1}
                                                  for name in ('jian', 'gun')]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
                                          'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [SPHERE] if talents else [], 'learned_talent_record_ids': list(talents)}},
        actor_id=actor_id)


def table(bundles, *, teams, squares, seed='AUTO85R1F1'):
    """A real fight of these compiled fighters, the first of them acting: the two-fighter shape tests/test_auto_elements.py
    drives. HP is raised so a strike cannot end the fight before the roll this test reads."""
    from combat.gate4_engine import Gate4ControllerEngine

    ids = [bundle['actor_id'] for bundle in bundles]
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(copy.deepcopy(bundle) for bundle in bundles),
                                   roster_setup={'primary_actor_ids': ids, 'team_by_actor': dict(zip(ids, teams)),
                                                 'starting_positions': squares})
    engine.state.current_slot_index = engine.state.initiative_order.index(ids[0])
    engine.state.current_actor_id = ids[0]
    engine._system_start_turn()
    for state in engine.state.actors.values():
        state.maximum_hp = state.current_hp = 2000
    return engine


def turn_of(engine, actor_id):
    """That fighter's turn begins (the switch tests/test_auto_elements.py makes by hand)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def open_turn(engine, actor_id):
    """An open table for that fighter: a question with nobody answering takes its printed default."""
    engine._active_intent = ActionIntent(intent_id='auto85r1', decision_id='auto85r1', candidate_id='auto85r1',
                                         state_version=0, actor_id=actor_id, target_ids=())
    engine._gate4_reaction_cache = {}


def use(engine, actor_id, name):
    """One real table action, by ``actor_id``. A weapon action readies its own weapon first, exactly as ``cast`` does."""
    from tests.equipment_readiness import ready_weapon

    attacks = [action for action in engine.action_catalog.values() if action.owner_id == actor_id and name in action.display_name
               and any(effect.get('type') == 'attack' for effect in ((action.parameters or {}).get('typed') or {}).get('effects') or [])]
    if attacks:
        ready_weapon(engine, min(attacks, key=lambda action: len(action.display_name)).display_name)
    open_turn(engine, actor_id)
    candidate = min((row for row in engine.legal_candidates() if row.actor_id == actor_id and name in row.display_name),
                    key=lambda row: (len(row.display_name), row.candidate_id))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def duel(ac=-50, *, bonus=40, seed='AUTO85R1F1', melee_armour_bonus=0, defender_hold=None, afterimages=0, guardian=None):
    """A settlement fixture: a qualifying Trick save checkpoint occurs during the enemy's turn, then its real sword
    attack is the roll Laughing Theft of Timing answers. The earlier Trip retains the fixture's deterministic rolls;
    it no longer qualifies on its own after changing turns. ``ac`` is the owner's own armour class, so
    the test decides hit or miss; the enemy's attack bonus is pinned so the roll is the same on every run.
    ``melee_armour_bonus`` adds that armour only against a melee attack, the shape a defensive AC bonus has: the roll is
    made against ``ac`` alone, and only the defence pipeline afterwards has to beat more. ``defender_hold`` is one
    ``(condition_id, source_id, data)`` hold put on the owner before it acts, in the shape a defensive ability's own choice
    puts there (Perfect Breath's "+1 AC against that creature", answered by its own ``hit_response``).
    ``afterimages`` puts that many afterimages on the owner in the shape Mirror-Monkey Technique's own cast puts them
    there, because its printed cast and the printed Trick are both Actions and a fighter gets one."""
    owner = fighter(ME, (M + 'LAUGHING_THEFT_OF_TIMING', TRICK) + ((M + 'MIRROR_MONKEY_TECHNIQUE',) if afterimages else ()))
    enemy = fighter(ENEMY)
    bundles, teams = [owner, enemy], ['team:a', 'team:b']
    squares = {ME: {'x': 3, 'y': 6}, ENEMY: {'x': 4, 'y': 6}}
    if guardian is not None:
        bundles.append(guardian)
        teams.append('team:a')
        squares[guardian['actor_id']] = {'x': 3, 'y': 5}
    engine = table(bundles, teams=teams, squares=squares, seed=seed)
    if guardian is not None:
        from tests.equipment_readiness import ready_weapon

        turn_of(engine, guardian['actor_id'])
        ready_weapon(engine, 'Ji (Halberd) attack (Constitution)')
        engine.state.actors[guardian['actor_id']].reaction_available = False
        turn_of(engine, ME)
    me, foe = engine.state.actors[ME], engine.state.actors[ENEMY]
    me.armor_class = ac
    foe.armor_class = -50           # the printed Trick lands, so it opens the printed scope
    if melee_armour_bonus:
        engine._add_modifier(me, 'test:auto85r2f1.rechecked_armour', 'armor_class_vs_melee', 'ADD',
                             int(melee_armour_bonus), 'SELF', expires_on='START_OF_SELF_NEXT_TURN')
    if defender_hold:
        engine._apply_condition(me, defender_hold[0], defender_hold[1], me.entity_id,
                                expires_on='START_OF_SELF_NEXT_TURN', data=dict(defender_hold[2] or {}))
    if afterimages:
        engine._apply_condition(me, monkey.MIRROR, 'passive:' + monkey.MIRROR_TALENT, me.entity_id, expires_on='CONCENTRATION_END',
                                data={'label': f'Mirror-Monkey Technique: {int(afterimages)} afterimage(s)', 'images': int(afterimages)})
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    use(engine, ME, 'Laughing Trip')
    me.reaction_available = True   # test-only: the Trip's own Finish already spent this round's Reaction on the enemy's
    turn_of(engine, ENEMY)         # saving throw, so the enemy attack below is penalised in its own right
    # These tests isolate the penalised roll's settlement, not the earlier turn's scope. Arrange the current-turn
    # prerequisite through the real save-record hook; the service regressions separately deliver and reload that hook.
    trip = next(action for action in engine.action_catalog.values()
                if action.owner_id == ME and action.display_name == 'Laughing Trip')
    context = te.Context(engine, me, trip, None, trip.parameters['typed'], [foe], foe, {})
    monkey.trick_or_finish_forced_save(context, foe, 'DEX', [])
    if guardian is not None:
        engine.state.actors[guardian['actor_id']].reaction_available = True
    from tests.equipment_readiness import ready_weapon

    ready_weapon(engine, 'Jian (Straight Sword) attack')
    open_turn(engine, ENEMY)
    candidate = next(row for row in engine.legal_candidates()
                     if row.actor_id == ENEMY and row.display_name == 'Jian (Straight Sword) attack' and ME in (row.target_ids or ()))
    typed = engine.action_catalog[candidate.source_definition_id].parameters['typed']
    typed['numbers'] = {**typed['numbers'], 'attack_bonus': bonus}
    return engine, me, foe, candidate


def strike(engine, candidate):
    """That pinned enemy strike, made."""
    engine.execute_intent(ActionIntent(intent_id='strike', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ENEMY, target_ids=candidate.target_ids))
    return [event for event in engine.events if event.event_type == 'ATTACK_ROLLED' and event.actor_id == ENEMY][-1]


def penalty_of(engine):
    """The 1d6 Laughing Theft of Timing rolled for that roll."""
    rolls = [roll for roll in engine.rolls if roll.reason == f'REACTION:{M}LAUGHING_THEFT_OF_TIMING']
    return int(rolls[-1].total) if rolls else 0


def unbroken_roll(seed='AUTO85R1F1'):
    """What the enemy's own attack roll would have been without the 1d6, measured once: the printed rule is "if the
    triggering roll fails BECAUSE OF THIS PENALTY", so a test has to know both numbers. Same seed, same pinned bonus, so
    the roll a test then makes is the roll that was measured."""
    engine, _me, _foe, candidate = duel(-50, seed=seed)
    struck = strike(engine, candidate)
    amount = penalty_of(engine)
    assert amount > 0, 'the printed 1d6 never reached that attack roll'
    return int(struck.payload['total']) + amount


@pytest.mark.parametrize('ac,owed', [(-50, False), (100, False)])
def test_a_penalised_enemy_attack_theft_owes_nothing_for(ac, owed):
    """"If the triggering roll fails because of this penalty, choose one: ..." -- an enemy attack roll the 1d6 did NOT
    break is not answered: one that landed (the printed Trick's own creature) and one that missed anyway (an AC no roll
    could have reached) both owe nothing, and the reservation is cleared either way so no later roll can pick it up."""
    from combat.ext import monkey

    asked = []
    engine, me, foe, candidate = duel(ac)
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    assert struck.payload['provisional_hit'] is bool(ac == -50), struck.payload
    assert bool(questions(asked, 'theft')) is owed, (ac, [(row[CHECKPOINT], row[PROMPT]) for row in asked])
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its reservation behind'


def test_a_penalised_enemy_attack_the_penalty_broke_answers_the_printed_list_once():
    """The printed list is the reward for the penalty turning a success into a failure: the enemy's sword roll is measured
    against an AC of exactly its own unpenalised total, so the 1d6 is what made the attack miss, and the list is asked --
    once. The enemy's own forced save earlier that turn (Laughing Trip's Finish) is an older roll of that same creature
    and must not be read as this one's."""
    from combat.ext import monkey

    ac = unbroken_roll()
    asked = []
    engine, me, foe, candidate = duel(ac)
    answering(engine, IMPROVISED, asked)
    assert [event for event in engine.events if event.event_type == 'SAVE_ROLLED' and event.actor_id == ENEMY], \
        'the printed Trick forced no save of its own'
    struck = strike(engine, candidate)
    total, faced = int(struck.payload['modified_total']), int(struck.payload['target_ac'])
    amount = penalty_of(engine)
    assert (total, faced, amount) == (ac - amount, ac, amount), (total, faced, amount)   # the 1d6 is exactly what missed
    offered = questions(asked, 'theft')
    assert len(offered) == 1, [(row[CHECKPOINT], row[PROMPT]) for row in offered]
    assert monkey.PENDING not in me.turn_flags
    assert [key for state in engine.state.actors.values() if state is not me
            for key in state.turn_flags if key.startswith(monkey.AFFECTED_ON)] == [], \
        'the printed scope was recorded on a fighter that forced nothing'
    swings = [event for event in engine.events if event.event_type == 'ATTACK_ROLLED' and 'improvised' in str(event.source_definition_id)]
    assert len(swings) == 1 and foe.entity_id in (swings[0].target_ids or ()), swings


def _measured_penalty_roll(ac):
    """One real penalised enemy attack, measured once: the total that roll ended up with and the 1d6 Laughing Theft of
    Timing subtracted. The duel is built from a fixed seed and a pinned attack bonus, so a test that then rebuilds the
    same duel reads the very same two numbers (unbroken_roll does the same for the unpenalised total)."""
    asked = []
    engine, _me, _foe, candidate = duel(ac)
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    amount = penalty_of(engine)
    assert amount > 0, 'the printed 1d6 never reached that attack roll'
    return int(struck.payload['modified_total']), amount, int(struck.payload['natural_result'] or 0)


def test_theft_owes_the_list_when_a_rechecked_ac_is_what_the_1d6_broke():
    """"If the triggering roll fails because of this penalty, choose one: ..." -- an attack that hit as it was rolled and
    only missed because a defence then raised the AC it had to beat. The fight writes that ATTACK_ROLLED snapshot before
    any defence answers, so reading the AC off it alone sees a hit and settles nothing; the roll's own defence receipt is
    what says which AC the attack really faced. The 1d6 is owed here, because the same roll without it still reaches that
    higher AC -- the printed list is the penalty turning a success into a failure, not a bonus for any miss at all."""
    from combat.ext import monkey

    rolled, amount, natural = _measured_penalty_roll(-50)
    raised = max(2, amount)        # this defence's own printed AC bonus; more than a point, and no more than the 1d6
    asked = []
    engine, me, foe, candidate = duel(rolled - 1, melee_armour_bonus=raised)   # the same roll, meeting an AC it beats as rolled
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    recheck = [event for event in engine.events if event.event_type == 'PASSIVE_TRIGGERED'
               and isinstance((event.payload or {}).get('new_ac'), int)
               and event.payload.get('hit_after_recheck') is False]
    assert natural < 20, f'this roll ({natural}) would be a natural 20, which no AC recheck can turn into a miss'
    assert struck.payload['provisional_hit'] is True, 'the roll did not hit as it was rolled'
    assert int(struck.payload['target_ac']) == rolled - 1, struck.payload
    assert recheck, 'no defence rechecked this attack, so the rechecked AC was never exercised'
    assert recheck[0].payload['new_ac'] == rolled - 1 + raised, recheck[0].payload
    assert not [event for event in engine.events if event.event_type == 'ATTACK_FORCED_MISS'], \
        'this attack was forced to miss, so it never tested the rechecked AC'
    assert rolled < rolled - 1 + raised <= rolled + amount, (rolled, raised, amount)   # only the 1d6 could have missed it
    offered = questions(asked, 'theft')
    assert len(offered) == 1, [(row[CHECKPOINT], row[PROMPT]) for row in offered]
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its reservation behind'


def test_theft_owes_the_list_when_a_plug_in_defence_raised_the_ac_the_1d6_broke():
    """"If the triggering roll fails because of this penalty, choose one: ..." -- the same printed rule when the AC that
    turned the hit into a miss was raised by a defence that answers a hit in its own way instead of through the fight's
    recorded recheck: Perfect Breath's "+1 AC against that target until the start of your next turn", which its own
    hit_response answers with (combat/ext/karate.py). No ``new_ac``/``hit_after_recheck`` pair is recorded for that kind of
    defence, so this is the case only the attack's one outcome receipt can settle, and the 1d6 is owed here: the roll did
    reach the AC it was made against, and without the 1d6 it still would have."""
    from combat.ext import karate, monkey

    rolled, amount, natural = _measured_penalty_roll(-50)
    asked = []
    # the printed hold itself, put on the defender exactly as Perfect Breath's own choice puts it (karate.py)
    engine, me, foe, candidate = duel(rolled, defender_hold=(karate.GUARD, karate.PREFIX + 'perfect_breath',
                                                              {'against': ENEMY, 'label': 'Perfect Breath: +1 AC against that creature'}))
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    breath = [event for event in engine.events if event.event_type == 'PASSIVE_TRIGGERED'
              and event.source_definition_id == karate.PREFIX + 'perfect_breath']
    assert natural < 20, f'this roll ({natural}) would be a natural 20, which no AC can turn into a miss'
    assert struck.payload['provisional_hit'] is True, 'the roll did not hit as it was rolled'
    assert int(struck.payload['target_ac']) == rolled == int(struck.payload['modified_total']), struck.payload
    assert breath, 'Perfect Breath never answered this hit, so its printed +1 AC was never exercised'
    assert not [event for event in engine.events if event.event_type == 'ATTACK_FORCED_MISS'], \
        'this attack was forced to miss, so it never tested the raised AC'
    assert not [event for event in engine.events if event.event_type in ('PASSIVE_TRIGGERED', 'REACTION_RESOLVED')
                and isinstance((event.payload or {}).get('new_ac'), int)], \
        'a recorded recheck wrote the raised AC itself, so this did not test a defence that writes none'
    assert rolled < rolled + 1 <= rolled + amount, (rolled, amount)     # only the 1d6 could have missed that AC
    offered = questions(asked, 'theft')
    assert len(offered) == 1, [(row[CHECKPOINT], row[PROMPT]) for row in asked]
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its reservation behind'


@pytest.mark.parametrize('defense', ['tusks', 'guard'])
@pytest.mark.parametrize('owed', [True, False])
def test_theft_after_a_numerical_guard_depends_on_its_own_penalty(defense, owed):
    """Real attacks with two allied reactions: replacement AC or Guard's PB penalty.

    Rebuild the same seeded table after measuring its roll. The other defense
    either needs Theft to cause failure or would stop the attack on its own.
    """
    from combat.attack_outcomes import attack_outcome
    from combat.ext import elephant_sovereign, white_heron
    from tests.test_riders_c7 import sheet, JI

    guard_id = 'auto85:guardian'
    prefix = elephant_sovereign.PREFIX if defense == 'tusks' else white_heron.PREFIX
    feature = prefix + ('shelter_beneath_the_tusks' if defense == 'tusks' else 'one_legged_guard')
    ids = [feature] if defense == 'tusks' else [white_heron.PREFIX + 'crescent_body_integration', feature]
    sh = sheet(ids, items=(JI,))
    sh['path_and_subpath']['path_record_ids'] = ['tianxia.path.body_refining']
    guardian = compile_character(sh, actor_id=guard_id)

    def setup(ac, guard_ac):
        engine, me, foe, candidate = duel(ac, guardian=guardian, seed='SOLFAUTO85r5-' + defense)
        guard = engine.state.actors[guard_id]
        guard.armor_class = guard_ac
        asked = []
        # Answer by option identity rather than prompt order: Guard's granted
        # attack opens its own checkpoints before the enemy's reserved roll.
        polearm = next((a.source_definition_id for a in engine.action_catalog.values()
                        if a.owner_id == guard_id and a.display_name == 'Ji (Halberd) attack (Constitution)'), '')
        answering(engine, ('use', 'target', 'minus', polearm,
                          'create a Monkey Link that lasts until the end of your next turn'), asked)
        return engine, me, foe, guard, candidate, asked

    engine, me, foe, guard, candidate, asked = setup(-50, -50)
    measured = strike(engine, candidate)
    total, amount = int(measured.payload['modified_total']), penalty_of(engine)
    assert amount > 0 and 1 < int(measured.payload['natural_result']) < 20
    minus = int(guard.proficiency_bonus) if defense == 'guard' else 0
    threshold = total + (1 if owed else amount + 1)
    ac = total if defense == 'tusks' else threshold - minus
    assert ac <= total, 'the original target must be hit before the defense answers'
    engine, me, foe, guard, candidate, asked = setup(ac, threshold if defense == 'tusks' else -50)
    before = len(engine.events)
    struck = strike(engine, candidate)
    assert int(struck.payload['modified_total']) == total
    assert penalty_of(engine) == amount
    assert struck.payload['provisional_hit'] is True
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == feature
               for e in engine.events[before:]), 'the allied defense was never exercised'
    if defense == 'guard':
        assert questions(asked, 'one_legged_guard'), 'Guard never hit and offered its penalty'
        assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == guard_id for e in engine.events[before:])
    index = next(i for i, e in enumerate(engine.events) if e is struck)
    receipt = attack_outcome(engine, ENEMY, index)
    assert receipt is not None and receipt['armor_class'] == threshold
    assert me.current_hp == 2000 and guard.current_hp == 2000
    assert (total < threshold <= total + amount) is owed
    assert len(questions(asked, 'theft')) == int(owed)
    assert monkey.PENDING not in me.turn_flags


def _measured_decoy_roll(ac, seed):
    """One real penalised enemy attack that struck an afterimage, measured once: the total that roll ended up with, the 1d6
    Laughing Theft of Timing subtracted, the natural die, and whether the afterimage really answered. The duel is built
    from a fixed seed and a pinned attack bonus, so a test that then rebuilds the same duel reads the very same numbers
    (``_measured_penalty_roll`` measures the same two numbers without an afterimage in the way)."""
    asked = []
    engine, me, _foe, candidate = duel(ac, seed=seed, afterimages=2)
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    amount = penalty_of(engine)
    assert amount > 0, 'the printed 1d6 never reached that attack roll'
    struck_afterimage = [event for event in engine.events if event.source_definition_id == 'passive:' + monkey.MIRROR_TALENT
                         and 'afterimage' in str((event.payload or {}).get('log') or '')]
    assert struck_afterimage, 'the printed afterimage never drew this attack away, so the case was not exercised'
    return int(struck.payload['modified_total']), amount, int(struck.payload['natural_result'] or 0)


def test_theft_owes_nothing_when_a_defence_made_the_attack_miss_whatever_it_rolled():
    """"If the triggering roll fails because of this penalty, choose one: ..." -- an attack that something else made miss
    whatever it rolled is not this 1d6's doing, because taking the 1d6 away would not have let the attack through. The
    afterimage is exactly that: Mirror-Monkey Technique's "1-2: The attack targets an afterimage", answered by the plug-in's
    own ``hit_response``, which is not a comparison against any AC and so records no ``new_ac``, no ATTACK_FORCED_MISS and
    no outcome receipt. Reading its made-up AC ("one higher than the roll") as the AC the roll was beaten by is what offered
    this printed list for an attack that had nothing to do with the penalty, so nothing is owed here. The numbers below do
    pass the printed test on their own -- without the 1d6 the roll would have reached the AC -- which is what makes this the
    case only the provenance can settle."""
    from combat.ext import monkey

    # Batch 3 changes the deterministic draw sequence. This seed still exercises a real afterimage interception;
    # the measured roll, penalty, critical guard and no-Theft-reward assertions below remain unchanged.
    seed = 'AUTO85R4F1-1'
    rolled, amount, natural = _measured_decoy_roll(-50, seed)
    asked = []
    engine, me, foe, candidate = duel(rolled, seed=seed, afterimages=2)   # the same roll, meeting an AC it beats as rolled
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    drawn = [event for event in engine.events if event.source_definition_id == 'passive:' + monkey.MIRROR_TALENT
             and 'afterimage' in str((event.payload or {}).get('log') or '')]
    images = [int((c.data or {}).get('images') or 0) for c in me.conditions.values() if c.condition_id == monkey.MIRROR]
    assert natural != 1 and natural < 20, f'this roll ({natural}) can decide nothing about a miss'
    assert struck.payload['provisional_hit'] is True, 'the roll did not hit as it was rolled, so no defence was asked'
    assert int(struck.payload['target_ac']) == rolled == int(struck.payload['modified_total']), struck.payload
    assert drawn, 'the printed afterimage never drew this attack away, so the case was not exercised'
    assert images == [1], f'the afterimage the attack struck is still there: {images}'
    assert me.current_hp == 2000, 'the attack that struck an afterimage still hurt the fighter'
    assert not [event for event in engine.events if event.event_type == 'ATTACK_FORCED_MISS'], \
        'this attack recorded a forced miss, so it was not a hit_response that made it miss'
    assert not [event for event in engine.events if event.event_type in ('PASSIVE_TRIGGERED', 'REACTION_RESOLVED')
                and isinstance((event.payload or {}).get('new_ac'), int)], \
        'a recorded recheck wrote an AC of its own, so this did not test a defence that compares against none'
    assert rolled < rolled + 1 <= rolled + amount, (rolled, amount)     # only the 1d6 could have missed that AC: the trap
    assert not questions(asked, 'theft'), [(row[CHECKPOINT], row[PROMPT]) for row in asked]
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its reservation behind'


def test_a_defence_that_compares_no_ac_says_so_in_its_own_reply():
    """The ``hit_response`` contract, where the provenance lives: a reply that made an attack miss without comparing any AC
    declares no armor_class at all, so the fight keeps the AC the roll was made against and publishes no outcome receipt
    for it; a reply that raises a real AC still names it. Read through the normaliser every provider's reply goes through,
    because no fight can show both sides of it at once."""
    from combat import attack_outcomes

    assert attack_outcomes.hit_defense_reply(attack_outcomes.unconditional_miss()) == (None, False, 'forced', None), \
        'a forced miss still carried a number for a reader to mistake for an AC'
    assert attack_outcomes.hit_defense_reply((19, False)) == (19, False, 'terminal', None), \
        'a legacy reply is terminal and keeps the AC it names'
    assert attack_outcomes.hit_defense_reply({'armor_class': 19, 'hit': False, 'miss_reason': 'armor_class'}) == \
        (19, False, 'armor_class', None), 'a real AC comparison lost its AC'
    assert attack_outcomes.hit_defense_reply({'armor_class': 12, 'hit': False, 'miss_reason': 'natural_replaced',
                                              'natural_result': 1}) == (None, False, 'natural_replaced', 1), \
        'a replaced natural die is not an AC comparison either'
    for bad in ({'armor_class': 19, 'hit': False, 'miss_reason': 'armor_class', 'natural_result': 21},
                {'armor_class': None, 'hit': True, 'miss_reason': 'forced'},
                {'armor_class': None, 'hit': False, 'miss_reason': 'because'},
                {'hit': False, 'miss_reason': 'armor_class'}):
        try:
            attack_outcomes.hit_defense_reply(bad)
        except ValueError:
            continue
        raise AssertionError(f'the contract accepted {bad}')


def test_the_outcome_receipt_is_only_ever_the_attempt_being_resolved():
    """The receipt that says how high the AC really became belongs to one swing of one creature, and the boundary is the
    shared helper's own (``attack_outcomes.attempt_end``), not each consumer's: the creature swings, a first swing's receipt
    is published, it swings again -- an attempt with no receipt of its own -- and only then does a second receipt appear. A
    reader settling the first swing must never see the second swing's outcome, and a reader settling the second must see
    None until its own outcome exists. Read here directly, because the fight resolves a swing while its own receipt is on
    the table and no fight can show the mismatch."""
    from combat import attack_outcomes
    from tests.test_auto_support import ME

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING')

    def swing(reason):
        engine._append_event('ATTACK_ROLLED', f'test:auto85r4f1.{reason}', actor_id=foe.entity_id,
                             target_ids=(me.entity_id,), payload={'reason': f'test:auto85r4f1.{reason}'})
        return len(engine.events) - 1

    first = swing('first')
    attack_outcomes.record_attack_outcome(engine, foe, 19, 'test:auto85r4f1.guard')
    assert attack_outcomes.attack_outcome(engine, foe.entity_id, first) == {
        'actor_id': foe.entity_id, 'recorded': first + 1, 'armor_class': 19, 'source_id': 'test:auto85r4f1.guard'}, \
        'the attempt being resolved cannot read the outcome its own defence published'
    assert attack_outcomes.attack_outcome(engine, me.entity_id, first) is None, "another creature read this swing's outcome"
    second = swing('second')
    assert attack_outcomes.attack_outcome(engine, foe.entity_id, second) is None, \
        'a later swing with no outcome of its own read an earlier one'
    attack_outcomes.record_attack_outcome(engine, foe, 21, 'test:auto85r4f1.second_guard')
    assert attack_outcomes.attack_outcome(engine, foe.entity_id, first) is None, \
        'the first swing read the second swing\'s outcome'
    assert attack_outcomes.attack_outcome(engine, foe.entity_id, second) == {
        'actor_id': foe.entity_id, 'recorded': second + 1, 'armor_class': 21, 'source_id': 'test:auto85r4f1.second_guard'}
    assert attack_outcomes.attempt_end(engine, foe.entity_id, second) == len(engine.events), \
        'an attempt with no next swing ends at the fight\'s present, not at some older event'


def test_theft_owes_nothing_for_an_attack_something_else_forced_to_miss(monkeypatch):
    """"If the triggering roll fails because of this penalty, choose one: ..." -- an attack that something else made miss
    whatever it rolled (a forced miss, which even beats a natural 20) is not this 1d6's doing, because taking the 1d6
    away would not have let the attack through. The numbers alone pass that test here -- without the penalty the roll
    would have reached the AC -- so this is the case only the fight's own ATTACK_FORCED_MISS receipt can settle, and it
    owes nothing."""
    from combat.ext import monkey
    from tests.test_lock_choices import install

    rolled, amount, natural = _measured_penalty_roll(-50)
    asked = []
    engine, me, foe, candidate = duel(rolled + 1)     # the same roll, facing an AC it cannot reach
    def rebuke(inner, attacker, defender, intent, context):
        if context.get('source_id') != candidate.source_definition_id:
            return None
        return {'force_miss': True, 'source_id': 'test:auto85r2f1.rebuke', 'label': 'Sleeve-Pulling Rebuke'}

    install(monkeypatch, 'before_attack', rebuke)     # the duel is built first: the printed Trick needed the real hooks
    answering(engine, IMPROVISED, asked)
    struck = strike(engine, candidate)
    forced = [event for event in engine.events if event.event_type == 'ATTACK_FORCED_MISS']
    assert forced, 'this attack was never forced to miss, so the case was not exercised'
    assert forced[0].payload['roll_id'] == struck.payload['roll_id'], forced[0].payload
    assert natural != 1 and rolled < rolled + 1 <= rolled + amount, \
        'the printed numbers do not pass, so nothing was decided by the 1d6 in the first place'
    assert not questions(asked, 'theft'), [(row[CHECKPOINT], row[PROMPT]) for row in asked]
    assert monkey.PENDING not in me.turn_flags, 'the settled roll left its reservation behind'


def test_only_this_fighters_own_forced_save_opens_their_theft():
    """"a creature YOU affected with a Monkey Style Trick, Finish, or feint this turn" -- one Monkey Style fighter's save
    does not open another's reaction. Two real owners, the second Tricks the enemy and forces its save; the first, who has
    touched nothing, gets no penalty, and the second does."""
    from combat.ext import monkey

    first, second, enemy = fighter(ME, (M + 'LAUGHING_THEFT_OF_TIMING',)), fighter('auto85:second', (M + 'LAUGHING_THEFT_OF_TIMING', TRICK), cl=12), fighter(ENEMY)
    engine = table([second, first, enemy], teams=['team:a', 'team:a', 'team:b'],
                   squares={'auto85:second': {'x': 4, 'y': 7}, ME: {'x': 2, 'y': 2}, ENEMY: {'x': 5, 'y': 7}})
    mine, theirs, foe = engine.state.actors[ME], engine.state.actors['auto85:second'], engine.state.actors[ENEMY]
    theirs.armor_class = -50
    monkey.create(engine, theirs, 'test', 'a printed link', counted=False)
    use(engine, 'auto85:second', 'Laughing Trip')
    assert [event for event in engine.events if event.event_type == 'SAVE_ROLLED' and event.actor_id == ENEMY], \
        "the second fighter's Trick forced no save of its own"
    for other in engine.state.actors.values():
        other.reaction_available = False
    mine.reaction_available = True
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] == 0, \
        "another fighter's forced save opened a Theft that never affected that creature"
    assert monkey.PENDING not in mine.turn_flags
    mine.reaction_available = False
    theirs.reaction_available = True
    assert tr.on_d20_pending(engine, foe, 'attack')['bonus'] < 0, 'the fighter that forced the save got no penalty'
    assert monkey.PENDING in theirs.turn_flags and monkey.PENDING not in mine.turn_flags


def test_the_theft_improvised_attack_is_one_attack_for_a_fighter_with_extra_attack():
    """"make one improvised-weapon attack against that creature" -- one. The sheet's own Extra Attack compiles four swings
    into the fighter's Attack action, and a printed option that copies that action must not hand over all four."""
    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING', extras=(TRICK, EXTRA_ATTACK), dc=16)
    action = min((row for row in engine.action_catalog.values() if row.owner_id == ME and row.display_name == 'Improvised weapon attack'),
                 key=lambda row: len(row.display_name))
    compiled_count = int((action.parameters['typed']['effects'][0]).get('count') or 1)
    assert compiled_count > 1, f'this fixture no longer carries Extra Attack ({compiled_count} attacks)'
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    asked = []
    answering(engine, IMPROVISED, asked)
    before = len(engine.events)
    cast(engine, 'Laughing Trip')
    swings = [event for event in engine.events[before:] if event.event_type == 'ATTACK_ROLLED' and 'improvised' in str(event.source_definition_id)]
    assert len(swings) == 1, f'extra_attack={compiled_count} attacks, the printed option made {len(swings)}'
    assert foe.current_hp < 2000, 'the single printed attack never reached the target'


def test_uncatchables_melee_weapon_attack_is_one_attack_for_a_fighter_with_extra_attack():
    """"make one melee weapon attack" (Uncatchable) -- one swing, even when the fighter's own Attack action has four."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'GREAT_SAGE_EQUAL_TO_HEAVEN', extras=(EXTRA_ATTACK,))
    cast(engine, 'Great Sage Equal to Heaven')
    from tests.equipment_readiness import ready_weapon

    ready_weapon(engine, 'Jian (Straight Sword) attack')
    asked = []
    answering(engine, f'Attack {foe.display_name} with your melee weapon', asked)
    before = len(engine.events)
    monkey._uncatchable(_ctx(engine, me, foe, 'Uncatchable'), me, foe)
    swings = [event for event in engine.events[before:] if event.event_type == 'ATTACK_ROLLED'
              and event.actor_id == me.entity_id and foe.entity_id in (event.target_ids or ())]
    assert len(swings) == 1, f'the printed "one melee weapon attack" made {len(swings)}'
    assert foe.current_hp < 2000, 'the single printed attack never reached the target'


# ------------------------------------------------------------------------- printed improvised-weapon attacks
IMPROVISED = "make one improvised-weapon attack against that creature"
MOON_ATTACK = "make one improvised-weapon attack against a creature within 20 feet using the projectile or a nearby object"


def test_theft_makes_its_printed_improvised_weapon_attack_not_its_readied_weapon():
    """"make one improvised-weapon attack against that creature" -- the fighter's own improvised weapon (the base rule's
    1d6, not the compiled 1d4 and not the readied sword), made against the creature the roll came from."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'LAUGHING_THEFT_OF_TIMING', extras=(M + 'LAUGHING_TRIP',), dc=16)
    monkey.create(engine, me, 'test', 'a printed link', counted=False)
    asked = []
    answering(engine, IMPROVISED, asked)
    before = len(engine.events)
    cast(engine, 'Laughing Trip')
    swings = [event for event in engine.events[before:] if event.event_type == 'ATTACK_ROLLED'
              and 'improvised' in str(event.source_definition_id)]
    assert len(swings) == 1, 'the printed improvised-weapon attack was not made'
    assert foe.entity_id in (swings[0].target_ids or ()), swings[0].target_ids
    damage = [event for event in engine.events[before:] if event.event_type == 'DAMAGE_ROLLED'
              and 'improvised' in str(event.source_definition_id)]
    assert damage and damage[0].payload['expression'].startswith('1d6'), \
        f"the printed Monkey Style improvised weapon deals 1d6, not {damage and damage[0].payload['expression']}"


def test_moon_improvised_attack_asks_which_creature_within_its_printed_twenty_feet():
    """"make one improvised-weapon attack against a creature within 20 feet using the projectile or a nearby object" -- a
    thrown improvised weapon, against a creature the owner picks from those in range; one 25 feet away is not offered."""
    _, engine, me, foe = fight(M + 'MONKEY_CATCHES_THE_MOON')
    ally = me.model_copy(deep=True)
    ally.entity_id, ally.position = 'auto85:ally', cell(8, 6)
    engine.state.actors[ally.entity_id] = ally
    near = me.model_copy(deep=True)
    near.entity_id, near.position, near.team_id = 'auto85:near', cell(7, 3), foe.team_id
    engine.state.actors[near.entity_id] = near
    far = me.model_copy(deep=True)
    far.entity_id, far.position, far.team_id = 'auto85:far', cell(7, 12), foe.team_id
    engine.state.actors[far.entity_id] = far
    foe.position = cell(4, 6)
    me.position = cell(7, 6)
    asked = []
    answering(engine, [['cell:7,6'], MOON_ATTACK, near.entity_id], asked)
    before = len(engine.events)
    tr.on_attack_missed(engine, foe, ally, {'range_ft': 30, 'source_definition_id': 'system:test', 'action_name': 'a longbow shot'})
    offered = questions(asked, 'catches_the_moon_target')
    assert offered, [row[CHECKPOINT] for row in asked]
    assert sorted(offered[0][OPTIONS]) == sorted([foe.entity_id, near.entity_id]), offered[0][OPTIONS]
    read = offered[0][PROMPT]
    assert 'choose the creature within 20 feet to attack' in read.lower(), read
    assert f'affecting {ally.display_name}' in read, f'the question did not name the missed ally: {read}'
    swings = [event for event in engine.events[before:] if event.event_type == 'ATTACK_ROLLED'
              and 'improvised' in str(event.source_definition_id)]
    assert len(swings) == 1, 'the printed improvised-weapon attack was not made'
    assert swings[0].target_ids == (near.entity_id,), swings[0].target_ids
    assert 'thrown' in str(swings[0].source_definition_id), swings[0].source_definition_id
    assert near.current_hp < 2000 and far.current_hp == 2000, 'the printed range or the chosen recipient was ignored'


# ------------------------------------------------------------------------- Monkey Catches the Moon
def test_monkey_catches_the_moon_steps_then_gives_the_missed_ally_half_cover():
    """"Move up to 10 feet ... choose one: ... give the missed ally Half Cover until the start of your next turn"."""
    _, engine, me, foe = fight(M + 'MONKEY_CATCHES_THE_MOON')
    ally = me.model_copy(deep=True)
    ally.entity_id = 'auto85:ally'
    ally.position = cell(2, 7)  # next to where the printed 10-foot step ends
    engine.state.actors[ally.entity_id] = ally
    asked = []
    answering(engine, [['cell:2,6'], 'give the missed ally Half Cover until the start of your next turn'], asked)
    spec = {'range_ft': 30, 'source_definition_id': 'system:test', 'action_name': 'a longbow shot'}
    tr.on_attack_missed(engine, foe, ally, spec)
    assert (me.position.x, me.position.y) == (2, 6), 'the printed 10-foot step did not happen'
    assert questions(asked, 'moon'), asked
    assert any(c.condition_id == 'condition:typed.monkey_half_cover' for c in ally.conditions.values()), \
        list(ally.conditions)
    assert engine._cover_bonus_actor_to_actor(foe, ally) == 2, 'the printed Half Cover is not counted'


HALF_COVER = 'give the missed ally Half Cover until the start of your next turn'


def moon_at(me_at, *, foe_at=(4, 6), ally_at=(8, 6)):
    """A ranged attack by ``foe_at`` that missed the ally at ``ally_at``, with the fighter at ``me_at``."""
    _, engine, me, foe = fight(M + 'MONKEY_CATCHES_THE_MOON')
    ally = me.model_copy(deep=True)
    ally.entity_id = 'auto85:ally'
    engine.state.actors[ally.entity_id] = ally
    me.position, foe.position, ally.position = cell(*me_at), cell(*foe_at), cell(*ally_at)
    return engine, me, foe, ally


def missed(engine, foe, ally, asked, answers):
    answering(engine, answers, asked)
    tr.on_attack_missed(engine, foe, ally, {'range_ft': 30, 'source_definition_id': 'system:test', 'action_name': 'a longbow shot'})
    return questions(asked, 'moon')


@pytest.mark.parametrize('where,note', [((8, 7), 'beside the missed creature'), ((6, 5), 'beside the middle of the shot')])
def test_moon_may_move_zero_feet_and_still_ends_beside_the_missed_attack(where, note):
    """"Move up to 10 feet ... If you end this movement adjacent to the missed attack's path or target space, choose
    one: ..." -- "up to 10 feet" permits zero feet, so a fighter already where the printed condition is met is still asked
    and still chooses. Covers the target space (beside the missed ally) and the flight itself (beside the shot's line)."""
    engine, me, foe, ally = moon_at(where)
    asked = []
    offered = missed(engine, foe, ally, asked, [[f'cell:{where[0]},{where[1]}'], HALF_COVER])
    assert (me.position.x, me.position.y) == where, 'staying put is a legal "up to 10 feet"'
    assert offered, f'{note}: the printed list was not asked'
    assert any(c.condition_id == 'condition:typed.monkey_half_cover' for c in ally.conditions.values()), note


def test_moon_does_not_open_its_list_for_standing_beside_the_creature_that_fired():
    """The printed words are "adjacent to the missed attack's path or target space", not the attacker. A fighter beside
    the shooter and out in the open gets no list."""
    engine, me, foe, ally = moon_at((3, 5))
    asked = []
    assert not missed(engine, foe, ally, asked, [[f'cell:3,5'], HALF_COVER]), \
        'proximity to the attacker alone is not the printed condition'
    assert not any(c.condition_id == 'condition:typed.monkey_half_cover' for c in ally.conditions.values())
    said = [str((event.payload or {}).get('log') or '') for event in engine.events if event.event_type == 'PASSIVE_TRIGGERED']
    assert any('you did not end next to where the missed shot flew' in line for line in said), said


def test_moon_declining_the_printed_movement_asks_no_list():
    """The printed list is the second sentence of the printed movement: a fighter who declines the movement never ends
    it anywhere, so there is nothing to choose."""
    engine, me, foe, ally = moon_at((8, 7))
    asked = []
    assert not missed(engine, foe, ally, asked, ['DECLINE']), 'a declined movement still ran the printed list'


def test_improvised_master_tap_finish_adds_a_die_and_the_proficiency_bonus():
    """Improvised Master: "if you hit with an improvised weapon and spend your Monkey Link on Tap Finish, increase the
    extra damage to 1d6 + Proficiency Bonus" -- combat/ext/monkey.py already ran it while the line still said the GM's,
    so the owner line is gone and the Tap Finish a player is offered says so."""
    from combat.ext import monkey

    _, engine, me, foe = fight(M + 'IMPROVISED_MASTER')
    cast(engine, 'Capering Footwork')
    linked(engine, me)
    action = min((a for a in engine.action_catalog.values() if a.owner_id == ME and 'Improvised weapon attack' in a.display_name),
                 key=lambda a: len(a.display_name))
    action = action.model_copy(update={'source_definition_id': f'{action.source_definition_id}#improvised'})
    options = monkey._finish_options(te.Context(engine, me, action, None, action.parameters['typed'], [foe], foe, {}), foe)
    assert options['tap'] == f'Tap Finish: +1d6 + {me.proficiency_bonus} Bludgeoning (Improvised Master)', options


def test_the_scope_has_no_new_gm_lines_for_what_the_table_now_runs():
    """A printed line the engine resolves must not also sit in the fight's GM list (the report's own metric)."""
    from combat.factory_compiler import _gm_lines

    for key in (M + 'LAUGHING_THEFT_OF_TIMING', M + 'IMPROVISED_MASTER'):
        assert _gm_lines(AUTH[key].get('riders') or [], AUTH[key], AUTH[key].get('effects') or []) == [], key
