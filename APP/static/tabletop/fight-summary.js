// End-of-fight summary (owner 2026-10-06: "a summary of damage and healing and stuff … a list of the fighters and
// various metrics"). Reads only the recorded summary the service sends with a finished fight (combat/fight_summary.py);
// this file never computes a number itself, it only lays them out.

const esc = text => String(text ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

// "resource:core.stamina" -> "Stamina", "condition:typed.burning" -> "Burning" when no printed label is known.
export function idLabel(id, labels = {}) {
  if (labels[id]) return labels[id];
  const tail = String(id || "").split(/[:.]/).filter(Boolean).pop() || String(id || "");
  return tail.replace(/[_-]+/g, " ").replace(/\b\w/g, ch => ch.toUpperCase());
}

const LIFE = {DEAD: "Dead", DEFEATED: "Defeated", DYING: "Dying", STABLE: "Stable", CONSCIOUS: "Conscious at 0 HP"};

function fighterCell(row, ctx) {
  const image = ctx.imageOf?.(row.entity_id);
  const dot = image ? `<img src="${esc(image)}" alt="">` : esc(ctx.initials?.(row.display_name) ?? "");
  const state = row.final_hp <= 0 || !row.active ? (LIFE[row.life_state] || (row.active ? "" : "Off the field")) : "";
  return `<td class="tt-sum-who"><span class="tt-init-dot" style="--team:${esc(ctx.teamColor?.(row.team) || "var(--accent)")}">${dot}</span>`
    + `<span><strong>${esc(row.display_name)}</strong>${row.summoner ? ` <span class="tt-sum-tag">summon</span>` : ""}`
    + `<span class="tt-sub">HP ${row.final_hp} / ${row.maximum_hp}${state ? ` · ${esc(state)}` : ""}</span></span></td>`;
}

function resources(spent, labels) {
  const parts = Object.entries(spent || {}).filter(([, amount]) => amount).map(([id, amount]) => `${amount} ${esc(idLabel(id, labels))}`);
  return parts.length ? parts.join(", ") : "—";
}

function metricCells(m, labels) {
  const taken = m.damage_taken;
  const soaked = Math.max(0, (taken.rolled || 0) - (taken.applied || 0));
  const types = Object.entries(m.damage_dealt.by_type || {}).sort((a, b) => b[1] - a[1])
    .map(([type, amount]) => `${amount} ${esc(idLabel(type).toLowerCase())}`).join(", ");
  const a = m.attacks;
  const hitRate = a.made ? ` (${Math.round(100 * a.hits / a.made)}%)` : "";
  return [
    `<td class="tt-num" title="${types}">${m.damage_dealt.total}</td>`,
    `<td class="tt-num" title="Before reductions: ${taken.rolled}${taken.temporary_hp_absorbed ? `; temporary HP absorbed ${taken.temporary_hp_absorbed}` : ""}">${taken.applied}${soaked ? `<span class="tt-sub"> −${soaked} soaked</span>` : ""}</td>`,
    `<td class="tt-num">${m.healing_done}${m.temporary_hp_granted ? `<span class="tt-sub"> +${m.temporary_hp_granted} temp</span>` : ""}</td>`,
    `<td class="tt-num">${a.hits} / ${a.made}${hitRate}${a.critical_hits ? `<span class="tt-sub"> · ${a.critical_hits} crit</span>` : ""}${a.concealment_misses ? `<span class="tt-sub"> · ${a.concealment_misses} lost to concealment</span>` : ""}</td>`,
    `<td class="tt-num">${m.saves_forced.failed} / ${m.saves_forced.total}</td>`,
    `<td class="tt-num">${m.creatures_downed.length}</td>`,
    `<td class="tt-num">${m.times_downed}</td>`,
    `<td>${resources(m.resources_spent, labels)}</td>`,
    `<td class="tt-num">${m.turns_taken}</td>`,
  ].join("");
}

const HEAD = `<tr><th>Fighter</th><th title="Damage this fighter dealt (hover a number for damage types)">Damage dealt</th>`
  + `<th title="Damage that landed, after reductions such as Stamina Guard or resistance">Damage taken</th>`
  + `<th>Healing given</th><th title="Hits / attacks made">Hits</th><th title="Saving throws failed / forced on others">Saves failed</th>`
  + `<th title="Creatures this fighter dropped to 0 HP">Downed</th><th title="Times this fighter dropped to 0 HP">Went down</th>`
  + `<th>Spent</th><th>Turns</th></tr>`;

function highlight(label, row, ctx, names_) {
  if (!row || !row.entity_ids?.length || !row.value) return "";
  // Names come from the summary's own rows first: a destroyed or dismissed summon is no longer on the table.
  const names = row.entity_ids.map(id => esc(names_.get(id) || ctx.nameOf?.(id) || "A fighter")).join(" & ");
  return `<div class="tt-sum-hi"><span class="tt-sub">${label}</span><strong>${names}</strong><span class="tt-num">${row.value}</span></div>`;
}

// Order fighters by team, owners before their summons, then by damage dealt.
function ordered(rows) {
  const owners = rows.filter(row => !row.summoner).sort((a, b) => b.metrics.damage_dealt.total - a.metrics.damage_dealt.total);
  const out = [];
  for (const owner of owners) {
    out.push(owner);
    for (const summon of rows.filter(row => row.summoner === owner.entity_id)) out.push(summon);
  }
  for (const row of rows) if (!out.includes(row)) out.push(row);
  return out;
}

export function fightSummaryHtml(summary, ctx = {}) {
  if (!summary || !Array.isArray(summary.actors)) return `<p class="tt-muted">No summary was recorded for this fight.</p>`;
  const labels = ctx.labels || {};
  const h = summary.highlights || {};
  const names = new Map(summary.actors.map(row => [row.entity_id, row.display_name]));
  const highlights = [highlight("Most damage dealt", h.most_damage_dealt, ctx, names), highlight("Most healing", h.most_healing, ctx, names),
    highlight("Most damage taken", h.most_damage_taken, ctx, names)].join("");
  // An older fight's log can lack some details; say so instead of letting a zero look exact.
  const limits = (summary.limitations || []).length
    ? `<div class="tt-sum-limits"><strong>Some numbers are incomplete for this fight:</strong><ul>${summary.limitations.map(note => `<li>${esc(note)}</li>`).join("")}</ul></div>` : "";
  const teams = [...new Set(summary.actors.map(row => row.team))];
  const sections = teams.map(team => {
    const rows = ordered(summary.actors.filter(row => row.team === team));
    const total = (summary.teams || []).find(row => row.team === team);
    const body = rows.map(row => `<tr class="${row.summoner ? "is-summon" : ""}">${fighterCell(row, ctx)}${metricCells(row.metrics, labels)}</tr>`).join("");
    const foot = total ? `<tr class="tt-sum-total"><td><strong>Team total</strong></td>${metricCells(total.metrics, labels)}</tr>` : "";
    return `<section class="tt-sum-team"><h3>${esc(ctx.teamName?.(team) || team)}${ctx.winner && ctx.winner === team ? ` <span class="tt-sum-tag">winner</span>` : ""}</h3>`
      + `<div class="tt-sum-scroll"><table class="tt-sum-table"><thead>${HEAD}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div></section>`;
  }).join("");
  return `${limits}${highlights ? `<div class="tt-sum-highlights">${highlights}</div>` : ""}${sections}`;
}

// Open the summary by itself once per finished fight; the button reopens it any time.
export function summaryAutoOpen(app, matchId) {
  if (!app.state?.summary || app.summaryShownFor === matchId) return false;
  app.summaryShownFor = matchId;
  return true;
}
