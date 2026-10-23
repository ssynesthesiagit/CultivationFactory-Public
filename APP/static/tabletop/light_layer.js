// Client-only presentation of the server's resolved light field. It never derives sight or light.
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
