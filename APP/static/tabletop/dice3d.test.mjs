// node --test APP/static/tabletop/dice3d.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseDiceExpression, rollLocal, cryptoRandomInt, THEMES, createDiceTray, getDieGeometry, restOrientation,
  topFace, tumbleOrientation, expandGroup, faceText, quatRotate, summarizeRoll,
} from './dice3d.js';

const scripted = (values) => { let i = 0; return () => values[i++]; };

test('parseDiceExpression handles the documented forms', () => {
  assert.deepEqual(parseDiceExpression('d20'), { groups: [{ count: 1, sides: 20 }], modifier: 0, mode: 'normal' });
  assert.deepEqual(parseDiceExpression('1d20+5'), { groups: [{ count: 1, sides: 20 }], modifier: 5, mode: 'normal' });
  assert.deepEqual(parseDiceExpression('2d6 + 1d4 - 1'),
    { groups: [{ count: 2, sides: 6 }, { count: 1, sides: 4 }], modifier: -1, mode: 'normal' });
  assert.equal(parseDiceExpression('1d20 adv').mode, 'advantage');
  assert.equal(parseDiceExpression('1d20 dis').mode, 'disadvantage');
  assert.equal(parseDiceExpression('1D20+3 Disadvantage').mode, 'disadvantage');
  assert.deepEqual(parseDiceExpression('d100').groups, [{ count: 1, sides: 100 }]);
  assert.deepEqual(parseDiceExpression('d%').groups, [{ count: 1, sides: 100 }]);
  assert.deepEqual(parseDiceExpression('  4d8  ').groups, [{ count: 4, sides: 8 }]);
  assert.equal(parseDiceExpression('2d6+3').modifier, 3);
  assert.equal(parseDiceExpression('1d20 + 1d4 + 2 adv').mode, 'advantage');
  assert.deepEqual(parseDiceExpression('1d2').groups, [{ count: 1, sides: 2 }]);
  assert.deepEqual(parseDiceExpression('d2 + 1d20').groups, [{ count: 1, sides: 2 }, { count: 1, sides: 20 }]);
});

test('parseDiceExpression rejects invalid input', () => {
  for (const bad of ['', '   ', 'hello', 'd7', '2d', '1d20 5', '5', '1d20 adv dis', '2d20 adv', '1d6 adv',
    '1d20 - 1d4', '0d6', '101d6', '1d20++2', '1d20 +', 'd20x', 42, null]) {
    assert.throws(() => parseDiceExpression(bad), `expected "${bad}" to throw`);
  }
});

test('cryptoRandomInt stays in 1..n and covers every face', () => {
  for (const n of [2, 4, 6, 8, 10, 12, 20, 100]) {
    const seen = new Set();
    for (let i = 0; i < n * 60; i++) {
      const v = cryptoRandomInt(n);
      assert.ok(Number.isInteger(v) && v >= 1 && v <= n, `d${n} gave ${v}`);
      seen.add(v);
    }
    assert.equal(seen.size, n, `d${n} should hit every face`);
  }
  assert.throws(() => cryptoRandomInt(0));
});

test('rollLocal ranges, totals and text', () => {
  for (let i = 0; i < 300; i++) {
    const r = rollLocal('2d6 + 1d4 - 1');
    assert.equal(r.groups.length, 3);
    r.groups.forEach((g, k) => assert.ok(g.value >= 1 && g.value <= (k < 2 ? 6 : 4)));
    assert.equal(r.total, r.groups.reduce((s, g) => s + g.value, 0) - 1);
    const p = rollLocal('d100');
    assert.ok(p.groups[0].value >= 1 && p.groups[0].value <= 100);
  }
  const r = rollLocal('2d6+3', scripted([4, 2]));
  assert.deepEqual(r.groups, [{ sides: 6, value: 4 }, { sides: 6, value: 2 }]);
  assert.equal(r.total, 9);
  assert.equal(r.text, '2d6+3: 4 + 2 + 3 = 9');
  assert.throws(() => rollLocal('1d6', () => 7), /rng returned 7/);
});

test('advantage keeps highest, disadvantage keeps lowest', () => {
  const adv = rollLocal('1d20+5 adv', scripted([4, 17]));
  assert.deepEqual(adv.groups, [{ sides: 20, value: 17 }]);
  assert.deepEqual(adv.discarded, [{ sides: 20, value: 4 }]);
  assert.equal(adv.total, 22);
  const dis = rollLocal('1d20 dis', scripted([15, 3]));
  assert.deepEqual(dis.groups, [{ sides: 20, value: 3 }]);
  assert.deepEqual(dis.discarded, [{ sides: 20, value: 15 }]);
  const bless = rollLocal('1d20 + 1d4 adv', scripted([9, 12, 3]));
  assert.deepEqual(bless.groups, [{ sides: 20, value: 12 }, { sides: 4, value: 3 }]);
  assert.deepEqual(bless.discarded, [{ sides: 20, value: 9 }]);
});

test('geometry: face counts, outward CCW faces, planar faces, labels and opposite sums', () => {
  for (const [sides, faces] of [[2, 2], [4, 4], [6, 6], [8, 8], [10, 10], [12, 12], [20, 20]]) {
    const g = getDieGeometry(sides);
    assert.equal(g.faces.length, faces, `d${sides} face count`);
    const values = g.faces.map((f) => f.value).sort((a, b) => a - b);
    const expected = Array.from({ length: faces }, (_, i) => (sides === 10 ? i : i + 1));
    assert.deepEqual(values, expected, `d${sides} labels`);
    for (const f of g.faces) {
      const P = f.idx.map((i) => g.verts[i]);
      // Newell normal of the vertex order must agree with the outward normal (drives back-face culling)
      const nw = [0, 0, 0];
      P.forEach((a, i) => { const b = P[(i + 1) % P.length]; nw[0] += (a[1] - b[1]) * (a[2] + b[2]); nw[1] += (a[2] - b[2]) * (a[0] + b[0]); nw[2] += (a[0] - b[0]) * (a[1] + b[1]); });
      assert.ok(nw[0] * f.n[0] + nw[1] * f.n[1] + nw[2] * f.n[2] > 0, `d${sides} face ${f.value} winding`);
      for (const p of P) assert.ok(Math.abs(p[0] * f.n[0] + p[1] * f.n[1] + p[2] * f.n[2] - f.d) < 1e-9, 'planar');
      assert.ok(f.font > 0.05, 'label size');
      if (sides !== 4) {
        const opp = g.faces.find((o) => o.n[0] * f.n[0] + o.n[1] * f.n[1] + o.n[2] * f.n[2] < -0.999999);
        assert.equal(f.value + opp.value, sides === 10 ? 9 : sides + 1, `d${sides} opposite of ${f.value}`);
      }
    }
    assert.equal(getDieGeometry(100), getDieGeometry(10), 'd100 reuses the d10 shape');
  }
});

test('rest orientation always shows the requested face, upright and not mirrored', () => {
  for (const sides of [2, 4, 6, 8, 10, 12, 20]) {
    const g = getDieGeometry(sides);
    for (const f of g.faces) {
      for (const yaw of [-0.25, 0, 0.25]) { // tray uses |yaw| <= 0.22
        const q = restOrientation(sides, f.value, { yaw });
        assert.equal(topFace(sides, q), f.value, `d${sides} value ${f.value} yaw ${yaw}`);
        const n = quatRotate(q, f.n), up = quatRotate(q, f.up), right = quatRotate(q, f.right);
        assert.ok(n[2] > 0.75, `d${sides}:${f.value} faces camera (${n[2]})`);
        // the requested face beats every other face by a clear margin
        const others = g.faces.filter((o) => o !== f).map((o) => quatRotate(q, o.n)[2]);
        assert.ok(n[2] - Math.max(...others) > 0.08, `d${sides}:${f.value} margin`);
        // glyph "up" points up the screen (within the small random yaw), whatever the presentation tilt
        assert.ok(up[1] > 0 && Math.abs(Math.atan2(up[0], up[1])) < 0.4, `d${sides}:${f.value} upright (${up})`);
        assert.ok(right[0] > 0.9, `d${sides}:${f.value} not mirrored (${right[0]})`);
      }
    }
  }
});

test('tumble decays to exactly the final orientation', () => {
  const spins = [{ axis: [0.3, -1, 0], angle: 19.1 }, { axis: [1, 1, 1], angle: 5.3 }];
  for (const sides of [2, 4, 6, 8, 10, 12, 20]) {
    for (const f of getDieGeometry(sides).faces) {
      const q = restOrientation(sides, f.value, { yaw: 0.2 });
      assert.deepEqual(tumbleOrientation(q, spins, 1), q);
      assert.equal(topFace(sides, tumbleOrientation(q, spins, 1)), f.value);
      const mid = tumbleOrientation(q, spins, 0.3);
      assert.ok(Math.abs(Math.hypot(...mid) - 1) < 1e-9, 'unit quaternion mid-tumble');
    }
  }
});

test('expandGroup maps caller values onto dice without re-randomising', () => {
  assert.deepEqual(expandGroup({ sides: 20, value: 17 }), [{ shape: 20, face: 17, role: 'plain' }]);
  assert.deepEqual(expandGroup({ sides: 10, value: 10 }), [{ shape: 10, face: 0, role: 'd10' }]);
  assert.equal(faceText('d10', 0), '10');
  for (let v = 1; v <= 100; v++) {
    const [tens, ones] = expandGroup({ sides: 100, value: v });
    assert.equal(tens.role, 'tens');
    assert.equal(ones.role, 'ones');
    const read = Number(faceText('tens', tens.face)) + Number(faceText('ones', ones.face));
    assert.equal(read === 0 ? 100 : read, v, `d100 ${v}`);
    assert.equal(topFace(10, restOrientation(10, tens.face)), tens.face);
    assert.equal(topFace(10, restOrientation(10, ones.face)), ones.face);
  }
  assert.deepEqual(expandGroup({ sides: 100, value: 100 }).map((d) => faceText(d.role, d.face)), ['00', '0']);
  for (const bad of [{ sides: 7, value: 1 }, { sides: 2, value: 3 }, { sides: 6, value: 0 }, { sides: 6, value: 7 }, { sides: 20, value: 2.5 }, { sides: 20 }, null]) {
    assert.throws(() => expandGroup(bad));
  }
});

test('d2 coin: each server-supplied value is the face that shows', () => {
  assert.deepEqual(getDieGeometry(2).faces.map((f) => f.value).sort((a, b) => a - b), [1, 2]);
  for (const value of [1, 2]) {
    for (const yaw of [-0.22, 0, 0.22]) assert.equal(topFace(2, restOrientation(2, value, { yaw })), value, `d2 ${value} yaw ${yaw}`);
  }
  assert.deepEqual(expandGroup({ sides: 2, value: 1 }), [{ shape: 2, face: 1, role: 'plain' }]);
  assert.deepEqual(expandGroup({ sides: 2, value: 2 }), [{ shape: 2, face: 2, role: 'plain' }]);
  assert.equal(faceText('plain', 2), '2');
  assert.throws(() => expandGroup({ sides: 2, value: 0 }), /cannot show 0/);
  assert.throws(() => expandGroup({ sides: 2, value: 3 }), /cannot show 3/);
  assert.deepEqual(rollLocal('1d2', scripted([2])).groups, [{ sides: 2, value: 2 }]);
});

// Minimal DOM and canvas stub: enough for createDiceTray to lay out, animate frame by frame and settle.
function stubTray(options = {}) {
  const frames = [];
  // Canvas 2D context: unknown members are no-op functions, known members are plain values.
  const base = { measureText: (s = '') => ({ width: 8 * String(s).length }) };
  const ctx = new Proxy(base, {
    get: (t, k) => (typeof k === 'symbol' ? undefined : k in t ? t[k] : () => ctx),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  const makeEl = () => ({ className: '', textContent: '', dataset: {}, style: { setProperty() {} }, offsetWidth: 0,
    width: 0, height: 0, parentNode: null, classList: { add() {}, remove() {} }, setAttribute() {},
    appendChild: (c) => c, removeChild() {}, replaceChildren() {}, getContext: () => ctx });
  const doc = { head: makeEl(), body: makeEl(), getElementById: () => null, createElement: makeEl };
  const win = {
    innerWidth: 1280, innerHeight: 800, devicePixelRatio: 1, matchMedia: () => ({ matches: false }),
    requestAnimationFrame: (cb) => { frames.push(cb); return frames.length; }, cancelAnimationFrame() {},
    setTimeout: () => 0, clearTimeout() {},
  };
  doc.defaultView = win;
  const container = { ownerDocument: doc, appendChild: (c) => c };
  return { tray: createDiceTray({ container, durationMs: 200, ...options }), frames };
}

// Drive the normal animation path (requestAnimationFrame ticks) until the roll promise settles.
async function rollThrough({ tray, frames }, groups, meta) {
  const done = tray.roll(groups, meta);
  let now = 0;
  for (let i = 0; frames.length && i < 5000; i++) { now += 16; frames.shift()(now); }
  let timer;
  const stuck = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('roll never settled')), 2000); });
  try { await Promise.race([done, stuck]); } finally { clearTimeout(timer); }
  return tray._snapshot().map((d) => [d.sides, d.requested, d.shown]);
}

test('createDiceTray.roll shows an event-shaped d2 and resolves through the normal path', async () => {
  for (const value of [1, 2]) {
    // Same shape the tabletop event loop passes for a TARGET_INTERCEPT d2 (dice_rows groups plus meta).
    const meta = { label: 'Which target do you hit?', modifier: 0, total: value, kind: 'plain', discarded: [],
      critical: false, fumble: false, mode: 'NORMAL', mode_sources: [] };
    assert.deepEqual(await rollThrough(stubTray(), [{ sides: 2, value }], meta), [[2, String(value), String(value)]]);
  }
  assert.deepEqual(await rollThrough(stubTray(), [{ sides: 20, value: 17 }, { sides: 2, value: 1 }], { kind: 'plain' }),
    [[20, '17', '17'], [2, '1', '1']]);
  assert.deepEqual(await rollThrough(stubTray(), [{ sides: 100, value: 37 }], { kind: 'plain' }),
    [[10, '30', '30'], [10, '7', '7']]);
});

test('createDiceTray.roll still rejects unsupported and out-of-range dice', async () => {
  const { tray } = stubTray();
  await assert.rejects(tray.roll([{ sides: 3, value: 1 }]), /Unsupported die: d3/);
  await assert.rejects(tray.roll([{ sides: 2, value: 3 }]), /d2 cannot show 3/);
});

test('summary text for the result chip', () => {
  const s = summarizeRoll([{ sides: 20, value: 17 }], { label: 'Attack — Dao', modifier: 9, total: 26, kind: 'attack' });
  assert.equal(s.text, 'Attack — Dao · 17 + 9 = 26');
  assert.equal(s.crit, false);
  assert.equal(summarizeRoll([{ sides: 20, value: 20 }], {}).crit, true);
  assert.equal(summarizeRoll([{ sides: 20, value: 1 }], {}).fumble, true);
  assert.equal(summarizeRoll([{ sides: 20, value: 20 }], { critical: false }).crit, false);
  assert.equal(summarizeRoll([{ sides: 6, value: 1 }], {}).fumble, false);
  assert.equal(summarizeRoll([{ sides: 8, value: 3 }], { critical: true }).crit, true);
  assert.equal(summarizeRoll([{ sides: 20, value: 14 }], {}).text, '14');
  assert.equal(summarizeRoll([{ sides: 6, value: 4 }, { sides: 6, value: 2 }], { modifier: -1, kind: 'damage' }).text, 'Damage · 4 + 2 − 1 = 5');
  assert.equal(summarizeRoll([{ sides: 20, value: 17 }], { modifier: 5, discarded: [{ sides: 20, value: 4 }] }).text,
    '17 (dropped 4) + 5 = 22');
});

test('module exports the public API and loads without a DOM', () => {
  assert.equal(typeof createDiceTray, 'function');
  assert.throws(() => createDiceTray(), /DOM/);
  for (const name of ['crimson', 'jade', 'ivory', 'midnight']) {
    for (const key of ['body', 'edge', 'text']) assert.equal(typeof THEMES[name][key], 'string');
  }
});
