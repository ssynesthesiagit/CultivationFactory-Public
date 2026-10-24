"""Actual recipients, post-save seal choices and source-local metal ground."""
import pytest
from combat import zones
from combat.ext import placed
from combat.typed_executor import condition_rules
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.auto_worker1_support import cell_send, turn
H = 'tianxia.talent.metal.heavenly_needle_sutra'
N = 'TAL_METAL_MERIDIAN_NAIL'
C = 'TAL_METAL_IRON_FILINGS_CLOUD'
POOL = 'resource:core.qi'

def settle(send, picker=None):
    answers, prompts = ([], [])
    for _ in range(20):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return (result, prompts)
        p = result['reaction']
        prompts.append(p)
        choice = p.get('choice') or {}
        ids = [o['id'] for o in choice.get('options', [])]
        chosen = picker(p) if picker else ids[:max(1, choice.get('minimum', 1))]
        decline = not chosen and choice.get('allow_decline', True)
        answers.append({**p['context'], 'selection': 'DECLINE' if decline else 'USE', 'option_ids': chosen})
    raise AssertionError('too many choices')

def blocked(e, aid):
    return any((r.get('no_reactions') for r in condition_rules(e.state.actors[aid])))

@pytest.mark.parametrize('ai', [False, True])
def test_heavenly_selects_actual_recipient_and_two_distinct_seals(tmp_path, ai):
    c, t, m = fight(tmp_path, [H], cl=15)

    def pick(p):
        source = p['context']['reaction_source_id']
        if source == 'choice:needle.rider_targets':
            return [RIGHT]
        if source == 'choice:needle.metal_second_seal':
            return ['SECOND']
        if source == 'choice:needle.metal_needle_seal':
            return ['Cannot take Reactions', 'Speed reduced by 15 feet']
        return [p['choice']['options'][0]['id']]
    _, prompts = settle(action_sender(c, t, m, 'Heavenly Needle Sutra', ai=ai, target_id=RIGHT), pick)
    e = reload(c, m)
    assert [v.actor_id for v in e.events if v.event_type == 'SAVE_ROLLED'] == [RIGHT]
    assert blocked(e, RIGHT) and (not blocked(e, LEFT))
    assert e._effective_speed(e.state.actors[RIGHT]) == 15
    assert e.state.actors[LEFT].resources[POOL] == 98
    if not ai:
        assert any(('Visitor failed' in str(p) for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert not blocked(e, RIGHT) and e._effective_speed(e.state.actors[RIGHT]) == 30

def test_heavenly_second_seal_is_optional_and_only_one_recipient(tmp_path):
    c, t, m = fight(tmp_path, [H], cl=15)
    second = []

    def pick(p):
        source = p['context']['reaction_source_id']
        if source == 'choice:needle.rider_targets':
            return [LEFT, RIGHT]
        if source == 'choice:needle.metal_second_seal':
            second.append(p)
            return ['SECOND']
        if source == 'choice:needle.metal_needle_seal':
            return ['Cannot take Reactions', 'Speed reduced by 15 feet'] if p['choice']['minimum'] == 2 else ['Cannot regain CP']
        return [p['choice']['options'][0]['id']]
    settle(lambda a: act(t, m, 'Heavenly Needle Sutra', a, target_id=RIGHT), pick)
    e = reload(c, m)
    assert len(second) == 1
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED']) == 2
    assert sum((blocked(e, aid) for aid in [LEFT, RIGHT])) == 1
    assert sum((e._effective_speed(e.state.actors[aid]) == 15 for aid in [LEFT, RIGHT])) == 1
    assert sum((any((r.get('no_cp_regain') for r in condition_rules(e.state.actors[aid]))) for aid in [LEFT, RIGHT])) == 1

@pytest.mark.parametrize('cl', [5, 15])
def test_heavenly_declining_extra_or_success_does_not_apply_extra_seals(tmp_path, cl):
    c, t, m = fight(tmp_path, [H], cl=cl)

    def pick(p):
        source = p['context']['reaction_source_id']
        return [RIGHT] if source == 'choice:needle.rider_targets' else [] if source == 'choice:needle.metal_second_seal' else ['Speed reduced by 15 feet']
    _, prompts = settle(lambda a: act(t, m, 'Heavenly Needle Sutra', a, target_id=RIGHT), pick)
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 15 and (not blocked(e, RIGHT))
    assert any((p['context']['reaction_source_id'] == 'choice:needle.metal_second_seal' for p in prompts)) == (cl == 15)

def test_heavenly_success_only_takes_half_damage(tmp_path):
    c, t, m = fight(tmp_path, [H], cl=15, left_save_dc=-100)
    _, prompts = settle(lambda a: act(t, m, 'Heavenly Needle Sutra', a, target_id=RIGHT), lambda p: [RIGHT])
    e = reload(c, m)
    assert not any(('metal_needle_seal' in str(p) or 'metal_second_seal' in str(p) for p in prompts))
    assert 0 < 1000 - e.state.actors[RIGHT].current_hp < 40 and (not blocked(e, RIGHT))

@pytest.mark.parametrize('ai', [False, True])
def test_meridian_choice_occurs_on_actual_hit_and_expires(tmp_path, ai):
    c, t, m = fight(tmp_path, [N], left_attack_bonus=100)
    _, prompts = settle(action_sender(c, t, m, 'Meridian Nail', ai=ai, target_id=RIGHT), lambda p: ['Reduce Speed'] if any((o['id'] == 'Reduce Speed' for o in p['choice']['options'])) else [p['choice']['options'][0]['id']])
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 20
    if not ai:
        assert any(('Visitor' in str(p) for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert reload(c, m)._effective_speed(reload(c, m).state.actors[RIGHT]) == 30

@pytest.mark.parametrize('cl', [5, 10])
def test_filings_mixed_saves_exemption_is_only_this_turn_and_exact_expiry(tmp_path, cl):
    c, t, m = fight(tmp_path, [C], cl=cl, left_score=214, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    settle(cell_send(t, m, 'Iron Filings Cloud', (4, 6)), lambda p: [LEFT, RIGHT])
    e = reload(c, m)
    save = [v for v in e.events if v.event_type == 'SAVE_ROLLED']
    assert {v.actor_id: v.payload['success'] for v in save} == {LEFT: True, RIGHT: False}
    ground, = placed.of(e, 'metal_filings')
    assert (6, 6) in zones.difficult_cells(e, e.state.actors[RIGHT]) and (3, 6) not in zones.difficult_cells(e, e.state.actors[LEFT])
    assert len([v for v in e.events if v.event_type == 'ZONE_CREATED' and v.payload['zone']['zone_id'] == ground.zone_id]) == 1
    turn(t, m, RIGHT)
    e = reload(c, m)
    assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])
    turn(t, m, LEFT)
    e = reload(c, m)
    assert bool(placed.of(e, 'metal_filings')) == (cl == 10)
    if cl == 10:
        settle(lambda a: act(t, m, 'end', a))
        assert not placed.of(reload(c, m), 'metal_filings')

def test_filings_all_success_creates_no_ground(tmp_path):
    c, t, m = fight(tmp_path, [C], left_save_dc=-100, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    settle(cell_send(t, m, 'Iron Filings Cloud', (4, 6)), lambda p: [LEFT, RIGHT])
    e = reload(c, m)
    assert not placed.of(e, 'metal_filings') and e.state.actors[LEFT].resources[POOL] == 98

def test_needle_flick_no_activity_does_not_penalize_unrelated_checks(tmp_path):
    c, t, m = fight(tmp_path, ['TAL_METAL_NEEDLE_FLICK'], left_attack_bonus=100)
    settle(lambda a: act(t, m, 'Needle Flick', a, target_id=RIGHT))
    e = reload(c, m)
    assert not any((r.get('check_mode') or r.get('concentration_mode') for r in condition_rules(e.state.actors[RIGHT])))

def test_needle_flick_penalty_consumes_only_on_next_actual_concentration_save(tmp_path):
    c, t, m = fight(tmp_path, ['TAL_METAL_NEEDLE_FLICK'], right_talents=['tianxia.talent.poison.miasma_form'], right_score=50, left_attack_bonus=100, prepare=[{'type': 'damage', 'flat': 1, 'damage_types': ['fire'], 'applies_to': 'target'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Needle Flick', a, target_id=RIGHT))
    e = reload(c, m)
    assert e.state.actors[RIGHT].concentration is not None
    assert any((r.get('concentration_mode') == 'DISADVANTAGE' for r in condition_rules(e.state.actors[RIGHT])))
    for _ in range(2):
        settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    saves = [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.source_definition_id == 'system:combat.concentration']
    assert [v.payload['mode'] for v in saves] == ['NORMAL', 'DISADVANTAGE', 'NORMAL']
    assert not any((r.get('concentration_mode') for r in condition_rules(e.state.actors[RIGHT])))
