// Independent HTTP client/controller for /play. No imports from the desktop entry point.
import {enc} from '../tabletop/api.js';
import {serverDriving, modelOwner} from '../tabletop/seats.js';
import {playerView, eligibleFighters, ownedMenu, ownPrompt, decisionKey, promptKey, optionsAt, pendingSubmission} from './play-model.js';
import {node, button, renderActions, renderGuidedActions, renderOptions, renderReaction, renderCharacter} from './play-ui.js';
import {renderMap, fitFighters} from './play-board.js';
import {CELL} from '../tabletop/board.js';

export function createPlay({doc, request, board, viewerStore, memoryStore, controlStore, frame = callback => requestAnimationFrame(callback), onMatchChange = () => {}}) {
  const $ = id => doc.getElementById(id);
  let matchId = '', state = null, seats = null, sequence = 0, targeting = null, busy = false;
  let generation = 0, polling = false, displayedPrompt = '', lastTurn = '', listKey = '', mapKey = '';
  let readDone=Promise.resolve(), finishRead, characterData=null, conditionData={};
  let fullOptions=false, controlInitPending=false;
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
    targeting = null; listKey = ''; status('Choose an action. Pinch to zoom; drag to pan.'); render(); $('actionSheet').hidden = false;
  }
  function change() { fullOptions=true; targeting=null; listKey=''; render(); }
  function actionList(menu, sheet) {
    const host=$('actionList');
    const handlers={choose,move:()=>choose({label:'Move',options:menu.moves},true),end:()=>submit(menu.end_turn),
      confirm:submit,change};
    if (menu?.control_mode === 'SUGGESTED' || menu?.turn_mode === 'Assisted')
      renderGuidedActions(host,menu,sheet,state,view(),handlers,fullOptions);
    else renderActions(host,menu,sheet,handlers);
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
  function choose(group, move = false) {
    if (busy || !ownedMenu(state,view()) || state.pending_action) return;
    // Destination-choice abilities ask for the destination during resolution, as on desktop.
    if (group.destination_choice && !group.placement_picker && group.options?.length) return submit(group.options[0].candidate_id);
    targeting = {...group,move,key:decisionKey(state.menu)};
    selectionUI(); $('actionSheet').hidden = false;
    status(`${group.label}: tap a token or square on the map. All options are also listed in Actions. Cancel returns to your actions.`);
    render();
  }
  function tap(cell, tokenId = null, screen = null) {
    if (!cell || !view().ready || busy) return;
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
  function render({mapRefresh = false} = {}) {
    if (!state) return;
    const v = view(), p = state.presentation, menu = ownedMenu(state,v), actor = myActor();
    const effective = v.ready && v.ownedIds.size > 0;
    $('map').hidden = !effective;
    if (!effective) $('characterCard').close();
    if (!effective) cover(v.reason === 'seats-unavailable' ? 'Character controls could not be checked. Reconnecting…' : 'Choose a manually controlled character to open your view.');
    if (targeting && targeting.key !== decisionKey(state.menu)) { targeting=null; listKey=''; status('The turn changed. Choose your action again.'); }
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
        renderReaction($('reactionBody'),prompt.reaction,{answer:a=>answer(a,key),error:status}); modal($('reactionCard'));
      } else $('reactionCard').close();
    }
    if (pending && !prompt) status('Waiting for another player’s decision. Your view remains open.');
    for (const host of [$('actionList'),$('reactionBody')]) for (const b of host.querySelectorAll('button')) b.disabled=busy;
  }
  async function refresh({force = false} = {}) {
    if (!matchId || (busy && !force) || polling) return;
    polling = true;
    readDone=new Promise(resolve=>{finishRead=resolve;});
    const id = matchId, epoch = generation, path = base();
    const query = new URLSearchParams({fog:'true',fog_view:'own'});
    for (const actor of binding()?.actor_ids || []) query.append('fog_actor_ids',actor);
    try {
      const [snapshot,control] = await Promise.all([request(`${path}/state?${query}`),request(`${path}/seat-status`).catch(()=>null)]);
      if (id!==matchId || epoch!==generation) return;
      const feed = await request(`${path}/events?after=${sequence}`);
      if (id!==matchId || epoch!==generation) return;
      seats = control; state = snapshot;
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
    generation++; matchId=id; state=null; seats=null; sequence=0; targeting=null; displayedPrompt=''; lastTurn=''; listKey=''; mapKey=''; fullOptions=false; controlInitPending=false;
    characterData=null;conditionData={};
    const epoch=generation;
    onMatchChange(id);
    $('reactionCard').close(); $('characterCard').close(); $('actionSheet').hidden=true;
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
    if (id===matchId) { targeting=null; fullOptions=false; listKey=''; generation++; }
  }
  async function submit(candidateId, route = null) {
    if (busy || !ownedMenu(state,view()) || state.pending_action) return false;
    const key=decisionKey(state.menu), id=matchId;
    busy=true; render();
    try {
      if (polling) status('Finishing the fight update, then checking your action…');
      await readDone;
      await refresh({force:true});
      const menu=ownedMenu(state,view());
      if (!menu || id!==matchId || decisionKey(menu)!==key || state.pending_action) throw new Error('The fight changed. Choose your action and target again.');
      const move=menu.moves?.find(o=>o.candidate_id===candidateId);
      if (candidateId!==menu.end_turn && !move && !menu.actions?.some(g=>g.options.some(o=>o.candidate_id===candidateId))) throw new Error('This option is no longer available.');
      let endpoint='act',body={candidate_id:candidateId,decision_id:menu.decision_id,state_version:menu.state_version};
      if (route==='jump_down') {
        if (!move?.can_jump_down) throw new Error('Choose an available Jump down route.');
        body={decision_id:menu.decision_id,state_version:menu.state_version,actor_id:menu.actor_id,waypoints:move.path,movement_mode:'jump_down'};
        const quote=await request(`${base()}/movement-path/preview`,{body});
        if (!view().ready || id!==matchId || decisionKey(state.menu)!==key || !quote.candidate?.candidate_id) throw new Error('The fight changed. Choose where to jump again.');
        body.candidate_id=quote.candidate.candidate_id; endpoint='movement-path/commit';
      }
      await mutate(endpoint,body); status('Action sent. Reading the fight…');
      return true;
    } catch (error) { status(error.message); return false; }
    finally { busy=false; await refresh(); listKey=''; render(); }
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
    const key=decisionKey(state.menu), id=matchId; busy=true; render();
    try {
      if (polling) status('Finishing the fight update, then checking the next step…');
      await readDone;
      await refresh({force:true});
      if (id!==matchId || $('nextStep').hidden || key!==decisionKey(state.menu)) throw new Error('The turn changed. Check the current turn before advancing.');
      await mutate('auto-step',{decision_id:state.menu.decision_id,state_version:state.menu.state_version,reactions:[]});
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
  $('nextStep').addEventListener('click',step);
  const zoomChanged=()=> $('map').style.setProperty('--play-zoom',board.view.zoom);
  $('fit').addEventListener('click',()=>{fitFighters(board,state,view());zoomChanged();});
  $('zoomIn').addEventListener('click',()=>{board.zoomBy(1.3);zoomChanged();});
  $('zoomOut').addEventListener('click',()=>{board.zoomBy(1/1.3);zoomChanged();});
  $('reactionCard').addEventListener('cancel',e=>e.preventDefault());
  return {load,bind,lobby,refresh,render:()=>render({mapRefresh:true}),tap,character,submit,answer,step,choose,cancel,
    setControl,change,get state() {return state;}, get busy() {return busy;}};
}
