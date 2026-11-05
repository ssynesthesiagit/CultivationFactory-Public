"""Off-turn paid choices use the owning fighter's control mode, including cold loads."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn
from tests.test_a2_disease import CHOICE, WOUND, wounds


def wound_fight(tmp_path, ownership="current"):
    def automatic_reactions(bundle):
        # Ordinary reactions use Auto. Wound alone must enroll its manual owner.
        for row in bundle.get('typed_reactions', []):
            row['ask'] = False
        if ownership == 'retained':
            bundle['typed_passives'] = [row for row in bundle.get('typed_passives', [])
                                        if row.get('block') != 'disease_wound']
        elif ownership == 'unsupported':
            for row in bundle.get('typed_passives', []):
                if row.get('block') == 'disease_wound':
                    row['policy'] = 0
    combat, table, mid = fight(tmp_path, [] if ownership == 'nonowner' else [WOUND], left_score=30,
                               bundle_edit=automatic_reactions)
    turn(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    return combat, table, mid


def fresh_moving_table(combat, mid):
    """Only force the primary move; all reaction choices use the shipped AI policy.

    The chooser reads the AI's perceived legal candidates, never the full roster.
    Starting adjacent, Visitor walks east out of Keeper's weapon reach.
    """
    fresh = CombatService(combat.source_root, combat.userdata_root)
    real = fresh.controller

    class MoveEast:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda visible: (
                next(c.candidate_id for c in visible.legal_candidates
                     if c.kind == 'MOVE' and c.destination is not None
                     and (c.destination.x, c.destination.y) == (6, 6)), ()
            )).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    fresh.controller = MoveEast()
    return fresh, TabletopService(fresh, combat.userdata_root)


@pytest.mark.parametrize('accept', [False, True])
def test_manual_wound_owner_pauses_ai_move_before_payment_and_answers_after_reload(tmp_path, accept):
    combat, table, mid = wound_fight(tmp_path)
    before = reload(combat, mid)
    balance = before.state.actors[LEFT].resources['resource:core.qi']
    state_before = before.state.model_dump(mode='json')
    combat, table = fresh_moving_table(combat, mid)
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == LEFT
    assert prompt['context']['reaction_source_id'] == CHOICE
    assert 'Contaminated Wound' in str(prompt)
    paused = reload(combat, mid)
    assert paused.state.model_dump(mode='json') == state_before
    assert not wounds(paused)
    assert paused.state.actors[LEFT].resources['resource:core.qi'] == balance
    assert 'disease_wound_turn' not in paused.state.actors[LEFT].turn_flags

    # Pending prompt and answer survive constructing both services from disk.
    combat, table = fresh_moving_table(combat, mid)
    repeated = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert repeated['status'] == 'REACTION_REQUIRED'
    assert repeated['reaction']['context'] == prompt['context']
    answer = {**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
              'option_ids': ['WOUND'] if accept else []}
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    after = reload(combat, mid)
    assert after.state.actors[RIGHT].position.x == 6
    assert any(e.event_type == 'REACTION_RESOLVED'
               and e.source_definition_id == 'system:combat.opportunity_attack'
               for e in after.events)
    assert len(wounds(after)) == int(accept)
    assert after.state.actors[LEFT].resources['resource:core.qi'] == balance - int(accept)
    assert ('disease_wound_turn' in after.state.actors[LEFT].turn_flags) == accept
    assert bool([e for e in after.events if e.event_type == 'DAMAGE_COMMITTED'
                 and e.payload.get('display_source_id') == WOUND]) == accept
    assert after.state.current_actor_id == RIGHT


def test_ai_wound_owner_answers_automatically_off_turn_after_reload(tmp_path):
    combat, table, mid = wound_fight(tmp_path)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    before = reload(combat, mid)
    assert LEFT not in before.typed_ask_reactors
    balance = before.state.actors[LEFT].resources['resource:core.qi']
    combat, table = fresh_moving_table(combat, mid)
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result
    after = reload(combat, mid)
    assert after.state.actors[RIGHT].position.x == 6
    assert len(wounds(after)) == 1
    assert after.state.actors[LEFT].resources['resource:core.qi'] == balance - 1
    assert 'disease_wound_turn' in after.state.actors[LEFT].turn_flags


@pytest.mark.parametrize('ownership', ['nonowner', 'retained', 'unsupported'])
def test_no_current_wound_policy_adds_no_off_turn_choice_owner(tmp_path, ownership):
    combat, table, mid = wound_fight(tmp_path, ownership)
    before = reload(combat, mid)
    assert LEFT not in before.typed_ask_reactors
    balance = before.state.actors[LEFT].resources['resource:core.qi']
    combat, table = fresh_moving_table(combat, mid)
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result
    after = reload(combat, mid)
    assert after.state.actors[RIGHT].position.x == 6
    assert not wounds(after)
    assert after.state.actors[LEFT].resources['resource:core.qi'] == balance
    assert 'disease_wound_turn' not in after.state.actors[LEFT].turn_flags
