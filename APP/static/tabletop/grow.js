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
const acquisitionSelections = {};

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
  const needsChoice = (row.choices || []).some(spec => !acquisitionSelections[row.id]?.[spec.key]);
  const allowed = (row.legal || gm()) && !needsChoice;
  return h("button", { type: "button", class: `btn ${row.legal ? "btn-accent" : ""}`, disabled: !allowed || busy || null,
                       dataset: { growAdd: kind, id: row.id },
                       title: row.legal ? "Learn it" : gm() ? "Add it anyway as a GM grant" : "Turn on the GM override to add it anyway" },
           row.legal ? "Learn" : "GM add");
}

function learningChoices(row) {
  const {h} = deps;
  return (row.choices || []).map(spec => h("label", {class:"def-note"}, spec.label,
    h("select", {class:"input", dataset:{growChoice:row.id, choiceKey:spec.key}},
      h("option", {value:""}, "Choose…"),
      ...spec.options.map(value => h("option", {value, selected:acquisitionSelections[row.id]?.[spec.key]===value || null},
        spec.labels?.[value] || value.replace(/_/g," ").replace(/^./,x=>x.toUpperCase()))))));
}

function render() {
  const { h, $ } = deps;
  if (!data) return;
  const gmOn = gm();
  const added = data.added || { spheres: [], talents: [], forged: [] };
  const addedRows = [
    ...added.spheres.map((row) => ["sphere", row.id, `${row.name} (Sphere)`, row.gm]),
    ...(added.source_options || []).map(row => ["source_option",row.id,row.name,row.gm]),
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
      h("span", null, row.name, why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null), ...learningChoices(row), learnButton("sphere", row)))));

  const tq = query.talent.trim().toLowerCase();
  const allTalents = [...(data.talents || []), ...(data.source_options || []).map(row => ({...row, kind:"source_option", sphere:row.sphere || "Source option"}))];
  const talents = allTalents.filter((row) => (!query.legalOnly || row.legal || (gmOn && row.gm))
    && (!tq || `${row.name} ${row.sphere}`.toLowerCase().includes(tq)));
  const talentBlock = h("details", { class: "def-block def-details", id: "grow-talents", open: $("grow-talents")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Learn a talent (${allTalents.filter((r) => r.legal).length} legal now)`)),
    h("div", { class: "powering-row" },
      h("input", { type: "search", class: "input", id: "grow-talent-q", placeholder: "Find a talent or Sphere…", value: query.talent }),
      h("label", null, h("input", { type: "checkbox", id: "grow-legal-only", checked: query.legalOnly || null }), " legal only")),
    h("div", { class: "grow-list" }, ...talents.slice(0, 120).map((row) => h("div", { class: "grow-row", title: row.summary || "" },
      h("span", null, h("strong", null, row.name), ` · ${row.sphere}${row.minimum_cl ? ` · CL ${row.minimum_cl}` : ""}`,
        why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null),
      learnButton(row.kind || "talent", row)))),
    talents.length > 120 ? h("p", { class: "def-note" }, `${talents.length - 120} more — search to narrow.`) : null);

  $("grow-root").replaceChildren(head, addedBlock, forgeBlock(), talentBlock, sphereBlock);
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
  const add = t.closest("[data-grow-add]");
  if (add) {
    void run("Not added", () => post("advancement", { kind: add.dataset.growAdd, record_id: add.dataset.id, gm: gm(),
      ...(acquisitionSelections[add.dataset.id] ? {choices:Object.fromEntries(Object.entries(acquisitionSelections[add.dataset.id]).map(([key,value])=>[key,[value]]))} : {}) }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Learned", "New fights use it.", 2200);
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
  if (t.dataset.growChoice) {
    (acquisitionSelections[t.dataset.growChoice] ||= {})[t.dataset.choiceKey] = t.value;
    render(); return;
  }
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
