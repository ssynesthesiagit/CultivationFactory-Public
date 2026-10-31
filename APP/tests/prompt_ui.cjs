// Production dialog functions, with a minimal DOM: no browser is launched.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
class Element {
  constructor(dataset = {}) { this.dataset = dataset; this.hidden = false; this.listeners = {}; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  removeEventListener(name) { delete this.listeners[name]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  setAttribute(key, value) { this[key] = value; }
  querySelectorAll(query) {
    return query === '[data-answer]' ? [use, pass] : query === '[data-option]' ? options
      : query === '[data-space-option]' ? squares : query === '.tt-choice-list input' ? inputs
      : query === '.tt-choice-list input:checked' ? inputs.filter(input => input.checked) : [];
  }
}
const dialog = new Element(), text = new Element(), title = new Element();
const use = new Element({answer: 'USE'}), pass = new Element({answer: 'DECLINE'});
let inputs = [], options = [], squares = [], warnings = [];
Object.defineProperty(text, 'innerHTML', {set(value) {
  this.html = value;
  inputs = [...value.matchAll(/<input type="checkbox" value="([^"]+)"/g)].map(m => ({value: m[1], checked: false}));
  options = [...value.matchAll(/data-option="([^"]+)"/g)].map(m => new Element({option: m[1]}));
  squares = [...value.matchAll(/data-space-option="([^"]+)"/g)].map(m => new Element({spaceOption: m[1]}));
}, get() { return this.html; }});
const source = fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.js'), 'utf8');
const context = vm.createContext({$: id => ({'#ttReaction': dialog, '#ttReactionText': text, '#ttReactionTitle': title})[id],
  app: {matchId: 'test'}, closeChoice: () => {}, playEvents: async () => {},
  escapeHtml: value => String(value || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  toast: message => warnings.push(message)});
vm.runInContext(source.slice(source.indexOf('function decisionText('), source.indexOf('// The Items panel')), context);
const plain = value => JSON.parse(JSON.stringify(value));
const map = {origin: {x: 17, y: 11}, chooser_id: 'me', width: 30, height: 30, blocked: [{x: 16, y: 9}],
  tokens: [{id: 'me', name: 'Tabik Damu', position: {x: 17, y: 11}},
           {id: 'target', name: 'Bonded Spirit', position: {x: 18, y: 11}}]};
const choice = {minimum: 1, maximum: 1, allow_decline: false, space_map: map,
  options: ['17,10', '17,12', '18,10', '18,12'].map(id => ({id, label: id, description: '',
    cell: {x: Number(id.split(',')[0]), y: Number(id.split(',')[1])}}))};
const prompt = {title: 'Elbow in the Door: choose a space', reactor: 'Tabik Damu', reaction: 'Elbow in the Door',
  trigger: 'Iron Fist damages Bonded Spirit', cost: 'none', summary: 'Choose one adjacent space.', choice};
(async () => {
  await require('./prompt_identity_harness.cjs').installPromptIdentity(context, {role: 'gm'});
  assert.equal(context.currentViewer().status, 'gm');
  let pending = context.askReaction(prompt);
  assert.equal(title.textContent, prompt.title);
  assert.match(text.innerHTML, /1 square north and 1 square east of you, beside Bonded Spirit/);
  assert.match(text.innerHTML, />TD<\/button>/);
  assert.match(text.innerHTML, />BS<\/button>/);
  assert.match(text.innerHTML, /is-wall[^>]*disabled/);
  assert.match(text.innerHTML, /Cost now:<\/strong> none/);
  assert.doesNotMatch(text.innerHTML, />17,10|>18,12/);
  assert.equal(options.length, 8); // Four legal squares and the four list fallback buttons.
  assert.equal(pass.hidden, true);
  dialog.listeners.cancel({preventDefault() {}}); assert.equal(dialog.open, true);
  options[0].onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['17,10']});
  pending = context.askReaction(prompt); options[7].onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['18,12']});
  pending = context.askReaction({...prompt, choice: {...choice, maximum: 2, allow_decline: true}});
  assert.equal(use.hidden, false); squares[0].onclick(); squares.find(square => square.dataset.spaceOption === '18,10').onclick();
  assert.equal(squares[0]['aria-pressed'], 'true'); assert.equal(inputs[2].checked, true);
  inputs[2].checked = false; inputs[2].onchange(); assert.equal(squares.find(square => square.dataset.spaceOption === '18,10')['aria-pressed'], 'false');
  inputs.forEach(input => input.checked = true); use.onclick(); assert.equal(warnings.length, 1);
  inputs[1].checked = false; inputs[3].checked = false; use.onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['17,10', '18,10']});
  pending = context.askReaction({...prompt, choice: {...choice, allow_decline: true}});
  pass.onclick(); assert.equal(await pending, 'DECLINE');
  pending = context.askReaction({...prompt, title: 'Reaction', choice: null});
  assert.equal(title.textContent, 'Reaction'); assert.equal(use.hidden, false); assert.equal(pass.hidden, false);
  use.onclick(); assert.equal(await pending, 'USE');
  pending = context.askReaction({...prompt, title: 'Choose an effect', choice: {...choice, space_map: null,
    options: [{id: 'trip', label: 'Trip', description: 'Trip'}, {id: 'safe', label: '<img>', description: '<script>'}]}});
  assert.doesNotMatch(text.innerHTML, /Trip<br>Trip/);
  assert.match(text.innerHTML, /&lt;img>/); assert.match(text.innerHTML, /&lt;script>/);
  options[0].onclick(); await pending;
  assert.match(context.spaceGrid({...choice, space_map: {...map, width: 100}, options: [{id: '90,11', label: '90,11', cell: {x: 90, y: 11}}]}, false), /data-option="90,11"/);
  assert.equal(context.spaceOptionLabel({cell: {x: 17, y: 10}, label: 'Step to 17,10 (5 ft; costs 1 Stamina)'}, map),
    'Step to 1 square north of you, beside Bonded Spirit (5 ft; costs 1 Stamina)');
  assert.equal(context.spaceOptionLabel({cell: map.origin, label: 'Stay put (still Footwork)'}, map),
    'your current square, beside Bonded Spirit: Stay put (still Footwork)');
  const largeMap = {...map, square_size_ft: 10, tokens: [map.tokens[0],
    {...map.tokens[1], cells: [{x: 18, y: 11}, {x: 19, y: 11}, {x: 18, y: 12}, {x: 19, y: 12}]}]};
  assert.equal(context.spaceDescription({x: 19, y: 12}, largeMap),
    '1 square south and 2 squares east of you, occupied by Bonded Spirit');
  assert.equal(context.spaceDescription({x: 20, y: 12}, largeMap),
    '1 square south and 3 squares east of you, beside Bonded Spirit');
  const largeChoice = {...choice, space_map: largeMap,
    options: [{id: 'cell:20,12', label: 'cell:20,12', cell: {x: 20, y: 12}}]};
  const largeGrid = context.spaceGrid(largeChoice, false);
  assert.equal([...largeGrid.matchAll(/>BS<\/button>/g)].length, 4);
  assert.match(largeGrid, /Each square is 10 feet/);
  pending = context.askReaction({...prompt, choice: largeChoice});
  options.find(option => option.dataset.option === 'cell:20,12').onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['cell:20,12']});
  // A chooser's own footprint must fit even if its legal options are near its anchor.
  const largeChooser = {...map, tokens: [{...map.tokens[0], cells: [{x: 17, y: 11}, {x: 18, y: 11}, {x: 19, y: 11}, {x: 20, y: 11}]}]};
  assert.equal([...context.spaceGrid({...choice, space_map: largeChooser}, false).matchAll(/>TD<\/button>/g)].length, 4);
  assert.equal(context.spaceDescription({x: 20, y: 11}, largeChooser),
    '3 squares east of your current top-left square, currently part of your space');
  // Equal-cost multi-square steps must have distinct list and accessible grid labels.
  const stepMap = {...map, origin: {x: 5, y: 5}, tokens: [{id: 'me', name: 'Tabik Damu', position: {x: 5, y: 5}}]};
  const steps = ['6,3', '7,4'].map(id => ({id: `cell:${id}`, label: `Step to ${id} (10 ft)`,
    cell: {x: Number(id.split(',')[0]), y: Number(id.split(',')[1])}}));
  const labels = ['Step to 2 squares north and 1 square east of you (10 ft)',
    'Step to 1 square north and 2 squares east of you (10 ft)'];
  assert.notEqual(context.spaceOptionLabel(steps[0], stepMap), context.spaceOptionLabel(steps[1], stepMap));
  for (let i = 0; i < steps.length; i++) for (const surface of ['grid', 'list']) {
    pending = context.askReaction({...prompt, choice: {...choice, space_map: stepMap, options: steps}});
    assert.ok(text.innerHTML.includes(`aria-label="${labels[i]}"`));
    assert.ok(text.innerHTML.includes(`>${labels[i]}</button>`));
    const matching = options.filter(option => option.dataset.option === steps[i].id);
    matching[surface === 'grid' ? 0 : 1].onclick();
    assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: [steps[i].id]});
  }
  // A 2x2 creature can move its anchor into a square it already occupies.
  const overlapMap = {...stepMap, tokens: [{...stepMap.tokens[0], cells:
    [{x: 5, y: 5}, {x: 6, y: 5}, {x: 5, y: 6}, {x: 6, y: 6}]}]};
  assert.equal(context.spaceDescription({x: 5, y: 5}, overlapMap), 'your current top-left square');
  const overlap = {id: 'cell:6,5', label: 'Step to 6,5 (5 ft)', cell: {x: 6, y: 5}};
  const overlapLabel = 'Step to 1 square east of your current top-left square, currently part of your space (5 ft)';
  for (const surface of ['grid', 'list']) {
    pending = context.askReaction({...prompt, choice: {...choice, space_map: overlapMap, options: [overlap]}});
    assert.ok(text.innerHTML.includes(`aria-label="${overlapLabel}"`));
    assert.ok(text.innerHTML.includes(`>${overlapLabel}</button>`));
    options[surface === 'grid' ? 0 : 1].onclick();
    assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['cell:6,5']});
  }
  console.log('PASS: space grid, descriptions, safe text, selection transport, bounds, multi-select sync, decline and title reset');
})().catch(error => { console.error(error); process.exitCode = 1; });
