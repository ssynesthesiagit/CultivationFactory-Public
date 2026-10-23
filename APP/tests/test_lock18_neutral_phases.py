"""A bystander must finish setup and accepted follow-ups through the Table."""
from combat.gate2_runtime_content import AN, LEE, LING, BAI
from combat.gate4_persistence import Gate4Persistence
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.relations import NEUTRAL_TEAM
from tests.test_lock17_relations import ROOT, _context
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import on_hold, HOLD


def fight(tmp_path):
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='LOCK18-NEUTRAL-9', roster_setup={
        'primary_actor_ids': [AN, LEE, LING, BAI],
        'team_by_actor': {AN: 'team:a', LEE: 'team:a', LING: 'team:b', BAI: NEUTRAL_TEAM},
        'starting_positions': {AN: {'x': 2, 'y': 6}, LEE: {'x': 3, 'y': 6},
                               LING: {'x': 6, 'y': 6}, BAI: {'x': 10, 'y': 6}}})
    assert session.engine.state.current_actor_id == BAI
    service = CombatService(ROOT, tmp_path)
    return service, TabletopService(service, tmp_path), session.match_id


def test_neutral_first_can_finish_another_actors_setup(monkeypatch, tmp_path):
    def tasks(engine):
        return [{'actor_id': AN, 'source_id': engine.state.actors[AN].action_ids[0]}]
    def setup(engine, actor, source, intent):
        engine._grant_temp_hp(actor, 3, source, actor.entity_id)
        return True
    install(monkeypatch, 'fight_setup_tasks', tasks)
    install(monkeypatch, 'fight_setup', setup)
    service, table, mid = fight(tmp_path)
    assert service._load_session(mid).engine.state.setup_tasks
    service.set_controller_mode(mid, actor_id=BAI, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.setup_tasks
    assert loaded.engine.state.actors[AN].temporary_hp == 3
    assert any(e.event_type == 'FIGHT_SETUP_COMPLETED' for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'


def test_neutral_pending_followup_keeps_use_and_decline_and_completes(monkeypatch, tmp_path):
    def pending(engine):
        actor, target = engine.state.actors[BAI], engine.state.actors[AN]
        engine._gain_resource(actor, 'resource:bai_meizhen.moon_sea_radiance', 1, 'test:followup')
        engine._open_follow_up_window(actor, target, 'test:followup', engine._active_intent,
                                     ['action:bai_meizhen.moon_disc_descent'])
    on_hold(monkeypatch, pending)
    service, table, mid = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode='MANUAL')
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.pending_resolution is not None
    context = _context(loaded.engine)
    assert {c.kind for c in context.legal_candidates} == {'OPTIONAL_RIDER', 'TAKE_NO_OPTIONAL_ACTION'}
    assert not context.bystander
    service.set_controller_mode(mid, actor_id=BAI, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.pending_resolution is None
    assert loaded.verify()['status'] == 'PASS'
