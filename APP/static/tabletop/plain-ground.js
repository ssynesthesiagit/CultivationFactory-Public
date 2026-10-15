// Plain ground shares one opaque pixel representation between the live board and
// remembered crops. Theme colours are resolved by CSS, not saved as variable names.
export function plainGroundPalette(host, detail = 1) {
  const probe = document.createElement('span');
  host.appendChild(probe);
  const resolve = (expression, fallback) => {
    probe.style.color = expression;
    const color = globalThis.getComputedStyle?.(probe)?.color || fallback;
    const parts = color.match(/[\d.]+/g)?.map(Number);
    // color-mix(in srgb, ...) commonly serializes as color(srgb r g b),
    // whose components are fractions, unlike rgb()'s 0..255 components.
    return parts?.length >= 3 ? parts.slice(0, 3).map(v => color.startsWith('color(srgb ') ? v * 255 : v)
      : fallback.match(/\d+/g).map(Number);
  };
  const base = resolve('var(--floor-1)', 'rgb(34,40,38)');
  const high = resolve('var(--floor-2)', 'rgb(44,50,48)');
  const line = resolve('var(--cf-text)', 'rgb(220,220,220)');
  probe.remove();
  return {base, high, line, contrast: 0.25 + 0.75 * detail};
}

export function paintPlainGround(width, height, pps, palette) {
  const canvas = document.createElement('canvas');
  canvas.width = width * pps; canvas.height = height * pps;
  const context = canvas.getContext('2d');
  const image = context.createImageData(canvas.width, canvas.height);
  // The same 30%/20% radial wash and 64/128 CSS-pixel grid as the original
  // plain backdrop. Area coverage keeps its one-pixel lines at floor resolution.
  const cx = width * 64 * 0.3, cy = height * 64 * 0.2;
  const radius = Math.hypot(width * 64 * 0.7, height * 64 * 0.8) * 0.7;
  const lineCoverage = (p, period) => {
    const lo = p * 64 / pps, hi = (p + 1) * 64 / pps;
    const end = Math.ceil(hi / period) * period;
    return Math.max(0, Math.min(hi, end) - Math.max(lo, end - 1)) / (hi - lo);
  };
  for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
    const wash = Math.max(0, 1 - Math.hypot((x + 0.5) * 64 / pps - cx, (y + 0.5) * 64 / pps - cy) / radius) * palette.contrast;
    const alpha = 1 - (1 - lineCoverage(x, 128) * 0.05) * (1 - lineCoverage(canvas.height - y - 1, 64) * 0.05);
    const i = (y * canvas.width + x) * 4;
    for (let c = 0; c < 3; c++) image.data[i + c] = (palette.base[c] + (palette.high[c] - palette.base[c]) * wash) * (1 - alpha) + palette.line[c] * alpha;
    image.data[i + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  return canvas;
}
