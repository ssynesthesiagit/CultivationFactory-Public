// Synthetic shared-renderer scene. No saved fights or owner artwork.
export const map = {width: 10, height: 10, background: {style: 'grass'},
  walls: [{shape: 'rect', points: [[2, 2], [7, 7]], filled: false, height_ft: 10}],
  roofs: {height_ft: 15},
  floors: [{style: 'wood', cells: Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)])}]};
export const actor = (z = 8) => ({id: 'caster', name: 'Flying gardener', x: 4, y: 4, z,
  position: {x: 4, y: 4, z}, hp: 10, maxHp: 10, conditions: []});
export const area = (extra = {}) => ({zone_id: 'garden', owner_id: 'caster', active: true,
  center: {x: 4, y: 4, z: 8}, radius_cells: 4,
  affected_cells: Array.from({length: 64}, (_, i) => [1 + i % 8, 1 + Math.floor(i / 8)]),
  trigger_profile: {name: 'Garden aura', aura: true, follows_owner: true, shape: 'emanation',
    visual: {material: 'vines', color: '#65bd49', obscured: 'light'}}, ...extra});
