"""Local drafts retain the engine's full legal choices and commit through the table."""
import json
import os
import subprocess
from itertools import product
from pathlib import Path

import pytest

from combat.ext import blossom, placed
from combat.option_composition import prepare
from combat.tabletop import TabletopError
from tests.test_a2_flowers import scene
from tests.hunt12_support import ME, reload


@pytest.fixture
def draft_fight(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED, blossom.GARDEN, blossom.THORN])
    state = table.state(mid)
    menu = state['menu']
    specs = menu['composition']
    sources = [next(row['source'] for row in specs.values() if row['source'].endswith(suffix))
               for suffix in ('blossom.seed.poison', 'blossom.pick.seed', 'blossom.garden.off')]
    action = next(row['source_definition_id'] for row in menu['actions']
                  if row['source_definition_id'].endswith('blossom.cultivate_bloom'))
    payload = dict(actor_id=ME, decision_id=menu['decision_id'], state_version=menu['state_version'],
                   sources=sources, source_definition_id=action, request_id='three-choices')
    return combat, table, mid, payload


def test_three_choices_preview_is_read_only_and_scoped_then_commit_reloads(draft_fight, tmp_path, monkeypatch):
    combat, table, mid, payload = draft_fight
    session = combat._load_session(mid)
    journal = session.store.journal_path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('A chooser rebuilt the full menu/state/ranking')
    with monkeypatch.context() as m:
        m.setattr(table, 'state', forbidden)
        m.setattr(table, '_rank_menu', forbidden)
        m.setattr(combat, 'decision', forbidden)
        from combat.gate4_engine import Gate4ControllerEngine
        m.setattr(Gate4ControllerEngine, 'legal_candidates', forbidden)
        result = table.preview_composition(mid, payload)
    assert session.store.journal_path.read_bytes() == journal
    probe, expected = prepare(table, mid, payload)
    assert expected
    sources = {c.source_definition_id for c in expected}
    native = [c for c in probe.legal_candidates() if c.source_definition_id in sources]
    assert [c.model_dump(mode='json') for c in expected] == [c.model_dump(mode='json') for c in native]
    options = [o for g in result['menu']['actions'] for o in g['options']]
    assert all(o['destination'] is not None for o in options)
    assert not any(g.get('placement_picker') for g in result['menu']['actions'])
    assert {o['candidate_id'] for o in options} == {c.candidate_id for c in native}
    # A willing self target removes attack-roll variance from the persistence check.
    chosen = next(o for o in options if o['target_ids'] == [ME]
                  or (o.get('destination') or {}).get('x') == 3 and (o.get('destination') or {}).get('y') == 6)
    reply = table.commit_composition(mid, payload, chosen['candidate_id'], 0)
    assert reply['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    config = next(c.data for c in engine.state.actors[ME].conditions.values() if c.condition_id == blossom.SETUP)
    assert (config['seed'], config['bloom'], config['garden']) == ('poison', 'seed', 'off')
    assert any(placed.data(zone).get('state') == 'seed' for zone in placed.of(engine, 'blossom', owner_id=ME))


def test_invalid_and_stale_drafts_cannot_write(draft_fight):
    combat, table, mid, payload = draft_fight
    path = combat._load_session(mid).store.journal_path
    before = path.read_bytes()
    with pytest.raises(TabletopError):
        table.preview_composition(mid, {**payload, 'sources': ['turn:end']})
    with pytest.raises(TabletopError):
        table.preview_composition(mid, {**payload, 'state_version': payload['state_version'] + 1})
    with pytest.raises(TabletopError):
        table.commit_composition(mid, payload, 'candidate:made-up', 0)
    assert path.read_bytes() == before


def test_client_choice_combinations_equal_server_validated_set(draft_fight):
    from combat.canonical import canonical_sha256
    from combat.ext.setting_choices import COMPOSITION_KIND, validate_batch
    from combat.gate2_runtime_models import ActionIntent
    combat, table, mid, payload = draft_fight
    engine = combat._load_session(mid).engine
    menu = table.state(mid)['menu']
    groups = {}
    for cid, spec in menu['composition'].items():
        if spec['key'][0] == 'blossom' and spec['key'][1] in {'seed', 'bloom', 'garden'}:
            groups.setdefault(tuple(spec['key']), []).append(cid)
    assert len(groups) == 3
    combinations = list(product(*groups.values()))
    expected = []
    for ids in combinations:
        sources = [menu['composition'][cid]['source'] for cid in ids]
        binding = {'kind':COMPOSITION_KIND, 'sources':sources}
        intent = ActionIntent(intent_id='test:choices',decision_id='settings:v1',
            candidate_id=canonical_sha256(binding), actor_id=ME,target_ids=(ME,),state_version=engine.state.state_version)
        assert len(validate_batch(engine,intent,binding)) == 3
        expected.append(sources)
    script = """
      import {OptionDraft} from './static/tabletop/option-composition.js';
      let text=''; for await (const part of process.stdin) text+=part;
      const {menu, combinations} = JSON.parse(text);
      console.log(JSON.stringify(combinations.map(ids=>{
        const draft = new OptionDraft(menu,'fight'); ids.forEach(id=>draft.choose(id));
        return draft.request('ability','request').sources;
      })));
    """
    result = subprocess.run(['node','--input-type=module','-e',script],
        input=json.dumps({'menu':menu,'combinations':combinations}),text=True,capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_composed_setting_batch_is_journaled_once_across_retry_and_reload(draft_fight):
    from combat.ext.setting_choices import COMPOSITION_KIND
    from combat.settings_service import match_batch
    combat, table, mid, payload = draft_fight
    receipt = match_batch(table, mid, ME, payload['sources'], 'three-setting-choices', kind=COMPOSITION_KIND)
    journal = combat._load_session(mid).store.journal_path.read_bytes()
    assert match_batch(table, mid, ME, payload['sources'], 'three-setting-choices', kind=COMPOSITION_KIND) == receipt
    assert combat._load_session(mid).store.journal_path.read_bytes() == journal
    engine = reload(combat.userdata_root, mid)
    config = next(c.data for c in engine.state.actors[ME].conditions.values()
                  if c.condition_id == blossom.SETUP)
    assert (config['seed'], config['bloom'], config['garden']) == ('poison', 'seed', 'off')


def test_client_composition_and_real_click_handlers():
    result = subprocess.run(['node', '--test', 'tests/option_composition.test.mjs',
        'tests/mobile_option_composition.test.mjs', 'tests/optdraft_sheet_overlay.test.mjs'],
        text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_http_scoped_preview_and_play_share_table_path(draft_fight, tmp_path, monkeypatch):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.h1_support import ROOT
    from tests.async_support import run_asgi
    _combat, _table, mid, payload = draft_fight
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    table = app.state.agent_seats.table
    def no_state(*args, **kwargs):
        raise AssertionError('Scoped HTTP preview requested the full state')
    monkeypatch.setattr(table, 'state', no_state)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            reply = await client.post(f'/api/tabletop/matches/{mid}/composition/preview',
                headers={'x-foundry-token':token},json=payload)
            assert reply.status_code == 200, reply.text
            assert reply.json()['menu']['actions']
            assert b'play.js' in (await client.get('/play')).content
            assert b'tabletop.js' in (await client.get('/tabletop')).content
    run_asgi(exercise())


@pytest.mark.skipif(os.environ.get('OPTIONSPEED_BROWSER') != '1', reason='Lead runs Chromium outside the sandbox')
def test_browser_option_clicks():
    """Opt-in real UI request count, using a lead-supplied scratch fight URL."""
    from playwright.sync_api import sync_playwright
    url = os.environ['OPTIONSPEED_URL']
    assert ':8765' not in url
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        page.goto(url)
        page.wait_for_function('window.tabletop?.app?.menu?.composition')
        actor_id = page.evaluate('window.tabletop.app.menu.actor_id')
        if not page.locator('#ttViewerPicker').evaluate('(dialog) => dialog.open'):
            gate = page.locator('#ttViewerGateChoose')
            (gate if gate.is_visible() else page.locator('#ttViewerChange')).click()
        page.locator(f'input[name="my-fighters"][value="{actor_id}"]').check()
        page.locator('#ttViewerApply').click()
        page.locator('#ttActionBar .tt-btn').first.wait_for()
        page.evaluate('window.optionRequests = []; const original = window.fetch; window.fetch = (...args) => { window.optionRequests.push(String(args[0])); return original(...args); };')
        for suffix in ['blossom.seed.poison', 'blossom.pick.seed', 'blossom.seed.piercing']:
            page.evaluate('suffix => { const {app, runButton} = window.tabletop; const spec = Object.values(app.menu.composition).find(x => x.source.endsWith(suffix)); return runButton({label: spec.label, combat:{source_definition_id:spec.source}}, app.menu.actor_id); }', suffix)
        assert page.evaluate('window.optionRequests') == []
        selected = page.evaluate('window.tabletop.app.optionDraft?.request("unused", "test").sources')
        assert selected is not None, 'Choose My fighters in the scratch browser view before testing'
        assert any(s.endswith('blossom.pick.seed') for s in selected)
        assert any(s.endswith('blossom.seed.piercing') for s in selected)
        assert not any(s.endswith('blossom.seed.poison') for s in selected)
        browser.close()


def test_optdraft_overlay_test_wired_into_runner():
    """Finding: optdraft_sheet_overlay.test.mjs was not referenced by any runner."""
    source = Path(__file__).read_text()
    assert 'tests/optdraft_sheet_overlay.test.mjs' in source, \
        'optdraft_sheet_overlay.test.mjs is not in the node --test runner list'


def test_option_composition_browser_modules_are_cache_busted():
    """Finding: option-composition.js import and changed HTML script tags lack version bumps."""
    root = Path(__file__).resolve().parent.parent
    tabletop_js = (root / 'static/tabletop/tabletop.js').read_text()
    assert 'option-composition.js?v=' in tabletop_js, \
        'tabletop.js imports option-composition.js without a ?v= cache-bust tag'
    tabletop_html = (root / 'static/tabletop/tabletop.html').read_text()
    assert 'optdraft1' in tabletop_html, \
        'tabletop.html tabletop.js script tag was not version-bumped for the optdraft change'
    sheet_html = (root / 'static/tabletop/sheet.html').read_text()
    assert 'sheet.js?v=rel6-3' in sheet_html, \
        'sheet.html sheet.js script tag was not version-bumped for the optdraft change'
