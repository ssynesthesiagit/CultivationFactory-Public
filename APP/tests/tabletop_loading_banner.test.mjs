import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
test('deferred-menu loading is delayed and only shown for the viewer-controlled creature', () => {
  const start = source.indexOf('async function renderActionBar()');
  const end = source.indexOf('\\n}', start) + 2;
  const render = source.slice(start, end);
  assert.match(render, /waitingForOwnMenu = !app\\.menu && !!app\\.state\\?\\.menu_pending/);
  assert.match(render, /isManualActor\\(current\\) && !automaticSlot\\(current\\)/);
  assert.match(render, /}, 400\\)/, 'quick menu reads must not flash loading');
  assert.match(render, /presentation\\(\\)\\?\\.current_actor_id === actorId/,
    'a delayed timer must not display after the turn changes');
  assert.match(render, /bar\\.replaceChildren\\(\\)/, 'loading remains hidden during the delay');
});
