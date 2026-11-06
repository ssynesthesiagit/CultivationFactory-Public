"""Unbroken Pursuit reserves its Motion through off-turn table commit/reload.

Only deterministic sealed fighters and local controllers; no live model calls.
"""
from types import SimpleNamespace

import pytest

from combat import movement_sequences
from combat.ext import athletics, granted_movement
from combat.gate2_runtime_models import Position
from tests.auto8f1_table_support import fixture, OWNER, FOE, SECOND
from tests.test_mgr_t16_athletics import MULTIPLE, MOBILITY, MOVING, FOCUS

UNBROKEN = athletics.UNBROKEN


@pytest.mark.parametrize('purchase,focus,combine', [
    (False, 2, False), (True, 1, False), (True, 2, False), (True, 2, True),
])
def test_unbroken_pursuit_requires_its_motion_and_separate_composition_payment(
        tmp_path, purchase, focus, combine):
    def prepare(bundles):
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        resource = next(r for r in owner['actor_template']['resources'] if r['resource_id'] == FOCUS)
        resource.update(initial=focus, maximum=2)
    game = fixture(tmp_path, [UNBROKEN, MOBILITY, MOVING] + ([MULTIPLE] if purchase else []),
        seed='athletics-pursuit-composition', bundle_transform=prepare,
        # Keep the pre-trigger route to 6,6 unoccupied too. The old foe at
        # 5,6 blocked that route within the 15-foot grant before any action.
        places={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 5, 'y': 5}, SECOND: {'x': 3, 'y': 5}},
        ask_actors=(SECOND,))
    game['turn_of'](FOE)
    before = game['stored_engine']()
    ordinary = before.state.actors[OWNER].movement_remaining_ft
    # Read the native destination's label before the trigger. Its candidate ID
    # changes with the event sequence, so answer using the freshly offered ID.
    routes = granted_movement.choices(before, before.state.actors[OWNER], 15)
    route = next((c for c in routes if c.destination == Position(x=6, y=6)), None)
    assert route is not None, ('pre-trigger grant missing 6,6',
        [(c.display_name, c.movement_cost_ft) for c in routes])
    assert route.movement_cost_ft == 15
    assert all(step != before.state.actors[FOE].position for step in route.canonical_path)
    moves = game['menu']()['moves']
    # Ground-level Position JSON omits its default z=0. Match coordinates,
    # rather than requiring a transport field the current model excludes.
    move = next((m for m in moves if (m['destination']['x'], m['destination']['y'],
                 m['destination'].get('z', 0)) == (7, 6, 0)), None)
    assert move is not None, ('triggering move missing 7,6', moves)
    prompts = []
    def choose(prompt, choice):
        prompts.append(prompt)
        source = prompt['context']['reaction_source_id']
        if 'motion_count' in source:
            assert 'Unbroken Pursuit' in str(prompt) and 'Owner' in str(prompt)
            assert 'Reaction' in str(prompt) and 'additional Martial Focus' in str(prompt)
            return ['two' if combine else 'one']
        if 'multiple_motions' in source:
            assert combine
            assert {o['id'] for o in choice['options']} == {MOBILITY, MOVING}
            return [MOBILITY]
        if source == 'choice:needle.athletics.unbroken_pursuit':
            option = next((o for o in choice['options']
                           if o['label'] == f'{route.display_name} (15 feet)'), None)
            assert option is not None, ('Pursuit destination missing', choice['options'])
            return [option['id']]
        return choice.get('preferred') or [choice['options'][0]['id']]
    # Accept the native reaction itself as well as its subsequent route and
    # composition choices. The fixture's ordinary helper declines nonchoices.
    answers = []
    for _ in range(20):
        result = game['send'](move['candidate_id'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = choose(prompt, prompt['choice'])
        answers.append(answer)
    else:
        pytest.fail('The triggering move never committed')
    engine = game['stored_engine']()
    owner = engine.state.actors[OWNER]
    assert engine.state.current_actor_id == FOE
    assert owner.position == Position(x=6, y=6)
    assert not owner.reaction_available and owner.movement_remaining_ft == ordinary
    assert owner.resources[FOCUS] == focus - 1 - int(combine)
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER]
    assert moves[-1].payload['movement_selections']['motion'] == [UNBROKEN] + ([MOBILITY] if combine else [])
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == FOCUS]
    assert len(spent) == 1 + int(combine)
    assert any(e.source_definition_id == MULTIPLE for e in spent) is combine
    counts = [p for p in prompts if 'motion_count' in p['context']['reaction_source_id']]
    assert len(counts) == int(purchase and focus > 1)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
               and e.actor_id == SECOND and OWNER in e.target_ids]
    assert len(attacks) == 1
    assert attacks[0].payload['mode'] == ('DISADVANTAGE' if combine else 'NORMAL')
    assert not getattr(engine, '_movement_sequence', None)
    assert not getattr(engine, '_movement_context', None)
    from tests.auto8f1_table_support import reload_identical
    reload_identical(game['combat'], game['match_id'], tmp_path)


def test_movement_context_is_actor_scoped_and_restored_on_nested_pause():
    engine = SimpleNamespace()
    owner, other = SimpleNamespace(entity_id=OWNER), SimpleNamespace(entity_id=FOE)
    with movement_sequences.sequence(engine, owner, context={'feature_id': UNBROKEN}):
        movement_sequences.bind(engine, owner, 'motion', [UNBROKEN, MOBILITY], [UNBROKEN])
        assert movement_sequences.context(engine, owner) == {'feature_id': UNBROKEN}
        assert movement_sequences.context(engine, other) == {}
        with pytest.raises(ValueError, match='pause'):
            with movement_sequences.sequence(engine, other):
                assert movement_sequences.context(engine, other) == {}
                assert movement_sequences.context(engine, owner) == {}
                raise ValueError('pause')
        assert movement_sequences.context(engine, owner) == {'feature_id': UNBROKEN}
        assert movement_sequences.receipt(engine, owner) == {'motion': [UNBROKEN]}
        assert not movement_sequences.enabled(engine, owner, MOBILITY)
    assert engine._movement_sequence is None and engine._movement_context is None
