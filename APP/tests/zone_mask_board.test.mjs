// node --test APP/tests/zone_mask_board.test.mjs
// Drives the real board and records the canvas used by its CSS mask, not a copy
// of zoneMask. This checks drawing geometry; it does not emulate browser blur.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {installDOM} from './objects_dom_stub.mjs';

const boardURL = new URL('../static/tabletop/board.js', import.meta.url);
// Negative control: load only a historical board.js from scratch, with today's
// unchanged dependencies. No checkout mutation or full app copy is needed.
const source = process.env.BOARD_MASK_TEST_SOURCE;
const moduleURL = source ? 'data:text/javascript;base64,' + Buffer.from(
  (await readFile(source, 'utf8')).replace(/from "(\.\/[^\"]+)"/g,
    (_, path) => `from "${new URL(path, boardURL).href}"`)
).toString('base64') : boardURL.href;
const {createBoard, CELL} = await import(moduleURL);

const ring = [];
for (let y = 2; y <= 8; y++) for (let x = 2; x <= 8; x++) {
  if (x === 2 || x === 8 || y === 2 || y === 8) ring.push([x, y]);
}
ring.push([12, 5]); // disconnected island, separated by excluded squares
const thinWall = [[2, 3], [3, 3], [4, 3], [10, 3]];

for (const material of ['darkness', 'haze', 'smoke', 'fog', 'fire', 'bamboo', 'stone']) {
  test(`${material}: real board masks fill full adjacent squares together and preserve empty space`, () => {
    const globals = ['document', 'window', 'history', 'localStorage', 'location', 'confirm',
      'requestAnimationFrame', 'cancelAnimationFrame', 'setInterval', 'setTimeout'];
    const previous = globals.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
    const doc = installDOM('<html><body><div id="v"></div></body></html>');
    const canvases = new Map();
    const create = doc.createElement.bind(doc);
    doc.createElement = tag => {
      const node = create(tag);
      if (tag === 'canvas') {
        const context = node.getContext('2d'), calls = [];
        for (const name of ['beginPath', 'rect', 'fill', 'fillRect']) {
          context[name] = (...args) => calls.push({name, args, filter: context.filter});
        }
        node.getContext = () => context;
        const url = `data:image/png;base64,mask${canvases.size}`;
        node.toDataURL = () => url;
        canvases.set(`url(${url})`, {node, calls});
      }
      return node;
    };
    try {
      const board = createBoard(doc.getElementById('v'));
      board.setMap({width: 16, height: 12, background: {style: 'flagstone', seed: 1},
        walls: [], trees: [], floors: [], cells: {}});
      const wall = material === 'stone';
      const cells = wall ? thinWall : ring;
      board.setZones([{zone_id: 'mask-test', active: true,
        source_definition_id: material === 'bamboo' ? 'system:battlefield.terrain' : 'action:test',
        owner_id: 'map', affected_cells: cells.map(([x, y]) => ({x, y})),
        trigger_profile: {kind: 'TYPED', name: 'Test area', shape: material === 'bamboo' ? 'painted' : 'sphere',
          ...(wall ? {wall: {blocks_movement: true, blocks_sight: true}} : {}),
          visual: {material, darkness: material === 'darkness', wall,
            ...(['haze', 'smoke', 'fog'].includes(material) ? {obscured: 'heavy'} : {})}},
      }], {round: 1});
      const nodes = doc.querySelectorAll('.tt-zone');
      assert.ok(nodes.length > 0, 'setZones attached rendered mask nodes');
      if (wall) assert.ok(doc.querySelector('.tt-zone-wall-shadow'), 'also exercise the wider shadow mask');
      for (const node of nodes) {
        assert.equal(node.style.webkitMaskImage, node.style.maskImage);
        const mask = canvases.get(node.style.maskImage);
        assert.ok(mask, 'CSS uses an actual recorded mask canvas');
        const {calls} = mask;
        assert.equal(calls.filter(c => c.name === 'fillRect').length, 0, 'no separate inset square fills');
        assert.equal(calls.filter(c => c.name === 'beginPath').length, 1);
        assert.equal(calls.filter(c => c.name === 'fill').length, 1, 'blur the combined path only once');
        assert.equal(calls[0].name, 'beginPath');
        assert.equal(calls.at(-1).name, 'fill');
        assert.equal(calls.at(-1).filter, node.classList.contains('tt-zone-wall-shadow') ? 'blur(5px)' : 'blur(3px)');
        const x0 = parseFloat(node.style.left) / CELL, y0 = parseFloat(node.style.top) / CELL;
        const rects = calls.filter(c => c.name === 'rect').map(c => c.args);
        assert.deepEqual(rects, cells.map(([x, y]) => [(x - x0) * 16, (y - y0) * 16, 16, 16]),
          'one path covers exactly the whole included squares, without an inset or bounding-box fill');
        assert.equal(mask.node.width, parseFloat(node.style.width) / CELL * 16);
        assert.equal(mask.node.height, parseFloat(node.style.height) / CELL * 16);
        const covered = (x, y) => rects.some(([rx, ry, w, h]) =>
          x >= rx && x <= rx + w && y >= ry && y <= ry + h);
        const at = (x, y) => [(x - x0) * 16, (y - y0) * 16];
        const [sx, sy] = at(3, wall ? 3.5 : 2.5);
        for (const dx of [-0.1, 0, 0.1]) assert.ok(covered(sx + dx, sy), 'adjacent square seam has no gap');
        assert.equal(covered(...at(wall ? 7.5 : 5.5, wall ? 3.5 : 5.5)), false,
          'widely separated excluded space / ring hole remains unpainted');
      }
    } finally {
      for (const [key, descriptor] of previous) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    }
  });
}
