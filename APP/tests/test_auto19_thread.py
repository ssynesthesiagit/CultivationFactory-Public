"""Thread Sphere automation lane AUTO19 (2026-10-04), review fixes AUTO19f1 (2026-10-05): the printed effects
that used to cost resources and do nothing, and Snaring Crossing's missing failure branch.

Before this lane, in a real table fight:
  * Puppet-Line Correction spent 2 CP on every eligible roll and applied no bonus at all -- its typed effect was
    the whole printed text as a rider, so the generic creature_d20 reaction had nothing to sign;
  * Borrow the Ally's Arm spent 1 CP on a missed melee attack and added nothing;
  * Snaring Crossing compiled no reaction at all, and its typed saving throw had an EMPTY failure branch, so
    "On a failure, its speed becomes 0 until the end of the current turn" never happened.

AUTO19f1 corrected what the independent review of that lane found, and those corrections are the point of half of
this file:
  * Snaring Crossing answers at the movement STEP that crosses a Thread Line, against the printed line geometry,
    instead of after the mover walked its whole submitted path. Every Snaring test below drives a real
    multi-square move; the hand-written MOVEMENT_COMMITTED receipts the lane used first cannot see a defect at
    the step, and are gone;
  * "only once per round" survives the Thread user's own turn start, and it refuses a second crossing by the same
    creature inside the same round;
  * pressing Pass on Snaring Crossing spends nothing, and the question put to the table carries its printed
    options, its labels and the creature it affects;
  * Puppet-Line Correction charges its printed 2 CP and its Reaction for the ATTEMPT whether or not the
    creature's Wisdom saving throw fails ("On a success, the roll is unaffected" is about the roll);
  * willingness is the rolling creature's own answer, asked through the shared consent transport, so a hostile
    creature can be helped when it agrees and an ally can refuse -- and Borrow the Ally's Arm is offered before
    Puppet-Line Correction for an ally, because it costs 1 CP rather than 2.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from combat import granted_movement
from combat import typed_executor as te
from combat.ext import thread_correction, thread_lines
from combat.ext.thread_common import LINE, mark_held_by, thread_line_cells
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.roll_checkpoints import rewrite_d20
from tests.h1_support import ROOT, bundle, ready
from tests.test_auto_support import AN, ME, _engine
from tests.test_zones import SHEET

AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
T = 'tianxia.talent.thread.'
PUPPET, BORROW, SNARING = T + 'puppet_line_correction', 'TAL_THREAD_BORROW_THE_ALLY_S_ARM', T + 'snaring_crossing'
OTHER_THREAD = T + 'severing_silk'
MARKED, WALKER, ALLY = 'actor:factory.auto19_marked', 'actor:factory.auto19_walker', 'actor:factory.auto19_ally'
WEAVER = 'actor:factory.h1'  # the Thread user on the arena board (the support duel's ME is another id)
FOCUS, QI = 'resource:core.martial_focus', 'resource:core.qi'
ORDER = (MARKED, WEAVER, WALKER, ALLY)


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50):
    """A real Factory character owning exactly one Thread talent (and that sphere's base abilities)."""
    from combat.factory_compiler import compile_character

    sphere = AUTH[key]['sphere_id']
    bases = [b for b, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
            'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [sphere],
            'learned_talent_record_ids': list(dict.fromkeys([*bases, key]))}}, actor_id=ME)


def _fight(key, foe_at=(4, 6)):
    engine = _engine(_compiled(key), foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    me.resources[FOCUS] = 1
    return engine, me, foe


def _line_on(engine, user, holder):
    engine._apply_condition(holder, te.mark_condition_id(LINE, user.entity_id), 'test', user.entity_id,
                            expires_on='UNTIL_REMOVED')


def _ally(engine, me, tag):
    ally = me.model_copy(deep=True)
    ally.entity_id = f'{tag}:ally'
    ally.team_id = me.team_id
    ally.position = ally.position.model_copy(update={'y': 7})  # the test map's adjacent square
    engine.state.actors[ally.entity_id] = ally
    return ally


def _save_roll(engine, subject, dc, source='test:save'):
    with engine.d20_scope({'kind': 'save', 'actor_id': subject.entity_id, 'target_id': subject.entity_id,
                           'source_id': source, 'source_actor_id': subject.entity_id, 'ability': 'DEX'}):
        return engine.roller.d20(modifier=0, actor_id=subject.entity_id, reason=f'SAVE:{source}:DEX')


def _check_roll(engine, subject, ability, dc, source='test:check'):
    """combat/typed_executor.py's ability-check path: check() rolls, adjust() rewrites that same roll."""
    with engine.d20_scope({'kind': 'check', 'actor_id': subject.entity_id, 'target_id': AN,
                           'source_id': source, 'source_actor_id': subject.entity_id, 'ability': ability, 'dc': dc}):
        return rewrite_d20(engine, engine.roller.raw_d20(modifier=0, actor_id=subject.entity_id,
                                                         reason=f'CHECK:{source}'))


def _attack_roll(engine, attacker, target, modifier=0, reach=5, source='test:attack'):
    spec = {'range_ft': reach, 'resolved_target_id': target.entity_id, 'declaration_done': True}
    with engine.d20_scope({'kind': 'attack', 'actor_id': attacker.entity_id, 'target_id': target.entity_id,
                           'spec': spec, 'source_id': source, 'source_actor_id': attacker.entity_id,
                           'attack_index': 1}):
        return engine.roller.d20(modifier=modifier, actor_id=attacker.entity_id, reason=f'ATTACK:{source}:1')


def _saves(engine, source, ability='DEX'):
    return [roll for roll in engine.rolls if roll.reason == f'SAVE:{source}:{ability}']


def _open_intent(engine, actor_id, intent_id='auto19f1'):
    """The active action the engine carries while it resolves a roll or a step (what execute_intent sets)."""
    engine._active_intent = ActionIntent(intent_id=intent_id, decision_id='d', candidate_id='c',
                                         state_version=engine.state.state_version, actor_id=actor_id)
    return engine._active_intent


# ------------------------------------------------------------------------------- Puppet-Line Correction
def test_puppet_line_correction_adds_the_proficiency_bonus_to_a_willing_connected_creature():
    engine, me, _ = _fight(PUPPET)
    ally = _ally(engine, me, 'puppet')
    _line_on(engine, me, ally)
    _save_roll(engine, ally, 10)
    assert me.resources[FOCUS] == 1  # the printed price is CP, not Martial Focus
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == me.proficiency_bonus
    assert rewritten[-1].payload['user_id'] == ME
    assert me.resources[QI] == 100 - 2 and not me.reaction_available
    assert any('Puppet-Line Correction' in str((e.payload or {}).get('log') or '')
               for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED')


def test_puppet_line_correction_charges_its_printed_price_even_when_the_creature_shrugs_it_off():
    """AUTO19f1: "Cost: 2 CP" and "On a success, the roll is unaffected." The printed activation is not refunded,
    so a creature that resists successfully still costs the weaver 2 CP and the Reaction and leaves the roll
    exactly as it was. The first cut of this lane made a resisted attempt free, which allowed repeated free tries."""
    engine, me, foe = _fight(PUPPET)
    _line_on(engine, me, foe)
    foe.saving_throws['WIS'] = 1000
    roll = _save_roll(engine, foe, 10)
    assert roll.total == roll.natural_result + roll.modifier
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert _saves(engine, PUPPET, 'WIS')  # the printed Wisdom saving throw was still made
    assert me.resources[QI] == 98 and not me.reaction_available


def test_puppet_line_correction_subtracts_the_proficiency_bonus_when_the_creature_fails_the_save():
    engine, me, foe = _fight(PUPPET)
    _line_on(engine, me, foe)
    foe.saving_throws['WIS'] = -1000
    _save_roll(engine, foe, 10)
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == -me.proficiency_bonus
    assert me.resources[QI] == 98 and not me.reaction_available


def test_puppet_line_correction_does_not_reach_an_unconnected_creature():
    engine, me, _ = _fight(PUPPET)
    _save_roll(engine, _ally(engine, me, 'loose'), 10)
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert me.resources[QI] == 100 and me.reaction_available


def test_puppet_line_correction_does_not_reach_beyond_thread_range():
    engine, me, _ = _fight(PUPPET, foe_at=(40, 6))
    far = _ally(engine, me, 'far')
    far.position = far.position.model_copy(update={'x': 40})
    engine.state.actors[far.entity_id] = far
    _line_on(engine, me, far)
    _save_roll(engine, far, 10)
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert me.resources[QI] == 100


def test_puppet_line_correction_reaches_30_feet_only_with_an_active_qi_thread():
    """Draw the Line: "Range: Mundane 20 feet, Qi Thread 30 feet." """
    from combat.ext.thread_weaving import QI_THREAD

    engine, me, _ = _fight(PUPPET, foe_at=(40, 6))
    far = _ally(engine, me, 'qi')
    # The map's squares are 5 feet: five cells away is 25 feet -- past mundane Thread range, inside Qi Thread range.
    far.position = far.position.model_copy(update={'x': me.position.x + 5, 'y': me.position.y})
    assert engine._distance_actor_to_actor(me, far) == 25
    engine.state.actors[far.entity_id] = far
    _line_on(engine, me, far)
    _save_roll(engine, far, 10)
    assert me.resources[QI] == 100  # 30 feet is out of mundane Thread range
    engine._apply_condition(me, QI_THREAD, 'test', ME, expires_on='UNTIL_REMOVED')
    _save_roll(engine, far, 10)
    assert me.resources[QI] == 98  # a Qi Thread of theirs reaches 30 feet


# ------------------------------------------------------------------------------- Borrow the Ally's Arm
def test_borrow_the_allys_arm_adds_the_proficiency_bonus_to_a_missed_melee_attack():
    engine, me, foe = _fight(BORROW)
    ally = _ally(engine, me, 'borrow')
    _line_on(engine, me, ally)
    roll = _attack_roll(engine, ally, foe, modifier=-20)  # a low roll against a high AC: a miss
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == me.proficiency_bonus
    # The receipt keeps the d20 as it was: the printed bonus is added to the roll, not a fresh die.
    assert rewritten[-1].payload['original']['total'] == roll.total - me.proficiency_bonus
    assert me.resources[QI] == 99 and not me.reaction_available


def test_borrow_the_allys_arm_answers_a_failed_ability_check():
    engine, me, _ = _fight(BORROW)
    ally = _ally(engine, me, 'check')
    _line_on(engine, me, ally)
    roll = _check_roll(engine, ally, 'STR', 30)  # "fails a Strength or Dexterity ability check"
    assert roll.total < 30 and me.resources[QI] == 99
    engine.end_turn()
    engine.end_turn()


def test_borrow_the_allys_arm_leaves_a_hit_alone():
    engine, me, foe = _fight(BORROW)
    ally = _ally(engine, me, 'hit')
    _line_on(engine, me, ally)
    _attack_roll(engine, ally, foe, modifier=40)
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert me.resources[QI] == 100 and me.reaction_available


def test_borrow_the_allys_arm_never_answers_an_enemy_roll():
    engine, me, foe = _fight(BORROW)
    _line_on(engine, me, foe)  # "a willing ally"
    _attack_roll(engine, foe, _ally(engine, me, 'target'))
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert me.resources[QI] == 100


# ------------------------------------------------------------------------------- Snaring Crossing, on real movement
#
# The board. The Thread user stands at (3,6) with its Thread Line mark on the creature at (7,6): Draw the Line
# runs the line "between yourself ... and the target", so the squares from x=3 to x=7 along y=6 are the line. The
# walker at (5,4) carries no line at all, so the only thing that can snare it is walking across that run of
# squares -- and the ally at (3,8) is off the line.
#
#   (3,6) WEAVER ......... (5,6) on the line ......... (7,6) MARKED
#   (5,4) WALKER                       (3,8) ALLY
ARENA = {WEAVER: (3, 6), MARKED: (7, 6), WALKER: (5, 4), ALLY: (3, 8)}


@lru_cache(maxsize=None)
def _bundles(talent):
    return (bundle(talent, actor_id=WEAVER, cl=20, dc=50),
            bundle(OTHER_THREAD, actor_id=MARKED, cl=5, dc=16),
            bundle(OTHER_THREAD, actor_id=WALKER, cl=5, dc=16),
            bundle(OTHER_THREAD, actor_id=ALLY, cl=5, dc=16))


@lru_cache(maxsize=None)
def _bundle(actor_id, mids):
    return bundle(mids, actor_id=actor_id, cl=5, dc=16)


def _arena(talent=SNARING, marks=(MARKED,), seed='AUTO19F1', extra=(), fly=(), lift=()):
    """A live four-creature Gate 4 fight -- real intents, real dice, real movement, a real choice transport.

    ``extra`` adds further fighters as (actor_id, mids, (x, y[, z])) -- a second Thread user, or a flyer on a
    square above the board -- and ``fly`` names those with a Fly Speed, so a step at a height is a real one.  They
    join the initiative order after the four above, so the existing turns and round boundaries do not move.
    ``lift`` then puts a fighter at an altitude after the fight has been built: the setup falls a creature that
    starts above the floor before it can hold a Fly Speed, which is the right behaviour and the wrong moment."""
    from combat.gate4_engine import Gate4ControllerEngine

    bundles = list(_bundles(talent))
    spots, teams, order = dict(ARENA), {WEAVER: 'team:a', MARKED: 'team:b', WALKER: 'team:b', ALLY: 'team:a'}, list(ORDER)
    for actor_id, mids, spot in extra:
        bundles.append(_bundle(actor_id, mids))
        spots[actor_id] = spot
        teams[actor_id] = 'team:a'
        order.append(actor_id)
    ids = [b['actor_id'] for b in bundles]
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=tuple(bundles),
        roster_setup={'primary_actor_ids': ids, 'team_by_actor': teams,
                      'starting_positions': {i: {'x': spots[i][0], 'y': spots[i][1]} for i in ids}})
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
        actor.armor_class = 12
        if actor.entity_id in fly:
            actor.fly_speed_ft = 30
    for actor_id, z in lift:
        actor = engine.state.actors[actor_id]
        actor.position = actor.position.model_copy(update={'z': z})
    engine.state.initiative_order = order
    engine.state.current_slot_index = 0
    engine.state.current_actor_id = order[0]
    engine._system_start_turn()
    ready(engine)
    for holder in marks:
        _line_on(engine, engine.state.actors[WEAVER], engine.state.actors[holder])
    return engine


def _turn(engine, actor_id):
    """Make it ``actor_id``'s turn with fresh economy (the helper the movement-step lock tests use)."""
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    actor.movement_remaining_ft = engine._effective_speed(actor)
    return actor


def _move(engine, actor_id, x, y, z=0):
    _turn(engine, actor_id)
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind.value == 'MOVE' and c.destination == Position(x=x, y=y, z=z))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f'auto19f1-move-{before}', decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return next(e for e in reversed(engine.events[before:]) if e.event_type == 'MOVEMENT_COMMITTED')


def _answer(pairs):
    """A reaction provider that answers by reaction_source_id fragment and records every request it is asked.

    Each recorded request carries the answer the table actually gave under 'answered', so a test can assert what
    the creature decided and not only that it was asked."""
    seen = []

    def provider(request):
        seen.append(request)
        for fragment, selection, options in pairs:
            if fragment in str(request['reaction_source_id']):
                decision = ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                            reaction_source_id=request['reaction_source_id'], selection=selection,
                                            option_ids=tuple(options))
                request['answered'] = (selection, list(options))
                return decision, None
        raise AssertionError(f'unexpected reaction asked: {request["reaction_source_id"]}')
    return provider, seen


def _by_reactor(answers):
    """A reaction provider that answers each chooser by its own id, and records what every chooser was asked and
    what it answered. Two Thread users whose lines cover the same step are two separate choosers."""
    seen = []

    def provider(request):
        seen.append(request)
        reactor = request['reactor_id']
        selection, options = answers[reactor]
        request['answered'] = (selection, list(options))
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=reactor,
                                reaction_source_id=request['reaction_source_id'], selection=selection,
                                option_ids=tuple(options)), None
    return provider, seen


def _focus(engine, actor_id=WEAVER):
    actor = engine.state.actors[actor_id]
    actor.resource_maximums.setdefault(FOCUS, 9)
    actor.resources[FOCUS] = 1


def test_snaring_crossing_stops_a_creature_on_the_near_edge_of_its_own_line():
    """The printed moment is the crossing. "On a failure, its speed becomes 0 until the end of the current turn",
    so the creature must not finish the step into the next square. Resolving on the movement receipt after the path
    ran -- what the lane did first -- let a creature walk its whole submitted path and only then lose its Speed,
    which is the printed effect arriving too late to stop anything."""
    engine = _arena()
    _focus(engine)
    engine.state.actors[MARKED].saving_throws['DEX'] = -1000
    receipt = _move(engine, MARKED, 8, 6)
    assert engine.state.actors[MARKED].position == Position(x=7, y=6)  # never entered the next square
    assert receipt.payload['path'] == [{'x': 7, 'y': 6}] and receipt.payload['cost_ft'] == 0
    assert engine._effective_speed(engine.state.actors[MARKED]) == 0
    assert engine.state.actors[WEAVER].resources[FOCUS] == 0 and not engine.state.actors[WEAVER].reaction_available
    assert _saves(engine, SNARING) and _saves(engine, SNARING)[-1].total < 50  # the printed Cultivation Save DC


def test_snaring_crossing_catches_an_unmarked_creature_that_walks_across_a_thread_line():
    """The printed trigger names the squares a Thread Line runs through, not the creature carrying the mark. A
    creature with no line on it that steps across one is snared, and is stopped on the near side of the line."""
    engine = _arena()
    _focus(engine)
    engine.state.actors[WALKER].saving_throws['DEX'] = -1000
    receipt = _move(engine, WALKER, 5, 8)  # (5,4) -> (5,8) passes (5,6), which is on the line
    assert engine.state.actors[WALKER].position == Position(x=5, y=5)
    assert receipt.payload['path'][-1] == {'x': 5, 'y': 5} and receipt.payload['cost_ft'] == 5
    assert engine._effective_speed(engine.state.actors[WALKER]) == 0
    assert engine.state.actors[WEAVER].resources[FOCUS] == 0


def test_snaring_crossing_leaves_movement_that_never_touches_a_line_alone():
    engine = _arena()
    _focus(engine)
    receipt = _move(engine, WALKER, 8, 4)  # the same unmarked creature, on a path that stays off the line
    assert engine.state.actors[WALKER].position == Position(x=8, y=4)
    assert receipt.payload['interrupted'] is False and len(receipt.payload['path']) == 4
    assert engine._effective_speed(engine.state.actors[WALKER]) == 30
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1 and engine.state.actors[WEAVER].reaction_available
    assert not _saves(engine, SNARING)


def test_snaring_crossing_printed_success_costs_ten_feet_and_lets_the_move_finish():
    """"On a success, its speed is reduced by 10 feet" -- nothing stops that crossing."""
    engine = _arena()
    _focus(engine)
    engine.state.actors[MARKED].saving_throws['DEX'] = 1000
    receipt = _move(engine, MARKED, 8, 6)
    assert engine.state.actors[MARKED].position == Position(x=8, y=6)
    assert receipt.payload['interrupted'] is False
    assert engine._effective_speed(engine.state.actors[MARKED]) == 20


def test_snaring_crossing_ends_at_the_end_of_the_crossing_creatures_turn():
    engine = _arena()
    _focus(engine)
    engine.state.actors[MARKED].saving_throws['DEX'] = -1000
    _move(engine, MARKED, 8, 6)
    assert engine._effective_speed(engine.state.actors[MARKED]) == 0
    engine.end_turn()   # the mover's own turn ends
    engine.end_turn()
    engine.end_turn()
    assert engine._effective_speed(engine.state.actors[MARKED]) == 30


def test_snaring_crossing_pressing_pass_spends_nothing():
    """The printed cost, the Reaction, the once-per-round limit and the effect are all untouched by a Pass. The
    first cut of this lane answered its own question when the player declined, so a Pass still charged CP and
    still applied the save."""
    engine = _arena()
    _focus(engine)
    provider, seen = _answer([('snaring_crossing', 'DECLINE', [])])
    engine.set_reaction_provider(provider)
    engine.state.actors[MARKED].saving_throws['DEX'] = -1000
    _move(engine, MARKED, 8, 6)
    assert engine.state.actors[MARKED].position == Position(x=8, y=6)  # the creature walked on
    assert engine._effective_speed(engine.state.actors[MARKED]) == 30
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1 and engine.state.actors[WEAVER].reaction_available
    assert not [key for key in engine.state.actors[WEAVER].turn_flags if 'snaring' in key]
    assert not _saves(engine, SNARING) and len(seen) == 1


def test_snaring_crossing_asks_the_thread_user_with_its_printed_options_and_the_creature_it_affects():
    engine = _arena()
    _focus(engine)
    provider, seen = _answer([('snaring_crossing', 'USE', ['cp'])])
    engine.set_reaction_provider(provider)
    engine.state.actors[MARKED].saving_throws['DEX'] = -1000
    _move(engine, MARKED, 8, 6)
    assert len(seen) == 1
    request = seen[0]
    assert request['reactor_id'] == WEAVER and request['reaction_source_id'] == 'choice:needle.snaring_crossing'
    assert request['extension_choice']['option_ids'] == ['focus', 'cp']
    assert request['extension_choice']['allow_decline'] is True
    trigger = request['choice_trigger']
    assert trigger['target_id'] == MARKED and trigger['name'] == 'Snaring Crossing'
    assert trigger['labels']['cp'].startswith('Spend 1 CP')  # the printed cost, spelled out
    prompt = trigger['prompt']
    assert 'Snaring Crossing' in prompt and engine.state.actors[MARKED].display_name in prompt
    assert 'Dexterity saving throw' in prompt and 'CP (cultivation points' in prompt and 'Reaction' in prompt


def test_snaring_crossing_keeps_its_once_per_round_limit_through_the_users_own_turn_start():
    """"A creature can be affected by your Snaring Crossing only once per round." The flag naming it lives in a
    turn's flags, and the engine clears those at the next turn start unless the key is one it keeps. The first cut
    of this lane used a key nothing keeps, so the Thread user's own turn start threw the printed limit away."""
    engine = _arena()
    _focus(engine)
    engine.state.actors[MARKED].saving_throws['DEX'] = 1000  # it saves, so it can still take its granted step
    _move(engine, MARKED, 8, 6)
    marker = {key: value for key, value in engine.state.actors[WEAVER].turn_flags.items() if 'snaring' in key}
    assert marker == {f'once_per_round:thread_snaring:{MARKED}': engine.state.round_number}
    round_now = engine.state.round_number

    _turn(engine, WEAVER)   # the Thread user's own turn starts, in the same round
    assert engine.state.round_number == round_now
    kept = {key: value for key, value in engine.state.actors[WEAVER].turn_flags.items() if 'snaring' in key}
    assert kept == marker   # the printed limit survived its owner's turn start
    _focus(engine)
    engine.state.actors[WEAVER].reaction_available = True

    # A second crossing by the same creature inside the same round, through the granted-movement seam the
    # movement-step documentation says shares this checkpoint.
    marked = engine.state.actors[MARKED]
    granted_movement.resolve_path(engine, marked, (marked.position, Position(x=7, y=6)), 'test:granted',
                                  feet=5, intent=_open_intent(engine, MARKED))
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1     # refused: nothing was spent
    assert engine._effective_speed(marked) == 30             # and no second -10 feet of Speed
    assert len(_saves(engine, SNARING)) == 1                 # only the printed saving throw of the first crossing


def test_snaring_crossing_costs_nothing_without_the_talent():
    engine = _arena(talent=OTHER_THREAD)
    _focus(engine)
    _move(engine, MARKED, 8, 6)
    assert engine.state.actors[MARKED].position == Position(x=8, y=6)
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1 and not _saves(engine, SNARING)


# -------------------------------------------------------------------- a Thread Line is a thing at a height
# The same line, read three ways.  The weaver's thread runs to the creature carrying its mark, so a mark on a
# ground creature makes a thread along the ground and a mark on a flyer raises it.
#
#   (3,6,0) WEAVER .. (5,6,2) on the raised line .. (7,6,4) MARKED, four squares up
#   (5,5,0) WALKER, on the ground under the thread      (5,5,2) FLIER, at the thread's height
FLYER = 'actor:factory.auto19_flier'


def _raised_line_arena(flier=True):
    """The weaver's Thread Line climbs to a mark four squares (20 feet) up, so the ground below it is clear. The
    marked creature and the flier are flyers, because they are up in the air and the table makes things fall."""
    return _arena(extra=((FLYER, OTHER_THREAD, (5, 5)),) if flier else (),
                  fly={MARKED, FLYER} if flier else {MARKED},
                  lift=(((MARKED, 4), (FLYER, 2)) if flier else ((MARKED, 4),)),
                  marks=(), seed='AUTO19F1-AIR')


def _raise_mark(engine):
    _line_on(engine, engine.state.actors[WEAVER], engine.state.actors[MARKED])
    return engine.state.actors[MARKED]


def test_a_thread_line_runs_at_the_height_its_mark_is_at():
    """Draw the Line: "you create a Thread Line between yourself ... and the target."  The thread is a physical
    line, so its cells carry the height of the run between the two creatures: the exact 3D traversal includes
    (5,6,2) on the way up to a mark 20 feet in the air, and no ground square at all."""
    engine = _raised_line_arena()
    marked = _raise_mark(engine)
    assert thread_line_cells(engine, engine.state.actors[WEAVER]) == {(3, 6, 0), (4, 6, 1), (5, 6, 2), (6, 6, 3), (7, 6, 4)}
    marked.position = marked.position.model_copy(update={'z': 0})
    assert thread_line_cells(engine, engine.state.actors[WEAVER]) == {(x, 6, 0) for x in range(3, 8)}

def test_snaring_crossing_reaches_a_creature_flying_through_the_thread_where_it_runs():
    """The positive half at a height: a flyer at the thread's own height is on it, and pays for stepping there."""
    engine = _raised_line_arena()
    _focus(engine)
    _raise_mark(engine)
    flier = engine.state.actors[FLYER]
    flier.saving_throws['DEX'] = 1000
    _move(engine, FLYER, 5, 6, 2)   # (5,5,2) -> (5,6,2): (5,6,2) is on the thread
    assert engine.state.actors[FLYER].position == Position(x=5, y=6, z=2)
    assert engine._effective_speed(flier) == 20      # "on a success, its speed is reduced by 10 feet"
    assert engine.state.actors[WEAVER].resources[FOCUS] == 0 and _saves(engine, SNARING)


def test_snaring_crossing_leaves_a_creature_that_steps_under_a_raised_thread_alone():
    """The negative half, and the bug the review found: the geometry used to drop the height, so a thread four
    squares up snared a creature walking along the floor beneath it -- spending the Thread user's Reaction and the
    printed payment, and stopping a walk that never crossed anything."""
    engine = _raised_line_arena(flier=False)
    _focus(engine)
    _raise_mark(engine)
    walker = engine.state.actors[WALKER]
    walker.position = walker.position.model_copy(update={'x': 5, 'y': 5, 'z': 0})
    walker.saving_throws['DEX'] = -1000
    _move(engine, WALKER, 5, 7)     # (5,5,0) -> (5,7,0) passes under (5,6,2)
    assert engine.state.actors[WALKER].position == Position(x=5, y=7, z=0)
    assert engine._effective_speed(walker) == 30
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1 and engine.state.actors[WEAVER].reaction_available
    assert not _saves(engine, SNARING)


def test_snaring_crossing_leaves_a_creature_that_steps_over_a_ground_thread_alone():
    """The other direction: a thread lying along the floor is not something a creature twenty feet above it walks
    into.  Both endpoints of the step are compared in three dimensions, so neither one is 'on' the line."""
    engine = _arena(extra=((FLYER, OTHER_THREAD, (5, 5)),), fly={FLYER}, lift=((FLYER, 4),))
    _focus(engine)
    flier = engine.state.actors[FLYER]
    flier.saving_throws['DEX'] = -1000
    _move(engine, FLYER, 5, 6, 4)   # straight over the ground thread from (3,6,0) to (7,6,0)
    assert engine.state.actors[FLYER].position == Position(x=5, y=6, z=4)
    assert engine._effective_speed(flier) == 30
    assert engine.state.actors[WEAVER].resources[FOCUS] == 1 and engine.state.actors[WEAVER].reaction_available
    assert not _saves(engine, SNARING)


# ----------------------------------------------------------------- every Thread user whose line is crossed
SECOND = 'actor:factory.auto19_weaver2'
SECOND_MARK = 'actor:factory.auto19_marked2'


def _two_weaver_arena():
    """A second Thread user at (3,7) with its own mark at (7,7), so one step from (5,6) to (5,7) leaves the first
    user's line and enters the second's: both printed limits are per user, and both reactions are on that step."""
    return _arena(extra=((SECOND, SNARING, (3, 7, 0)), (SECOND_MARK, OTHER_THREAD, (7, 7, 0))), seed='AUTO19F1-TWO')


def test_snaring_crossing_offers_the_second_thread_user_when_the_first_one_saved():
    """The printed limit is "A creature can be affected by your Snaring Crossing only once per round" -- each
    user's own.  The hook used to return after the first activation, so the second Thread user whose line the
    same step crossed was never offered their own Reaction, and a one-step move leaves no later checkpoint to
    recover the choice on."""
    engine = _two_weaver_arena()
    _line_on(engine, engine.state.actors[SECOND], engine.state.actors[SECOND_MARK])
    for user in (WEAVER, SECOND):
        _focus(engine, user)
        engine.state.actors[user].reaction_available = True
    provider, seen = _by_reactor({WEAVER: ('USE', ['focus']), SECOND: ('USE', ['focus'])})
    engine.set_reaction_provider(provider)
    walker = engine.state.actors[WALKER]
    walker.position = walker.position.model_copy(update={'x': 5, 'y': 6})
    walker.saving_throws['DEX'] = 1000   # it saves both times, so the step stays possible for the second user
    _move(engine, WALKER, 5, 7)
    assert [r['reactor_id'] for r in seen] == [WEAVER, SECOND]   # both were asked, in turn
    assert all(r['reaction_source_id'] == 'choice:needle.snaring_crossing' for r in seen)
    assert [r['answered'] for r in seen] == [('USE', ['focus']), ('USE', ['focus'])]
    assert engine.state.actors[WALKER].position == Position(x=5, y=7)
    # 20 feet, not 10: two uses of the SAME ability refresh rather than stack (combat/typed_executor._modifier,
    # "using the same ability again refreshes its bonus", owner 2026-09-26).  Both printed saving throws were made
    # and both users paid; the Speed reduction of the second replaces the first's.  Reported as a balance reading.
    assert engine._effective_speed(walker) == 20
    assert len(_saves(engine, SNARING)) == 2                   # two printed Dexterity saving throws
    for user in (WEAVER, SECOND):
        actor = engine.state.actors[user]
        assert actor.resources[FOCUS] == 0 and not actor.reaction_available
        assert actor.turn_flags[f'once_per_round:thread_snaring:{WALKER}'] == engine.state.round_number


def test_snaring_crossing_lets_the_second_thread_user_pass_without_ending_the_step():
    """Every eligible owner is offered; answering for one is not an answer for the other."""
    engine = _two_weaver_arena()
    _line_on(engine, engine.state.actors[SECOND], engine.state.actors[SECOND_MARK])
    for user in (WEAVER, SECOND):
        _focus(engine, user)
        engine.state.actors[user].reaction_available = True
    provider, seen = _by_reactor({WEAVER: ('USE', ['focus']), SECOND: ('DECLINE', [])})
    engine.set_reaction_provider(provider)
    walker = engine.state.actors[WALKER]
    walker.position = walker.position.model_copy(update={'x': 5, 'y': 6})
    walker.saving_throws['DEX'] = 1000
    _move(engine, WALKER, 5, 7)
    assert [r['reactor_id'] for r in seen] == [WEAVER, SECOND]
    assert seen[1]['answered'] == ('DECLINE', [])
    assert engine._effective_speed(walker) == 20          # only the first crossing took 10 feet away
    assert engine.state.actors[SECOND].resources[FOCUS] == 1
    assert engine.state.actors[SECOND].reaction_available
    assert not [k for k in engine.state.actors[SECOND].turn_flags if 'snaring' in k]
    assert len(_saves(engine, SNARING)) == 1


def test_snaring_crossing_stops_offering_the_second_thread_user_once_the_creature_is_stopped():
    """A failed save takes the creature's Speed, so it is not going to cross anything: the first user's printed
    effect already ended the step, and the second user is not offered a reaction for a crossing that cannot happen."""
    engine = _two_weaver_arena()
    _line_on(engine, engine.state.actors[SECOND], engine.state.actors[SECOND_MARK])
    for user in (WEAVER, SECOND):
        _focus(engine, user)
        engine.state.actors[user].reaction_available = True
    provider, seen = _by_reactor({WEAVER: ('USE', ['focus']), SECOND: ('USE', ['focus'])})
    engine.set_reaction_provider(provider)
    walker = engine.state.actors[WALKER]
    walker.position = walker.position.model_copy(update={'x': 5, 'y': 6})
    walker.saving_throws['DEX'] = -1000
    receipt = _move(engine, WALKER, 5, 7)
    assert [r['reactor_id'] for r in seen] == [WEAVER]
    assert engine.state.actors[WALKER].position == Position(x=5, y=6)   # stopped on the near side of the line
    assert receipt.payload['path'] == [{'x': 5, 'y': 6}] and receipt.payload['cost_ft'] == 0
    assert receipt.payload['interrupted'] is True and engine._effective_speed(walker) == 0
    assert engine.state.actors[SECOND].resources[FOCUS] == 1
    assert engine.state.actors[SECOND].reaction_available
    assert len(_saves(engine, SNARING)) == 1


# ------------------------------------------------------------------------------- willingness is the creature's answer
def _correction(talent, *, ally=False, consent=('USE', ['refuse']), wis=None, weaver='USE', roll='save'):
    """One eligible roll with a live reaction provider, and what the table decided.

    ``roll`` picks the trigger the talent's printed text names, because a test that rolls something the talent
    never answers proves nothing: 'save' is a Dexterity saving throw (Puppet-Line Correction), 'miss' is a melee
    attack that missed (Borrow the Ally's Arm's "misses with a melee attack")."""
    engine = _arena(talent=talent, marks=(ALLY if ally else MARKED,))
    _open_intent(engine, ALLY if ally else MARKED)
    engine.state.actors[WEAVER].reaction_available = True
    subject = engine.state.actors[ALLY if ally else MARKED]
    if wis is not None:
        subject.saving_throws['WIS'] = wis
    options = [thread_correction.NAME[talent]] if weaver == 'USE' else []
    provider, seen = _answer([('thread_correction', weaver, options), ('consent', *consent)])
    engine.set_reaction_provider(provider)
    if roll == 'miss':
        return engine, seen, _attack_roll(engine, subject, engine.state.actors[MARKED], modifier=-20)
    return engine, seen, _save_roll(engine, subject, 10)


def _asked(seen, fragment):
    return next(request for request in seen if fragment in request['reaction_source_id'])


def test_puppet_line_correction_helps_a_hostile_creature_that_agrees():
    """AUTO19f1: the first cut read "willing" off which side a creature stood on, so an opposing creature could
    never receive Puppet-Line Correction's benefit however much it wanted to. Willingness is the affected
    creature's own answer, so a hostile creature that accepts is helped."""
    engine, seen, _ = _correction(PUPPET, consent=('USE', ['accept']))
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == engine.state.actors[WEAVER].proficiency_bonus
    assert engine.state.actors[WEAVER].resources[QI] == 30 - 2
    assert not _saves(engine, PUPPET, 'WIS')  # a willing creature makes no saving throw
    consent = next(r for r in seen if r['reaction_source_id'] == 'choice:willing.consent')
    assert consent['reactor_id'] == MARKED and consent['protected_target_id'] == MARKED


def test_puppet_line_correction_makes_the_printed_wisdom_save_when_the_creature_refuses():
    engine, _, _ = _correction(PUPPET, consent=('USE', ['refuse']), wis=-1000)
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == -engine.state.actors[WEAVER].proficiency_bonus
    assert _saves(engine, PUPPET, 'WIS')
    assert engine.state.actors[WEAVER].resources[QI] == 28


def test_borrow_the_allys_arm_needs_its_ally_to_agree():
    """Printed "A willing ally": a refusal ends the option and spends nothing.

    AUTO19r1f1: this test used to drive a Dexterity SAVING THROW, which Borrow the Ally's Arm never answers
    ("misses with a melee attack or fails a Strength or Dexterity ability check").  No question was ever asked and
    no consent could be refused, so all three assertions passed with the refusal handling deleted.  It now makes
    the ally miss a melee attack -- the printed trigger -- checks that both questions were actually put, that the
    ally's recorded answer really was 'refuse', and that the roll, the printed price and the Reaction are all
    untouched."""
    engine, seen, roll = _correction(BORROW, ally=True, consent=('USE', ['refuse']), roll='miss')
    asked = _asked(seen, 'thread_correction')
    consent = _asked(seen, 'consent')
    assert asked['reactor_id'] == WEAVER and asked['answered'] == ('USE', [thread_correction.NAME[BORROW]])
    assert consent['reactor_id'] == ALLY and consent['answered'] == ('USE', ['refuse'])
    assert consent['choice_trigger']['prompt'] and 'Borrow the Ally' in consent['choice_trigger']['prompt']
    assert len(seen) == 2                     # exactly the two printed questions, and nothing else
    assert not [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert roll.total == roll.natural_result + roll.modifier   # the ally's own roll, untouched
    assert engine.state.actors[WEAVER].resources[QI] == 30     # no 1 CP paid for a refused offer
    assert engine.state.actors[WEAVER].reaction_available
    assert not _saves(engine, BORROW, 'WIS')                   # and no saving throw of any kind


def test_borrow_the_allys_arm_pays_its_printed_price_when_the_ally_agrees():
    """The same eligible trigger with an accept, so the refusal test above is not the only thing it could be
    asserting: the consent answer really is what decides, and the accepted price is the printed 1 CP."""
    engine, seen, roll = _correction(BORROW, ally=True, consent=('USE', ['accept']), roll='miss')
    consent = _asked(seen, 'consent')
    assert consent['answered'] == ('USE', ['accept'])
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == engine.state.actors[WEAVER].proficiency_bonus
    assert rewritten[-1].payload['original']['total'] == roll.total - engine.state.actors[WEAVER].proficiency_bonus
    assert engine.state.actors[WEAVER].resources[QI] == 29 and not engine.state.actors[WEAVER].reaction_available


def test_each_consent_question_says_what_a_refusal_actually_costs():
    """AUTO19r1f1, finding 3.  Puppet-Line Correction is hostile to an unwilling creature and prints the Wisdom
    saving throw, so its question quotes it.  Borrow the Ally's Arm prints no such thing -- a refusal leaves the
    roll alone and spends neither CP nor the Reaction -- and the question used to describe Puppet's saving throw
    and Proficiency Bonus penalty for both, which pressured a player into accepting using consequences that
    Borrow the Ally's Arm does not have."""
    borrow, borrow_seen, _ = _correction(BORROW, ally=True, consent=('USE', ['accept']), roll='miss')
    borrow_prompt = _asked(borrow_seen, 'consent')['choice_trigger']['prompt']
    puppet, puppet_seen, _ = _correction(PUPPET, consent=('USE', ['accept']))
    puppet_prompt = _asked(puppet_seen, 'consent')['choice_trigger']['prompt']
    ally_name = borrow.state.actors[ALLY].display_name
    weaver_name = borrow.state.actors[WEAVER].display_name
    assert 'Borrow the Ally' in borrow_prompt and ally_name in borrow_prompt and weaver_name in borrow_prompt
    assert 'Wisdom saving throw' not in borrow_prompt and 'subtracts' not in borrow_prompt
    assert 'Refuse, and nothing happens at all' in borrow_prompt
    assert 'spends no CP and keeps their Reaction' in borrow_prompt
    assert 'Puppet-Line Correction' in puppet_prompt
    assert 'Wisdom saving throw' in puppet_prompt and borrow.state.actors[MARKED].display_name in puppet_prompt


def test_borrow_the_allys_arm_is_offered_before_puppet_line_correction_for_an_ally():
    """Both talents reach a willing ally. Borrow the Ally's Arm costs 1 CP and Puppet-Line Correction 2, so the
    cheaper printed option is the one the table asks about first."""
    engine = _arena(talent=(PUPPET, BORROW), marks=(ALLY,), seed='AUTO19F1B')
    _open_intent(engine, ALLY)
    provider, seen = _answer([('thread_correction', 'USE', [thread_correction.NAME[BORROW]]),
                              ('consent', 'USE', ['accept'])])
    engine.set_reaction_provider(provider)
    _attack_roll(engine, engine.state.actors[ALLY], engine.state.actors[MARKED], modifier=-20)
    asked = next(r for r in seen if 'thread_correction' in r['reaction_source_id'])
    assert asked['legal_option_ids'] == [thread_correction.NAME[BORROW]]
    assert engine.state.actors[WEAVER].resources[QI] == 29
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == engine.state.actors[WEAVER].proficiency_bonus


def _in_order(steps):
    """A reaction provider that answers a queue of ``(fragment, selection, options)`` in the order the questions
    are asked, and records every request.

    ``_answer`` above matches on a fragment alone, so it can only give every question of one kind the same answer.
    These tests have to be able to say otherwise: one creature is asked once per talent, and its answer to one
    offer is not its answer to the other."""
    seen, queue = [], list(steps)

    def provider(request):
        seen.append(request)
        for index, (fragment, selection, options) in enumerate(queue):
            if fragment in str(request['reaction_source_id']):
                queue.pop(index)
                request['answered'] = (selection, list(options))
                return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                        reaction_source_id=request['reaction_source_id'], selection=selection,
                                        option_ids=tuple(options)), None
        raise AssertionError(f'unexpected reaction asked: {request["reaction_source_id"]}')
    return provider, seen


def _both_talents(answers, wis=None):
    """One missed melee attack by an ally that BOTH corrections reach, with the weaver answering USE to both of its
    offers and the ally answering ``answers`` -- the accept-or-refuse answers it gives to the two consent
    questions, in the order they are asked."""
    engine = _arena(talent=(PUPPET, BORROW), marks=(ALLY,), seed='AUTO19F1D')
    _open_intent(engine, ALLY)
    engine.state.actors[WEAVER].reaction_available = True
    if wis is not None:
        engine.state.actors[ALLY].saving_throws['WIS'] = wis
    provider, seen = _in_order([('thread_correction', 'USE', [thread_correction.NAME[BORROW]]),
                                ('consent', 'USE', [answers[0]]),
                                ('thread_correction', 'USE', [thread_correction.NAME[PUPPET]]),
                                ('consent', 'USE', [answers[1]])])
    engine.set_reaction_provider(provider)
    return engine, seen, _attack_roll(engine, engine.state.actors[ALLY], engine.state.actors[MARKED], modifier=-20)


def test_refusing_borrow_leaves_puppet_to_ask_the_ally_its_own_question():
    """AUTO19r3f1, finding 1: one willingness answer per TALENT, not one per line and creature.

    Both corrections reach an ally's missed melee attack, and the cheaper printed option (Borrow the Ally's Arm,
    1 CP) is offered first.  Refusing it promises "nothing happens at all", which is Borrow's promise about
    Borrow.  Puppet-Line Correction is a different offer on the same roll, at 2 CP and its own Reaction, so the
    ally has to answer it on its own.  Caching one answer per (line, creature) reused Borrow's refusal for Puppet:
    the ally was never asked a second time, and its roll was pulled down by the Thread user's Proficiency Bonus on
    a Wisdom saving throw it had never been told about."""
    engine, seen, roll = _both_talents(('refuse', 'accept'))
    consents = [request for request in seen if request['reaction_source_id'] == 'choice:willing.consent']
    assert len(seen) == 4                    # both offers and both consent questions, and nothing else
    assert [r['reactor_id'] for r in consents] == [ALLY, ALLY]
    assert [r['answered'] for r in consents] == [('USE', ['refuse']), ('USE', ['accept'])]
    borrow_prompt, puppet_prompt = (r['choice_trigger']['prompt'] for r in consents)
    assert 'Borrow the Ally' in borrow_prompt and 'Refuse, and nothing happens at all' in borrow_prompt
    assert 'Puppet-Line Correction' in puppet_prompt and 'Wisdom saving throw' in puppet_prompt
    assert 'nothing happens at all' not in puppet_prompt   # Borrow's promise is not Puppet's
    weaver = engine.state.actors[WEAVER]
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert len(rewritten) == 1 and rewritten[-1].payload['bonus'] == weaver.proficiency_bonus
    assert rewritten[-1].payload['original']['total'] == roll.total - weaver.proficiency_bonus
    assert weaver.resources[QI] == 30 - 2      # Puppet's printed price only; a refused Borrow is not charged
    assert not weaver.reaction_available       # and exactly one Reaction, for the answer it actually got
    assert not _saves(engine, PUPPET, 'WIS')   # a willing creature makes no saving throw


def test_refusing_both_thread_corrections_runs_puppets_own_printed_unwilling_branch():
    """The other half of finding 1: an ally that refuses Puppet-Line Correction too hears that talent's own
    question and gets that talent's own unwilling branch -- the printed Wisdom saving throw -- for the printed
    2 CP and the Reaction.  "On a success, the roll is unaffected" is about the roll, and there is no printed
    refund, so a creature that resists successfully still costs the Thread user both."""
    engine, seen, roll = _both_talents(('refuse', 'refuse'), wis=-1000)
    consents = [request for request in seen if request['reaction_source_id'] == 'choice:willing.consent']
    assert len(seen) == 4 and len(consents) == 2
    assert [r['answered'] for r in consents] == [('USE', ['refuse']), ('USE', ['refuse'])]
    assert 'Wisdom saving throw' in consents[-1]['choice_trigger']['prompt']
    assert len(_saves(engine, PUPPET, 'WIS')) == 1 and not _saves(engine, BORROW, 'WIS')
    weaver = engine.state.actors[WEAVER]
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert len(rewritten) == 1 and rewritten[-1].payload['bonus'] == -weaver.proficiency_bonus
    assert rewritten[-1].payload['original']['total'] == roll.total + weaver.proficiency_bonus
    assert weaver.resources[QI] == 30 - 2 and not weaver.reaction_available


def test_thread_correction_asks_with_its_printed_cost_the_triggering_roll_and_the_affected_creature():
    engine, seen, _ = _correction(PUPPET, consent=('USE', ['accept']))
    asked = next(r for r in seen if 'thread_correction' in r['reaction_source_id'])
    assert asked['reactor_id'] == WEAVER
    assert asked['legal_option_ids'] == [thread_correction.NAME[PUPPET]]
    trigger = asked['choice_trigger']
    name = engine.state.actors[MARKED].display_name
    assert trigger['name'] == 'Puppet-Line Correction' and trigger['feature_id'] == PUPPET
    assert trigger['target_id'] == MARKED and name in trigger['labels'][thread_correction.NAME[PUPPET]]
    prompt = trigger['prompt']
    assert 'Puppet-Line Correction' in prompt and name in prompt
    assert 'Dexterity saving throw' in prompt and 'Wisdom saving throw' in prompt and 'Reaction' in prompt
    assert 'CP (cultivation points' in prompt  # the printed cost, spelled out for a player


def test_passing_the_correction_asks_nobody_else_and_spends_nothing():
    engine, seen, _ = _correction(PUPPET, weaver='DECLINE')
    assert len(seen) == 1 and 'consent' not in seen[0]['reaction_source_id']
    assert engine.state.actors[WEAVER].resources[QI] == 30
    assert engine.state.actors[WEAVER].reaction_available


# ------------------------------------------------------------------------------- typed data and the shared lookups
def test_the_three_automated_reactions_print_only_what_the_gm_must_still_decide():
    """The point of the lane: nothing is left for the GM that the table can answer. Snaring Crossing keeps one
    honest reminder, because a fixed anchor you control is not a thing the table keeps track of -- so it is CORE
    with a rider rather than a claim of full coverage."""
    for key in (PUPPET, BORROW):
        record = AUTH[key]
        assert record['coverage'] == 'FULL', key
        assert not record.get('riders'), (key, record.get('riders'))
        action = [a for a in _compiled(key)['action_catalog']
                  if (a.get('parameters') or {}).get('typed', {}).get('source') == key]
        for row in action:
            assert not (row['parameters']['typed'].get('riders') or []), (key, row['display_name'])
    snaring = AUTH[SNARING]
    assert snaring['coverage'] == 'CORE_WITH_RIDERS'
    assert len(snaring['riders']) == 1 and 'anchor' in snaring['riders'][0]
    from combat.history_text import rider_text
    from tests.rider_text_support import rider_problems
    line = rider_text({'rider': snaring['riders'][0]}, 'A Fighter', 'Snaring Crossing', 'it') or ''
    assert not rider_problems(line), line


def test_the_thread_line_and_its_geometry_are_read_once_for_every_thread_talent():
    """One lookup for the mark, one for the squares the line runs through, so no two Thread talents can disagree
    about what "connected by one of your Thread Lines" means."""
    engine = _arena()
    me, marked = engine.state.actors[WEAVER], engine.state.actors[MARKED]
    assert thread_lines._held(marked, WEAVER, LINE) == mark_held_by(marked, WEAVER, LINE)
    assert thread_line_cells(engine, me) == {(x, 6, 0) for x in range(3, 8)}
    engine._remove_condition(marked, te.mark_condition_id(LINE, WEAVER), 'test')
    assert thread_line_cells(engine, me) == set()


def test_thread_correction_hooks_are_documented_in_ext_init():
    """A seam has to be written down where the other seams are (change standard, modularity 6)."""
    doc = (Path(__file__).resolve().parents[1] / 'combat/ext/__init__.py').read_text(encoding='utf-8')
    assert 'combat/ext/thread_correction.py' in doc and 'd20_bonus' in doc
    assert 'movement_attempt' in doc and 'combat/ext/thread_lines.py' in doc
    assert 'thread_common.thread_line_cells' in doc
    assert thread_correction.PUPPET in AUTH and thread_correction.BORROW in AUTH

# ------------------------------------------------------------------------------- at the table, through a commit and a reload
def test_snaring_crossing_at_the_table_declines_cleanly_and_its_limit_survives_a_reload(tmp_path, monkeypatch):
    """The service/table level the review asked for: the question a player is asked carries the printed options,
    a Pass spends nothing, and the printed once-per-round limit is still in the fight after a table commit and a
    reload from the store."""
    from combat import ext
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    from tests.test_r4_integration import candidate, reach

    weaver, foe = FACTORY_ACTOR_PREFIX + 'a19-weaver', FACTORY_ACTOR_PREFIX + 'a19-foe'
    ids = [weaver, foe]
    bundles = []
    for actor_id, mids, display in ((weaver, [SNARING], 'Thread Weaver'), (foe, [], 'Thread Foe')):
        document = sheet(mids, cl=20, dc=50)
        document['identity']['display_name'] = display
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        document['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}]
        folder = tmp_path / 'portable_characters' / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with __import__('zipfile').ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        bundles.append(__import__('combat.factory_compiler', fromlist=['compile_character']).compile_character(
            document, actor_id=actor_id, reaction_plan={'ask': True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids, {weaver: 'team:a', foe: 'team:b'},
                                       {weaver: {'x': 3, 'y': 6}, foe: {'x': 7, 'y': 6}},
                                       combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [weaver], [foe],
                                       control_modes={i: 'MANUAL' for i in ids}, match_seed='AUTO19F1-TABLE',
                                       display_name='AUTO19f1 table', maximum_rounds=10)['match_id']

    def send(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    def move_to(x, y):
        options = [o for o in table.state(mid)['menu']['moves']
                   if o['destination']['x'] == x and o['destination']['y'] == y]
        assert options, sorted({(o['destination']['x'], o['destination']['y']) for o in table.state(mid)['menu']['moves']})
        return options[0]['candidate_id']

    def lay_the_line():
        reach(table, mid, weaver)
        assert send(candidate(table, mid, 'Draw the Line: Guide', foe))['status'] == 'COMMITTED'
        loaded = combat._load_session(mid)
        assert thread_line_cells(loaded.engine, loaded.engine.state.actors[weaver]), 'Draw the Line laid no line'

    # Every attack roll in this test hits, so Draw the Line really lays a line (it is a Thread Attack).
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'd20_result',
                        [lambda *a: {'source_id': 'auto19f1:hit', 'operation': 'replace', 'natural_result': 20}])

    lay_the_line()
    reach(table, mid, foe)
    result = send(move_to(8, 6))
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert [option['id'] for option in prompt['choice']['options']] == ['focus', 'cp']
    assert prompt['choice']['allow_decline'] is True
    for text in ('Snaring Crossing', 'Dexterity saving throw', 'Thread Foe'):
        assert text in prompt['moment'], prompt['moment']
    weaver_actor = combat._load_session(mid).engine.state.actors[weaver]
    before = weaver_actor.resources.get(FOCUS, 0)
    assert send(move_to(8, 6), [{**prompt['context'], 'selection': 'DECLINE', 'option_ids': []}])['status'] == 'COMMITTED'

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[foe].position.x == 8     # the creature walked on
    assert loaded.engine.state.actors[weaver].resources.get(FOCUS, 0) == before
    assert not [k for k in loaded.engine.state.actors[weaver].turn_flags if 'snaring' in k]
    assert loaded.mechanical.replay()['status'] == 'PASS'

    lay_the_line()
    reach(table, mid, foe)
    result = send(move_to(7, 6))
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    choice = next(option['id'] for option in prompt['choice']['options'] if option['id'] == 'focus')
    assert send(move_to(7, 6), [{**prompt['context'], 'selection': 'USE', 'option_ids': [choice]}])['status'] == 'COMMITTED'

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    weaver_actor, foe_actor = loaded.engine.state.actors[weaver], loaded.engine.state.actors[foe]
    assert weaver_actor.turn_flags[f'once_per_round:thread_snaring:{foe}'] == loaded.engine.state.round_number
    assert foe_actor.position.x == 8                          # stopped on the near side of the line
    assert loaded.engine._effective_speed(foe_actor) == 0
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_the_consent_question_reaches_the_table_with_its_printed_wording(tmp_path):
    """AUTO19r1f1, finding 3, at the service/table level: the consent question a player is actually shown has to
    say what refusing costs for the talent it belongs to, and name the creature that has to answer it.

    Puppet-Line Correction is the correction that can be reached at the table today: Draw the Line is compiled
    HOSTILE_ENTITY, so the only creature a Thread Line can be put on is one on the other side, and Borrow the
    Ally's Arm's printed "a willing ally" has no reachable subject. That gap is reported, not fixed here; Borrow's
    own wording is asserted through the same consent transport at engine level in
    ``test_each_consent_question_says_what_a_refusal_actually_costs``."""
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    from tests.test_r4_integration import candidate, reach

    weaver, foe = FACTORY_ACTOR_PREFIX + 'a19r1-weaver', FACTORY_ACTOR_PREFIX + 'a19r1-foe'
    ids = [weaver, foe]
    bundles = []
    for actor_id, mids, display in ((weaver, [PUPPET], 'Thread Weaver'), (foe, [], 'Thread Foe')):
        document = sheet(mids, cl=20, dc=50)
        document['identity']['display_name'] = display
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        # The Draw the Line really lays a line (technique_attack_bonus 100 always beats the foe's AC), so no dice
        # have to be scripted and the test cannot pass or fail on a roll.
        document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        document['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}]
        folder = tmp_path / 'portable_characters' / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with __import__('zipfile').ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        bundles.append(__import__('combat.factory_compiler', fromlist=['compile_character']).compile_character(
            document, actor_id=actor_id, reaction_plan={'ask': True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids, {weaver: 'team:a', foe: 'team:b'},
                                       {weaver: {'x': 3, 'y': 6}, foe: {'x': 4, 'y': 6}},
                                       combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [weaver], [foe],
                                       control_modes={i: 'MANUAL' for i in ids}, match_seed='AUTO19R1F1-CONSENT',
                                       display_name='AUTO19r1f1 consent', maximum_rounds=10)['match_id']

    def send(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    reach(table, mid, weaver)
    assert send(candidate(table, mid, 'Draw the Line: Guide', foe))['status'] == 'COMMITTED'
    loaded = combat._load_session(mid)
    assert thread_line_cells(loaded.engine, loaded.engine.state.actors[weaver]), 'Draw the Line laid no line'

    reach(table, mid, foe)
    attack = candidate(table, mid, 'Jian (Straight Sword) attack', weaver)
    before = combat._load_session(mid).engine.state.actors[weaver].resources[QI]
    asked = send(attack)
    assert asked['status'] == 'REACTION_REQUIRED'
    offer = asked['reaction']
    assert offer['reactor'] == 'Thread Weaver' and offer['affected'] == 'Thread Foe'
    # Approved batch 3 wording names the compiled paying pool (Qi) and explains it; never a bare CP amount.
    for text in ('Puppet-Line Correction', 'Thread Foe', 'Reaction', '2 Qi (cultivation points', 'Wisdom saving throw'):
        assert text in offer['moment'], offer['moment']
    assert not re.search(r'\b\d+ CP\b', offer['moment']), offer['moment']

    consent = send(attack, [{**offer['context'], 'selection': 'USE', 'option_ids': ['Puppet-Line Correction']}])
    assert consent['status'] == 'REACTION_REQUIRED'
    prompt = consent['reaction']
    assert prompt['reactor'] == 'Thread Foe'          # the affected creature answers, not the Thread user
    assert prompt['context']['reaction_source_id'] == 'choice:willing.consent'
    assert [option['id'] for option in prompt['choice']['options']] == ['accept', 'refuse']
    for text in ('Puppet-Line Correction', 'Thread Weaver', 'Thread Foe', 'attack roll',
                 'Wisdom saving throw', 'Cultivation Save DC (50)', '2 cultivation points (your Path resource)', 'their Reaction'):
        assert text in prompt['moment'], prompt['moment']
    assert not re.search(r'\b\d+ CP\b', prompt['moment']), prompt['moment']
    # The borrowed wording must not leak into the talent that does print a saving throw.
    assert 'spends no CP and keeps their Reaction' not in prompt['moment']

    committed = send(attack, [{**offer['context'], 'selection': 'USE', 'option_ids': ['Puppet-Line Correction']},
                              {**prompt['context'], 'selection': 'USE', 'option_ids': ['accept']}])
    assert committed['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    weaver_actor = loaded.engine.state.actors[weaver]
    rewritten = [e for e in loaded.engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['bonus'] == weaver_actor.proficiency_bonus
    assert weaver_actor.resources[QI] == before - 2 and not weaver_actor.reaction_available
    assert loaded.mechanical.replay()['status'] == 'PASS'
