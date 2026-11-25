// Optimism changes selection markers only. Combat effects remain server-owned.
// Instant only on the server's positive fact that the press stores a setting
// (setting_only, SELF, no cost). Anything else waits for the confirmed commit.
export function isInstantToggle(menu, candidateId, route) {
  return !route && !menu?.composition?.[candidateId] && menu?.actions?.some(group =>
    group.stores_setting === true && group.options.some(option => option.candidate_id === candidateId));
}

export class InstantToggles {
  tail = Promise.resolve();
  pending = 0;

  shouldQueue(menu, candidateId, route) {
    return this.pending > 0 || isInstantToggle(menu, candidateId, route);
  }

  run({app, candidateId, route, execute, render, toast}) {
    const match = app.matchId, menu = app.state?.menu;
    const group = menu?.actions?.find(g => g.options.some(o => o.candidate_id === candidateId));
    const option = group?.options.find(o => o.candidate_id === candidateId);
    const queued = this.pending++ > 0;
    const run = async () => {
      if (app.matchId !== match || app.state?.menu?.actor_id !== menu?.actor_id) return false;
      if (queued && group) {
        const options = app.state?.menu?.actions?.find(g => g.source_definition_id === group.source_definition_id)?.options || [];
        const matches = options.filter(o => ['target_ids', 'option_ids', 'destination', 'label'].every(k =>
          JSON.stringify(o[k]) === JSON.stringify(option[k])));
        if (matches.length !== 1) { toast('The fight changed. Choose your action again.', true); return false; }
        candidateId = matches[0].candidate_id;
      } else if (queued && app.state?.menu?.state_version !== menu?.state_version) {
        toast('The fight changed. Choose your action again.', true); return false;
      }
      const instant = isInstantToggle(app.state?.menu, candidateId, route);
      const actor = menu.actor_id, key = group && `act:${group.source_definition_id}`;
      const before = app.state?.button_states?.[actor]?.[key];
      const flip = value => render({...app.state, button_states: {...app.state.button_states,
        [actor]: {...app.state.button_states?.[actor], [key]: value}}}, {keepBar: true});
      if (instant) flip({...before, active: !before?.active});
      try {
        const result = await execute(candidateId, route, instant);
        if (!result && instant && app.matchId === match) flip(before);
        return result;
      } catch (error) {
        if (instant && app.matchId === match) flip(before);
        toast(error.message, true);   // ApiError.message is the player-facing text (api.js)
        return false;
      }
    };
    // The first flip runs synchronously, before even the first request await.
    const result = queued ? this.tail.then(run) : run();
    this.tail = result.catch(() => {}).finally(() => { this.pending--; });
    return result;
  }
}
