// Model seats at the table (owner 2026-10-06/07): a fighter can be played by you, the built-in game AI, or a model
// the owner configured (API, local server or signed-in CLI; APP/agent_seats/README.md). The server runs model turns
// and answers model-owned reactions; this file only shows who plays whom and what the model decided.

const esc = text => String(text ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

// The saved seat of one fighter: "MANUAL", "AI" or "MODEL" (with its provider), from /seat-status.
export function seatOf(status, actorId) {
  return (status && status.seats && status.seats[actorId]) || null;
}

export function isModelSeat(status, actorId) {
  return seatOf(status, actorId)?.control === "MODEL";
}

// The fighter whose model seat governs this actor: a summon follows its owner's seat, and a defeated slot is the
// engine's automatic End turn, never the model's (agent_seats/runner.py _model_owner). Null when no model plays it.
export function modelOwner(status, actor) {
  if (!actor || actor.active === false) return null;
  const owner = actor.owner_id || actor.entity_id;
  return isModelSeat(status, owner) ? owner : null;
}

// Keep observing a fight with model seats until it ends. A human menu may be suspended by a model reaction;
// even an IDLE runner can expose a human follow-up prompt without committing an event. Pause stops turns,
// not observation (another table can press Play, and a human action can still need a model reaction).
export function serverDriving(status, {terminal = false, humanMenu = false, humanPrompt = false} = {}) {
  const any = Object.values((status && status.seats) || {}).some(seat => seat?.control === "MODEL");
  return Boolean(any && !terminal && !humanPrompt);
}

export function providerLabel(providers, providerId) {
  const row = (providers || []).find(p => p.id === providerId);
  return row ? (row.label || row.model || row.id) : "a model";
}

// Which "Played by" button is lit: a model seat wins over the engine's controller mark, because a model fighter is
// submitted through the engine's manual path.
export function controlOf(status, actorId, manual) {
  if (isModelSeat(status, actorId)) return "MODEL";
  return manual ? "MANUAL" : "LOCAL_AUTO";
}

// The "Played by" buttons. Model appears only when the owner has installed at least one provider.
export function playedByHtml(providers) {
  const model = (providers || []).length
    ? `<button class="tt-tool" type="button" data-control="MODEL" title="Let a model you set up play this fighter">Model</button>` : "";
  return `<span class="tt-control" role="group" aria-label="Played by">
        <button class="tt-tool" type="button" data-control="MANUAL">You</button>
        <button class="tt-tool" type="button" data-control="SUGGESTED" title="Assisted: see five ranked choices per turn slot and pick yourself">Assisted</button>
        <button class="tt-tool" type="button" data-control="LOCAL_AUTO">AI (Dao)</button>${model}
      </span>`;
}

// The model picker: radio buttons plus an explicit button, so no scroll-wheel or keypress can hand a fighter over.
export function pickerHtml(providers, currentId) {
  const rows = (providers || []).map((p, index) => {
    const id = `ttSeatProvider${index}`;
    const kind = {openai_compatible: "API", local: "Local", cli: "Signed-in app"}[p.kind] || p.kind || "";
    const detail = [kind, p.model, p.vision ? "sees the map" : ""].filter(Boolean).map(esc).join(" · ");
    return `<label class="tt-seat-provider" for="${id}"><input type="radio" name="ttSeatProvider" id="${id}" value="${esc(p.id)}"${p.id === currentId || (!currentId && index === 0) ? " checked" : ""}>
      <span><strong>${esc(p.label || p.id)}</strong><span class="tt-sub">${detail}</span></span></label>`;
  }).join("");
  return rows || `<p class="tt-muted">No models are set up yet. Add one in APP/agent_seats/providers.json (see its README), then reopen this.</p>`;
}

function clock(seconds) {
  if (!seconds) return "";
  const d = new Date(seconds * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

// The model's recent decisions, newest first, in plain words: what it chose, what the built-in AI would have done,
// how long it took, and whether it fell back to the built-in AI.
export function decisionsHtml(rows, nameOf = id => id) {
  const shown = (rows || []).filter(row => row.kind !== "STEP").slice().reverse();
  if (!shown.length) return `<p class="tt-muted">No model decisions yet in this fight.</p>`;
  return `<ol class="tt-seat-log">${shown.map(row => {
    const builtIn = row.built_in_menu?.action;
    const chose = (row.chosen_menu || []).map(option => option.action).filter(Boolean);
    const differs = builtIn && chose.length && chose[0] !== builtIn;
    const meta = [row.model, row.latency_ms != null ? `${(row.latency_ms / 1000).toFixed(1)} s` : "",
      row.tokens?.total_tokens ? `${row.tokens.total_tokens} tokens` : ""].filter(Boolean).map(esc).join(" · ");
    return `<li class="${row.fallback || row.kind === "ERROR" ? "is-fallback" : ""}">
      <span class="tt-sub">${esc(clock(row.recorded_at))}${row.actor_id ? ` · ${esc(nameOf(row.actor_id))}` : ""}</span>
      <span>${esc(row.text || row.error || "")}</span>
      ${differs ? `<span class="tt-sub">The built-in AI would have chosen: ${esc(builtIn)}</span>` : ""}
      ${meta ? `<span class="tt-sub">${meta}</span>` : ""}
    </li>`;
  }).join("")}</ol>`;
}

// Play style: how much of the turn the controller prepares for the model. A provider's own prompt profile sets the
// suggested style ("choices" for small models); a seat may override it. Null means "use the model's suggestion".
export function suggestedStyle(provider) {
  return provider?.prompt_profile === "choices" ? "choices" : "full";
}

// Send an override only when it changes what the model would actually get: a "compact" or "tiny" provider is
// suggested "Plan the whole turn", and choosing it must still switch that seat to the full prompt.
export function styleToSend(provider, chosen) {
  return chosen && chosen !== (provider?.prompt_profile || "full") ? chosen : null;
}

export function styleHtml(provider, currentStyle) {
  if (!provider) return "";
  const suggested = suggestedStyle(provider);
  const chosen = currentStyle || suggested;
  const rows = [
    ["choices", "Pick from a short list", "The game lists a few good options and the model picks one. Fast; best for small models running on this computer."],
    ["full", "Plan the whole turn", "The model sees every legal option and plans its whole turn itself. Best for large models."],
  ].map(([value, title, help], index) => {
    const id = `ttSeatStyle${index}`;
    const note = value === suggested ? " (suggested for this model)" : "";
    return `<label class="tt-seat-provider" for="${id}"><input type="radio" name="ttSeatStyle" id="${id}" value="${value}"${value === chosen ? " checked" : ""}>
      <span><strong>${esc(title)}${esc(note)}</strong><span class="tt-sub">${esc(help)}</span></span></label>`;
  }).join("");
  return `<fieldset class="tt-seat-style"><legend>How the model plays</legend>${rows}</fieldset>`;
}

// Fight setup "Who plays" dropdown (owner 2026-10-08): You, AI, then each installed model as "MODEL:<provider id>".
// Create keeps model fighters manual and pauses playback while their seats are installed.
export const MODEL_PREFIX = "MODEL:";

export function setupControlHtml(providers) {
  const models = (providers || []).map((p, index) => `<option value="${esc(MODEL_PREFIX + p.id)}">${esc(p.label || p.model || `Installed model ${index + 1}`)}</option>`).join("");
  return `<option value="MANUAL">Manual — you choose</option><option value="SUGGESTED">Assisted — ranked choices, you choose</option><option value="LOCAL_AUTO">Auto — AI chooses</option>${models}`;
}

// Re-renders one "Who plays" menu after the model list changes (SEATLIST1), keeping the chosen mode when it still exists.
export function refreshSetupControl(select, providers) {
  const chosen = select.value;
  select.innerHTML = setupControlHtml(providers);
  select.value = chosen;
  if (select.value !== chosen) select.value = "LOCAL_AUTO";
}

// {mode, provider}: You/AI mode for the fighter picker and the provider (or null).
// Create overrides a model selection to MANUAL until its seat is installed.
export function splitSetupControl(value) {
  if (typeof value === "string" && value.startsWith(MODEL_PREFIX)) return {mode: "LOCAL_AUTO", provider: value.slice(MODEL_PREFIX.length)};
  return {mode: ["MANUAL", "SUGGESTED"].includes(value) ? value : "LOCAL_AUTO", provider: null};
}
