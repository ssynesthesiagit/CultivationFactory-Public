// Preview zones from map materials using the same map-scenery metadata as fights.
import {MAP_TERRAIN_SOURCE} from "./zones.js?v=r25x2";

export function previewTerrainZones(materials, terrains, naturalHaze = false) {
  return (materials || []).filter(row => row.material.startsWith("terrain:") && row.cells.length).map(row => {
    const name = row.material.slice(8);
    const rule = terrains.find(entry => entry.name === name) || {};
    return {zone_id: `preview:${name}:${row.occluder || "cell"}`, source_definition_id: MAP_TERRAIN_SOURCE,
      owner_id: null, active: true, radius_cells: 0, center: {x: row.cells[0][0], y: row.cells[0][1]},
      affected_cells: row.cells.map(([x, y]) => ({x, y})),
      trigger_profile: {kind: "TYPED", name: rule.label || name, terrain: [name], map: true, natural_haze: naturalHaze === true,
        difficult: rule.difficult ? "all" : null, obscured: rule.obscured || null, color: rule.color || null, shape: "painted",
        move_through: rule.move_through || null, visual: {material: rule.material || "generic"}}};
  });
}
