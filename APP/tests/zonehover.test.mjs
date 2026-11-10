import test from 'node:test';
import assert from 'node:assert/strict';
import {zoneLook, zoneTooltip} from '../static/tabletop/zones.js';

for (const form of ['Zone', 'Aura']) {
  test(`${form} hover leads with the actual area, then effects, then original print`, () => {
    const zone = {detail: `${form}: 30-foot-radius sphere. Lasts 10 rounds while its creator concentrates.`,
      source_detail: 'Based on: Spear-Light Seed. Original technique rules (its range and shape do not describe this area):\nRange: 60-foot line, 5 feet wide. Creatures in the line make Dexterity saving throws.',
      trigger_profile: {name: 'Forged spear area', shape: 'sphere', size_ft: 30,
        numbers: {save_dc: 15}, triggers: [{on: ['enter', 'start'], who: 'hostile',
          effects: [{type: 'save', ability: 'DEX', on_fail: [{type: 'damage', dice: {count: 3, sides: 6}, damage_types: ['force']}], on_success: [{type: 'half_damage'}]}]}]}};
    const {lines} = zoneTooltip(zone, zoneLook(zone));
    assert.equal(lines[0], zone.detail);
    assert.match(lines[1], /Entering it or starting a turn in it.*creator's foes.*Dexterity save DC 15.*3d6 force damage.*half damage/);
    assert.equal(lines.at(-1), zone.source_detail);
    assert.ok(lines.slice(0, -1).every(line => !line.includes('60-foot line')));
  });
}

test('original technique cost stays explained and labelled in the displayed hover', () => {
  const zone = {detail: 'Zone: 20-foot-radius sphere. Lasts 10 rounds while its creator concentrates.',
    source_detail: 'Based on: Heaven-Splitting Gale. Original technique rules (its range and shape do not describe this zone):\nOriginal technique cost: 3 Qi (points from the paying Path resource pool)',
    trigger_profile: {shape: 'sphere', size_ft: 20, triggers: []}};
  const {lines} = zoneTooltip(zone, zoneLook(zone));
  assert.equal(lines.at(-1), zone.source_detail);
  assert.match(lines.at(-1), /Original technique cost: 3 Qi \(points from the paying Path resource pool\)/);
  assert.ok(lines.every(line => !/\bCP\b/.test(line)));
});
