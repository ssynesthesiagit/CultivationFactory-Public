"""Review regressions for Glass Heart Refraction's turn-boundary offer and scene checkpoint.

Synthetic table fixtures only: no live models, private inputs or GUI.
"""
from combat.ext.foundation_combat import held
from combat.ext.glass_heart_refraction import CHOICE
from tests.glass_refraction_support import available, declare
from tests.test_a2_foundations_two import table_fixture, use
from tests.glass_refraction_support import _asked, _glass_fight, _to_next_owner_turn
from tests.worker2_support import OWNER, FOE, act, reload, turn


def test_turn_start_scene_question_pauses_the_fight_before_the_bearer_acts(tmp_path):
    # The GM question is a real table pause: the step that starts the bearer's
    # turn returns REACTION_REQUIRED, no scene is recorded, and nothing is offered
    # until the owner answers. GLASS-TURN-0 deals initiative to the ally first.
    combat, table, mid = _glass_fight(tmp_path, match_seed='GLASS-TURN-0')
    result = None
    for _ in range(12):
        cid = table.state(mid)['menu']['end_turn']
        assert table.state(mid)['menu']['actor_id'] != OWNER, 'never reached a bare bearer turn start'
        result = act(table, mid, cid)
        if result['status'] == 'REACTION_REQUIRED':
            break
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['context']['reaction_source_id'] == CHOICE
    # The paused step is rolled back until the owner answers, so nothing is
    # recorded or offered and no turn has been taken on the owner's behalf.
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id != OWNER
    assert not [e for e in engine.events if e.event_type == 'TABLE_FACT_RECORDED']
    assert not available(engine)
    answer = {**result['reaction']['context'], 'selection': 'USE', 'option_ids': ['Major combat']}
    assert act(table, mid, cid, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    assert available(engine)


def test_foe_turn_declaration_is_offered_and_payable_on_bearers_next_turn(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    turn(table, mid, FOE)
    declare(combat, table, mid, 'Major combat')
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert available(engine), 'a qualifying scene declared on another turn must be offered on the bearer turn'
    before_qi = engine.state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert held(owner, 'glass_refraction')
    assert owner.resources['resource:core.qi'] == before_qi - 2
    assert not owner.bonus_action_available


def test_turn_start_scene_answer_is_payable_in_the_same_turn(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert _asked(prompts)
    assert available(reload(tmp_path, mid))
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')


def test_neither_is_asked_once_across_consecutive_bearer_turns(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert len(_asked(first)) == 1
    # Each bearer turn is its own scene check: a Neither answer covers only its own turn,
    # so the next turn's scene is asked again (review finding 1).
    second = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert len(_asked(second)) == 1, 'a later bearer turn must ask its own scene question'
    assert not available(reload(tmp_path, mid))


def test_declined_scene_question_is_asked_once_across_consecutive_bearer_turns(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: None})  # the owner declines the scene question
    assert len(_asked(first)) == 1
    # A decline is recorded as Neither for its own turn only; the next bearer turn is asked afresh.
    second = _to_next_owner_turn(table, mid, {CHOICE: None})
    assert len(_asked(second)) == 1, 'a later bearer turn must ask its own scene question'
    assert not available(reload(tmp_path, mid))


def test_second_qualifying_scene_in_one_fight_is_asked_and_offered(tmp_path):
    # Review finding 1: the first answer must not suppress a later qualifying scene in the same fight.
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert len(_asked(first)) == 1
    assert available(reload(tmp_path, mid))
    second = _to_next_owner_turn(table, mid, {CHOICE: ['Emotionally decisive scene']})
    assert len(_asked(second)) == 1, 'the second qualifying scene in the fight was never asked'
    assert available(reload(tmp_path, mid)), 'the second qualifying scene must be offered on its bearer turn'
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
