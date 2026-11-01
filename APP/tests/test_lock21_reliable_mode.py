"""Non-damaging rider value stays independent of the enemy HP threshold."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_models import DecisionContext
from tests.test_lock_choices import install
from tests.test_lock16_ai_support import checked, context
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act


def component(score, name):
    return next((c.value for c in score.components if c.component == name), 0)


def test_rider_beats_damage_tie_without_false_finish_and_table_replays(monkeypatch, tmp_path):
    def actions(info):
        return [ActionDefinition(source_definition_id=f'test:dose:{mode}:' + info['actor_id'],
            display_name='Deliver a dose' + (' with a guaranteed mark' if mode == 'reliable' else ''),
            owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED',
            target_kind='HOSTILE_ENTITY', range_ft=60,
            parameters={'expected_damage': 20, **({'rider_utility': 8} if mode == 'reliable' else {}),
                'typed': {'numbers': info['numbers'], **({'replacement': {'reliable': True}} if mode == 'reliable' else {}), 'effects': [
                    {'type': 'damage', 'flat': 20, 'damage_types': ['force'], 'applies_to': 'target'},
                    *([{'type': 'mark', 'mark': 'Test Dose', 'applies_to': 'target',
                        'duration': {'kind': 'until_end_of_next_turn'}}] if mode == 'reliable' else [])]}})
                for mode in ('base', 'reliable')]
    install(monkeypatch, 'compile_actions', actions)
    def injury(engine):
        foe = engine.state.actors[RIGHT]
        engine._commit_damage(foe, foe.current_hp - 24, 'FORCE', 'test:injury', LEFT, None, reaction_depth=0)
    on_hold(monkeypatch, injury)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = checked(combat, tmp_path, mid)
    before = (engine.state.model_dump(mode='json'), len(engine.events), len(engine.rolls))
    ctx = context(combat, mid)
    base = next(c for c in ctx.legal_candidates if c.source_definition_id == 'test:dose:base:' + LEFT)
    reliable = next(c for c in ctx.legal_candidates if c.source_definition_id == 'test:dose:reliable:' + LEFT)
    assert base.metadata['expected_damage'] == reliable.metadata['expected_damage'] == 20
    assert 'rider_utility' not in base.metadata and reliable.metadata['rider_utility'] == 8
    base_score = combat.controller._score_candidate(ctx, base, ())
    reliable_score = combat.controller._score_candidate(ctx, reliable, ())
    assert component(base_score, 'immediate_effect') == component(reliable_score, 'immediate_effect')
    assert component(base_score, 'defeat_prevention_or_finish') == component(reliable_score, 'defeat_prevention_or_finish') == 0
    assert reliable_score.total - base_score.total == 8 * ctx.policy.weights['immediate_effect']
    assert combat.controller.choose_primary_action(ctx).intent.candidate_id == reliable.candidate_id
    assert DecisionContext.model_validate_json(ctx.model_dump_json()) == ctx
    assert before == (engine.state.model_dump(mode='json'), len(engine.events), len(engine.rolls))
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    fresh = checked(combat, tmp_path, mid)
    assert fresh.state.actors[RIGHT].current_hp == 4
    from combat.typed_executor import bears_mark
    assert bears_mark(fresh.state.actors[RIGHT], LEFT, 'Test Dose')


@pytest.mark.parametrize('utility', [None, 0, False, True, 8.5, '8'])
def test_absent_or_invalid_utility_preserves_legacy_candidate_and_score(utility):
    from tests.test_combat_gate4_controller import engine, choose, AN
    from combat.gate2_runtime_models import CandidateKind
    e = engine('L21-RIDER-INERT')
    _, ctx = choose(e, AN)
    actor = e.state.actors[AN]
    action = ActionDefinition(source_definition_id='test:utility', display_name='Test effect', owner_id=AN,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'expected_damage': 0})
    e.action_catalog[action.source_definition_id] = action
    legacy = e._candidate(CandidateKind.ACTION, actor, action.source_definition_id, action.display_name)
    e.action_catalog[action.source_definition_id] = action.model_copy(update={'parameters': {**action.parameters, 'rider_utility': utility}})
    candidate = e._candidate(CandidateKind.ACTION, actor, action.source_definition_id, action.display_name)
    assert candidate == legacy
    from combat.gate4_controller import LocalDeterministicController
    controller = LocalDeterministicController()
    assert controller._score_candidate(ctx, candidate, ()) == controller._score_candidate(ctx, legacy, ())


def test_precomputed_area_damage_and_remembered_target_do_not_gain_damage():
    from tests.test_combat_gate4_controller import engine, choose, AN
    from combat.gate2_runtime_models import CandidateKind
    from combat.gate4_controller import LocalDeterministicController
    e = engine('L21-RIDER-AREA')
    _, ctx = choose(e, AN)
    action = ActionDefinition(source_definition_id='test:area', display_name='Area effect', owner_id=AN,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'expected_damage': 20, 'rider_utility': 8})
    e.action_catalog[action.source_definition_id] = action
    row = e._candidate(CandidateKind.ACTION, e.state.actors[AN], action.source_definition_id,
        action.display_name, metadata={'expected_damage': 60, 'hostiles_in_area': 3})
    assert row.metadata['expected_damage'] == 60 and row.metadata['rider_utility'] == 8
    seen = LocalDeterministicController()._score_candidate(ctx, row, ())
    hidden = row.model_copy(update={'metadata': {**row.metadata, 'target_knowledge': 'LAST_OBSERVED'}})
    assert component(seen, 'rider_utility') > 0
    assert component(LocalDeterministicController()._score_candidate(ctx, hidden, ()), 'rider_utility') == 0
