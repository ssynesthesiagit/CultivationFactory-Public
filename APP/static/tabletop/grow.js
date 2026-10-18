// The sheet's Grow tab (owner 2026-09-27): "the character sheets be updated with new spheres etc so when the player is
// playing theres a way to interact with the sheets", and "composite techniques ... created and added" (PHB ch. 18
// Forged Techniques). Rules-checked, with a GM override; the server decides legality (combat/table_advance.py) and
// builds each technique (character_creation/constructed_arts/forged_technique.py). Additions apply to new fights.

let deps = null;          // {h, $, fetchJson, toast, reloadSheet, projectId}
let data = null;          // GET /advancement
let query = { sphere: "", talent: "", legalOnly: true };
let forge = { name: "", base_form: "", primary_talent_id: "", secondary_talent_ids: [], augment_ids: [], drawback_ids: [], choices: {} };
let preview = null;       // POST /forge result or {error}
let busy = false;
let insightDraft = { query: "", note: "From play", choice: "" };
let artDraft = { name: "", source_record_id: "", aspect_id: "", factor_ids: [], burdens: [] };
let artProof = { die: 1, research_hours: 0, materials_gp: 0 };
let artNote = "From play";
let artPreview = null;

export function initGrow(options) {
  deps = options;
  const root = deps.$("grow-root");
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
  root.addEventListener("input", onInput);
}

export async function loadGrow() {
  const { $, fetchJson, h } = deps;
  try {
    data = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/advancement`);
    render();
  } catch (error) {
    $("grow-root").replaceChildren(h("p", { class: "muted" }, `Could not load what this character can learn: ${error.message}`));
  }
}

function gm() { return Boolean(deps.$("grow-gm")?.checked); }

async function post(path, body) {
  const session = await deps.fetchJson("/api/session");
  return deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: JSON.stringify(body),
  });
}

function why(row) {
  if (row.legal) return null;
  return (row.reasons || []).join("; ") || "not legal now";
}

function learnButton(kind, row) {
  const { h } = deps;
  const allowed = row.legal || gm();
  return h("button", { type: "button", class: `btn ${row.legal ? "btn-accent" : ""}`, disabled: !allowed || busy || null,
                       dataset: { growAdd: kind, id: row.id },
                       title: row.legal ? "Learn it" : gm() ? "Add it anyway as a GM grant" : "Turn on the GM override to add it anyway" },
           row.legal ? "Learn" : "GM add");
}


// Ability scores (combat/table_advance.py): a GM respec sets all six scores under point-buy; a level increase adds
// bounded deltas at CL 4+. The server decides legality; this panel previews the modifiers the change would give.
let abilityDraft = { mode: "level_increase", values: {} };
const ABILITY_ORDER = ["STR", "DEX", "CON", "INT", "WIS", "CHA"];
const ABILITY_NAMES = { STR: "Strength", DEX: "Dexterity", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma" };
const modOf = (score) => Math.floor((score - 10) / 2);
const signed = (n) => (n >= 0 ? `+${n}` : `${n}`);

function abilityDefaults() {
  const panel = data.ability_panel || {};
  if (abilityDraft.mode === "gm_respec") return { ...(panel.default_spread || {}) };
  return Object.fromEntries(ABILITY_ORDER.map((a) => [a, 0]));
}

function abilityPreview() {
  const panel = data.ability_panel || {};
  const current = panel.scores || {};
  const values = { ...abilityDefaults(), ...abilityDraft.values };
  if (abilityDraft.mode === "gm_respec") {
    // Only the server's authority may price a score; missing costs fail closed.
    const costs = panel.point_buy_cost || {};
    const spent = ABILITY_ORDER.reduce((s, a) => s + (costs[values[a]] ?? 0), 0);
    const cap = (panel.level_increase || {}).cap || 20;
    const rows = ABILITY_ORDER.map((a) => ({ a, from: current[a], base: values[a],
      bonus: (panel.respec_bonuses || {})[a] || 0,
      to: values[a] + ((panel.respec_bonuses || {})[a] || 0) }));
    const baseLegal = ABILITY_ORDER.every((a) => costs[values[a]] !== undefined) && spent === (panel.point_buy_budget || 27);
    const finalLegal = rows.every((r) => r.to >= 1 && r.to <= cap);
    return { legal: baseLegal && finalLegal, spent, rows,
      note: !baseLegal ? `Point-buy must be 8–15 and spend exactly ${panel.point_buy_budget || 27} points (now ${spent}).`
        : !finalLegal ? `Final scores, including earned increases, must be between 1 and ${cap}. A higher score requires the GM override.`
        : `Point-buy legal: ${panel.point_buy_budget} points. Earned Background and level increases are retained in the final scores.` };
  }
  const spent = ABILITY_ORDER.reduce((s, a) => s + (Number(values[a]) || 0), 0);
  const budget = (panel.level_increase || {}).budget || 2;
  const rule = panel.level_increase || {};
  const legal = (rule.cl || []).includes(data.cl) && !(rule.recorded_cls || []).includes(data.cl) &&
    spent === budget && ABILITY_ORDER.every((a) => {
      const increase = Number(values[a]) || 0;
      return (increase === 0 || (rule.deltas || []).includes(increase)) &&
        (current[a] ?? 0) + increase <= (rule.cap || 20);
    });
  return { legal, spent, rows: ABILITY_ORDER.map((a) => ({ a, from: current[a], to: (current[a] ?? 0) + (Number(values[a]) || 0) })),
    note: legal ? "Level increase legal: 2 points, +1 or +2 each." : `A level increase needs an unused opportunity at cultivation level ${(rule.cl || []).join(", ")}, exactly ${budget} points, and scores no higher than ${rule.cap || 20} (now ${spent} points).` };
}

function abilityBlock() {
  const { h } = deps;
  const panel = data.ability_panel || {};
  const isRespec = abilityDraft.mode === "gm_respec";
  const values = { ...abilityDefaults(), ...abilityDraft.values };
  const pv = abilityPreview();
  const rows = (data.added && data.added.abilities) || [];
  return h("details", { class: "def-block def-details", id: "grow-abilities", open: true },
    h("summary", null, h("span", { class: "def-label" }, `Ability scores (${rows.length} change${rows.length === 1 ? "" : "s"})`)),
    h("div", { class: "powering-row" },
      h("label", null, h("input", { type: "radio", name: "grow-ability-mode", value: "level_increase", id: "grow-ability-mode-level", checked: !isRespec || null, dataset: { growAbilityMode: "level_increase" } }), " Level increase (cultivation level ", (panel.level_increase || {}).cl?.join(", ") || "4", ")"),
      h("label", null, h("input", { type: "radio", name: "grow-ability-mode", value: "gm_respec", id: "grow-ability-mode-respec", checked: isRespec || null, dataset: { growAbilityMode: "gm_respec" } }), " GM score reset (set six base scores; spend exactly 27 points)"),
      isRespec ? h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilitySpread: "1" } }, "Optimized starting scores") : null),
    h("div", { class: "grow-list" }, ...ABILITY_ORDER.map((a) => h("div", { class: "grow-row" },
      h("span", null, `${ABILITY_NAMES[a]} `, h("span", { class: "def-note" }, `score ${(panel.scores || {})[a] ?? "—"}${isRespec ? "" : ` (modifier ${signed(modOf((panel.scores || {})[a] ?? 10))})`}`)),
      h("input", { type: "number", class: "input", id: `grow-ability-${a}`, min: isRespec ? 8 : 0, max: isRespec ? 15 : 2, step: 1, value: values[a], dataset: { growAbility: a } })))),
    h("p", { class: `def-note${pv.legal ? "" : " grow-why"}` }, pv.note),
    h("p", { class: "def-note" }, "A higher score improves checks and saves using that ability; its modifier also affects attacks, defenses, or other numbers that use it."),
    h("p", { class: "def-note" }, pv.rows.map((r) => isRespec
      ? `${ABILITY_NAMES[r.a]}: base ${r.base} ${signed(r.bonus)} earned = final ${r.to} (current ${r.from ?? "—"})`
      : `${ABILITY_NAMES[r.a]} ${r.from ?? "—"}→${r.to ?? "—"}`).join(" · ")),
    h("div", { class: "powering-row" },
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilitySave: "1" } }, "Record change"),
      h("span", { class: "def-note" }, "Recording updates ability modifiers, hit points, Armor Class, saving throws, initiative, skills, and technique attack and save numbers.")),
    rows.length ? h("div", { class: "grow-list" }, ...rows.map((row) => h("div", { class: "grow-row" },
      h("span", null, `${row.reason === "gm_respec" ? "GM respec" : "Level increase"} at CL ${row.cl}: ${Object.entries(row.changes || {}).map(([a, v]) => `${ABILITY_NAMES[a]} ${row.reason === "gm_respec" ? v : signed(v)}`).join(", ")}`,
        row.gm ? h("span", { class: "badge badge-gm", title: "Past the rules, by the GM" }, "GM") : null),
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilityRemove: String(row.index) } }, "Remove"))))
      : null);
}

function render() {
  const { h, $ } = deps;
  if (!data) return;
  const gmOn = gm();
  const added = data.added || { spheres: [], talents: [], forged: [] };
  const addedRows = [
    ...added.spheres.map((row) => ["sphere", row.id, `${row.name} (Sphere)`, row.gm]),
    ...added.talents.map((row) => ["talent", row.id, row.name, row.gm]),
    ...added.forged.map((row) => ["forged", row.technique_id, `${row.name} — ${row.form}, ${row.cp} CP, Complexity ${row.complexity}`, row.gm]),
  ];
  const head = h("div", { class: "def-block" },
    h("div", { class: "powering-row" },
      h("span", null, `CL ${data.cl} · ${data.realm} · ${(data.paths || []).map((p) => p.split(".").pop().replace(/_/g, " ")).join(" + ")}`),
      h("label", { class: "grow-gm", title: "Add what the rules don't allow; it is marked as a GM grant" },
        h("input", { type: "checkbox", id: "grow-gm", checked: gmOn || null }), " GM override")),
    h("p", { class: "def-note" }, "What you add here is laid over the finished character for the table and every new fight; " +
      "the Factory's sealed character is not changed. Legal means a Path can learn the Sphere, or the talent's Sphere is " +
      "known and its prerequisites hold."));
  const addedBlock = h("details", { class: "def-block def-details", open: true },
    h("summary", null, h("span", { class: "def-label" }, `Added at the table (${addedRows.length})`)),
    addedRows.length ? h("div", { class: "grow-list" }, ...addedRows.map(([kind, id, label, isGm]) => h("div", { class: "grow-row" },
      h("span", null, label, isGm ? h("span", { class: "badge badge-gm", title: "Added past the rules by the GM" }, "GM") : null),
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growRemove: kind, id } }, "Remove"))))
      : h("p", { class: "def-note" }, "Nothing yet."));

  const sq = query.sphere.trim().toLowerCase();
  const spheres = (data.spheres || []).filter((row) => !sq || row.name.toLowerCase().includes(sq));
  const sphereBlock = h("details", { class: "def-block def-details", id: "grow-spheres", open: $("grow-spheres")?.open || null },
    h("summary", null, h("span", { class: "def-label" }, `Learn a Sphere (${(data.spheres || []).filter((r) => r.legal).length} open)`)),
    h("input", { type: "search", class: "input", id: "grow-sphere-q", placeholder: "Find a Sphere…", value: query.sphere }),
    h("div", { class: "grow-list" }, ...spheres.slice(0, 80).map((row) => h("div", { class: "grow-row" },
      h("span", null, row.name, why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null), learnButton("sphere", row)))));

  const tq = query.talent.trim().toLowerCase();
  const talents = (data.talents || []).filter((row) => (!query.legalOnly || row.legal || (gmOn && row.gm))
    && (!tq || `${row.name} ${row.sphere}`.toLowerCase().includes(tq)));
  const talentBlock = h("details", { class: "def-block def-details", id: "grow-talents", open: $("grow-talents")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Learn a talent (${(data.talents || []).filter((r) => r.legal).length} legal now)`)),
    h("div", { class: "powering-row" },
      h("input", { type: "search", class: "input", id: "grow-talent-q", placeholder: "Find a talent or Sphere…", value: query.talent }),
      h("label", null, h("input", { type: "checkbox", id: "grow-legal-only", checked: query.legalOnly || null }), " legal only")),
    h("div", { class: "grow-list" }, ...talents.slice(0, 120).map((row) => h("div", { class: "grow-row", title: row.summary || "" },
      h("span", null, h("strong", null, row.name), ` · ${row.sphere}${row.minimum_cl ? ` · CL ${row.minimum_cl}` : ""}`,
        why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null),
      learnButton("talent", row)))),
    talents.length > 120 ? h("p", { class: "def-note" }, `${talents.length - 120} more — search to narrow.`) : null);

  $("grow-root").replaceChildren(head, abilityBlock(), addedBlock, insightBlock(), immortalArtBlock(), forgeBlock(), talentBlock, sphereBlock);
}

// Campaign gains use the same persisted record as every other Grow entry.
function insightBlock() {
  const { h, $ } = deps;
  const q = insightDraft.query.toLowerCase().trim();
  const rows = (data.insights || []).filter((row) => !q || (row.name + " " + row.text).toLowerCase().includes(q));
  return h("details", { class: "def-block def-details", id: "grow-insights", open: $("grow-insights")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, "Insights gained in play")),
    h("p", { class: "def-note" }, "Record a lesson or reward without gaining a level. You gain the Insight's benefit, not its level-selection ability-score increase. The sheet explains which benefits the fight automates and which need the Game Master."),
    h("label", null, "Where it came from ", h("input", { class: "input", id: "grow-insight-note", maxlength: 240, value: insightDraft.note })),
    h("label", null, "Choice required by the Insight (if any) ", h("input", { class: "input", id: "grow-insight-choice", maxlength: 240, value: insightDraft.choice })),
    h("p", { class: "def-note" }, "The GM override confirms story prerequisites and chosen options; it cannot bypass level, known-feature, or repeat limits."),
    h("input", { class: "input", type: "search", id: "grow-insight-q", placeholder: "Find an Insight…", value: insightDraft.query }),
    h("div", { class: "grow-list" }, ...rows.map((row) => h("details", { class: "grow-row" },
      h("summary", null, row.name),
      h("p", { class: "def-note", style: "white-space:pre-wrap" }, row.text),
      why(row) ? h("p", { class: "grow-why" }, why(row)) : null,
      h("button", { type: "button", class: "btn", disabled: busy || (!row.legal && !gm()) || null,
        dataset: { growInsight: row.id } }, "Record Insight")))),
    ...(data.added.insights || []).map((row) => h("div", { class: "grow-row" },
      h("span", null, row.name, " — ", row.note, row.choice ? " · " + row.choice : "", row.gm ? " (GM confirmed)" : ""),
      h("button", { type: "button", class: "btn", disabled: busy || null,
        dataset: { growRemove: "insight", id: String(row.index) } }, "Remove"))));
}

function immortalArtBlock() {
  const { h, $ } = deps;
  const menu = data.immortal_art || {};
  const aspect = (menu.aspects || []).find((row) => row.id === artDraft.aspect_id);
  const option = (value, label, selected) => h("option", { value, selected: selected || null }, label);
  const picks = (kind, rows) => h("div", { class: "grow-chips" }, ...rows.map((row) => h("label", { title: row.text || "" },
    h("input", { type: "checkbox", dataset: { growArtPick: kind, id: row.id }, checked: artDraft[kind].includes(row.id) || null }), " ", row.name)));
  const preview = artPreview?.art;
  return h("details", { class: "def-block def-details", id: "grow-immortal-art", open: $("grow-immortal-art")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Custom Immortal Arts (${menu.known || 0} of ${menu.limit || 0} known)`)),
    h("p", { class: "def-note" }, "At cultivation level 15 or higher, elevate a known action with a Dao Aspect (a powerful principle) and Factors (specific upgrades). Burdens are restrictions that reduce the cost or difficulty. Only source actions supported by the character-creation validator are offered; the same construction rules apply here."),
    menu.unavailable ? h("p", { class: "grow-why" }, menu.unavailable + " Install the Immortal Art authoring rules to create an Art here.") : null,
    h("label", null, "Name ", h("input", { class: "input", id: "grow-art-name", maxlength: 80, value: artDraft.name })),
    h("label", null, "Base action ", h("select", { class: "input", id: "grow-art-source" },
      option("", "Choose a known source action", !artDraft.source_record_id),
      ...(menu.sources || []).map((row) => option(row.id, row.name, row.id === artDraft.source_record_id)))),
    h("label", null, "Dao Aspect ", h("select", { class: "input", id: "grow-art-aspect" },
      option("", "Choose a principle", !artDraft.aspect_id),
      ...(menu.aspects || []).map((row) => option(row.id, row.name, row.id === artDraft.aspect_id)))),
    aspect ? h("div", null, h("p", null, "Factors — select upgrades (hover for rules)"), picks("factor_ids", aspect.factors),
      h("p", null, "Burdens — restrictions you must follow"), picks("burdens", aspect.burdens)) : null,
    h("button", { type: "button", class: "btn", disabled: busy || !artDraft.source_record_id || !aspect || null,
      dataset: { growArtCheck: "1" } }, "Check Art"),
    preview ? h("div", { class: "grow-preview" },
      h("p", null, `${artPreview.name}: ${preview.action_surface.action_type}; ${preview.action_surface.range}; ${preview.action_surface.target}; ${preview.action_surface.duration}. Costs ${preview.activation_cp} ${preview.action_surface.resource_name} per use. Complexity ${preview.mandate_complexity}; Refinement Check difficulty ${preview.refinement_dc}.`),
      h("p", { class: "def-note" }, artPreview.combat_note),
      h("p", { class: "def-note" }, `Before recording, complete ${artPreview.required_research_hours} hours of research, pay ${artPreview.required_materials_gp} gp in materials, and succeed on a d20 + proficiency bonus + Path ability modifier check. Record what happened at your table; this does not spend money or pass time automatically.`),
      h("label", null, "Refinement d20 result ", h("input", { class: "input", type: "number", min: 1, max: 20, id: "grow-art-die", value: artProof.die })),
      h("label", null, "Completed research hours ", h("input", { class: "input", type: "number", min: 0, id: "grow-art-hours", value: artProof.research_hours })),
      h("label", null, "Materials already paid (gp) ", h("input", { class: "input", type: "number", min: 0, id: "grow-art-gp", value: artProof.materials_gp })),
      h("label", null, "Where it came from ", h("input", { class: "input", maxlength: 240, id: "grow-art-note", value: artNote })),
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growArtSave: "1" } }, "Record refined Art")) : null,
    ...(data.added.immortal_arts || []).map((row) => h("details", { class: "grow-row" },
      h("summary", null, row.name, " — ", row.note),
      h("p", null, `Costs ${row.art.activation_cp} ${row.art.action_surface.resource_name}; ${row.art.action_surface.action_type}; ${row.art.action_surface.range}; ${row.art.action_surface.duration}.`),
      h("p", { class: "def-note" }, "Full source, upgrade and restriction rules are in the sheet's Immortal Arts library."),
      h("button", { type: "button", class: "btn", disabled: busy || null,
        dataset: { growRemove: "immortal_art", id: row.id } }, "Remove"))));
}

function forgeBlock() {
  const { h, $ } = deps;
  const f = data.forge || {};
  if (!f.available) {
    return h("details", { class: "def-block def-details" }, h("summary", null, h("span", { class: "def-label" }, "Forge a technique")),
      h("p", { class: "def-note" }, `Technique Forging opens at CL ${f.minimum_cl || 5} (Foundation).`));
  }
  const form = (f.forms || []).find((row) => row.form_id === forge.base_form);
  const primary = (f.sources || []).find((row) => row.id === forge.primary_talent_id);
  const secondaries = (f.sources || []).filter((row) => primary && row.sphere_id !== primary.sphere_id);
  const option = (value, label, on) => h("option", { value, selected: on || null }, label);
  const chips = (kind, rows, picked, label, extra) => h("div", { class: "grow-chips" }, ...rows.map((row) => h("label", {
      class: "grow-chip", title: extra?.(row) || "" },
    h("input", { type: "checkbox", dataset: { forgePick: kind, id: row[label.id] }, checked: picked.includes(row[label.id]) || null,
                 disabled: (row.legal === false && !gm()) || null }),
    ` ${row[label.name]}${label.cost ? ` (${label.cost(row)})` : ""}`)));
  const choiceRows = Object.entries(f.choices || {}).filter(([key]) => forge.augment_ids.includes(key)).map(([key, values]) =>
    h("div", { class: "powering-row" }, h("span", null, key.replace(/_/g, " ")),
      h("select", { class: "input", dataset: { forgeChoice: key } }, ...values.map((value) => option(value, value.replace(/_/g, " "), forge.choices[key] === value)))));
  const result = preview?.error ? h("p", { class: "def-note grow-error" }, preview.error)
    : preview ? h("div", { class: "grow-preview" },
      h("div", null, h("strong", null, preview.technique.name), ` — ${preview.technique.base_form.display_name}, `,
        `${preview.technique.cp_cost.final} CP, Complexity ${preview.technique.complexity.final} of ${preview.technique.complexity.realm_maximum}, `,
        `${preview.technique.action_type}, forging DC ${preview.technique.technique_forging_dc}`),
      preview.combat ? h("ul", { class: "grow-effects" },
        h("li", null, [preview.combat.range && `Range ${preview.combat.range}`, preview.combat.area, preview.combat.duration].filter(Boolean).join(" · ")),
        ...(preview.combat.effects || []).map((line) => h("li", null, line)),
        ...(preview.combat.gm || []).map((line) => h("li", { class: "def-note" }, `GM: ${line}`))) : null,
      h("button", { type: "button", class: "btn btn-accent", disabled: busy || null, dataset: { forgeSave: "1" } }, "Add to character"))
    : null;
  return h("details", { class: "def-block def-details", id: "grow-forge", open: $("grow-forge")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Forge a technique (${f.known} of ${f.limit} known · Complexity up to ${f.max_complexity} · up to ${f.max_spheres} Spheres)`)),
    h("div", { class: "powering-rows" },
      h("div", { class: "powering-row" }, h("span", null, "Name"),
        h("input", { class: "input", id: "forge-name", maxlength: "80", placeholder: "(the Forge names it)", value: forge.name })),
      h("div", { class: "powering-row" }, h("span", null, "Base Form"),
        h("select", { class: "input", id: "forge-form" }, option("", "—", !forge.base_form),
          ...(f.forms || []).map((row) => option(row.form_id, `${row.display_name} (Complexity ${row.complexity}, ${row.starting_cp} CP) — ${row.use}`, row.form_id === forge.base_form)))),
      h("div", { class: "powering-row" }, h("span", null, "Primary Sphere Effect"),
        h("select", { class: "input", id: "forge-primary" }, option("", "—", !forge.primary_talent_id),
          ...(f.sources || []).map((row) => option(row.id, `${row.name} (${row.sphere})`, row.id === forge.primary_talent_id))))),
    primary ? h("div", null, h("div", { class: "def-label" }, "Secondary Sphere Effects (+1 Complexity each, one per Sphere)"),
      chips("secondary", secondaries, forge.secondary_talent_ids, { id: "id", name: "name" }, (row) => row.sphere)) : null,
    h("div", { class: "def-label" }, "Augments"),
    chips("augment", f.augments || [], forge.augment_ids, { id: "augment_id", name: "display_name", cost: (row) => `+${row.complexity} Complexity, +${row.cp} CP` },
      (row) => row.legal === false ? `Needs ${row.minimum_realm}` : row.tier),
    ...choiceRows,
    h("div", { class: "def-label" }, "Drawbacks"),
    chips("drawback", f.drawbacks || [], forge.drawback_ids, { id: "drawback_id", name: "display_name", cost: (row) => `−${row.cp_reduction} CP` }, (row) => row.restriction),
    h("div", { class: "powering-row" },
      h("span", { class: "def-note" }, form ? form.use : "Choose a Base Form and a Primary Sphere Effect."),
      h("button", { type: "button", class: "btn", disabled: !form || !primary || busy || null, dataset: { forgePreview: "1" } }, "Check")),
    result);
}

function design() {
  return { name: forge.name.trim() || null, base_form: forge.base_form, primary_talent_id: forge.primary_talent_id,
           secondary_talent_ids: forge.secondary_talent_ids, augment_ids: forge.augment_ids, drawback_ids: forge.drawback_ids,
           choices: Object.fromEntries(Object.entries(forge.choices).filter(([key]) => forge.augment_ids.includes(key))) };
}

async function run(label, call, after) {
  busy = true;
  render();
  try {
    const result = await call();
    if (after) await after(result);
  } catch (error) {
    deps.toast("error", label, error.message, 4200);
  } finally {
    busy = false;
    render();
  }
}

function onClick(event) {
  const t = event.target;
  const insight = t.closest("[data-grow-insight]");
  if (insight) {
    void run("Insight not recorded", () => post("advancement/insight", {
      record_id: insight.dataset.growInsight, note: insightDraft.note, choice: insightDraft.choice, gm: gm()
    }), async (result) => { data = result; await deps.reloadSheet(); });
    return;
  }
  if (t.closest("[data-grow-art-check]")) {
    void run("Art is not valid", () => post("advancement/immortal-art", { design: artDraft }),
      (result) => { artPreview = result; });
    return;
  }
  if (t.closest("[data-grow-art-save]")) {
    void run("Art not recorded", () => post("advancement/immortal-art", {
      design: artDraft, note: artNote, proof: artProof, save: true
    }), async (result) => { data = result.advancement; artPreview = null; await deps.reloadSheet(); });
    return;
  }
  const add = t.closest("[data-grow-add]");
  if (add) {
    void run("Not added", () => post("advancement", { kind: add.dataset.growAdd, record_id: add.dataset.id, gm: gm() }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Learned", "New fights use it.", 2200);
    });
    return;
  }
  const abilityMode = t.closest("[data-grow-ability-mode]");
  if (abilityMode) {
    abilityDraft = { mode: abilityMode.dataset.growAbilityMode, values: {} };
    render();
    return;
  }
  if (t.closest("[data-grow-ability-spread]")) {
    abilityDraft = { mode: "gm_respec", values: { ...((data.ability_panel || {}).default_spread || {}) } };
    render();
    return;
  }
  if (t.closest("[data-grow-ability-save]")) {
    const pv = abilityPreview();
    const values = { ...abilityDefaults(), ...abilityDraft.values };
    const changes = Object.fromEntries(ABILITY_ORDER.map((a) => [a, Number(values[a]) || 0]));
    const body = abilityDraft.mode === "gm_respec"
      ? { reason: "gm_respec", changes, cl: data.cl, note: "", gm: gm() }
      : { reason: "level_increase", changes: Object.fromEntries(Object.entries(changes).filter(([, v]) => v)), cl: data.cl, note: "", gm: gm() };
    void run("Not recorded", () => post("advancement/ability", body), async (result) => {
      data = result;
      abilityDraft = { mode: abilityDraft.mode, values: {} };
      await deps.reloadSheet();
      deps.toast(pv.legal ? "ok" : "warn", "Ability scores recorded", "The sheet and new fights use the new scores.", 2600);
    });
    return;
  }
  const abilityRemove = t.closest("[data-grow-ability-remove]");
  if (abilityRemove) {
    void run("Not removed", () => post("advancement/remove", { kind: "ability", record_id: abilityRemove.dataset.growAbilityRemove }), async (result) => {
      data = result;
      await deps.reloadSheet();
    });
    return;
  }
  const remove = t.closest("[data-grow-remove]");
  if (remove) {
    void run("Not removed", () => post("advancement/remove", { kind: remove.dataset.growRemove, record_id: remove.dataset.id }), async (result) => {
      data = result;
      await deps.reloadSheet();
    });
    return;
  }
  if (t.closest("[data-forge-preview]")) {
    void run("Not forged", async () => {
      try {
        preview = await post("forge", { design: design(), gm: gm(), save: false });
      } catch (error) {
        preview = { error: error.message };
      }
    });
    return;
  }
  if (t.closest("[data-forge-save]")) {
    void run("Not forged", () => post("forge", { design: design(), gm: gm(), save: true }), async (result) => {
      data = result.advancement;
      preview = null;
      forge = { name: "", base_form: "", primary_talent_id: "", secondary_talent_ids: [], augment_ids: [], drawback_ids: [], choices: {} };
      await deps.reloadSheet();
      deps.toast("ok", `${result.technique.name} forged`, "It is on the Actions tab and in new fights.", 2600);
    });
  }
}

function onChange(event) {
  const t = event.target;
  if (t.id === "grow-gm") { render(); return; }
  if (t.id === "grow-art-source" || t.id === "grow-art-aspect") {
    artDraft[t.id === "grow-art-source" ? "source_record_id" : "aspect_id"] = t.value;
    artDraft.factor_ids = []; artDraft.burdens = []; artPreview = null; render(); return;
  }
  if (t.dataset.growArtPick) {
    const key = t.dataset.growArtPick;
    artDraft[key] = t.checked ? [...artDraft[key], t.dataset.id] : artDraft[key].filter((id) => id !== t.dataset.id);
    artPreview = null; render(); return;
  }
  if (t.id === "grow-legal-only") { query.legalOnly = t.checked; render(); return; }
  if (t.id === "forge-form") { forge.base_form = t.value; preview = null; render(); return; }
  if (t.id === "forge-primary") {
    forge.primary_talent_id = t.value;
    forge.secondary_talent_ids = [];
    preview = null;
    render();
    return;
  }
  if (t.dataset.forgeChoice) { forge.choices[t.dataset.forgeChoice] = t.value; preview = null; return; }
  if (t.dataset.forgePick) {
    const key = { secondary: "secondary_talent_ids", augment: "augment_ids", drawback: "drawback_ids" }[t.dataset.forgePick];
    const id = t.dataset.id;
    forge[key] = t.checked ? [...forge[key].filter((x) => x !== id), id] : forge[key].filter((x) => x !== id);
    if (key === "secondary_talent_ids" && t.checked) {
      // One effect per Sphere: a second pick from the same Sphere replaces the first.
      const sphere = (data.forge.sources || []).find((row) => row.id === id)?.sphere_id;
      forge[key] = forge[key].filter((x) => x === id || (data.forge.sources || []).find((row) => row.id === x)?.sphere_id !== sphere);
    }
    preview = null;
    render();
  }
}

let typing = 0;
function onInput(event) {
  const ab = event.target.dataset && event.target.dataset.growAbility;
  if (ab) {
    const id = event.target.id;
    const start = event.target.selectionStart;
    const end = event.target.selectionEnd;
    abilityDraft.values = { ...abilityDraft.values, [ab]: Number(event.target.value) || 0 };
    render();
    const input = deps.$(id);
    if (input) {
      input.focus();
      if (input.type === "text") input.setSelectionRange(start, end);
    }
    return;
  }
  const t = event.target;
  if (t.id === "grow-insight-note") { insightDraft.note = t.value; return; }
  if (t.id === "grow-insight-choice") { insightDraft.choice = t.value; return; }
  if (t.id === "grow-insight-q") {
    insightDraft.query = t.value;
    clearTimeout(typing);
    typing = setTimeout(() => { const at = t.selectionStart; render(); const again = deps.$("grow-insight-q");
      if (again) { again.focus(); again.setSelectionRange(at, at); } }, 150);
    return;
  }
  if (t.id === "grow-art-name") { artDraft.name = t.value; artPreview = null; return; }
  if (t.id === "grow-art-note") { artNote = t.value; return; }
  const proofField = { "grow-art-die": "die", "grow-art-hours": "research_hours", "grow-art-gp": "materials_gp" }[t.id];
  if (proofField) { artProof[proofField] = Number(t.value); return; }
  if (t.id === "forge-name") { forge.name = t.value; preview = null; return; }
  if (t.id === "grow-sphere-q" || t.id === "grow-talent-q") {
    query[t.id === "grow-sphere-q" ? "sphere" : "talent"] = t.value;
    clearTimeout(typing);
    typing = setTimeout(() => {
      const id = t.id, at = t.selectionStart;
      render();
      const again = deps.$(id);
      if (again) { again.focus(); again.setSelectionRange(at, at); }
    }, 150);
  }
}
