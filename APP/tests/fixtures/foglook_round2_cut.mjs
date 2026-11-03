// Negative control: rejected round-2 inward raster treatment.
// Fog wash only. Exact sight and explored masks still isolate remembered art,
// tokens and interaction. Narrow dark spikes cannot safely be erased: instead
// inset visible ground to merge their narrow gaps, and soften the enlarged shade.

// Two-pass chamfer distance at 16 pixels/square. Work is linear in map area;
// no per-tree filters or full-resolution pixel readback. Outside the board is
// not a blocker, so fully lit maps do not acquire an artificial dark border.
export function inwardFeather(alpha, width, height, cell, inset = 0.2, feather = 0.8, threshold = 254) {
  const distance = new Float32Array(width * height);
  const diagonal = Math.SQRT2, cap = (inset + feather) * cell + 2;
  for (let i = 0; i < distance.length; i++) distance[i] = alpha[i] < threshold ? 0 : cap;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = y * width + x;
    let d = distance[i];
    if (x) d = Math.min(d, distance[i - 1] + 1);
    if (y) {
      d = Math.min(d, distance[i - width] + 1);
      if (x) d = Math.min(d, distance[i - width - 1] + diagonal);
      if (x + 1 < width) d = Math.min(d, distance[i - width + 1] + diagonal);
    }
    distance[i] = d;
  }
  for (let y = height - 1; y >= 0; y--) for (let x = width - 1; x >= 0; x--) {
    const i = y * width + x;
    let d = distance[i];
    if (x + 1 < width) d = Math.min(d, distance[i + 1] + 1);
    if (y + 1 < height) {
      d = Math.min(d, distance[i + width] + 1);
      if (x) d = Math.min(d, distance[i + width - 1] + diagonal);
      if (x + 1 < width) d = Math.min(d, distance[i + width + 1] + diagonal);
    }
    distance[i] = d;
  }
  const out = new Uint8ClampedArray(distance.length), start = 0.5 + inset * cell, span = feather * cell;
  for (let i = 0; i < out.length; i++) out[i] = 255 * Math.max(0, Math.min(1, (distance[i] - start) / span));
  return out;
}

// Retain only the last current and remembered low-resolution cuts. Hash lookup
// is followed by byte equality: a collision can never reuse another sight mask.
// The full-size scratch is reused and ALWAYS intersected with today's exact
// mask after upsampling, even on a cache hit. No art outside it is lightened.
export function softFogCut(mask, cell, owner, remembered = false) {
  const state = owner.presentation ||= {entries: []};
  const width = Math.ceil(mask.width / 4), height = Math.ceil(mask.height / 4);
  const sample = state.sample ||= document.createElement('canvas');
  if (sample.width !== width || sample.height !== height) {
    sample.width = width; sample.height = height;
  }
  // Let the browser downsample before readback; do not request a CPU canvas
  // that may first have to fetch the full-resolution source texture.
  const s = sample.getContext('2d', {willReadFrequently: false});
  s.clearRect(0, 0, width, height);
  s.drawImage(mask, 0, 0, width, height);
  const pixels = s.getImageData(0, 0, width, height).data;
  const alpha = new Uint8ClampedArray(width * height);
  let hash = 2166136261;
  for (let i = 0; i < alpha.length; i++) {
    alpha[i] = pixels[i * 4 + 3];
    hash = Math.imul(hash ^ alpha[i], 16777619);
  }
  let entry = state.entries.find(e => e.hash === hash && e.width === width && e.height === height &&
    e.cell === cell && e.remembered === remembered && e.alpha.every((a, i) => a === alpha[i]));
  if (!entry) {
    const cut = document.createElement('canvas'); cut.width = width; cut.height = height;
    const c = cut.getContext('2d'), image = c.createImageData(width, height);
    // Memory keeps single-square saved pictures readable. Both bands use the
    // same inward distance pass, with a smaller remembered frontier transition.
    const softened = inwardFeather(alpha, width, height, cell / 4,
      remembered ? 0 : 0.2, remembered ? 0.2 : 0.8, remembered ? 128 : 254);
    for (let i = 0; i < alpha.length; i++) {
      image.data[i * 4] = image.data[i * 4 + 1] = image.data[i * 4 + 2] = 255;
      image.data[i * 4 + 3] = softened[i];
    }
    c.putImageData(image, 0, 0);
    entry = {hash, width, height, cell, remembered, alpha, cut};
    state.entries = [entry, ...state.entries.filter(e => e.remembered !== remembered)].slice(0, 2);
  }
  const full = state.full ||= document.createElement('canvas');
  if (full.width !== mask.width || full.height !== mask.height) {
    full.width = mask.width; full.height = mask.height;
  }
  const c = full.getContext('2d');
  c.globalCompositeOperation = 'source-over';
  c.clearRect(0, 0, full.width, full.height);
  c.drawImage(entry.cut, 0, 0, full.width, full.height);
  c.globalCompositeOperation = 'destination-in';
  c.drawImage(mask, 0, 0);
  c.globalCompositeOperation = 'source-over';
  return full;
}

