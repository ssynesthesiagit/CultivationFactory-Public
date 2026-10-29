// Production table coordination, identity and rendering with real view/board/fog
// modules. Only network transport, unrelated panels and browser layout are stubbed.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setTimeout as nativeTimeout, clearTimeout as nativeClearTimeout} from 'node:timers';
import {createBoard, initials, treeCells, CELL} from '../static/tabletop/board.js';
import {heightFeet, flightText} from '../static/tabletop/flight-ui.js';
import {DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView, fogViewers} from '../static/tabletop/fog_view.js';
import {isModelSeat, modelOwner, serverDriving} from '../static/tabletop/seats.js';
import {centerlineTerrain, opacityGrid, perceivedCells, perceivedObjects, tokenHiddenByFog, tokenSensePresentation, wallCells} from '../static/tabletop/vision.js';
import {wallSightCells} from '../static/tabletop/zones.js';
import {blockerSegments, visibilityPolygons} from '../static/tabletop/fog_polygon.js';
import {emptyMemory, loadMemory, memoryKey} from '../static/tabletop/fog_memory.js';
import {createFogMemoryStore} from '../static/tabletop/fog_memory_store.js';
import {altitudeVisibilityPolygons, altitudeFogKey, viewerEye} from '../static/tabletop/fog-altitude.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';
import {decisionChanged} from '../static/tabletop/pending-decision.js';
import {createViewerStore, resolveViewerIdentity, isPrimaryFighter, mintViewId, isValidViewId}
  from '../static/tabletop/viewer-identity.js';
import {compactStatePath} from '../static/tabletop/movement-grid.js';
import {installDOM} from './objects_dom_stub.mjs';

export const TABLE_SOURCE = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
export function functionSource(name, source = TABLE_SOURCE, optional = false) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  if (optional && start < 0) return '';
  assert.ok(start >= 0, `production function ${name}`);
  const end = source.indexOf('\n}', start);
  assert.ok(end > start, `production function ${name} closes`);
  return source.slice(start, end + 2);
}
export function constSource(name, source = TABLE_SOURCE) {
  const line = source.split('\n').find(row => row.startsWith(`const ${name} =`));
  assert.ok(line, `production const ${name}`);
  return line;
}
export function memoryStorage(initial = []) {
  const values = new Map(initial);
  return {values, getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key)};
}
export function actor(id, position, extra = {}) {
  return {entity_id:id, display_name:id, controller:'MANUAL', team_index:0,
    primary_combatant:true, active:true, position, conditions:[],
    footprint:{width_cells:1,height_cells:1}, hit_points:{current:10,maximum:10}, ...extra};
}
export const OUT = {x:20,y:15}, IN = {x:4,y:4};
const village = JSON.parse(readFileSync(new URL('../combat/maps/builtin-willow-village-compound.json', import.meta.url), 'utf8'));
export function tableState(roster, {matchId = 'match', sequence = 1, perception = null, map = village} = {}) {
  const width = map.width_squares ?? map.width, height = map.height_squares ?? map.height;
  return {last_sequence:sequence, items:[], objects:[], menu:null,
    map:{...map, floors:map.floors || (map.materials || []).filter(r=>r.material.startsWith('floor:'))
      .map(r=>({style:r.material.slice(6),cells:r.cells}))},
    presentation:{match_id:matchId, display_name:'Identity test', round_number:1,
      current_actor_id:roster[0]?.entity_id, actors:roster, zones:[],
      battlefield:{display_name:'Willow Village Compound',width_squares:width,height_squares:height,
        blocked_cells:[],cover_cells:[],hazard_cells:[],difficult_cells:[],terrain_regions:[]}},
    fog_perception:perception || Object.fromEntries(roster.filter(a=>a.position)
      .map(a=>[a.entity_id,{cells:[[a.position.x,a.position.y]],creatures:[a.entity_id]}]))};
}

export function createTableHarness({viewId = 'view-one', storage = memoryStorage(), boundIds = null,
  gm = false, fog = null, roster = [actor('own',OUT)], state = null, seats = {seats:{}},
  matchId = 'match', initialize = true, source = TABLE_SOURCE, boardFactory = createBoard} = {}) {
  // Real markup includes the first-frame player-view gate and the real picker.
  const html = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  const document = installDOM(html);
  const window = globalThis.window;
  // The DOM stub has no layout; real timers still yield at every movement step.
  globalThis.setTimeout = (fn, ms, ...args) => nativeTimeout(fn, Math.min(Number(ms) || 0, 2), ...args);
  globalThis.clearTimeout = nativeClearTimeout;
  globalThis.requestAnimationFrame = fn => nativeTimeout(fn, 0);
  globalThis.cancelAnimationFrame = nativeClearTimeout;
  const location = {search:`?match=${matchId}&view=${viewId}&fogSquares=1`,
    href:`http://localhost/tabletop?match=${matchId}&view=${viewId}&fogSquares=1`,origin:'http://localhost'};
  const urls = [], calls = [], fogFrames = [], tokenFrames = [], messages = [], opens = [], prompts = [];
  window.open = (...args) => {opens.push(args);return null;};
  const history = {replaceState: (_data, _title, url) => { urls.push(url); location.search = url.slice(url.indexOf('?')); }};
  const viewerStore = createViewerStore({viewId, storage});
  if (boundIds) viewerStore.bindPlayer(matchId, boundIds);
  if (gm) viewerStore.bindGM(matchId);
  if (!gm && fog !== null) viewerStore.writeFog(matchId, fog);
  const board = boardFactory(document.getElementById('ttViewport'));
  const setFog = board.setFog, setTokens = board.setTokens;
  board.setFog = (seen, explored, geometry) => {
    fogFrames.push({seen:seen && Array.from(seen),explored:explored && Array.from(explored)});
    return setFog(seen, explored, geometry);
  };
  board.setTokens = rows => {
    tokenFrames.push(rows.map(row=>({id:row.id,hidden:row.hidden,x:row.x,y:row.y})));
    return setTokens(rows);
  };
  const noop = () => {};
  let client;
  const bindings = {board, document, window, history, location, URL, URLSearchParams, heightFeet, flightText,
    viewerStore, viewId, resolveViewerIdentity, isPrimaryFighter, mintViewId, isValidViewId,
    createViewerStore, DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView, fogViewers,
    modelOwner, isModelSeat, serverDriving, initials, treeCells, centerlineTerrain, opacityGrid, perceivedCells, perceivedObjects,
    tokenHiddenByFog, tokenSensePresentation, wallCells, wallSightCells, blockerSegments, visibilityPolygons,
    altitudeVisibilityPolygons, altitudeFogKey, viewerEye,
    tableObjectTokens, decisionChanged, compactStatePath, TEAM_HEX:{0:'#fff',1:'#000',2:'#aaa'}, enc:encodeURIComponent,
    $: selector => document.querySelector(selector),
    escapeHtml: value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
    rememberFog:()=>null, emptyMemory, loadMemory, memoryKey, preferenceStorage: storage,
    fogMemoryStore:createFogMemoryStore({storage, backend:{supported:false,
      get:async()=>undefined, set:async()=>{}}}),
    shownCondition:()=>false, conditionText:()=>'', conditionTone:()=>'',
    renderCommitNotice:noop, invalidateTargeting:noop, renderZones:noop,
    hoverCard:{close:noop},
    renderInitiative:noop, renderRoster:noop, renderInspector:noop, renderActionBar:noop,
    renderItemsPanel:noop, renderShapePanel:noop, scheduleAutoPlay:noop, renderHighlights:noop,
    broadcastActors:noop, renderPip:noop, scheduleSeatPoll:noop,
    appendFeed:noop, appendTableLine:noop, gmNotice:noop, hint:noop,
    closeChoice:noop, cancelTargeting:noop, loadConditionInfo:noop,
    openLobby:noop, resumePendingAction:async pending=>prompts.push(pending),
    sleep:async()=>{}, toast:(...args)=>messages.push(args),
    loadProviders:async()=>{},
    api:async(url,options)=>{
      calls.push({url,options});
      if (client.api) return client.api(url,options);
      if (url.endsWith('/seat-status')) return client.nextSeats;
      if (url.includes('/events?')) return {events:[],dice:[],last_sequence:client.nextState.last_sequence};
      return client.nextState;
    },
    refresh:async()=>{client.render(client.nextState);},
  };
  const appStart = source.indexOf('const app = {');
  assert.ok(appStart >= 0, 'production app initialization');
  const appLiteral = source.slice(appStart, source.indexOf('\n};', appStart) + 3);
  const toggleStart = source.indexOf('$("#ttRoofs").addEventListener("click",');
  const toggleEnd = source.indexOf('$("#ttZoomOut")', toggleStart);
  assert.ok(toggleStart >= 0 && toggleEnd > toggleStart, 'production roof toggle handler');
  const pickerStart = source.indexOf('$("#ttFog").addEventListener("change",');
  const pickerEnd = source.indexOf('$("#ttZoomIn")', pickerStart);
  assert.ok(pickerStart >= 0 && pickerEnd > pickerStart, 'production identity picker handlers');
  const funcs = ['currentViewer','isGMView','suspendViewerDialogs','resumeViewerDialogs','resetViewerPresentation','renderViewerIdentity','reconcileViewerIdentity',
    'applyViewerChange','savePlayerView','selectGMView','openViewerPicker',
    'rememberFogView','setFogPicker','mapFromState','groveCells','loadMatch','readTableState','render',
    'fogAudience','roofAudience','visibility','rememberedCells','squareFogDebug','tabletopUrl','fogGeometry',
    'viewerIds','unseenByViewers','tokenLabels','tokenGeometry','tokenImage','renderTokens','playEvents','playEventBatch',
    'loadSeats','pollTable','renderObservedState','eventsThroughState','resumeServerPrompt','reconcileOptionDraft','handleUnavailableFight',
    'tokenIdsKey','rememberedTokenIds','closeLoadedFight'];
  const body = [appLiteral,'let refreshSequence = 0;','let seatReadSequence = 0;','const feedFollow = {on:true,unseen:0};',
    ...['presentation','offMap','actors','actorById','teamIndex','isManualActor','isOwnedActor'].map(name=>constSource(name,source)),
    ...funcs.map(name=>functionSource(name,source)), source.slice(toggleStart,toggleEnd),source.slice(pickerStart,pickerEnd),
    `return {app, ${funcs.join(',')}, isOwnedActor, viewerStore};`].join('\n');
  client = new Function(...Object.keys(bindings), body)(...Object.values(bindings));
  Object.assign(client,{board,document,window,history,location,urls,calls,fogFrames,tokenFrames,messages,opens,prompts,
    nextSeats:seats,nextState:state || tableState(roster,{matchId}),
    opacity:(index=0)=>board.element.querySelectorAll('[data-roof]')[index]?.style.opacity,
    position:id=>{
      const nums = board.tokenNode(id)?.style.transform.match(/-?\d+(?:\.\d+)?/g)?.map(Number);
      return nums ? {x:nums[0]/CELL,y:nums[1]/CELL} : null;
    }});
  if (initialize) {
    client.app.matchId = matchId;
    client.app.seatStatus = seats;
    client.app.movePositions = new Map();
    client.app.fog = viewerStore.readFog(matchId);
    client.render(client.nextState);
  }
  return client;
}
