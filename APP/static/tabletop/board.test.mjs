// node APP/static/tabletop/board.test.mjs
//
// A move is drawn once, along the path the fight committed to (owner 2026-10-03: "When it loads the move action it
// moves forward then jumps back before loading then finally moving super fast to the location"). These tests play a
// move on the real board module and record every square the token is put on, so no browser is needed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {BLINK_FADE_MS, CELL, createBoard, moveFrames} from './board.js';

// The stub blanks out the clock, and it does so again on every installDOM, so it is installed once here. Node's own
// timers are put back so a walk really takes its time (in milliseconds, not the table's 110), and a frame is the
// next turn of that clock.
const realSetTimeout = globalThis.setTimeout;
installDOM('<body></body>');
globalThis.setTimeout = realSetTimeout;
// Frames are counted, because a requestAnimationFrame callback runs BEFORE the paint: one callback is not yet a
// drawn frame, and the difference between the two is exactly what lets a blink be lifted after its square is on the
// board instead of in the same frame as the square changing.
let frames = 0;
globalThis.requestAnimationFrame = callback => realSetTimeout(() => { frames += 1; callback(0); }, 0);

// The stylesheet the table really loads. The stub cannot paint, so the declarations that decide whether a teleport
// slides or fades are checked here, against the file that draws it. A selector may appear in several rules (a blink
// sets its opacity in one and its transition in another), so every rule for it is searched for the property.
const css = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
const cssDecl = (selector, property) => {
  const rules = css.matchAll(new RegExp(`${selector.replace(/\./g, '\\.')}(?:\\s*,[^{]*?)?\\s*\\{([^}]*)\\}`, 'g'));
  const wanted = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`);
  for (const rule of rules) {
    const found = wanted.exec(rule[1]);
    if (found) return found[1].trim();
  }
  assert.fail(`the stylesheet has no ${property} for ${selector}`);
};

// A time as the stylesheet writes it ("0s", ".18s", "180ms"), in the milliseconds the board waits.
const cssMs = value => {
  const match = /^([\d.]+)(ms|s)$/.exec(value);
  assert.ok(match, `"${value}" is not a time the board can wait`);
  return Math.round(Number(match[1]) * (match[2] === 's' ? 1000 : 1));
};

// Record every square the token is put on, in order, skipping a placement that does not move it. This is where the
// old code snapped back to where it started.
function record(node) {
  const walked = [];
  const style = node.style;
  let current = style.transform;
  Object.defineProperty(style, 'transform', {
    configurable: true,
    get: () => current,
    set: next => {
      const point = at(next), last = walked[walked.length - 1];
      if (!last || last.x !== point.x || last.y !== point.y) walked.push(point);
      current = next;
    },
  });
  return walked;
}

// Record a node's square changes and class changes as one story, each stamped with the frame the board was on when it
// happened and the classes the node wore at that moment. A blink that lifts itself in the same frame it changes square
// is what makes a teleport slide, and only the frame stamp can tell.
function timeline(node) {
  const events = [];
  const note = (what, point) => events.push({what, point, at: frames, ms: Date.now(), classes: [...node.classes]});
  const style = node.style;
  let current = style.transform;
  Object.defineProperty(style, 'transform', {
    configurable: true,
    get: () => current,
    set: next => { current = next; note('square', at(next)); },
  });
  const list = node.classList;
  for (const method of ['add', 'remove', 'toggle']) {
    const original = list[method].bind(list);
    list[method] = (...args) => { const result = original(...args); note(`${method} ${args[0]}`); return result; };
  }
  return events;
}

// Record the class changes on a token, so a blink can be told from a slide.
function recordClasses(node) {
  const states = [];
  const list = node.classList;
  for (const method of ['add', 'remove', 'toggle']) {
    const original = list[method].bind(list);
    list[method] = (...args) => {
      const result = original(...args);
      states.push([...node.classes]);
      return result;
    };
  }
  return states;
}

function at(transform) {
  const match = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(transform || '');
  return match ? {x: Math.round(Number(match[1]) / CELL), y: Math.round(Number(match[2]) / CELL)} : null;
}

function fighter(x, y, light = null) {
  return {id: 'a', x, y, name: 'Test Fighter', hp: 10, maxHp: 10, object: false, kind: null, image: '', label: '',
    light, hidden: false, current: false, selected: false, targetable: false, down: false, unseen: false,
    yours: true, item: false, conditions: [], color: '#ffffff', size: 1, height: 1, scale: 1, badge: ''};
}

// A board of its own per test, so the glow of one test is never mistaken for another's.
function table({light = null} = {}) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const board = createBoard(host);
  board.setTokens([fighter(1, 1, light)]);
  return {board, node: board.tokenNode('a'), glow: light ? host.querySelector('.tt-light') : null};
}

const delay = ms => new Promise(resolve => realSetTimeout(resolve, ms));

test('a committed move is walked once and left on the square the fight committed to', async () => {
  const {board, node} = table();
  const walked = record(node);

  await board.animateMove('a', [{x: 1, y: 1}, {x: 2, y: 1}, {x: 3, y: 1}, {x: 4, y: 1}], {stepMs: 1});

  assert.deepEqual(walked, [{x: 2, y: 1}, {x: 3, y: 1}, {x: 4, y: 1}], 'walks forward one square at a time');
  assert.equal(at(node.style.transform).x, 4, 'and stops on the committed square');
  assert.ok(!walked.some(point => point.x === 1), 'never slides back to where it started');
});

test('the state that arrives after a move does not move or replay the token', async () => {
  const {board, node} = table();
  const walked = record(node);
  await board.animateMove('a', [{x: 1, y: 1}, {x: 2, y: 1}, {x: 3, y: 1}, {x: 4, y: 1}], {stepMs: 1});
  const landed = node.style.transform;

  // The fight's own state reaches the table after the walk (an act re-reads it), asking for the square the move
  // already ended on. Nothing is left to animate, so the token must not shift at all.
  board.setTokens([fighter(4, 1)]);

  assert.equal(node.style.transform, landed, 'the arriving state does not slide the token across the map');
  assert.deepEqual(walked.slice(-1), [{x: 4, y: 1}], 'and adds no second move of its own');
});

test('a teleport blinks to the committed square instead of sliding there', async () => {
  const {board, node} = table();
  const walked = record(node);
  const states = recordClasses(node);

  await board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 1, teleport: true});

  assert.deepEqual(walked, [{x: 9, y: 9}], 'one blink onto the committed square, no walk between the squares');
  assert.ok(states.some(names => names.includes('is-blinking')), 'it blinks');
  assert.ok(!node.classList.contains('is-blinking'), 'and the blink is finished when it lands');

  const landed = node.style.transform;
  board.setTokens([fighter(9, 9)]);
  assert.equal(node.style.transform, landed, 'the arriving state does not replay it either');
});

test('a teleport waits two frame callbacks after relocation before lifting the blink', async () => {
  const {board, node} = table();
  const events = timeline(node);

  await board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 1, teleport: true});

  const landed = events.find(event => event.what === 'square' && event.point.x === 9);
  assert.ok(landed, 'it reappears on the committed square');
  assert.ok(landed.classes.includes('is-blinking'), 'while the is-blinking transform 0s rule is still on it');
  const lifted = events.slice(events.indexOf(landed) + 1).find(event => event.what === 'remove is-blinking');
  assert.ok(lifted, 'the blink is lifted afterwards, so the token fades back in');
  // Lifting the blink hands the transform back to the ordinary 0.18s slide. If that happens in the same frame the
  // square changed, or the frame before it has been painted, the browser animates the token across the map.
  assert.ok(lifted.at - landed.at >= 2,
    `two frame callbacks precede lifting the blink (got ${lifted.at - landed.at}, needs 2; stub does not paint)`);
});

test('a teleport waits the stylesheet fade interval before relocation', async () => {
  // The stylesheet and the board's wait are one rule: if the stylesheet fades for longer than the board waits, the
  // creature is still half visible when it jumps, and the crossing squares are on screen.
  const fade = cssDecl('.tt-token.is-blinking', 'transition');
  assert.match(fade, /transform 0s/, 'a blinking token does not transition its transform');
  const opacity = /\bopacity\s+([\d.]+m?s)/.exec(fade);
  assert.ok(opacity, 'a blinking token fades its opacity in');
  assert.equal(cssMs(opacity[1]), BLINK_FADE_MS,
    'the board waits exactly as long as the fade the stylesheet draws');

  const {board, node} = table();
  const events = timeline(node);
  await board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 1, teleport: true});

  const on = events.find(event => event.what === 'add is-blinking');
  const landed = events.find(event => event.what === 'square' && event.point.x === 9);
  assert.ok(landed.ms - on.ms >= BLINK_FADE_MS - 5,
    `relocation waits the fade interval (waited ${landed.ms - on.ms}ms of ${BLINK_FADE_MS}ms; stub does not paint)`);
  // A quick AI or replayed teleport used to wait only 60ms, so it reappeared while it was still visible.
  assert.equal(moveFrames([{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 60, teleport: true})[0].delayMs, BLINK_FADE_MS,
    'a quick teleport waits for the fade too, instead of 60ms');
});

test('the glow a creature carries blinks with it, instead of sliding and breathing through the blink', async () => {
  const {board, node, glow} = table({light: {radius_ft: 20, color: '#ffd28a', level: 'bright'}});
  assert.ok(glow, 'the torch has a glow drawn on the board');
  const lit = timeline(glow);
  const token = timeline(node);

  await board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 1, teleport: true});

  const litSquares = lit.filter(event => event.what === 'square');
  assert.equal(litSquares.length, 2, 'the glow follows the creature to the committed square and nowhere else');
  assert.ok(litSquares[0].classes.includes('is-blinking'), 'and it changes square while the blink is on it');
  assert.ok(token.find(event => event.what === 'add is-blinking' && event.classes.includes('is-blinking')),
    'the creature blinks at the same time as its glow');
  assert.ok(!glow.classList.contains('is-blinking'), 'and the glow is back when the blink is over');

  // The stub cannot paint, so the declarations that stop the glow from sliding or breathing through the blink are
  // checked against the stylesheet that draws it. A torch's glow is otherwise lit and slides across every square it
  // passes, while the creature carrying it blinks.
  const lightFade = cssDecl('.tt-light.is-blinking', 'transition');
  assert.match(lightFade, /transform 0s/, 'a blinking glow does not transition its transform');
  assert.match(cssDecl('.tt-light.is-blinking', 'animation'), /none/,
    'and its breathing animation is switched off, because an animation outranks the plain opacity: 0 blink rule');
});

test('a move that takes over mid-blink is what is left on the board', async () => {
  const {board, node} = table();

  // The fixed blink uses BLINK_FADE_MS; the old code used stepMs. Keep both longer than the takeover delay so this
  // also detects the old behavior, and make the replacement walk finish before either fade would finish.
  const blink = board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 120, teleport: true});
  await delay(20);
  const walk = board.animateMove('a', [{x: 9, y: 9}, {x: 10, y: 9}, {x: 11, y: 9}], {stepMs: 1});
  assert.ok(!node.classList.contains('is-blinking'), 'the replacement walk is visible immediately, before the old fade wakes');
  await Promise.all([blink, walk]);

  // The superseded blink used to carry on putting the creature back on the square it was leaving, once its fade ran
  // out, and left it there after the walk had already finished.
  assert.equal(at(node.style.transform).x, 11, 'the walk that replaced the blink is what the player is left looking at');
  assert.ok(!node.classList.contains('is-blinking'), 'and the creature is not left hidden by the blink it replaced');
  assert.ok(!node.classList.contains('is-moving'), 'nor left marked as moving');
});

test('a blink replaced by a later blink leaves the later square on the board', async () => {
  const {board, node} = table();

  const first = board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {stepMs: 120, teleport: true});
  await delay(20);
  const second = board.animateMove('a', [{x: 1, y: 1}, {x: 2, y: 2}], {stepMs: 20, teleport: true});
  await Promise.all([first, second]);

  assert.equal(at(node.style.transform).x, 2, 'the blink that replaced it wins, and the obsolete square is never put back');
  assert.ok(!node.classList.contains('is-blinking'), 'the blink that replaced it is the one that is lifted');
});

test('a replacement blink owns visibility when it takes over during either relocation frame', async () => {
  const clock = globalThis.requestAnimationFrame;
  try {
    for (const takeoverFrame of [1, 2]) {
      const {board, node, glow} = table({light: {radius_ft: 20, color: '#ffd28a', level: 'bright'}});
      const pending = [];
      globalThis.requestAnimationFrame = callback => { pending.push(callback); };
      const first = board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {teleport: true});
      while (!pending.length) await delay(5);
      if (takeoverFrame === 2) {
        pending.shift()(0);
        await Promise.resolve();
        assert.equal(pending.length, 1);
      }
      const second = board.animateMove('a', [{x: 9, y: 9}, {x: 2, y: 2}], {teleport: true});
      const changes = timeline(node);
      pending.shift()(0);
      await first;
      const obsoleteChanges = [...changes];
      const tokenStillBlinking = node.classList.contains('is-blinking');
      const lightStillBlinking = glow.classList.contains('is-blinking');
      while (!pending.length) await delay(5);
      pending.shift()(0);
      await Promise.resolve();
      pending.shift()(0);
      await second;
      assert.deepEqual(obsoleteChanges, [], 'the obsolete continuation makes no token mutation');
      assert.ok(tokenStillBlinking, 'the newer token blink stays on');
      assert.ok(lightStillBlinking, 'the newer light blink stays on');
      assert.equal(at(node.style.transform).x, 2);
      assert.ok(!node.classList.contains('is-blinking'));
    }
  } finally {
    globalThis.requestAnimationFrame = clock;
  }
});

test('suspended teleport frames finish on visibility changes or a bounded fallback and release resources', async () => {
  const original = {
    request: globalThis.requestAnimationFrame, cancel: globalThis.cancelAnimationFrame,
    add: document.addEventListener, remove: document.removeEventListener,
    hidden: Object.getOwnPropertyDescriptor(document, 'hidden'),
  };
  try {
    // Hide before relocation, during either frame wait, or leave a visible tab with all callbacks withheld.
    for (const hideAt of [0, 1, 2, null]) {
      globalThis.requestAnimationFrame = original.request;
      const {board, node, glow} = table({light: {radius_ft: 20, color: '#ffd28a', level: 'bright'}});
      await delay(10); // finish the light's unrelated entry frames before withholding relocation frames
      document.hidden = hideAt === 0;
      const callbacks = [], activeFrames = new Set(), listeners = new Set();
      globalThis.requestAnimationFrame = callback => {
        callbacks.push(callback);
        activeFrames.add(callbacks.length);
        return callbacks.length;
      };
      globalThis.cancelAnimationFrame = id => activeFrames.delete(id);
      document.addEventListener = (type, callback) => {
        assert.equal(type, 'visibilitychange');
        listeners.add(callback);
      };
      document.removeEventListener = (type, callback) => {
        assert.equal(type, 'visibilitychange');
        listeners.delete(callback);
      };
      const walked = record(node);
      const flushed = [];
      for (const member of [node, glow]) Object.defineProperty(member, 'offsetWidth', {
        configurable: true,
        get: () => { flushed.push({member, transform: member.style.transform, blinking: member.classList.contains('is-blinking')}); return 64; },
      });
      const moving = board.animateMove('a', [{x: 1, y: 1}, {x: 9, y: 9}], {teleport: true});
      const check = async () => {
        if (hideAt === 1 || hideAt === 2) {
          const deadline = Date.now() + 600;
          while (!callbacks.length && Date.now() < deadline) await delay(2);
          assert.equal(callbacks.length, 1, 'the first relocation frame is waiting');
          if (hideAt === 2) {
            callbacks[0](0);
            await Promise.resolve();
            assert.equal(callbacks.length, 2, 'the second relocation frame is waiting');
          }
          document.hidden = true;
          for (const listener of [...listeners]) listener();
          // Resolve through microtasks alone: a visibility event must release play without waiting for the timer.
          for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
          assert.ok(!node.classList.contains('is-moving'), 'hiding the tab releases animation immediately');
        }
        await moving;
      };
      let deadlineTimer;
      try {
        await Promise.race([check(), new Promise((_, reject) => {
          deadlineTimer = realSetTimeout(() => reject(new Error(`teleport stalled with hideAt=${hideAt}`)), 1000);
        })]);
      } finally { clearTimeout(deadlineTimer); }
      assert.deepEqual(walked, [{x: 9, y: 9}], 'the committed action is placed once');
      for (const member of [node, glow]) {
        assert.ok(!member.classList.contains('is-blinking'));
        assert.equal(member.style.transitionDuration, '');
        assert.ok(flushed.some(row => row.member === member && row.transform === member.style.transform && row.blinking),
          'destination styles are committed with the blink still on, even without a painted frame');
      }
      assert.ok(!node.classList.contains('is-moving'));
      assert.equal(listeners.size, 0, 'visibility listeners are removed');
      assert.equal(activeFrames.size, 0, 'pending frame requests are cancelled');
      const landed = node.style.transform;
      for (const callback of callbacks) callback(0); // cancelled callbacks must be harmless even if delivered late
      await Promise.resolve();
      assert.equal(node.style.transform, landed);
      board.setTokens([fighter(9, 9, {radius_ft: 20, color: '#ffd28a', level: 'bright'})]);
      assert.deepEqual(walked, [{x: 9, y: 9}], 'arriving committed state does not replay the move');
      board.setTokens([fighter(10, 9)]);
      assert.equal(at(node.style.transform).x, 10, 'animation ownership is released for later state updates');
    }
  } finally {
    globalThis.requestAnimationFrame = original.request;
    globalThis.cancelAnimationFrame = original.cancel;
    document.addEventListener = original.add;
    document.removeEventListener = original.remove;
    if (original.hidden) Object.defineProperty(document, 'hidden', original.hidden);
    else delete document.hidden;
  }
});

test('a clicked move waits on the token without moving it', () => {
  const {board, node} = table();
  const walked = record(node);
  const before = node.style.transform;

  board.setHighlights({pending: {actorId: 'a', path: [{x: 1, y: 1}, {x: 2, y: 1}], destination: {x: 2, y: 1}}});

  assert.deepEqual(walked, [], 'the token is not moved ahead of the fight');
  assert.equal(node.style.transform, before);
  assert.ok(node.classList.contains('is-pending'), 'it is marked as on its way instead');

  board.setHighlights({moves: [{x: 2, y: 1}]});
  assert.ok(!node.classList.contains('is-pending'), 'the mark clears once the fight answers');
});

test('moveFrames is the one rule for how a move is played', () => {
  const path = [{x: 1, y: 1}, {x: 2, y: 1}, {x: 3, y: 1}];
  assert.deepEqual(moveFrames(path, {stepMs: 110}), [
    {kind: 'step', delayMs: 110, to: {x: 2, y: 1}},
    {kind: 'step', delayMs: 110, to: {x: 3, y: 1}},
  ], 'a walk is the same steady pace for every square');
  assert.deepEqual(moveFrames(path, {stepMs: 60}), [
    {kind: 'step', delayMs: 60, to: {x: 2, y: 1}},
    {kind: 'step', delayMs: 60, to: {x: 3, y: 1}},
  ], 'an AI or replayed move keeps the same shape, only quicker');
  assert.deepEqual(moveFrames(path, {stepMs: 110, teleport: true}),
    [{kind: 'blink', delayMs: BLINK_FADE_MS, to: {x: 3, y: 1}}], 'a teleport is a single blink, which waits out the fade');
  assert.deepEqual(moveFrames([{x: 1, y: 1}], {stepMs: 110}), [], 'a move that never left its square has nothing to play');
  assert.deepEqual(moveFrames(null), []);
});
