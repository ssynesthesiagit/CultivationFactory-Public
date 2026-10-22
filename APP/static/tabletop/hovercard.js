// The shared hover card for the combat table, the map and the sheets.
//
// Owner, 2026-10-03: "there needs to be a way to hover over the tooltip to scroll down with middle mouse roll
// button. wait for it to pop up, then move over to the box and select things or scroll down etc." The card used to be
// a picture of the text you could not touch: it was drawn with `pointer-events: none`, it had no height limit, and
// a long one (Darkness, then Pure Darkness, Hungry Darkness, Eternal, Greater Darkness, then Court of Charged Paths)
// simply ran off the bottom of the screen with the text you wanted out of reach.
//
// One card, one behaviour, every surface. The map's zone/ground card, the token card, condition pills, action
// buttons and sheet rows all go through `createHoverCard` instead of growing their own tooltip, so a rule changed
// here reaches all of them. What the card does:
//
//   - it STAYS OPEN while the pointer travels from the thing you hovered onto the card. The pointer leaving the
//     trigger only starts a short grace period (GRACE_MS). The trigger's box,
//     card's box and connecting corridor, grown by BRIDGE_GAP_PX, form the hover
//     bridge; it works in either direction even when zoom leaves a wider gap;
//   - inside the card the MOUSE WHEEL scrolls the card -- the card scrolls itself, for any wheel button, and the
//     event never reaches the map's zoom handler or the page. A press of the middle mouse BUTTON is swallowed there
//     too, so the browser's own middle-drag autoscroll cannot fight the card's scrolling;
//   - its text can be selected and copied, and the card closes on Escape, on a click elsewhere, or when the
//     pointer has been off both the trigger and the card for the grace period;
//   - it is placed BESIDE the trigger, never over the thing you are pointing at.
//
// Accessibility: while a card is open its trigger is pointed at the card with aria-describedby, so a screen
// reader reads the same words the pointer just hovered. Closing the card removes the pointer again.
//
// `place()` is exported on its own (pure, no DOM) because choosing a side is the part worth testing.

export const GRACE_MS = 300;      // how long the card survives the pointer leaving for
export const HOVER_OPEN_DELAY_MS = 500; // restore the browser tooltip pause before pointer-triggered cards open
export const BRIDGE_GAP_PX = 28;  // how far the hover bridge reaches past the trigger and the card
export const EDGE_GAP_PX = 8;     // keep this much screen between the card and the window edge
export const OFFSET_PX = 14;      // how far from the trigger the card sits

// A trigger's screen box arrives in either shape: getBoundingClientRect's {left, top, right, bottom}, or the older
// {left, top, width, height}. Both mean the same rectangle, and a card has to keep clear of the WHOLE of it: a map
// token is 40x40, not the two-pixel dot the pointer is. `fallback` (a point) is used when a box carries no area.
// Returns null for anything that is not a usable box.
export function asRect(box, fallback = null) {
  if (!box) return null;
  const left = Number(box.left), top = Number(box.top);
  if (!Number.isFinite(left) || !Number.isFinite(top)) return null;
  const width = Number(box.width), height = Number(box.height);
  const right = Number.isFinite(Number(box.right)) ? Number(box.right) : left + (Number.isFinite(width) ? width : 0);
  const bottom = Number.isFinite(Number(box.bottom)) ? Number(box.bottom) : top + (Number.isFinite(height) ? height : 0);
  if (right < left || bottom < top) return null;
  if (right === left && bottom === top) return fallback ? pointBox(fallback.x, fallback.y, 1) : null;
  return {left, top, right, bottom};
}

// Pick where to put the card: the first spot that fits on screen and does not cover `avoid` (the trigger's box), then
// clamped into the window. Returns the card's top-left in window coordinates.
export function place({anchor, avoid, size, view, gap = OFFSET_PX, edge = EDGE_GAP_PX}) {
  const width = Math.max(0, Number(size?.width) || 0);
  const height = Math.max(0, Number(size?.height) || 0);
  const vw = Number(view?.width) || 0;
  const vh = Number(view?.height) || 0;
  const point = anchor || {x: edge, y: edge};
  const clear = asRect(avoid, point) || pointBox(point.x, point.y, 1);
  const boxOf = spot => ({left: spot.left, top: spot.top, right: spot.left + width, bottom: spot.top + height});
  const overlaps = box => box.left < clear.right && box.right > clear.left && box.top < clear.bottom && box.bottom > clear.top;
  const inWindow = spot => {
    const box = boxOf(spot);
    return box.left >= edge && box.top >= edge && box.right <= vw - edge && box.bottom <= vh - edge;
  };
  const clamp = spot => ({
    left: Math.min(Math.max(edge, spot.left), Math.max(edge, vw - width - edge)),
    top: Math.min(Math.max(edge, spot.top), Math.max(edge, vh - height - edge)),
  });
  // Below, above, right, left: the sides measured from the POINTER, the order the pointer is most likely to travel
  // next, so the card opens "forward".
  const sides = [
    {left: point.x + gap, top: point.y + gap},
    {left: point.x + gap, top: point.y - height - gap},
    {left: point.x + gap, top: point.y - height / 2},
    {left: point.x - width - gap, top: point.y - height / 2},
  ];
  // When the trigger is a box the pointer sits in the MIDDLE of it, and all four of those sides can land back on the
  // trigger. These four are measured from the trigger's box itself, so one of them always clears it.
  const beside = [
    {left: clear.right + gap, top: clear.top},
    {left: clear.left - width - gap, top: clear.top},
    {left: clear.left, top: clear.bottom + gap},
    {left: clear.left, top: clear.top - height - gap},
  ];
  // Clamp every candidate FIRST, so the overlap test below always runs on the card's real final box. A card that
  // clears the trigger and is then clamped back onto it is the bug this ordering avoids.
  const spots = [...sides, ...beside].map(clamp);
  // The best card is one that fits on screen and clears the trigger; failing that, one that at least clears it.
  const best = spots.find(spot => inWindow(spot) && !overlaps(boxOf(spot)))
    || spots.find(spot => !overlaps(boxOf(spot)));
  if (best) return best;
  // Nothing cleared the trigger (a trigger wider than the window, say). Slide the card off its nearest edge rather
  // than sit on the thing the player is trying to read.
  const slid = [
    {left: spots[0].left, top: clear.top - height - edge},
    {left: spots[0].left, top: clear.bottom + edge},
    {left: clear.right + edge, top: spots[0].top},
    {left: clear.left - width - edge, top: spots[0].top},
  ].map(clamp);
  return slid.find(spot => !overlaps(boxOf(spot))) || spots[0];
}

// Grow a box by n on every side. Boxes come from getBoundingClientRect, which the test doubles fake.
export function inflate(box, n) {
  if (!box) return null;
  return {left: box.left - n, top: box.top - n, right: (box.right ?? box.left + box.width) + n,
          bottom: (box.bottom ?? box.top + box.height) + n};
}

export function inside(point, box) {
  if (!box || !point) return false;
  return point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom;
}

// The convex corridor joining the source square/token and the popup. Independent
// inflation alone leaves holes when zoom or viewport clamping separates them.
// Both board and delegated cards use this; unrelated squares outside it still close.
export function inHoverBridge(point, source, card, gap = BRIDGE_GAP_PX) {
  if (!point) return false;
  const boxes = [source, card].filter(Boolean).map(box => inflate(box, gap));
  if (boxes.some(box => inside(point, box))) return true;
  if (boxes.length < 2) return false;
  const points = boxes.flatMap(b => [
    {x: b.left, y: b.top}, {x: b.right, y: b.top},
    {x: b.right, y: b.bottom}, {x: b.left, y: b.bottom},
  ]).sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const half = list => {
    const hull = [];
    for (const p of list) {
      while (hull.length > 1 && cross(hull.at(-2), hull.at(-1), p) <= 0) hull.pop();
      hull.push(p);
    }
    return hull.slice(0, -1);
  };
  const hull = [...half(points), ...half([...points].reverse())];
  return hull.every((p, i) => cross(p, hull[(i + 1) % hull.length], point) >= 0);
}

// A point, plus a small box for it. Used when there is no element to measure (the map's ground is one big canvas).
export function pointBox(x, y, radius = 0) {
  return {left: x - radius, top: y - radius, right: x + radius, bottom: y + radius};
}

// Document-owned state also survives imports with different cache-version URLs. Callers get separate handles
// (and close/dismiss callbacks), but share one popup. A stale map update cannot close the sheet's current card.
const SHARED_CARD = Symbol.for("tianxia.hovercard.document");
const TIP_BINDINGS = Symbol.for("tianxia.hovercard.bindings");

// Remove competing native titles, including nested labels. An empty title on the custom trigger blocks an
// inherited ancestor title without destroying that ancestor's help for its other controls.
export function suppressNativeTooltip(element) {
  element?.removeAttribute?.("title");
  for (const child of element?.querySelectorAll?.("[title]") || []) child.removeAttribute("title");
  for (let parent = element?.parentElement || element?.parentNode; parent; parent = parent.parentElement || parent.parentNode) {
    if (parent.hasAttribute?.("title")) { element.setAttribute("title", ""); break; }
  }
}

export function createHoverCard({doc = globalThis.document, win = globalThis.window,
                                  graceMs = GRACE_MS, bridgeGap = BRIDGE_GAP_PX,
                                  setTimer = (fn, ms) => setTimeout(fn, ms),
                                  clearTimer = id => clearTimeout(id),
                                  onClose = null, onDismiss = null} = {}) {
  if (!doc) throw new Error("createHoverCard needs a document");
  if (doc[SHARED_CARD]) return doc[SHARED_CARD]({onClose, onDismiss});

  const node = doc.createElement("div");
  node.className = "tt-hovercard";
  node.hidden = true;
  node.id = "tt-hovercard";
  node.setAttribute("role", "tooltip");
  // The card's INTERACTIVE half is set here, in the markup, not only in the stylesheet. A page (or a test harness)
  // that has not loaded hovercard.css still gets a card that can be reached, scrolled and selected; the stylesheet
  // only adds the look and the scrollbar. A card that silently stopped scrolling because a stylesheet was missing
  // is exactly the bug this replaces, so the behaviour must not depend on the load order.
  node.style.position = "fixed";
  node.style.zIndex = "60";
  node.style.pointerEvents = "auto";
  node.style.boxSizing = "border-box";
  node.style.overflowX = "hidden";
  node.style.overflowY = "auto";
  node.style.overscrollBehavior = "contain";
  node.style.userSelect = "text";
  node.style.webkitUserSelect = "text";
  (doc.body || doc.documentElement || doc).appendChild(node);

  let trigger = null;      // the element the pointer came from, when there is one
  let avoid = null;        // the trigger's box: the card must never cover it
  let bridge = "element";  // "element": leaving the trigger starts the grace period. "card": the card survives
  // (the map's zone card is triggered by the pointer resting on a square, not by an element)
  let pointer = null;      // last pointer position, in window coordinates
  let anchorPoint = null;  // where the card was opened from. Kept apart from `pointer` on purpose: placement must
                           // follow the spot the card opened at, not the cursor, or the card would slide out from
                           // under the pointer the moment the pointer reached it
  let contentKey = null;   // what is in the card now, so a re-hover of the same text does not rebuild it
  let closeTimer = null;
  let pendingOpen = null;  // latest same-trigger update, held while its text is selected
  let selecting = false;  // pointer press in the card, before the browser has made a selection
  const listeners = [];    // [target, type, fn, options] removed on close
  let owner = null;        // handle that supplied the current content and callbacks
  const dismissalListeners = new Map(); // listener -> client, so a replacement can identify its incoming owner

  const on = (target, type, fn, options) => {
    if (!target?.addEventListener) return;
    target.addEventListener(type, fn, options);
    listeners.push([target, type, fn, options]);
  };
  function cancelClose() { if (closeTimer !== null) { clearTimer(closeTimer); closeTimer = null; } }
  function armClose() {
    cancelClose();
    if (selecting || hasSelection()) return;
    closeTimer = setTimer(() => { closeTimer = null; close(); }, graceMs);
  }

  function view() {
    return {width: win?.innerWidth || doc.documentElement?.clientWidth || 0,
            height: win?.innerHeight || doc.documentElement?.clientHeight || 0};
  }

  // The hover bridge: the pointer counts as "still on the card" while it is over the card, over the gap between the
  // card and the trigger, or over the trigger itself. This is what lets the owner wait for the card, move onto it,
  // and scroll it. A card with bridge "card" is triggered by the pointer resting on a map square rather than by an
  // element. Its source square must still be in the bridge, or the first small
  // move toward a right-hand card dismisses it before the pointer reaches the gap.
  function ownsPointer(point = pointer) {
    if (!point || node.hidden) return false;
    return inHoverBridge(point, avoid, rectOf(node), bridgeGap);
  }

  function rectOf(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") return null;
    const r = element.getBoundingClientRect();
    if (r.width == null && r.right == null) return null;
    return {left: r.left ?? 0, top: r.top ?? 0, right: r.right ?? (r.left ?? 0) + (r.width ?? 0),
            bottom: r.bottom ?? (r.top ?? 0) + (r.height ?? 0)};
  }

  function describe(next) {
    // Drop the old trigger's pointer, then point the new one at the card: a screen reader reads the same words the
    // pointer just hovered. Closing (describe(null)) removes the pointer again.
    if (trigger && trigger !== next) trigger.removeAttribute?.("aria-describedby");
    trigger = next || null;
    if (trigger) trigger.setAttribute?.("aria-describedby", node.id);
  }

  function hasSelection() {
    const selection = win?.getSelection?.();
    if (!selection || selection.isCollapsed) return false;
    for (let i = 0; i < selection.rangeCount; i++) {
      if (selection.getRangeAt(i).intersectsNode(node)) return true;
    }
    return false;
  }

  // Shared blur policy for tokens and delegated controls. A press on non-focusable card text can blur its
  // trigger before selection exists; the pointerdown capture below records that press before blur runs.
  function releaseFocus(event) {
    if (node.contains?.(event?.relatedTarget) || inside(pointer, rectOf(node)) || hasSelection()) {
      cancelClose();
      return;
    }
    close();
  }

  // Viewport/trigger leave can precede the document's next pointermove when entering this body overlay.
  // Use the leave coordinates and the shared bridge/grace policy, never an immediate caller-owned close.
  function releasePointer(event) {
    pointer = {x: event.clientX, y: event.clientY};
    if (ownsPointer()) cancelClose(); else armClose();
  }

  // Explicit player dismissal also invalidates caller-owned delayed opens. Internal replacement/refresh uses
  // close() only, so it does not cancel a legitimate rest timer. onDismiss receives "escape", "outside-press",
  // or "replacement" when another caller takes ownership of the document's popup.
  function dismiss(reason) {
    for (const listener of dismissalListeners.keys()) listener(reason);
    owner?.onDismiss?.(reason);
    close();
  }

  // `key` identifies visible content. Same-trigger changes update in place and retain scroll; selected text
  // stays intact until selectionchange clears it, then the latest deferred update is shown. Different triggers
  // still start at the top. `force` explicitly requests rebuilding even when the key is unchanged.
  function open({trigger: next = null, anchor = null, avoid: nextAvoid = null, build = null, key = null,
                 force = false, bridge: nextBridge = "element"} = {}) {
    const sameTrigger = next === trigger;
    if (!force && !node.hidden && sameTrigger && (key === null || key === contentKey)) {
      pendingOpen = null;
      // Same trigger, same words: preserve the popup and its reading position.
      // A map-square open supplies real pointer coordinates. A token refresh
      // supplies a token anchor, which must not overwrite the actual pointer
      // halfway across the bridge (or while the player is scrolling the card).
      if (anchor && bridge === "card") {
        pointer = {x: anchor.x, y: anchor.y};
        if (!ownsPointer(pointer)) anchorPoint = {x: anchor.x, y: anchor.y};
      }
      position();
      cancelClose();
      return;
    }
    if (!force && !node.hidden && sameTrigger) {
      if (selecting || hasSelection()) {
        pendingOpen = {trigger: next, anchor, avoid: nextAvoid, build, key, force, bridge: nextBridge};
        return;
      }
      pendingOpen = null;
      const scroll = node.scrollTop;
      if (build) build(node);
      contentKey = key;
      avoid = nextAvoid || avoid;
      node.scrollTop = scroll;
      position();
      cancelClose();
      return;
    }
    close();
    describe(next);
    watch(next);
    bridge = nextBridge;
    avoid = nextAvoid || rectOf(next) || (anchor ? pointBox(anchor.x, anchor.y, 2) : null);
    pointer = anchor ? {x: anchor.x, y: anchor.y} : null;
    anchorPoint = pointer ? {x: pointer.x, y: pointer.y} : null;
    if (build) build(node);
    contentKey = key;
    node.hidden = false;
    node.scrollTop = 0;
    position();
    attach();
    cancelClose();
  }

  function position() {
    const box = view();
    // The same cap the stylesheet gives with calc(100vh - 16px), applied here so a long card scrolls even when
    // hovercard.css is not loaded (see the note where the node is created).
    node.style.maxHeight = `${Math.max(160, box.height - 2 * EDGE_GAP_PX)}px`;
    // Placement follows the spot the card OPENED at, never the last pointer position: re-anchoring on every move
    // would walk the card away from the pointer as it travelled towards it.
    const anchor = anchorPoint || (avoid ? {x: (avoid.left + avoid.right) / 2, y: avoid.top} : {x: EDGE_GAP_PX, y: EDGE_GAP_PX});
    const spot = place({anchor, avoid, size: {width: node.offsetWidth, height: node.offsetHeight}, view: box});
    node.style.left = `${Math.round(spot.left)}px`;
    node.style.top = `${Math.round(spot.top)}px`;
  }

  function close() {
    cancelClose();
    pendingOpen = null;
    selecting = false;
    if (node.hidden) return;
    node.hidden = true;
    node.scrollTop = 0;
    contentKey = null;
    detach();
    describe(null);
    avoid = null;
    bridge = "element";
    pointer = null;
    anchorPoint = null;
    // Whoever put something in the card (the map's token card keeps the token it is describing) has to hear about the
    // close, or it will go on believing a card it no longer has is on screen.
    owner?.onClose?.();
  }

  // One set of listeners per open card. The wheel listener is registered on the card (not the window) so it only
  // ever runs while the pointer is over the card.
  function attach() {
    // Details in structured cards resize the same overlay, regardless of which caller currently owns it.
    on(node, "toggle", () => position(), true);
    on(node, "wheel", event => {
      // The card scrolls ITSELF. `overflow-y: auto` is not enough on its own: the card is a fixed overlay on a page
      // whose wheel handler zooms the map, so an unconsumed wheel scrolls the map instead of the rules. Scrolling
      // here and consuming the event is what makes the owner's mouse wheel (middle wheel included) move the text
      // they came for, and is why the event is cancelled rather than left to the browser's own scroll.
      const step = event.deltaMode === 1 ? 16 : 1;   // Firefox counts a wheel notch in LINES, everyone else in pixels
      node.scrollTop = node.scrollTop + (Number(event.deltaY) || 0) * step;
      event.preventDefault();
      event.stopPropagation();
    }, {passive: false});
    // Entering the card must not move it: it is already placed, and re-placing on entry walked it out from under the
    // pointer. Just make sure no close is armed while the pointer is on it.
    on(node, "pointerenter", () => cancelClose());
    on(node, "pointermove", event => { pointer = {x: event.clientX, y: event.clientY}; cancelClose(); });
    on(node, "pointerleave", event => { pointer = {x: event.clientX, y: event.clientY}; armClose(); });
    on(node, "mousedown", event => { if (event.button === 1) event.preventDefault(); });
    on(doc, "pointermove", event => {
      pointer = {x: event.clientX, y: event.clientY};
      // Coming BACK onto the card cancels the pending close, not just staying on it. A card armed to close while the
      // pointer crossed the gap used to shut itself in the player's face as they arrived.
      if (ownsPointer()) cancelClose(); else armClose();
    }, true);
    on(doc, "keydown", event => { if (event.key === "Escape") dismiss("escape"); });
    // Test the press where it landed, not at the last pointermove: pressing ON the card must not dismiss it.
    on(doc, "pointerdown", event => {
      pointer = {x: event.clientX, y: event.clientY};
      selecting = inside(pointer, rectOf(node)) && event.button === 0;
      if (selecting) cancelClose();
      if (!ownsPointer()) dismiss("outside-press");
    }, true);
    const refreshAfterSelection = () => {
      if (selecting || hasSelection()) { cancelClose(); return; }
      if (pendingOpen) {
        const update = pendingOpen;
        pendingOpen = null;
        open(update);
      }
      if (!ownsPointer()) armClose();
    };
    on(doc, "pointerup", () => { selecting = false; refreshAfterSelection(); }, true);
    on(doc, "pointercancel", () => { selecting = false; refreshAfterSelection(); }, true);
    on(doc, "selectionchange", refreshAfterSelection);
  }
  function detach() { while (listeners.length) { const [target, type, fn, options] = listeners.pop(); target.removeEventListener(type, fn, options); } watched.clear(); }

  // Track the trigger so leaving it starts the grace period rather than an instant close. open() calls this, and it
  // is safe to call again: a trigger is only ever watched once per open card.
  const watched = new Set();
  function watch(triggerElement) {
    if (!triggerElement?.addEventListener || watched.has(triggerElement)) return;
    triggerElement.setAttribute?.("data-hover-card", "");
    suppressNativeTooltip(triggerElement);
    watched.add(triggerElement);
    on(triggerElement, "pointerenter", () => cancelClose());
    on(triggerElement, "pointerleave", event => { pointer = {x: event.clientX, y: event.clientY}; armClose(); });
  }

  function client(callbacks) {
    // The first caller also owns pre-open pointer/grace handling; later callers take over only on open().
    if (!owner) owner = callbacks;
    const mine = () => owner === callbacks;
    return {node,
      open(options) {
        if (!mine()) {
          // Cancel the previous caller's delayed opens as well as its visible content.
          for (const [listener, listenerOwner] of dismissalListeners) {
            listener("replacement", listenerOwner === callbacks);
          }
          owner?.onDismiss?.("replacement");
          close(); owner = callbacks;
        }
        open(options);
      },
      close() {
        if (!mine()) return;
        for (const listener of dismissalListeners.keys()) listener("close");
        close();
      },
      // Subscribe to user dismissal and content replacement so caller-owned delayed work can be cancelled too.
      // Replacement listeners receive (reason, isIncomingOwner); all other notifications pass only the reason.
      // Returns an unsubscribe function; listeners are shared because the visible card is shared across clients.
      onDismiss(listener) {
        if (typeof listener !== "function") return () => {};
        dismissalListeners.set(listener, callbacks);
        return () => dismissalListeners.delete(listener);
      },
      watch(element) { if (mine()) watch(element); },
      cancelClose() { if (mine()) cancelClose(); },
      ownsPointer(point) { return mine() && ownsPointer(point); },
      position() { if (mine()) position(); },
      releaseFocus(event) { if (mine()) releaseFocus(event); },
      releasePointer(event) { if (mine()) releasePointer(event); },
      get interacting() { return mine() && !node.hidden && (inside(pointer, rectOf(node)) || hasSelection()); },
      get isOpen() { return mine() && !node.hidden; }, get trigger() { return mine() ? trigger : null; }};
  }
  doc[SHARED_CARD] = client;
  return client({onClose, onDismiss});
}

// Bind every `[data-tip]` element under `root` to the shared card: hovering it opens the card, and its text comes
// from `data-tip` (or from a `data-tip-from` function name on `options`). This is the one seam the condition pills,
// the action buttons and the sheet rows use, so none of them needs its own hover code.
// `glossary(text)` returns plain definitions for terms the card or its trigger names (Qi, Martial Focus, Mark...):
// the native-title glossary is suppressed on app cards, so its help lives in the one card instead, appended once and
// never when the card's own text already says it.
export function bindTipTargets(card, root = null, {selector = "[data-tip]", delay = HOVER_OPEN_DELAY_MS, setTimer, clearTimer, glossary = null} = {}) {
  const doc = root?.ownerDocument || globalThis.document;
  const host = root || doc;
  // Delegation survives replacement of rows. Rebinding the same surface/selector replaces the old listener
  // set and cancels its delayed open, rather than stacking handlers or keeping a detached row alive.
  const bindings = host[TIP_BINDINGS] ||= new Map();
  bindings.get(selector)?.dispose();
  const listeners = [];
  const on = (type, fn) => { host.addEventListener(type, fn); listeners.push([type, fn]); };
  const wait = setTimer || ((fn, ms) => setTimeout(fn, ms));
  const forget = clearTimer || (id => clearTimeout(id));
  let timer = null;
  let pendingTarget = null;
  const cancelPending = () => {
    if (timer !== null) forget(timer);
    timer = null;
    pendingTarget = null;
  };
  const unsubscribeDismiss = card.onDismiss?.(() => cancelPending());
  // A render can replace a row without pointerout. Only targets still in this bound surface may open.
  const currentTarget = element => host.isConnected !== false && host.contains(element) && element.closest(selector) === element;
  const contentOf = element => {
    const from = element.dataset.tipFrom;
    if (from && typeof element[from] === "function") return String(element[from]() ?? "");
    return element.dataset.tip || "";
  };
  const glossaryFor = (element, own) => {
    if (typeof glossary !== "function") return [];
    const said = own.toLowerCase();
    const label = element.getAttribute?.("aria-label") || "";
    return (glossary(`${element.textContent || ""}\n${label}\n${own}`) || [])
      .filter(help => help && !said.includes(String(help).toLowerCase()));
  };
  const show = element => {
    if (!currentTarget(element)) return;
    const own = contentOf(element);
    if (!own) return;
    const terms = glossaryFor(element, own);
    const text = [own, ...terms].join("\n\n");
    const r = element.getBoundingClientRect();
    // A trigger may supply a structured card (rules.js action cards, the AC card) as `tipCard(doc, {terms})`.
    // Its data-tip stays the plain text: the content key, and what tests and assistive tech read.
    const structured = typeof element.tipCard === "function" ? element.tipCard : null;
    card.open({trigger: element, anchor: {x: r.left + r.width / 2, y: r.top + r.height},
               avoid: {left: r.left, top: r.top, right: r.right ?? r.left + r.width, bottom: r.bottom ?? r.top + r.height},
               key: text, build: node => {
                 node.className = "tt-hovercard";
                 node.replaceChildren();
                 const owner = node.ownerDocument || (typeof host.createElement === "function" ? host : doc);
                 const built = structured && structured(owner, {terms});
                 if (built) {
                   node.classList?.add?.("tt-tipcard"); node.append(built);
                 }
                 else { node.classList?.remove?.("tt-tipcard"); node.textContent = text; }
               }});
  };
  on("pointerover", event => {
    const element = event.target?.closest?.(selector);
    if (element && pendingTarget === element) return; // Moving between children keeps the original delay.
    cancelPending();
    if (!element || !contentOf(element)) return;
    suppressNativeTooltip(element);
    if (card.trigger === element) return;
    pendingTarget = element;
    timer = wait(() => {
      if (pendingTarget !== element) return;
      timer = null;
      pendingTarget = null;
      show(element);
    }, delay);
  });
  on("pointerout", event => {
    const element = event.target?.closest?.(selector);
    if (!element || element.contains(event.relatedTarget)) return;
    if (pendingTarget === element) cancelPending();
  });
  // Focus reaches the same card, so a keyboard user gets the same words a mouse user does.
  on("focusin", event => {
    cancelPending();
    const element = event.target?.closest?.(selector);
    if (element && contentOf(element)) show(element);
  });
  on("focusout", event => {
    const element = event.target?.closest?.(selector);
    if (element && card.trigger === element) card.releaseFocus(event);
  });
  // Optional activation seam for stat breakdowns: existing hover-only rows are
  // inert unless they explicitly carry data-tip-click. Touch and keyboard use
  // the same card as pointer hover, never a second tooltip.
  on("click", event => {
    const element = event.target?.closest?.(selector);
    if (element?.hasAttribute("data-tip-click")) { cancelPending(); show(element); }
  });
  on("keydown", event => {
    const element = event.target?.closest?.(selector);
    if (element?.hasAttribute("data-tip-click") && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault(); cancelPending(); show(element);
    }
  });
  const binding = {show, dispose() {
    cancelPending();
    unsubscribeDismiss?.();
    for (const [type, fn] of listeners) host.removeEventListener(type, fn);
    listeners.length = 0;
    if (bindings.get(selector) === binding) bindings.delete(selector);
  }};
  bindings.set(selector, binding);
  return binding;
}
