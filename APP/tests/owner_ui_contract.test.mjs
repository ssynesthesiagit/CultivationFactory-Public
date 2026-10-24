// Owner UI contracts: real board/card DOM events, no browser or model server.
// Sources: docs/tabletop/TABLETOP_GUIDE.md, FIGHT_AUDIT_2026-09-29.md,
// FOLLOWUPS MMX95/2026-10-06 duplicate hover text, and UIREGRESS1.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {functionSource, createTableHarness, tableState, actor} from './viewer_identity_harness.mjs';

const fighter = {id: 'a', name: 'Guo Yuan', x: 3, y: 3, z: 8, hp: 12, maxHp: 12,
  conditions: [{name: 'Grove Domain', text: 'Enemies in your Living Claims spend extra movement.'}]};
const zone = {zone_id: 'grove', name: 'Grove Domain', owner_id: 'a',
  affected_cells: [[4, 4]], detail: 'Enemies spend extra movement in Living Claims.',
  duration_rounds: 10, created_round: 1};

async function page(run, handlers = {}) {
  const original = {setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout};
  const doc = installDOM('<div id="board"></div>');
  let now = 0, seq = 0;
  const timers = new Map();
  globalThis.setTimeout = (fn, ms) => { timers.set(++seq, {fn, at: now + ms}); return seq; };
  globalThis.clearTimeout = id => timers.delete(id);
  const advance = ms => {
    now += ms;
    for (const [id, row] of [...timers]) if (row.at <= now) { timers.delete(id); row.fn(); }
  };
  const create = doc.createElement.bind(doc);
  doc.createElement = tag => {
    const node = create(tag);
    if (tag === 'canvas') node.toDataURL = () => 'data:image/png;base64,';
    return node;
  };
  try {
    const board = createBoard(doc.querySelector('#board'), handlers);
    board.setMap({width: 10, height: 8, background: {style: 'plain'}});
    await run({doc, board, advance, card: doc.body.querySelector('.tt-hovercard'),
      move: async (x, y, target = board.viewport) => {
        const event = {clientX: x, clientY: y, buttons: 0, target};
        await doc.dispatch('pointermove', event); // capture before viewport bubble
        await board.viewport.dispatch('pointermove', event);
      }});
  } finally { Object.assign(globalThis, original); }
}

for (const side of ['left', 'right']) {
  test(`${side} zone popup survives crossing its square and a wide gap, poll refresh, entry and wheel`, async () => {
    await page(async ({doc, board, advance, card, move}) => {
      board.setZones([zone], {round: 7});
      const left = side === 'right' ? 470 : 40;
      card.getBoundingClientRect = () => ({left, top: 100, right: left + 170, bottom: 450});
      await move(288, 288);
      advance(900);
      assert.equal(card.hidden, false);
      const content = card.firstChild, position = [card.style.left, card.style.top];
      // Real continuous path, rather than teleporting directly onto the overlay.
      for (const x of side === 'right' ? [295, 325, 370, 425, 465, 475] : [280, 255, 230, 215, 205]) {
        await move(x, 288);
        // Snapshot reconciliation can happen while approaching the card.
        board.setTokens([fighter]);
        board.setZones([{...zone}], {round: 7});
        board.setFog(null);
        board.setMovementExplanation({summary: {actor_id: 'a', movement_remaining_ft: 20}, destinations: {}});
        advance(100);
        assert.equal(card.hidden, false, `card survives at x=${x}`);
        assert.equal(card.firstChild, content, 'refresh cannot rebuild the rules being read');
        assert.deepEqual([card.style.left, card.style.top], position, 'popup never walks away');
      }
      await board.viewport.dispatch('pointerleave', {clientX: side === 'right' ? 475 : 205, clientY: 288, relatedTarget: card});
      await card.dispatch('pointerenter');
      await doc.dispatch('pointermove', {target: card, clientX: left + 80, clientY: 288});
      advance(2000);
      let prevented = false, stopped = false;
      card.scrollTop = 0;
      await card.dispatch('wheel', {deltaY: 90, preventDefault: () => { prevented = true; }, stopPropagation: () => { stopped = true; }});
      assert.equal(card.scrollTop, 90);
      assert.ok(prevented && stopped, 'wheel scrolls rules without zooming the map');
      assert.equal(card.firstChild, content);
      await doc.dispatch('pointermove', {clientX: 750, clientY: 550});
      advance(300);
      assert.equal(card.hidden, true, 'leaving the corridor still dismisses');
    });
  });
}

for (const side of ['left', 'right']) {
  for (const phase of ['source', 'approach', 'card', 'selection']) {
    test(`${side} destination guidance invalidates on clear/change during ${phase}`, async () => {
      for (const clear of [true, false]) await page(async ({doc, board, card, advance, move}) => {
        const oldReason = 'The old route costs 10 feet.';
        const newReason = 'The new route is blocked.';
        const initial = {destinations: {'4,4': {available: true, reasons: [{message: oldReason}]}}};
        const next = clear ? null : {destinations: {'4,4': {
          available: false, explained_refusal: true, reasons: [{message: newReason}],
        }}};
        board.setZones([zone]); // mixed rules + movement content must invalidate too
        board.setMovementExplanation(initial);
        const left = side === 'right' ? 470 : 40;
        card.getBoundingClientRect = () => ({left, top: 100, right: left + 170, bottom: 450});
        await move(288, 288); advance(900);
        assert.equal(card.hidden, false);
        assert.ok(card.querySelectorAll('span').some(node => node.textContent === oldReason));
        const content = card.firstChild;
        if (phase === 'approach') await move(side === 'right' ? 370 : 230, 288);
        if (phase === 'card' || phase === 'selection') {
          await doc.dispatch('pointermove', {target: card, clientX: left + 80, clientY: 288});
          await card.dispatch('pointerenter');
        }
        if (phase === 'selection') {
          globalThis.window.getSelection = () => ({isCollapsed: false, rangeCount: 1,
            getRangeAt: () => ({intersectsNode: node => node === card})});
        }
        board.setMovementExplanation(JSON.parse(JSON.stringify(initial)));
        assert.equal(card.hidden, false, 'an unchanged poll preserves guidance');
        assert.equal(card.firstChild, content);
        board.setMovementExplanation(next);
        assert.equal(card.hidden, true, 'changed movement must invalidate the actually open card');
        advance(2000);
        assert.equal(card.hidden, true, 'no stale delayed open survives invalidation');
        globalThis.window.getSelection = () => ({isCollapsed: true, rangeCount: 0});
        await move(288, 288); advance(900);
        assert.equal(card.hidden, false, 'fresh hover still shows zone rules');
        const lines = card.querySelectorAll('span').map(node => node.textContent);
        assert.ok(!lines.includes(oldReason));
        assert.equal(card.querySelectorAll('.tt-movement-tip').length, clear ? 0 : 1);
        if (!clear) assert.ok(lines.includes(newReason), 'fresh hover uses the new refusal');
      });
    });
  }
}

test('token card survives a poll refresh during approach and stays dismissed after Escape', async () => {
  await page(async ({doc, board, card, advance, move}) => {
    board.setTokens([fighter]);
    const token = board.tokenNode('a');
    token.getBoundingClientRect = () => ({left: 192, top: 192, right: 256, bottom: 256, width: 64, height: 64});
    card.getBoundingClientRect = () => ({left: 470, top: 100, right: 640, bottom: 450});
    await token.dispatch('pointerenter'); advance(500);
    await move(370, 224);
    board.setTokens([{...fighter, hp: 7}]);
    await move(425, 224);
    advance(400);
    assert.equal(card.hidden, false);
    await doc.dispatch('pointermove', {target: card, clientX: 480, clientY: 224});
    await card.dispatch('wheel', {deltaY: 60});
    assert.equal(card.scrollTop, 60);
    await doc.dispatch('keydown', {key: 'Escape'});
    board.setTokens([fighter]); advance(2000);
    assert.equal(card.hidden, true);
  });
});

test('remembered-area card opens after resting inside a token card bridge', async () => {
  await page(async ({board, card, advance, move}) => {
    card.getBoundingClientRect = () => ({left: 470, top: 100, right: 640, bottom: 450});
    board.setTokens([fighter]);
    const token = board.tokenNode('a');
    token.getBoundingClientRect = () => ({left: 192, top: 192, right: 256, bottom: 256, width: 64, height: 64});
    const tokenCell = board.cellAt(224, 224);
    const ghostCell = board.cellAt(352, 288);
    assert.deepEqual(ghostCell, {x: 5, y: 4});
    await token.dispatch('pointerenter', {clientX: 224, clientY: 224});
    advance(500);
    assert.match(card.innerHTML, /Guo Yuan/);

    const seen = new Uint8Array(10 * 8);
    seen[tokenCell.y * 10 + tokenCell.x] = 1;
    board.setFog(seen);
    board.setRemembered({width: 10, ghosts: [ghostCell.y * 10 + ghostCell.x], cells: {}});

    const previousContent = card.firstChild;
    await move(300, 288); // the pointer is travelling through the existing card's bridge
    await move(352, 288); // remembered square, still inside that bridge
    assert.equal(card.firstChild, previousContent, 'travel and polling keep the current card intact');
    advance(1999);
    assert.equal(card.firstChild, previousContent, 'the remembered card waits for a deliberate rest');
    advance(1);
    assert.notEqual(card.firstChild, previousContent, 'the remembered explanation replaces the old card after resting');
    assert.ok(card.querySelectorAll('span').some(node => node.textContent === 'You remember this area as it looked when you last saw it.'));
  });
});

test('crossing another token toward an open zone card cannot replace the rules', async () => {
  await page(async ({doc, board, card, advance, move}) => {
    board.setZones([zone]);
    board.setTokens([fighter]);
    card.getBoundingClientRect = () => ({left: 470, top: 100, right: 640, bottom: 450});
    await move(288, 288); advance(900);
    const content = card.firstChild, token = board.tokenNode('a');
    await token.dispatch('pointerenter', {clientX: 370, clientY: 288});
    await move(370, 288, token); advance(1000);
    assert.equal(card.firstChild, content);
    assert.equal(card.hidden, false);
    await doc.dispatch('keydown', {key: 'Escape'});
    await token.dispatch('pointerenter', {clientX: 224, clientY: 224}); advance(500);
    assert.match(card.innerHTML, /Guo Yuan/, 'a fresh hover still opens the creature card');
  });
});

test('one altitude badge per token through repeated table snapshots and height changes', () => {
  const t = createTableHarness({gm: true, state: tableState([actor('own', {x: 4, y: 4}, {altitude_ft: 40})],
    {map: {width: 10, height: 8, background: {style: 'plain'}}})});
  for (const height of [40, 40, 15, 0, 40]) {
    t.app.state.presentation.actors[0].altitude_ft = height;
    t.renderTokens();
    assert.equal(t.board.element.querySelectorAll('.tt-token').length, 1);
    assert.equal(t.board.tokenNode('own').dataset.tokenId, 'own');
    const badges = t.board.tokenNode('own').querySelectorAll('.tt-token-height');
    assert.equal(badges.length, 1);
    assert.equal(badges[0].textContent, height ? `↑${height} ft` : '');
  }
});

test('scratch browser entity gate accepts colocated claim badges and still rejects duplicate entities/badges', async () => {
  // Exercise the actual browser acceptance block with DOM-backed locators. This
  // guards the opt-in gate without launching Chromium or contacting a service.
  const source = readFileSync(new URL('./owner_ui_contract.browser.test.mjs', import.meta.url), 'utf8');
  const start = source.indexOf('      const visibleTokens =');
  const end = source.indexOf('      const point =', start);
  assert.ok(start >= 0 && end > start, 'scratch entity check is present');
  const check = new (Object.getPrototypeOf(async function () {}).constructor)(
    'page', 'assert', source.slice(start, end));
  await page(async ({doc, board}) => {
    board.setTokens([fighter, ...['claim-1', 'claim-2'].map(id => ({
      ...fighter, id, name: 'Living Claim', item: true,
    }))]);
    const nodes = board.element.querySelectorAll('.tt-token');
    const badges = nodes.flatMap(node => node.querySelectorAll('.tt-token-height'));
    for (const badge of badges) badge.getBoundingClientRect = () => ({
      left: 200, right: 245, top: 200, bottom: 215, width: 45, height: 15,
      toJSON() { return {...this}; },
    }); // distinct entities have intentionally identical badge rectangles
    const fakePage = {
      locator: selector => {
        assert.equal(selector, '.tt-token:not(.is-hidden)');
        return {evaluateAll: async fn => fn(nodes), all: async () => nodes.map(node => ({
          locator: css => ({count: async () => node.querySelectorAll(css).length}),
        }))};
      },
      evaluate: async fn => new Function('document', `return (${fn})();`)({
        querySelectorAll: () => badges,
      }),
    };
    await check(fakePage, assert);
    nodes[1].dataset.tokenId = 'a';
    await assert.rejects(check(fakePage, assert), /each visible entity is rendered once/);
    nodes[1].dataset.tokenId = 'claim-1';
    nodes[0].appendChild(doc.createElement('span')).className = 'tt-token-height';
    await assert.rejects(check(fakePage, assert), {code: 'ERR_ASSERTION'});
  });
});

test('double-click pops out a primary character sheet in a stable reusable window', async () => {
  const opened = [], messages = [];
  const open = new Function('actorById', 'projectOf', 'window', 'enc', 'toast',
    `${functionSource('openSheetFor')}\nreturn openSheetFor;`)(
    id => ({primary_combatant: id === 'a'}), () => 'project-1',
    {open: (...args) => { opened.push(args); return {}; }}, encodeURIComponent, (...args) => messages.push(args));
  await page(async ({board}) => {
    board.setTokens([fighter]);
    await board.tokenNode('a').dispatch('dblclick');
    await board.tokenNode('a').dispatch('dblclick');
    assert.equal(opened.length, 2);
    assert.deepEqual(opened[0], ['/tabletop/sheet?project=project-1', 'tt-sheet-project-1', 'popup=yes,width=1280,height=860']);
    assert.deepEqual(opened[0], opened[1]);
    assert.equal(messages.length, 0);
  }, {onTokenDoubleClick: open});
});

test('Escape resolves target cancellation and clears preview and choice UI', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('document.addEventListener("keydown", event => {');
  const handler = source.slice(start, source.indexOf('\n});', start) + 4);
  const doc = installDOM('<button id="target"></button>');
  const results = [], cleared = [];
  const app = {targeting: {resolve: value => results.push(value)}, hoverTarget: 'foe'};
  new Function('document', 'app', 'hint', 'renderHighlights', 'closeChoice', 'currentViewer',
    `const renderShapePanel = () => {}, renderActionBar = () => {};\n${functionSource('cancelTargeting', source)}\n${functionSource('abilityChoiceActive', source)}\n${functionSource('abilityReserved', source)}\n${functionSource('releaseMapPick', source)}\n${functionSource('cancelAbilityChoice', source)}\n${handler}`)(doc, app,
    value => cleared.push(value), () => cleared.push('preview'), () => cleared.push('choice'), () => ({ready: true}));
  await doc.dispatch('keydown', {target: doc.querySelector('#target'), key: 'Escape'});
  assert.equal(app.targeting, null); assert.equal(app.hoverTarget, null);
  assert.deepEqual(results, [false]); assert.deepEqual(cleared, [null, 'preview', 'choice']);
});

test('Escape and the visible Cancel button both decline a cancellable square choice', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('document.addEventListener("keydown", event => {');
  const handler = source.slice(start, source.indexOf('\n});', start) + 4);
  // The real cancel chain, loaded from source: cancelMapPick -> cancelAbilityChoice -> cancelTargeting, plus hint.
  const chain = ['cancelTargeting', 'abilityChoiceActive', 'abilityReserved', 'releaseMapPick', 'cancelAbilityChoice', 'cancelMapPick', 'hint']
    .map(name => functionSource(name, source)).join('\n');
  const stubs = 'const renderShapePanel = () => {}, renderActionBar = () => {}, renderHighlights = () => {}, closeChoice = () => {};';
  for (const gesture of ['escape', 'button']) {
    const doc = installDOM('<button id="target"></button><div id="ttHint"></div>');
    const replies = [], app = {mapPick: {allow_decline: true, close: value => replies.push(value)}};
    const hint = new Function('document', 'app', 'currentViewer', '$', 'escapeHtml',
      stubs + '\n' + chain + '\n' + handler + '\nreturn hint;')(
        doc, app, () => ({ready: true}), selector => doc.querySelector(selector), String);
    // The production map picker hands hint() the cancelMapPick callback (cancelAbilityChoice when unreserved).
    hint('Choose a square for Grove Domain.', () => app.mapPick.close({cancelled: true}), 'Cancel ability (Esc)',
      {label: 'Skip this choice', onClick: () => app.mapPick.close('DECLINE')});
    if (gesture === 'escape') await doc.dispatch('keydown', {target: doc.querySelector('#target'), key: 'Escape'});
    else await doc.querySelector('#ttHint').querySelector('button').dispatch('click');
    // Esc and the visible Cancel abandon the attempt, as the ESCCANCEL1 brief requires.
    assert.deepEqual(replies, [{cancelled: true}]);
  }
});

test('uploaded map art survives redraw and missing art retains the grid fallback', async () => {
  await page(async ({board}) => {
    const map = {width: 10, height: 8, background: {url: '/owner-map.png', style: 'plain'}};
    board.setMap(map); board.setZones([zone]); board.setTokens([fighter]); board.setMap(map);
    assert.equal(board.element.querySelector('.tt-bg-image').src, '/owner-map.png');
    assert.ok(board.element.querySelector('.tt-grid').children.length > 0);
    board.setMap({...map, background: {style: 'plain'}});
    assert.ok(board.element.querySelector('.tt-grid').children.length > 0);
    assert.ok(board.tokenNode('a'), 'tokens remain reachable without external art');
  });
});
