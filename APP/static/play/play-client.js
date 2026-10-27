// Independent HTTP client/controller for /play. No imports from the desktop entry point.
import {enc} from '../tabletop/api.js';
import {automaticTurn} from '../tabletop/automatic-turn.js';
import {serverDriving, modelOwner} from '../tabletop/seats.js';
import {playerView, eligibleFighters, ownedMenu, ownPrompt, decisionKey, promptKey, optionsAt, pendingSubmission, mapPickOptions, mapPickAnswer} from './play-model.js';
import {node, button, renderActions, renderGuidedActions, renderOptions, renderReaction, renderCharacter} from './play-ui.js';
import {renderMap, fitFighters} from './play-board.js';
import {fightSummaryHtml} from '../tabletop/fight-summary.js?v=sol143-2';
import {CELL} from '../tabletop/board.js';
import {OptionDraft} from '../tabletop/option-composition.js';
import {expandMovementGrid} from '../tabletop/movement-grid.js';
import {expandSource, checkMove, retainMenuInspection, copyMoveInspection, menuInspectionKey, moveKey} from '../tabletop/assisted-menu.js';

export function createPlay({doc, request, board, viewerStore, memoryStore, controlStore, frame = callback => requestAnimationFrame(callback), onMatchChange = () => {}}) {
  const $ = id => doc.getElementById(id);
  let matchId = '', state = null, seats = null, sequence = 0, targeting = null, busy = false;
  let pickKey = '', pickIds = new Set();
  let chooserSequence = 0;
  let generation = 0, polling = false, displayedPrompt = '', lastTurn = '', listKey = '', mapKey = '';
  let summaryMatch = '';
  let readDone=Promise.resolve(), finishRead, characterData=null, conditionData={};
  let fullOptions=false, controlInitPending=false;
  let draft=null;
  const sheets = new Map();
  const controlChoices = new Map();
  const controlKey = () => `${matchId}:${binding()?.actor_ids?.[0]}`;
  const preferredControl = () => controlChoices.get(controlKey()) || controlStore?.read(controlKey());
  const binding = () => matchId ? viewerStore.read(matchId) : null;
  const view = () => playerView(binding(), state, seats);
  const myActor = () => state?.presentation?.actors?.find(a=>a.entity_id === binding()?.actor_ids?.[0]);
  const base = () => `/api/tabletop/matches/${enc(matchId)}`;
  const status = text => { $('status').textContent = text; };
  const modal = dialog => { if (!dialog.open) dialog.showModal(); };
  const cover = text => { $('mapCover').hidden = false; $('mapCover').textContent = text; board.closeHoverCard(); };

  async function sheetFor(actor, force = false) {
    const prefix = 'actor:factory.';
    if (!actor?.entity_id.startsWith(prefix)) return null;
    const project = actor.entity_id.slice(prefix.length);
    if (force || !sheets.has(project)) sheets.set(project, request(`/api/tabletop/characters/${enc(project)}/sheet`).catch(() => { sheets.delete(project); return null; }));
    return sheets.get(project);
  }
  function selectionUI(options = targeting?.options || []) {
    if (!targeting) return;
    $('actionTitle').textContent = `${targeting.label} — choose a target or square`;
    renderOptions($('actionList'),options,state,view(),(o,route)=>submit(o.candidate_id,route),cancel);
  }
  function cancel() {
    ++chooserSequence;
    targeting = null; listKey = ''; status('Choose an action. Pinch to zoom; drag to pan.'); render(); $('actionSheet').hidden = false;
  }
  function change() { fullOptions=true; targeting=null; listKey=''; render(); }
  function actionList(menu, sheet) {
    const host=$('actionList');
    const handlers={choose,move:()=>choose({label:'Move',options:menu.moves},true),end:()=>submit(menu.end_turn),
      confirm:submit,inspect:inspectSuggestion,change,families:state.shapes?.[menu?.actor_id] || []};
    if (menu?.control_mode === 'SUGGESTED' || menu?.turn_mode === 'Assisted')
      renderGuidedActions(host,menu,sheet,state,view(),handlers,fullOptions);
    else renderActions(host,menu,sheet,handlers);
    markDraftChoices();
    if (menu) {
      const label=node(doc,'label','Played by: '), select=node(doc,'select');
      select.setAttribute('aria-label','Played by');
      for (const [value,text] of [['SUGGESTED','Assisted — app suggests, you confirm'],['MANUAL','You — Manual, choose every action']]) {
        const option=node(doc,'option',text); option.value=value; select.append(option);
      }
      select.value=menu.control_mode === 'SUGGESTED' || menu.turn_mode === 'Assisted' ? 'SUGGESTED' : 'MANUAL';
      select.disabled=busy;
      select.addEventListener('change',()=>setControl(select.value));
      label.append(select); host.append(label);
    }
    if (busy) for (const b of host.querySelectorAll('button')) b.disabled=true;
  }
  async function inspectSuggestion(proposal) {
    if (busy || !ownedMenu(state,view()) || state.pending_action) return;
    const serial = ++chooserSequence, menu = state.menu, match = matchId, key = menuInspectionKey(state), epoch = generation;
    const current = () => serial === chooserSequence && epoch === generation && match === matchId && key === menuInspectionKey(state)
      && !busy && !!ownedMenu(state,view()) && !state.pending_action;
    const load = (path, options) => request(`/api/tabletop/matches/${enc(match)}${path}`, options);
    status(`Checking ${proposal.label}…`);
    try {
      if (proposal.unresolved) {
        const expanded = await expandSource(menu, proposal.group, load, current);
        if (!expanded) return;
        const row = state.menu.actions.find(g => g.source_definition_id === expanded.source_definition_id);
        if (row !== expanded) Object.assign(row, expanded);
        status(expanded.options.length ? 'Check the target and cost, then confirm this step.' : 'No legal targets for that action. Compare another step.');
      } else {
        const move = await checkMove(menu, proposal.option, load, current);
        if (!move) return;
        const row = state.menu.moves.find(m => moveKey(m) === moveKey(move));
        if (!row) return;
        if (row !== move) copyMoveInspection(row, move);
        status('Check the route and movement cost, then confirm this step.');
      }
      listKey = ''; render();
    } catch (error) { if (current()) status(error.message); }
  }
  function chooseSetting(candidateId) {
    const menu=ownedMenu(state,view());
    if (!menu?.composition?.[candidateId]) return false;
    if (!draft?.matches(menu,matchId)) draft=new OptionDraft(menu,matchId);
    draft.choose(candidateId);
    targeting=null;
    markDraftChoices();
    status('Options selected. Choose the ability and its target to use them. Each setting keeps its latest choice.');
    return true;
  }
  function markDraftChoices() {
    const selected=new Set([...(draft?.picks.values() || [])].map(p=>p.source));
    for (const b of $('actionList').querySelectorAll('[data-option-source]'))
      b.setAttribute('aria-pressed',String(selected.has(b.dataset.optionSource)));
    for (const b of $('actionList').querySelectorAll('[data-draft-only]'))
      b.disabled=busy || !draft?.dirty;
  }
  async function choose(group, move = false) {
    if (busy || !ownedMenu(state,view()) || state.pending_action) return;
    if (group.options?.length===1 && chooseSetting(group.options[0].candidate_id)) return;
    if (group.composition_only && !draft?.dirty) return;
    if (draft?.dirty && !move && !group.source_definition_id?.startsWith('system:')) {
      const key=decisionKey(state.menu), id=matchId;
      busy=true;
      try {
        await readDone;
        if (!draft?.matches(state.menu,matchId) || id!==matchId) throw new Error('The fight changed. Choose your options again.');
        const composition=draft.request(group.alias_of || group.source_definition_id,crypto.randomUUID());
        const result=await request(`${base()}/composition/preview`,{body:composition});
        if (id!==matchId || key!==decisionKey(state.menu)) throw new Error('The fight changed. Choose your options again.');
        const options=result.menu.actions.flatMap(g=>g.options);
        if (!options.length) throw new Error('No legal target is available for these options. Change your options and try again.');
        targeting={...group,options,move:false,key,boundary:menuInspectionKey(state),composition,preview:result.menu};
        selectionUI(); $('actionSheet').hidden=false;
        status(`${group.label}: choose a target or square. Your options will be saved when you use the ability.`);
      } catch (error) { status(error.message); }
      finally { busy=false; render(); }
      return;
    }
    const serial = ++chooserSequence;
    if (group.lazy) {
      const match = matchId, key = decisionKey(state.menu), menu = state.menu;
      status(`Loading ${group.label} choices…`);
      try {
        const query = new URLSearchParams({source: group.source_definition_id,
          decision_id: menu.decision_id, state_version: menu.state_version});
        const result = await request(`${base()}/action-options?${query}`);
        if (serial !== chooserSequence || matchId !== match || decisionKey(state?.menu) !== key || busy
            || !ownedMenu(state,view()) || state.pending_action) return;
        const expanded = result.actions.find(row => row.source_definition_id === group.source_definition_id);
        if (!expanded?.options?.length) { status(result.message || 'No legal options right now.'); return; }
        Object.assign(group, expanded, {lazy: false, expanded_from_lazy: true});
        const current = state.menu.actions?.find(row => row.source_definition_id === group.source_definition_id);
        if (current && current !== group) Object.assign(current, group);
      } catch (error) { status(error.message); return; }
    }
    // Destination-choice abilities ask for the destination during resolution, as on desktop.
    if (group.destination_choice && !group.placement_picker && group.options?.length) return submit(group.options[0].candidate_id);
    targeting = {...group,move,key:decisionKey(state.menu),boundary:menuInspectionKey(state)};
    selectionUI(); $('actionSheet').hidden = false;
    status(`${group.label}: tap a token or square on the map. All options are also listed in Actions. Cancel returns to your actions.`);
    render();
  }
  function drawReaction(pending) {
    const key = promptKey(pending);
    renderReaction($('reactionBody'), pending.reaction, {answer: a => answer(a, key), error: status,
      selected: [...pickIds], onSelect: (id, on) => { if (on) pickIds.add(id); else pickIds.delete(id); }});
  }
  function tapMapPick(cell, pending, options) {
    const hits = options.filter(o => o.cell.x === cell.x && o.cell.y === cell.y);
    if (!hits.length) return status('That square is not a legal choice. Tap a highlighted square or use the card.');
    if (hits.length > 1) return status('Several choices use this square. Choose one from the card.');
    const choice = pending.reaction.choice, key = promptKey(pending);
    if (choice.maximum <= 1) return answer(mapPickAnswer(pending, [hits[0].id]), key);
    if (pickKey !== key) { pickKey = key; pickIds = new Set(); }
    const id = hits[0].id;
    if (pickIds.has(id)) pickIds.delete(id);
    else if (pickIds.size >= choice.maximum) return status(`Choose up to ${choice.maximum} options, then confirm.`);
    else pickIds.add(id);
    drawReaction(pending);
    status(`${pickIds.size} of up to ${choice.maximum} selected. Confirm in the decision card.`);
  }
  function tap(cell, tokenId = null, screen = null) {
    if (!cell || !view().ready || busy) return;
    const pending = state?.pending_action, pick = mapPickOptions(pending, view());
    if (pick) return tapMapPick(cell, pending, pick);
    if (targeting) {
      const point = screen ? board.cellAt(screen.x,screen.y,{continuous:true}) : null;
      const near = p => point && Math.hypot(point.x-p.x-.5,point.y-p.y-.5)*CELL*board.view.zoom <= 22;
      const visible = state.presentation.actors.filter(a=>view().visible(a) && a.position && (near(a.position) || (cell.x>=a.position.x && cell.y>=a.position.y
        && cell.x<a.position.x+(a.footprint?.width_cells || 1) && cell.y<a.position.y+(a.footprint?.height_cells || 1))));
      const hits = new Map(optionsAt(targeting.options,cell,tokenId).map(o=>[o.candidate_id,o]));
      for (const actor of visible) for (const o of optionsAt(targeting.options,null,actor.entity_id)) hits.set(o.candidate_id,o);
      for (const object of state.objects || []) if (near(object) && view().seen[object.y*board.map.width+object.x])
        for (const o of optionsAt(targeting.options,null,object.id)) hits.set(o.candidate_id,o);
      const options = [...hits.values()];
      if (!options.length) { status('That square has no available option for this action. Choose another square or open Actions.'); return; }
      if (options.length === 1 && !options[0].can_jump_down) return submit(options[0].candidate_id);
      selectionUI(options); $('actionSheet').hidden = false; return;
    }
    if (tokenId && view().isOwned(tokenId)) return character();
    const at = state.presentation.actors.filter(a=>a.position && view().visible(a) && a.position.x===cell.x && a.position.y===cell.y);
    status(at.length ? at.map(a=>a.display_name).join(', ') : `Square ${cell.x+1}, ${cell.y+1}. Choose an action to target it.`);
  }
  // The recorded end-of-fight metrics (combat/fight_summary.py), opened once when
  // the end reaches this screen and reopenable from the footer button afterwards.
  function showSummary() {
    const p = state?.presentation;
    if (!p || !state.summary) return;
    const teams = p.teams || [];
    const teamOf = id => teams.find(team => team.team_id === id || team.runtime_team_ids?.includes(id));
    const initials = name => String(name || '').split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase();
    $('summaryBody').innerHTML = fightSummaryHtml(state.summary, {
      nameOf: id => p.actors.find(actor => actor.entity_id === id)?.display_name,
      initials, teamName: id => teamOf(id)?.display_name || 'Team',
      winner: p.terminal_result?.winning_team_id || null,
    });
    summaryMatch = matchId;
    modal($('summaryCard'));
  }

  function maybeSummary() {
    if (!state?.summary || summaryMatch === matchId || !view().ready) return;
    showSummary();
  }

  function render({mapRefresh = false} = {}) {
    if (!state) return;
    const v = view(), p = state.presentation, menu = ownedMenu(state,v), actor = myActor();
    if (draft && (!menu || !draft.matches(menu,matchId))) draft=null;
    const effective = v.ready && v.ownedIds.size > 0;
    $('map').hidden = !effective;
    if (!effective) $('characterCard').close();
    if (!effective) cover(v.reason === 'seats-unavailable' ? 'Character controls could not be checked. Reconnecting…' : 'Choose a manually controlled character to open your view.');
    if (targeting && (targeting.key !== decisionKey(state.menu) || targeting.boundary !== menuInspectionKey(state))) { targeting=null; listKey=''; status('The turn changed. Choose your action again.'); }
    if (effective) {
      const signature=JSON.stringify([p,state.map,state.fog_perception,state.objects,state.items,binding(),[...v.ownedIds],targeting]);
      let changed=false;
      if (mapRefresh || signature!==mapKey) {
        changed=renderMap(board,state,v,{matchId,actorId:actor?.entity_id,memoryStore,targeting});
        mapKey=signature;
      }
      $('mapCover').hidden = true;
      if (changed) frame(()=>{fitFighters(board,state,view()); $('map').style.setProperty('--play-zoom',board.view.zoom);});
    }
    $('fightName').textContent = p.display_name || 'Fight';
    const current = p.actors.find(a=>a.entity_id===p.current_actor_id);
    $('turn').textContent = p.terminal ? 'Fight over' : `Round ${p.round_number} · ${current && v.visible(current) ? current.display_name : 'Another creature'}’s turn`;
    $('summaryButton').hidden = !p.terminal;
    maybeSummary();
    $('yourTurn').hidden = !menu || !!state.pending_action;
    $('actionsButton').disabled = !menu || busy || !!state.pending_action;
    $('characterButton').disabled = !effective;
    $('chooseFight').disabled = busy;
    if (effective && $('characterCard').open) renderCharacter($('characterBody'),actor,characterData,conditionData);
    $('nextStep').hidden = !effective || !state.menu || state.menu.manual || !!state.pending_action || !!modelOwner(seats,current) || serverDriving(seats) || !!p.terminal;
    $('nextStep').disabled = busy;
    if (!targeting) {
      $('actionTitle').textContent = menu ? `${p.actors.find(a=>a.entity_id===menu.actor_id)?.display_name || 'Your character'}’s actions` : 'Your actions';
      const key = JSON.stringify([menu,state.button_states,fullOptions,busy]);
      if (key !== listKey) {
        listKey = key;
        actionList(menu,null);
        const expected = menu;
        if (menu) sheetFor(p.actors.find(a=>a.entity_id===menu.actor_id)).then(sheet=>{
          if (expected === ownedMenu(state,view()) && !targeting) actionList(menu,sheet);
        });
      }
    }
    if (!menu || state.pending_action) $('actionSheet').hidden = true;
    if (menu && lastTurn !== menu.actor_id && !state.pending_action) $('actionSheet').hidden = false;
    lastTurn = menu?.actor_id || '';
    const pending = state.pending_action, prompt = ownPrompt(pending,v) ? pending : null;
    const key = promptKey(prompt);
    if (key !== displayedPrompt) {
      displayedPrompt = key;
      if (prompt) {
        $('reactionTitle').textContent = prompt.reaction.title || prompt.reaction.reaction || 'Your decision';
        if (pickKey !== key) { pickKey = key; pickIds = new Set(); }
        renderReaction($('reactionBody'),prompt.reaction,{answer:a=>answer(a,key),error:status,selected:[...pickIds],onSelect:(id,on)=>{if(on)pickIds.add(id);else pickIds.delete(id);}}); modal($('reactionCard'));
      } else $('reactionCard').close();
    }
    if (pending && !prompt) status('Waiting for another player’s decision. Your view remains open.');
    for (const host of [$('actionList'),$('reactionBody')]) for (const b of host.querySelectorAll('button'))
      b.disabled=busy || (b.hasAttribute('data-draft-only') && !draft?.dirty);
  }
  async function refresh({force = false} = {}) {
    if (!matchId || (busy && !force) || polling) return;
    polling = true;
    readDone=new Promise(resolve=>{finishRead=resolve;});
    const id = matchId, epoch = generation, path = base();
    const query = new URLSearchParams({fog:'true',fog_view:'own',compact:'true'});
    for (const actor of binding()?.actor_ids || []) query.append('fog_actor_ids',actor);
    try {
      if (draft && !force) {
        const [feed,control]=await Promise.all([request(`${path}/events?after=${sequence}`),request(`${path}/seat-status`).catch(()=>null)]);
        if (id!==matchId || epoch!==generation) return;
        seats=control;
        if (!(feed.events?.length) && (feed.last_sequence ?? sequence)===sequence) { render(); return; }
      }
      const [snapshot,control] = await Promise.all([request(`${path}/state?${query}`),request(`${path}/seat-status`).catch(()=>null)]);
      if (id!==matchId || epoch!==generation) return;
      const feed = await request(`${path}/events?after=${sequence}`);
      if (id!==matchId || epoch!==generation) return;
      if (snapshot.menu?.movement_grid) snapshot.menu = expandMovementGrid(snapshot.menu);
      retainMenuInspection(state, snapshot);
      seats = control; state = snapshot;
      if (targeting?.move && targeting.boundary === menuInspectionKey(state)) {
        const moves = new Map((state.menu.moves || []).map(m => [moveKey(m), m]));
        targeting.options = targeting.options.flatMap(old => moves.has(moveKey(old)) ? [moves.get(moveKey(old))] : []);
        selectionUI();
      }
      // Sequence is advanced only after events have been read; no gap on hidden-only updates.
      sequence = Math.max(sequence,snapshot.last_sequence || 0,feed.last_sequence || 0);
      if (!targeting && !snapshot.pending_action && !busy) {
        // Events are read to keep the journal cursor contiguous. Their prose may
        // name unseen opponents, so the phone announces updates without that text.
        if (feed.events?.length) status('The fight has updated. Check the turn indicator and your actions.');
      }
      render();
    } catch (error) {
      seats=null; render(); cover('Connection lost. Reconnecting before showing the map or accepting actions.');
      status(error.message);
    } finally { polling=false; finishRead(); }
    // Entry may be waiting on a decision answered by a different client. Once
    // it clears, initialize control without requiring another bind or reload.
    if (controlInitPending && !busy && id===matchId && epoch===generation
        && view().isOwned(myActor()) && !state.pending_action) await defaultControl();
  }
  async function load(id) {
    if (busy) return;
    generation++; matchId=id; state=null; seats=null; sequence=0; targeting=null; draft=null; displayedPrompt=''; lastTurn=''; listKey=''; mapKey=''; fullOptions=false; controlInitPending=false;
    characterData=null;conditionData={};
    const epoch=generation;
    onMatchChange(id);
    $('reactionCard').close(); $('characterCard').close(); $('actionSheet').hidden=true;
    $('summaryCard').close(); summaryMatch='';
    cover('Checking your character’s view…');
    await readDone;
    if (epoch!==generation) return;
    await refresh();
    fillFighters();
    await defaultControl();
  }
  function fillFighters() {
    $('fighters').replaceChildren();
    for (const actor of eligibleFighters(state,seats)) {
      const option = node(doc,'option',actor.display_name); option.value=actor.entity_id; $('fighters').append(option);
    }
    $('bind').disabled = !$('fighters').options.length;
  }
  async function lobby() {
    if (busy) return;
    modal($('bindingCard'));
    try {
      const rows = await request('/api/combat/matches');
      $('fights').replaceChildren();
      for (const row of rows.slice().reverse()) { const option=node(doc,'option',row.display_name || 'Saved fight'); option.value=row.match_id; $('fights').append(option); }
      if (matchId) $('fights').value=matchId;
      if (!state && $('fights').value) await load($('fights').value);
      fillFighters();
      if (!rows.length) status('No saved fights yet. Ask your Game Master to open a fight on the table.');
    } catch (error) { status(error.message); }
  }
  async function bind(actorId = $('fighters').value) {
    if (busy || !eligibleFighters(state,seats).some(a=>a.entity_id===actorId)) { status('Choose a manually controlled character from this fight.'); return false; }
    cover('Opening your character’s view…');
    viewerStore.bindPlayer(matchId,[actorId]);
    generation++; listKey=''; displayedPrompt=''; controlInitPending=false;
    $('characterCard').close();characterData=null;conditionData={};
    $('bindingCard').close();
    await readDone;
    await refresh();
    return defaultControl();
  }
  async function defaultControl() {
    // Initialize a restored phone binding too; an explicit Manual choice wins
    // on later visits. Wait for seat authority and pending decisions to recover
    // before changing control, including when entry's first state read failed.
    // The saved player binding records intent even before a roster is available;
    // ownership is still checked below and again immediately before the write.
    controlInitPending=binding()?.role === 'player' && !!binding()?.actor_ids?.length;
    if (!view().isOwned(myActor())) return false;
    if (state.pending_action) return false;
    controlInitPending=false;
    const mode=preferredControl() || 'SUGGESTED';
    if (myActor().controller === mode) return true;
    const initialized=await setControl(mode);
    // Re-arm only after setControl's final read, so a failed setting waits for
    // the next poll instead of recursively retrying. Each retry checks ownership.
    controlInitPending=!initialized;
    return initialized;
  }
  async function setControl(mode) {
    if (busy || !['MANUAL','SUGGESTED'].includes(mode) || !view().isOwned(myActor())) return false;
    const id=matchId, actorId=myActor().entity_id;
    busy=true; render();
    try {
      await readDone;
      await refresh({force:true});
      if (id!==matchId || !view().isOwned(actorId) || actorId!==myActor()?.entity_id || state.pending_action)
        throw new Error('The character or decision changed. Choose your control mode again after answering any decision.');
      await request(`/api/combat/matches/${enc(id)}/controller-mode`,{body:{actor_id:actorId,controller_mode:mode}});
      controlChoices.set(controlKey(),mode);
      controlStore?.write(controlKey(),mode);
      generation++; targeting=null; fullOptions=false; listKey='';
      status(mode === 'SUGGESTED' ? 'Assisted: the app suggests each step; you confirm or change it.' : 'Manual: choose from every legal action and destination.');
      return true;
    } catch (error) { status(error.message); return false; }
    finally { busy=false; await refresh(); render(); }
  }
  async function mutate(endpoint, body) {
    const id=matchId, path=base();
    // Never resend an act after a network error. Refresh recovers a saved pending prompt.
    await request(`${path}/${endpoint}`,{body:{...body,after:sequence}});
    if (id===matchId) { targeting=null; draft=null; fullOptions=false; listKey=''; generation++; }
  }
  async function submit(candidateId, route = null) {
    if (busy || !ownedMenu(state,view()) || state.pending_action) return false;
    if (chooseSetting(candidateId)) return true;
    // Suggested-plan confirmation must aim using the draft instead of sending
    // a candidate from the unchanged menu.
    if (draft?.dirty && !targeting?.composition) {
      const group=state.menu.actions.find(g=>g.options.some(o=>o.candidate_id===candidateId));
      if (group && !group.source_definition_id?.startsWith('system:')) { await choose(group); return false; }
    }
    const key=decisionKey(state.menu), boundary=menuInspectionKey(state), id=matchId;
    const composed=targeting?.composition ? targeting : null;
    const initialMove=state.menu.moves?.find(o=>o.candidate_id===candidateId);
    const native=state.menu.actions.find(g=>g.source_definition_id?.startsWith('system:') && g.options.some(o=>o.candidate_id===candidateId));
    const nativeDraft=!composed && (native || initialMove) ? draft : null, draftRound=state.presentation?.round_number;
    let committed=false;
    busy=true; render();
    try {
      if (polling) status('Finishing the fight update, then checking your action…');
      await readDone;
      if (!composed) await refresh({force:true});
      const menu=ownedMenu(state,view());
      if (!menu || id!==matchId || decisionKey(menu)!==key || boundary!==menuInspectionKey(state) || state.pending_action) throw new Error('The fight changed. Choose your action and target again.');
      const move=menu.moves?.find(o=>o.candidate_id===candidateId
        || (initialMove && JSON.stringify(o.destination)===JSON.stringify(initialMove.destination)));
      if (composed ? !composed.options.some(o=>o.candidate_id===candidateId) :
          candidateId!==menu.end_turn && !move && !menu.actions?.some(g=>g.options.some(o=>o.candidate_id===candidateId))) throw new Error('This option is no longer available.');
      const decision=composed?.preview || menu;
      let endpoint='act',body={candidate_id:candidateId,decision_id:decision.decision_id,state_version:decision.state_version};
      if (composed) body.composition=composed.composition;
      if (move?.deferred_route) {
        if (route==='jump_down' && !move.can_jump_down) throw new Error('Choose an available Jump down route.');
        const mode = route==='jump_down' ? 'jump_down' : move.movement_mode || 'walk';
        if (!move.route_checked || move.route_mode !== mode) {
          await checkMove(menu, move, (path, options) => request(`${base()}${path}`, options),
            () => view().ready && id===matchId && boundary===menuInspectionKey(state), mode);
          if (!move.route_checked) throw new Error('The fight changed. Choose your destination again.');
          targeting = {label:'Move',move:true,options:[move],key,boundary};
          selectionUI(); $('actionSheet').hidden=false;
          status('Check the route, movement cost and any warning, then confirm your move.');
          return false;
        }
        body={decision_id:menu.decision_id,state_version:menu.state_version,actor_id:menu.actor_id,
          candidate_id:move.route_candidate_id,waypoints:move.path,movement_mode:mode};
        endpoint='movement-path/commit';
      }
      if (route==='jump_down' && !move?.deferred_route) {
        if (!move?.can_jump_down) throw new Error('Choose an available Jump down route.');
        body={decision_id:menu.decision_id,state_version:menu.state_version,actor_id:menu.actor_id,waypoints:move.path,movement_mode:'jump_down'};
        const quote=await request(`${base()}/movement-path/preview`,{body});
        if (!view().ready || id!==matchId || decisionKey(state.menu)!==key || !quote.candidate?.candidate_id) throw new Error('The fight changed. Choose where to jump again.');
        body.candidate_id=quote.candidate.candidate_id; endpoint='movement-path/commit';
      }
      await mutate(endpoint,body); status('Action sent. Reading the fight…');
      committed=true;
      return true;
    } catch (error) { status(error.message); return false; }
    finally {
      busy=false; draft=null; await refresh();
      if (committed && nativeDraft && draftRound===state.presentation?.round_number) draft=nativeDraft.rebase(state.menu,matchId);
      listKey=''; render();
    }
  }
  async function answer(value, expected) {
    if (busy || promptKey(state?.pending_action)!==expected || !ownPrompt(state.pending_action,view())) return;
    const id=matchId;
    busy=true; render();
    try {
      if (polling) status('Finishing the fight update, then checking your decision…');
      await readDone;
      await refresh({force:true});
      if (id!==matchId || promptKey(state.pending_action)!==expected || !ownPrompt(state.pending_action,view())) throw new Error('That decision has changed. Read the current card before answering.');
      const submission=pendingSubmission(state.pending_action,value,sequence);
      await mutate(submission.endpoint,submission.body);
    } catch (error) { status(error.message); }
    finally { busy=false; displayedPrompt=''; await refresh(); await defaultControl(); render(); }
  }
  async function step() {
    if (busy || $('nextStep').hidden) return;
    const id=matchId; busy=true; render();
    try {
      await readDone;
      const result=await automaticTurn({
        start:()=>request(`${base()}/automatic-run`,{body:{}}),
        observe:()=>request(`${base()}/seat-status`),
        wait:ms=>new Promise(resolve=>setTimeout(resolve,ms)),
        current:()=>id===matchId,
        status:value=>{seats=value;},
      });
      if (result?.status==='ERROR') status(result.text);
    } catch (error) { status(error.message); }
    finally { busy=false; await refresh(); render(); }
  }
  async function character() {
    if (!view().ready || !view().ownedIds.size) return;
    const actor=myActor(), epoch=generation;
    renderCharacter($('characterBody'),actor,null); modal($('characterCard'));
    const [sheet,conditions]=await Promise.all([sheetFor(actor,true),request('/api/tabletop/conditions').catch(()=>({}))]);
    if (epoch!==generation || !view().isOwned(actor)) return;
    const info=conditions.conditions || {};
    characterData=sheet;conditionData=info;
    renderCharacter($('characterBody'),myActor(),sheet,info);
  }
  $('chooseFight').addEventListener('click',lobby);
  $('fights').addEventListener('change',()=>load($('fights').value));
  $('bind').addEventListener('click',()=>bind());
  $('closeBinding').addEventListener('click',()=>$('bindingCard').close());
  $('actionsButton').addEventListener('click',()=>{ if (targeting) selectionUI(); $('actionSheet').hidden=false; });
  $('closeActions').addEventListener('click',()=>$('actionSheet').hidden=true);
  $('characterButton').addEventListener('click',character);
  $('closeCharacter').addEventListener('click',()=>$('characterCard').close());
  $('summaryButton').addEventListener('click',showSummary);
  $('closeSummary').addEventListener('click',()=>$('summaryCard').close());
  $('nextStep').addEventListener('click',step);
  const zoomChanged=()=> $('map').style.setProperty('--play-zoom',board.view.zoom);
  $('fit').addEventListener('click',()=>{fitFighters(board,state,view());zoomChanged();});
  $('zoomIn').addEventListener('click',()=>{board.zoomBy(1.3);zoomChanged();});
  $('zoomOut').addEventListener('click',()=>{board.zoomBy(1/1.3);zoomChanged();});
  $('reactionCard').addEventListener('cancel',e=>e.preventDefault());
  return {load,bind,lobby,refresh,render:()=>render({mapRefresh:true}),tap,character,submit,answer,step,choose,cancel,
    setControl,change,get state() {return state;}, get busy() {return busy;}};
}
