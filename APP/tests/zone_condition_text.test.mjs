// node --test APP/tests/zone_condition_text.test.mjs
// The area reader must describe a condition, never show its internal key (AUDIT6 finding 1/2), say
// every effect the engine applies, and say it the same way the sheet's own condition hover does;
// the sheet's one unreachable "paying pool" toast must name a control a player can find (finding 3).
import test from 'node:test';
import assert from 'node:assert/strict';
import {zoneTooltip, zoneLook, effectText} from '../static/tabletop/zones.js';
import {CONDITIONS} from '../static/tabletop/zone-text.js';
import {playerError} from '../static/tabletop/error-text.js';

// Every condition key measured to reach the zone reader from the typed authority
// (authority/typed_mechanics/reviewed_final.d + combat/rules at 65cf60c9).
const ZONE_KEYS = ['blinded', 'bound', 'burning', 'flustered', 'frightened', 'no_bonus_actions', 'no_dash',
  'poisoned', 'prone', 'reaction_denied', 'restrained', 'sickened', 'silenced', 'smothered', 'turbulent'];

// The three keys the old code rendered as bare fragments ("no bonus actions", "no dash", "reaction denied").
const FRAGMENT_KEYS = ['no_bonus_actions', 'no_dash', 'reaction_denied'];

// A zone whose trigger fails the save into these conditions, so the text is checked where a
// player reads it: the tooltip the table paints.
const tipFor = conditions => {
  const zone = {zone_id: 'zone:typed:actor:factory.x:9', owner_id: 'a', active: true, affected_cells: [{x: 1, y: 1}],
    trigger_profile: {kind: 'TYPED', name: 'Ashfall', visual: {material: 'ash'},
      triggers: [{name: 'Rending Field', on: ['enter'], who: 'hostile',
        effects: [{type: 'save', ability: 'dex', on_fail: conditions.map(condition => ({type: 'condition', condition}))}]}]}};
  const line = zoneTooltip(zone, zoneLook(zone), {round: 1, foe: true}).lines.find(text => text.startsWith('Rending Field:'));
  assert.ok(line, 'no trigger line in the tooltip');
  return line;
};

test('an area description says what each condition does, never the internal key', () => {
  for (const key of [...ZONE_KEYS, ...FRAGMENT_KEYS]) {
    const text = effectText([{type: 'condition', condition: key}]);
    assert.ok(text.length > 10, `${key} must read as a sentence, got ${JSON.stringify(text)}`);
    assert.ok(!text.includes('_'), `${key} leaked an internal key: ${text}`);
    assert.ok(!/^[a-z]+(?: [a-z]+)*$/.test(text), `${key} rendered as a bare fragment: ${text}`);
    assert.notEqual(text, key, `${key} rendered as its own key`);
  }
});

test('the three keys that used to leak as fragments now say what they deny', () => {
  assert.equal(effectText([{type: 'condition', condition: 'no_dash'}]), 'It can\'t benefit from the Dash action.');
  assert.equal(effectText([{type: 'condition', condition: 'no_bonus_actions'}]), 'It can\'t take Bonus Actions.');
  assert.match(effectText([{type: 'condition', condition: 'reaction_denied'}]), /take Reactions/);
});

test('an unknown condition key does not reach the player as a code name', () => {
  const text = effectText([{type: 'condition', condition: 'some_future_condition_key'}]);
  assert.ok(!text.includes('_'), `unknown key leaked: ${text}`);
  assert.ok(!text.includes('some_future'), `unknown key leaked: ${text}`);
  assert.equal(text, 'The Game Master resolves what this does');
  assert.equal(effectText([{type: 'condition'}]), 'The Game Master resolves what this does');
  // A namespaced id resolves by its condition, as the sheet's own pill does.
  assert.equal(effectText([{type: 'condition', condition: 'condition:typed.no_dash'}]), 'It can\'t benefit from the Dash action.');
});

test('the zone tooltip a player hovers shows the plain reading, at the level the bug showed', () => {
  const line = tipFor(['prone', 'no_dash']);
  assert.ok(line.includes('It can only crawl; standing up costs half its Speed'), line);
  assert.ok(line.includes('benefit from the Dash action'), line);
  assert.ok(!line.includes('_'), line);
});

test('the conditions that decide an attack say what the engine applies (MMX9r finding 1)', () => {
  // typed_conditions.json gives each of these an attack-roll mode the old text left out.
  const attack = {
    frightened: ['Its attack rolls have Disadvantage while it can see the source of its fear',
      'Disadvantage on ability checks while it can see the source of its fear'],
    prone: ['Its attack rolls have Disadvantage', 'Attacks against it from within 5 feet have Advantage',
      'Attacks against it from farther away have Disadvantage', 'Standing up ends it and costs half its Speed'],
    restrained: ['Its Speed is 0', 'Its attack rolls have Disadvantage', 'Attack rolls against it have Advantage',
      'Disadvantage on Dexterity saving throws'],
    poisoned: ['Its attack rolls and all ability checks have Disadvantage'],
    blinded: ['Attack rolls against it have Advantage'],
  };
  for (const [condition, effects] of Object.entries(attack)) {
    const line = tipFor([condition]);
    for (const effect of effects) assert.ok(line.includes(effect), `${condition} hides "${effect}": ${line}`);
  }
});

test('Stunned and Muffle say what the rules do, not what they do not do (MMX9r finding 2)', () => {
  // combat/rules/typed_conditions.json: Stunned auto-fails Strength and Dexterity saves only and
  // never sets Speed to 0; condition_text.READING says its Speed is unchanged.
  const stunned = tipFor(['stunned']);
  assert.ok(stunned.includes('automatically fails Strength and Dexterity saving throws'), stunned);
  assert.ok(stunned.includes('Its Speed is unchanged'), stunned);
  assert.ok(!/Speed is 0/.test(stunned), `Stunned must not claim Speed 0: ${stunned}`);
  assert.ok(!/automatically fails saves\b/.test(stunned), `Stunned must not say it fails every save: ${stunned}`);
  // Muffle is a hearing Disadvantage that takes away heavy armor's Stealth Disadvantage. It does
  // not muffle the creature's own attacks.
  const muffled = tipFor(['glamer_muffled']);
  assert.ok(muffled.includes('Disadvantage to hear it'), muffled);
  assert.ok(muffled.includes('its heavy armor gives no Stealth Disadvantage'), muffled);
  assert.ok(!/own attacks are muffled/i.test(muffled), `Muffle must not invent muffled attacks: ${muffled}`);
});

test('a lasting area never explains a condition with a code name or a workshop note', () => {
  // The reader is generated from combat/condition_text.py, so a file path or a lane in that
  // module would reach every player who hovers a zone.
  for (const [key, text] of Object.entries(CONDITIONS)) {
    assert.ok(!/combat\/|tools\/|\.py\b|gate[1-9]|reviewed_final|typed_[a-z]/.test(text), `${key} leaks a workshop note: ${text}`);
  }
});

test('a condition a newcomer has never met still says what it does (MMX9r finding 2)', () => {
  // These four used to read as bare labels ("Anchored for the duration", "it is a Calamity
  // Incarnation for the duration") or repeat a rule reference instead of explaining it.
  const explained = {
    anchored: ['cannot teleport', 'An unwilling creature repeats the Charisma saving throw'],
    kindled: ['Any ability that says it works on a Kindled creature works on it'],
    sovereign_iron_body: ['Unarmed Strikes ignore Resistance to Bludgeoning and Force damage'],
    calamity_sovereign_incarnation: ['Destructive Blast', 'one augment costs 1 cultivation points (your Path resource) less'],
  };
  for (const [key, phrases] of Object.entries(explained)) {
    for (const phrase of phrases) assert.ok(CONDITIONS[key].includes(phrase), `${key} hides "${phrase}": ${CONDITIONS[key]}`);
  }
  // A condition with no reading and no engine rule says who resolves it rather than nothing.
  assert.equal(CONDITIONS.held, 'The Game Master resolves what this does');
});

test('the reading a player hovers explains the terms it uses (MMX41 finding 3)', () => {
  // Checking the generated dictionary is not enough: this is the line a player reads, and the
  // MMX9r replacement explained the ability in words only someone who owns the book can read.
  const line = tipFor(['calamity_sovereign_incarnation']);
  const explained = {
    'cultivation points (your Path resource) is the pool its Destruction abilities pay their costs from': 'the paying resource is unexplained',
    'an augment is an extra Destruction talent that costs cultivation points (your Path resource)': 'a Destruction augment is unexplained',
    'a Destruction Die is the die its Blast Type rolls to work out the blast\'s damage': 'a Destruction Die is unexplained',
    'a Blast Shape that lets it release Destructive Blast as a Reaction against the creature that damaged it':
      'Returning Calamity is unexplained',
  };
  for (const [phrase, why] of Object.entries(explained)) {
    assert.ok(line.includes(phrase), `${why}: ${line}`);
  }
  // The reader must not fall back on the old shorthand that named the terms without explaining them.
  assert.ok(!line.includes('1 CP comes back off the cost'), `the unexplained wording is back: ${line}`);
});

test('a filtered reading still says who resolves the effect (MMX41 finding 1)', () => {
  // plain_reading() drops the workshop's own bookkeeping. Who resolves an effect is not
  // bookkeeping: Bleeding deals its damage only when the Game Master applies it, and Thorn-Flesh
  // Armory still sends that damage as a GM rider (combat/ext/thorn_bleeding.py), so a reading that
  // dropped the qualification would promise a roll the fight never makes.
  const bleeding = tipFor(['bleeding']);
  // Matched without the closing period: the area wraps the reading in its own sentence
  // ("... Your Game Master resolves it on a failure"), so the player text is not sentence-final.
  assert.match(bleeding, /Your Game Master resolves it\b/, bleeding);
  assert.ok(bleeding.includes('deals Proficiency Bonus damage'), bleeding);
  assert.ok(!/adjudicated|lock round|GM_RIDER/.test(bleeding), `a workshop note reached the player: ${bleeding}`);
  // Charmed still has a manual ruling. The reviewed lock18/19 condition hooks
  // now enforce nearby critical hits for Paralyzed and Unconscious.
  for (const condition of ['charmed']) {
    const said = tipFor([condition]);
    assert.match(said, /Your Game Master (decides|resolves it)\b/, `${condition} hides who resolves it: ${said}`);
  }
  for (const condition of ['paralyzed', 'unconscious']) {
    const said = tipFor([condition]);
    assert.match(said, /critical hit: roll twice the damage dice/, said);
    assert.ok(!/Your Game Master (decides|resolves it)\b/.test(said), said);
  }
  // Petrified's combat effects are now automatic; its weight and aging remain manual.
  assert.match(tipFor(['petrified']), /Weight and aging are tracked by your Game Master\b/);
  // The name is spelled out everywhere: a kept clause that says "the GM" is the one place a
  // newcomer meets an abbreviation the rest of the readings never use.
  for (const condition of ['cannot_teleport', 'bleeding', 'paralyzed', 'charmed']) {
    const said = tipFor([condition]);
    assert.ok(!/\bGM\b/.test(said), `${condition} leaves the name abbreviated: ${said}`);
  }
  // It holds inside the note the filter drops too (MMX48): the parenthetical naming the file also
  // said who has to end the effect, and dropping the whole parenthetical left the reading promising
  // a rest that does not arrive on its own.
  const immunity = tipFor(['grandstanding_slam_immune']);
  assert.match(immunity, /Your Game Master resolves it\b/, immunity);
  assert.ok(immunity.includes('immune to it until a short or long rest'), immunity);
  assert.ok(!/reminder|adjudicated|combat\/ext/.test(immunity), `a workshop note reached the player: ${immunity}`);
});

test('a Blood Puppet lists every command its puppeteer may give (MMX41 finding 2)', () => {
  // combat/ext/blood_riders.py PUPPET_COMMANDS: six commands, of which the movement pair is easy to
  // leave out of a rewritten sentence, and a player who cannot see it cannot reposition a puppet.
  const line = tipFor(['blood_puppet']);
  assert.ok(line.includes('move it up to half its Speed'), line);
  assert.ok(/toward the puppeteer or away from it/.test(line), `the movement option loses its directions: ${line}`);
  for (const command of ['fall Prone', 'taking Reactions', 'Speed to 0', 'drop what it holds']) {
    assert.ok(line.includes(command), `the reading hides "${command}": ${line}`);
  }
});

test('the paying-pool toast names the sheet control and defines the pools', () => {
  const text = playerError({code: 'POWERING_INVALID_POOL', status: 400});
  assert.ok(!/paying pool/i.test(text), `"paying pool" is undefined on this path: ${text}`);
  assert.ok(text.includes('Which pool pays'), `the toast must name the control the player finds: ${text}`);
  for (const pool of ['Stamina', 'Qi', 'Resonance']) {
    assert.ok(text.includes(pool), `the toast must say which pools exist: ${text}`);
  }
  assert.ok(text.includes('save again'), `the toast must say what to do next: ${text}`);
});
