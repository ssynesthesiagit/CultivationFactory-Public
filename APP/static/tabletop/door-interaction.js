// The server's legal menu owns reach, sight, turn budget and occupancy checks.
export function doorMenu(object, menu, state = {}) {
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
  if (!options.length) {
    const source = `act:system:door.${operation.toLowerCase()}`;
    const informative = value => typeof value === 'string' && value.trim()
      && !/^No eligible target or position is currently available for this action\.?$/i.test(value.trim());
    const utilizeReason = state.unavailable_reasons?.[`${source}.utilize:${object.id}`];
    const freeReason = state.unavailable_reasons?.[`${source}.free:${object.id}`];
    // A generic target refusal says nothing the player can act on. Prefer a
    // specific refusal for an applicable payment, otherwise explain the reach
    // and turn-budget requirements below.
    const reason = informative(freeReason) ? freeReason
      : informative(utilizeReason) ? utilizeReason : null;
    if (reason) message += ` ${reason}`;
    const current = state.presentation?.actors?.find(actor =>
      actor.entity_id === state.presentation.current_actor_id);
    if (current?.display_name) message += ` It is ${current.display_name}'s turn.`;
    message += ` To ${operation.toLowerCase()} this door, the current fighter must be within 5 feet and have a free object interaction or an Action available.`;
    if (object.open) message += ' The opening must be clear of creatures and objects.';
  }
  return {message, options};
}
