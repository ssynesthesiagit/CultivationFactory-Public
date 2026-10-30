#!/usr/bin/env python3
"""Lead-run controller UI regression, using only disposable data and offline models.

CONTROLLER_BROWSER=1 enables Chromium outside the sandbox; otherwise skipped.
--fixture-only always exercises the real HTTP fixtures without importing Playwright.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

APP = Path(__file__).resolve().parents[1]
PLAYWRIGHT = Path(os.environ.get('PLAYWRIGHT_MODULES') or Path.home() / 'Projects/hermes-agent/node_modules')
PROJECTS = ['00000171-0000-4000-8000-000000000001', '00000171-0000-4000-8000-000000000002']
ACTORS = ['actor:factory.' + pid for pid in PROJECTS]

# Kept inline so the disposable ESM file resolves the lead's existing node_modules.
BROWSER = r'''
import assert from 'node:assert/strict';
const [base, match, actor, name, mode, shots] = process.argv.slice(2);
const labels = mode === 'providers' ? [
  '1 fighter card: You / AI (Dao) / Model',
  '2 Model picker: named fighter and both providers',
  '3 suggestions re-render when switching small to big',
  '4 explicit short-list style saved through seat-status',
  '5 completed model turn decision shown in the decision log',
] : mode === 'regressions' ? [
  '7 last Model seat leaves a paused fight; normal Play advances AI',
  '8 idle observation preserves Full rules, focus and action bar',
] : mode === 'setup' ? [
  '9 setup model ownership precedes actions; one fight and saved team restore',
] : mode === 'removed' ? [
  '10 saved team with removed provider falls back to AI',
] : ['6 no providers file: no Model button'];
let failures = 0;
const seen = new Set();
async function check(index, fn) {
  seen.add(index);
  try { await fn(); console.log(`PASS ${labels[index]}`); return true; }
  catch (error) { failures++; console.log(`FAIL ${labels[index]}: ${error.message}`); return false; }
}
let browser;
try {
  const {chromium} = await import('playwright');
  browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.setDefaultTimeout(20000);
  await page.goto(`${base}/tabletop?match=${encodeURIComponent(match)}`);
  await page.waitForFunction(() => window.tabletop?.app.state && !window.tabletop.app.busy);
  // Select through the rendered roster, rather than calling a UI helper directly.
  await page.locator('#ttRoster button').filter({has: page.locator('strong', {hasText: name})}).first().click();
  const card = page.locator('#ttInspector');
  if (mode === 'setup' || mode === 'removed') {
    async function api(path, body) {
      // Request-context reads bypass page routes used to hold installation.
      const token = (await (await page.request.get(`${base}/api/session`)).json()).token;
      const response = body === undefined ? await page.request.get(base + path, {
        headers: {'X-Controller-Fixture': '1'},
      }) : await page.request.post(base + path, {
        headers: {'X-Foundry-Token': token}, data: body,
      });
      assert.ok(response.ok(), `${path}: HTTP ${response.status()}`);
      return response.json();
    }
    const teamName = 'Controller browser model team';
    const teams = page.locator('#ttBuilder .tt-team');
    const controls = side => side.locator('.tt-slot select[aria-label^="Who plays"]');
    async function builder() {
      await page.locator('#ttLobbyOpen').click();
      await teams.nth(1).waitFor();
    }
    async function loadTeam() {
      const side = teams.first();
      await page.waitForFunction(title => [...document.querySelectorAll('#ttBuilder [data-team] option')]
        .some(option => option.value === title), teamName);
      await side.locator('[data-team]').selectOption(teamName);
      await side.locator('[data-team-load]').click();
    }
    await check(0, async () => {
      try {
        if (mode === 'removed') {
          assert.deepEqual((await api('/api/tabletop/providers')).providers.map(row => row.id), ['small']);
          const saved = (await api('/api/tabletop/saved-teams')).teams.find(row => row.name === teamName);
          assert.equal(saved.members[0].mode, 'MODEL:big', 'Stored choice must survive actual provider removal');
          await builder();
          await loadTeam();
          await page.waitForFunction(() => document.querySelector('#ttBuilder .tt-team .tt-slot select[aria-label^="Who plays"]')?.value === 'LOCAL_AUTO');
          assert.equal(await teams.first().locator('.tt-slot select').first().inputValue(), actor.replace('actor:factory.', ''));
          assert.equal(await controls(teams.first()).inputValue(), 'LOCAL_AUTO');
          assert.equal(await controls(teams.first()).locator('option[value="MODEL:big"]').count(), 0);
          return;
        }
        await builder();
        for (let i = 0; i < 2; i++) {
          const side = teams.nth(i);
          await side.locator('.tt-slot-face').click();
          await page.locator('.tt-picker section[aria-label="All characters"] button')
            .filter({hasText: i === 0 ? 'Controller fighter' : 'Controller opponent'}).first().click();
          assert.deepEqual(await controls(side).locator('option').allTextContents(), ['You', 'AI', 'small', 'big']);
          await controls(side).selectOption(i === 0 ? 'MODEL:big' : 'LOCAL_AUTO');
        }
        await page.locator('#ttBuilder .tt-builder-foot select').selectOption('battlefield:map.controller-browser');
        const before = await api('/api/combat/matches');
        let createdId, baseline, initialEvents, seatObserved = false, releaseObserved = false;
        const routeErrors = [];
        async function unchanged(root) {
          const state = await api(`${root}/state`);
          assert.equal(state.menu.state_version, baseline.menu.state_version, 'Action committed before model ownership');
          assert.equal(state.last_sequence, baseline.last_sequence, 'Event sequence advanced during setup');
          assert.equal(state.pending_action, null, 'Action/reaction began before ownership was ready');
          assert.deepEqual(await api(`${root}/events?after=0`), initialEvents, 'Setup event log changed');
        }
        const intercept = async route => {
          const request = route.request();
          const path = decodeURIComponent(new URL(request.url()).pathname);
          if (request.method() !== 'POST') return route.continue();
          try {
            if (path === '/api/combat/factory-matches') {
              assert.equal(request.postDataJSON().control_modes[actor], 'MANUAL');
              assert.equal(request.postDataJSON().control_modes['actor:factory.00000171-0000-4000-8000-000000000002'], 'LOCAL_AUTO');
              const response = await route.fetch();
              assert.ok(response.ok(), 'Factory Create must succeed');
              createdId = (await response.json()).match_id;
              const root = `/api/tabletop/matches/${encodeURIComponent(createdId)}`;
              baseline = await api(`${root}/state`);
              initialEvents = await api(`${root}/events?after=0`);
              assert.ok(Number.isInteger(baseline.menu?.state_version), 'Initial state version required');
              assert.ok(Number.isInteger(baseline.last_sequence), 'Initial event sequence required');
              assert.equal(baseline.pending_action, null);
              assert.deepEqual((await api(`${root}/seat-status`)).seats, {});
              return route.fulfill({response});
            }
            const root = `/api/tabletop/matches/${encodeURIComponent(createdId)}`;
            if (path === `/api/tabletop/matches/${createdId}/seat`) {
              assert.equal((await api(`${root}/seat-status`)).paused, true);
              await unchanged(root);
              const response = await route.fetch();
              assert.ok(response.ok(), 'Setup seat POST must succeed');
              const seat = (await api(`${root}/seat-status`)).seats[actor];
              assert.equal(seat.control, 'MODEL');
              assert.equal(seat.provider_id, 'big');
              await unchanged(root);
              seatObserved = true;
              return route.fulfill({response});
            }
            if (path === `/api/tabletop/matches/${createdId}/playback` && request.postDataJSON().paused === false) {
              assert.ok(seatObserved, 'Playback released before model seat existed');
              await unchanged(root);
              releaseObserved = true;
            }
            return route.continue();
          } catch (error) { routeErrors.push(error.message); await route.abort(); }
        };
        await page.route('**/api/**', intercept);
        try {
          await page.locator('#ttBuilder').getByRole('button', {name: 'Create fight', exact: true}).click();
          await page.waitForFunction(old => window.tabletop.app.matchId !== old
            && window.tabletop.app.state && !window.tabletop.app.busy && !document.querySelector('#ttLobby').open, match);
          assert.deepEqual(routeErrors, []);
          assert.ok(seatObserved && releaseObserved, 'Seat/release checkpoints were not reached');
          assert.equal(await page.evaluate(() => window.tabletop.app.matchId), createdId);
          const after = await api('/api/combat/matches');
          assert.equal(after.length, before.length + 1, 'Create must add exactly one fight');
          assert.deepEqual(after.filter(row => !before.some(old => old.match_id === row.match_id)).map(row => row.match_id), [createdId]);
          const seat = (await api(`/api/tabletop/matches/${encodeURIComponent(createdId)}/seat-status`)).seats[actor];
          assert.equal(seat.control, 'MODEL');
          assert.equal(seat.provider_id, 'big');
          console.log(`PASS 9a no pre-seat action: version=${baseline.menu.state_version}, sequence=${baseline.last_sequence}; single fight=${createdId}`);
          await page.screenshot({path: `${shots}/09-setup-model-table.png`, fullPage: true});
        } finally { await page.unroute('**/api/**', intercept); }
        await builder();
        page.once('dialog', dialog => dialog.accept(teamName));
        const saved = page.waitForResponse(r => decodeURIComponent(new URL(r.url()).pathname)
          === '/api/tabletop/saved-teams' && r.request().method() === 'POST');
        await teams.first().locator('[data-team-save]').click();
        const response = await saved;
        assert.ok(response.ok());
        assert.equal((await response.json()).members[0].mode, 'MODEL:big');
        await page.reload();
        await page.waitForFunction(() => window.tabletop?.app.state && !window.tabletop.app.busy);
        await builder();
        await loadTeam();
        await page.waitForFunction(() => document.querySelector('#ttBuilder .tt-team .tt-slot select[aria-label^="Who plays"]')?.value === 'MODEL:big');
        assert.equal(await controls(teams.first()).inputValue(), 'MODEL:big');
        assert.equal(await teams.first().locator('.tt-slot select').first().inputValue(), actor.replace('actor:factory.', ''));
      } finally {
        await page.screenshot({path: `${shots}/${mode === 'setup' ? '09-setup-model-preset' : '10-removed-model-ai'}.png`, fullPage: true});
      }
    });
  } else if (mode === 'empty') {
    await check(0, async () => {
      await card.getByRole('button', {name: 'You', exact: true}).waitFor();
      await card.getByRole('button', {name: 'AI (Dao)', exact: true}).waitFor();
      assert.equal(await card.getByRole('button', {name: 'Model', exact: true}).count(), 0);
      assert.equal(await page.locator('[data-control="MODEL"]').count(), 0);
      await page.screenshot({path: `${shots}/06-no-model.png`, fullPage: true});
    });
  } else if (mode === 'regressions') {
    // Each regression gets a fresh fight; checks 1-6 may already have spent turns.
    const opponent = 'actor:factory.00000171-0000-4000-8000-000000000002';
    async function api(path, body) {
      return page.evaluate(async ({path, body}) => {
        const token = (await (await fetch('/api/session')).json()).token;
        const response = await fetch(path, body === undefined ? {headers: {'X-Controller-Fixture': '1'}} : {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-Foundry-Token': token},
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(`${path}: HTTP ${response.status} ${await response.text()}`);
        return response.json();
      }, {path, body});
    }
    async function freshFight(number) {
      const created = await api('/api/combat/factory-matches', {
        project_ids: [actor.replace('actor:factory.', '')], opponent_actor_ids: [opponent],
        control_modes: {[actor]: 'MANUAL', [opponent]: 'MANUAL'},
        arena_id: 'battlefield:map.controller-browser', match_seed: `CTRLBROWSER-${number}`,
        display_name: `Disposable controller check ${number}`,
        prefight: {[actor.replace('actor:factory.', '')]: [], [opponent.replace('actor:factory.', '')]: []},
      });
      const root = `/api/tabletop/matches/${encodeURIComponent(created.match_id)}`;
      let state = await api(`${root}/state`);
      if (state.menu.actor_id !== actor) {
        const menu = state.menu;
        const ended = await api(`${root}/act`, {candidate_id: menu.end_turn,
          decision_id: menu.decision_id, state_version: menu.state_version, after: 0, reactions: []});
        assert.equal(ended.status, 'COMMITTED');
        state = await api(`${root}/state`);
      }
      assert.equal(state.menu.actor_id, actor);
      return {root, mid: created.match_id};
    }
    async function openFight(mid) {
      await page.goto(`${base}/tabletop?match=${encodeURIComponent(mid)}`);
      await page.waitForFunction(() => window.tabletop?.app.state && !window.tabletop.app.busy);
    }
    async function playbackClick(mid, paused) {
      const response = page.waitForResponse(r => decodeURIComponent(new URL(r.url()).pathname)
        === `/api/tabletop/matches/${mid}/playback` && r.request().method() === 'POST');
      await page.locator('#ttActionBar [data-play]').filter({hasText: paused ? 'Pause' : 'Play'}).click();
      assert.ok((await response).ok(), 'Playback POST must succeed');
      await page.waitForFunction(paused => window.tabletop.app.seatStatus.paused === paused
        && !window.tabletop.app.playbackInFlight, paused);
    }
    await check(0, async () => {
      try {
        const {root, mid} = await freshFight(7);
        // Start held so loading the page cannot race the offline model to fight end.
        await api(`${root}/playback`, {paused: true});
        await api(`${root}/seat`, {actor_id: opponent, control: 'MODEL', provider_id: 'big', style: 'choices'});
        await api(`${root}/seat`, {actor_id: actor, control: 'AI'});
        await openFight(mid);
        await playbackClick(mid, false);
        await playbackClick(mid, true);
        assert.equal((await api(`${root}/seat-status`)).paused, true);
        const held = (await api(`${root}/events?after=0`)).last_sequence;
        for (let i = 0; i < 10; i++) {
          await page.waitForTimeout(500);
          assert.equal((await api(`${root}/events?after=0`)).last_sequence, held, 'Paused fight advanced');
        }
        const opponentName = (await api(`${root}/state`)).presentation.actors
          .find(row => row.entity_id === opponent).display_name;
        await page.locator('#ttRoster button').filter({has: page.locator('strong', {hasText: opponentName})}).first().click();
        const saved = page.waitForResponse(r => decodeURIComponent(new URL(r.url()).pathname)
          === `/api/tabletop/matches/${mid}/seat` && r.request().method() === 'POST');
        await card.getByRole('button', {name: 'You', exact: true}).click();
        assert.ok((await saved).ok(), 'Seat POST must succeed');
        const status = await api(`${root}/seat-status`);
        assert.ok(!Object.values(status.seats).some(seat => seat.control === 'MODEL'));
        assert.equal(status.paused, false, 'Last Model seat must clear persisted pause');
        await page.waitForFunction(() => !window.tabletop.app.busy
          && !Object.values(window.tabletop.app.seatStatus.seats).some(seat => seat.control === 'MODEL'));
        // If the server reached the Model turn before Pause, finish that human
        // turn through the UI, then stop the ordinary local playback first.
        if ((await api(`${root}/state`)).menu?.actor_id === opponent)
          await page.locator('#ttActionBar [data-end]').click();
        const play = page.locator('#ttActionBar [data-play]');
        await play.waitFor();
        if ((await play.innerText()).includes('Pause')) await play.click();
        await page.waitForFunction(() => !window.tabletop.app.busy && !window.tabletop.app.playing);
        assert.equal((await api(`${root}/state`)).presentation.current_actor_id, actor, 'Built-in AI turn required');
        const before = (await api(`${root}/events?after=0`)).last_sequence;
        const step = page.waitForResponse(r => decodeURIComponent(new URL(r.url()).pathname)
          === `/api/tabletop/matches/${mid}/auto-step` && r.request().method() === 'POST');
        await play.filter({hasText: 'Play'}).click();
        const response = await step;
        assert.ok(response.ok(), `Normal Play Auto Step HTTP ${response.status()}`);
        assert.equal((await response.json()).status, 'COMMITTED');
        let advanced = false;
        for (let i = 0; i < 40; i++) {
          if ((await api(`${root}/events?after=0`)).last_sequence > before) { advanced = true; break; }
          await page.waitForTimeout(250);
        }
        assert.ok(advanced, 'Normal Play did not advance the AI event sequence');
      } finally { await page.screenshot({path: `${shots}/07-last-model-leaves.png`, fullPage: true}); }
    });
    await check(1, async () => {
      let bar, details, summary;
      let observations = 0;
      let root;
      const observe = response => {
        if (root && !response.request().headers()['x-controller-fixture']
            && decodeURIComponent(new URL(response.url()).pathname) === decodeURIComponent(`${root}/state`)
            && response.ok()) observations++;
      };
      try {
        const fight = await freshFight(8);
        root = fight.root;
        await api(`${root}/seat`, {actor_id: opponent, control: 'MODEL', provider_id: 'big', style: 'choices'});
        await openFight(fight.mid);
        await page.locator('#ttActionBar details summary').filter({hasText: /^Full rules$/}).first().waitFor();
        await page.waitForFunction(() => window.tabletop.app.menu?.actor_id === window.tabletop.app.state.presentation.current_actor_id
          && window.tabletop.app.menu.manual && !window.tabletop.app.polling);
        bar = await page.locator('#ttActionBar').elementHandle();
        summary = await page.locator('#ttActionBar details summary').filter({hasText: /^Full rules$/}).first().elementHandle();
        details = await summary.evaluateHandle(node => node.parentElement);
        await summary.click();
        await summary.focus();
        const stable = JSON.stringify(await api(`${root}/state`));
        const sequence = (await api(`${root}/events?after=0`)).last_sequence;
        const seats = await api(`${root}/seat-status`);
        assert.equal(seats.seats[opponent].control, 'MODEL');
        assert.notEqual(seats.seats[actor]?.control, 'MODEL');
        page.on('response', observe);
        // Model observation runs every 1.5 s. Count real state responses, not
        // merely wall time, and use explicit polling rather than async predicates.
        const deadline = Date.now() + 15000;
        let intervals = 0;
        do {
          await page.waitForTimeout(1500);
          intervals++;
          assert.equal(JSON.stringify(await api(`${root}/state`)), stable, 'Human state changed');
          assert.equal((await api(`${root}/events?after=0`)).last_sequence, sequence, 'Idle events changed');
          assert.ok(await details.evaluate(node => node.isConnected && node.open), 'Full rules was closed or replaced');
          assert.ok(await summary.evaluate(node => node.isConnected && document.activeElement === node), 'Summary lost focus');
          assert.ok(await bar.evaluate(node => node.isConnected && document.querySelector('#ttActionBar') === node), 'Action bar was replaced');
        } while ((intervals < 4 || observations < 4) && Date.now() < deadline);
        assert.ok(observations >= 4, `Only ${observations} idle state polls observed`);
      } finally {
        page.off('response', observe);
        await page.screenshot({path: `${shots}/08-idle-full-rules.png`, fullPage: true});
        for (const handle of [summary, details, bar]) if (handle) await handle.dispose();
      }
    });
  } else {
    await check(0, async () => {
      for (const text of ['You', 'AI (Dao)', 'Model'])
        await card.getByRole('button', {name: text, exact: true}).waitFor();
    });
    const dialog = page.locator('#ttSeat');
    await check(1, async () => {
      await card.getByRole('button', {name: 'Model', exact: true}).click();
      await dialog.waitFor({state: 'visible'});
      assert.equal(await dialog.locator('h2').innerText(), `Who plays ${name}?`);
      assert.deepEqual(await dialog.locator('input[name=ttSeatProvider]').evaluateAll(rows => rows.map(r => r.value)), ['small', 'big']);
      await dialog.getByText('small', {exact: true}).waitFor();
      await dialog.getByText('big', {exact: true}).waitFor();
      await page.screenshot({path: `${shots}/02-picker.png`, fullPage: true});
    });
    await check(2, async () => {
      await dialog.locator('input[name=ttSeatProvider][value=small]').check();
      await dialog.getByText('How the model plays', {exact: true}).waitFor();
      assert.ok(await dialog.getByRole('radio', {name: /^Pick from a short list \(suggested for this model\)/}).isChecked());
      assert.equal(await dialog.locator('input[name=ttSeatStyle][value=full]').isChecked(), false);
      await page.screenshot({path: `${shots}/03-small-suggestion.png`, fullPage: true});
      await dialog.locator('input[name=ttSeatProvider][value=big]').check();
      assert.ok(await dialog.getByRole('radio', {name: /^Plan the whole turn \(suggested for this model\)/}).isChecked());
      assert.equal(await dialog.locator('input[name=ttSeatStyle][value=choices]').isChecked(), false);
      await page.screenshot({path: `${shots}/03-big-suggestion.png`, fullPage: true});
    });
    await check(3, async () => {
      await dialog.locator('input[name=ttSeatProvider][value=big]').check();
      await dialog.locator('input[name=ttSeatStyle][value=choices]').check();
      const saved = page.waitForResponse(r => decodeURIComponent(new URL(r.url()).pathname) === `/api/tabletop/matches/${match}/seat` && r.request().method() === 'POST');
      await dialog.getByRole('button', {name: 'Let this model play', exact: true}).click();
      assert.ok((await saved).ok(), 'Seat POST must succeed');
      await dialog.waitFor({state: 'hidden'});
      const seat = await page.evaluate(async ({match, actor}) => {
        const r = await fetch(`/api/tabletop/matches/${encodeURIComponent(match)}/seat-status`);
        if (!r.ok) throw new Error(`seat-status HTTP ${r.status}`);
        return (await r.json()).seats[actor];
      }, {match, actor});
      assert.deepEqual(seat, {control: 'MODEL', provider_id: 'big', style: 'choices'});
    });
    await check(4, async () => {
      // Require a COMPLETED model turn for the model fighter: an ERROR row, a fallback, or a table stuck on
      // "is deciding…" must fail. The rendered decision log must then show that same decision.
      const completedTurn = rows => rows.find(row => row.kind === 'TURN' && row.actor_id === actor
        && !row.error && !row.fallback && (row.text || '').trim());
      // Self-test of the acceptance rule (printed every run): ERROR-only and empty (permanently deciding) fail.
      assert.equal(completedTurn([{kind: 'ERROR', actor_id: actor, error: 'TimeoutError', text: 'Model control stopped.'}]), undefined);
      assert.equal(completedTurn([]), undefined);
      assert.equal(completedTurn([{kind: 'TURN', actor_id: actor, fallback: 'provider', text: 'built-in AI chose'}]), undefined);
      assert.ok(completedTurn([{kind: 'TURN', actor_id: actor, fallback: null, text: 'plans: Move'}]));
      console.log('PASS 5a acceptance rule rejects ERROR-only, fallback-only and never-finished decisions');
      // waitForFunction treats an async predicate's Promise as truthy, so poll explicitly.
      let rows = [], done;
      for (let tries = 0; tries < 120 && !done; tries++) {
        rows = await page.evaluate(async match => {
          const r = await fetch(`/api/tabletop/matches/${encodeURIComponent(match)}/seat-decisions`);
          return r.ok ? (await r.json()).decisions : [];
        }, match);
        done = completedTurn(rows);
        if (!done) await page.waitForTimeout(500);
      }
      console.log(`seat-decisions rows: ${JSON.stringify(rows).slice(0, 600)}`);
      assert.ok(done, 'no completed model TURN decision for the model fighter within 60 s');
      await card.locator('[data-seat-log]').click();
      await page.locator('#ttSeatLog[open] .tt-seat-log li').first().waitFor();
      await page.screenshot({path: `${shots}/05-decision-log.png`, fullPage: true});
      const rendered = await page.locator('#ttSeatLogBody').innerText();
      assert.ok(rendered.includes(done.text.trim()), `decision log does not show the completed decision: ${done.text}`);
    });
  }
} catch (error) {
  for (let i = 0; i < labels.length; i++) if (!seen.has(i)) {
    failures++; console.log(`FAIL ${labels[i]}: fixture/browser setup: ${error.message}`);
  }
  if (seen.size === labels.length) { failures++; console.log(`FAIL browser lifecycle: ${error.message}`); }
} finally { if (browser) await browser.close(); }
process.exitCode = failures ? 1 : 0;
'''


def fixture_app(data: Path):
    """Build only this runner's isolated app, including its offline transport."""
    from app.api import create_app
    from app.core import Settings

    settings = replace(Settings.from_env(APP, data), security_dir=data.resolve() / 'security',
                       factory_zip=None, fixture_path=None)
    application = create_app(settings)

    # This synthetic provider sits outside the app's mutation-token middleware:
    # model transports do not send a table session token. All real table routes
    # still pass through the app's unchanged security and service code.
    @application.middleware('http')
    async def offline_completion(request, call_next):
        if request.url.path == '/controller-fixture/v1/chat/completions' and request.method == 'POST':
            # Only checks 7-8 use this marker. Keep a Model turn observable long
            # enough to press Pause; the original picker checks stay unchanged.
            if (data / 'regression-delay').exists():
                import asyncio
                await asyncio.sleep(1)
            from starlette.responses import JSONResponse
            return JSONResponse({'choices': [{'message': {'content': 'A'}}]})
        return await call_next(request)

    return application


def serve(data: Path, fd: int) -> None:
    import uvicorn

    application = fixture_app(data)

    with socket.socket(fileno=fd) as sock:
        uvicorn.Server(uvicorn.Config(application, log_level='warning')).run(sockets=[sock])


def reserve_socket() -> socket.socket:
    while True:
        sock = socket.socket()
        try:
            sock.bind(('127.0.0.1', 0))
            if sock.getsockname()[1] != 8765:
                sock.listen(128)
                return sock
        except BaseException:
            sock.close()
            raise
        sock.close()


def seed_sheets(data: Path) -> None:
    from tests.h1_support import sheet
    from tests.test_carry import KIT

    for pid in PROJECTS:
        folder = data / 'portable_characters' / pid
        folder.mkdir(parents=True)
        document = sheet([], cl=15, kit={'starting_kit': KIT})
        document['identity']['name'] = 'Controller fighter' if pid == PROJECTS[0] else 'Controller opponent'
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))


def fixture(base: str, process: subprocess.Popen, providers: bool) -> tuple[str, str]:
    token = None

    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Foundry-Token'] = token
        req = urllib.request.Request(base + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    deadline = time.monotonic() + 120
    while True:
        if process.poll() is not None:
            raise RuntimeError(f'Isolated server exited: {process.returncode}')
        try:
            token = request('/api/session')['token']
            break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise RuntimeError('Isolated server readiness deadline exceeded')
            time.sleep(0.2)
    if providers:
        rows = request('/api/tabletop/providers')['providers']
        assert [(r['id'], r['prompt_profile']) for r in rows] == [('small', 'choices'), ('big', 'full')], rows
        from agent_seats.providers import ProviderRegistry, complete
        for config in ProviderRegistry().load().values():
            assert complete(config, 'Offline fixture check')[0] == 'A'
    else:
        # A missing registry currently returns 500; the page catches this and
        # leaves its provider list empty. An empty-list API fix is also valid.
        try:
            assert request('/api/tabletop/providers')['providers'] == []
        except urllib.error.HTTPError as exc:
            if exc.code != 500:
                raise
    request('/api/tabletop/maps', {'map': {
        'map_id': 'controller-browser', 'display_name': 'Controller check floor',
        'width_squares': 20, 'height_squares': 14,
        'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]},
    }})
    created = request('/api/combat/factory-matches', {
        'project_ids': [PROJECTS[0]], 'opponent_actor_ids': [ACTORS[1]],
        'control_modes': {actor: 'MANUAL' for actor in ACTORS},
        'arena_id': 'battlefield:map.controller-browser', 'match_seed': 'CTRLBROWSER',
        'display_name': 'Disposable controller browser check',
        'prefight': {pid: [] for pid in PROJECTS},
    })
    mid = created['match_id']
    root = f'/api/tabletop/matches/{mid}'
    state = request(root + '/state')
    if state['menu']['actor_id'] != ACTORS[0]:
        menu = state['menu']
        ended = request(root + '/act', {'candidate_id': menu['end_turn'], 'decision_id': menu['decision_id'],
                                       'state_version': menu['state_version'], 'after': 0, 'reactions': []})
        assert ended['status'] == 'COMMITTED', ended
        state = request(root + '/state')
    assert state['menu']['actor_id'] == ACTORS[0]
    assert {row['entity_id'] for row in state['presentation']['actors']} == set(ACTORS)
    assert request(root + '/seat-status')['seats'] == {}
    name = next(row['display_name'] for row in state['presentation']['actors'] if row['entity_id'] == ACTORS[0])
    with urllib.request.urlopen(base + '/tabletop?match=' + mid) as response:
        assert b'id="ttSeat"' in response.read()
    print(f'PASS HTTP fixture ({"providers" if providers else "no providers file"}): match={mid}', flush=True)
    return mid, name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-only', action='store_true')
    parser.add_argument('--shots', type=Path, help='Retained screenshot directory (required for browser mode)')
    parser.add_argument('--log', type=Path, help='Retained log (default: unique /var/tmp log)')
    parser.add_argument('--playwright-modules', type=Path, default=PLAYWRIGHT)
    parser.add_argument('--serve', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--socket-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.socket_fd)
        return 0
    if not args.fixture_only:
        if os.environ.get('CONTROLLER_BROWSER') != '1':
            print('SKIP controller browser: set CONTROLLER_BROWSER=1 outside the sandbox, or use --fixture-only')
            return 0
        if not args.shots:
            parser.error('--shots is required for browser checks')
        if not (args.playwright_modules / 'playwright/package.json').is_file() or not Path('/usr/bin/chromium').is_file():
            parser.error('Requires the lead Playwright module and /usr/bin/chromium outside the sandbox')
        args.shots = args.shots.resolve()
        args.shots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ctrlbrowser-', dir='/var/tmp') as temporary:
        scratch = Path(temporary)
        log_path = (args.log or scratch.with_suffix('.log')).resolve()
        if scratch == log_path or scratch in log_path.parents:
            parser.error('--log must be outside the disposable directory')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        print(f'Retained log: {log_path}', flush=True)
        browser_test = scratch / 'controller.mjs'
        if not args.fixture_only:
            (scratch / 'node_modules').symlink_to(args.playwright_modules.resolve(), target_is_directory=True)
            browser_test.write_text(BROWSER)
        failed = False
        with log_path.open('w') as log:
            for providers in (True, False):
                data = scratch / ('with-providers' if providers else 'no-providers')
                seed_sheets(data)
                with reserve_socket() as sock:
                    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
                    provider_path = data / 'providers.json'
                    if providers:
                        rows = [{'id': pid, 'label': pid, 'kind': 'local', 'model': 'offline-' + pid,
                                 'base_url': base + '/controller-fixture/v1', 'timeout_s': 10,
                                 **({'prompt_profile': 'choices'} if pid == 'small' else {})}
                                for pid in ('small', 'big')]
                        provider_path.write_text(json.dumps({'providers': rows}))
                    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(APP),
                               TIANXIA_FOUNDRY_DATA=str(data), TIANXIA_FOUNDRY_SECURITY_DIR=str(data / 'security'),
                               FACTORY_SEAT_PROVIDERS=str(provider_path))
                    for key in ('TIANXIA_FACTORY_ZIP', 'TIANXIA_FACTORY_FIXTURE'):
                        env.pop(key, None)
                    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', str(data),
                                                '--socket-fd', str(sock.fileno())], cwd=APP, env=env,
                                               pass_fds=(sock.fileno(),), stdout=log, stderr=subprocess.STDOUT)
                    print(f'Isolated server PID: {process.pid}; data: {data}', flush=True)
                    try:
                        sock.close()
                        # Registry transport verification uses this exact temp file,
                        # never the owner's ambient providers or credentials.
                        previous = os.environ.get('FACTORY_SEAT_PROVIDERS')
                        os.environ['FACTORY_SEAT_PROVIDERS'] = str(provider_path)
                        try:
                            mid, name = fixture(base, process, providers)
                        finally:
                            if previous is None:
                                os.environ.pop('FACTORY_SEAT_PROVIDERS', None)
                            else:
                                os.environ['FACTORY_SEAT_PROVIDERS'] = previous
                        if not args.fixture_only:
                            result = subprocess.run(['/usr/bin/node', str(browser_test), base, mid, ACTORS[0], name,
                                                     'providers' if providers else 'empty', str(args.shots)],
                                                    cwd=APP, env=env, stdout=subprocess.PIPE,
                                                    stderr=subprocess.STDOUT, text=True, timeout=180)
                            print(result.stdout, end='', flush=True)
                            log.write(result.stdout)
                            failed |= result.returncode != 0
                            if providers:
                                (data / 'regression-delay').touch()
                                result = subprocess.run(['/usr/bin/node', str(browser_test), base, mid, ACTORS[0], name,
                                                         'regressions', str(args.shots)],
                                                        cwd=APP, env=env, stdout=subprocess.PIPE,
                                                        stderr=subprocess.STDOUT, text=True, timeout=180)
                                print(result.stdout, end='', flush=True)
                                log.write(result.stdout)
                                failed |= result.returncode != 0
                                for setup_mode in ('setup', 'removed'):
                                    if setup_mode == 'removed':
                                        # Remove the provider from this disposable registry only;
                                        # check 10 must load check 9's genuinely persisted team.
                                        provider_path.write_text(json.dumps({'providers': rows[:1]}))
                                    result = subprocess.run(['/usr/bin/node', str(browser_test), base, mid, ACTORS[0], name,
                                                             setup_mode, str(args.shots)],
                                                            cwd=APP, env=env, stdout=subprocess.PIPE,
                                                            stderr=subprocess.STDOUT, text=True, timeout=180)
                                    print(result.stdout, end='', flush=True)
                                    log.write(result.stdout)
                                    failed |= result.returncode != 0
                    except Exception as exc:
                        print(f'FAIL {"provider" if providers else "no-provider"} run: {exc}', flush=True)
                        failed = True
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=15)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                        log.flush()
        print('Disposable servers stopped and scratch removed on exit; logs/screenshots retained.', flush=True)
        return int(failed)


if __name__ == '__main__':
    sys.path.insert(0, str(APP))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'FAIL controller fixture setup: {type(exc).__name__}: {exc}', flush=True)
        raise SystemExit(1)
