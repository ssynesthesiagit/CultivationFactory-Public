// Synthetic public presentation rows; no owner fight data is retained here.
export const map = {width: 8, height: 8, background: {style: 'flagstone', seed: 7}, walls: [], trees: [], floors: [], cells: {}};
const area = (id, name, visual, extra = {}) => ({
  zone_id: id, active: true, owner_id: 'caster', applied_by: 'Cloud caster',
  affected_cells: [{x: 3, y: 3}, {x: 4, y: 3}, {x: 3, y: 4}],
  duration_rounds: 10, created_round: 1, concentration_link: true,
  sight_rules: {concealment_miss_percent: 17, total_concealment_miss_percent: 43},
  trigger_profile: {kind: 'TYPED', name, visual, ...extra},
});
export const zones = [
  area('fog', 'Dust Cloud', {material: 'fog', obscured: 'light'}, {obscured: 'light'}),
  area('dust', 'Airborne dust', {material: 'dust', obscured: 'light'}, {obscured: 'light'}),
  area('smoke', 'Smoke Veil', {material: 'smoke', obscured: 'heavy', wall: true}, {wall: {obscures: 'all'}}),
  area('dark', 'Darkness', {material: 'darkness', darkness: true, darkness_look: 'pitch'}),
  {...area('ended', 'Ended cloud', {material: 'fog', obscured: 'light'}), active: false},
];
