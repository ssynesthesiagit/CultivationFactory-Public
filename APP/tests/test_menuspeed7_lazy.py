"""Lazy human menus preserve complete native choices and isolate query caches."""
from types import SimpleNamespace

import pytest

from combat import ext, menu_rank
from combat.gate2_engine import Gate2Engine
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop_service import TabletopError
from tests.worker2_support import fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda *a: pytest.fail('No live models'), prefetch=lambda *a, **kw: None))


@pytest.mark.parametrize('talents', [[], ['TAL_AIR_COURT_OF_THE_FOUR_WINDS']])
def test_union_of_expansions_matches_native_across_three_commits(tmp_path, talents):
    combat, table, mid = fixture(tmp_path, talents, ask=False, seed='MENUSPEED7' + str(bool(talents)))
    for boundary in range(3):
        state = table.state(mid, lazy=True)
        menu = state['menu']
        assert menu.get('lazy'), menu
        assert any(g.get('lazy') for g in menu['actions'])
        session = combat._load_session(mid)
        native = session.engine.legal_candidates()
        ids = {menu['end_turn']}
        for group in menu['actions']:
            if group.get('lazy'):
                reply = table.expand_action(mid, group['source_definition_id'], menu['decision_id'], menu['state_version'])
                for expanded in reply['actions']:
                    ids.update(o['candidate_id'] for o in expanded['options'])
            else:
                ids.update(o['candidate_id'] for o in group['options'])
        assert ids == {c.candidate_id for c in native if c.kind != 'MOVE'}
        actor = session.engine.state.actors[menu['actor_id']]
        assert {tuple(row) for row in menu['movement_grid']} == {
            (c.destination.x, c.destination.y, c.destination.z,
             c.movement_cost_ft * session.engine._drag_multiplier(actor),
             c.metadata.get('movement_mode', 'walk'), bool(c.metadata.get('can_jump_down')))
            for c in native if c.kind == 'MOVE'}
        # Cached headers cannot leak into native/AI candidates or vice versa.
        assert all(not c.metadata.get('lazy_action') for c in combat._legal_candidates(session))
        assert table.state(mid, lazy=True) == state
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                           state['last_sequence'], defer_menu=True)
        assert result['status'] == 'COMMITTED'
        assert combat._load_session(mid).engine.state.state_version > menu['state_version']
        with pytest.raises(TabletopError):
            table.expand_action(mid, menu['actions'][0]['source_definition_id'], menu['decision_id'], menu['state_version'])


def test_first_layer_has_no_move_objects_or_candidate_veto_fanout(tmp_path, monkeypatch):
    _, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-work')
    created, vetoed = [], []
    original = Gate2Engine._candidate
    def candidate(self, kind, *args, **kwargs):
        if kind == 'MOVE':
            created.append(kwargs.get('destination'))
        return original(self, kind, *args, **kwargs)
    ext._load()
    def veto(engine, actor, candidate, action):
        if candidate.kind == 'MOVE':
            vetoed.append(candidate.destination)
            return False
    monkeypatch.setattr(Gate2Engine, '_candidate', candidate)
    monkeypatch.setitem(ext._HOOKS, 'candidate_allowed', [*ext._HOOKS['candidate_allowed'], veto])
    state = table.state(mid, lazy=True)
    assert state['menu']['movement_grid']
    assert not created and not vetoed
    menu = state['menu']
    x, y, z, _, mode, _ = menu['movement_grid'][0]
    with pytest.raises(TabletopError):
        table.preview_destination(mid, menu['decision_id'], menu['state_version'], menu['actor_id'],
                                  {'x': x, 'y': y, 'z': z}, mode)
    assert vetoed, 'exact click must still apply movement vetoes'


def test_expansion_only_queries_selected_source_and_memoizes(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-scope')
    menu = table.state(mid, lazy=True)['menu']
    group = next(g for g in menu['actions'] if g.get('lazy'))
    calls = []
    original = Gate4ControllerEngine._action_candidates
    def action(self, actor, definition, **kwargs):
        calls.append(definition.source_definition_id)
        return original(self, actor, definition, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_action_candidates', action)
    reply = table.expand_action(mid, group['source_definition_id'], menu['decision_id'], menu['state_version'])
    assert calls and set(calls) == {group['source_definition_id']}
    calls.clear()
    assert table.expand_action(mid, group['source_definition_id'], menu['decision_id'], menu['state_version']) == reply
    assert calls == []
    reply['actions'].clear()
    assert table.expand_action(mid, group['source_definition_id'], menu['decision_id'], menu['state_version'])['actions']


def test_expanded_option_commits_and_reloads(tmp_path):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-commit')
    state = table.state(mid, lazy=True)
    menu = state['menu']
    source = 'system:combat.dodge'
    reply = table.expand_action(mid, source, menu['decision_id'], menu['state_version'])
    candidate = reply['actions'][0]['options'][0]
    result = table.act(mid, candidate['candidate_id'], menu['decision_id'], menu['state_version'],
                       state['last_sequence'], defer_menu=True)
    assert result['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    assert not engine.state.actors[menu['actor_id']].action_available


def test_ai_query_ignores_lazy_scope(tmp_path):
    from combat.lazy_menu import query
    combat, _, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-ai')
    engine = combat._load_session(mid).engine
    engine.typed_control_modes[engine.state.current_actor_id] = 'LOCAL_AUTO'
    expected = engine.legal_candidates()
    with query():
        assert engine.legal_candidates() == expected


def test_unchanged_zone_recipient_policy_runs_once_per_pure_route_query(monkeypatch):
    from combat.read_queries import pure
    from combat.zones import zone_is_difficult
    from tests.h1_support import duel, ME
    engine = duel([])
    actor = engine.state.actors[ME]
    zone = SimpleNamespace(owner_id='other', trigger_profile={'difficult': 'all'})
    calls = []
    ext._load()
    def exempt(engine, actor, zone):
        calls.append(actor.position)
        return actor.position.z > 0
    monkeypatch.setitem(ext._HOOKS, 'difficult_zone_exempt', [exempt])
    @pure
    def search(engine):
        assert all(zone_is_difficult(engine, zone, actor) for _ in range(10))
        projected = actor.model_copy(update={'position': actor.position.model_copy(update={'z': 1})})
        assert not zone_is_difficult(engine, zone, projected)
        assert zone_is_difficult(engine, zone, actor)
    search(engine)
    assert len(calls) == 2
    search(engine)
    assert len(calls) == 4


def test_warm_layer_reuses_text_without_sharing_mutable_client_rows(tmp_path, monkeypatch):
    _, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-layers')
    first = table.state(mid, lazy=True)
    monkeypatch.setattr(table, '_menu_descriptions', lambda *a: pytest.fail('rebuilt menu text'))
    assert table.state(mid, lazy=True) == first
    first['menu']['actions'].clear()
    assert table.state(mid, lazy=True)['menu']['actions']


def test_http_lazy_state_and_scoped_expansion_reject_stale_versions(tmp_path, monkeypatch):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    from tests.h1_support import ROOT
    _, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7-http')
    menu = table.state(mid, lazy=True)['menu']
    # The combat fixture shares the synthetic database with the API. Create
    # the optional provider-settings schema before app startup, whose bridge
    # inspects it during initialization (no provider or model is configured).
    import sqlite3
    settings = Settings.from_env(ROOT, tmp_path)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS ai_provider_settings (
            provider_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
            endpoint TEXT NOT NULL, model TEXT NOT NULL,
            thinking_mode TEXT NOT NULL, max_output_tokens INTEGER NOT NULL,
            timeout_seconds INTEGER NOT NULL,
            data_sharing_acknowledged INTEGER NOT NULL,
            acknowledged_by TEXT, acknowledged_at TEXT, updated_at TEXT NOT NULL
        )''')
    # The endpoint under test is tabletop-only; avoid loading unrelated
    # non-sphere authority snapshots so this synthetic API test is portable.
    import app.api as api_module
    class StubNonSphereAuthority:
        def __init__(self, *_args, **_kwargs):
            pass
        def resolve_evidence(self, *_args, **_kwargs):
            return None
    monkeypatch.setattr(api_module, 'NonSphereAuthorityService', StubNonSphereAuthority)
    app = create_app(settings)
    app.state.agent_seats.background = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            state = await client.get(f'/api/tabletop/matches/{mid}/state', params={'compact': 'true'})
            assert state.status_code == 200, state.text
            assert state.json()['menu']['lazy'] is True
            movement = state.json()['menu']['movement_grid']
            assert movement['format'] == 'layers-v2'
            assert movement['layers'], 'compact HTTP state must serialize lazy movement rows'
            params = {'source': 'system:combat.dodge', 'decision_id': menu['decision_id'],
                      'state_version': menu['state_version']}
            reply = await client.get(f'/api/tabletop/matches/{mid}/action-options', params=params)
            assert reply.status_code == 200, reply.text
            assert reply.json()['actions'][0]['options']
            params['state_version'] -= 1
            stale = await client.get(f'/api/tabletop/matches/{mid}/action-options', params=params)
            assert stale.status_code == 409, stale.text
    run_asgi(exercise())


def test_lazy_menu_retains_existing_modifier_setting_controls(tmp_path):
    from tests.hunt36_support import fight, turn
    combat, table, mid = fight(tmp_path, ['TAL_VOID_NULLIFYING_STRIKE'], seed='MENUSPEED7-settings', cl=5)
    turn(combat, table, mid)
    eager = table.state(mid)
    lazy = table.state(mid, lazy=True)
    assert eager['shapes'] == lazy['shapes']
    engine = combat._load_session(mid).engine
    sources = {s for s, a in engine.action_catalog.items() if a.parameters.get('attack_modifier_setting')}
    expected = {g['source_definition_id']: g['options'] for g in eager['menu']['actions']
                if g['source_definition_id'] in sources}
    assert expected, 'fixture must exercise standing modifier choices'
    assert expected == {g['source_definition_id']: g['options'] for g in lazy['menu']['actions']
                        if g['source_definition_id'] in sources}


def test_lazy_expansion_browser_opt_in():
    """Opt-in Chromium check on a disposable fight with a human turn ready."""
    import os
    import re
    url, action = os.environ.get('MENUSPEED7_URL'), os.environ.get('MENUSPEED7_ACTION')
    if not url or not action:
        pytest.skip('Set MENUSPEED7_URL and MENUSPEED7_ACTION to enable this browser check')
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(url)
            button = page.get_by_role('button', name=re.compile('^' + re.escape(action))).first
            expect(button).to_be_enabled(timeout=60000)
            with page.expect_response(lambda response: '/action-options?' in response.url) as reply:
                button.click()
            assert reply.value.status == 200
            assert reply.value.json()['actions']
        finally:
            browser.close()
