// Painting map scenery (trees, decoration) as bitmaps (SOL196 review; owner: speed is a top priority). A 150-tree map
// is tens of thousands of SVG shapes; as live SVG the browser re-rasterizes all of them on every zoom and pan frame and
// the map editor rebuilt them on every edit. Here each distinct drawing (a kind of tree, a decoration piece) is
// rasterized once into a small sprite bitmap, kept in a bounded cache, and stamped onto one layer canvas wherever it
// stands; a layer whose content (its key) is unchanged is not redrawn. Zooming and panning only scale a bitmap.
// Without a browser image decoder (Node tests), or when decoding fails, the layer is drawn as live SVG instead.
const SVG_NS = "http://www.w3.org/2000/svg";

export function rasterSupported(win = globalThis) {
  return typeof win.Image === "function" && typeof win.Blob === "function" && typeof win.URL?.createObjectURL === "function"
    && typeof win.document?.createElement === "function";
}

// ---------------------------------------------------------------- the sprite cache (bounded, least recently used)
// Sprites are kept by drawing and resolution; resolutions are snapped to powers of two so maps of different sizes share
// them. When the cached pixels pass the byte limit, the least recently used sprites are dropped (a dropped sprite is
// simply drawn again the next time a map needs it). A failed sprite is never kept, so a later draw retries it.
let limitBytes = 96 * 1024 * 1024;
const sprites = new Map();  // key -> {promise, bytes}; Map order is recency (oldest first)
let cachedBytes = 0;

export function setSpriteCacheLimit(bytes) { limitBytes = bytes; trim(); }
export function spriteCacheStats() { return {entries: sprites.size, bytes: cachedBytes, limit: limitBytes}; }
export function clearSpriteCache() { sprites.clear(); cachedBytes = 0; }

function trim(keep = null) {
  for (const [key, entry] of sprites) {
    if (cachedBytes <= limitBytes) break;
    if (key === keep || !entry.bytes) continue;
    sprites.delete(key);
    cachedBytes -= entry.bytes;
  }
}

export const snapPixels = ppc => 2 ** Math.max(4, Math.min(7, Math.floor(Math.log2(Math.max(16, ppc)))));

function sprite(win, doc, id, markup, box, ppc) {
  const key = `${id}@${ppc}`;
  const hit = sprites.get(key);
  if (hit) { sprites.delete(key); sprites.set(key, hit); return hit.promise; }  // most recently used
  const [x0, y0, w, h] = box;
  const entry = {bytes: 0};
  entry.promise = new Promise(resolve => {
    const width = Math.ceil(w * ppc), height = Math.ceil(h * ppc);
    const text = `<svg xmlns="${SVG_NS}" viewBox="${x0} ${y0} ${w} ${h}" width="${width}" height="${height}">${markup}</svg>`;
    const url = win.URL.createObjectURL(new win.Blob([text], {type: "image/svg+xml"}));
    const image = new win.Image();
    const fail = () => {
      win.URL.revokeObjectURL(url);
      if (sprites.get(key) === entry) sprites.delete(key);  // never keep a failure: the next draw retries
      resolve(null);
    };
    image.onload = () => {
      try {
        win.URL.revokeObjectURL(url);
        const canvas = doc.createElement("canvas");
        canvas.width = width; canvas.height = height;
        canvas.getContext("2d").drawImage(image, 0, 0);
        if (sprites.get(key) === entry) { entry.bytes = width * height * 4; cachedBytes += entry.bytes; trim(key); }
        resolve({canvas, box});
      } catch { fail(); }
    };
    image.onerror = fail;
    image.src = url;
  });
  sprites.set(key, entry);
  return entry.promise;
}

// ---------------------------------------------------------------- one layer
// scene: {shapes: Map(id -> {markup, box: [x0, y0, w, h] in squares around the placement}), placements: [{id, x, y,
// rotation}], fallback(): the same scene as one live-SVG string}. bounds: [x0, y0, w, h] in squares; key: identifies
// the content. parent/before place the layer canvas; svgLayer is the live-SVG layer (cell-unit viewBox).
export function createSpriteLayer(doc, parent, before, className, svgLayer, cellPx, {retryMs = 2000, retries = 3} = {}) {
  let lastKey = null, token = 0;
  const win = doc.defaultView || globalThis;
  const raster = rasterSupported(win) && typeof parent.insertBefore === "function";
  let canvas = null;
  if (raster) {
    canvas = doc.createElement("canvas");
    canvas.className = `tt-layer ${className}`;
    Object.assign(canvas.style, {position: "absolute", inset: "auto", pointerEvents: "none"});
    canvas.hidden = true;
    parent.insertBefore(canvas, before);
  }
  const layer = {
    canvas,
    // Returns true when the layer was (re)drawn, false when the content was unchanged.
    draw(scene, bounds, key, attempt = 0) {
      if (key === lastKey && attempt === 0) return false;
      lastKey = key;
      const mine = ++token;
      if (!scene || !scene.placements.length) { if (canvas) canvas.hidden = true; svgLayer.replaceChildren(); return true; }
      if (!raster) { svgLayer.innerHTML = scene.fallback(); return true; }
      canvas.dataset.pending = "1";
      const [bx, by, bw, bh] = bounds;
      const ppc = snapPixels(Math.min(cellPx * Math.min(2, win.devicePixelRatio || 1), Math.floor(Math.sqrt(24e6 / (bw * bh)))));
      const ids = [...new Set(scene.placements.map(p => p.id))];
      Promise.all(ids.map(id => sprite(win, doc, id, scene.shapes.get(id).markup, scene.shapes.get(id).box, ppc))).then(done => {
        if (mine !== token) return;  // a newer draw replaced this one
        delete canvas.dataset.pending;
        if (done.some(s => !s)) {
          // A drawing failed to decode: show the whole layer as live SVG so nothing on the map goes missing, and try the
          // bitmaps again a little later (failed sprites were not cached).
          canvas.hidden = true;
          svgLayer.innerHTML = scene.fallback();
          canvas.dataset.fallback = String(mine);
          if (attempt < retries) win.setTimeout?.(() => { if (mine === token) layer.draw(scene, bounds, key, attempt + 1); }, retryMs);
          return;
        }
        const byId = new Map(ids.map((id, i) => [id, done[i]]));
        canvas.width = Math.round(bw * ppc); canvas.height = Math.round(bh * ppc);
        const context = canvas.getContext("2d");
        context.clearRect(0, 0, canvas.width, canvas.height);
        for (const {id, x, y, rotation = 0} of scene.placements) {
          const [x0, y0, w, h] = byId.get(id).box;
          context.save();
          context.translate((x - bx) * ppc, (y - by) * ppc);
          if (rotation) { context.translate(0.5 * ppc, 0.5 * ppc); context.rotate(rotation * Math.PI / 180); context.translate(-0.5 * ppc, -0.5 * ppc); }
          context.drawImage(byId.get(id).canvas, x0 * ppc, y0 * ppc, w * ppc, h * ppc);
          context.restore();
        }
        svgLayer.replaceChildren();
        Object.assign(canvas.style, {left: `${bx * cellPx}px`, top: `${by * cellPx}px`, width: `${bw * cellPx}px`, height: `${bh * cellPx}px`});
        canvas.hidden = false;
        delete canvas.dataset.fallback;
        canvas.dataset.ready = String(mine);
      });
      return true;
    },
  };
  return layer;
}
