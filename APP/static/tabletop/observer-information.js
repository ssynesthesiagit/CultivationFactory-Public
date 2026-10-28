// Limited supernatural information belongs to its observer, never to a side.
// This renderer cannot turn a direction into a token position or target.
export function observerInformationLines(viewer, perception) {
  if (!viewer?.entity_id) return [];
  const result = [];
  for (const row of perception?.[viewer.entity_id]?.information || []) {
    if (row.viewer_id !== viewer.entity_id) continue;
    const details = row.details || {};
    if (row.kind === 'direction' && typeof details.direction === 'string') {
      // The provider that sensed it names what it sensed (a broken-blood creature, a
      // Bell-Marked one); the shared kind only says that it is a direction. A reading
      // without a subject stays the neutral, non-claiming line.
      const subject = typeof row.subject === 'string' && row.subject.trim() ? row.subject.trim() : 'A supernatural presence';
      result.push(`${subject} is ${details.direction}. This gives a direction, not a precise location.`);
    }
    else if (row.kind === 'concealment_exists')
      result.push('Concealment exists; its location and nature remain unknown.');
    else if (row.kind === 'resonance') {
      // Source-owned visible traces may name their precise revealed location.
      // Direction-only and failed-concealment rows never enter this branch.
      const cell = p => p && ['x', 'y'].every(k => Number.isInteger(p[k])) && Number.isInteger(p.z ?? 0)
        ? `square (${p.x}, ${p.y}), ${(p.z ?? 0) * 5} feet high` : '';
      if (typeof details.text === 'string' && details.text.trim()) {
        let line = details.text;
        if (cell(details.position)) line += ` Location: ${cell(details.position)}.`;
        else if (cell(details.from) && cell(details.to))
          line += ` From ${cell(details.from)} to ${cell(details.to)}.`;
        result.push(line);
      } else result.push('You detect visible or audible supernatural resonance.');
    }
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
