// The fighter picker in Fights > New fight (owner 2026-10-04: "I want the character selection with add fighter to be
// better organized, listed by recency would be good, but also better ways to choose; organize the UI to be larger and
// more visual, with searches, maybe the tokens to select").
//
// "+ Add fighter" (or a team's fighter slot) opens a large panel: a search box (name, Path, Subpath, Sphere), Path and
// CL filters, sort by Recent / Name / CL, a "Recently used" row, and a card per character with its table token. A pick
// only sets the slot's old "— choose —" dropdown and fires its change event, so a fight is created exactly as before.
//
// The list comes from GET /api/combat/factory-characters (subpath, spheres, edited_at and token_url are read-only card
// fields, combat/fighter_picker.py); "played" comes from the saved fights the lobby already lists (created_at,
// updated_at and participant_control_modes per fight). The top half of this file is plain functions (node tests in
// tests/fighter_picker.test.mjs); open() builds the panel.

const FACTORY = "actor:factory.";
export const SORTS = [["recent", "Recent first"], ["name", "Name (A–Z)"], ["cl", "CL (highest first)"]];

const fold = text => String(text ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const later = (a, b) => (!a ? b : !b ? a : (a > b ? a : b));  // ISO UTC strings ("…Z") compare as text
const clOf = row => (Number.isFinite(Number(row.cultivation_level)) && row.cultivation_level !== null ? Number(row.cultivation_level) : null);
// Older API rows still carry just path; the panel's existing layout is unchanged.
const pathsOf = row => row.paths?.length ? row.paths : (row.path ? [row.path] : []);

/** Everything a search matches against: name, Path, Subpath and Sphere names. */
export function searchText(row) {
  return fold([row.display_name, row.path_summary, ...pathsOf(row), row.subpath, ...(row.spheres || [])].filter(Boolean).join(" "));
}

/** Every word typed must appear somewhere ("fire qi" finds a Qi Cultivation character with the Fire Sphere). */
export function matchesQuery(row, query) {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = searchText(row);
  return words.every(word => text.includes(word));
}

/** filters: {query, path, clMin, clMax}; empty values do not filter. A character with no CL fails a CL bound. */
export function filterCharacters(rows, {query = "", path = "", clMin = null, clMax = null} = {}) {
  const low = clMin === "" || clMin === null || clMin === undefined ? null : Number(clMin);
  const high = clMax === "" || clMax === null || clMax === undefined ? null : Number(clMax);
  return rows.filter(row => {
    if (path && !pathsOf(row).includes(path)) return false;
    const cl = clOf(row);
    if (low !== null && (cl === null || cl < low)) return false;
    if (high !== null && (cl === null || cl > high)) return false;
    return matchesQuery(row, query);
  });
}

/** Per character: {played, recent}. played = the latest saved fight it is in; recent = the later of that and the last
 *  time the character itself changed (finished, re-installed, renamed or advanced at the table). */
export function recencyIndex(characters, fights = []) {
  const played = {};
  for (const fight of fights || []) {
    const when = fight.last_played_at || later(fight.created_at, fight.updated_at);  // last_played_at: the fight list's activity time
    if (!when) continue;
    for (const actorId of Object.keys(fight.participant_control_modes || {})) {
      if (!actorId.startsWith(FACTORY)) continue;
      const pid = actorId.slice(FACTORY.length);
      played[pid] = later(played[pid], when);
    }
  }
  return Object.fromEntries(characters.map(row => [row.project_id,
    {played: played[row.project_id] || null, recent: later(played[row.project_id], row.edited_at) || null}]));
}

const byName = (a, b) => fold(a.display_name).localeCompare(fold(b.display_name)) || String(a.project_id).localeCompare(String(b.project_id));

/** sort: "recent" (newest first, never-seen last), "name", or "cl" (highest first). Ties fall back to the name. */
export function sortCharacters(rows, sort = "recent", recency = {}) {
  const out = rows.slice();
  if (sort === "name") return out.sort(byName);
  if (sort === "cl") return out.sort((a, b) => (clOf(b) ?? -1) - (clOf(a) ?? -1) || byName(a, b));
  return out.sort((a, b) => {
    const x = recency[a.project_id]?.recent || "", y = recency[b.project_id]?.recent || "";
    return x === y ? byName(a, b) : (x < y ? 1 : -1);
  });
}

/** The "Recently used" row: characters that have fought, latest fight first. */
export function recentlyUsed(rows, recency = {}, limit = 8) {
  return rows.filter(row => recency[row.project_id]?.played)
    .sort((a, b) => {
      const x = recency[a.project_id].played, y = recency[b.project_id].played;
      return x === y ? byName(a, b) : (x < y ? 1 : -1);
    })
    .slice(0, limit);
}

export function pathOptions(rows) {
  return [...new Set(rows.flatMap(pathsOf).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

export function initialsOf(name) {
  const words = String(name || "?").trim().split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] || "?") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

/** One line under the name: "CL 5 · Qi Cultivation · Cinder Heart Cultivator". */
export function describe(row) {
  const cl = clOf(row);
  return [cl !== null ? `CL ${cl}` : "", row.path_summary || row.path || "", row.path_summary ? "" : row.subpath || ""].filter(Boolean).join(" · ");
}

/** What a screen reader hears for a card. */
export function cardLabel(row, teamName, taken = false) {
  const spheres = (row.spheres || []).length ? `; Spheres: ${row.spheres.join(", ")}` : "";
  const bits = [row.display_name, describe(row)].filter(Boolean).join(", ");
  return taken ? `${bits}${spheres}. Already in this fight.` : `Add ${bits}${spheres} to ${teamName}`;
}

/** Fill a team slot from a pick: the same dropdown value and change event the old "— choose —" list produced. */
export function applyPick(entry, {pid, mode}) {
  entry.who.value = pid;
  if (mode) entry.control.value = mode;
  entry.who.dispatchEvent(new Event("change"));
}

// ------------------------------------------------------------------------------------------------ the panel (DOM)
let fights = [];  // the saved fights the lobby listed last (their participants and dates give "played")
const remembered = {query: "", path: "", clMin: "", clMax: "", sort: "recent", keepOpen: false};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A round token picture, or the character's initials when it has none (or it fails to load). */
function face(row, className) {
  const disc = el("span", className);
  disc.setAttribute("aria-hidden", "true");
  const letters = () => { disc.replaceChildren(); disc.textContent = initialsOf(row?.display_name); disc.classList?.add("is-initials"); };
  if (row?.token_url) {
    const image = el("img");
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.src = row.token_url;
    image.addEventListener("error", letters);
    disc.appendChild(image);
  } else letters();
  return disc;
}

/** The face of a team slot: the chosen character's token, name and CL/Path, or "Choose a fighter…". */
function fillSlotFace(button, row, teamName) {
  button.replaceChildren();
  if (row) {
    const text = el("span", "tt-slot-face-text");
    text.append(el("strong", "", row.display_name), el("small", "", describe(row)));
    button.append(face(row, "tt-pick-face"), text);
    button.setAttribute("aria-label", `${row.display_name} on ${teamName}. Click to choose a different fighter.`);
    button.title = "Choose a different fighter";
  } else {
    button.append(el("span", "tt-pick-face is-empty", "+"), el("span", "tt-slot-face-text", "Choose a fighter…"));
    button.setAttribute("aria-label", `Choose a fighter for ${teamName}`);
    button.title = "";
  }
}

function card(row, teamName, taken) {
  const button = el("button", "tt-pick-card");
  button.type = "button";
  button.dataset.pid = row.project_id;
  button.tabIndex = -1;
  if (taken) { button.disabled = true; button.classList.add("is-taken"); }
  button.setAttribute("aria-label", cardLabel(row, teamName, taken));
  const spheres = el("span", "tt-pick-spheres");
  for (const name of (row.spheres || []).slice(0, 4)) spheres.appendChild(el("span", "tt-pick-chip", name));
  if ((row.spheres || []).length > 4) spheres.appendChild(el("span", "tt-pick-chip", `+${row.spheres.length - 4}`));
  button.append(face(row, "tt-pick-face"), el("strong", "tt-pick-name", row.display_name), el("small", "tt-pick-line", describe(row)), spheres);
  if (taken) button.appendChild(el("span", "tt-pick-taken", "In this fight"));
  button.title = [row.display_name, describe(row), (row.spheres || []).length ? `Spheres: ${row.spheres.join(", ")}` : "", taken ? "Already in this fight" : ""].filter(Boolean).join("\n");
  return button;
}

// Arrow keys move to the nearest card in that direction (the grid reflows with the window, so go by position).
function neighbour(cards, from, key) {
  const a = from.getBoundingClientRect();
  const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let best = null, bestScore = Infinity;
  for (const other of cards) {
    if (other === from) continue;
    const b = other.getBoundingClientRect();
    const dx = b.left + b.width / 2 - ax, dy = b.top + b.height / 2 - ay;
    const along = {ArrowRight: dx, ArrowLeft: -dx, ArrowDown: dy, ArrowUp: -dy}[key];
    const across = key === "ArrowLeft" || key === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
    if (along <= 1) continue;
    // Left/right stay on the row; up/down prefer the same column.
    if ((key === "ArrowLeft" || key === "ArrowRight") && across > a.height / 2) continue;
    const score = along + across * 3;
    if (score < bestScore) { best = other; bestScore = score; }
  }
  return best;
}

/**
 * Open the picker.  options: {characters, teamName, mode ("MANUAL"|"LOCAL_AUTO"), taken: Set of project ids already
 * on a side, onPick({pid, mode}) -> true when more can be added, onCancel()}.  Nothing is added until a card is picked.
 */
function open({characters, teamName, mode = "MANUAL", taken = new Set(), onPick, onCancel}) {
  const recency = recencyIndex(characters, fights);
  const used = new Set(taken);
  let picked = false;
  const dialog = el("dialog", "tt-dialog tt-picker");
  dialog.setAttribute("aria-labelledby", "ttPickerTitle");
  const close = el("form", "tt-dialog-close");
  close.method = "dialog";
  const closeButton = el("button", "tt-tool", "✕");
  closeButton.setAttribute("aria-label", "Close without adding");
  close.appendChild(closeButton);
  const title = el("h2", "", `Choose a fighter for ${teamName}`);
  title.id = "ttPickerTitle";

  const bar = el("div", "tt-picker-bar");
  const search = el("input", "tt-picker-search");
  search.type = "search";
  search.placeholder = "Search by name, Path, Subpath or Sphere";
  search.setAttribute("aria-label", "Search characters by name, Path, Subpath or Sphere");
  search.value = remembered.query;
  const pathSelect = el("select");
  pathSelect.replaceChildren(new Option("Any Path", ""), ...pathOptions(characters).map(path => new Option(path, path)));
  pathSelect.value = pathOptions(characters).includes(remembered.path) ? remembered.path : "";
  const pathLabel = el("label", "tt-picker-field", "Path ");
  pathLabel.appendChild(pathSelect);
  const clLabel = el("span", "tt-picker-field tt-picker-cl", "CL ");
  const clMin = el("input"), clMax = el("input");
  for (const [input, words, value] of [[clMin, "Lowest Cultivation Level (CL) to show", remembered.clMin], [clMax, "Highest Cultivation Level (CL) to show", remembered.clMax]]) {
    input.type = "number"; input.min = "1"; input.max = "20"; input.inputMode = "numeric"; input.value = value;
    input.setAttribute("aria-label", words);
    input.title = words;
  }
  clMin.placeholder = "from"; clMax.placeholder = "to";
  clLabel.append(clMin, " – ", clMax);
  const sortSelect = el("select");
  sortSelect.replaceChildren(...SORTS.map(([value, words]) => new Option(words, value)));
  sortSelect.value = remembered.sort;
  const sortLabel = el("label", "tt-picker-field", "Sort ");
  sortLabel.appendChild(sortSelect);
  const modes = el("fieldset", "tt-picker-mode");
  modes.appendChild(el("legend", "", "Who plays them"));
  const modeInputs = {};
  for (const [value, words, help] of [["MANUAL", "You", "You choose every move with the action buttons."], ["LOCAL_AUTO", "AI", "The Local AI plays them, following the character's Dao."]]) {
    const label = el("label");
    const radio = el("input");
    radio.type = "radio"; radio.name = "ttPickerMode"; radio.value = value; radio.checked = value === mode;
    label.title = help;
    label.append(radio, ` ${words}`);
    modeInputs[value] = radio;
    modes.appendChild(label);
  }
  const keepLabel = el("label", "tt-picker-field tt-picker-keep");
  const keep = el("input");
  keep.type = "checkbox"; keep.checked = remembered.keepOpen;
  keepLabel.append(keep, " Keep open to add more");
  keepLabel.title = "Leave this panel open after a pick, to add several fighters to this side in a row.";
  const clear = el("button", "tt-tool", "Clear filters");
  clear.type = "button";
  bar.append(search, pathLabel, clLabel, sortLabel, modes, keepLabel, clear);

  const count = el("p", "tt-muted tt-picker-count");
  count.setAttribute("aria-live", "polite");
  const scroller = el("div", "tt-picker-scroll");
  dialog.append(close, title, bar, count, scroller);

  const currentMode = () => (modeInputs.LOCAL_AUTO.checked ? "LOCAL_AUTO" : "MANUAL");
  const filters = () => ({query: search.value, path: pathSelect.value, clMin: clMin.value, clMax: clMax.value});
  const cards = () => [...scroller.querySelectorAll(".tt-pick-card:not(:disabled)")];

  function render() {
    Object.assign(remembered, filters(), {sort: sortSelect.value});
    const shown = sortCharacters(filterCharacters(characters, filters()), sortSelect.value, recency);
    const sections = [];
    const plain = !search.value.trim() && !pathSelect.value && !clMin.value && !clMax.value;
    const recent = plain ? recentlyUsed(characters, recency) : [];
    if (recent.length) {
      const section = el("section", "tt-picker-section");
      section.setAttribute("aria-label", "Recently used");
      const row = el("div", "tt-picker-row");
      row.append(...recent.map(item => card(item, teamName, used.has(item.project_id))));
      section.append(el("h3", "", "Recently used"), row);
      sections.push(section);
    }
    const section = el("section", "tt-picker-section");
    section.setAttribute("aria-label", "All characters");
    const grid = el("div", "tt-picker-grid");
    grid.append(...shown.map(item => card(item, teamName, used.has(item.project_id))));
    section.append(el("h3", "", plain ? "All characters" : "Matching characters"), grid);
    if (!shown.length) section.appendChild(el("p", "tt-muted", "No character matches. Try fewer words or clear the filters."));
    sections.push(section);
    scroller.replaceChildren(...sections);
    count.textContent = `${shown.length} of ${characters.length} character${characters.length === 1 ? "" : "s"}`
      + (shown.length ? " — Enter adds the first; arrow keys move between cards." : "");
    const first = cards()[0];
    if (first) first.tabIndex = 0;
  }

  function choose(pid) {
    if (!pid || used.has(pid)) return;
    picked = true;
    const more = onPick({pid, mode: currentMode()});
    used.add(pid);
    if (keep.checked && more) {
      render();
      search.select();
      search.focus();
    } else dialog.close();
  }

  for (const input of [search, clMin, clMax]) input.addEventListener("input", render);
  for (const input of [pathSelect, sortSelect]) input.addEventListener("change", render);
  keep.addEventListener("change", () => { remembered.keepOpen = keep.checked; });
  clear.addEventListener("click", () => { search.value = ""; pathSelect.value = ""; clMin.value = ""; clMax.value = ""; render(); search.focus(); });
  scroller.addEventListener("click", event => { const target = event.target.closest(".tt-pick-card"); if (target && !target.disabled) choose(target.dataset.pid); });
  search.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); const first = cards()[0]; if (first) choose(first.dataset.pid); }
    else if (event.key === "ArrowDown") { const first = cards()[0]; if (first) { event.preventDefault(); first.focus(); } }
  });
  scroller.addEventListener("keydown", event => {
    const current = event.target.closest?.(".tt-pick-card");
    if (!current) return;
    if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      const next = neighbour(cards(), current, event.key);
      if (next) { current.tabIndex = -1; next.tabIndex = 0; next.focus(); next.scrollIntoView({block: "nearest"}); }
      else if (event.key === "ArrowUp") search.focus();
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey && event.key !== " ") {
      // Type to search from anywhere in the grid.
      search.focus();
    }
  });
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (!picked) onCancel?.();
  });

  document.body.appendChild(dialog);
  render();
  dialog.showModal();
  search.focus();
  search.select();
}

export const fighterPicker = {
  open,
  fillSlotFace,
  /** The lobby's saved-fight list, kept for "played" recency. */
  rememberFights(rows) { fights = Array.isArray(rows) ? rows : []; },
};
