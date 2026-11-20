// Shared synthetic roster and storage for viewer tests.
import {readFileSync} from 'node:fs';

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
