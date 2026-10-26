// node --test APP/static/tabletop/hovercard.test.mjs
// The shared hover card (owner 2026-10-03): "there needs to be a way to hover over the tooltip to scroll down with
// middle mouse roll button. wait for it to pop up, then move over to the box and select things or scroll down etc."
//
// This is the regression for that report, at the level it showed. The card used to be painted with
// pointer-events: none and given no height limit, so a long zone card (Darkness and its four riders, then a Court)
// ran off the bottom of the screen and the pointer could never reach it: no scrolling, no selecting, and moving
// towards it closed it. The tests below pin each of those four things, on the real hovercard.js and the real CSS.
//
// No browser: a small DOM double stands in for layout (getBoundingClientRect from the placed left/top and the
// card's size) and a fake clock drives the grace period, so nothing here waits on a real timer.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {BRIDGE_GAP_PX, GRACE_MS, HOVER_OPEN_DELAY_MS, asRect, bindTipTargets, createHoverCard, inflate, inside, place} from './hovercard.js?v=tipdelay-1';

const css = name => readFileSync(new URL(name, import.meta.url), 'utf8');

// ----------------------------------------------------------------- the DOM double
class FakeElement {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.style = {};
    this.listeners = [];
    this.textContent = '';
    this.hidden = false;
    this.className = '';
    this.offsetWidth = 0;
    this.offsetHeight = 0;
    this.rect = null;                 // set directly to fake a trigger's place on screen
    this.contentHeight = 0;           // how tall the text INSIDE a scroll box is, so overflow can be modelled
    this._scrollTop = 0;
    const attributes = this.attributes;
    // The real DOM reflects dataset writes to data-* attributes, and closest("[data-tip]") reads the attribute.
    // Reflect both ways so a test can use the same `el.dataset.tip = ...` the sheet's h() helper uses.
    const data = {};
    this.dataset = new Proxy(data, {
      get: (store, key) => store[key],
      set: (store, key, value) => { store[key] = String(value); attributes[`data-${key.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)}`] = String(value); return true; },
      has: (store, key) => key in store,
    });
  }
  get offsetParent() { return this.parentNode; }
  // A real scroll box: it reports how tall its content is, and scrollTop only moves between the top and the bottom.
  // Modelling that is what lets a test say "the wheel scrolled the long text", not just "the wheel was cancelled".
  get clientHeight() { return this.offsetHeight; }
  get scrollHeight() { return Math.max(this.offsetHeight, this.contentHeight); }
  get scrollTop() { return this._scrollTop; }
  set scrollTop(value) {
    const room = Math.max(0, this.scrollHeight - this.clientHeight);
    this._scrollTop = Math.min(Math.max(0, Number(value) || 0), room);
  }
  getBoundingClientRect() {
    if (this.rect) return this.rect;
    const left = parseFloat(this.style.left) || 0;
    const top = parseFloat(this.style.top) || 0;
    return {left, top, right: left + this.offsetWidth, bottom: top + this.offsetHeight,
            width: this.offsetWidth, height: this.offsetHeight};
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
  }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  hasAttribute(name) { return name in this.attributes; }
  removeAttribute(name) { delete this.attributes[name]; }
  appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
  contains(other) {
    for (let node = other; node; node = node.parentNode) if (node === this) return true;
    return false;
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    for (const node of nodes) this.appendChild(node);
  }
  closest(selector) {
    for (let node = this; node; node = node.parentNode) {
      const tag = selector.replace(/^\[|\]$/g, '').split('=')[0].replace(/[\[\]]/g, '');
      if (node.hasAttribute(tag)) return node;
      if (node.tagName === selector.toUpperCase()) return node;
    }
    return null;
  }
  addEventListener(type, fn, options) {
    const capture = options === true || (options && typeof options === 'object' && Boolean(options.capture));
    this.listeners.push({type, fn, capture});
  }
  removeEventListener(type, fn, options) {
    const capture = options === true || (options && typeof options === 'object' && Boolean(options.capture));
    this.listeners = this.listeners.filter(row => !(row.type === type && row.fn === fn && row.capture === capture));
  }
  // Walk root -> target (capture) then target -> root, like the browser, so a document-level capture
  // listener registered by the card really does see an event aimed at the card.
  fire(type, detail = {}) {
    const path = [];
    for (let node = this; node; node = node.parentNode) path.unshift(node);
    const event = {type, target: this, defaultPrevented: false, propagationStopped: false,
                   preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.propagationStopped = true; },
                   ...detail};
    for (const node of path) {
      if (event.propagationStopped) break;
      for (const row of node.listeners.filter(r => r.type === type && r.capture)) row.fn.call(node, event);
    }
    for (const node of [...path].reverse()) {
      if (event.propagationStopped) break;
      for (const row of node.listeners.filter(r => r.type === type && !r.capture)) row.fn.call(node, event);
    }
    return event;
  }
}

function makeDoc() {
  const doc = new FakeElement('#document');
  doc.body = new FakeElement('body');
  doc.documentElement = doc;
  doc.createElement = tag => new FakeElement(tag);
  doc.body.parentNode = doc;
  doc.appendChild(doc.body);
  return doc;
}

function fakeClock() {
  let now = 0;
  let nextId = 1;
  const jobs = new Map();
  return {
    setTimer(fn, ms) { const id = nextId++; jobs.set(id, {fn, at: now + (ms || 0)}); return id; },
    clearTimer(id) { jobs.delete(id); },
    advance(ms) { now += ms; for (const [id, job] of [...jobs]) if (job.at <= now) { jobs.delete(id); job.fn(); } },
    get pending() { return jobs.size; },
  };
}

// A card that is 240x300 sitting where the code put it, on a 1200x800 window.
function harness({width = 240, height = 300} = {}) {
  const doc = makeDoc();
  const clock = fakeClock();
  const win = {innerWidth: 1200, innerHeight: 800};
  const card = createHoverCard({doc, win, setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  card.node.offsetWidth = width;
  card.node.offsetHeight = height;
  return {doc, clock, win, card};
}

// ----------------------------------------------------------------- 1. the CSS contract
test('the card is a scroll box that takes the pointer, and neither card blocks or clips it', () => {
  const shared = css('./hovercard.css');
  // These four are the whole bug. Without them the card cannot be scrolled, cannot be reached and runs off screen.
  assert.match(shared, /\.tt-hovercard\s*\{[^}]*pointer-events:\s*auto/, 'the card must take the pointer');
  assert.match(shared, /\.tt-hovercard\s*\{[^}]*max-height:\s*calc\(100vh/, 'a long card must be capped, not run off screen');
  assert.match(shared, /\.tt-hovercard\s*\{[^}]*overflow-y:\s*auto/, 'the cap must be scrollable');
  assert.match(shared, /\.tt-hovercard\s*\{[^}]*overscroll-behavior:\s*contain/, 'scrolling the card must not carry on into the map');
  assert.match(shared, /\.tt-hovercard\s*\{[^}]*user-select:\s*text/, 'the owner must be able to select and copy the text');
  assert.match(shared, /-webkit-scrollbar-thumb/, 'an overflowing card must show a scrollbar');

  // The two looks may not take the pointer away again, nor clip what the shared card now scrolls.
  const table = css('./tabletop.css');
  assert.doesNotMatch(table, /\.tt-zone-tip\s*\{[^}]*pointer-events:\s*none/, '.tt-zone-tip must not be pointer-events: none');
  assert.doesNotMatch(table, /\.tt-token-card\s*\{[^}]*pointer-events:\s*none/, '.tt-token-card must not be pointer-events: none');
  assert.doesNotMatch(table, /\.tt-token-card\s*\{[^}]*overflow:\s*hidden/, 'the token card must not clip its own text');
});

test('both pages load the one card stylesheet, before their own look', () => {
  // Compare with the page's OWN stylesheet by name: matching a cache key ('.css?v=r24"') broke whenever a key changed.
  for (const [page, own] of [['./tabletop.html', 'tabletop.css'], ['./sheet.html', 'sheet.css']]) {
    const html = css(page);
    const shared = html.indexOf('hovercard.css');
    assert.ok(shared > 0, `${page} must load the shared hover card stylesheet`);
    assert.ok(html.indexOf(`/${own}`) > 0, `${page} loads its own look`);
    assert.ok(shared < html.indexOf(`/${own}`), `${page} loads the shared card before its own look`);
  }
});

test('the card is interactive on its own, without relying on the stylesheet being loaded', () => {
  // Five opt-in browser harnesses mount the board with tabletop.css only, and a page that has not picked up a new
  // stylesheet yet must not silently get a card it cannot scroll. The behaviour is set on the element itself; the
  // stylesheet only adds the look and the scrollbar.
  const {card, win} = harness();
  card.open({build: node => { node.textContent = 'Darkness'; }});
  const s = card.node.style;
  assert.equal(s.position, 'fixed', 'the card is positioned against the window, so left/top place it');
  assert.equal(s.pointerEvents, 'auto', 'the card takes the pointer');
  assert.equal(s.overflowY, 'auto', 'the card scrolls its own content');
  assert.equal(s.overscrollBehavior, 'contain', 'scrolling stops at the end instead of zooming the map');
  assert.equal(s.userSelect, 'text', 'the text can be selected');
  // The cap is the same value the stylesheet gives with calc(100vh - 16px).
  assert.equal(s.maxHeight, `${win.innerHeight - 16}px`, 'a long card is capped to the window, not run off it');
});

test('the behaviour set in JS and the behaviour in the stylesheet agree', () => {
  // The two are deliberately the same numbers. If one changes, this fails rather than the card quietly differing
  // between a page with the stylesheet and a harness without it.
  const shared = css('./hovercard.css');
  const block = shared.match(/\.tt-hovercard\s*\{[^}]*\}/)[0];
  for (const [property, jsValue, cssValue] of [
    ['position', 'fixed', /position:\s*fixed/],
    ['z-index', '60', /z-index:\s*60/],
    ['overflow-y', 'auto', /overflow-y:\s*auto/],
    ['overscroll-behavior', 'contain', /overscroll-behavior:\s*contain/],
    ['user-select', 'text', /user-select:\s*text/],
  ]) {
    assert.match(block, cssValue, `hovercard.css must still set ${property} (JS guarantees ${jsValue})`);
  }
  assert.match(block, /max-height:\s*calc\(100vh - 16px\)/, 'hovercard.css must still cap the height the same way');
});

// ----------------------------------------------------------------- 2. placement
test('place() puts the card beside the trigger, never on it, and never off the window', () => {
  const view = {width: 1200, height: 800};
  const size = {width: 240, height: 300};
  // Trigger in the middle of the screen: the card must not overlap it in any of the sides it tries.
  const avoid = {left: 500, top: 400, right: 580, bottom: 440};
  const spot = place({anchor: {x: 540, y: 440}, avoid, size, view});
  const box = {left: spot.left, top: spot.top, right: spot.left + 240, bottom: spot.top + 300};
  const covers = box.left < avoid.right && box.right > avoid.left && box.top < avoid.bottom && box.bottom > avoid.top;
  assert.equal(covers, false, 'the card must not cover the thing the pointer is on');
  assert.ok(box.left >= 8 && box.top >= 8 && box.right <= 1200 - 8 && box.bottom <= 800 - 8, 'the card stays on screen');

  // A trigger hard against the bottom-right: the card is flipped up and left rather than pushed off screen.
  const corner = {left: 1150, top: 760, right: 1190, bottom: 795};
  const flipped = place({anchor: {x: 1170, y: 760}, avoid: corner, size, view});
  assert.ok(flipped.top + 300 <= 800 - 8, 'a card near the bottom fits on screen');
  assert.ok(flipped.left >= 8, 'a card near the right edge fits on screen');
});

// ----------------------------------------------------------------- 3. the grace period
test('the card survives the pointer leaving the trigger for the grace period, then closes', () => {
  const {clock, card} = harness();
  const trigger = new FakeElement('button');
  trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
  card.open({trigger, anchor: {x: 140, y: 100}, build: node => { node.textContent = 'Darkness'; }});
  assert.equal(card.isOpen, true, 'the card is up while the pointer is on the trigger');

  trigger.fire('pointerleave', {clientX: 90, clientY: 90});   // stepping off towards the card
  assert.equal(card.isOpen, true, 'leaving the trigger does not close the card straight away');
  clock.advance(GRACE_MS - 1);
  assert.equal(card.isOpen, true, 'still up just before the grace period ends');
  clock.advance(1);
  assert.equal(card.isOpen, false, 'the card closes once the pointer has been gone for the grace period');
});

test('the card keeps its listeners for its life and lets go of them when it closes', () => {
  const {card} = harness();
  assert.equal(card.node.listeners.length, 0, 'a fresh card has no listeners attached');
  card.open({build: node => { node.textContent = 'Darkness'; }});
  assert.ok(card.node.listeners.length > 0, 'opening the card attaches its listeners');
  card.close();
  assert.equal(card.node.listeners.length, 0, 'closing the card removes every listener it added');
});

// ----------------------------------------------------------------- 4. the hover bridge
test('the gap between the trigger and the card is part of the card, so crossing it keeps the card up', () => {
  const {card, clock} = harness();
  const trigger = new FakeElement('button');
  trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
  card.open({trigger, anchor: {x: 140, y: 100}, build: node => { node.textContent = 'Darkness'; }});
  const box = card.node.getBoundingClientRect();

  // The bridge is the card's box grown by BRIDGE_GAP_PX: a point in the empty gap between trigger and card, and a
  // point just outside the card but inside the gap, are both still "on the card".
  const inGap = {x: (180 + box.left) / 2, y: 100};
  const justOutside = {x: box.left + box.width / 2, y: box.top - Math.floor(BRIDGE_GAP_PX / 2)};
  assert.equal(card.ownsPointer(inGap), true, 'a point in the gap between trigger and card is still on the card');
  assert.equal(card.ownsPointer(justOutside), true, 'the bridge reaches past the card by BRIDGE_GAP_PX');
  assert.equal(card.ownsPointer({x: 700, y: 700}), false, 'a point far away is not on the card');

  // Moving into the gap must not arm a close at all, however long the pointer sits there.
  clock.advance(GRACE_MS * 10);
  assert.equal(card.isOpen, true, 'the card does not close while the pointer is on the bridge');
});

test('the map zone card includes its source square in the route to the popup', () => {
  // Owner UIREGRESS1: moving within the source square toward a right-hand popup
  // must not recreate it. Ordinary departure outside the corridor still closes.
  const {card} = harness();
  card.open({bridge: 'card', anchor: {x: 200, y: 200}, avoid: {left: 100, top: 200, right: 164, bottom: 264},
             build: node => { node.textContent = 'Darkness'; }});
  assert.equal(card.ownsPointer({x: 130, y: 230}), true, 'the source square is part of the bridge');
  assert.equal(card.ownsPointer({x: 700, y: 700}), false, 'unrelated ground is outside the bridge');
  const box = card.node.getBoundingClientRect();
  assert.equal(card.ownsPointer({x: box.left + 5, y: box.top + 5}), true, 'the card and its gap still count');
});

// ----------------------------------------------------------------- 5. the wheel
test('the wheel scrolls the long card itself, and never reaches the map underneath it', () => {
  const {card} = harness();
  card.node.contentHeight = 900;   // 900px of rules in a 300px card: there is something to scroll
  card.open({build: node => { node.textContent = 'Darkness'; }});
  // The map's wheel handler zooms; if the event escaped the card the map would zoom under the pointer.
  assert.equal(card.node.listeners.filter(r => r.type === 'wheel').length, 1, 'the card owns the wheel while it is open');

  // This is the owner's actual request: hover, wait, move onto the card, and roll the wheel down the text.
  card.node.fire('wheel', {deltaY: 120});
  assert.equal(card.node.scrollTop, 120, 'the wheel scrolls the card down by its own amount');
  card.node.fire('wheel', {deltaY: -60});
  assert.equal(card.node.scrollTop, 60, 'and back up again');
  // Reaching the end stops there instead of carrying on into the map (overscroll-behavior: contain).
  card.node.fire('wheel', {deltaY: 5000});
  assert.equal(card.node.scrollTop, 600, 'the card stops at the end of its own text, it does not run off');
  // The owner asked for the MIDDLE mouse wheel specifically; a wheel event carries the button that rolled it.
  card.node.scrollTop = 0;
  card.node.fire('wheel', {deltaY: 100, button: 1});
  assert.equal(card.node.scrollTop, 100, 'the middle mouse wheel scrolls the card too');
  // Firefox counts a notch in LINES rather than pixels, and a line is not a fraction of a pixel.
  card.node.scrollTop = 0;
  card.node.fire('wheel', {deltaY: 3, deltaMode: 1});
  assert.equal(card.node.scrollTop, 48, 'a wheel measured in lines moves the card by whole lines');

  const event = card.node.fire('wheel', {deltaY: 30});
  assert.equal(event.defaultPrevented, true, 'the wheel is consumed: the page must not scroll behind the card');
  assert.equal(event.propagationStopped, true, 'the wheel never reaches the map zoom handler');
});

test('a middle-button press on the card does not start the browser autoscroll', () => {
  // The card scrolls its own wheel, so the browser's middle-drag autoscroll (which would scroll the same box a
  // second way, or paste) is stopped here on purpose.
  const {card} = harness();
  card.open({build: node => { node.textContent = 'Darkness'; }});
  const event = card.node.fire('mousedown', {button: 1});
  assert.equal(event.defaultPrevented, true, 'middle-click autoscroll/paste is suppressed on the card');
});

// ----------------------------------------------------------------- 6. Escape
test('Escape closes the card', () => {
  const {doc, card} = harness();
  card.open({build: node => { node.textContent = 'Darkness'; }});
  assert.equal(card.isOpen, true);
  doc.fire('keydown', {key: 'Escape'});
  assert.equal(card.isOpen, false, 'Escape closes the card');
});

test('a press somewhere else closes the card, but a press on the card does not', () => {
  const {doc, card} = harness();
  card.open({build: node => { node.textContent = 'Darkness'; }});
  const box = card.node.getBoundingClientRect();
  doc.fire('pointerdown', {clientX: box.left + 10, clientY: box.top + 10});
  assert.equal(card.isOpen, true, 'pressing on the card is not a dismiss');
  doc.fire('pointerdown', {clientX: 900, clientY: 700});
  assert.equal(card.isOpen, false, 'pressing elsewhere dismisses the card');
});

// ----------------------------------------------------------------- 7. the seam, not copies
test('the map, the table and the sheet all take their hover card from the one shared module', () => {
  for (const [file, pattern] of [['./board.js', /import\s*\{[^}]*createHoverCard[^}]*\}\s*from\s*"\.\/hovercard\.js/],
                                 ['./tabletop.js', /import\s*\{[^}]*createHoverCard[^}]*\}\s*from\s*"\.\/hovercard\.js/],
                                 ['./sheet.js', /import\s*\{[^}]*createHoverCard[^}]*\}\s*from\s*"\.\/hovercard\.js/]]) {
    assert.match(css(file), pattern, `${file} must use the shared hover card`);
  }
  // No hand-rolled second card: the old board-only element is gone, and neither file builds its own tooltip box.
  const board = css('./board.js');
  assert.doesNotMatch(board, /el\("div",\s*"tt-zone-tip"/, 'the zone card is the shared element, not a new one');
  assert.doesNotMatch(board, /el\("div",\s*"tt-token-card"/, 'the token card is the shared element, not a new one');
});

test('every sheet row\'s hover text goes to the shared card, and the pill and button rows with it', () => {
  // sheet.js builds every row through h(); the one seam there is what sends title to the card.
  const sheet = css('./sheet.js');
  assert.match(sheet, /key === "title"\)\s*el\.dataset\.tip\s*=/, 'h() must send a row\'s title to the shared card');
  assert.doesNotMatch(sheet, /key === "title"\)\s*el\.setAttribute\("title"/, 'no row may fall back to a native tooltip');

  const table = css('./tabletop.js');
  assert.match(table, /data-tip="\$\{escapeHtml\(conditionText\(row\)\)\}"/, 'a condition pill uses the shared card');
  assert.doesNotMatch(table, /is-condition[^"]*"[^>]*title=/, 'a condition pill must not hang text off a native tooltip');
  assert.match(table, /button\.dataset\.tip = group\.description/, 'an action button uses the shared card');
});

// ----------------------------------------------------------------- 8. the binder
test('stat breakdown click and keyboard opt in to the same single hover card', () => {
  const doc = makeDoc();
  const clock = fakeClock();
  const card = createHoverCard({doc, win: {innerWidth: 1200, innerHeight: 800},
    setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  bindTipTargets(card, doc, {setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  const stat = doc.createElement('button');
  stat.dataset.tip = 'AC: 10 base + 2 Dexterity = 12';
  stat.rect = {left: 20, top: 30, right: 120, bottom: 54, width: 100, height: 24};
  doc.body.appendChild(stat);
  stat.fire('click');
  assert.equal(card.isOpen, false, 'existing rows do not acquire click behavior');
  stat.setAttribute('data-tip-click', '');
  stat.fire('click');
  assert.equal(card.node.textContent, stat.dataset.tip);
  card.close();
  stat.fire('keydown', {key: 'Enter'});
  assert.equal(card.isOpen, true);
  assert.equal(stat.getAttribute('title'), null);
});
test('a condition pill or sheet row opens the shared card, and points at it while it is open', () => {
  const doc = makeDoc();
  const clock = fakeClock();
  const card = createHoverCard({doc, win: {innerWidth: 1200, innerHeight: 800},
                               setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  bindTipTargets(card, doc, {delay: 0, setTimer: clock.setTimer, clearTimer: clock.clearTimer});

  const pill = doc.createElement('span');
  pill.dataset.tip = 'Blinded: you cannot see, and you automatically fail any check that needs sight.';
  pill.rect = {left: 20, top: 30, right: 120, bottom: 54, width: 100, height: 24};
  doc.body.appendChild(pill);

  pill.fire('pointerover', {});
  clock.advance(1);
  assert.equal(card.isOpen, true, 'hovering a pill opens the shared card');
  assert.equal(card.node.textContent, 'Blinded: you cannot see, and you automatically fail any check that needs sight.');
  assert.equal(pill.getAttribute('aria-describedby'), card.node.id,
               'while the card is up, the pill points at it, so a screen reader reads the same words');
  assert.equal(pill.getAttribute('title'), null, 'no native tooltip is left to double up with the card');

  card.close();
  assert.equal(pill.getAttribute('aria-describedby'), null, 'closing the card removes the pointer again');
});

test('pointer hover waits half a second, leaving cancels, and keyboard focus opens immediately', () => {
  const {doc, clock, card} = harness();
  bindTipTargets(card, doc, {setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  const row = doc.createElement('button');
  row.dataset.tip = 'A delayed hover card';
  doc.body.appendChild(row);

  row.fire('pointerover');
  clock.advance(HOVER_OPEN_DELAY_MS - 1);
  assert.equal(card.isOpen, false, 'pointer hover does not open before 500 ms');
  clock.advance(1);
  assert.equal(card.isOpen, true, 'pointer hover opens at 500 ms');
  card.close();

  row.fire('pointerover');
  row.fire('pointerout', {relatedTarget: doc.body});
  clock.advance(HOVER_OPEN_DELAY_MS);
  assert.equal(card.isOpen, false, 'leaving before the delay cancels the pending card');

  row.fire('focusin');
  assert.equal(card.isOpen, true, 'keyboard focus opens without the pointer delay');
});

test('Escape cancels a pending delegated open from another row', () => {
  const {doc, clock, card} = harness();
  bindTipTargets(card, doc, {setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  const rowA = doc.createElement('button');
  rowA.dataset.tip = 'Action A';
  const rowB = doc.createElement('button');
  rowB.dataset.tip = 'Action B';
  doc.body.appendChild(rowA);
  doc.body.appendChild(rowB);

  rowA.fire('focusin');
  assert.equal(card.trigger, rowA, 'A is open before the second row is hovered');
  rowB.fire('pointerover');
  assert.equal(clock.pending, 1, 'B has a delegated open waiting');
  doc.fire('keydown', {key: 'Escape'});
  assert.equal(card.isOpen, false, 'Escape dismisses A');
  clock.advance(HOVER_OPEN_DELAY_MS + 1);
  assert.equal(card.isOpen, false, 'the pending hover cannot reopen a card after dismissal');
});

test('a pill with no hover text opens nothing', () => {
  const doc = makeDoc();
  const clock = fakeClock();
  const card = createHoverCard({doc, win: {innerWidth: 1200, innerHeight: 800},
                               setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  bindTipTargets(card, doc, {delay: 0, setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  const bare = doc.createElement('span');
  bare.rect = {left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10};
  doc.body.appendChild(bare);
  bare.fire('pointerover', {});
  clock.advance(1);
  assert.equal(card.isOpen, false, 'nothing to say means no card');
});

// ----------------------------------------------------------------- 9. the helpers
for (const delay of [0, 30]) {
  for (const alreadyOpen of [false, true]) {
    test(`departing a pending row cancels its open (delay=${delay}, existing card=${alreadyOpen})`, () => {
      const {doc, clock, card} = harness();
      bindTipTargets(card, doc, {delay, setTimer: clock.setTimer, clearTimer: clock.clearTimer});
      const previous = doc.createElement('button');
      previous.dataset.tip = 'Previous action';
      doc.body.appendChild(previous);
      if (alreadyOpen) previous.fire('focusin');
      const row = doc.createElement('button');
      row.dataset.tip = 'Departed action';
      doc.body.appendChild(row);
      row.fire('pointerover');
      row.fire('pointerout', {relatedTarget: doc.body});
      assert.equal(clock.pending, 0, 'departure cancels the open even before this row is displayed');
      clock.advance(delay + 1);
      assert.equal(card.isOpen, alreadyOpen);
      assert.equal(card.trigger, alreadyOpen ? previous : null);
    });
  }
}

for (const change of ['remove', 'replace', 'move outside root', 'remove tip']) {
  test(`a render cannot open an obsolete pending row: ${change}`, () => {
    const {doc, clock, card} = harness();
    const root = doc.createElement('section');
    doc.body.appendChild(root);
    bindTipTargets(card, root, {setTimer: clock.setTimer, clearTimer: clock.clearTimer});
    const row = doc.createElement('button');
    row.dataset.tip = 'Old action';
    root.appendChild(row);
    row.fire('pointerover');
    if (change === 'remove tip') row.removeAttribute('data-tip');
    else {
      root.replaceChildren();
      if (change === 'move outside root') doc.body.appendChild(row);
      if (change === 'replace') {
        const replacement = doc.createElement('button');
        replacement.dataset.tip = 'Replacement action';
        root.appendChild(replacement);
      }
    }
    clock.advance(HOVER_OPEN_DELAY_MS + 1);
    assert.equal(clock.pending, 0, 'the delayed callback has run before checking the obsolete row');
    assert.equal(card.isOpen, false, 'no pointerout is needed to reject an obsolete row');
    assert.equal(row.getAttribute('aria-describedby'), null);
  });
}

test('moving between children preserves the pending row and its original open delay', () => {
  const {doc, clock, card} = harness();
  bindTipTargets(card, doc, {delay: 30, setTimer: clock.setTimer, clearTimer: clock.clearTimer});
  const row = doc.createElement('button');
  row.dataset.tip = 'Action with two child labels';
  doc.body.appendChild(row);
  const first = row.appendChild(doc.createElement('span'));
  const second = row.appendChild(doc.createElement('span'));
  first.fire('pointerover');
  clock.advance(20);
  first.fire('pointerout', {relatedTarget: second});
  second.fire('pointerover', {relatedTarget: first});
  clock.advance(10);
  assert.equal(card.trigger, row, 'child transitions neither cancel nor restart the delay');
});

for (const next of ['another row', 'empty row', 'current card', 'keyboard focus']) {
  test(`a pending row is superseded by ${next}`, () => {
    const {doc, clock, card} = harness();
    const {show} = bindTipTargets(card, doc, {delay: 0, setTimer: clock.setTimer, clearTimer: clock.clearTimer});
    const old = doc.createElement('button');
    old.dataset.tip = 'Obsolete action';
    doc.body.appendChild(old);
    const target = doc.createElement('button');
    target.dataset.tip = next === 'empty row' ? '' : 'Current action';
    doc.body.appendChild(target);
    if (next === 'current card') show(target);
    old.fire('pointerover');
    target.fire(next === 'keyboard focus' ? 'focusin' : 'pointerover');
    clock.advance(1);
    assert.equal(card.isOpen, next !== 'empty row');
    assert.equal(card.trigger, next === 'empty row' ? null : target);
  });
}

test('inflate and inside are the geometry the bridge is built from', () => {
  const box = {left: 10, top: 20, right: 30, bottom: 40};
  const grown = inflate(box, 5);
  assert.deepEqual([grown.left, grown.top, grown.right, grown.bottom], [5, 15, 35, 45]);
  assert.equal(inside({x: 35, y: 45}, grown), true, 'the edge counts as inside');
  assert.equal(inside({x: 36, y: 45}, grown), false, 'past the edge is outside');
  assert.equal(inside({x: 10, y: 20}, box), true);
  assert.equal(inside({x: 31, y: 20}, box), false);
  assert.equal(inside(null, box), false, 'no pointer is not on the card');
});

// ----------------------------------------------------------------- 10. reaching the card
// Owner, 2026-10-03: "wait for it to pop up, then move over to the box and select things or scroll down etc."
// The card used to be PLACED AGAIN every time the pointer reached it, so it walked out from under the pointer: a
// card opened at (154,114) moved to (174,134) as the pointer entered it at (160,120), and the pointer was outside
// again. A card you cannot keep your pointer on is a card you cannot scroll.
test('reaching the card does not move it: it is placed once, where it opened', () => {
  const {card, doc} = harness();
  const trigger = new FakeElement('button');
  trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
  card.open({trigger, anchor: {x: 140, y: 100}, avoid: {left: 100, top: 100, right: 180, bottom: 140},
             build: node => { node.textContent = 'Darkness'; }});
  const where = `${card.node.style.left},${card.node.style.top}`;
  const box = card.node.getBoundingClientRect();

  // The pointer walks off the trigger, across the gap, and onto the card. The document's capture handler sees every
  // one of those moves before the card's own handlers do, which is exactly how it used to re-place the card.
  for (const point of [{x: 160, y: 120},                                     // entering the card
                       {x: (180 + box.left) / 2, y: 120},                   // the gap between trigger and card
                       {x: box.left + 10, y: box.top + 10},                 // on the card
                       {x: box.left + box.width / 2, y: box.top + 40}]) {   // reading / scrolling it
    doc.fire('pointermove', {clientX: point.x, clientY: point.y});
    card.node.fire('pointerenter', {clientX: point.x, clientY: point.y});
    card.node.fire('pointermove', {clientX: point.x, clientY: point.y});
    assert.equal(`${card.node.style.left},${card.node.style.top}`, where,
                 `the card must not slide while the pointer travels to ${point.x},${point.y}`);
  }
  // And the pointer is still on the card it reached, which is the whole point of the owner's request.
  assert.equal(card.ownsPointer({x: box.left + box.width / 2, y: box.top + 40}), true,
               'the card is still under the pointer that reached it');
});

test('a map square card still follows the pointer between squares, but freezes once the pointer is on it', () => {
  // bridge: "card" (the map's zone card) is triggered by the pointer RESTING on a square, so moving to the next
  // square must move the card -- but not while the player is reading or scrolling the card itself.
  const {card} = harness();
  card.node.offsetHeight = 300;
  const open = (x, y) => card.open({bridge: 'card', anchor: {x, y}, avoid: {left: x - 32, top: y - 32, right: x + 32, bottom: y + 32},
                                    key: 'Darkness', build: node => { node.textContent = 'Darkness'; }});
  open(200, 200);
  const first = `${card.node.style.left},${card.node.style.top}`;
  open(600, 200);                     // the next square along: the same words, so the card is not rebuilt
  assert.notEqual(`${card.node.style.left},${card.node.style.top}`, first,
                  'a card for a square you moved to must move with you');
  const onCard = {x: parseFloat(card.node.style.left) + 5, y: parseFloat(card.node.style.top) + 5};
  const where = `${card.node.style.left},${card.node.style.top}`;
  open(onCard.x, onCard.y);           // the pointer is on the card: it must hold still
  assert.equal(`${card.node.style.left},${card.node.style.top}`, where, 'a card being read stays where it is');
});

// ----------------------------------------------------------------- 11. the bridge comes back
test('coming back onto the card cancels a close that was already armed', () => {
  // The card used to arm a close the moment the pointer left it and never take it back, so a player who stepped off
  // the trigger, found the gap, and stepped onto the card had the card shut in their face as they arrived.
  const {card, doc, clock} = harness();
  const trigger = new FakeElement('button');
  trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
  card.open({trigger, anchor: {x: 140, y: 100}, avoid: {left: 100, top: 100, right: 180, bottom: 140},
             build: node => { node.textContent = 'Darkness'; }});
  const box = card.node.getBoundingClientRect();

  doc.fire('pointermove', {clientX: 900, clientY: 700});    // away from both the trigger and the card
  assert.equal(clock.pending, 1, 'being off both arms the grace timer');
  doc.fire('pointermove', {clientX: box.left + 5, clientY: box.top + 5});   // back onto the card
  assert.equal(clock.pending, 0, 'coming back onto the card cancels the pending close');
  clock.advance(GRACE_MS * 5);
  assert.equal(card.isOpen, true, 'the card must not shut itself as the player arrives');
  // A pointer that stays away still dismisses it, so returning is not a way to keep a card up forever.
  doc.fire('pointermove', {clientX: 900, clientY: 700});
  clock.advance(GRACE_MS);
  assert.equal(card.isOpen, false, 'a pointer that stays away still dismisses the card');
});

// ----------------------------------------------------------------- 12. the trigger's real box
test('the card keeps clear of the WHOLE trigger, whichever shape its box arrives in', () => {
  const view = {width: 1200, height: 800};
  const size = {width: 240, height: 300};
  // What the review found: the board hands over {left, top, right, bottom} (getBoundingClientRect's shape) and
  // placement only understood {left, top, width, height}, so a map token was avoided as if it were a 2px dot.
  const token = {left: 100, top: 100, right: 180, bottom: 140};
  const covers = spot => {
    const box = {left: spot.left, top: spot.top, right: spot.left + size.width, bottom: spot.top + size.height};
    return box.left < token.right && box.right > token.left && box.top < token.bottom && box.bottom > token.top;
  };
  const fromEdges = place({anchor: {x: 140, y: 100}, avoid: token, size, view});
  const fromSize = place({anchor: {x: 140, y: 100}, avoid: {left: 100, top: 100, width: 80, height: 40}, size, view});
  assert.equal(covers(fromEdges), false, 'the card must not sit on an 80x40 token, only on the pointer dot');
  assert.deepEqual(fromEdges, fromSize, 'both rectangle shapes mean the same place');
  assert.ok(fromEdges.left >= 8 && fromEdges.top >= 8 && fromEdges.left + 240 <= 1192 && fromEdges.top + 300 <= 792,
            'and the card is still on screen');
});

test('every trigger on the map ends up with a card that is on screen and off the trigger', () => {
  // The property the bug was really about, swept over the whole window: a card is placed beside a trigger, clamped
  // into the window, and CHECKED AGAIN after the clamp, so no trigger anywhere can end up under the card. A card
  // that covers a token steals the click meant for the token.
  const view = {width: 1200, height: 800};
  const size = {width: 240, height: 300};
  for (let x = 4; x < view.width; x += 37) {
    for (let y = 4; y < view.height; y += 37) {
      const trigger = {left: x, top: y, right: x + 80, bottom: y + 40};
      const spot = place({anchor: {x: x + 40, y}, avoid: trigger, size, view});
      const box = {left: spot.left, top: spot.top, right: spot.left + size.width, bottom: spot.top + size.height};
      const where = `trigger at ${x},${y}`;
      assert.ok(box.left >= 8 && box.top >= 8 && box.right <= view.width - 8 && box.bottom <= view.height - 8,
                `the card stays on screen for a ${where}`);
      assert.ok(!(box.left < trigger.right && box.right > trigger.left && box.top < trigger.bottom && box.bottom > trigger.top),
                `the card must not cover a ${where}, even after it was clamped into the window`);
    }
  }
});

test('asRect reads either rectangle shape, and says so when there is no box to avoid', () => {
  assert.deepEqual(asRect({left: 10, top: 20, right: 30, bottom: 40}), {left: 10, top: 20, right: 30, bottom: 40});
  assert.deepEqual(asRect({left: 10, top: 20, width: 20, height: 20}), {left: 10, top: 20, right: 30, bottom: 40});
  assert.equal(asRect(null), null, 'no box, nothing to avoid');
  assert.equal(asRect({left: 10, top: 20}), null, 'a box with no area is no box');
  assert.deepEqual(asRect({left: 10, top: 20}, {x: 50, y: 60}), {left: 49, top: 59, right: 51, bottom: 61},
                   'a box with no area falls back to the pointer, so the card still avoids where you are');
});

// ----------------------------------------------------------------- 13. one card per document
test('page and map share one card, with only the current trigger described', () => {
  // SOL211 replaces the two-node contract with one popup, retaining the original accessibility guarantee:
  // aria-describedby resolves to the visible rules, never a different hidden card.
  const doc = makeDoc();
  const clock = fakeClock();
  const options = {doc, win: {innerWidth: 1200, innerHeight: 800}, setTimer: clock.setTimer, clearTimer: clock.clearTimer};
  const pageCard = createHoverCard(options);
  const mapCard = createHoverCard(options);
  assert.equal(pageCard.node, mapCard.node, 'one card node per document');

  const pill = new FakeElement('span');
  pill.rect = {left: 20, top: 30, right: 120, bottom: 54, width: 100, height: 24};
  const token = new FakeElement('button');
  token.rect = {left: 700, top: 300, right: 780, bottom: 340, width: 80, height: 40};
  doc.body.appendChild(pill);
  doc.body.appendChild(token);
  pageCard.open({trigger: pill, anchor: {x: 70, y: 54}, build: node => { node.textContent = 'Blinded.'; }});
  mapCard.open({trigger: token, anchor: {x: 740, y: 300}, build: node => { node.textContent = 'Kael, 10 of 12 hit points.'; }});

  assert.equal(pill.getAttribute('aria-describedby'), null, 'the replaced pill no longer points at any card');
  assert.equal(token.getAttribute('aria-describedby'), mapCard.node.id, 'the token points at the map card');
  // Resolve the pointer the way a screen reader would: the id must find THAT card in the document.
  const byId = id => doc.body.children.find(child => child.id === id);
  assert.equal(byId(token.getAttribute('aria-describedby')), mapCard.node, 'the token\'s id finds the map card');
  assert.equal(byId(token.getAttribute('aria-describedby')).textContent, 'Kael, 10 of 12 hit points.',
               'so the token is described by its own rules, not the page card\'s');
  pageCard.close();
  assert.equal(mapCard.isOpen, true, 'a stale page handle cannot close the map card');
});

// ----------------------------------------------------------------- 14. closing tells the board
test('closing the card tells whoever filled it, however it closed', () => {
  // The map remembers which token it is describing, so it can refresh that card's hit points. If the card goes away
  // without saying so -- Escape, a press elsewhere, or the pointer leaving for good -- the map carries on believing
  // it has a card up and puts it straight back on the next token update.
  const how = {
    'Escape closes it': ({doc, clock}) => doc.fire('keydown', {key: 'Escape'}),
    'a press elsewhere closes it': ({doc}) => doc.fire('pointerdown', {clientX: 1000, y: 700}),
    'the pointer leaving for good closes it': ({doc, clock}) => { doc.fire('pointermove', {clientX: 1000, y: 700}); clock.advance(GRACE_MS); },
  };
  for (const [name, dismiss] of Object.entries(how)) {
    const {doc, clock} = harness();
    const closed = [];
    const card = createHoverCard({doc, win: {innerWidth: 1200, innerHeight: 800}, setTimer: clock.setTimer,
                                  clearTimer: clock.clearTimer, onClose: () => closed.push(true)});
    const trigger = new FakeElement('button');
    trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
    card.open({trigger, anchor: {x: 140, y: 100}, build: node => { node.textContent = 'Kael'; }});
    dismiss({doc, clock});
    assert.equal(card.isOpen, false, `${name}`);
    assert.equal(closed.length, 1, `${name}, so the map forgets the token it was describing`);
  }
  // Refilling the same card is not a dismissal: the token is still the one being described.
  const {doc, clock} = harness();
  const closed = [];
  const card = createHoverCard({doc, win: {innerWidth: 1200, innerHeight: 800}, setTimer: clock.setTimer,
                                clearTimer: clock.clearTimer, onClose: () => closed.push(true)});
  const trigger = new FakeElement('button');
  trigger.rect = {left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40};
  card.open({trigger, anchor: {x: 140, y: 100}, build: node => { node.textContent = 'Kael'; }});
  card.open({trigger, anchor: {x: 140, y: 100}, force: true, build: node => { node.textContent = 'Kael, 11 hit points.'; }});
  assert.equal(closed.length, 1, 'refilling the card is reported as a close, which is what the board expects');
  assert.equal(card.node.textContent, 'Kael, 11 hit points.', 'and the new text is in the card');
});
