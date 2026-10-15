"""Real sheet module and HTTP caller contracts, with no browser or live server."""
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from app.api import create_app
from app.core import Settings
from tests.async_support import run_asgi
from tests.test_formula_archivist_table import install, PID, ROOT, NAMESPACE, COMMON, call
from tests.test_formula_archivist_choices import with_paths, ready


def test_http_procedure_forms_choices_preview_and_seat_boundary(tmp_path):
    table = install(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            headers = {'x-foundry-token': (await client.get('/api/session')).json()['token']}
            url = f'/api/tabletop/characters/{PID}/procedures'
            result = await client.get(url)
            assert result.status_code == 200
            menu = result.json()['procedures'][0]
            form = next(f for f in menu['forms'] if f['id'] == 'grant-Common')
            assert len(form['fields'][0]['options']) == len(menu['grants'][0]['options'])
            suggestion = await client.post(url + '/suggest', headers=headers, json={
                'namespace': NAMESPACE, 'form_id': form['id'], 'revision': 0, 'provider_id': 'builtin'})
            assert suggestion.status_code == 200, suggestion.text
            payload = {'namespace': NAMESPACE, 'action': form['action'], 'payload': {'formula_id': COMMON},
                       'revision': 0, 'request_id': 'ui-common', 'preview': True}
            preview = await client.post(url, headers=headers, json=payload)
            assert preview.status_code == 200 and preview.json()['status'] == 'PREVIEW'
            assert not table.buttons.get(PID).get('advancement')
            payload['preview'] = False
            saved = await client.post(url, headers=headers, json=payload)
            assert saved.status_code == 200 and saved.json()['status'] == 'COMMITTED'
            refreshed = (await client.get(url)).json()['procedures'][0]
            assert refreshed['revision'] == 1
            assert [f['id'] for f in refreshed['forms'] if f['action'] == 'choose'] == ['grant-Uncommon']
    run_asgi(exercise())


@pytest.mark.skipif(os.environ.get('CF_FORMULA_BROWSER') != '1', reason='Lead runs Chromium outside the sandbox with CF_FORMULA_BROWSER=1')
def test_opt_in_real_dom_formula_selection(tmp_path):
    """Visual/DOM smoke check; no live service, model or owner data is used."""
    from playwright.sync_api import sync_playwright
    table = install(tmp_path)
    menu = table.procedures(PID)[0]
    source = (ROOT / 'static/tabletop/procedures.js').read_text().replace('export function', 'function', 1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.set_content('<main id="studies"></main>')
            page.evaluate('menu => window.menu = menu', menu)
            page.add_script_tag(content=source + """
              function h(tag, attrs, ...children) {
                const e = document.createElement(tag);
                for (const [key, value] of Object.entries(attrs || {})) {
                  if (value == null) continue;
                  if (key in e) e[key] = value; else e.setAttribute(key, value);
                }
                e.append(...children.filter(c => c != null)); return e;
              }
              window.records = [];
              const ui = createProcedures({h, projectId: () => 'aaaaaaaa', toast: () => {}, reloadSheet: async () => {},
                fetchJson: async url => url.endsWith('/providers') ? {providers: []} : {procedures: [window.menu]},
                post: async (path, value) => { window.records.push(value); return {status: 'COMMITTED'}; }});
              document.querySelector('#studies').append(ui.root); ui.load();
            """)
            form = page.locator('form').filter(has=page.get_by_role('heading', name='Formula Archivist: learn one additional Common formula. No crafting cost; knowledge only.', exact=True))
            assert form.locator('select[name=formula_id] option').count() == len(menu['grants'][0]['options'])
            selected = menu['grants'][0]['options'][-1]['id']
            form.locator('select[name=formula_id]').select_option(selected)
            form.get_by_role('button', name='Record', exact=True).click()
            page.wait_for_function('window.records.length === 1')
            assert page.evaluate('window.records[0].payload.formula_id') == selected
        finally:
            browser.close()
