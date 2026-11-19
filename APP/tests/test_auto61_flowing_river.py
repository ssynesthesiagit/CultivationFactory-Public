"""Real failed Response-save choices, native standing gate and saved clocks."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.test_auto45_metal import settle
from tests.test_auto42_stars import turn
from combat import posture
P = 'TAL_FLOWING_RIVER_'
RESPONSE = P + 'FLOWING_RESPONSE'
FLOOR = P + 'SOFT_BODY_HARD_FLOOR'
DRAW = P + 'DRAW_PAST'

def choose(option):
    return lambda p: [option] if p['context']['reaction_source_id'] == 'choice:needle.soft_floor' else [o['id'] for o in (p.get('choice') or {}).get('options', [])][:1]

def resolve(send, option):
    answers, prompts = ([], [])
    for _ in range(20):
        result = send(answers)
        if result['status'] == 'COMMITTED':
            return (result, prompts)
        assert result['status'] == 'REACTION_REQUIRED'
        p = result['reaction']
        prompts.append(p)
        ids = choose(option)(p)
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': ids})
    raise AssertionError('too many choices')

@pytest.mark.parametrize('distance', [10, 15])
def test_empty_step_table_policy_controls_distance(tmp_path, monkeypatch, distance):
    from combat import factory_compiler
    from tests.r1i_service_support import reload as cold_reload
    from tests.test_auto2_flowing_river import settle as settle_response
    original = factory_compiler._read_compilation_authority

    def read(path):
        authority, digest = original(path)
        mechanics = dict(authority['mechanics'])
        response = mechanics[RESPONSE]
        mechanics[RESPONSE] = {**response, 'activation': {**response['activation'],
            'trigger': 'A creature you can see targets you with a melee attack; a creature within your reach forces a Strength or Dexterity saving throw to avoid being moved, knocked Prone, Grappled, or Restrained.'}}
        return {**authority, 'mechanics': mechanics}, digest

    monkeypatch.setattr(factory_compiler, '_read_compilation_authority', read)

    def edit(bundle):
        for row in bundle['typed_passives']:
            if row.get('feature_id') == P + 'EMPTY_STEP':
                assert row['response_step']['distance_ft'] == 10
                row['response_step']['distance_ft'] = distance
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Cause':
                action['parameters']['typed']['numbers']['attack_bonus'] = -100
                action['parameters']['typed']['range_ft'] = None

    c, t, m = fight(tmp_path, [RESPONSE, P + 'EMPTY_STEP'], bundle_edit=edit, left_score=50,
                    cause=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}], map_terrain=[])
    settle(lambda a: act(t, m, 'Flowing Response: step away', a))
    turn(t, m, RIGHT)
    destination = f'step:{3 - distance // 5},6,0'

    def pick(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.river_step':
            assert destination in [option['id'] for option in prompt['choice']['options']]
            return [destination]
        return [o['id'] for o in (prompt.get('choice') or {}).get('options', [])][:1]

    result, prompts = settle_response(lambda a: act(t, m, 'Cause', a, target_id=LEFT), pick)
    assert result['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'] == 'choice:needle.river_step' for p in prompts)
    engine = cold_reload(tmp_path, m)
    moved = [v for v in engine.events if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == LEFT]
    assert moved[-1].payload['granted_cost_ft'] == distance


@pytest.mark.parametrize('option', ['stand', 'speed', 'dash'])
@pytest.mark.parametrize('ai', [False, True])
def test_actual_failed_response_save_choice_and_target_start_expiry(tmp_path, option, ai):
    c, t, m = fight(tmp_path, [RESPONSE, DRAW, FLOOR], left_score=50, right_score=14, cause_target='SELF', cause=[{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    settle(lambda a: act(t, m, 'Flowing Response: Draw Past', a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    assert posture.standing_cost(reload(c, m), reload(c, m).state.actors[RIGHT]) is not None
    _, prompts = resolve(action_sender(c, t, m, 'Unarmed Strike', ai=ai, target_id=LEFT), option)
    e = reload(c, m)
    assert any((v.event_type == 'ATTACK_ROLLED' and (not v.payload['provisional_hit']) for v in e.events))
    assert any((v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT and (not v.payload['success']) for v in e.events))
    prompt = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.soft_floor'))
    assert all((s in str(prompt) for s in ['Soft Body, Hard Floor', 'Visitor', 'next turn starts']))
    if option == 'stand':
        assert any((v.condition_id == 'condition:typed.cannot_stand' for v in e.state.actors[RIGHT].conditions.values()))
        assert posture.standing_cost(e, e.state.actors[RIGHT]) is None
        assert not any((v.source_definition_id == posture.SOURCE for v in e.legal_candidates()))
    if option == 'speed':
        assert e._effective_speed(e.state.actors[RIGHT]) == 0
    if option == 'dash':
        assert any((v.condition_id == 'condition:typed.no_dash' for v in e.state.actors[RIGHT].conditions.values()))
    if ai:
        c.set_controller_mode(m, actor_id=RIGHT, controller_mode='MANUAL')
    turn(t, m, LEFT)
    turn(t, m, RIGHT)
    e = reload(c, m)
    assert not any((v.condition_id in {'condition:typed.cannot_stand', 'condition:typed.no_dash'} for v in e.state.actors[RIGHT].conditions.values()))
    assert e._effective_speed(e.state.actors[RIGHT]) == 30

@pytest.mark.parametrize('option', ['stand', 'speed', 'dash'])
@pytest.mark.parametrize('ai', [False, True])
def test_final_success_replacing_failed_response_save_has_no_floor_rider(monkeypatch, tmp_path, option, ai):
    """An outcome rewrite must settle before Floor offers any consequence."""
    from combat import ext

    provisional, final = [], []

    def replace_outcome(ctx, subject, ability, named, failed):
        if subject.entity_id != RIGHT or ctx.typed.get('_rider_response_talent') != DRAW:
            return
        provisional.append(failed)
        # Use the real pending-outcome contract consumed by settle_typed_save;
        # leave the recorded roll failed, as outcome-replacement abilities do.
        ctx.engine._typed_roll_outcome = {
            **(getattr(ctx.engine, '_typed_roll_outcome', None) or {}),
            subject.entity_id: 'success',
        }

    def observe_final(ctx, subject, ability, named, failed):
        if subject.entity_id == RIGHT and ctx.typed.get('_rider_response_talent') == DRAW:
            final.append(failed)

    ext.effects()
    # Retain every production subscriber, including Floor's early legacy hook.
    for point, callback in [('after_save', replace_outcome), ('after_save_resolved', observe_final)]:
        monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), callback])
    c, t, m = fight(tmp_path, [RESPONSE, DRAW, FLOOR], left_score=50, right_score=14,
                     cause_target='SELF', cause=[{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    settle(lambda a: act(t, m, 'Flowing Response: Draw Past', a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    result, prompts = resolve(action_sender(c, t, m, 'Unarmed Strike', ai=ai, target_id=LEFT), option)
    assert result['status'] == 'COMMITTED'
    e = reload(c, m)  # fresh service load also verifies mechanical replay
    assert provisional and all(provisional)
    assert final and not any(final)
    assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT and not v.payload['success'] for v in e.events)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.soft_floor' for p in prompts)
    actor = e.state.actors[RIGHT]
    assert posture.prone_conditions(actor)
    assert posture.standing_cost(e, actor) == 15
    assert e._effective_speed(actor) == 30
    assert not any(v.condition_id in {'condition:typed.cannot_stand', 'condition:typed.no_dash'}
                   for v in actor.conditions.values())

@pytest.mark.parametrize('case', ['unowned', 'ordinary_save', 'legacy'])
def test_soft_floor_requires_owned_response_receipt_and_new_sealed_contract(tmp_path, case):

    def legacy(b):
        if case == 'legacy':
            for r in b['typed_passives']:
                if r.get('block') == 'rider_response_fail':
                    r['spec'].pop('final_save', None)
                    r['spec']['menu']['options'][2]['effects'] = [{'type': 'rider', 'text': 'Cannot stand (GM)'}]
    c, t, m = fight(tmp_path, [RESPONSE, DRAW] + ([] if case == 'unowned' else [FLOOR]), left_score=50, bundle_edit=legacy, prepare=[{'type': 'save', 'ability': 'str', 'dc': 'technique_save_dc', 'on_fail': [], 'on_success': []}])
    if case == 'ordinary_save':
        _, prompts = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    else:
        settle(lambda a: act(t, m, 'Flowing Response: Draw Past', a))
        turn(t, m, RIGHT)
        _, prompts = resolve(lambda a: act(t, m, 'Unarmed Strike', a, target_id=LEFT), 'stand')
    e = reload(c, m)
    assert not any((v.condition_id == 'condition:typed.cannot_stand' for v in e.state.actors[RIGHT].conditions.values()))
    if case != 'legacy':
        assert not any((p['context']['reaction_source_id'] == 'choice:needle.soft_floor' for p in prompts))

@pytest.mark.parametrize('case', ['manual', 'ai', 'unowned', 'legacy'])
def test_low_river_stance_actual_standing_cost(tmp_path, case):

    def legacy(b):
        if case == 'legacy':
            b['typed_passives'][:] = [r for r in b['typed_passives'] if r.get('kind') != 'low_river_stance']
    c, t, m = fight(tmp_path, [] if case == 'unowned' else [P + 'LOW_RIVER_STANCE'], bundle_edit=legacy, prepare_target='SELF', prepare=[{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    settle(lambda a: act(t, m, 'Prepare', a))
    e = reload(c, m)
    actor = e.state.actors[LEFT]
    cost = 15 if case in {'unowned', 'legacy'} else 5
    assert posture.standing_cost(e, actor) == cost
    before = actor.movement_remaining_ft
    settle(action_sender(c, t, m, posture.SOURCE, ai=case == 'ai'))
    e = reload(c, m)
    assert not posture.prone_conditions(e.state.actors[LEFT])
    assert e.state.actors[LEFT].movement_remaining_ft == before - cost
    assert e.state.actors[LEFT].action_available
    assert [v for v in e.events if v.event_type == 'STOOD_UP'][-1].payload['cost_ft'] == cost
