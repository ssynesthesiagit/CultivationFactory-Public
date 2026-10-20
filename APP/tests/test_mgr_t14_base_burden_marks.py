"""Assigned base-row regressions through compiled sources and table commits.

Earth is acquired through the portable sheet's automatic sphere-component
field. Weight-Seeking Clod, not an injected mark/receipt, produces each mark.
The shared fixture's free preparation actions supply only the triggering
damage/push/Prone; assertions use cold session reload and mechanical replay.
"""
import pytest

from combat.ext import earth_responses as earth
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import (
    LEFT, RIGHT, ALLY, act, fight, reload, turn, settle, cell_send,
    action_sender,
)

CLOD = 'EARTH_BASE_WEIGHT_SEEKING_CLOD'
FOUNDATION = 'EARTH_BASE_SET_FOUNDATION'


def packet(tmp_path, *, owned=True, other_owner=False, **kwargs):
    def acquired(doc, aid):
        if aid == LEFT:
            block = doc['spheres_and_talents']
            block['sphere_record_ids'] = ['tianxia.sphere.earth']
            block['automatic_sphere_component_record_ids'] = [CLOD, FOUNDATION, *([earth.BASE] if owned else [])]
            block['learned_talent_record_ids'] = []
        elif aid == ALLY and other_owner:
            block = doc['spheres_and_talents']
            block['sphere_record_ids'] = ['tianxia.sphere.earth']
            block['automatic_sphere_component_record_ids'] = [earth.BASE, CLOD]
    return fight(tmp_path, [], left_attack_bonus=100, right_score=30,
                 sheet_edit=acquired, **kwargs)


def mark(combat, table, mid):
    assert act(table, mid, CLOD, target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert any(e.event_type == 'ATTACK_ROLLED' and CLOD in e.source_definition_id for e in engine.events)
    return engine


def choose(*, anchor=False, drag=False, recipient=None, consent=True, settle_impact=False, bear=False):
    def answer(prompt):
        options = [o['id'] for o in (prompt.get('choice') or {}).get('options', [])]
        if 'accept' in options:
            return ['accept' if consent else 'refuse']
        if 'earth_shift_recipient' in str(prompt):
            return [recipient] if recipient in options else []
        for key, use in [('anchor', anchor), ('drag', drag), ('settle', settle_impact), ('bear', bear)]:
            if key in options:
                return [key] if use else []
        return []
    return answer


@pytest.mark.parametrize('cl,penalty', [(1, 10), (11, 20)])
def test_anchor_waits_for_movement_and_persists_speed_until_turn_end(tmp_path, cl, penalty):
    combat, table, mid = packet(tmp_path, cl=cl)
    mark(combat, table, mid)
    _, prompts = settle(lambda answers: act(table, mid, 'end', answers), choose=choose(anchor=True))
    assert not any('Anchor Step' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    _, prompts = settle(cell_send(table, mid, 'Move', (4, 7)), choose=choose(anchor=True))
    assert any('Anchor Step' in str(p) and 'Visitor' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30 - penalty
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert engine.state.actors[LEFT].reaction_available  # no Reaction or Action
    settle(lambda answers: act(table, mid, 'end', answers), choose=choose())
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


def test_unowned_response_does_not_spend_a_native_mark(tmp_path):
    combat, table, mid = packet(tmp_path, owned=False, other_owner=True, ally=[])
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    _, prompts = settle(cell_send(table, mid, 'Move', (4, 7)), choose=choose(anchor=True, drag=True))
    assert not any('Earth Response' in str(p) for p in prompts)
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark')


def test_anchor_also_shortens_native_forced_movement_and_expires_off_turn(tmp_path):
    combat, table, mid = packet(tmp_path, cl=1, prepare=[
        {'type': 'forced_movement', 'distance_ft': 15, 'direction': 'away', 'applies_to': 'target'}])
    before = mark(combat, table, mid).state.actors[RIGHT].position
    settle(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT), choose=choose(anchor=True))
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert engine.grid.distance_ft(before, target.position) == 5
    assert engine._effective_speed(target) == 20
    assert not bears_mark(target, LEFT, 'Burden Mark')
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


def test_drag_success_changes_speed_so_dash_cannot_restore_the_penalty(tmp_path):
    combat, table, mid = packet(tmp_path, left_save_dc=1)
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    settle(cell_send(table, mid, 'Move', (4, 7)), choose=choose(drag=True))
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 25
    before = engine.state.actors[RIGHT].movement_remaining_ft
    assert act(table, mid, 'Dash')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].movement_remaining_ft - before == 25
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


@pytest.mark.parametrize('success', [False, True])
def test_drag_answers_actual_standing_attempt_and_rechecks_eligibility(tmp_path, success):
    combat, table, mid = packet(tmp_path, left_save_dc=1 if success else 100,
        cause_target='SELF', cause=[{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[RIGHT].movement_remaining_ft
    _, prompts = settle(lambda answers: act(table, mid, 'system:combat.stand_up', answers), choose=choose(drag=True))
    assert any('Drag Down' in str(p) for p in prompts)
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert bool([c for c in target.conditions.values() if c.expires_on == 'STAND_UP']) == (not success)
    assert engine._effective_speed(target) == (25 if success else 0)
    assert target.movement_remaining_ft == (before - 5 - 12 if success else 0)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('accept', [True, False])
def test_shift_chooses_another_recipient_and_asks_consent_before_spending(tmp_path, accept, ai_turn):
    combat, table, mid = packet(tmp_path, ally=[], positions={
        LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 7}})
    engine = mark(combat, table, mid)
    row = next(r for r in engine.typed_passive_rows[LEFT] if r.get('kind') == 'burden')
    amount = max(1, row['pb'] + row['key_mod'])
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, 'Unarmed Strike', target_id=LEFT, ai=ai_turn)
    _, prompts = settle(send,
                        choose=choose(recipient=ALLY, consent=accept))
    assert any('Shift the Load' in str(p) for p in prompts)
    assert any('accept' in [o['id'] for o in p['choice']['options']] for p in prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].temporary_hp == (amount if accept else 0)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark') == (not accept)
    assert engine.state.actors[LEFT].temporary_hp == 0
    if accept:
        grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and ALLY in e.target_ids)
        damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids)
        assert grant.sequence < damage.sequence


def test_shift_doubles_for_chosen_recipient_not_the_creature_hit(tmp_path):
    combat, table, mid = packet(tmp_path, ally=[], positions={
        LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 7}})
    assert act(table, mid, FOUNDATION, target_id=LEFT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = mark(combat, table, mid)
    row = next(r for r in engine.typed_passive_rows[LEFT] if r.get('kind') == 'burden')
    amount = max(1, row['pb'] + row['key_mod']) * 2
    assert earth._on_foundation(engine, engine.state.actors[LEFT], engine.state.actors[LEFT])
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, 'Unarmed Strike', answers, target_id=ALLY), choose=choose(recipient=LEFT))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].temporary_hp == amount
    assert engine.state.actors[ALLY].temporary_hp == 0


@pytest.mark.parametrize('cl,cut', [(1, 10), (11, 20)])
def test_settle_can_protect_an_enemy_and_uses_the_native_mark_owner(tmp_path, cl, cut):
    combat, table, mid = packet(tmp_path, cl=cl, ally=[], ally_team='team:opponents',
        cause_target='ANY_CREATURE', cause=[
            {'type': 'forced_movement', 'distance_ft': 25, 'direction': 'away', 'applies_to': 'target'}],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 4, 'y': 7}})
    engine = mark(combat, table, mid)
    before = engine.state.actors[ALLY].position
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, 'Cause', answers, target_id=ALLY), choose=choose(settle_impact=True))
    engine = reload(combat, mid)
    assert engine.grid.distance_ft(before, engine.state.actors[ALLY].position) == 25 - cut
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')


@pytest.mark.parametrize('cl,dice', [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_bear_uses_native_damage_and_printed_scaling(tmp_path, cl, dice):
    combat, table, mid = packet(tmp_path, cl=cl, cause=[
        {'type': 'damage', 'flat': 50, 'damage_type': 'FORCE', 'applies_to': 'target'}])
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, 'Cause', answers, target_id=LEFT), choose=choose(bear=True))
    engine = reload(combat, mid)
    rolled = next(r for r in engine.rolls if r.reason == 'BEAR_THE_BLOW')
    assert len(rolled.dice) == dice
    row = next(r for r in engine.typed_passive_rows[LEFT] if r.get('kind') == 'burden')
    event = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids)
    assert event.payload['reduced_to'] == max(0, 50 - max(0, rolled.total + row['key_mod']))
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')


@pytest.mark.parametrize('distance,offered', [(5, True), (10, False)])
def test_bear_requires_nearby_damage_recipient_without_foundation(tmp_path, distance, offered):
    combat, table, mid = packet(tmp_path, ally=[], cause_target='ANY_CREATURE',
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 6 + distance // 5}},
        cause=[{'type': 'damage', 'flat': 20, 'damage_type': 'FORCE', 'applies_to': 'target'}])
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    _, prompts = settle(lambda answers: act(table, mid, 'Cause', answers, target_id=ALLY), choose=choose(bear=True))
    assert any('Bear the Blow' in str(p) for p in prompts) == offered
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark') == (not offered)


@pytest.mark.parametrize('height,offered', [(2, True), (3, False)])
def test_drag_uses_native_solid_surface_distance_for_open_air_flyer(tmp_path, height, offered):
    def innate_flight(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template'].update(fly_speed_ft=30, hover=True)
    def open_map(arena):
        arena['terrain_regions'] = []
        arena['map_terrain'] = []
    combat, table, mid = packet(tmp_path, bundle_edit=innate_flight, arena_edit=open_map,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6, 'z': height}})
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    def send(answers):
        state = table.state(mid)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.source_definition_id == 'system:combat.movement'
                         and c.destination is not None
                         and (c.destination.x, c.destination.y, c.destination.z) == (4, 7, height))
        menu = state['menu']
        return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'],
                         state['last_sequence'], answers)
    _, prompts = settle(send, choose=choose(drag=True))
    assert any('Drag Down' in str(p) for p in prompts) == offered
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark') == (not offered)


def test_ai_response_owner_chooses_shift_without_a_human_prompt(tmp_path):
    combat, table, mid = packet(tmp_path)
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    _, prompts = settle(lambda answers: act(table, mid, 'Unarmed Strike', answers, target_id=LEFT), choose=choose())
    assert not any('Shift the Load' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == earth.BASE for e in engine.events)


@pytest.mark.parametrize('distance,included', [(10, True), (15, False)])
def test_shift_recipient_range_is_measured_from_the_creature_hit(tmp_path, distance, included):
    combat, table, mid = packet(tmp_path, ally=[], positions={
        LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 6 + distance // 5}})
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    _, prompts = settle(lambda answers: act(table, mid, 'Unarmed Strike', answers, target_id=LEFT), choose=choose())
    prompt = next(p for p in prompts if 'earth_shift_recipient' in str(p))
    assert (ALLY in [o['id'] for o in prompt['choice']['options']]) == included
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark')


def test_shift_requires_surface_contact_from_the_attacker(tmp_path):
    def innate_flight(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template'].update(fly_speed_ft=30, hover=True)
    combat, table, mid = packet(tmp_path, bundle_edit=innate_flight,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6, 'z': 1}})
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    _, prompts = settle(lambda answers: act(table, mid, 'Unarmed Strike', answers, target_id=LEFT), choose=choose())
    assert not any('Shift the Load' in str(p) for p in prompts)
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark')


def test_zero_settle_step_preserves_other_creatures_opportunity_attacks(tmp_path):
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    witness = 'actor:factory.auto111-witness'
    combat, table, mid = packet(tmp_path, cl=1, ally=[], extra_witness=True,
        witness_position={'x': 5, 'y': 7}, cause_target='ANY_CREATURE',
        cause=[{'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away', 'applies_to': 'target'}],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 4, 'y': 7}})
    mark(combat, table, mid)
    turn(table, mid, RIGHT)
    answers = []
    for _ in range(12):
        result = act(table, mid, 'Cause', answers, target_id=ALLY)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        prompt = result['reaction']
        options = [o['id'] for o in (prompt.get('choice') or {}).get('options', [])]
        if 'settle' in options:
            selected = ['settle']
        elif 'earth_settle_step' in str(prompt):
            selected = [cell_id(Position(x=3, y=8))]
            assert selected[0] in options
        else:
            selected = []
        answers.append({**prompt['context'], 'selection': 'USE' if selected or not prompt.get('choice') else 'DECLINE',
                        'option_ids': selected})
    else:
        raise AssertionError('Settle the Impact did not finish')
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].position == Position(x=3, y=8)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and ALLY in e.target_ids]
    assert any(e.actor_id == witness for e in attacks)
    assert not any(e.actor_id == RIGHT for e in attacks)


def test_bear_negative_key_modifier_never_increases_damage(tmp_path):
    combat, table, mid = packet(tmp_path, cl=1, left_score=1, maximum_rounds=12,
        cause=[{'type': 'damage', 'flat': 20, 'damage_type': 'FORCE', 'applies_to': 'target'}])
    for _ in range(10):
        mark(combat, table, mid)
        turn(table, mid, RIGHT)
        settle(lambda answers: act(table, mid, 'Cause', answers, target_id=LEFT), choose=choose(bear=True))
        engine = reload(combat, mid)
        rolled = next(r for r in reversed(engine.rolls) if r.reason == 'BEAR_THE_BLOW')
        event = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids)
        assert event.payload['reduced_to'] <= 20
        row = next(r for r in engine.typed_passive_rows[LEFT] if r.get('kind') == 'burden')
        if rolled.total + row['key_mod'] < 0:
            assert event.payload['reduced_to'] == 20
            return
        turn(table, mid, LEFT)
    raise AssertionError('Native seeded rolls did not exercise a negative reduction')


def test_two_earth_owners_keep_separate_native_speed_effects(tmp_path):
    combat, table, mid = packet(tmp_path, cl=1, other_owner=True, ally=[])
    mark(combat, table, mid)
    turn(table, mid, ALLY)
    assert act(table, mid, CLOD, target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    settle(cell_send(table, mid, 'Move', (4, 7)), choose=choose(anchor=True))
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    effects = [m for m in target.modifiers.values() if m.source_definition_id == earth.BASE and m.target_field == 'speed_ft']
    assert {m.source_actor_id for m in effects} == {LEFT, ALLY}
    # Native identical-source penalties use the strongest application, not a
    # sum; ownership preserves both applications and their independent expiry.
    assert engine._effective_speed(target) == 20
    assert not bears_mark(target, LEFT, 'Burden Mark')
    assert not bears_mark(target, ALLY, 'Burden Mark')
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
