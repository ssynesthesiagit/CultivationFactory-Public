// Local option drafts. The server-issued manifest defines independent keys and
// toggle semantics; no client catalogue, combat rule or target is invented here.
export class OptionDraft {
  constructor(menu, matchId) {
    this.matchId = matchId;
    this.actorId = menu.actor_id;
    this.decisionId = menu.decision_id;
    this.version = menu.state_version;
    this.manifest = menu.composition || {};
    this.picks = new Map();
    this.revision = 0;
  }
  matches(menu, matchId) {
    return this.matchId === matchId && this.actorId === menu?.actor_id
      && this.decisionId === menu?.decision_id && this.version === menu?.state_version;
  }
  choose(candidateId) {
    const spec = this.manifest[candidateId];
    if (!spec) return false;
    const key = JSON.stringify(spec.key);
    if (spec.mode === 'clear') {
      for (const [id, row] of this.picks) {
        if (row.key[0] === 'augment' && row.family === spec.family) this.picks.delete(id);
      }
    }
    if (spec.mode === 'toggle' && this.picks.has(key)) this.picks.delete(key);
    else this.picks.set(key, spec);
    this.revision++;
    return true;
  }
  get dirty() { return this.picks.size > 0; }
  // Only a confirmed native action in the same turn calls this. Rebind local
  // choices to newly issued candidates; never carry stale combat targets or
  // partially retain a configuration whose settings are no longer available.
  rebase(menu, matchId) {
    if (!menu?.manual || this.actorId !== menu.actor_id || this.matchId !== matchId) return null;
    const next = new OptionDraft(menu, matchId);
    for (const pick of this.picks.values()) {
      const id = Object.keys(next.manifest).find(id => next.manifest[id].source === pick.source);
      if (!id) return null;
      next.choose(id);
    }
    return next;
  }
  request(source, requestId) {
    return {actor_id: this.actorId, decision_id: this.decisionId, state_version: this.version,
      sources: [...this.picks.values()].map(row => row.source), source_definition_id: source, request_id: requestId};
  }
  project(entries) {
    const rows = structuredClone(entries);
    const selected = option => {
      const spec = this.manifest[option.candidate_id];
      return spec && this.picks.get(JSON.stringify(spec.key));
    };
    for (const entry of rows) {
      const clear = [...this.picks.values()].some(p => p.mode === 'clear' && p.family === entry.base);
      for (const row of entry.augments || []) {
        if (clear) row.on = false;
        if (selected(row)) row.on = !row.on;
      }
      for (const row of [...(entry.options || []), ...(entry.choices || [])]) {
        const pick = selected(row);
        if (pick) row.active = pick.source === this.manifest[row.candidate_id].source;
      }
      for (const modifier of entry.modifiers || []) {
        if (selected(modifier)) modifier.on = !modifier.on;
        for (const selector of modifier.selectors || []) {
          selector.options = selector.all_options || selector.options;
          for (const option of selector.options) {
            const pick = selected(option);
            if (pick && pick.source === this.manifest[option.candidate_id]?.source) selector.current = option.value;
          }
        }
        const effect = modifier.selectors?.find(s => s.field === 'option')?.current;
        for (const selector of modifier.selectors || []) {
          const allowed = selector.allowed_by_effect?.[effect];
          if (allowed) selector.options = selector.options.filter(o => allowed.includes(o.value));
          if (!selector.options.some(o => o.value === selector.current)) selector.current = 'ask';
        }
      }
      entry.augments_label = (entry.augments || []).filter(r => r.on).map(r => r.name).join(' + ') || null;
      entry.current = [...(entry.options || []), ...(entry.choices || [])].filter(r => r.active).map(r => r.label).join(' · ') || entry.current;
    }
    return rows;
  }
}

// One reader for what the draft does to sheet Active marks: projects the draft's
// picks into a button_id -> active map. The sheet overlays this over its saved
// server states (overlayButtonStates) for the creature whose draft is open; rows
// that share a button (a shape's options, an ability's augments) are active when any is.
export function draftButtonStates(draft, rows) {
  const states = {};
  const put = (row, active) => {
    if (row?.button_id) states[row.button_id] = states[row.button_id] === true || active;
  };
  for (const entry of draft.project(rows)) {
    for (const row of [...(entry.options || []), ...(entry.choices || [])]) put(row, Boolean(row.active));
    for (const row of entry.augments || []) put(row, Boolean(row.on));
    for (const row of entry.modifiers || []) put(row, Boolean(row.on));
  }
  return states;
}

// Layers draft marks over the server's button_states without touching the server copy.
export function overlayButtonStates(serverStates = {}, draftStates = null) {
  if (!draftStates) return serverStates;
  const merged = {...serverStates};
  for (const [id, active] of Object.entries(draftStates)) merged[id] = {...(serverStates[id] || {}), active};
  return merged;
}
