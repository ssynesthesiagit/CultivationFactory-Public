// The server's legal menu owns reach, sight, turn budget and occupancy checks.
export function doorMenu(object, menu) {
  if (object?.interaction !== 'simple_door') return null;
  const operation = object.open ? 'Close' : 'Open';
  let message = `${object.name}: ${object.open ? 'Open' : 'Closed'}.`;
  if (object.door_locked) return {message: `${message} Locked: this door cannot be opened or closed this way.`, options: []};
  if (object.door_jammed) return {message: `${message} Stuck: this door cannot be opened or closed this way.`, options: []};
  const options = menu?.manual ? (menu.actions || []).flatMap(group =>
    String(group.source_definition_id || '').startsWith('system:door.')
      ? group.options.filter(option => option.target_ids.includes(object.id)).map(option => ({
          candidate_id: option.candidate_id,
          label: `${operation} ${object.name} (${group.economy === 'NONE' ? 'free interaction' : 'Utilize action'})`,
        })) : []) : [];
  if (!options.length) message += ' You must be within 5 feet, on your turn, with an interaction available and space to close it.';
  return {message, options};
}
