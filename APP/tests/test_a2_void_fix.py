"""Review regressions through persisted service transactions and cold reload."""
import copy
import json
from pathlib import Path
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, action_sender
from tests.void_support import settle, turn
from tests.test_a2_void import SHELL, PURCHASE, SOVEREIGN, attack, accurate, pressure, landing
from tests.h1_support import ROOT


def sovereign_fight(tmp_path, **kwargs):
    supplied_edit = kwargs.pop('bundle_edit', None)
    def edit(bundle):
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Cause':
                action['parameters']['typed']['numbers']['attack_bonus'] = -100
        if supplied_edit:
            supplied_edit(bundle)
    c, t, m = fight(tmp_path, [SOVEREIGN], prepare=[
        {'type': 'condition', 'condition': 'hollowed', 'applies_to': 'target', 'duration': 'one_minute'}],
        cause=attack('weapon'), right_score=1, bundle_edit=edit, **kwargs)
    settle(action_sender(c, t, m, 'Prepare', target_id=RIGHT))
    settle(action_sender(c, t, m, 'Void-Sovereign Incarnation'))
    turn(t, m, RIGHT)
    return c, t, m


def test_paid_miss_cannot_use_only_resonance(tmp_path):
    def resources(bundle):
        if bundle['actor_id'] == LEFT:
            bundle['actor_template']['resources'].append(
                {'resource_id': 'resource:core.resonance', 'initial': 7, 'maximum': 7})
    c, t, m = sovereign_fight(tmp_path, bundle_edit=resources,
        extra_actions=[('Drain CP', {'effects': [
            {'type': 'spend_resource', 'resource_id': 'resource:core.qi', 'flat': 100}]})])
    turn(t, m, LEFT)
    settle(action_sender(c, t, m, 'Drain CP'))
    turn(t, m, RIGHT)
    settle(action_sender(c, t, m, 'Cause', target_id=LEFT), lambda p: landing(p, 2, 6))
    before = reload(c, m).state.actors[LEFT].model_dump(mode='json')
    _, prompts = settle(action_sender(c, t, m, 'Cause', target_id=LEFT))
    after = reload(c, m).state.actors[LEFT]
    assert not any(p['context']['reaction_source_id'].endswith('void_sovereign_step') for p in prompts)
    assert after.resources['resource:core.qi'] == 0
    assert after.resources['resource:core.resonance'] == 7
    assert after.position.model_dump(mode='json') == before['position']


@pytest.mark.parametrize('paid', [False, True])
@pytest.mark.parametrize('unavailable', [False, True])
def test_unaccepted_landing_preserves_allowance_and_payment(tmp_path, paid, unavailable):
    def blind_action(bundle):
        if bundle['actor_id'] == RIGHT:
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Cause'))
            action.update(source_definition_id='action:test.blind_keeper', display_name='Blind Keeper')
            action['parameters']['typed']['effects'] = [
                {'type': 'condition', 'condition': 'blinded', 'applies_to': 'target', 'duration': 'one_minute'}]
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
    c, t, m = sovereign_fight(tmp_path, bundle_edit=blind_action)
    if paid:
        # Consume this turn's free use only with an accepted, visible landing.
        settle(action_sender(c, t, m, 'Cause', target_id=LEFT), lambda p: landing(p, 2, 6))
    if unavailable:
        settle(action_sender(c, t, m, 'Blind Keeper', target_id=LEFT))
    before = reload(c, m).state.actors[LEFT].model_dump(mode='json')
    def choose(p):
        return [] if p['context']['reaction_source_id'].endswith('reaction_teleport') else pressure(p)
    prompts = []
    for _ in range(4):
        _, offered = settle(action_sender(c, t, m, 'Cause', target_id=LEFT), choose)
        prompts.extend(offered)
        if any(p['context']['reaction_source_id'].endswith('void_sovereign_step') for p in offered):
            break
    assert any(p['context']['reaction_source_id'].endswith('void_sovereign_step') for p in prompts)
    after = reload(c, m).state.actors[LEFT]
    assert after.position.model_dump(mode='json') == before['position']
    assert after.resources == before['resources']
    assert after.turn_flags.get('void_sovereign_free_turn') == before['turn_flags'].get('void_sovereign_free_turn')
    assert after.reaction_available
    assert any(p['context']['reaction_source_id'].endswith('reaction_teleport') for p in prompts) != unavailable


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('miss', [False, True])
def test_trigger_prompt_names_action_and_affected_creatures(tmp_path, ai, miss):
    if miss:
        c, t, m = sovereign_fight(tmp_path)
        suffix = 'void_sovereign_step'
    else:
        c, t, m = fight(tmp_path, [SHELL, PURCHASE], cause=attack('weapon'),
                       right_score=214, bundle_edit=accurate)
        settle(action_sender(c, t, m, 'Void Shell'))
        turn(t, m, RIGHT)
        suffix = 'void_no_purchase'
    _, prompts = settle(action_sender(c, t, m, 'Cause', ai=ai, target_id=LEFT))
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith(suffix))
    (tmp_path / 'trigger-prompt.json').write_text(json.dumps(prompt, indent=2) + '\n')
    assert prompt['context']['reactor_id'] == LEFT
    text = prompt['moment']
    assert 'Cause' in text and 'Keeper' in text and 'Visitor' in text
    assert prompt['action'] == 'Cause'
    assert prompt['affected'] == ('Keeper' if miss else 'Visitor')
    assert reload(c, m).state.actors[LEFT].reaction_available


@pytest.mark.parametrize('blinded', [False, True])
def test_ai_defender_uses_only_visible_landings(tmp_path, blinded):
    from combat.ext.teleport_steps import destinations
    from tests.test_a2_void import rolls
    def edit(bundle):
        if blinded and bundle['actor_id'] == LEFT:
            prepare = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Prepare')
            prepare['parameters']['typed']['effects'].append(
                {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'duration': 'one_minute'})
    c, t, m = sovereign_fight(tmp_path, bundle_edit=edit)
    c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    before = reload(c, m)
    actor = before.state.actors[LEFT]
    start = actor.position
    legal = destinations(before, actor, 10)
    assert bool(legal) != blinded
    for _ in range(4):
        _, prompts = settle(action_sender(c, t, m, 'Cause', target_id=LEFT))
        assert not any(p['context']['reactor_id'] == LEFT for p in prompts)
        after = reload(c, m)
        if not rolls(after)[-1].payload['provisional_hit']:
            break
    else:
        raise AssertionError('fixture did not produce a miss')
    actor = after.state.actors[LEFT]
    assert actor.resources['resource:core.qi'] == 90
    assert actor.reaction_available
    if blinded:
        assert actor.position == start
        assert 'void_sovereign_free_turn' not in actor.turn_flags
    else:
        assert actor.position in legal
        assert 'void_sovereign_free_turn' in actor.turn_flags


@pytest.mark.parametrize('ability', [SHELL, PURCHASE, SOVEREIGN])
def test_unique_review_retains_service_behavior_after_reload(tmp_path, ability):
    owned = [SHELL, PURCHASE] if ability == PURCHASE else [ability]
    c, t, m = fight(tmp_path, owned, cause=attack('weapon'), right_score=214, bundle_edit=accurate)
    settle(action_sender(c, t, m, 'Void-Sovereign Incarnation' if ability == SOVEREIGN else 'Void Shell'))
    if ability == PURCHASE:
        turn(t, m, RIGHT)
        settle(action_sender(c, t, m, 'Cause', target_id=LEFT), pressure)
    e = reload(c, m)
    if ability == PURCHASE:
        assert any(x.condition_id.endswith('.void_cost_lock') for x in e.state.actors[RIGHT].conditions.values())
    else:
        marker = '.void_sovereign_flight' if ability == SOVEREIGN else '.void_shell_hits'
        assert any(x.condition_id.endswith(marker) for x in e.state.actors[LEFT].conditions.values())
    folder = Path(ROOT) / 'authority/typed_mechanics'
    paths = [folder / 'reviewed_final.json', *sorted((folder / 'reviewed_final.d').glob('*.json'))]
    owners = []
    for path in paths:
        doc = json.loads(path.read_text())
        if ability in doc.get('mechanics', doc):
            owners.append(str(path.relative_to(ROOT)))
    assert len(owners) == 1, owners
