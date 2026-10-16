"""Earth Speed changes preserve distance already committed in another mode."""
import pytest
import json

from combat import flight, granted_movement
from combat.gate2_runtime_models import Position
from combat.typed_executor import bears_mark
from tests.cw2_service_support import seal
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_committed_movement import EARTH, CLOD, native_burden
from tests.worker2_support import FOE, OWNER, fixture, reload, turn


# These dynamic inputs also belong to the native regressions imported above.
# Keep their paths literal so older public exporters can discover them; a
# missing overlay must fail qualification rather than imitate an engine bug.
INPUTS = (
    'combat/rules/feature_blocks.d/riders_c2.json',
    'combat/rules/feature_blocks.d/riders_lane9.json',
    'combat/rules/feature_blocks.d/a2_qi_subpaths_6.json',
    'combat/rules/feature_blocks.d/walkable-roofs.json',
    'combat/rules/feature_blocks.d/athletics-second-pass.json',
)


def test_acceptance_inputs_include_the_dynamic_slam_earth_and_climbing_providers():
    from combat.typed_reactions import rules
    installed = rules()
    for path in INPUTS:
        data = json.loads((ROOT / path).read_text())
        for source, block in data['features'].items():
            assert installed['features'][source] == block, (path, source)


@pytest.mark.parametrize('mode', ['fly', 'climb'])
def test_movement_safety_uses_the_selected_mode_with_zero_walking_speed(mode):
    from combat.ext.movement_safety import movement_allowed
    from combat.gate2_runtime_models import CandidateKind
    from tests.test_roof_movement import engine_at_wall, condition
    engine, actor = engine_at_wall(climb_speed=30)
    actor.fly_speed_ft = 30
    condition(actor, 'condition:typed.review_walking_penalty',
              data={'movement_speed_reductions': {'walk': actor.speed_ft}})
    move = engine._candidate(CandidateKind.MOVE, actor, 'system:combat.movement',
        'Move', destination=actor.position.model_copy(update={'y': actor.position.y + 1}),
        metadata={'movement_mode': mode})
    assert engine._effective_speed(actor) == 0
    assert movement_allowed(engine, actor, move, None) is None
    condition(actor, 'condition:typed.review_immobilized', data={'rule': {'speed_zero': True}})
    assert movement_allowed(engine, actor, move, None) is False


def commit_route(table, mid, path, response=None):
    """Use the real chosen-route API, including its transactional reactions."""
    state = table.state(mid)
    menu = state['menu']
    points = [p.model_dump(mode='json') for p in path]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'],
                                    FOE, points, 'fly')
    answers = []
    prompts = []
    for _ in range(20):
        result = table.commit_move_path(mid, quote['candidate']['candidate_id'],
            menu['decision_id'], menu['state_version'], FOE, points,
            state['last_sequence'], movement_mode='fly', reactions=answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        rid = prompt['context']['reaction_source_id']
        pick = {'choice:needle.earth_response': response,
                'choice:needle.anchor_speed': 'walk'}.get(rid)
        answer = {**prompt['context'], 'selection': 'USE' if pick else 'DECLINE'}
        if pick:
            answer['option_ids'] = [pick]
        answers.append(answer)
    raise AssertionError('Route did not settle')


@pytest.mark.parametrize('response,penalty', [('anchor', 10), ('drag', 5)])
@pytest.mark.parametrize('spent', [5, 10, 15])
def test_walking_penalty_never_refunds_spent_flight_after_table_reload(tmp_path, response, penalty, spent):
    def wings(bundles):
        bundles[2]['actor_template'].update(speed_ft=10, fly_speed_ft=30, hover=True)
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=6, owner_dc=1,
        bundle_transform=wings, foe_sheet=sheet([], cl=6, score=30),
        foe_position={'x': 3, 'y': 5}, seed='EARTH-SPENT-' + response)
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    # Explicit flight along the ground retains surface contact for Anchor.
    path = [Position(x=3, y=5-i) for i in range(spent // 5 + 1)]
    commit_route(table, mid, path)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[FOE]
    assert flight.remaining(engine, actor, 'fly') == 30 - spent
    assert actor.movement_remaining_ft == max(0, 10 - spent)
    assert actor.turn_flags.get('flight_movement_overrun_ft', 0) == max(0, spent - 10)
    assert bears_mark(actor, OWNER, 'Burden Mark')

    endpoint = path[-1].model_copy(update={'y': path[-1].y - 1})
    prompts = commit_route(table, mid, [path[-1], endpoint], response)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[FOE]
    assert any(p['context']['reaction_source_id'] == 'choice:needle.earth_response' for p in prompts)
    assert actor.position == endpoint
    assert engine._effective_speed(actor) == 10 - penalty
    assert flight.profile(engine, actor).speed_ft == 30
    assert flight.remaining(engine, actor, 'fly') == 30 - spent - 5
    assert flight.budget(engine, actor).available_ft == 30 - spent - 5
    assert granted_movement.routes(engine, actor, 5)
    if response == 'drag':
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id.endswith('DRAG_DOWN')]
        assert saves and saves[-1].payload['total'] >= 1
    # A later committed flight segment must consume, rather than restore, feet.
    last = endpoint.model_copy(update={'y': endpoint.y + 1})
    commit_route(table, mid, [endpoint, last])
    engine = reload(tmp_path, mid)
    assert flight.remaining(engine, engine.state.actors[FOE], 'fly') == 30 - spent - 10
