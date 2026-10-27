// Shared board/editor hover entries built once per map; no sight evaluation.
import {wallCells} from './vision.js?v=rel6-2';
import {wallHeightText, buildingHeightText, roofHeightText, sceneryHeightText,
  sceneryHeightFt, sceneryBaseFt} from './map-heights.js';
import {roofSettings} from './roof-regions.js?v=rel6-2';

// Match the represented span: the base is included and the top is excluded.
function effectHeightText(row, family, effect, zeroEffect) {
  const height = sceneryHeightFt(row, family), base = sceneryBaseFt(row, family);
  return height === 0 ? `Zero height: ${zeroEffect}.`
    : `${effect} from ${base} ft up to, but not including, ${base + height} ft above ground.`;
}

export function indexHeightCards(map, regions) {
  const index = new Map();
  function add(key, card) {
    if (!index.has(key)) index.set(key, []);
    const cards = index.get(key);
    if (!cards.some(c => c.title === card.title)) cards.push(card);
  }
  for (const wall of map.walls || []) for (const i of wallCells(wall, map.width, map.height))
    add(`${i % map.width},${Math.floor(i / map.width)}`, {title: wallHeightText(wall),
      lines: [wall.blocks === 'sight' ? 'Blocks sight up to this height; you can walk through it.' :
        'Blocks sight and movement up to this height.']});
  for (const tree of map.trees || []) {
    for (let dx = 0; dx < (tree.size || 1); dx++) for (let dy = 0; dy < (tree.size || 1); dy++)
      add(`${tree.x + dx},${tree.y + dy}`, {title: sceneryHeightText(tree, 'tree',
        `Tree (${(tree.look || 'broadleaf').replaceAll('_', ' ')})`),
        lines: [effectHeightText(tree, 'tree', 'The trunk blocks sight and movement',
          'this trunk does not block sight or movement') + ' The canopy is only a drawing.']});
  }
  for (const row of map.ruleTerrain || map.terrain || []) for (const [x, y] of row.cells || [])
    add(`${x},${y}`, {title: sceneryHeightText(row, 'terrain', row.look?.replaceAll('_', ' ') ||
      (row.type === 'SIMPLE_COVER' ? 'Cover' : 'Ground terrain')),
      lines: [row.type === 'SIMPLE_COVER' ? effectHeightText(row, 'terrain', 'Provides cover to a line passing',
        'this scenery provides no cover') : 'Height of this terrain above its base.']});
  for (const row of map.materials || []) if (row.material === 'terrain:bamboo thicket')
    for (const [x, y] of row.cells || []) add(`${x},${y}`, {title: sceneryHeightText(row, 'material', 'Bamboo thicket'),
      lines: [effectHeightText(row, 'material', 'Dense stands block sight',
        'this bamboo does not block sight') + ' Bamboo can be walked through.']});
  for (const region of regions) {
    const settings = roofSettings(region, map.roofs);
    for (const key of region.inside) {
      add(key, {title: buildingHeightText(region), lines: ['Height of the building walls above the ground.']});
      if (settings.enabled) add(key, {title: roofHeightText(settings),
        lines: ['Roof top above the ground. From above, the roof hides the room beneath it.']});
    }
  }
  return index;
}
