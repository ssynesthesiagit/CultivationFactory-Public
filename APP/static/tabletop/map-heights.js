// Shared scenery defaults, also loaded by combat/map_heights.py.
import defaults from './map-heights.json' with {type: 'json'};

export function wallHeightFt(wall = {}) {
  if (wall.height_ft != null) return wall.height_ft;
  if (wall.kind === 'building') return defaults.storey_ft * (wall.storeys ?? 1);
  return defaults.low_ft[wall.kind] ?? defaults.low_ft[wall.look] ?? defaults.wall_ft;
}

export const roofHeightFt = (settings = {}, wallHeight = defaults.wall_ft) =>
  settings.height_ft ?? wallHeight + defaults.roof_rise_ft;

// Mirrors combat/map_heights.py walking_height_ft: standing height is the roof top to the nearest 5 ft, ties up.
export const walkingRoofHeightFt = heightFt => Math.floor((heightFt + 2) / 5) * 5;

export function heightInput(value) {
  if (String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : null;
}

export const wallHeightText = wall => `Wall · ${wallHeightFt(wall)} ft high`;
export const buildingHeightText = region => `Building · ${region.wall_height_ft} ft high`;
export const roofHeightText = settings => `Roof · ${settings.height_ft} ft`;

// Mirrored authoring policy in combat/map_heights.py. Consumers read the
// represented span; they never choose a height by looking at a creature.
export function sceneryHeightFt(row = {}, family) {
  if (Object.hasOwn(row, 'height_ft')) return row.height_ft;
  if (family === 'object') return defaults.object_ft[row.kind] ?? defaults.object_fallback_ft;
  if (family === 'tree') return (defaults.tree_ft[row.look] ?? defaults.tree_ft.broadleaf)
    * (row.size === 2 ? defaults.great_tree_multiplier : 1);
  if (family === 'material') return row.material === 'terrain:bamboo thicket' ? defaults.bamboo_ft : 0;
  if (family === 'terrain') return defaults.terrain_ft[row.look]
    ?? (row.type === 'SIMPLE_COVER' ? defaults.cover_fallback_ft : 0);
  throw Error('Unknown scenery family');
}

export const sceneryBaseFt = (row, family) => family === 'object'
  ? row.altitude_ft ?? (row.z ?? 0) * 5 : row.base_altitude_ft ?? 0;

export function sceneryHeightText(row, family, label = 'Scenery') {
  const height = sceneryHeightFt(row, family), bottom = sceneryBaseFt(row, family);
  return `${label} · ${height} ft high${family === 'object' ? ' above its base' : ''}${bottom ? ` · top ${bottom + height} ft above ground (base ${bottom} ft)` : ''}`;
}

export function authorSceneryHeights(doc) {
  for (const [key, family] of [['objects', 'object'], ['trees', 'tree'], ['terrain', 'terrain'], ['materials', 'material']])
    for (const row of doc[key] || []) {
      if (family === 'material' && row.material !== 'terrain:bamboo thicket') continue;
      if (!Object.hasOwn(row, 'height_ft')) row.height_ft = sceneryHeightFt(row, family);
    }
  return doc;
}
