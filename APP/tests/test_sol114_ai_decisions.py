"""AI reaction and area decisions through Table commit, reload and replay."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate4_models import ReactionContext
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install

GUARD = 'tianxia.path.body_refining.feature.stamina_guard'
FORM = 'tianxia.talent.destruction.calamity_form'


@pytest.mark.parametrize('pending', [0, 1, 3, 5, 7, 8])
def test_generic_reaction_selection_agrees_with_scores(pending):
    policy = PolicyLibrary(H.ROOT).fallback()
    ctx = ReactionContext(match_id='m', state_version=1, decision_id='d', checkpoint='cp',
        reactor_id='r', reaction_source_id='reaction:practice', pending_damage=pending,
        legal_reaction_ids=('reaction:practice',), resources={}, conditions=(), policy=policy)
    choice = LocalDeterministicController().choose_reaction(ctx)
    scores = {s.candidate_id: s.total for s in choice.record.scored_alternatives}
    assert choice.decision.selection == 'USE'
    assert scores[choice.record.selected_candidate_id] == max(scores.values())
    reserved = ctx.model_copy(update={'policy': policy.model_copy(update={
        'reaction_rules': {'reaction:practice': {'minimum_packet': 8}}})})
    choice = LocalDeterministicController().choose_reaction(reserved)
    assert choice.decision.selection == ('USE' if pending >= 8 else 'DECLINE')
    scores = {s.candidate_id: s.total for s in choice.record.scored_alternatives}
    assert scores[choice.record.selected_candidate_id] == max(scores.values())


def checked(combat, mid, tmp_path):
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == combat._load_session(mid).engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def test_table_native_guard_uses_generic_score_for_sub_eight_packet(monkeypatch, tmp_path):
    from combat.gate2_runtime_content import AN
    from tests.test_lock13_native_opportunity import fight, ME
    from tests.test_lock2_persistence import act
    combat, table, mid = fight(tmp_path)
    combat.set_controller_mode(mid, actor_id=AN, controller_mode='LOCAL_AUTO')
    policy = combat.policies.fallback()
    monkeypatch.setattr(combat.policies, 'for_actor', lambda _: (policy, True))
    def impact(engine):
        # Exhaust the competing guard through a recorded payment, so this
        # checkpoint tests Stamina Guard rather than the first legal reaction.
        actor = engine.state.actors[AN]
        engine._spend_resource(actor, 'resource:an_eui.severance_edge',
                               actor.resources['resource:an_eui.severance_edge'], 'test:training_payment')
        engine._commit_damage(engine.state.actors[AN], 3, 'FORCE', 'test:impact', ME,
                              engine._active_intent, reaction_depth=0)
    H.on_hold(monkeypatch, impact)
    before = combat._load_session(mid).engine.state.actors[AN]
    hp, stamina = before.current_hp, before.resources['resource:an_eui.stamina']
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    engine = checked(combat, mid, tmp_path)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == 'reaction:core.stamina_guard']
    assert len(resolved) == 1
    assert not engine.state.actors[AN].reaction_available
    assert engine.state.actors[AN].resources['resource:an_eui.stamina'] == stamina - 1
    assert engine.state.actors[AN].current_hp > hp - 3


@pytest.mark.parametrize('packet', [1, 3, 7])
def test_ai_uses_stamina_guard_for_small_packet_and_reloads(monkeypatch, tmp_path, packet):
    source = 'test:small_training_packet'
    def actions(info):
        if info['actor_id'] != H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=source, display_name='Training impact',
            owner_id=H.LEFT, economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'numbers': info['numbers'], 'effects': [
                {'type': 'damage', 'applies_to': 'self', 'flat': packet, 'damage_type': 'force'}]}})]
    install(monkeypatch, 'compile_actions', actions)
    combat, table, mid = H.table_fight(tmp_path, [GUARD], ally_talents=[], primary='Stamina')
    combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    production = combat.controller
    class TrainingController:
        def choose_primary_action(self, ctx):
            candidate = next(c for c in ctx.legal_candidates if c.source_definition_id == source)
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(ctx)
        def choose_reaction(self, ctx):
            return production.choose_reaction(ctx)
    combat.controller = TrainingController()
    state = table.state(mid)
    before = combat._load_session(mid).engine.state.actors[H.LEFT]
    hp, stamina = before.current_hp, before.resources['resource:core.stamina']
    assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
    engine = checked(combat, mid, tmp_path)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and GUARD in (e.source_definition_id or '')]
    assert len(resolved) == 1
    actor = engine.state.actors[H.LEFT]
    assert not actor.reaction_available
    assert actor.resources['resource:core.stamina'] < stamina
    assert actor.current_hp > hp - packet


def test_calamity_family_uses_safe_shape_on_actual_ai_turn(tmp_path, monkeypatch):
    combat, table, mid = H.table_fight(tmp_path, [FORM], ally_talents=[])
    combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    # Give the printed ability priority; placement still comes entirely from
    # production candidate generation, risk classification and controller.
    fallback = combat.policies.fallback()
    engine = combat._load_session(mid).engine
    form_ids = {sid for sid in engine.action_catalog if '.calamity_form.' in sid}
    policy = fallback.model_copy(update={'action_priorities': {
        sid: 2000 if sid.endswith('.line') else 1000 for sid in form_ids}})
    monkeypatch.setattr(combat.policies, 'for_actor', lambda _: (policy, True))
    ctx = build_decision_context(engine, policy, for_ai=True)
    placements = [c for c in ctx.legal_candidates if c.source_definition_id in form_ids]
    assert any(c.metadata.get('unavoidable_allies_in_area') for c in placements)
    assert any(c.metadata.get('hostiles_in_area') and not c.metadata.get('unavoidable_allies_in_area') for c in placements)
    choice = combat.controller.choose_primary_action(ctx)
    chosen = next(c for c in placements if c.candidate_id == choice.intent.candidate_id)
    state = table.state(mid)
    sequence = engine.state.event_sequence
    assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
    loaded = checked(combat, mid, tmp_path)
    events = [e for e in loaded.events if e.sequence > sequence and '.calamity_form.' in (e.source_definition_id or '')]
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == H.RIGHT for e in events)
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id in {H.LEFT, H.ALLY} for e in events)
    assert not chosen.metadata.get('unavoidable_allies_in_area')
    assert '.sphere' in chosen.source_definition_id


@pytest.mark.parametrize('scope', ['creatures_in_area', 'enemies_in_area'])
@pytest.mark.parametrize('kind', ['condition', 'healing'])
def test_area_safety_uses_recipients_not_estimated_damage(monkeypatch, tmp_path, scope, kind):
    source = 'test:placement'
    def actions(info):
        if info['actor_id'] != H.LEFT:
            return []
        effect = ({'type': 'condition', 'condition': 'prone', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}
                  if kind == 'condition' else {'type': 'healing', 'flat': 1})
        return [ActionDefinition(source_definition_id=source, display_name='Practice field', owner_id=H.LEFT,
            economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='CELL', range_ft=60,
            parameters={'typed': {'numbers': info['numbers'], 'area': {'shape': 'sphere', 'size_ft': 5},
                'effects': [{'type': 'save', 'ability': 'WIS', 'applies_to': scope,
                             'on_fail': [effect], 'on_success': []}]}})]
    install(monkeypatch, 'compile_actions', actions)
    combat, _, mid = H.table_fight(tmp_path, [], ally_talents=[])
    engine = combat._load_session(mid).engine
    policy = combat.policies.fallback()
    ctx = build_decision_context(engine, policy, for_ai=True)
    rows = [c for c in ctx.legal_candidates if c.source_definition_id == source]
    ctx = ctx.model_copy(update={'legal_candidates': tuple(rows)})
    choice = combat.controller.choose_primary_action(ctx)
    considered = {r.candidate_id for r in choice.record.scored_alternatives}
    risky = {c.candidate_id for c in rows if c.metadata.get('unavoidable_allies_in_area')}
    if scope == 'creatures_in_area' and kind == 'condition':
        assert risky and considered.isdisjoint(risky)
        # No safe placement: retain legal unavoidable options rather than fail.
        ctx = ctx.model_copy(update={'legal_candidates': tuple(c for c in rows if c.candidate_id in risky)})
        assert combat.controller.choose_primary_action(ctx).intent.candidate_id in risky
    else:
        assert not risky and considered == {c.candidate_id for c in rows}
