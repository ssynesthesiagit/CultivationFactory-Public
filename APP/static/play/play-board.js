// Reuses the table renderer and server perception. Square fog is the board's
// supported exact-cell presentation; this page implements no LOS/fog algorithm.
import {initials, CELL} from '../tabletop/board.js';
import {perceivedObjects, tokenSensePresentation} from '../tabletop/vision.js';
import {tableObjectTokens} from '../tabletop/object-presentation.js';
import {recordSeen, ghostCells, memoryKey} from '../tabletop/fog_memory.js';
import {mapFromState} from './play-model.js';

const colors = ['#5fb8e8','#e8795f','#c9a2ff','#e8d25f'];
// Phone-only framing through the shared board's public camera API. Hidden
// actors and unseen map extent must never move the camera or shrink tokens.
export function fitFighters(board, state, view) {
  const actors=(state?.presentation?.actors || []).filter(a => a.position && view.visible(a));
  if (!actors.length) return;
  const bounds = rows => ({left:Math.min(...rows.map(a=>a.position.x)), top:Math.min(...rows.map(a=>a.position.y)),
    right:Math.max(...rows.map(a=>a.position.x+(a.footprint?.width_cells || 1))),
    bottom:Math.max(...rows.map(a=>a.position.y+(a.footprint?.height_cells || 1)))});
  const rect=board.element.getBoundingClientRect(), box=bounds(actors);
  const zoom=Math.max(28/CELL, Math.min(1, rect.width/((box.right-box.left+4)*CELL), rect.height/((box.bottom-box.top+4)*CELL)));
  const owned=actors.filter(a=>view.isOwned(a));
  const center=(box.right-box.left+4)*CELL*zoom>rect.width || (box.bottom-box.top+4)*CELL*zoom>rect.height
    ? bounds(owned.length ? owned : actors.slice(0,1)) : box;
  board.zoomBy(zoom/board.view.zoom);
  board.centerOn((center.left+center.right)/2-.5,(center.top+center.bottom)/2-.5);
}
export function renderMap(board, state, view, {matchId, actorId, memoryStore, targeting = null}) {
  const map = mapFromState(state), actors = state.presentation.actors || [];
  const key = JSON.stringify(map);
  const changed = key !== board.element.dataset.playMap;
  // A new board is GM by default (for editors). Install player roof/fog role first.
  board.setRoofView({gm:false, viewers:[], enabled:true, seen:new Uint8Array(map.width*map.height)});
  if (changed) { board.setMap(map); board.element.dataset.playMap = key; }
  const visibleActors = actors.filter(a => a.position && view.visible(a));
  const targetable = new Set((targeting?.options || []).flatMap(o => o.target_ids || []));
  const objects = perceivedObjects(view.viewers, state.fog_perception, state.objects);
  board.setZones(state.presentation.zones || [], {round:state.presentation.round_number,
    teamOf: id => { const owner = actors.find(a => a.entity_id === id); return owner ? {color:colors[owner.team_index || 0], owner:owner.display_name, foe:!view.teams.has(owner.team_index || 0)} : null; }});
  board.setTokens(visibleActors.map(a => ({id:a.entity_id,x:a.position.x,y:a.position.y,z:a.position.z ?? (a.altitude_ft || 0)/5,
    name:a.display_name,label:initials(a.display_name),color:colors[a.team_index || 0],hp:a.hit_points?.current,maxHp:a.hit_points?.maximum,
    current:a.entity_id === state.presentation.current_actor_id, yours:view.isOwned(a), selected:a.entity_id === actorId,
    down:a.active === false, size:a.footprint?.width_cells || 1,height:a.footprint?.height_cells || 1,
    targetable:targetable.has(a.entity_id), image:a.token_image || (a.entity_id.startsWith('actor:factory.') ? `/api/tabletop/characters/${encodeURIComponent(a.entity_id.slice('actor:factory.'.length))}/token.png` : null),
    conditions:[], ...tokenSensePresentation(a,view.viewers,state.fog_perception,true)}))
    .concat((state.items || []).filter(i => view.seen[i.y*map.width+i.x]).map(i => ({...i,id:i.id,name:i.name,label:i.label || '⚔',item:true,hp:1,maxHp:1,color:'#9aa3ad'})))
    .concat(tableObjectTokens(state.objects,targetable,state.presentation.battlefield.blocked_cells || [],view.seen,map.width,String(state.map?.background?.seed || ''),objects)));
  board.setRoofView({gm:false,viewers:actors.filter(a=>view.isOwned(a) && a.active !== false && a.position), enabled:true,seen:view.seen});
  const memoryId = memoryKey(matchId, `play:${actorId}:own`,map.width,map.height);
  let memory = memoryStore.read(memoryId);
  if (memoryStore.ready(memoryId) && view.ready) {
    memory = recordSeen(memory,view.seen,index => {
      const x=index%map.width,y=Math.floor(index/map.width);
      // Preserve explicit null for empty scenery: omitting it lets the shared
      // renderer's legacy fallback reveal later, unseen map edits.
      return {terrain:board.terrainAt(x,y),zones:board.zonesAt(x,y),floor:board.floorRecordAt(x,y),
        scenery:board.sceneryRecordAt(x,y),
        tokens:visibleActors.filter(a=>!view.isOwned(a) && a.position.x===x && a.position.y===y).map(a=>({id:a.entity_id,name:a.display_name,label:initials(a.display_name),color:colors[a.team_index || 0],x,y})),
        objects:(state.objects || []).filter(o=>o.hp>0 && objects.has(o.id) && o.x===x && o.y===y).map(o=>{
          const art=board.objectArtRecordAt(o.id);
          return {id:o.id,name:o.name,kind:o.kind,x,y,...(art ? {art} : {})};
        })};
    });
    memoryStore.save(memoryId,memory);
  }
  const explored = new Uint8Array(view.seen.length);
  for (const index of Object.keys(memory.cells)) explored[Number(index)] = 1;
  const ghosts = ghostCells(memory,view.seen);
  // Always use last-seen artwork on remembered squares, including changed floors.
  board.setFog(view.seen,explored,{squareFog:true},new Uint8Array(explored));
  board.setRemembered({cells:memory.cells,ghosts,changed:ghosts,width:map.width});
  board.setHighlights({moves: targeting?.move ? targeting.options.map(o=>o.destination) : [],
    targets:visibleActors.filter(a=>targetable.has(a.entity_id)).map(a=>({...a.position,width:a.footprint?.width_cells || 1,height:a.footprint?.height_cells || 1})),
    areas:(targeting?.options || []).map(o=>o.area?.center).filter(Boolean),
    areaCells:(targeting?.options || []).map(o=>o.destination || o.area?.center).filter(Boolean)});
  return changed;
}
