import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {sep} from 'node:path';
import {appRoot, flightStaticHandler} from './flight_ui_static_server.mjs';

async function request(url, root = appRoot + sep) {
  const response = {status: 200, headers: {}, setHeader(key, value) { this.headers[key] = value; },
    writeHead(status) { this.status = status; }, end(body) { this.body = String(body || ''); }};
  await flightStaticHandler(root)({url}, response);
  return response;
}

test('trailing-slash APP root serves all entry points and query-keyed modules as JavaScript', async () => {
  for (const name of ['board.js', 'tabletop.js', 'sheet.js', 'flight-ui.js', 'live-stats.mjs']) {
    const response = await request(`/static/tabletop/${name}?v=flightui1`);
    assert.equal(response.status, 200, name);
    assert.equal(response.headers['content-type'], 'text/javascript', name);
    assert.ok(response.body.length > 0, name);
  }
});

test('module smoke pages retain real DOM and defer entry imports to the browser check', async () => {
  for (const name of ['tabletop', 'sheet']) {
    const response = await request(`/module-check/${name}.html`);
    assert.equal(response.status, 200);
    assert.equal(response.headers['content-type'], 'text/html');
    assert.match(response.body, /<!doctype html>/i);
    assert.doesNotMatch(response.body, /<script\b/i);
  }
  assert.equal((await request('/static/tabletop/missing.js')).status, 404);
  // Synthetic traversal target: a sibling file outside the served root.
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'flight-static-'));
  try {
    fs.mkdirSync(path.join(scratch, 'root'));
    fs.writeFileSync(path.join(scratch, 'outside.txt'), 'outside');
    assert.equal((await request('/%2e%2e/outside.txt', path.join(scratch, 'root') + sep)).status, 404);
  } finally {
    fs.rmSync(scratch, {recursive: true, force: true});
  }
});

test('browser JSON module imports receive the required JSON content type', async () => {
  const response = await request('/static/tabletop/map-heights.json');
  assert.equal(response.status, 200);
  assert.equal(response.headers['content-type'], 'application/json');
  assert.equal(JSON.parse(response.body).bamboo_ft, 20);
});
