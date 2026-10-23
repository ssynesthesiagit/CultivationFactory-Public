import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {fightSummaryHtml, summaryAutoOpen} from '../static/tabletop/fight-summary.js';
import {economyPills} from '../static/tabletop/action-economy.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {Element, installDOM} from './objects_dom_stub.mjs';
import {actor, createTableHarness, functionSource, IN, memoryStorage, OUT, tableState}
  from './viewer_identity_harness.mjs';

// These are the production functions, compiled without the unrelated lobby and
// action panels. The final test imports the complete, unmodified entry point.
// The shared DOM models handlers and dialog state, not layout, focus or top-layer
// painting; those remain part of the browser review procedure.
function production(h, names, extras = {}) {
  const bindings = {app:h.app, currentViewer:h.currentViewer,
    $:selector => h.document.querySelector(selector), document:h.document, window:h.window,
    presentation:() => h.app.state?.presentation,
    actorById:id => h.app.state?.presentation.actors.find(row => row.entity_id === id),
    openViewerPicker:h.openViewerPicker, ...extras};
  return new Function(...Object.keys(bindings),
    `${names.map(name => functionSource(name)).join('\n')}\nreturn {${names.join(',')}};`)
    (...Object.values(bindings));
}

function reactionHandlers(h) {
  // The dialog answer path now goes through the production wireReactionDialog and its
  // cancel chain (91545a4e); slice the real definitions so the answer promise is bound
  // exactly as the shipped table binds it. The hint line is presentation only here.
  return production(h, ['wireReactionDialog', 'abilityChoiceActive', 'abilityReserved',
    'cancelAbilityChoice', 'askReactionInput', 'askReaction'], {
    decisionText:prompt => prompt.title || 'Reaction', closeChoice:() => {},
    resumeViewerDialogs:h.resumeViewerDialogs,
    hint:() => {}, renderShapePanel:() => {}, renderActionBar:() => {},
    cancelTargeting:() => {}, releaseMapPick:() => {},
    escapeHtml:value => String(value ?? ''),
  });
}

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
async function until(check, message) {
  for (let i = 0; i < 100 && !check(); i++) await tick();
  assert.ok(check(), message);
}

function installTableDOM() {
  const dom = installDOM(readFileSync(new URL('../static/tabletop/tabletop.html',import.meta.url),'utf8'));
  // The real information renderer needs the native document/child-node contract.
  // Supply it only on this panel; keep the shared minimal DOM unchanged.
  const information = dom.querySelector('#ttInformation');
  information.ownerDocument = dom;
  Object.defineProperty(information, 'childNodes', {get: () => information.children});
  return dom;
}

// Import the shipped entry point, use its action transport and picker handlers,
// and control only HTTP completion order. No viewer arrays or lifecycle helpers
// are injected. The dialog stub observes open/close, not native browser focus.
async function latePromptTable(kind) {
  const dom = installTableDOM();
  const matchId = `late-${kind}`, viewId = `view-${kind}`;
  const storage = memoryStorage();
  createViewerStore({viewId,storage}).bindPlayer(matchId,['a']);
  window.sessionStorage = storage;
  window.localStorage = memoryStorage();
  Object.assign(location,{search:`?match=${matchId}&view=${viewId}`,
    origin:'http://localhost',href:`http://localhost/tabletop?match=${matchId}&view=${viewId}`});
  let poll;
  globalThis.setInterval = fn => { poll = fn; return 0; };
  const state = tableState([actor('a',OUT),actor('b',IN)],{matchId});
  Object.assign(state.presentation,{terminal:false,teams:[],initiative_order:[]});
  state.menu = {actor_id:'a',decision_id:'turn-1',state_version:1,
    actions:[],moves:[],end_turn:'end-turn'};
  const events = {events:[],dice:[],last_sequence:1};
  const prompt = {title:'Turn the Blade Aside',reaction:'Turn the Blade Aside',
    moment:'B attacks A. Spend 1 CP to make B hesitate.',
    context:{decision_id:'reaction-1',reactor_id:'a',reaction_source_id:'beauty-response'}};
  if (kind.includes('choice')) prompt.choice = {minimum:1,maximum:1,allow_decline:true,
    options:[{id:'b',label:'B',description:'Make B hesitate during this attack.'}]};
  const actionResponse = deferred(), seatResponse = deferred();
  const calls = [];
  let seats = 'valid', currentState = state;
  const response = result => ({ok:true,status:200,text:async() => JSON.stringify(result),json:async() => result});
  globalThis.fetch = async (path,options = {}) => {
    calls.push({path,options,body:options.body ? JSON.parse(options.body) : null});
    // Preparation reserves nothing; only the final /act is the submitted action these assertions count.
    if (path.endsWith('/prepare')) return response({status:'PREPARED'});
    if (path.endsWith('/act')) {
      const actions = calls.filter(call=>call.path.endsWith('/act'));
      return response(actions.length === 1 ? await actionResponse.promise
        : {status:'COMMITTED',state,events});
    }
    if (path.endsWith('/seat-status')) {
      if (seats === 'delayed') return response(await seatResponse.promise);
      if (seats === 'failed') throw Error('seat read unavailable');
      return response({seats:{}});
    }
    if (path === '/api/session') return response({token:'test'});
    if (path === '/api/tabletop/conditions') return response({conditions:{}});
    if (path === '/api/tabletop/providers') return response({providers:[]});
    if (path.includes('/events?')) return response(events);
    if (path.includes('/state?')) return response(structuredClone(currentState));
    throw Error(`Unexpected production API ${path}`);
  };
  await import(`../static/tabletop/tabletop.js?late-prompt-${kind}`);
  await until(()=>window.tabletop, 'the complete production table boots');
  const {app,act} = window.tabletop;
  assert.equal(dom.body.classList.contains('is-viewer-pending'), false, 'start with a valid chosen view');
  seats = 'delayed';
  const idleRead = poll();
  await until(()=>calls.filter(call=>call.path.endsWith('/seat-status')).length >= 2,
    'idle seat-status read is in flight before the action');
  let settled = false;
  const action = act('end-turn').then(value=>{settled=true;return value;});
  await until(()=>calls.some(call=>call.path.endsWith('/act')), 'real action request is in flight');
  seats = 'failed';
  seatResponse.reject(Error('delayed seat read failed'));
  await idleRead;
  assert.equal(app.seatStatus, null);
  assert.equal(dom.body.classList.contains('is-viewer-pending'), true);
  const dialog = dom.querySelector('#ttReaction');
  // Native dialogs start with open=false; the minimal DOM leaves it undefined
  // until the first open/close. Establish that native default before observing.
  dialog.close();
  let openings = 0;
  const show = dialog.showModal.bind(dialog);
  dialog.showModal = () => { openings++; show(); };
  currentState = {...state,pending_action:{request:{candidate_id:'end-turn'},reaction:prompt}};
  actionResponse.resolve({status:'REACTION_REQUIRED',reaction:prompt,events});
  await until(()=>app.waitingReaction && app.finishReaction, 'the action received its late prompt');
  await tick();
  const waiting = app.waitingReaction, finish = app.finishReaction;
  assert.equal(dialog.open, false, `${kind}: late prompt must never open a hidden blocking modal`);
  assert.equal(openings, 0, 'no showModal call occurs while identity is unavailable');
  assert.equal(settled, false, 'the original action still waits for the player');
  assert.equal(dom.querySelector('#ttViewerChange').disabled, false);
  assert.equal(dom.querySelector('#ttViewerRetry').hidden, false);
  await dom.querySelector('#ttViewerChange').click();
  assert.equal(dom.querySelector('#ttViewerPicker').open, true, 'recovery picker remains reachable');
  dom.querySelector('#ttViewerPicker').close();
  for (let i=0;i<2;i++) {
    const count = calls.length;
    await dom.querySelector('#ttViewerRetry').click();
    await until(()=>calls.length>count, 'Check controls again sends a read');
    await tick();
    assert.equal(dialog.open, false, 'repeated same-key failed reads leave no hidden modal');
    assert.equal(app.waitingReaction, waiting);
    assert.equal(app.finishReaction, finish);
  }
  return {dom,app,action,waiting,finish,prompt,calls,poll,
    setSeats:value=>{seats=value;},setState:value=>{currentState=value;},state,
    isSettled:()=>settled,openings:()=>openings};
}

test('remote completion cleans a deferred list choice before recovery or a match switch', async () => {
  const h = await latePromptTable('list-choice-remote');
  assert.equal(await window.tabletop.loadMatch('other'), false,
    'the existing busy guard prevents switching away from an outstanding action');
  h.setState(h.state); // Another client has answered the saved decision.
  await h.poll();
  assert.equal(await h.action, true);
  const dialog = h.dom.querySelector('#ttReaction');
  assert.equal(h.calls.filter(call=>call.path.endsWith('/act')).length, 1,
    'a superseded decision sends no fabricated answer');
  assert.equal(h.app.waitingReaction, null);
  assert.equal(h.app.finishReaction, null);
  assert.equal(h.app.viewerSuspendedReaction, null);
  assert.equal((dialog.listeners.get('cancel') || []).length, 0);
  assert.equal(h.openings(), 0);
  h.setSeats('valid');
  h.setState({...h.state,presentation:{...h.state.presentation,match_id:'other'}});
  await window.tabletop.loadMatch('other');
  await h.dom.querySelector('#ttViewerGM').click();
  assert.equal(h.app.matchId, 'other');
  assert.equal(dialog.open, false, 'the completed old decision cannot revive in another fight');
  assert.equal(h.openings(), 0);
});

test('explicit Game Master identity resumes the same late reaction and a user cancel answers once', async () => {
  const h = await latePromptTable('reaction-gm');
  await h.dom.querySelector('#ttViewerChange').click();
  await h.dom.querySelector('#ttViewerGM').click();
  const dialog = h.dom.querySelector('#ttReaction');
  assert.equal(dialog.open, true);
  assert.equal(h.openings(), 1);
  assert.equal(h.app.waitingReaction, h.waiting);
  assert.equal(h.app.finishReaction, h.finish);
  assert.equal(h.isSettled(), false);
  assert.equal(h.calls.filter(call=>call.path.endsWith('/act')).length, 1);
  assert.equal(h.dom.body.classList.contains('is-viewer-pending'), false);
  await dialog.dispatch('cancel');
  assert.equal(await h.action, true);
  const actions = h.calls.filter(call=>call.path.endsWith('/act'));
  assert.equal(actions.length, 2);
  assert.deepEqual(actions[1].body.reactions, [{...h.prompt.context,selection:'DECLINE'}]);
  assert.equal(h.app.viewerSuspendedReaction, null);
  assert.equal(h.app.finishReaction, null);
  assert.equal((dialog.listeners.get('cancel') || []).length, 0);
});

for (const kind of ['reaction','list-choice']) {
  test(`complete production action defers a late ${kind} until identity recovery`, async () => {
    const h = await latePromptTable(kind);
    const dialog = h.dom.querySelector('#ttReaction');
    let openings = 0;
    const show = dialog.showModal.bind(dialog);
    dialog.showModal = () => { openings++; show(); };
    h.setSeats('valid');
    await h.dom.querySelector('#ttViewerRetry').click();
    await until(()=>dialog.open, 'the same prompt reopens after successful seat recovery');
    await h.poll();
    assert.equal(openings, 1, 'recovery and subsequent reads present the pending prompt exactly once');
    assert.equal(h.app.waitingReaction, h.waiting);
    assert.equal(h.app.finishReaction, h.finish);
    assert.equal(h.dom.querySelector('#ttReactionTitle').textContent, h.prompt.title);
    assert.match(h.dom.querySelector('#ttReactionText').innerHTML, /B attacks A/);
    assert.equal(h.isSettled(), false);
    assert.equal(h.calls.filter(call=>call.path.endsWith('/act')).length, 1,
      'identity recovery neither retries the action nor submits an answer');
    const button = dialog.querySelector(kind === 'reaction' ? '[data-answer="USE"]' : '[data-option="b"]');
    assert.ok(button, 'the original choice remains available');
    button.onclick();
    assert.equal(await h.action, true);
    const actions = h.calls.filter(call=>call.path.endsWith('/act'));
    assert.equal(actions.length, 2, 'only the user answer continues the original transport');
    assert.deepEqual(actions[0].body.reactions, []);
    assert.deepEqual(actions[1].body.reactions, [{...h.prompt.context,selection:'USE',
      ...(kind === 'list-choice' ? {option_ids:['b']} : {})}]);
    assert.equal(h.app.waitingReaction, null);
    assert.equal(h.app.finishReaction, null);
    assert.equal(h.app.viewerSuspendedReaction, null);
    assert.equal((dialog.listeners.get('cancel') || []).length, 0, 'answer removes its cancel listener');
    assert.equal(dialog.open, false);
  });
}

test('player confirmation refuses empty, missing and nonprimary choices without opening the map', async () => {
  const h = createTableHarness({roster:[actor('a',OUT),
    actor('summon',IN,{primary_combatant:false,owner_id:'a',summon_status:'present'})]});
  const picker = h.document.querySelector('#ttViewerPicker');
  assert.equal(picker.open, true);
  await h.document.querySelector('#ttViewerApply').click();
  for (const ids of [['missing'], ['summon'], ['a','missing']]) assert.equal(h.savePlayerView(ids), false);
  assert.equal(h.viewerStore.read('match'), null);
  assert.equal(h.currentViewer().ready, false);
  assert.equal(picker.open, true, 'invalid confirmation keeps the picker usable');
  assert.equal(h.document.body.classList.contains('is-viewer-pending'), true);
  assert.ok(h.board.tokenNode('a').classList.contains('is-hidden'));
  assert.equal(h.calls.length, 0, 'choosing a view sends no fight mutation');
  assert.equal(h.messages.length, 4);
});

test('changing GM fog to a player mode requires an explicit fighter confirmation', async () => {
  const h = createTableHarness({gm:true,roster:[actor('a',OUT),actor('b',IN)]});
  const fog = h.document.querySelector('#ttFog');
  fog.value = 'team';
  await fog.dispatch('change');
  assert.equal(h.currentViewer().status, 'gm');
  assert.equal(h.viewerStore.readFog('match'), 'off');
  assert.equal(fog.value, 'off');
  assert.equal(h.document.querySelector('#ttViewerPicker').open, true);
  const choice = h.document.querySelector('#ttViewerChoices').querySelectorAll('input')
    .find(input => input.value === 'b');
  choice.checked = true;
  await h.document.querySelector('#ttViewerApply').click();
  assert.equal(h.currentViewer().status, 'player');
  assert.deepEqual([...h.currentViewer().ownedIds], ['b']);
  assert.equal(h.viewerStore.readFog('match'), 'own');
  assert.equal(fog.value, 'own');
  assert.equal(h.document.querySelector('#ttViewerPicker').open, false);
  assert.equal(h.calls.length, 0);
});

test('covering a live reaction closes its modal without answering and resumes the same prompt', async () => {
  const h = createTableHarness({boundIds:['own']});
  const {askReaction} = reactionHandlers(h);
  let settled = false;
  const answer = askReaction({title:'Use your reaction?'}).then(value => {settled = true;return value;});
  const dialog = h.document.querySelector('#ttReaction');
  const waiting = h.app.waitingReaction, finish = h.app.finishReaction;
  assert.equal(dialog.open, true);
  h.app.seatStatus = null;
  h.renderTokens();
  await tick();
  assert.equal(dialog.open, false, 'the hidden modal no longer makes the page inert');
  assert.equal(settled, false, 'identity checks do not choose DECLINE or USE');
  assert.equal(h.app.waitingReaction, waiting);
  assert.equal(h.app.finishReaction, finish);
  assert.equal(h.document.body.classList.contains('is-viewer-pending'), true);
  h.app.seatStatus = {seats:{}};
  h.renderTokens();
  assert.equal(dialog.open, true);
  assert.equal(h.app.viewerSuspendedReaction, null);
  assert.equal(settled, false);
  dialog.querySelector('[data-answer="USE"]').onclick();
  assert.equal(await answer, 'USE');
  assert.equal(dialog.open, false);
  assert.equal(h.app.waitingReaction, null);
  assert.equal(h.calls.length, 0);
});

test('a superseded reaction cannot reopen after identity checking finishes', async () => {
  const h = createTableHarness({boundIds:['own']});
  const {askReaction} = reactionHandlers(h);
  const answer = askReaction({title:'Old prompt'});
  const waiting = h.app.waitingReaction;
  h.app.seatStatus = null;
  h.renderTokens();
  const remote = {...h.nextState,last_sequence:2};
  waiting.stop(remote);
  assert.deepEqual(await answer, {superseded:true,preparation:false,state:remote});
  h.app.seatStatus = {seats:{}};
  h.renderTokens();
  assert.equal(h.document.querySelector('#ttReaction').open, false);
  assert.equal(h.app.viewerSuspendedReaction, null);
  assert.equal(h.app.finishReaction, null);
  assert.equal(h.calls.length, 0);
});

test('suspended dialog tokens do not cross a match or a replacement prompt', () => {
  for (const changed of ['match','waiting','finish']) {
    const h = createTableHarness({boundIds:['own']});
    const dialog = h.document.querySelector('#ttReaction');
    h.app.waitingReaction = {prompt:'old'};
    h.app.finishReaction = () => {throw Error('suspending must not answer');};
    dialog.showModal();
    h.suspendViewerDialogs();
    if (changed === 'match') {
      h.app.matchId = 'other';
      h.viewerStore.bindPlayer('other',['own']);
    } else if (changed === 'waiting') h.app.waitingReaction = {prompt:'new'};
    else h.app.finishReaction = () => {};
    h.resumeViewerDialogs();
    assert.equal(dialog.open, false, `${changed} mismatch discards the suspended modal`);
    assert.equal(h.app.viewerSuspendedReaction, null);
  }
});

test('identity changes close passive summary and seat dialogs without reopening them', () => {
  const h = createTableHarness({boundIds:['own']});
  const dialogs = ['#ttSummary','#ttSeat','#ttSeatLog'].map(id => h.document.querySelector(id));
  dialogs.forEach(dialog => dialog.showModal());
  h.app.seatStatus = null;
  h.renderTokens();
  assert.ok(dialogs.every(dialog => !dialog.open));
  h.app.seatStatus = {seats:{}};
  h.renderTokens();
  assert.ok(dialogs.every(dialog => !dialog.open));
  assert.equal(h.calls.length, 0);
});

test('a covered terminal fight preserves its one-time summary until the viewer is ready', async () => {
  const state = tableState([actor('own',OUT)]);
  state.presentation.terminal = true;
  state.summary = {actors:[],limitations:['A recorded summary is available.']};
  const h = createTableHarness({state});
  const {renderActionBar,openFightSummary} = production(h, ['renderActionBar','openFightSummary'], {
    fightSummaryHtml,summaryAutoOpen,initials:() => '',TEAM_COLORS:['#fff'],tokenImage:() => null,
    openLobby:() => {},
  });
  await renderActionBar();
  openFightSummary();
  assert.equal(h.app.summaryShownFor, undefined);
  assert.ok(!h.document.querySelector('#ttSummary').open);
  assert.match(h.document.querySelector('#ttActionBar').textContent, /Choose My fighters/);
  assert.equal(h.savePlayerView(['own']), true);
  await renderActionBar();
  assert.equal(h.app.summaryShownFor, 'match');
  assert.equal(h.document.querySelector('#ttSummary').open, true);
  assert.match(h.document.querySelector('#ttSummaryBody').innerHTML, /recorded summary/);
  h.document.querySelector('#ttSummary').close();
  await renderActionBar();
  assert.equal(h.document.querySelector('#ttSummary').open, false, 'automatic summary is still once per fight');
});

test('the mini sheet is cleared while covered and cannot be opened before confirmation', async () => {
  const h = createTableHarness({boundIds:['own']});
  const root = new Element('div');
  root.className = 'tt-pip-root';
  // Model the native textContent setter here, because the shared minimal DOM's
  // plain text property deliberately does not model removal of child elements.
  let text = '';
  Object.defineProperty(root,'textContent',{get:() => text,set:value => {
    text = String(value);root.replaceChildren();
  }});
  const pipDocument = {querySelector:selector => selector === '.tt-pip-root' ? root : null,
    createElement:tag => new Element(tag)};
  h.app.pip = {closed:false,document:pipDocument};
  let requested = 0;
  h.window.documentPictureInPicture = {requestWindow:() => {requested++;throw Error('must stay covered');}};
  const {renderPip,openPip} = production(h,['renderPip','openPip'],{
    pct:(current,maximum) => current/maximum*100,movementLeft:() => '30 ft',economyPills,
  });
  h.app.selected.add('own');
  renderPip();
  assert.equal(root.querySelector('strong').textContent, 'own');
  h.app.seatStatus = null;
  h.renderTokens();
  assert.equal(root.querySelector('strong'), null, 'cover synchronously removes prior fighter stats');
  assert.match(root.textContent, /Choose My fighters/);
  h.app.selected.add('own');
  renderPip();
  assert.equal(root.querySelector('strong'), null);
  await openPip();
  assert.equal(requested, 0);
  assert.equal(h.document.querySelector('#ttViewerPicker').open, true);
  h.app.seatStatus = {seats:{}};
  h.renderTokens();
  h.app.selected.add('own');
  renderPip();
  assert.equal(root.querySelector('strong').textContent, 'own');
});

for (const chosen of ['a', 'b']) {
test(`the complete production table binds ${chosen}, replaces private facts on rebinding, and clears them for GM`, async () => {
  const other = chosen === 'a' ? 'b' : 'a';
  const dom = installTableDOM();
  assert.equal(dom.body.classList.contains('is-viewer-pending'), true, 'markup covers the first frame before script execution');
  const storage = memoryStorage();
  window.sessionStorage = storage;
  window.localStorage = memoryStorage([['tt-fog','off']]);
  location.search = '?match=dialog-boot&view=boot-view';
  location.origin = 'http://localhost';
  location.href = `http://localhost/tabletop${location.search}`;
  const state = tableState([actor('a',OUT),actor('b',IN)],{matchId:'dialog-boot'});
  state.observer_information = {
    a:{information_text:['Bloodsense: A senses spilled blood.']},
    b:{information_text:['Bloodsense: B senses a fresh wound.']},
  };
  Object.assign(state.presentation,{terminal:true,current_actor_id:null,teams:[],initiative_order:[]});
  const calls = [];
  globalThis.fetch = async (path,options = {}) => {
    calls.push({path,options});
    let result;
    if (path === '/api/session') result = {token:'test'};
    else if (path === '/api/tabletop/conditions') result = {conditions:{}};
    else if (path === '/api/tabletop/providers') result = {providers:[]};
    else if (path.endsWith('/seat-status')) result = {seats:{}};
    else if (path.includes('/events?')) result = {events:[],dice:[],last_sequence:1};
    else if (path.startsWith('/api/tabletop/matches/dialog-boot/state?')) result = structuredClone(state);
    else throw Error(`Unexpected boot API ${path}`);
    return {ok:true,status:200,text:async() => JSON.stringify(result),json:async() => result};
  };
  await import(`../static/tabletop/tabletop.js?viewer-identity-dialog-test-${chosen}`);
  for (let i = 0; i < 100 && !window.tabletop; i++) await tick();
  assert.ok(window.tabletop, dom.querySelector('.tt-toast.is-error')?.textContent || 'table startup settled');
  const {app,board} = window.tabletop;
  assert.equal(app.state?.presentation.match_id, 'dialog-boot');
  assert.equal(app.fog, 'own', 'an old origin-wide GM preference does not supply a role');
  assert.equal(dom.body.classList.contains('is-viewer-pending'), true);
  assert.equal(board.tokenNode('a').classList.contains('is-hidden'), true);
  assert.equal(board.tokenNode('b').classList.contains('is-hidden'), true);
  assert.equal(dom.querySelector('#ttInformation').hidden, true, 'private facts stay covered before confirmation');
  assert.equal(dom.querySelector('#ttViewerPicker').open, true);
  const choices = dom.querySelector('#ttViewerChoices').querySelectorAll('input');
  assert.deepEqual(choices.map(input => input.value), ['a','b']);
  choices.find(input => input.value === chosen).checked = true;
  await dom.querySelector('#ttViewerApply').click();
  assert.equal(dom.querySelector('#ttViewerPicker').open, false);
  assert.equal(dom.body.classList.contains('is-viewer-pending'), false);
  assert.equal(board.tokenNode(chosen).classList.contains('is-hidden'), false);
  assert.equal(board.tokenNode(other).classList.contains('is-hidden'), true);
  if (chosen === 'b') {
    assert.equal(board.element.querySelector('[data-roof]').style.opacity, '0', 'the confirmed occupant opens its building');
  }
  const reloaded = createViewerStore({viewId:'boot-view',storage});
  assert.deepEqual(reloaded.read('dialog-boot').actor_ids, [chosen]);
  assert.ok(calls.filter(call => call.path.includes('/state?')).every(call => call.path.includes('fog=true')));
  assert.ok(calls.every(call => !call.options.method || call.options.method === 'GET'));
  assert.equal(dom.querySelector('.tt-toast.is-error'), null);
  const information = dom.querySelector('#ttInformation');
  assert.deepEqual(information.querySelectorAll('p').map(node => node.textContent),
    state.observer_information[chosen].information_text, 'only the chosen fighter supplies private facts');
  assert.equal(information.hidden, false);
  await dom.querySelector('#ttViewerChange').click();
  const reboundChoices = dom.querySelector('#ttViewerChoices').querySelectorAll('input');
  for (const input of reboundChoices) input.checked = input.value === other;
  await dom.querySelector('#ttViewerApply').click();
  // Stores cache their own reads for a tab. Reconstruct one to check the
  // persisted rebind, just as a reload would, rather than reuse its old cache.
  assert.deepEqual(createViewerStore({viewId:'boot-view',storage}).read('dialog-boot').actor_ids, [other]);
  assert.deepEqual(information.querySelectorAll('p').map(node => node.textContent),
    state.observer_information[other].information_text, 'rebinding replaces the previous fighter\'s private facts');
  await dom.querySelector('#ttViewerChange').click();
  await dom.querySelector('#ttViewerGM').click();
  assert.equal(information.hidden, true, 'changing away from the player view clears private facts');
  assert.deepEqual(information.childNodes, []);
  assert.ok(calls.every(call => !call.options.method || call.options.method === 'GET'));
});
}
