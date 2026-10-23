// A lane audit consumes its diff against the integrated base, never permanent
// hashes of shared files. Authorized future desktop changes don't break /play.
import test from 'node:test';
import assert from 'node:assert/strict';
export function assertMobileLaneDiff(paths) {
  const shared = paths.filter(path => (path.startsWith('APP/static/') && !path.startsWith('APP/static/play/'))
    || (path.startsWith('APP/tests/') && !/^APP\/tests\/(?:test_)?mobile_play/.test(path)
      && path !== 'APP/tests/fixtures/mobile_play_desktop_baseline.json'));
  assert.deepEqual(shared, [], `Phone lane changed desktop files: ${shared.join(', ')}`);
}

test('desktop guard audits lane paths without freezing main desktop contents', () => {
  assertMobileLaneDiff(['APP/static/play/play-client.js', 'APP/tests/mobile_play.test.mjs', 'APP/app/api.py']);
  for (const path of ['APP/static/tabletop/tabletop.js', 'APP/static/tabletop/sheet.js', 'APP/tests/tabletop_target_selection.test.mjs',
    'APP/tests/viewer_identity.test.mjs', 'APP/static/app.css'])
    assert.throws(() => assertMobileLaneDiff([path]), /Phone lane changed desktop files/);
});
