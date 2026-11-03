// Map ruler (owner feedback desk FD-17): "we should have a ruler tool when you right click on a
// square and drag it to another square it has a line to it and says the length".
//
// It is client-side only: it writes nothing to the fight, spends no action and works while anyone
// is taking their turn, the AI included.
//
// The distance rule is the engine's (combat/gate2_grid.py, distance_between_cell_sets_ft): squares
// are counted with the chessboard (Chebyshev) metric, where a diagonal step costs exactly one
// square like a king's move, a height counts as a third axis when either square has one, and the
// count is multiplied by the map's square size. Keeping that rule in this one small function is
// what stops the ruler disagreeing with the engine's reach and range checks: tests/test_map_ruler.py
// recomputes the same paths through the engine and compares.

export const RULER_DRAG_PX = 6;
export const RULER_GROUND_NOTE = "ground distance";

const SVGNS = "http://www.w3.org/2000/svg";

// Missing height means ground level, the same default the engine's Position uses.
function axis(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function squareSize(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 5;
}

// Engine metric: max(|dx|, |dy|, |dz|) squares, so straight and diagonal paths cost the same.
export function rulerCells(from, to) {
  return Math.max(Math.abs(axis(from.x) - axis(to.x)), Math.abs(axis(from.y) - axis(to.y)),
    Math.abs(axis(from.z) - axis(to.z)));
}

// What the label says. "15 ft (3 squares)" is the length; the second line says whether the height
// of either end was counted, because a height-inclusive distance is not the same as ground distance.
export function rulerMeasure(from, to, squareSizeFt = 5) {
  const cells = rulerCells(from, to);
  const feet = cells * squareSize(squareSizeFt);
  const heightIncluded = axis(from.z) !== 0 || axis(to.z) !== 0;
  const squares = cells === 1 ? "1 square" : `${cells} squares`;
  return {
    cells,
    feet,
    heightIncluded,
    headline: `${feet} ft (${squares})`,
    detail: heightIncluded ? "distance including height" : RULER_GROUND_NOTE,
  };
}

function round(value) {
  return Math.round(value * 100) / 100;
}

// The drawing, in viewport pixels. A plain line between the two square centres with a dot at each
// end and the length tag on it, readable at any zoom because the layer is not scaled with the map.
export function rulerMarkup(a, b, measure, {width = 0} = {}) {
  const boxWidth = Math.max(measure.headline.length, measure.detail.length) * 6.6 + 16;
  const midX = (a.x + b.x) / 2;
  const midY = (a.y + b.y) / 2;
  const lowest = boxWidth / 2 + 4;
  const labelX = width > 0 ? Math.min(Math.max(midX, lowest), Math.max(width - lowest, lowest)) : midX;
  const baseY = midY - 14;
  return [
    `<line class="tt-ruler-line" x1="${round(a.x)}" y1="${round(a.y)}" x2="${round(b.x)}" y2="${round(b.y)}"/>`,
    `<circle class="tt-ruler-end" cx="${round(a.x)}" cy="${round(a.y)}" r="4"/>`,
    `<circle class="tt-ruler-end" cx="${round(b.x)}" cy="${round(b.y)}" r="4"/>`,
    `<g class="tt-ruler-label" transform="translate(${round(labelX)} ${round(baseY)})">`,
    `<rect x="${round(-boxWidth / 2)}" y="-32" width="${round(boxWidth)}" height="32" rx="6"/>`,
    `<text class="tt-ruler-ft" x="0" y="-19">${measure.headline}</text>`,
    `<text class="tt-ruler-kind" x="0" y="-6">${measure.detail}</text>`,
    "</g>",
  ].join("");
}

// Right-press and drag measure; a right-press that never passes threshold is still an ordinary
// right click (the table cancels an open ability pick with it), so the two never fight:
//  - the press is tracked here, never the contextmenu event, because browsers disagree about
//    whether contextmenu fires on press or on release;
//  - a release without a drag calls onPlainRightClick (cancel the pick);
//  - a release after a drag only clears the ruler;
//  - blocksCancel() lets the table's contextmenu handler skip its own cancel while a press or a
//    just-finished drag belongs to the ruler.
export function createMapRuler({
  viewport,
  cellAt,
  toPixels,
  squareSizeFt = 5,
  onPlainRightClick = null,
  threshold = RULER_DRAG_PX,
  doc = globalThis.document,
} = {}) {
  if (!viewport || typeof cellAt !== "function" || typeof toPixels !== "function") {
    throw new TypeError("the ruler needs a viewport, a cellAt() and a toPixels()");
  }
  const host = doc.createElement("div");
  host.className = "tt-ruler-layer";
  host.setAttribute("aria-hidden", "true");
  const svg = doc.createElementNS(SVGNS, "svg");
  svg.setAttribute("class", "tt-ruler");
  svg.setAttribute("aria-hidden", "true");
  host.appendChild(svg);
  viewport.appendChild(host);

  let press = null;
  // One-shot: the right press was already handled on release (measured, or cancelled there), so a
  // contextmenu that arrives afterwards must not answer the pick a second time. It is only set when
  // no contextmenu came during the press (macOS fires it on release); otherwise a later keyboard menu
  // key would be swallowed once.
  let justHandled = false;

  const size = () => squareSize(typeof squareSizeFt === "function" ? squareSizeFt() : squareSizeFt);
  const clear = () => { if (svg.innerHTML) svg.innerHTML = ""; };
  function draw() {
    if (!press || !press.from || !press.to) { clear(); return; }
    svg.innerHTML = rulerMarkup(toPixels(press.from), toPixels(press.to),
      rulerMeasure(press.from, press.to, size()), {width: viewport.clientWidth || 0});
  }

  function onDown(event) {
    if (event.button !== 2) return;
    justHandled = false;
    press = {id: event.pointerId, sx: event.clientX, sy: event.clientY,
      from: cellAt(event.clientX, event.clientY), to: null, dragging: false, menuSeen: false};
    press.to = press.from;
    try { viewport.setPointerCapture?.(event.pointerId); } catch { /* released before the drag began */ }
  }
  function onMove(event) {
    if (!press || press.id !== event.pointerId) return;
    if (!press.dragging && Math.hypot(event.clientX - press.sx, event.clientY - press.sy) > threshold) press.dragging = true;
    if (!press.dragging) return;
    const cell = cellAt(event.clientX, event.clientY);
    if (cell && !press.from) press.from = cell;
    if (cell) press.to = cell;
    draw();
  }
  function onUp(event) {
    if (!press || press.id !== event.pointerId) return;
    const dragged = press.dragging;
    const menuSeen = press.menuSeen;
    press = null;
    clear();
    try { viewport.releasePointerCapture?.(event.pointerId); } catch { /* already released */ }
    justHandled = !menuSeen;
    if (!dragged) onPlainRightClick?.();
  }
  function onCancel() {
    press = null;
    justHandled = false;
    clear();
  }

  // pointerdown is listened to in the capture phase: tokens stop propagation of their own pointerdown
  // (board.js), so a bubble-phase listener on the viewport never sees a press that starts on a token.
  // Capture runs before the token, so the ruler also measures from token squares.
  viewport.addEventListener("pointerdown", onDown, {capture: true});
  viewport.addEventListener("pointermove", onMove);
  viewport.addEventListener("pointerup", onUp);
  viewport.addEventListener("pointercancel", onCancel);

  return {
    // True while a right press is held, and once for a press already handled on release, so a
    // contextmenu cannot cancel the ability pick a second time (or cancel it after a ruler drag).
    // Reading it consumes the one-shot half.
    blocksCancel() {
      if (press) { press.menuSeen = true; return true; }
      if (!justHandled) return false;
      justHandled = false;
      return true;
    },
    clear,
    destroy() {
      viewport.removeEventListener("pointerdown", onDown, {capture: true});
      viewport.removeEventListener("pointermove", onMove);
      viewport.removeEventListener("pointerup", onUp);
      viewport.removeEventListener("pointercancel", onCancel);
      host.remove();
      press = null;
    },
  };
}
