"""Needle's physical route is followed at the manual/Auto Step table boundary.

Public sheets replace hunt rosters. Setup is evented inside a table transaction;
the owned Action, Focus payment, rest limit, attacks and movement are real.
"""
import pytest

from combat import ext
from combat.gate2_runtime_models import Position
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.r10_fixup_support import cast_sender, fixed_dice
from tests.test_carry import KIT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, ALLY, HOLD

TALENT = 'TAL_FENCING_NEEDLE_THROUGH_TEN_THOUSAND_GUARDS'
NAME = 'Needle Through Ten Thousand Guards'
FOCUS = 'resource:core.martial_focus'


def setup_table(tmp_path, monkeypatch, *, fear=False, invisible=False, distant=False):
    combat, table, mid = table_fight(tmp_path, [TALENT], ask=True,
                                    kit={'starting_kit': KIT}, ally_talents=[])

    def stage(engine):
        for actor_id, position in ((RIGHT, (7, 4) if distant else (2, 4)),
                                   (ALLY, (9, 4) if distant else (7, 4))):
            actor = engine.state.actors[actor_id]
            start = actor.position
            actor.position = Position(x=position[0], y=position[1])
            engine._append_event('MOVEMENT_COMMITTED', 'test:needle-layout', actor_id=actor_id,
                payload={'destination': actor.position.model_dump(mode='json'), 'cost_ft': 0,
                         'forced': True, 'path': [start.model_dump(mode='json'), actor.position.model_dump(mode='json')]})
        if fear:
            engine._apply_condition(engine.state.actors[LEFT], 'condition:typed.frightened',
                                    'test:needle-fear', ALLY, expires_on='UNTIL_REMOVED')
        if invisible:
            engine._apply_condition(engine.state.actors[ALLY], 'condition:typed.invisible',
                                    'test:needle-unseen', ALLY, expires_on='UNTIL_REMOVED')

    on_hold(monkeypatch, stage)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [19, 19, *([1] * 100)])
    return combat, table, mid


def sender(combat, table, mid, auto, destination, *, blocked=None):
    if not auto:
        return cast_sender(combat, table, mid, NAME)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    original = combat.controller

    class NeedleController:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates if c.display_name == NAME)
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)

        def choose_reaction(self, context):
            choice = original.choose_reaction(context)
            if context.reaction_source_id.endswith('guards_path'):
                if blocked is not None:
                    assert ('cell:5,4' in context.legal_option_ids) is not blocked
                assert destination in context.legal_option_ids
                options = (destination,)
            elif context.reaction_source_id.endswith('guards_targets'):
                assert RIGHT in context.legal_option_ids
                options = (RIGHT,)
            else:
                return choice
            decision = choice.decision.model_copy(update={'selection': 'USE', 'option_ids': options})
            record = choice.record.model_copy(update={'selected_option_ids': options,
                                                      'selected_reaction': decision})
            return choice.model_copy(update={'decision': decision, 'record': record})

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = NeedleController()
    state = table.state(mid)
    return lambda answers=(): table.auto_step(mid, state['last_sequence'], list(answers))


def settle(send, combat, mid, before, destination, *, blocked=None):
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        source = prompt['context']['reaction_source_id']
        options = {o['id'] for o in prompt['choice']['options']} if prompt.get('choice') else set()
        answer = {**prompt['context'], 'selection': 'USE'}
        if source.endswith('guards_path'):
            assert prompt['context']['reactor_id'] == LEFT
            assert 'Needle Through Ten Thousand Guards' in prompt['trigger']
            if blocked is not None:
                assert ('cell:5,4' in options) is not blocked
            assert destination in options
            assert send(answers)['reaction'] == prompt
            answer['option_ids'] = [destination]
        elif source.endswith('guards_targets'):
            assert RIGHT in options
            answer['option_ids'] = [RIGHT]
        else:
            answer['selection'] = 'DECLINE'
            answer['option_ids'] = []
        answers.append(answer)
    pytest.fail('Needle did not commit')


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('fear,invisible', [(True, False), (False, False), (True, True)])
def test_needle_route_menu_filters_visible_fear_and_preserves_controls(
        tmp_path, monkeypatch, auto, fear, invisible):
    combat, table, mid = setup_table(tmp_path, monkeypatch, fear=fear, invisible=invisible)
    blocked = fear and not invisible
    destination = 'cell:1,4' if blocked else 'cell:5,4'
    send = sender(combat, table, mid, auto, destination, blocked=blocked)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    prompts = settle(send, combat, mid, before, destination, blocked=blocked)
    assert bool(prompts) is not auto
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.position == Position(x=1 if blocked else 5, y=4)
    assert actor.resources[FOCUS] == before['actors'][LEFT]['resources'][FOCUS] - 1
    assert actor.movement_remaining_ft == before['actors'][LEFT]['movement_remaining_ft']
    assert not any(c.display_name == NAME for c in loaded.engine.legal_candidates())
    events = [e for e in loaded.engine.events if e.sequence > before['event_sequence']]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT]) == 1
    moves = [e for e in events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT]
    # The away route detours around Right's occupied square and its corners.
    assert len(moves) == (4 if blocked else 2)
    assert all(e.payload['without_provoking'] and e.payload['cost_ft'] == 0 for e in moves)
    assert all(loaded.engine.grid.distance_ft(Position(**e.payload['path'][0]),
                                              Position(**e.payload['path'][1])) == 5 for e in moves)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('interrupt', ['none', 'blocker', 'immobilized'])
def test_needle_walks_each_square_and_never_attacks_from_an_unreached_square(
        tmp_path, monkeypatch, auto, interrupt):
    combat, table, mid = setup_table(tmp_path, monkeypatch, distant=True)
    ext.effects()

    def interrupt_entry(engine, kind, kwargs):
        if kind != 'MOVEMENT_COMMITTED' or kwargs.get('actor_id') != LEFT:
            return
        actor = engine.state.actors[LEFT]
        if actor.position != Position(x=4, y=4):
            return
        if interrupt == 'immobilized':
            engine._apply_condition(actor, 'condition:typed.restrained', 'test:needle-entry',
                                    RIGHT, expires_on='UNTIL_REMOVED')
        elif interrupt == 'blocker':
            other = engine.state.actors[ALLY]
            start = other.position
            other.position = Position(x=5, y=4)
            engine._append_event('MOVEMENT_COMMITTED', 'test:needle-blocker', actor_id=ALLY,
                payload={'destination': other.position.model_dump(mode='json'), 'cost_ft': 0,
                         'forced': True, 'path': [start.model_dump(mode='json'), other.position.model_dump(mode='json')]})

    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), interrupt_entry])
    send = sender(combat, table, mid, auto, 'cell:6,4')
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    settle(send, combat, mid, before, 'cell:6,4')
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    stopped = interrupt != 'none'
    assert actor.position == Position(x=4 if stopped else 6, y=4)
    assert actor.resources[FOCUS] == before['actors'][LEFT]['resources'][FOCUS] - 1
    assert actor.movement_remaining_ft == before['actors'][LEFT]['movement_remaining_ft']
    events = [e for e in loaded.engine.events if e.sequence > before['event_sequence']]
    moves = [e for e in events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT]
    assert len(moves) == (1 if stopped else 3)
    assert all(e.payload['without_provoking'] and e.payload['cost_ft'] == 0 for e in moves)
    attacks = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT]
    assert len(attacks) == (0 if stopped else 1)
    if not stopped:
        assert attacks[0].target_ids == (RIGHT,)
        assert attacks[0].payload['mode'] == 'ADVANTAGE'
        assert moves[-1].sequence < attacks[0].sequence
    assert not any('opportunity' in str(e.source_definition_id).lower() for e in events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
