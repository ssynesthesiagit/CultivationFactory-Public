// Natural finite region walls. Presentation only: the arena remains the authority
// for blocked cells and height. Authored architectural wall looks keep their art.
import {rock, seeded, r2} from './art-kit.js?v=sol196p2';

export function regionWallRows(regions = [], walls = []) {
  return regions.filter(row => {
    if (row.terrain_type !== 'BLOCKED' || !(row.height_ft > 0)) return false;
    if (/^(tree\.height\.|roof\.wall\.)/.test(row.region_id || '')) return false;
    const wall = walls.find(w => `wall.height.${w.id}` === row.region_id);
    return !wall?.look || wall.look === 'rock_cliff';
  });
}

export function regionWallIndex(rows = []) {
  const index = new Map();
  for (const row of rows) {
    const cells = new Set((row.cells || []).map(c => Array.isArray(c) ? c.join(',') : `${c.x},${c.y}`));
    for (const key of cells) {
      const [x, y] = key.split(',').map(Number);
      const entry = {type: 'BLOCKED', look: 'rock_cliff', height_ft: row.height_ft,
        seed: seedOf(`${row.region_id || ''}:${x},${y}`),
        edges: [!cells.has(`${x},${y-1}`), !cells.has(`${x+1},${y}`),
          !cells.has(`${x},${y+1}`), !cells.has(`${x-1},${y}`)]};
      if (!index.has(key) || index.get(key).height_ft < entry.height_ft) index.set(key, entry);
    }
  }
  return index;
}

function seedOf(text) {
  let seed = 2166136261;
  for (const c of text) seed = Math.imul(seed ^ c.charCodeAt(0), 16777619);
  return seed >>> 0;
}

// One square is 64 art units. Continuous bedrock joins across interior cells;
// only exposed boundaries get a cap/face. Depth grows with height, capped inside
// the footprint so artwork cannot expose or cover a neighbouring fog square.
export function regionWallCellMarkup(entry) {
  const rand = seeded(entry.seed), [north, east, south, west] = entry.edges;
  const depth = r2(Math.min(28, Math.max(3, entry.height_ft * 1.2)));
  let art = '<rect width="64" height="64" fill="#7c776d"/>';
  for (let i = 0; i < 4; i++) art += rock(rand()*64, rand()*64, 18+rand()*16,
    Math.floor(rand()*0xffffffff), 'grey', {shadow: false, squash: .7+rand()*.3});
  if (south) art += `<path class="tt-cliff-face" d="M0 ${64-depth}L64 ${64-depth}V64H0Z" fill="#4f4b45"/>`
    + `<path d="M0 ${64-depth}H64" stroke="#e3ddcb" stroke-width="1.5"/>`;
  if (east) art += `<path class="tt-cliff-face" d="M${64-depth*.6} 0H64V64L${64-depth*.6} ${64-depth}Z" fill="#5c574f"/>`;
  // Broken vertical strata vary per square, rather than a repeating wall pattern.
  if (south || east) for (let i = 0; i < 4; i++) {
    const x = r2(rand()*64), y = r2(64-depth);
    if (south) art += `<path d="M${x} ${y}l${r2(rand()*6-3)} ${depth}" stroke="#302d28" stroke-width="${r2(.6+rand())}"/>`;
  }
  if (north) art += '<path class="tt-cliff-top-edge" d="M0 1H64" stroke="#e3ddcb" stroke-width="2"/>';
  if (west) art += '<path class="tt-cliff-top-edge" d="M1 0V64" stroke="#b4ae9f" stroke-width="2"/>';
  return `<svg class="tt-region-cliff" data-height-ft="${entry.height_ft}" data-face-depth="${depth}" width="64" height="64" viewBox="0 0 64 64" overflow="hidden"><title>Rock cliff, ${entry.height_ft} feet high. Blocks sight and movement below its top.</title>${art}</svg>`;
}
