// Phone Factory setup. Reuses the desktop's installed-character creation path;
// no combat rules, controller patches, model calls or automatic combat steps.
import {node} from './play-ui.js';

export function installNewFight({doc, request, open, back}) {
  const $=id=>doc.getElementById(id);
  let epoch=0, creating=false, picks=[], maps=[];
  const say=text=>{ $('newFightStatus').textContent=text; };
  const describe=()=>{ $('newFightMapDescription').textContent=maps.find(m=>m.arena_id===$('newFightMap').value)?.description || ''; };
  function select(labelText, choices) {
    const label=node(doc,'label',labelText), input=node(doc,'select');
    input.setAttribute('aria-label',labelText);
    for (const [value,text] of choices) {
      const option=node(doc,'option',text); option.value=value; input.append(option);
    }
    label.append(input); return {label,input};
  }
  async function choices() {
    const ticket=++epoch;
    $('createFight').disabled=true; $('retryNewFight').hidden=true;
    $('newFightRoster').replaceChildren(); $('newFightMap').replaceChildren(); picks=[];
    say('Loading maps and your finished characters…');
    try {
      const [characters,arenas]=await Promise.all([
        request('/api/combat/factory-characters'),request('/api/combat/factory-arenas')]);
      if (ticket!==epoch) return;
      maps=arenas;
      for (const map of maps) {
        const option=node(doc,'option',map.display_name); option.value=map.arena_id; $('newFightMap').append(option);
      }
      describe();
      for (const [index,character] of characters.entries()) {
        const card=node(doc,'div',null,'play-fighter');
        const label=node(doc,'label'), chosen=node(doc,'input'); chosen.type='checkbox';
        label.append(chosen,node(doc,'span',character.display_name)); card.append(label);
        const side=select(`Side for ${character.display_name}`,[['1','Side 1'],['2','Side 2']]);
        const control=select(`Who controls ${character.display_name}?`,[['MANUAL','You — choose actions'],['LOCAL_AUTO','AI — automatic actions']]);
        side.input.value=index===0 ? '1' : '2'; control.input.value=index===0 ? 'MANUAL' : 'LOCAL_AUTO';
        card.append(side.label,control.label); $('newFightRoster').append(card);
        picks.push({character,chosen,side:side.input,control:control.input});
      }
      $('createFight').disabled=characters.length<2 || !maps.length;
      say(!maps.length ? 'No maps are available. Add a map on the desktop, then retry.' : characters.length<2
        ? 'You need at least two finished characters. Finish characters on the desktop, then retry.'
        : 'Select fighters for both sides (up to 10 per side). The fight is saved when you tap Create and open fight.');
      $('retryNewFight').hidden=!$('createFight').disabled;
    } catch (error) {
      if (ticket!==epoch) return;
      say(`Could not load the choices. ${error.message}`); $('retryNewFight').hidden=false;
    }
  }
  function close() {
    if (creating) return;
    epoch++; $('newFightCard').close(); return back();
  }
  async function create() {
    if (creating || $('createFight').disabled) return;
    const chosen=picks.filter(p=>p.chosen.checked), sides=['1','2'].map(side=>chosen.filter(p=>p.side.value===side));
    if (sides.some(side=>!side.length)) { say('Choose at least one fighter for each side.'); return; }
    if (sides.some(side=>side.length>10)) { say('Choose up to 10 fighters per side.'); return; }
    const actorId=p=>p.character.actor_id || `actor:factory.${p.character.project_id}`;
    const payload={project_ids:sides[0].map(p=>p.character.project_id),opponent_actor_ids:sides[1].map(actorId),
      arena_id:$('newFightMap').value,control_modes:Object.fromEntries(chosen.map(p=>[actorId(p),p.control.value]))};
    creating=true;
    const inputs=[$('createFight'),$('closeNewFight'),$('newFightMap'),...$('newFightRoster').querySelectorAll('input,select')];
    for (const input of inputs) input.disabled=true;
    say('Creating fight… this can take up to a minute. Please keep this screen open.');
    $('newFightCard').setAttribute('aria-busy','true');
    let result;
    try { result=await request('/api/combat/factory-matches',{body:payload}); }
    catch (error) {
      say(`Could not confirm fight creation. ${error.message} Check the saved fights before trying again: the fight may already have been saved.`);
    } finally {
      creating=false; for (const input of inputs) input.disabled=false;
      $('newFightCard').setAttribute('aria-busy','false');
    }
    if (!result) return;
    $('newFightCard').close();
    const player=chosen.find(p=>p.control.value==='MANUAL');
    await open(result.match_id,player ? actorId(player) : null);
  }
  $('newFight').addEventListener('click',()=>{
    if (!$('newFightCard').open) $('newFightCard').showModal();
    return choices();
  });
  $('newFightMap').addEventListener('change',describe);
  $('retryNewFight').addEventListener('click',choices);
  $('closeNewFight').addEventListener('click',close);
  $('newFightCard').addEventListener('cancel',event=>{event.preventDefault();return close();});
  $('createFight').addEventListener('click',create);
}
