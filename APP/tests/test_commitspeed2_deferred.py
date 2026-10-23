"""Offline commit acknowledgement and complete on-demand menu equivalence."""
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import FOE, fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))
    def denied(*a, **kw):
        raise AssertionError('No live model or socket in commit/menu regressions')
    monkeypatch.setattr(socket.socket, 'connect', denied)


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('kind', ['mark', 'attack'])
def test_acknowledgement_defers_next_menu_and_rejects_old_binding(tmp_path, monkeypatch, mode, kind):
    from tests.worker2_support import OWNER, ALLY
    combat, table, mid = fixture(tmp_path, ['TAL_DAEMONIC_CULTIVATION_DEMON_MARK'], ask=False,
        owner_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}},
        foe_position={'x': 3, 'y': 5}, seed='COMMITSPEED2', modes={OWNER: mode, ALLY: mode, FOE: mode})
    before = table.state(mid)
    candidates = combat._legal_candidates(combat._load_session(mid))
    chosen = next(c for c in candidates if c.target_ids == (FOE,) and
        ('DEMON_MARK' in c.source_definition_id if kind == 'mark' else
         c.kind == 'ACTION' and '.weapon.' in c.source_definition_id and '#' not in c.source_definition_id))
    reads = []
    original = combat.decision
    def decision(*args, **kwargs):
        reads.append(kwargs['session'].engine.state.state_version)
        return original(*args, **kwargs)
    monkeypatch.setattr(combat, 'decision', decision)
    generations = []
    generate = combat._legal_candidates
    def candidates(*a, **kw):
        generations.append(a[0].engine.state.state_version)
        return generate(*a, **kw)
    monkeypatch.setattr(combat, '_legal_candidates', candidates)
    result = table.act(mid, chosen.candidate_id, chosen.decision_id, chosen.state_version,
                       before['last_sequence'], defer_menu=True)
    assert result['status'] == 'COMMITTED'
    assert reads == [chosen.state_version], 'post-commit menu enumeration blocked acknowledgement'
    assert all(v == chosen.state_version for v in generations), 'presentation generated next choices'
    assert result['state']['menu'] is None
    assert result['state']['menu_pending']['state_version'] > chosen.state_version
    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert result['state'] == cold.state(mid, fog=True, include_menu=False)
    assert result['events'] == cold.events(mid, before['last_sequence'])
    with pytest.raises(TabletopError) as stale:
        table.act(mid, chosen.candidate_id, chosen.decision_id, chosen.state_version, 0, defer_menu=True)
    assert stale.value.code == 'TABLETOP_STALE'
    expanded = table.state(mid, fog=True)
    assert 'menu_pending' not in expanded
    assert expanded == cold.state(mid, fog=True)
    assert expanded['menu']['state_version'] == result['state']['menu_pending']['state_version']
    assert cold.combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_ranking_projection_preserves_full_scores_and_boundary_invalidation(tmp_path):
    # CELL actions exercise range bounding; attacks/moves exercise the controller
    # projection. The entire context remains available for tactical admission.
    combat, table, mid = fixture(tmp_path, ['TAL_DARK_PURE_DARKNESS'], ask=False, seed='COMMITSPEED2-CELL')
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(session.engine.state.current_actor_id)
    # The ranking projection skips the built-in AI's restraint (ai_veto=False): it orders a person's own
    # menu, so rows the AI would leave alone must still be scored (STALEMATE1, review 2026-10-21).
    expected = build_decision_context(session.engine, policy, for_ai=True, ai_veto=False)
    context = combat.menu_ranking_context(session)
    assert context == expected
    again = combat.menu_ranking_context(session)
    assert again == expected and again is not context
    full = combat.controller.choose_primary_action(context)
    ids = {row.candidate_id for row in full.record.scored_alternatives[::2]}
    ids.add(full.record.selected_candidate_id)
    projected = combat.controller.score_primary_projection(context, ids)
    assert projected.record.scored_alternatives == tuple(
        row for row in full.record.scored_alternatives if row.candidate_id in ids)
    known = {row.entity_id for row in context.actors}
    scores = menu_rank.native_scores(combat, session.engine, known, session=session, candidate_ids=ids)
    # Table scores use the incumbent scorer (no AI tier profile), MAINREDSPEED1F2.
    display_context = context.model_copy(update={'zones': (), 'recent_events': (), 'tactics': {},
        'team_behavior': context.team_behavior.model_copy(update={'focus_target_id': None})})
    display_pick = combat.controller.score_primary_projection(display_context, ids)
    assert scores == {row.candidate_id: row.total for row in display_pick.record.scored_alternatives}
    session.engine.state.actors[context.active_actor_id].current_hp -= 1
    assert combat._state_key(session) is None
    changed = combat.menu_ranking_context(session)
    assert changed != expected
    assert changed == build_decision_context(session.engine, policy, for_ai=True, ai_veto=False)


@pytest.mark.parametrize('same_place', [False, True])
def test_exact_ranking_batches_origins_and_keeps_player_availability(tmp_path, monkeypatch, same_place):
    from tests.test_lock_choices import install
    from tests.test_menuspeed3_placement import setup, OWNER
    origins = [{'id': 'test:a', 'label': 'First current', 'position': {'x': 2, 'y': 6}},
               {'id': 'test:b', 'label': 'Second current', 'position': {'x': 5, 'y': 6}}]
    if same_place:
        origins[1]['position'] = origins[0]['position']
    install(monkeypatch, 'effect_origins', lambda engine, actor, action:
        origins if actor.entity_id == OWNER and action.target_kind == 'CELL' else [])
    combat, _, mid = setup(tmp_path)
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(session.engine.state.current_actor_id)
    expected = build_decision_context(session.engine, policy, for_ai=True)
    player = combat._legal_candidates(session)
    availability = session.engine._cf_availability
    combat._legal_candidates(session, knowledge_only=True, progress_guard=False)
    session.engine._cf_availability = availability
    actual = combat.menu_ranking_context(session)
    assert actual == expected
    assert session.engine._cf_availability is availability
    assert combat._legal_candidates(session) == player


def test_local_auto_acknowledges_without_building_next_choices(tmp_path, monkeypatch):
    from tests.test_r6_6_7_combat_presentation_architecture import _create_service_match
    combat, mid = _create_service_match(tmp_path)
    userdata = tmp_path / 'UserData'
    table = TabletopService(combat, userdata)
    calls = []
    original = combat.decision
    def decision(*a, **kw):
        calls.append(kw.get('table_header', False))
        return original(*a, **kw)
    monkeypatch.setattr(combat, 'decision', decision)
    result = table.auto_step(mid, 0, defer_menu=True)
    assert result['status'] == 'COMMITTED'
    assert calls == [False]
    assert result['state']['menu'] is None
    cold = TabletopService(CombatService(ROOT, userdata), userdata)
    assert result['state'] == cold.state(mid, include_menu=False, fog=True)
    assert table.state(mid, fog=True) == cold.state(mid, fog=True)


def test_client_acknowledgement_and_late_menu_races_without_browser():
    subprocess.run(['node', '--test', str(Path(__file__).with_name('commitspeed2_deferred.test.mjs'))], check=True)


def test_deferred_human_handoff_uses_production_rendering_and_selection():
    subprocess.run(['node', '--test', str(Path(__file__).with_name('commitspeed2_selection.test.mjs'))],
                   check=True, timeout=60)


def test_http_commit_defers_choices_on_the_production_route(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    _, _, mid = fixture(tmp_path, [], ask=False, seed='COMMITSPEED2-HTTP')
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            prefix = f'/api/tabletop/matches/{mid}'
            initial = (await client.get(prefix + '/state')).json()
            menu = initial['menu']
            response = await client.post(prefix + '/act', headers={'x-foundry-token': token}, json={
                'candidate_id': menu['end_turn'], 'decision_id': menu['decision_id'],
                'state_version': menu['state_version'], 'after': initial['last_sequence']})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['status'] == 'COMMITTED' and result['state']['menu'] is None
            assert result['state']['menu_pending']['state_version'] > menu['state_version']
            full = (await client.get(prefix + '/state')).json()
            assert full['menu']['state_version'] == result['state']['menu_pending']['state_version']
    run_asgi(exercise())


@pytest.mark.parametrize('controller,model,paused,active,expected', [
    ('MANUAL', False, False, True, False), ('SUGGESTED', False, False, True, False),
    ('MANUAL', True, False, True, True), ('LOCAL_AUTO', False, False, True, True),
    ('MANUAL', True, True, True, False), ('MANUAL', True, False, False, True),
])
def test_deferred_response_schedules_seats_without_issuing_a_menu(tmp_path, monkeypatch, controller, model, paused, active, expected):
    from agent_seats.runner import SeatRunner
    # Use the real scheduler with its provider boundary replaced; no work or
    # model calls happen in this regression.
    table = SimpleNamespace(data_root=tmp_path, decision_driver=None)
    runner = SeatRunner(table, render_png=lambda view: None)
    monkeypatch.setattr(runner, 'seats', lambda mid: {'p': {'control': 'MODEL' if model else 'MANUAL'},
                                                    'other': {'control': 'MODEL'}})
    monkeypatch.setattr(runner, 'playback', lambda mid: {'paused': paused})
    runner.background = True
    kicked = []
    monkeypatch.setattr(runner, 'kick', kicked.append)
    result = {'status': 'COMMITTED', 'state': {'menu': None, 'menu_pending': {'actor_id': 'p', 'state_version': 7},
        'pending_action': None, 'presentation': {'actors': [{'entity_id': 'p', 'active': active,
            'primary_combatant': True, 'controller': controller}]}}}
    assert runner.observe('m', result) == result
    assert bool(kicked) == expected
    assert result['state']['menu'] is None
