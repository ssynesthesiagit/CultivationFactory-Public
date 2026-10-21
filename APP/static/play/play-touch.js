// Touch adapter around the board's public zoomBy/centerOn/cellAt methods.
// No engine patching, board mutation or replacement of shared handlers.
import {CELL} from '../tabletop/board.js';

export function installTouch(viewport, board, tap) {
  const pointers = new Map();
  let baseline = null, moved = false, pinched = false;
  const point = e => ({x: e.clientX, y: e.clientY});
  const geometry = () => {
    const rows = [...pointers.values()];
    return {x: rows.reduce((s,p) => s+p.x,0)/rows.length, y: rows.reduce((s,p) => s+p.y,0)/rows.length,
      distance: rows.length > 1 ? Math.hypot(rows[0].x-rows[1].x, rows[0].y-rows[1].y) : 0};
  };
  const pan = (dx,dy) => {
    const rect = viewport.getBoundingClientRect(), v = board.view;
    board.centerOn((rect.width/2-v.x-dx)/(CELL*v.zoom)-.5, (rect.height/2-v.y-dy)/(CELL*v.zoom)-.5);
  };
  function down(e) {
    if (e.pointerType !== 'touch') return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (!pointers.size) { moved = false; pinched = false; }
    pointers.set(e.pointerId, {...point(e), sx:e.clientX, sy:e.clientY});
    if (pointers.size > 1) pinched = true;
    baseline = geometry();
    viewport.setPointerCapture(e.pointerId);
    board.closeHoverCard();
  }
  function move(e) {
    if (!pointers.has(e.pointerId)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const old = pointers.get(e.pointerId);
    if (Math.hypot(e.clientX-old.sx,e.clientY-old.sy)>6) moved = true;
    pointers.set(e.pointerId,{...old,...point(e)});
    const next = geometry();
    if (baseline.distance && next.distance) board.zoomBy(next.distance/baseline.distance, baseline.x, baseline.y);
    viewport.style.setProperty('--play-zoom',board.view.zoom);
    if (moved || pinched) pan(next.x-baseline.x,next.y-baseline.y);
    baseline = next;
  }
  function up(e) {
    if (!pointers.has(e.pointerId)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const old = pointers.get(e.pointerId);
    if (Math.hypot(e.clientX-old.sx,e.clientY-old.sy)>6) moved = true;
    pointers.delete(e.pointerId);
    viewport.releasePointerCapture?.(e.pointerId);
    if (!pointers.size) {
      if (!moved && !pinched && e.type !== 'pointercancel') tap(board.cellAt(e.clientX,e.clientY),point(e));
      baseline = null;
    } else baseline = geometry();
  }
  for (const [name,handler] of [['pointerdown',down],['pointermove',move],['pointerup',up],['pointercancel',up]]) viewport.addEventListener(name,handler,{capture:true,passive:false});
  // Prevent a synthetic click after touch from submitting the same candidate twice.
  const click = e => { if (e.pointerType === 'touch' || e.sourceCapabilities?.firesTouchEvents) { e.preventDefault(); e.stopImmediatePropagation(); } };
  viewport.addEventListener('click',click,true);
  return () => {
    for (const [name,handler] of [['pointerdown',down],['pointermove',move],['pointerup',up],['pointercancel',up]]) viewport.removeEventListener(name,handler,true);
    viewport.removeEventListener('click',click,true);
  };
}
