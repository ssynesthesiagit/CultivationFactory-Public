// Client-only presentation of the server's resolved light field. It never derives sight or light.
// The field a shared view shows is the union of the selected viewers' fields: a square is lit when any selected
// viewer's own field lights it. Taking the maximum per square (2-bit levels) makes the answer independent of the
// order the viewers were listed in, instead of whichever creature happened to come first.
export function combineLightPayloads(payloads) {
  const list = (payloads || []).filter(Boolean);
  if (list.length <= 1) return list[0] || null;
  const arrays = list.map(payload => Uint8Array.from(atob(payload.cells || ""), char => char.charCodeAt(0)));
  const length = arrays[0].length;
  if (arrays.some(bytes => bytes.length !== length)) throw new Error("Light fields differ in size.");
  const out = new Uint8Array(length);
  for (let i = 0; i < length; i++) {
    let byte = 0;
    for (let lane = 0; lane < 4; lane++) {
      let best = 0;
      for (const bytes of arrays) best = Math.max(best, (bytes[i] >> (2 * lane)) & 3);
      byte |= best << (2 * lane);
    }
    out[i] = byte;
  }
  let binary = "";
  for (const byte of out) binary += String.fromCharCode(byte);
  return {...list[0], by: null, cells: btoa(binary)};
}

export function decodeLightCells(encoded, count) {
  const bytes = Uint8Array.from(atob(encoded || ""), char => char.charCodeAt(0));
  if (bytes.length !== Math.ceil(count / 4)) throw new Error("Invalid light field size.");
  return Uint8Array.from({length: count}, (_, i) => (bytes[Math.floor(i / 4)] >> (2 * (i % 4))) & 3);
}

export function paintLight(context, width, height, cells, sources = [], {
  cellSize = 64, darknessPct = 62, dimPct = 26, perceived = null, gm = false, clipSources = true,
} = {}) {
  const pixelWidth = width * cellSize, pixelHeight = height * cellSize;
  context.clearRect(0, 0, pixelWidth, pixelHeight);
  // Source glows must stay within both the server-resolved light field and the viewer's
  // perceived cells. Gradients are presentation only; neither may expose a hidden cell.
  if (clipSources) {
    context.save();
    context.beginPath();
    for (let i = 0; i < width * height; i++) {
      if ((perceived && !perceived[i]) || !(cells?.[i] > 0)) continue;
      context.rect((i % width) * cellSize, Math.floor(i / width) * cellSize, cellSize, cellSize);
    }
    context.clip();
  }
  for (const source of sources || []) {
    if (!Number.isFinite(source.x) || !Number.isFinite(source.y)) continue;
    const radius = Math.max(0, Number(source.dim_ft) / 5);
    if (!radius) continue;
    const cx = (source.x + .5) * cellSize, cy = (source.y + .5) * cellSize;
    const gradient = context.createRadialGradient(cx, cy, 0, cx, cy, radius * cellSize);
    const color = source.color || "#fff1c4";
    gradient.addColorStop(0, color);
    gradient.addColorStop(Math.min(1, Number(source.bright_ft || 0) / Math.max(1, Number(source.dim_ft))), color);
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    context.globalCompositeOperation = "screen";
    context.globalAlpha = .2;
    context.fillStyle = gradient;
    context.fillRect(cx - radius * cellSize, cy - radius * cellSize, radius * 2 * cellSize, radius * 2 * cellSize);
  }
  if (clipSources) context.restore();
  context.globalAlpha = 1;
  // Shade only currently perceived cells. Unseen cells retain the existing fog/explored image.
  context.globalCompositeOperation = "source-over";
  context.filter = `blur(${cellSize / 8}px)`;
  for (let i = 0; i < width * height; i++) {
    if (perceived && !perceived[i]) continue;
    const level = cells?.[i] ?? (gm ? 2 : 0);
    if (level >= 2) continue;
    context.fillStyle = level === 1 ? `rgba(0,0,0,${dimPct / 100})` : `rgba(0,0,0,${darknessPct / 100})`;
    context.fillRect((i % width) * cellSize, Math.floor(i / width) * cellSize, cellSize, cellSize);
  }
  context.filter = "none";
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = 1;
}
