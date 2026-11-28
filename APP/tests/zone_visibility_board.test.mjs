import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {readFile} from 'node:fs/promises';
import {zoneLook} from '../static/tabletop/zones.js';
import {map, zones} from './zone_visibility_fixture.mjs';
const boardURL = new URL('../static/tabletop/board.js', import.meta.url);
// Negative control against a historical board without changing the checkout.
const base = process.env.SOL144_BOARD_SOURCE;
const source = base && await readFile(base, 'utf8');
const moduleURL = base ? 'data:text/javascript;base64,' + Buffer.from(source.replace(/from "(\.\/[^\"]+)"/g,
  (_, path) => `from "${new URL(path, boardURL).href}"`)).toString('base64') : boardURL.href;
const {createBoard, CELL} = await import(moduleURL);

for (const reverse of [false, true]) test(`overlapping cloud/darkness art and hover, reverse=${reverse}`, async () => {
  const doc = installDOM('<html><body><div id="v"></div></body></html>');
  const viewport = doc.getElementById('v'), board = createBoard(viewport);
  board.setMap(map);
  board.setZones(reverse ? [...zones].reverse() : zones, {round: 4});
  assert.equal(zoneLook(zones.find(z => z.zone_id === 'dust')).material, 'dust', 'dust retains its own material');
  board.fit();
  const air = doc.querySelector('.tt-zones-clouds'), dark = doc.querySelector('.tt-zones-air'), fog = doc.querySelector('.tt-fog');
  assert.ok(air, 'perceived cloud band exists');
  assert.ok(air.parentNode.children.indexOf(air) > air.parentNode.children.indexOf(fog), 'perceived art above fog wash');
  assert.equal(air.style.isolation, 'isolate', 'air ordering cannot cover token band');
  assert.equal(dark.querySelector('.is-dark').style.zIndex, '0');
  assert.ok(dark.parentNode.children.indexOf(dark) < air.parentNode.children.indexOf(air), 'cloud band above darkness');
  for (const level of ['light', 'heavy']) {
    const cloud = air.querySelector(`.is-${level}`);
    assert.ok(cloud, `${level} cloud retains separate material art`);
    assert.equal(cloud.style.zIndex, '1', 'cloud above darkness independent of arrival order');
    assert.ok(cloud.style.maskImage.startsWith('url('), 'merged cloud mask retained');
  }
  const seen = new Uint8Array(64); seen[3 * 8 + 3] = 1;
  board.setFog(seen, null, {squareFog: true});
  assert.ok(air.style.maskImage.startsWith('url('), 'clip art to engine-perceived cells');
  assert.equal(air.style.webkitMaskImage, air.style.maskImage);
  for (const prefix of ['', 'webkit']) {
    const property = name => prefix ? prefix + name : name[0].toLowerCase() + name.slice(1);
    assert.equal(air.style[property('MaskSize')], '100% 100%');
    assert.equal(air.style[property('MaskRepeat')], 'no-repeat');
    assert.equal(air.style[property('MaskPosition')], '0 0');
  }
  const hover = async (x, y) => {
    const callbacks = [], before = globalThis.setTimeout;
    globalThis.setTimeout = callback => {callbacks.push(callback); return callbacks.length;};
    try {
      const v = board.view, event = {clientX: v.x + (x + .5) * CELL * v.zoom,
        clientY: v.y + (y + .5) * CELL * v.zoom, buttons: 0, target: viewport};
      await doc.dispatch('pointermove', event);
      await viewport.dispatch('pointermove', event);
      for (const callback of callbacks) callback();
    } finally {globalThis.setTimeout = before;}
    const card = doc.querySelector('.tt-hovercard');
    if (card.hidden) return '';
    return card.querySelectorAll('.tt-zone-tip-item').map(item => item.textContent + item.children.map(child => child.textContent).join(' | ')).join('\n');
  };
  const hidden = await hover(4, 3);
  // Main's GATETIP1 explicitly permits the known cause of an unseen square.
  // It does not authorize current zone state, or non-obscuring zones there.
  assert.match(hidden, /You can't see in here: (Smoke Veil|Darkness)/);
  assert.doesNotMatch(hidden, /Dust Cloud|Airborne dust|rounds left|Concentration|miss chance/,
    'hidden cells disclose only their known cause, not live zone details');
  assert.equal(await hover(7, 7), '', 'a hidden square without a known cause reveals nothing');
  const text = await hover(3, 3);
  for (const name of ['Dust Cloud', 'Smoke Veil', 'Darkness', 'Cloud caster', '7 rounds left', 'Concentration']) assert.ok(text.includes(name), name);
  assert.match(text, /17% miss chance \(concealment\)/);
  assert.match(text, /43% miss chance \(total concealment\)/);
  assert.match(text, /can't see have Disadvantage/);
  assert.doesNotMatch(text, /Ended cloud/);
  board.setFog(null);
  assert.equal(air.style.maskImage, 'none', 'off view clears perception clipping');
  assert.match(await hover(4, 3), /Dust Cloud/);
});
