// node --test APP/tests/hovercard_board_dom.test.mjs
// The MAP's side of the shared hover card, on the real board.js in a DOM stub: no browser, no GUI.
//
// The review of MMX100 found that a token card the player had dismissed came straight back. board.js remembers which
// token it is describing (so it can refresh that card's hit points), but Escape, a press elsewhere and the grace
// period all closed the card without telling the board, so the next token update -- which arrives constantly -- put
// the same card back up. A card that ignores "go away" is worse than no card, because it covers the tokens.
//
// This file tests that at the level the bug showed: a mounted board, real tokens, real events, the real card.
import test from 'node:test';
import assert from 'node:assert/strict';

import {installDOM} from './objects_dom_stub.mjs';

const realSetTimeout = globalThis.setTimeout;
// A fresh page per test: two boards on one page would share the document (and the card ids in it), and a card left
// over from an earlier test would be found by the "the card in this page" lookups below.
// installDOM blanks the clock so nothing in the board waits on a real timer, and re-blanks it on every call, so
// node:test's own waits are handed back each time (corkboard #141).
function freshPage() {
  const doc = installDOM('<html><body><div id="board"></div><span id="pill">Blinded</span></body></html>');
  globalThis.setTimeout = realSetTimeout;
  return doc;
}
let doc = freshPage();

const {createBoard} = await import('../static/tabletop/board.js');
// The same specifier board.js uses, so this is the SAME module instance the board's card came from. Two instances of
// this module would each keep their own id counter, which is a test artefact the browser never has.
const {createHoverCard, bindTipTargets} = await import('../static/tabletop/hovercard.js?v=tipdelay-1');

const fighter = (over = {}) => ({id: 'a', name: 'Kael', hp: 12, maxHp: 12, x: 3, y: 3, conditions: [], ...over});

function mountBoard() {
  doc = freshPage();
  return createBoard(doc.querySelector('#board') || doc.getElementById('board'), {});
}
const cardNode = () => doc.body.querySelector('.tt-hovercard');
const tokenNode = board => board.element.querySelector('.tt-token');

async function withClock(run) {
  const original = {setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout};
  let now = 0, seq = 0;
  const timers = new Map();
  globalThis.setTimeout = (fn, ms) => { timers.set(++seq, {fn, at: now + ms}); return seq; };
  globalThis.clearTimeout = id => timers.delete(id);
  const advance = ms => {
    now += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
  };
  try { await run(advance); }
  finally { Object.assign(globalThis, original); }
}

for (const outside of [false, true]) {
  test(`zone card survives viewport-to-overlay transfer (${outside ? 'outside' : 'inside'} viewport)`, async () => {
    const board = mountBoard();
    await withClock(async advance => {
      const createElement = doc.createElement.bind(doc);
      doc.createElement = tag => {
        const node = createElement(tag);
        if (tag === 'canvas') node.toDataURL = () => 'data:image/png;base64,';
        return node;
      };
      board.setMap({width: 10, height: 8, background: {style: 'plain'}});
      board.setZones([{zone_id: 'dark', name: 'Darkness', affected_cells: [[4, 4]]}]);
      const card = cardNode();
      const left = outside ? 810 : 400;
      card.getBoundingClientRect = () => ({left, top: 250, right: left + 160, bottom: 450});
      await board.viewport.dispatch('pointermove', {clientX: 288, clientY: 288});
      advance(900);
      assert.equal(card.hidden, false);
      assert.ok(card.classList.contains('tt-zone-tip'));
      assert.equal(card.parentNode, doc.body, 'overlay is a sibling of the viewport');
      // The last document move is in the bridge, not the card. Browser hit testing sends viewport leave BEFORE
      // the next document pointermove on entering a body overlay, even when it visually covers the viewport.
      await doc.dispatch('pointermove', {clientX: left - 10, clientY: 288});
      await board.viewport.dispatch('pointerleave', {relatedTarget: card, clientX: left + 2, clientY: 288});
      assert.equal(card.hidden, false, 'viewport leave must not close before overlay enter');
      await card.dispatch('pointerenter', {clientX: left + 2, clientY: 288});
      await doc.dispatch('pointermove', {target: card, clientX: left + 2, clientY: 288});
      advance(1000);
      assert.equal(card.hidden, false);
      card.scrollTop = 0;
      await card.dispatch('wheel', {deltaY: 80});
      assert.equal(card.scrollTop, 80, 'card remains interactive after the transfer');
      await card.dispatch('pointerleave', {clientX: 20, clientY: 20});
      await doc.dispatch('pointermove', {clientX: 20, clientY: 20});
      advance(300);
      assert.equal(card.hidden, true, 'ordinary departure still closes after grace');
    });
  });
}

for (const dismissal of ['escape', 'outside-press']) {
  test(`${dismissal} invalidates a pending token movement-summary open`, async () => {
    const board = mountBoard();
    await withClock(async advance => {
      board.setTokens([fighter()]);
      board.setMovementExplanation({summary: {actor_id: 'a', effective_speed_ft: 30,
        movement_remaining_ft: 20, reasons: []}, destinations: {}});
      const token = tokenNode(board), card = cardNode();
      token.getBoundingClientRect = () => ({left: 192, top: 192, right: 256, bottom: 256});
      card.getBoundingClientRect = () => ({left: 400, top: 200, right: 560, bottom: 400});
      const rest = {target: token, clientX: 224, clientY: 224, buttons: 0};
      await token.dispatch('pointerenter');
      await doc.dispatch('pointermove', rest); // document capture precedes the viewport handler
      await board.viewport.dispatch('pointermove', rest);
      advance(500);
      assert.equal(card.hidden, false);
      assert.ok(!card.innerHTML.includes('Your movement this turn'));
      if (dismissal === 'escape') await doc.dispatch('keydown', {key: 'Escape'});
      else await doc.dispatch('pointerdown', {target: doc.body, clientX: 20, clientY: 20});
      assert.equal(card.hidden, true);
      advance(1000);
      board.setTokens([fighter({hp: 7})]);
      assert.equal(card.hidden, true, 'no timer or refresh can undo explicit dismissal');
      await token.dispatch('pointerenter');
      await doc.dispatch('pointermove', rest);
      await board.viewport.dispatch('pointermove', rest);
      advance(900);
      assert.equal(card.hidden, false, 'a fresh hover can open again');
      assert.ok(card.innerHTML.includes('Your movement this turn'));
      await doc.dispatch('keydown', {key: 'Escape'});
    });
  });
}

test('the board keeps its movement summary when it replaces a delegated card', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    board.setMovementExplanation({summary: {actor_id: 'a', effective_speed_ft: 30,
      movement_remaining_ft: 20, reasons: []}, destinations: {}});
    const token = tokenNode(board), card = cardNode();
    token.getBoundingClientRect = () => ({left: 192, top: 192, right: 256, bottom: 256});
    card.getBoundingClientRect = () => ({left: 400, top: 200, right: 560, bottom: 400});

    const action = doc.createElement('button');
    action.setAttribute('data-tip', 'Spend 1 Stamina to move 5 feet.');
    doc.body.appendChild(action);
    const actionCard = createHoverCard({doc, win: globalThis.window});
    bindTipTargets(actionCard, doc);
    await doc.dispatch('pointerover', {target: action});
    advance(500);
    assert.match(card.textContent, /Spend 1 Stamina/, 'the delegated card owns the shared popup first');

    const rest = {target: token, clientX: 224, clientY: 224, buttons: 0};
    await token.dispatch('pointerenter');
    await doc.dispatch('pointermove', rest);
    await board.viewport.dispatch('pointermove', rest);
    advance(500);
    assert.equal(card.hidden, false);
    assert.ok(card.classList.contains('tt-token-card'));
    assert.match(card.innerHTML, /Kael/, 'the creature card replaces the delegated popup at 500 ms');
    assert.ok(!card.innerHTML.includes('Your movement this turn'));
    advance(399);
    assert.ok(!card.innerHTML.includes('Your movement this turn'));
    advance(1);
    assert.ok(card.innerHTML.includes('Your movement this turn'),
      'the pending movement summary follows at 900 ms without another pointermove');
    await doc.dispatch('keydown', {key: 'Escape'});
  });
});

test('token hover opens after 500 ms and leaving sooner cancels it', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    const token = tokenNode(board), card = cardNode();
    await token.dispatch('pointerenter');
    advance(499);
    assert.equal(card.hidden, true, 'the token card stays closed before the delay');
    await token.dispatch('pointerleave');
    advance(1);
    assert.equal(card.hidden, true, 'leaving the token cancels its pending card');
    await token.dispatch('pointerenter');
    advance(500);
    assert.equal(card.hidden, false, 'a sustained hover opens the token card');
  });
});

test('Escape on a delegated card cancels a pending token card from the board', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    const token = tokenNode(board), card = cardNode();
    token.getBoundingClientRect = () => ({left: 192, top: 192, right: 256, bottom: 256});
    const action = doc.createElement('button');
    action.setAttribute('data-tip', 'Spend 1 Stamina to move 5 feet.');
    doc.body.appendChild(action);
    const actionCard = createHoverCard({doc, win: globalThis.window});
    bindTipTargets(actionCard, doc);

    await doc.dispatch('pointerover', {target: action});
    advance(500);
    assert.equal(card.hidden, false, 'the delegated action card is visible');
    assert.match(card.textContent, /Spend 1 Stamina/);

    await token.dispatch('pointerenter');
    await doc.dispatch('keydown', {key: 'Escape'});
    assert.equal(card.hidden, true, 'Escape dismisses the action card');
    advance(500);
    assert.equal(card.hidden, true, 'the pending token card stays dismissed');
  });
});

test('keyboard focus supersedes a pending hover on another token', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter(), fighter({id: 'b', name: 'Other'})]);
    const [first, second] = board.element.querySelectorAll('.tt-token');
    const card = cardNode();
    await first.dispatch('pointerenter');
    await second.dispatch('focus');
    assert.match(card.innerHTML, /Other/, 'keyboard focus opens the focused token immediately');
    advance(500);
    assert.match(card.innerHTML, /Other/, 'the earlier pointer timer cannot replace the focused token card');
  });
});

test('removing a token invalidates its pending hover open', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    const token = tokenNode(board), card = cardNode();
    await token.dispatch('pointerenter');
    board.setTokens([]);
    advance(500);
    assert.equal(card.hidden, true, 'a removed token cannot open its stale card after the delay');
    assert.equal(card.getAttribute('aria-describedby'), null);
  });
});

test('movement summaries are scheduled through the real token hover bridge', async () => {
  const {runMovementHover} = await import('./movement_tooltip_hover.mjs');
  const reason = {message: 'Difficult terrain costs extra movement.'};
  await runMovementHover({summary: {actor_id: 'a', effective_speed_ft: 30, movement_remaining_ft: 20, reasons: [reason]},
    destinations: {'4,4': {available: false, explained_refusal: true, reasons: [reason]}}});
});

test('token refresh preserves scroll, unchanged DOM, selection and the movement summary', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    const data = fighter({conditions: Array.from({length: 20}, (_, i) => ({name: `Effect ${i}`, text: 'Long rules text.'}))});
    const list = [data, fighter({id: 'b', name: 'Other'})];
    board.setTokens(list);
    await tokenNode(board).dispatch('pointerenter');
    advance(500);
    const card = cardNode();
    card.scrollTop = 175;
    const originalChild = card.firstChild;
    let selected = true;
    globalThis.window.getSelection = () => ({isCollapsed: !selected, rangeCount: selected ? 1 : 0,
      getRangeAt: () => ({intersectsNode: node => node === card})});
    board.setTokens([data, fighter({id: 'b', name: 'Other', hp: 3})]);
    assert.equal(card.scrollTop, 175);
    assert.equal(card.firstChild, originalChild, 'unchanged visible content retains its actual nodes');
    board.setTokens([{...data, hp: 7}, list[1]]);
    assert.equal(card.firstChild, originalChild, 'selected text is retained even when its token changes');
    assert.match(card.innerHTML, /12 \/ 12 HP/, 'replacement waits until selection is released');
    board.setTokens([{...data, hp: 5}, list[1]]);
    selected = false;
    await doc.dispatch('selectionchange');
    assert.match(card.innerHTML, /5 \/ 12 HP/, 'the latest deferred update is applied');
    assert.equal(card.scrollTop, 175, 'changed content keeps the reading position');
    assert.equal(card.hidden, false);
    // A token update arriving between pointerdown and the browser creating a Range must not spoil the drag.
    card.getBoundingClientRect = () => ({left: 100, top: 100, right: 300, bottom: 300});
    const beforePress = card.firstChild;
    await doc.dispatch('pointerdown', {clientX: 150, clientY: 150});
    board.setTokens([{...data, hp: 4}, list[1]]);
    await doc.dispatch('selectionchange'); // a collapsed selection while the press is still held
    assert.equal(card.firstChild, beforePress);
    await doc.dispatch('pointerup');
    assert.match(card.innerHTML, /4 \/ 12 HP/, 'a press without selection flushes the pending update on release');
    await doc.dispatch('keydown', {key: 'Escape'});
    board.setTokens(list);
    assert.equal(card.hidden, true, 'deferred updates cannot resurrect a dismissed card');
  });
});

test('focused tokens and delegated controls stay open through pointer press, blur and text selection', async () => {
  for (const kind of ['token', 'action', 'resource']) {
    const board = mountBoard();
    let trigger, card;
    if (kind === 'token') {
      board.setTokens([fighter()]); trigger = tokenNode(board);
      await trigger.dispatch('focus'); card = cardNode();
    } else {
      trigger = doc.createElement(kind === 'action' ? 'button' : 'div');
      trigger.setAttribute('data-tip', 'Spend 1 Stamina to move 5 feet.');
      doc.body.appendChild(trigger);
      const pageCard = createHoverCard({doc, win: globalThis.window});
      bindTipTargets(pageCard, doc);
      await doc.dispatch('focusin', {target: trigger}); card = pageCard.node;
    }
    card.getBoundingClientRect = () => ({left: 100, top: 100, right: 300, bottom: 300});
    await doc.dispatch('pointermove', {clientX: 150, clientY: 150});
    await doc.dispatch('pointerdown', {target: card, clientX: 150, clientY: 150});
    if (kind === 'token') await trigger.dispatch('blur', {relatedTarget: null});
    else await doc.dispatch('focusout', {target: trigger, relatedTarget: null});
    assert.equal(card.hidden, false, `${kind}: clicking non-focusable text must survive blur before selection starts`);
    const selectedNode = card.firstChild || card;
    globalThis.window.getSelection = () => ({isCollapsed: false, rangeCount: 1,
      getRangeAt: () => ({intersectsNode: node => node === card})});
    await doc.dispatch('selectionchange');
    assert.equal(card.hidden, false); assert.equal(card.firstChild || card, selectedNode);
    await doc.dispatch('keydown', {key: 'Escape'});
    assert.equal(card.hidden, true, 'Escape still dismisses selected text');
  }
});

test('a token card the player dismissed stays dismissed when the tokens update', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    const token = tokenNode(board);
    assert.ok(token, 'the board built a token');

    await token.dispatch('pointerenter');            // hover the token: the card comes up describing it
    advance(500);
    const card = cardNode();
    assert.equal(card.hidden, false, 'hovering a token puts its card up');
    assert.match(card.innerHTML, /Kael/, 'and the card names the token');
    assert.equal(token.getAttribute('aria-describedby'), card.id, 'the token points at its own card');

    await doc.dispatch('keydown', {key: 'Escape'}); // the player says no
    assert.equal(card.hidden, true, 'Escape closes the card');

  // The engine sends token updates all the time (hit points, a condition, a move). None of them may bring back a
  // card the player has already dismissed.
    board.setTokens([fighter({hp: 7})]);
    assert.equal(card.hidden, true, 'a token update must not resurrect a card the player dismissed');
    board.setTokens([fighter({hp: 7, conditions: [{name: 'Blinded', text: 'You cannot see.'}]})]);
    assert.equal(card.hidden, true, 'nor may a condition update');

  // A fresh hover still works: dismissing one card is not closing the card off.
    await token.dispatch('pointerenter');
    advance(500);
    assert.equal(card.hidden, false, 'hovering the token again brings the card back');
    assert.match(card.innerHTML, /7 \/ 12 HP/, 'with the token\'s current hit points');
  });
});

test('a press somewhere else also dismisses a token card, and a token update does not undo it', async () => {
  const board = mountBoard();
  await withClock(async advance => {
    board.setTokens([fighter()]);
    await tokenNode(board).dispatch('pointerenter');
    advance(500);
    const card = cardNode();
    assert.equal(card.hidden, false, 'the card is up while the pointer is on the token');

    await doc.dispatch('pointerdown', {clientX: 5000, clientY: 5000});   // a press out in the empty map
    assert.equal(card.hidden, true, 'a press elsewhere dismisses the card');
    board.setTokens([fighter({hp: 4})]);
    assert.equal(card.hidden, true, 'and the next token update leaves it dismissed');
  });
});

test('the board and sheet share one popup and describe only the current trigger', async () => {
  // SOL211: shared content must preserve the original screen-reader guarantee and clear map ownership.
  const board = mountBoard();
  await withClock(async advance => {
    const pageCard = createHoverCard({doc, win: globalThis.window});
    board.setTokens([fighter()]);
    await tokenNode(board).dispatch('pointerenter');
    advance(500);
    const mapCard = cardNode();      // the board's card ELEMENT, as the page sees it
    assert.equal(pageCard.node, mapCard, 'one popup per document');
    assert.match(mapCard.innerHTML, /Kael/, 'the map initially supplies the token rules');

    const pill = doc.body.querySelector('#pill');
    pageCard.open({trigger: pill, anchor: {x: 30, y: 20}, build: node => { node.textContent = 'Blinded: you cannot see.'; }});
    assert.equal(pill.getAttribute('aria-describedby'), pageCard.node.id, 'the pill points at the page card');
    assert.equal(tokenNode(board).getAttribute('aria-describedby'), null, 'the replaced token description is removed');
    assert.equal(doc.body.querySelector(`#${pill.getAttribute('aria-describedby')}`), pageCard.node,
                 'the pill is described by the page card');
    board.setTokens([fighter({hp: 5})]);
    assert.equal(pageCard.node.textContent, 'Blinded: you cannot see.', 'map refresh does not reclaim the sheet popup');
    assert.equal(doc.body.querySelectorAll('.tt-hovercard').length, 1);
  });
});
