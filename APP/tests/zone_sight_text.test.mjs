import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {zoneLook, zoneTooltip} from '../static/tabletop/zones.js';

const policy = JSON.parse(readFileSync(new URL('../combat/rules/targeting.json', import.meta.url)));
const text = (profile, rules) => zoneTooltip({trigger_profile: profile, sight_rules: rules},
  zoneLook({trigger_profile: profile})).lines.join('\n');

test('fallback uses mechanical metadata and current targeting policy', () => {
  for (const profile of [{obscured: 'light'}, {lightly_obscured: true}, {visual: {light: 'dim'}}]) {
    const value = text(profile, policy);
    assert.match(value, /creatures inside are still visible/);
    if (policy.concealment_miss_percent) assert.ok(value.includes(`${policy.concealment_miss_percent}% miss chance`));
    assert.match(value, /without sight.*within their range/);
  }
  const heavy = text({obscured: 'heavy', owner_sees: true, team_sees: true}, policy);
  if (policy.total_concealment_miss_percent) assert.ok(heavy.includes(`${policy.total_concealment_miss_percent}% miss chance`));
  assert.match(heavy, /creator sees through it normally/);
  assert.match(heavy, /teammates see creatures inside as lightly obscured/);
  if (policy.concealment_miss_percent) assert.ok(heavy.includes(`${policy.concealment_miss_percent}% miss chance`));
  assert.match(text({obscured: 'heavy', visual: {sees: 'inward'}}, policy), /inside cannot see out.*outside can see in/);
  assert.match(text({wall: {obscures: 'hostile'}}, policy), /other side from its creator's foes/);
  assert.doesNotMatch(text({wall: {blocks_sight: true}, visual: {obscured: 'heavy'}}, policy), /adds no concealment/);
  for (const level of ['light', 'heavy']) {
    const decorative = text({visual: {material: 'fog', obscured: level}}, policy);
    assert.equal(decorative, 'Visual cloud only: this area adds no concealment.');
    for (const rules of [undefined, {}, {concealment_miss_percent: 0, total_concealment_miss_percent: 0}]) {
      const mechanical = text({obscured: level, owner_sees: true, team_sees: true}, rules);
      assert.match(mechanical, /can't see have Disadvantage/);
      assert.doesNotMatch(mechanical, /%|miss chance/);
    }
  }
  const changed = text({obscured: 'heavy', owner_sees: true, team_sees: true},
    {concealment_miss_percent: 9, total_concealment_miss_percent: 31});
  assert.match(changed, /31% miss chance/); assert.match(changed, /9% miss chance/);
  const server = {trigger_profile: {obscured: 'heavy'}, sight_text: 'Current server policy'};
  assert.deepEqual(zoneTooltip(server, zoneLook(server)).lines, ['Current server policy']);
});
