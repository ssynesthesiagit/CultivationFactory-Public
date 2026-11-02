"""The printed movement lock, the printed Resistance bypass and One Line Cannot Be Crossed's printed choices
through a real table fight (worker AUTO56f2 review fixes, 2026-10-05; AUTO56r1f1 review fixes, 2026-10-05).

`tests/test_auto56_spear.py` proves what the printed rows do inside a Gate 4 engine.  This file proves the things
only a service fight can show (owner 2026-10-05 review finding 5 and AUTO56r1 review finding 2, checklist 7/9):

  * a table commit and a reload from disk restore both conditions with their own turn's expiry, and the restored lock
    still stops the step that would cross it -- a JSON dump is not a persistence test;
  * the lock ends on the printed turn ("until the start of Mo Ruo's next turn"), not before and not a turn later;
  * "Choose two" and the printed 10-foot step are really asked of a MANUAL / Ask me owner on an OPPONENT's turn --
    the pause names the ability, the triggering attack and the creature, the answer resumes the same action, and the
    printed cost and the two chosen effects each happen exactly once; an AI owner answers by itself and commits.

The lock and the bypass rows are applied through `combat.typed_executor.run_effects` inside a committed action
(`tests/test_tabletop_hunt6.on_hold`), so the conditions are real saved state and the reload is a real one.
"""

from combat import ext
from combat import typed_executor as te
from combat.ext import approach_lock
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_auto_martial import SPEAR_KIT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, RIGHT, on_hold, table_fight

TALENT = 'TAL_SPEAR_WORLD_TRANSFIXING_POINT'
ONE_LINE = 'TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED'
LOCK = approach_lock.CONDITION
BYPASS = 'condition:typed.resistance_bypass'


def _fight(tmp_path, **kwargs):
    # Stamina is the printed pool of these Spear lines; the sheet's own pool carries 30 points.
    return table_fight(tmp_path, [TALENT], cl=15, kit=SPEAR_KIT, primary='Stamina', **kwargs)


def _lock_and_bypass(engine):
    """Put the printed "choose one creature that failed" branch on RIGHT, inside a committed action."""
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == LEFT and row.source_definition_id.endswith('WORLD_TRANSFIXING_POINT'))
    rows = [row for row in next(row for row in action.parameters['typed']['effects']
                               if row.get('type') == 'rider_after_failed_save')['after']
            if row.get('type') in ('held_at_distance', 'target_resistance_ignored')]
    assert {row['type'] for row in rows} == {'held_at_distance', 'target_resistance_ignored'}, rows
    te.run_effects(te.Context(engine, actor, action, engine._active_intent, action.parameters['typed'],
                              [target], target, {}), rows)


def _reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_the_lock_and_the_bypass_survive_a_table_commit_and_reload(monkeypatch, tmp_path):
    """The two printed "choose one creature" conditions are saved state, not a JSON dump: they come back from disk
    with their own expiry name, and the restored lock still stops a step that would cross it."""
    _combat, table, mid = _fight(tmp_path)
    on_hold(monkeypatch, _lock_and_bypass)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = _reload(tmp_path, mid)
    holder, anchor = loaded.state.actors[RIGHT], loaded.state.actors[LEFT]
    lock = approach_lock.records(loaded, holder)
    assert lock and lock[0]['anchor_id'] == LEFT, [c.condition_id for c in holder.conditions.values()]
    assert lock[0]['mode'] == 'both', lock
    assert lock[0]['until'] == f"until the start of {anchor.display_name}'s next turn", lock
    assert lock[0]['reading'].endswith(f"{anchor.display_name}'s next turn."), lock
    condition = next(c for c in holder.conditions.values() if c.condition_id == LOCK)
    assert condition.expires_on == 'START_OF_SOURCE_NEXT_TURN', condition.expires_on
    bypass = [c for c in holder.conditions.values() if c.condition_id == BYPASS]
    assert bypass and bypass[0].data['damage_types'] == 'PIERCING|FORCE', bypass
    # the printed attacker scope is saved state too: this bullet names no source, so any attacker may ignore it
    assert bypass[0].data['attacker_scope'] == 'anyone', bypass[0].data
    assert bypass[0].expires_on == 'START_OF_SOURCE_NEXT_TURN', bypass[0].expires_on
    # the restored lock is live: closing the distance is refused, keeping it is not
    here = (holder.position.x, holder.position.y)
    assert holder.position != anchor.position
    stop = approach_lock.stop_at_the_line(loaded, holder, here, (anchor.position.x, anchor.position.y), None)
    assert stop and 'willingly' in stop['label'] and anchor.display_name in stop['label'], stop
    assert approach_lock.stop_at_the_line(loaded, holder, here, (here[0], here[1] + 1), None) is None


def test_the_lock_ends_on_the_printed_turn_and_not_a_turn_later(monkeypatch, tmp_path):
    """"Until the start of your next turn": the lock is still there while the caster's current turn finishes and
    through the foe's own turn, and it is gone once the caster's next turn begins."""
    _combat, table, mid = _fight(tmp_path)
    on_hold(monkeypatch, _lock_and_bypass)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    still_locked, whose = [], []
    for _ in range(8):
        engine = _reload(tmp_path, mid)
        if engine.state.terminal_result is not None:
            break
        still_locked.append(bool(approach_lock.records(engine, engine.state.actors[RIGHT])))
        whose.append(engine.state.current_actor_id)
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert still_locked[0], (still_locked, whose)
    assert False in still_locked, f'the lock never ended: {still_locked}'
    # LEFT placed the lock on its own turn and acts first, so the lock is gone exactly when its next
    # turn begins -- after the other two creatures' turns, not before, and not a turn later
    assert still_locked[:3] == [True, True, True], list(zip(whose, still_locked))
    assert next(who for who, locked in zip(whose, still_locked) if not locked) == LEFT, list(zip(whose, still_locked))
    engine = _reload(tmp_path, mid)
    assert not approach_lock.records(engine, engine.state.actors[RIGHT])
    assert not [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == BYPASS]

# -------------------------------------- One Line Cannot Be Crossed's printed choices, at the table


def _one_line_hit(monkeypatch, natural=15):
    """One Line's own Spear attack must hit for its printed "Choose two" menu to be printed at all.

    ``d20_result`` is the documented seam for a recorded rewrite (combat/ext/__init__.py); it replaces only
    LEFT's own rolls, so RIGHT's attack and every save are still the seeded ones.
    """
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', ()),
                       lambda engine, roll, intent: ({"source_id": "test:auto56.one_line", "operation": "replace",
                                                      "natural_result": natural}
                                                     if getattr(roll, "actor_id", "") == LEFT else None)])


def _attack_the_ally(combat):
    """RIGHT's own turn always ends in one printed attack against ALLY, the ally next to LEFT.

    The reaction is printed as "a creature bearing your Spear Intent ... attacks one ally adjacent to you",
    so the opponent's ordinary attack is the trigger and LEFT's Reaction has to be unspent.
    """
    real = combat.controller

    class AllyAttackController:
        def choose_primary_action(self, context):
            attack = next((c for c in context.legal_candidates
                           if ALLY in (c.target_ids or ()) and c.display_name in ('Qiang (Spear) attack', 'Unarmed Strike')), None)
            chosen = attack or next(c for c in context.legal_candidates if c.kind.value == 'END_TURN')
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = AllyAttackController()


def _one_line_fight(monkeypatch, tmp_path, *, owner_mode='MANUAL'):
    """A real table fight with the printed trigger about to happen: LEFT marked RIGHT with a printed Spear
    Thrust on its own turn (an Action, so LEFT's Reaction is still unspent), then RIGHT's turn."""
    _one_line_hit(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [ONE_LINE], cl=15, kit=SPEAR_KIT, primary='Stamina', ask=True)
    menu = table.state(mid)['menu']
    assert menu['actor_id'] == LEFT, menu['actor_id']
    thrust = next(group for group in menu['actions'] if group['label'] == 'Spear Thrust: Apply Spear Intent')
    assert table.act(mid, thrust['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'],
                     0)['status'] == 'COMMITTED'
    from combat.typed_executor import bears_mark
    assert bears_mark(CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[RIGHT], LEFT, 'Spear Intent')
    _attack_the_ally(combat)
    for actor in (ALLY, RIGHT):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    if owner_mode == 'LOCAL_AUTO':
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    return combat, table, mid


def _drive(table, combat, mid, answer_for, *, turns=8):
    """Play on until RIGHT's attack has resolved, answering every pause with ``answer_for``.

    Returns the prompts the table asked, in order.  A MANUAL owner's own turns are sent through ``act``
    (the AI cannot play them); RIGHT's turn is an AI step, so this really is the opponent's turn.
    """
    asked, answers = [], []
    for _ in range(turns):
        menu = table.state(mid)['menu']
        if menu['manual']:
            end = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                       if c.kind.value == 'END_TURN')
            result = table.act(mid, end, menu['decision_id'], menu['state_version'], 0, list(answers))
        else:
            result = table.auto_step(mid, 0, list(answers))
        if result['status'] == 'REACTION_REQUIRED':
            prompt = result['reaction']
            asked.append(prompt)
            answers += answer_for(prompt)
            continue
        assert result['status'] == 'COMMITTED', result['status']
        answers = []
        if menu['actor_id'] == RIGHT:
            break
    else:
        raise AssertionError('the opponent never got its attack in')
    return asked


def _never_asked(prompt):
    """An AI owner answers by itself, so a pause here is the defect."""
    raise AssertionError(f'an AI owner must not be asked: {prompt}')


def _answers_for(picks, cell=0):
    """The answers a player gives: use the reaction, take ``picks`` of the five printed options, then a square."""
    def answer_for(prompt):
        context = prompt['context']
        if not context['reaction_source_id'].startswith('choice:needle.'):
            return [{**context, 'selection': 'USE'}]
        options = [one['id'] for one in prompt['choice']['options']]
        if context['reaction_source_id'].endswith('spear_line_cannot_be_crossed'):
            assert set(picks) <= set(options), (picks, options)
            return [{**context, 'selection': 'USE', 'option_ids': list(picks)}]
        return [{**context, 'selection': 'USE', 'option_ids': [options[cell]]}]
    return answer_for


def test_one_line_asks_a_manual_owner_on_the_opponents_turn_and_commits_what_was_chosen(monkeypatch, tmp_path):
    """"Hit: Choose two" and "move 10 feet without provoking opportunity attacks from the target", decided by a
    player who is asked on somebody else's turn: three pauses (use the reaction, choose two of five, choose a
    square), each naming the ability, the triggering attack and the creature, then one commit that pays the
    printed 4 Stamina once and applies exactly the two chosen effects."""
    combat, table, mid = _one_line_fight(monkeypatch, tmp_path, owner_mode='MANUAL')
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine
    stamina = before.state.actors[LEFT].resources['resource:core.stamina']
    where = before.state.actors[LEFT].position
    moves_left = before.state.actors[RIGHT].movement_remaining_ft
    asked = _drive(table, combat, mid, _answers_for(['no_reactions', 'step']))
    sources = [prompt['context']['reaction_source_id'] for prompt in asked]
    assert sources == ['reaction:typed.TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED',
                       'choice:needle.spear_line_cannot_be_crossed',
                       'choice:needle.move_without_provoking'], sources
    assert all(prompt['context']['reactor_id'] == LEFT for prompt in asked), sources
    # what the player is asked: the ability, the triggering attack, the creature, and the printed count
    consent, menu, square = asked
    assert 'attacks Ally' in str(consent['moment']) and 'Qiang (Spear) attack' in str(consent['moment']), consent['moment']
    assert 'One Line Cannot Be Crossed' in str(menu['moment']) and 'Choose 2 effects' in str(menu['moment']), menu['moment']
    assert [one['id'] for one in menu['choice']['options']] == ['pin', 'no_reactions', 'push', 'prone', 'step'], menu['choice']
    assert 'One Line Cannot Be Crossed' in str(square['moment']) and 'without provoking an opportunity attack' \
        in str(square['moment']), square['moment']
    assert all('Right' in str(one['label']) for one in square['choice']['options']), square['choice']['options'][:2]
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    # exactly once: the printed cost, the chosen denial, the printed step, and nothing else of the menu
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.source_definition_id.endswith('ONE_LINE_CANNOT_BE_CROSSED')]
    assert len(spent) == 1 and int((spent[0].payload or {}).get('amount') or 0) == 4, [e.payload for e in spent]
    assert actor.resources['resource:core.stamina'] == stamina - 4, actor.resources
    assert not actor.reaction_available, 'the printed Reaction was spent'
    assert any(str(c.condition_id).endswith('reaction_denied') for c in target.conditions.values()), \
        [c.condition_id for c in target.conditions.values()]
    # the three printed options that were NOT chosen did not run
    assert target.movement_remaining_ft == moves_left, 'reduce remaining movement to 0 was not one of the two'
    assert not any(str(c.condition_id).endswith('prone') for c in target.conditions.values()), \
        "knock Prone was not one of the two chosen"
    # the step was walked, on the opponent's turn, as part of that one committed action
    step = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT]
    assert len(step) == 1 and str(step[0].source_definition_id).endswith('ONE_LINE_CANNOT_BE_CROSSED'), \
        [(e.event_type, e.source_definition_id) for e in step]
    attack = next(i for i, e in enumerate(engine.events) if e.event_type == 'INTENT_ACCEPTED' and e.actor_id == RIGHT)
    window = next(i for i, e in enumerate(engine.events) if e.event_type == 'REACTION_WINDOW_OPENED'
                  and str(e.source_definition_id).endswith('ONE_LINE_CANNOT_BE_CROSSED'))
    walked = next(i for i, e in enumerate(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT)
    assert attack < window <= walked, (attack, window, walked)
    assert not [e for e in engine.events if e.event_type == 'GM_RIDER'], \
        [str((e.payload or {}).get('rider')) for e in engine.events if e.event_type == 'GM_RIDER']
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


def test_one_line_resolves_itself_for_an_ai_owner_and_picks_two_printed_options(monkeypatch, tmp_path):
    """The same trigger with an AI owner asks nobody: the first two printed options run, the step is not one of
    them, and the printed cost is still paid exactly once."""
    combat, table, mid = _one_line_fight(monkeypatch, tmp_path, owner_mode='LOCAL_AUTO')
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine
    stamina, where = before.state.actors[LEFT].resources['resource:core.stamina'], before.state.actors[LEFT].position
    asked = _drive(table, combat, mid, _never_asked)
    assert asked == [], asked
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.source_definition_id.endswith('ONE_LINE_CANNOT_BE_CROSSED')]
    assert len(spent) == 1 and int((spent[0].payload or {}).get('amount') or 0) == 4, [e.payload for e in spent]
    assert actor.resources['resource:core.stamina'] == stamina - 4, actor.resources
    assert any(str(c.condition_id).endswith('reaction_denied') for c in target.conditions.values()), \
        [c.condition_id for c in target.conditions.values()]
    assert actor.position == where, 'the AI took the first two printed options, which are not the step'
    assert not [e for e in engine.events if e.event_type == 'GM_RIDER'], \
        [str((e.payload or {}).get('rider')) for e in engine.events if e.event_type == 'GM_RIDER']
