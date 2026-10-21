// Limited supernatural information belongs to its observer, never to a side.
// This renderer cannot turn a direction into a token position or target.
const signNames = {wind: 'Wind Sign', rain: 'Rain Sign', cold: 'Cold Sign',
  heat: 'Heat Sign', dry: 'Dry Sign (aridity)', thunder: 'Thunder Sign'};
const categoryNames = {wind: 'Wind', precipitation: 'Rain or snow', cold: 'Cold',
  heat: 'Heat', aridity: 'Dryness', storm: 'Storm'};

function weatherText(value) {
  if (Array.isArray(value)) return value.map(weatherText).join('; ');
  if (value && typeof value === 'object') {
    if ('hour' in value && 'categories' in value)
      return `${value.hour === 0 ? 'Now' : `In ${value.hour} hours`}: ${weatherText(value.categories)}`;
    return Object.entries(value).map(([key, item]) => {
      if (key in categoryNames && Number.isInteger(item))
        return `${categoryNames[key]}: ${item === 0 ? 'not active' : `active, strength ${item} of 4 (higher means stronger)`}`;
      if (key === 'categories') return weatherText(item);
      if (key === 'origin') return `Origin: ${weatherText(item)}`;
      if (key === 'concentration') return `Sustained by Concentration: ${item === 1 ? 'yes' : item === 0 ? 'no' : weatherText(item)}`;
      return `${key}: ${weatherText(item)}`;
    }).join('; ');
  }
  const origins = {natural: 'natural weather', supernatural: 'supernatural weather',
    'cultivation-made': 'weather created by a cultivation technique',
    concentration: 'sustained by Concentration (the caster must keep focusing)'};
  return origins[value] || String(value ?? 'Unknown');
}

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
    else if (row.kind === 'resonance') result.push('You detect visible or audible supernatural resonance.');
    else if (row.kind === 'declaration' && details.ability === 'Antidote Profile')
      result.push(`Antidote Profile saved for ${details.subject_name || 'the examined source'}.`);
    else if (row.kind === 'answer') {
      if (details.check_failed && !Object.keys(details.answers || {}).length)
        result.push(`${details.ability || 'Reading'} on ${details.subject_name || 'the examined target'}: the check failed. You learn no information.`);
      const weather = String(details.ability || '').startsWith('Read the Sky') || details.subject_id === 'scene';
      const text = value => weather ? weatherText(value) : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : typeof value === 'string' ? value : JSON.stringify(value);
      for (const [question, answer] of Object.entries(details.answers || {}))
        result.push(`${details.ability || 'Reading'}${details.subject_name ? ` on ${details.subject_name}` : ''}: ${question}: ${text(answer)}`);
      if (details.sign) result.push(`${details.ability || 'Battle Reading'}: ${signNames[details.sign] || 'an unfamiliar Weather Sign'} is active in this scene.`);
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
