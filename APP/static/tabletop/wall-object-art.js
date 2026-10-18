// Destructible masonry and earth ramparts share the filled-wall painter's tiles.
// Geometry is visual only: one full cell per object, no merged tokens or rules.
// Missing/destroyed neighbours expose an edge; destroyed cells never receive fill.
import {wallPatternDefs, wallLook} from './wall-art.js?v=sol214';

const styles = {wall_section: 'grey_brick', sandbag_wall: 'rammed_earth'};
const directions = [['w', -1, 0], ['n', 0, -1], ['e', 1, 0], ['s', 0, 1]];
const destroyed = row => row.destroyed || String(row.state).toLowerCase() === 'destroyed' || row.hp === 0;
const patterns = new Map();
for (const markup of wallPatternDefs().matchAll(/<pattern\b[^>]*>.*?<\/pattern>/g)) {
  const look = /id="tt-wall-pat-([^"]+?)(?:-v)?"/.exec(markup[0])[1];
  patterns.set(look, (patterns.get(look) || '') + markup[0]);
}
let serial = 0;

// Called once per board update, for editor and table alike. Authored map objects
// determine the course axis, even after a breach or on a fresh/fogged board.
// Only visible, surviving tokens determine fill and joined edges. Without map
// geometry, use all supplied object tokens (including hidden/destroyed rows).
// Hidden, displaced or scaled props retain their ordinary art.
export function wallObjectArt(objects, authoredObjects = []) {
  const fullCell = row => Object.hasOwn(styles, row.kind)
    && !row.shared && !(Number(row.offsetX) || Number(row.offsetY)) && (!row.scale || row.scale === 1);
  const objectRows = objects.filter(row => row.object && fullCell(row));
  const rows = objectRows.filter(row => !row.hidden);
  const lookOf = row => wallLook(row) || styles[row.kind];
  const index = rows => new Map(rows.map(row => [`${row.x},${row.y},${lookOf(row)}`, row]));
  const cells = index(rows), layoutCells = index(objectRows), authoredCells = index(authoredObjects.filter(fullCell));
  const art = new Map();
  for (const row of rows) {
    const {x, y} = row, look = lookOf(row), prefix = `ttwo${++serial}`;
    const neighbours = directions.map(([dir, dx, dy]) => [dir, cells.get(`${x + dx},${y + dy},${look}`)]);
    // Never infer an authored wall's axis from its surviving/visible neighbours.
    const key = `${x},${y},${look}`, geometry = authoredCells.has(key) ? authoredCells : layoutCells;
    const source = geometry.get(key) || row;
    const adjacent = directions.filter(([, dx, dy]) => geometry.has(`${x + dx},${y + dy},${look}`));
    const vertical = adjacent.filter(([dir]) => dir === 'n' || dir === 's').length;
    const horizontal = adjacent.filter(([dir]) => dir === 'w' || dir === 'e').length;
    const axis = vertical > horizontal || (!vertical && !horizontal && (Number(source.rotation) % 180 === 90 || ['north', 'south'].includes(source.facing))) ? 'v' : 'h';
    const edges = neighbours.filter(([, other]) => !other || destroyed(other)).map(([dir]) => dir).join('');
    let body;
    if (destroyed(row)) {
      body = `<g data-wall-rubble="1" style="fill:#8a8478;stroke:#4a463f;stroke-width:.015"><polygon points="${x+.15},${y+.65} ${x+.3},${y+.43} ${x+.48},${y+.63}"/><polygon points="${x+.58},${y+.46} ${x+.75},${y+.38} ${x+.84},${y+.56}"/></g>`;
    } else {
      // Inline styles also protect this unit-space SVG from legacy object-icon CSS.
      const defs = patterns.get(look).replaceAll('tt-wall-pat-', `${prefix}-`)
        .replace(/<(rect|path) ([^>]+)\/>/g, (_, tag, attrs) => {
          const paint = [...attrs.matchAll(/(fill|stroke|stroke-width)="([^"]+)"/g)].map(m => `${m[1]}:${m[2]}`).join(';');
          return `<${tag} ${attrs} style="${paint}"/>`;
        });
      const lines = {w: `M${x} ${y}v1`, n: `M${x} ${y}h1`, e: `M${x+1} ${y}v1`, s: `M${x} ${y+1}h1`};
      body = `<defs>${defs}</defs><rect x="${x}" y="${y}" width="1" height="1" style="fill:url(#${prefix}-${look}${axis === 'v' ? '-v' : ''});stroke:none"/>`
        + `<path d="${[...edges].map(dir => lines[dir]).join('')}" style="fill:none;stroke:#3e3b36;stroke-width:.025;stroke-linecap:butt;stroke-linejoin:miter"/>`;
    }
    art.set(row.id, `<svg viewBox="${x} ${y} 1 1" aria-hidden="true" class="tt-object-art tt-wall-object-art" data-wall-axis="${axis}" data-wall-edges="${edges}">${body}</svg>`);
  }
  return art;
}
