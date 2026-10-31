// Real desktop auto-step/deferred-menu/playback code; no browser or model server.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {modelOwner, serverDriving} from '../static/tabletop/seats.js';
import {readStdinPayload} from './node_stdin.mjs';

const input = await readStdinPayload();
// The handoff under review is between summoned AI turns, not the human action menu.
// No stdin payload means this file is not being driven by its Python caller (the
// public CI node job runs the file on its own); report a skip, never a hang or a throw.
const fixtures = input.trim() ? JSON.parse(input).filter(row => !row.expanded.menu?.manual) : null;
const noFixture = fixtures ? false : 'Python supplies the auto-step fixtures on stdin';
const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function piece(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}

test('commanded servant auto-step paints its commit, loads the next header and remains actionable', {skip: noFixture}, async () => {
  const document = installDOM('<body><div id="ttActionBar"></div><span id="ttMatchName"></span><span id="ttRound"></span></body>');
  const app = {matchId: fixtures[0].before.match_id, state: null, menu: null, selected: new Set(),
    lastSequence: fixtures[0].before.last_sequence, playing: false, busy: false, fog: 'own',
    seatStatus: {seats: {}}, diceOn: false, speed: 0};
  const requests = [], notices = [], painted = [];
  let active, ui;
  const noop = () => {};
  const map = {width: 48, height: 36, walls: [], objects: [], trees: [], decor: [], background: {url: ''},
    cells: {blocked: [], sight: []}, floors: []};
  const bindings = {
    app, document, modelOwner, serverDriving, enc: encodeURIComponent,
    $: selector => document.querySelector(selector),
    presentation: () => app.state?.presentation,
    actors: () => app.state?.presentation.actors || [],
    actorById: id => app.state?.presentation.actors.find(actor => actor.entity_id === id),
    currentViewer: () => ({ready: true}), isGMView: () => false,
    isManualActor: actor => ['MANUAL', 'SUGGESTED'].includes(actor?.controller), automaticSlot: () => false,
    reconcileViewerIdentity: noop, renderCommitNotice: noop, reconcileOptionDraft: noop,
    invalidateTargeting: noop, broadcastDraftStates: noop, mapFromState: () => map,
    wallSightCells: () => [], opacityGrid: () => [], teamIndex: () => 0,
    board: {setRoofView: noop, setMap: noop, setRemembered: noop, animateMove: async () => {}, floatText: noop},
    renderZones: noop, renderTokens: noop, renderInitiative: noop, renderRoster: noop, renderInspector: noop,
    renderItemsPanel: noop, renderShapePanel: noop, scheduleAutoPlay: noop, renderHighlights: noop,
    broadcastActors: noop, renderPip: noop, scheduleSeatPoll: noop,
    appendFeed: rows => painted.push(...rows), resumeServerPrompt: noop,
    hint: noop, toggleAIPlayback: noop, setControl: noop, openSeatLog: noop,
    withReactions: send => send([]), loadSeats: async () => {},
    readTableState: async () => active.expanded,
    renderObservedState: state => ui.render(state),
    handleUnavailableFight: async () => false, toast: text => notices.push(text),
    api: async (path, options) => {
      if (path.includes('/events?')) return active.result.events;
      assert.ok(path.endsWith('/auto-step'), path);
      requests.push(options.body);
      return active.result;
    },
  };
  ui = Function(...Object.keys(bindings), 'let refreshSequence = 0; let deferredMenuRead = null; '
    + 'let menuLoadingTimer = null; let menuLoadingActor = null;\n'
    + ['modelTurnNow', 'renderActionBar', 'render', 'requestDeferredMenu', 'refresh', 'eventsThroughState',
       'playEvents', 'playEventBatch', 'autoStep'].map(piece).join('\n')
    + '\nreturn {render, autoStep, requestDeferredMenu};')(...Object.values(bindings));
  for (const fixture of fixtures) {
    active = fixture;
    ui.render(fixture.before);
    assert.equal(app.menu, null, 'an AI header must not become a player action list');
    assert.equal(await ui.autoStep(), true);
    if (app.state.menu_pending) await ui.requestDeferredMenu();
    assert.equal(app.busy, false);
    assert.equal(document.body.classList.contains('is-working'), false);
    assert.equal(app.state.last_sequence, fixture.expanded.last_sequence);
    assert.ok(app.lastSequence > fixture.before.last_sequence, 'the event cursor advances');
    assert.equal(app.state.menu_pending, undefined);
    const expected = fixture.expanded.presentation.actors.find(
      actor => actor.entity_id === fixture.expanded.presentation.current_actor_id).display_name;
    assert.equal(document.querySelector('#ttActionBar strong').textContent, expected);
  }
  assert.equal(requests.length, fixtures.length);
  assert.ok(painted.length);
  assert.deepEqual(notices, []);
});
