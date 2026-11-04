"""Hundred-Form Combination through actual Attack sequences and later strikes."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, settle, turn
H = 'TAL_IRON_FIST_HUNDRED_FORM_COMBINATION'
B = 'TAL_IRON_FIST_BREAKING_KNUCKLE'
E = 'TAL_IRON_FIST_ELBOW_IN_THE_DOOR'
X = 'tianxia.path.body_refining.feature.extra_attack'
TRAIN = 'TAL_IRON_FIST_IRON_FIST_TRAINING'
ACTIVE = 'condition:typed.hundred_form_combination'

def setup(tmp_path, owned=True, extra=True, cl=10):
    return fight(tmp_path, [TRAIN, B, E, *([H] if owned else []), *([X] if extra else [])], cl=cl, left_score=50, prepare=[{'type': 'attack', 'attack_kind': 'unarmed', 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning'], 'applies_to': 'target'}]}], prepare_attack_bonus=100)

def combo(e):
    return next((c for c in e.state.actors[LEFT].conditions.values() if c.condition_id == ACTIVE), None)

def picker(p):
    source = p['context']['reaction_source_id']
    if source == 'choice:needle.hundred_forms':
        return [B, E]
    if source == 'choice:needle.iron_forms':
        return [p['choice']['options'][0]['id']]
    return [p['choice']['options'][0]['id']]

@pytest.mark.parametrize('ai', [False, True])
def test_two_actual_strikes_unlock_distinct_forms_once_each_then_expire(tmp_path, ai):
    c, t, m = setup(tmp_path)
    _, prompts = settle(action_sender(c, t, m, 'Unarmed Strike (Iron Fist)', ai=ai, target_id=RIGHT), picker)
    e = reload(c, m)
    held = combo(e)
    assert held and set(held.data['forms']) == {B, E} and (held.data['used'] == [])
    assert len([v for v in e.events if v.event_type == 'ATTACK_ROLLED']) == 2
    if not ai:
        assert any((p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    before = len(e.events)
    _, uses = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), picker)
    e = reload(c, m)
    assert set(combo(e).data['used']) == {B, E}
    assert len([p for p in uses if p['context']['reaction_source_id'] == 'choice:needle.iron_forms']) == 2
    assert any((v.event_type == 'DAMAGE_COMMITTED' and v.payload['hp_damage'] == 4 for v in e.events[before:]))
    assert any((v.event_type == 'ZONE_CREATED' and v.payload['zone']['trigger_profile'].get('placed', {}).get('tag') == 'iron_elbow' for v in e.events[before:]))
    _, again = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), picker)
    assert not any((p['context']['reaction_source_id'] == 'choice:needle.iron_forms' for p in again))
    turn(t, m, RIGHT)
    assert combo(reload(c, m)) is None

def test_manual_decline_leaves_no_combination_or_extra_cost(tmp_path):
    c, t, m = setup(tmp_path)

    def decline(p):
        return [] if p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' else picker(p)
    _, prompts = settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), decline)
    e = reload(c, m)
    assert combo(e) is None and e.state.actors[LEFT].resources['resource:core.qi'] == 100
    assert any((p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' for p in prompts))

@pytest.mark.parametrize('owned,extra', [(False, True), (True, False)])
def test_unowned_or_one_attack_never_unlocks_combination(tmp_path, owned, extra):
    c, t, m = setup(tmp_path, owned=owned, extra=extra)
    _, prompts = settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), picker)
    assert combo(reload(c, m)) is None
    assert not any((p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' for p in prompts))

def test_extra_strike_outside_attack_action_does_not_unlock_combination(tmp_path):
    c, t, m = setup(tmp_path)
    prompts = []
    for _ in range(2):
        _, p = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), picker)
        prompts.extend(p)
    assert combo(reload(c, m)) is None and (not any((p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' for p in prompts)))

def test_declining_form_keeps_both_uses_for_a_later_real_hit(tmp_path):
    c, t, m = setup(tmp_path)
    settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), picker)

    def decline(p):
        return [] if p['context']['reaction_source_id'] == 'choice:needle.iron_forms' else picker(p)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), decline)
    assert combo(reload(c, m)).data['used'] == []
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), picker)
    assert set(combo(reload(c, m)).data['used']) == {B, E}

def test_two_actual_misses_still_unlock_the_printed_combination(tmp_path):
    c, t, m = fight(tmp_path, [TRAIN, B, E, H, X], cl=10, left_score=50, cause_target='SELF', cause=[{'type': 'ac_bonus', 'applies_to': 'self', 'flat': 1000, 'duration': 'one_minute'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), picker)
    e = reload(c, m)
    assert len([v for v in e.events if v.event_type == 'ATTACK_ROLLED']) == 2
    assert e.state.actors[RIGHT].current_hp == 1000 and combo(e) is not None
    assert combo(e).data['used'] == []

def test_rising_knee_waits_for_a_real_grapple_before_extra_damage(tmp_path):
    rising = 'TAL_IRON_FIST_RISING_KNEE'
    c, t, m = fight(tmp_path, [TRAIN, B, rising, H, X], cl=10, left_score=50, prepare_attack_bonus=100, prepare=[{'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'duration': 'until_removed'}, {'type': 'attack', 'attack_kind': 'unarmed', 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning'], 'applies_to': 'target'}]}])

    def pick(p):
        return [B, rising] if p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' else picker(p)
    settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), pick)
    e = reload(c, m)
    assert combo(e).data['used'] == []
    before = len(e.events)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), pick)
    e = reload(c, m)
    assert any((v.condition_id == 'condition:typed.grappled' and v.source_actor_id == LEFT for v in e.state.actors[RIGHT].conditions.values()))
    assert set(combo(e).data['used']) == {B, rising}
    assert any((v.event_type == 'DAMAGE_ROLLED' and v.payload['expression'] == '1d6+0' for v in e.events[before:]))

def test_defeating_the_last_target_does_not_ask_a_post_terminal_form_choice(tmp_path):
    """Temporary HP absorbs strike one; strike two causes an actual massive-damage defeat."""
    c, t, m = fight(tmp_path, [TRAIN, B, E, H, X], cl=10, left_score=4010, cause_target='SELF', cause=[{'type': 'temp_hp', 'applies_to': 'self', 'flat': 2000}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    turn(t, m, LEFT)
    _, prompts = settle(lambda a: act(t, m, 'Unarmed Strike (Iron Fist)', a, target_id=RIGHT), picker)
    e = reload(c, m)
    assert not e.state.actors[RIGHT].active
    assert e.state.terminal_result is not None
    assert len([v for v in e.events if v.event_type == 'ATTACK_ROLLED']) == 2
    assert not any((p['context']['reaction_source_id'] == 'choice:needle.hundred_forms' for p in prompts))
    assert combo(e) is None
