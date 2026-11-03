"""Review regressions for Glass Heart Refraction's turn-boundary offer and scene checkpoint.

Synthetic table fixtures only: no live models, private inputs or GUI.
"""
from combat.ext.foundation_combat import held
from combat.ext.glass_heart_refraction import SOURCE, long_rest
from combat.ext.glass_heart_refraction import CHOICE
from tests.glass_refraction_support import available, declare
from tests.test_a2_foundations_two import table_fixture, use
from tests.glass_refraction_support import _asked, _glass_fight, _to_next_owner_turn
from tests.worker2_support import OWNER, FOE, act, reload, turn


def test_rest_recharges_actual_action_cost_only():
    from types import SimpleNamespace

    rid = 'resource:uses.actual-counter'
    actor = {'resources': {rid: 0, 'resource:core.qi': 3},
             'bundle': {'actor_template': {'resources': [
                 {'resource_id': rid, 'maximum': 1}]},
                 'action_catalog': [{'source_definition_id': 'different-action-id',
                     'parameters': {'typed': {'source': SOURCE}},
                     'costs': [[rid, 1], ['resource:core.qi', 2]]}]}}
    session = SimpleNamespace(state={'actors': {OWNER: actor}})
    long_rest(session, OWNER)
    assert actor['resources'] == {rid: 1, 'resource:core.qi': 3}


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


def test_neither_is_not_asked_again_in_same_scene(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert len(_asked(first)) == 1
    second = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert not _asked(second), 'the same scene must not be asked again'
    assert not available(reload(tmp_path, mid))


def test_declined_scene_question_is_not_asked_again_in_same_scene(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: None})  # the owner declines the scene question
    assert len(_asked(first)) == 1
    second = _to_next_owner_turn(table, mid, {CHOICE: None})
    assert not _asked(second), 'the same scene must not be asked again'
    assert not available(reload(tmp_path, mid))


def test_second_qualifying_scene_in_one_fight_is_asked_and_offered(tmp_path):
    # The owner can explicitly record a new scene during the same fight.
    combat, table, mid = _glass_fight(tmp_path)
    first = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert len(_asked(first)) == 1
    assert available(reload(tmp_path, mid))
    declare(combat, table, mid, 'Emotionally decisive scene')
    second = _to_next_owner_turn(table, mid, {CHOICE: ['Emotionally decisive scene']})
    assert not _asked(second)
    assert available(reload(tmp_path, mid)), 'the second qualifying scene must be offered on its bearer turn'
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
