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
let learningSource = "campaign";
let levelDraft = { open: false, step: 0, talent_ids: [], subpaths: {}, advancement: "", changes: {} };

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
    ...added.talents.map((row) => ["talent", row.id, `${row.name}${row.cl ? ` · cultivation level ${row.cl}` : ""}${row.source ? ` · ${row.source}` : ""}`, row.gm, row.source === "level"]),
    ...added.forged.map((row) => ["forged", row.technique_id, `${row.name} — ${row.form}, ${row.cp} CP, Complexity ${row.complexity}${row.source ? ` · ${row.source}` : ""}`, row.gm]),
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
    addedRows.length ? h("div", { class: "grow-list" }, ...addedRows.map(([kind, id, label, isGm, isLevel]) => h("div", { class: "grow-row" },
      h("span", null, label, isGm ? h("span", { class: "badge badge-gm", title: "Added past the rules by the GM" }, "GM") : null),
      isLevel ? h("span", { class: "def-note" }, "Use Undo last level to remove")
        : h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growRemove: kind, id } }, "Remove"))))
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

  const sourcePicker = h("label", { class: "powering-row" }, "Learning source ",
    h("select", { id: "grow-source", class: "input" }, ...(data.sources || ["campaign", "manual", "jade tablet"]).map((value) =>
      h("option", { value, selected: learningSource === value || null }, value === "campaign" ? "Campaign reward or training" : value === "manual" ? "Martial manual" : "Jade tablet"))));
  $("grow-root").replaceChildren(head, levelBlock(), abilityBlock(), addedBlock, sourcePicker, forgeBlock(), talentBlock, sphereBlock);
}

function levelBlock() {
  const { h } = deps;
  const info = data.level_up || {};
  const history = info.history || [];
  const controls = h("div", { class: "powering-row" },
    h("button", { type: "button", class: "btn btn-accent", dataset: { levelOpen: "1" }, disabled: busy || !info.available || null }, "Level up"),
    history.length ? h("button", { type: "button", class: "btn", dataset: { levelUndo: "1" }, disabled: busy || null,
      title: "Undo only the last level. Remove any later campaign gains first." }, "Undo last level") : null);
  const review = history.map((row) => h("details", null,
    h("summary", null, `Cultivation level ${row.cl} · ${String(row.at || "").slice(0, 10)}`),
    h("p", { class: "def-note" }, [...(row.features || []), ...(row.talents || [])].map((r) => r.name).join(", "))));
  if (!levelDraft.open) return h("section", { class: "def-block" }, h("h3", null, "Level up"), controls,
    h("p", { class: "def-note" }, info.reason || "Review the next level, choose its benefits, then record them together. No training cost or breakthrough is paid here."),
    ...review);
  const steps = ["Review", "Choose a talent", ...(info.subpaths?.length ? ["Choose a Subpath"] : []),
    ...(info.advancement_choice ? ["Choose ability scores or an Insight"] : []), "Confirm"];
  const title = steps[levelDraft.step] || "Confirm";
  const content = [];
  if (title === "Review") {
    content.push(h("p", null, `Cultivation level ${data.cl} → ${info.cl}. Proficiency bonus: +${info.statistics?.pb}. Maximum hit points: ${info.statistics?.hp?.maximum}.`));
    const resource = info.statistics?.resource;
    if (resource) content.push(h("p", null, `${resource.name} maximum: ${resource.maximum}. These points pay for your Path's abilities.`));
    content.push(h("p", null, "Features gained automatically:"));
    content.push(...(info.features || []).map((r) => h("details", null, h("summary", null, r.name), h("p", { style: "white-space: pre-wrap" }, r.text))));
  } else if (title === "Choose a talent") {
    content.push(h("p", null, `Choose exactly ${info.talent_count} talent from a Sphere you know. New Spheres require training or another printed source, not a free level pick.`));
    content.push(...(info.talents || []).map((r) => h("label", { class: "grow-row" },
      h("input", { type: "checkbox", value: r.id, dataset: { levelTalent: "1" },
        checked: levelDraft.talent_ids.includes(r.id) || null, disabled: !r.legal || null }),
      r.name, !r.legal ? h("span", { class: "def-note" }, (r.reasons || []).join("; ")) : null)));
  } else if (title === "Choose a Subpath") {
    for (const group of info.subpaths || []) content.push(h("label", { class: "grow-row" }, group.name,
      h("select", { class: "input", dataset: { levelSubpath: group.path_id } },
        h("option", { value: "" }, "Choose a Subpath…"), ...group.options.map((r) => h("option", {
          value: r.id, selected: levelDraft.subpaths[group.path_id] === r.id || null, disabled: r.legal === false || null },
          `${r.name} — ${r.access}; ${r.legal === false ? `needs cultivation level ${r.minimum_cl}` : `gain ${r.features.join(", ")}`}`)))));
    content.push(h("label", null, h("input", { id: "level-access", type: "checkbox", checked: levelDraft.access_confirmed || null }),
      " The Game Master confirms any required access to this Subpath."));
  } else if (title === "Choose ability scores or an Insight") {
    content.push(h("select", { class: "input", id: "level-advancement" },
      h("option", { value: "" }, "Choose one…"),
      h("option", { value: "ability", selected: levelDraft.advancement === "ability" || null }, "Improve ability scores"),
      h("option", { value: "insight", selected: levelDraft.advancement === "insight" || null }, "Learn a Cultivation Insight")));
    if (levelDraft.advancement === "ability") content.push(...ABILITY_ORDER.map((a) => h("label", { class: "grow-row" }, ABILITY_NAMES[a],
      h("input", { type: "number", min: 0, max: 2, value: levelDraft.changes[a] || 0, dataset: { levelAbility: a } }))));
    else content.push(h("p", null, "Insight level selection requires the campaign Insight growth update; no choice will be silently substituted."));
  } else {
    content.push(h("p", null, `Record cultivation level ${info.cl} and all these choices? This updates the sheet and new fights, not fights already running. The sealed character package stays unchanged.`));
    content.push(h("p", null, levelDraft.talent_ids.map((id) => info.talents.find((r) => r.id === id)?.name || "").join(", ")));
  }
  return h("section", { class: "def-block" }, h("h3", null, `Level up — ${levelDraft.step + 1} of ${steps.length}: ${title}`),
    ...content, h("div", { class: "powering-row" },
      h("button", { type: "button", class: "btn", dataset: { levelCancel: "1" } }, "Cancel"),
      levelDraft.step ? h("button", { type: "button", class: "btn", dataset: { levelBack: "1" } }, "Back") : null,
      title === "Confirm" ? h("button", { type: "button", class: "btn btn-accent", dataset: { levelSave: "1" }, disabled: busy || null }, "Record level")
        : h("button", { type: "button", class: "btn", dataset: { levelNext: "1" }, disabled: busy || null }, "Next")));
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
  if (t.closest("[data-level-open]")) { levelDraft = { open: true, step: 0, talent_ids: [], subpaths: {}, advancement: "", changes: {} }; render(); return; }
  if (t.closest("[data-level-cancel]")) { levelDraft.open = false; render(); return; }
  if (t.closest("[data-level-next]")) { levelDraft.step++; render(); return; }
  if (t.closest("[data-level-back]")) { levelDraft.step = Math.max(0, levelDraft.step - 1); render(); return; }
  if (t.closest("[data-level-save]") || t.closest("[data-level-undo]")) {
    const undo = Boolean(t.closest("[data-level-undo]"));
    void run(undo ? "Level not undone" : "Level not recorded", () => post(undo ? "advancement/level/undo" : "advancement/level",
      undo ? {} : { ...Object.fromEntries(Object.entries(levelDraft).filter(([key]) => !["open", "step"].includes(key))), cl: data.level_up.cl }), async (result) => {
        data = result; levelDraft.open = false; await deps.reloadSheet();
        deps.toast("ok", undo ? "Last level undone" : "Level up recorded", "The sheet and new fights use this growth record.", 2600);
      });
    return;
  }
  const add = t.closest("[data-grow-add]");
  if (add) {
    void run("Not added", () => post("advancement", { kind: add.dataset.growAdd, record_id: add.dataset.id, gm: gm(), source: learningSource }), async (result) => {
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
        preview = await post("forge", { design: design(), gm: gm(), save: false, source: learningSource });
      } catch (error) {
        preview = { error: error.message };
      }
    });
    return;
  }
  if (t.closest("[data-forge-save]")) {
    void run("Not forged", () => post("forge", { design: design(), gm: gm(), save: true, source: learningSource }), async (result) => {
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
  if (t.id === "grow-source") { learningSource = t.value; return; }
  if (t.dataset.levelTalent !== undefined) {
    levelDraft.talent_ids = t.checked ? [...levelDraft.talent_ids, t.value] : levelDraft.talent_ids.filter((id) => id !== t.value); render(); return;
  }
  if (t.dataset.levelSubpath) { levelDraft.subpaths[t.dataset.levelSubpath] = t.value; render(); return; }
  if (t.id === "level-access") { levelDraft.access_confirmed = t.checked; return; }
  if (t.id === "level-advancement") { levelDraft.advancement = t.value; render(); return; }
  if (t.id === "grow-gm") { render(); return; }
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
  if (event.target.dataset.levelAbility) { levelDraft.changes[event.target.dataset.levelAbility] = Number(event.target.value); return; }
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
