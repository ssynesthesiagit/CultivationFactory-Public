// Exercise round17's production choice dialog and retry loop with a minimal DOM.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
class Element {
  constructor() { this.dataset = {}; this.hidden = false; this.checked = false; this.listeners = {}; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  removeEventListener(name) { delete this.listeners[name]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  querySelectorAll(query) {
    return query === '[data-answer]' ? [use, pass] : query === '[data-option]' ? options
      : query === '.tt-choice-list input:checked' ? inputs.filter(i => i.checked) : [];
  }
}
const dialog = new Element(), text = new Element(), use = new Element(), pass = new Element();
use.dataset.answer = 'USE'; pass.dataset.answer = 'DECLINE';
let inputs = [], options = [], warnings = [];
Object.defineProperty(text, 'innerHTML', {
  set(value) {
    this.html = value;
    inputs = [...value.matchAll(/<input type="checkbox" value="([^"]+)"/g)].map(m => ({value: m[1], checked: false}));
    options = [...value.matchAll(/data-option="([^"]+)"/g)].map(m => Object.assign(new Element(), {dataset: {option: m[1]}}));
  }, get() { return this.html; }
});
const source = fs.readFileSync('static/tabletop/tabletop.js', 'utf8');
const functions = source.slice(source.indexOf('function decisionText(prompt)'), source.indexOf('// The Items panel'));
const context = vm.createContext({$: id => id === '#ttReaction' ? dialog : text,
  app: {matchId: 'test:clarity'}, // Production prompts now bind their waiting state to the active fight.
  escapeHtml: value => String(value), toast: message => warnings.push(message),
  playEvents: async () => {}, broadcastActors: () => {}, renderShapePanel() {}, renderActionBar() {}, hint() {}, cancelTargeting() {}});
// Use the shipped cleanup helper rather than replacing its behavior with a stub.
const cleanupStart = source.indexOf('function closeChoice()');
const cleanup = source.slice(cleanupStart, source.indexOf('// A refresh can replace', cleanupStart));
// Esc and Cancel share the ability cancel rule, so its helpers are shipped code too.
const abilityStart = source.indexOf('// Esc, Cancel and right-click.');
const abilityRules = source.slice(abilityStart, source.indexOf("// The table's one open choice", abilityStart));
vm.runInContext(cleanup + abilityRules + functions, context);
const prompt = {context: {checkpoint: 'test'}, reactor: 'Caster', reaction: 'Bell of Clarity', moment: 'Choose creatures'};
const choice = (minimum, maximum, allow_decline = true) => ({options: ['a', 'b', 'c'].map(id => ({id, label: `Name ${id}`})),
  minimum, maximum, allow_decline, preferred: []});
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  await require('./prompt_identity_harness.cjs').installPromptIdentity(context, {role: 'gm'});
  assert.equal(context.currentViewer().status, 'gm');
  let pending = context.askReaction({...prompt, choice: choice(0, 2)});
  assert.match(text.innerHTML, /Bell of Clarity.*Choose creatures/);
  inputs.forEach(i => { i.checked = true; }); use.onclick();
  assert.equal(dialog.open, true); assert.equal(warnings.length, 1);
  inputs[1].checked = false; use.onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['a', 'c']});
  pending = context.askReaction({...prompt, choice: choice(0, 2)}); use.onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: []});
  pending = context.askReaction({...prompt, choice: choice(1, 2)}); use.onclick();
  assert.equal(dialog.open, true); assert.equal(warnings.length, 2);
  pass.onclick(); assert.equal(await pending, 'DECLINE');
  pending = context.askReaction({...prompt, choice: choice(1, 1)});
  assert.equal(use.hidden, true); options[2].onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['c']});
  pending = context.askReaction({...prompt, choice: choice(1, 1, false)});
  assert.equal(pass.hidden, true);
  // Esc abandons the ability while it is being prepared; a required choice is never answered for the player.
  dialog.listeners.cancel({preventDefault() {}});
  assert.deepEqual(plain(await pending), {cancelled: true});
  assert.equal(dialog.open, false);
  pending = context.askReaction({...prompt, choice: choice(1, 1, false)});
  options[0].onclick();
  assert.deepEqual(plain(await pending), {selection: 'USE', option_ids: ['a']});
  pending = context.askReaction(prompt); assert.equal(pass.hidden, false); assert.equal(use.hidden, false);
  use.onclick(); assert.equal(await pending, 'USE');
  let calls = 0;
  const result = await context.withReactions(async reactions => {
    if (++calls === 1) {
      setImmediate(() => { inputs[1].checked = true; use.onclick(); });
      return {status: 'REACTION_REQUIRED', reaction: {...prompt, choice: choice(0, 2)}};
    }
    assert.deepEqual(plain(reactions), [{checkpoint: 'test', selection: 'USE', option_ids: ['b']}]);
    return {status: 'COMMITTED'};
  });
  assert.equal(result.status, 'COMMITTED');
  console.log('bounds, explicit selection, decline, legacy reset and option transport passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
