"""AI placement choices through persisted service fights, plus pure-query isolation."""
import pytest

from combat import candidate_knowledge
from combat.ext.teleport_steps import destinations
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_mmx86_paid_teleport_variant import OWNER, FOE, _owner_sheet, _write
from tests.test_hidden_targeting import hidden_fight, LEFT, RIGHT, turn, move_to
from tests.test_lock2_persistence import act


def ai_fight(tmp_path, *, map_terrain=()):
    docs = [_owner_sheet(), sheet([], cl=17)]
    docs[0]['ability_scores_and_statistics']['speed']['walking_ft'] = 5
    for aid, doc in zip((OWNER, FOE), docs):
        _write(doc, aid, tmp_path)
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip((OWNER, FOE), docs)]
    combat = CombatService(ROOT, tmp_path)
    arena = dict(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['map_terrain'] = list(map_terrain)
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 1}, FOE: {'x': 17, 'y': 1}},
        arena, [OWNER], [FOE],
        control_modes={OWNER: 'LOCAL_AUTO', FOE: 'MANUAL'},
        match_seed='SOL149', display_name='AI teleport regression', maximum_rounds=6)['match_id']
    session = combat._load_session(mid)
    while session.engine.state.current_actor_id != OWNER:
        end = next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN')
        session.submit_intent(ActionIntent(intent_id='end', decision_id=end.decision_id,
            candidate_id=end.candidate_id, state_version=end.state_version, actor_id=end.actor_id),
            primary_decision_record=None, reaction_provider=None)
    return combat, session


def test_ai_teleport_out_of_damaging_terrain_estimates_and_replays(tmp_path):
    from combat import zones

    # Obsidian has actual distance-triggered damage; ordinary Ash Terrain
    # denies Reactions rather than dealing damage. Both use move_through.
    combat, session = ai_fight(tmp_path, map_terrain=[
        {'terrain': 'obsidian terrain', 'cells': [[3, 1]]},
        {'terrain': 'fire terrain', 'cells': [[7, 1]]},
    ])
    engine = session.engine
    actor = engine.state.actors[OWNER]
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    hops = [c for c in context.legal_candidates if c.metadata.get('teleport')]
    safe = next(c for c in hops if c.destination == Position(x=7, y=2))
    entry = next(c for c in hops if c.destination == Position(x=7, y=1))
    assert zones.hazard_test(engine, actor)(safe.destination), 'walking still counts terrain distance'
    assert not safe.metadata.get('hazard_exposure'), 'teleporting out does not walk through terrain'
    assert entry.metadata.get('hazard_exposure'), 'teleport entry damage must still be estimated'
    choice = combat.controller.choose_primary_action(context)
    chosen = next(c for c in hops if c.candidate_id == choice.intent.candidate_id)
    assert engine.grid.distance_ft(actor.position, chosen.destination) > 10
    assert not chosen.metadata.get('hazard_exposure')
    hp, sequence = actor.current_hp, engine.state.event_sequence
    result = combat.local_step(session.match_id)
    assert result['status'] == 'COMMITTED'
    assert result['record']['selected_candidate_id'] == chosen.candidate_id
    loaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert loaded.engine.state.actors[OWNER].position == chosen.destination
    assert loaded.engine.state.actors[OWNER].current_hp == hp
    assert not [e for e in loaded.engine.events if e.sequence > sequence
                and e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('moment') == 'move_through']
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(session.match_id)['menu']


def test_ai_teleport_has_all_player_landings_and_commits_without_prompt(tmp_path):
    combat, session = ai_fight(tmp_path)
    engine = session.engine
    actor = engine.state.actors[OWNER]
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    candidates = [c for c in context.legal_candidates if c.metadata.get('teleport')
                  and c.source_definition_id.endswith('TAL_VOID_EMPTY_STEP')]
    assert len(candidates) > 16
    assert {(c.destination.x, c.destination.y) for c in candidates} == {
        (p.x, p.y) for p in destinations(engine, actor, 20,
                                        action=engine.action_catalog[candidates[0].source_definition_id])}
    # The slow caster cannot walk into range, but a legal hop can close the gap.
    # Use the complete AI menu and record, including its alternative actions.
    choice = combat.controller.choose_primary_action(context)
    chosen = next((c for c in context.legal_candidates if c.metadata.get('teleport')
                   and c.candidate_id == choice.intent.candidate_id), None)
    assert chosen is not None, choice.record.explanation
    assert engine.grid.distance_ft(chosen.destination, engine.state.actors[FOE].position) < 70
    before = dict(actor.resources)
    costs = engine.action_catalog[chosen.source_definition_id].costs
    result = combat.local_step(session.match_id)
    assert result['status'] == 'COMMITTED'
    assert result['record']['selected_candidate_id'] == chosen.candidate_id
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert reloaded.engine.state.actors[OWNER].position == chosen.destination
    for resource, amount in costs:
        before[resource] -= amount
    assert reloaded.engine.state.actors[OWNER].resources == before
    assert reloaded.verify()['status'] == 'PASS'
    assert reloaded.mechanical.replay()['status'] == 'PASS'
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(session.match_id)['menu']


def test_remembered_only_area_submits_and_resolves_real_roster(tmp_path, monkeypatch):
    ability = 'FIRE_TAL_FIREBALL_ART'
    _, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_abilities=(ability,))
    turn(table, mid, RIGHT)
    move_to(table, mid, (20, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    combat = CombatService(ROOT, tmp_path)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    session = combat._load_session(mid)
    engine = session.engine
    policy, _ = combat.policies.for_actor(LEFT)
    before = engine.state.model_dump(mode='json')
    raw_ids = {c.candidate_id for c in engine.legal_candidates()}
    context = build_decision_context(engine, policy, for_ai=True)
    assert engine.state.model_dump(mode='json') == before
    candidates = [c for c in context.legal_candidates if ability in c.source_definition_id
                  and c.candidate_id not in raw_ids]
    assert candidates, 'remembered occupancy must restore an area absent from the live preview'
    c = candidates[0]
    from combat.typed_executor import _area_targets
    action = engine.action_catalog[c.source_definition_id]
    actual = _area_targets(engine, engine.state.actors[LEFT], c.destination,
                           action.parameters['typed']['area'], typed=action.parameters['typed'])
    assert RIGHT not in {a.entity_id for a in actual}
    hp = engine.state.actors[RIGHT].current_hp
    # Populate the canonical cache first, as table.state does before auto_step.
    combat._legal_candidates(combat._load_session(mid))
    result = combat.local_step(mid)
    assert result['status'] == 'COMMITTED'
    # The AI may prefer a free move over an expensive spell. Its service menu
    # must still contain the remembered-only cast, even with the player cache primed.
    assert c.candidate_id in result['record']['legal_alternatives']
    session = combat._load_session(mid)
    context = build_decision_context(session.engine, policy, for_ai=True)
    c = next(candidate for candidate in context.legal_candidates
             if candidate.source_definition_id == c.source_definition_id and candidate.destination == c.destination)
    intent = ActionIntent(intent_id='sol149:remembered-area', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids)
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[RIGHT].current_hp == hp
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_query_scope_restores_on_exception_and_is_engine_local(tmp_path):
    _, session = ai_fight(tmp_path)
    engine = session.engine
    assert candidate_knowledge.roster(engine) is None
    # A tactical wall is an area estimate too. Its screen value must follow
    # the last observed enemy, rather than a hidden enemy's new position.
    from combat.ext.docket_walls import tactical
    from combat.gate2_runtime_models import ActionDefinition, ConditionInstance, CandidateKind, EconomyKind
    from combat.target_knowledge import knowledge
    actor, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    prepared = tuple(engine.legal_candidates())
    with pytest.raises(RuntimeError):
        with candidate_knowledge.prepared_binding(engine, prepared):
            assert candidate_knowledge.binding_candidates(engine) == prepared
            assert candidate_knowledge.binding_candidates(object()) is None
            # An unversioned in-transaction change must invalidate acceptance.
            actor.current_hp -= 1
            assert candidate_knowledge.binding_candidates(engine) is None
            actor.current_hp += 1
            assert candidate_knowledge.binding_candidates(engine) == prepared
            raise RuntimeError('leave prepared binding')
    assert candidate_knowledge.binding_candidates(engine) is None
    foe.conditions['test:hidden'] = ConditionInstance(instance_id='test:hidden',
        condition_id='condition:typed.invisible', source_definition_id='test:hidden',
        source_actor_id=FOE, target_id=FOE, applied_sequence=engine.state.event_sequence,
        expires_on='UNTIL_REMOVED')
    engine.state.observations.setdefault(actor.team_id, {})[FOE] = foe.position.model_copy()
    actor.current_hp = actor.maximum_hp // 2
    wall = ActionDefinition(source_definition_id='test:wall', display_name='Screening wall', owner_id=OWNER,
        economy=EconomyKind.ACTION, target_kind='CELL', resolution_kind='TYPED',
        parameters={'typed': {'zone_spec': {'size_ft': 30, 'wall': {'blocks_movement': True}}}})
    rows = [engine._candidate(CandidateKind.ACTION, actor, wall.source_definition_id, wall.display_name,
        destination=Position(x=8, y=1), metadata={'empty_area': True})]
    assert knowledge(engine, actor, foe).mode == 'LAST_OBSERVED'
    with candidate_knowledge.query(engine):
        before = tactical(engine, actor, wall, rows)[0].metadata
    assert before.get('tactical_wall')
    foe.position = Position(x=0, y=12)
    with candidate_knowledge.query(engine):
        assert tactical(engine, actor, wall, rows)[0].metadata == before
    with pytest.raises(RuntimeError):
        with candidate_knowledge.query(engine):
            assert candidate_knowledge.roster(engine)
            assert candidate_knowledge.roster(object()) is None
            raise RuntimeError('leave scope')
    assert candidate_knowledge.roster(engine) is None
