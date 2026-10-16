// Shared desktop/phone Assisted discovery contract. These handles are never
// submitted: selected sources expand natively and routes are quoted first.
export const sourceRankId = group => `source:${group.source_definition_id}`;

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

export async function checkMove(menu, move, load, current) {
  const result = await load('/movement-destination/preview', {body: {
    decision_id: menu.decision_id, state_version: menu.state_version, actor_id: menu.actor_id,
    destination: move.destination, movement_mode: move.movement_mode || 'walk'}});
  if (!current()) return null;
  if (!result.candidate?.candidate_id) throw new Error('This route is no longer available. Choose another destination.');
  move.path = result.candidate.canonical_path;
  // Match the concrete menu's player-facing projection. Do not copy arbitrary
  // metadata (reactor identities or private plug-in state) into the client row.
  move.hazard_exposure = !!result.candidate.metadata?.hazard_exposure;
  move.route_checked = true;
  return move;
}
