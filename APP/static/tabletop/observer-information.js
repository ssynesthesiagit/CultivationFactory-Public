// Limited supernatural information belongs to its observer, never to a side.
// This renderer cannot turn a direction into a token position or target.
export function observerInformationLines(viewer, perception) {
  if (!viewer?.entity_id) return [];
  const result = [];
  for (const row of perception?.[viewer.entity_id]?.information || []) {
    if (row.viewer_id !== viewer.entity_id) continue;
    const details = row.details || {};
    if (row.kind === 'direction' && typeof details.direction === 'string')
      result.push(`A supernatural presence is ${details.direction}. This gives a direction, not a precise location.`);
    else if (row.kind === 'concealment_exists')
      result.push('Concealment exists; its location and nature remain unknown.');
    else if (row.kind === 'declaration' && typeof details.text === 'string') result.push(details.text);
    else if (row.kind === 'resonance') result.push('You detect visible or audible supernatural resonance.');
    else if (row.kind === 'field_event') {
      const events = {enters: 'entry', teleports_in: 'teleportation into the field',
        becomes_invisible: 'a creature becoming Invisible', begins_possession: 'a possession beginning',
        audible_technique: 'an audible technique being activated'};
      if (!events[details.event_type] || typeof details.direction !== 'string') continue;
      const relation = ['friendly', 'hostile'].includes(details.allegiance) ? details.allegiance : 'unidentified';
      result.push(`Field watch: ${events[details.event_type]}, ${details.direction} of the Anchor; ${relation} source.`);
    }
  }
  return [...new Set(result)];
}
