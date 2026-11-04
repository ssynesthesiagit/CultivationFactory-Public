// Exercise the page and board's actual function bodies with test-owned presentation data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const page = fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.js'), 'utf8');
const board = fs.readFileSync(path.join(__dirname, '../static/tabletop/board.js'), 'utf8');
function body(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const indent = source.slice(source.lastIndexOf('\n', start) + 1, start);
  return source.slice(start, source.indexOf(`\n${indent}}`, start) + indent.length + 2);
}
const rows = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rider = rows.find(a => a.conditions.some(c => c.condition_id === 'condition:typed.mounted'));
assert.ok(rider, 'real table state has mounted rider');
const mount = rows.find(a => a.entity_id === rider.conditions.find(c => c.condition_id === 'condition:typed.mounted').source_actor_id);
assert.equal(mount.footprint.width_cells, 2);
const nodes = [];
const tokens = new Map(), clicked = [];
const ctx = vm.createContext({OBJECT_FACE: {}, actors: () => rows, actorById: id => rows.find(a => a.entity_id === id),
  tokens, markSvg: {replaceChildren() {nodes.length = 0;}}, svg: (tag, attrs) => nodes.push({tag, attrs})});
vm.runInContext(body(page, 'tokenGeometry') + '\n' + body(board, 'setHighlights'), ctx);
const r = ctx.tokenGeometry(rider), m = ctx.tokenGeometry(mount);
assert.equal(r.ridingOn, mount.entity_id); assert.equal(r.scale, 0.8);
assert.equal(m.width, 2); assert.equal(m.height, 2); assert.equal(m.scale, 1);
ctx.setHighlights({targets: [{...mount.position, ...m}, {...rider.position, ...r}]});
assert.equal(nodes[0].attrs.rx, 1.12); assert.equal(nodes[1].attrs.rx, 0.62);
assert.equal(nodes[0].attrs.cx, nodes[1].attrs.cx);
assert.equal(nodes[0].attrs.cy, nodes[1].attrs.cy);
assert.match(fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.css'), 'utf8'), /\.tt-token\.is-riding \{ z-index: 3;/);
function node() {
  const children = new Map(), classes = new Set();
  return {style: {setProperty() {}}, dataset: {}, events: {}, textContent: '',
    classList: {toggle(k, on) {on ? classes.add(k) : classes.delete(k);}, contains: k => classes.has(k)},
    querySelector(k) {if (!children.has(k)) children.set(k, node()); return children.get(k);},
    addEventListener(k, fn) {this.events[k] = fn;},
    removeEventListener(k, fn) {if (this.events[k] === fn) delete this.events[k];},
    setAttribute() {}, removeAttribute() {}, toggleAttribute() {}, remove() {},
    getBoundingClientRect: () => ({left: 100, top: 100, width: 64})};
}
// setTokens/showCard use the real shared hover-card dependency, including its open/close ownership state.
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/tabletop/hovercard.js'), 'utf8')
  .replace(/^export /gm, ''), ctx);
ctx.window = {innerWidth: 1024, innerHeight: 800};
ctx.hover = ctx.createHoverCard({doc: {createElement: node, body: {appendChild() {}},
  addEventListener() {}, removeEventListener() {}}, win: ctx.window});
// setTokens reads the board's authored map objects (destructible wall runs); this fixture has none.
Object.assign(ctx, {tokens, CELL: 64, card: {owner: null}, el: () => node(), tokenLayer: {}, map: {objects: []},
  handlers: {onTokenClick: id => clicked.push(id)}, showCard() {}, hideCard() {},
  initials: n => n.slice(0, 2), setTokenLight() {}, normalizeLight: x => x, removeNodes() {}, setRoofView() {}});
vm.runInContext(body(board, 'setTokens') + '\n' + body(board, 'placeToken'), ctx);
// This footprint/card fixture explicitly runs as GM; player identity and roof
// audiences are exercised by viewer_identity_wiring.test.mjs.
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/tabletop/viewer-identity.js'),'utf8')
  .replace(/^export /mg,''),ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/tabletop/flight-ui.js'),'utf8')
  .replace(/^export /mg,''),ctx);
vm.runInContext("const mountedView=createViewerStore({viewId:'mounted-test'}); mountedView.bindGM('fight'); function currentViewer(){return resolveViewerIdentity(mountedView.read('fight'),[],{seats:{}});}",ctx);
Object.assign(ctx, {presentation: () => ({current_actor_id: rider.entity_id}), tokenLabels: () => new Map(),
  visibility: () => null, actors: () => rows, TEAM_HEX: ['#fff'], teamIndex: () => 0,
  unseenByViewers: () => false, isManualActor: () => true, shownCondition: () => true,
  isOwnedActor:()=>false,isGMView:()=>true,reconcileViewerIdentity:()=>false,resumeViewerDialogs() {},roofAudience:()=>[],
  document:{body:{classList:{toggle() {}}}}, $:()=>null,
  conditionText: () => 'Test condition description', conditionTone: () => 'debuff', OBJECT_FACE: {},
  app: {selected: new Set(), state: {tokens: {}, presentation: {battlefield: {blocked_cells: []}}}, targeting: {byTarget: new Map(rows.map(a => [a.entity_id, []]))}},
  board: {map: {width: 20}, setTokens: ctx.setTokens, setFog() {}, setRoofView() {}}});
vm.runInContext(body(page, 'tokenImage') + '\n' + body(page, 'fogGeometry') + '\n' + body(page, 'renderTokens'), ctx);
// Use the new shared object module, as the actual page does (no browser), with its real
// arrangement and wall-opening dependencies (object-presentation.js imports both), plus the
// destructible-wall painter board.js setTokens calls (wall-object-art.js and its wall-art.js).
for (const dep of ['object-arrange.js', 'wall-openings.js', 'wall-art.js', 'wall-object-art.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/tabletop', dep), 'utf8')
    .replace(/^import .*;$/mg, '').replace(/^export /mg, ''), ctx);
}
const objectPresentation = fs.readFileSync(path.join(__dirname, '../static/tabletop/object-presentation.js'), 'utf8');
vm.runInContext(objectPresentation.replace(/^import .*;$/mg, '').replace(/^export /mg, ''), ctx);
ctx.renderTokens();
const rn = tokens.get(rider.entity_id).node, mn = tokens.get(mount.entity_id).node;
assert.equal(rn.style.width, '51.2px'); assert.equal(mn.style.width, '128px');
assert.ok(rn.classList.contains('is-riding')); assert.ok(mn.classList.contains('is-large'));
const click = {stopPropagation() {}};
rn.events.click(click); mn.events.click(click);
assert.deepEqual(clicked, [rider.entity_id, mount.entity_id]);
console.log('mounted table footprint and target geometry: PASS');
Object.assign(ctx, {window: {innerWidth: 1024},
  escapeText: text => String(text ?? '').replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]))});
ctx.card.node = ctx.hover.node;
vm.runInContext(body(board, 'showCard') + '\n' + body(board, 'hideCard'), ctx);
for (const [hovered, relation, other] of [[rider, 'Riding', mount], [mount, 'Ridden by', rider]]) {
  ctx.showCard(tokens.get(hovered.entity_id));
  const html = ctx.card.node.innerHTML;
  assert.ok(html.includes(`${relation} ${ctx.escapeText(other.display_name)}`));
  for (const a of [rider, mount]) {
    assert.ok(html.includes(`${a.hit_points.current} / ${a.hit_points.maximum} HP`));
    assert.ok(html.includes(ctx.escapeText(a.display_name)));
  }
}
// Updating the companion after the hovered entry must refresh the open card as well.
ctx.showCard(tokens.get(rider.entity_id));
mount.hit_points.current = 7;
mount.conditions.push({condition_id: 'test', display_name: '<Prone>', stacks: 1});
ctx.renderTokens();
assert.ok(ctx.card.node.innerHTML.includes(`7 / ${mount.hit_points.maximum} HP`));
assert.ok(ctx.card.node.innerHTML.includes('&lt;Prone&gt;'));
assert.ok(ctx.card.node.innerHTML.includes('Test condition description'));
tokens.get(mount.entity_id).data.hidden = true;
ctx.showCard(tokens.get(rider.entity_id));
assert.ok(!ctx.card.node.innerHTML.includes('tt-card-companion'), 'hidden companion stats are not leaked');
tokens.get(rider.entity_id).data.ridingOn = null;
ctx.showCard(tokens.get(rider.entity_id));
assert.ok(!ctx.card.node.innerHTML.includes('tt-card-companion'), 'dismounted card shows only self');
console.log('mounted cards, live refresh, visibility and dismount: PASS');
