"""Source-bound Double Current Method through table commit, cold load and replay."""
import hashlib
import json

import pytest

from combat.ext.flowing_river import DOUBLE_CURRENT, DOUBLE_USED
from combat.factory_compiler import compile_character
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import action_sender
from tests.test_auto2_flowing_river import P, RESPONSE, FOCUS, reload, settle, decline_steps

HAND = P + 'HAND_ON_THE_WRIST'
WATER = P + 'WATER_WEARS_STONE'
CHOICE = 'choice:needle.double_current_method'


def acquired(doc, aid):
    if aid == LEFT:
        doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = [DOUBLE_CURRENT]


def attack_bundle(bundle):
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Cause':
            action.update(resolution_kind='ATTACK', range_ft=None, reach_ft=5,
                          attack_bonus=-100, damage=None, damage_type='BLUDGEONING')
            action['parameters'] = {'attack_kind': 'weapon', 'free_primary': True}


def setup(tmp_path, *, owned=True, control=False, extra=(), failure=False):
    cause = ([{'type': 'save', 'ability': 'str', 'on_fail': [
        {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}], 'on_success': []}]
        if control else [{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}])
    def edit(bundle):
        if not control:
            attack_bundle(bundle)
            if failure:
                for action in bundle['action_catalog']:
                    if action['display_name'] == 'Cause':
                        action['attack_bonus'] = 100
    return fight(tmp_path, [RESPONSE, HAND, WATER, *extra], left_score=50,
                 spheres=['tianxia.sphere.flowing_river'],
                 sheet_edit=acquired if owned else None, bundle_edit=edit,
                 cause=cause, cause_save_dc=1, prepare_target='SELF',
                 prepare=[{'type': 'spend_resource', 'resource_id': FOCUS, 'flat': 1}])


def choose_pair(prompt):
    if prompt['context']['reaction_source_id'] == CHOICE:
        return [next(o['id'] for o in prompt['choice']['options']
                     if 'Hand on the Wrist' in o['label'] and 'Water Wears Stone' in o['label'])]
    return decline_steps(prompt)


@pytest.mark.parametrize('control,ai_owner,ai_attacker', [
    (False, False, False), (False, False, True), (False, True, False),
    (True, False, False)])
def test_success_pair_is_free_persistent_and_once_per_scene(tmp_path, control, ai_owner, ai_attacker):
    c, t, m = setup(tmp_path, control=control)
    settle(lambda a: act(t, m, 'Flowing Response: Water Wears Stone', a))
    settle(lambda a: act(t, m, 'Prepare', a))
    turn(t, m, RIGHT)
    if ai_owner:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    before = reload(c, m)
    assert before.state.actors[LEFT].resources[FOCUS] == 0
    assert any(r['feature_id'] == DOUBLE_CURRENT for r in before.typed_passive_rows[LEFT])
    sequence = before.state.event_sequence
    snapshot = before.state.model_dump(mode='json')
    send = action_sender(c, t, m, 'Cause', ai=ai_attacker, target_id=LEFT)
    def pure_send(answers):
        result = send(answers)
        if result['status'] == 'REACTION_REQUIRED':
            assert c._load_session(m).engine.state.model_dump(mode='json') == snapshot
            assert send(answers) == result  # repeated/cancelled preview is pure
        return result
    _, prompts = settle(pure_send, choose_pair)
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp == before.state.actors[RIGHT].current_hp - 4
    assert any(v.condition_id.endswith('.reaction_denied') for v in e.state.actors[RIGHT].conditions.values())
    assert sum(v.condition_id == DOUBLE_USED for v in e.state.actors[LEFT].conditions.values()) == 1
    assert not e.state.actors[LEFT].reaction_available
    assert not any(v.event_type == 'RESOURCE_SPENT' and v.payload.get('resource_id') == FOCUS
                   for v in e.events if v.sequence > sequence)
    offers = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert bool(offers) is (not ai_owner)
    if offers:
        assert all(word in str(offers[0]) for word in ('Double Current Method', 'Cause', 'Keeper', 'Visitor', 'scene'))
    # Real turn advancement refreshes Reaction, but not the scene allowance.
    if ai_owner:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    if ai_attacker:
        c.set_controller_mode(m, actor_id=RIGHT, controller_mode='MANUAL')
    turn(t, m, LEFT)
    turn(t, m, RIGHT)
    _, again = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), choose_pair)
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in again)
    assert sum(v.condition_id == DOUBLE_USED for v in reload(c, m).state.actors[LEFT].conditions.values()) == 1


@pytest.mark.parametrize('case', ['decline', 'unowned', 'failure'])
def test_no_use_on_decline_unowned_or_failed_response(tmp_path, case):
    c, t, m = setup(tmp_path, owned=case != 'unowned', failure=case == 'failure')
    turn(t, m, RIGHT)
    def pick(prompt):
        return [] if prompt['context']['reaction_source_id'] == CHOICE else decline_steps(prompt)
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), pick)
    e = reload(c, m)
    assert not any(v.condition_id == DOUBLE_USED for v in e.state.actors[LEFT].conditions.values())
    assert bool([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) is (case == 'decline')


def test_complete_pair_menu_filters_trigger_and_unknown_talents(tmp_path):
    extras = [P+'EMPTY_STEP', P+'RETURN_THE_GRIP', P+'RIVER_TAKES_THE_SPEAR']
    c, t, m = setup(tmp_path, control=True, extra=extras)
    turn(t, m, RIGHT)
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), choose_pair)
    offer = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    # Hand, Water and Empty Step are legal on this actual control save: all C(3,2) pairs.
    labels = [o['label'] for o in offer['choice']['options']]
    assert len(labels) == 3 and len(set(labels)) == 3
    assert not any(word in str(labels) for word in ('Return the Grip', 'River Takes the Spear', 'Bend the Blade'))
    reload(c, m)


def test_compiled_ownership_is_acquired_and_source_hash_bound():
    from factory_authoring.insight_sources import current_insight_sources
    source = current_insight_sources(ROOT)[DOUBLE_CURRENT]
    text = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())[DOUBLE_CURRENT]
    assert hashlib.sha256(text.encode()).hexdigest() == source['source']['text_sha256'] == 'c15541a0367382f775db89acb0b6dfc433143c23741c83a6a91859a151af3616'
    doc = sheet([RESPONSE, HAND, WATER])
    acquired(doc, LEFT)
    bundle = compile_character(doc, actor_id=LEFT)
    assert any(r['feature_id'] == DOUBLE_CURRENT and r['kind'] == 'double_current_method'
               for r in bundle['typed_passives'])
    doc['spheres_and_talents']['cultivation_insight_record_ids'] = []
    doc['spheres_and_talents']['insight_priorities'] = [DOUBLE_CURRENT]
    assert not any(r['feature_id'] == DOUBLE_CURRENT for r in compile_character(doc, actor_id=LEFT)['typed_passives'])


def test_existing_native_insight_build_contract_keeps_every_ability_alternative():
    from stage2.insight_authority import compile_insight_stage2_authority
    from character_creation.creative_controller.linear_menus import _relation_satisfied
    catalog = json.loads((ROOT/'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    row = next(r for r in catalog['insights'] if r['record_id'] == DOUBLE_CURRENT)
    authority = compile_insight_stage2_authority(row, DOUBLE_CURRENT)
    assert authority['minimum_cl'] == 5
    assert 4 not in authority['allowed_cls'] and 5 in authority['allowed_cls']
    prerequisites = authority['typed_prerequisites']
    assert prerequisites == [{'kind': 'sphere', 'operator': 'requires', 'target_id': 'tianxia.sphere.flowing_river'}]
    assert _relation_satisfied(prerequisites[0], {'tianxia.sphere.flowing_river'}) is True
    assert _relation_satisfied(prerequisites[0], set()) is False
    change = authority['ability_change']
    assert change['selection_mode'] == 'level_selection'
    assert change['allowed_abilities'] == ['DEX', 'WIS', 'CON']
    assert change['amount'] == 1 and change['cap'] == 20
    assert authority['ability_change'] == authority['insight_ability_change']


def test_pair_keeps_bend_the_blade_own_cost_and_allied_target(tmp_path):
    from tests.auto_worker1_support import ALLY
    c, t, m = fight(tmp_path, [RESPONSE, HAND, P+'BEND_THE_BLADE'],
                       left_score=50, sheet_edit=acquired, ally=(), spheres=['tianxia.sphere.flowing_river'])
    turn(t, m, RIGHT)
    before = reload(c, m)
    def pick(prompt):
        kind = prompt['context']['reaction_source_id']
        if kind == CHOICE:
            return [prompt['choice']['options'][0]['id']]
        if kind == 'choice:needle.river_bend_target':
            return [ALLY]
        return decline_steps(prompt)
    _, prompts = settle(lambda a: act(t, m, '.weapon.bi_shou', a, target_id=LEFT), pick)
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.river_bend_target' for p in prompts)
    e = reload(c, m)
    assert e.state.actors[LEFT].resources[FOCUS] == before.state.actors[LEFT].resources[FOCUS] - 1
    bends = [v for v in e.events if v.event_type == 'PASSIVE_TRIGGERED' and
             v.source_definition_id == 'passive:'+P+'BEND_THE_BLADE']
    assert len(bends) == 1 and bends[0].target_ids == (RIGHT, ALLY)
    assert len([v for v in e.events if v.event_type == 'ATTACK_ROLLED']) == 1


def test_control_waits_for_native_perfect_posture_final_success(tmp_path):
    """A real owned late save correction must precede the Response success.

    First measure this seeded native save, then set the second scene's real
    save DC one above it. Perfect Posture's native 1d4 necessarily closes that
    one-point shortfall; no outcome, ownership or receipt is stubbed.
    """
    posture = 'tianxia.talent.beauty.perfect_posture'
    dc = 100
    for index in range(2):
        c, t, m = fight(tmp_path/str(index), [RESPONSE, HAND, WATER, posture],
            spheres=['tianxia.sphere.flowing_river', 'tianxia.sphere.beauty'],
            sheet_edit=acquired, cause_save_dc=dc,
            cause=[{'type': 'save', 'ability': 'str', 'on_fail': [
                {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}], 'on_success': [
                {'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}])
        turn(t, m, RIGHT)
        _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), choose_pair)
        e = reload(c, m)
        raw = next(v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == LEFT)
        assert raw.payload['success'] is False
        if index == 0:
            dc = int(raw.payload['total']) + 1
            assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
            continue
        correction = next(v for v in e.events if v.event_type == 'PASSIVE_TRIGGERED' and
                          v.source_definition_id == posture)
        assert correction.payload['shortfall'] == 1 and correction.payload['turned_into_success']
        assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
        response = next(v for v in e.events if v.event_type == 'PASSIVE_TRIGGERED' and
                        v.source_definition_id == 'passive:'+RESPONSE)
        assert response.sequence > correction.sequence
        success_damage = next(v for v in e.events if v.event_type == 'DAMAGE_COMMITTED' and LEFT in v.target_ids)
        assert response.sequence > success_damage.sequence
        assert any(v.condition_id == DOUBLE_USED for v in e.state.actors[LEFT].conditions.values())
        assert not any(v.condition_id.endswith('.prone') for v in e.state.actors[LEFT].conditions.values())
