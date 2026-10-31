// Sight-time map scenery for board.js and tabletop.js fog memory. Creature
// tokens, zones and fog are deliberately absent. Records contain JSON strings
// so persistence never retains DOM nodes or references to a changing map.
import {treeScene} from './tree-art.js?v=sol196r1';
import {decorScene} from './decor-art.js?v=sol196r1';

export function sceneryIndex(map) {
  const cells = new Map();
  const add = (kind, row, [left, top, right, bottom]) => {
    for (let y = Math.max(0, Math.floor(top)); y < Math.min(map.height, Math.ceil(bottom)); y++)
      for (let x = Math.max(0, Math.floor(left)); x < Math.min(map.width, Math.ceil(right)); x++) {
        const key = `${x},${y}`;
        if (!cells.has(key)) cells.set(key, {trees: [], decor: [], walls: []});
        cells.get(key)[kind].push(row);
      }
  };
  for (const tree of map.trees || []) {
    const size = tree.size === 2 ? 2 : 1;
    // Same generous crown/shadow bounds as treeScene's sprite, including
    // overhang into a square that does not contain the tree's trunk.
    add('trees', tree, [tree.x - 3, tree.y - 3, tree.x + size + 3, tree.y + size + 3]);
  }
  for (const row of map.decor || []) add('decor', row, [row.x - 0.5, row.y - 0.5, row.x + 1.5, row.y + 1.5]);
  for (const wall of map.walls || []) {
    const points = wall.points || [];
    if (!points.length) continue;
    let xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    if (wall.shape === 'circle' && points.length >= 2) {
      const [[x, y], [ex, ey]] = points, r = Math.hypot(ex - x, ey - y);
      xs = [x - r, x + r]; ys = [y - r, y + r];
    }
    add('walls', wall, [Math.min(...xs) - 0.5, Math.min(...ys) - 0.5, Math.max(...xs) + 0.5, Math.max(...ys) + 0.5]);
  }
  return new Map([...cells].map(([key, value]) => [key, JSON.stringify(value)]));
}

export function readScenery(record) {
  try {
    const scene = JSON.parse(record);
    return scene && ['trees', 'decor', 'walls'].every(key => Array.isArray(scene[key])) ? scene : null;
  } catch { return null; }
}

// Generated SVG ids must belong to this remembered drawing, not a current map
// or prop whose painter happened to reuse an id after reload.
export function namespaceSvg(markup, prefix) {
  return markup.replace(/\bid="([^"]+)"/g, (_match, id) => `id="${prefix}-${id}"`)
    .replace(/url\(#([^)]+)\)/g, (_match, id) => `url(#${prefix}-${id})`)
    .replace(/\bhref="#([^"]+)"/g, (_match, id) => `href="#${prefix}-${id}"`);
}

// Use the live painters, including contact shadows. Register each sprite once
// per remembered layer and reference it from clipped cells: copying an entire
// tree into every square of its generous shadow bounds would multiply the DOM.
function sceneMarkup(scene, kind, register) {
  return scene.placements.map(({id, x, y, rotation = 0}) =>
    `<g transform="translate(${x} ${y})${rotation ? ` rotate(${rotation} .5 .5)` : ''}"><use href="#${register(`${kind}:${id}`, scene.shapes.get(id).markup)}"/></g>`).join('');
}
export function sceneryMarkup(scene, register) {
  return {decor: sceneMarkup(decorScene(scene.decor), 'decor', register), trees: sceneMarkup(treeScene(scene.trees), 'tree', register)};
}
