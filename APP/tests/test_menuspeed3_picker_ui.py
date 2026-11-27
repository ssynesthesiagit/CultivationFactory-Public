"""Headless source harness plus an explicit opt-in Chromium check for the lead."""
import os
import json
from pathlib import Path
import re
import subprocess

import pytest

APP = Path(__file__).resolve().parents[1]


def test_existing_square_picker_source_harness():
    files = ['tabletop_map_pick.test.mjs', 'tabletop_map_pick_hit.test.mjs', 'tabletop.test.mjs']
    result = subprocess.run(['node', '--experimental-vm-modules', '--test', *[str(APP / 'static/tabletop' / f) for f in files]],
        text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-3000:]
    standalone = subprocess.run(
        ['node', '--test', '--test-reporter=tap', str(APP / 'static/tabletop/tabletop.test.mjs')],
        text=True, capture_output=True, timeout=90)
    assert standalone.returncode == 0, standalone.stdout + standalone.stderr
    for name in (
        'tabletop page: act renders the retained commit notice',
        'tabletop page: autoStep renders the retained commit notice',
        'human origin picker lists multiple origins and immediately submits a single origin',
    ):
        assert re.search(rf'^ok \d+ - {re.escape(name)}$', standalone.stdout, re.MULTILINE), (
            f'Missing standalone TAP pass for {name}\n{standalone.stdout}{standalone.stderr}'
        )


def test_square_picker_retains_both_heights_without_a_browser():
    source = (APP / 'static/tabletop/tabletop.js').read_text()
    def function(start, end):
        return source[source.index(start):source.index(end, source.index(start))]
    code = function('function mapPickCells(', '// A place choice is always')
    code += function('function answerMapPick(', 'function cancelMapPick(')
    script = '''(async () => {
      const app = {}, currentViewer = () => ({ready: true});
      let offered = [], chosen = null;
      const showChoiceDialog = prompt => {
        offered = prompt.choice.options;
        return Promise.resolve({selection: 'USE', option_ids: [offered[Math.min(1, offered.length - 1)].id]});
      };
      const {mapPickCells, answerMapPick} = new Function('app', 'currentViewer', 'showChoiceDialog',
        CODE + '; return {mapPickCells, answerMapPick};')(app, currentViewer, showChoiceDialog);
      const choice = {options: [
        {id: 'cell:2,3,0', label: 'At ground level — Hits allies too: Tobin', cell: {x: 2, y: 3, z: 0}},
        {id: 'cell:2,3,4', label: '20 feet above ground — Allies you can choose: Tobin', cell: {x: 2, y: 3, z: 4}}], maximum: 1};
      app.mapPick = {...mapPickCells(choice), prompt: {choice}, close: answer => {chosen = answer;}};
      answerMapPick({x: 2, y: 3});
      await Promise.resolve();
      if (JSON.stringify(offered.map(o => o.id)) !== JSON.stringify(['cell:2,3,0', 'cell:2,3,4']))
        throw new Error('A legal altitude disappeared');
      if (JSON.stringify(chosen.option_ids) !== JSON.stringify(['cell:2,3,4']))
        throw new Error('The chosen altitude was not submitted');
      if (!offered[0].label.includes('Hits allies too: Tobin') || !offered[1].label.includes('Allies you can choose: Tobin'))
        throw new Error('Native warnings must survive height selection');
      chosen = null;
      const ground = {...choice, options: [choice.options[0]]};
      app.mapPick = {...mapPickCells(ground), prompt: {choice: ground}, close: answer => {chosen = answer;}};
      answerMapPick({x: 2, y: 3});
      if (chosen !== null || !offered[0].label.includes('Hits allies too: Tobin'))
        throw new Error('A risky single-height square must show its warning before submission');
    })().catch(error => {console.error(error); process.exitCode = 1;});'''.replace('CODE', json.dumps(code))
    result = subprocess.run(['node', '-e', script], text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.environ.get('MENUSPEED3_BROWSER') != '1',
                    reason='Lead must run MENUSPEED3_BROWSER=1 outside the sandbox')
def test_chromium_square_picker_retains_both_heights():
    playwright = pytest.importorskip('playwright.sync_api')
    source = (APP / 'static/tabletop/tabletop.js').read_text()
    def function(start, end):
        return source[source.index(start):source.index(end, source.index(start))]
    code = function('function mapPickCells(', '// A place choice is always')
    code += function('function answerMapPick(', 'function cancelMapPick(')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            result = page.evaluate('''code => {
              const app = {}, currentViewer = () => ({ready: true});
              let offered = [], chosen = null;
              const showChoiceDialog = prompt => {
                offered = prompt.choice.options;
                return Promise.resolve({selection: 'USE', option_ids: [offered[1].id]});
              };
              const {mapPickCells, answerMapPick} = new Function('app', 'currentViewer', 'showChoiceDialog',
                code + '; return {mapPickCells, answerMapPick};')(app, currentViewer, showChoiceDialog);
              const choice = {options: [
                {id: 'cell:2,3,0', cell: {x: 2, y: 3, z: 0}},
                {id: 'cell:2,3,4', cell: {x: 2, y: 3, z: 4}}], maximum: 1};
              app.mapPick = {...mapPickCells(choice), prompt: {choice}, close: answer => {chosen = answer;}};
              answerMapPick({x: 2, y: 3});
              return Promise.resolve().then(() => ({offered: offered.map(o => o.id), chosen}));
            }''', code)
            assert result['offered'] == ['cell:2,3,0', 'cell:2,3,4']
            assert result['chosen']['option_ids'] == ['cell:2,3,4']
        finally:
            browser.close()
