// Run actual lobby handlers without starting a browser or server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.js'), 'utf8');
function body(name) {
  let start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function node() {
  const selectors = new Map();
  return {value: '', events: {}, children: [],
    setAttribute() {}, remove() {this.removed = true;},
    replaceChildren(...children) {this.children = children; this.value = ''; this.textContent = '';},
    append(...children) {this.children.push(...children);},
    appendChild(child) {this.children.push(child);},
    querySelector(key) {if (!selectors.has(key)) selectors.set(key, node()); return selectors.get(key);},
    addEventListener(event, fn) {this.events[event] = fn;}};
}
function side() {
  const side = {slots: []};
  side.addSlot = () => {
    const entry = {who: node(), control: node(), slot: node(), buffs: node(), prefight: null};
    side.slots.push(entry); return entry;
  };
  side.addSlot();
  return side;
}
const json = value => JSON.parse(JSON.stringify(value));
let saved = [], posts = [], notices = [], confirms = [], reply = '', allow = true;
const prefightData = {options: [{action_id: 'cast', name: 'Ward', costs: [], duration: '10 minutes'}], picks: ['cast'], max: 2};
let prefightResponse = () => Promise.resolve(prefightData);
const oldSetup = {name: 'Old setup', teams: [[{pid: 'a', mode: 'MANUAL', prefight: ['cast']}], [{pid: 'b', mode: 'LOCAL_AUTO', prefight: null}]], arena_id: 'arena', fight_name: 'Old fight'};
const ctx = vm.createContext({document: {createElement: node}, Option: function(text, value) {this.text = text; this.value = value;},
  enc: encodeURIComponent, prompt: () => reply, confirm: message => (confirms.push(message), allow),
  toast: message => notices.push(message), POOL_NAMES: {},
  api: async (url, options = {}) => {
    if (url.includes('factory-prefight')) return prefightResponse();
    if (url === '/api/tabletop/team-presets') {
      if (options.body) {posts.push(json(options.body.preset)); return options.body.preset;}
      return {presets: [oldSetup]};
    }
    assert.ok(url.startsWith('/api/tabletop/saved-teams'));
    if (options.method === 'DELETE') {saved = saved.filter(row => row.name !== decodeURIComponent(url.split('/').pop())); return {};}
    if (options.body) {
      const record = json(options.body.preset); posts.push(json(record));
      const existing = saved.find(row => row.name === record.name);
      if (existing && !record.replace) throw Error('Confirm replacement');
      saved = saved.filter(row => row.name !== record.name);
      delete record.replace; saved.push(record); return record;
    }
    return {teams: json(saved)};
  }});
// tt/prefight-tooltips 907a1a08 (PREFIGHTr2.review.md) extracted this real row builder.
const prefightRows = fs.readFileSync(path.join(__dirname, '../static/tabletop/prefight_row.js'), 'utf8');
vm.runInContext(prefightRows.replace('export function', 'function'), ctx);
vm.runInContext(['prefightCost', 'serializePrefight', 'loadPrefight', 'updatePresetSaveButtons', 'savedTeamMembers', 'fillSavedTeam', 'singleTeamBar', 'presetBar'].map(body).join('\n'), ctx);
const settle = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  const left = side(), right = side(), refreshers = [];
  const chars = [{project_id: 'a'}, {project_id: 'b'}];
  const bars = [ctx.singleTeamBar(left, chars, refreshers, 'Team 1'), ctx.singleTeamBar(right, chars, refreshers, 'Team 2')];
  await settle();
  left.slots[0].who.value = 'a'; left.slots[0].control.value = 'MANUAL'; left.slots[0].prefight = new Set(['cast']);
  reply = '  First   team  ';
  await bars[0].querySelector('[data-team-save]').events.click();
  assert.equal(posts[0].name, 'First team');
  assert.deepEqual(posts[0].members, [{pid: 'a', mode: 'MANUAL', prefight: ['cast']}]);
  assert.equal(bars[1].querySelector('[data-team]').children[1].value, 'First team');
  allow = false;
  await bars[0].querySelector('[data-team-save]').events.click();
  assert.equal(posts.length, 1, 'cancelled replacement does not post');
  allow = true;
  await bars[0].querySelector('[data-team-save]').events.click();
  assert.equal(posts[1].replace, true);
  assert.match(confirms[0], /First team/);
  right.slots[0].who.value = 'b';
  const oldRight = right.slots[0];
  bars[1].querySelector('[data-team]').value = 'First team';
  await bars[1].querySelector('[data-team-load]').events.click();
  assert.equal(oldRight.slot.removed, true);
  assert.equal(right.slots.length, 1);
  assert.equal(right.slots[0].who.value, 'a');
  assert.equal(right.slots[0].control.value, 'MANUAL');
  assert.deepEqual([...right.slots[0].prefight], ['cast']);
  assert.equal(left.slots[0].who.value, 'a');
  // A second saved team can be mixed with the first, and loaded back into either side.
  right.slots[0].who.value = 'b'; right.slots[0].control.value = 'LOCAL_AUTO'; right.slots[0].prefight = new Set();
  reply = 'Second';
  await bars[1].querySelector('[data-team-save]').events.click();
  bars[0].querySelector('[data-team]').value = 'Second';
  await bars[0].querySelector('[data-team-load]').events.click();
  assert.equal(left.slots[0].who.value, 'b');
  bars[1].querySelector('[data-team]').value = 'First team';
  await bars[1].querySelector('[data-team-load]').events.click();
  assert.equal(right.slots[0].who.value, 'a');
  assert.deepEqual([...left.slots[0].prefight], []);
  saved.push({name: 'Missing', members: [{pid: 'gone', mode: 'MANUAL', prefight: []}]});
  await Promise.all(refreshers.map(fn => fn()));
  bars[0].querySelector('[data-team]').value = 'Missing';
  await bars[0].querySelector('[data-team-load]').events.click();
  assert.equal(left.slots.length, 1); assert.equal(left.slots[0].who.value, '');
  assert.match(notices.at(-1), /1 fighter is no longer available/);
  bars[0].querySelector('[data-team]').value = 'First team';
  allow = false;
  await bars[0].querySelector('[data-team-delete]').events.click();
  assert.ok(saved.some(row => row.name === 'First team'));
  allow = true;
  await bars[0].querySelector('[data-team-delete]').events.click();
  assert.ok(!saved.some(row => row.name === 'First team'));
  assert.ok(!bars[1].querySelector('[data-team]').children.some(row => row.value === 'First team'));
  const fightName = node(), map = node(); map.options = [{value: 'arena'}];
  let describedArena = null;
  const wholeSetupBar = ctx.presetBar([left, right], fightName, map, chars, () => { describedArena = map.value; });
  await settle();
  wholeSetupBar.querySelector('[data-preset]').value = 'Old setup';
  await wholeSetupBar.querySelector('[data-preset-load]').events.click();
  assert.equal(left.slots[0].who.value, 'a'); assert.equal(right.slots[0].who.value, 'b');
  assert.equal(fightName.value, 'Old fight'); assert.equal(map.value, 'arena');
  assert.equal(describedArena, 'arena', 'loading a saved setup refreshes the selected arena description');
  // Real asynchronous restoration: saves must not capture an unresolved snapshot.
  for (const picks of [['cast'], []]) {
    saved.push({name: 'Deferred', members: [{pid: 'a', mode: 'MANUAL', prefight: picks}]});
    await Promise.all(refreshers.map(fn => fn()));
    bars[0].querySelector('[data-team]').value = 'Deferred';
    let resolve;
    prefightResponse = () => new Promise(done => {resolve = done;});
    const noticeCount = notices.length;
    const loading = bars[0].querySelector('[data-team-load]').events.click();
    const count = posts.length;
    assert.equal(bars[0].querySelector('[data-team-save]').disabled, true);
    assert.equal(wholeSetupBar.querySelector('[data-preset-save]').disabled, true);
    assert.equal(bars[1].querySelector('[data-team-save]').disabled, false);
    assert.equal(notices.length, noticeCount, 'no premature load success');
    await bars[0].querySelector('[data-team-save]').events.click();
    await wholeSetupBar.querySelector('[data-preset-save]').events.click();
    assert.equal(posts.length, count);
    resolve(prefightData); await loading;
    assert.equal(left.slots[0].buffs.textContent, '', 'loading message clears after restoration');
    assert.equal(bars[0].querySelector('[data-team-save]').disabled, false);
    assert.equal(wholeSetupBar.querySelector('[data-preset-save]').disabled, false);
    reply = 'Restored';
    await bars[0].querySelector('[data-team-save]').events.click();
    assert.deepEqual(posts.at(-1).members[0].prefight, picks);
    // Rejected restoration keeps explicit empty/nonempty choices and reports failure.
    prefightResponse = () => Promise.reject(Error('offline'));
    await bars[0].querySelector('[data-team-load]').events.click();
    assert.match(notices.at(-1), /could not restore.*Saved cast choices have been kept/);
    assert.equal(bars[0].querySelector('[data-team-save]').disabled, false);
    reply = 'Preserved';
    await bars[0].querySelector('[data-team-save]').events.click();
    assert.deepEqual(posts.at(-1).members[0].prefight, picks);
    saved = saved.filter(row => row.name !== 'Deferred');
  }
  // Whole setups use the same restoration and snapshot helpers.
  const setupResolvers = [];
  prefightResponse = () => new Promise(done => {setupResolvers.push(done);});
  const emptySetup = {...oldSetup, teams: [[{pid: 'a', mode: 'MANUAL', prefight: []}], [{pid: 'b', mode: 'LOCAL_AUTO', prefight: ['cast']}]]};
  oldSetup.teams = emptySetup.teams;
  const setupLoading = wholeSetupBar.querySelector('[data-preset-load]').events.click();
  assert.equal(wholeSetupBar.querySelector('[data-preset-save]').disabled, true);
  assert.equal(bars[0].querySelector('[data-team-save]').disabled, true);
  setupResolvers.forEach(done => done(prefightData)); await setupLoading;
  assert.deepEqual([...left.slots[0].prefight], []);
  reply = 'Restored setup';
  await wholeSetupBar.querySelector('[data-preset-save]').events.click();
  assert.deepEqual(posts.at(-1).teams.map(team => team[0].prefight), [[], ['cast']]);
  wholeSetupBar.querySelector('[data-preset]').value = 'Old setup';
  prefightResponse = () => Promise.reject(Error('offline'));
  await wholeSetupBar.querySelector('[data-preset-load]').events.click();
  assert.match(notices.at(-1), /could not restore/);
  assert.deepEqual([...left.slots[0].prefight], []);
  reply = 'Preserved setup';
  await wholeSetupBar.querySelector('[data-preset-save]').events.click();
  assert.deepEqual(posts.at(-1).teams.map(team => team[0].prefight), [[], ['cast']]);
  // A stale request for the same fighter must not overwrite a newer restoration.
  const entry = left.slots[0];
  let resolveOld;
  prefightResponse = () => new Promise(done => {resolveOld = done;});
  const oldLoad = ctx.loadPrefight(entry, entry.buffs, ['cast']);
  prefightResponse = () => Promise.resolve(prefightData);
  await ctx.loadPrefight(entry, entry.buffs, []);
  resolveOld(prefightData); await oldLoad;
  assert.deepEqual([...entry.prefight], []);
  prefightResponse = () => Promise.resolve({...prefightData, setup_choices: [
    {id: 'example_charge', label: 'Stored points for each prepared item', kind: 'integer_range_list',
      count: 1, item_label: 'Item', minimum: 0, maximum: 4, unit: 'CP', default: [4]}
  ]});
  await ctx.loadPrefight(entry, entry.buffs, null);
  const choice = entry.buffs.children[0].children.at(-1).children[1];
  assert.equal(choice.value, '4');
  choice.value = '1'; choice.events.change();
  assert.deepEqual(json(ctx.serializePrefight(entry)), ['cast', 'setup-choice:example_charge:1']);
  // Saved choices are reconciled before display and before either team/fight serialization.
  const declaration = {id: 'example_charge', label: 'Stored points for each prepared item',
    help: 'Points stored when crafting. Using an item restores those points.', kind: 'integer_range_list',
    count: 3, item_label: 'Item', minimum: 0, maximum: 4, unit: 'CP', default: [4, 3, 2]};
  const textIn = host => [host.textContent || '', ...(host.children || []).flatMap(textIn)];
  for (const [savedValues, count, maximum, expected] of [
    ['1', 3, 4, [1, 3, 2]], // count grew: initialize untouched new controls
    ['1,2,3', 1, 4, [1]], // count shrank: trim hidden surplus
    ['4,2,0', 3, 2, [2, 2, 0]], // range changed: replace invalid values with defaults
    ['-1,1.5,nope', 3, 4, [4, 3, 2]],
    ['', 3, 4, [4, 3, 2]],
    ['1,,0', 3, 4, [1, 3, 0]],
  ]) {
    const current = {...declaration, count, maximum,
      default: declaration.default.slice(0, count).map(value => Math.min(value, maximum))};
    prefightResponse = () => Promise.resolve({...prefightData, setup_choices: [current]});
    await ctx.loadPrefight(entry, entry.buffs, ['cast', `setup-choice:example_charge:${savedValues}`]);
    assert.deepEqual(json(entry.setupChoices.example_charge), expected);
    assert.deepEqual(json(ctx.serializePrefight(entry)), ['cast', `setup-choice:example_charge:${expected.join(',')}`]);
    const rendered = entry.buffs.children[0].children.filter(row => row.children?.[1]?.children?.length);
    assert.deepEqual(rendered.map(row => Number(row.children[1].value)), expected);
    assert.ok(textIn(entry.buffs).some(text => /Saved setup choices were updated/.test(text)));
    assert.ok(textIn(entry.buffs).includes(current.help), 'help rendered from declaration as plain text');
  }
  prefightResponse = () => Promise.resolve({...prefightData, setup_choices: [declaration]});
  await ctx.loadPrefight(entry, entry.buffs, ['cast']);
  assert.deepEqual(json(entry.setupChoices.example_charge), [4, 3, 2]);
  assert.ok(textIn(entry.buffs).some(text => /Saved setup choices were updated/.test(text)));
  await ctx.loadPrefight(entry, entry.buffs, ['cast', 'setup-choice:example_charge:1,2,3']);
  assert.ok(!textIn(entry.buffs).some(text => /Saved setup choices were updated/.test(text)), 'unchanged choices need no notice');
  // An ability removed from a fighter must not submit obsolete setup fields.
  prefightResponse = () => Promise.resolve(prefightData);
  await ctx.loadPrefight(entry, entry.buffs, ['cast', 'setup-choice:example_charge:1,2,3']);
  assert.deepEqual(json(ctx.serializePrefight(entry)), ['cast']);
  assert.ok(textIn(entry.buffs).some(text => /Saved setup choices were updated/.test(text)));
  // Actual builder mounts a team bar on each panel and retains the whole setup bar.
  assert.match(body('buildFightBuilder'), /box.appendChild\(singleTeamBar\(side, characters, teamBars, title\)\)/);
  assert.match(body('buildFightBuilder'), /host.append\(presetBar\(sides, name, mapSelect, characters, describeArena\), teams, foot\)/);
  console.log('team saves: existing flows, delayed/failed restoration, empty casts, setup guards and stale responses PASS');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
