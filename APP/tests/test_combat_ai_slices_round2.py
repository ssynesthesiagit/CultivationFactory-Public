"""Second review: personal ally facts and footprint-safe occupied-area escape."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate4_controller import LocalDeterministicController
from tests.test_combat_ai_slices import offline, context, hazard_engine


def component(ctx, candidate, name, options=()):
    score = LocalDeterministicController()._score_candidate(ctx, candidate, options)
    return next(c.value for c in score.components if c.component == name)


@pytest.mark.parametrize('enabled', [False, True])
def test_visible_wounded_ally_retains_healing_priority(tmp_path, monkeypatch, enabled):
    from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
    from tests.test_lock_choices import install
    from tests.test_lock2_persistence import act
    from tests.test_lock16_ai_support import context as table_context, checked

    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1' if enabled else '0')
    def actions(info):
        return [ActionDefinition(source_definition_id='test:review-heal:' + info['actor_id'],
            display_name='Heal an ally', owner_id=info['actor_id'],
            economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED',
            target_kind='ALLY_OR_SELF', range_ft=60,
            parameters={'typed': {'numbers': info['numbers'],
                'effects': [{'type': 'healing', 'flat': 20, 'applies_to': 'target'}]}})]
    install(monkeypatch, 'compile_actions', actions)
    on_hold(monkeypatch, lambda engine: engine._commit_damage(engine.state.actors[ALLY],
        25, 'FORCE', 'test:injury', RIGHT, None, reaction_depth=0))
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    checked(combat, tmp_path, mid)
    ctx = table_context(combat, mid)
    if enabled:
        assert next(a for a in ctx.own_knowledge.creatures if a.entity_id == ALLY).mode == 'DIRECT'
    heal = next(c for c in ctx.legal_candidates
                if c.source_definition_id == 'test:review-heal:' + LEFT and c.target_ids == (ALLY,))
    self_heal = next(c for c in ctx.legal_candidates
                if c.source_definition_id == heal.source_definition_id and c.target_ids == (LEFT,))
    policy = ctx.policy.model_copy(update={'support_wounded_allies': True,
        'ally_companion_priorities': {}, 'weights': {**ctx.policy.weights, 'ally_support': 1}})
    ctx = ctx.model_copy(update={'policy': policy})
    assert component(ctx, heal, 'ally_support') == 20
    assert component(ctx, heal, 'ally_support') > component(ctx, self_heal, 'ally_support')
    assert table.act(mid, heal.candidate_id, heal.decision_id, heal.state_version, 0, [])['status'] == 'COMMITTED'
    fresh = checked(combat, tmp_path, mid)
    assert fresh.state.actors[ALLY].current_hp == fresh.state.actors[ALLY].maximum_hp - 5


def test_visible_wounded_ally_keeps_measure_bonus(monkeypatch):
    from tests.test_combat_gate4_controller import engine, LING, BAI
    e = engine('REVIEW-MEASURE')
    e.state.actors[BAI].position = e.state.actors[LING].position.model_copy(update={'x': 5})
    e.state.actors[BAI].current_hp = 10
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    before = context(e, LING)
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    after = context(e, LING)
    assert next(a for a in after.own_knowledge.creatures if a.entity_id == BAI).mode == 'DIRECT'
    def measure(ctx):
        return next(c for c in ctx.legal_candidates if c.source_definition_id == 'action:ling_qi.keep_the_measure')
    assert component(after, measure(after), 'policy_sequence') == component(before, measure(before), 'policy_sequence') == 8


@pytest.mark.parametrize('distance_cells, reachable', [(4, True), (10, False)])
def test_visible_companion_retains_strike_and_approach_estimates(monkeypatch, distance_cells, reachable):
    from tests.test_combat_gate4_controller import engine, BAI, CUI, AN
    e = engine('REVIEW-COMPANION')
    e.state.actors[BAI].position = Position(x=3, y=6)
    e.state.actors[CUI].position = Position(x=4, y=6)
    e.state.actors[AN].position = Position(x=4 + distance_cells, y=6)
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    before = context(e, BAI)
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    after = context(e, BAI)
    companion = next(a for a in after.actors if a.entity_id == CUI)
    assert companion.speed_ft == e.state.actors[CUI].speed_ft > 0
    assert (distance_cells * 5 <= companion.speed_ft + 5) is reachable
    def strike(ctx):
        row = next(c for c in ctx.legal_candidates
                   if c.source_definition_id == 'action:bai_meizhen.command_cui'
                   and c.target_ids == (AN,) and c.option_ids == ('STRIKE',))
        return row, row.option_ids
    a, ao = strike(after)
    b, bo = strike(before)
    for name in ('immediate_effect', 'policy_sequence'):
        assert component(after, a, name, ao) == component(before, b, name, bo)


def test_large_damaging_start_escape_requires_entire_footprint_clear(monkeypatch):
    from combat import zones
    from combat.ext.ai_movement import destination_details, movement_order
    from combat.target_knowledge import observe
    from combat.footprints import ActorFootprintDefinition
    from tests.test_zones import _cast, AN
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    e = hazard_engine()
    actor = e.state.actors[AN]
    actor.size_category = 'Large'
    e.actor_footprints[AN] = ActorFootprintDefinition.rectangle(2, 2,
        footprint_id='footprint:review.large', source_definition_id='test:large')
    assert e._footprint(actor).width_cells == 2
    _cast(e, 'Conflagration', Position(x=13, y=6))
    # Start at the known boundary so both the clipped and fully clear spaces
    # are reachable despite Fire Terrain's movement cost.
    actor.position = Position(x=10, y=6)
    e.state.current_actor_id = AN
    e.state.current_slot_index = e.state.initiative_order.index(AN)
    hp = actor.current_hp
    e._system_start_turn()
    assert actor.current_hp < hp
    assert e._footprint(actor).width_cells == 2
    observe(e)
    actor.action_available = actor.bonus_action_available = False
    ctx = context(e)
    assert ctx.own_knowledge.harms and all(h.complete_boundary for h in ctx.own_knowledge.harms)
    cells = tuple(p for z in zones.typed_zones(e) for p in z.affected_cells)
    moves = tuple(c for c in ctx.legal_candidates if c.kind == 'MOVE')
    clipped = next(c for c in moves if c.destination not in cells
                   and e._footprint_intersects(actor, cells, position=c.destination))
    clear = next(c for c in moves if not e._footprint_intersects(actor, cells, position=c.destination))
    details = destination_details(ctx)
    assert details[clipped.candidate_id]['features']['escape'] == 0
    assert details[clipped.candidate_id]['features']['stay'] < 0
    assert details[clear.candidate_id]['features']['escape'] > 0
    assert details[clear.candidate_id]['features']['stay'] == 0
    ordered = movement_order(ctx, moves)
    assert set(ordered) == {c.candidate_id for c in moves}
    assert len(ordered) == len(moves) > 5
    selected = LocalDeterministicController().choose_primary_action(ctx).intent.candidate_id
    destination = next(c.destination for c in moves if c.candidate_id == selected)
    assert not e._footprint_intersects(actor, cells, position=destination)


@pytest.mark.parametrize('check', [
    'test_persisted_full_menus_and_ai_context_shared_across_reload',
    'test_native_ranking_and_auto_progress_policy_share_generation_without_cutting_options',
    'test_post_commit_refresh_reuses_exact_saved_session_and_matches_reload',
])
def test_flag_on_preserves_main_shared_service_seams(tmp_path, monkeypatch, check):
    """Run main's real service guards with the personal projection enabled."""
    from tests import test_menuspeed2_shared_reads as shared
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    getattr(shared, check)(tmp_path, monkeypatch)


def test_remembered_ally_does_not_leak_current_health_or_mobility(monkeypatch):
    from tests.test_combat_gate4_controller import engine, LING, BAI
    from combat.gate2_runtime_models import ConditionInstance
    from combat.target_knowledge import observe
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    e = engine('REVIEW-ALLY-MEMORY')
    ally = e.state.actors[BAI]
    ally.position = Position(x=5, y=6)
    observe(e)
    ally.conditions['hidden'] = ConditionInstance(instance_id='hidden',
        condition_id='condition:typed.invisible', source_definition_id='test',
        source_actor_id=BAI, target_id=BAI, applied_sequence=0)
    ally.position = Position(x=30, y=15)
    before = context(e, LING)
    ally.current_hp = 1
    ally.speed_ft = 100
    after = context(e, LING)
    remembered = next(a for a in after.own_knowledge.creatures if a.entity_id == BAI)
    assert remembered.mode == 'LAST_OBSERVED'
    assert before.own_knowledge == after.own_knowledge
    assert next(a for a in before.actors if a.entity_id == BAI) == next(
        a for a in after.actors if a.entity_id == BAI)
