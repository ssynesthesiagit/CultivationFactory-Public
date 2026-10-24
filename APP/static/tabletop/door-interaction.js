// The hover card's plain-words line for a door (owner 2026-10-21: "Door — closed. Within 5 ft: open it as a free
// object interaction or an Action"). The state a newcomer needs (closed/open, locked, stuck), what it costs to change,
// and the door's AC/HP all read in one sentence; no internal ids or code names.
export function doorDetail(object) {
  const locked = Boolean(object?.door_locked), jammed = Boolean(object?.door_jammed);
  const state = locked ? "closed and locked" : jammed ? "closed and stuck" : object?.open ? "open" : "closed";
  const action = locked || jammed
    ? "This door cannot be opened or closed by hand."
    : `Within 5 ft: ${object?.open ? "close" : "open"} it as a free object interaction or an Action.`;
  const facts = [];
  if (object?.ac != null) facts.push(`AC ${object.ac}`);
  if (object?.hp != null) facts.push(`${object.hp} HP`);
  return `Door — ${state}. ${action}${facts.length ? ` (${facts.join(", ")}).` : ""}`;
}

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
