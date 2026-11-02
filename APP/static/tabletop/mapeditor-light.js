// Editor-only preview of authored lighting. Combat levels still come exclusively from the server.
const levels = {bright: 2, dim: 1, dark: 0};
const times = {day: 2, dawn: 1, dusk: 1, night: 0, underground: 0};

export function editorLightPreview(doc) {
  const {width_squares: width, height_squares: height} = doc;
  const ambient = doc.ambient || {};
  const cells = new Uint8Array(width * height).fill(
    ambient.level == null ? (times[ambient.time_of_day] ?? 2) : (levels[ambient.level] ?? ambient.level));
  for (const region of doc.ambient_regions || []) {
    const value = levels[region.level] ?? region.level;
    for (const [x, y] of region.cells || []) if (x >= 0 && y >= 0 && x < width && y < height) cells[y * width + x] = value;
  }
  const packed = new Uint8Array(Math.ceil(cells.length / 4));
  cells.forEach((value, index) => { packed[Math.floor(index / 4)] |= (value & 3) << ((index % 4) * 2); });
  let binary = "";
  for (const byte of packed) binary += String.fromCharCode(byte);
  const sources = (doc.lights || []).filter(light => light.lit !== false).map(light => ({
    x: light.x, y: light.y, bright_ft: light.bright_ft, dim_ft: light.dim_ft, color: light.color,
  }));
  return {cells: btoa(binary), sources};
}

