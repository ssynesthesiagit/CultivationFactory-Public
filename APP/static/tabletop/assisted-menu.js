// Shared desktop/phone Assisted discovery contract. These handles are never
// submitted: selected sources expand natively and routes are quoted first.
export const sourceRankId = group => `source:${group.source_definition_id}`;

// Both clients keep read-only inspections only within this exact authority
// boundary. Pending questions, terminal fights and automatic turns invalidate it.
export function menuInspectionKey(state) {
  const menu = state?.menu;
  if (!menu?.manual || state.pending_action || state.presentation?.terminal) return null;
  return JSON.stringify([state.presentation?.match_id, menu.decision_id, menu.state_version,
    menu.actor_id, menu.control_mode, menu.turn_mode]);
}

export const moveKey = move => JSON.stringify([move.destination?.x, move.destination?.y,
  move.destination?.z || 0, move.movement_mode || 'walk']);

// An inspection reply can race an unchanged poll. Keep the current row's
// local handle while transferring only the route presentation/native quote.
export function copyMoveInspection(row, checked) {
  Object.assign(row, {route_checked: true, path: checked.path.map(p => ({...p})),
    hazard_exposure: checked.hazard_exposure, route_candidate_id: checked.route_candidate_id,
    route_mode: checked.route_mode});
}

// Fresh compact rows have local, order-dependent IDs. Match by destination and
// mode, and copy only disclosed route fields, never arbitrary server metadata.
export function retainMenuInspection(previous, next) {
  const key = menuInspectionKey(next);
  if (!key || key !== menuInspectionKey(previous)) return;
  for (const row of next.menu.actions || []) {
    const expanded = previous.menu.actions?.find(old => old.source_definition_id === row.source_definition_id && old.expanded_from_lazy);
    if (row.lazy && expanded) Object.assign(row, expanded);
  }
  const checked = new Map((previous.menu.moves || []).filter(m => m.deferred_route && m.route_checked)
    .map(m => [moveKey(m), m]));
  for (const row of next.menu.moves || []) {
    const old = checked.get(moveKey(row));
    if (row.deferred_route && old) copyMoveInspection(row, old);
  }
}

export function rankedIds(menu, slot) {
  return (menu.ranked_slots?.[slot] || []).flatMap(id => {
    if (id === 'movement:compact') return (menu.moves || []).map(m => m.candidate_id);
    const group = (menu.actions || []).find(g => sourceRankId(g) === id);
    return group && !group.lazy ? group.options.map(o => o.candidate_id) : [id];
  });
}

export async function expandSource(menu, group, load, current) {
  const query = new URLSearchParams({source: group.source_definition_id,
    decision_id: menu.decision_id, state_version: menu.state_version});
  const result = await load(`/action-options?${query}`);
  if (!current()) return null;
  const expanded = result.actions.find(g => g.source_definition_id === group.source_definition_id);
  Object.assign(group, expanded || {options: []}, {lazy: false, expanded_from_lazy: true});
  return group;
}

export function confirmRouteQuote(move, quote, confirm = message => window.confirm(message)) {
  const candidate = quote?.candidate;
  if (!candidate?.candidate_id) return false;
  const destination = move.destination;
  const path = (candidate.canonical_path || []).map(p => `(${p.x}, ${p.y}, height ${(p.z || 0) * 5} ft)`).join(' → ');
  const warning = candidate.metadata?.hazard_exposure
    ? '\nWarning: this route crosses a known hazard.' : '';
  const cost = move.cost_ft ?? candidate.movement_cost_ft;
  return confirm(`Move to (${destination.x}, ${destination.y}), height ${(destination.z || 0) * 5} ft?\nRoute: ${path}\nMovement cost: ${cost} ft.${warning}`);
}

export async function checkMove(menu, move, load, current, mode = move.movement_mode || 'walk') {
  const result = await load('/movement-destination/preview', {body: {
    decision_id: menu.decision_id, state_version: menu.state_version, actor_id: menu.actor_id,
    destination: move.destination, movement_mode: mode}});
  if (!current()) return null;
  if (!result.candidate?.candidate_id) throw new Error('This route is no longer available. Choose another destination.');
  move.path = result.candidate.canonical_path;
  move.route_candidate_id = result.candidate.candidate_id;
  move.route_mode = mode;
  // Keep the menu's effective price, which already includes drag multipliers.
  // Native candidate movement_cost_ft is the unmultiplied engine route cost.
  // Match the concrete menu's player-facing projection. Do not copy arbitrary
  // metadata (reactor identities or private plug-in state) into the client row.
  move.hazard_exposure = !!result.candidate.metadata?.hazard_exposure;
  move.route_checked = true;
  return move;
}
