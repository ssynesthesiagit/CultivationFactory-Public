"""Cascade uses actual table choices, saves, penalties and persisted deadlines."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT, sheet
from tests.auto_worker1_support import act, turn, reload, action_sender

OWNER, FIRST, SECOND = ('actor:factory.cascade-' + n for n in ('owner', 'first', 'second'))
CASCADE = 'tianxia.talent.pressure_points.nine_needle_cascade'
TRAINING = 'PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING'
NUMB = 'PRESSURE_POINTS_BASE_NUMBING_POINT'


def settle(send, picker=None):
    """Accept ordinary Use/Pass reactions, and answer bounded ability menus.

    An ordinary reaction has no option IDs: an empty option list still means Use.
    Only an explicit empty selection from an ability menu means Decline.
    """
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']
        prompts.append(p)
        choice = p.get('choice')
        ids = [o['id'] for o in (choice or {}).get('options', [])]
        selected = picker(p) if picker else ids[:1]
        answers.append({**p['context'], 'selection': 'DECLINE' if choice and not selected else 'USE',
                        'option_ids': selected})
    raise AssertionError('too many choices')


def fixture(tmp_path, *, friendly=False, success=False, owned=True, offturn=False, far=False, legacy=False, blind=False):
    talents = [TRAINING, NUMB] + ([CASCADE] if owned else [])
    if offturn:
        talents.append('tianxia.talent.pressure_points.needle_meets_blade')
    bundles = []
    for aid, label in ((OWNER, 'Point Keeper'), (FIRST, 'First Fighter'), (SECOND, 'Nearby Friend' if friendly else 'Nearby Fighter')):
        doc = sheet(talents if aid == OWNER else [], cl=15, dc=100,
                    score=50 if aid == OWNER else (214 if aid == SECOND and success else 14),
                    kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}}
                    if offturn and aid == FIRST else None)
        doc['identity']['display_name'] = label
        stats = doc['ability_scores_and_statistics']
        stats['armor_class']['base_value'] = 1
        stats['hit_points']['maximum'] = 1000
        stats['technique_attack_bonus'] = 100
        # Only explicitly owned talents; do not silently grant every sphere base.
        doc.setdefault('spheres_and_talents', {})['automatic_sphere_component_record_ids'] = []
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
        if aid == OWNER and legacy:
            leaf = next(r for r in bundle['typed_passives'] if r.get('feature_id') == CASCADE)
            extra = leaf['point_effects'][0]
            extra.pop('choice_name')
            extra.pop('choice_prompt')
            extra.pop('requires_perception')
            extra.pop('prefer')
            extra['who'] = 'hostile'
            extra['effects'][0]['on_fail'] = [{'type': 'mark', 'mark': 'Numbing Point',
                'applies_to': 'target', 'duration': {'kind': 'until_removed'}}]
        if aid == OWNER and blind:
            source = 'action:test.cascade.blindfold'
            bundle['actor_template']['action_ids'].append(source)
            bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Blindfold',
                'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                'parameters': {'typed': {'effects': [{'type': 'condition', 'condition': 'blinded',
                    'applies_to': 'self', 'duration': 'until_removed'}], 'numbers': {}, 'riders': []}}})
        if legacy or blind:
            from combat.canonical import canonical_sha256

            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, [OWNER, FIRST, SECOND],
        {OWNER: 'team:a', FIRST: 'team:b', SECOND: 'team:a' if friendly else 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FIRST: {'x': 4, 'y': 6}, SECOND: {'x': 10 if far else 3, 'y': 5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER] + ([SECOND] if friendly else []), [FIRST] + ([] if friendly else [SECOND]),
        control_modes={a: 'MANUAL' for a in (OWNER, FIRST, SECOND)}, match_seed='CASCADE-R1',
        display_name='Cascade regression', maximum_rounds=10)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    if owned:
        assert act(table, mid, 'Touch the Point: Nine-Needle Cascade')['status'] == 'COMMITTED'
    if blind:
        assert act(table, mid, 'Blindfold')['status'] == 'COMMITTED'
    if offturn:
        settle(lambda a: act(table, mid, 'Unarmed Strike', a, target_id=FIRST),
               lambda p: pick(p, option='numb_arm'))
    return combat, table, mid


def pick(prompt, *, decline=False, option='numb_leg'):
    choice = prompt['context']['reaction_source_id']
    ids = [o['id'] for o in (prompt.get('choice') or {}).get('options', [])]
    if choice == 'choice:needle.beauty_targets':
        return [] if decline or SECOND not in ids else [SECOND]
    if choice == 'choice:needle.pp_numbing':
        return [option]
    return ids[:1]


@pytest.mark.parametrize('friendly', [False, True])
@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_cascade_real_secondary_choice_penalty_reload_and_expiry(tmp_path, friendly, mode):
    c, t, m = fixture(tmp_path, friendly=friendly)
    c.set_controller_mode(m, actor_id=OWNER, controller_mode=mode)
    before = c._load_session(m).engine.state.model_dump(mode='json')
    paused = act(t, m, 'Unarmed Strike', target_id=FIRST)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert c._load_session(m).engine.state.model_dump(mode='json') == before
    assert act(t, m, 'Unarmed Strike', target_id=FIRST)['reaction'] == paused['reaction']
    result, prompts = settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=FIRST), pick)
    target_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.beauty_targets')
    assert SECOND in [o['id'] for o in target_prompt['choice']['options']]
    text = str(target_prompt)
    for phrase in ('Nine-Needle Cascade', 'Unarmed Strike', 'First Fighter', 'Dexterity', 'Numbing Point'):
        assert phrase in text
    numbing = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.pp_numbing')
    assert numbing['context']['reactor_id'] == OWNER
    assert 'next turn' in str(numbing) and '10 feet' in str(numbing)
    e = reload(c, m)
    assert bears_mark(e.state.actors[SECOND], OWNER, 'Pressure Point')
    assert not bears_mark(e.state.actors[SECOND], OWNER, 'Numbing Point')
    assert e._effective_speed(e.state.actors[SECOND]) == 20
    assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == SECOND and not v.payload['success'] for v in e.events)
    turn(t, m, FIRST)
    turn(t, m, OWNER)
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[SECOND]) == 30
    assert bears_mark(e.state.actors[SECOND], OWNER, 'Pressure Point')
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    assert not bears_mark(reload(c, m).state.actors[SECOND], OWNER, 'Pressure Point')


@pytest.mark.parametrize('case', ['success', 'decline', 'far', 'nonowner', 'blind'])
def test_cascade_save_success_decline_range_and_nonowner_are_inert(tmp_path, case):
    c, t, m = fixture(tmp_path, success=case == 'success', far=case == 'far', owned=case != 'nonowner', blind=case == 'blind')
    _, prompts = settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=FIRST),
                        lambda p: pick(p, decline=case == 'decline'))
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[SECOND]) == 30
    assert not bears_mark(e.state.actors[SECOND], OWNER, 'Pressure Point')
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.pp_numbing' for p in prompts)
    saves = [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == SECOND]
    assert bool(saves) == (case == 'success')
    if saves:
        assert saves[-1].payload['success']


def test_legacy_sealed_cascade_keeps_its_original_tag_and_no_new_numbing_choice(tmp_path):
    c, t, m = fixture(tmp_path, legacy=True)
    _, prompts = settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=FIRST), pick)
    e = reload(c, m)
    assert bears_mark(e.state.actors[SECOND], OWNER, 'Numbing Point')
    assert not bears_mark(e.state.actors[SECOND], OWNER, 'Pressure Point')
    assert e._effective_speed(e.state.actors[SECOND]) == 30
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.pp_numbing' for p in prompts)


def test_cascade_ai_selects_secondary_and_numbing_without_prompt(tmp_path):
    c, t, m = fixture(tmp_path)
    send = action_sender(c, t, m, 'Unarmed Strike', ai=True, target_id=FIRST)
    _, prompts = settle(send)
    assert not prompts
    e = reload(c, m)
    assert bears_mark(e.state.actors[SECOND], OWNER, 'Pressure Point')
    assert any(mod.target_field == 'attack_mode' and mod.value == 'DISADVANTAGE'
               for mod in e.state.actors[SECOND].modifiers.values())
    c.set_controller_mode(m, actor_id=OWNER, controller_mode='MANUAL')
    turn(t, m, SECOND)
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=OWNER))
    e = reload(c, m)
    rolls = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == SECOND]
    assert rolls[-1].payload['mode'] == 'DISADVANTAGE'


def test_cascade_ai_declines_when_only_itself_and_friends_are_available(tmp_path):
    c, t, m = fixture(tmp_path, friendly=True)
    _, prompts = settle(action_sender(c, t, m, 'Unarmed Strike', ai=True, target_id=FIRST))
    assert not prompts
    e = reload(c, m)
    for aid in (OWNER, SECOND):
        assert not bears_mark(e.state.actors[aid], OWNER, 'Pressure Point')
    assert not any(v.event_type == 'SAVE_ROLLED' for v in e.events)


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_cascade_manual_owner_chooses_during_enemy_turn(tmp_path, ai, mode):
    c, t, m = fixture(tmp_path, offturn=True)
    c.set_controller_mode(m, actor_id=OWNER, controller_mode=mode)
    turn(t, m, FIRST)
    send = action_sender(c, t, m, 'Dao (Saber / Broadsword) attack', ai=ai, target_id=OWNER)
    _, prompts = settle(send, pick)
    numbing = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.pp_numbing')
    assert numbing['context']['reactor_id'] == OWNER
    assert 'Needle Meets Blade' in str(numbing) and 'Nearby Fighter' in str(numbing)
    assert reload(c, m)._effective_speed(reload(c, m).state.actors[SECOND]) == 20
