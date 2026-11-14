"""Fight setup "Who plays" model list: a failed providers fetch is retried, not read as "no models" (SEATLIST1).

The browser module (static/tabletop/provider-list.js) runs under node here with an injected fetch and timers; no browser,
no live model server. Synthetic fixtures only, so the test can run on public CI."""
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import assert from 'node:assert/strict';
import {createProviderList} from './static/tabletop/provider-list.js';
import {setupControlHtml, refreshSetupControl, MODEL_PREFIX} from './static/tabletop/seats.js';

const MODEL = {id: 'local-test', label: 'Test Model'};
function harness(responses) {
  const timers = [];
  const calls = [];
  const changes = [];
  const list = createProviderList({
    fetchProviders: async () => { calls.push(1); const next = responses.shift(); if (next instanceof Error) throw next; return next; },
    onChange: state => changes.push({providers: state.providers.length, unavailable: state.unavailable}),
    setTimer: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
    clearTimer: id => { timers[id - 1] && (timers[id - 1].cleared = true); },
  });
  const fire = async () => { const next = timers.filter(t => !t.cleared && !t.fired).shift(); assert.ok(next, 'a retry is scheduled'); next.fired = true; await next.fn(); };
  return {list, timers, calls, changes, fire};
}

// 1. Fetch fails, then succeeds: the model options end up in the menu and the open dropdown is refreshed.
{
  const h = harness([new Error('server restarting'), {providers: [MODEL]}]);
  await h.list.load();
  assert.equal(h.list.state.unavailable, true);
  assert.equal(h.list.state.providers.length, 0);
  assert.equal(h.timers[0].ms, 2000);
  assert.ok(!setupControlHtml(h.list.state.providers).includes(MODEL_PREFIX), 'no model option while unavailable');
  const select = {value: 'MANUAL', innerHTML: ''};
  refreshSetupControl(select, h.list.state.providers);
  await h.fire();
  assert.equal(h.list.state.unavailable, false);
  assert.equal(h.list.state.known, true);
  assert.deepEqual(h.changes.at(-1), {providers: 1, unavailable: false});
  assert.ok(setupControlHtml(h.list.state.providers).includes('value="' + MODEL_PREFIX + 'local-test"'));
  refreshSetupControl(select, h.list.state.providers);
  assert.ok(select.innerHTML.includes('value="' + MODEL_PREFIX + 'local-test"'), 'open dropdown gets the model');
  assert.equal(select.value, 'MANUAL', 'the chosen mode survives the refresh');
  assert.equal(h.timers.length, 1, 'no retry after success');
}

// 2. A successful empty list: no models, no warning, no retry.
{
  const h = harness([{providers: []}]);
  await h.list.load();
  assert.equal(h.list.state.known, true);
  assert.equal(h.list.state.unavailable, false);
  assert.equal(h.timers.length, 0);
  assert.ok(!setupControlHtml(h.list.state.providers).includes(MODEL_PREFIX));
}

// 3. A later failure keeps the last good list and shows no warning.
{
  const h = harness([{providers: [MODEL]}, new Error('down')]);
  await h.list.load();
  await h.list.load();
  assert.equal(h.list.state.providers.length, 1);
  assert.equal(h.list.state.unavailable, false);
  assert.equal(h.timers.length, 0);
}

// 4. Backoff: 2 s, 5 s, 10 s, then 10 s again while still failing.
{
  const h = harness([new Error('a'), new Error('b'), new Error('c'), new Error('d'), {providers: []}]);
  await h.list.load();
  for (let i = 0; i < 4; i++) await h.fire();
  assert.deepEqual(h.timers.map(t => t.ms), [2000, 5000, 10000, 10000]);
  assert.equal(h.list.state.unavailable, false);
}

// 5. A malformed reply counts as a failed fetch, not as an empty list.
{
  const h = harness([{}]);
  await h.list.load();
  assert.equal(h.list.state.unavailable, true);
  assert.equal(h.timers.length, 1);
}
console.log('ok');
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_failed_providers_fetch_is_retried_and_empty_list_is_quiet():
    result = subprocess.run(["node", "--input-type=module", "-e", SCRIPT], cwd=APP, text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
