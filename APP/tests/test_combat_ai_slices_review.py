"""Review regressions at native menu, AI context and package policy boundaries."""
import json
from types import SimpleNamespace
import zipfile

import pytest
from combat import zones
from combat.candidate_knowledge import query
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX, runtime_actor_id
from tests.test_combat_ai_slices import offline, context, hazard_engine, hazard_sheet
from tests.test_zones import _cast, OWNER, AN


def test_team_only_sighting_preserves_service_manual_menu(tmp_path, monkeypatch):
    from tests.test_lock6_observations import case, hide
    from combat.target_knowledge import knowledge
    service, engine, viewer, target, action = case(tmp_path)
    hide(engine, target)
    # A teammate's observation is native team knowledge, never a personal receipt.
    engine.events = [e.model_copy(update={'payload': {k: v for k, v in e.payload.items()
                     if k != 'personal_observations'}}) for e in engine.events]
    engine.state.observations[viewer.team_id] = {target.entity_id: target.position}
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    # Use the table's actual manual menu seam without its saved-state cache.
    monkeypatch.setattr(service, '_state_key', lambda _: None)
    session = SimpleNamespace(engine=engine, mechanical=SimpleNamespace(_records=[]))
    manual_before = service._legal_candidates(session)
    before = engine._action_candidates(viewer, action)
    assert before
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    after = engine._action_candidates(viewer, action)
    assert [c.candidate_id for c in service._legal_candidates(session)] == [
        c.candidate_id for c in manual_before]
    assert [c.model_dump() for c in after] == [c.model_dump() for c in before]
    assert knowledge(engine, viewer, target, action) is not None
    with query(engine):
        assert knowledge(engine, viewer, target, action) is None
    policy, _ = service.policies.for_actor(viewer.entity_id)
    from combat.gate4_context import build_decision_context
    assert build_decision_context(engine, policy, for_ai=False).own_knowledge is None
    assert target.entity_id not in {c.entity_id for c in
        build_decision_context(engine, policy, for_ai=True).own_knowledge.creatures}


def test_perceived_fire_entry_warns_before_personal_damage(monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = hazard_engine()
    _cast(engine, 'Conflagration', Position(x=13, y=6))
    engine.state.actors[AN].position = Position(x=18, y=6)
    ctx = context(engine)
    entering = [c for c in ctx.legal_candidates if c.kind == 'MOVE'
                and c.destination == Position(x=16, y=6)]
    assert entering and not ctx.own_knowledge.harms
    assert all(c.metadata['zone_hazard_exposure'] and c.metadata['hazard_exposure'] for c in entering)
    # Hidden geometry cannot supply warnings even when native truth knows it.
    for zone in zones.typed_zones(engine):
        zone.trigger_profile['visual']['invisible'] = True
    hidden = context(engine)
    assert not next(c for c in hidden.legal_candidates if c.candidate_id == entering[0].candidate_id
                    ).metadata['zone_hazard_exposure']


def test_large_footprint_clips_perceived_qi_hazard(monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = hazard_engine()
    actor = engine.state.actors[AN]
    actor.size_category = 'Large'
    actor.transformed_size_category = 'Large'
    assert engine._footprint(actor).width_cells == 2
    engine.grid.qi_hazard.add((15, 7))
    ctx = context(engine)
    clipped = next(c for c in ctx.legal_candidates if c.kind == 'MOVE'
                   and c.destination == Position(x=14, y=6))
    assert all((p.x, p.y) != (15, 7) for p in clipped.canonical_path)
    assert clipped.metadata['hazard_exposure']
    assert not clipped.metadata['zone_hazard_exposure']


@pytest.mark.parametrize('moment', ['cross', 'move_through'])
def test_perceived_line_and_cumulative_terrain_warnings(monkeypatch, moment):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = hazard_engine()
    actor = engine.state.actors[AN]
    actor.position = Position(x=14, y=6)
    profile = {'kind': 'TYPED', 'shape': 'line', 'terrain': ['fire terrain'],
               'visual': {'material': 'fire'}, 'triggers': []}
    damage = [{'type': 'damage', 'flat': 1, 'damage_types': ['fire']}]
    if moment == 'cross':
        cells = tuple(Position(x=16, y=y) for y in range(4, 9))
        profile['triggers'] = [{'id': 'cross', 'name': 'Crossing fire', 'on': ['cross'],
                                'who': 'any', 'effects': damage}]
    else:
        cells = tuple(Position(x=x, y=6) for x in range(14, 20))
        profile['move_through'] = {'who': 'any', 'min_ft': 5, 'effects': damage}
    zone = ZoneState(zone_id='review:visible', source_definition_id='review:terrain', owner_id=OWNER,
        center=cells[0], radius_cells=0, affected_cells=cells, concentration_link=False,
        created_round=1, trigger_profile=profile)
    engine.state.zones[zone.zone_id] = zone
    ctx = context(engine)
    row = next(c for c in ctx.legal_candidates if c.kind == 'MOVE'
               and c.destination == Position(x=18, y=6))
    assert row.metadata['zone_hazard_exposure'] and row.metadata['hazard_exposure']


@pytest.mark.parametrize('factory', [True, False])
@pytest.mark.parametrize('optional, phrase', [
    ('{broken', 'Protect companions'), ('[]', 'Protect companions'),
    ('{"dao_i_ching": ["invalid"]}', 'Protect companions'),
    ('{"dao": {"core_theme": "Withdraw when hurt"}}', 'Withdraw when hurt'),
])
def test_optional_profile_keeps_package_dao_policy(tmp_path, monkeypatch, factory, optional, phrase):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    from combat.ai_observation import goal_from_sheet
    from factory_authoring.sphere_dao import character_dao, controller_policy, sheet_sphere_talents
    sheet = hazard_sheet()
    sheet['dao_i_ching'] = {'dao': {'core_theme': 'Protect companions'}}
    package = tmp_path / 'character' / 'current.zip'
    package.parent.mkdir()
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
        archive.writestr('Dao_IChing_Combat_Profile.json', optional)
    entry = SimpleNamespace(character_project_id='review-character', source_package_sha256='a' * 64)
    aid = FACTORY_ACTOR_PREFIX + 'character' if factory else runtime_actor_id(
        entry.character_project_id, entry.source_package_sha256)
    service = CombatService.__new__(CombatService)
    service._dao_policies = {}
    service.combatant_library = SimpleNamespace(install_root=tmp_path,
        inventory=lambda: SimpleNamespace(accepted_candidates=[entry]), _package_for_entry=lambda _: package)
    monkeypatch.setattr(service, '_factory_owner_sheet', lambda _: sheet)
    expected = controller_policy(character_dao(sheet_sphere_talents(sheet)), aid)
    actual = service._dao_policy_for_actor(aid)
    assert actual is not None
    assert phrase in actual['goal_description']
    if phrase == 'Protect companions':
        assert actual['goal_description'] == goal_from_sheet(sheet)
    assert actual['policy_id'] == expected['policy_id']


def test_personally_suffered_fire_survives_table_commit_and_reload(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    from combat.tabletop_service import TabletopService
    from tests.test_combat_ai_slices import ROOT
    fire = FACTORY_ACTOR_PREFIX + 'review-fire'
    package = tmp_path / 'portable_characters' / 'review-fire' / 'current.zip'
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(hazard_sheet()))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Review fire yard', 'width_squares': 24,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[13, 6]]}})
    view = service.create_factory_match(project_ids=['review-fire'], opponent_actor_ids=[AN],
        control_modes={fire: 'MANUAL', AN: 'MANUAL'}, arena_id='battlefield:map.review-fire-yard',
        match_seed='REVIEW-FIRE-RELOAD')
    table = TabletopService(service, tmp_path)
    mid = view['match_id']
    def act(candidate_id):
        state = table.state(mid)
        menu = state['menu']
        answers = []
        for _ in range(8):
            result = table.act(mid, candidate_id, menu['decision_id'], menu['state_version'],
                               state['last_sequence'], answers)
            if result['status'] == 'COMMITTED':
                return
            assert result['status'] == 'REACTION_REQUIRED', result
            answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        pytest.fail('Unbounded reaction prompts in the fire persistence fixture')
    if table.state(mid)['menu']['actor_id'] != fire:
        act(table.state(mid)['menu']['end_turn'])
    session = service._load_session(mid)
    cast = next(c for c in session.engine.legal_candidates() if c.display_name.startswith('Conflagration')
                and c.destination == Position(x=13, y=6))
    act(cast.candidate_id)
    act(table.state(mid)['menu']['end_turn'])
    before_engine = service._load_session(mid).engine
    before = context(before_engine).own_knowledge
    assert before.harms and before.harms[0].damage > 0
    # One more table commit must preserve the primitive receipt as well.
    hold = next(c for c in before_engine.legal_candidates() if c.kind == 'HOLD_POSITION')
    act(hold.candidate_id)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    after = context(loaded).own_knowledge
    assert after.harms == before.harms
    assert after.harms[0].cells and after.harms[0].complete_boundary
