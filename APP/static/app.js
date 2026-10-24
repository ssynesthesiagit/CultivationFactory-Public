let token = null;
let selectedProject = null;
let lastPackValidation = null;
const selectedPackLocks = new Set();
let characterBuilderOptions = null;
let creationMode = "quick";
const sheetSelectedChoices = new Map();
let activeSheetSphereId = null;
let guidedProjectId = null;
let guidedProjectLifecycle = null;
let guidedRun = null;
let guidedCompleteResponseSource = {kind: "none", file: null};
let guidedResponseSubmissionAction = "manual";
let guidedRecovery = null;
let ownerCharacterSheet = null;
let lastGMExport = null;
let guidedWizardStep = 1;
let guidedNavigationGeneration = 0;
let guidedStartupRecovery = {active: null, draft: null};
let productionOwnerShellReady = false;
let methodCompatibility = {key: null, state: "not_checked", result: null};
let methodCompatibilityRequestSerial = 0;
let guidedSelectedRoute = "LOCAL_AI";
// Seeded autogeneration: the seed makes every build choice instead of the AI.
let guidedAutogenSeed = null;
let guidedLocalStatus = null;
let guidedLocalPollTimer = null;
let guidedFinalizeInFlight = false;
let guidedAIWorkingTimer = null;
let gmAuthoringRatificationChallenge = null;
let guidedCandidateGMAuthoring = {
  runId: null,
  summary: null,
  status: null,
  challenge: null,
  loading: false,
  generation: 0,
};
let manualLineageResolver = {
  active: false,
  projectId: null,
  contract: null,
  targetsByType: new Map(),
  selectedTargetIds: new Set(),
  envelope: null,
  challenge: null,
  loading: false,
  approved: false,
};
let manualLineageResolverRequestSerial = 0;
const INSIGHT_BROWSER_PAGE_SIZE = 24;
const SPHERE_BROWSER_PAGE_SIZE = 36;
const TALENT_BROWSER_PAGE_SIZE = 48;
const PLANNING_FREEZE_MESSAGE = "Edit Brief / Create New Request is required to change this frozen planning envelope.";
const sphereTalentLogic = globalThis.TianxiaSphereTalentLogic;
const TianxiaSheetViewModel = globalThis.TianxiaSheetViewModel;
const pretty = value => JSON.stringify(value, null, 2);

function clearNode(node) {
  node.replaceChildren();
}

function appendTextCell(row, value, useCode = false) {
  const cell = document.createElement("td");
  const target = useCode ? document.createElement("code") : cell;
  target.textContent = value === null || value === undefined ? "" : String(value);
  if (useCode) cell.appendChild(target);
  row.appendChild(cell);
}

async function api(path, options = {}, tokenRefreshed = false) {
  const headers = {...(options.headers || {})};
  const bodyIsBinary = options.body instanceof Blob || options.body instanceof ArrayBuffer;
  if (options.body !== undefined && !bodyIsBinary && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (options.method && options.method !== "GET") headers["X-Foundry-Token"] = token;
  const response = await fetch(path, {...options, headers});
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; }
  catch (_error) { data = {error: {message: text || `Local service returned HTTP ${response.status}.`}}; }
  if (response.status === 403 && data?.error?.code === "CSRF_TOKEN_REQUIRED" && !tokenRefreshed) {
    // The local service was restarted after this page loaded, so its session
    // token changed.  Fetch the current token once and repeat the request
    // instead of stranding the page behind "a valid local session token is
    // required for mutations" until a manual reload.
    token = (await api("/api/session")).token;
    return api(path, options, true);
  }
  if (!response.ok) throw new Error(pretty(data));
  return data;
}

function closeAdvancedProductMenu() {
  const menu = document.getElementById("advancedProductMenu");
  if (menu) menu.open = false;
}

function showScreen(name, {preserveNavigation = false} = {}) {
  if (!preserveNavigation) guidedNavigationGeneration += 1;
  document.querySelectorAll(".screen").forEach(x => x.classList.toggle("active", x.id === `screen-${name}`));
  // One "Create a Character" entry covers both creation modes (the duplicate
  // detailed entry was removed 2026-09-24), so highlight by screen alone.
  document.querySelectorAll("button[data-screen]").forEach(x => x.classList.toggle("active", x.dataset.screen === name));
}

document.querySelectorAll("button[data-screen]").forEach(btn => btn.addEventListener("click", async () => {
  if (btn.closest("#advancedProductMenu")) closeAdvancedProductMenu();
  if (btn.dataset.builderMode) await startNewCharacter(btn.dataset.builderMode);
  else {
    showScreen(btn.dataset.screen);
    if (btn.dataset.screen === "projects") await loadProjects().catch(error => setGuidedStatus(plainAPIError(error, "Character Sheets could not be loaded."), true));
    if (btn.dataset.screen === "catalog") await loadCatalog().catch(() => {});
    if (btn.dataset.screen === "quickbuild") await loadQuickBuildScreen().catch(error => quickBuildStatus(plainAPIError(error, "Quick Build could not load."), true));
    if (btn.dataset.screen === "items") await loadItemsScreen().catch(error => itemsStatus(plainAPIError(error, "Items could not load."), true));
  }
}));

// Items (owner 2026-09-24): make treasures and give them to characters.
let itemsCatalog = null;
const itemsDraft = {kind: "weapon", chassis_id: "", grade: "", material_id: "", chosen: [], item_name: "", name: "", source: "catalog", custom_id: ""};
let itemsChoices = null;
let itemsCustom = null;  // the owner's custom item library (Your items)

function itemsStatus(text, isError = false) {
  const node = document.getElementById("itemsStatus");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

function itemsEl(tag, props = {}, children = []) {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) if (child) node.append(child);
  return node;
}

function itemsSelect(label, options, value, onChange, {blank = null} = {}) {
  const select = itemsEl("select");
  if (blank !== null) select.append(new Option(blank, ""));
  for (const [optionValue, text] of options) select.append(new Option(text, optionValue));
  select.value = value || "";
  select.addEventListener("change", () => onChange(select.value));
  return itemsEl("label", {}, [document.createTextNode(label), select]);
}

function itemsSpec() {
  const draft = itemsDraft;
  if (draft.kind === "weapon") return {kind: "weapon", chassis_id: draft.chassis_id, grade: draft.grade, material_id: draft.material_id, enchantment_ids: draft.chosen, name: draft.name || null};
  if (draft.kind === "armour") return {kind: "armour", chassis_id: draft.chassis_id, grade: draft.grade, material_id: draft.material_id, enhancement_ids: draft.chosen, name: draft.name || null};
  if (draft.source === "custom") return {kind: draft.kind, custom_id: draft.custom_id};
  return {kind: draft.kind, item_name: draft.item_name};
}

async function itemsRefreshChoices() {
  const draft = itemsDraft;
  if (!["weapon", "armour"].includes(draft.kind) || !draft.chassis_id || !draft.grade) { itemsChoices = null; return; }
  itemsChoices = await api("/api/items/choices", {method: "POST", body: JSON.stringify({kind: draft.kind, chassis_id: draft.chassis_id, grade: draft.grade, material_id: draft.material_id || null, chosen_ids: draft.chosen})});
  draft.material_id = itemsChoices.material_id || "";
}

async function itemsRenderForm() {
  const host = document.getElementById("itemsForm");
  const draft = itemsDraft;
  const kindRules = draft.kind === "weapon" ? itemsCatalog.weapon : draft.kind === "armour" ? itemsCatalog.armour : null;
  clearNode(host);
  if (kindRules) {
    if (!draft.chassis_id || !kindRules.chassis.some(row => row.item_id === draft.chassis_id)) draft.chassis_id = kindRules.chassis[0].item_id;
    if (!draft.grade) draft.grade = kindRules.grades[0].grade;
    await itemsRefreshChoices();
    const extras = draft.kind === "weapon" ? row => row.damage : row => row.armor_class;
    host.append(itemsSelect(draft.kind === "weapon" ? "Weapon" : "Armour",
      kindRules.chassis.map(row => [row.item_id, `${row.name} — ${extras(row)}`]), draft.chassis_id,
      async value => { draft.chassis_id = value; draft.chosen = []; await itemsRenderForm(); }));
    host.append(itemsSelect("Grade (+N)",
      kindRules.grades.map(row => [row.grade, `+${row.refinement_bonus} ${row.grade} — ${row.enchantment_capacity} ${draft.kind === "weapon" ? "enchantment" : "enhancement"} slot${row.enchantment_capacity === 1 ? "" : "s"}`]),
      draft.grade, async value => { draft.grade = value; draft.chosen = []; await itemsRenderForm(); }));
    host.append(itemsSelect("Material", (itemsChoices?.materials || []).map(row => [row.material_id, `${row.name}${row.property_name ? ` — ${row.property_name}` : ""}`]),
      draft.material_id, async value => { draft.material_id = value; draft.chosen = []; await itemsRenderForm(); }));
    const all = draft.kind === "weapon" ? kindRules.enchantments : kindRules.enhancements;
    const idKey = draft.kind === "weapon" ? "enchantment_id" : "enhancement_id";
    const byId = new Map(all.map(row => [row[idKey], row]));
    const chips = itemsEl("div", {className: "items-chips"});
    for (const id of draft.chosen) {
      const remove = itemsEl("button", {type: "button", textContent: "×", title: "Remove"});
      remove.addEventListener("click", async () => { draft.chosen = draft.chosen.filter(value => value !== id); await itemsRenderForm(); });
      chips.append(itemsEl("span", {className: "items-chip"}, [document.createTextNode(byId.get(id)?.name || id), remove]));
    }
    const legal = (draft.kind === "weapon" ? itemsChoices?.enchantments : itemsChoices?.enhancements) || [];
    const noun = draft.kind === "weapon" ? "enchantment" : "enhancement";
    host.append(itemsEl("label", {}, [document.createTextNode(`${noun[0].toUpperCase()}${noun.slice(1)}s`), chips]));
    if (legal.length) {
      host.append(itemsSelect(`Add an ${noun}`, legal.map(row => [row[idKey], `${row.name} (${row.family}${row.equivalent_bonus > 1 ? `, uses ${row.equivalent_bonus} slots` : ""})`]), "",
        async value => { if (value) { draft.chosen = [...draft.chosen, value]; await itemsRenderForm(); } }, {blank: `— choose an ${noun} —`}));
    } else {
      host.append(itemsEl("p", {className: "action-meta", textContent: draft.chosen.length ? `No slots left at this grade.` : `No ${noun}s suit this item at this grade.`}));
    }
    const name = itemsEl("input", {value: draft.name, placeholder: "Leave blank for an automatic name"});
    name.addEventListener("change", async () => { draft.name = name.value.trim(); await itemsRenderPreview(); });
    host.append(itemsEl("label", {}, [document.createTextNode("Name (optional)"), name]));
  } else {
    // Wondrous items and consumables: the Tianxia catalog, your own library, or a new custom item.
    const sources = itemsEl("div", {className: "items-source", role: "radiogroup"});
    for (const [value, label] of [["catalog", "Tianxia catalog"], ["custom", "Your items"], ["new", "New custom item"]]) {
      const radio = itemsEl("input", {type: "radio", name: "itemsSource", value, checked: draft.source === value});
      radio.addEventListener("change", async () => { draft.source = value; await itemsRenderForm(); });
      sources.append(itemsEl("label", {}, [radio, document.createTextNode(label)]));
    }
    host.append(sources);
    if (draft.source === "custom") {
      const mine = (itemsCustom || []).filter(row => row.kind === draft.kind);
      if (!mine.length) {
        host.append(itemsEl("p", {className: "action-meta", textContent: "No custom items of this kind yet. Make one with New custom item, or import some below."}));
      } else {
        if (!mine.some(row => row.custom_id === draft.custom_id)) draft.custom_id = mine[0].custom_id;
        host.append(itemsSelect("Your items", mine.map(row => [row.custom_id, `${row.name} — ${row.grade}${row.source === "import" ? " (imported)" : ""}`]), draft.custom_id,
          async value => { draft.custom_id = value; await itemsRenderPreview(); }));
        const remove = itemsEl("button", {type: "button", textContent: "Delete from your items"});
        remove.addEventListener("click", async () => {
          ({items: itemsCustom} = await api(`/api/items/custom/${encodeURIComponent(draft.custom_id)}`, {method: "DELETE"}));
          draft.custom_id = ""; await itemsRenderForm(); itemsRenderBrowse();
        });
        host.append(itemsEl("div", {className: "items-actions"}, [remove]));
      }
      await itemsRenderPreview();
      return;
    }
    if (draft.source === "new") {
      const fields = {};
      const field = (key, label, props = {}) => {
        const input = itemsEl(props.multiline ? "textarea" : "input", {placeholder: props.placeholder || "", rows: props.multiline ? 6 : undefined});
        if (props.value !== undefined) input.value = props.value;
        fields[key] = input;
        host.append(itemsEl("label", {}, [document.createTextNode(label), input]));
      };
      field("name", "Name", {placeholder: "Cloud-Step Anklet"});
      field("item_type", "Type", {placeholder: draft.kind === "wondrous" ? "Ring, Amulet, Talisman, Robe…" : "Pill, Elixir, Incense…"});
      const grade = itemsEl("select");
      for (const value of ["Mortal", "Spiritual", "Saint", "Sovereign", "Imperial"]) grade.append(new Option(value, value));
      grade.value = "Spiritual";
      host.append(itemsEl("label", {}, [document.createTextNode("Grade"), grade]));
      field("attunement_slots", "Attunement slots (0-3)", {value: draft.kind === "wondrous" ? "1" : "0"});
      field("activation", "Activation", {placeholder: "Action, Bonus Action, Reaction, Passive…"});
      field("family", "Theme (optional)", {placeholder: "Movement, Healing, Spatial Storage…"});
      field("text", "Rules text", {multiline: true, placeholder: "Exact rules: numbers, uses per rest, ranges, durations."});
      const save = itemsEl("button", {type: "button", className: "primary-action", textContent: "Save to your items"});
      save.addEventListener("click", async () => {
        try {
          const entry = {kind: draft.kind, grade: grade.value, sphere_influences: []};
          for (const [key, input] of Object.entries(fields)) entry[key] = key === "attunement_slots" ? Number(input.value || 0) : input.value;
          const result = await api("/api/items/custom", {method: "POST", body: JSON.stringify({items: [entry], source: "owner"})});
          itemsCustom = result.items;
          draft.source = "custom"; draft.custom_id = result.added[0].custom_id;
          itemsStatus(`Saved ${result.added[0].name} to your items. Choose a character and press Give item.`);
          await itemsRenderForm(); itemsRenderBrowse();
        } catch (error) {
          itemsStatus(plainAPIError(error, "The custom item could not be saved."), true);
        }
      });
      host.append(itemsEl("div", {className: "items-actions"}, [save]));
      clearNode(document.getElementById("itemsPreview"));
      return;
    }
    const rows = draft.kind === "wondrous" ? itemsCatalog.wondrous : itemsCatalog.consumables;
    if (!draft.item_name || !rows.some(row => row.name === draft.item_name)) draft.item_name = rows[0]?.name || "";
    const search = itemsEl("input", {type: "search", placeholder: "Filter by name or family"});
    const holder = itemsEl("div");
    const renderSelect = () => {
      clearNode(holder);
      const term = search.value.trim().toLowerCase();
      const shown = rows.filter(row => !term || `${row.name} ${row.family} ${row.item_type || ""}`.toLowerCase().includes(term));
      holder.append(itemsSelect(draft.kind === "wondrous" ? "Wondrous item" : "Consumable",
        shown.map(row => [row.name, `${row.name} — ${row.grade}${row.family ? `, ${row.family}` : ""}`]), draft.item_name,
        async value => { draft.item_name = value; await itemsRenderPreview(); }));
    };
    search.addEventListener("input", renderSelect);
    host.append(itemsEl("label", {}, [document.createTextNode("Search"), search]), holder);
    renderSelect();
  }
  await itemsRenderPreview();
}

function itemsDescribe(item) {
  const record = item.record || {};
  const lines = [];
  if (item.kind === "weapon") {
    const chassis = record.chassis || {};
    lines.push(`${chassis.name || ""} · ${chassis.damage || ""} · +${record.refinement_bonus} to hit and damage${chassis.properties ? ` · ${chassis.properties}` : ""}`);
  } else if (item.kind === "armour") {
    const chassis = record.chassis || {};
    lines.push(`${chassis.name || ""} · AC ${chassis.armor_class || ""} +${record.refinement_bonus} · ${chassis.armor_category || ""}`);
  } else {
    lines.push([record.item_type, record.family, record.grade, record.activation].filter(Boolean).join(" · "));
  }
  if (record.material?.name) lines.push(`Material: ${record.material.name}${record.material.property_name ? ` (${record.material.property_name})` : ""}`);
  for (const row of record.enchantments || record.enhancements || []) lines.push(`${row.name}: ${String(row.text || "").replace(/\s+/g, " ").slice(0, 400)}`);
  if (!["weapon", "armour"].includes(item.kind) && record.text) lines.push(String(record.text).replace(/\*\*/g, "").slice(0, 600));
  return lines.filter(Boolean).join("\n");
}

async function itemsRenderPreview() {
  const host = document.getElementById("itemsPreview");
  clearNode(host);
  try {
    const item = await api("/api/items/preview", {method: "POST", body: JSON.stringify(itemsSpec())});
    host.append(itemsEl("strong", {textContent: item.name}), itemsEl("span", {textContent: itemsDescribe(item)}));
  } catch (error) {
    host.append(itemsEl("span", {className: "error", textContent: plainAPIError(error, "This item cannot be made as chosen.")}));
  }
}

async function itemsRenderOwned() {
  const host = document.getElementById("itemsOwnedList");
  const select = document.getElementById("itemsCharacter");
  clearNode(host);
  if (!select.value) { host.append(itemsEl("p", {textContent: "Choose a character."})); return; }
  const {items = []} = await api(`/api/items/owned/${encodeURIComponent(select.value)}`);
  document.getElementById("itemsOwnedHeading").textContent = `Given to ${select.selectedOptions[0]?.textContent || "this character"}`;
  if (!items.length) host.append(itemsEl("p", {textContent: "Nothing given yet."}));
  for (const item of items) {
    const card = itemsEl("article", {className: "items-owned-card"});
    card.append(itemsEl("strong", {textContent: `${item.name}${item.kind === "armour" ? (item.equipped ? " (worn)" : " (not worn)") : ""}`}),
      itemsEl("span", {className: "action-meta", textContent: itemsDescribe(item)}));
    const actions = itemsEl("div", {className: "items-actions"});
    if (item.kind === "armour" && !item.equipped) {
      const wear = itemsEl("button", {type: "button", textContent: "Wear this armour"});
      wear.addEventListener("click", async () => { await api(`/api/items/owned/${encodeURIComponent(select.value)}/${encodeURIComponent(item.item_uid)}/equip`, {method: "POST", body: "{}"}); await itemsRenderOwned(); });
      actions.append(wear);
    }
    const remove = itemsEl("button", {type: "button", textContent: "Remove"});
    remove.addEventListener("click", async () => { await api(`/api/items/owned/${encodeURIComponent(select.value)}/${encodeURIComponent(item.item_uid)}`, {method: "DELETE"}); await itemsRenderOwned(); });
    actions.append(remove);
    card.append(actions);
    host.append(card);
  }
}

function itemsRenderBrowse() {
  const host = document.getElementById("itemsBrowseList");
  const term = document.getElementById("itemsBrowseSearch").value.trim().toLowerCase();
  clearNode(host);
  const groups = [
    ["Weapons", itemsCatalog.weapon.chassis, row => `${row.damage} · ${row.properties || ""} · ${row.weapon_family || ""}`],
    ["Weapon enchantments", itemsCatalog.weapon.enchantments, row => `${row.family} · from ${row.minimum_grade} · ${row.equivalent_bonus} slot(s)\n${row.text}`],
    ["Weapon materials", itemsCatalog.weapon.materials, row => `${row.grade} (up to ${row.normal_ceiling}) · ${row.property_name || ""}\n${row.property_text || ""}`],
    ["Armour", itemsCatalog.armour.chassis, row => `AC ${row.armor_class} · ${row.armor_category} · Stealth ${row.stealth}`],
    ["Armour enhancements", itemsCatalog.armour.enhancements, row => `${row.family} · ${row.compatibility_text || ""} · from ${row.minimum_grade}\n${row.text}`],
    ["Armour materials", itemsCatalog.armour.materials, row => `${row.grade} (up to ${row.normal_ceiling}) · ${row.property_name || ""}\n${row.property_text || ""}`],
    ["Wondrous items", itemsCatalog.wondrous, row => `${row.item_type || ""} · ${row.family} · ${row.grade} · ${row.attunement_slots || 0} attunement\n${row.text}`],
    ["Consumables", itemsCatalog.consumables, row => `${row.family} · ${row.grade} · ${row.activation || ""} · ${row.batch_quantity || ""} ${row.batch_unit || ""}\n${row.text || ""}`],
    ["Your items", itemsCustom || [], row => `${row.kind} · ${row.item_type || ""} · ${row.grade} · ${row.attunement_slots} attunement · ${row.activation || ""}${row.source === "import" ? " · imported" : ""}\n${row.text}`],
  ];
  let shown = 0;
  for (const [title, rows, describe] of groups) {
    const matches = rows.filter(row => !term || `${row.name} ${describe(row)}`.toLowerCase().includes(term));
    if (!matches.length) continue;
    host.append(itemsEl("h4", {textContent: `${title} (${matches.length})`}));
    for (const row of matches.slice(0, term ? 200 : 60)) {
      const text = String(describe(row)).replace(/\*\*/g, "");
      host.append(itemsEl("details", {}, [itemsEl("summary", {textContent: row.name}), itemsEl("p", {textContent: text})]));
      shown += 1;
    }
  }
  if (!shown) host.append(itemsEl("p", {textContent: "Nothing matches."}));
}

async function loadItemsScreen() {
  if (!itemsCatalog) itemsCatalog = await api("/api/items/catalog");
  const custom = await api("/api/items/custom");
  itemsCustom = custom.items;
  itemsInstructions = `${custom.instructions}\n\nExample:\n${JSON.stringify(custom.example, null, 1)}`;
  const select = document.getElementById("itemsCharacter");
  const previous = select.value;
  const {finished = [], building = []} = await api("/api/items/characters");
  clearNode(select);
  const done = itemsEl("optgroup", {label: "Finished characters"});
  for (const row of finished) done.append(new Option(`${row.display_name}${row.cultivation_level ? ` (CL ${row.cultivation_level})` : ""}`, row.project_id));
  const inProgress = itemsEl("optgroup", {label: "Being built"});
  for (const row of building) inProgress.append(new Option(`${row.display_name} · ${String(row.created_at || "").slice(0, 10)}`, row.project_id));
  select.append(done, inProgress);
  if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
  await itemsRenderForm();
  await itemsRenderOwned();
  itemsRenderBrowse();
}

document.querySelectorAll('input[name="itemsKind"]').forEach(input => input.addEventListener("change", async () => {
  itemsDraft.kind = input.value; itemsDraft.chosen = []; itemsDraft.chassis_id = ""; itemsDraft.grade = ""; itemsDraft.material_id = ""; itemsDraft.name = ""; itemsDraft.source = "catalog";
  await itemsRenderForm().catch(error => itemsStatus(plainAPIError(error, "The item form could not load."), true));
}));
document.getElementById("itemsCharacter")?.addEventListener("change", () => itemsRenderOwned().catch(error => itemsStatus(plainAPIError(error, "Given items could not load."), true)));
document.getElementById("itemsBrowseSearch")?.addEventListener("input", () => itemsRenderBrowse());
let itemsInstructions = "";
function itemsImportStatus(text, isError = false) {
  const node = document.getElementById("itemsImportStatus");
  node.textContent = text; node.classList.toggle("error", Boolean(isError));
}
document.getElementById("itemsCopyInstructions")?.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(itemsInstructions); itemsImportStatus("AI instructions copied. Paste them into the AI's chat, then paste its JSON reply above."); }
  catch (error) { document.getElementById("itemsImportText").value = itemsInstructions; itemsImportStatus("The clipboard is blocked here, so the instructions are in the box instead; copy them from there."); }
});
document.getElementById("itemsImport")?.addEventListener("click", async () => {
  const raw = document.getElementById("itemsImportText").value.trim();
  let payload;
  try {
    const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/);  // AI replies often wrap JSON in a code fence
    payload = JSON.parse(fenced ? fenced[1] : raw);
  } catch (error) { itemsImportStatus("That is not valid JSON. Paste the AI's JSON reply (a code block is fine).", true); return; }
  const items = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : payload && typeof payload === "object" ? [payload] : [];
  if (!items.length) { itemsImportStatus("No items found in that JSON.", true); return; }
  try {
    const result = await api("/api/items/custom", {method: "POST", body: JSON.stringify({items, source: "import"})});
    itemsCustom = result.items;
    itemsImportStatus(`Imported ${result.added.length} item${result.added.length === 1 ? "" : "s"}: ${result.added.map(row => row.name).join(", ")}. Find them under Your items.`);
    document.getElementById("itemsImportText").value = "";
    itemsRenderBrowse();
    if (["wondrous", "consumable"].includes(itemsDraft.kind) && itemsDraft.source === "custom") await itemsRenderForm();
  } catch (error) {
    itemsImportStatus(plainAPIError(error, "The items could not be imported."), true);
  }
});
document.getElementById("itemsGive")?.addEventListener("click", async () => {
  const select = document.getElementById("itemsCharacter");
  if (!select.value) { itemsStatus("Choose a character first.", true); return; }
  try {
    const result = await api(`/api/items/owned/${encodeURIComponent(select.value)}`, {method: "POST", body: JSON.stringify(itemsSpec())});
    itemsStatus(`Gave ${result.item.name} to ${select.selectedOptions[0]?.textContent || "the character"}.`);
    await itemsRenderOwned();
  } catch (error) {
    itemsStatus(plainAPIError(error, "The item could not be given."), true);
  }
});

// Quick Build (owner 2026-09-24): many seeded or Local AI characters in one go.
function quickBuildSeed() {
  const bytes = crypto.getRandomValues(new Uint8Array(3));
  return "QB-" + Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("").toUpperCase();
}

function quickBuildStatus(text, isError = false) {
  const node = document.getElementById("quickBuildStatus");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

function renderQuickBuildRows() {
  const body = document.getElementById("quickBuildRows");
  const count = Math.max(1, Math.min(12, Number(document.getElementById("quickBuildCount").value) || 1));
  const existing = [...body.querySelectorAll("tr")].map(row => ({seed: row.querySelector("input").value, route: row.querySelector("select").value}));
  clearNode(body);
  for (let index = 0; index < count; index += 1) {
    const prior = existing[index] || {seed: quickBuildSeed(), route: "seeded"};
    const row = document.createElement("tr");
    const seed = Object.assign(document.createElement("input"), {value: prior.seed, maxLength: 64, spellcheck: false, autocomplete: "off"});
    seed.setAttribute("aria-label", `Seed for character ${index + 1}`);
    const roll = Object.assign(document.createElement("button"), {type: "button", textContent: "🎲", title: "Roll a new seed"});
    roll.addEventListener("click", () => { seed.value = quickBuildSeed(); });
    const route = document.createElement("select");
    route.setAttribute("aria-label", `Who builds character ${index + 1}`);
    route.append(new Option("Seed (no AI, fast)", "seeded"), new Option("Local AI", "local_ai"));
    route.value = prior.route;
    const sync = () => { seed.disabled = roll.disabled = route.value === "local_ai"; };
    route.addEventListener("change", sync); sync();
    const number = document.createElement("td"); number.textContent = String(index + 1);
    const seedCell = document.createElement("td"); seedCell.className = "seed-input-row"; seedCell.append(seed, roll);
    const routeCell = document.createElement("td"); routeCell.append(route);
    row.append(number, seedCell, routeCell);
    body.appendChild(row);
  }
}

const QUICK_BUILD_ACTIVE = new Set(["queued", "waiting_to_build", "building", "waiting_to_finalize", "finalizing"]);
const QUICK_BUILD_LABELS = {queued: "Queued", waiting_to_build: "Waiting to build", building: "Building", waiting_to_finalize: "Waiting to finalize", finalizing: "Finalizing",
  finished: "Finished", ready: "Ready for review", needs_review: "Needs review", failed: "Failed", interrupted: "Interrupted"};
let quickBuildPoll = null;

async function loadQuickBuilds() {
  const host = document.getElementById("quickBuildBatches");
  if (!host) return;
  const {batches = []} = await api("/api/quick-builds");
  clearNode(host);
  if (!batches.length) host.appendChild(Object.assign(document.createElement("p"), {textContent: "No quick builds yet."}));
  let active = false;
  for (const batch of batches) {
    const card = document.createElement("article"); card.className = "quick-build-batch";
    const done = batch.items.filter(item => item.status === "finished").length;
    card.appendChild(Object.assign(document.createElement("h4"), {textContent:
      `CL ${batch.target_cl} · ${batch.items.length} ${batch.items.length === 1 ? "character" : "characters"} · ${done} finished · started ${new Date(batch.created_at).toLocaleString()}`}));
    const list = document.createElement("ol");
    for (const item of batch.items) {
      active = active || QUICK_BUILD_ACTIVE.has(item.status);
      const line = document.createElement("li"); line.className = `quick-build-item status-${item.status}`;
      const badge = Object.assign(document.createElement("span"), {className: "quick-build-badge", textContent: QUICK_BUILD_LABELS[item.status] || item.status});
      const who = item.name || (item.route === "seeded" ? `Seed ${item.seed}` : "Local AI character");
      const timing = [item.walk_seconds != null ? `walk ${item.walk_seconds} s` : "", item.finalize_seconds != null ? `finalize ${Math.round(item.finalize_seconds / 60)} min` : ""].filter(Boolean).join(" · ");
      line.append(badge, Object.assign(document.createElement("strong"), {textContent: ` ${who}`}),
        Object.assign(document.createElement("span"), {className: "action-meta", textContent: [item.name && item.seed ? `seed ${item.seed}` : "", timing, item.message].filter(Boolean).join(" · ")}));
      list.appendChild(line);
    }
    card.appendChild(list);
    host.appendChild(card);
  }
  clearTimeout(quickBuildPoll);
  if (active && document.getElementById("screen-quickbuild")?.classList.contains("active")) quickBuildPoll = setTimeout(() => loadQuickBuilds().catch(() => {}), 5000);
}

async function loadQuickBuildScreen() {
  if (!document.querySelector("#quickBuildRows tr")) renderQuickBuildRows();
  await loadQuickBuilds();
}

document.getElementById("quickBuildCount")?.addEventListener("change", renderQuickBuildRows);
document.getElementById("quickBuildRollAll")?.addEventListener("click", () => {
  for (const row of document.querySelectorAll("#quickBuildRows tr")) {
    const input = row.querySelector("input");
    if (!input.disabled) input.value = quickBuildSeed();
  }
});
document.getElementById("guidedSeedRoll")?.addEventListener("click", () => { document.getElementById("guidedSeed").value = quickBuildSeed(); });
document.getElementById("quickBuildForm")?.addEventListener("submit", async event => {
  event.preventDefault();
  const submit = document.getElementById("quickBuildSubmit");
  const items = [...document.querySelectorAll("#quickBuildRows tr")].map(row => {
    const route = row.querySelector("select").value;
    return route === "seeded" ? {route, seed: row.querySelector("input").value.trim() || null} : {route};
  });
  const bad = items.find(item => item.seed && !/^[A-Za-z0-9._:-]{1,64}$/.test(item.seed));
  if (bad) { quickBuildStatus(`Seed "${bad.seed}" can only use letters, digits, dots, dashes, colons and underscores.`, true); return; }
  submit.disabled = true;
  try {
    await api("/api/quick-builds", {method: "POST", body: JSON.stringify({
      items, target_cl: Number(document.getElementById("quickBuildLevel").value) || 5,
      power_band: document.getElementById("quickBuildPower").value,
      finalize: document.getElementById("quickBuildFinalize").checked})});
    quickBuildStatus(`Started ${items.length} ${items.length === 1 ? "build" : "builds"}. Progress shows below; you can leave this page.`);
    renderQuickBuildRows();
    for (const row of document.querySelectorAll("#quickBuildRows tr")) { const input = row.querySelector("input"); if (!input.disabled) input.value = quickBuildSeed(); }
    await loadQuickBuilds();
  } catch (error) {
    quickBuildStatus(plainAPIError(error, "Quick Build could not start."), true);
  } finally {
    submit.disabled = false;
  }
});

// One-page review (plan 2026-09-13, Part A): the wizard is four steps and step
// 4 is the single "Your character" page.  Steps 5-8 no longer exist as screens;
// their content lives in collapsed sections of step 4, so a legacy call that
// names one of them keeps the owner on step 4 and opens that section instead.
const OWNER_REVIEW_SECTION_FOR_STEP = {
  5: "ownerCompiledInsights",
  6: "ownerCompiledSpheres",
  7: "ownerSheetPreviewSection",
  8: "ownerExportSection",
};

function setGuidedStep(step, {preserveNavigation = false, section = null} = {}) {
  if (!preserveNavigation) guidedNavigationGeneration += 1;
  const requested = Number(step) || 1;
  const normalized = Math.max(1, Math.min(4, requested));
  guidedWizardStep = normalized;
  if (productionOwnerShellReady && normalized >= 2 && normalized <= 4 && creationMode !== "detailed") setCreationMode("detailed");
  const panels = {
    1: document.getElementById("builderDescribe"),
    2: document.getElementById("builderPaths"),
    3: document.getElementById("builderAI"),
    4: document.getElementById("builderReview"),
  };
  Object.entries(panels).forEach(([number, panel]) => { if (panel) panel.hidden = Number(number) !== normalized; });
  const store = document.getElementById("characterSheetPanel");
  if (store) {
    store.hidden = true;
    store.dataset.ownerStage = String(normalized);
  }
  for (let number = 1; number <= 4; number += 1) {
    const marker = document.getElementById(`builderProgress${number}`);
    if (!marker) continue;
    marker.classList.toggle("current", number === normalized);
    marker.classList.toggle("complete", number < normalized);
  }
  document.querySelectorAll("[data-owner-step]").forEach(button => {
    const active = Number(button.dataset.ownerStep) === normalized;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
  });
  const active = panels[normalized];
  if (active && requested < 5) active.scrollIntoView({behavior: "smooth", block: "start"});
  const sectionId = section || OWNER_REVIEW_SECTION_FOR_STEP[requested] || null;
  if (sectionId) openOwnerReviewSection(sectionId);
  renderPlanningFreeze();
  renderOwnerChrome();
  renderOwnerNextAction();
  renderOwnerPrimaryActions(guidedRun);
  renderCompiledOwnerStages(guidedRun);
}

function openOwnerReviewSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (!section) return null;
  const disclosure = section.tagName === "DETAILS" ? section : section.closest("details");
  if (disclosure && "open" in disclosure) disclosure.open = true;
  const target = disclosure || section;
  target.scrollIntoView?.({behavior: "smooth", block: "start"});
  return section;
}


function guidedNavigationIsCurrent(generation) {
  return generation === guidedNavigationGeneration;
}

function renderOwnerChrome(run = guidedRun) {
  const identity = ownerDisplayIdentity(run);
  const name = document.getElementById("ownerBuilderName");
  const state = document.getElementById("ownerBuilderState");
  const lifecycle = document.getElementById("diagnosticsLifecycleState");
  const displayName = identity.name || document.getElementById("guidedName")?.value.trim() || (guidedProjectId ? "Unnamed character" : "New character");
  const displayState = run?.owner_view?.display_state || {};
  const stateLabel = run ? (displayState.label || friendlyLabel(run.status || "draft")) : (guidedProjectLifecycle?.display_label || "Draft");
  if (name) name.textContent = displayName;
  if (state) state.textContent = stateLabel;
  if (lifecycle) lifecycle.textContent = run
    ? `${stateLabel} · owner screen ${displayState.step || guidedWizardStep}`
    : guidedProjectLifecycle?.plain_explanation || "No active character run.";
}

function prepareProductionOwnerShell() {
  if (productionOwnerShellReady) return;
  const panel = document.getElementById("characterSheetPanel");
  const detailHost = document.getElementById("ownerDetailHost");
  const cultivationHost = document.getElementById("ownerCultivationHost");
  const pathHost = document.getElementById("ownerPathCards");
  const insightHost = document.getElementById("ownerInsightHost");
  const sphereHost = document.getElementById("ownerSphereHost");
  if (!panel || !detailHost || !cultivationHost || !pathHost || !insightHost || !sphereHost) return;
  const ability = panel.querySelector(".ability-section");
  const cultivation = panel.querySelector('[aria-labelledby="cultivationHeading"]');
  const growth = panel.querySelector('[aria-labelledby="growthHeading"]');
  const pathChoices = panel.querySelector("#sheetPaths");
  const insightCollection = panel.querySelector("#sheetInsightAdd")?.closest(".choice-collection");
  const sphereCollection = panel.querySelector(".sphere-talent-collection");
  const itemCollection = panel.querySelector("#sheetItemAdd")?.closest(".choice-collection");
  if (cultivation) cultivationHost.appendChild(cultivation);
  if (ability) detailHost.appendChild(ability);
  if (pathChoices) pathHost.appendChild(pathChoices);
  if (insightCollection) insightHost.appendChild(insightCollection);
  if (sphereCollection) sphereHost.appendChild(sphereCollection);
  if (itemCollection) sphereHost.appendChild(itemCollection);
  if (growth && !growth.querySelector(".choice-collection")) growth.remove();
  panel.hidden = true;
  panel.classList.add("production-state-store");
  productionOwnerShellReady = true;
  renderPlanningFreeze();
}

prepareProductionOwnerShell();

document.querySelectorAll("[data-owner-step]").forEach(button => button.addEventListener("click", () => setGuidedStep(button.dataset.ownerStep)));
document.querySelectorAll("[data-owner-target]").forEach(button => button.addEventListener("click", () => setGuidedStep(button.dataset.ownerTarget)));

const diagnosticsDrawer = document.getElementById("diagnosticsDrawer");
const diagnosticsToggle = document.getElementById("diagnosticsToggle");
const closeDiagnostics = document.getElementById("closeDiagnostics");
const drawerScrim = document.getElementById("drawerScrim");
let diagnosticsOpener = null;
function diagnosticsFocusables() {
  return diagnosticsDrawer ? Array.from(diagnosticsDrawer.querySelectorAll('button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])')).filter(node => !node.disabled && node.offsetParent !== null) : [];
}
function setDiagnostics(open) {
  if (!diagnosticsDrawer || !diagnosticsToggle || !drawerScrim) return;
  diagnosticsDrawer.classList.toggle("is-open", open);
  diagnosticsDrawer.setAttribute("aria-hidden", String(!open));
  diagnosticsToggle.setAttribute("aria-pressed", String(open));
  drawerScrim.hidden = !open;
  if (open) {
    diagnosticsOpener = document.activeElement;
    requestAnimationFrame(() => (diagnosticsFocusables()[0] || diagnosticsDrawer).focus({preventScroll: true}));
  } else {
    requestAnimationFrame(() => diagnosticsOpener?.focus?.({preventScroll: true}));
  }
}
diagnosticsToggle?.addEventListener("click", () => {
  closeAdvancedProductMenu();
  setDiagnostics(true);
});
closeDiagnostics?.addEventListener("click", () => setDiagnostics(false));
drawerScrim?.addEventListener("click", () => setDiagnostics(false));
document.addEventListener("keydown", event => {
  if (!diagnosticsDrawer?.classList.contains("is-open")) return;
  if (event.key === "Escape") { event.preventDefault(); setDiagnostics(false); return; }
  if (event.key !== "Tab") return;
  const focusables = diagnosticsFocusables();
  if (!focusables.length) { event.preventDefault(); diagnosticsDrawer.focus(); return; }
  const first = focusables[0]; const last = focusables[focusables.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

function setGuidedStatus(message, isError = false) {
  const status = document.getElementById("guidedStatus");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function formatGuidedElapsed(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

const GUIDED_CONTROLLER_ROUTE = "DETERMINISTIC_CREATIVE_CONTROLLER";
let guidedControllerProgressTimer = null;
let guidedControllerProgressStartedAt = 0;
let guidedControllerProgressGeneration = 0;

function guidedUsesController(route, mode) {
  // Owner decision (plan section 13): the guided Local AI route defaults to
  // the deterministic controller; the legacy full-plan prompt is an explicit
  // Advanced opt-out.  Manual Chat never calls a provider, so it keeps the
  // legacy request packet.
  if (mode === "MANUAL_CHAT") return false;
  if (guidedAutogenSeed) return true;
  if (route !== "LOCAL_AI") return false;
  return !document.getElementById("guidedLegacyFullPlanOptOut")?.checked;
}

function stopGuidedControllerProgress() {
  if (guidedControllerProgressTimer) window.clearInterval(guidedControllerProgressTimer);
  guidedControllerProgressTimer = null;
  // Invalidate in-flight ticks so a late poll cannot overwrite the status
  // (for example an error message) after the walk has stopped.
  guidedControllerProgressGeneration += 1;
}

function guidedControllerHeadline(progress) {
  const walk = progress?.walk;
  if (!walk) return "Guided build: preparing the frozen request…";
  const ordinal = Number.isInteger(walk.step_ordinal) ? walk.step_ordinal : 0;
  const estimate = Number.isInteger(walk.steps_estimate) && walk.steps_estimate > 0
    ? (ordinal > walk.steps_estimate ? ` (the estimate was ${walk.steps_estimate})` : ` of about ${walk.steps_estimate}`)
    : "";
  const title = walk.step_title ? ` — ${walk.step_title}` : "";
  if (walk.state === "COMPLETED") return `Guided build: all ${ordinal} steps chosen; the Factory is validating and compiling`;
  if (walk.state === "NEEDS_REVIEW") return `Guided build stopped at step ${ordinal}${title}`;
  return `Guided build: step ${ordinal}${estimate}${title}`;
}

function renderGuidedControllerProgress(progress, elapsedMs = null) {
  const box = document.getElementById("guidedControllerProgress");
  const headline = guidedControllerHeadline(progress);
  if (box) {
    box.hidden = false;
    box.replaceChildren();
    const heading = document.createElement("p");
    heading.textContent = headline;
    box.appendChild(heading);
    const rows = Array.isArray(progress?.committed_choices) ? progress.committed_choices : [];
    if (rows.length) {
      const list = document.createElement("ul");
      for (const row of rows) {
        const item = document.createElement("li");
        const names = Array.isArray(row.names) && row.names.length ? row.names.join(", ") : `${row.count || 1} chosen`;
        item.textContent = `${row.title}: ${names}`;
        list.appendChild(item);
      }
      box.appendChild(list);
    }
    if (progress?.diagnostic?.message) {
      const note = document.createElement("p");
      note.className = "error";
      note.textContent = `${progress.diagnostic.step_title ? `${progress.diagnostic.step_title}: ` : ""}${progress.diagnostic.message}`;
      box.appendChild(note);
    }
  }
  if (elapsedMs !== null) {
    const status = document.getElementById("guidedStatus");
    if (status) {
      status.textContent = `${headline} · ${formatGuidedElapsed(elapsedMs)} elapsed`;
      status.classList.remove("error");
      status.classList.add("working");
      status.setAttribute("aria-busy", "true");
    }
  }
}

function startGuidedControllerProgress(projectId, runIdHint = null) {
  stopGuidedAIWorking();
  guidedControllerProgressStartedAt = Date.now();
  const generation = guidedControllerProgressGeneration;
  let runId = runIdHint;
  const box = document.getElementById("guidedControllerProgress");
  if (box) {
    box.hidden = false;
    box.textContent = "Guided build: preparing the frozen request…";
  }
  let inFlight = false;
  const tick = async () => {
    // Never overlap polls: the active-run lookup is one indexed row read,
    // but a slow progress read must not pile up behind itself while the
    // server is busy assembling the request or waiting on the model.
    if (inFlight) return;
    inFlight = true;
    try {
      if (generation !== guidedControllerProgressGeneration) return;
      if (!runId) {
        const active = await api(`/api/projects/${encodeURIComponent(projectId)}/character-creation/controller/active`);
        runId = active?.run_id || null;
      }
      if (generation !== guidedControllerProgressGeneration) return;
      if (!runId) {
        setGuidedStatus(`Guided build: the Factory is assembling and freezing the request (the slow catalogue step) · ${formatGuidedElapsed(Date.now() - guidedControllerProgressStartedAt)} elapsed`);
        return;
      }
      const progress = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/controller/progress`);
      if (generation !== guidedControllerProgressGeneration) return;
      renderGuidedControllerProgress(progress, Date.now() - guidedControllerProgressStartedAt);
    } catch (_ignored) {
      // Transient read failures while the walk holds the write lock are
      // expected; the next tick retries.
    } finally {
      inFlight = false;
    }
  };
  tick();
  guidedControllerProgressTimer = window.setInterval(tick, 4000);
}

async function refreshGuidedControllerProgress(run) {
  if (run?.request?.controller_route !== GUIDED_CONTROLLER_ROUTE || !run?.run_id) return;
  try {
    renderGuidedControllerProgress(await api(`/api/character-creation/runs/${encodeURIComponent(run.run_id)}/controller/progress`));
  } catch (_ignored) {
    // The candidate view still renders; progress is a convenience.
  }
}

function updateGuidedControllerResume(run) {
  const button = document.getElementById("guidedResumeControllerWalk");
  if (!button) return;
  // A walk stopped by a bounded failure (NEEDS_REVIEW) or by a service
  // restart mid-walk (still PREPARING_REQUEST) both resume from the saved
  // step through the same continue route.
  const eligible = run?.request?.controller_route === GUIDED_CONTROLLER_ROUTE && ["NEEDS_REVIEW", "PREPARING_REQUEST"].includes(run?.status)
    && !guidedRunAtGmGate(run);
  button.hidden = !eligible;
  button.disabled = !eligible;
  button.dataset.runId = eligible ? run.run_id : "";
}

function stopGuidedAIWorking() {
  stopGuidedControllerProgress();
  if (guidedAIWorkingTimer !== null) window.clearInterval(guidedAIWorkingTimer);
  guidedAIWorkingTimer = null;
  const status = document.getElementById("guidedStatus");
  if (!status) return;
  status.classList.remove("working");
  status.removeAttribute("aria-busy");
}

function startGuidedAIWorking(message) {
  stopGuidedAIWorking();
  const startedAt = Date.now();
  const update = () => {
    const status = document.getElementById("guidedStatus");
    if (!status) return;
    status.textContent = `${message} · ${formatGuidedElapsed(Date.now() - startedAt)} elapsed`;
    status.classList.remove("error");
    status.classList.add("working");
    status.setAttribute("aria-busy", "true");
  };
  update();
  guidedAIWorkingTimer = window.setInterval(update, 1000);
}

function parseAPIError(error) {
  const raw = error?.message || String(error || "");
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.error || parsed;
    return {raw: parsed, code: detail?.code || "LOCAL_ERROR", message: detail?.message || raw, details: detail?.details ?? null};
  } catch (_ignored) {
    return {raw, code: "LOCAL_ERROR", message: raw, details: null};
  }
}

function readableDiagnosticValue(value, key = "") {
  if (Array.isArray(value)) return value.map(item => readableDiagnosticValue(item, key)).join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value).map(([name, item]) => `${friendlyLabel(name)}: ${readableDiagnosticValue(item, name)}`).join("; ");
  }
  if (value === null || value === undefined || value === "") return "not supplied";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" && ["path", "paths", "required_path_ids", "unsupported_path_ids", "proposed_method_granted_path_ids"].some(token => key.includes(token))) {
    const ids = value.split(", ").map(item => item.trim()).filter(Boolean);
    return ids.map(id => choiceFor("path_choice", id)?.name || id).join(", ");
  }
  return String(value);
}

function ownerDiagnosticMessage(diagnostic, fallback = "The requested action could not be completed.") {
  const message = diagnostic?.message || fallback;
  const details = diagnostic?.details;
  if (diagnostic?.code === "CG1_DELEGATED_ONE_SHOT_BINDING_MISMATCH") {
    return `${message} Expected: a response for the currently active one-shot request. Proposed: this response belongs to a different build request.`;
  }
  if (!details || typeof details !== "object") return message;
  if (details.required_path_ids || details.unsupported_path_ids || details.proposed_method_granted_path_ids) {
    const expected = readableDiagnosticValue(details.required_path_ids || [], "required_path_ids");
    const proposed = readableDiagnosticValue(details.proposed_method_granted_path_ids || [], "proposed_method_granted_path_ids");
    const missing = readableDiagnosticValue(details.unsupported_path_ids || [], "unsupported_path_ids");
    return `${message} Expected: the selected Method must support every locked Path (${expected || "no Path locks"}). Proposed: it supports ${proposed || "no matching locked Paths"}; missing ${missing || "none"}.`;
  }
  const expected = details.expected ?? details.required ?? details.expected_value;
  const proposed = details.proposed ?? details.actual ?? details.actual_value;
  if (expected !== undefined || proposed !== undefined) {
    const parts = [];
    if (expected !== undefined) parts.push(`Expected: ${readableDiagnosticValue(expected, "expected")}`);
    if (proposed !== undefined) parts.push(`Proposed: ${readableDiagnosticValue(proposed, "proposed")}`);
    return `${message} ${parts.join(" ")}`;
  }
  if (details.mismatches && typeof details.mismatches === "object") {
    const mismatch = Object.entries(details.mismatches).slice(0, 3).map(([field, value]) => {
      const row = value && typeof value === "object" ? value : {actual: value};
      return `${friendlyLabel(field)} expected ${readableDiagnosticValue(row.expected, "expected")}, proposed ${readableDiagnosticValue(row.actual ?? row.proposed, "proposed")}`;
    });
    if (mismatch.length) return `${message} Expected-versus-proposed: ${mismatch.join("; ")}.`;
  }
  if (Array.isArray(details.choice_ids) && details.slot_id) {
    const proposedChoices = details.choice_ids.map(id => choiceFor(details.slot_id, id)?.name || choiceFor(details.slot_id, id)?.canonical_name || id).join(", ");
    const slotLabel = details.slot_id === "sphere_priorities" ? "Sphere selections" : friendlyLabel(details.slot_id);
    const reasons = details.reasons && typeof details.reasons === "object"
      ? Object.entries(details.reasons).map(([id, reason]) => `${choiceFor(details.slot_id, id)?.name || id}: ${reason === "origin_proficiency_grammar_unresolved" ? "its tool, kit, language or trade proficiency option is not typed yet; choose an Origin whose options are all skills" : friendlyLabel(String(reason))}`)
      : [];
    const why = reasons.length ? ` Why: ${reasons.join("; ")}.` : "";
    return `${message} Expected: exact ${slotLabel.toLowerCase()} with their complete mechanical rows. Proposed: ${proposedChoices || "no selections"} were supplied as selection intent only.${why}`;
  }
  return message;
}

function recordGuidedDiagnostic(error, context = "") {
  const host = document.getElementById("guidedDiagnosticsDetail");
  if (!host) return;
  const diagnostic = parseAPIError(error);
  host.textContent = pretty({context: context || "owner_action", code: diagnostic.code, message: diagnostic.message, details: diagnostic.details});
}

function isManualLineageBoundedChoiceDiagnostic(diagnostic) {
  return diagnostic?.code === "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"
    && diagnostic?.details?.slot_id === "manual_lineage_training_source";
}

function manualLineageDiagnosticFromRun(run) {
  if (!run) return null;
  const owner = ownerViewFor(run);
  const candidates = [
    run.submission_error,
    run.validation?.last_submission_error,
    ...(Array.isArray(run.blockers) ? run.blockers : []),
    ...(Array.isArray(owner.blockers) ? owner.blockers : []),
    ...(Array.isArray(owner.decisions) ? owner.decisions : []),
  ];
  return candidates.find(isManualLineageBoundedChoiceDiagnostic) || null;
}

function manualLineageResetState() {
  manualLineageResolverRequestSerial += 1;
  manualLineageResolver = {
    active: false,
    projectId: null,
    contract: null,
    targetsByType: new Map(),
    selectedTargetIds: new Set(),
    envelope: null,
    challenge: null,
    loading: false,
    approved: false,
  };
  const host = document.getElementById("guidedManualLineageResolver");
  if (host) host.hidden = true;
  const routes = document.getElementById("guidedManualLineageRoutes");
  if (routes) clearNode(routes);
  const ownerForm = document.getElementById("guidedManualLineageOwnerForm");
  if (ownerForm) ownerForm.hidden = true;
  const preview = document.getElementById("guidedManualLineagePreview");
  if (preview) preview.hidden = true;
  const previewFields = document.getElementById("guidedManualLineagePreviewFields");
  if (previewFields) clearNode(previewFields);
  const advanced = document.getElementById("guidedManualLineageAdvancedDetails");
  if (advanced) advanced.textContent = "";
  const confirm = document.getElementById("guidedManualLineageApprovalConfirm");
  if (confirm) confirm.checked = false;
  const targetOptions = document.getElementById("guidedManualLineageTargetOptions");
  if (targetOptions) clearNode(targetOptions);
}

function setManualLineageStatus(message, state = "") {
  const successful = state === "success" || state === "prepared";
  const status = document.getElementById("guidedManualLineageStatus");
  if (status) {
    status.textContent = message;
    status.classList.toggle("error", state === "error");
    status.classList.toggle("success", successful);
  }
  const pill = document.getElementById("guidedManualLineageStatusPill");
  if (pill) {
    pill.textContent = state === "error" ? "Choice unavailable" : state === "success" ? "Source sealed" : state === "prepared" ? "Approval prepared" : "Choice required";
    pill.dataset.state = state || "pending";
  }
}

function appendManualLineagePreviewField(host, label, value, {fullWidth = false, pre = false} = {}) {
  const field = document.createElement("div");
  field.className = `manual-lineage-preview-field${fullWidth ? " full-width" : ""}`;
  const heading = document.createElement("strong");
  heading.textContent = label;
  field.appendChild(heading);
  if (pre) {
    const content = document.createElement("pre");
    content.textContent = value === null || value === undefined ? "" : String(value);
    field.appendChild(content);
  } else {
    const content = document.createElement("code");
    content.textContent = value === null || value === undefined ? "" : String(value);
    field.appendChild(content);
  }
  host.appendChild(field);
}

function renderManualLineagePreview(challengeResponse) {
  const preview = challengeResponse?.preview || {};
  const host = document.getElementById("guidedManualLineagePreviewFields");
  const previewPanel = document.getElementById("guidedManualLineagePreview");
  if (!host || !previewPanel) return;
  clearNode(host);
  appendManualLineagePreviewField(host, "Display name", preview.display_name);
  appendManualLineagePreviewField(host, "Summary", preview.summary, {fullWidth: true, pre: true});
  appendManualLineagePreviewField(host, "Exact source text", preview.source_text, {fullWidth: true, pre: true});
  appendManualLineagePreviewField(host, "Source path", preview.source_path);
  appendManualLineagePreviewField(host, "Source anchor", preview.source_anchor);
  appendManualLineagePreviewField(host, "Source text SHA-256", preview.source_text_sha256);
  appendManualLineagePreviewField(host, "Access mode", preview.access_mode);
  appendManualLineagePreviewField(host, "Training types", (preview.training_types || []).join(", "));
  appendManualLineagePreviewField(host, "Target identities", pretty(preview.target_identities || []), {fullWidth: true, pre: true});
  appendManualLineagePreviewField(host, "Record identity", `${preview.record_id || ""} · ${preview.record_hash || ""}`, {fullWidth: true});
  appendManualLineagePreviewField(host, "Exact record bytes SHA-256", preview.exact_record_bytes_sha256, {fullWidth: true});
  appendManualLineagePreviewField(host, "Approval binding", pretty(preview.binding || challengeResponse.binding || {}), {fullWidth: true, pre: true});
  appendManualLineagePreviewField(host, "Project lock proof SHA-256", preview.project_lock_proof_hash || challengeResponse.project_lock_proof_hash, {fullWidth: true});
  const advanced = document.getElementById("guidedManualLineageAdvancedDetails");
  if (advanced) {
    advanced.textContent = pretty({
      challenge_id: challengeResponse.challenge?.challenge_id,
      nonce: challengeResponse.challenge?.nonce,
      exact_bytes_hash: challengeResponse.challenge?.exact_bytes_hash,
      binding: challengeResponse.binding,
      project_lock_proof_hash: challengeResponse.project_lock_proof_hash,
    });
  }
  previewPanel.hidden = false;
  const postApproval = document.getElementById("guidedManualLineagePostApproval");
  if (postApproval) postApproval.hidden = !manualLineageResolver.approved;
  const confirm = document.getElementById("guidedManualLineageApprovalConfirm");
  if (confirm) confirm.checked = false;
  updateManualLineageButtons();
}

function renderManualLineageRoutes(contract) {
  const host = document.getElementById("guidedManualLineageRoutes");
  if (!host) return;
  clearNode(host);
  const routes = Array.isArray(contract?.resolution_routes) ? contract.resolution_routes : [];
  for (const route of routes) {
    if (!route || typeof route !== "object") continue;
    const card = document.createElement("article");
    card.className = "manual-lineage-route-card";
    card.dataset.routeId = String(route.route_id || "");
    card.dataset.selected = "false";
    const title = document.createElement("h5");
    title.textContent = String(route.route_id || "Manual Lineage route").replaceAll("_", " ");
    const status = document.createElement("p");
    status.className = "manual-lineage-route-status";
    const available = route.available === true;
    if (route.route_id === "selected_ai_custom_training_source") {
      status.textContent = route.actionable_now === false
        ? `${route.availability_status || "requires_explicit_ai_proposal"} — Not actionable now; an explicit server-owned AI proposal is required.`
        : String(route.availability_status || "Proposal required");
    } else if (route.route_id === "locked_canonical_training_source") {
      status.textContent = available
        ? `${Number(route.total_count) || 0} authenticated locked source${Number(route.total_count) === 1 ? "" : "s"} available.`
        : "Unavailable — no authenticated project-locked source is available.";
      if (!available) card.classList.add("unavailable");
    } else {
      status.textContent = available ? "Available for explicit owner entry." : "Unavailable.";
    }
    card.appendChild(title);
    card.appendChild(status);
    const requirements = document.createElement("small");
    requirements.textContent = String(route.requirements || "");
    card.appendChild(requirements);
    if (route.route_id === "locked_canonical_training_source" && available && Array.isArray(contract.locked_canonical_records)) {
      const list = document.createElement("ul");
      for (const source of contract.locked_canonical_records.slice(0, 50)) {
        const item = document.createElement("li");
        item.textContent = `${source.display_name || "Unnamed source"} · ${source.source_path || "authenticated source"}`;
        list.appendChild(item);
      }
      card.appendChild(list);
    }
    host.appendChild(card);
  }
  const ownerRoute = routes.find(route => route?.route_id === "owner_supplied_custom_training_source");
  const ownerForm = document.getElementById("guidedManualLineageOwnerForm");
  if (ownerForm) ownerForm.hidden = ownerRoute?.actionable_now !== true;
}

function manualLineageSelectedTrainingTypes() {
  const select = document.getElementById("guidedManualLineageTrainingTypes");
  if (!select) return [];
  return [...select.selectedOptions].map(option => option.value).filter(Boolean);
}

function renderManualLineageTargetOptions(trainingType = manualLineageSelectedTrainingTypes()[0] || "new_sphere") {
  const select = document.getElementById("guidedManualLineageTargetOptions");
  if (!select) return;
  clearNode(select);
  const records = manualLineageResolver.targetsByType.get(trainingType) || [];
  for (const record of records) {
    const option = document.createElement("option");
    option.value = String(record.record_id || "");
    option.textContent = `${record.display_name || "Unnamed target"} · ${record.content_type || trainingType}`;
    option.selected = manualLineageResolver.selectedTargetIds.has(option.value);
    select.appendChild(option);
  }
}

function updateManualLineageButtons() {
  const form = document.getElementById("guidedManualLineageOwnerForm");
  const prepare = document.getElementById("guidedManualLineagePrepare");
  const approve = document.getElementById("guidedManualLineageApprove");
  const confirm = document.getElementById("guidedManualLineageApprovalConfirm");
  const ready = Boolean(form?.checkValidity()) && manualLineageSelectedTrainingTypes().length > 0 && manualLineageResolver.selectedTargetIds.size > 0;
  if (prepare) prepare.disabled = !ready || manualLineageResolver.loading || manualLineageResolver.approved;
  if (approve) approve.disabled = !manualLineageResolver.challenge || !confirm?.checked || manualLineageResolver.approved;
}

function manualLineageEnvelopeFromForm() {
  const value = id => document.getElementById(id)?.value.trim() || "";
  return {
    route_id: "owner_supplied_custom_training_source",
    owner_confirmation_id: value("guidedManualLineageOwnerConfirmation"),
    display_name: value("guidedManualLineageDisplayName"),
    summary: value("guidedManualLineageSummary"),
    source_text: value("guidedManualLineageSourceText"),
    source_anchor: value("guidedManualLineageSourceAnchor"),
    access_mode: value("guidedManualLineageAccessMode"),
    training_types: manualLineageSelectedTrainingTypes(),
    target_record_ids: [...manualLineageResolver.selectedTargetIds].sort(),
  };
}

async function loadManualLineageTargets() {
  if (!manualLineageResolver.active || !manualLineageResolver.projectId) return;
  const types = manualLineageSelectedTrainingTypes();
  const type = types[0] || "new_sphere";
  const queryNode = document.getElementById("guidedManualLineageTargetQuery");
  const rawQuery = queryNode?.value || "";
  const query = rawQuery.trim();
  const status = document.getElementById("guidedManualLineageTargetStatus");
  if (rawQuery && !query) {
    if (status) status.textContent = "Enter a name or leave Search blank; whitespace-only queries are not sent.";
    renderManualLineageTargetOptions(type);
    return;
  }
  if (status) status.textContent = "Loading authenticated legal targets…";
  const serial = manualLineageResolverRequestSerial;
  const queryString = query ? `&q=${encodeURIComponent(query)}` : "";
  try {
    const result = await api(`/api/projects/${encodeURIComponent(manualLineageResolver.projectId)}/manual-lineage-training-source/targets?training_type=${encodeURIComponent(type)}&limit=50${queryString}`);
    if (serial !== manualLineageResolverRequestSerial || !manualLineageResolver.active) return;
    manualLineageResolver.targetsByType.set(type, Array.isArray(result.records) ? result.records : []);
    renderManualLineageTargetOptions(type);
    if (status) status.textContent = `${manualLineageResolver.targetsByType.get(type).length} authenticated ${type.replaceAll("_", " ")} target(s) shown; choose from the list.`;
    updateManualLineageButtons();
  } catch (error) {
    if (status) {
      status.textContent = ownerDiagnosticMessage(parseAPIError(error), "Authenticated legal targets could not be loaded.");
      status.classList.add("error");
    }
  }
}

function manualLineageShowError(error, fallback) {
  const diagnostic = parseAPIError(error);
  recordGuidedDiagnostic(error, "manual_lineage_training_source");
  setManualLineageStatus(ownerDiagnosticMessage(diagnostic, fallback), "error");
}

async function loadManualLineageResolverContract() {
  if (!manualLineageResolver.active || !manualLineageResolver.projectId || manualLineageResolver.loading) return;
  manualLineageResolver.loading = true;
  const serial = ++manualLineageResolverRequestSerial;
  setManualLineageStatus("Loading the exact server-owned choice contract…");
  try {
    const contract = await api(`/api/projects/${encodeURIComponent(manualLineageResolver.projectId)}/manual-lineage-training-source`);
    if (serial !== manualLineageResolverRequestSerial || !manualLineageResolver.active) return;
    manualLineageResolver.contract = contract;
    renderManualLineageRoutes(contract);
    const requirement = document.getElementById("guidedManualLineageRequirement");
    if (requirement) requirement.textContent = `${contract.requirement || "One source-backed training source"}. ${contract.owner_warning || "No route is selected automatically."}`;
    setManualLineageStatus("No route is selected automatically. Owner-supplied source entry is available when you are ready.");
    await loadManualLineageTargets();
  } catch (error) {
    if (serial === manualLineageResolverRequestSerial) manualLineageShowError(error, "The Manual Lineage choice contract could not be loaded.");
  } finally {
    if (serial === manualLineageResolverRequestSerial) {
      manualLineageResolver.loading = false;
      updateManualLineageButtons();
    }
  }
}

function openManualLineageResolver(diagnostic) {
  if (!isManualLineageBoundedChoiceDiagnostic(diagnostic) || !guidedProjectId) return;
  if (manualLineageResolver.projectId !== guidedProjectId) manualLineageResetState();
  manualLineageResolver.active = true;
  manualLineageResolver.projectId = guidedProjectId;
  const host = document.getElementById("guidedManualLineageResolver");
  if (host) host.hidden = false;
  if (!manualLineageResolver.contract && !manualLineageResolver.loading) void loadManualLineageResolverContract();
}

function syncManualLineageResolverForRun(run) {
  const diagnostic = manualLineageDiagnosticFromRun(run);
  if (diagnostic) openManualLineageResolver(diagnostic);
  else if (!manualLineageResolver.approved) {
    const host = document.getElementById("guidedManualLineageResolver");
    if (host) host.hidden = true;
    manualLineageResolver.active = false;
  }
}

function initManualLineageResolver() {
  const form = document.getElementById("guidedManualLineageOwnerForm");
  const typeSelect = document.getElementById("guidedManualLineageTrainingTypes");
  const search = document.getElementById("guidedManualLineageTargetSearch");
  const query = document.getElementById("guidedManualLineageTargetQuery");
  const targetOptions = document.getElementById("guidedManualLineageTargetOptions");
  const confirm = document.getElementById("guidedManualLineageApprovalConfirm");
  const approve = document.getElementById("guidedManualLineageApprove");
  if (typeSelect) {
    typeSelect.options[0].selected = true;
    typeSelect.addEventListener("change", () => { renderManualLineageTargetOptions(); void loadManualLineageTargets(); updateManualLineageButtons(); });
  }
  if (search) search.addEventListener("click", () => void loadManualLineageTargets());
  if (query) query.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); void loadManualLineageTargets(); } });
  if (targetOptions) targetOptions.addEventListener("change", () => {
    for (const option of targetOptions.options) {
      if (option.selected) manualLineageResolver.selectedTargetIds.add(option.value);
      else manualLineageResolver.selectedTargetIds.delete(option.value);
    }
    updateManualLineageButtons();
  });
  form?.addEventListener("input", updateManualLineageButtons);
  form?.addEventListener("change", updateManualLineageButtons);
  form?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!manualLineageResolver.active || !manualLineageResolver.contract || manualLineageResolver.approved) return;
    const prepare = document.getElementById("guidedManualLineagePrepare");
    if (!form.checkValidity() || !manualLineageSelectedTrainingTypes().length || !manualLineageResolver.selectedTargetIds.size) {
      form.reportValidity();
      setManualLineageStatus("Complete the bounded source fields and choose authenticated legal targets before preparing approval.", "error");
      return;
    }
    const envelope = manualLineageEnvelopeFromForm();
    manualLineageResolver.loading = true;
    if (prepare) prepare.disabled = true;
    setManualLineageStatus("Preparing the exact approval challenge; nothing is sealed yet…");
    try {
      const issued = await api(`/api/projects/${encodeURIComponent(manualLineageResolver.projectId)}/manual-lineage-training-source/challenge`, {method: "POST", body: JSON.stringify({...envelope, ttl_seconds: 300})});
      manualLineageResolver.envelope = envelope;
      manualLineageResolver.challenge = issued;
      manualLineageResolver.approved = false;
      renderManualLineagePreview(issued);
      setManualLineageStatus("Exact approval prepared. Review the source and hashes, then explicitly approve; nothing was sealed by this step.", "prepared");
    } catch (error) {
      manualLineageShowError(error, "The exact approval challenge could not be prepared.");
    } finally {
      manualLineageResolver.loading = false;
      updateManualLineageButtons();
    }
  });
  confirm?.addEventListener("change", updateManualLineageButtons);
  approve?.addEventListener("click", async () => {
    const issued = manualLineageResolver.challenge;
    const challenge = issued?.challenge;
    if (!challenge || !confirm?.checked || manualLineageResolver.approved) return;
    approve.disabled = true;
    setManualLineageStatus("Sealing the reviewed exact source through the one-time approval…");
    try {
      const receipt = await api(`/api/projects/${encodeURIComponent(manualLineageResolver.projectId)}/manual-lineage-training-source/approve`, {
        method: "POST",
        body: JSON.stringify({
          ...manualLineageEnvelopeFromForm(),
          ...(manualLineageResolver.envelope || {}),
          challenge_id: challenge.challenge_id,
          nonce: challenge.nonce,
        }),
      });
      manualLineageResolver.approved = true;
      const postApproval = document.getElementById("guidedManualLineagePostApproval");
      if (postApproval) postApproval.hidden = false;
      setManualLineageStatus("The exact source is sealed. A new candidate revision and regenerated candidate/binding review are required before Finalize.", "success");
      const advanced = document.getElementById("guidedManualLineageAdvancedDetails");
      if (advanced) advanced.textContent = pretty({challenge: receipt.approval || challenge, receipt});
      updateManualLineageButtons();
    } catch (error) {
      manualLineageShowError(error, "The exact source could not be approved.");
      updateManualLineageButtons();
    }
  });
}

initManualLineageResolver();

function ownerViewFor(run) {
  return run?.owner_view && typeof run.owner_view === "object" ? run.owner_view : {};
}

function ownerDisplayIdentity(run) {
  const owner = ownerViewFor(run);
  const preview = run?.dry_run?.preview || {};
  const identity = owner.identity || preview.identity?.identity || preview.identity || {};
  return identity && typeof identity === "object" ? identity : {};
}

function ownerText(value, fallback = "Pending owner review") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return value.name || value.display_name || value.label || value.title || fallback;
}

function ownerCardLines(rows, fallback = "No validated owner-readable values are available yet.") {
  if (!Array.isArray(rows) || !rows.length) return [fallback];
  return rows.map(row => {
    if (typeof row === "string") return row;
     const name = ownerText(row?.name || row?.subpath || row?.display_name, "Unnamed value");
     const description = row?.description || row?.note;
      const state = row?.state || row?.mode;
      const attainment = row?.attainment !== undefined && row?.attainment !== null ? ` · attainment ${row.attainment}` : "";
      const owningPath = row?.path || row?.owning_path_name;
      const provenance = row?.provenance ? ` · ${row.provenance}` : "";
      const planning = row?.planning_only ? " · planning only" : "";
      return `${name}${owningPath ? ` · ${owningPath}` : ""}${state ? ` · ${friendlyLabel(state)}` : ""}${provenance}${planning}${attainment}${description ? ` — ${description}` : ""}`;
  });
}

function ownerCardSummary(row, fallback = "Not projected yet") {
  if (typeof row === "string") return row;
  if (!row || typeof row !== "object") return fallback;
  const name = ownerText(row.name || row.subpath || row.display_name, fallback);
  const context = row.sphere || row.path || row.owning_path_name || "";
  const cl = row.cl !== undefined && row.cl !== null ? `CL ${row.cl}` : "";
  const state = row.state || row.mode || "";
  return [name, context, cl, state ? friendlyLabel(state) : ""].filter(Boolean).join(" · ");
}

function appendCompiledRecord(host, row, {kind = "record", showDescription = true} = {}) {
  const card = document.createElement("article");
  card.className = `compiled-record-card compiled-record-${kind}`;
  const heading = document.createElement("strong");
  heading.textContent = ownerText(row?.name || row?.display_name || row?.canonical_name || row?.title || row?.label || row?.insight || row?.talent_name || row?.sphere_name || row?.choice_id, "Unnamed source-backed value");
  card.appendChild(heading);
  const meta = [row?.sphere, row?.cl !== undefined && row?.cl !== null ? `CL ${row.cl}` : "", row?.category || row?.timing, row?.acquisition ? friendlyLabel(row.acquisition) : ""].filter(Boolean);
  if (meta.length) {
    const line = document.createElement("span");
    line.className = "compiled-record-meta";
    line.textContent = meta.join(" · ");
    card.appendChild(line);
  }
  const descriptionText = row?.description || row?.short_description || row?.one_line_description || row?.full_description || row?.full_description_text || row?.player_rules_text || row?.effect || row?.summary;
  if (showDescription && descriptionText) {
    const details = document.createElement("details");
    details.className = "compiled-record-details";
    const summary = document.createElement("summary");
    summary.textContent = "View details";
    details.appendChild(summary);
    const description = document.createElement("p");
    description.className = "compiled-record-description";
    description.textContent = descriptionText;
    details.appendChild(description);
    card.appendChild(details);
  }
  host.appendChild(card);
}

function ownerInsightDisplayRecord(row) {
  if (typeof row === "string") return {name: row};
  const catalogRecord = row?.choice_id ? choiceFor("insight_priorities", row.choice_id) : null;
  const record = catalogRecord && typeof catalogRecord === "object" ? catalogRecord : {};
  return {
    ...record,
    ...(row && typeof row === "object" ? row : {}),
    name: row?.name || row?.display_name || row?.canonical_name || row?.insight || record.name || record.display_name || record.canonical_name,
    description: row?.description || row?.short_description || record.description || record.short_description,
  };
}

function appendCompiledEmpty(host, message) {
  const empty = document.createElement("p");
  empty.className = "compiled-empty";
  empty.textContent = message;
  host.appendChild(empty);
}

function groupedByCL(rows) {
  const groups = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = Number.isInteger(row?.cl) ? row.cl : "unscheduled";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return groups;
}

function proposalAcquisitionSummary(proposal = {}) {
  const acquisitions = proposal.acquisitions || {};
  const counted = (rows, label) => `${rows.length} ${label}${rows.length === 1 ? "" : "s"}`;
  return [
    counted(proposal.background_sphere || [], "Background Sphere"),
    counted(proposal.background_talent || [], "Background Talent"),
    counted(acquisitions.sphere_free_talent_pairs || [], "starting free pair"),
    counted(acquisitions.level_talents || acquisitions.ordinary_talents || [], "free level Talent"),
    Array.isArray(acquisitions.trained_choices) ? counted(acquisitions.trained_choices, "trained choice") : "Training details unavailable",
    Array.isArray(acquisitions.new_sphere_bonus_talents) ? counted(acquisitions.new_sphere_bonus_talents, "new-Sphere bonus Talent") : "New-Sphere bonus details unavailable",
  ].join(" · ");
}

function renderProposalSphereInventory(host, inventory) {
  const holdings = Array.isArray(inventory.holdings) ? inventory.holdings : [];
  const requestedMissing = Array.isArray(inventory.requested_not_acquired) ? inventory.requested_not_acquired : [];
  const unassigned = Array.isArray(inventory.unassigned_talents) ? inventory.unassigned_talents : [];
  const missing = Array.isArray(inventory.missing_mandatory) ? inventory.missing_mandatory : [];
  const counts = inventory.counts || {};
  const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
  const group = (label, open) => {
    const details = document.createElement("details");
    details.className = "compiled-disclosure-card compiled-sphere-group compiled-sphere-inventory";
    details.open = Boolean(open);
    const summary = document.createElement("summary"); summary.textContent = label; details.appendChild(summary);
    return details;
  };
  const inventoryGroup = group(`Sphere inventory · ${plural(holdings.length, "Sphere")} · ${plural(Number(counts.talents) || 0, "Talent")}${counts.validated_spheres ? ` · ${counts.validated_spheres} validated` : ""}`, true);
  const note = document.createElement("p"); note.className = "compiled-planning-note";
  note.textContent = "Every Sphere this response would hold, with how and when it is acquired and the Talents that depend on it. Rows stay proposed until the compiled result confirms them; requested priorities that never arrived are listed separately.";
  inventoryGroup.appendChild(note);
  if (holdings.length) {
    const grid = document.createElement("div"); grid.className = "compiled-record-grid";
    for (const row of holdings) {
      const card = document.createElement("article"); card.className = "compiled-record-card compiled-record-proposal compiled-inventory-card";
      const heading = document.createElement("strong"); heading.textContent = ownerText(row.name, "Unnamed Sphere"); card.appendChild(heading);
      const meta = [row.source, Number.isInteger(row.cl) ? `CL ${row.cl}` : "", Number.isInteger(row.slot) ? `slot ${row.slot}` : "", row.requested ? "requested" : "", friendlyLabel(row.state || "proposed")].filter(Boolean);
      const line = document.createElement("span"); line.className = "compiled-record-meta"; line.textContent = meta.join(" · "); card.appendChild(line);
      const talents = Array.isArray(row.talents) ? row.talents : [];
      if (talents.length) {
        const list = document.createElement("ul"); list.className = "compiled-inventory-talents";
        for (const talent of talents) {
          const item = document.createElement("li");
          item.textContent = `${ownerText(talent.name, "Talent")} — ${talent.source}${Number.isInteger(talent.cl) ? ` (CL ${talent.cl})` : ""}`;
          list.appendChild(item);
        }
        card.appendChild(list);
      } else {
        const empty = document.createElement("span"); empty.className = "compiled-record-meta"; empty.textContent = "No Talents proposed from this Sphere yet."; card.appendChild(empty);
      }
      grid.appendChild(card);
    }
    inventoryGroup.appendChild(grid);
  } else appendCompiledEmpty(inventoryGroup, "The response proposes no Sphere holdings.");
  host.appendChild(inventoryGroup);
  if (requestedMissing.length) {
    const wanted = group(`Requested but not acquired · ${requestedMissing.length}`, true);
    const grid = document.createElement("div"); grid.className = "compiled-record-grid";
    requestedMissing.forEach(row => appendCompiledRecord(grid, {name: row.name, acquisition: "planning priority not acquired"}, {kind: "proposal", showDescription: false}));
    wanted.appendChild(grid); host.appendChild(wanted);
  }
  if (unassigned.length) {
    const orphan = group(`Talents without a held Sphere · ${unassigned.length}`, true);
    const grid = document.createElement("div"); grid.className = "compiled-record-grid";
    unassigned.forEach(row => appendCompiledRecord(grid, {name: row.name, sphere: row.sphere || "owning Sphere unknown", cl: row.cl, acquisition: row.source}, {kind: "proposal", showDescription: false}));
    orphan.appendChild(grid); host.appendChild(orphan);
  }
  if (missing.length) {
    const gaps = group(`Missing mandatory choices · ${missing.length}`, true);
    const grid = document.createElement("div"); grid.className = "compiled-record-grid";
    missing.forEach(row => appendCompiledRecord(grid, {name: row.summary, category: row.step_id ? `next step ${row.step_id}` : row.code, description: row.detail}, {kind: "proposal", showDescription: true}));
    gaps.appendChild(grid); host.appendChild(gaps);
  }
}

function renderCompiledOwnerStages(run = guidedRun) {
  const owner = ownerViewFor(run);
  const sheet = owner.scratch_candidate?.sheet;
  const proposal = owner.proposal && typeof owner.proposal === "object" ? owner.proposal : null;
  const hasSheet = Boolean(sheet && typeof sheet === "object" && Object.keys(sheet).length);
  const hasProposal = Boolean(proposal?.available);
  for (const id of ["ownerCompiledInsightsLabel", "ownerCompiledSpheresLabel"]) {
    const label = document.getElementById(id);
    if (label) label.textContent = hasSheet ? "Compiled result" : hasProposal ? "Proposed acquisitions" : "Awaiting response";
  }
  const insightHeading = document.getElementById("ownerCompiledInsightsHeading");
  if (insightHeading) insightHeading.textContent = hasSheet ? "Insights earned by the character" : hasProposal ? "Proposed Insights and progression" : "Insights and progression";
  const sphereHeading = document.getElementById("ownerCompiledSpheresHeading");
  if (sphereHeading) sphereHeading.textContent = hasSheet ? "Acquired Spheres and associated abilities" : hasProposal ? "Proposed Spheres and Talents" : "Spheres, Talents, and abilities";
  const frozen = !planningIsEditable();
  const insightsPanel = document.getElementById("ownerCompiledInsights");
  const insightBody = document.getElementById("ownerCompiledInsightsBody");
  const insightIntro = document.getElementById("ownerCompiledInsightsIntro");
  const insightSummary = document.getElementById("ownerCompiledInsightSummary");
  const insightPlanning = document.getElementById("ownerInsightHost");
  const spheresPanel = document.getElementById("ownerCompiledSpheres");
  const sphereBody = document.getElementById("ownerCompiledSpheresBody");
  const sphereIntro = document.getElementById("ownerCompiledSpheresIntro");
  const sphereSummary = document.getElementById("ownerCompiledSphereSummary");
  if (!insightsPanel || !insightBody || !spheresPanel || !sphereBody) return;
  insightsPanel.hidden = false;
  spheresPanel.hidden = false;
  if (insightPlanning) insightPlanning.hidden = frozen || hasSheet;
  const editBrief = document.getElementById("ownerInsightsEditBrief");
  if (editBrief) {
    const editAvailability = run?.action_availability?.edit_brief_create_new_request;
    const canEdit = frozen && Boolean(run?.run_id) && editAvailability?.available === true;
    editBrief.hidden = !canEdit;
    editBrief.disabled = !canEdit;
    editBrief.onclick = canEdit ? () => document.getElementById("guidedEditBrief")?.click() : null;
  }
  clearNode(insightBody);
  clearNode(sphereBody);
  const insights = Array.isArray(sheet?.insights) ? sheet.insights : [];
  const progression = Array.isArray(sheet?.progression) ? sheet.progression : [];
  const spheres = Array.isArray(sheet?.spheres) ? sheet.spheres : [];
  const talents = Array.isArray(sheet?.talents) ? sheet.talents : [];
  const automatic = Array.isArray(sheet?.automatic_components) ? sheet.automatic_components : [];
  const equipment = Array.isArray(sheet?.equipment) ? sheet.equipment : [];
  const totalTalentCount = talents.length;
  if (!hasSheet) {
    if (hasProposal) {
      if (insightIntro) insightIntro.textContent = "AI proposal received. These are planning and acquisition intents, not yet compiled or canonical; the Factory will replace them with the source-backed result after a bound clean build.";
      if (sphereIntro) sphereIntro.textContent = "Review the proposed acquisitions by source. Background grants follow their activation rules. Training, free level Talents and new-Sphere bonuses are shown separately. Nothing is granted until compilation succeeds; priorities remain preferences.";
      const proposedInsights = Array.isArray(proposal.insights) ? proposal.insights : [];
      const proposedProgression = Array.isArray(proposal.progression) ? proposal.progression : [];
      const pairRows = proposal.acquisitions?.sphere_free_talent_pairs || [];
      const ordinaryRows = proposal.acquisitions?.level_talents || (proposal.acquisitions?.ordinary_talents || []).map((name, index) => ({name, cl: index + 1}));
      const trainingRows = proposal.acquisitions?.trained_choices || [];
      const bonusRows = proposal.acquisitions?.new_sphere_bonus_talents || [];
      if (insightSummary) insightSummary.textContent = `${proposedInsights.length} Insight priorities · ${proposedProgression.length} progression choices`;
      if (sphereSummary) sphereSummary.textContent = proposalAcquisitionSummary(proposal);
      if (proposedProgression.length) {
        const overview = document.createElement("div"); overview.className = "compiled-progression-overview";
        const heading = document.createElement("h4"); heading.textContent = "Milestone choice per level"; overview.appendChild(heading);
        const note = document.createElement("p"); note.className = "availability-note";
        note.textContent = "Every chosen Path advances at every level, so each Path reaches the target CL. This only shows which Path's milestone choice the AI resolved at each level where more than one Path offers one.";
        overview.appendChild(note);
        const grid = document.createElement("div"); grid.className = "compiled-overview-grid";
        for (const row of proposedProgression) {
          const card = document.createElement("article"); card.className = "compiled-overview-card";
          const title = document.createElement("strong"); title.textContent = `CL ${row.cl}`;
          const summary = document.createElement("span"); summary.textContent = row.path || "Path choice pending";
          card.append(title, summary); grid.appendChild(card);
        }
        overview.appendChild(grid); insightBody.appendChild(overview);
      }
      if (proposedInsights.length) {
        const heading = document.createElement("h4");
        heading.textContent = `AI-proposed Insights · ${proposedInsights.length}`;
        insightBody.appendChild(heading);
        const insightNote = document.createElement("p"); insightNote.className = "availability-note";
        insightNote.textContent = "One advancement milestone applies per level. Where both Paths list one, only the Path named for that level above counts; the compiled result shows what was applied.";
        insightBody.appendChild(insightNote);
        const grid = document.createElement("div"); grid.className = "compiled-record-grid";
        proposedInsights.forEach(row => appendCompiledRecord(grid, ownerInsightDisplayRecord(row), {kind: "insight", showDescription: true}));
        insightBody.appendChild(grid);
      } else appendCompiledEmpty(insightBody, "No Insight priorities were supplied in the parsed proposal.");
      const inventory = proposal.sphere_inventory && typeof proposal.sphere_inventory === "object" ? proposal.sphere_inventory : null;
      if (inventory) renderProposalSphereInventory(sphereBody, inventory);
      const proposedGroups = [
        ["Background", proposal.background || [], true],
        ["Background Sphere", (proposal.background_sphere || []).map(row => ({...row, acquisition: "Background selection · No training slot"})), true],
        ["Background Talent", (proposal.background_talent || []).map(row => ({...row, acquisition: "Background selection · Free"})), true],
        ["Starting free Sphere/Talent grants", pairRows.map(row => ({name: `${row.sphere || "Sphere"} · ${row.talent || "Talent"}`, acquisition: "Starting grant · Free"})), true],
        ["Free level Talents", ordinaryRows.map(row => ({...row, acquisition: "Level talent · Free"}))],
        ["Trained choices", trainingRows.map(row => ({
          ...row,
          category: `Slot ${row.slot ?? "?"} · ${row.choice_type === "new_sphere" ? "New Sphere" : "Talent"} · ${Number.isInteger(row.outcome?.slot_cost) ? `${row.outcome.slot_cost} training ${row.outcome.slot_cost === 1 ? "choice" : "choices"}` : "Training cost missing"}`,
          acquisition: row.source?.route === "recorded_self_training" ? "Self-training" : row.source?.route === "published_legal_teaching_route" ? "Published teaching route" : "Training source pending",
        }))],
        ["Free talents from new Spheres", bonusRows.map(row => ({...row, acquisition: "Bonus for learning this Sphere · Free"}))],
        ["Sphere priorities", proposal.spheres || []],
        ["Talent priorities", proposal.talents || []],
      ];
      for (const [label, rows, initiallyOpen] of proposedGroups) {
        if (!rows.length) continue;
        const details = document.createElement("details"); details.className = "compiled-disclosure-card compiled-sphere-group";
        details.open = Boolean(initiallyOpen);
        const summary = document.createElement("summary"); summary.textContent = `${label} · ${rows.length}`; details.appendChild(summary);
        const grid = document.createElement("div"); grid.className = "compiled-record-grid";
        rows.forEach(row => appendCompiledRecord(grid, row, {kind: "proposal", showDescription: false}));
        details.appendChild(grid); sphereBody.appendChild(details);
      }
      if (!sphereBody.childElementCount) appendCompiledEmpty(sphereBody, "No Sphere or Talent intent was supplied in the parsed proposal.");
      return;
    }
    if (insightIntro) insightIntro.textContent = frozen
      ? "This request is frozen. Load a matching response from the AI route to populate the review surface; planning priorities are closed for this request."
      : "No compiled response is available yet. Continue from the AI route, then return here to review the actual character Insights and CL progression.";
    if (sphereIntro) sphereIntro.textContent = frozen
      ? "This request is frozen. Load a matching response from the AI route to populate the source-backed result."
      : "No compiled response is available yet. This screen will replace the planning catalogue with compact, source-backed Sphere groups after import.";
    if (insightSummary) insightSummary.textContent = "Awaiting response";
    if (sphereSummary) sphereSummary.textContent = "Awaiting response";
    appendCompiledEmpty(insightBody, frozen
      ? "No response has been loaded yet. Return to the AI route to load one; no Insight planning control is available after request freeze."
      : "The compiled Insights view will be populated after a valid response is accepted. The ordinary planning catalogue remains above for pre-request planning.");
    appendCompiledEmpty(sphereBody, frozen
      ? "No response has been loaded yet. Return to the AI route to load one; no acquisition is being implied."
      : "The compiled Sphere view will be populated after a valid response is accepted. No acquisition is being implied yet.");
    return;
  }
  if (insightIntro) insightIntro.textContent = "These are the source-backed Insights in the compiled candidate. Open a CL group for descriptions and ability changes.";
  if (sphereIntro) sphereIntro.textContent = "Each group keeps the Sphere, its associated Talents, and automatic abilities together. Details open on demand.";
  if (insightSummary) insightSummary.textContent = `${insights.length} Insight${insights.length === 1 ? "" : "s"} · ${progression.length} CL group${progression.length === 1 ? "" : "s"}`;
  if (sphereSummary) sphereSummary.textContent = `${spheres.length} Sphere${spheres.length === 1 ? "" : "s"} · ${totalTalentCount} Talent${totalTalentCount === 1 ? "" : "s"}`;

  if (progression.length) {
    const overview = document.createElement("div");
    overview.className = "compiled-progression-overview";
    const heading = document.createElement("h4");
    heading.textContent = "Progression at a glance";
    overview.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "compiled-overview-grid";
    for (const row of progression) {
      const card = document.createElement("article");
      card.className = "compiled-overview-card";
      const title = document.createElement("strong");
      title.textContent = `CL ${row.cl}`;
      const counts = [
        [row.spheres, "Sphere"],
        [row.talents, "Talent"],
        [row.insights, "Insight"],
        [row.automatic_components, "automatic ability"],
        [row.features, "feature"],
      ].filter(([values]) => Array.isArray(values) && values.length).map(([values, label]) => `${values.length} ${label}${values.length === 1 ? "" : "s"}`);
      const summary = document.createElement("span");
      summary.textContent = counts.join(" · ") || (row.status ? friendlyLabel(row.status) : "No source-backed acquisitions listed");
      card.append(title, summary);
      grid.appendChild(card);
    }
    overview.appendChild(grid);
    insightBody.appendChild(overview);
  }
  if (!insights.length) {
    const plannedInsights = Array.isArray(proposal?.acquisitions?.insight_occurrences)
      ? proposal.acquisitions.insight_occurrences
      : [];
    if (plannedInsights.length) {
      const heading = document.createElement("h4");
      heading.textContent = `Planning-only Insight proposals · ${plannedInsights.length}`;
      insightBody.appendChild(heading);
      const note = document.createElement("p");
      note.className = "compiled-planning-note";
      note.textContent = "These AI-proposed Insights were retained for review but were not acquired by this deterministic build because the authoritative progression did not schedule them. No Insight is implied by this list.";
      insightBody.appendChild(note);
      const grid = document.createElement("div");
      grid.className = "compiled-record-grid";
      plannedInsights.forEach(row => appendCompiledRecord(grid, {
        name: row?.insight || "Insight proposal",
        description: row?.description || row?.short_description || row?.summary,
      }, {kind: "proposal", showDescription: true}));
      insightBody.appendChild(grid);
    } else {
      appendCompiledEmpty(insightBody, "No source-backed Insights were acquired in this compiled candidate. The Factory did not substitute the planning catalogue for the character result.");
    }
  } else {
    const heading = document.createElement("h4");
    heading.textContent = "Insights at a glance";
    insightBody.appendChild(heading);
    for (const [cl, rows] of groupedByCL(insights)) {
      const group = document.createElement("section");
      group.className = "compiled-insight-group";
      const groupHeading = document.createElement("h5");
      groupHeading.textContent = cl === "unscheduled" ? `Unscheduled · ${rows.length} Insight${rows.length === 1 ? "" : "s"}` : `CL ${cl} · ${rows.length} Insight${rows.length === 1 ? "" : "s"}`;
      group.appendChild(groupHeading);
      const grid = document.createElement("div");
      grid.className = "compiled-record-grid";
      rows.forEach(row => appendCompiledRecord(grid, row, {kind: "insight"}));
      group.appendChild(grid);
      insightBody.appendChild(group);
    }
  }

  const sphereTalentByName = new Map();
  for (const talent of talents) {
    const key = String(talent?.sphere || "Other compiled Talents");
    if (!sphereTalentByName.has(key)) sphereTalentByName.set(key, []);
    sphereTalentByName.get(key).push(talent);
  }
  const automaticBySphere = new Map();
  for (const component of automatic) {
    const key = String(component?.sphere || "Automatic abilities without a named Sphere");
    if (!automaticBySphere.has(key)) automaticBySphere.set(key, []);
    automaticBySphere.get(key).push(component);
  }
  if (!spheres.length && !talents.length && !automatic.length) {
    appendCompiledEmpty(sphereBody, "No acquired Spheres, Talents, or automatic abilities are projected in this compiled candidate.");
  } else {
    const groups = spheres.map(row => ({name: ownerText(row?.name, "Unnamed Sphere"), sphere: row}));
    for (const name of new Set([...sphereTalentByName.keys(), ...automaticBySphere.keys()])) {
      if (!groups.some(group => group.name === name)) groups.push({name, sphere: null});
    }
    for (const group of groups) {
      const details = document.createElement("details");
      details.className = "compiled-disclosure-card compiled-sphere-group";
      const summary = document.createElement("summary");
      const sphereName = document.createElement("strong");
      sphereName.textContent = group.name;
      const sphereRows = sphereTalentByName.get(group.name) || [];
      const componentRows = automaticBySphere.get(group.name) || [];
      const meta = document.createElement("span");
      meta.className = "compiled-record-meta";
      meta.textContent = [group.sphere?.cl !== undefined && group.sphere?.cl !== null ? `CL ${group.sphere.cl}` : "", `${sphereRows.length} Talent${sphereRows.length === 1 ? "" : "s"}`, `${componentRows.length} automatic ${componentRows.length === 1 ? "ability" : "abilities"}`].filter(Boolean).join(" · ");
      summary.append(sphereName, meta);
      details.appendChild(summary);
      const grid = document.createElement("div");
      grid.className = "compiled-record-grid";
      if (group.sphere) appendCompiledRecord(grid, group.sphere, {kind: "sphere"});
      componentRows.forEach(row => appendCompiledRecord(grid, row, {kind: "ability"}));
      sphereRows.forEach(row => appendCompiledRecord(grid, row, {kind: "talent"}));
      if (!grid.childElementCount) appendCompiledEmpty(grid, "No associated source-backed records are listed for this group.");
      details.appendChild(grid);
      sphereBody.appendChild(details);
    }
  }
  if (equipment.length) {
    const equipmentDetails = document.createElement("details");
    equipmentDetails.className = "compiled-disclosure-card compiled-equipment-group";
    const summary = document.createElement("summary");
    summary.textContent = `Equipment direction · ${equipment.length} item${equipment.length === 1 ? "" : "s"}`;
    equipmentDetails.appendChild(summary);
    const grid = document.createElement("div");
    grid.className = "compiled-record-grid";
    equipment.forEach(row => appendCompiledRecord(grid, row, {kind: "equipment"}));
    equipmentDetails.appendChild(grid);
    sphereBody.appendChild(equipmentDetails);
  }
}

function guidedResponseProcessingDiagnostic(run) {
  return run?.submission_error || run?.validation?.last_submission_error || null;
}

function renderGuidedResponseProcessing(run = guidedRun, phase = "idle") {
  const list = document.getElementById("guidedResponseProcessingList");
  const state = document.getElementById("guidedResponseProcessingState");
  if (!list || !state) return;
  clearNode(list);
  const diagnostic = phase === "submitting" || phase === "selected" ? null : guidedResponseProcessingDiagnostic(run);
  const sourceSelected = guidedCompleteResponseSource.kind !== "none";
  const responseReceived = Boolean(run?.response?.response_sha256 || run?.transport?.uploaded_filename || run?.transport?.uploaded_sha256);
  const parserFailure = diagnostic?.boundary === "JSON_PARSING" || diagnostic?.code === "CG1_PLAN_JSON_INVALID";
  const serverEvidenceVisible = !["selected", "submitting"].includes(phase);
  const stageDefinitions = [
    ["SOURCE_TRANSPORT", "Response uploaded and received", "The source is only selected locally until you choose Build Complete Candidate; server receipt appears after upload."],
    ["JSON_PARSING", "JSON syntax parsed", "The Factory first parses the uploaded bytes as JSON."],
    ["RESPONSE_SHAPE", "Response shape checked", "The parsed value must use the accepted complete-response object shape."],
    ["RESPONSE_SCHEMA", "Response schema checked", "Stable IDs, acquisition intent, and bounded choices must match the frozen response contract."],
    ["REQUEST_BINDING", "Bound to this exact request", "The response request hash must match the sealed request currently on screen."],
    ["SEMANTIC_AUTHORITY", "Selection intent checked", "The Factory checks that the response only asks for choices offered by the frozen authority."],
    ["LEGALITY", "Legality checked", "Paths, Path-owned Subpaths, Method access, Foundation, and other legal boundaries are checked."],
    ["AI_CORRECTION", "AI correction required", "Response-authored mechanical omissions or illegal selections return to the same AI for correction."],
    ["COMPILATION", "Compiled twice for review", "Two isolated server-owned builds create the review candidate and compare their deterministic results."],
  ];
  const order = stageDefinitions.map(([key]) => key);
  const rawDiagnosticStage = diagnostic?.boundary || diagnostic?.stage || diagnostic?.category || "";
  const diagnosticStage = order.includes(rawDiagnosticStage)
    ? rawDiagnosticStage
    : rawDiagnosticStage === "JSON_SCHEMA" ? (parserFailure ? "JSON_PARSING" : "RESPONSE_SCHEMA") : rawDiagnosticStage;
  const failedStage = diagnosticStage && order.includes(diagnosticStage) ? diagnosticStage : diagnostic ? "COMPILATION" : "";
  const failedIndex = failedStage ? order.indexOf(failedStage) : -1;
  const ready = run?.status === "READY_FOR_REVIEW" || run?.status === "CLEAN_AND_FINALIZED";
  for (const [key, label, description] of stageDefinitions) {
    const item = document.createElement("li");
    const index = order.indexOf(key);
    let itemState = "pending";
    let detail = description;
    if (ready || (serverEvidenceVisible && failedIndex < 0 && responseReceived && index < 2)) itemState = "success";
    if (failedIndex >= 0) {
      if (index < failedIndex) itemState = "success";
      else if (index === failedIndex) itemState = "error";
    } else if (phase === "submitting" && index <= 1) itemState = "active";
    if (itemState === "error") {
      if (key === "JSON_PARSING" && parserFailure) detail = "The response could not be parsed as JSON. Choose a corrected response file.";
      else if (key === "RESPONSE_SHAPE" || key === "RESPONSE_SCHEMA") detail = diagnostic?.message || "JSON was parsed, but the response shape was not accepted. This is not a malformed-JSON result.";
      else if (diagnostic?.message) detail = ownerDiagnosticMessage(diagnostic, description);
    } else if (itemState === "active") detail = key === "SOURCE_TRANSPORT" ? "Reading the selected response source…" : "Validating the response through the server-owned pipeline…";
    else if (phase === "selected" && index === 0) detail = "Selected locally. Choose Build Complete Candidate to upload it to the Factory.";
    const marker = document.createElement("span");
    marker.className = `response-processing-marker ${itemState}`;
    marker.textContent = itemState === "success" ? "✓" : itemState === "error" ? "!" : itemState === "active" ? "…" : "·";
    const copy = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = label;
    const text = document.createElement("span"); text.textContent = detail;
    copy.append(title, text);
    item.dataset.state = itemState;
    item.append(marker, copy);
    list.appendChild(item);
  }
  if (ready) state.textContent = "Ready for owner review";
  else if (failedIndex >= 0) state.textContent = parserFailure ? "Parsing failed" : `${friendlyLabel(failedStage)} needs attention`;
  else if (phase === "submitting") state.textContent = "Processing response…";
  else if (sourceSelected) state.textContent = "File selected — ready to import";
  else state.textContent = "Waiting for a source";
  state.dataset.state = failedIndex >= 0 ? "error" : ready ? "success" : phase === "submitting" ? "active" : "pending";
}

function recordGuidedRunDiagnostics(run) {
  const host = document.getElementById("guidedDiagnosticsDetail");
  if (!host || !run) return;
  const diagnostics = run.diagnostics || {};
  host.textContent = pretty({
    run_id: run.run_id,
    project_id: run.project_id,
    request_sha256: run.request?.request_sha256,
    response_sha256: run.response?.response_sha256,
    response_binding: run.owner_descriptive_fields?.response_binding,
    status: run.status,
    blockers: run.blockers || [],
    warnings: run.warnings || [],
    submission_error: run.submission_error || null,
    quality: run.quality || {},
    diagnostics,
  });
}

function resetGuidedCandidateGMAuthoring() {
  guidedCandidateGMAuthoring.generation += 1;
  guidedCandidateGMAuthoring = {
    runId: null,
    summary: null,
    status: null,
    challenge: null,
    loading: false,
    generation: guidedCandidateGMAuthoring.generation,
  };
  renderGuidedCandidateGMAuthoring();
}

function guidedRunAtGmGate(run) {
  if (!run || String(run.status || "").toUpperCase() !== "NEEDS_REVIEW") return false;
  const owner = ownerViewFor(run);
  return (Array.isArray(owner.blockers) ? owner.blockers : []).some(row => row?.control?.type === "gm_candidate_authoring");
}

function renderGuidedCandidateGMAuthoring() {
  const panel = document.getElementById("guidedCandidateGMAuthoring");
  if (!panel) return;
  const state = guidedCandidateGMAuthoring;
  // At the GM authoring gate the panel is the next step, so it stays visible
  // even when its summary fetch failed (for example during a service
  // restart); the Author action itself needs only the run id.
  const atGate = guidedRunAtGmGate(guidedRun) && state.runId === guidedRun?.run_id;
  panel.hidden = !state.summary && !atGate;
  if (!state.summary && !atGate) return;
  const summary = state.summary || {gm_authoring_status: "NOT_AUTHORED"};
  const status = state.status || {};
  const notAuthored = status.status === "CANDIDATE_GM_AUTHORING_NOT_AUTHORED"
    || summary.gm_authoring_status === "NOT_AUTHORED";
  const approved = status.owner_ratified === true
    || status.status === "CANDIDATE_GM_AUTHORING_OWNER_APPROVED";
  const authored = !notAuthored;
  const pill = document.getElementById("guidedCandidateGMAuthoringStatusPill");
  if (pill) {
    pill.textContent = approved ? "Owner approved" : authored ? "Receipt ready" : "Not authored";
    pill.dataset.state = approved ? "success" : authored ? "active" : "pending";
  }
  const message = document.getElementById("guidedCandidateGMAuthoringStatus");
  if (message) {
    message.textContent = state.loading
      ? "Working through the server-owned candidate GM path…"
      : approved
        ? "The candidate GM workspace is owner-approved. Use Retry Local Build to bind it through the normal scratch and live gates."
        : authored
          ? "A source-bound GM receipt is ready for review. Issue a challenge only after inspecting the evidence below."
          : "A staged candidate exists, but no GM receipt has been authored yet.";
    message.classList.toggle("success", approved);
    message.classList.toggle("error", false);
  }
  const author = document.getElementById("guidedCandidateGMAuthor");
  const build = document.getElementById("guidedCandidateGMBuild");
  const issue = document.getElementById("guidedCandidateGMIssueApproval");
  const confirm = document.getElementById("guidedCandidateGMApprovalConfirm");
  const approve = document.getElementById("guidedCandidateGMApprove");
  if (author) author.disabled = state.loading || authored;
  if (build) build.disabled = state.loading || !authored;
  if (issue) issue.disabled = state.loading || !authored || approved;
  if (confirm) {
    confirm.disabled = state.loading || approved;
    if (approved) confirm.checked = false;
  }
  if (approve) approve.disabled = state.loading || approved || !state.challenge || !confirm?.checked;
  const details = document.getElementById("guidedCandidateGMDetails");
  if (details) details.textContent = pretty({summary, status, challenge: state.challenge});
}

async function refreshGuidedCandidateGMAuthoring(run, {force = false} = {}) {
  const runId = run?.run_id;
  if (!runId) {
    resetGuidedCandidateGMAuthoring();
    return;
  }
  if (!force && guidedCandidateGMAuthoring.runId === runId
    && (guidedCandidateGMAuthoring.summary || guidedCandidateGMAuthoring.loading)) {
    renderGuidedCandidateGMAuthoring();
    return;
  }
  const generation = guidedCandidateGMAuthoring.generation + 1;
  guidedCandidateGMAuthoring = {
    runId,
    summary: guidedCandidateGMAuthoring.runId === runId ? guidedCandidateGMAuthoring.summary : null,
    status: guidedCandidateGMAuthoring.runId === runId ? guidedCandidateGMAuthoring.status : null,
    challenge: guidedCandidateGMAuthoring.runId === runId ? guidedCandidateGMAuthoring.challenge : null,
    loading: true,
    generation,
  };
  renderGuidedCandidateGMAuthoring();
  try {
    const summary = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate`);
    if (guidedCandidateGMAuthoring.generation !== generation) return;
    let status;
    try {
      status = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate/author/status`);
    } catch (error) {
      const diagnostic = parseAPIError(error);
      if (diagnostic.code !== "GM_AUTHORING_RECEIPT_NOT_FOUND") throw error;
      status = {
        status: "CANDIDATE_GM_AUTHORING_NOT_AUTHORED",
        run_id: runId,
        owner_ratified: false,
      };
    }
    if (guidedCandidateGMAuthoring.generation !== generation) return;
    guidedCandidateGMAuthoring.summary = summary;
    guidedCandidateGMAuthoring.status = status;
  } catch (error) {
    if (guidedCandidateGMAuthoring.generation !== generation) return;
    // A run without a captured candidate has no panel to show. Other errors
    // stay in the normal run diagnostics and do not invent a review surface.
    guidedCandidateGMAuthoring.summary = null;
    guidedCandidateGMAuthoring.status = null;
    guidedCandidateGMAuthoring.challenge = null;
  } finally {
    if (guidedCandidateGMAuthoring.generation === generation) {
      guidedCandidateGMAuthoring.loading = false;
      renderGuidedCandidateGMAuthoring();
    }
  }
}

function resetGuidedBuilder() {
  guidedRun = null;
  resetGuidedCandidateGMAuthoring();
  guidedResponseSubmissionAction = "manual";
  methodCompatibilityRequestSerial += 1;
  methodCompatibility = {key: methodCompatibilityKey([]), state: "not_checked", result: null};
  resetGuidedResponseSource();
  const response = document.getElementById("guidedCompleteResponseText");
  const fileStatus = document.getElementById("guidedCompleteReplyStatus");
  const downloadStatus = document.getElementById("guidedDownloadCompleteRequestStatus");
  const progress = document.getElementById("guidedBuildProgress");
  const candidate = document.getElementById("guidedCandidateSummary");
  const review = document.getElementById("guidedReviewDetail");
  const finalSummary = document.getElementById("guidedFinalSummary");
  if (response) response.value = "";
  if (fileStatus) fileStatus.textContent = "";
  if (downloadStatus) { downloadStatus.textContent = ""; downloadStatus.classList.remove("error", "success"); }
  if (progress) progress.textContent = "No complete-character build started.";
  if (candidate) clearNode(candidate);
  if (review) review.textContent = "";
  if (finalSummary) clearNode(finalSummary);
  const manual = document.getElementById("guidedManualTransfer");
  if (manual) manual.hidden = true;
  const fallbackWarning = document.getElementById("guidedProviderFallbackWarning");
  if (fallbackWarning) {
    fallbackWarning.hidden = true;
    fallbackWarning.textContent = "";
  }
  const download = document.getElementById("guidedDownloadCompleteRequest");
  const correctionDownload = document.getElementById("guidedDownloadAICorrection");
  const submit = document.getElementById("guidedSubmitCompleteResponse");
  if (download) download.disabled = true;
  if (correctionDownload) { correctionDownload.hidden = true; correctionDownload.disabled = true; }
  if (submit) submit.disabled = true;
   const consent = document.getElementById("guidedAutoFinalizeConsent");
   if (consent) consent.checked = false;
  const capability = document.getElementById("guidedAutoFinalizeCapability");
  if (capability) capability.checked = false;
  const localConsent = document.getElementById("guidedLocalAutoFinalizeConsent");
  if (localConsent) localConsent.checked = false;
  const localBuildMode = document.querySelector('input[name="guidedLocalBuildMode"][value="LOCAL_AUTO"]');
  if (localBuildMode) localBuildMode.checked = true;
  guidedFinalizeInFlight = false;
  manualLineageResetState();
  setGuidedRoute("LOCAL_AI");
  updateGuidedModeUI();
  setGuidedStatus("");
   setGuidedStep(1);
   renderOwnerMethodCompatibility();
}

async function startNewCharacter(mode = "quick") {
  guidedNavigationGeneration += 1;
  try {
    const discarded = await discardGuidedTemporaryProject();
    if (!discarded) {
      renderGuidedStartupRecovery();
      return;
    }
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The temporary character could not be discarded safely."), true);
    renderGuidedStartupRecovery();
    return;
  }
  hideGuidedStartupRecovery();
  selectedProject = null;
  resetFinalCharacterReviewState();
  guidedProjectId = null;
  guidedAutogenSeed = null;
  guidedProjectLifecycle = null;
  renderGuidedPersistence();
  document.getElementById("guidedCreate").reset();
  document.getElementById("guidedLevel").value = "15";
  document.getElementById("guidedPower").value = "rival/boss";
  resetCharacterSheet();
  resetGuidedBuilder();
  setCreationMode(mode);
  showScreen("builder");
  setGuidedStatus(mode === "detailed"
    ? "Full character sheet opened. Leave anything you do not care about on Auto."
    : "Ready to start a new character. Saved Drafts and completed characters remain under Character Sheets.");
}

function guidedPromptForChatGPT(prompt) {
  return [
    "FACTORY RESPONSE BINDING",
    "Use this exact value for prompt_sha256 in your JSON response:",
    prompt.prompt_sha256,
    "The fingerprint identifies the original PROMPT_TEXT below; do not recalculate it from this wrapper.",
    "",
    "PROMPT_TEXT",
    prompt.prompt_text
  ].join("\n");
}

function plainAPIError(error, fallback) {
  const diagnostic = parseAPIError(error);
  recordGuidedDiagnostic(error);
  return ownerDiagnosticMessage(diagnostic, fallback);
}

function setScreenState(elementId, state, message, retry = null, error = null) {
  const host = document.getElementById(elementId);
  if (!host) return;
  clearNode(host);
  host.dataset.state = state;
  const text = document.createElement("span");
  text.textContent = message;
  host.appendChild(text);
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Retry";
    button.addEventListener("click", retry);
    host.appendChild(button);
  }
  if (error) {
    const details = document.createElement("details");
    const summary = document.createElement("summary"); summary.textContent = "Advanced details";
    const pre = document.createElement("pre"); pre.textContent = error.message || String(error);
    details.append(summary, pre); host.appendChild(details);
  }
}

function categoryFor(slotId) {
  return characterBuilderOptions?.categories?.find(category => category.slot_id === slotId) || null;
}

function categoryMaximum(category) {
  return Number.isInteger(category?.max) ? Number(category.max) : null;
}

function categoryAvailabilityText(category) {
  if (!category || category.status !== "offered") return category?.blocked_message || "No verified choices are installed for this section yet.";
  const maximum = categoryMaximum(category);
  return maximum === null
    ? `${category.choices.length} verified choices available; choose any number of valid priorities.`
    : `${category.choices.length} verified choices available; lock up to ${maximum}.`;
}

function planningIsEditable() {
  return !guidedProjectId;
}

function guardPlanningMutation() {
  if (planningIsEditable()) return true;
  restoreFrozenPlanningValues();
  setGuidedStatus(PLANNING_FREEZE_MESSAGE, true);
  renderPlanningFreeze();
  return false;
}

function managePlanningDisabled(node, frozen) {
  if (!node) return;
  if (frozen) {
    if (!Object.prototype.hasOwnProperty.call(node.dataset, "planningPriorDisabled")) {
      node.dataset.planningPriorDisabled = node.disabled ? "true" : "false";
      node.dataset.planningFrozenValue = node.value ?? "";
      node.dataset.planningFrozenChecked = node.checked ? "true" : "false";
    }
    node.disabled = true;
    node.setAttribute("aria-disabled", "true");
  } else if (Object.prototype.hasOwnProperty.call(node.dataset, "planningPriorDisabled")) {
    node.disabled = node.dataset.planningPriorDisabled === "true";
    delete node.dataset.planningPriorDisabled;
    node.removeAttribute("aria-disabled");
  }
}

function restoreFrozenPlanningValues() {
  document.querySelectorAll("[data-planning-prior-disabled]").forEach(node => {
    if (Object.prototype.hasOwnProperty.call(node.dataset, "planningFrozenValue")) node.value = node.dataset.planningFrozenValue;
    if (Object.prototype.hasOwnProperty.call(node.dataset, "planningFrozenChecked")) node.checked = node.dataset.planningFrozenChecked === "true";
  });
}

function renderOwnerLockSummary() {
  const pathCount = selectedSet("path_choice").size;
  const insightCount = selectedSet("insight_priorities").size;
  const sphereCount = selectedSet("sphere_priorities").size;
  const values = {
    ownerDetailPathSummary: `${pathCount} of 3 locked`,
    ownerDetailInsightSummary: `${insightCount} priorit${insightCount === 1 ? "y" : "ies"}`,
    ownerDetailSphereSummary: `${sphereCount} priorit${sphereCount === 1 ? "y" : "ies"}`,
    ownerDetailFreezeSummary: planningIsEditable() ? "Editable before project creation" : "Frozen in server request",
  };
  for (const [id, text] of Object.entries(values)) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  }
  const mode = document.getElementById("ownerDetailModeSummary");
  if (mode) mode.textContent = creationMode === "detailed" ? "Manual details" : "Auto choices";
}

function renderPlanningFreeze() {
  const frozen = !planningIsEditable();
  const controls = [
    ...document.querySelectorAll(
      "#ownerDetailHost [data-ability], #ownerCultivationHost [data-sheet-slot], #ownerCultivationHost [data-ability], #ownerCultivationHost input[name='sheetMethodMode'], #ownerCultivationHost #sheetMethodRouteChoice, #ownerCultivationHost #sheetMethodLearningNote, #ownerInsightHost [data-multi-slot], #ownerSphereHost [data-multi-slot], #sheetPaths input, #sheetBackground, #sheetBackgroundSphere, #sheetBackgroundTalent, #sheetOriginInsight, #sheetFoundation, #sheetSubpath, #sheetMethod, #sheetMethodRouteChoice, #sheetMethodLearningNote, [data-add-slot]"
    ),
  ];
  controls.forEach(node => managePlanningDisabled(node, frozen));
  document.querySelectorAll("[data-planning-mutator]").forEach(button => managePlanningDisabled(button, frozen));
  document.querySelectorAll("[data-planning-freeze-note], #planningFreezeReason").forEach(note => {
    note.hidden = !frozen;
    note.textContent = PLANNING_FREEZE_MESSAGE;
  });
  for (const id of ["guidedName", "guidedConcept", "guidedLevel", "guidedPower", "guidedSource", "guidedBriefContinue", "guidedBuildButton"]) {
    managePlanningDisabled(document.getElementById(id), frozen);
  }
  document.querySelectorAll("#builderModeQuick, #builderModeDetailed").forEach(button => managePlanningDisabled(button, frozen));
  renderOwnerLockSummary();
}

function renderGuidedPersistence() {
  const panel = document.getElementById("guidedPersistencePanel");
  const label = document.getElementById("guidedPersistenceLabel");
  const explanation = document.getElementById("guidedPersistenceExplanation");
  const save = document.getElementById("guidedSaveDraft");
  if (!guidedProjectId || !guidedProjectLifecycle) {
    panel.hidden = true;
    renderPlanningFreeze();
    return;
  }
  panel.hidden = false;
  label.textContent = guidedProjectLifecycle.display_label || "Saved / existing";
  explanation.textContent = guidedProjectLifecycle.plain_explanation || "This character is retained.";
  save.hidden = !guidedProjectLifecycle.is_temporary;
  save.disabled = !guidedProjectLifecycle.is_temporary;
  renderPlanningFreeze();
}

async function discardGuidedTemporaryProject(reason = "owner_abandoned_or_started_over") {
  if (!guidedProjectId || !guidedProjectLifecycle?.is_temporary) return true;
  const projectId = guidedProjectId;
  // The page's copy goes stale when a build finalizes on its own (auto-finalize, Quick Build): a finished character is
  // not temporary any more, and the server refuses to discard it (owner 2026-09-27, "Start another character" did
  // nothing). Ask the server first; only a character still temporary there is discarded.
  try {
    guidedProjectLifecycle = await api(`/api/character-builder/projects/${encodeURIComponent(projectId)}/lifecycle`);
    renderGuidedPersistence();
  } catch (error) { /* keep the page's copy; the discard below reports a real problem */ }
  if (!guidedProjectLifecycle?.is_temporary) return true;
  try {
    const recovery = await api(`/api/projects/${encodeURIComponent(projectId)}/character-creation/recovery`);
    if (recovery.active_run) {
      const run = recovery.active_run;
      const confirmed = window.confirm(`This character has an incomplete build (${run.status}). Cancel run ${run.run_id} and discard the temporary character? Choose Cancel to return to the active build.`);
      if (!confirmed) return false;
      await api(`/api/character-creation/runs/${encodeURIComponent(run.run_id)}/cancel`, {method: "POST", body: "{}"});
    }
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The active build could not be checked. It was kept safely."), true);
    return false;
  }
  await api(`/api/character-builder/projects/${encodeURIComponent(projectId)}/temporary`, {method: "DELETE"});
  if (selectedProject === projectId) selectedProject = null;
  guidedProjectId = null;
  guidedAutogenSeed = null;
  guidedProjectLifecycle = null;
  guidedRecovery = null;
  renderGuidedPersistence();
  return true;
}

function setCreationMode(mode) {
  creationMode = mode === "detailed" ? "detailed" : "quick";
  const detailed = creationMode === "detailed";
  const sheetPanel = document.getElementById("characterSheetPanel");
  const detailDisclosure = document.getElementById("ownerCustomizationDetails");
  if (sheetPanel) sheetPanel.hidden = productionOwnerShellReady ? true : !detailed;
  if (detailDisclosure && detailed) detailDisclosure.open = true;
  for (const [id, active] of [["builderModeQuick", !detailed], ["builderModeDetailed", detailed]]) {
    const button = document.getElementById(id);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
  if (detailed) updatePointBuySummary();
  renderOwnerLockSummary();
  renderPlanningFreeze();
  evaluateGuidedReadiness();
}

function optionLabel(choice) {
  const minimum = Number.isInteger(choice.minimum_cl) ? ` — Available at CL ${choice.minimum_cl}` : "";
  const access = choice.access?.canonical_category || choice.access?.printed_category || choice.access_category || "";
  const accessLabel = access ? ` — ${access}` : "";
  const insightType = choice.insight_authority?.authority_type ? ` — ${choice.insight_authority.authority_type}` : "";
  return `${choice.name}${insightType}${minimum}${accessLabel}`;
}

function populateSheetSelect(select, category, promptText = "Auto — let the Factory choose") {
  const priorValue = select.value;
  const choicesOverride = arguments.length > 3 ? arguments[3] : null;
  clearNode(select);
  const automatic = document.createElement("option");
  automatic.value = "";
  automatic.textContent = promptText;
  select.appendChild(automatic);
  if (!category || category.status !== "offered") {
    select.disabled = true;
    automatic.textContent = "Auto — authority not installed yet";
    return;
  }
  select.disabled = false;
   const safeChoices = sphereTalentLogic.uniqueChoices(choicesOverride || category.choices);
   const appendChoice = choice => {
     const option = document.createElement("option");
    option.value = choice.choice_id;
    const preferenceBlocked = choice.planning_priority_available === false;
    const initialMethodBlocked = choice.initial_creation_selectable === false;
    option.textContent = preferenceBlocked
      ? `${choice.name} — unavailable: ${choice.unavailable_reason || "not creator-ready"}`
      : initialMethodBlocked
        ? `${choice.name} — unavailable: ${choice.initial_creation_unavailable_reason || "requires post-creation acquisition authority"}`
        : optionLabel(choice);
    option.title = choice.unavailable_reason || choice.initial_creation_unavailable_reason || choice.description || choice.name;
     option.disabled = preferenceBlocked || initialMethodBlocked;
     select.appendChild(option);
   };
   if (category.grouped_projection === "typed_insight_metadata") {
      for (const group of category.groups || []) {
       const choices = safeChoices.filter(choice => choice.insight_group === group.id);
       if (!choices.length) continue;
       const optgroup = document.createElement("optgroup");
       optgroup.label = group.label;
       choices.forEach(choice => {
         const option = document.createElement("option");
         option.value = choice.choice_id;
          const preferenceBlocked = choice.planning_priority_available === false;
          const initialMethodBlocked = choice.initial_creation_selectable === false;
          option.textContent = preferenceBlocked
            ? `${choice.name} — unavailable: ${choice.unavailable_reason || "not creator-ready"}`
            : initialMethodBlocked
              ? `${choice.name} — unavailable: ${choice.initial_creation_unavailable_reason || "requires post-creation acquisition authority"}`
              : optionLabel(choice);
          option.title = choice.unavailable_reason || choice.initial_creation_unavailable_reason || choice.description || choice.name;
          option.disabled = preferenceBlocked || initialMethodBlocked;
         optgroup.appendChild(option);
       });
       select.appendChild(optgroup);
     }
     const groupedIds = new Set((category.groups || []).map(group => group.id));
     safeChoices.filter(choice => !groupedIds.has(choice.insight_group)).forEach(appendChoice);
   } else safeChoices.forEach(appendChoice);
   if (Array.from(select.options).some(option => option.value === priorValue)) select.value = priorValue;
}

function methodChoiceFor(value = null) {
  const methodId = value === null ? document.getElementById("sheetMethod")?.value : value;
  return categoryFor("method_choice")?.choices?.find(choice => choice.choice_id === methodId) || null;
}

function methodPlanningMode() {
  return document.querySelector('input[name="sheetMethodMode"]:checked')?.value || "AUTO";
}

function selectedPathIds() {
  return Array.from(selectedSet("path_choice"));
}

function methodCompatibilityKey(pathIds = selectedPathIds()) {
  return Array.from(new Set(pathIds)).sort().join("|");
}

function renderOwnerMethodCompatibility() {
  const host = document.getElementById("ownerCompatibleMethods");
  const status = document.getElementById("ownerMethodCompatibilityStatus");
  const count = document.getElementById("ownerPathRequirementSummary");
  if (count) count.textContent = `${selectedPathIds().length} of 3 requirements selected`;
  if (!host || !status) return;
  clearNode(host);
  const state = methodCompatibility.state;
  if (state === "checking") {
    status.textContent = "Checking compatibility…";
    status.dataset.state = "checking";
    return;
  }
  if (state === "stale") {
    status.textContent = "Path requirements changed. Check compatibility again.";
    status.dataset.state = "stale";
    return;
  }
  if (state === "unavailable") {
    status.textContent = "Compatibility could not be checked. No inferred Methods are shown.";
    status.dataset.state = "unavailable";
    return;
  }
  const pendingSummary = document.getElementById("ownerCompatibleMethodsSummary");
  if (pendingSummary) pendingSummary.textContent = state === "checking" ? "Compatible Methods — checking…" : state === "stale" ? "Compatible Methods — result is stale" : "Compatible Methods — not checked yet";
  if (state !== "accepted" || !methodCompatibility.result) {
    status.textContent = "Compatibility has not been checked.";
    status.dataset.state = "not_checked";
    return;
  }
  const methods = methodCompatibility.result.compatible_methods || [];
  status.textContent = methods.length
    ? `${methods.length} validator-confirmed Method${methods.length === 1 ? "" : "s"} available.`
    : "No confirmed Method satisfies the current Path requirement. Revise the requirement or leave it open for the legal Method route.";
  status.dataset.state = methods.length ? "accepted" : "empty";
  const resultDetails = document.getElementById("ownerCompatibleMethodsDetails");
  const resultSummary = document.getElementById("ownerCompatibleMethodsSummary");
  if (resultSummary) resultSummary.textContent = methods.length ? `Compatible Methods — ${methods.length} confirmed (show or hide)` : "Compatible Methods — none confirmed";
  if (resultDetails) resultDetails.dataset.resultKey = methodCompatibilityKey();
   for (const method of methods) {
     const card = document.createElement("article");
     card.className = "owner-compatible-method";
     const name = document.createElement("strong"); name.textContent = method.name;
     const paths = document.createElement("small"); paths.textContent = `Confirmed for ${method.supported_paths.join(", ") || "the legal Method route"}.`;
     const access = document.createElement("div");
     access.className = "method-compatibility-access";
     const direct = document.createElement("small");
     direct.textContent = method.direct_access
       ? "Direct access: available during initial creation."
       : "Access required: compatibility does not grant access.";
     const tier = document.createElement("small");
     tier.textContent = `Access tier: ${method.access_tier || "not published"}.`;
     const accessText = document.createElement("small");
     accessText.textContent = method.access_text || method.owner_description || "No additional access text was published.";
     access.append(direct, tier, accessText);
     const routes = document.createElement("small");
     const routeOptions = method.owner_route_options || [];
     routes.textContent = routeOptions.length
       ? `Owner route options: ${routeOptions.map(row => row.label || row.typed_route || row.choice_id).join(", ")}.`
       : "Owner route options: none published.";
     const exact = document.createElement("small");
     const exactConfigurable = method.exact_lock_configurable ?? method.exact_selection_available ?? false;
     exact.textContent = `Exact lock: ${exactConfigurable ? "configurable" : "not configurable"}.`;
      const choose = document.createElement("button");
      choose.type = "button"; choose.className = "secondary-action"; choose.textContent = "Use this Method";
      choose.disabled = !planningIsEditable() || !exactConfigurable;
      choose.title = !planningIsEditable()
        ? PLANNING_FREEZE_MESSAGE
        : exactConfigurable
          ? method.access_required
            ? "Open the exact Method route controls; a route or evidence is still required before compilation."
            : "Lock this confirmed Method into the new project."
          : "This compatible Method has no exact owner route that can be configured, so it remains unavailable.";
      choose.addEventListener("click", () => {
        if (!guardPlanningMutation()) return;
       const select = document.getElementById("sheetMethod");
      const mode = document.querySelector('input[name="sheetMethodMode"][value="EXACT"]');
      if (mode) mode.checked = true;
       if (select) { select.disabled = false; select.value = method.method_id; }
       populateMethodPlanning();
       evaluateGuidedReadiness();
       if (method.access_required) document.getElementById("sheetMethodAccessPlan")?.scrollIntoView({behavior: "smooth", block: "nearest"});
     });
     card.append(name, paths, access, routes, exact, choose);
     host.appendChild(card);
   }
}

async function requestMethodCompatibility() {
  const selected = selectedPathIds();
  const key = methodCompatibilityKey(selected);
  const serial = ++methodCompatibilityRequestSerial;
  methodCompatibility = {key, state: "checking", result: null};
  renderOwnerMethodCompatibility();
  populateMethodPlanning();
  try {
    const result = await api("/api/character-builder/method-compatibility", {
      method: "POST",
      body: JSON.stringify({selected_path_ids: selected}),
    });
    if (serial !== methodCompatibilityRequestSerial || key !== methodCompatibilityKey()) return result;
    methodCompatibility = {key, state: "accepted", result};
    renderOwnerMethodCompatibility();
    populateMethodPlanning();
    return result;
  } catch (error) {
    if (serial !== methodCompatibilityRequestSerial || key !== methodCompatibilityKey()) return null;
    methodCompatibility = {key, state: "unavailable", result: null};
    renderOwnerMethodCompatibility();
    populateMethodPlanning();
    setGuidedStatus(ownerDiagnosticMessage(parseAPIError(error), "Method compatibility could not be checked."), true);
    return null;
  }
}

function renderPathChoices() {
  const host = document.getElementById("sheetPaths");
  const category = categoryFor("path_choice");
  if (!host || !category) return;
  clearNode(host);
  const selected = selectedSet("path_choice");
   const maximum = Number(category.max ?? 3);
  const lockSummary = document.createElement("small");
  lockSummary.className = "path-lock-summary";
  lockSummary.textContent = `${selected.size} of ${maximum} Path locks selected`;
  host.appendChild(lockSummary);
  for (const choice of category.choices || []) {
     const label = document.createElement("label");
     label.className = "owner-path-choice-card";
    const input = document.createElement("input");
    input.type = "checkbox";
     input.value = choice.choice_id;
     input.checked = selected.has(choice.choice_id);
     label.classList.toggle("selected", input.checked);
     input.disabled = !planningIsEditable() || (!input.checked && selected.size >= maximum);
     input.setAttribute("aria-label", `Lock ${choice.name} as an advancing Path`);
     input.onchange = () => {
       if (!guardPlanningMutation()) {
         input.checked = selected.has(choice.choice_id);
         label.classList.toggle("selected", input.checked);
         return;
       }
       if (input.checked) selected.add(choice.choice_id);
       else selected.delete(choice.choice_id);
       // A Subpath is owned by exactly one selected Path.  Prune this
       // dependent selection synchronously so the owner-facing count cannot
       // briefly describe an orphaned binding while the compatibility check
       // is in flight.
       pruneOrphanedSubpathSelections();
       label.classList.toggle("selected", input.checked);
       const currentMethod = methodChoiceFor();
       if (currentMethod) {
         document.getElementById("sheetMethod").value = "";
         clearMethodAccessInputs();
         setGuidedStatus("Path requirements changed, so the previous Method result is stale and was cleared.");
       }
       void refreshMethodPathChoices({announce: true, preserve: true});
      evaluateGuidedReadiness();
    };
     const copy = document.createElement("span");
     const name = document.createElement("strong"); name.textContent = choice.name;
     const state = document.createElement("small"); state.textContent = input.checked ? "Advancing · attainment pending" : "Dormant · starts at level 0";
     copy.append(name, state);
     label.append(input, copy);
     host.appendChild(label);
   }
   renderOwnerLockSummary();
 }

function pruneOrphanedSubpathSelections() {
  const selected = selectedSet("subpath_choice");
  const category = categoryFor("subpath_choice");
  const byId = new Map((category?.choices || []).map(choice => [choice.choice_id, choice]));
  const pathIds = new Set(selectedPathIds());
  const pathIndex = characterBuilderOptions?.path_subpath_index || {};
  const allowed = new Set(Array.from(pathIds).flatMap(pathId => pathIndex[pathId] || []));
  for (const choiceId of Array.from(selected)) {
    const ownerId = byId.get(choiceId)?.owning_path_id;
    if (!pathIds.has(ownerId) || !allowed.has(choiceId)) selected.delete(choiceId);
  }
}

function setMethodPlanningMode(value) {
  const normalized = value === "HARD_LOCK" ? "EXACT" : (value || "AUTO");
  const option = document.querySelector(`input[name="sheetMethodMode"][value="${normalized}"]`);
  if (option) option.checked = true;
}

function populateMethodPlanning() {
  const select = document.getElementById("sheetMethod");
  const category = categoryFor("method_choice");
  if (!select || !category) return;
  // Legacy contract wording retained for source compatibility; the active
  // owner path uses the server-confirmed compatibility result below rather
  // than inferring from Method prose or browser-local relations:
  // requiredPaths.every(pathId => (choice.related_choice_ids || []).includes(pathId))
  const prior = select.value;
  const mode = methodPlanningMode();
  clearNode(select);
   const prompt = document.createElement("option");
   prompt.value = "";
   prompt.textContent = "Choose a confirmed Method";
   select.appendChild(prompt);
   const requiredPaths = selectedPathIds();
   const compatibilityReady = methodCompatibility.state === "accepted"
     && methodCompatibility.key === methodCompatibilityKey(requiredPaths);
   const confirmedIds = new Set((methodCompatibility.result?.compatible_methods || []).map(row => row.method_id));
   const compatibleChoices = compatibilityReady
     ? (category.choices || []).filter(choice => confirmedIds.has(choice.choice_id))
     : [];
  for (const choice of compatibleChoices) {
    const plan = choice.method_planning || {};
    const option = document.createElement("option");
    option.value = choice.choice_id;
    option.textContent = choice.name;
    option.disabled = mode === "EXACT" && !plan.exact_selection_available;
    option.title = choice.description || "";
    select.appendChild(option);
  }
  if (Array.from(select.options).some(option => option.value === prior && !option.disabled)) select.value = prior;
  const choiceField = document.getElementById("sheetMethodChoiceField");
   if (choiceField) choiceField.hidden = mode === "AUTO";
    select.disabled = !planningIsEditable() || mode === "AUTO" || !compatibilityReady;
  const plan = methodChoiceFor()?.method_planning;
  const status = document.getElementById("sheetMethodAuthority");
  if (status) status.textContent = mode === "AUTO"
    ? "The Factory will choose a fitting Method."
     : !compatibilityReady ? "Check compatibility before choosing a Method."
       : !plan ? (requiredPaths.length && !compatibleChoices.length ? "No confirmed Method supports every selected Path." : "Choose a confirmed Method.")
      : mode === "PREFERENCE"
        ? "The Factory will treat this as a preference and may choose differently if the character needs it."
        : plan.exact_selection_available
          ? "The Factory will use this Method and keep its rules consistent."
          : (plan.owner_unavailable_reason || "This Method cannot be used during initial character creation.");
   populateMethodAccessPlan();
   renderPlanningFreeze();
 }

function populateMethodAccessPlan() {
  const panel = document.getElementById("sheetMethodAccessPlan");
  const status = document.getElementById("sheetMethodAccessStatus");
  const route = document.getElementById("sheetMethodRouteChoice");
  const choice = methodChoiceFor();
  const plan = choice?.method_planning || {};
  const needsOwnerRoute = methodPlanningMode() === "EXACT" && choice && !plan.direct_initial_acquisition_available;
  if (panel) panel.hidden = !needsOwnerRoute;
  if (status) {
    status.hidden = methodPlanningMode() !== "EXACT" || !choice;
    status.textContent = !choice ? "" : plan.direct_initial_acquisition_available
      ? "This Method is ready to use."
      : (plan.owner_route_options || []).length
        ? "Choose the answer that fits this character. The Factory handles the rules behind it."
        : (plan.owner_unavailable_reason || "This Method cannot be used during initial character creation.");
  }
  if (!route) return;
  const prior = route.value;
  clearNode(route);
  const prompt = document.createElement("option"); prompt.value = ""; prompt.textContent = "Choose one"; route.appendChild(prompt);
  for (const value of plan.owner_route_options || []) {
    const option = document.createElement("option"); option.value = value.choice_id; option.textContent = value.label; option.title = value.description || ""; route.appendChild(option);
  }
  if (Array.from(route.options).some(option => option.value === prior)) route.value = prior;
  updateMethodLearningNoteRequirement();
}

function updateMethodLearningNoteRequirement() {
  const routeId = document.getElementById("sheetMethodRouteChoice")?.value || "";
  const option = methodChoiceFor()?.method_planning?.owner_route_options?.find(row => row.choice_id === routeId);
  const required = option?.requires_explanation === true;
  const note = document.getElementById("sheetMethodLearningNote");
  const label = document.getElementById("sheetMethodLearningNoteLabel");
  if (note) note.required = required;
  if (label) label.textContent = required ? "Explanation (required for Custom)" : "Optional note";
}

function methodRouteChoiceForSubmission() {
  if (methodPlanningMode() !== "EXACT") return null;
  const choice = methodChoiceFor();
  if (!choice || choice.method_planning?.direct_initial_acquisition_available) return null;
  return document.getElementById("sheetMethodRouteChoice")?.value || null;
}

function clearMethodAccessInputs() {
  const route = document.getElementById("sheetMethodRouteChoice");
  const note = document.getElementById("sheetMethodLearningNote");
  if (route) route.value = "";
  if (note) note.value = "";
}

const INSIGHT_GROUP_LABELS = {
  general_cultivation_insights: "General",
  path_insights: "Path",
  sphere_insights: "Sphere",
  technique_forging_insights: "Technique-Forging",
  metatechnique_insights: "Metatechnique",
  companion_insights: "Companion",
  narrative_secret_insights: "Narrative / Secret",
};

function ordinaryInsightChoices() {
  return (categoryFor("insight_priorities")?.choices || []).filter(choice =>
    choice.content_type !== "origin_insight" && choice.insight_authority?.authority_type !== "Background-Origin"
  );
}

function insightGroupId(choice) {
  return choice?.insight_group || "unresolved_insights";
}

function insightGroupLabel(choice) {
  return choice?.insight_group_label?.replace(/ Insights?$/i, "") || INSIGHT_GROUP_LABELS[insightGroupId(choice)] || "Other";
}

function insightPathGroup(choice) {
  const hierarchy = choice?.insight_hierarchy?.length
    ? choice.insight_hierarchy
    : choice?.insight_authority?.hierarchy_path || [];
  return hierarchy.length > 1 ? hierarchy[hierarchy.length - 1] : choice?.insight_authority?.insight_group?.leaf_label || "";
}

function insightSphereFacetIds(choice) {
  const direct = choice?.insight_facets?.length ? choice.insight_facets : choice?.insight_authority?.owning_canonical_sphere_ids || [];
  const nested = choice?.insight_authority?.insight_group?.facet_ids || [];
  return Array.from(new Set([...direct, ...nested].map(value => String(value).replace(/^sphere:/, "")).filter(Boolean)));
}

function insightChoiceMatches(choice, filters) {
  if (filters.group && insightGroupId(choice) !== filters.group) return false;
  if (filters.path && insightPathGroup(choice) !== filters.path) return false;
  if (filters.sphere && !insightSphereFacetIds(choice).includes(filters.sphere)) return false;
  if (filters.query && !`${choice.name} ${choice.description || ""}`.toLowerCase().includes(filters.query)) return false;
  return true;
}

function insightDisabledReason(choice) {
  if (choice?.planning_priority_available === false) return choice.unavailable_reason || "This Insight is not available as an owner planning priority.";
  if (choice?.initial_creation_selectable === false) return choice.initial_creation_unavailable_reason || "This Insight is not selectable during initial creation.";
  return "";
}

function insightBrowseSubgroup(choice, group) {
  if (group === "path_insights") return insightPathGroup(choice) || "Path group pending source classification";
  if (group === "sphere_insights") {
    const sphereMap = new Map((categoryFor("sphere_priorities")?.choices || []).map(row => [row.choice_id, row.name || row.canonical_name]));
    const names = insightSphereFacetIds(choice).map(id => sphereMap.get(id) || id).filter(Boolean).sort((left, right) => left.localeCompare(right));
    return names[0] || "Sphere group pending source classification";
  }
  return "";
}

function appendInsightBrowseCard(host, choice, selected) {
  const card = document.createElement("article");
  card.className = `insight-browse-card${selected ? " selected" : ""}`;
  card.dataset.insightId = choice.choice_id;
  const heading = document.createElement("div"); heading.className = "insight-browse-heading";
  const title = document.createElement("h6"); title.textContent = choice.name;
  const badge = document.createElement("span"); badge.className = "insight-category-badge"; badge.textContent = insightGroupLabel(choice);
  heading.append(title, badge);
  const description = document.createElement("p"); description.textContent = choice.short_description || choice.description || "No short player-facing purpose is present in the authenticated source.";
  const scope = document.createElement("small");
  const subgroup = insightBrowseSubgroup(choice, insightGroupId(choice));
  scope.textContent = subgroup ? `${insightGroupLabel(choice)} · ${subgroup}` : insightGroupLabel(choice);
  const disabledReason = insightDisabledReason(choice);
  const action = document.createElement("button"); action.type = "button"; action.className = "insight-priority-toggle";
  action.dataset.planningMutator = "true";
  action.disabled = Boolean(disabledReason) || !planningIsEditable();
  action.textContent = selected ? "Remove priority" : "Add priority";
  action.title = !planningIsEditable() ? PLANNING_FREEZE_MESSAGE : disabledReason || "This records a planning priority only; the Factory decides legal acquisition.";
  action.setAttribute("aria-label", `${action.textContent} ${choice.name}`);
  action.onclick = () => {
    if (!guardPlanningMutation()) return;
    if (selected) {
      selectedSet("insight_priorities").delete(choice.choice_id);
      renderInsightBrowser();
      renderChoiceChips("insight_priorities");
      renderOwnerLockSummary();
    } else addSheetChoice("insight_priorities", choice.choice_id);
  };
  card.append(heading, description, scope);
  if (disabledReason) {
    const reason = document.createElement("small"); reason.className = "disabled-reason"; reason.textContent = `Unavailable: ${disabledReason}`; card.appendChild(reason);
  }
  card.appendChild(action);
  host.appendChild(card);
}

function renderInsightCards(choices, all) {
  const host = document.getElementById("sheetInsightCards");
  const count = document.getElementById("sheetInsightBrowserCount");
  if (!host) return;
  clearNode(host);
  const limit = Number(host.dataset.browserLimit || INSIGHT_BROWSER_PAGE_SIZE);
  const selected = selectedSet("insight_priorities");
  const rows = choices.slice(0, limit);
  const selectedRows = choices.filter(choice => selected.has(choice.choice_id));
  for (const choice of selectedRows) if (!rows.some(row => row.choice_id === choice.choice_id)) rows.push(choice);
  const groups = new Map();
  rows.forEach(choice => {
    const group = insightGroupId(choice);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(choice);
  });
  for (const [group, groupRows] of Array.from(groups.entries()).sort(([left], [right]) => (INSIGHT_GROUP_LABELS[left] || left).localeCompare(INSIGHT_GROUP_LABELS[right] || right))) {
    const section = document.createElement("section"); section.className = "insight-category-group";
    const heading = document.createElement("h5"); heading.textContent = `${INSIGHT_GROUP_LABELS[group] || "Other / needs authority"} (${choices.filter(choice => insightGroupId(choice) === group).length})`;
    section.appendChild(heading);
    const subgroupMap = new Map();
    for (const choice of groupRows) {
      const subgroup = insightBrowseSubgroup(choice, group);
      if (!subgroup) {
        if (!subgroupMap.has("")) subgroupMap.set("", []);
        subgroupMap.get("").push(choice);
      } else {
        if (!subgroupMap.has(subgroup)) subgroupMap.set(subgroup, []);
        subgroupMap.get(subgroup).push(choice);
      }
    }
    for (const [subgroup, subgroupRows] of Array.from(subgroupMap.entries()).sort(([left], [right]) => left.localeCompare(right))) {
      if (subgroup) { const subheading = document.createElement("h6"); subheading.textContent = subgroup; section.appendChild(subheading); }
      const grid = document.createElement("div"); grid.className = "insight-card-grid";
      subgroupRows.sort((left, right) => left.name.localeCompare(right.name)).forEach(choice => appendInsightBrowseCard(grid, choice, selected.has(choice.choice_id)));
      section.appendChild(grid);
    }
    host.appendChild(section);
  }
  if (!rows.length) {
    const empty = document.createElement("p"); empty.className = "catalog-empty-state"; empty.textContent = "No ordinary Insights match this category and search. Background-Origin records are intentionally not part of this browser."; host.appendChild(empty);
  }
  if (limit < choices.length) {
    const more = document.createElement("button"); more.type = "button"; more.className = "catalog-more-button";
    more.textContent = `Show ${Math.min(INSIGHT_BROWSER_PAGE_SIZE, choices.length - limit)} more Insights`;
    more.onclick = () => { host.dataset.browserLimit = String(limit + INSIGHT_BROWSER_PAGE_SIZE); renderInsightBrowser(); };
    host.appendChild(more);
  }
  if (count) count.textContent = `${choices.length} matching · ${all.length} ordinary installed · ${selected.size} selected`;
}

function renderInsightBrowser() {
  const select = document.getElementById("sheetInsightAdd");
  if (!select) return;
  const all = ordinaryInsightChoices();
  const groupFilter = document.getElementById("sheetInsightAuthorityFilter")?.value || "";
  const pathWrap = document.getElementById("sheetInsightHierarchyFilterWrap");
  const sphereWrap = document.getElementById("sheetInsightSphereFilterWrap");
  const pathFilter = document.getElementById("sheetInsightHierarchyFilter")?.value || "";
  const sphereFilter = document.getElementById("sheetInsightSphereFilter")?.value || "";
  const query = String(document.getElementById("sheetInsightSearch")?.value || "").trim().toLowerCase();
  const filters = {group: groupFilter, path: groupFilter === "path_insights" ? pathFilter : "", sphere: groupFilter === "sphere_insights" ? sphereFilter : "", query};
  if (pathWrap) pathWrap.hidden = groupFilter !== "path_insights";
  if (sphereWrap) sphereWrap.hidden = groupFilter !== "sphere_insights";
  const pathSelect = document.getElementById("sheetInsightHierarchyFilter");
  if (pathSelect) {
    const prior = pathSelect.value;
    clearNode(pathSelect);
    pathSelect.append(new Option("All Path groups", ""));
    const groups = Array.from(new Set(all.filter(choice => insightGroupId(choice) === "path_insights").map(insightPathGroup).filter(Boolean))).sort();
    groups.forEach(value => pathSelect.append(new Option(value, value)));
    pathSelect.value = groups.includes(prior) ? prior : "";
  }
  const sphereSelect = document.getElementById("sheetInsightSphereFilter");
  if (sphereSelect) {
    const prior = sphereSelect.value;
    const sphereMap = new Map((categoryFor("sphere_priorities")?.choices || []).map(choice => [choice.choice_id, choice.name]));
    clearNode(sphereSelect);
    sphereSelect.append(new Option("All Sphere facets", ""));
    const ids = Array.from(new Set(all.filter(choice => insightGroupId(choice) === "sphere_insights").flatMap(insightSphereFacetIds))).sort((left, right) => (sphereMap.get(left) || left).localeCompare(sphereMap.get(right) || right));
    ids.forEach(id => sphereSelect.append(new Option(sphereMap.get(id) || id, id)));
    sphereSelect.value = ids.includes(prior) ? prior : "";
    filters.sphere = groupFilter === "sphere_insights" ? sphereSelect.value : "";
  }
   const choices = all.filter(choice => insightChoiceMatches(choice, filters));
   renderInsightCards(choices, all);
   const ownerCount = document.getElementById("ownerInsightCount");
   if (ownerCount) ownerCount.textContent = `${choices.length} matching · ${all.length} ordinary`;
  const priorValue = select.value;
  clearNode(select);
  select.append(new Option(choices.length ? "Choose an Insight preference" : "No matching ordinary Insights", ""));
  const byGroup = new Map();
  choices.forEach(choice => {
    const group = insightGroupId(choice);
    if (!byGroup.has(group)) byGroup.set(group, []);
    byGroup.get(group).push(choice);
  });
  for (const [group, rows] of Array.from(byGroup.entries()).sort(([left], [right]) => (INSIGHT_GROUP_LABELS[left] || left).localeCompare(INSIGHT_GROUP_LABELS[right] || right))) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = `${INSIGHT_GROUP_LABELS[group] || group} (${rows.length})`;
    rows.sort((left, right) => left.name.localeCompare(right.name)).forEach(choice => {
      const option = new Option(choice.name, choice.choice_id);
      option.title = choice.description || `${insightGroupLabel(choice)} Insight`;
      option.disabled = choice.planning_priority_available === false || choice.initial_creation_selectable === false;
      optgroup.appendChild(option);
    });
    select.appendChild(optgroup);
  }
   if (choices.some(choice => choice.choice_id === priorValue)) select.value = priorValue;
   renderInsightAuthorityDetail();
   renderPlanningFreeze();
}

function renderInsightAuthorityDetail() {
  const select = document.getElementById("sheetInsightAdd");
  const host = document.getElementById("sheetInsightAuthorityDetail");
  if (!select || !host) return;
  const choice = categoryFor("insight_priorities")?.choices?.find(row => row.choice_id === select.value);
  const authority = choice?.insight_authority;
  if (!authority) {
    host.textContent = "Choose an Insight to see its category and requirements.";
    return;
  }
  const group = insightGroupLabel(choice);
  const path = insightPathGroup(choice);
  const sphereMap = new Map((categoryFor("sphere_priorities")?.choices || []).map(row => [row.choice_id, row.name]));
  const facets = insightSphereFacetIds(choice).map(id => sphereMap.get(id) || id);
  const scope = path ? ` Path group: ${path}.` : facets.length ? ` Sphere facet: ${facets.join(", ")}.` : "";
  host.textContent = `Category: ${group}.${scope} Requirements: ${authority.prerequisites || "None"}. ${authority.preference_only ? "This is a planning preference; it does not grant anything by itself." : ""}`;
}

function setMethodPathAuthorityNotice(message = "", isError = false) {
  const host = document.getElementById("sheetPathAuthorityNotice");
  if (host) {
    host.textContent = message;
    host.classList.toggle("error", isError);
  }
  const ownerStatus = document.getElementById("ownerMethodCompatibilityStatus");
  if (ownerStatus && methodCompatibility.state === "not_checked") ownerStatus.textContent = message || "Compatibility has not been checked.";
}

async function refreshMethodPathChoices({announce = false, preserve = true} = {}) {
  const subpathSelect = document.getElementById("sheetSubpath");
  if (!subpathSelect || !characterBuilderOptions) return;
  const previousPaths = selectedPathIds();
  const previousSubpaths = Array.from(selectedSet("subpath_choice"));
  renderPathChoices();
  methodCompatibility = {key: methodCompatibilityKey(previousPaths), state: "stale", result: null};
  renderOwnerMethodCompatibility();
  populateMethodPlanning();
  setMethodPathAuthorityNotice(previousPaths.length
    ? `${previousPaths.length} Path lock${previousPaths.length === 1 ? "" : "s"} selected. Check the Factory for confirmed Methods.`
    : "0 Path locks: the legal Method route may choose the advancing Paths. Add up to three locks when you want to require them.");
  refreshPathSubpathChoices({announce, preferredValues: preserve ? previousSubpaths : []});
  await requestMethodCompatibility();
}

function refreshPathSubpathChoices({announce = false, preferredValue = null, preferredValues = null} = {}) {
  // Subpaths are grouped by their exact owning Path.  The underlying select is
  // still retained for compatibility with existing browser harnesses, but it
  // is now a bounded multi-select rather than a global primary Subpath field.
  const subpathSelect = document.getElementById("sheetSubpath");
  if (!subpathSelect) return;
  if (!characterBuilderOptions) {
    selectedSet("subpath_choice").clear();
    clearNode(subpathSelect);
    subpathSelect.disabled = true;
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Choose a Starting Path first.";
    option.disabled = true;
    subpathSelect.appendChild(option);
    const notice = document.getElementById("sheetSubpathAuthorityNotice");
    if (notice) notice.textContent = "0 of 0 Path-owned Subpaths selected. Select a Path to browse its owned Subpaths or Traditions.";
    return;
  }
  const oldValues = preferredValues !== null
    ? Array.from(new Set(preferredValues || []))
    : preferredValue !== null
      ? (preferredValue ? [preferredValue] : [])
      : Array.from(selectedSet("subpath_choice"));
  const pathIds = selectedPathIds();
  const category = categoryFor("subpath_choice");
  const byId = new Map((category?.choices || []).map(choice => [choice.choice_id, choice]));
  const selected = selectedSet("subpath_choice");
  const allowed = new Set(pathIds.flatMap(pathId => characterBuilderOptions.path_subpath_index?.[pathId] || []));
  const retained = oldValues.filter(choiceId => allowed.has(choiceId));
  selected.clear();
  const ownerBySelection = new Map();
  for (const choiceId of retained) {
    const choice = byId.get(choiceId);
    const ownerId = choice?.owning_path_id;
    const owners = ownerId && pathIds.includes(ownerId) ? [ownerId] : [];
    if (owners.length !== 1 || ownerBySelection.has(owners[0])) continue;
    ownerBySelection.set(owners[0], choiceId);
    selected.add(choiceId);
  }

  clearNode(subpathSelect);
  subpathSelect.multiple = true;
  subpathSelect.size = Math.min(10, Math.max(4, pathIds.length * 3));
  if (!pathIds.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Choose a Starting Path first.";
    option.disabled = true;
    subpathSelect.appendChild(option);
    subpathSelect.disabled = true;
  } else {
    for (const pathId of pathIds) {
      const group = document.createElement("optgroup");
      const pathChoice = choiceFor("path_choice", pathId);
      group.label = `${pathChoice?.name || pathId} — choose up to one`;
      for (const choiceId of characterBuilderOptions.path_subpath_index?.[pathId] || []) {
        const choice = byId.get(choiceId);
        if (!choice) continue;
        const option = document.createElement("option");
        option.value = choiceId;
        option.textContent = optionLabel(choice);
        option.title = choice.description || choice.name;
        option.selected = selected.has(choiceId);
        group.appendChild(option);
      }
      if (group.children.length) subpathSelect.appendChild(group);
    }
    subpathSelect.disabled = !planningIsEditable();
  }
  // A native multi-select replaces the whole selection on a plain click and
  // only accumulates with Ctrl or Shift held, which reads as "my second
  // Subpath replaced my first."  Make a plain click toggle the option, and
  // make a click inside a Path's group switch that Path's single binding, so
  // one Subpath per selected Path needs no modifier keys.  Keyboard
  // selection keeps its native behaviour.
  subpathSelect.onmousedown = event => {
    const option = event && event.target;
    if (!option || option.tagName !== "OPTION" || option.disabled || subpathSelect.disabled) return;
    if (event.preventDefault) event.preventDefault();
    const group = option.parentNode;
    if (group && group.tagName === "OPTGROUP") {
      for (const sibling of Array.from(group.children)) if (sibling !== option) sibling.selected = false;
    }
    option.selected = !option.selected;
    if (subpathSelect.focus) subpathSelect.focus();
    if (subpathSelect.onchange) subpathSelect.onchange();
  };
  subpathSelect.onchange = () => {
    if (!guardPlanningMutation()) {
      refreshPathSubpathChoices({announce: false});
      return;
    }
    const requested = Array.from(subpathSelect.selectedOptions || []).map(option => option.value).filter(Boolean);
    const next = new Set();
    const owners = new Set();
    const dropped = [];
    for (const choiceId of requested) {
      const choice = byId.get(choiceId);
      const ownerId = choice?.owning_path_id;
      const owner = ownerId && pathIds.includes(ownerId) ? ownerId : null;
      if (!owner || owners.has(owner)) {
        dropped.push(choiceId);
        continue;
      }
      owners.add(owner);
      next.add(choiceId);
    }
    selected.clear();
    for (const choiceId of next) selected.add(choiceId);
    if (dropped.length) {
      setGuidedStatus("Only one Subpath or Tradition can be bound to each selected Path; the duplicate binding was cleared.", true);
    }
    refreshPathSubpathChoices({announce: false});
    evaluateGuidedReadiness();
  };
  const notice = document.getElementById("sheetSubpathAuthorityNotice");
  if (notice) notice.textContent = `${selected.size} of ${pathIds.length} Path-owned Subpath${pathIds.length === 1 ? "" : "s"} selected.${pathIds.length ? "" : " Select a Path to browse its owned Subpaths or Traditions."}`;
  if (announce && oldValues.some(choiceId => !allowed.has(choiceId))) {
    setGuidedStatus("A previous Subpath binding no longer belongs to a selected Path, so it was cleared.", true);
  }
}

function exactBackgroundRoutes(backgroundId) {
  const background = categoryFor("background_choice")?.choices?.find(choice => choice.choice_id === backgroundId);
  return background?.ns1r_exact_route_authority?.route_options || [];
}

function refreshBackgroundChoiceLinks({backgroundChanged = false, sphereChanged = false} = {}) {
  const background = document.getElementById("sheetBackground");
  const sphere = document.getElementById("sheetBackgroundSphere");
  const talent = document.getElementById("sheetBackgroundTalent");
  const origin = document.getElementById("sheetOriginInsight");
  if (!background || !sphere || !talent || !origin || !characterBuilderOptions) return;
   const routes = exactBackgroundRoutes(background.value);
   const sphereIds = new Set(routes.map(route => route.background_sphere_choice_id));
   const talentIds = new Set(routes.map(route => route.background_talent_choice_id));
    const backgroundChoice = categoryFor("background_choice")?.choices?.find(choice => choice.choice_id === background.value);
    const insightIds = new Set(backgroundChoice?.related_choice_ids || []);
   if (backgroundChanged) {
     sphere.value = "";
     talent.value = "";
     origin.value = "";
   }
   const sphereChoices = (categoryFor("background_sphere_choice")?.choices || []).filter(choice => !background.value || sphereIds.has(choice.choice_id));
   populateSheetSelect(sphere, categoryFor("background_sphere_choice"), undefined, sphereChoices);
   const selectedSphere = sphere.value;
   const talentChoices = (categoryFor("background_talent_choice")?.choices || []).filter(choice =>
     talentIds.has(choice.choice_id) && (!selectedSphere || routes.some(route => route.background_sphere_choice_id === selectedSphere && route.background_talent_choice_id === choice.choice_id))
   );
   if (sphereChanged) talent.value = "";
   populateSheetSelect(talent, categoryFor("background_talent_choice"), undefined, talentChoices);
   const originChoices = (categoryFor("origin_insight_choice")?.choices || []).filter(choice => !background.value || insightIds.has(choice.choice_id));
   populateSheetSelect(origin, categoryFor("origin_insight_choice"), undefined, originChoices);
}

function chipHostFor(slotId) {
  return Array.from(document.querySelectorAll("[data-chip-host]")).find(node => node.dataset.chipHost === slotId) || null;
}

function selectedSet(slotId) {
  if (!sheetSelectedChoices.has(slotId)) sheetSelectedChoices.set(slotId, new Set());
  return sheetSelectedChoices.get(slotId);
}

function sphereTalentIndex() {
  return characterBuilderOptions?.sphere_talent_index || {by_sphere: {}, by_talent: {}, unassigned_talent_ids: [], audit: {}};
}

function choiceFor(slotId, choiceId) {
  return categoryFor(slotId)?.choices?.find(choice => choice.choice_id === choiceId) || null;
}

function setSphereTalentNotice(message, isError = false) {
  const host = document.getElementById("sheetSphereTalentNotice");
  if (!host) return;
  host.textContent = message || "";
  host.classList.toggle("error", isError);
}

function selectedTalentNames(ids) {
  return ids.map(id => choiceFor("advancement_skeleton", id)?.canonical_name || choiceFor("advancement_skeleton", id)?.name || id);
}

function removeSheetSphere(sphereId) {
  if (!guardPlanningMutation()) return;
  const result = sphereTalentLogic.removeSphereSelection(
    Array.from(selectedSet("sphere_priorities")),
    Array.from(selectedSet("advancement_skeleton")),
    sphereId,
    sphereTalentIndex()
  );
  sheetSelectedChoices.set("sphere_priorities", new Set(result.sphere_ids));
  sheetSelectedChoices.set("advancement_skeleton", new Set(result.talent_ids));
  if (activeSheetSphereId === sphereId || !result.sphere_ids.includes(activeSheetSphereId)) {
    activeSheetSphereId = result.sphere_ids[0] || null;
  }
  if (result.removed_talent_ids.length) {
    setSphereTalentNotice(`Removed ${selectedTalentNames(result.removed_talent_ids).join(", ")} because no remaining selected Sphere supports ${result.removed_talent_ids.length === 1 ? "it" : "them"}.`);
  } else {
    const sphere = choiceFor("sphere_priorities", sphereId);
    setSphereTalentNotice(`${sphere?.canonical_name || sphere?.name || "Sphere"} removed. No selected Talent became orphaned.`);
  }
  renderSphereTalentWorkspace();
}

function toggleSheetTalent(talentId) {
  if (!guardPlanningMutation()) return;
  const values = selectedSet("advancement_skeleton");
  const category = categoryFor("advancement_skeleton");
  if (values.has(talentId)) {
    values.delete(talentId);
    setSphereTalentNotice("");
  } else {
    const maximum = categoryMaximum(category);
    if (maximum !== null && values.size >= maximum) {
      setSphereTalentNotice(`This section can lock up to ${maximum} choices. Remove one or leave the rest on Auto.`, true);
      return;
    }
    values.add(talentId);
    setSphereTalentNotice("");
  }
  renderSphereTalentWorkspace();
  evaluateGuidedReadiness();
}

function canonicalTalentAvailability(talent) {
  const restricted = talent.restricted === true || talent.selection_disposition === "RESTRICTED_CONTENT" || !["ordinary_or_unspecified", "ordinary"].includes(talent.restriction_status || "ordinary_or_unspecified");
  if (talent.planning_priority_available === false) {
    return {selectable: false, status: "Unavailable", reason: talent.unavailable_reason || "This Talent is not available as a planning priority."};
  }
  if (restricted) {
    return {
      selectable: true,
      status: "Restricted initial-creation priority",
      reason: "This records initial-creation intent only. Exact provenance is recorded only if Stage 2 legally acquires the Talent; post-creation mutation still requires exact evidence."
    };
  }
  const minimum = Number.isInteger(talent.minimum_cl) ? talent.minimum_cl : null;
  if (!talent.creator_selectability_can_be_evaluated_safely) {
    return {
      selectable: true,
      status: "Priority available; acquisition unresolved",
      reason: talent.unresolved_reason || "The natural-language prerequisite remains unresolved for acquisition. The priority does not grant the Talent."
    };
  }
  if (minimum !== null) {
    return {selectable: true, status: "Priority available", reason: `Earliest known acquisition is CL ${minimum}; local Stage 2 authority must schedule it legally.`};
  }
  return {selectable: true, status: "Priority available", reason: "This records planning direction only; local Stage 2 authority decides legal acquisition."};
}

function appendTalentToggle(host, talent, selected, sphereContext = null) {
  const row = document.createElement("article");
  const availability = canonicalTalentAvailability(talent);
  row.className = `talent-option${selected ? " selected" : ""}${availability.selectable ? "" : " locked"}`;
  row.dataset.talentId = talent.choice_id;
  row.dataset.selectionStatus = availability.status;
  const text = document.createElement("div");
  const title = document.createElement("strong"); title.textContent = talent.canonical_name || talent.name;
  const detail = document.createElement("small"); detail.textContent = talent.short_description || talent.description || talent.choice_id;
  const meta = document.createElement("dl"); meta.className = "talent-authority-meta";
  const metaRows = [
    ["Owning Sphere", talent.owning_canonical_sphere_name || talent.owning_canonical_sphere_id || "Unresolved"],
    ["Earliest known CL", Number.isInteger(talent.minimum_cl) ? `CL ${talent.minimum_cl}` : "No exact minimum recorded"],
    ["Prerequisite", talent.raw_prerequisite_prose || talent.unresolved_reason || (talent.typed_constraints || []).map(row => row.kind).join(", ") || "No additional exact prerequisite recorded"],
    ["Creator state", talent.creator_ready ? "Creator-ready for exact acquisition validation" : (talent.creator_selectability_can_be_evaluated_safely ? "Acquisition requires Stage 2 validation" : "Unresolved for acquisition")],
    ["Restriction", talent.restricted ? "Restricted" : "Not restricted"]
  ];
  for (const [label, value] of metaRows) {
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    meta.append(dt, dd);
  }
  const full = document.createElement("details");
  const summary = document.createElement("summary"); summary.textContent = "Details and full description";
  const prose = document.createElement("p"); prose.textContent = talent.full_description || talent.description || "No full description is present in the authenticated source.";
  full.append(summary, meta, prose);
  const state = document.createElement("small"); state.className = "talent-authority-state"; state.textContent = `${availability.status}: ${availability.reason}`;
  full.insertBefore(state, prose);
  text.append(title, detail, full);
  const controls = document.createElement("div"); controls.className = "talent-route-controls";
   const priorityButton = document.createElement("button"); priorityButton.type = "button"; priorityButton.className = "talent-toggle";
   priorityButton.dataset.planningMutator = "true";
  priorityButton.textContent = selected ? "Remove Priority" : "Prioritize Talent";
   priorityButton.disabled = !availability.selectable || !planningIsEditable();
  priorityButton.setAttribute("aria-pressed", selected ? "true" : "false");
  priorityButton.setAttribute("aria-label", `${selected ? "Remove priority" : "Prioritize"} ${talent.canonical_name || talent.name}${sphereContext ? ` for ${sphereContext}` : ""}`);
  priorityButton.title = availability.reason;
   priorityButton.title = planningIsEditable() ? availability.reason : PLANNING_FREEZE_MESSAGE;
   priorityButton.onclick = () => toggleSheetTalent(talent.choice_id);
  controls.append(priorityButton);
   row.append(text, controls); host.appendChild(row);
}

function sphereBaseAbilities(sphere) {
  return Array.isArray(sphere?.resolved_automatic_base_abilities)
    ? sphere.resolved_automatic_base_abilities
    : Array.isArray(sphere?.automatic_base_abilities) ? sphere.automatic_base_abilities : [];
}

function sphereProjectionWarning(sphere, baseAbilities) {
  const explicit = sphere?.projection_warning || sphere?.projection_error || sphere?.owner_projection_warning;
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
  if (!baseAbilities.length) return "Base-ability projection is not available in the installed source for this Sphere.";
  return "";
}

function acquiredSphereNames() {
  const rows = guidedRun?.owner_view?.scratch_candidate?.sheet?.spheres || [];
  return new Set(rows.map(row => typeof row === "string" ? row : row?.name).filter(Boolean));
}

function appendSphereBrowseCard(host, sphere, selected, acquiredNames, index) {
  const card = document.createElement("article");
  card.className = `sphere-browse-card${selected ? " selected" : ""}`;
  card.dataset.sphereId = sphere.choice_id;
  const heading = document.createElement("div"); heading.className = "sphere-browse-heading";
  const title = document.createElement("h6"); title.textContent = sphere.canonical_name || sphere.name;
  const state = document.createElement("span"); state.className = "sphere-state-badge";
  const displayName = sphere.canonical_name || sphere.name;
  const acquired = acquiredNames.has(displayName);
  state.textContent = acquired ? "Acquired" : selected ? "Priority" : "Available";
  heading.append(title, state);
  const baseAbilities = sphereBaseAbilities(sphere);
  const first = baseAbilities[0];
  const abilityName = first?.display_name || first?.name || "Automatic base ability";
  const rawRulesText = first
    ? first.player_rules_text || first.full_exact_source_text || first.full_description || first.effect || "Player text is present in the validated source."
    : "No player-facing automatic base-ability text is available for this Sphere yet.";
  const explanation = document.createElement("details"); explanation.className = "sphere-browse-explanation";
  const explanationSummary = document.createElement("summary"); explanationSummary.textContent = "View explanation";
  const explanationPanel = document.createElement("div"); explanationPanel.className = "sphere-browse-explanation-panel";
  const abilityHeading = document.createElement("h6"); abilityHeading.className = "sphere-browse-ability-name"; abilityHeading.textContent = abilityName;
  const rules = document.createElement("p"); rules.className = "sphere-browse-explanation-text";
  rules.textContent = String(rawRulesText).replace(/^\s*#{1,6}\s*/gm, "").trim();
  explanationPanel.append(abilityHeading, rules);
  explanation.append(explanationSummary, explanationPanel);
  const talentCount = sphereTalentLogic.talentIdsForSphere(index, sphere.choice_id).length;
  const meta = document.createElement("small");
  meta.textContent = `${talentCount} child Talent${talentCount === 1 ? "" : "s"} · ${acquired ? "acquired result" : selected ? "planning preference only" : "not selected"}`;
  const warning = sphereProjectionWarning(sphere, baseAbilities);
  let warningNode = null;
  if (warning) {
    warningNode = document.createElement("small"); warningNode.className = "projection-warning"; warningNode.textContent = warning;
  }
  const action = document.createElement("button"); action.type = "button"; action.className = "sphere-priority-toggle";
  action.dataset.planningMutator = "true";
  const unavailable = sphere.planning_priority_available === false;
  action.disabled = acquired || unavailable || !planningIsEditable();
  action.textContent = acquired ? "Acquired" : selected ? "Remove priority" : "Prioritize Sphere";
  action.title = !planningIsEditable()
    ? PLANNING_FREEZE_MESSAGE
    : unavailable ? (sphere.unavailable_reason || "This Sphere is not available as a planning priority.")
      : acquired ? "This Sphere is already present in the validated candidate; planning does not grant it again."
        : "Record this Sphere as a planning priority. It does not acquire the Sphere by itself.";
  action.setAttribute("aria-label", `${action.textContent} ${displayName}`);
  action.onclick = () => {
    if (!guardPlanningMutation()) return;
    if (selected) removeSheetSphere(sphere.choice_id); else addSheetChoice("sphere_priorities", sphere.choice_id);
  };
  card.append(heading, meta, action);
  if (warningNode) card.appendChild(warningNode);
  card.appendChild(explanation);
  host.appendChild(card);
}

function renderSphereCatalog(sphereCategory, index, sphereIds) {
  const host = document.getElementById("sheetSphereCatalog");
  const countHost = document.getElementById("sheetSphereBrowserCount");
  if (!host || !sphereCategory) return;
  clearNode(host);
  const allInstalled = sphereTalentLogic.uniqueChoices(sphereCategory.choices || []).sort((left, right) => (left.canonical_name || left.name || "").localeCompare(right.canonical_name || right.name || ""));
  const sphereQuery = String(document.getElementById("sheetSphereSearch")?.value || "").trim().toLowerCase();
  const all = allInstalled.filter(choice => !sphereQuery || `${choice.canonical_name || choice.name || ""} ${choice.short_description || choice.description || ""}`.toLowerCase().includes(sphereQuery));
  const limit = Number(host.dataset.browserLimit || SPHERE_BROWSER_PAGE_SIZE);
  const selectedSetValue = new Set(sphereIds);
  const selectedRows = all.filter(choice => selectedSetValue.has(choice.choice_id));
  const rows = all.slice(0, limit);
  for (const selected of selectedRows) if (!rows.some(row => row.choice_id === selected.choice_id)) rows.push(selected);
  const acquiredNames = acquiredSphereNames();
  rows.forEach(sphere => appendSphereBrowseCard(host, sphere, selectedSetValue.has(sphere.choice_id), acquiredNames, index));
  if (limit < all.length) {
    const more = document.createElement("button"); more.type = "button"; more.className = "catalog-more-button";
    more.textContent = `Show ${Math.min(SPHERE_BROWSER_PAGE_SIZE, all.length - limit)} more Spheres`;
    more.onclick = () => { host.dataset.browserLimit = String(limit + SPHERE_BROWSER_PAGE_SIZE); renderSphereCatalog(sphereCategory, index, sphereIds); renderPlanningFreeze(); };
    host.appendChild(more);
  }
  if (countHost) countHost.textContent = `${allInstalled.length} installed · ${sphereIds.length} planning priorit${sphereIds.length === 1 ? "y" : "ies"} · ${rows.length} shown${sphereQuery ? ` of ${all.length} matching` : ""}`;
}

function renderSphereTalentWorkspace() {
  if (!characterBuilderOptions || !sphereTalentLogic) return;
  const sphereCategory = categoryFor("sphere_priorities");
  const talentCategory = categoryFor("advancement_skeleton");
  const index = sphereTalentIndex();
  const sphereIds = Array.from(selectedSet("sphere_priorities"));
  const talentIds = Array.from(selectedSet("advancement_skeleton"));
   const selectedTalentSet = new Set(talentIds);
   if (!activeSheetSphereId || !sphereIds.includes(activeSheetSphereId)) activeSheetSphereId = sphereIds[0] || null;

   renderSphereCatalog(sphereCategory, index, sphereIds);

  const sphereAdd = document.getElementById("sheetSphereAdd");
  if (sphereAdd && sphereCategory) {
    const unselected = sphereTalentLogic.uniqueChoices(sphereCategory.choices).filter(choice => !sphereIds.includes(choice.choice_id));
    populateSheetSelect(sphereAdd, sphereCategory, "Choose a Sphere priority", unselected);
    const available = unselected.filter(choice => choice.planning_priority_available !== false);
     sphereAdd.disabled = !planningIsEditable() || (categoryMaximum(sphereCategory) !== null && sphereIds.length >= categoryMaximum(sphereCategory)) || !available.length;
  }

  const sphereHost = document.getElementById("sheetSphereList");
  if (sphereHost) {
    clearNode(sphereHost);
    if (!sphereIds.length) {
      const empty = document.createElement("p");
      empty.className = "sphere-empty-state";
      empty.textContent = "No Sphere priority selected. Unavailable zero-talent Spheres remain visible in the list with an exact reason but cannot be added.";
      sphereHost.appendChild(empty);
    }
    for (const sphereId of sphereIds) {
      const sphere = choiceFor("sphere_priorities", sphereId);
      if (!sphere) continue;
      const card = document.createElement("article");
      card.className = `sphere-card${sphereId === activeSheetSphereId ? " active" : ""}`;
      const activate = document.createElement("button");
      activate.type = "button";
      activate.className = "sphere-activate";
      activate.setAttribute("aria-pressed", sphereId === activeSheetSphereId ? "true" : "false");
      activate.onclick = () => { activeSheetSphereId = sphereId; renderSphereTalentWorkspace(); };
      const name = document.createElement("strong");
      name.textContent = sphere.canonical_name || sphere.name;
      const count = document.createElement("small");
      const sphereTalentIds = sphereTalentLogic.talentIdsForSphere(index, sphereId);
      const coverage = index.per_sphere_coverage?.[sphereId] || {};
      count.textContent = coverage.honest_label || `${sphereTalentIds.length} source-authorized Talent${sphereTalentIds.length === 1 ? "" : "s"}`;
      activate.append(name, count);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "sphere-remove";
      remove.dataset.planningMutator = "true";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${sphere.canonical_name || sphere.name}`);
      remove.title = planningIsEditable() ? "Remove this planning priority." : PLANNING_FREEZE_MESSAGE;
      remove.onclick = () => removeSheetSphere(sphereId);
      const selectedForSphere = talentIds.filter(talentId => sphereTalentLogic.talentSphereIds(index, talentId).includes(sphereId));
      const associated = document.createElement("div");
      associated.className = "sphere-card-talents";
      const baseAbilities = sphere.resolved_automatic_base_abilities || sphere.automatic_base_abilities || [];
      const acquired = acquiredSphereNames().has(sphere.canonical_name || sphere.name);
      associated.textContent = `${acquired ? "Acquired result" : "Planning priority only"} — ${acquired ? "this card reflects a validated Sphere;" : "it does not acquire a Sphere or consume a grant;"} child Talent priorities: ${selectedForSphere.length ? selectedTalentNames(selectedForSphere).join(", ") : "none"}. Automatic base abilities cost no slot; free and ordinary Talent acquisition remains Factory-derived.`;
      const grants = document.createElement("ul"); grants.className = "automatic-base-abilities";
      for (const ability of baseAbilities) {
        const item = document.createElement("li");
        item.dataset.baseAbilityId = ability.base_ability_id;
        const details = document.createElement("details"); details.className = "base-ability-detail";
        const summary = document.createElement("summary");
        summary.textContent = `${ability.display_name} — automatic Sphere component`;
        const grant = document.createElement("p");
        grant.textContent = "Granted automatically; cannot be removed; costs 0 talent, advancement, or training slots.";
        const playerText = ability.player_rules_text || ability.full_exact_source_text || ability.full_description || ability.effect || "";
        if (playerText) {
          const readable = document.createElement("p");
          readable.className = "base-ability-player-text";
          readable.textContent = playerText;
          details.append(summary, grant, readable);
        } else details.append(summary, grant);
        const structured = ability.source_component_structured_fields || ability.structured_fields || {};
        const fields = document.createElement("dl"); fields.className = "base-ability-fields";
        const fieldRows = [
          ["Action type", ability.action_type], ["Range", ability.range], ["Cost", ability.cost],
          ["Target", ability.target], ["Trigger", ability.trigger], ["Use limit", ability.use_limit],
          ["Scaling", Array.isArray(ability.scaling) ? ability.scaling.join(" ") : ability.scaling],
          ["Tags", Array.isArray(ability.tags) ? ability.tags.join(", ") : ability.tags],
          ...Object.entries(structured).map(([key, value]) => [friendlyLabel(key), Array.isArray(value) ? value.join(", ") : (value && typeof value === "object" ? pretty(value) : value)]),
        ];
        for (const [term, value] of fieldRows) {
          const empty = value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length);
          if (empty) continue;
          const dt = document.createElement("dt"); dt.textContent = term;
          const dd = document.createElement("dd"); dd.textContent = String(value);
          fields.append(dt, dd);
        }
        if (fields.children.length) details.append(fields);
        const technical = document.createElement("details");
        technical.className = "developer-only base-ability-technical";
        technical.hidden = true;
        const technicalSummary = document.createElement("summary"); technicalSummary.textContent = "Developer / Diagnostics: source routing";
        const technicalFields = document.createElement("dl"); technicalFields.className = "base-ability-fields";
        for (const [term, value] of [
          ["Base ability ID", ability.base_ability_id],
          ["Component hash", ability.component_hash || ability.source_component_sha256 || ability.source_hash],
          ["Record commitment", ability.record_commitment_sha256 || ability.commitment_sha256],
          ["Factory routing", ability.factory_routing],
          ["Source section / path", ability.source_reference?.source_section || ability.source_reference?.source_path || ability.source_reference?.path],
          ["Source anchor", ability.source_reference?.source_anchor || ability.source_reference?.anchor],
          ["Owner ruling", ability.owner_ruling_id || ability.ruling_id],
        ]) {
          if (value === null || value === undefined || value === "") continue;
          const dt = document.createElement("dt"); dt.textContent = term;
          const dd = document.createElement("dd"); dd.textContent = String(value);
          technicalFields.append(dt, dd);
        }
        technical.append(technicalSummary, technicalFields);
        details.append(technical);
        item.appendChild(details);
        grants.appendChild(item);
      }
       const projectionWarning = sphereProjectionWarning(sphere, baseAbilities);
       if (!baseAbilities.length) {
         const item = document.createElement("li"); item.className = "base-ability-none";
         item.textContent = "No player-facing automatic base-ability text is available for this Sphere yet.";
         grants.appendChild(item);
       }
       const warningNode = projectionWarning ? document.createElement("small") : null;
       if (warningNode) { warningNode.className = "projection-warning"; warningNode.textContent = projectionWarning; }
      card.append(activate, remove, grants, associated);
      if (warningNode) card.appendChild(warningNode);
      sphereHost.appendChild(card);
    }
  }

  const panelTitle = document.getElementById("sheetTalentPanelTitle");
  const message = document.getElementById("sheetTalentPanelMessage");
  const search = document.getElementById("sheetTalentSearch");
  const optionsHost = document.getElementById("sheetTalentOptions");
  if (optionsHost) clearNode(optionsHost);
  const activeSphere = activeSheetSphereId ? choiceFor("sphere_priorities", activeSheetSphereId) : null;
  if (!activeSphere) {
    if (panelTitle) panelTitle.textContent = "Talents";
    if (message) message.textContent = "Select a Sphere first.";
    if (search) { search.disabled = true; search.value = ""; }
  } else {
    const activeName = activeSphere.canonical_name || activeSphere.name;
    if (panelTitle) panelTitle.textContent = `Talents for ${activeName}`;
    const coverage = index.per_sphere_coverage?.[activeSheetSphereId] || {};
    if (message) message.textContent = coverage.selectable_talent_count === 0
      ? (coverage.unavailable_reason || "Not currently creator-ready — no canonical selectable talent authority")
      : "Canonical published Talents are shown as planning priorities. Current CL does not disable a priority; acquisition remains fail-closed in Stage 2.";
    if (search) search.disabled = false;
    const query = String(search?.value || "").trim().toLowerCase();
    const talentMap = new Map((talentCategory?.choices || []).map(choice => [choice.choice_id, choice]));
    const allRows = sphereTalentLogic.talentIdsForSphere(index, activeSheetSphereId)
      .map(id => talentMap.get(id))
      .filter(Boolean)
      .filter(talent => !query || `${talent.canonical_name || talent.name} ${talent.description || ""}`.toLowerCase().includes(query));
    const limit = Number(optionsHost?.dataset.browserLimit || TALENT_BROWSER_PAGE_SIZE);
    const rows = allRows.slice(0, limit);
    const selectedRows = allRows.filter(talent => selectedTalentSet.has(talent.choice_id));
    for (const selected of selectedRows) {
      if (!rows.some(row => row.choice_id === selected.choice_id)) rows.push(selected);
    }
    for (const talent of rows) appendTalentToggle(optionsHost, talent, selectedTalentSet.has(talent.choice_id), activeName);
    if (optionsHost && limit < allRows.length) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "catalog-more-button talent-catalog-more";
      more.textContent = `Show ${Math.min(TALENT_BROWSER_PAGE_SIZE, allRows.length - limit)} more Talents${query ? " matching this search" : ""}`;
      more.onclick = () => {
        optionsHost.dataset.browserLimit = String(limit + TALENT_BROWSER_PAGE_SIZE);
        renderSphereTalentWorkspace();
      };
      optionsHost.appendChild(more);
    }
    if (optionsHost && !rows.length) {
      const empty = document.createElement("p");
      empty.className = "talent-empty-state";
      const coverage = index.per_sphere_coverage?.[activeSheetSphereId] || {};
      empty.textContent = query
        ? "No source-authorized Talent matches this search."
        : (coverage.selectable_talent_count === 0
          ? "Authority gap: no source-confirmed selectable Talent is available for this Sphere."
          : "No source-authorized Talent is available for this Sphere.");
      optionsHost.appendChild(empty);
    }
  }

  const selectedHost = document.getElementById("sheetTalentList");
  if (selectedHost) {
    clearNode(selectedHost);
    const talentMap = new Map((talentCategory?.choices || []).map(choice => [choice.choice_id, choice]));
    if (!talentIds.length) {
      const empty = document.createElement("span");
      empty.className = "talent-empty-state";
      empty.textContent = "No Talent priority selected.";
      selectedHost.appendChild(empty);
    }
    const legacyFindings = characterBuilderOptions.legacy_talent_findings || {};
    for (const talentId of talentIds) {
      const talent = talentMap.get(talentId);
      const legacy = legacyFindings[talentId];
      const chip = document.createElement("span");
      chip.className = `choice-chip${!talent ? " legacy-authority-finding" : ""}`;
      const label = document.createElement("span");
      if (talent) {
        label.textContent = talent.canonical_name || talent.name;
      } else if (legacy) {
        label.textContent = `${legacy.name || talentId} — needs review (${legacy.source_role || "unresolved source role"})`;
        chip.title = `${legacy.finding || "This saved row is no longer a selectable Talent."} ${legacy.resolution || ""}`.trim();
      } else {
        label.textContent = `${talentId} — unavailable; preserved without substitution`;
        chip.title = "This saved ID is not present in the current selectable authority. No replacement was inferred.";
      }
      const remove = document.createElement("button");
     remove.type = "button";
     remove.dataset.planningMutator = "true";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${talent ? (talent.canonical_name || talent.name) : (legacy?.name || talentId)}`);
       remove.disabled = !planningIsEditable();
       remove.title = planningIsEditable() ? "Remove this planning priority." : PLANNING_FREEZE_MESSAGE;
       remove.onclick = () => toggleSheetTalent(talentId);
      chip.append(label, remove);
      selectedHost.appendChild(chip);
    }
  }
  const countHost = document.getElementById("sheetTalentSelectionCount");
  if (countHost) countHost.textContent = `${talentIds.length} prioritized`;

  const audit = index.audit || {};
  const talentHelp = document.getElementById("sheetTalentHelp");
  if (talentHelp) talentHelp.textContent = `${audit.talent_count || 0} canonical Talents are accounted for exactly once. Priorities consume no grant or slot; restricted content remains unavailable.`;
  const sphereHelp = document.getElementById("sheetSphereHelp");
  if (sphereHelp) {
    const unavailable = (sphereCategory?.choices || []).filter(choice => choice.planning_priority_available === false).length;
     const maximum = categoryMaximum(sphereCategory);
     sphereHelp.textContent = `${audit.sphere_count || sphereCategory?.choices?.length || 0} canonical Spheres; ${unavailable} are not creator-ready because they have no legal free-talent authority. ${maximum === null ? "There is no fixed priority cap." : `The installed authority allows up to ${maximum} priorities.`}`;
  }

  const unassignedIds = sphereTalentLogic.uniqueIds(index.unassigned_talent_ids || []);
  const details = document.getElementById("sheetUnassignedTalentDetails");
  const unassignedCount = document.getElementById("sheetUnassignedTalentCount");
  const unassignedHost = document.getElementById("sheetUnassignedTalentOptions");
  const unassignedSearch = document.getElementById("sheetUnassignedTalentSearch");
  if (details) details.hidden = unassignedIds.length === 0;
  if (unassignedCount) unassignedCount.textContent = String(unassignedIds.length);
   if (unassignedHost) {
    clearNode(unassignedHost);
    const query = String(unassignedSearch?.value || "").trim().toLowerCase();
    const talentMap = new Map((talentCategory?.choices || []).map(choice => [choice.choice_id, choice]));
    const matching = unassignedIds.filter(talentId => {
      const talent = talentMap.get(talentId);
      return Boolean(talent) && (!query || `${talent.canonical_name || talent.name} ${talent.description || ""}`.toLowerCase().includes(query));
    });
    const limit = Number(unassignedHost.dataset.browserLimit || TALENT_BROWSER_PAGE_SIZE);
    for (const talentId of matching.slice(0, limit)) {
      const talent = talentMap.get(talentId);
      appendTalentToggle(unassignedHost, talent, selectedTalentSet.has(talentId));
    }
    if (limit < matching.length) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "catalog-more-button talent-catalog-more";
      more.textContent = `Show ${Math.min(TALENT_BROWSER_PAGE_SIZE, matching.length - limit)} more Talents${query ? " matching this search" : ""}`;
      more.onclick = () => {
        unassignedHost.dataset.browserLimit = String(limit + TALENT_BROWSER_PAGE_SIZE);
        renderSphereTalentWorkspace();
      };
      unassignedHost.appendChild(more);
    }
   }
   renderOwnerLockSummary();
   renderPlanningFreeze();
}

function renderChoiceChips(slotId) {
  if (slotId === "sphere_priorities" || slotId === "advancement_skeleton") {
    renderSphereTalentWorkspace();
    return;
  }
  const host = chipHostFor(slotId);
  if (!host) return;
  clearNode(host);
  const category = categoryFor(slotId);
  const byId = new Map((category?.choices || []).map(choice => [choice.choice_id, choice]));
  for (const choiceId of selectedSet(slotId)) {
    const choice = byId.get(choiceId);
    if (!choice) continue;
    const chip = document.createElement("span");
    chip.className = "choice-chip";
    chip.title = choice.description || choice.name;
    const label = document.createElement("span");
    const insightType = choice.insight_authority ? insightGroupLabel(choice) : "";
    label.textContent = insightType ? `${choice.name} — ${insightType}` : choice.name;
    const remove = document.createElement("button");
    remove.type = "button";
     remove.setAttribute("aria-label", `Remove ${choice.name}`);
     remove.textContent = "×";
     remove.onclick = () => {
       if (!guardPlanningMutation()) return;
       selectedSet(slotId).delete(choiceId);
       renderChoiceChips(slotId);
    };
     chip.append(label, remove);
     host.appendChild(chip);
   }
   renderOwnerLockSummary();
   renderPlanningFreeze();
 }

function addSheetChoice(slotId, requestedChoiceId = null) {
  if (!guardPlanningMutation()) return;
  const select = Array.from(document.querySelectorAll("[data-multi-slot]")).find(node => node.dataset.multiSlot === slotId);
  const category = categoryFor(slotId);
  const choiceId = requestedChoiceId || select?.value || "";
  if (!category || !choiceId) return;
  const values = selectedSet(slotId);
  const maximum = categoryMaximum(category);
  if (maximum !== null && values.size >= maximum) {
    setGuidedStatus(`This section can lock up to ${maximum} choices. Leave the rest on Auto.`, true);
    return;
  }
   const choice = choiceFor(slotId, choiceId);
  if (slotId === "sphere_priorities" && choice?.planning_priority_available === false) {
    setGuidedStatus(`${choice.name} cannot be prioritized: ${choice.unavailable_reason || "not creator-ready"}`, true);
    select.focus();
    return;
  }
   values.add(choiceId);
   if (slotId === "sphere_priorities") activeSheetSphereId = choiceId;
   if (select) select.value = "";
  renderChoiceChips(slotId);
  setGuidedStatus("");
  renderOwnerLockSummary();
  evaluateGuidedReadiness();
}

function setAbilitySelectState(message) {
  for (const select of document.querySelectorAll("[data-ability]")) {
    clearNode(select);
    const option = document.createElement("option");
    option.value = "";
    option.textContent = message;
    option.disabled = true;
    option.selected = true;
    select.appendChild(option);
    select.disabled = true;
  }
}

function populateAbilitySelects() {
  const pointBuy = characterBuilderOptions?.point_buy;
  if (!pointBuy) {
    setAbilitySelectState("Verified choices unavailable");
    return;
  }
  for (const select of document.querySelectorAll("[data-ability]")) {
    clearNode(select);
    const automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = "Auto";
    select.appendChild(automatic);
    for (let score = pointBuy.minimum; score <= pointBuy.maximum; score += 1) {
      const option = document.createElement("option");
      option.value = String(score);
      option.textContent = `${score} (${pointBuy.costs[String(score)]} pts)`;
      select.appendChild(option);
    }
    select.disabled = select.options.length < 2;
    select.onchange = () => { if (!guardPlanningMutation()) return; updatePointBuySummary(); };
  }
}

function collectAbilityScores() {
  const result = {};
  for (const select of document.querySelectorAll("[data-ability]")) {
    result[select.dataset.ability] = select.value === "" ? null : Number(select.value);
  }
  return result;
}

function updatePointBuySummary() {
  if (!characterBuilderOptions) return;
  const scores = collectAbilityScores();
  const costs = characterBuilderOptions.point_buy.costs;
  const budget = characterBuilderOptions.point_buy.budget;
  let spent = 0;
  let autoCount = 0;
  for (const value of Object.values(scores)) {
    if (value === null) autoCount += 1;
    else spent += Number(costs[String(value)] || 0);
  }
  const remaining = budget - spent;
  const summary = autoCount
    ? `${spent} of ${budget} points reserved — ${remaining} left for ${autoCount} Auto ${autoCount === 1 ? "ability" : "abilities"}`
    : `${spent} of ${budget} points used`;
  document.getElementById("pointBuySummary").textContent = summary;
  document.getElementById("pointBuyBar").style.width = `${Math.min(100, (spent / budget) * 100)}%`;
  document.querySelector(".point-buy-meter")?.classList.toggle("over-budget", spent > budget);
  evaluateGuidedReadiness();
}

function collectSheetSelections() {
  const result = {};
  for (const select of document.querySelectorAll("[data-sheet-slot]")) {
    const values = select.multiple
      ? Array.from(select.selectedOptions || []).map(option => option.value).filter(Boolean)
      : (select.value ? [select.value] : []);
    if (values.length && (select.dataset.sheetSlot !== "method_choice" || methodPlanningMode() === "EXACT")) {
      result[select.dataset.sheetSlot] = values;
    }
  }
  if (selectedSet("path_choice").size) result.path_choice = selectedPathIds();
  for (const [slotId, values] of sheetSelectedChoices.entries()) {
    if (["sphere_priorities", "advancement_skeleton"].includes(slotId)) continue;
    if (values.size) result[slotId] = Array.from(values);
  }
  return result;
}

function resetCharacterSheet() {
  sheetSelectedChoices.clear();
  activeSheetSphereId = null;
  for (const select of document.querySelectorAll("[data-sheet-slot], [data-multi-slot], [data-ability]")) select.value = "";
  for (const host of document.querySelectorAll("[data-chip-host]")) clearNode(host);
  const talentSearch = document.getElementById("sheetTalentSearch");
  const unassignedSearch = document.getElementById("sheetUnassignedTalentSearch");
  if (talentSearch) talentSearch.value = "";
  if (unassignedSearch) unassignedSearch.value = "";
  const learningNote = document.getElementById("sheetMethodLearningNote");
  if (learningNote) learningNote.value = "";
  const insightFilter = document.getElementById("sheetInsightAuthorityFilter");
  const insightHierarchyFilter = document.getElementById("sheetInsightHierarchyFilter");
  const insightSphereFilter = document.getElementById("sheetInsightSphereFilter");
  const insightSearch = document.getElementById("sheetInsightSearch");
  setMethodPlanningMode("AUTO");
  if (insightFilter) insightFilter.value = "";
  if (insightHierarchyFilter) insightHierarchyFilter.value = "";
  if (insightSphereFilter) insightSphereFilter.value = "";
  if (insightSearch) insightSearch.value = "";
  renderInsightBrowser();
  renderInsightAuthorityDetail();
  setSphereTalentNotice("");
  if (characterBuilderOptions) {
    renderPathChoices();
    renderSphereTalentWorkspace();
  }
  updatePointBuySummary();
  setCreationMode("quick");
}

function restoreCharacterSheet(locks) {
  resetCharacterSheet();
  const mode = locks["character_sheet.creation_mode"] === "detailed" ? "detailed" : "quick";
  const pointBuy = locks["character_sheet.ability_point_buy"] || {};
  const fixedScores = pointBuy.fixed_scores || {};
  for (const select of document.querySelectorAll("[data-ability]")) {
    const score = fixedScores[select.dataset.ability];
    select.value = Number.isInteger(score) ? String(score) : "";
  }
  const locked = sphereTalentLogic.normalizeLockedSelections(locks["character_sheet.locked_choices"] || {});
  const planning = locks["character_sheet.planning_preferences"] || {};
  setMethodPlanningMode(locks["character_sheet.method_planning_mode"] || (locked.method_choice?.length ? "EXACT" : planning.method_preference_id ? "PREFERENCE" : "AUTO"));
  for (const select of document.querySelectorAll("[data-sheet-slot]")) {
    const values = locked[select.dataset.sheetSlot] || [];
    if (select.multiple) {
      Array.from(select.options || []).forEach(option => { option.selected = values.includes(option.value); });
    } else {
      select.value = values[0] || "";
    }
  }
  sheetSelectedChoices.set("path_choice", new Set(locked.path_choice || []));
  sheetSelectedChoices.set("subpath_choice", new Set(locked.subpath_choice || []));
  if (planning.method_preference_id) document.getElementById("sheetMethod").value = planning.method_preference_id;
  if (planning.method_exact_choice_id) document.getElementById("sheetMethod").value = planning.method_exact_choice_id;
  populateMethodPlanning();
  const savedMethodPlan = locks["character_sheet.method_access_plan"] || {};
  const savedRoute = methodChoiceFor()?.method_planning?.owner_route_options?.find(option => option.typed_route === savedMethodPlan.route_type || option.description === savedMethodPlan.route_type);
  if (savedRoute) document.getElementById("sheetMethodRouteChoice").value = savedRoute.choice_id;
  const learningNote = document.getElementById("sheetMethodLearningNote");
  if (learningNote) learningNote.value = savedMethodPlan.owner_annotation || "";
  refreshMethodPathChoices({preserve: true});
  refreshPathSubpathChoices({preferredValues: locked.subpath_choice || []});
  sheetSelectedChoices.set("sphere_priorities", new Set(planning.sphere_priority_ids || locked.sphere_priorities || []));
  sheetSelectedChoices.set("advancement_skeleton", new Set(planning.talent_priority_ids || locked.advancement_skeleton || []));
  for (const slotId of ["insight_priorities", "item_priorities"]) {
    sheetSelectedChoices.set(slotId, new Set(locked[slotId] || []));
  }
  activeSheetSphereId = Array.from(selectedSet("sphere_priorities"))[0] || null;
  renderSphereTalentWorkspace();
  renderChoiceChips("insight_priorities");
  renderChoiceChips("item_priorities");
  refreshBackgroundChoiceLinks();
   setCreationMode(mode);
   syncFoundationAvailability();
   updatePointBuySummary();
   renderPlanningFreeze();
}

function foundationAcquisitionCl() {
  const value = Number(characterBuilderOptions?.initial_foundation_acquisition_cl);
  return Number.isInteger(value) && value > 0 ? value : 5;
}

// A Foundation is acquired at the published CL; below it the picker is locked
// and any pick is cleared so the server never receives a Foundation it refuses.
function syncFoundationAvailability() {
  const select = document.getElementById("sheetFoundation");
  if (!select) return;
  const minimum = foundationAcquisitionCl();
  const level = Number(document.getElementById("guidedLevel")?.value);
  const locked = Number.isInteger(level) && level < minimum;
  if (locked) select.value = "";
  select.disabled = locked;
  const notice = document.getElementById("sheetFoundationNotice");
  if (notice) notice.textContent = locked ? `Foundations open at level ${minimum}.` : "";
}

async function loadCharacterBuilderOptions() {
  const status = document.getElementById("sheetOptionsStatus");
  setAbilitySelectState("Loading verified choices…");
  try {
    characterBuilderOptions = await api("/api/character-builder/options");
    populateAbilitySelects();
    for (const select of document.querySelectorAll("[data-sheet-slot]")) {
      populateSheetSelect(select, categoryFor(select.dataset.sheetSlot));
    }
    populateMethodPlanning();
    syncFoundationAvailability();
     document.getElementById("sheetMethod").onchange = () => { if (!guardPlanningMutation()) return; clearMethodAccessInputs(); populateMethodPlanning(); evaluateGuidedReadiness(); };
     for (const option of document.querySelectorAll('input[name="sheetMethodMode"]')) option.onchange = () => { if (!guardPlanningMutation()) return; clearMethodAccessInputs(); populateMethodPlanning(); refreshMethodPathChoices({announce: true, preserve: true}); evaluateGuidedReadiness(); };
     document.getElementById("sheetMethodRouteChoice").onchange = () => { if (!guardPlanningMutation()) return; updateMethodLearningNoteRequirement(); evaluateGuidedReadiness(); };
     document.getElementById("sheetMethodLearningNote").oninput = () => { if (planningIsEditable()) evaluateGuidedReadiness(); else guardPlanningMutation(); };
    document.getElementById("guidedLevel").addEventListener("change", () => {
      renderSphereTalentWorkspace();
      syncFoundationAvailability();
      evaluateGuidedReadiness();
    });
    document.getElementById("guidedLevel").addEventListener("input", syncFoundationAvailability);
     void refreshMethodPathChoices();
    refreshBackgroundChoiceLinks();
     document.getElementById("sheetBackground").onchange = () => { if (!guardPlanningMutation()) return; refreshBackgroundChoiceLinks({backgroundChanged: true}); evaluateGuidedReadiness(); };
     document.getElementById("sheetBackgroundSphere").onchange = () => { if (!guardPlanningMutation()) return; refreshBackgroundChoiceLinks({sphereChanged: true}); evaluateGuidedReadiness(); };
     document.getElementById("sheetBackgroundTalent").onchange = () => { if (planningIsEditable()) evaluateGuidedReadiness(); else guardPlanningMutation(); };
     document.getElementById("sheetOriginInsight").onchange = () => { if (planningIsEditable()) evaluateGuidedReadiness(); else guardPlanningMutation(); };
     document.getElementById("sheetFoundation").onchange = () => { if (planningIsEditable()) evaluateGuidedReadiness(); else guardPlanningMutation(); };
    const helpIds = {
      sphere_priorities: "sheetSphereHelp",
      advancement_skeleton: "sheetTalentHelp",
      insight_priorities: "sheetInsightHelp",
      item_priorities: "sheetItemHelp"
    };
    for (const select of document.querySelectorAll("[data-multi-slot]")) {
      const slotId = select.dataset.multiSlot;
      const category = categoryFor(slotId);
      populateSheetSelect(select, category, "Choose an option to add");
      const help = document.getElementById(helpIds[slotId]);
      if (help) help.textContent = categoryAvailabilityText(category);
    }
    const insightFilter = document.getElementById("sheetInsightAuthorityFilter");
    const insightChoices = ordinaryInsightChoices();
    const filterCounts = new Map();
    insightChoices.forEach(choice => filterCounts.set(insightGroupId(choice), (filterCounts.get(insightGroupId(choice)) || 0) + 1));
    for (const option of insightFilter?.options || []) {
      if (!option.value) continue;
      option.textContent = `${option.textContent.split(" (")[0]} (${filterCounts.get(option.value) || 0})`;
    }
    const insightHelp = document.getElementById("sheetInsightHelp");
    if (insightHelp) insightHelp.textContent = `${insightChoices.length} ordinary Insights are available. Background-Origin Insights remain separate and are not mixed into this browser. Filter Path groups or Sphere facets when useful.`;
    insightFilter.onchange = renderInsightBrowser;
    document.getElementById("sheetInsightHierarchyFilter").onchange = renderInsightBrowser;
    document.getElementById("sheetInsightSphereFilter").onchange = renderInsightBrowser;
    document.getElementById("sheetInsightSearch").oninput = renderInsightBrowser;
    document.getElementById("sheetInsightAdd").onchange = renderInsightAuthorityDetail;
    renderInsightBrowser();
    document.getElementById("sheetTalentSearch").oninput = renderSphereTalentWorkspace;
    const sphereSearch = document.getElementById("sheetSphereSearch");
    if (sphereSearch) sphereSearch.oninput = () => { const catalog = document.getElementById("sheetSphereCatalog"); if (catalog) delete catalog.dataset.browserLimit; renderSphereTalentWorkspace(); };
    document.getElementById("sheetUnassignedTalentSearch").oninput = renderSphereTalentWorkspace;
    renderSphereTalentWorkspace();
    const blocked = characterBuilderOptions.categories.filter(category => category.status !== "offered").map(category => category.label);
    const counts = characterBuilderOptions.owner_surface_counts || {};
    const ordinaryInsightCount = insightChoices.filter(choice => choice.insight_authority?.authority_type !== "Background-Origin").length;
    const backgroundOriginCount = (categoryFor("origin_insight_choice")?.choices || []).filter(choice => choice.insight_authority?.authority_type === "Background-Origin").length;
    const automaticSphereComponentCount = counts.resolved_automatic_base_components ?? counts.automatic_base_components ?? 0;
     status.textContent = `${counts.canonical_spheres || 0} canonical Spheres, ${counts.canonical_talents || 0} canonical Talents, and ${automaticSphereComponentCount} automatic Sphere components loaded. ${ordinaryInsightCount} ordinary Insights and ${backgroundOriginCount} separate Background-Origin Insights are available. ${counts.zero_talent_spheres || 0} zero-talent Spheres are explicitly unavailable in character creation; ${counts.quarantined_records || 0} quarantined records remain unchanged.${blocked.length ? ` Auto remains required for: ${blocked.join(", ")}.` : ""}`;
     const insightCount = document.getElementById("ownerInsightCount");
     if (insightCount) insightCount.textContent = `${ordinaryInsightCount} ordinary · ${backgroundOriginCount} Background-Origin separate`;
     const sphereCount = document.getElementById("ownerSphereCount");
     if (sphereCount) sphereCount.textContent = `${counts.canonical_spheres || 0} canonical Spheres · no planning cap`;
     const diagnosticsCatalog = document.getElementById("diagnosticsCatalogState");
     if (diagnosticsCatalog) diagnosticsCatalog.textContent = `${ordinaryInsightCount} ordinary Insights · ${backgroundOriginCount} Background-Origin · ${counts.canonical_spheres || 0} Spheres · ${counts.canonical_talents || 0} Talents`;
    updatePointBuySummary();
    evaluateGuidedReadiness();
  } catch (error) {
    characterBuilderOptions = null;
    setAbilitySelectState("Verified choices unavailable");
    status.textContent = plainAPIError(error, "The Factory could not load the character-sheet choices.");
    status.classList.add("error");
  }
}

document.getElementById("builderModeQuick").onclick = () => setCreationMode("quick");
document.getElementById("builderModeDetailed").onclick = () => setCreationMode("detailed");
document.getElementById("checkMethodCompatibility")?.addEventListener("click", () => { void requestMethodCompatibility(); });
for (const id of ["guidedName", "guidedConcept", "guidedLevel", "guidedPower", "guidedSource"]) {
  document.getElementById(id)?.addEventListener("input", evaluateGuidedReadiness);
  document.getElementById(id)?.addEventListener("change", evaluateGuidedReadiness);
}
document.querySelectorAll("[data-add-slot]").forEach(button => {
  button.addEventListener("click", () => addSheetChoice(button.dataset.addSlot));
});

function guidedDraftCandidate(projectRows) {
  const rows = Array.isArray(projectRows) ? projectRows : [];
  const interruptedPreRun = rows.find(row =>
    row.status === "stage_1"
    && row.builder_persistence_state === "temporary"
    && Number(row.character_creation_run_count || 0) === 0
  );
  const savedPreRun = rows.find(row =>
    row.status === "stage_1"
    && row.builder_persistence_state === "saved_draft"
    && Number(row.character_creation_run_count || 0) === 0
  );
  return interruptedPreRun
    || savedPreRun
    || rows.find(row => row.status === "draft" && row.revision === 0 && row.builder_persistence_state !== "temporary")
    || null;
}

function guidedStartupPrefersDraft() {
  return guidedStartupRecovery.draft
    && guidedStartupRecovery.draft.builder_persistence_state === "temporary"
    && Number(guidedStartupRecovery.draft.character_creation_run_count || 0) === 0;
}

function hideGuidedStartupRecovery() {
  const host = document.getElementById("guidedStartupRecovery");
  if (host) host.hidden = true;
}

function renderGuidedStartupRecovery(projectRows = []) {
  const host = document.getElementById("guidedStartupRecovery");
  const label = document.getElementById("guidedStartupRecoveryLabel");
  const explanation = document.getElementById("guidedStartupRecoveryExplanation");
  const continueButton = document.getElementById("guidedStartupContinue");
  if (!host || !label || !explanation || !continueButton) return;
  guidedStartupRecovery.draft = guidedDraftCandidate(projectRows);
  const active = guidedStartupPrefersDraft() ? null : guidedStartupRecovery.active;
  if (!active && !guidedStartupRecovery.draft) {
    host.hidden = true;
    return;
  }
  const activeName = active?.project_name || active?.active_run?.project_name || "saved character";
  const interruptedPreRun = guidedStartupPrefersDraft();
  label.textContent = active
    ? `Saved active build: ${activeName}`
    : interruptedPreRun
      ? `Saved character setup: ${guidedStartupRecovery.draft.working_name || "Unnamed character"}`
      : `Saved draft: ${guidedStartupRecovery.draft.working_name || "Unnamed character"}`;
  explanation.textContent = active
    ? "Your active build is still saved. Continue only when you want to open it."
    : interruptedPreRun
      ? "Project setup finished before the page closed. Continue this exact character without creating another project."
      : "Your saved draft is still here. Continue only when you want to open it.";
  continueButton.disabled = false;
  host.hidden = false;
}

async function continueGuidedStartupRecovery() {
  const continueButton = document.getElementById("guidedStartupContinue");
  if (!continueButton || continueButton.disabled) return;
  const navigationGeneration = guidedNavigationGeneration;
  continueButton.disabled = true;
  try {
    const active = guidedStartupPrefersDraft() ? null : guidedStartupRecovery.active;
    if (active?.active_run) {
      await restoreGuidedActiveBuild(active.project_id, active.active_run.run_id, false, navigationGeneration);
    } else if (guidedStartupRecovery.draft) {
      await resumeGuidedDraft([guidedStartupRecovery.draft], navigationGeneration);
    }
  } catch (error) {
    if (guidedNavigationIsCurrent(navigationGeneration)) {
      setGuidedStatus(`Your saved character is safe. Resume failed while ${error.message || String(error)}.`, true);
    }
  } finally {
    if (guidedNavigationIsCurrent(navigationGeneration)) continueButton.disabled = false;
  }
}

document.getElementById("guidedStartupContinue")?.addEventListener("click", () => { void continueGuidedStartupRecovery(); });
document.getElementById("guidedStartupNew")?.addEventListener("click", () => { void startNewCharacter("quick"); });

async function resumeGuidedDraft(projectRows, navigationGeneration = guidedNavigationGeneration) {
  let resumeStage = "finding the saved draft";
  try {
  const candidate = guidedDraftCandidate(projectRows);
  if (!candidate || !guidedNavigationIsCurrent(navigationGeneration)) return false;
  resumeStage = "reading the saved project";
  const detail = await api(`/api/projects/${encodeURIComponent(candidate.project_id)}`);
  if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
  resumeStage = "reading the saved character fields";
  const locks = Object.fromEntries((detail.project.user_locks || []).map(lock => [lock.field, lock.value]));
  const owns = key => Object.prototype.hasOwnProperty.call(locks, key);
  if (!owns("concept") || !owns("target_cl") || !owns("power_band")) return false;

  resumeStage = "reading the saved build preference";
  const preference = await api(`/api/projects/${encodeURIComponent(candidate.project_id)}/character-creation/preference`);
  if (!guidedNavigationIsCurrent(navigationGeneration)) return false;

  resumeStage = "restoring the saved character fields";
  selectedProject = candidate.project_id;
  guidedProjectId = candidate.project_id;
  guidedAutogenSeed = null;
  guidedProjectLifecycle = detail.builder_lifecycle || candidate.builder_lifecycle || {persistence_state: "legacy_persistent", is_temporary: false, display_label: "Saved / existing", plain_explanation: "This existing character is retained."};
  renderGuidedPersistence();
  const restoredName = owns("character.identity.display_name") ? locks["character.identity.display_name"] : candidate.working_name;
  const guidedName = document.getElementById("guidedName");
  if (guidedName) guidedName.value = TianxiaSheetViewModel.isPlaceholderName(restoredName) ? "" : String(restoredName || "");
  document.getElementById("guidedConcept").value = String(locks.concept || "");
  document.getElementById("guidedSource").value = locks.source_reference === "Original character" ? "" : String(locks.source_reference || "");
  document.getElementById("guidedLevel").value = String(locks.target_cl);
  document.getElementById("guidedPower").value = String(locks.power_band);
  restoreCharacterSheet(locks);
  resumeStage = "opening complete-character build mode";
  if (candidate.builder_persistence_state === "temporary" && Number(candidate.character_creation_run_count || 0) === 0) {
    setGuidedRoute("LOCAL_AI");
    updateGuidedModeUI();
  } else {
    applyGuidedExecutionPreference(preference.execution_mode);
  }
  setGuidedStatus(`Resumed ${TianxiaSheetViewModel.isPlaceholderName(restoredName) ? "saved draft" : restoredName}. Choose a complete-character build mode.`);
   showScreen("builder", {preserveNavigation: true});
   setGuidedStep(3, {preserveNavigation: true});
   hideGuidedStartupRecovery();
   return true;
  } catch (error) {
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    const detail = error && error.message ? error.message : String(error);
    throw new Error(`${resumeStage}: ${detail.slice(0, 300)}`);
  }
}

function gmCharacterLibraryIsResumableDraft(character) {
  return character?.lifecycle?.persistence_state === "saved_draft"
    && !character.workflow?.active_run
    && !character.workflow?.latest_run;
}

async function resumeCharacterLibraryDraft(projectId, navigationGeneration = guidedNavigationGeneration) {
  if (!projectId || !guidedNavigationIsCurrent(navigationGeneration)) return false;
  try {
    const projectRows = await api("/api/projects");
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    const project = Array.isArray(projectRows)
      ? projectRows.find(row => row?.project_id === projectId)
      : null;
    if (!project) return false;
    return await resumeGuidedDraft([project], navigationGeneration);
  } catch (error) {
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    setGuidedStatus(plainAPIError(error, "The saved draft could not be opened. Your character was kept safe."), true);
    return false;
  }
}

function guidedRecoveryDescription(recovery) {
  const run = recovery?.active_run || recovery?.latest_run;
  return run?.owner_descriptive_fields?.resolved || {};
}

async function restoreGuidedActiveBuild(projectId = null, runId = null, inspect = false, navigationGeneration = guidedNavigationGeneration) {
  try {
    const recoveries = await api("/api/character-builder/recovery");
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    const recovery = projectId
      ? recoveries.find(row => row.project_id === projectId)
      : recoveries.find(row => row.active_run);
    if (!recovery?.active_run) return false;
    const active = recovery.active_run;
    if (runId && active.run_id !== runId) return false;
    const detail = await api(`/api/projects/${encodeURIComponent(recovery.project_id)}`);
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    const locks = Object.fromEntries((detail.project.user_locks || []).map(lock => [lock.field, lock.value]));
    const restoredRun = await api(`/api/character-creation/runs/${encodeURIComponent(active.run_id)}`);
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    selectedProject = recovery.project_id;
    guidedProjectId = recovery.project_id;
    guidedAutogenSeed = null;
    guidedProjectLifecycle = detail.builder_lifecycle || {persistence_state: "temporary", is_temporary: true, display_label: "Temporary", plain_explanation: "Retained while this build is incomplete."};
    guidedRecovery = recovery;
    renderGuidedPersistence();
    const restoredResolved = restoredRun?.owner_descriptive_fields?.resolved;
    const resolved = restoredResolved && typeof restoredResolved === "object"
      ? restoredResolved
      : guidedRecoveryDescription(recovery);
    document.getElementById("guidedName").value = String(locks["character.identity.display_name"] || ((resolved.identity || {}).name && active.status === "CLEAN_AND_FINALIZED" ? resolved.identity.name : ""));
    document.getElementById("guidedConcept").value = String(locks.concept || "");
    document.getElementById("guidedSource").value = locks.source_reference === "Original character" ? "" : String(locks.source_reference || "");
    if (locks.target_cl) document.getElementById("guidedLevel").value = String(locks.target_cl);
    if (locks.power_band) document.getElementById("guidedPower").value = String(locks.power_band);
    restoreCharacterSheet(locks);
    guidedRun = restoredRun;
     applyGuidedExecutionPreference(active.execution_mode, guidedRun);
    resetGuidedResponseSource("The run was restored from the Factory. If a response file was not submitted, choose it again; the server-side run and diagnostics remain saved.");
    showScreen("builder", {preserveNavigation: true});
    renderGuidedCandidate(guidedRun);
    hideGuidedStartupRecovery();
    if (inspect && ["WAITING_FOR_RESPONSE", "PREPARING_REQUEST"].includes(guidedRun.status)) {
      document.getElementById("guidedBuildProgress")?.scrollIntoView({behavior: "smooth", block: "center"});
    }
    return true;
  } catch (error) {
    if (!guidedNavigationIsCurrent(navigationGeneration)) return false;
    setGuidedStatus(plainAPIError(error, "The active build could not be restored. The server-side run was kept."), true);
    return false;
  }
}

function recoveryActionButton(label, handler, primary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (primary) button.className = "primary-action";
  button.addEventListener("click", event => { event.stopPropagation(); void handler(); });
  return button;
}

function renderActiveBuildRecovery(characters = []) {
  const host = document.getElementById("activeBuildRecovery");
  if (!host) return;
  clearNode(host);
  const recoveries = characters
    .filter(row => row.workflow?.active_run)
    .sort((a, b) => activeBuildRecency(b).localeCompare(activeBuildRecency(a)))
    .map(row => ({
      ...row.workflow,
      project_name: row.name || row.workflow.project_name,
      character_title: row.title || null,
      target_cl: row.target_cl ?? null,
      background: row.background || null,
      paths: Array.isArray(row.paths) ? row.paths : [],
    }));
  if (!recoveries.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const heading = document.createElement("h3"); heading.textContent = "Characters in progress"; host.appendChild(heading);
  const intro = document.createElement("p"); intro.textContent = "Your progress is saved. You can leave this screen and come back whenever you are ready."; host.appendChild(intro);
  for (const recovery of recoveries) {
    const run = recovery.active_run;
    const card = document.createElement("article");
    const title = document.createElement("strong");
    title.textContent = `${recovery.project_name || "Character in progress"}${recovery.character_title ? ` — ${recovery.character_title}` : ""}`;
    const facts = [
      recovery.target_cl ? `CL ${recovery.target_cl}` : null,
      recovery.background,
      recovery.paths.length ? recovery.paths.join(" / ") : null,
    ].filter(Boolean);
    const meta = document.createElement("p"); meta.className = "active-build-facts"; meta.textContent = facts.join(" · ");
    meta.hidden = !facts.length;
    const status = String(run.status || "").toUpperCase();
    const ownerMessage = status === "WAITING_FOR_RESPONSE"
      ? "The character request is ready. Continue when you have the AI response."
      : status === "NEEDS_REVIEW"
        ? "The draft is ready for you to review."
        : ["READY_TO_FINALIZE", "FINALIZE_READY", "CLEAN"].includes(status)
          ? "The character is ready for a final review."
          : "Continue from where you left off.";
    const touched = String(run.updated_at || run.created_at || "").replace("T", " ").replace(/\.\d+/, "").replace(/(Z|\+00:00)$/, " UTC");
    // One compact row per draft (owner 2026-09-27: "can we make these boxes much smaller and take up way less space"):
    // name and facts, a short status with the date, the buttons, and the advanced details folded behind "⋯".
    const shortStatus = status === "WAITING_FOR_RESPONSE" ? "Waiting for the AI response"
      : status === "NEEDS_REVIEW" ? "Ready to review"
        : ["READY_TO_FINALIZE", "FINALIZE_READY", "CLEAN"].includes(status) ? "Ready to finalize" : "In progress";
    const detail = document.createElement("span"); detail.className = "recovery-when";
    detail.textContent = touched ? `${shortStatus} · ${touched.replace(/:\d\d UTC$/, " UTC")}` : shortStatus;
    detail.title = touched ? `${ownerMessage} Last worked on ${touched}.` : ownerMessage;
    const actions = document.createElement("div"); actions.className = "recovery-actions";
    actions.append(
      recoveryActionButton("Continue", () => restoreGuidedActiveBuild(recovery.project_id, run.run_id), true),
      recoveryActionButton("View Character", async () => { selectedProject = recovery.project_id; showScreen("projects"); await openOwnerCharacterSheet(recovery.project_id); }),
    );
    const inspectDetails = document.createElement("details"); inspectDetails.className = "recovery-inspect-disclosure";
    const inspectSummary = document.createElement("summary"); inspectSummary.textContent = "⋯"; inspectSummary.title = "Advanced details";
    inspectSummary.setAttribute("aria-label", "Advanced details");
    const technicalIdentity = document.createElement("p"); technicalIdentity.className = "technical-build-identity";
    technicalIdentity.textContent = `Run ${run.run_id} · ${run.status} · Step ${run.owner_stage || run.stage}. ${run.next_legal_action}`;
    const inspectActions = document.createElement("div"); inspectActions.className = "recovery-actions";
    inspectActions.append(recoveryActionButton("Inspect Build / Errors", () => restoreGuidedActiveBuild(recovery.project_id, run.run_id, true)));
    inspectDetails.append(inspectSummary, technicalIdentity, inspectActions);
    card.className = "recovery-row";
    const main = document.createElement("div"); main.className = "recovery-main";
    main.append(title, meta);
    card.append(main, detail, actions, inspectDetails); host.appendChild(card);
  }
}

document.getElementById("guidedBriefContinue")?.addEventListener("click", () => {
  setGuidedStep(2);
  setGuidedStatus("Brief saved in this owner session. Choose zero to three Path requirements; the real project is created when you continue into the AI route.");
});
document.getElementById("ownerPathsBack")?.addEventListener("click", () => setGuidedStep(1));

document.getElementById("guidedCreate").addEventListener("submit", async event => {
  event.preventDefault();
  if (guidedWizardStep !== 2) {
    setGuidedStep(2);
    return;
  }
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  setGuidedStatus("Preparing your character. This may take a moment...");
  try {
    const readiness = evaluateGuidedReadiness();
    if (!readiness.valid) {
      focusGuidedBlocker(readiness.blockers[0]);
      throw new Error(readiness.blockers[0].message);
    }
    if (!characterBuilderOptions) throw new Error("The character choices are still loading. Try the button once more.");
    const packs = await api("/api/content-packs");
    // Preserve the trusted-core owner default from the accepted Factory UI.
    // CharacterBuilderService resolves the immutable locks locally, while this
    // preflight keeps the friendly setup failure before project creation.
    let chosen = packs.filter(pack =>
      pack.trust_state === "trusted_core" && pack.authority === "canonical" && pack.record_count > 0
    );
    if (!chosen.length) chosen = packs.filter(pack => pack.selectable === true && pack.authority === "canonical");
    if (!chosen.length) chosen = packs.filter(pack => pack.selectable === true);
    if (!chosen.length) {
      throw new Error("No ready-to-use rules were found. This is a Factory setup problem, not something you need to fix.");
    }
    const name = document.getElementById("guidedName").value.trim();
    const concept = document.getElementById("guidedConcept").value.trim();
    const seed = document.getElementById("guidedSeed")?.value.trim() || "";
    if (seed && !/^[A-Za-z0-9._:-]{1,64}$/.test(seed)) throw new Error("A seed is 1-64 letters, digits, dots, dashes, colons or underscores.");
    const source = document.getElementById("guidedSource").value.trim();
    const level = Number(document.getElementById("guidedLevel").value);
    const power = document.getElementById("guidedPower").value;
    const detailed = creationMode === "detailed";
    const created = await api("/api/character-builder/projects", {
      method: "POST",
      body: JSON.stringify({
        working_name: name,
        concept,
        source_reference: source || null,
        target_cl: level,
        power_band: power,
        creation_mode: creationMode,
        // Complete-character planning is provider-assisted in all three
        // supported modes. Record that route explicitly so the typed planner
        // may emit one causal initial Sphere/free-Talent pair per acquisition.
        generation_route: "ai_bootstrap",
        ability_scores: detailed ? collectAbilityScores() : {},
        selections: detailed ? collectSheetSelections() : {},
        sphere_priority_ids: detailed ? Array.from(selectedSet("sphere_priorities")) : [],
        talent_priority_ids: detailed ? Array.from(selectedSet("advancement_skeleton")) : [],
        method_planning_mode: detailed ? methodPlanningMode() : "AUTO",
        method_preference_id: detailed && methodPlanningMode() === "PREFERENCE" ? (document.getElementById("sheetMethod").value || null) : null,
        method_route_choice: detailed ? methodRouteChoiceForSubmission() : null,
        method_learning_note: detailed && methodPlanningMode() === "EXACT" ? (document.getElementById("sheetMethodLearningNote")?.value.trim() || null) : null,
        gear_preference_ids: selectedGearPreferences(),
        ...(seed ? {autogen_seed: seed} : {})
      })
    });
    selectedProject = created.project_id;
    guidedProjectId = created.project_id;
    guidedAutogenSeed = seed || null;
    guidedProjectLifecycle = created.builder_lifecycle || {persistence_state: "temporary", is_temporary: true, display_label: "Temporary", plain_explanation: "Disappears if abandoned or the Factory closes before you save it."};
    renderGuidedPersistence();
    const firstCycle = await api(`/api/character-builder/projects/${encodeURIComponent(created.project_id)}/normal-first-cycle-catalog-choice-lock`, {method: "POST", body: "{}"});
    await loadProjects();
    const lockedCount = Object.values(created.character_sheet?.locked_choices || {}).reduce((total, values) => total + (Array.isArray(values) ? values.length : 0), 0)
      + (created.character_sheet?.method_planning_mode === "EXACT" ? 1 : 0);
    const planning = created.character_sheet?.planning_preferences || {};
    const grantAccounting = firstCycle.grant_plan?.grant_accounting || {};
    const acquiredSphereCount = (firstCycle.grant_plan?.acquired_canonical_sphere_ids || []).length;
    const ordinaryTalentCount = (grantAccounting.ordinary_talent_ids || []).length;
    const preferenceCount = (planning.sphere_priority_ids || []).length + (planning.talent_priority_ids || []).length
      + (planning.method_preference_id ? 1 : 0);
    const ownerLabel = name || "AI-proposed character";
     const descriptiveNote = seed
       ? `Seed ${seed} will make every choice, including the name and concept; no AI is used, whichever build button you press.`
       : name || concept ? "Your supplied wording is locked for review." : "Name and Concept are delegated; the AI will propose both for your review.";
    setGuidedStatus(`${ownerLabel} is temporary and ready. ${descriptiveNote} ${lockedCount} exact ${lockedCount === 1 ? "choice" : "choices"}; ${preferenceCount} planning ${preferenceCount === 1 ? "preference" : "preferences"}; ${acquiredSphereCount} first-cycle ${acquiredSphereCount === 1 ? "Sphere" : "Spheres"} and ${ordinaryTalentCount} ordinary Talent ${ordinaryTalentCount === 1 ? "slot" : "slots"} server-validated and frozen. Choose a complete-character build mode.`);
     setGuidedStep(3);
     updateGuidedModeUI();
   } catch (error) {
     setGuidedStatus(plainAPIError(error, "The Factory could not start this character. Send me a screenshot and I will fix it."), true);
   } finally {
     if (submit) submit.disabled = !planningIsEditable();
     renderPlanningFreeze();
   }
});

document.getElementById("guidedSaveDraft").onclick = async () => {
  if (!guidedProjectId || !guidedProjectLifecycle?.is_temporary) return;
  try {
    guidedProjectLifecycle = await api(`/api/character-builder/projects/${encodeURIComponent(guidedProjectId)}/save-draft`, {method: "POST", body: "{}"});
    renderGuidedPersistence();
    await loadProjects();
    setGuidedStatus("Saved Draft — this character will be retained for later.");
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The draft could not be saved."), true);
  }
};

function setGuidedRoute(route) {
  const selected = ["LOCAL_AI", "STANDARD_API", "MANUAL_CHAT"].includes(route) ? route : "LOCAL_AI";
  guidedSelectedRoute = selected;
  const input = document.querySelector(`input[name="guidedExecutionMode"][value="${selected}"]`);
  if (input) input.checked = true;
  for (const button of document.querySelectorAll("[data-guided-route]")) {
    const active = button.dataset.guidedRoute === selected;
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  }
  return selected;
}

function preferredGuidedRoute(executionMode, run = null) {
  if (executionMode === "MANUAL_CHAT") return "MANUAL_CHAT";
  const directProviderId = [
    run?.transport?.provider_id,
    run?.transport?.local_correction?.provider_id,
    run?.provider_id,
    run?.receipt?.provider_id,
  ].find(value => typeof value === "string" && value);
  const attemptProviderId = Array.isArray(run?.attempt_history)
    ? run.attempt_history.slice().reverse().flatMap(attempt => [
      attempt?.transport?.provider_id,
      attempt?.transport?.local_correction?.provider_id,
      attempt?.binding?.transport?.provider_id,
      attempt?.binding?.transport?.local_correction?.provider_id,
      attempt?.provider_id,
    ]).find(value => ["local", "lemonade"].includes(value))
    : null;
  const providerId = directProviderId || attemptProviderId || [
    guidedProviderStatus?.provider_id,
    guidedLocalStatus?.provider?.provider_id,
  ].find(value => typeof value === "string" && value);
  if (["local", "lemonade"].includes(providerId)) return "LOCAL_AI";
  if (executionMode === "STANDARD_API" || executionMode === "AUTO_FINALIZE_WHEN_CLEAN") return "STANDARD_API";
  return "LOCAL_AI";
}

function guidedLocalBuildMode() {
  return document.querySelector('input[name="guidedLocalBuildMode"]:checked')?.value === "LOCAL_PREVIEW"
    ? "LOCAL_PREVIEW"
    : "LOCAL_AUTO";
}

function setGuidedLocalBuildMode(mode) {
  const selected = mode === "LOCAL_PREVIEW" ? "LOCAL_PREVIEW" : "LOCAL_AUTO";
  const input = document.querySelector(`input[name="guidedLocalBuildMode"][value="${selected}"]`);
  if (input) input.checked = true;
  return selected;
}

function applyGuidedExecutionPreference(executionMode, run = null) {
  const route = setGuidedRoute(preferredGuidedRoute(executionMode, run));
  if (route === "LOCAL_AI") setGuidedLocalBuildMode(executionMode === "AUTO_FINALIZE_WHEN_CLEAN" ? "LOCAL_AUTO" : "LOCAL_PREVIEW");
  const capability = document.getElementById("guidedAutoFinalizeCapability");
  if (capability) capability.checked = route === "STANDARD_API" && executionMode === "AUTO_FINALIZE_WHEN_CLEAN";
  const localConsent = document.getElementById("guidedLocalAutoFinalizeConsent");
  if (localConsent && route !== "LOCAL_AI") localConsent.checked = false;
  updateGuidedModeUI();
  return route;
}

function guidedExecutionMode() {
  const selected = document.querySelector('input[name="guidedExecutionMode"]:checked')?.value || guidedSelectedRoute || "LOCAL_AI";
  guidedSelectedRoute = ["LOCAL_AI", "STANDARD_API", "MANUAL_CHAT"].includes(selected) ? selected : "LOCAL_AI";
  return guidedSelectedRoute === "STANDARD_API" && document.getElementById("guidedAutoFinalizeCapability")?.checked
    ? "AUTO_FINALIZE_WHEN_CLEAN"
    : guidedSelectedRoute === "LOCAL_AI" ? (guidedLocalBuildMode() === "LOCAL_AUTO" ? "AUTO_FINALIZE_WHEN_CLEAN" : "STANDARD_API") : guidedSelectedRoute;
}

function updateGuidedModeUI() {
  const mode = guidedExecutionMode();
  const route = guidedSelectedRoute;
  const consentPanel = document.getElementById("guidedAutoConsentPanel");
  const localConsentPanel = document.getElementById("guidedLocalAutoConsentPanel");
  const manual = document.getElementById("guidedManualTransfer");
  const manualDetails = document.getElementById("guidedManualFallbackDetails");
  const localSetup = document.getElementById("guidedLocalSetup");
  const providerSetup = document.getElementById("guidedProviderSetup");
  const advancedOptions = document.getElementById("guidedAdvancedAIOptions");
  const localTab = document.getElementById("guidedLocalRouteTab");
  const manualTab = document.getElementById("guidedManualRouteTab");
  const providerTab = document.getElementById("guidedProviderRouteTab");
  if (consentPanel) consentPanel.hidden = !(route === "STANDARD_API" && mode === "AUTO_FINALIZE_WHEN_CLEAN");
  if (localConsentPanel) localConsentPanel.hidden = !(route === "LOCAL_AI" && mode === "AUTO_FINALIZE_WHEN_CLEAN");
  if (manual) manual.hidden = route !== "MANUAL_CHAT" || !guidedRun;
  if (manualDetails) manualDetails.open = route === "MANUAL_CHAT";
  if (localSetup) localSetup.hidden = route !== "LOCAL_AI";
  if (providerSetup) providerSetup.hidden = route !== "STANDARD_API";
  if (advancedOptions && route === "STANDARD_API") advancedOptions.open = true;
  if (localTab) {
    localTab.setAttribute("aria-selected", route === "LOCAL_AI" ? "true" : "false");
    localTab.tabIndex = route === "LOCAL_AI" ? 0 : -1;
  }
  if (manualTab) {
    manualTab.setAttribute("aria-selected", route === "MANUAL_CHAT" ? "true" : "false");
    manualTab.tabIndex = route === "MANUAL_CHAT" ? 0 : -1;
  }
  if (providerTab) {
    providerTab.setAttribute("aria-selected", route === "STANDARD_API" ? "true" : "false");
    providerTab.tabIndex = route === "STANDARD_API" ? 0 : -1;
  }
  const start = document.getElementById("guidedStartBuild");
  if (start) start.textContent = route === "MANUAL_CHAT"
    ? "Prepare Complete Request"
    : route === "LOCAL_AI"
      ? mode === "AUTO_FINALIZE_WHEN_CLEAN" ? "Build & save automatically" : "Build Local AI preview"
      : "Build Character";
}

function evaluateGuidedReadiness() {
  const blockers = [];
  const name = document.getElementById("guidedName")?.value.trim() || "";
  const concept = document.getElementById("guidedConcept")?.value.trim() || "";
  const level = Number(document.getElementById("guidedLevel")?.value || 0);
  if (!characterBuilderOptions) blockers.push({fieldId: "guidedName", message: "Installed character choices are still loading."});
  if (!Number.isInteger(level) || level < 1 || level > 20) blockers.push({fieldId: "guidedLevel", message: "Intended level must be from 1 through 20."});
  if (creationMode === "detailed" && characterBuilderOptions) {
    const selectedMethod = methodPlanningMode() === "EXACT" ? methodChoiceFor() : null;
    if (methodPlanningMode() !== "AUTO" && !methodChoiceFor()) blockers.push({fieldId: "sheetMethod", message: "Choose a Method or choose for me."});
    if (selectedMethod && !selectedMethod.method_planning?.direct_initial_acquisition_available) {
      if (!methodRouteChoiceForSubmission()) blockers.push({fieldId: "sheetMethodRouteChoice", message: "Choose how this character learned the selected Method."});
      const route = selectedMethod.method_planning?.owner_route_options?.find(row => row.choice_id === methodRouteChoiceForSubmission());
      if (route?.requires_explanation && !document.getElementById("sheetMethodLearningNote")?.value.trim()) {
        blockers.push({fieldId: "sheetMethodLearningNote", message: "Describe the Custom Method learning route."});
      }
    }
    const selectedPaths = selectedPathIds();
    const grantedPathIds = new Set(selectedMethod?.related_choice_ids || []);
    if (selectedMethod && !grantedPathIds.size) {
      blockers.push({fieldId: "sheetMethod", message: "The selected Cultivation Method grants no legal starting Path for initial creation."});
    }
    if (selectedMethod && selectedPaths.some(pathId => !grantedPathIds.has(pathId))) {
      blockers.push({fieldId: "sheetPaths", message: "The selected Method must support every selected Path."});
    }
    const selectedBackground = document.getElementById("sheetBackground")?.value || "";
    const selectedSphere = document.getElementById("sheetBackgroundSphere")?.value || "";
    const selectedTalent = document.getElementById("sheetBackgroundTalent")?.value || "";
    if (selectedBackground && (selectedSphere || selectedTalent)) {
      const exactRoutes = exactBackgroundRoutes(selectedBackground);
      const exact = exactRoutes.some(route =>
        (!selectedSphere || route.background_sphere_choice_id === selectedSphere)
        && (!selectedTalent || route.background_talent_choice_id === selectedTalent)
      );
      if (!exact) blockers.push({fieldId: "sheetBackgroundTalent", message: "The selected Background Sphere and Talent are not one exact published Background route."});
    }
    const pointBuy = collectAbilityScores();
    const costs = characterBuilderOptions.point_buy.costs;
    const spent = Object.values(pointBuy).reduce((total, value) => total + (value === null ? 0 : Number(costs[String(value)] || 0)), 0);
    if (spent > characterBuilderOptions.point_buy.budget) blockers.push({fieldId: "abilitySTR", message: `Ability locks use ${spent} points; reduce them to ${characterBuilderOptions.point_buy.budget} or fewer.`});
    for (const sphereId of selectedSet("sphere_priorities")) {
      const sphere = choiceFor("sphere_priorities", sphereId);
      if (!sphere || sphere.planning_priority_available === false) blockers.push({fieldId: "sheetSphereAdd", message: `${sphere?.name || sphereId} cannot be prioritized: ${sphere?.unavailable_reason || "not creator-ready"}`});
    }
    for (const talentId of selectedSet("advancement_skeleton")) {
      const talent = choiceFor("advancement_skeleton", talentId);
      const state = talent ? canonicalTalentAvailability(talent) : {selectable: false, reason: "not in current canonical authority"};
      if (!state.selectable) blockers.push({fieldId: "sheetTalentOptions", message: `${talent?.canonical_name || talent?.name || talentId} cannot be prioritized: ${state.reason}`});
      if (talent?.owning_canonical_sphere_id && !selectedSet("sphere_priorities").has(talent.owning_canonical_sphere_id)) blockers.push({fieldId: "sheetSphereAdd", message: `Prioritize ${talent.owning_canonical_sphere_name} before ${talent.canonical_name || talent.name}.`});
    }
  }
  const valid = blockers.length === 0;
  const editable = planningIsEditable();
  const reason = document.getElementById("guidedBuildButtonReason");
  if (reason) {
    reason.textContent = !editable
      ? PLANNING_FREEZE_MESSAGE
      : !valid
        ? (blockers[0]?.message || "Complete the required planning choices before creating the project.")
        : "Ready — all required planning choices are complete.";
  }
  const button = document.getElementById("guidedBuildButton");
  if (button) button.disabled = !valid || !editable;
  return {valid, blockers};
}

function focusGuidedBlocker(blocker) {
  if (!blocker?.fieldId) return;
  const target = document.getElementById(blocker.fieldId);
  if (!target) return;
  if (target.closest("#characterSheetPanel") && creationMode !== "detailed") setCreationMode("detailed");
  target.focus?.();
  target.scrollIntoView?.({behavior: "smooth", block: "center"});
}

function appendCandidateLine(host, label, value, className = "") {
  const row = document.createElement("div");
  if (className) row.className = className;
  const strong = document.createElement("strong"); strong.textContent = label;
  const span = document.createElement("span"); span.textContent = value;
  row.append(strong, span); host.appendChild(row);
}

function findNestedObject(root, key, depth = 0) {
  if (!root || typeof root !== "object" || depth > 8) return null;
  if (Object.prototype.hasOwnProperty.call(root, key) && root[key] && typeof root[key] === "object") return root[key];
  for (const value of Object.values(root)) {
    const found = findNestedObject(value, key, depth + 1);
    if (found) return found;
  }
  return null;
}

function recordName(value) {
  if (value === null || value === undefined) return "Unspecified";
  if (typeof value === "string") return value;
  return value.display_name || value.name || value.canonical_name || value.talent_name || value.sphere_name || value.record_id || value.id || pretty(value);
}

function candidateList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(recordName);
  if (typeof value === "object") return Object.values(value).flatMap(item => Array.isArray(item) ? item.map(recordName) : [recordName(item)]);
  return [String(value)];
}

function hasSubstantiveCommit(commit) {
  const substantive = value => {
    if (value === null || value === undefined) return false;
    if (typeof value === "string") return value.trim().length > 0;
    if (Array.isArray(value)) return value.some(substantive);
    if (typeof value === "object") return Object.values(value).some(substantive);
    return true;
  };
  if (!commit || typeof commit !== "object" || Array.isArray(commit)) return false;
  return Object.values(commit).some(substantive);
}

function descriptiveFieldValue(projection, field) {
  const resolved = projection?.resolved || {};
  const proposed = projection?.proposed || {};
  if (field === "name") return String(resolved.identity?.name || proposed.identity?.name || "");
  if (field === "title") return String(resolved.identity?.title || proposed.identity?.title || "");
  return String(resolved.concept || proposed.concept || "");
}

function renderGuidedDescriptiveFields(run, editable = false) {
  const projection = run?.owner_descriptive_fields || {};
  const name = document.getElementById("guidedProposedName");
  const title = document.getElementById("guidedProposedTitle");
  const concept = document.getElementById("guidedProposedConcept");
  const status = document.getElementById("guidedDescriptiveFieldsStatus");
  const save = document.getElementById("guidedSaveDescriptiveFields");
  if (name) {
    name.value = descriptiveFieldValue(projection, "name");
    name.disabled = !editable;
  }
  if (title) {
    title.value = descriptiveFieldValue(projection, "title");
    title.disabled = !editable;
  }
  if (concept) {
    concept.value = descriptiveFieldValue(projection, "concept");
    concept.disabled = !editable;
  }
  if (save) save.disabled = !editable;
  if (status) {
    status.textContent = run?.finalize_in_progress === true || guidedFinalizeInFlight
      ? "Finalizing — this takes a few minutes, and the wording can't change now"
      : projection.state === "OWNER_ACCEPTED"
      ? "Your wording is saved"
      : projection.state === "AI_PROPOSED"
        ? "AI wording in use — edit it here if you like; nothing is required"
        : "No wording proposed — add some if you like; the character can still be finalized";
    status.classList.toggle("success", projection.state === "OWNER_ACCEPTED");
    status.classList.toggle("warning", projection.state === "AI_PROPOSED");
  }
}

function guidedRunOwnerMessage(run) {
  if (!run) return "No complete-character build has started.";
  const submission = run.submission_error || run.validation?.last_submission_error;
  if (submission) return ownerDiagnosticMessage(submission, "The submitted response could not be accepted.");
  const owner = ownerViewFor(run);
  const ownerDecisions = Array.isArray(owner.decisions) ? owner.decisions : [];
  const ownerBlockers = Array.isArray(owner.blockers) ? owner.blockers : [];
  const blockers = (ownerDecisions.length ? ownerDecisions : ownerBlockers.length ? ownerBlockers : (run.blockers || []))
    .map(row => ownerDiagnosticMessage(row, "The candidate needs one correction before review."));
  if (blockers.length) return blockers.join(" ");
  if (run.status === "WAITING_FOR_RESPONSE") return "The complete request is ready. Load one matching response file or paste one complete response.";
  if (run.status === "PREPARING_REQUEST") return "The Factory is preparing the complete request. The saved run remains available if the screen is changed.";
  if (run.status === "READY_FOR_REVIEW") return "The complete candidate is ready for your review. No canonical character change has occurred.";
  if (run.status === "NEEDS_REVIEW") return "The candidate needs review before it can be finalized. No canonical character change has occurred.";
  if (run.status === "CANCELLED") return "This build was cancelled. No canonical character change was committed.";
  if (run.status === "REVISED") return "A replacement request is ready. Load one response for the revised run.";
  if (run.status === "CLEAN_AND_FINALIZED") return "The character is finalized and ready in Character Sheets.";
  return `The build is ${friendlyLabel(run.status || "unknown")}. Open Developer / Diagnostics for the recorded details.`;
}

function guidedAIPerformanceSummary(run) {
  const transports = [run?.transport];
  for (const attempt of Array.isArray(run?.attempt_history) ? run.attempt_history : []) {
    transports.push(attempt?.transport, attempt?.binding?.transport);
  }
  const seen = new Set();
  const calls = [];
  for (const transport of transports) {
    if (!transport || transport.provider_called !== true || !transport.model) continue;
    const identity = transport.provider_request_sha256
      || `${transport.model}:${transport.purpose || "unknown"}:${transport.provider_response_sha256 || "unknown"}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    calls.push(transport);
  }
  if (!calls.length) return null;
  const sumKnown = key => {
    const values = calls.map(call => call.usage?.[key]).filter(Number.isFinite);
    return values.length ? values.reduce((total, value) => total + value, 0) : null;
  };
  const durations = calls.map(call => call.performance?.duration_ms).filter(Number.isFinite);
  const promptTokens = sumKnown("prompt_tokens");
  const completionTokens = sumKnown("completion_tokens");
  const totalTokens = sumKnown("total_tokens");
  const durationMs = durations.length ? durations.reduce((total, value) => total + value, 0) : null;
  const models = [...new Set(calls.map(call => call.model))];
  const durationLabel = durationMs === null
    ? "time unavailable"
    : durationMs >= 60000
      ? `${Math.floor(durationMs / 60000)}m ${Math.round((durationMs % 60000) / 1000)}s`
      : `${(durationMs / 1000).toFixed(1)}s`;
  const tokenLabel = totalTokens === null
    ? "token count unavailable"
    : `${totalTokens.toLocaleString()} tokens (${(promptTokens || 0).toLocaleString()} input + ${(completionTokens || 0).toLocaleString()} output)`;
  const speed = durationMs && completionTokens !== null
    ? ` · ${(completionTokens / (durationMs / 1000)).toFixed(2)} output tokens/sec`
    : "";
  return `${models.join(" + ")} · ${calls.length} AI call${calls.length === 1 ? "" : "s"} · ${tokenLabel} · ${durationLabel}${speed}`;
}

function guidedResponseResultMessage(run) {
  const diagnostic = guidedResponseProcessingDiagnostic(run);
  const source = guidedResponseSourceName();
  const prefix = source === "none" ? "The stored response" : `“${source}”`;
  if (diagnostic) {
    if (diagnostic.stage === "SOURCE_TRANSPORT" || diagnostic.category === "SOURCE_TRANSPORT") return `${prefix} was selected, but the Factory could not accept it at the upload/transport boundary.`;
    if (diagnostic.boundary === "JSON_PARSING" || diagnostic.code === "CG1_PLAN_JSON_INVALID") return `${prefix} was received, but its JSON syntax could not be parsed.`;
    if (["RESPONSE_SHAPE", "RESPONSE_SCHEMA", "JSON_SCHEMA"].includes(diagnostic.boundary || diagnostic.stage || diagnostic.category)) return `${prefix} was received and parsed as JSON, but its response contract was not accepted.`;
    return `${prefix} was received; ${friendlyLabel(diagnostic.stage || diagnostic.category || "validation")} needs attention.`;
  }
  if (run?.status === "READY_FOR_REVIEW" || run?.status === "CLEAN_AND_FINALIZED") return `${prefix} was accepted, bound to this request, and compiled. The owner-facing result is ready.`;
  return null;
}

// A finalize started elsewhere (a reload, another tab) is still running on the
// server: show it and refresh this page when it ends.
let guidedFinalizeWatchTimer = null;
function watchFinalizeInProgress(run) {
  if (!run?.run_id || run.finalize_in_progress !== true || guidedFinalizeWatchTimer) return;
  setGuidedStatus("This character is being finalized. It takes a few minutes; the saved sheet opens here when it finishes.");
  const runId = run.run_id;
  guidedFinalizeWatchTimer = window.setInterval(async () => {
    try {
      const fresh = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`);
      if (fresh?.finalize_in_progress === true) return;
      window.clearInterval(guidedFinalizeWatchTimer);
      guidedFinalizeWatchTimer = null;
      if (guidedRun?.run_id !== runId) return;
      guidedRun = fresh;
      renderGuidedCandidate(fresh);
      renderOwnerPrimaryActions(fresh);
      const done = fresh?.status === "CLEAN_AND_FINALIZED";
      // Say why in plain words (owner 2026-09-25: the old text pointed "above" at nothing).
      const reasonRow = (fresh?.blockers || [])[0] || fresh?.submission_error || fresh?.last_submission_error || null;
      const reason = reasonRow ? (reasonRow.message || reasonRow.code || "") : "";
      setGuidedStatus(done ? "Finalized. The saved character sheet is below."
        : `Finalize ended without saving${reason ? `: ${reason}` : "."} You can press Finalize Character again.`, !done);
    } catch (_ignored) {
      // The next tick retries while the Factory is busy.
    }
  }, 5000);
}

function renderGuidedCandidate(run) {
  watchFinalizeInProgress(run);
  if (run?.status === "CLEAN_AND_FINALIZED" && guidedProjectId && guidedProjectLifecycle?.is_temporary) {
    // Finalized without the Finalize button (auto-finalize): the character is saved now, so the page stops calling it Temporary.
    const projectId = guidedProjectId;
    api(`/api/character-builder/projects/${encodeURIComponent(projectId)}/lifecycle`).then(lifecycle => {
      if (guidedProjectId === projectId) { guidedProjectLifecycle = lifecycle; renderGuidedPersistence(); }
    }).catch(() => {});
  }
  guidedRun = run;
  void refreshGuidedCandidateGMAuthoring(run);
  updateGuidedControllerResume(run);
  refreshGuidedControllerProgress(run);
  syncManualLineageResolverForRun(run);
  recordGuidedRunDiagnostics(run);
  renderGuidedResponseProcessing(run, "result");
  const responseResult = guidedResponseResultMessage(run);
  if (responseResult) renderGuidedResponseSourceState(responseResult, Boolean(guidedResponseProcessingDiagnostic(run)));
  const owner = ownerViewFor(run);
  const ownerDecisionRows = Array.isArray(owner.decisions) ? owner.decisions : [];
  const ownerBlockerRows = Array.isArray(owner.blockers) ? owner.blockers : [];
  const progress = document.getElementById("guidedBuildProgress");
  if (progress) progress.textContent = guidedRunOwnerMessage(run);
  const candidateAvailable = Boolean((owner.scratch_candidate?.available && owner.scratch_candidate?.sheet) || owner.proposal?.available);
  const correctionAvailable = run.execution_mode === "MANUAL_CHAT" && run.manual_ai_correction?.required === true;
  const reviewable = run.status === "READY_FOR_REVIEW"
    || (run.status === "NEEDS_REVIEW" && (candidateAvailable || correctionAvailable));
  const commitPresent = hasSubstantiveCommit(run.commit);
  const clean = reviewable && run.quality?.status === "CLEAN" && !(run.blockers || []).length
    && !ownerDecisionRows.length && !ownerBlockerRows.length && !commitPresent;
  const finalized = run.status === "CLEAN_AND_FINALIZED" && commitPresent;
  // Wording is locked once Finalize (or auto-finalize) starts: the character is being saved with the wording it
  // started with, and a change now would never reach it (owner 2026-09-27: a rename saved mid-finalize was lost).
  renderGuidedDescriptiveFields(run, reviewable && !commitPresent && run?.finalize_in_progress !== true && !guidedFinalizeInFlight);
  if (finalized) {
    renderGuidedRecoveryActions(run, false);
    renderGuidedFinal(run);
    renderOwnerPrimaryActions(run);
    setGuidedStep(4);
    return;
  }
  if (run.status === "CLEAN_AND_FINALIZED" && !commitPresent) {
    renderGuidedRecoveryActions(run, false);
    setGuidedStatus("Finalized status was returned without a substantive canonical commit receipt. No finalized result can be displayed.", true);
    renderOwnerPrimaryActions(run);
    setGuidedStep(3);
    return;
  }
  const manual = document.getElementById("guidedManualTransfer");
  const download = document.getElementById("guidedDownloadCompleteRequest");
  const correctionDownload = document.getElementById("guidedDownloadAICorrection");
  if (correctionDownload) {
    correctionDownload.hidden = !correctionAvailable;
    correctionDownload.disabled = !correctionAvailable || !run.run_id;
  }
  const reviewCorrectionDownload = document.getElementById("guidedReviewDownloadAICorrection");
  if (reviewCorrectionDownload) {
    reviewCorrectionDownload.hidden = !correctionAvailable;
    reviewCorrectionDownload.disabled = !correctionAvailable || !run.run_id;
  }
  if (!reviewable) {
    renderGuidedRecoveryActions(run, run.status === "NEEDS_REVIEW");
    setGuidedStep(run.status === "NEEDS_REVIEW" && !candidateAvailable ? 3 : owner.display_state?.step || 3);
    if (manual) manual.hidden = run.status !== "WAITING_FOR_RESPONSE" && !correctionAvailable;
    if (download) download.disabled = run.status !== "WAITING_FOR_RESPONSE" || !run.run_id;
    if (run.status === "WAITING_FOR_RESPONSE") renderGuidedResponseSourceState();
    setGuidedStatus(guidedRunOwnerMessage(run), Boolean(run.submission_error || (run.blockers || []).length || ownerDecisionRows.length || ownerBlockerRows.length || run.status === "NEEDS_REVIEW"));
    renderOwnerPrimaryActions(run);
    return;
  }
  const identity = ownerDisplayIdentity(run);
  const scratch = owner.scratch_candidate || {};
  const sheet = scratch.sheet || {};
  const host = document.getElementById("guidedCandidateSummary");
  const technicalHost = document.getElementById("guidedCandidateTechnicalSummary");
  clearNode(host);
  clearNode(technicalHost);
  appendCandidateLine(host, "Character", ownerText(identity.name, document.getElementById("guidedName").value || "Unnamed character"));
  appendCandidateLine(host, "Title", ownerText(identity.title, "Title pending owner review"));
  appendCandidateLine(host, "Identity wording", run.owner_descriptive_fields?.label || "AI proposal is available for review");
  appendCandidateLine(host, "Concept", ownerText(identity.concept, document.getElementById("guidedConcept").value || "Concept pending owner review"));
  appendCandidateLine(host, "Target CL", ownerText(identity.target_cl, document.getElementById("guidedLevel").value || "pending"));
  const aiPerformance = guidedAIPerformanceSummary(run);
  if (aiPerformance) appendCandidateLine(host, "AI time & tokens", aiPerformance);
  const secondBuildPending = scratch.independent_compilations === 1;
  appendCandidateLine(
    technicalHost,
    "Two isolated builds",
    scratch.independent_compilations === 2 && scratch.deterministic
      ? "PASS — deterministic identities match"
      : secondBuildPending
        ? "First build done — the independent second build runs with GM authoring or at Finalize, before anything is saved"
        : "Not verified",
    scratch.deterministic ? "success" : secondBuildPending ? "warning" : "error",
  );
  appendCandidateLine(technicalHost, "Canonical mutation before Finalize", commitPresent ? "Unexpected commit present" : "None", commitPresent ? "error" : "success");
  appendCandidateLine(technicalHost, "Quality gate", `${run.quality?.status || "Unknown"}${(run.warnings || []).length ? ` — ${(run.warnings || []).length} warning(s)` : ""}`, clean ? "success" : "warning");
  appendCandidateLine(host, "Paths", (owner.paths || []).map(row => ownerCardSummary(row)).join("; ") || "No Path tracks are projected yet.");
  appendCandidateLine(host, "Method", ownerText(owner.method?.name, "Method pending validated compilation"));
  appendCandidateLine(host, "Foundation", ownerText(owner.foundation?.name, "Foundation pending"));
  appendCandidateLine(host, "Path-owned Subpaths", (owner.subpath_bindings || owner.subpaths || []).map(row => ownerCardSummary(row)).join("; ") || "No Path-owned Subpath is projected yet.");
  appendCandidateLine(host, "Items / Equipment planning", (owner.planning_items || []).map(row => ownerCardSummary(row)).join("; ") || "No Items / Equipment planning proposal is recorded yet.");
  const proposal = owner.proposal || {};
  const sphereCount = (sheet.spheres || []).length;
  const talentCount = (sheet.talents || []).length;
  const insightCount = (sheet.insights || []).length;
  const progressionCount = (sheet.progression || []).length;
  appendCandidateLine(host, sheet.spheres ? "Compiled result" : "Parsed AI proposal", sheet.spheres
    ? `${sphereCount} Sphere${sphereCount === 1 ? "" : "s"} · ${talentCount} Talent${talentCount === 1 ? "" : "s"} · ${insightCount} Insight${insightCount === 1 ? "" : "s"} · ${progressionCount} CL progression group${progressionCount === 1 ? "" : "s"}`
    : proposalAcquisitionSummary(proposal));
  const decisionRows = ownerDecisionRows;
  const blockerRows = ownerBlockerRows;
  if (decisionRows.length) appendCandidateLine(host, "What to decide next", decisionRows.map(row => `${row.title || "Review required"}: ${row.message || ownerDiagnosticMessage(row, "The candidate needs one correction before review.")}${row.resolving_action ? ` Action: ${row.resolving_action}.` : ""}`).join(" "), "error");
  else if (blockerRows.length) appendCandidateLine(host, "What blocks the build", blockerRows.map(row => `${row.title || "Build blocker"}: ${row.message || ownerDiagnosticMessage(row, "Replace the response and try again.")}${row.resolving_action ? ` Action: ${row.resolving_action}.` : ""}`).join(" "), "error");
  const provenanceSummary = Object.entries(owner.provenance_groups || {})
    .filter(([, rows]) => Array.isArray(rows) && rows.length)
    .map(([label, rows]) => `${label}: ${rows.length}`);
  if (provenanceSummary.length) appendCandidateLine(technicalHost, "Proposal provenance", provenanceSummary.join(" · "));
  document.getElementById("guidedReviewDetail").textContent = pretty({
    status: run.status,
    display_state: owner.display_state,
    owner_view: {
      identity: owner.identity,
      paths: owner.paths,
       method: owner.method,
       foundation: owner.foundation,
       tradition: owner.tradition,
       subpaths: owner.subpaths,
       subpath_bindings: owner.subpath_bindings,
       planning_preferences: owner.planning_preferences,
      planning_items: owner.planning_items,
      provenance_groups: owner.provenance_groups,
      decisions: owner.decisions,
      blockers: owner.blockers,
      review: owner.review,
      scratch_candidate: owner.scratch_candidate,
    },
    quality: run.quality,
    blockers: run.blockers || [],
    warnings: run.warnings || [],
    diagnostics: run.diagnostics || {},
  });
  const finalizeButton = document.getElementById("guidedFinalize");
  finalizeButton.disabled = !clean || run.status === "CLEAN_AND_FINALIZED" || guidedFinalizeInFlight;
  const leadBlocker = ownerBlockerRows[0] || (run.blockers || [])[0];
  const blockerHeadline = leadBlocker?.title || leadBlocker?.message;
  setGuidedStatus(clean ? "The compiled proposal is clean and has not been committed. Review the source-backed result, then choose Finalize Character to accept it." : blockerHeadline ? `Stopped: ${blockerHeadline}` : "The complete candidate needs review. No canonical mutation occurred.", !clean);
  const nextAction = document.getElementById("guidedNextAction");
  if (nextAction) nextAction.textContent = clean
     ? "Next legal action: review the readable compiled result, then choose Finalize Character, Edit Brief / Create New Request, or Cancel Build."
    : guidedRunAtGmGate(run)
      ? "Next legal action: write the GM guidance in the Candidate GM review panel above (Author GM candidate, Build review, Issue approval challenge, approve), then Retry Local Build."
    : ownerDecisionRows.length
      ? "Next legal action: use the named owner decision control above, then rebuild the candidate."
      : ownerBlockerRows.length || (run.blockers || []).length
      ? "Next legal action: use the named recovery action above, then submit one replacement response."
       : "Next legal action: review the compiled result. No unresolved owner decision is reported unless one is named above.";
  renderGuidedRecoveryActions(run, true);
  renderOwnerReviewGroups(run);
  renderOwnerProductionSheet(run, false);
  renderCompiledOwnerStages(run);
  renderOwnerPrimaryActions(run);
  setGuidedStep(owner.display_state?.step || 4);
}

function ownerChoiceNames(slotId, ids) {
  return (ids || []).map(id => choiceFor(slotId, id)?.name || choiceFor(slotId, id)?.canonical_name || id).filter(Boolean);
}

function appendOwnerSheetCard(host, title, body, fullWidth = false) {
  const card = document.createElement("article");
  card.className = `owner-sheet-card${fullWidth ? " full-width" : ""}`;
  const heading = document.createElement("h3"); heading.textContent = title;
  card.appendChild(heading);
  if (Array.isArray(body)) {
    const list = document.createElement("ul");
    for (const value of body) { const item = document.createElement("li"); item.textContent = value; list.appendChild(item); }
    if (!list.childElementCount) { const empty = document.createElement("p"); empty.textContent = "No selections are recorded for this stage."; card.appendChild(empty); }
    else card.appendChild(list);
  } else {
    const paragraph = document.createElement("p"); paragraph.textContent = body; card.appendChild(paragraph);
  }
  host.appendChild(card);
}

function openOwnerDecisionResolution(row) {
  const target = Number(row?.target_step) || 4;
  const action = row?.resolving_action || "Open the named resolving step";
  if (action.startsWith("Replace Response")) {
    const replace = document.getElementById("guidedReplaceResponse");
    if (replace && !replace.disabled) {
      replace.click();
      return;
    }
  }
  setGuidedStep(target);
  const focusId = row?.field === "identity.name" || row?.field?.endsWith(".identity.name")
    ? "guidedProposedName"
    : row?.field === "identity.title" || row?.field?.endsWith(".identity.title") || row?.field === "title" || row?.field?.endsWith(".title")
      ? "guidedProposedTitle"
      : row?.field === "concept" || row?.field?.endsWith(".concept") ? "guidedProposedConcept" : null;
  if (focusId) window.setTimeout(() => document.getElementById(focusId)?.focus(), 0);
  setGuidedStatus(`${action} is the resolving action for this decision.`, true);
}

function appendOwnerDecisionItem(list, row) {
  const item = document.createElement("li");
  item.className = "owner-decision-item";
  const title = document.createElement("strong");
  title.textContent = row?.title || "Unresolved owner decision";
  const reason = document.createElement("p");
  reason.className = "owner-decision-reason";
  reason.textContent = row?.reason || row?.message || "The Factory cannot continue until this named decision is resolved.";
  item.append(title, reason);

  const proposal = document.createElement("p");
  proposal.className = "owner-decision-proposal";
  const proposalLabel = document.createElement("strong");
  proposalLabel.textContent = "AI proposal: ";
  proposal.append(proposalLabel, document.createTextNode(ownerText(row?.ai_proposed ?? row?.proposed, "No proposal supplied")));
  item.appendChild(proposal);

  const choices = Array.isArray(row?.legal_choices) ? row.legal_choices : [];
  const choiceCount = Number(row?.legal_choice_count) || choices.length;
  if (choices.length) {
    const disclosure = document.createElement("details");
    disclosure.className = "owner-decision-choices";
    const summary = document.createElement("summary");
    summary.textContent = `Show legal choices${choiceCount ? ` (${choiceCount})` : ""}`;
    disclosure.appendChild(summary);
    const controlLabel = document.createElement("label");
    controlLabel.className = "owner-decision-control-label";
    controlLabel.textContent = "Choose the legal value";
    const select = document.createElement("select");
    select.className = "owner-decision-control";
    select.setAttribute("aria-label", `Choose legal value for ${row?.field || "owner decision"}`);
    choices.forEach((choice, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = ownerText(choice?.name, String(choice?.value ?? "Legal choice"));
      if (choice?.description) option.title = choice.description;
      select.appendChild(option);
    });
    controlLabel.appendChild(select);
    const note = document.createElement("p");
    note.textContent = "The list is complete for this frozen request. Applying a value keeps the original response bytes and reruns the normal legality and deterministic build checks.";
    disclosure.append(controlLabel, note);
    item.appendChild(disclosure);
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "primary-action owner-decision-apply";
    apply.textContent = row?.control?.apply_label || "Apply decision and rebuild";
    apply.addEventListener("click", async () => {
      const selected = choices[Number(select.value)];
      if (!selected || !guidedRun?.run_id) return;
      apply.disabled = true;
      setGuidedStatus("Applying the bound owner decision and rebuilding the candidate…");
      try {
        guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/resolve-decision`, {
          method: "POST",
          body: JSON.stringify({
            decision_id: row.decision_id,
            field: row.field,
            slot_id: row.slot_id || null,
            operation: selected.operation || row.operation || "replace_slot_value",
            target_value: selected.target_value ?? row.target_value ?? null,
            value: selected.value,
            request_sha256: row.binding?.request_sha256 || guidedRun.request?.request_sha256,
            response_sha256: row.binding?.response_sha256 || guidedRun.response?.response_sha256,
            content_lock_hash: row.binding?.content_lock_hash || guidedRun.request?.content_lock_hash,
          }),
        });
        renderGuidedCandidate(guidedRun);
        setGuidedStatus(guidedRun.status === "READY_FOR_REVIEW" ? "Decision applied. The deterministic candidate is ready for review." : guidedRunOwnerMessage(guidedRun), guidedRun.status === "NEEDS_REVIEW");
      } catch (error) {
        recordGuidedDiagnostic(error, "resolve_owner_decision");
        setGuidedStatus(plainAPIError(error, "The owner decision could not be applied."), true);
        apply.disabled = false;
      }
    });
    item.appendChild(apply);
  } else {
    const noChoices = document.createElement("p");
    noChoices.className = "owner-decision-no-choices";
    noChoices.textContent = row?.legal_choices_note || "No direct choice list was published for this field; use the named resolving action to provide a corrected response.";
    item.appendChild(noChoices);
  }

  const surface = document.createElement("p");
  surface.className = "owner-decision-surface";
  surface.textContent = `Make this decision in: ${ownerText(row?.resolution_surface, "the named resolving step")}.`;
  item.appendChild(surface);
  if (!choices.length) {
    const action = document.createElement("button");
    action.type = "button";
    action.className = "secondary-action owner-decision-action";
    action.textContent = `${row?.recovery_action ? "Replace Response (recovery)" : ownerText(row?.resolving_action, "Open resolving step")} →`;
    action.addEventListener("click", () => openOwnerDecisionResolution(row));
    item.appendChild(action);
  }
  list.appendChild(item);
}

function renderOwnerReviewGroups(run) {
  const host = document.getElementById("ownerReviewGroups");
  if (!host) return;
  clearNode(host);
  const owner = ownerViewFor(run);
  const groups = owner.provenance_groups || {};
  const decisionRows = Array.isArray(owner.decisions) ? owner.decisions : [];
  const qualityStatus = String(run.quality?.status || "").trim().toUpperCase();
  const blockerCount = (Array.isArray(run.blockers) ? run.blockers.length : 0) + (Array.isArray(owner.blockers) ? owner.blockers.length : 0);
  const genuinelyNeedsAttention = run.status === "NEEDS_REVIEW" || Boolean(qualityStatus && qualityStatus !== "CLEAN") || blockerCount > 0;
  const groupDefinitions = [
    ["Owner", "owner", "Owner choices"],
    ["AI proposed", "ai", "AI-proposed wording and choices"],
    ["Automatic", "automatic", "Factory-derived results"],
    ["Needs owner decision", "decision", "Unresolved decisions"],
  ];
  for (const [label, className, title] of groupDefinitions) {
    const rows = label === "Needs owner decision" && decisionRows.length
      ? [...decisionRows]
      : Array.isArray(groups[label]) ? [...groups[label]] : [];
    const card = document.createElement("article");
    card.className = label === "Owner" ? "owner-review-group" : "owner-review-group disclosure-body";
    const badge = document.createElement("span"); badge.className = `provenance-badge ${className}`; badge.textContent = label;
    const heading = document.createElement("h4"); heading.textContent = title;
    const list = document.createElement("ul");
    for (const row of rows) {
      if (label === "Needs owner decision") {
        appendOwnerDecisionItem(list, row);
        continue;
      }
      const item = document.createElement("li");
      const titleText = row?.title ? `${row.title}: ` : "";
      const messageText = row?.message || row?.note || "";
      const actionText = row?.resolving_action ? ` Action: ${row.resolving_action}.` : "";
      item.textContent = `${titleText}${ownerText(row?.name, "Unlabeled review item")}${messageText && !row?.name ? messageText : row?.note ? ` — ${messageText}` : ""}${actionText}`;
      list.appendChild(item);
    }
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.textContent = label === "Needs owner decision" ? "No unresolved owner decisions are reported." : "No values are recorded for this provenance group yet.";
      card.append(badge, heading, empty);
    } else card.append(badge, heading, list);
    if (label === "Owner") {
      host.appendChild(card);
      continue;
    }
    const disclosure = document.createElement("details");
    disclosure.className = `owner-review-disclosure ${className}`;
    disclosure.open = label === "Needs owner decision" && rows.length > 0 && genuinelyNeedsAttention;
    const summary = document.createElement("summary");
    const summaryTitle = document.createElement("span"); summaryTitle.className = "owner-review-disclosure-title"; summaryTitle.textContent = title;
    const summaryCount = document.createElement("span"); summaryCount.className = "owner-review-disclosure-count"; summaryCount.textContent = `${rows.length} item${rows.length === 1 ? "" : "s"}`;
    summary.append(summaryTitle, summaryCount);
    disclosure.append(summary, card);
    host.appendChild(disclosure);
  }
  const identity = owner.identity || {};
  const identityCard = document.createElement("article"); identityCard.className = "owner-review-group full-width";
  const identityBadge = document.createElement("span"); identityBadge.className = "provenance-badge owner"; identityBadge.textContent = identity.name_provenance || "Owner";
  const identityTitle = document.createElement("h4"); identityTitle.textContent = ownerText(identity.name, "AI-proposed identity wording");
  const identityText = document.createElement("p"); identityText.textContent = `Title: ${ownerText(identity.title, "Title pending owner review")} · ${ownerText(identity.concept, "Concept pending owner review")} · Target CL ${ownerText(identity.target_cl, "pending")}. Review or edit this wording in the identity fields below; it does not grant mechanics.`;
  identityCard.append(identityBadge, identityTitle, identityText); host.appendChild(identityCard);
}

function renderOwnerProductionSheet(run = null, finalized = false, sheet = null) {
  const host = document.getElementById("ownerProductionSheet");
  const state = document.getElementById("ownerSheetState");
  const label = document.getElementById("ownerSheetStateLabel");
  const intro = document.getElementById("ownerSheetPreviewIntro");
  if (!host) return;
  clearNode(host);
  if (finalized && sheet) {
    const identity = sheet.identity || {};
    if (state) { state.textContent = "Persisted Character Sheet"; state.dataset.state = "ready"; }
    if (label) label.textContent = "Saved Character Sheet";
    if (intro) intro.textContent = "This view is rebuilt from the real /api/characters/{project_id}/sheet response after Finalize and reopen.";
    appendOwnerSheetCard(host, "Identity and CL", `${identity.name || "Unnamed character"} · Title: ${identity.title || "Title pending owner review"} · CL ${identity.current_cl ?? "pending"} of target ${identity.target_cl ?? "pending"}. ${identity.concept || "No concept recorded."}`, true);
     const path = sheet.owner_character_sheet?.path_and_subpath || {};
     const savedPaths = (path.paths || []).map(row => `${row.name || row.display_name || row.path_id || "Path"}${row.attainment !== undefined ? ` · attainment ${row.attainment}` : ""}`);
     const savedSubpaths = (path.bindings || path.subpaths || []).map(row => {
       const subpath = row.subpath || row.name || row.display_name || row.subpath_id || "Subpath / Tradition";
       const pathName = row.path || row.owning_path_name || row.path_id || "Path pending";
       return `${subpath} · ${pathName}`;
     });
     appendOwnerSheetCard(host, "Paths and attainment", savedPaths.length ? savedPaths : path.path ? [String(path.path.name || path.path.display_name || path.path)] : "Path attainment is not available in this saved sheet.");
     appendOwnerSheetCard(host, "Subpaths / Traditions", savedSubpaths.length ? savedSubpaths : "No Subpath or Tradition is recorded.");
    appendOwnerSheetCard(host, "Method and Foundation", sheet.owner_character_sheet?.method?.name || sheet.identity?.path ? `${sheet.owner_character_sheet?.method?.name || "Method recorded in the saved sheet"}. Foundation values are shown only when source-backed.` : "Method and Foundation are pending.");
    const sphereSurface = sheet.owner_character_sheet?.spheres_and_talents || {};
    appendOwnerSheetCard(host, "Spheres, Talents, and Insights", [`${(sphereSurface.sphere_record_ids || []).length} acquired Spheres`, `${(sphereSurface.learned_talent_record_ids || []).length} learned Talents`, `${(sphereSurface.cultivation_insight_record_ids || []).length} Insights`, `${(sphereSurface.automatic_sphere_component_record_ids || []).length} automatic Sphere components`]);
    appendOwnerSheetCard(host, "Resources and actions", sheet.owner_character_sheet?.ability_scores_and_statistics ? "Compiled resources and actions are available in the saved Character Sheet sections." : "Resources and actions are pending.");
    const unresolved = (sheet.workflow?.active_run?.blockers || []).map(row => ownerDiagnosticMessage(row, "Resolve the saved owner decision."));
    appendOwnerSheetCard(host, "Unresolved owner decisions", unresolved.length ? unresolved : "No unresolved owner decisions are reported by the saved sheet.", true);
    return;
  }
  if (state) { state.textContent = "Proposal preview · not canonical"; state.dataset.state = "pending"; }
  if (label) label.textContent = "Proposal preview · not yet canonical";
  if (intro) intro.textContent = "Before Finalize, this is a server-derived scratch candidate. It is not the persisted Character Sheet.";
  const owner = ownerViewFor(run);
  const identity = owner.identity || {};
  const scratch = owner.scratch_candidate || {};
  const previewSheet = scratch.sheet || {};
  appendOwnerSheetCard(host, "Identity and CL", `${ownerText(identity.name, document.getElementById("guidedName")?.value || "Name pending owner review")} · Title: ${ownerText(identity.title, "Title pending owner review")} · target CL ${ownerText(identity.target_cl, "pending")}. ${ownerText(identity.concept, document.getElementById("guidedConcept")?.value || "Concept pending owner review.")}`, true);
  appendOwnerSheetCard(host, "Paths and attainment", ownerCardLines(owner.paths, "All three level-zero Path tracks remain visible."));
   appendOwnerSheetCard(host, "Method and Foundation", `${ownerText(owner.method?.name, "Method pending Factory validation")}. Foundation: ${ownerText(owner.foundation?.name, "pending")}.`);
   appendOwnerSheetCard(host, "Subpaths / Traditions", ownerCardLines(owner.subpath_bindings || owner.subpaths, "No Subpath or Tradition is projected yet."));
   appendOwnerSheetCard(host, "Planning preferences · non-acquisitive", [
     ...ownerCardLines(owner.planning_preferences?.sphere_priorities, "No Sphere planning priorities are recorded."),
     ...ownerCardLines(owner.planning_preferences?.talent_priorities, "No Talent planning priorities are recorded."),
     ...ownerCardLines(owner.planning_preferences?.insight_priorities, "No Insight planning priorities are recorded."),
     ...ownerCardLines(owner.planning_items, "No Items / Equipment planning proposal is recorded."),
   ]);
   const resourceLines = Array.isArray(previewSheet.resources) && previewSheet.resources.length
    ? previewSheet.resources.map(row => `${ownerText(row?.name, "Resource")}: ${ownerText(row?.current, "pending")} / ${ownerText(row?.maximum, "pending")}`)
    : ["Pending — the Factory has not compiled validated resource values for this proposal."];
  appendOwnerSheetCard(host, "Resources", resourceLines);
  appendOwnerSheetCard(host, "Spheres, Talents, and abilities", [
    `${(previewSheet.spheres || []).length} acquired Sphere${(previewSheet.spheres || []).length === 1 ? "" : "s"}`,
    `${(previewSheet.free_talents || []).length} free Talent${(previewSheet.free_talents || []).length === 1 ? "" : "s"}`,
    `${(previewSheet.ordinary_talents || []).length} ordinary Talent${(previewSheet.ordinary_talents || []).length === 1 ? "" : "s"}`,
    `${(previewSheet.automatic_components || []).length} automatic base abil${(previewSheet.automatic_components || []).length === 1 ? "ity" : "ities"}`,
    "Open Spheres, Talents and training above for the compact Sphere groups and on-demand source-backed details.",
  ]);
  appendOwnerSheetCard(host, "Insights, equipment, and progression", [
    `${(previewSheet.insights || []).length} compiled Insight${(previewSheet.insights || []).length === 1 ? "" : "s"}`,
    `${(previewSheet.progression || []).length} CL progression group${(previewSheet.progression || []).length === 1 ? "" : "s"}`,
    `${(previewSheet.equipment || []).length} equipment direction item${(previewSheet.equipment || []).length === 1 ? "" : "s"}`,
    "Open Insights and progression above for Insight descriptions and progression at a glance.",
  ]);
  const correctionRequired = owner.ai_correction_required === true;
  const decisions = correctionRequired ? [] : Array.isArray(owner.decisions) && owner.decisions.length
    ? owner.decisions
    : Array.isArray(owner.blockers) && owner.blockers.length
      ? owner.blockers
      : run?.blockers || [];
  appendOwnerSheetCard(host, correctionRequired ? "AI correction status" : "Unresolved owner decisions", correctionRequired
     ? "The same AI must correct the response-authored mechanical selection. No owner decision control is available and no canonical mutation has occurred."
     : decisions.length
       ? decisions.map(row => `${row.title || "Review required"}: ${row.message || ownerText(row.name, "Use the named recovery action.")}${row.resolving_action ? ` Action: ${row.resolving_action}.` : ""}`)
       : "No unresolved owner decisions are reported. Review the proposal and choose Finalize Character when ready.", true);
}

async function loadFinalOwnerSheet() {
  if (!guidedProjectId) return null;
  try {
    const sheet = await api(`/api/characters/${encodeURIComponent(guidedProjectId)}/sheet`);
    ownerCharacterSheet = sheet;
    renderOwnerProductionSheet(null, true, sheet);
    renderOwnerExportAvailability(sheet);
    // The full saved viewer also lands on step 4 (plan Part B target layout);
    // loading it here keeps "Open character sheet" a no-navigation action.
    const previewHost = document.getElementById("ownerSheetPreviewHost");
    if (previewHost) renderOwnerSheet(sheet, previewHost);
    // The status strip and the action rows now describe the persisted sheet.
    renderOwnerPrimaryActions(guidedRun);
    return sheet;
  } catch (error) {
    const host = document.getElementById("ownerProductionSheet");
    if (host) { clearNode(host); const message = document.createElement("p"); message.className = "pending-copy"; message.textContent = plainAPIError(error, "The persisted Character Sheet could not be rebuilt yet."); host.appendChild(message); }
    return null;
  }
}

function renderOwnerExportAvailability(sheet = ownerCharacterSheet) {
  const finalized = guidedRun?.status === "CLEAN_AND_FINALIZED" && hasSubstantiveCommit(guidedRun.commit);
  const owner = ownerViewFor(guidedRun);
  const serverAvailability = owner.export_availability || {};
  const gmAvailable = Boolean(sheet?.gm_export?.available);
  document.querySelectorAll("[data-owner-export-kind]").forEach(button => {
    const kind = button.dataset.ownerExportKind;
    const serverKind = kind === "gm_character" ? "gm_package" : kind;
    const available = serverAvailability[serverKind]
      ? serverAvailability[serverKind].available === true
      : kind === "project_backup" ? Boolean(guidedProjectId)
        : kind === "chat_request" ? Boolean(guidedRun?.run_id && guidedRun?.request)
           : kind === "completed_character" ? finalized && serverAvailability.completed_character?.available === true
            : kind === "gm_character" ? gmAvailable : false;
    button.disabled = !available;
  });
  const completedReason = document.getElementById("ownerCompletedExportReason");
  if (completedReason) completedReason.textContent = serverAvailability.completed_character?.reason || (finalized && !gmAvailable ? "Finalize succeeded, but the server reports that the GM/Character export gate is still pending." : finalized ? "Available from the real validated export state." : "Available only after validated Finalize.");
  const gmReason = document.getElementById("ownerGMExportReason");
  if (gmReason) gmReason.textContent = serverAvailability.gm_package?.reason || (gmAvailable ? "The server reports a verified GM export." : "Available only after the real GM export gate.");
}

function currentOwnerReviewBlocker(run) {
  if (!run) return null;
  const owner = ownerViewFor(run);
  const projectedRows = [
    ...(Array.isArray(owner.decisions) ? owner.decisions : []),
    ...(Array.isArray(owner.blockers) ? owner.blockers : []),
  ].filter(row => row && typeof row === "object");
  const rawRows = [
    ...(Array.isArray(run.blockers) ? run.blockers : []),
    run.submission_error,
    run.validation?.last_submission_error,
  ].filter(row => row && typeof row === "object");
  const raw = rawRows.find(row => row.code || row.message) || rawRows[0] || {};
  const projected = projectedRows.find(row => row.field && row.field === raw.field) || projectedRows[0] || {};
  if (!Object.keys(raw).length && !Object.keys(projected).length) return null;
  return {...projected, ...raw, owner_message: projected.message || null, owner_title: projected.title || null};
}

function ownerReviewBlockerRecordId(blocker) {
  const details = blocker?.details && typeof blocker.details === "object" ? blocker.details : {};
  const nested = [blocker?.record, blocker?.authority_record, details.record, details.authority_record, details.selected_record];
  const values = [
    blocker?.record_id, blocker?.recordId, blocker?.authority_record_id, blocker?.selected_record_id, blocker?.method_id, blocker?.choice_id,
    details.record_id, details.recordId, details.authority_record_id, details.selected_record_id, details.method_id, details.method_record_id, details.choice_id,
    ...nested.flatMap(row => row && typeof row === "object" ? [row.record_id, row.recordId, row.id] : []),
  ];
  return values.find(value => typeof value === "string" && value.trim()) || "";
}

function ownerReviewRecovery(blocker) {
  if (["CG1_IMMORTAL_ART_AUTHORITY_MISSING", "CG1_IMMORTAL_ART_SOURCE_UNAVAILABLE", "CG1_IMMORTAL_ART_SOURCE_DEPENDENCY_UNAVAILABLE", "CG1_PATH_ATTAINMENT_AUTHORITY_INVALID", "CG1_PATH_ATTAINMENT_POLICY_INVALID"].includes(blocker?.code)) {
    return {label: "Factory update required", replaceResponse: false, factorySupport: true};
  }
  const details = blocker?.details && typeof blocker.details === "object" ? blocker.details : {};
  const control = blocker?.control && typeof blocker.control === "object" ? blocker.control : {};
  if (control.type === "gm_candidate_authoring" || /author gm candidate/i.test(String(blocker?.recovery_action || ""))) {
    // The captured candidate is sound; only its GM guidance is provisional.
    return {label: "Author GM candidate", replaceResponse: false, gmCandidate: true};
  }
  // The request's own planning choices cannot work together (e.g. a Method that also grants a
  // Path the owner did not pick): no response can fix that; change the plan (owner 2026-09-25).
  if (["DCC_LINEAR_PROGRESSION_UNSATISFIABLE"].includes(blocker?.code)) {
    // The frozen plan itself cannot be built; a linked request would reuse it, so start fresh.
    return {label: "Start a new character", replaceResponse: false, newCharacter: true};
  }
  const candidates = [blocker?.recovery_action, blocker?.resolving_action, details.recovery_action, details.resolving_action]
    .filter(value => typeof value === "string" && value.trim());
  const replaceResponse = blocker?.code === "CG1_AUTHORITY_SHAPE_UNRESOLVED"
    || candidates.some(value => value.toLowerCase().includes("replace response"));
  return {
    label: replaceResponse ? "Replace Response" : candidates[0] || "Open review recovery",
    replaceResponse,
  };
}

function renderOwnerNextActionBlocker(run) {
  const panel = document.getElementById("ownerNextActionBlocker");
  if (!panel) return null;
  const blocker = currentOwnerReviewBlocker(run);
  if (!blocker) {
    panel.hidden = true;
    return null;
  }
  const code = blocker.code || blocker.error_code || blocker.diagnostic_code || blocker.details?.code || "Review blocker";
  const owner = ownerViewFor(run);
  const method = owner.method?.name;
  const methodName = method && !/^(No Method|Method pending|pending)/i.test(String(method)) ? String(method) : "";
  const recordId = ownerReviewBlockerRecordId(blocker)
    || ownerReviewBlockerRecordId(owner.method)
    || ownerReviewBlockerRecordId(owner.proposal?.method)
    || run?.resolution?.method_id
    || run?.request?.method_id
    || "";
  const localFixAvailable = run?.action_availability?.retry_local_ai_correction?.available === true;
  let classifiedRecovery = ownerReviewRecovery({...blocker, code});
  // Never point at a button the server says is unavailable for this run (owner 2026-09-25:
  // "pushing the button does nothing"); a new linked request is the way out instead.
  if (classifiedRecovery.replaceResponse && run?.action_availability?.replace_response?.available === false
      && run?.action_availability?.edit_brief_create_new_request?.available !== false) {
    classifiedRecovery = {label: "Edit Brief / Create New Request", replaceResponse: false, editBrief: true};
  }
  const recovery = localFixAvailable && !classifiedRecovery.factorySupport && !classifiedRecovery.gmCandidate && !classifiedRecovery.editBrief && !classifiedRecovery.newCharacter
    ? {label: "Fix with Local AI", replaceResponse: false, localAIFix: true}
    : classifiedRecovery;
  // The server's owner projection explains a gate in plain words; the raw
  // validator sentence stays available under the technical code.
  const message = (recovery.gmCandidate && blocker.owner_message)
    || blocker.message || blocker.details?.message || "The current candidate needs a correction before it can continue.";
  const codeNode = document.getElementById("ownerNextActionBlockerCode");
  const recordNode = document.getElementById("ownerNextActionBlockerRecord");
  const messageNode = document.getElementById("ownerNextActionBlockerMessage");
  const recoveryNode = document.getElementById("ownerNextActionBlockerRecovery");
  if (codeNode) codeNode.textContent = code;
  if (recordNode) {
    recordNode.textContent = recovery.factorySupport ? "Source-action authority is incomplete in the Factory."
      : recovery.gmCandidate ? "The character build is complete; only its GM guidance has not been written yet."
      : methodName
      ? `Selected Method: ${methodName}${recordId ? ` · authority record ${recordId}` : ""}`
      : recordId ? `Authority record: ${recordId}` : "";
    recordNode.hidden = !recordNode.textContent;
  }
  if (messageNode) messageNode.textContent = message;
  if (recoveryNode) recoveryNode.textContent = `Recovery action: ${recovery.label}.`;
  panel.hidden = false;
  return {blocker: {...blocker, code}, recovery, target: Number(blocker.target_step) || 4};
}

// Returns the single legal next action for the current run, together with the
// click behaviour that performs it.  Both the "Next legal action" card and the
// one-page review action rows are filled from this, so the recovery button the
// owner sees in the top row is always the action the server named.
function ownerNextActionDecision(run = guidedRun) {
  const owner = ownerViewFor(run);
  const serverAction = owner.next_legal_action;
  const blockerSummary = renderOwnerNextActionBlocker(run);
  const localFixAvailable = !blockerSummary?.recovery.factorySupport && !blockerSummary?.recovery.gmCandidate && !blockerSummary?.recovery.editBrief && !blockerSummary?.recovery.newCharacter && run?.action_availability?.retry_local_ai_correction?.available === true;
  let target = 1; let label = "Return to brief"; let heading = "Describe a character first"; let copy = "Optional Name and Concept, target CL, power band, and detail belong in the brief.";
  let recovery = null; let disabled = false;
  const cleanCandidate = run?.status === "READY_FOR_REVIEW" && run?.quality?.status === "CLEAN"
    && !(run.blockers || []).length && !(owner.blockers || []).length && !(owner.decisions || []).length;
  if (cleanCandidate) {
    const finalizing = guidedFinalizeInFlight || run.finalize_in_progress === true;
    const finalizeLabel = finalizing ? "Finalizing…" : "Finalize character";
    return {
      label: finalizeLabel,
      heading: finalizing ? "Finalizing this character" : "Review, then finalize",
      copy: finalizing
        ? "The Factory is building and saving this character. This takes a few minutes; the saved sheet opens here when it finishes."
        : "The candidate is clean. Review it below, then finalize to save it.",
      target: 4, disabled: finalizing, recovery: "finalize", blockerSummary,
      onClick: () => {
        const live = document.getElementById("guidedFinalize");
        if (live && !guidedFinalizeInFlight && run.finalize_in_progress !== true) live.click();
      },
    };
  }
  if (blockerSummary?.recovery.factorySupport) {
    target = 4;
    label = "Factory update required";
    heading = "The Factory needs source support for this build";
    copy = "Your choices are retained. This rules-authority gap requires a Factory update; replacing the response cannot resolve it.";
    disabled = true;
  } else if (blockerSummary?.recovery.gmCandidate) {
    target = 4;
    label = "Author GM candidate";
    heading = "Write the GM guidance to continue";
    copy = "Your character build is done. GM guidance is the Factory's write-up of how a Game Master runs this character at the table; your Local AI writes it and you approve it. On this page, press Author GM candidate, then Build review from saved receipt, then Issue approval challenge and approve, then Retry Local Build. Nothing about the character changes.";
    recovery = "gmCandidate";
  } else if (localFixAvailable) {
    target = 4;
    label = "Fix with Local AI";
    heading = "Fix the response with Local AI";
    copy = "The selected Local AI will choose a bounded legal correction while the Factory preserves the frozen request and every unrelated choice.";
    recovery = "localAIFix";
  } else if (blockerSummary?.recovery.newCharacter) {
    target = 4;
    label = "Start a new character";
    heading = "This plan can't be finished";
    const details = blockerSummary.blocker?.details || {};
    const attained = details.path_attainment || {};
    const bound = (details.constraints || []).flatMap(row => row.paths || []);
    const missing = [...new Set(bound.filter(pathId => !attained[pathId]))]
      .map(pathId => String(pathId).split(".").pop().replace(/_/g, " ").replace(/\b\w/g, char => char.toUpperCase()));
    copy = `The Method sealed into this draft also advances ${missing.length ? missing.join(" and ") : "a Path you didn't pick"}, so it can never be built — and Edit Brief would reuse the same plan. Start a new character: pick your Paths, press Check Method compatibility, and choose one of the Methods it lists (only Methods that fit your Paths appear now). This draft stays in your history.`;
    recovery = "newCharacter";
  } else if (blockerSummary?.recovery.editBrief) {
    target = 4;
    label = "Edit brief";
    heading = "Change the plan to clear this blocker";
    copy = "The choices sealed into this request can't work together — for example a Method that also advances a Path you didn't pick. Edit the brief to choose a different Method or Paths; the Factory creates a linked new request and keeps this one in the history.";
    recovery = "editBrief";
  } else if (blockerSummary?.recovery.replaceResponse) {
    target = 3;
    label = "Replace Response";
    heading = "Replace the response to clear this blocker";
    copy = "The current response cannot satisfy the selected authority contract. Use the existing Replace Response flow for this exact frozen request.";
    recovery = "replaceResponse";
  } else if (blockerSummary) {
    target = blockerSummary.target;
    label = blockerSummary.recovery.label;
    heading = "Resolve the current review blocker";
    copy = "Use the named recovery action below; the current request remains server-bound and unchanged.";
  } else if (serverAction?.label) { target = Number(serverAction.target_step) || owner.display_state?.step || 1; label = serverAction.label; heading = serverAction.label; copy = serverAction.description || "Follow the Factory's next legal action."; }
  else if (run?.status === "CLEAN_AND_FINALIZED" && hasSubstantiveCommit(run.commit)) { target = 4; label = "Open character sheet"; heading = "Review the saved Character Sheet"; copy = "Finalize has completed. The sheet below is rebuilt from the persisted owner sheet."; recovery = "openSheet"; }
  else if (run?.status === "READY_FOR_REVIEW" || run?.status === "NEEDS_REVIEW") { target = 4; label = "Resolve proposal review"; heading = "Review the imported proposal"; copy = "Compare Owner, AI proposed, Automatic, and Needs owner decision state before Finalize."; }
  else if (run?.status === "WAITING_FOR_RESPONSE" || guidedWizardStep === 3) { target = 3; label = "Open AI route"; heading = "Bring one response back"; copy = "Manual Chat uses the sealed request ZIP and the shared paste/file/drop response path."; }
  else if (guidedProjectId && guidedWizardStep < 3) { target = 3; label = "Choose AI route"; heading = "Choose an AI route"; copy = "The real project is ready. Manual Chat and API Provider share the same validator."; }
  const onClick = () => {
    if (recovery === "localAIFix") {
      const fix = document.getElementById("guidedRetryLocalAICorrection");
      if (fix && !fix.disabled) fix.click();
      else setGuidedStatus("Fix with Local AI is not available from the current server state.", true);
      return;
    }
    if (recovery === "gmCandidate") {
      setGuidedStep(4);
      void refreshGuidedCandidateGMAuthoring(run, {force: true});
      renderGuidedCandidateGMAuthoring();
      const author = document.getElementById("guidedCandidateGMAuthor");
      if (author) {
        const disclosure = author.closest("details");
        if (disclosure) disclosure.open = true;
        author.scrollIntoView?.({behavior: "smooth", block: "center"});
        author.focus?.();
      }
      return;
    }
    if (recovery === "newCharacter") {
      document.getElementById("guidedBack")?.click();
      return;
    }
    if (recovery === "editBrief") {
      const edit = document.getElementById("guidedEditBrief");
      if (edit && !edit.disabled) edit.click();
      else setGuidedStatus("Edit Brief is not available from the current server state; start a new character from Create a Character.", true);
      return;
    }
    if (recovery === "replaceResponse") {
      const replace = document.getElementById("guidedReplaceResponse");
      if (replace && !replace.disabled) replace.click();
      else setGuidedStatus("Replace Response is not available from the current server state.", true);
      return;
    }
    if (recovery === "openSheet") {
      void openFinalizedSheetPreview();
      return;
    }
    setGuidedStep(target);
  };
  return {label, heading, copy, target, disabled, recovery, blockerSummary};
}

// Move the persisted Character Sheet into the step 4 preview disclosure and
// open it, so "Open character sheet" never sends the owner to another screen.
async function openFinalizedSheetPreview() {
  const projectId = guidedProjectId || ownerCharacterSheet?.project_id || selectedProject;
  const host = document.getElementById("ownerSheetPreviewHost");
  const section = document.getElementById("ownerSheetPreviewHostSection");
  if (section) section.open = true;
  if (!projectId) {
    setGuidedStatus("No finalized character is open on this page yet.", true);
    return;
  }
  if (host) {
    clearNode(host);
    const message = document.createElement("p");
    message.className = "pending-copy";
    message.textContent = "Opening the saved character sheet…";
    host.appendChild(message);
  }
  try {
    const sheet = await api(`/api/characters/${encodeURIComponent(projectId)}/sheet`);
    if (host) renderOwnerSheet(sheet, host);
    renderOwnerExportAvailability(sheet);
    setGuidedStatus("The saved Character Sheet is shown below, rebuilt from the persisted owner sheet.");
  } catch (error) {
    if (host) {
      clearNode(host);
      const message = document.createElement("p");
      message.className = "pending-copy";
      message.textContent = plainAPIError(error, "The saved Character Sheet could not be opened yet.");
      host.appendChild(message);
    }
    setGuidedStatus(plainAPIError(error, "The saved Character Sheet could not be opened yet."), true);
  }
}

function ownerRunProgressing(run) {
  return !run || ["PREPARING_REQUEST", "WAITING_FOR_RESPONSE"].includes(String(run.status || ""));
}

// The page-level copy describes the state the owner is actually in.
const OWNER_REVIEW_INTRO = Object.freeze({
  finalized: "The canonical commit is sealed and the saved Character Sheet is on this page. Nothing here changes the character.",
  ready: "This candidate is compiled and clean. Nothing is committed until you press Finalize; everything about this character is on this page.",
  attention: "The build stopped before compilation finished. The named recovery below is the next legal action; nothing has been committed.",
  working: "The Factory is building this character. Nothing is committed yet; everything about the character will appear on this page.",
  cancelled: "This build was cancelled. No canonical character changes were committed.",
  default: "No canonical mutation has occurred until you press Finalize. Everything about this character is on this page.",
});

function renderOwnerReviewStatus(run = guidedRun) {
  const pill = document.getElementById("ownerReviewStatusPill");
  const headline = document.getElementById("ownerReviewStatusHeadline");
  if (!pill || !headline) return;
  const decision = run ? ownerNextActionDecision(run) : null;
  const status = String(run?.status || "");
  const state = !run ? "pending"
    : status === "CLEAN_AND_FINALIZED" ? "finalized"
    : status === "READY_FOR_REVIEW" ? "ready"
    : status === "NEEDS_REVIEW" ? "attention"
    : "working";
  const label = !run ? "Waiting"
    : status === "CLEAN_AND_FINALIZED" ? "Finalized"
    : status === "READY_FOR_REVIEW" ? "Ready to finalize"
    : status === "NEEDS_REVIEW" ? "Needs attention"
    : status === "WAITING_FOR_RESPONSE" ? "Build running"
    : status === "PREPARING_REQUEST" ? "Preparing"
    : status === "CANCELLED" ? "Cancelled"
    : friendlyLabel(status || "Draft");
  pill.textContent = label;
  pill.dataset.state = state;
  headline.textContent = decision ? decision.heading : "No complete-character build has started yet.";
  const intro = document.getElementById("ownerReviewIntro");
  if (intro) intro.textContent = OWNER_REVIEW_INTRO[state] || OWNER_REVIEW_INTRO.default;
  // The status strip already names the next action, and the "Next legal action"
  // card below it carries the full sentence and the control.  The bare
  // placeholder line between them is redundant once a run exists.
  const nextAction = document.getElementById("guidedNextAction");
  if (nextAction) nextAction.hidden = Boolean(run);
}

function appendOwnerActionButton(host, label, {variant = "secondary", onClick = null, disabled = false, title = null, primary = false} = {}) {
  if (!host) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = primary ? "primary-action" : "secondary-action";
  button.textContent = label;
  button.disabled = Boolean(disabled);
  if (title) button.title = title;
  if (onClick) button.onclick = onClick;
  host.appendChild(button);
  return button;
}

function renderOwnerActionRow(host, run) {
  if (!host) return;
  // The internal Finalize button is hidden on every render and unhidden only
  // while this run is a clean candidate awaiting Finalize, so a disabled bare
  // "Finalize Character" can never sit at the bottom of a finalized page.
  const finalizeControl = document.getElementById("guidedFinalize");
  if (finalizeControl) {
    finalizeControl.hidden = true;
    const finalizeRow = finalizeControl.closest(".owner-finalize-row");
    if (finalizeRow) finalizeRow.hidden = true;
  }
  clearNode(host);
  if (!run) {
    appendOwnerActionButton(host, "Start a character brief", {primary: true, onClick: () => setGuidedStep(1)});
    return;
  }
  const status = String(run.status || "");
  const decision = ownerNextActionDecision(run);
  if (ownerRunProgressing(run)) {
    const note = document.createElement("p");
    note.className = "owner-action-note";
    note.textContent = status === "PREPARING_REQUEST"
      ? "The Factory is preparing the complete-character request. Finalize appears as soon as a compiled candidate is ready."
      : "The build is running. Finalize appears as soon as the compiled candidate is ready.";
    host.appendChild(note);
    appendOwnerActionButton(host, "Retry Local Build", {onClick: () => document.getElementById("guidedRetryLocalBuild")?.click(), disabled: !run.run_id});
    appendOwnerActionButton(host, "Edit brief", {onClick: () => document.getElementById("guidedEditBrief")?.click(), disabled: !run.run_id});
    appendOwnerActionButton(host, "Cancel", {onClick: () => document.getElementById("guidedCancel")?.click(), disabled: !run.run_id});
    return;
  }
  if (status === "CLEAN_AND_FINALIZED" && hasSubstantiveCommit(run.commit)) {
    appendOwnerActionButton(host, "Open character sheet", {primary: true, onClick: () => void openFinalizedSheetPreview()});
    // The character's picture and token (owner 2026-09-27: "a full picture in creation ... the token can be created from
    // the main picture"): Anima Studio paints it until one is liked, or upload one; a circle over the head is the token.
    appendOwnerActionButton(host, "Picture and token", {disabled: !run.project_id,
      title: "Make the character's picture with Anima Studio (retry until you like it) or upload one; a circle over the head becomes the table token",
      onClick: () => import("/static/tabletop/portrait.js")
        .then((module) => module.openPictureDialog({projectId: run.project_id}))
        .catch((error) => window.alert(`The picture dialog could not open: ${error.message}`))});
    appendOwnerActionButton(host, "Exports and GM readiness", {onClick: () => openOwnerReviewSection("ownerExportSection")});
    appendOwnerActionButton(host, "Start another character", {onClick: () => document.getElementById("guidedNewCharacter")?.click()});
    appendOwnerActionButton(host, "Open Character Sheets", {onClick: () => document.getElementById("ownerExportOpenSheets")?.click()});
    return;
  }
  const clean = run.status === "READY_FOR_REVIEW" && run.quality?.status === "CLEAN"
    && !(run.blockers || []).length
    && !(ownerViewFor(run).blockers || []).length
    && !(ownerViewFor(run).decisions || []).length;
  if (clean) {
    // One Finalize control: the "Next legal action" card above performs it
    // (owner smoke test 2026-09-24: three Finalize buttons were confusing).
  } else {
    appendOwnerActionButton(host, decision.label, {
      primary: true,
      disabled: decision.disabled,
      onClick: decision.onClick,
      title: decision.copy,
    });
  }
  if (decision.recovery !== "localAIFix") {
    appendOwnerActionButton(host, "Fix with Local AI", {onClick: () => document.getElementById("guidedRetryLocalAICorrection")?.click(), disabled: run.action_availability?.retry_local_ai_correction?.available !== true});
  }
  appendOwnerActionButton(host, "Retry Local Build", {onClick: () => document.getElementById("guidedRetryLocalBuild")?.click(), disabled: !run.run_id});
  if (decision.recovery === "replaceResponse") {
    appendOwnerActionButton(host, "Replace Response", {onClick: () => document.getElementById("guidedReplaceResponse")?.click(), disabled: !run.run_id});
  }
  if (decision.recovery === "gmCandidate") {
    appendOwnerActionButton(host, "GM candidate controls", {onClick: () => {
      const panel = document.getElementById("guidedCandidateGMAuthoring");
      const disclosure = panel?.closest("details");
      if (disclosure) disclosure.open = true;
      panel?.scrollIntoView?.({behavior: "smooth", block: "start"});
      panel?.querySelector("button")?.focus?.();
    }});
  }
  appendOwnerActionButton(host, "Edit brief", {onClick: () => document.getElementById("guidedEditBrief")?.click(), disabled: !run.run_id});
  appendOwnerActionButton(host, "Cancel", {onClick: () => document.getElementById("guidedCancel")?.click(), disabled: !run.run_id});
}

function renderOwnerPrimaryActions(run = guidedRun) {
  renderOwnerReviewStatus(run);
  renderOwnerNextAction();
  renderOwnerActionRow(document.getElementById("ownerPrimaryActions"), run);
  renderOwnerActionRow(document.getElementById("ownerPrimaryActionsBottom"), run);
}

function renderOwnerNextAction() {
  const title = document.getElementById("ownerNextActionTitle");
  const text = document.getElementById("ownerNextActionText");
  const button = document.getElementById("ownerNextActionButton");
  if (!title || !text || !button) return;
  const decision = ownerNextActionDecision(guidedRun);
  const target = decision.target;
  button.textContent = decision.disabled ? decision.label : `${decision.label} →`;
  button.dataset.ownerTarget = String(target);
  button.disabled = decision.disabled;
  button.onclick = decision.onClick;
  title.textContent = decision.heading;
  text.textContent = decision.copy;
}

document.getElementById("ownerExportOpenSheets")?.addEventListener("click", async () => {
  showScreen("projects");
  await loadProjects().catch(() => {});
  if (selectedProject) await openOwnerCharacterSheet(selectedProject);
});
for (const button of document.querySelectorAll("[data-owner-export-kind]")) {
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    const status = document.getElementById("ownerExportStatus");
    if (status) status.textContent = "Staging the requested artifact through the existing Factory service…";
    try {
      const result = await api("/api/owner-artifacts/stage", {
        method: "POST",
        body: JSON.stringify({artifact_kind: button.dataset.ownerExportKind, project_id: guidedProjectId || selectedProject}),
      });
      if (status) status.textContent = `${friendlyLabel(button.dataset.ownerExportKind)} staged: ${result.filename} (${result.bytes} bytes). Open Character Sheets → Advanced Exports for native Save As.`;
      const diagnosticsState = document.getElementById("diagnosticsTechnicalState");
      if (diagnosticsState) diagnosticsState.textContent = `${result.filename} staged through the real artifact API; technical identity is available in Character Sheets Advanced Exports.`;
    } catch (error) {
      if (status) status.textContent = plainAPIError(error, "The requested artifact is not available from the current server state.");
    }
  });
}

function renderGuidedRecoveryActions(run, visible = true) {
  const panel = document.getElementById("guidedRecoveryActions");
  if (!panel) return;
  panel.hidden = !visible;
  if (!visible || !run) return;
  const availability = run.action_availability || {};
  const correctionAvailable = run.execution_mode === "MANUAL_CHAT" && run.manual_ai_correction?.required === true;
  const controls = {
    guidedRetryLocalAICorrection: availability.retry_local_ai_correction,
    guidedReplaceResponse: availability.replace_response,
    guidedReviewDownloadAICorrection: {
      available: correctionAvailable,
      reason: correctionAvailable
        ? "Download the exact-response-bound correction packet for the same chat."
        : "No AI correction packet is required for the current build.",
    },
    guidedRetryLocalBuild: availability.retry_local_build,
    guidedEditBrief: availability.edit_brief_create_new_request,
    guidedCancel: availability.cancel_build,
  };
  for (const [id, state] of Object.entries(controls)) {
    const button = document.getElementById(id);
    if (!button) continue;
    if (id === "guidedRetryLocalAICorrection") {
      if (typeof run.run_id === "string" && run.run_id) button.dataset.runId = run.run_id;
      else delete button.dataset.runId;
    }
    if (id === "guidedRetryLocalAICorrection") button.hidden = state?.available !== true;
    button.disabled = state ? state.available !== true : true;
    button.title = state?.reason || "This action is not available for the current build state.";
  }
  const explanation = document.getElementById("guidedRecoveryExplanation");
  const localCorrectionAvailable = availability.retry_local_ai_correction?.available === true;
  if (explanation) explanation.textContent = guidedRunAtGmGate(run)
    ? "The build is complete. Write and approve the GM guidance in the Candidate GM review panel above, then use Retry Local Build here to run the final gates. Replace Response is not needed."
    : run.status === "NEEDS_REVIEW"
    ? `${localCorrectionAvailable ? "Fix with Local AI sends the exact retained response and validator issue to the selected Local AI while keeping this request frozen. " : ""}Replace Response imports a corrected answer for this exact request. Retry Local Build (no provider) reuses the saved answer. Edit Brief / Create New Request changes the brief and links a new run. Cancel ends this run without canonical mutation.`
    : "Replace Response and Retry Local Build preserve this frozen request. Edit Brief / Create New Request deliberately starts a linked request. Cancel ends this run without canonical mutation.";
  const history = document.getElementById("guidedAttemptHistory");
  if (!history) return;
  clearNode(history);
  const attempts = Array.isArray(run.attempt_history) ? run.attempt_history : [];
  if (!attempts.length) {
    const empty = document.createElement("p");
    empty.textContent = "No recorded attempts yet.";
    history.appendChild(empty);
    return;
  }
  for (const attempt of attempts) {
    const item = document.createElement("article");
    item.className = "attempt-history-item";
    const title = document.createElement("strong");
    title.textContent = `${friendlyLabel(attempt.action_type || "attempt")} — ${friendlyLabel(attempt.status || "recorded")}`;
    const detail = document.createElement("p");
    const blocker = Array.isArray(attempt.blockers) && attempt.blockers[0];
    detail.textContent = blocker?.message
      ? blocker.message
      : `${attempt.created_at || "Recorded"}${attempt.prior_attempt_id ? " · linked to the prior attempt" : ""}`;
    item.append(title, detail);
    history.appendChild(item);
  }
}

async function guidedCandidateGMAuthoringAction(action) {
  const runId = guidedRun?.run_id || guidedCandidateGMAuthoring.runId;
  if (!runId || guidedCandidateGMAuthoring.loading) return;
  if (action === "approve" && !guidedCandidateGMAuthoring.challenge) {
    setGuidedStatus("Issue an approval challenge after reviewing the staged GM evidence.", true);
    return;
  }
  guidedCandidateGMAuthoring.loading = true;
  renderGuidedCandidateGMAuthoring();
  try {
    let result;
    if (action === "author") {
      result = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate/author`, {method: "POST", body: "{}"});
    } else if (action === "build") {
      result = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate/author/build`, {method: "POST", body: "{}"});
    } else if (action === "issue") {
      result = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate/approval-challenge`, {method: "POST", body: JSON.stringify({ttl_seconds: 300})});
      guidedCandidateGMAuthoring.challenge = result.challenge || null;
    } else if (action === "approve") {
      const challenge = guidedCandidateGMAuthoring.challenge;
      result = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/gm-candidate/approve`, {
        method: "POST",
        body: JSON.stringify({challenge_id: challenge.challenge_id, nonce: challenge.nonce}),
      });
      guidedCandidateGMAuthoring.challenge = null;
    }
    await refreshGuidedCandidateGMAuthoring({run_id: runId}, {force: true});
    if (action === "approve") {
      // Approval changes only the candidate authority. Refresh the ordinary
      // run so the existing Retry Local Build control receives its server
      // computed availability and no client flag acts as authorization.
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`);
      renderGuidedCandidate(guidedRun);
      setGuidedStatus("The staged GM candidate is approved. Retry Local Build to run the normal two-scratch and live gates.");
    } else if (action === "issue") {
      setGuidedStatus("Approval challenge issued. Review the exact challenge details, confirm the checkbox, then approve the staged GM candidate.");
    } else if (result) {
      setGuidedStatus(action === "author" ? "The candidate GM receipt is ready for review." : "The saved candidate GM receipt was rebuilt for review.");
    }
  } catch (error) {
    recordGuidedDiagnostic(error, `candidate_gm_${action}`);
    setGuidedStatus(plainAPIError(error, "The staged GM action could not be completed."), true);
  } finally {
    guidedCandidateGMAuthoring.loading = false;
    renderGuidedCandidateGMAuthoring();
  }
}

document.getElementById("guidedCandidateGMAuthor")?.addEventListener("click", () => {
  void guidedCandidateGMAuthoringAction("author");
});
document.getElementById("guidedCandidateGMBuild")?.addEventListener("click", () => {
  void guidedCandidateGMAuthoringAction("build");
});
document.getElementById("guidedCandidateGMIssueApproval")?.addEventListener("click", () => {
  void guidedCandidateGMAuthoringAction("issue");
});
document.getElementById("guidedCandidateGMApprove")?.addEventListener("click", () => {
  void guidedCandidateGMAuthoringAction("approve");
});
document.getElementById("guidedCandidateGMApprovalConfirm")?.addEventListener("change", renderGuidedCandidateGMAuthoring);

function renderGuidedFinal(run) {
  const host = document.getElementById("guidedFinalSummary");
  clearNode(host);
  appendCandidateLine(host, "Status", "Clean and finalized", "success");
  appendCandidateLine(host, "Name", descriptiveFieldValue(run.owner_descriptive_fields, "name") || "Unnamed character");
  appendCandidateLine(host, "Title", descriptiveFieldValue(run.owner_descriptive_fields, "title") || "No title supplied");
  appendCandidateLine(host, "Concept", descriptiveFieldValue(run.owner_descriptive_fields, "concept") || "No concept supplied");
  appendCandidateLine(host, "Canonical commit", pretty(run.commit), "success");
  appendCandidateLine(host, "Approved candidate identity", run.commit?.approved_candidate_identity || run.dry_run?.candidate_identity || "Recorded");
  appendCandidateLine(host, "Approval authority", "Server-derived local principal");
  const aiPerformance = guidedAIPerformanceSummary(run);
  if (aiPerformance) appendCandidateLine(host, "AI time & tokens", aiPerformance);
  appendCandidateLine(host, "Portable Character", run.outputs?.portable_character ? "Produced and verified" : "See final output evidence");
   appendCandidateLine(host, "GM output", run.outputs?.gm_model || run.outputs?.gm_consumer ? "Produced and verified" : "See final output evidence");
   setGuidedStatus("Character finalized. The saved Character Sheet and its exports are on this page.");
    renderOwnerProductionSheet(run, false);
    if (ownerCharacterSheet) renderOwnerProductionSheet(null, true, ownerCharacterSheet);
    renderOwnerExportAvailability();
    renderOwnerPrimaryActions(run);
    setGuidedStep(4);
    void loadFinalOwnerSheet();
}

function guidedErrorSummary(run = guidedRun) {
  if (!run) return "No complete-character build has started.";
  const lines = [
    `Build status: ${run.status || "unknown"}`,
    guidedRunOwnerMessage(run),
  ];
  if (run.request?.request_sha256) lines.push(`Request: ${run.request.request_sha256}`);
  if (run.response?.response_sha256) lines.push(`Response: ${run.response.response_sha256}`);
  return lines.join("\n");
}

document.getElementById("guidedSaveDescriptiveFields").onclick = async () => {
  if (!guidedRun?.run_id) return;
  try {
    const name = document.getElementById("guidedProposedName").value.trim();
    const title = document.getElementById("guidedProposedTitle").value.trim();
    const concept = document.getElementById("guidedProposedConcept").value.trim();
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/descriptive-fields`, {
      method: "POST",
      body: JSON.stringify({name: name || null, title: title || null, concept: concept || null}),
    });
    renderGuidedCandidate(guidedRun);
    setGuidedStatus("Identity wording saved for this review. Mechanics and accepted catalog authority were not changed.");
  } catch (error) {
    recordGuidedDiagnostic(error, "save_descriptive_fields");
    setGuidedStatus(plainAPIError(error, "The identity wording could not be saved."), true);
  }
};

document.getElementById("guidedCopyErrorSummary").onclick = async () => {
  const summary = guidedErrorSummary();
  try {
    await navigator.clipboard.writeText(summary);
    setGuidedStatus("The plain error summary was copied. Full codes and details remain under Developer / Diagnostics.");
  } catch (_error) {
    setGuidedStatus(summary);
  }
};

document.getElementById("guidedDownloadEvidence").onclick = () => {
  if (!guidedRun?.run_id) return void setGuidedStatus("No build evidence is available yet.", true);
  window.location.assign(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/evidence.json`);
};

// Seeded builds use no AI (owner 2026-09-24); say so on the one-build save consent.
function syncSeededConsentLabel() {
  const seeded = Boolean((document.getElementById("guidedSeed")?.value || "").trim());
  const label = document.querySelector("#guidedLocalAutoConsentPanel strong");
  if (label) label.textContent = seeded ? "Allow this seeded build to save itself after a clean candidate (no AI is used)" : "Allow Local AI to save this build after a clean candidate";
}
document.getElementById("guidedSeed")?.addEventListener("input", syncSeededConsentLabel);
document.addEventListener("DOMContentLoaded", syncSeededConsentLabel);
setInterval(syncSeededConsentLabel, 1500);

async function startGuidedCompleteBuild() {
  if (!guidedProjectId) return void setGuidedStatus("Describe and continue the character first.", true);
  const route = guidedSelectedRoute;
  const mode = guidedExecutionMode();
  if (route === "LOCAL_AI") {
    const local = guidedLocalStatus?.provider ? guidedLocalStatus : await loadGuidedLocalStatus();
    const provider = local?.provider;
    if (!provider || !["local", "lemonade"].includes(provider.provider_id) || !provider.ready) {
      return void setGuidedStatus(provider?.readiness_reason || "Select a detected Local AI model and complete its explicit connection test before building.", true);
    }
  } else if (route === "STANDARD_API") {
    const provider = guidedProviderStatus || await loadGuidedProviderStatus();
    if (["local", "lemonade"].includes(provider?.provider_id)) {
      return void setGuidedStatus("API Provider is selected, but the saved transport is Local AI. Save and test an API Provider profile before building through this route.", true);
    }
    if (!provider?.ready) return void setGuidedStatus(provider?.readiness_reason || "Save and test the API Provider before building.", true);
  }
  guidedResponseSubmissionAction = "manual";
  const consent = route === "LOCAL_AI"
    ? document.getElementById("guidedLocalAutoFinalizeConsent")
    : document.getElementById("guidedAutoFinalizeConsent");
  if (mode === "AUTO_FINALIZE_WHEN_CLEAN" && !consent?.checked) {
    consent?.focus();
    const seeded = Boolean((document.getElementById("guidedSeed")?.value || "").trim());
    return void setGuidedStatus(seeded
      ? "Build & save automatically needs your OK for this one build: tick “Allow this seeded build to save itself” (the seed makes every choice; no AI is used), or choose a preview to review before saving."
      : route === "LOCAL_AI"
      ? "Build & save automatically requires explicit one-build consent. Check the Local AI consent box or choose a preview."
      : "Auto-Finalize is off by default. Check the explicit one-build consent box or choose another mode.", true);
  }
  document.getElementById("guidedStartBuild").disabled = true;
  const fallbackWarning = document.getElementById("guidedProviderFallbackWarning");
  if (fallbackWarning) {
    fallbackWarning.hidden = true;
    fallbackWarning.textContent = "";
  }
  setGuidedStatus(mode === "MANUAL_CHAT"
    ? "Preparing the complete CG1 request ZIP…"
    : route === "LOCAL_AI" && mode === "AUTO_FINALIZE_WHEN_CLEAN"
      ? "Local AI is filling the blank identity and legal choices, then will save only after a clean candidate. One bounded correction may run; a genuine blocker stops for review…"
      : route === "LOCAL_AI"
        ? "Local AI is building a preview for review. No automatic save is requested; review and Finalize when ready…"
        : "Building the complete candidate through the accepted shared pipeline…");
  const useController = guidedUsesController(route, mode);
  const showAIWorking = mode !== "MANUAL_CHAT";
  if (showAIWorking && useController) {
    startGuidedControllerProgress(guidedProjectId);
  } else if (showAIWorking) {
    startGuidedAIWorking(route === "LOCAL_AI"
      ? "Local AI is working on the complete character. A cold first reply can take up to 40 minutes; keep this page open and do not retry. The Factory will validate its result"
      : "The selected AI provider is working on the complete character. The Factory will validate its result");
  }
  try {
    await api(`/api/character-builder/projects/${encodeURIComponent(guidedProjectId)}/normal-first-cycle-catalog-choice-lock`, {method: "POST", body: "{}"});
    const startBody = {execution_mode: mode, idempotency_key: `primary.${Date.now()}.${crypto.randomUUID()}`};
    if (useController) startBody.controller_route = GUIDED_CONTROLLER_ROUTE;
    guidedRun = await api(`/api/projects/${encodeURIComponent(guidedProjectId)}/character-creation/runs`, {method: "POST", body: JSON.stringify(startBody)});
    stopGuidedAIWorking();
    if (useController) await refreshGuidedControllerProgress(guidedRun);
    applyGuidedExecutionPreference(guidedRun.execution_mode, guidedRun);
    if (route === "LOCAL_AI") {
      const localConsent = document.getElementById("guidedLocalAutoFinalizeConsent");
      if (localConsent) localConsent.checked = false;
    }
    renderGuidedCandidate(guidedRun);
    if (guidedRun.execution_mode === "MANUAL_CHAT" && guidedRun.status === "WAITING_FOR_RESPONSE") {
      const fallbackWarnings = (guidedRun.warnings || []).filter(row =>
        typeof row?.code === "string" && row.code.startsWith("CG1_PROVIDER_") && row.code.endsWith("_FALLBACK_MANUAL")
      );
      const fallbackWarning = document.getElementById("guidedProviderFallbackWarning");
      if (fallbackWarning) {
        fallbackWarning.textContent = fallbackWarnings.map(row => `${row.code}: ${row.message}`).join(" | ");
        fallbackWarning.hidden = fallbackWarnings.length === 0;
      }
      document.getElementById("guidedManualTransfer").hidden = false;
      document.getElementById("guidedDownloadCompleteRequest").disabled = false;
      renderGuidedResponseSourceState();
      document.getElementById("guidedBuildProgress").textContent = pretty({
        status: guidedRun.status,
        execution_mode: guidedRun.execution_mode,
        warnings: guidedRun.warnings || [],
        request_sha256: guidedRun.request?.request_sha256 || "recorded",
        canonical_mutation: "None",
      });
      setGuidedStatus(fallbackWarnings.length
        ? "The provider call failed or was unavailable. This run returned to Manual Chat, and no canonical mutation occurred. Follow the transfer instructions above."
        : "Complete request ready. No canonical mutation occurred. Download the ZIP, obtain one complete response, then build the complete candidate.");
      return;
    }
    const ownerState = ownerViewFor(guidedRun);
    const ownerDecisionBlocked = Array.isArray(ownerState.decisions) && ownerState.decisions.length > 0;
    const ownerBlockerBlocked = Array.isArray(ownerState.blockers) && ownerState.blockers.length > 0;
    if (mode === "AUTO_FINALIZE_WHEN_CLEAN" && guidedRun.status === "READY_FOR_REVIEW" && guidedRun.quality?.status === "CLEAN" && !(guidedRun.blockers || []).length && !ownerDecisionBlocked && !ownerBlockerBlocked && !hasSubstantiveCommit(guidedRun.commit)) {
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/auto-finalize-opt-in`, {method: "POST", body: "{}"});
      renderGuidedCandidate(guidedRun);
    }
  } catch (error) {
    stopGuidedAIWorking();
    setGuidedStatus(plainAPIError(error, "The complete-character build could not start."), true);
  } finally {
    stopGuidedAIWorking();
    document.getElementById("guidedStartBuild").disabled = false;
  }
}

document.querySelectorAll('input[name="guidedExecutionMode"]').forEach(input => input.addEventListener("change", () => {
  setGuidedRoute(input.value);
  updateGuidedModeUI();
}));
document.querySelectorAll('input[name="guidedLocalBuildMode"]').forEach(input => input.addEventListener("change", updateGuidedModeUI));
document.querySelectorAll("[data-guided-route]").forEach(button => {
  button.addEventListener("click", () => { setGuidedRoute(button.dataset.guidedRoute); updateGuidedModeUI(); });
  button.addEventListener("keydown", event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(document.querySelectorAll("[data-guided-route]"));
    const index = tabs.indexOf(button);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[nextIndex]?.focus();
    setGuidedRoute(tabs[nextIndex]?.dataset.guidedRoute);
    updateGuidedModeUI();
  });
});
setGuidedRoute("LOCAL_AI");
updateGuidedModeUI();
document.getElementById("guidedAutoFinalizeCapability")?.addEventListener("change", updateGuidedModeUI);
let guidedProviderDirty = false;
let guidedProviderStatus = null;
const GUIDED_PROVIDER_DEFAULTS = {
  openai: {endpoint: "https://api.openai.com/v1/chat/completions", model: "gpt-4o-mini", preset: true},
  deepseek: {endpoint: "https://api.deepseek.com/chat/completions", model: "deepseek-v4-flash", preset: true},
  custom: {endpoint: "", model: "compatible-model", preset: false},
  // The agent bridge makes no network call of its own: the app hands each
  // request to a harness-held agent through the durable mailbox and validates
  // the agent's answer exactly as it validates a provider answer.
  agent: {endpoint: "", model: "agent-authored", preset: true, agent: true},
};
function guidedProviderProfile() {
  return document.getElementById("guidedProviderProfile")?.value || "openai";
}
function updateGuidedProviderProfileFields({resetModel = false} = {}) {
  const profile = GUIDED_PROVIDER_DEFAULTS[guidedProviderProfile()] || GUIDED_PROVIDER_DEFAULTS.openai;
  const endpoint = document.getElementById("guidedProviderEndpoint");
  const model = document.getElementById("guidedProviderModel");
  if (endpoint) {
    if (profile.preset || !endpoint.value) endpoint.value = profile.endpoint;
    endpoint.readOnly = profile.preset;
    endpoint.setAttribute("aria-readonly", profile.preset ? "true" : "false");
  }
  if (model && (resetModel || !model.value || Object.values(GUIDED_PROVIDER_DEFAULTS).some(row => row.model === model.value))) model.value = profile.model;
  // The agent bridge holds no credential, so its key controls must not imply
  // one exists: hide the key field and disable (and hide) key removal.  The
  // cloud-sharing acknowledgement below stays untouched for every profile.
  const isAgentProfile = profile.agent === true;
  const keyRow = document.getElementById("guidedProviderKey")?.closest("label");
  if (keyRow) keyRow.hidden = isAgentProfile;
  const deleteKey = document.getElementById("guidedProviderDeleteKey");
  if (deleteKey) {
    deleteKey.hidden = isAgentProfile;
    deleteKey.disabled = isAgentProfile;
  }
}
function providerStatusMessage(status, dirty = false) {
  const display = status?.profile?.display_name || status?.settings?.provider_id || "API Provider";
  const saved = status?.readiness_reason || "Saved API Provider readiness is unknown.";
  const prefix = dirty ? "Settings not saved. " : "";
  // ``profile.agent`` is a boolean flag; compare it as one, and only then fall
  // back to the saved profile id.
  const isAgentProfile = status?.profile?.agent === true || status?.settings?.provider_id === "agent";
  if (isAgentProfile) {
    const pending = status?.agent_bridge?.pending ?? 0;
    return `${prefix}${saved} No key is stored; ${pending} request${pending === 1 ? "" : "s"} waiting for an agent answer.`;
  }
  const key = status?.secret?.present ? "Protected key stored." : "No protected key stored.";
  return `${prefix}${saved} ${key} Manual Chat remains available without ${display}.`;
}

// --- Agent bridge panel: pending counter, Copy prompt, Paste answer ----------
let guidedPendingAgentRequest = null;
function renderGuidedAgentBridge(status) {
  const panel = document.getElementById("guidedAgentBridgePanel");
  const label = document.getElementById("guidedAgentBridgeState");
  if (!panel) return;
  const isAgent = (status?.profile?.agent === true) || (status?.settings?.provider_id === "agent");
  panel.hidden = !isAgent;
  if (!isAgent) {
    guidedPendingAgentRequest = null;
    return;
  }
  const bridge = status?.agent_bridge || {};
  const pending = Number.isFinite(bridge.pending) ? bridge.pending : 0;
  if (label) label.textContent = pending
    ? `${pending} agent request${pending === 1 ? "" : "s"} waiting. Copy the prompt, answer it in your own agent, then paste the JSON answer back.`
    : "No agent request is waiting. The next authoring step appears here for your agent.";
}

// The answering agent is not the acknowledging owner: both are required from
// the owner's own agent, and neither is invented client-side.
const AGENT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;
const AGENT_MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:+/~-]{0,99}$/;
function guidedAgentIdentity() {
  const agentId = (document.getElementById("guidedAgentId")?.value || "").trim();
  const agentModel = (document.getElementById("guidedAgentModel")?.value || "").trim();
  if (!AGENT_ID_PATTERN.test(agentId)) return {error: "Enter the answering agent id (letters, digits, . _ : -)."};
  if (!AGENT_MODEL_PATTERN.test(agentModel)) return {error: "Enter the model that agent used (letters, digits, . _ : + / ~ -)."};
  return {agentId, agentModel};
}
function bindGuidedAgentRequest(request) {
  const idBox = document.getElementById("guidedAgentBoundRequest");
  const shaBox = document.getElementById("guidedAgentBoundRequestSha");
  if (idBox) idBox.value = request?.request_id || "";
  if (shaBox) shaBox.value = request?.request_sha256 || "";
}
async function loadGuidedPendingAgentRequest() {
  try {
    const listing = await api("/api/ai-provider/agent/requests?state=PENDING");
    guidedPendingAgentRequest = (listing?.requests || [])[0] || null;
    return guidedPendingAgentRequest;
  } catch (_error) {
    guidedPendingAgentRequest = null;
    return null;
  }
}
async function guidedAgentCopyPrompt() {
  const host = document.getElementById("guidedAgentBridgeState");
  try {
    const request = guidedPendingAgentRequest || await loadGuidedPendingAgentRequest();
    if (!request) { if (host) host.textContent = "No pending agent request to copy."; return; }
    const document_ = await api(`/api/ai-provider/agent/requests/${encodeURIComponent(request.request_id)}`);
    const messages = document_?.request_json?.messages || [];
    const rendered = messages.map(message => `## ${message.role}\n${message.content}`).join("\n\n");
    const schema = JSON.stringify(document_?.schema || {}, null, 2);
    const constants = document_?.request_json?.messages?.[1]?.content
      ? (() => { try { return JSON.parse(document_.request_json.messages[1].content)?.response_constants || null; } catch (_error) { return null; } })()
      : null;
    const constantsNote = constants && typeof constants.request_sha256 === "string"
      ? ` If your answer schema (or the prompt's response_constants) carries request_sha256, copy it exactly from the supplied response_constants (${constants.request_sha256}) and keep project_id, projection_id and candidate_sha256 as supplied there; those are inner lineage fields, not this transport hash.`
      : "";
    await navigator.clipboard.writeText(`${rendered}\n\n## response schema\n${schema}\n\nAnswer with one JSON object. Transport binding (mailbox): request_sha256 ${request.request_sha256} — this is the outer hash this submit posts back.${constantsNote}`);
    // Bind the copy to this exact request so a queue change cannot redirect
    // the pasted answer to a different step.
    bindGuidedAgentRequest(request);
    if (host) host.textContent = `Copied ${request.prompt_id} (${request.request_id}). Answer it with your own agent, then paste the JSON back.`;
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "The agent prompt could not be copied.");
  }
}
async function guidedAgentSubmitAnswer() {
  const host = document.getElementById("guidedAgentBridgeState");
  const box = document.getElementById("guidedAgentAnswerBox");
  if (!box) return;
  try {
    const identity = guidedAgentIdentity();
    if (identity.error) { if (host) host.textContent = identity.error; return; }
    const text = box.value.trim();
    if (!text) { if (host) host.textContent = "Paste one JSON answer first."; return; }
    // Prefer the request the prompt was copied from; fall back to the current
    // oldest pending request only when no copy has bound one yet.
    const boundId = document.getElementById("guidedAgentBoundRequest")?.value || "";
    const boundSha = document.getElementById("guidedAgentBoundRequestSha")?.value || "";
    const request = boundId
      ? await api(`/api/ai-provider/agent/requests/${encodeURIComponent(boundId)}`)
      : (guidedPendingAgentRequest || await loadGuidedPendingAgentRequest());
    if (!request) { if (host) host.textContent = "No pending agent request to answer."; return; }
    if (request.state !== "PENDING" && request.state !== "CLAIMED") {
      bindGuidedAgentRequest(null);
      if (host) host.textContent = `That request is ${request.state}; copy the current prompt before answering.`;
      return;
    }
    const requestSha = boundSha || request.request_sha256;
    await api(`/api/ai-provider/agent/requests/${encodeURIComponent(request.request_id)}/answer`, {method: "POST", body: JSON.stringify({
      agent_id: identity.agentId,
      agent_model: identity.agentModel,
      request_sha256: requestSha,
      response_text: text,
    })});
    box.value = "";
    bindGuidedAgentRequest(null);
    if (host) host.textContent = `Answer accepted from ${identity.agentId} (${identity.agentModel}) for ${request.prompt_id}. Re-run that step to finish it.`;
    await loadGuidedProviderStatus();
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "The agent answer was rejected; the request stays pending so you can retry.");
  }
}

function localCandidateStatus(candidate) {
  if (candidate?.ready) return "Ready — explicit connection test still applies when selected.";
  if (candidate?.loading) return "Loading / warming up — wait for the server to report ready.";
  if (candidate?.server_reachable) return "Server reachable, but no ready model is reported.";
  return "Not ready. Detection did not start or download this runtime.";
}

// The bundled Lemonade runtime is an optional extra; the detected local models
// are the normal path.  This reports the bundled runtime's real state instead
// of offering an always-enabled button that silently cannot work.
function renderGuidedBundledRuntimeState() {
  const host = document.getElementById("guidedBundledRuntimeState");
  if (!host) return;
  const managed = guidedLocalStatus?.managed || {};
  const stages = Array.isArray(managed.stages) ? managed.stages : [];
  const latest = stages.length ? stages[stages.length - 1] : null;
  if (managed.ready) {
    host.textContent = `Bundled runtime is ready: ${managed.model || "its model"} on ${managed.endpoint || "its loopback port"}.`;
    return;
  }
  if (managed.loading) {
    host.textContent = `Bundled runtime setup is running${latest ? `: ${latest.message}` : "…"}`;
    return;
  }
  if (managed.state === "ERROR") {
    host.textContent = `Bundled runtime setup failed: ${managed.error || "unknown error"}`;
    return;
  }
  host.textContent = `Bundled runtime is not running. Its model (${managed.default_model || managed.model || "the bundled model"}) has to be downloaded before this path can be used. Any model your own local server already serves is usable now from the list above.`;
}

// Probe one owner-supplied endpoint for its model list.  This is an explicit
// endpoint the owner names, not a scan: anything it has not entered is never
// contacted.
const LOCAL_ENDPOINT_KNOWN_SUFFIXES = Object.freeze(["/v1", "/api/v1", "/openai/v1"]);

function ownerEndpointBaseUrl(raw) {
  const text = String(raw || "").trim().replace(/\/+$/, "");
  if (!text) return "";
  const withScheme = /^https?:\/\//i.test(text) ? text : `http://${text}`;
  try {
    const url = new URL(withScheme);
    if (!url.hostname) return "";
    // A pasted completion URL is accepted and reduced to its base.
    let path = url.pathname.replace(/\/(chat\/completions|completions)$/i, "").replace(/\/+$/, "");
    if (!path) path = "";
    return `${url.protocol}//${url.host}${path}`;
  } catch (_error) {
    return "";
  }
}

function ownerEndpointModelUrls(base) {
  const suffix = LOCAL_ENDPOINT_KNOWN_SUFFIXES.find(candidate => base.toLowerCase().endsWith(candidate));
  if (suffix) return [`${base}/models`];
  return [...LOCAL_ENDPOINT_KNOWN_SUFFIXES.map(candidate => `${base}${candidate}/models`), `${base}/models`];
}

function ownerEndpointCompletionsUrl(base) {
  const suffix = LOCAL_ENDPOINT_KNOWN_SUFFIXES.find(candidate => base.toLowerCase().endsWith(candidate));
  return suffix ? `${base}/chat/completions` : `${base}/v1/chat/completions`;
}

async function probeOwnerEndpoint(rawBase) {
  const base = ownerEndpointBaseUrl(rawBase);
  if (!base) throw new Error("Enter an endpoint such as http://127.0.0.1:11442/v1");
  let lastError = "";
  for (const url of ownerEndpointModelUrls(base)) {
    try {
      const response = await fetch(url, {headers: {"Accept": "application/json"}});
      if (!response.ok) { lastError = `${url} returned ${response.status}`; continue; }
      const payload = await response.json();
      const rows = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload?.models) ? payload.models : [];
      const models = rows
        .map(row => (typeof row === "string" ? row : row?.id || row?.model || row?.name))
        .filter(value => typeof value === "string" && value.trim());
      if (!models.length) { lastError = `${url} listed no models`; continue; }
      return {base, modelsUrl: url, completionsUrl: ownerEndpointCompletionsUrl(base), models};
    } catch (error) {
      lastError = `${url}: ${String(error?.message || error)}`;
    }
  }
  throw new Error(lastError || "That endpoint did not answer with an OpenAI-compatible model list.");
}

function renderOwnerEndpointModels(probe) {
  const host = document.getElementById("guidedCustomEndpointModels");
  if (!host) return;
  clearNode(host);
  for (const model of probe.models) {
    const card = document.createElement("article");
    card.className = "local-ai-candidate";
    const heading = document.createElement("h5");
    heading.textContent = model;
    const details = document.createElement("p");
    details.textContent = `${probe.completionsUrl} · listed by the endpoint you entered`;
    const use = document.createElement("button");
    use.type = "button";
    use.className = "primary-action";
    use.textContent = "Use this AI";
    use.addEventListener("click", () => selectGuidedLocalCandidate(
      {provider_id: "local", model, endpoint: probe.completionsUrl, ready: true},
      use,
    ));
    card.append(heading, details, use);
    host.appendChild(card);
  }
}

function renderGuidedLocalCandidates(candidates = []) {
  const host = document.getElementById("guidedLocalCandidates");
  if (!host) return;
  clearNode(host);
  // The bundled Lemonade entry is a "download me first" placeholder, not a
  // usable model.  It only clutters the choice when its runtime is not ready,
  // so show it only once it can actually be selected.
  const usable = (Array.isArray(candidates) ? candidates : []).filter(
    candidate => candidate.provider_id !== "lemonade" || candidate.ready,
  );
  if (!usable.length) {
    const empty = document.createElement("p");
    empty.className = "availability-note";
    empty.textContent = "No compatible running local model was found on the bounded loopback ports.";
    host.appendChild(empty);
    return;
  }
  for (const candidate of usable) {
    const card = document.createElement("article");
    card.className = "local-ai-candidate";
    const heading = document.createElement("h5");
    heading.textContent = candidate.display_name || candidate.model || "Local model";
    card.appendChild(heading);
    const details = document.createElement("p");
    details.textContent = `${candidate.model || "Model not reported"} · ${candidate.runtime || "OpenAI-compatible local server"} · ${candidate.endpoint || "Endpoint pending"}`;
    card.appendChild(details);
    const state = document.createElement("p");
    state.className = candidate.ready ? "local-ai-ready" : "local-ai-not-ready";
    state.textContent = localCandidateStatus(candidate);
    card.appendChild(state);
    if (candidate.endpoint && candidate.model && candidate.provider_id === "local" && candidate.ready) {
      const use = document.createElement("button");
      use.type = "button";
      use.className = "primary-action";
      use.textContent = "Use this AI";
      use.addEventListener("click", () => selectGuidedLocalCandidate(candidate, use));
      card.appendChild(use);
    }
    host.appendChild(card);
  }
}

async function loadGuidedLocalStatus() {
  const host = document.getElementById("guidedLocalStatus");
  try {
    const status = await api("/api/local-ai/status");
    guidedLocalStatus = status;
    const provider = status?.provider;
    const managed = status?.managed || {};
    const managedPrepare = document.getElementById("guidedManagedPrepare");
    if (managedPrepare) managedPrepare.disabled = !!managed.loading;
    const progress = document.getElementById("guidedManagedProgress");
    const latestStage = Array.isArray(managed.stages) && managed.stages.length ? managed.stages[managed.stages.length - 1] : null;
    if (progress && (managed.loading || managed.state === "ERROR" || managed.ready)) {
      progress.hidden = false;
      progress.textContent = latestStage ? `${latestStage.stage}: ${latestStage.state} — ${latestStage.message}` : managed.ready ? "Built-in Local AI is ready." : managed.error || "Built-in Local AI setup is waiting.";
    }
    if (host) {
      const settings = provider?.settings || {};
      const active = provider && ["local", "lemonade"].includes(provider.provider_id) && provider.ready
        ? `Active model: ${ownerSheetRunnableName(settings.model) || "selected"} at ${ownerSheetRunnableName(settings.endpoint) || "its endpoint"}.`
        : "";
      host.textContent = provider
        ? [provider.readiness_reason || "Local AI status loaded.", active].filter(Boolean).join(" ")
        : "Local AI status loaded.";
    }
    if (provider && ["local", "lemonade"].includes(provider.provider_id)) setGuidedRoute("LOCAL_AI");
    renderGuidedBundledRuntimeState();
    updateGuidedModeUI();
    if (managed.loading) {
      if (guidedLocalPollTimer) clearTimeout(guidedLocalPollTimer);
      guidedLocalPollTimer = setTimeout(loadGuidedLocalStatus, 1000);
    } else if (guidedLocalPollTimer) {
      clearTimeout(guidedLocalPollTimer);
      guidedLocalPollTimer = null;
    }
    return status;
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "Local AI status could not be loaded.");
    return null;
  }
}

async function detectGuidedLocalAI() {
  const host = document.getElementById("guidedLocalStatus");
  const button = document.getElementById("guidedDetectLocalAI");
  if (button) button.disabled = true;
  if (host) host.textContent = "Checking bounded loopback ports for running local models…";
  try {
    const result = await api("/api/local-ai/detect", {method: "POST", body: "{}"});
    guidedLocalStatus = result;
    renderGuidedLocalCandidates(result.candidates || []);
    if (host) host.textContent = `${(result.candidates || []).filter(row => row.provider_id === "local").length} running local model candidate(s) found. Nothing was started or downloaded.`;
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "Local AI detection failed.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function selectGuidedLocalCandidate(candidate, button) {
  if (button) button.disabled = true;
  const host = document.getElementById("guidedLocalStatus");
  if (host) host.textContent = `Selecting ${candidate.model} and running the explicit connection test…`;
  try {
    const selected = await api("/api/local-ai/select", {method: "POST", body: JSON.stringify({endpoint: candidate.endpoint, model: candidate.model, provider_id: "local"})});
    setGuidedRoute("LOCAL_AI");
    await loadGuidedLocalStatus();
    const test = selected?.selection_test || guidedLocalStatus?.provider?.selection_test || {};
    if (host) {
      if (test.status === "FAILED") host.textContent = `That model did not pass its connection test: ${test.message || "unknown failure"}`;
      else if (test.status === "PASS") host.textContent = `Selected ${candidate.model} at ${candidate.endpoint}. Its explicit connection test passed; the build can start now.`;
      else host.textContent = `Selected ${candidate.model} at ${candidate.endpoint}. Connection test status: ${test.status || "not reported"}.`;
    }
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "The selected local model did not pass its explicit connection test.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function selectGuidedManagedLocal() {
  const host = document.getElementById("guidedBundledRuntimeState") || document.getElementById("guidedLocalStatus");
  const button = document.getElementById("guidedManagedSelect");
  if (button) button.disabled = true;
  try {
    const requested = guidedLocalStatus?.managed?.model || guidedLocalStatus?.managed?.default_model || "Qwen3-4B-GGUF";
    await api("/api/local-ai/managed/select", {method: "POST", body: JSON.stringify({model: requested})});
    setGuidedRoute("LOCAL_AI");
    await loadGuidedLocalStatus();
    // Selecting the bundled profile only helps if its runtime is actually up.
    if (host) {
      const managed = guidedLocalStatus?.managed || {};
      host.textContent = managed.ready
        ? `Bundled runtime selected: ${managed.model}.`
        : `Bundled runtime selected, but it is not running yet (state ${managed.state || "unknown"}). Press "Download and start bundled runtime", or use a model your own local server already serves.`;
    }
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "The bundled Local AI could not be selected.");
  } finally {
    if (button) button.disabled = false;
    renderGuidedBundledRuntimeState();
  }
}

async function prepareGuidedManagedLocal() {
  const host = document.getElementById("guidedManagedProgress");
  const button = document.getElementById("guidedManagedPrepare");
  if (button) button.disabled = true;
  if (host) { host.hidden = false; host.textContent = "Starting built-in Local AI setup…"; }
  try {
    const requested = guidedLocalStatus?.managed?.model || guidedLocalStatus?.managed?.default_model || "Qwen3-4B-GGUF";
    await api("/api/local-ai/managed/prepare", {method: "POST", body: JSON.stringify({model: requested})});
    setGuidedRoute("LOCAL_AI");
    await loadGuidedLocalStatus();
    const managed = guidedLocalStatus?.managed || {};
    if (host) {
      host.textContent = managed.loading
        ? "Bundled runtime setup is running. Progress is polled here; this page stays usable."
        : managed.ready
          ? "Bundled runtime is ready."
          : `Bundled runtime did not start. ${managed.error || "Check the staged messages above."} A model your own local server already serves needs no download.`;
    }
  } catch (error) {
    if (host) host.textContent = plainAPIError(error, "Bundled Local AI setup could not start.");
  } finally {
    if (button) button.disabled = false;
    renderGuidedBundledRuntimeState();
  }
}

async function loadGuidedProviderStatus() {
  const host = document.getElementById("guidedProviderStatus");
  try {
    const status = await api("/api/ai-provider");
    guidedProviderStatus = status;
    const settings = status.settings || {};
    if (["local", "lemonade"].includes(settings.provider_id || status.provider_id)) {
      setGuidedRoute("LOCAL_AI");
      await loadGuidedLocalStatus();
      host.textContent = "Local AI is selected. Choose the Local AI route to manage loopback models.";
      return status;
    }
    document.getElementById("guidedProviderProfile").value = settings.provider_id || status.provider_id || "deepseek";
    updateGuidedProviderProfileFields();
    document.getElementById("guidedProviderEndpoint").value = settings.endpoint || GUIDED_PROVIDER_DEFAULTS[guidedProviderProfile()].endpoint;
    document.getElementById("guidedProviderModel").value = settings.model || GUIDED_PROVIDER_DEFAULTS[guidedProviderProfile()].model;
    document.getElementById("guidedProviderEnabled").checked = !!settings.enabled;
    document.getElementById("guidedProviderAcknowledged").checked = !!settings.data_sharing_acknowledged;
    document.getElementById("guidedProviderActor").value = settings.acknowledged_by || "";
    const waitInput = document.getElementById("guidedProviderAgentWait");
    if (waitInput) waitInput.value = String(status.agent_bridge?.wait_seconds || settings.agent_wait_seconds || 300);
    guidedProviderDirty = false;
    host.textContent = providerStatusMessage(status);
    renderGuidedAgentBridge(status);
    if ((status.profile?.agent === true) || status.provider_id === "agent") await loadGuidedPendingAgentRequest();
    return status;
  } catch (error) { host.textContent = plainAPIError(error, "Provider status could not be loaded."); return null; }
}
document.getElementById("guidedProviderSave").onclick = async () => {
  const host = document.getElementById("guidedProviderStatus");
  const keyInput = document.getElementById("guidedProviderKey");
  const key = keyInput.value;
  try {
    await api("/api/ai-provider/configure", {method: "POST", body: JSON.stringify({
      enabled: document.getElementById("guidedProviderEnabled").checked,
      provider_id: guidedProviderProfile(),
      endpoint: document.getElementById("guidedProviderEndpoint").value.trim() || null,
      model: document.getElementById("guidedProviderModel").value.trim(),
      thinking_mode: "disabled", max_output_tokens: 16384, timeout_seconds: 120,
      agent_wait_seconds: Number(document.getElementById("guidedProviderAgentWait")?.value || 300),
      data_sharing_acknowledged: document.getElementById("guidedProviderAcknowledged").checked,
      acknowledged_by: document.getElementById("guidedProviderActor").value.trim() || null,
    })});
    const isAgentProfile = guidedProviderProfile() === "agent";
    if (key && !isAgentProfile) await api("/api/ai-provider/key", {method: "POST", body: JSON.stringify({api_key: key})});
    keyInput.value = "";
    await loadGuidedProviderStatus();
    if (isAgentProfile) {
      host.textContent = `${host.textContent} The agent bridge holds no key; hand each request to your own agent.`;
    } else if (guidedProviderStatus?.secret?.present && guidedProviderStatus?.settings?.enabled) {
      host.textContent = "API Provider settings saved. Testing the configured connection once…";
      await api("/api/ai-provider/test", {method: "POST", body: "{}"});
      await loadGuidedProviderStatus();
      host.textContent = `${host.textContent} Connection test passed. (run Test Connection once remains available for a repeat check.)`;
    } else host.textContent = `${host.textContent} Save and test is ready when a protected key is available.`;
  } catch (error) {
    keyInput.value = "";
    host.textContent = plainAPIError(error, "API Provider settings were not saved.");
  }
};
document.getElementById("guidedProviderDeleteKey").onclick = async () => {
  try { await api("/api/ai-provider/key", {method: "DELETE"}); document.getElementById("guidedProviderKey").value = ""; await loadGuidedProviderStatus(); }
  catch (error) { document.getElementById("guidedProviderStatus").textContent = plainAPIError(error, "The protected API Provider key was not deleted."); }
};
document.getElementById("guidedProviderTest").onclick = async () => {
  const host = document.getElementById("guidedProviderStatus");
  host.textContent = "Testing the configured API Provider connection once…";
  try { await api("/api/ai-provider/test", {method: "POST", body: "{}"}); await loadGuidedProviderStatus(); }
  catch (error) { await loadGuidedProviderStatus(); host.textContent = `${host.textContent} ${plainAPIError(error, "API Provider connection test failed.")}`; }
};
["guidedProviderProfile", "guidedProviderEndpoint", "guidedProviderModel", "guidedProviderEnabled", "guidedProviderAcknowledged", "guidedProviderActor"].forEach(id => {
  const input = document.getElementById(id);
  const eventName = input.type === "checkbox" ? "change" : "input";
  input.addEventListener(eventName, () => {
    if (id === "guidedProviderProfile") updateGuidedProviderProfileFields({resetModel: true});
    guidedProviderDirty = true;
    const host = document.getElementById("guidedProviderStatus");
    host.textContent = providerStatusMessage(guidedProviderStatus, true);
  });
});
document.getElementById("guidedAgentCopyPrompt")?.addEventListener("click", guidedAgentCopyPrompt);
document.getElementById("guidedAgentSubmitAnswer")?.addEventListener("click", guidedAgentSubmitAnswer);
document.getElementById("guidedDetectLocalAI")?.addEventListener("click", detectGuidedLocalAI);
document.getElementById("guidedManagedSelect")?.addEventListener("click", selectGuidedManagedLocal);
document.getElementById("guidedManagedPrepare")?.addEventListener("click", prepareGuidedManagedLocal);

document.getElementById("guidedCustomEndpointProbe")?.addEventListener("click", async () => {
  const status = document.getElementById("guidedCustomEndpointStatus");
  const host = document.getElementById("guidedCustomEndpointModels");
  const button = document.getElementById("guidedCustomEndpointProbe");
  const raw = document.getElementById("guidedCustomEndpointUrl")?.value || "";
  if (host) clearNode(host);
  if (button) button.disabled = true;
  if (status) status.textContent = "Asking that endpoint which models it serves…";
  try {
    const probe = await probeOwnerEndpoint(raw);
    if (status) status.textContent = `${probe.models.length} model${probe.models.length === 1 ? "" : "s"} found at ${probe.modelsUrl}. Nothing was started or downloaded.`;
    renderOwnerEndpointModels(probe);
  } catch (error) {
    if (status) status.textContent = String(error?.message || error);
  } finally {
    if (button) button.disabled = false;
  }
});
loadGuidedProviderStatus();
loadGuidedLocalStatus();
document.getElementById("guidedStartBuild").onclick = startGuidedCompleteBuild;
document.getElementById("guidedDownloadCompleteRequest").onclick = window.TianxiaCompleteRequestSave.createController({
  getRunId: () => guidedRun?.run_id,
  getNativeSave: () => window.pywebview?.api?.save_complete_request,
  getBrowserSave: () => runId => window.TianxiaCompleteRequestSave.saveWithBrowser(runId),
  button: document.getElementById("guidedDownloadCompleteRequest"),
  status: document.getElementById("guidedDownloadCompleteRequestStatus"),
  navigate: url => window.location.assign(url),
});
function downloadGuidedAICorrection() {
  if (guidedRun?.run_id && guidedRun.execution_mode === "MANUAL_CHAT" && guidedRun.manual_ai_correction?.required === true) {
    window.location.assign(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/manual-ai-correction.zip`);
  }
}
document.getElementById("guidedDownloadAICorrection").onclick = downloadGuidedAICorrection;
document.getElementById("guidedReviewDownloadAICorrection").onclick = downloadGuidedAICorrection;

function guidedResponseSourceName() {
  if (guidedCompleteResponseSource.kind === "file") return guidedCompleteResponseSource.file?.name || "selected file";
  if (guidedCompleteResponseSource.kind === "paste") return "pasted response";
  return "none";
}

function renderGuidedResponseSourceState(message = null, isError = false) {
  const source = guidedCompleteResponseSource;
  const state = document.getElementById("guidedResponseSourceState");
  const status = document.getElementById("guidedCompleteReplyStatus");
  const submit = document.getElementById("guidedSubmitCompleteResponse");
  const remove = document.getElementById("guidedRemoveCompleteReply");
  const replace = document.getElementById("guidedReplaceCompleteReply");
  const label = source.kind === "file"
    ? `Response source: file — ${source.file?.name || "selected file"}. Pasted text is cleared.`
    : source.kind === "paste"
      ? "Response source: paste — the selected file, if any, was cleared."
      : "Response source: none. Choose a file or paste a response.";
  if (state) {
    state.textContent = message || label;
    state.classList.toggle("error", isError);
    state.classList.toggle("success", !isError && source.kind !== "none");
  }
  if (status && message) {
    status.textContent = message;
    status.classList.toggle("error", isError);
    status.classList.toggle("success", !isError && source.kind !== "none");
  }
  if (submit) submit.disabled = source.kind === "none" || !guidedRun?.run_id;
  if (remove) remove.disabled = source.kind === "none";
  if (replace) replace.disabled = !guidedRun?.run_id;
  renderGuidedResponseProcessing(guidedRun, guidedRun?.submission_error || guidedRun?.validation?.last_submission_error ? "result" : source.kind !== "none" ? "selected" : "idle");
}

function setGuidedImportTab(tab) {
  const paste = tab === "paste";
  const pasteTab = document.getElementById("guidedPasteTab");
  const fileTab = document.getElementById("guidedFileTab");
  const pastePanel = document.getElementById("guidedPasteImport");
  const filePanel = document.getElementById("guidedFileImport");
  if (pasteTab) pasteTab.setAttribute("aria-selected", paste ? "true" : "false");
  if (fileTab) fileTab.setAttribute("aria-selected", paste ? "false" : "true");
  if (pastePanel) pastePanel.hidden = !paste;
  if (filePanel) filePanel.hidden = paste;
}
document.getElementById("guidedPasteTab")?.addEventListener("click", () => setGuidedImportTab("paste"));
document.getElementById("guidedFileTab")?.addEventListener("click", () => setGuidedImportTab("file"));
setGuidedImportTab("file");

function resetGuidedResponseSource(message = null) {
  guidedCompleteResponseSource = {kind: "none", file: null};
  const text = document.getElementById("guidedCompleteResponseText");
  const file = document.getElementById("guidedCompleteReplyFile");
  if (text) text.value = "";
  if (file) file.value = "";
  renderGuidedResponseSourceState(message);
}

function removeGuidedResponseSource() {
  resetGuidedResponseSource("Response source removed. Choose a new file or paste a new response.");
}

function selectGuidedResponseFile(file) {
  const unchanged = guidedCompleteResponseSource.kind === "none"
    ? " No response source is currently selected."
    : " The current response source was not changed.";
  if (!file) {
    renderGuidedResponseSourceState(`Drop or choose one response file. A folder or empty drop is not a response file.${unchanged}`, true);
    return false;
  }
  const name = String(file.name || "");
  const extensionValid = /\.(zip|json|md|txt)$/i.test(name);
  const sizeValid = Number(file.size || 0) > 0 && Number(file.size || 0) <= 16 * 1024 * 1024;
  if (!extensionValid) {
    renderGuidedResponseSourceState(`That file was not accepted. Choose one .zip, .json, .md, or .txt response file.${unchanged}`, true);
    return false;
  }
  if (!sizeValid) {
    renderGuidedResponseSourceState(`That file was not accepted. The response must be larger than 0 bytes and no more than 16 MB.${unchanged}`, true);
    return false;
  }
  guidedCompleteResponseSource = {kind: "file", file};
  const text = document.getElementById("guidedCompleteResponseText");
  if (text) text.value = "";
  renderGuidedResponseSourceState(`${name} selected. This file replaces any pasted response; Remove or Replace it before choosing another source.`);
  return true;
}

function chooseGuidedResponseFile() {
  document.getElementById("guidedCompleteReplyFile")?.click();
}

const completeReplyFile = document.getElementById("guidedCompleteReplyFile");
document.getElementById("guidedChooseCompleteReply").onclick = event => { event.stopPropagation(); chooseGuidedResponseFile(); };
document.getElementById("guidedReplaceCompleteReply").onclick = event => { event.stopPropagation(); chooseGuidedResponseFile(); };
document.getElementById("guidedRemoveCompleteReply").onclick = event => { event.stopPropagation(); removeGuidedResponseSource(); };
completeReplyFile.onchange = () => { selectGuidedResponseFile(completeReplyFile.files?.[0] || null); completeReplyFile.value = ""; };
const completeDrop = document.getElementById("guidedCompleteReplyDrop");
completeDrop.onclick = event => { if (!["guidedChooseCompleteReply", "guidedReplaceCompleteReply", "guidedRemoveCompleteReply"].includes(event.target.id)) chooseGuidedResponseFile(); };
completeDrop.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); chooseGuidedResponseFile(); } };
for (const type of ["dragenter", "dragover"]) completeDrop.addEventListener(type, event => { event.preventDefault(); completeDrop.classList.add("active"); });
for (const type of ["dragleave", "drop"]) completeDrop.addEventListener(type, event => { event.preventDefault(); completeDrop.classList.remove("active"); });
completeDrop.addEventListener("drop", event => {
  const files = Array.from(event.dataTransfer?.files || []);
  if (files.length !== 1) {
    renderGuidedResponseSourceState(files.length > 1 ? "Drop one response file at a time. The current response source was not changed." : "That drop did not contain one response file. Choose a .zip, .json, .md, or .txt file.", true);
    return;
  }
  selectGuidedResponseFile(files[0]);
});
document.getElementById("guidedCompleteResponseText").addEventListener("input", event => {
  if (event.target.value.trim()) {
    guidedCompleteResponseSource = {kind: "paste", file: null};
    if (completeReplyFile) completeReplyFile.value = "";
    renderGuidedResponseSourceState("Response source: paste. Any previously selected file was cleared.");
  } else if (guidedCompleteResponseSource.kind === "paste") {
    resetGuidedResponseSource();
  }
});
renderGuidedResponseSourceState();

document.getElementById("guidedSubmitCompleteResponse").onclick = async () => {
  if (!guidedRun?.run_id) return void setGuidedStatus("Prepare the complete request first.", true);
  const source = guidedCompleteResponseSource;
  const pasted = source.kind === "paste" ? document.getElementById("guidedCompleteResponseText").value.trim() : "";
  if (source.kind === "none" || (source.kind === "paste" && !pasted) || (source.kind === "file" && !source.file)) {
    return void setGuidedStatus("Choose one complete response file or paste the complete response JSON. Remove the current source before selecting a different one.", true);
  }
  setGuidedStatus("Validating the response and running two isolated complete-character builds…");
  renderGuidedResponseProcessing(guidedRun, "submitting");
  try {
    if (source.kind === "file") {
      const endpoint = guidedResponseSubmissionAction === "replace" ? "replace-response-file" : "manual-response-file";
      const response = await fetch(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/${endpoint}?filename=${encodeURIComponent(source.file.name)}`, {method: "POST", headers: {"X-Foundry-Token": token, "Content-Type": "application/octet-stream"}, body: await source.file.arrayBuffer()});
      const data = await response.json();
      if (!response.ok) throw new Error(pretty(data));
      guidedRun = data;
    } else {
      const endpoint = guidedResponseSubmissionAction === "replace" ? "replace-response" : "manual-response";
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/${endpoint}`, {method: "POST", body: JSON.stringify({response_text: pasted, request_sha256: guidedRun.request.request_sha256})});
    }
    guidedResponseSubmissionAction = "manual";
    renderGuidedCandidate(guidedRun);
  } catch (error) {
    recordGuidedDiagnostic(error, "submit_complete_response");
    const parsed = parseAPIError(error);
    try {
      const refreshed = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}`);
      guidedRun = refreshed;
      renderGuidedCandidate(guidedRun);
      setGuidedStatus(guidedRunOwnerMessage(guidedRun), true);
    } catch (_refreshError) {
      setGuidedStatus(parsed.message || "The complete response could not be compiled.", true);
      renderGuidedResponseProcessing(guidedRun, "result");
    }
  }
};

document.getElementById("guidedFinalize").onclick = async () => {
  const button = document.getElementById("guidedFinalize");
  if (!guidedRun?.run_id || guidedFinalizeInFlight) return;
  guidedFinalizeInFlight = true;
  if (button) button.disabled = true;
  renderOwnerPrimaryActions(guidedRun);
  let failed = false;
  setGuidedStatus("Finalizing through the accepted atomic pipeline…");
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/finalize`, {method: "POST", body: "{}"});
    guidedProjectLifecycle = await api(`/api/character-builder/projects/${encodeURIComponent(guidedProjectId)}/lifecycle`);
    renderGuidedPersistence();
    await loadProjects();
    // One page (plan 2026-09-13): Finalize never navigates.  Stay on step 4,
    // rebuild the page in place, and put the owner back at the top so the
    // finalized action row and the saved sheet are in view.
    renderGuidedCandidate(guidedRun);
    setGuidedStep(4);
    document.getElementById("builderReview")?.scrollIntoView?.({behavior: "smooth", block: "start"});
  } catch (error) {
    failed = true;
    const diagnostic = parseAPIError(error);
    // A restart or a dropped connection is not a validation failure: say so
    // plainly and let the owner press Finalize again.
    const networkFailure = error instanceof TypeError
      || /failed to fetch|networkerror|network error|load failed|err_connection_refused|err_empty_response|err_network/i.test(String(error?.message || ""));
    if (diagnostic.code === "CG1_FINALIZATION_IN_PROGRESS" && diagnostic.details?.same_run === true && guidedRun) {
      // This character is already finalizing (another tab or a reload):
      // follow it instead of reporting an error.
      guidedRun = {...guidedRun, finalize_in_progress: true};
      watchFinalizeInProgress(guidedRun);
      return;
    }
    setGuidedStatus(networkFailure
      ? "The Factory was restarting; press Finalize again."
      : plainAPIError(error, "The character could not be finalized."), true);
    if (!networkFailure && isManualLineageBoundedChoiceDiagnostic(diagnostic)) openManualLineageResolver(diagnostic);
  } finally {
    guidedFinalizeInFlight = false;
    if (button && (failed || guidedRun?.status !== "CLEAN_AND_FINALIZED")) button.disabled = false;
    renderOwnerPrimaryActions(guidedRun);
  }
};

document.getElementById("guidedReplaceResponse").onclick = async () => {
  if (!guidedRun?.run_id) return;
  guidedResponseSubmissionAction = "replace";
  setGuidedStep(3);
  setGuidedRoute("MANUAL_CHAT");
  updateGuidedModeUI();
  document.getElementById("guidedManualTransfer").hidden = false;
  document.getElementById("guidedDownloadCompleteRequest").disabled = false;
  resetGuidedResponseSource("Replace Response selected. Choose one corrected response for this exact request.");
  setGuidedStatus("Replace Response keeps the frozen request and preserves the prior attempt history. Choose the corrected response now.");
};

document.getElementById("guidedRetryLocalBuild").onclick = async () => {
  if (!guidedRun?.run_id) return;
  setGuidedStatus("Retrying the saved response locally. No external provider call will be made…");
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/retry-local-build`, {method: "POST", body: "{}"});
    renderGuidedCandidate(guidedRun);
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The saved response could not be retried locally."), true);
  }
};

document.getElementById("guidedResumeControllerWalk").onclick = async () => {
  const button = document.getElementById("guidedResumeControllerWalk");
  if (!button || button.disabled) return;
  const runId = button.dataset.runId || guidedRun?.run_id;
  if (!runId) return void setGuidedStatus("The on-screen build has no guided walk to resume.", true);
  button.disabled = true;
  startGuidedControllerProgress(guidedProjectId, runId);
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/controller/continue`, {method: "POST", body: "{}"});
    stopGuidedAIWorking();
    await refreshGuidedControllerProgress(guidedRun);
    renderGuidedCandidate(guidedRun);
    if (guidedRun.status === "NEEDS_REVIEW") {
      setGuidedStatus("The guided build stopped again; the step and reason are listed above. Resume once the Local AI is responsive, or use another recovery action.", true);
    } else {
      setGuidedStatus("The guided build resumed from its saved step and the Factory validated the result. Review it before Finalize.");
    }
  } catch (error) {
    stopGuidedAIWorking();
    updateGuidedControllerResume(guidedRun);
    setGuidedStatus(plainAPIError(error, "The guided build could not be resumed."), true);
  }
};

document.getElementById("guidedRetryLocalAICorrection").onclick = async () => {
  const button = document.getElementById("guidedRetryLocalAICorrection");
  if (!button || button.disabled) return;
  const runId = button.dataset.runId;
  if (!runId) return void setGuidedStatus("The on-screen build has no repair target. Reopen the saved build before trying again.", true);
  button.disabled = true;
  startGuidedAIWorking("Local AI is working on one bounded repair. A cold first reply can take up to 40 minutes; keep this page open and do not retry. It will choose only the replacement needed for the blocker; every other saved character field remains untouched");
  try {
    const correctedRun = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}/retry-local-ai-correction`, {method: "POST", body: "{}"});
    stopGuidedAIWorking();
    guidedRun = correctedRun;
    renderGuidedCandidate(guidedRun);
    if (guidedRun.transport?.local_correction?.status === "FAILED") {
      setGuidedStatus("Local AI could not produce an accepted correction. The original response remains retained; choose this action again or use Replace Response.", true);
    } else if (guidedRun.status === "NEEDS_REVIEW") {
      setGuidedStatus("Local AI returned a correction, but the Factory still needs review. The request and attempt history remain frozen.", true);
    } else {
      setGuidedStatus("Local AI returned a correction for the frozen request. Review it before Finalize.");
    }
  } catch (error) {
    stopGuidedAIWorking();
    const failureMessage = plainAPIError(error, "Local AI could not correct the retained response; the saved response remains available.");
    try {
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`);
      renderGuidedCandidate(guidedRun);
    } catch (_refreshError) {}
    setGuidedStatus(`Local AI repair stopped: ${failureMessage}`, true);
  } finally {
    stopGuidedAIWorking();
    renderGuidedRecoveryActions(guidedRun, Boolean(guidedRun));
  }
};

document.getElementById("guidedEditBrief").onclick = async () => {
  if (!guidedRun?.run_id) return;
  try {
    const ownerNotes = document.getElementById("guidedRevisionNotes").value;
    const prepared = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/edit-brief/prepare`, {method: "POST", body: JSON.stringify({owner_notes: ownerNotes, brief: {owner_notes: ownerNotes}, user_locks: []})});
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/edit-brief-create-new-request`, {method: "POST", body: JSON.stringify({edit_id: prepared.edit_id})});
    guidedResponseSubmissionAction = "manual";
    resetGuidedResponseSource();
    setGuidedStep(3);
    setGuidedRoute("MANUAL_CHAT");
    updateGuidedModeUI();
    document.getElementById("guidedManualTransfer").hidden = false;
    document.getElementById("guidedDownloadCompleteRequest").disabled = false;
    renderGuidedResponseSourceState();
    setGuidedStatus("A linked new request was created. The prior response and blockers remain in Attempt history; this new request has its own response binding.");
  } catch (error) { setGuidedStatus(plainAPIError(error, "A revision request could not be prepared."), true); }
};

document.getElementById("guidedCancel").onclick = async () => {
  if (!guidedRun?.run_id) return;
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/cancel`, {method: "POST", body: "{}"});
    renderGuidedRecoveryActions(guidedRun, false);
    document.getElementById("guidedBuildProgress").textContent = pretty(guidedRun);
    setGuidedStatus("Build cancelled. No canonical character changes were committed.");
    renderOwnerPrimaryActions(guidedRun);
    setGuidedStep(4);
  } catch (error) { setGuidedStatus(plainAPIError(error, "The build could not be cancelled."), true); }
};

document.getElementById("guidedBack").onclick = async () => { await startNewCharacter("quick"); };

document.getElementById("builderProgress1").addEventListener("click", async () => { await startNewCharacter("quick"); });
document.getElementById("builderProgress1").addEventListener("keydown", async event => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    await startNewCharacter("quick");
  }
});

document.getElementById("guidedOpenCharacter").onclick = async () => {
  showScreen("projects");
  await loadProjects();
  await refreshSelectedProject();
  await refreshStage2Status();
};

// Seeded ancient-style names by Dao (owner 2026-09-27): six to choose from; the seed shown draws the same six again.
document.getElementById("guidedNameDice")?.addEventListener("click", async () => {
  const seedInput = document.getElementById("guidedNameSeed");
  const host = document.getElementById("guidedNameChoices");
  const params = new URLSearchParams({count: "6"});
  const seed = seedInput?.value.trim();
  const dao = document.getElementById("guidedNameDao")?.value;
  if (seed) params.set("seed", seed);
  if (dao) params.set("dao", dao);
  try {
    const result = await api(`/api/names/generate?${params.toString()}`);
    if (seedInput) seedInput.value = result.seed;
    clearNode(host);
    for (const row of result.names || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "name-choice";
      button.textContent = row.name;
      button.title = `${row.hanzi} — ${row.meaning}`;
      button.addEventListener("click", () => {
        const input = document.getElementById("guidedName");
        input.value = row.name.split(",")[0];
        input.dispatchEvent(new Event("input", {bubbles: true}));
      });
      host.appendChild(button);
    }
    const note = document.createElement("small");
    note.textContent = `Seed ${result.seed}; empty the seed box for new names.`;
    host.appendChild(note);
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "Names could not be drawn."), true);
  }
});

document.getElementById("guidedNewCharacter").onclick = async () => {
  await startNewCharacter("quick");
};

async function loadStatus() {
  setScreenState("statusScreenState", "loading", "Loading application health and data locations…");
  try {
    const data = await api("/api/system/status");
    const entries = [
      ["Application / process health", data.health],
      ["Build and version", data.build || data.packaging],
      ["Writable data root", {data_root: data.readiness?.data_root, directories: data.directories}],
      ["Project store / database", data.project_store || data.readiness?.project_store],
      ["Authenticated producer corpus", data.producer_corpus || data.readiness?.producer_corpus],
      ["Factory adapter", data.factory_adapter],
      ["Core catalog", data.catalog],
      ["Canonical catalog authority", data.canonical_catalog_authority || data.readiness?.canonical_catalog_authority],
      ["GM consumer", data.gm_consumer || data.readiness?.gm_consumer],
      ["Combat runtime", data.combat_runtime || data.readiness?.combat_runtime],
      ["Combatant library", data.combatant_library],
      ["Native Windows acceptance", data.native_windows || {status: "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED"}],
      ["Optional AI provider", data.ai_provider]
    ];
    const cards = document.getElementById("statusCards"); clearNode(cards);
    for (const [title, value] of entries) {
      const article = document.createElement("article"); article.className = "card";
      const heading = document.createElement("h3"); heading.textContent = title;
      const pre = document.createElement("pre"); pre.textContent = pretty(value);
      article.append(heading, pre); cards.appendChild(article);
    }
    document.getElementById("recentErrors").textContent = data.recent_errors?.length ? pretty(data.recent_errors) : "None";
    setScreenState("statusScreenState", "loaded", "Advanced status loaded.");
    return data;
  } catch (error) {
    setScreenState("statusScreenState", "error", "Advanced Status could not be loaded. Other tabs remain available.", loadStatus, error);
    throw error;
  }
}

function catalogRulesText(record) {
  const candidates = [
    record?.full_exact_source_text,
    record?.player_rules_text,
    record?.rules_text,
    record?.description,
    record?.short_description,
    record?.text,
  ];
  return candidates.find(value => typeof value === "string" && value.trim())?.trim() || "";
}

function renderCatalogRulesText(text) {
  const host = document.createElement("div"); host.className = "catalog-readable-rules";
  let list = null;
  for (const sourceLine of text.split(/\r?\n/)) {
    const line = sourceLine.replace(/<br\s*\/?>/gi, " ").replace(/<[^>]+>/g, "").replace(/&nbsp;/gi, " ").trim();
    if (!line) { list = null; continue; }
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      list = null;
      const heading = document.createElement(headingMatch[1].length <= 2 ? "h4" : "h5");
      heading.textContent = headingMatch[2]; host.appendChild(heading); continue;
    }
    const bulletMatch = line.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      if (!list) { list = document.createElement("ul"); host.appendChild(list); }
      const item = document.createElement("li"); item.textContent = bulletMatch[1]; list.appendChild(item); continue;
    }
    list = null;
    const paragraph = document.createElement(/^[“\"]/.test(line) ? "blockquote" : "p");
    paragraph.textContent = line; host.appendChild(paragraph);
  }
  return host;
}

function renderCatalogDetail(row, record) {
  const host = document.getElementById("catalogDetail");
  const raw = document.getElementById("catalogRawDetail");
  const developer = document.getElementById("catalogDeveloperDetail");
  clearNode(host);
  const heading = document.createElement("h3");
  heading.id = "catalogDetailHeading";
  heading.textContent = record?.display_name || row.display_name || friendlyLabel(row.record_id);
  const meta = document.createElement("div"); meta.className = "catalog-detail-meta";
  for (const value of [row.content_type, row.authority !== "canonical" ? row.authority : null].filter(Boolean)) {
    const badge = document.createElement("span"); badge.textContent = friendlyLabel(value); meta.appendChild(badge);
  }
  host.append(heading, meta);
  const shortDescription = [record?.short_description, record?.prerequisite_summary]
    .find(value => typeof value === "string" && value.trim());
  if (shortDescription) {
    const intro = document.createElement("p"); intro.className = "catalog-detail-intro"; intro.textContent = shortDescription.trim(); host.appendChild(intro);
  }
  const rulesText = catalogRulesText(record);
  if (rulesText) {
    host.appendChild(renderCatalogRulesText(rulesText));
  } else {
    const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "This rule does not include a readable description yet."; host.appendChild(empty);
  }
  raw.textContent = pretty({record_id: row.record_id, content_type: row.content_type, authority: row.authority, record});
  developer.open = false;
}

async function loadCatalog(event) {
  if (event) event.preventDefault();
  setScreenState("catalogScreenState", "loading", "Loading rules…");
  try {
    const params = new URLSearchParams();
    const q = document.getElementById("catalogQuery").value.trim();
    const type = document.getElementById("catalogType").value.trim();
    const authority = document.getElementById("catalogAuthority").value;
    if (q) params.set("q", q); if (type) params.set("content_type", type); if (authority) params.set("authority", authority);
    if (document.getElementById("includeTest").checked) params.set("include_test", "true");
    const data = await api(`/api/catalog/records?${params}`);
    const records = data.records || [];
    const body = document.getElementById("catalogRows"); clearNode(body);
    const summary = document.getElementById("catalogResultSummary");
    summary.textContent = `${records.length} ${records.length === 1 ? "rule" : "rules"}`;
    for (const row of records) {
      const item = document.createElement("article"); item.setAttribute("role", "listitem");
      const button = document.createElement("button"); button.type = "button"; button.className = "catalog-result-card";
      const name = document.createElement("strong"); name.textContent = row.display_name || friendlyLabel(row.record_id);
      const type = document.createElement("span"); type.textContent = friendlyLabel(row.content_type || "rule");
      button.append(name, type);
      button.onclick = async () => {
        body.querySelectorAll(".catalog-result-card").forEach(candidate => candidate.classList.toggle("is-selected", candidate === button));
        const detail = document.getElementById("catalogDetail"); clearNode(detail);
        const loading = document.createElement("p"); loading.textContent = `Opening ${name.textContent}…`; detail.appendChild(loading);
        try { renderCatalogDetail(row, await api(`/api/catalog/records/${encodeURIComponent(row.record_id)}?all_versions=true`)); }
        catch (error) {
          clearNode(detail);
          const failure = document.createElement("p"); failure.className = "friendly-error"; failure.textContent = plainAPIError(error, "That rule could not be opened."); detail.appendChild(failure);
        }
      };
      item.appendChild(button); body.appendChild(item);
    }
    if (!records.length) setScreenState("catalogScreenState", "empty", q || type || authority ? "No rules match this search." : "No rules are available yet. Try Refresh after setup finishes.", loadCatalog);
    else setScreenState("catalogScreenState", "loaded", `${records.length} rules loaded.`);
    return data;
  } catch (error) {
    setScreenState("catalogScreenState", "error", "Browse Rules could not reach the local catalog. Character creation and Character Sheets remain available.", loadCatalog, error);
    throw error;
  }
}

async function loadPacks() {
  setScreenState("packsScreenState", "loading", "Loading required and optional content packs…");
  try {
    const rows = await api("/api/content-packs");
    const body = document.getElementById("packRows"); clearNode(body);
    for (const row of rows) {
      const tr = document.createElement("tr"); const key = `${row.pack_id}@${row.version}`;
      if (row.authority === "canonical" && row.selectable === true && selectedPackLocks.size === 0) selectedPackLocks.add(key);
      const selectCell = document.createElement("td"); const selector = document.createElement("input"); selector.type = "checkbox";
      selector.disabled = row.selectable !== true; selector.checked = selectedPackLocks.has(key) && row.selectable === true;
      selector.setAttribute("aria-label", `Use ${key} for a new project`); selector.addEventListener("click", event => event.stopPropagation());
      selector.addEventListener("change", () => { if (selector.checked) selectedPackLocks.add(key); else selectedPackLocks.delete(key); });
      selectCell.appendChild(selector); tr.appendChild(selectCell);
      appendTextCell(tr, row.pack_id, true); appendTextCell(tr, row.version); appendTextCell(tr, row.lifecycle_state); appendTextCell(tr, row.authority);
      appendTextCell(tr, row.trust_state || "none"); appendTextCell(tr, row.selectable === true ? "yes" : "no"); appendTextCell(tr, row.record_count); appendTextCell(tr, row.dependent_projects);
      tr.onclick = async () => {
        try { document.getElementById("packResult").textContent = pretty(await api(`/api/content-packs/${encodeURIComponent(row.pack_id)}/${encodeURIComponent(row.version)}`)); }
        catch (error) { document.getElementById("packResult").textContent = plainAPIError(error, "That content pack could not be opened."); }
      };
      body.appendChild(tr);
    }
    const optional = rows.filter(row => row.authority !== "canonical");
    if (!optional.length) setScreenState("packsScreenState", "empty", rows.length ? "The required core content is installed. No additional content packs are installed." : "No content packs are registered yet. First-run initialization may still be completing.", loadPacks);
    else setScreenState("packsScreenState", "loaded", `${rows.length} content packs loaded.`);
    return rows;
  } catch (error) {
    setScreenState("packsScreenState", "error", "Manage Content could not load the local pack registry. Other tabs remain available.", loadPacks, error);
    throw error;
  }
}

async function packOperation(action) {
  const filename = document.getElementById("packFilename").value.trim();
  if (action === "install" && (
    !lastPackValidation
    || lastPackValidation.filename !== filename
    || lastPackValidation.result.trust_state !== "trusted_signed"
  )) {
    document.getElementById("packResult").textContent = "Only an immediately validated trusted-signed pack may use this install button. Use exact-archive human trust for unsigned local packs.";
    return;
  }
  try {
    const result = await api(`/api/content-packs/${action}`, {method: "POST", body: JSON.stringify({package_name: filename})});
    if (action === "validate") {
      lastPackValidation = {filename, result};
      document.getElementById("installPack").disabled = !(result.valid && result.trust_state === "trusted_signed");
      document.getElementById("installTrustedPack").disabled = !(result.valid && result.package_identity && result.package_identity.archive_sha256);
    }
    document.getElementById("packResult").textContent = pretty(result); await loadPacks(); await loadCatalog();
  } catch (e) { document.getElementById("packResult").textContent = e.message; }
}

async function installExactTrustedPack() {
  const filename = document.getElementById("packFilename").value.trim();
  const actor = document.getElementById("packApprover").value.trim();
  if (!lastPackValidation || lastPackValidation.filename !== filename || !lastPackValidation.result.valid) {
    document.getElementById("packResult").textContent = "Validate this exact filename immediately before trusting it.";
    return;
  }
  if (!actor) {
    document.getElementById("packResult").textContent = "A named local approver is required.";
    return;
  }
  const digest = lastPackValidation.result.package_identity.archive_sha256;
  try {
    const challengeResult = await api("/api/content-packs/exact-trust-challenge", {
      method: "POST", body: JSON.stringify({package_name: filename})
    });
    const challenge = challengeResult.challenge;
    const result = await api("/api/content-packs/install", {
      method: "POST",
      body: JSON.stringify({
        package_name: filename,
        human_trust: {
          archive_sha256: digest,
          approved_by: actor,
          confirmation: `TRUST_LOCAL_CONTENT_PACK:${digest}`
        },
        challenge_id: challenge.challenge_id,
        nonce: challenge.nonce
      })
    });
    document.getElementById("packResult").textContent = pretty(result);
    lastPackValidation = null;
    document.getElementById("installTrustedPack").disabled = true;
    await loadPacks(); await loadCatalog();
  } catch (e) { document.getElementById("packResult").textContent = e.message; }
}

async function loadProjects() {
  const rows = await api("/api/projects");
  const body = document.getElementById("projectRows"); clearNode(body);
  for (const row of rows) {
    const tr = document.createElement("tr");
    appendTextCell(tr, row.working_name);
    appendTextCell(tr, row.revision);
    appendTextCell(tr, `${row.builder_lifecycle?.display_label || "Saved / existing"} · ${row.status}`);
    tr.onclick = async () => { selectedProject = row.project_id; document.getElementById("projectDetail").textContent = pretty(await api(`/api/projects/${row.project_id}/read-models`)); };
    body.appendChild(tr);
  }
  return rows;
}

document.getElementById("createProject").addEventListener("submit", async event => {
  event.preventDefault();
  const locks = document.getElementById("projectLocks").value.split(",").map(x => x.trim()).filter(Boolean).map(value => {
    const at = value.lastIndexOf("@"); return {pack_id: value.slice(0, at), version: value.slice(at + 1)};
  });
  const result = await api("/api/projects", {method: "POST", body: JSON.stringify({working_name: document.getElementById("projectName").value, pack_locks: locks})});
  selectedProject = result.project_id; document.getElementById("projectDetail").textContent = pretty(result); await loadProjects();
});

document.getElementById("draftEvent").addEventListener("submit", async event => {
  event.preventDefault(); if (!selectedProject) return;
  const project = await api(`/api/projects/${selectedProject}`);
  const recordId = document.getElementById("eventRecordId").value.trim();
  const body = {
    event_type: "acquire", effective_point: {cl: Number(document.getElementById("eventCL").value || 1)}, actor_type: "human",
    stable_rule_ids: [recordId], acquisition_channel: document.getElementById("eventChannel").value.trim(),
    content_pack_references: project.content_locks.map(x => ({pack_id: x.pack_id, version: x.version, pack_hash: x.pack_hash})),
    payload: {}, rationale: "UI Phase 2 test event"
  };
  try {
    const draft = await api(`/api/projects/${selectedProject}/draft-events`, {method: "POST", body: JSON.stringify(body)});
    const validation = await api(`/api/draft-events/${draft.draft_id}/validate`, {method: "POST", body: "{}"});
    if (!validation.valid) throw new Error(pretty(validation));
    await api(`/api/draft-events/${draft.draft_id}/approve`, {method: "POST", body: JSON.stringify({approved_by: "local-user"})});
    const committed = await api(`/api/draft-events/${draft.draft_id}/commit`, {method: "POST", body: "{}"});
    document.getElementById("projectActionResult").textContent = pretty(committed); await loadProjects();
  } catch (e) { document.getElementById("projectActionResult").textContent = e.message; }
});

document.getElementById("replayProject").onclick = async () => {
  if (!selectedProject) return; document.getElementById("projectActionResult").textContent = pretty(await api(`/api/projects/${selectedProject}/replay`, {method: "POST", body: "{}"}));
};

document.getElementById("buildProjection").onclick = async () => {
  if (!selectedProject) return;
  try {
    const result = await api(`/api/projects/${selectedProject}/projection/build`, {method: "POST", body: JSON.stringify({force: false})});
    document.getElementById("projectActionResult").textContent = pretty(result);
    renderProjectionDownloads(result);
  } catch (e) { document.getElementById("projectActionResult").textContent = e.message; }
};
document.getElementById("projectionStatus").onclick = async () => {
  if (!selectedProject) return;
  const result = await api(`/api/projects/${selectedProject}/projection/status`);
  document.getElementById("projectActionResult").textContent = pretty(result);
  renderProjectionDownloads(result);
};
function renderProjectionDownloads(result) {
  const host = document.getElementById("projectionDownloads"); clearNode(host);
  for (const artifact of (result.artifacts || [])) {
    const a = document.createElement("a");
    a.href = `/api/projects/${selectedProject}/projection/artifacts/${encodeURIComponent(artifact.artifact_name)}`;
    a.textContent = artifact.artifact_name; a.target = "_blank"; host.appendChild(a);
  }
}

document.getElementById("exportProject").onclick = async () => {
  if (!selectedProject) return; document.getElementById("projectActionResult").textContent = pretty(await api(`/api/projects/${selectedProject}/export`, {method: "POST", body: "{}"}));
};

document.getElementById("catalogSearch").addEventListener("submit", loadCatalog);
document.getElementById("validatePack").onclick = () => packOperation("validate");
document.getElementById("installPack").onclick = () => packOperation("install");
document.getElementById("installTrustedPack").onclick = installExactTrustedPack;
document.getElementById("packFilename").addEventListener("input", () => {
  lastPackValidation = null;
  document.getElementById("installPack").disabled = true;
  document.getElementById("installTrustedPack").disabled = true;
});
document.getElementById("useSelectedPacks").onclick = () => {
  const locks = Array.from(selectedPackLocks).sort();
  document.getElementById("projectLocks").value = locks.join(", ");
  showScreen("projects");
};
document.getElementById("foundationHandoffAction").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const result = await api("/api/foundation-packs/prepare", {
      method: "POST",
      body: JSON.stringify({
        package_name: document.getElementById("foundationHandoffFilename").value.trim(),
        output_name: document.getElementById("foundationPackOutput").value.trim(),
        authorize_stage_repairs: document.getElementById("authorizeFoundationRepairs").checked
      })
    });
    document.getElementById("packFilename").value = result.output_name;
    lastPackValidation = null;
    document.getElementById("installTrustedPack").disabled = true;
    document.getElementById("packResult").textContent = pretty(result);
  } catch (e) { document.getElementById("packResult").textContent = e.message; }
});
document.getElementById("refreshAll").onclick = async () => {
  closeAdvancedProductMenu();
  await Promise.allSettled([loadStatus(), loadCatalog(), loadPacks(), loadProjects()]);
};

let stage1PromptData = null;
let stage1Attempt = null;
let aiProviderStatus = null;
let aiProviderDirty = false;

function updateAIProviderControls() {
  document.getElementById("runAIProvider").disabled = !(
    stage1PromptData && aiProviderStatus && aiProviderStatus.ready
  );
}

async function loadAIProviderStatus() {
  aiProviderStatus = await api("/api/ai-provider");
  const settings = aiProviderStatus.settings;
  document.getElementById("aiProviderEnabled").checked = settings.enabled;
  document.getElementById("aiProviderModel").value = settings.model;
  document.getElementById("aiProviderThinking").value = settings.thinking_mode;
  document.getElementById("aiProviderMaxTokens").value = settings.max_output_tokens;
  document.getElementById("aiProviderTimeout").value = settings.timeout_seconds;
  document.getElementById("aiProviderAcknowledged").checked = settings.data_sharing_acknowledged;
  if (settings.acknowledged_by) document.getElementById("aiProviderActor").value = settings.acknowledged_by;
  aiProviderDirty = false;
  document.getElementById("aiProviderStatus").textContent = providerStatusMessage(aiProviderStatus);
  updateAIProviderControls();
  return aiProviderStatus;
}

async function refreshSelectedProject() {
  if (!selectedProject) return null;
  const [project, preference] = await Promise.all([
    api(`/api/projects/${selectedProject}`),
    api(`/api/projects/${selectedProject}/character-creation/preference`)
  ]);
  const canonical = project.project;
  const mode = document.getElementById("characterCreationMode");
  if (mode && preference?.execution_mode) {
    mode.value = preference.execution_mode;
    document.getElementById("cgManualLabel").hidden = mode.value !== "MANUAL_CHAT";
  }
  document.getElementById("stage1ProjectRevision").textContent = `Project ${canonical.name} — revision ${canonical.revision} — catalog ${canonical.content_lock.catalog_build_id}`;
  document.getElementById("projectDetail").textContent = pretty(await api(`/api/projects/${selectedProject}/read-models`));
  await loadNonSphereAuthorityPanel();
  return project;
}

function friendlyLabel(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function conciseRecordName(record) {
  if (record === null || record === undefined) return "Not compiled yet";
  if (typeof record !== "object") return String(record);
  return record.display_name || record.name || record.title || record.label || record.canonical_name || record.character_name || record.id || record.record_id || "Recorded detail";
}

function appendReadableValue(host, value, depth = 0) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) {
    const empty = document.createElement("span"); empty.className = "not-compiled"; empty.textContent = "Not present for this stage"; host.appendChild(empty); return;
  }
  if (typeof value !== "object") {
    const span = document.createElement("span");
    span.textContent = typeof value === "boolean" ? (value ? "Yes" : "No") : String(value);
    host.appendChild(span); return;
  }
  if (depth > 12) {
    const pre = document.createElement("pre"); pre.className = "sheet-readable-json"; pre.textContent = JSON.stringify(value, null, 2); host.appendChild(pre); return;
  }
  if (Array.isArray(value)) {
    const list = document.createElement("ul"); list.className = "sheet-readable-list";
    for (const item of value) {
      const li = document.createElement("li");
      if (typeof item === "object" && item !== null) {
        const details = document.createElement("details"); details.className = "sheet-readable-detail";
        const summary = document.createElement("summary"); summary.textContent = conciseRecordName(item);
        details.appendChild(summary); appendReadableValue(details, item, depth + 1); li.appendChild(details);
      } else {
        li.textContent = item === null || item === undefined ? "Not present for this stage" : String(item);
      }
      list.appendChild(li);
    }
    host.appendChild(list); return;
  }
  const grid = document.createElement("dl"); grid.className = "sheet-readable-grid";
  for (const [key, item] of Object.entries(value)) {
    if (["schema_version", "source_packet_ids", "source_id", "record_id", "character_id"].includes(key) && depth === 0) continue;
    const dt = document.createElement("dt"); dt.textContent = friendlyLabel(key);
    const dd = document.createElement("dd");
    if (typeof item === "object" && item !== null) appendReadableValue(dd, item, depth + 1);
    else dd.textContent = item === null || item === undefined || item === "" ? "Not present for this stage" : typeof item === "boolean" ? (item ? "Yes" : "No") : String(item);
    grid.append(dt, dd);
  }
  host.appendChild(grid);
}

const ADVANCEMENT_DISPLAY_FIELDS = Object.freeze([
  "event_count", "event_head_hash", "levels", "canonical_allocations", "typed_choice_snapshot"
]);

function compactOwnerLockMetadata(lock) {
  if (!lock || typeof lock !== "object" || Array.isArray(lock)) return {};
  const metadata = {};
  for (const key of ["lock_id", "field", "created_revision"]) {
    if (Object.prototype.hasOwnProperty.call(lock, key)) metadata[key] = lock[key];
  }
  return metadata;
}

function compactOwnerLockList(locks) {
  const rows = Array.isArray(locks) ? locks : [];
  return {count: rows.length, locks: rows.map(compactOwnerLockMetadata)};
}

function buildDisplaySafeAdvancementSummary(advancement) {
  if (!advancement || typeof advancement !== "object" || Array.isArray(advancement)) return advancement;
  const summary = {};
  for (const key of ADVANCEMENT_DISPLAY_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(advancement, key)) summary[key] = advancement[key];
  }
  if (Object.prototype.hasOwnProperty.call(advancement, "owner_choice_locks")) {
    summary.owner_choice_locks = compactOwnerLockList(advancement.owner_choice_locks);
  }
  if (Object.prototype.hasOwnProperty.call(advancement, "all_owner_locks")) {
    summary.all_owner_locks = compactOwnerLockList(advancement.all_owner_locks);
  }
  return summary;
}

function pickTechnicalFields(source, fields) {
  if (!source || typeof source !== "object" || Array.isArray(source)) return {};
  const result = {};
  for (const key of fields) {
    if (Object.prototype.hasOwnProperty.call(source, key)) result[key] = source[key];
  }
  return result;
}

function buildProvenanceStatusSummary(provenance) {
  if (!provenance || typeof provenance !== "object" || Array.isArray(provenance)) return {};
  const summary = {};
  for (const [key, item] of Object.entries(provenance)) {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      summary[key] = pickTechnicalFields(item, ["status", "label"]);
    }
  }
  return summary;
}

function buildOwnerSheetTechnicalSummary(sheet) {
  const snapshot = ownerSnapshotForDisplay(sheet);
  return {
    identity: sheet?.identity,
    build_status: sheet?.build_status,
    readiness: sheet?.readiness,
    combat_readiness: sheet?.combat_readiness,
    sheet_artifact: pickTechnicalFields(sheet?.sheet_artifact, ["sheet_id", "path", "sha256", "bytes", "display_contract_sha256", "readiness_profile_sha256"]),
    factory_workspace: pickTechnicalFields(sheet?.factory_workspace, [
      "status", "gm_authoring", "gm_authorship_status", "gm_authoring_actual", "gm_authoring_profile_classification", "command5", "command6", "gm_screen_consumer_verification", "gm_export_available", "eligible_for_later_command5_checkpoint"
    ]),
    gm_export: pickTechnicalFields(sheet?.gm_export, [
      "available", "readiness", "source_consumer_verified", "native_or_interactive_acceptance", "combat", "blockers", "next_step"
    ]),
    snapshot: {
      authority_and_artifact_identity: pickTechnicalFields(snapshot?.authority_and_artifact_identity, [
        "project_id", "project_revision", "event_count", "event_head_hash", "content_lock_hash", "typed_choice_snapshot_sha256", "projection_id", "advancement_artifact_hashes", "display_contract", "readiness_profile"
      ])
    },
    provenance: buildProvenanceStatusSummary(sheet?.provenance)
  };
}

function ownerNextLegalAction(sheet) {
  const status = String(sheet?.build_status || "").toUpperCase();
  if (status === "TEMPORARY") return "Save Draft when you want to keep this character after closing the builder.";
  if (status === "SAVED_DRAFT") return "Open the draft in the builder and prepare its complete-character request.";
  if (status === "BLUEPRINT") return "Prepare the complete-character request for this saved plan.";
  if (status === "ADVANCEMENT_READY") return "Build the owner-facing Character Sheet from the deterministic advancement result.";
  if (status === "CHARACTER_SHEET_READY") {
    return sheet?.gm_export?.available
      ? "Open Advanced Exports only when you need a Character or GM ZIP."
      : "Prepare the Factory workspace; GM export stays unavailable until its separate verification gate is complete.";
  }
  if (status === "GM_READY") return "Open Advanced Exports if you need the validated GM-compatible ZIP.";
  return "Select one action above to continue this character.";
}


const NS1R_API_CONTRACT_ROUTES = Object.freeze([
  {method: "GET", path: "/api/non-sphere/authority/status"},
  {method: "GET", path: "/api/non-sphere/paths"},
  {method: "GET", path: "/api/non-sphere/methods"},
  {method: "GET", path: "/api/non-sphere/foundations"},
  {method: "GET", path: "/api/non-sphere/backgrounds"},
  {method: "GET", path: "/api/non-sphere/subpaths"},
  {method: "GET", path: "/api/non-sphere/projects/{project_id}/state"},
  {method: "PUT", path: "/api/non-sphere/projects/{project_id}/state"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/primary-method"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/target-cl"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/access-sources"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/path-attainment"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/advancement"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/resource"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/subpath"},
  {method: "POST", path: "/api/non-sphere/projects/{project_id}/foundation"},
  {method: "GET", path: "/api/non-sphere/projects/{project_id}/ap-eligibility"},
  {method: "GET", path: "/api/non-sphere/projects/{project_id}/evidence"},
  {method: "POST", path: "/api/non-sphere/compatibility/resolve"},
  {method: "GET", path: "/api/non-sphere/projects/{project_id}/readiness"},
  {method: "POST", path: "/api/non-sphere/backgrounds/validate"},
  {method: "POST", path: "/api/non-sphere/migration/preview"},
]);

let nonSphereCatalogCache = null;
let nonSpherePanelRequestGeneration = 0;
let nonSpherePanelContext = null;

function setNonSphereActionControlsDisabled(disabled) {
  for (const id of [
    "nonSphereAccessSources", "nonSpherePrimaryMethod", "nonSphereFoundation",
    "setNonSphereAccessSources", "setNonSpherePrimaryMethod", "setNonSphereFoundation",
  ]) {
    const node = document.getElementById(id);
    if (node) node.disabled = Boolean(disabled);
  }
}

function invalidateNonSpherePanelActions() {
  nonSpherePanelRequestGeneration += 1;
  nonSpherePanelContext = null;
  setNonSphereActionControlsDisabled(true);
}

function currentNonSphereActionContext() {
  const context = nonSpherePanelContext;
  if (!context || context.requestGeneration !== nonSpherePanelRequestGeneration || selectedProject !== context.projectId) return null;
  return context;
}

function nonSphereActionIsCurrent(context) {
  return Boolean(
    context
    && context.requestGeneration === nonSpherePanelRequestGeneration
    && selectedProject === context.projectId
    && nonSpherePanelContext?.requestGeneration === context.requestGeneration
    && nonSpherePanelContext?.projectId === context.projectId,
  );
}

function rejectStaleNonSphereAction() {
  const technical = document.getElementById("nonSphereTechnical");
  if (technical) technical.textContent = "This Cultivation control is stale for the current character. Refresh the panel before saving.";
  return null;
}

function nonSphereOption(select, value, label, {disabled = false, selected = false} = {}) {
  const option = document.createElement("option");
  option.value = value; option.textContent = label; option.disabled = disabled; option.selected = selected;
  select.appendChild(option); return option;
}

function readNonSphereEvidence() {
  const field = document.getElementById("nonSphereAccessSources");
  if (!field) return [];
  return Array.from(field.selectedOptions || []).map(option => option.value).filter(Boolean);
}

function evidenceMatches(record, authorityType, matches = {}) {
  return record.authority_type === authorityType && Object.entries(matches).every(([key, value]) => record.targets?.[key] === value);
}

async function loadNonSphereAuthorityPanel(projectId = selectedProject) {
  const statusNode = document.getElementById("nonSphereAuthorityStatus");
  const technical = document.getElementById("nonSphereTechnical");
  if (!statusNode || !technical) return;
  const requestGeneration = ++nonSpherePanelRequestGeneration;
  nonSpherePanelContext = null;
  setNonSphereActionControlsDisabled(true);
  const isCurrent = () => requestGeneration === nonSpherePanelRequestGeneration && selectedProject === projectId;
  try {
    if (!nonSphereCatalogCache) {
      const [status, paths, foundations] = await Promise.all([
        api("/api/non-sphere/authority/status"), api("/api/non-sphere/paths"), api("/api/non-sphere/foundations")
      ]);
      nonSphereCatalogCache = {status, paths, foundations};
    }
    if (!isCurrent()) return;
    const {status, paths, foundations} = nonSphereCatalogCache;
    statusNode.textContent = `${friendlyLabel(status.status)} · ${status.method_count} Methods · ${status.orthodox_foundation_count} orthodox Foundations · ${status.operative_pairwise_authority_rows} operative pairwise rows`;
    if (!projectId) {
      document.getElementById("setNonSpherePrimaryMethod").disabled = true;
      document.getElementById("setNonSphereFoundation").disabled = true;
      document.getElementById("nonSpherePathTracks").innerHTML = "<p>Select a character to inspect its persistent Path tracks.</p>";
      technical.textContent = pretty(status);
      nonSpherePanelContext = Object.freeze({projectId, requestGeneration});
      return;
    }
    const [state, methods, readiness, apEligibility, evidenceLedger, ...subpathCatalogs] = await Promise.all([
      api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/state`),
      api(`/api/non-sphere/methods?project_id=${encodeURIComponent(projectId)}`),
      api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/readiness`),
      api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/ap-eligibility`),
      api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/evidence`),
      ...paths.records.map(row => api(`/api/non-sphere/subpaths?path_id=${encodeURIComponent(row.path_id)}`))
    ]);
    if (!isCurrent()) return;
    const actionContext = Object.freeze({projectId, requestGeneration});
    nonSpherePanelContext = actionContext;
    const evidenceSelect = document.getElementById("nonSphereAccessSources"); clearNode(evidenceSelect);
    const selectedEvidence = new Set((state.access_source_records || []).map(row => row.evidence_id));
    for (const record of evidenceLedger.evidence || []) {
      if (record.authority_type === "ap_award") continue;
      nonSphereOption(evidenceSelect, record.evidence_id, `${friendlyLabel(record.authority_type)} · ${Object.values(record.targets || {}).join(" · ")}`, {selected: selectedEvidence.has(record.evidence_id)});
    }
    if (!(evidenceLedger.evidence || []).some(record => record.authority_type !== "ap_award")) nonSphereOption(evidenceSelect, "", "No committed access/completion evidence available", {disabled:true});
    const methodSelect = document.getElementById("nonSpherePrimaryMethod"); clearNode(methodSelect);
    nonSphereOption(methodSelect, "", "Choose one known or accessible Method", {selected: !state.primary_method_id});
    for (const row of methods.records.sort((a,b) => a.method_id.localeCompare(b.method_id))) {
      const d = row.disposition || {};
      nonSphereOption(methodSelect, row.method_id, `${row.method_id} — ${row.name} — ${friendlyLabel(d.state)}`, {disabled: !d.selectable_as_primary, selected: row.method_id === state.primary_method_id});
    }
    document.getElementById("setNonSpherePrimaryMethod").disabled = false;
    const foundationSelect = document.getElementById("nonSphereFoundation"); clearNode(foundationSelect);
    nonSphereOption(foundationSelect, "", "No Foundation selected", {selected: !state.foundation_id});
    for (const row of foundations.orthodox) nonSphereOption(foundationSelect, row.foundation_id, `${row.catalog_number}. ${row.display_name}`, {selected: row.foundation_id === state.foundation_id});
    document.getElementById("setNonSphereFoundation").disabled = false;
    document.getElementById("setNonSphereAccessSources").disabled = false;
    for (const id of ["nonSphereAccessSources", "nonSpherePrimaryMethod", "nonSphereFoundation"]) document.getElementById(id).disabled = false;

    const host = document.getElementById("nonSpherePathTracks"); clearNode(host);
    state.paths.forEach((path, index) => {
      const card = document.createElement("section"); card.className = "non-sphere-path-card";
      const title = document.createElement("h4"); title.textContent = path.display_name;
      const statusLine = document.createElement("p"); statusLine.className = "path-status"; statusLine.textContent = `${path.status} · attainment ${path.attainment}/${state.target_cl}`;
      const resource = document.createElement("p"); resource.textContent = `${path.resource.resource_name}: ${path.resource.current ?? "unresolved"} / ${path.resource.maximum ?? "unresolved"}`;
      const methodProfile = document.createElement("small"); methodProfile.textContent = path.resource.method_profile ? "Primary Method resource profile is active for this Path." : "No Primary Method resource profile for this Path.";
      const controls = document.createElement("div"); controls.className = "path-controls";
      const attainmentLabel = document.createElement("p"); attainmentLabel.textContent = `Attainment ${path.attainment}; increases use the Method-gated advancement transaction below.`;
      controls.append(attainmentLabel);
      const currentLabel = document.createElement("label"); currentLabel.textContent = `Current ${path.resource.resource_name}`;
      const current = document.createElement("input"); current.type = "number"; current.min = "0"; current.value = path.resource.current ?? "";
      const maxLabel = document.createElement("label"); maxLabel.textContent = `Maximum ${path.resource.resource_name}`;
      const maximum = document.createElement("input"); maximum.type = "number"; maximum.min = "0"; maximum.value = path.resource.maximum ?? "";
      const setResource = document.createElement("button"); setResource.type = "button"; setResource.textContent = "Save resource";
      setResource.onclick = () => updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/resource`, {path_id: path.path_id, current: current.value === "" ? null : Number(current.value), maximum: maximum.value === "" ? null : Number(maximum.value)}, actionContext);
      currentLabel.appendChild(current); maxLabel.appendChild(maximum); controls.append(currentLabel, maxLabel, setResource);
      const subLabel = document.createElement("label"); subLabel.textContent = "Subpath / Tradition";
      const subSelect = document.createElement("select");
      nonSphereOption(subSelect, "", path.subpath_or_tradition_id ? "Clear not available from this bounded panel" : "None selected", {selected: !path.subpath_or_tradition_id});
      for (const choice of subpathCatalogs[index].records) {
        const accessCategory = choice.access?.canonical_category || choice.access?.printed_category || "Open";
        const kind = choice.option_type === "tradition" ? "Spirit Tradition" : `${choice.owning_path_name} Subpath`;
        nonSphereOption(subSelect, choice.canonical_id, `${choice.display_name} — ${kind} — ${accessCategory}`, {selected: choice.canonical_id === path.subpath_or_tradition_id});
      }
      const setSubpath = document.createElement("button"); setSubpath.type = "button"; setSubpath.textContent = "Set selection"; setSubpath.disabled = path.attainment < 3;
      setSubpath.onclick = () => { if (subSelect.value) updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/subpath`, {path_id: path.path_id, selection_id: subSelect.value, evidence_ids: readNonSphereEvidence(actionContext)}, actionContext); };
      subLabel.appendChild(subSelect); controls.append(subLabel, setSubpath);
      card.append(title, statusLine, resource, methodProfile, controls); host.appendChild(card);
    });
    const advanceHost = document.getElementById("nonSphereAdvancementControls"); clearNode(advanceHost);
    if (apEligibility.paths) {
      const inputs = {};
      for (const route of apEligibility.paths) {
        const label = document.createElement("label"); label.textContent = `${friendlyLabel(route.path_id)} attainment increase`;
        const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.value = "0"; input.disabled = !route.eligible;
        inputs[route.path_id] = input; label.appendChild(input); advanceHost.appendChild(label);
      }
      const sourceLabel = document.createElement("label"); sourceLabel.textContent = "Committed AP award";
      const source = document.createElement("select");
      nonSphereOption(source, "", "Select a matching AP award");
      for (const record of evidenceLedger.evidence || []) {
        if (evidenceMatches(record, "ap_award", {method_id: state.primary_method_id, target_cl: state.target_cl}) && Number(record.remaining_amount || 0) > 0) {
          nonSphereOption(source, record.evidence_id, `${record.evidence_id} · ${record.remaining_amount}/${record.amount_awarded} AP remaining`);
        }
      }
      sourceLabel.appendChild(source); advanceHost.appendChild(sourceLabel);
      const button = document.createElement("button"); button.type = "button"; button.textContent = `Apply advancement (${apEligibility.numeric_burden_multiplier || "?"}× burden)`;
      button.onclick = () => {
        const allocations = Object.fromEntries(Object.entries(inputs).map(([pathId, input]) => [pathId, Number(input.value || 0)]));
        if (!source.value) throw new Error("Select a committed AP-award evidence record.");
        updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/advancement`, {
          allocations, evidence_id: source.value, idempotency_key: crypto.randomUUID()
        }, actionContext);
      };
      advanceHost.appendChild(button);
    } else {
      advanceHost.textContent = apEligibility.blocker?.message || "Choose an acquired Primary Method before allocating AP.";
    }

    const readyNode = document.getElementById("nonSphereReadiness");
    const ready = Boolean(readiness.ready);
    readyNode.className = `non-sphere-readiness ${ready ? "ready" : "blocked"}`;
    readyNode.textContent = ready ? "Non-Sphere authority is ready for this character." : `Blocked: ${(readiness.blockers || []).map(row => ownerDiagnosticMessage(row, "Cultivation selections remain incomplete.")).join(" · ") || "Cultivation selections remain incomplete."}`;
    technical.textContent = pretty({state, readiness, ap_eligibility: apEligibility, authority: status});
  } catch (error) {
    if (!isCurrent()) return;
    statusNode.textContent = plainAPIError(error, "Non-Sphere authority could not be loaded.");
    technical.textContent = statusNode.textContent;
  }
}

async function updateNonSphere(url, body, actionContext = currentNonSphereActionContext()) {
  if (!nonSphereActionIsCurrent(actionContext)) return rejectStaleNonSphereAction();
  const technical = document.getElementById("nonSphereTechnical");
  try {
    if (!nonSphereActionIsCurrent(actionContext)) return rejectStaleNonSphereAction();
    technical.textContent = "Saving canonical cultivation state…";
    const result = await api(url, {method: "POST", body: JSON.stringify(body)});
    if (!nonSphereActionIsCurrent(actionContext)) return;
    technical.textContent = pretty(result);
    await loadNonSphereAuthorityPanel(actionContext.projectId);
    if (selectedProject === actionContext.projectId) await openOwnerCharacterSheet(actionContext.projectId, false);
  } catch (error) {
    if (nonSphereActionIsCurrent(actionContext)) technical.textContent = plainAPIError(error, "Cultivation state was not changed.");
  }
}

function gmEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function ownerResolvedWorkflowName(sheet) {
  const run = sheet?.workflow?.latest_run || sheet?.workflow?.active_run || null;
  return ((((run || {}).owner_descriptive_fields || {}).resolved || {}).identity || {}).name || "";
}

// Human kicker for the sheet header. The exact build-status enum stays in
// Advanced / Developer (it is part of the technical summary); the primary
// surface speaks product language only.
function gmOwnerKicker(model) {
  if (model.state.tone === "ready") return "Completed character";
  if (model.state.tone === "attention") return "Character needs attention";
  return "Character in progress";
}

// Safe views of payload surfaces that older or partial projects may omit.
// Normalize in place so every later reference keeps its historical shape.
function gmNormalizeSheetSurfaces(sheet) {
  if (!sheet.provenance || typeof sheet.provenance !== "object") sheet.provenance = {};
  if (!sheet.gm_export || typeof sheet.gm_export !== "object") {
    sheet.gm_export = {available: false, blockers: [], next_step: null};
  } else if (!Array.isArray(sheet.gm_export.blockers)) {
    sheet.gm_export.blockers = [];
  }
}

// Client-side join inputs captured while rendering the Character Sheets
// library, keyed by project_id, so the sheet header can apply deterministic
// final-name precedence without changing any API payload.
const gmLibraryJoin = {characterListRows: new Map(), libraryRows: new Map(), enrichmentError: null};
const GM_LIBRARY_ENRICHMENT_TIMEOUT_MS = Number(globalThis.__TIANXIA_LIBRARY_ENRICHMENT_TIMEOUT_MS__) > 0
  ? Number(globalThis.__TIANXIA_LIBRARY_ENRICHMENT_TIMEOUT_MS__)
  : 5000;
let gmLibraryRequestGeneration = 0;
let gmLibraryEnrichmentAttempt = null;
let gmSheetRequestGeneration = 0;

function gmAbilityChipsGrid(chips) {
  const grid = gmEl("div", "gm-ability-grid");
  for (const chip of chips) {
    const card = gmEl("article", "gm-ability-chip");
    card.append(
      gmEl("strong", "gm-ability-name", chip.ability),
      gmEl("b", "gm-ability-score", chip.score === null || chip.score === undefined ? "—" : String(chip.score)),
      gmEl("span", "gm-ability-mod", chip.modifier ? `Mod ${chip.modifier}` : ""),
    );
    grid.appendChild(card);
  }
  return grid;
}

function gmInfoCard(title, lines, extraClass = "") {
  const card = gmEl("article", `gm-info-card${extraClass ? ` ${extraClass}` : ""}`);
  card.appendChild(gmEl("h5", null, title));
  const body = gmEl("div", "gm-info-body");
  for (const line of Array.isArray(lines) ? lines : [lines]) {
    if (line === null || line === undefined || line === "") continue;
    body.appendChild(gmEl("p", null, line));
  }
  if (!body.childElementCount) body.appendChild(gmEl("p", "gm-muted", "Not available yet."));
  card.appendChild(body);
  return card;
}

function gmBadge(text) {
  return gmEl("span", "gm-badge", text);
}

function gmAbilityCard(card) {
  const article = gmEl("article", "gm-ability-card");
  const head = gmEl("header", "gm-ability-head");
  const titleWrap = gmEl("div");
  titleWrap.append(gmEl("h5", null, card.name));
  if (card.summary) titleWrap.appendChild(gmEl("p", "gm-card-summary", card.summary));
  head.appendChild(titleWrap);
  const badges = gmEl("div", "gm-badges");
  if (card.source) badges.appendChild(gmBadge(card.source));
  if (card.timing) badges.appendChild(gmBadge(card.timing));
  if (card.acquiredAtCL !== null) badges.appendChild(gmBadge(`CL ${card.acquiredAtCL}`));
  if (badges.childElementCount) head.appendChild(badges);
  article.appendChild(head);
  if (card.fullText && card.fullText !== card.summary) {
    const details = document.createElement("details");
    details.className = "gm-ability-more";
    const summary = document.createElement("summary");
    summary.textContent = "Full description";
    const body = gmEl("div", "gm-ability-fulltext");
    body.appendChild(gmEl("p", null, card.fullText));
    if (card.combatNote) body.appendChild(gmEl("small", "gm-muted", card.combatNote));
    details.append(summary, body);
    article.appendChild(details);
  } else if (card.combatNote) {
    article.appendChild(gmEl("small", "gm-muted gm-card-combat-note", card.combatNote));
  }
  return article;
}

const GM_COMPLETE_VALUE_KEYS = Object.freeze([
  // Human-facing scalar and mechanics fields.  This is deliberately an
  // allowlist: complete-character records can carry receipts, requests, and
  // seeds that must remain in Advanced / Developer rather than the owner UI.
  "text", "description", "summary", "full_description", "full_text", "record_text", "one_line_description",
  "name", "display_name", "title", "label", "item_name", "equipment_name", "value", "amount", "current", "maximum",
  "score", "modifier", "quantity", "unit", "minimum", "minimum_cl", "required", "available", "status", "state", "reason", "acquired_at_character_cl", "acquired_at_path_level", "attained_at_cl",
  "type", "kind", "category", "realm", "cl", "level", "current_cl", "cultivation_level", "effective_cl", "path_level",
  "owning_path_level", "attained_path_level", "required_path_level", "acquisition_cl", "gained_at_cl", "granted_at_cl",
  "path", "path_id", "path_name", "owning_path_id", "owning_path_name", "subpath", "subpath_id", "subpath_name",
  "feature_id", "feature_record_id", "record_id", "art_id", "insight_id", "event_id", "occurrence_id", "choice_id", "choice_kind", "packet_id", "sequence", "event", "attainment_event", "acquisition_event",
  "repeat_index", "parent_record_id", "parent_record_hash", "source_id", "source_hash", "source_record_hash", "record_hash", "factor_id", "feature_record_hash",
  "source_anchor", "source_packet_ids", "source_evidence", "source_binding", "source", "source_rules_text", "effective_rules_text", "path_source", "corpus_path", "factory_source_path", "pack_id", "pack_hash", "pack_version",
  "line_start", "line_end", "section_sha256", "source_section_hash", "source_file_hash", "source_path", "sha256", "file_hash", "file_sha256", "anchor", "published_text", "published_block", "published_section", "section_text", "source_text", "source_excerpt", "source_kind", "source_cl_basis", "minimum_realm_band",
  "effect", "full_effect", "effective_effect", "mechanics", "source_mechanics", "action", "actions", "action_surface", "primary_action", "action_type", "action_type_label", "target", "range", "timing", "mechanical_projection", "classification", "access_category", "canonical_category",
  "roll", "roll_save_check", "attack", "attack_roll", "save", "saving_throws", "check", "dc", "formula", "dice", "bonus",
  "damage", "damage_type", "cost", "costs", "cp", "mc", "complexity", "learning_dc", "resource_costs", "resource_gains", "resource_requirements", "resource_cost_options", "default", "resource_limits", "drawbacks",
  "training_choice_cost", "limit", "limits", "counterplay", "failure", "success", "success_by_10", "on_success", "on_failure",
  "duration", "reach", "size", "stability_credit", "cp_credit", "hp_restoration", "at_owning_path_cl_14", "bone_strike",
  "guard_the_sovereign", "riders", "resolution", "cleanup", "requirements", "requirement", "precondition", "preconditions",
  "states", "state_array", "state_arrays", "condition", "stacking", "non_stacking", "ownership", "acquisition", "attainment",
  "factors", "factor_adapters", "factor_count", "factor_ids", "canonical_id", "steps", "step", "construction", "automatic_construction",
  "mode", "outcome", "payment", "roll", "source_selection", "source_selection_score", "automatic_policy", "identity",
  "deltas", "ability_scores", "ability_scores_after", "abilities", "ability", "STR", "DEX", "CON", "INT", "WIS", "CHA", "ability_change_applied", "trained_choices", "choices",
  "levels", "level", "hp", "pb", "proficiency_bonus", "resources", "resource", "resource_id", "state_id", "current_state_note", "ability_scores_before", "granted_feature_ids", "automatic_feature_record_ids", "method", "foundation",
  "coverage", "selected", "selection", "insight_occurrence", "content_binding", "execution_authority", "manual_runtime_boundary", "rest_cadence", "action_or_procedure", "durations_detected", "expression_kind", "frequency_or_recharge", "ranges_detected", "recordkeeping_required", "resolution_methods", "resource_costs_detected",
  "action_types", "execution_profile", "execution_status", "profile", "capabilities", "display_only_not_execution_authority",
  "training_sources", "contents", "restrictions", "risks", "false_routes", "methods", "recipes", "theory", "warnings", "recorded_arts", "recorded_art_ids", "taught_arts", "manuals", "manual_lineage", "lineage", "source_provenance",
  "hook", "hooks", "dao", "i_ching", "core_theme", "principles", "roleplay_expression", "tactical_expression", "gm_usage_notes",
  "branches", "branch", "fallback", "economy", "round_offset", "priorities", "resources", "states", "capability_status",
  "source_backed", "finalized", "valid", "required_count", "available_count", "member_count", "checksum_count", "reports",
]);

const GM_COMPLETE_LONG_TEXT_KEYS = Object.freeze([
  "record_text", "full_description", "full_text", "source_rules_text", "effective_rules_text", "description", "text",
]);

function gmCompleteDocuments(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return [];
  const documents = Object.entries(data)
    .filter(([key, value]) => /\.json$/i.test(key) && value && typeof value === "object")
    .map(([, value]) => value);
  return documents.length ? documents : [data];
}

function gmCompleteDisplayValue(value, depth = 0) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (depth > 6) return "";
  if (Array.isArray(value)) {
    return value.map(item => gmCompleteDisplayValue(item, depth + 1)).filter(Boolean).join(" · ");
  }
  if (typeof value !== "object") return "";
  return GM_COMPLETE_VALUE_KEYS
    .filter(key => Object.prototype.hasOwnProperty.call(value, key))
    .map(key => {
      const rendered = gmCompleteDisplayValue(value[key], depth + 1);
      return rendered ? `${friendlyLabel(key)}: ${rendered}` : "";
    })
    .filter(Boolean)
    .join("; ");
}

function gmCompleteRowIdentity(row, identity = "record") {
  if (!row || typeof row !== "object") return "";
  const scalar = value => Array.isArray(value) ? value.map(item => String(item ?? "")).join(",") : String(value ?? "");
  const nestedEventId = value => value && typeof value === "object" ? (value.event_id || value.id || "") : "";
  const event = row.event_id || row.acquisition_event_id || row.level_event_id
    || nestedEventId(row.attainment_event) || nestedEventId(row.acquisition_event) || nestedEventId(row.event);
  if (identity === "occurrence") {
    const selectionEvent = row.selection && typeof row.selection === "object" ? nestedEventId(row.selection.event) : "";
    const id = row.occurrence_id || row.event_id || row.insight_id || row.feature_occurrence_id
      || row.feature_id || row.feature_record_id || row.record_id || event || row.id;
    const cl = row.gained_at_cl ?? row.acquisition_cl ?? row.attained_at_cl ?? row.acquired_at_character_cl ?? row.cl;
    const pathLevel = row.owning_path_level ?? row.acquired_at_path_level ?? row.attained_path_level ?? row.path_level;
    const repeat = row.repeat_index ?? "";
    const packets = scalar(row.source_packet_ids || row.source_packets || row.source_packet_id);
    if (id || cl !== undefined && cl !== null || pathLevel !== undefined && pathLevel !== null || repeat !== "" || event || selectionEvent || packets) {
      return ["occurrence", id, cl, pathLevel, repeat, event, selectionEvent, packets].join("|");
    }
  } else if (identity === "level") {
    const cl = row.cl ?? row.effective_cl ?? row.level;
    const levelEvent = event || row.sequence;
    if (cl !== undefined || levelEvent) return ["level", cl, levelEvent].join("|");
  }
  return [row.display_name, row.name, row.title, row.label, row.record_id, row.id, row.summary, row.description]
    .map(value => scalar(value)).join("|");
}

function gmCompleteAliasSignature(row) {
  if (!row || typeof row !== "object") return null;
  const scalar = value => Array.isArray(value) ? value.map(item => String(item ?? "")).join(",") : String(value ?? "");
  const nested = (value, keys) => {
    if (!value || typeof value !== "object") return "";
    for (const key of keys) if (value[key] !== undefined && value[key] !== null && value[key] !== "") return String(value[key]);
    return "";
  };
  const base = new Set();
  for (const [prefix, value] of [
    ["record", row.record_id || row.art_id || row.manual_id || row.allocation_id || row.feature_record_id || row.insight_id],
    ["source", row.source_id || nested(row.source, ["source_id", "record_id", "id"])],
    ["hash", row.record_hash || row.source_record_hash || row.feature_record_hash || nested(row.source, ["record_hash", "source_hash", "hash"])],
  ]) {
    if (value !== undefined && value !== null && value !== "") base.add(`${prefix}:${value}`);
  }
  const occurrence = row.occurrence_id || row.feature_occurrence_id || row.insight_id || "";
  const event = row.event_id || row.acquisition_event_id || row.level_event_id
    || nested(row.attainment_event, ["event_id", "id"]) || nested(row.acquisition_event, ["event_id", "id"])
    || nested(row.event, ["event_id", "id"]);
  const clValue = row.gained_at_cl ?? row.acquisition_cl ?? row.acquired_at_character_cl ?? row.granted_at_cl ?? row.cl;
  const cl = clValue === undefined || clValue === null || clValue === "" ? "" : String(clValue);
  const packets = new Set((Array.isArray(row.source_packet_ids) ? row.source_packet_ids : [row.source_packet_id || row.source_packets])
    .filter(value => value !== undefined && value !== null && value !== "").map(value => String(value)));
  if (!base.size && !occurrence && !event && !cl && !packets.size) return null;
  return {base, occurrence: String(occurrence || ""), event: String(event || ""), cl, packets};
}

function gmCompleteAliasSignaturesConflict(left, right) {
  if (left.occurrence && right.occurrence && left.occurrence !== right.occurrence) return true;
  if (left.event && right.event && left.event !== right.event) return true;
  if (left.cl && right.cl && left.cl !== right.cl) return true;
  if (left.packets.size && right.packets.size && ![...left.packets].some(packet => right.packets.has(packet))) return true;
  return false;
}

function gmCompleteAliasMatches(left, right) {
  if (!left || !right || ![...left.base].some(token => right.base.has(token))) return false;
  return !gmCompleteAliasSignaturesConflict(left, right);
}

function gmCompleteRows(documents, keys, {nested = true, objects = true, dedupe = true, identity = "record"} = {}) {
  const rows = [];
  const append = value => {
    if (Array.isArray(value)) rows.push(...value.filter(item => item && typeof item === "object"));
    else if (objects && value && typeof value === "object") rows.push(value);
  };
  for (const document of documents) {
    if (!document || typeof document !== "object") continue;
    for (const key of keys) append(document[key]);
    if (!nested) continue;
    for (const value of Object.values(document)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      for (const key of keys) append(value[key]);
    }
  }
  if (!dedupe) return rows;
  if (identity === "alias") {
    const signatures = [];
    return rows.filter(row => {
      const signature = gmCompleteAliasSignature(row);
      if (!signature) return true;
      if (signatures.some(previous => gmCompleteAliasMatches(previous, signature))) return false;
      signatures.push(signature);
      return true;
    });
  }
  const seen = new Set();
  return rows.filter(row => {
    const key = gmCompleteRowIdentity(row, identity);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function gmCompleteFirst(documents, keys) {
  for (const document of documents) {
    for (const key of keys) {
      const value = document && typeof document === "object" ? document[key] : null;
      if (value !== null && value !== undefined && value !== "") return value;
    }
  }
  return null;
}

function gmCompleteRecordName(row, fallback = "Source-backed record") {
  if (!row || typeof row !== "object") return typeof row === "string" ? row : fallback;
  return row.display_name || row.name || row.title || row.label || row.item_name || row.equipment_name || fallback;
}

function gmCompleteDetailDisclosure(row, fields) {
  if (!row || typeof row !== "object") return null;
  const renderedFields = [];
  for (const [key, label] of fields) {
    if (!Object.prototype.hasOwnProperty.call(row, key)) continue;
    const rendered = gmCompleteDisplayValue(row[key]);
    if (!rendered) continue;
    renderedFields.push({key, label, rendered});
  }
  if (!renderedFields.length) return null;
  const details = document.createElement("details");
  details.className = "gm-complete-record-details";
  details.appendChild(gmEl("summary", null, "Full source-backed rules and provenance"));
  const body = gmEl("dl", "gm-complete-record-fields");
  for (const field of renderedFields) {
    body.appendChild(gmEl("dt", null, field.label));
    const valueClass = GM_COMPLETE_LONG_TEXT_KEYS.includes(field.key) ? "gm-complete-longtext" : "";
    body.appendChild(gmEl("dd", valueClass, field.rendered));
  }
  details.appendChild(body);
  return details;
}

function gmCompleteRecordCard(row, {className = "", fallback = "Source-backed record", runtimeBoundaryNote = ""} = {}) {
  const article = gmEl("article", `gm-complete-record-card${className ? ` ${className}` : ""}`);
  if (row && typeof row === "object") {
    const occurrenceId = row.occurrence_id || row.feature_occurrence_id || row.insight_id
      || row.feature_id || row.feature_record_id || row.record_id;
    const eventId = row.event_id || row.acquisition_event_id || row.level_event_id
      || (row.attainment_event && (row.attainment_event.event_id || row.attainment_event.id))
      || (row.acquisition_event && (row.acquisition_event.event_id || row.acquisition_event.id))
      || (row.event && (row.event.event_id || row.event.id));
    if (occurrenceId) article.dataset.occurrenceId = String(occurrenceId);
    if (eventId) article.dataset.eventId = String(eventId);
    const level = row.cl ?? row.gained_at_cl ?? row.acquisition_cl ?? row.acquired_at_character_cl ?? row.path_level;
    if (level !== undefined && level !== null) article.dataset.characterLevel = String(level);
  }
  const name = gmCompleteRecordName(row, fallback);
  if (!name) return null;
  article.appendChild(gmEl("h5", null, name));
  const summary = row && typeof row === "object"
    ? row.one_line_description || row.summary || row.description
    : row;
  if (summary) article.appendChild(gmEl("p", "gm-card-summary", gmCompleteDisplayValue(summary)));
  const facts = [];
  for (const [key, label] of [
    ["timing_or_category", "Timing / category"], ["timing", "Timing"], ["acquisition_cl", "Acquired at CL"],
    ["acquired_at_character_cl", "Acquired at character CL"], ["gained_at_cl", "Gained at CL"], ["cl", "Character level"],
    ["required_path_level", "Required Path level"], ["owning_path_level", "Owning Path level"],
    ["acquired_at_path_level", "Acquired Path level"], ["attained_path_level", "Attained Path level"],
    ["path_level", "Acquired Path level"], ["event_id", "Event"], ["occurrence_id", "Occurrence"],
    ["choice_kind", "Choice"], ["ability", "Ability"], ["amount", "Amount"], ["ability_change_applied", "Ability change applied"],
    ["repeat_index", "Repeat"], ["type", "Type"], ["quantity", "Quantity"], ["state", "State"], ["status", "Status"],
    ["cost", "Cost"], ["cp", "CP"], ["mc", "MC"], ["dc", "DC"], ["training_choice_cost", "Trained-choice cost"],
    ["manual_runtime_boundary", "Runtime boundary"], ["source_id", "Source"], ["source_record_hash", "Source record hash"],
  ]) {
    const value = row && typeof row === "object" ? row[key] : null;
    const rendered = gmCompleteDisplayValue(value);
    if (rendered) facts.push(`${label}: ${rendered}`);
  }
  if (facts.length) article.appendChild(gmEl("p", "gm-complete-facts", facts.join(" · ")));
  if (runtimeBoundaryNote) article.appendChild(gmEl("p", "gm-complete-boundary", runtimeBoundaryNote));
  const details = gmCompleteDetailDisclosure(row, [
    ["record_text", "Complete record text"], ["full_description", "Full description"], ["full_text", "Full text"],
    ["effective_rules_text", "Effective source rules"], ["source_rules_text", "Published source rules"],
    ["mechanics", "Mechanics"], ["effect", "Effect"], ["action", "Action"], ["actions", "Actions"],
    ["factors", "Factors"], ["factor_adapters", "Factor applications"], ["steps", "Construction steps"],
    ["acquisition", "Acquisition"], ["attainment_event", "Attainment event"], ["acquisition_event", "Acquisition event"],
    ["event", "Event provenance"], ["selection", "Selected choice and provenance"], ["source", "Source binding"], ["source_binding", "Source binding"],
    ["source_packet_ids", "Source packets"], ["source_evidence", "Source evidence"], ["content_binding", "Content binding"],
    ["execution_authority", "Execution authority"], ["construction", "Construction provenance"], ["automatic_construction", "Automatic construction"],
    ["contents", "Manual contents"], ["training_sources", "Training sources"], ["restrictions", "Restrictions"], ["risks", "Risks"], ["lineage", "Lineage"],
    ["deltas", "Selected deltas"], ["ability_scores_after", "Resulting ability scores"], ["ability_change_applied", "Ability change applied"],
  ]);
  if (details) article.appendChild(details);
  return article;
}

function gmCompleteListCard(title, values, {className = ""} = {}) {
  const card = gmEl("article", `gm-info-card${className ? ` ${className}` : ""}`);
  card.appendChild(gmEl("h5", null, title));
  const list = gmEl("ul", "gm-complete-list");
  for (const value of values) {
    const rendered = gmCompleteDisplayValue(value);
    if (rendered) list.appendChild(gmEl("li", null, rendered));
  }
  if (list.childElementCount) card.appendChild(list);
  return card;
}

function gmCompleteSurfaceSection(surface, content, {className = ""} = {}) {
  const section = gmEl("section", `gm-complete-surface${className ? ` ${className}` : ""}`);
  section.dataset.completeSurface = surface.id;
  section.appendChild(gmEl("h3", "gm-complete-surface-heading", surface.label));
  if (surface.available) {
    if (content && content.childElementCount) section.appendChild(content);
    else section.appendChild(gmEl("p", "gm-muted", "No human-facing records reported by the verified source."));
  } else {
    section.appendChild(gmEl("p", "gm-complete-unavailable", "This surface is unavailable for the current verified character source."));
  }
  return section;
}

function gmCompleteNoneState(documents, keys = []) {
  return documents.some(document => {
    if (!document || typeof document !== "object") return false;
    const values = keys.length ? keys.map(key => document[key]) : [document.none_state, document.state, document.status];
    return values.some(value => {
      if (value === true) return true;
      if (typeof value === "string") return ["none", "explicit_none", "not_acquired", "not_projected"].includes(value.toLowerCase());
      return value && typeof value === "object" && (
        value.state === "none" || value.status === "none" || value.explicit === true || value.present === false
      );
    });
  });
}

function gmCompleteRecordSurfaceContent(documents, keys, title, {noneKeys = [], occurrence = false, aliasDedupe = false, excludeSyntheticProjectTraining = false} = {}) {
  const content = gmEl("div", "gm-complete-surface-content");
  const identity = aliasDedupe ? "alias" : occurrence ? "occurrence" : "record";
  const collectedRows = gmCompleteRows(documents, keys, {
    nested: true, objects: false, dedupe: aliasDedupe || !occurrence, identity,
  });
  const rows = excludeSyntheticProjectTraining
    ? collectedRows.filter(row => !(row && row.type === "other"
      && typeof row.source_id === "string" && row.source_id.startsWith("gm.training.project.")))
    : collectedRows;
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row, {fallback: occurrence ? "Source-backed occurrence" : "Source-backed record"});
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  } else if (gmCompleteNoneState(documents, noneKeys)) {
    content.appendChild(gmInfoCard(title, "Explicitly none in the verified source."));
  }
  return content;
}

function gmCompleteActionContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const readiness = gmCompleteFirst(documents, ["status", "candidate_status", "combat_execution_status"]);
  const globalReadiness = gmCompleteFirst(documents, ["global_combat_readiness"]);
  const authority = gmCompleteFirst(documents, ["mechanical_authority", "execution_authority"]);
  const signature = gmCompleteFirst(documents, ["signature_loadout_record_ids"]);
  const readinessLines = [];
  if (readiness) readinessLines.push(`Source status: ${friendlyLabel(readiness)}`);
  if (globalReadiness !== null && globalReadiness !== undefined) readinessLines.push(`Global combat readiness: ${gmCompleteDisplayValue(globalReadiness)}`);
  if (authority !== null && authority !== undefined) readinessLines.push(`Readiness classification: ${gmCompleteDisplayValue(authority)}`);
  if (Array.isArray(signature)) readinessLines.push(`Signature loadout: ${signature.length} source-bound record${signature.length === 1 ? "" : "s"}`);
  if (readinessLines.length) content.appendChild(gmInfoCard("Action surface readiness", readinessLines));
  const actions = gmCompleteRows(documents, ["actions", "procedures"], {nested: false, objects: false});
  if (!actions.length) return content;
  const cards = gmEl("div", "gm-complete-action-grid");
  for (const action of actions) {
    const card = gmEl("article", "gm-complete-action-card");
    card.appendChild(gmEl("h4", null, gmCompleteRecordName(action, "Source-backed action")));
    const badges = gmEl("div", "gm-badges");
    for (const [key, label] of [["action_type_label", "Type"], ["action_type", "Type"], ["type", "Type"], ["timing", "Timing"], ["category", "Category"], ["combat_execution_status", "Readiness"], ["capability_status", "Classification"]]) {
      const rendered = gmCompleteDisplayValue(action[key]);
      if (rendered && !Array.from(badges.children).some(node => node.textContent === `${label}: ${rendered}`)) badges.appendChild(gmBadge(`${label}: ${rendered}`));
    }
    if (badges.childElementCount) card.appendChild(badges);
    const mechanics = [
      ["Cost", action.cost], ["Range", action.range], ["Target", action.target], ["Roll / save / check", action.roll_save_check],
      ["Effect", action.effect], ["Failure", action.failure], ["Duration", action.duration], ["Limit", action.limit],
      ["Counterplay", action.counterplay], ["Resource costs", action.resource_costs], ["Cost options", action.resource_cost_options], ["Resource gains", action.resource_gains],
      ["Requirements", action.resource_requirements], ["States", action.state_arrays], ["Description", action.full_description || action.one_line_description],
    ];
    const facts = gmEl("dl", "gm-complete-mechanics");
    for (const [label, value] of mechanics) {
      const rendered = gmCompleteDisplayValue(value);
      if (!rendered) continue;
      facts.append(gmEl("dt", null, label), gmEl("dd", null, rendered));
    }
    if (facts.childElementCount) card.appendChild(facts);
    cards.appendChild(card);
  }
  content.appendChild(cards);
  return content;
}

function gmCompleteActionReference(value) {
  if (typeof value !== "string" || !value.trim() || /^gm[._-]?training(?:[._-]|$)/i.test(value.trim())) return "";
  return value.trim();
}

function gmCompleteActionId(row) {
  if (!row || typeof row !== "object") return "";
  return gmCompleteActionReference(row.action_id || row.record_id || row.stable_id);
}

function gmCompleteActionLookup(actionDocuments, composite) {
  const lookup = new Map();
  const add = row => {
    const id = gmCompleteActionId(row);
    if (!id) return;
    const previous = lookup.get(id);
    lookup.set(id, previous ? {...row, ...previous} : row);
  };
  for (const row of gmCompleteRows(actionDocuments, ["actions", "procedures"], {nested: false, objects: false})) add(row);
  for (const row of Array.isArray(composite?.linked_action_details) ? composite.linked_action_details : []) add(row);
  return lookup;
}

function gmCompleteActionNameFromId(value, lookup) {
  const id = gmCompleteActionReference(value);
  if (!id) return "";
  return gmCompleteRecordName(lookup.get(id), "Source-backed action");
}

function gmCompleteActionMechanicsCard(action, {className = "gm-complete-action-card"} = {}) {
  const card = gmEl("article", className);
  card.appendChild(gmEl("h4", null, gmCompleteRecordName(action, "Source-backed action")));
  const badges = gmEl("div", "gm-badges");
  for (const [key, label] of [["action_type_label", "Type"], ["action_type", "Type"], ["type", "Type"], ["timing", "Timing"], ["category", "Category"], ["combat_execution_status", "Readiness"], ["capability_status", "Classification"]]) {
    const rendered = gmCompleteDisplayValue(action?.[key]);
    if (rendered && !Array.from(badges.children).some(node => node.textContent === `${label}: ${rendered}`)) badges.appendChild(gmBadge(`${label}: ${rendered}`));
  }
  if (badges.childElementCount) card.appendChild(badges);
  const mechanics = [
    ["Cost", action?.cost], ["Range", action?.range], ["Target", action?.target], ["Roll / save / check", action?.roll_save_check],
    ["Effect", action?.effect], ["Failure", action?.failure], ["Duration", action?.duration], ["Limit", action?.limit],
    ["Counterplay", action?.counterplay], ["Resource costs", action?.resource_costs], ["Cost options", action?.resource_cost_options], ["Resource gains", action?.resource_gains],
    ["Requirements", action?.resource_requirements], ["States", action?.state_arrays], ["Description", action?.full_description || action?.one_line_description],
  ];
  const facts = gmEl("dl", "gm-complete-mechanics");
  for (const [label, value] of mechanics) {
    const rendered = gmCompleteDisplayValue(value);
    if (!rendered) continue;
    facts.append(gmEl("dt", null, label), gmEl("dd", null, rendered));
  }
  if (facts.childElementCount) card.appendChild(facts);
  return card;
}

function gmCompleteFactsCard(title, facts) {
  const lines = [];
  for (const [label, value] of facts) {
    const rendered = gmCompleteDisplayValue(value);
    if (rendered) lines.push(`${label}: ${rendered}`);
  }
  return lines.length ? gmInfoCard(title, lines) : null;
}

function gmCompleteOverviewContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const identity = gmCompleteFirst(documents, ["identity"]);
  const identityCard = gmCompleteFactsCard("Identity", [
    ["Name", identity && (identity.display_name || identity.name)], ["Title", identity && identity.title],
    ["Concept", identity && identity.concept], ["Species", identity && (identity.species || identity.creature_type)],
    ["Realm", identity && (identity.realm_display || identity.realm)], ["Cultivation level", identity && (identity.cultivation_level || identity.effective_cl)],
    ["Path", identity && identity.path], ["Subpath", identity && identity.subpath], ["Key ability", identity && identity.key_ability],
  ]);
  if (identityCard) content.appendChild(identityCard);
  const stats = gmCompleteFirst(documents, ["core_stats", "stats"]);
  const statsCard = gmCompleteFactsCard("Core stats", [
    ["Armor Class", stats && stats.armor_class], ["Hit Points", stats && stats.hit_points], ["Initiative", stats && stats.initiative],
    ["Speed", stats && stats.speed], ["Primary resource", stats && stats.primary_resource],
    ["Technique attack", stats && stats.technique_attack_bonus], ["Technique save DC", stats && stats.technique_save_dc],
  ]);
  if (statsCard) content.appendChild(statsCard);
  const abilities = stats && Array.isArray(stats.abilities) ? stats.abilities : [];
  if (abilities.length) content.appendChild(gmCompleteListCard("Ability scores", abilities));
  return content;
}

function gmCompleteLevelRowCard(level, index) {
  const cl = level && typeof level === "object" ? level.cl ?? level.effective_cl ?? level.level : null;
  const card = gmEl("article", "gm-complete-level-card");
  if (cl !== null && cl !== undefined) card.dataset.characterLevel = String(cl);
  card.dataset.levelRow = String(index + 1);
  card.appendChild(gmEl("h4", null, cl === null || cl === undefined ? `Advancement ${index + 1}` : `CL ${cl}`));
  const facts = [];
  for (const [key, label] of [["realm", "Realm"], ["pb", "Proficiency bonus"], ["proficiency_bonus", "Proficiency bonus"], ["hp", "Hit points"], ["resources", "Resources"], ["ability_scores", "Ability scores"], ["ability_scores_after", "Resulting ability scores"], ["deltas", "Selected increases"], ["trained_choices", "Trained choices"]]) {
    const value = level && typeof level === "object" ? level[key] : null;
    const rendered = gmCompleteDisplayValue(value);
    if (rendered) facts.push(`${label}: ${rendered}`);
  }
  if (facts.length) card.appendChild(gmEl("p", "gm-complete-facts", facts.join(" · ")));
  const grants = gmCompleteRows([level], ["earned_feature_occurrences", "automatic_feature_occurrences", "automatic_grants", "earned_features"], {nested: false, objects: false, dedupe: false, identity: "occurrence"});
  if (grants.length) {
    card.appendChild(gmEl("h5", "gm-complete-level-grants-heading", "Automatic grants at this level"));
    const list = gmEl("div", "gm-complete-occurrence-grid");
    for (const grant of grants) {
      const grantCard = gmCompleteRecordCard(grant, {className: "gm-complete-occurrence-card", fallback: "Automatic feature occurrence"});
      if (grantCard) list.appendChild(grantCard);
    }
    card.appendChild(list);
  }
  const choices = gmCompleteRows([level], ["trained_choices", "choices"], {nested: false, objects: false, dedupe: false, identity: "occurrence"});
  if (choices.length) card.appendChild(gmCompleteListCard("Choices at this level", choices));
  return card;
}

function gmCompleteLevelingContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const levels = gmCompleteRows(documents, ["levels"], {nested: false, objects: false, dedupe: false, identity: "level"});
  if (!levels.length) return content;
  const grid = gmEl("div", "gm-complete-level-grid");
  levels.forEach((level, index) => grid.appendChild(gmCompleteLevelRowCard(level, index)));
  content.appendChild(grid);
  return content;
}

function gmCompleteBackgroundContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const background = gmCompleteFirst(documents, ["background_origin"]);
  if (background && typeof background === "object") {
    const backgroundCard = gmCompleteFactsCard("Background", [
      ["Name", background.background && (background.background.display_name || background.background.name)],
      ["Summary", background.background && (background.background.summary || background.background.description)],
      ["Skills", background.background && background.background.skill_proficiencies],
      ["Languages", background.background && background.background.languages],
      ["Talent", background.background_talent && (background.background_talent.display_name || background.background_talent.name)],
    ]);
    if (backgroundCard) content.appendChild(backgroundCard);
    const originCard = gmCompleteFactsCard("Origin insight", [
      ["Name", background.origin_insight && (background.origin_insight.display_name || background.origin_insight.name)],
      ["Summary", background.origin_insight && (background.origin_insight.summary || background.origin_insight.description)],
      ["Selected skill", background.origin_insight && background.origin_insight.selected_skill],
      ["Selected tool", background.origin_insight && background.origin_insight.selected_tool],
      ["Selected trade", background.origin_insight && background.origin_insight.selected_trade],
      ["Selected language", background.origin_insight && background.origin_insight.selected_language],
      ["Initiative effect", background.origin_insight && background.origin_insight.initiative_effect],
    ]);
    if (originCard) content.appendChild(originCard);
  }
  return content;
}

function gmCompletePathsContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const rows = gmCompleteRows(documents, ["paths", "subpaths", "path_selections"], {objects: false, dedupe: true});
  for (const key of ["path", "subpath"]) {
    const value = gmCompleteFirst(documents, [key]);
    if (value && typeof value === "object" && !Array.isArray(value)) rows.push(value);
  }
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row);
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  }
  const occurrences = gmCompleteRows(documents, ["earned_feature_occurrences", "path_feature_occurrences", "subpath_feature_occurrences"], {
    nested: true, objects: false, dedupe: false, identity: "occurrence",
  });
  if (!occurrences.length) return content;
  const byPath = new Map();
  for (const occurrence of occurrences) {
    const pathName = occurrence.owning_path_name || occurrence.path_name || occurrence.owning_path_id || occurrence.path_id || occurrence.path || "Owning Path not stated";
    const required = occurrence.required_path_level ?? occurrence.required_level ?? occurrence.minimum_path_level;
    const level = occurrence.owning_path_level ?? occurrence.acquired_at_path_level ?? occurrence.path_level ?? occurrence.attained_path_level ?? "?";
    const groupKey = `${pathName}|${level}`;
    if (!byPath.has(groupKey)) byPath.set(groupKey, {pathName, level, rows: []});
    byPath.get(groupKey).rows.push({...occurrence, required_path_level: required});
  }
  const heading = gmEl("section", "gm-complete-occurrence-groups");
  heading.appendChild(gmEl("h4", "gm-group-heading", "Earned features by owning Path and level"));
  heading.appendChild(gmEl("p", "gm-muted", "Each earned occurrence is shown with its source binding; mechanical effects follow the canonical ledger, including valid later choices."));
  for (const group of byPath.values()) {
    const groupSection = gmEl("section", "gm-complete-occurrence-group");
    groupSection.appendChild(gmEl("h5", null, `${group.pathName} · Path level ${group.level}`));
    const grid = gmEl("div", "gm-complete-occurrence-grid");
    for (const occurrence of group.rows) {
      const card = gmCompleteRecordCard(occurrence, {className: "gm-complete-occurrence-card", fallback: "Earned feature occurrence"});
      if (card) grid.appendChild(card);
    }
    groupSection.appendChild(grid);
    heading.appendChild(groupSection);
  }
  content.appendChild(heading);
  return content;
}

function gmCompleteSpheresContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const rows = gmCompleteRows(documents, ["spheres", "learned_talents", "background_talents", "automatic_sphere_components", "automatic_components"], {nested: true, objects: false, dedupe: false, identity: "occurrence"});
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row);
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  }
  return content;
}

function gmCompleteInsightBoundaryForRow(insight, pathDocuments) {
  if (!insight || typeof insight !== "object" || !Array.isArray(pathDocuments)) return null;
  const nonblank = value => value !== undefined && value !== null && value !== ""
    && (typeof value !== "string" || value.trim() !== "");
  const same = (left, right) => nonblank(left) && nonblank(right) && String(left) === String(right);
  const packets = value => Array.isArray(value)
    ? value.filter(nonblank).map(value => String(value))
    : [];
  const insightId = insight.insight_id;
  const gainedAt = insight.gained_at_cl;
  const recordHash = insight.source_record_hash;
  const standalonePackets = packets(insight.source_packet_ids);
  if (!nonblank(insightId) || !nonblank(gainedAt) || !nonblank(recordHash) || !standalonePackets.length) return null;
  const occurrences = gmCompleteRows(pathDocuments, ["earned_feature_occurrences", "path_feature_occurrences", "subpath_feature_occurrences"], {
    nested: true, objects: false, dedupe: false, identity: "occurrence",
  });
  const matches = [];
  for (const parent of occurrences) {
    if (!parent || typeof parent !== "object") continue;
    const selection = parent.selection;
    const nested = selection && typeof selection === "object" ? selection.insight_occurrence : null;
    const event = selection && typeof selection === "object" ? selection.event : null;
    const binding = nested && typeof nested === "object" ? nested.content_binding : null;
    const authority = nested && typeof nested === "object" ? nested.execution_authority : null;
    if (!nested || typeof nested !== "object" || !event || typeof event !== "object" || !binding || typeof binding !== "object") continue;
    if (!same(insightId, nested.record_id)
      || !same(gainedAt, nested.acquisition_cl)
      || !same(gainedAt, parent.acquired_at_character_cl)
      || !same(recordHash, binding.record_hash)) continue;
    const selectionEventId = event.event_id;
    const nestedEventId = nested.event_id;
    const packetId = event.packet_id;
    const parentPackets = packets(parent.source_packet_ids);
    if (!nonblank(selectionEventId) || !same(selectionEventId, nestedEventId) || !nonblank(packetId)
      || !parentPackets.includes(String(packetId)) || !standalonePackets.includes(String(packetId))) continue;
    if (nonblank(insight.event_id) && !same(insight.event_id, selectionEventId)) continue;
    matches.push(authority && typeof authority === "object" ? authority.manual_runtime_boundary : null);
  }
  if (matches.length !== 1) return null;
  const boundary = matches[0];
  return typeof boundary === "string" && boundary.trim() ? boundary : null;
}

function gmCompleteInsightsContent(documents, pathDocuments = []) {
  const content = gmEl("div", "gm-complete-surface-content");
  const coverage = gmCompleteFirst(documents, ["coverage"]);
  const coverageCard = gmCompleteFactsCard("Insight coverage", [["Coverage", coverage]]);
  if (coverageCard) content.appendChild(coverageCard);
  const rows = gmCompleteRows(documents, ["insights", "cultivation_insight_occurrences", "insight_occurrences"], {nested: true, objects: false, dedupe: true, identity: "occurrence"});
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const boundary = gmCompleteInsightBoundaryForRow(row, pathDocuments);
      const card = gmCompleteRecordCard(row, {
        fallback: "Cultivation insight occurrence",
        runtimeBoundaryNote: boundary
          ? `Related Path acquisition boundary: ${boundary}`
          : "Execution boundary not supplied for this occurrence.",
      });
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  }
  return content;
}

function gmCompleteFoundationMethodContent(documents, key) {
  const content = gmEl("div", "gm-complete-surface-content");
  const value = gmCompleteFirst(documents, [key]);
  if (value && typeof value === "object") {
    if (gmCompleteNoneState([{[key]: value}], [key])) content.appendChild(gmInfoCard(friendlyLabel(key), "Explicitly none in the verified source."));
    else {
      const card = gmCompleteRecordCard(value);
      if (card) content.appendChild(card);
    }
  }
  return content;
}

function gmCompleteCompanionsContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const coverageCard = gmCompleteFactsCard("Companion coverage", [["Coverage", gmCompleteFirst(documents, ["coverage"])] ]);
  if (coverageCard) content.appendChild(coverageCard);
  const rows = gmCompleteRows(documents, ["companions", "spirit_companions"], {nested: false, objects: false});
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row);
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  }
  return content;
}

function gmCompleteEquipmentContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const rows = gmCompleteRows(documents, ["equipment"], {nested: false, objects: false});
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row);
      if (card) cards.appendChild(card);
    }
    content.appendChild(cards);
  } else if (gmCompleteNoneState(documents, ["equipment", "none_state"])) {
    content.appendChild(gmInfoCard("Equipment", "Explicitly none in the verified source."));
  }
  return content;
}

function gmCompleteResourceRows(documents) {
  const rows = [];
  const resourceRowsSeen = new Set();
  const append = value => {
    if (Array.isArray(value)) rows.push(...value.filter(item => item && typeof item === "object"));
  };
  const appendResources = value => {
    // The verified GM model retains all pools in the primary-resource wrapper.
    // Its historical qi_maximum name also wraps Stamina and Resonance builds.
    const primary = value && !Array.isArray(value) ? value.qi_maximum : null;
    const definitions = Array.isArray(value) ? value
      : Array.isArray(primary?.definitions) && primary.definitions.length ? primary.definitions
      : primary && typeof primary === "object" ? [primary] : [];
    for (const definition of definitions) {
      if (!definition || typeof definition !== "object") continue;
      const row = {...definition,
        current: definition.current ?? definition.build_state_current,
        maximum: definition.maximum ?? definition.max,
        current_state_note: definition.current_state_note ?? primary?.current_state_note,
      };
      const signature = JSON.stringify(row);
      if (resourceRowsSeen.has(signature)) continue;
      resourceRowsSeen.add(signature);
      rows.push(row);
    }
  };
  for (const document of documents) {
    if (!document || typeof document !== "object") continue;
    appendResources(document.resources); append(document.states); append(document.suppression); append(document.rule_exports);
    const nested = document.equipment_resources_states;
    if (nested && typeof nested === "object") {
      appendResources(nested.resources); append(nested.states); append(nested.typed_definitions);
    }
  }
  return rows;
}

function gmCompleteResourcesContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  const rows = gmCompleteResourceRows(documents);
  if (rows.length) {
    const cards = gmEl("div", "gm-complete-record-grid");
    for (const row of rows) {
      const card = gmCompleteRecordCard(row);
      if (card) {
        if (row.resource_id) card.dataset.resourceId = String(row.resource_id);
        const amounts = [["Saved current", row.current], ["Maximum", row.maximum]]
          .filter(([, value]) => typeof value === "number" && Number.isFinite(value))
          .map(([label, value]) => `${label}: ${value}`);
        if (amounts.length) card.appendChild(gmEl("p", "gm-complete-facts", amounts.join(" · ")));
        if (row.current_state_note) card.appendChild(gmEl("p", "gm-muted", gmCompleteDisplayValue(row.current_state_note)));
        cards.appendChild(card);
      }
    }
    content.appendChild(cards);
  }
  const stateNote = gmCompleteFirst(documents, ["current_state_note"]);
  if (stateNote) content.appendChild(gmInfoCard("State note", stateNote));
  return content;
}

function gmCompleteDaoContent(documents) {
  const content = gmEl("div", "gm-complete-surface-content");
  for (const [key, label] of [["dao", "Dao"], ["i_ching", "I Ching"], ["dao_i_ching", "Dao / I Ching"]]) {
    const value = gmCompleteFirst(documents, [key]);
    if (!value || typeof value !== "object") continue;
    const card = gmCompleteFactsCard(label, [
      ["Name", value.display_name || value.name], ["Core theme", value.core_theme], ["Principles", value.principles],
      ["Roleplay expression", value.roleplay_expression], ["At the table", value.tactical_expression], ["GM usage", value.gm_usage_notes],
    ]);
    if (card) content.appendChild(card);
  }
  return content;
}

function gmCompleteDiagnosticsContent(surface) {
  const details = document.createElement("details");
  details.className = "developer-diagnostics gm-complete-diagnostics";
  details.appendChild(gmEl("summary", null, "Bounded verification details"));
  const body = gmEl("div", "gm-complete-diagnostic-body");
  const data = surface.data && typeof surface.data === "object" ? surface.data : {};
  const archive = data.archive && typeof data.archive === "object" ? data.archive : {};
  const source = data.source && typeof data.source === "object" ? data.source : {};
  const statusCard = gmCompleteFactsCard("Verification status", [["Archive", archive.status], ["Source", source.kind], ["Finalized", source.finalized]]);
  if (statusCard) body.appendChild(statusCard);
  const reports = data.reports && typeof data.reports === "object" ? Object.values(data.reports) : [];
  const reportLines = [];
  for (const report of reports) {
    if (!report || typeof report !== "object") continue;
    const values = [report.status, report.verdict, report.valid, report.issue_count, report.action_display_count, report.training_coverage_count].filter(value => value !== undefined && value !== null);
    if (values.length) reportLines.push(values.map(gmCompleteDisplayValue).filter(Boolean).join(" · "));
  }
  if (reportLines.length) body.appendChild(gmCompleteListCard("Bounded report statuses", reportLines));
  if (!body.childElementCount) body.appendChild(gmEl("p", "gm-muted", "No bounded diagnostic status was reported."));
  details.appendChild(body);
  return details;
}

function gmCompleteSurfaceContent(surface, {actionDocuments = [], pathDocuments = []} = {}) {
  const documents = gmCompleteDocuments(surface.data);
  switch (surface.id) {
    case "overview_core_stats": return gmCompleteOverviewContent(documents);
    case "leveling": return gmCompleteLevelingContent(documents);
    case "background": return gmCompleteBackgroundContent(documents);
    case "paths_subpaths": return gmCompletePathsContent(documents);
    case "spheres_talents": return gmCompleteSpheresContent(documents);
    case "insights": return gmCompleteInsightsContent(documents, pathDocuments);
    case "actions": return gmCompleteActionContent(documents);
    case "forged_techniques": return gmCompleteRecordSurfaceContent(documents, ["forged_techniques"], "Forged techniques", {occurrence: true});
    case "manuals_recorded_arts": return gmCompleteRecordSurfaceContent(documents, ["manuals", "martial_manuals", "recorded_arts", "training_sources", "manual_lineage"], "Manuals and recorded arts", {noneKeys: ["none_state", "recorded_arts_none_state"], occurrence: true, aliasDedupe: true, excludeSyntheticProjectTraining: true});
    case "immortal_arts": return gmCompleteRecordSurfaceContent(documents, ["immortal_arts"], "Immortal arts", {noneKeys: ["none_state"], occurrence: true});
    case "foundation": return gmCompleteFoundationMethodContent(documents, "foundation");
    case "method": return gmCompleteFoundationMethodContent(documents, "method");
    case "companions": return gmCompleteCompanionsContent(documents);
    case "equipment": return gmCompleteEquipmentContent(documents);
    case "resources_states_suppression": return gmCompleteResourcesContent(documents);
    case "dao_i_ching": return gmCompleteDaoContent(documents);
    case "diagnostics": return gmCompleteDiagnosticsContent(surface);
    default: return gmEl("div", "gm-complete-surface-content");
  }
}

function gmBuildCompleteCharacterPanel(model) {
  const panel = gmPanelShell("complete_character", "Complete Character");
  panel.classList.add("gm-complete-character-panel");
  const complete = model.completeCharacter;
  if (!complete) {
    panel.appendChild(gmInfoCard("Complete character mechanics", "No complete-character envelope was supplied for this saved sheet."));
    return panel;
  }
  const status = gmEl("section", "gm-complete-status");
  const coverage = complete.coverage || {};
  const coverageLabel = `${coverage.availableCount}/${coverage.requiredCount} surfaces verified`;
  status.appendChild(gmEl("h3", null, complete.available && coverage.complete ? "Complete character verified" : "Complete character unavailable"));
  status.appendChild(gmEl("p", null, `${complete.sourceLabel} · ${coverageLabel}.`));
  if (!complete.available) status.appendChild(gmEl("p", "gm-complete-unavailable", "The existing character sheet and export readiness remain unchanged; complete mechanics are not available from a trustworthy matching source."));
  else if (!coverage.complete) status.appendChild(gmEl("p", "gm-complete-unavailable", "Some canonical mechanics surfaces are unavailable and are shown as such."));
  if (complete.reason) status.appendChild(gmEl("p", "gm-muted", complete.reason));
  panel.appendChild(status);
  const surfaces = gmEl("div", "gm-complete-surface-grid");
  const actionSurface = complete.surfaces.actions;
  const actionDocuments = actionSurface ? gmCompleteDocuments(actionSurface.data) : [];
  const pathSurface = complete.surfaces.paths_subpaths;
  const pathDocuments = pathSurface ? gmCompleteDocuments(pathSurface.data) : [];
  for (const id of TianxiaSheetViewModel.COMPLETE_CHARACTER_SURFACE_IDS) {
    const surface = complete.surfaces[id];
    if (!surface) continue;
    surfaces.appendChild(gmCompleteSurfaceSection(surface, gmCompleteSurfaceContent(surface, {actionDocuments, pathDocuments}), {
    }));
  }
  panel.appendChild(surfaces);
  return panel;
}

/* =====================================================================
 * 2026-09-13 owner request (plan Part B): the finalized Character Sheet is
 * laid out like the GM Screen character viewer.  Every tab gets the same
 * skeleton -- a title, a one-line subtitle, human cards built from the
 * descriptive fields first, and exactly one collapsed "Technical" disclosure
 * holding ids, hashes, packet ids, and provenance.  Nothing technical appears
 * outside that disclosure, and no card is only an id or a hash.
 * ===================================================================== */

const OWNER_SHEET_TAB_SUBTITLES = Object.freeze({
  overview_core_stats: "Stable combat math and quick-read defenses.",
  leveling: "Every level, what it granted, and what changed.",
  background: "Where this cultivator came from and what that granted.",
  paths_subpaths: "The Paths walked, their Subpaths, and every earned feature.",
  spheres_talents: "Known Spheres with their automatic base abilities, and every learned Talent with its printed rules.",
  insights: "Each cultivation Insight, the milestone it was taken at, and what it raised.",
  actions: "The GM-authored Actions this character can actually take.",
  forged_techniques: "Custom techniques constructed from sealed Core tables.",
  manuals_recorded_arts: "Lineage Manuals and the Recorded Arts learned from them.",
  immortal_arts: "Immortal Arts, their Dao aspect, factors, and burdens.",
  foundation: "The Foundation, its stage benefits, and its lifecycle coverage.",
  method: "The cultivation Method and the math it applies.",
  companions: "Companions, spirits, and beasts bound to this character.",
  equipment: "Carried items and the equipment direction recorded at creation.",
  resources_states_suppression: "Resources, active states, and suppressed rules.",
  dao_i_ching: "Combat doctrine and the I Ching reading.",
  diagnostics: "Renderer, adapter, and build diagnostics.",
});

// Owner decision 2026-09-13: the read-only GM guidance note belongs in exactly
// one place — Diagnostics, the meta tab — not repeated at the top of every
// guidance-bearing tab.
const OWNER_SHEET_GUIDANCE_TABS = Object.freeze(["diagnostics"]);
const OWNER_SHEET_GUIDANCE_NOTE = "Display-only guidance; grants no action or bonus. Dao, I Ching, training sources, and advanced-art states are display-only. They grant no action, bonus, resource change, legality, or execution authority.";

// The rail portrait (owner 2026-09-27: "the token on the GX part in the top left and clicking into it to load the
// token/full size generation screen"): a completed character's circle token, or its initials; clicking it (or dropping
// a picture on it) opens the Picture and token dialog (static/tabletop/portrait.js).
function ownerRailPortrait(model, sheet) {
  const portrait = gmEl("div", "owner-rail-portrait", ownerInitials(model.name || "Tianxia"));
  const projectId = sheet?.project_id;
  if (!projectId || model.state?.tone !== "ready") return portrait;
  portrait.classList.add("is-clickable");
  portrait.tabIndex = 0;
  portrait.setAttribute("role", "button");
  portrait.title = "Picture and token: click to make or change them (drop a picture here too)";
  portrait.setAttribute("aria-label", "Picture and token");
  const showToken = () => {
    const probe = new Image();
    probe.onload = () => { portrait.style.backgroundImage = `url("${probe.src}")`; portrait.classList.add("has-token"); portrait.textContent = ""; };
    probe.src = `/api/tabletop/characters/${encodeURIComponent(projectId)}/token.png?v=${Date.now()}`;
  };
  const open = (start = null) => import("/static/tabletop/portrait.js")
    .then((module) => module.openPictureDialog({projectId, start, onSaved: showToken}))
    .catch((error) => window.alert(`The picture dialog could not open: ${error.message}`));
  portrait.addEventListener("click", () => open());
  portrait.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  portrait.addEventListener("dragover", (event) => { event.preventDefault(); portrait.classList.add("is-drop"); });
  portrait.addEventListener("dragleave", () => portrait.classList.remove("is-drop"));
  portrait.addEventListener("drop", (event) => {
    event.preventDefault();
    portrait.classList.remove("is-drop");
    const file = [...(event.dataTransfer?.files || [])].find((row) => row.type.startsWith("image/"));
    if (file) open({file});
  });
  showToken();
  return portrait;
}

// Two-letter initials for the rail portrait, as in the GM Screen viewer.
function ownerInitials(value) {
  const words = ownerSheetRunnableName(value).split(/\s+/).filter(Boolean);
  if (!words.length) return "TX";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

function ownerSheetRunnableName(value) {
  if (value === null || value === undefined) return "";
  const text = String(value).trim();
  if (!text || /^(?:-|—|–|\?|n\/?a|null|undefined|none)$/i.test(text)) return "";
  return text;
}

function ownerSheetList(value) {
  if (Array.isArray(value)) return value.map(entry => ownerSheetRunnableName(entry)).filter(Boolean);
  const single = ownerSheetRunnableName(value);
  return single ? [single] : [];
}

// The Armor Class a fight actually uses, as the sheet publishes it, without any wording around it:
// "20 (unarmored 18)". Each caller phrases it in its own voice -- the owner card reads "AC 20 ... .",
// the GM panel "Armor Class 20 ...." -- so the number and its alternative have exactly one source.
// The sheet writes the fighting numbers BESIDE the projection's own: effective_value is the Armor
// Class the table rolls against, unarmored_value is what this character would have with no body armour
// and no Shield, and effective_walking_ft already has the Strength penalty subtracted. A sheet written
// before that publishes none of the three and keeps its own reading.
// base_value is deliberately NOT labelled "unarmored": it is the chosen calculation before the
// standing bonuses are folded into value (base 17 with a standing +1 means 18 unarmored, not 17), so a
// sheet that only has base_value falls back to the plain word "base".
// Returns null when the sheet records no Armor Class at all.
function sheetArmorClassSummary(ac) {
  if (ac.value === null || ac.value === undefined) return null;
  const fighting = ac.effective_value ?? ac.value;
  const unarmored = ac.unarmored_value;
  if (unarmored !== null && unarmored !== undefined) {
    return unarmored !== fighting ? `${fighting} (unarmored ${unarmored})` : `${fighting}`;
  }
  const base = ac.base_value !== undefined && ac.base_value !== ac.value ? ` (base ${ac.base_value})` : "";
  return `${fighting}${base}`;
}

function sheetWalkingSpeedLines(speed) {
  if (speed.walking_ft === null || speed.walking_ft === undefined) return ["Not recorded."];
  const walking = speed.effective_walking_ft ?? speed.walking_ft;
  return [
    `${walking} ft walking.`,
    walking !== speed.walking_ft ? `Your armour slows you: ${speed.walking_ft} ft without it.` : null,
  ];
}

// owner_character_sheet is the sealed artifact-identical snapshot;
// display_owner_character_sheet carries the printed rules text.  The viewer
// reads the display copy when the server provides one.
function ownerSnapshotForDisplay(sheet) {
  if (!sheet || typeof sheet !== "object") return {};
  return sheet.display_owner_character_sheet || sheet.owner_character_sheet || {};
}

function ownerSheetContext(sheet) {
  const snapshot = ownerSnapshotForDisplay(sheet);
  const identity = snapshot.identity || {};
  const stats = snapshot.ability_scores_and_statistics || {};
  const complete = sheet && sheet.complete_character ? sheet.complete_character : null;
  const surfaceData = (id) => (complete && complete.surfaces && complete.surfaces[id] ? complete.surfaces[id].data : null);
  const sphereData = surfaceData("spheres_talents") || {};
  const talentLedger = sphereData["Talent_Source_Ledger.json"] || {};
  const sphereCatalog = sphereData["Selected_Spheres.json"] || {};
  const talentIndex = new Map();
  for (const row of [...(talentLedger.learned_talents || []), ...(talentLedger.background_talents || [])]) {
    if (row && row.record_id) talentIndex.set(String(row.record_id), row);
  }
  const sphereRows = Array.isArray(sphereCatalog.spheres) ? sphereCatalog.spheres : [];
  const sphereIndex = new Map();
  for (const row of sphereRows) {
    const id = row.sphere_id || row.record_id || row.sphere_record_id;
    if (id) sphereIndex.set(String(id), row);
  }
  const nameByRecordId = new Map();
  for (const [id, row] of talentIndex) if (row.display_name) nameByRecordId.set(id, row.display_name);
  for (const [id, row] of sphereIndex) {
    const name = row.display_name || row.name;
    if (name) nameByRecordId.set(id, name);
  }
  const selectedSections = snapshot.selected_record_sections || {};
  for (const rows of Object.values(selectedSections)) {
    for (const row of Array.isArray(rows) ? rows : []) {
      if (row && row.record_id && row.display_name) nameByRecordId.set(String(row.record_id), row.display_name);
    }
  }
  // Server-provided display labels: the sheet's own talent rows carry no
  // Sphere link, so grouping uses this map and falls back to Other talents.
  const talentSphereNames = sheet && sheet.talent_sphere_names && typeof sheet.talent_sphere_names === "object"
    ? sheet.talent_sphere_names
    : {};
  return {
    sheet, snapshot, identity, stats, complete, surfaceData,
    talentLedger, sphereCatalog, sphereRows, talentIndex, sphereIndex, selectedSections, talentSphereNames,
    nameFor(value) {
      const text = ownerSheetRunnableName(value);
      if (!text) return "";
      return nameByRecordId.get(text) || text;
    },
  };
}

// Internal record kinds are never shown to a human: they become plain words.
const OWNER_ACQUISITION_ROUTES = Object.freeze({
  background_talent_acquisition: "Background talent",
  background_acquisition: "Background",
  free_level_talent_acquisition: "Free level talent",
  level_advance: "Level advancement",
  new_sphere_bonus_talent_acquisition: "New-Sphere bonus",
  starting_grant: "Starting grant",
  creation_training_sphere_acquisition: "Creation training",
  creation_training_talent_acquisition: "Creation training",
  level_talent_acquisition: "Level talent",
  ai_bootstrap_talent_acquisition: "Chosen at creation",
  sphere_training_attempt: "Sphere training",
  ai_bootstrap_sphere_acquisition: "Chosen at creation",
  trained_choice_acquisition: "Trained choice",
  training_source_access: "Training source",
  cultivation_insight_acquisition: "Cultivation Insight",
  typed_none: "None recorded",
  explicit_none: "None recorded",
  method_acquisition: "Method",
  foundation_acquisition: "Foundation",
  path_acquisition: "Path",
  source_granted_subpath_feature: "Granted by Subpath",
  manual_training_attempt: "Manual training",
  manual_lineage: "Manual lineage",
  recorded_self_training: "Self-training",
  published_legal_teaching_route: "Published teaching route",
});

function ownerAcquisitionLabel(context, value) {
  const text = ownerSheetRunnableName(value);
  if (!text) return "";
  if (OWNER_ACQUISITION_ROUTES[text]) return OWNER_ACQUISITION_ROUTES[text];
  const words = text.replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

// Internal ids and hashes are never a human value: a structured value is
// flattened to its readable parts, and anything that still looks like an id or
// a hash is dropped rather than printed.
const OWNER_TECHNICAL_VALUE = /^(?:[0-9a-f]{16,}|(?:tianxia|ns1r)\.|(?:action|art|record|packet|sphere|talent|choice|event|insight|path|method|foundation)[._:][A-Za-z0-9._:\-]+$)/i;

function ownerReadableValue(value, depth = 0) {
  if (value === null || value === undefined || depth > 3) return "";
  if (typeof value === "string") {
    const text = value.trim();
    if (!text || OWNER_TECHNICAL_VALUE.test(text)) return "";
    // Several fields are a JSON array of strings; the reader wants the items.
    if (text.startsWith("[") || text.startsWith("{")) {
      const parsed = safeJson(text);
      if (parsed !== null) return ownerReadableValue(parsed, depth + 1);
    }
    return ownerStripMarkdown(ownerStripSourceChrome(text) || text);
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map(entry => ownerReadableValue(entry, depth + 1)).filter(Boolean).join(", ");
  }
  if (typeof value === "object") {
    const parts = [];
    for (const [key, entry] of Object.entries(value)) {
      // A human value keeps the fields that carry a rule, a cost, or a state
      // name.  Everything else in an evidence object -- ids, hashes, schema
      // versions, factory buckets, source locators -- is not a value a human
      // reads here.
      if (!/^(name|display_name|amount|value|cost|costs?|cp|mc|dc|limit|effect|timing|target|duration|condition|note|summary|description|text|state|status|result|route|mode|kind|type|grant|benefit|outcome|count|level|cl|bonus|penalty|modifier|resource|resources|requirement|requirements|failure|success|successful_save|failed_save|failure_by_5|counterplay|immunity|trigger|cleanup|duration_note)$/i.test(key)) continue;
      const label = ownerSheetRunnableName(key).replace(/_/g, " ");
      const rendered = ownerReadableValue(entry, depth + 1);
      if (rendered) parts.push(`${label} ${rendered}`);
    }
    return parts.join(", ");
  }
  return "";
}

// The Command 4 action surface carries an immutable JSON evidence blob inside
// its description and an identity block inside its one-line text.  Neither is a
// human description: the readable lines are extracted here and everything
// technical stays in the Technical disclosure.
const OWNER_TECHNICAL_LINE = /^\s*(record identity|source binding|execution authority|execution derivation|mechanical authority|content binding|source packets?|source evidence|packet|event hash|record hash|sha256|anchor|path|factory source path|line_start|line_end|schema|schema_version|display contract|contract)\s*[:\[]/i;

function ownerHumanLines(text, {max = 40} = {}) {
  const source = ownerSheetRunnableName(text);
  if (!source) return "";
  if (source.startsWith("{") || source.startsWith("[")) return ownerReadableValue(safeJson(source), 1);
  // The source block's own heading and the Factory's routing bookkeeping are
  // never part of the human rules text.
  const raw = ownerStripSourceChrome(source);
  if (!raw) return "";
  const lines = [];
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (OWNER_TECHNICAL_LINE.test(trimmed)) break;
    // A line that opens or embeds a raw evidence object ends the human text.
    if (trimmed.startsWith("{") || trimmed.startsWith("[") || /\{\s*"[a-z_]+"\s*:/.test(trimmed) || /":\s*[\{\[]/.test(trimmed)) {
      const cut = trimmed.search(/[\{\[]\s*"/);
      if (cut > 0) lines.push(trimmed.slice(0, cut).trim());
      break;
    }
    lines.push(trimmed);
    if (lines.length >= max) break;
  }
  const bare = ownerBareSourceText(lines.join("\n"));
  return ownerStripMarkdown(ownerDropRepeatedLines(ownerRenderTableRows(ownerSplitMergedFields(bare).split("\n")).join("\n").trim()));
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch (_error) {
    return null;
  }
}

function ownerSigned(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return number >= 0 ? `+${number}` : String(number);
}

function ownerSheetTiles(entries) {
  const grid = gmEl("div", "owner-quick-tiles");
  for (const [label, value] of entries) {
    const rendered = ownerSheetRunnableName(value);
    if (!rendered) continue;
    const tile = gmEl("article", "owner-quick-tile");
    tile.append(gmEl("span", "owner-quick-tile-label", label), gmEl("strong", "owner-quick-tile-value", rendered));
    grid.appendChild(tile);
  }
  return grid;
}

function ownerSheetTextCard(title, text, {extraClass = ""} = {}) {
  const body = ownerSheetRunnableName(text);
  if (!title && !body) return null;
  const card = gmEl("article", `gm-info-card owner-sheet-text-card${extraClass ? ` ${extraClass}` : ""}`);
  if (title) card.appendChild(gmEl("h5", null, title));
  if (body) card.appendChild(gmEl("p", "owner-sheet-rules-text", body));
  return card;
}

function ownerSheetRecordCard(row, {title = null, badges = [], summary = null, rules = null, facts = [], fallback = "Recorded character detail"} = {}) {
  const printed = ownerSheetRulesHeading(row);
  const named = ownerSheetRunnableName(title);
  const fromRow = gmCompleteRecordName(row, "");
  const heading = (named && !OWNER_TECHNICAL_VALUE.test(named) ? named : "")
    || (fromRow && !OWNER_TECHNICAL_VALUE.test(fromRow) ? fromRow : "")
    || printed
    || ownerSheetRunnableName(title)
    || fallback;
  if (!heading) return null;
  const card = gmEl("article", "gm-complete-record-card owner-sheet-record-card");
  if (row && typeof row === "object") {
    const occurrenceId = row.occurrence_id || row.feature_occurrence_id || row.insight_id || row.record_id;
    if (occurrenceId) card.dataset.occurrenceId = String(occurrenceId);
    const level = row.cl ?? row.acquisition_cl ?? row.acquired_at_character_cl ?? row.acquired_at_path_level ?? row.path_level;
    if (level !== undefined && level !== null) card.dataset.characterLevel = String(level);
    const eventId = row.event_id || row.acquisition_event_id || row.acquisition_event?.event_id;
    if (eventId) card.dataset.eventId = String(eventId);
  }
  const header = gmEl("header", "owner-record-header");
  header.appendChild(gmEl("h5", null, heading));
  const badgeRow = gmEl("div", "owner-record-badges");
  for (const badge of badges) {
    const rendered = ownerReadableValue(badge) || ownerSheetRunnableName(badge);
    if (rendered && !OWNER_TECHNICAL_VALUE.test(rendered)) badgeRow.appendChild(gmBadge(rendered));
  }
  if (badgeRow.childElementCount) header.appendChild(badgeRow);
  card.appendChild(header);
  const rulesText = ownerSheetRunnableName(rules);
  let summaryText = ownerSheetRunnableName(summary);
  // A summary that is just the opening of the rules text would print the same
  // sentence twice.
  if (summaryText && rulesText && rulesText.replace(/\s+/g, " ").startsWith(summaryText.replace(/\s+/g, " ").replace(/…$/, ""))) summaryText = "";
  if (summaryText) card.appendChild(gmEl("p", "gm-card-summary", summaryText));
  const factLines = facts.map(entry => ownerReadableValue(entry) || ownerSheetRunnableName(entry))
    .filter(entry => entry && !OWNER_TECHNICAL_VALUE.test(entry));
  if (factLines.length) card.appendChild(gmEl("p", "gm-complete-facts", factLines.join(" · ")));
  if (rulesText && rulesText !== summaryText) card.appendChild(gmEl("p", "owner-sheet-rules-text", rulesText));
  // A lineage Manual teaches its Recorded Arts through inherited access.  Show
  // each child's technique, Sphere and learning DC inline, because a Manual is
  // only meaningful through what it grants.
  if (row && Array.isArray(row.recorded_arts) && row.recorded_arts.length) {
    const list = gmEl("ul", "owner-manual-arts");
    for (const art of row.recorded_arts) {
      if (!art || typeof art !== "object") continue;
      const technique = ownerSheetRunnableName(art.technique_name) || ownerSheetRunnableName(art.display_name) || "Recorded Art";
      // The art carries Sphere record ids; fall back to the readable tail of the
      // id rather than inventing a display name for it.
      const sphereNames = Array.isArray(art.associated_sphere_record_ids)
        ? art.associated_sphere_record_ids
            .map(id => ownerSheetRunnableName(String(id).split(".").pop().replace(/_/g, " ")))
            .filter(Boolean)
        : [];
      const dcText = ownerLearningDcText(art.learning_dc);
      // An exact_named_talent expression is the printed Talent itself, taught
      // by the book; say so plainly instead of showing the internal kind.
      const sphereLabel = sphereNames.map(name => name.replace(/\b\w/g, ch => ch.toUpperCase())).join(" / ");
      const kind = String(art.expression_kind || "");
      const teaches = kind === "exact_named_talent"
        ? `Recorded Art of the ${sphereLabel ? `${sphereLabel} ` : ""}Talent`
        : [sphereLabel, ownerReadableValue(kind)].filter(Boolean).join(" · ");
      const bits = [teaches, dcText ? `Learning ${dcText}` : ""]
        .filter(entry => entry && !OWNER_TECHNICAL_VALUE.test(String(entry)));
      const item = gmEl("li", "owner-manual-art");
      item.appendChild(gmEl("strong", null, technique));
      if (bits.length) item.appendChild(gmEl("span", "owner-manual-art-meta", ` — ${bits.join(" · ")}`));
      const block = ((art.execution_derivation || {}).source_block);
      const blockText = ownerSheetRunnableName(block);
      if (blockText) {
        // Full printed rules, nested under the art so the Manual list stays
        // compact (owner 2026-09-23: descriptions were cut off mid-effect).
        const full = ownerHumanLines(blockText, {max: 200}) || blockText;
        const preview = full.length > 220 ? `${full.slice(0, 220).replace(/\s+\S*$/, "")}…` : full;
        if (full === preview) {
          item.appendChild(gmEl("p", "owner-manual-art-block", full));
        } else {
          const details = document.createElement("details");
          details.className = "owner-manual-art-rules";
          const summary = document.createElement("summary");
          summary.textContent = preview;
          details.append(summary, gmEl("p", "owner-manual-art-block", full));
          item.appendChild(details);
        }
      }
      list.appendChild(item);
    }
    if (list.childElementCount) card.appendChild(list);
  }
  return card;
}

function ownerSheetCardGrid(cards) {
  const grid = gmEl("div", "owner-sheet-card-grid");
  for (const card of cards) if (card) grid.appendChild(card);
  return grid;
}

function ownerSheetSection(title, content, {subtitle = null, extraClass = ""} = {}) {
  const section = gmEl("section", `owner-sheet-section${extraClass ? ` ${extraClass}` : ""}`);
  section.appendChild(gmEl("h4", "owner-sheet-section-heading", title));
  const rendered = ownerSheetRunnableName(subtitle);
  if (rendered) section.appendChild(gmEl("p", "owner-sheet-section-subtitle", rendered));
  if (content) section.appendChild(content);
  return section;
}

function ownerSheetCountedGrid(count, noun, cards, {empty = null} = {}) {
  if (cards.length) return ownerSheetCardGrid(cards);
  const message = ownerSheetRunnableName(empty) || `No ${noun} recorded.`;
  return gmEl("p", "gm-muted owner-sheet-empty", message);
}

function ownerSheetRoutesFor(context, recordId) {
  const talent = context.talentIndex.get(String(recordId));
  if (talent) return talent.acquisition_route;
  const sphere = context.sphereIndex.get(String(recordId));
  return sphere ? sphere.acquisition_route : "";
}

// The locked source block opens with its own printed heading and carries the
// Factory's routing bookkeeping.  Both stay in the Technical disclosure; a
// human card shows the rules paragraph only.
const OWNER_SOURCE_HEADING = /^#{1,6}\s+/;
const OWNER_FACTORY_BOOKKEEPING = /^\s*Factory (Combat Bucket|Routing)\s*:/i;

function ownerSourceHeading(text) {
  const raw = ownerSheetRunnableName(text);
  if (!raw) return "";
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (OWNER_SOURCE_HEADING.test(trimmed)) return trimmed.replace(OWNER_SOURCE_HEADING, "").trim();
    return "";
  }
  return "";
}

// The printed blocks repeat a line now and then; a card does not need it twice.
function ownerDropRepeatedLines(text) {
  const kept = [];
  const exact = new Set();
  const labels = new Set();
  for (const line of String(text || "").split("\n")) {
    const key = line.trim();
    if (!key) { kept.push(line); continue; }
    if (exact.has(key)) continue;
    exact.add(key);
    // A label that already opened a line ("Prerequisite:") should not open a
    // second one, even when the remainder differs; the second is the duplicate
    // the generated blocks carry.
    const label = (/^([A-Za-z][A-Za-z \/]{2,30}):/.exec(key) || [])[1];
    if (label) {
      const labelKey = label.toLowerCase();
      if (labels.has(labelKey)) continue;
      labels.add(labelKey);
    }
    kept.push(line);
  }
  return kept.join("\n");
}

// Source text arrives with light markdown.  A card shows the words, not the
// punctuation: bold/italic runs, inline code ticks and heading hashes go.
function ownerStripMarkdown(text) {
  return String(text || "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(^|\s)\*(\S[^*]*?)\*(?=\s|$)/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .trim();
}

function ownerStripSourceChrome(text) {
  const raw = ownerSheetRunnableName(text);
  if (!raw) return "";
  const kept = [];
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (OWNER_SOURCE_HEADING.test(trimmed)) continue;
    if (OWNER_FACTORY_BOOKKEEPING.test(trimmed)) continue;
    // The Factory's bucket/routing words also appear mid-line in generated
    // text; remove them there too.
    const cleaned = line.replace(/\s*Factory (?:Combat Bucket|Routing)\s*:[^\n]*?(?=\s{2,}|$)/g, "").trimEnd();
    kept.push(cleaned);
  }
  return ownerBareSourceText(kept.join("\n")).replace(/^\s*\n+/, "").trim();
}

// Pipe tables in the printed source become readable rows; a raw "| a | b |"
// line is not something a human reads in a card.
function ownerRenderTableRows(lines) {
  const rendered = [];
  let header = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!/^\|.*\|$/.test(line)) { rendered.push(raw); header = null; continue; }
    const cells = line.split("|").slice(1, -1).map(c => c.trim());
    if (cells.every(c => /^:?-{2,}:?$/.test(c) || c === "")) continue;
    if (!header) { header = cells; continue; }
    const pairs = cells.map((cell, i) => (header[i] && cell ? `${header[i]} ${cell}` : cell)).filter(Boolean);
    if (pairs.length) rendered.push(pairs.join(": "));
  }
  return rendered;
}

// A printed field can end and the next begin on one line ("Cost: None" then
// "Concentration: Not required" with no separator); give them their own lines.
function ownerSplitMergedFields(text) {
  return String(text || "")
    .replace(/([a-z)\.])(?=(?:Concentration|Factory|Timing|Range|Target|Duration|Cost|Trigger|Area|Limit|Tags|Action Type|Roll\/Save\/Check|DC Basis|Effect|Failure|Counterplay|Cleanup)\s*:)/g, "$1\n")
    .replace(/\n{3,}/g, "\n\n");
}

// Some generated fields quote a whole source block inside a JSON array
// ("Normalized Procedure: [\"## CL9 - Iron Voice ...\"]").  The array's own
// text is written inside quotes, so line-based stripping cannot see it; the
// JSON string literals are unwrapped and de-marked here instead.
function ownerBareSourceText(text) {
  const raw = ownerSheetRunnableName(text);
  if (!raw || !/[\{\[]/.test(raw)) return raw;
  return raw
    .replace(/\[\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*"(?:[^"\\]|\\.)*")*\s*\]/g, (_match, first) => {
      const opened = first.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\t/g, "\t");
      const lines = opened.split(/\r?\n/)
        .filter(line => !OWNER_SOURCE_HEADING.test(line.trim()) && !OWNER_FACTORY_BOOKKEEPING.test(line.trim()))
        .map(line => line.replace(/^\s*\*\*(.+?)\*\*\s*$/, "$1").replace(/\*\*/g, ""));
      return lines.join("\n");
    })
    .split(/\r?\n/)
    .filter(line => !OWNER_SOURCE_HEADING.test(line.trim()) && !OWNER_FACTORY_BOOKKEEPING.test(line.trim()))
    .join("\n")
    .replace(/\\n/g, "\n")
    .replace(/\*\*/g, "")
    .trim();
}

function ownerSheetRulesText(row) {
  if (!row || typeof row !== "object") return "";
  for (const key of ["full_description", "player_rules_text", "effective_rules_text", "source_rules_text", "record_text", "description", "summary", "one_line_description"]) {
    const text = ownerSheetRunnableName(row[key]);
    if (text) {
      const cleaned = ownerRenderTableRows(ownerSplitMergedFields(ownerStripSourceChrome(text)).split("\n")).join("\n").trim();
      return ownerStripMarkdown(ownerDropRepeatedLines(cleaned));
    }
  }
  return "";
}

function ownerSheetRulesHeading(row) {
  if (!row || typeof row !== "object") return "";
  for (const key of ["full_description", "player_rules_text", "effective_rules_text", "source_rules_text", "record_text"]) {
    const heading = ownerSourceHeading(row[key]);
    if (heading) return heading;
  }
  return "";
}

function ownerSheetShortText(row) {
  if (!row || typeof row !== "object") return "";
  for (const key of ["summary", "short_description", "description", "one_line_description"]) {
    const raw = ownerSheetRunnableName(row[key]);
    if (!raw) continue;
    const text = ownerStripMarkdown(ownerStripSourceChrome(raw));
    if (!text) continue;
    // A printed rules block is not a one-line summary, and a bare source
    // heading ("#### Crystallize Path") is not a summary either; leave both to
    // `rules` so the card does not print the heading as its description.
    if (text.length > 160 || /\n/.test(text)) continue;
    if (ownerSourceHeading(raw) === text) continue;
    return text;
  }
  return "";
}

// ---------------------------------------------------------------- Overview
// A multi-Path character keeps one pool per Path (Stamina, Qi, Resonance)
// under the primary-resource wrapper; show every pool, not just the first.
function ownerResourcePools(resource) {
  const definitions = Array.isArray(resource?.definitions) && resource.definitions.length ? resource.definitions : [resource];
  return definitions
    .filter(row => row && typeof row === "object" && (row.max ?? row.maximum) !== undefined && (row.max ?? row.maximum) !== null)
    .map(row => ({
      name: ownerSheetRunnableName(row.name) || "Primary resource",
      current: row.current ?? row.build_state_current ?? "?",
      maximum: row.max ?? row.maximum,
    }));
}

function ownerOverviewContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const stats = context.stats || {};
  const ac = stats.armor_class || {};
  const hp = stats.hit_points || {};
  const resource = stats.primary_resource || {};
  const speed = stats.speed || {};
  const currentHp = hp.build_state_current ?? hp.current ?? hp.maximum;
  const speedCard = gmInfoCard("Speed", [
    ...sheetWalkingSpeedLines(speed),
    ownerSheetRunnableName(speed.worn_note),
  ]);
  const pools = ownerResourcePools(resource);
  const resourceCard = pools.length > 1
    ? gmInfoCard("Resources", pools.map(pool => `${pool.name}: ${pool.current} of ${pool.maximum} maximum.`))
    : gmInfoCard(pools[0]?.name || "Primary Resource", [
      pools.length ? `${pools[0].current} of ${pools[0].maximum} maximum.` : "Not recorded.",
    ]);
  const armorSummary = sheetArmorClassSummary(ac);
  const armorCard = gmInfoCard("Armor Class", [
    armorSummary === null ? "Not recorded." : `AC ${armorSummary}.`,
    ownerSheetRunnableName(ac.worn_note),
    ownerSheetRunnableName(ac.calculation),
    ownerSheetRunnableName(ac.conditional_note),
  ]);
  const hpCard = gmInfoCard("Hit Points", [
    hp.maximum === null || hp.maximum === undefined ? "Not recorded." : `${currentHp ?? "?"} of ${hp.maximum} maximum.`,
  ]);
  const offense = gmInfoCard("Attack and save", [
    stats.technique_attack_bonus === null || stats.technique_attack_bonus === undefined ? null : `Attack Bonus ${ownerSigned(stats.technique_attack_bonus)} (technique attack).`,
    stats.technique_save_dc === null || stats.technique_save_dc === undefined ? null : `Save DC ${stats.technique_save_dc} against this character's techniques.`,
    (stats.initiative && Number.isFinite(Number(stats.initiative.bonus))) ? `Initiative ${ownerSigned(stats.initiative.bonus)} (${stats.initiative.ability || "DEX"}).` : null,
  ]);
  content.appendChild(ownerSheetCardGrid([armorCard, hpCard, speedCard]));
  content.appendChild(ownerSheetCardGrid([offense, resourceCard]));

  if (stats.table_adjustment_note) content.appendChild(gmEl("p", "owner-sheet-note", stats.table_adjustment_note));
  const abilities = Array.isArray(stats.abilities) ? stats.abilities : [];
  const proficiency = Number(context.identity.proficiency_bonus);
  if (abilities.length) {
    const grid = gmEl("div", "owner-ability-grid");
    for (const row of abilities) {
      const card = gmEl("article", "owner-ability-card");
      const modifier = Number(row.modifier);
      const recordedSave = (stats.saving_throws || {})[row.ability];
      const declared = (stats.saving_throw_proficiencies || []).includes(row.ability);
      const save = Number.isFinite(recordedSave) ? recordedSave :
        Number.isFinite(modifier) ? modifier + (declared && Number.isFinite(proficiency) ? proficiency : 0) : null;
      card.append(
        gmEl("strong", null, ownerSheetRunnableName(row.ability) || "Ability"),
        gmEl("b", null, row.score === null || row.score === undefined ? "—" : String(row.score)),
        gmEl("span", null, `Mod ${Number.isFinite(modifier) ? ownerSigned(modifier) : "—"}`),
        gmEl("span", null, `Save ${save === null ? "—" : ownerSigned(save)}`),
      );
      grid.appendChild(card);
    }
    content.appendChild(ownerSheetSection(
      "Ability Scores / Saves",
      grid,
      {subtitle: "Saving throws include proficiency only where the character declares it."},
    ));
  }

  const skills = Array.isArray(stats.skills) ? stats.skills : [];
  if (skills.length) {
    const cloud = gmEl("div", "owner-skill-cloud");
    for (const row of skills) {
      const star = row.proficiency === "expertise" ? " **" : row.proficiency ? " *" : "";
      cloud.appendChild(gmEl("span", "owner-skill-chip", `${ownerSheetRunnableName(row.skill) || "Skill"} ${ownerSigned(row.bonus) || "—"}${star}`));
    }
    content.appendChild(ownerSheetSection("Skills", cloud, {subtitle: "* proficient · ** expertise"}));
  }

  // SENSES and DEFENSES appear only when the verified source carries them;
  // this character's payload has neither, and nothing is invented for it.
  const senses = ownerSheetList(stats.senses);
  const defenses = ownerSheetList(stats.defenses);
  if (senses.length || defenses.length) {
    const pair = gmEl("div", "owner-two-card-grid");
    if (senses.length) pair.appendChild(gmInfoCard("Senses", senses));
    if (defenses.length) pair.appendChild(gmInfoCard("Defenses", defenses));
    content.appendChild(pair);
  }

  // The summary strip: one tile per figure, as in the GM Screen viewer.
  const sphereSurface = context.snapshot.spheres_and_talents || {};
  const effectiveCls = (Array.isArray(context.identity.paths) ? context.identity.paths : [])
    .map(path => path.effective_cl)
    .filter(value => value !== null && value !== undefined);
  const summaryTiles = ownerSheetTiles([
    ["Effective CL", effectiveCls.length ? effectiveCls.join(" / ") : context.identity.cultivation_level],
    ["Suppressed rules", (context.snapshot.explicit_none_systems || []).length],
    ["Items", ownerSheetItemCount(context.snapshot.equipment)],
    ["Active companions", ownerSheetList(context.surfaceData("companions")?.companions).length],
    ["Selected insights", (sphereSurface.cultivation_insight_record_ids || []).length],
    ["Immortal Arts", Array.isArray(context.snapshot.immortal_arts) ? context.snapshot.immortal_arts.length : 0],
  ]);
  content.appendChild(ownerSheetSection("Summary", summaryTiles));
  return content;
}

// A starting-kit row counts its carried items; any other row is one item.
function ownerSheetItemCount(equipment) {
  return (Array.isArray(equipment) ? equipment : []).reduce((total, row) => {
    const kitItems = row?.starting_kit?.items;
    const kit = row?.starting_kit || {};
    const bought = kit.resolved_treasure_purchases || {};
    const treasures = (kit.resolved_treasure_weapon ? 1 : 0) + (kit.resolved_treasure_armor ? 1 : 0)
      + (Array.isArray(bought.wondrous) ? bought.wondrous.length : 0) + (Array.isArray(bought.consumables) ? bought.consumables.length : 0);
    return total + (Array.isArray(kitItems) ? kitItems.length + treasures : 1);
  }, 0);
}

// ------------------------------------------------------- Leveling Ledger
function ownerRuleLinkItem(name, detail, tabId, recordId) {
  const item = gmEl("li", "owner-rule-link-item");
  item.appendChild(gmEl("strong", null, name));
  if (ownerSheetRunnableName(detail)) item.appendChild(gmEl("span", "owner-action-origin", ` ${detail}`));
  if (recordId) {
    const link = gmEl("button", "owner-action-rule-link", "Rules ↗");
    link.type = "button";
    link.addEventListener("click", () => ownerOpenRuleCard(tabId, String(recordId)));
    item.appendChild(link);
  }
  return item;
}

function ownerRuleLinkList(items) {
  const list = gmEl("ul", "owner-rule-link-list");
  for (const item of items) if (item) list.appendChild(item);
  return list;
}

// Entry point to the table sheet's Grow tab (change scores, learn talents and Spheres, forge techniques).
// Shown only for finalized characters that have a Factory project id.
function ownerGrowEntry(projectId) {
  const box = gmEl("section", "owner-grow-entry");
  const button = gmEl("button", "owner-grow-entry-button", "Change or level up this character");
  button.type = "button";
  box.appendChild(button);
  box.appendChild(gmEl("p", "owner-grow-entry-note", "Opens the Grow page: change ability scores, learn talents and Spheres, forge techniques. No fight needed."));
  button.addEventListener("click", () => {
    const url = `/tabletop/sheet?project=${encodeURIComponent(projectId)}&tab=grow`;
    const popup = window.open(url, `tt-sheet-${projectId}`, "popup=yes,width=1280,height=860");
    if (!popup) box.appendChild(gmEl("p", "owner-grow-entry-note", "Your browser blocked the pop-up; allow pop-ups for this page."));
  });
  return box;
}

function ownerLevelingContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const growProjectId = context.sheet?.project_id;
  if (context.sheet?.build_status === "CHARACTER_SHEET_READY" && growProjectId) content.appendChild(ownerGrowEntry(growProjectId));
  const levels = Array.isArray(context.surfaceData("leveling")?.levels) ? context.surfaceData("leveling").levels : [];
  const table = gmEl("div", "owner-level-ledger");
  let previous = null;
  levels.forEach((level, index) => {
    const row = gmEl("article", "owner-level-row");
    row.dataset.levelRow = String(index + 1);
    if (level.cl !== undefined && level.cl !== null) row.dataset.characterLevel = String(level.cl);
    const heading = gmEl("header", "owner-level-heading");
    heading.appendChild(gmEl("h5", null, `CL ${level.cl ?? index + 1}`));
    const badges = gmEl("div", "owner-record-badges");
    const levelResource = ownerReadableValue(level.resource) || ownerReadableValue(level.resource_max);
    const levelHp = ownerReadableValue(level.hp);
    for (const badge of [level.realm, level.pb === undefined || level.pb === null ? null : `PB ${ownerSigned(level.pb)}`, levelResource ? `Resource ${levelResource}` : null, levelHp ? `HP ${levelHp}` : null]) {
      const rendered = ownerSheetRunnableName(badge);
      if (rendered) badges.appendChild(gmBadge(rendered));
    }
    if (badges.childElementCount) heading.appendChild(badges);
    row.appendChild(heading);

    const facts = [];
    const after = level.ability_scores_after && typeof level.ability_scores_after === "object" ? level.ability_scores_after : null;
    if (after && previous) {
      const changes = [];
      for (const key of Object.keys(after)) {
        const before = Number(previous[key]);
        const now = Number(after[key]);
        if (Number.isFinite(before) && Number.isFinite(now) && now !== before) changes.push(`${key} ${before} → ${now}`);
      }
      if (changes.length) facts.push(`Ability changes: ${changes.join(", ")}`);
    } else if (Array.isArray(level.deltas) && level.deltas.length) {
      facts.push(`Ability changes: ${level.deltas.map(delta => `${delta.ability || "Ability"} ${ownerSigned(delta.amount)}`).join(", ")}`);
    }
    const trained = Array.isArray(level.trained_choices) ? level.trained_choices : [];
    if (trained.length) {
      facts.push(`Trained choices: ${trained.map(choice => {
        const name = context.nameFor(choice.choice_id || choice.record_id || choice.talent_id || choice.sphere_id);
        const kind = choice.choice_type === "new_sphere" ? "new Sphere" : "Talent";
        return `${name || kind}${Number.isInteger(choice.slot) ? ` (slot ${choice.slot})` : ""}`;
      }).join(", ")}`);
    }
    if (facts.length) row.appendChild(gmEl("p", "gm-complete-facts", facts.join(" · ")));

    // Owner 2026-09-23: rules appear once (Spheres & Talents, Paths); the
    // ledger names what each level granted and links to those rules.
    const gainedCards = [];
    for (const id of level.talent_record_ids_gained || []) {
      const recordId = String(id);
      const talent = context.talentIndex.get(recordId) || {};
      gainedCards.push(ownerRuleLinkItem(context.nameFor(recordId) || "Talent", ownerAcquisitionLabel(context, talent.acquisition_route || ownerSheetRoutesFor(context, recordId)), "spheres_talents", recordId));
    }
    if (gainedCards.length) {
      row.appendChild(ownerSheetSection("Talents gained", ownerRuleLinkList(gainedCards)));
    }

    const occurrences = Array.isArray(level.earned_feature_occurrences) ? level.earned_feature_occurrences : [];
    if (occurrences.length) {
      const items = occurrences.map(occurrence => {
        const name = ownerSheetRunnableName(occurrence.display_name || occurrence.feature_name || occurrence.name) || context.nameFor(occurrence.record_id || occurrence.feature_record_id) || "Earned feature";
        const pathName = ownerSheetRunnableName(occurrence.owner_path_name || occurrence.path_display_name);
        const where = [pathName, occurrence.acquired_at_path_level === undefined || occurrence.acquired_at_path_level === null ? null : `Path level ${occurrence.acquired_at_path_level}`].filter(Boolean).join(" · ");
        return ownerRuleLinkItem(name, where, "paths_subpaths", occurrence.occurrence_id || occurrence.feature_occurrence_id || occurrence.record_id);
      });
      row.appendChild(ownerSheetSection("Features gained", ownerRuleLinkList(items)));
    }
    if (!gainedCards.length && !occurrences.length) {
      row.appendChild(gmEl("p", "gm-muted owner-sheet-empty", "No Talent or Path feature was granted at this level."));
    }
    table.appendChild(row);
    previous = after || previous;
  });
  if (levels.length) content.appendChild(table);
  else content.appendChild(gmEl("p", "gm-muted owner-sheet-empty", "No leveling ledger rows were recorded."));
  return content;
}

// ------------------------------------------------- Background & Origin
function ownerBackgroundContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("background") || {};
  const origin = surface.background_origin || {};
  const background = origin.background || {};
  const insight = origin.origin_insight || {};
  const identity = context.identity || {};

  const summaryText = ownerSheetRunnableName(background.summary);
  content.appendChild(gmInfoCard(ownerSheetRunnableName(background.name) || "Background", [
    summaryText ? summaryText.split("\n").filter(line => line.trim() && !line.trim().startsWith("#")).slice(0, 3).join(" ") : null,
  ]));

  content.appendChild(gmInfoCard("Proficiencies granted", [
    ownerSheetList(background.skill_proficiencies).length ? `Skills: ${ownerSheetList(background.skill_proficiencies).join(", ")}` : null,
    ownerSheetList(background.tool_proficiencies).length ? `Tools: ${ownerSheetList(background.tool_proficiencies).join(", ")}` : null,
    ownerSheetList(background.languages).length ? `Languages: ${ownerSheetList(background.languages).join(", ")}` : null,
  ]));

  const abilityChange = background.ability_score_change;
  const changeLines = [];
  if (Array.isArray(abilityChange)) {
    for (const row of abilityChange) changeLines.push(`${row.ability || "Ability"} ${ownerSigned(row.amount ?? row.value ?? 0)}`);
  } else if (abilityChange && typeof abilityChange === "object") {
    for (const [key, value] of Object.entries(abilityChange)) if (ownerSheetRunnableName(value)) changeLines.push(`${key} ${ownerSigned(value) || value}`);
  }
  if (changeLines.length) content.appendChild(gmInfoCard("Ability score change", changeLines));

  const backgroundTalentId = origin.background_talent_record_id || background.background_talent_id;
  const backgroundTalent = backgroundTalentId ? context.talentIndex.get(String(backgroundTalentId)) || {} : {};
  const sphereCard = gmInfoCard("Background Sphere", [
    ownerSheetRunnableName(background.background_sphere) || ownerSheetRunnableName(origin.background_sphere_name) || "Not recorded.",
  ]);
  const talentCard = ownerSheetRecordCard(backgroundTalent, {
    title: ownerSheetRunnableName(background.background_talent) || context.nameFor(backgroundTalentId) || "Background Talent",
    badges: [ownerAcquisitionLabel(context, backgroundTalent.acquisition_route || "background_talent_acquisition")],
    summary: ownerSheetShortText(backgroundTalent),
    rules: ownerSheetRulesText(backgroundTalent),
    fallback: "Background Talent",
  });
  content.appendChild(ownerSheetCardGrid([sphereCard, talentCard]));

  const grantedType = insight.selected_skill ? "Skill"
    : insight.selected_tool ? "Tool"
    : insight.selected_trade ? "Trade"
    : insight.selected_language ? "Language"
    : "";
  const grantedValue = insight.selected_skill || insight.selected_tool || insight.selected_trade || insight.selected_language || "";
  const grantLine = grantedType
    ? `${grantedType}: ${grantedValue}${insight.result ? ` (${ownerSheetRunnableName(insight.result)})` : ""}`
    : "No typed grant was recorded for this Origin Insight.";
  content.appendChild(gmInfoCard(ownerSheetRunnableName(insight.name) || "Origin Insight", [
    grantLine,
    ownerSheetRunnableName(insight.summary),
    ownerSheetList(insight.tool_expertise).length ? `Tool expertise: ${ownerSheetList(insight.tool_expertise).join(", ")}` : null,
  ]));

  const deception = origin.deception_expertise_result;
  if (deception && (deception.selected_skill || deception.result)) {
    content.appendChild(gmInfoCard("Additional typed grant", [
      `${deception.selected_skill || "Grant"} (${ownerSheetRunnableName(deception.result) || "granted"})`,
    ]));
  }
  content.appendChild(gmInfoCard("Identity", [
    `Name: ${ownerSheetRunnableName(identity.display_name) || "Unnamed character"}`,
    ownerSheetRunnableName(identity.title) ? `Title: ${ownerSheetRunnableName(identity.title)}` : null,
    ownerSheetRunnableName(identity.concept),
    `Realm: ${ownerSheetRunnableName(identity.realm_display || identity.realm) || "not recorded"} · CL ${identity.cultivation_level ?? "?"} · Key ability ${ownerSheetRunnableName(identity.key_ability) || "not recorded"}`,
  ]));
  return content;
}

// ------------------------------------------------- Paths & Subpaths
function ownerPathsContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("paths_subpaths") || {};
  const snapshotPath = context.snapshot.path_and_subpath || {};
  const pathRows = Array.isArray(snapshotPath.paths) && snapshotPath.paths.length
    ? snapshotPath.paths
    : (Array.isArray(surface.path) ? surface.path : []);
  const subpathRows = Array.isArray(snapshotPath.subpaths) && snapshotPath.subpaths.length
    ? snapshotPath.subpaths
    : (Array.isArray(surface.subpaths) ? surface.subpaths : []);

  const pathCards = pathRows.map(row => ownerSheetRecordCard(row, {
    title: ownerSheetRunnableName(row.display_name || row.name),
    badges: [
      row.effective_cl === undefined || row.effective_cl === null ? null : `Effective CL ${row.effective_cl}`,
      ownerSheetRunnableName(row.key_ability) ? `Key ability ${row.key_ability}` : null,
    ],
    facts: ownerSheetList(row.selected_skills).length ? [`Skills: ${ownerSheetList(row.selected_skills).join(", ")}`] : [],
    fallback: "Path",
  }));
  content.appendChild(ownerSheetSection("Paths", ownerSheetCountedGrid(pathCards.length, "Paths", pathCards, {empty: "No Path is recorded."})));

  const subpathCards = subpathRows.map(row => ownerSheetRecordCard(row, {
    title: ownerSheetRunnableName(row.display_name || row.name || row.subpath_name),
    badges: [row.selected_at_cl === undefined || row.selected_at_cl === null ? null : `Selected at CL ${row.selected_at_cl}`],
    facts: [ownerSheetRunnableName(row.owning_path_name || row.path_display_name) ? `Path: ${row.owning_path_name || row.path_display_name}` : null],
    fallback: "Subpath",
  }));
  content.appendChild(ownerSheetSection("Subpaths", ownerSheetCountedGrid(subpathCards.length, "Subpaths", subpathCards, {empty: "No Subpath is recorded."})));

  const occurrences = Array.isArray(snapshotPath.earned_feature_occurrences)
    ? snapshotPath.earned_feature_occurrences
    : (Array.isArray(surface.earned_feature_occurrences) ? surface.earned_feature_occurrences : []);
  const byPath = new Map();
  for (const occurrence of occurrences) {
    const pathName = ownerSheetRunnableName(occurrence.owner_path_name || occurrence.path_display_name || occurrence.path_name)
      || context.nameFor(occurrence.owning_path_id || occurrence.parent_record_id)
      || "Path features";
    if (!byPath.has(pathName)) byPath.set(pathName, []);
    byPath.get(pathName).push(occurrence);
  }
  const printedRules = new Map();
  for (const [pathName, rows] of [...byPath.entries()].sort((left, right) => left[0].localeCompare(right[0]))) {
    rows.sort((left, right) => Number(left.acquired_at_path_level ?? 0) - Number(right.acquired_at_path_level ?? 0));
    const cards = rows.map(occurrence => {
      // Rules print once per sheet; a repeated feature (each ASI milestone,
      // the same feature on another Path) points back to the first copy.
      const rules = ownerSheetRulesText(occurrence);
      const firstCopy = rules ? printedRules.get(rules) : null;
      if (rules && !firstCopy) printedRules.set(rules, `${ownerSheetRunnableName(occurrence.display_name) || "this feature"} (${pathName})`);
      const card = ownerSheetRecordCard(occurrence, {
        fallback: "Earned feature",
        facts: [ownerFeatureSelectionText(occurrence.selection), firstCopy ? `Rules: see ${firstCopy} above.` : null],
        summary: firstCopy ? null : ownerSheetShortText(occurrence),
        rules: firstCopy ? null : rules,
      });
      // Owner 2026-09-24: each ability collapses to its name so the page
      // stays navigable; open one to read it.
      const title = card ? card.querySelector(":scope > header h5")?.textContent : "";
      return ownerCollapsible(title || ownerSheetRunnableName(occurrence.display_name) || "Earned feature", [
        occurrence.acquired_at_character_cl === undefined || occurrence.acquired_at_character_cl === null ? null : `CL ${occurrence.acquired_at_character_cl}`,
        occurrence.acquired_at_path_level === undefined || occurrence.acquired_at_path_level === null ? null : `Path level ${occurrence.acquired_at_path_level}`,
      ], [ownerCardBody(card)], {extraClass: "owner-talent-entry"});
    });
    const list = gmEl("div", "owner-talent-list");
    for (const card of cards) list.appendChild(card);
    content.appendChild(ownerCollapsible(pathName, [`${rows.length} ${rows.length === 1 ? "feature" : "features"}`], [list],
      {open: true, extraClass: "owner-sphere-group"}));
  }
  if (!byPath.size) content.appendChild(gmEl("p", "gm-muted owner-sheet-empty", "No earned Path feature was recorded."));
  return content;
}

// What the character chose at a feature: ability increases, or the named pick.
function ownerFeatureSelectionText(selection) {
  if (!selection || typeof selection !== "object") return null;
  const deltas = selection.deltas && typeof selection.deltas === "object" ? Object.entries(selection.deltas) : [];
  if (deltas.length) return `Chosen: ${deltas.map(([ability, value]) => `${ability} ${Number(value) >= 0 ? "+" : ""}${value}`).join(", ")}.`;
  const picked = ownerSheetRunnableName(selection.display_name || selection.selected_name || selection.name);
  return picked ? `Chosen: ${picked}.` : null;
}

// ------------------------------------------------- Spheres & Talents
// Owner 2026-09-24: one collapsible entry per known Sphere, holding its base
// abilities and every Talent of that Sphere; each Talent collapses by name.
function ownerCollapsible(title, badges, bodyNodes, {open = false, extraClass = ""} = {}) {
  const details = document.createElement("details");
  details.className = `owner-collapsible${extraClass ? ` ${extraClass}` : ""}`;
  details.open = open;
  const summary = document.createElement("summary");
  // Some source headings are printed in capitals ("DIRTY TRICK").
  const text = String(title || "");
  const shown = /[a-z]/.test(text) ? text : text.toLowerCase().replace(/(^|[\s(\-—/])(\p{L})/gu, (_m, lead, ch) => lead + ch.toUpperCase());
  summary.appendChild(gmEl("span", "owner-collapsible-title", shown));
  const badgeRow = gmEl("span", "owner-record-badges");
  for (const badge of badges) {
    const rendered = ownerSheetRunnableName(badge);
    if (rendered && !OWNER_TECHNICAL_VALUE.test(rendered)) badgeRow.appendChild(gmBadge(rendered));
  }
  if (badgeRow.childElementCount) summary.appendChild(badgeRow);
  details.appendChild(summary);
  const body = gmEl("div", "owner-collapsible-body");
  for (const node of bodyNodes) if (node) body.appendChild(node);
  details.appendChild(body);
  return details;
}

// The record card's own header would repeat the collapsible's name.
function ownerCardBody(card) {
  if (!card) return null;
  const header = card.querySelector(":scope > header");
  if (header) header.remove();
  return card.childElementCount ? card : null;
}

function ownerSpheresContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const spheres = Array.isArray(context.sphereRows) ? context.sphereRows : [];
  const sphereNameFor = (recordId) => {
    const sphere = context.sphereIndex.get(String(recordId)) || {};
    return ownerSheetRunnableName(sphere.display_name || sphere.name) || context.nameFor(recordId) || "Sphere";
  };
  // The snapshot carries the granted Background Sphere; the complete-character
  // surface for background has been reduced to identity fields.
  const backgroundOrigin = context.surfaceData("background")?.background_origin || {};
  const snapshotBackground = context.snapshot.background_and_origin || {};
  const backgroundTalentId = String(snapshotBackground.background_talent_record_id || backgroundOrigin.background_talent_record_id || "");
  const backgroundSphereName = ownerSheetRunnableName(
    snapshotBackground.background?.background_sphere
    || backgroundOrigin.background?.background_sphere
    || snapshotBackground.background_sphere,
  );
  const sphereNameForTalent = (talent) => {
    const recordId = String(talent.record_id || "");
    const mapped = ownerSheetRunnableName(context.talentSphereNames[recordId]);
    if (mapped) return mapped;
    if (ownerSheetRunnableName(talent.parent_sphere_id)) return sphereNameFor(talent.parent_sphere_id);
    // Last resort: the record id's own sphere token ("TAL_EARTH_..." or
    // "tianxia.talent.earth....").
    const dotted = /^tianxia\.talent\.([a-z0-9_]+)\./.exec(recordId);
    const hit = dotted
      ? context.sphereRows.find(row => String(row.record_id || row.sphere_id || "") === `tianxia.sphere.${dotted[1]}`)
      : (recordId.split("_")[1] ? context.sphereRows.find(row => String(row.record_id || "").toUpperCase().includes(recordId.split("_")[1])) : null);
    return hit ? ownerSheetRunnableName(hit.display_name || hit.name) : "";
  };

  // One group per Sphere name, seeded from the known Spheres so a Sphere with
  // no Talents still appears, then filled with the Talents.
  const groups = new Map();
  const groupFor = (name) => {
    if (!groups.has(name)) groups.set(name, {name, sphere: null, talents: []});
    return groups.get(name);
  };
  for (const sphere of spheres) {
    const name = sphereNameFor(sphere.sphere_id || sphere.record_id || sphere.sphere_record_id);
    const group = groupFor(name);
    if (!group.sphere) group.sphere = sphere;
  }
  const talents = [...context.talentIndex.values()];
  for (const talent of talents) groupFor(sphereNameForTalent(talent) || "Other talents").talents.push(talent);

  const clOf = (row) => (row && row.acquisition_cl !== undefined && row.acquisition_cl !== null ? Number(row.acquisition_cl) : Infinity);
  const firstCl = (group) => Math.min(clOf(group.sphere), ...group.talents.map(clOf));
  // Background Sphere first, then the order the Spheres were learned, then name.
  const order = [...groups.values()].sort((left, right) => {
    if (left.name === "Other talents" || right.name === "Other talents") return left.name === "Other talents" ? 1 : -1;
    if (backgroundSphereName && (left.name === backgroundSphereName) !== (right.name === backgroundSphereName)) {
      return left.name === backgroundSphereName ? -1 : 1;
    }
    return (firstCl(left) - firstCl(right)) || left.name.localeCompare(right.name);
  });

  content.appendChild(gmEl("p", "owner-sheet-section-subtitle",
    `${spheres.length} ${spheres.length === 1 ? "Sphere" : "Spheres"} · ${talents.length} ${talents.length === 1 ? "Talent" : "Talents"}. Open a Sphere to see its base abilities and Talents; open a Talent to read its rules.`));

  for (const group of order) {
    const sphere = group.sphere || {};
    const automatic = sphere.automatic_component_authority && Array.isArray(sphere.automatic_component_authority.components)
      ? sphere.automatic_component_authority.components
      : [];
    const body = [];
    if (group.sphere) {
      if (automatic.length) {
        const list = gmEl("div", "owner-sphere-automatic");
        for (const component of automatic) {
          const name = ownerSheetRunnableName(component.display_name)
            || ownerSourceHeading(component.player_rules_text || component.full_description)
            || context.nameFor(component.component_id)
            || "Automatic ability";
          // Sphere components carry the printed block in player_rules_text; the
          // same chrome stripping, merged-field split and table rendering the
          // other rules text gets must apply here too.
          const source = component.player_rules_text || component.full_description;
          const text = ownerSheetRulesText({ full_description: source }) || ownerSheetRunnableName(component.one_line_description);
          list.appendChild(ownerCollapsible(name, ["Base ability"],
            [text ? gmEl("p", "owner-sheet-rules-text", text) : null], {extraClass: "owner-sphere-component"}));
        }
        body.push(list);
      } else {
        body.push(gmEl("p", "gm-muted owner-sheet-empty", "This Sphere grants no automatic base ability in the verified source."));
      }
    }
    const rows = group.talents.sort((left, right) => (clOf(left) - clOf(right))
      || String(ownerSheetRunnableName(left.display_name)).localeCompare(String(ownerSheetRunnableName(right.display_name))));
    if (rows.length) {
      const list = gmEl("div", "owner-talent-list");
      for (const talent of rows) {
        const isBackgroundTalent = String(talent.record_id) === backgroundTalentId || String(talent.acquisition_route || "").includes("background_talent");
        const card = ownerSheetRecordCard(talent, {
          title: ownerSheetRunnableName(talent.display_name),
          badges: [ownerSheetRunnableName(talent.timing_or_category) || ownerSheetRunnableName(talent.subsection)],
          summary: ownerSheetShortText(talent),
          rules: ownerSheetRulesText(talent),
          fallback: "Talent",
        });
        const title = card ? card.querySelector(":scope > header h5")?.textContent : "";
        list.appendChild(ownerCollapsible(
          title || ownerSheetRunnableName(talent.display_name) || "Talent",
          [
            talent.acquisition_cl === undefined || talent.acquisition_cl === null ? null : `CL ${talent.acquisition_cl}`,
            isBackgroundTalent ? "Background talent" : ownerAcquisitionLabel(context, talent.acquisition_route),
          ],
          [ownerCardBody(card)],
          {extraClass: "owner-talent-entry"},
        ));
      }
      body.push(list);
    }
    const talentWord = `${rows.length} ${rows.length === 1 ? "Talent" : "Talents"}`;
    content.appendChild(ownerCollapsible(group.name, group.sphere
      ? [
          group.name === backgroundSphereName ? "Background Sphere" : ownerAcquisitionLabel(context, sphere.acquisition_route),
          sphere.acquisition_cl === undefined || sphere.acquisition_cl === null ? null : `CL ${sphere.acquisition_cl}`,
          talentWord,
          automatic.length ? `${automatic.length} base ${automatic.length === 1 ? "ability" : "abilities"}` : null,
        ]
      : [talentWord], body, {extraClass: "owner-sphere-group"}));
  }
  if (!order.length) content.appendChild(gmEl("p", "gm-muted owner-sheet-empty", "No Sphere or Talent is recorded."));
  return content;
}

// ---------------------------------------------------------------- Insights
function ownerInsightsContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("insights") || {};
  const ledger = surface["Character_Master_Ledger.json"] || {};
  const occurrences = Array.isArray(ledger.cultivation_insight_occurrences) ? ledger.cultivation_insight_occurrences : [];
  const records = Array.isArray(ledger.insights) ? ledger.insights : [];
  const byId = new Map();
  for (const record of records) {
    const id = record.insight_id || record.record_id;
    if (id) byId.set(String(id), record);
  }
  const cards = [];
  if (occurrences.length) {
    for (const occurrence of occurrences) {
      const recordId = occurrence.insight_id || occurrence.record_id || occurrence.insight_record_id;
      const record = byId.get(String(recordId)) || occurrence;
      const facts = [];
      const ability = occurrence.ability || occurrence.raised_ability || occurrence.ability_raised;
      if (ownerSheetRunnableName(ability)) facts.push(`Raised: ${ownerSheetRunnableName(ability)}`);
      const amount = occurrence.amount ?? occurrence.ability_increase;
      if (amount !== undefined && amount !== null && ownerSheetRunnableName(amount)) facts.push(`Increase: ${ownerSigned(amount) || amount}`);
      const insightRules = ownerSheetRulesText(record) || ownerSheetRulesText(occurrence);
      const card = ownerSheetRecordCard(record, {
        title: ownerSheetRunnableName(record.display_name || record.name),
        badges: [
          occurrence.gained_at_cl !== undefined && occurrence.gained_at_cl !== null ? `Milestone CL ${occurrence.gained_at_cl}` : null,
          occurrence.repeat_index ? `Repeat ${occurrence.repeat_index}` : null,
        ],
        summary: ownerSheetShortText(record),
        rules: insightRules,
        facts,
        fallback: "Insight",
      });
      // The text comes from the shared Insight record, but the card is one
      // acquisition: carry that acquisition's event and level, so a repeat
      // does not claim the first acquisition's identity.
      if (card) {
        const eventId = occurrence.event_id || occurrence.acquisition_event_id || occurrence.acquisition_event?.event_id;
        const level = occurrence.gained_at_cl ?? occurrence.acquisition_cl ?? occurrence.cl;
        if (eventId) card.dataset.eventId = String(eventId); else delete card.dataset.eventId;
        if (level !== undefined && level !== null) card.dataset.characterLevel = String(level); else delete card.dataset.characterLevel;
        if (occurrence.occurrence_id) card.dataset.occurrenceId = String(occurrence.occurrence_id);
      }
      cards.push(card);
    }
  } else {
    for (const record of records) {
      cards.push(ownerSheetRecordCard(record, {
        title: ownerSheetRunnableName(record.display_name || record.name),
        summary: ownerSheetShortText(record),
        rules: ownerSheetRulesText(record),
        fallback: "Insight",
      }));
    }
  }
  content.appendChild(ownerSheetCountedGrid(cards.length, "Insights", cards, {empty: "No cultivation Insight was recorded."}));
  return content;
}

// ----------------------------------------------------------------- Actions
// The Actions tab is the character's player-facing repertoire: every owned
// record that the printed rules make independently usable, plus the authored
// action surface.  Owner definition 2026-09-13: actions and Composite
// Playbooks are different things — a plan must not define the repertoire, and a
// modifier must not be promoted into a standalone action.
const OWNER_ACTION_ORDER = Object.freeze(["Action", "Bonus Action", "Reaction", "Free Action", "Passive"]);

function ownerPrintedActionType(text) {
  const match = /Action Type:\s*([^\n]+)/i.exec(String(text || ""));
  if (!match) return "";
  return ownerSheetRunnableName(match[1].replace(/\*\*/g, "").replace(/\.$/, ""));
}

// Base combat actions are delegated to the 5.5e baseline rather than
// restated.  Tianxia's own combat bootstrap says: "Use normal 5.5e combat
// procedures unless a Tianxia Source Rule changes the case", and "This is a
// compatibility summary, not a reproduction of the 5.5e rulebook"
// (LocalSources/01_core_rules/Tianxia_Combat_Bootstrap_Rules_Reference_v0_1.md
// section 3).  So the repertoire names them and cites the baseline; the rules
// text is not copied here, and a Tianxia Source Rule that changes one of them
// takes precedence.  Buckets follow the bootstrap: action, bonus_action,
// reaction, passive only.
const OWNER_BASE_COMBAT_ACTIONS = Object.freeze([
  {name: "Attack", actionType: "Action", note: "Make one attack with a weapon, natural weapon, or unarmed strike."},
  {name: "Dash", actionType: "Action"},
  {name: "Disengage", actionType: "Action"},
  {name: "Dodge", actionType: "Action"},
  {name: "Help", actionType: "Action"},
  {name: "Hide", actionType: "Action"},
  {name: "Ready", actionType: "Action"},
  {name: "Search", actionType: "Action"},
  {name: "Use an Object", actionType: "Action"},
  {name: "Grapple", actionType: "Action"},
  {name: "Shove", actionType: "Action"},
  {name: "Escape a Grapple", actionType: "Action"},
  {name: "Opportunity Attack", actionType: "Reaction"},
]);

const OWNER_BASE_ACTION_SOURCE = "5.5e baseline (Tianxia combat bootstrap section 3)";

function ownerBaseActionRows() {
  return OWNER_BASE_COMBAT_ACTIONS.map(action => ({
    name: action.name,
    actionType: action.actionType,
    sourceLabel: OWNER_BASE_ACTION_SOURCE,
    note: action.note || "",
    base: true,
  }));
}

function ownerActionRepertoire(context) {
  const sources = [
    ["talents", context.selectedSections.talents, "Talent"],
    ["sphere_automatic_components", context.selectedSections.sphere_automatic_components, "Sphere ability"],
    ["path_features", context.selectedSections.path_features, "Path feature"],
    ["advancement_features", context.selectedSections.advancement_features, "Advancement feature"],
    ["background_talent", context.selectedSections.background_talent, "Background talent"],
  ];
  const rows = [];
  const seen = new Set();
  for (const [kind, list, sourceLabel] of sources) {
    for (const record of Array.isArray(list) ? list : []) {
      if (!record || typeof record !== "object") continue;
      const recordId = String(record.record_id || "");
      if (!recordId || seen.has(recordId)) continue;
      const rawText = ownerSheetRunnableName(record.full_description) || ownerSheetRunnableName(record.player_rules_text);
      const text = ownerSheetRulesText(record);
      const actionType = ownerPrintedActionType(rawText);
      // No printed action type means the rules do not make it independently
      // usable; it is not a modifier promoted to an action.
      if (!actionType) continue;
      seen.add(recordId);
      const rules = text || ownerStripMarkdown(ownerStripSourceChrome(rawText));
      const trigger = (/^Trigger:\s*(.+)$/im.exec(rawText) || [])[1];
      rows.push({
        record,
        recordId,
        name: ownerSheetRunnableName(record.display_name) || context.nameFor(recordId),
        rules,
        actionType,
        sourceLabel,
        sphere: ownerSheetRunnableName((context.sphereIndex.get(String(record.parent_sphere_id || "")) || {}).display_name),
        trigger: ownerSheetRunnableName(trigger),
        text,
      });
    }
  }
  const rank = (row) => {
    const index = OWNER_ACTION_ORDER.findIndex(value => value.toLowerCase() === row.actionType.toLowerCase());
    return index === -1 ? OWNER_ACTION_ORDER.length : index;
  };
  // Base 5.5e actions are part of the character's usable options even though no
  // owned record grants them; they sort after the character's own capabilities
  // inside each bucket so the character's identity leads.
  rows.push(...ownerBaseActionRows());
  rows.sort((left, right) => rank(left) - rank(right)
    || (left.base ? 1 : 0) - (right.base ? 1 : 0)
    || left.name.localeCompare(right.name));
  return rows;
}

// Where each repertoire source's full rules live, so an action row can point
// to them instead of repeating them (owner 2026-09-23: rules appear once).
const OWNER_ACTION_RULE_TABS = Object.freeze({
  "Talent": "spheres_talents",
  "Sphere ability": "spheres_talents",
  "Path feature": "paths_subpaths",
  "Advancement feature": "paths_subpaths",
  "Background talent": "background",
});

function ownerActionField(text, labels) {
  const source = String(text || "");
  for (const label of labels) {
    const match = new RegExp(`^[\\s*_]*${label}[\\s*_]*:[\\s*_]*(.+)$`, "im").exec(source);
    if (match) {
      const value = ownerStripMarkdown(match[1]).replace(/\s+/g, " ").trim();
      if (value) return value;
    }
  }
  return "";
}

function ownerOpenRuleCard(tabId, recordId) {
  const sheetRoot = document.getElementById("ownerCharacterSheet");
  if (!sheetRoot) return;
  const button = sheetRoot.querySelector(`.owner-rail-tab[data-gm-tab="${tabId}"]`) || sheetRoot.querySelector(`[data-gm-tab="${tabId}"]`);
  if (button) button.click();
  const panel = document.getElementById(`gmPanel-${tabId}`);
  const card = panel && recordId ? panel.querySelector(`[data-occurrence-id="${CSS.escape(recordId)}"]`) : null;
  if (card) {
    for (let node = card.parentElement; node && node !== panel; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
    card.scrollIntoView({behavior: "smooth", block: "center"});
    card.classList.add("owner-rule-card-flash");
    setTimeout(() => card.classList.remove("owner-rule-card-flash"), 1800);
  }
}

function ownerActionsContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("actions") || {};
  const authored = Array.isArray(surface.actions) ? surface.actions : [];
  const authoredByRecord = new Map();
  for (const action of authored) {
    if (action && action.record_id && !authoredByRecord.has(String(action.record_id))) authoredByRecord.set(String(action.record_id), action);
  }
  const repertoire = ownerActionRepertoire(context).filter(row => !row.base);
  const base = ownerBaseActionRows();
  if (!repertoire.length) {
    content.appendChild(gmEl("p", "gm-muted owner-sheet-empty", "No owned record carries a printed action type in the verified source."));
  }
  const byType = new Map();
  for (const row of repertoire) {
    if (!byType.has(row.actionType)) byType.set(row.actionType, []);
    byType.get(row.actionType).push(row);
  }
  const order = type => {
    const index = OWNER_ACTION_ORDER.findIndex(value => value.toLowerCase() === type.toLowerCase());
    return index === -1 ? OWNER_ACTION_ORDER.length : index;
  };
  for (const actionType of [...byType.keys()].sort((a, b) => order(a) - order(b))) {
    const table = gmEl("table", "owner-action-table");
    const head = gmEl("tr");
    for (const label of ["Action", "Cost", "Range / Area", "Target", "Duration", "Limit", "Rules"]) head.appendChild(gmEl("th", null, label));
    const thead = gmEl("thead"); thead.appendChild(head); table.appendChild(thead);
    const tbody = gmEl("tbody");
    for (const row of byType.get(actionType)) {
      const raw = ownerSheetRunnableName(row.record?.full_description) || ownerSheetRunnableName(row.record?.player_rules_text) || row.rules || "";
      const authoredRow = authoredByRecord.get(row.recordId);
      let cost = ownerActionField(raw, ["Cost", "Costs"]);
      if (authoredRow && Array.isArray(authoredRow.resource_costs) && authoredRow.resource_costs.length) {
        cost = authoredRow.resource_costs.map(entry => `${ownerReadableValue(entry.amount)} ${ownerReadableValue(entry.resource_name) || context.nameFor(entry.resource_id) || ""}`.trim()).filter(Boolean).join(" · ") || cost;
      }
      const range = ownerReadableValue(authoredRow?.range) || ownerActionField(raw, ["Range", "Area"]);
      const target = ownerReadableValue(authoredRow?.target) || ownerActionField(raw, ["Target", "Targets"]);
      const duration = ownerReadableValue(authoredRow?.duration) || ownerActionField(raw, ["Duration"]);
      const limit = ownerActionField(raw, ["Use Limit", "Uses", "Limit", "Frequency"]);
      const tr = gmEl("tr");
      const nameCell = gmEl("td", "owner-action-name");
      nameCell.appendChild(gmEl("strong", null, row.name));
      const origin = [row.sphere, row.sourceLabel].filter(Boolean).join(" · ");
      if (origin) nameCell.appendChild(gmEl("span", "owner-action-origin", origin));
      if (row.trigger) nameCell.appendChild(gmEl("span", "owner-action-trigger", `Trigger: ${row.trigger}`));
      tr.appendChild(nameCell);
      for (const value of [cost, range, target, duration, limit]) tr.appendChild(gmEl("td", null, value || "—"));
      const ruleCell = gmEl("td");
      const tabId = OWNER_ACTION_RULE_TABS[row.sourceLabel];
      if (tabId) {
        const link = gmEl("button", "owner-action-rule-link", "Rules ↗");
        link.type = "button";
        link.title = `Open the full rules for ${row.name}`;
        link.addEventListener("click", () => ownerOpenRuleCard(tabId, row.recordId));
        ruleCell.appendChild(link);
      }
      tr.appendChild(ruleCell);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    content.appendChild(ownerSheetSection(`${actionType} (${byType.get(actionType).length})`, table));
  }
  if (base.length) {
    content.appendChild(ownerSheetSection(
      "Standard actions",
      gmEl("p", "owner-sheet-empty", `${base.map(row => `${row.name} (${row.actionType})`).join(" · ")} — ${OWNER_BASE_ACTION_SOURCE}. A Tianxia Source Rule replaces the baseline where it names the same action.`),
    ));
  }
  return content;
}

function actionSurfaceStatusLine(surface) {
  const status = ownerSheetRunnableName(surface.status) || "ACTION_SURFACE_PARTIAL";
  if (status === "ACTION_SURFACE_COMPLETE") return "Every repertoire entry has an authored execution record.";
  return "The Factory has not authored a full execution record for every repertoire entry yet, so the cards above carry the printed rules.";
}

// ------------------------------------------------------- Immortal Arts
function ownerImmortalArtPublishedBlock(art) {
  const text = String(art.record_text || "");
  const match = /Published source block[^\n]*\n-----\n([\s\S]*?)\n-----/.exec(text);
  return match ? match[1].trim() : "";
}

function ownerKeyLabel(key) {
  const words = String(key || "").replace(/_/g, " ").trim().replace(/\b(hp|cp|ac|dc|pb)\b/gi, word => word.toUpperCase());
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

// Printed rules keep their line breaks; a trailing rule line is dropped.
function ownerArtRulesText(text, max) {
  const lines = ownerHumanLines(text, {max}) || ownerSheetRunnableName(text);
  return lines ? lines.replace(/\n?-{3,}\s*$/, "").trim() : "";
}

// "Label: value." lines for an effect object, known save outcomes first.
const OWNER_ART_EFFECT_LABELS = {
  binding_save: "", failed_save: "On a failed save", failure_by_5: "Failed by 5 or more",
  successful_save: "On a successful save", immunity: "", counterplay: "Breaking free",
};

function ownerArtEffectLines(effect) {
  if (!effect || typeof effect !== "object") return [];
  const known = Object.keys(OWNER_ART_EFFECT_LABELS).filter(key => key in effect);
  // What the effect does leads; its duration and cleanup follow.
  const trailing = ["duration", "stacking", "cleanup"].filter(key => key in effect);
  const rest = Object.keys(effect).filter(key => !(key in OWNER_ART_EFFECT_LABELS) && !trailing.includes(key));
  const lines = [];
  for (const key of [...known, ...rest, ...trailing]) {
    const value = ownerReadableValue(effect[key]);
    if (!value) continue;
    const label = key in OWNER_ART_EFFECT_LABELS ? OWNER_ART_EFFECT_LABELS[key] : ownerKeyLabel(key);
    lines.push(`${label ? `${label}: ` : ""}${value.replace(/\.$/, "")}.`);
  }
  return lines;
}

// Owner 2026-09-24: an Immortal Art is an existing technique the character
// already has, refined by a Dao Aspect and its factors.  The card names that
// base technique and where it came from, then what modifies it, then the
// finished Art as a rules stat block.
function ownerImmortalArtParts(art) {
  const surface = art.action_surface && typeof art.action_surface === "object" ? art.action_surface : {};
  const application = surface.factor_application && typeof surface.factor_application === "object" ? surface.factor_application : {};
  const effective = application.effective_effect && typeof application.effective_effect === "object" ? application.effective_effect : {};
  const base = effective.base_source_effect || surface.effect || {};
  const refinement = effective.factor_refinement && typeof effective.factor_refinement === "object" ? effective.factor_refinement : {};
  const source = art.source && typeof art.source === "object" ? art.source : {};
  const block = ownerImmortalArtPublishedBlock(art);
  const sourceName = ownerSheetRunnableName(source.display_name)
    || ownerSheetRunnableName((/## (?:CL\d+\s*[-—]\s*)?([^\n]+)/.exec(block) || [])[1])
    || "the source technique";
  const kind = String(source.acquisition?.kind || source.content_type || "");
  const pathName = ownerSheetRunnableName(art.path_name);
  const origin = ownerSheetRunnableName(source.sphere_name)
    ? `${ownerSheetRunnableName(source.sphere_name)} Sphere talent`
    : /path/i.test(kind)
      ? `${pathName ? `${pathName} ` : ""}${/subpath/i.test(kind) ? "Subpath" : "Path"} feature`
      : ownerKeyLabel(kind);
  const gainedCl = source.acquired_at_cl ?? source.acquisition?.acquired_at_cl;
  const aspect = ownerReadableValue(art.dao_aspect?.display_name) || "Dao Aspect";
  const cp = (value) => (value === undefined || value === null ? "" : ` (+${value} CP)`);
  const factors = (Array.isArray(art.factors) ? art.factors : []).map(factor => ({
    name: ownerReadableValue(factor.display_name) || "Factor",
    cp: factor.cp_cost,
    rules: ownerArtRulesText(factor.mechanical_chassis, 40),
  }));

  const breakdown = art.activation_cp_breakdown && typeof art.activation_cp_breakdown === "object" ? art.activation_cp_breakdown : {};
  const costParts = [
    breakdown.base_source_cp ? `${sourceName} ${breakdown.base_source_cp}` : null,
    breakdown.aspect_cp ? `${aspect} ${breakdown.aspect_cp}` : null,
    breakdown.factor_cp ? `factors ${breakdown.factor_cp}` : null,
    breakdown.bridge_cp ? `bridge ${breakdown.bridge_cp}` : null,
  ].filter(Boolean);
  const credit = breakdown.burden_cp_credit ? ` − burdens ${breakdown.burden_cp_credit}` : "";
  const cost = art.activation_cp !== undefined && art.activation_cp !== null
    ? `Cost ${ownerReadableValue(art.activation_cp)} CP${costParts.length > 1 ? ` (${costParts.join(" + ")}${credit})` : ""}`
    : null;
  const stats = [];
  const header = [
    ownerReadableValue(surface.activation) || ownerReadableValue(surface.action_type),
    cost,
    ownerReadableValue(surface.range) ? `Range ${ownerReadableValue(surface.range)}` : null,
    ownerReadableValue(surface.area) ? `Area ${ownerReadableValue(surface.area)}` : null,
    ownerReadableValue(surface.target) ? `Target: ${ownerReadableValue(surface.target)}` : null,
    ownerReadableValue(surface.duration) ? `Duration: ${ownerReadableValue(surface.duration)}` : null,
  ].filter(Boolean);
  if (header.length) stats.push(header.join(" · "));
  if (ownerReadableValue(surface.trigger)) stats.push(`Trigger: ${ownerReadableValue(surface.trigger)}`);
  const saveAbility = (/Saving Throw:\**\s*([A-Za-z]+)/.exec(block) || [])[1];
  const dcBasis = ownerReadableValue(surface.dc_basis);
  const hasDc = dcBasis && !/^none$/i.test(dcBasis);
  if (saveAbility || hasDc) stats.push(`Save: ${[saveAbility, hasDc ? `DC ${dcBasis}` : null].filter(Boolean).join(" — ")}`);
  stats.push(...ownerArtEffectLines(base));
  const added = ownerArtEffectLines(refinement);
  if (added.length) stats.push(`${aspect} adds:\n${added.join("\n")}`);
  for (const burden of Array.isArray(art.burdens) ? art.burdens : []) {
    const text = ownerReadableValue(burden?.display_name) || ownerReadableValue(burden);
    if (text) stats.push(`Burden: ${text}`);
  }
  return {block, sourceName, origin, gainedCl, aspect, aspectCp: art.dao_aspect?.cp_modifier, factors, cp, stats};
}

function ownerImmortalArtsContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("immortal_arts") || {};
  const surfaceArts = Array.isArray(surface.immortal_arts) ? surface.immortal_arts : [];
  // The sheet snapshot keeps each Art's complete action surface (the tab
  // surface is trimmed), so prefer it for the stat block.
  const snapshotArts = Array.isArray(context.snapshot?.immortal_arts) ? context.snapshot.immortal_arts : [];
  const byId = new Map(snapshotArts.filter(art => art && (art.art_id || art.record_id)).map(art => [String(art.art_id || art.record_id), art]));
  const arts = surfaceArts.length
    ? surfaceArts.map(art => byId.get(String(art.art_id || art.record_id || "")) || art)
    : snapshotArts;
  const cards = arts.map(art => {
    const parts = ownerImmortalArtParts(art);
    const card = ownerSheetRecordCard(art, {
      title: ownerSheetRunnableName(art.display_name || art.name),
      badges: [
        art.cl_created === undefined || art.cl_created === null ? null : `Created at CL ${art.cl_created}`,
        ownerReadableValue(art.realm),
      ],
      summary: null,
      rules: null,
      facts: [],
      fallback: "Immortal Art",
    });
    if (!card) return null;
    const section = (label, nodes) => {
      const wrap = gmEl("div", "owner-art-part");
      wrap.appendChild(gmEl("h6", "owner-art-part-label", label));
      for (const node of nodes) if (node) wrap.appendChild(node);
      card.appendChild(wrap);
    };
    const baseLine = `${parts.sourceName}${parts.origin ? ` — ${parts.origin}` : ""}${parts.gainedCl !== undefined && parts.gainedCl !== null ? `, gained at CL ${parts.gainedCl}` : ""}.`;
    section("Base technique", [
      gmEl("p", "owner-sheet-rules-text", baseLine),
      parts.block ? ownerCollapsible(`Printed rules of ${parts.sourceName}`, [],
        [gmEl("p", "owner-sheet-rules-text", ownerArtRulesText(parts.block, 200))]) : null,
    ]);
    section("Modified by", [
      gmEl("p", "owner-sheet-rules-text", `Dao Aspect: ${parts.aspect}${parts.cp(parts.aspectCp)}`),
      ...parts.factors.map(factor => factor.rules
        ? ownerCollapsible(`Factor: ${factor.name}${parts.cp(factor.cp)}`, [], [gmEl("p", "owner-sheet-rules-text", factor.rules)])
        : gmEl("p", "owner-sheet-rules-text", `Factor: ${factor.name}${parts.cp(factor.cp)}`)),
    ]);
    section("The Art", parts.stats.map(line => gmEl("p", "owner-sheet-rules-text", line)));
    return card;
  });
  content.appendChild(ownerSheetCountedGrid(cards.length, "Immortal Arts", cards.filter(Boolean), {empty: "No Immortal Art is recorded."}));
  return content;
}

// ------------------------------------------- Foundation / Method / generic
function ownerSelectedRecord(context, recordId) {
  for (const rows of Object.values(context.selectedSections || {})) {
    for (const row of Array.isArray(rows) ? rows : []) {
      if (row && String(row.record_id || "") === String(recordId || "")) return row;
    }
  }
  return null;
}

// Owner 2026-09-23: the Foundation and Method tabs showed only stage/status.
// The sheet snapshot carries the description, the Foundation's features with
// their printed fields, its resource, and the Method's per-Path mechanics.
// Printed rules text that keeps its own sub-headings (feature names such as
// "#### Blackblood Guard"), which ownerHumanLines deliberately drops.
function ownerPrintedTextNodes(text) {
  const nodes = [];
  let buffer = [];
  const flush = () => {
    const body = ownerStripMarkdown(ownerRenderTableRows(buffer).join("\n")).replace(/\n{3,}/g, "\n\n").trim();
    if (body) nodes.push(gmEl("p", "owner-sheet-rules-text", body));
    buffer = [];
  };
  for (const line of String(text || "").split(/\r?\n/)) {
    const heading = /^(#{2,6})\s+(.+)$/.exec(line.trim());
    if (heading) {
      flush();
      nodes.push(gmEl("h6", `owner-printed-heading owner-printed-heading-${heading[1].length}`, ownerStripMarkdown(heading[2])));
    } else if (/^-{3,}\s*$/.test(line.trim())) {
      flush();
    } else {
      buffer.push(line);
    }
  }
  flush();
  return nodes;
}

// Owner 2026-09-24: the Foundation must explain how it works, so the whole
// published chapter is shown, each part collapsible.
const OWNER_FOUNDATION_OPEN_PARTS = new Set(["What This Foundation Does", "Core Benefits at a Glance", "Foundation Features"]);

function ownerFoundationDetailContent(context, row) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const record = ownerSelectedRecord(context, row.record_id || row.foundation_id) || {};
  const intro = [
    row.stage ? `Stage: ${ownerSheetRunnableName(row.stage)}` : null,
    ownerSheetRunnableName(row.state) ? `State: ${friendlyLabel(row.state)}` : null,
    ownerSheetRunnableName(row.full_description) || ownerSheetRunnableName(record.full_description),
  ].filter(Boolean);
  content.appendChild(gmInfoCard(ownerSheetRunnableName(row.display_name) || "Foundation", intro));
  const chapter = Array.isArray(row.printed_chapter) ? row.printed_chapter : [];
  if (chapter.length) {
    const stage = ownerSheetRunnableName(row.stage);
    for (const part of chapter) {
      const heading = ownerSheetRunnableName(part && part.heading);
      if (!heading) continue;
      content.appendChild(ownerCollapsible(
        heading,
        [heading === "Stage Progression" && stage ? `Current stage: ${stage}` : null],
        ownerPrintedTextNodes(part.text),
        {open: OWNER_FOUNDATION_OPEN_PARTS.has(heading), extraClass: "owner-printed-part"},
      ));
    }
    return content;
  }
  const features = new Map();
  const mechanics = row.mechanics && typeof row.mechanics === "object" ? row.mechanics : {};
  for (const value of Object.values(mechanics)) {
    for (const entry of Array.isArray(value) ? value : []) {
      const name = ownerSheetRunnableName(entry && entry.feature_name);
      const fields = entry && entry.source_fields && typeof entry.source_fields === "object" ? entry.source_fields : null;
      if (!name || !fields || features.has(name)) continue;
      features.set(name, fields);
    }
  }
  const cards = [];
  for (const [name, fields] of features) {
    const order = ["Type", "Trigger", "Range", "Target", "Effect", "Limit", "Counterplay and Boundaries"];
    const lines = order.filter(key => fields[key]).map(key => `${key === "Counterplay and Boundaries" ? "Counterplay" : key}: ${ownerSheetRunnableName(fields[key])}`);
    for (const [key, value] of Object.entries(fields)) if (!order.includes(key) && ownerSheetRunnableName(value)) lines.push(`${key}: ${ownerSheetRunnableName(value)}`);
    const card = gmEl("article", "gm-complete-record-card owner-sheet-record-card");
    card.appendChild(gmEl("h5", null, name));
    for (const line of lines) card.appendChild(gmEl("p", "owner-sheet-rules-text", line));
    cards.push(card);
  }
  if (cards.length) content.appendChild(ownerSheetSection(`Foundation features (${cards.length})`, ownerSheetCardGrid(cards)));
  const resource = row.resource && typeof row.resource === "object" ? row.resource : null;
  if (resource && ownerSheetRunnableName(resource.name)) {
    const lines = [`Maximum: ${ownerReadableValue(resource.maximum)}`];
    for (const rule of Array.isArray(resource.rule_descriptions) ? resource.rule_descriptions : []) {
      if (rule && rule.name && rule.description) lines.push(`${ownerSheetRunnableName(rule.name)}: ${ownerSheetRunnableName(rule.description)}`);
    }
    content.appendChild(gmInfoCard(`Resource: ${ownerSheetRunnableName(resource.name)}`, lines));
  }
  return content;
}

function ownerMethodDetailContent(context, row) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const record = ownerSelectedRecord(context, row.record_id) || {};
  const mechanics = row.mechanics && typeof row.mechanics === "object" ? row.mechanics : {};
  const lines = [
    ownerSheetRunnableName(record.full_description) || ownerSheetRunnableName(record.one_line_description),
    ownerSheetRunnableName(row.state) ? `State: ${friendlyLabel(row.state)}` : null,
    mechanics.activation_min_cl ? `Active from CL ${ownerReadableValue(mechanics.activation_min_cl)}` : null,
  ].filter(Boolean);
  const printed = row.printed_entry && typeof row.printed_entry === "object" ? row.printed_entry : null;
  if (printed && ownerSheetRunnableName(printed.description)) lines[0] = ownerSheetRunnableName(printed.description);
  content.appendChild(gmInfoCard(ownerSheetRunnableName(row.display_name) || "Method", lines));
  // Owner 2026-09-24: the Method's published entry, not only its resource math.
  const labelled = (rows) => (Array.isArray(rows) ? rows : [])
    .map(entry => entry && ownerSheetRunnableName(entry.text) ? `${ownerSheetRunnableName(entry.label)}: ${ownerSheetRunnableName(entry.text)}` : null)
    .filter(Boolean);
  if (printed) {
    const how = labelled(printed.fields);
    if (how.length) content.appendChild(gmInfoCard("How this Method works", how));
    const access = labelled(printed.access);
    if (access.length) content.appendChild(gmInfoCard("Access", access));
    const risks = (Array.isArray(printed.risks) ? printed.risks : []).map(ownerSheetRunnableName).filter(Boolean);
    if (risks.length) content.appendChild(gmInfoCard("Risks and limitations", risks.map(risk => `• ${risk}`)));
    const switching = labelled(printed.switching);
    if (switching.length) {
      content.appendChild(ownerCollapsible("If the character changes Primary Method", [],
        switching.map(line => gmEl("p", "owner-sheet-rules-text", line)), {extraClass: "owner-printed-part"}));
    }
  }
  const profiles = Array.isArray(mechanics.per_path_resource_profiles) ? mechanics.per_path_resource_profiles : [];
  if (profiles.length) {
    content.appendChild(gmInfoCard("Resource effect by Path", profiles.map(profile => {
      const path = friendlyLabel(String(profile.path_id || "").toLowerCase());
      const resource = ownerSheetRunnableName(profile.resource_name) || "resource";
      const text = ownerSheetRunnableName(profile.source_text) || ownerSheetRunnableName(profile.shape_key) || "no modifier";
      // Say what the shape does: the exact change to the pool's maximum.
      const effect = [
        ownerSheetRunnableName(profile.exact_modifier) ? `maximum ${resource} ${profile.exact_modifier}` : null,
        profile.applies_independently === true ? "applied to this pool alone" : null,
        profile.conversion_permitted === false ? "cannot be converted to another pool" : null,
      ].filter(Boolean).join("; ");
      return `${path} — ${resource}: ${text}${effect ? ` (${effect})` : ""}`;
    })));
  }
  return content;
}

function ownerFoundationMethodContent(context, key) {
  const snapshotRow = context.snapshot && context.snapshot[key] && typeof context.snapshot[key] === "object" ? context.snapshot[key] : null;
  if (snapshotRow && snapshotRow.record_id && (key === "foundation" || key === "method")) {
    return key === "foundation" ? ownerFoundationDetailContent(context, snapshotRow) : ownerMethodDetailContent(context, snapshotRow);
  }
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData(key) || {};
  const row = surface[key] || {};
  const facts = [];
  for (const [field, label] of [
    ["display_name", "Name"], ["name", "Name"], ["grade", "Grade"], ["realm", "Realm"], ["status_stage", "Status stage"],
    ["stage", "Stage"], ["resource_shape", "Resource shape"], ["status", "Status"], ["summary", "Summary"],
  ]) {
    const rendered = ownerSheetRunnableName(row[field]);
    if (rendered && rendered !== ownerSheetRunnableName(row.display_name)) facts.push(`${label}: ${rendered}`);
  }
  content.appendChild(gmInfoCard(ownerSheetRunnableName(row.display_name || row.name) || friendlyLabel(key), facts.length ? facts : [surface.none_state ? "Explicitly none in the verified source." : "No detail was recorded."]));
  for (const [field, title] of [
    ["benefits", "Benefits"], ["passive_chassis", "Passive chassis"], ["mechanical_effects", "Mechanical effects"],
    ["applied_math", "Applied math"], ["resource_modifiers", "Resource modifiers"], ["primary_resource_modifiers", "Primary resource modifiers"],
    ["actions_riders", "Actions and riders"], ["fixed_scope", "Fixed scope"], ["suppressed_or_excluded_benefits", "Suppressed benefits"],
    ["foundation_compatibility", "Foundation compatibility"], ["incompatibilities", "Incompatibilities"], ["ai_notes", "AI piloting notes"],
    ["resources_counters", "Resources and counters"],
  ]) {
    const values = ownerSheetList(row[field]);
    if (values.length) content.appendChild(gmInfoCard(title, values));
  }
  const stageMap = row.stage_benefit_map;
  if (stageMap && typeof stageMap === "object" && !Array.isArray(stageMap)) {
    const lines = [];
    for (const [stage, benefits] of Object.entries(stageMap)) {
      const rendered = ownerSheetList(benefits);
      lines.push(`${friendlyLabel(stage)}: ${rendered.length ? rendered.join(" · ") : "no separate benefit recorded"}`);
    }
    if (lines.length) content.appendChild(gmInfoCard("Benefits by attained stage", lines));
  }
  return content;
}

// A Manual is meaningful only through the Recorded Arts it teaches.  The sheet
// carries the arts as their own records plus, where the display overlay ran, a
// nested copy on each Manual. Collect both sources, collapse aliases of the
// same acquisition, and retain distinct acquisition events/levels. The generic
// "selected-record training" bucket rows
// are grouping metadata, not manuals, so they are dropped.
function ownerManualRows(context) {
  const data = context.surfaceData("manuals_recorded_arts") || {};
  // Read the surface's own keys rather than a generic traversal: the GM model
  // holds the Recorded Arts as a flat list and the manuals live in their own
  // document, so a name-based walk loses the parent link that joins them.
  const docs = gmCompleteDocuments(data);
  const manuals = [];
  const arts = [];
  const seenManual = new Set();
  const takeManual = row => {
    if (!row || typeof row !== "object") return;
    const id = String(row.record_id || row.display_name || "");
    if (!id || seenManual.has(id)) return;
    seenManual.add(id);
    manuals.push(row);
  };
  const takeArt = row => {
    if (!row || typeof row !== "object") return;
    if (!row.record_id && !row.display_name) return;
    // An art definition identifies the kind of art; its event and level
    // identify an acquisition. Source packets are optional provenance and
    // must not split aliases of the same acquisition. Treat missing event or
    // level data as compatible, while retaining rows that conflict on either.
    const recordId = String(row.record_id || row.display_name);
    const eventId = String(row.event_id || row.acquisition_event_id || row.level_event_id || "");
    const cl = row.acquisition_cl ?? row.gained_at_cl ?? row.acquired_at_character_cl ?? "";
    const isAlias = arts.some(existing => {
      if (String(existing.record_id || existing.display_name) !== recordId) return false;
      const existingEventId = String(existing.event_id || existing.acquisition_event_id || existing.level_event_id || "");
      const existingCl = existing.acquisition_cl ?? existing.gained_at_cl ?? existing.acquired_at_character_cl ?? "";
      return (!eventId || !existingEventId || eventId === existingEventId)
        && (cl === "" || existingCl === "" || String(cl) === String(existingCl));
    });
    if (isAlias) return;
    arts.push(row);
  };
  for (const doc of docs) {
    for (const key of ["manuals", "martial_manuals"]) {
      for (const row of Array.isArray(doc[key]) ? doc[key] : []) {
        takeManual(row);
        for (const child of Array.isArray(row.recorded_arts) ? row.recorded_arts : []) takeArt(child);
      }
    }
    for (const row of Array.isArray(doc.recorded_arts) ? doc.recorded_arts : []) takeArt(row);
  }
  // Sealed manual rows are the authority for which Manuals exist.
  for (const row of context.selectedSections.manuals || []) {
    if (!row || typeof row !== "object") continue;
    takeManual(row);
    for (const child of Array.isArray(row.recorded_arts) ? row.recorded_arts : []) takeArt(child);
  }
  // Manuals given at the table (Tabik's Clearsight manual): the sealed package is never rewritten, so the server
  // lists them beside it (combat/tabletop_service.py table_manuals); their Recorded Arts are learned in fights.
  const tableManuals = context.sheet && Array.isArray(context.sheet.table_manuals) ? context.sheet.table_manuals : [];
  for (const row of tableManuals) {
    takeManual(row);
    for (const child of Array.isArray(row.recorded_arts) ? row.recorded_arts : []) takeArt(child);
  }
  const artsByParent = new Map();
  for (const art of arts) {
    const parent = art && art.parent_manual_record_id;
    if (typeof parent !== "string" || !parent) continue;
    if (!artsByParent.has(parent)) artsByParent.set(parent, []);
    artsByParent.get(parent).push(art);
  }
  return {manuals, arts, artsByParent};
}

function ownerManualsAndArtsContent(context) {
  const {manuals, arts, artsByParent} = ownerManualRows(context);
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  if (manuals.length) {
    const cards = manuals.map(manual => ownerRecordSurfaceCard(
      context, manual, artsByParent.get(String(manual.record_id || "")) || null));
    content.appendChild(ownerSheetSection(`Lineage Manuals (${cards.length})`, ownerSheetCardGrid(cards)));
  }
  if (arts.length) {
    const cards = arts.map(art => ownerRecordSurfaceCard(context, art));
    content.appendChild(ownerSheetSection(`Recorded Arts (${cards.length})`, ownerSheetCardGrid(cards)));
  }
  if (!manuals.length && !arts.length) {
    content.appendChild(ownerSheetSection("Manuals and Recorded Arts",
      gmEl("p", "owner-sheet-empty", "No Manual or Recorded Art is recorded.")));
  }
  return content;
}

// A Recorded Art's learning DC is 10 + its access difficulty, +2 for each
// other Art learned at the same CL; the record stores only the difficulty.
function ownerLearningDcText(dc) {
  if (!dc || typeof dc !== "object") return "";
  const fixed = ownerReadableValue(dc.computed_dc) || ownerReadableValue(dc.value);
  if (fixed) return `DC ${fixed}`;
  const difficulty = Number(dc.difficulty);
  if (dc.mode === "difficulty_formula" && Number.isFinite(difficulty)) return `DC ${10 + difficulty} (+2 for each other Art learned at the same CL)`;
  return ownerReadableValue(dc.difficulty) ? `difficulty ${ownerReadableValue(dc.difficulty)}` : "";
}

function ownerRecordSurfaceCard(context, row, children = null) {
  if (!row || typeof row !== "object") return null;
  const facts = [];
  const artFacts = [];
  if (row.technique_name) artFacts.push(`Technique: ${ownerSheetRunnableName(row.technique_name)}`);
  if (Array.isArray(row.associated_sphere_record_ids) && row.associated_sphere_record_ids.length) {
    artFacts.push(`Sphere: ${row.associated_sphere_record_ids
      .map(id => ownerSheetRunnableName(String(id).split(".").pop().replace(/_/g, " "))).filter(Boolean).join(" / ")}`);
  }
  const dcText = ownerLearningDcText(row.learning_dc);
  if (dcText) artFacts.push(`Learning ${dcText}`);
  const study = row.study_time || {};
  if (ownerReadableValue(study.value)) artFacts.push(`Study ${ownerReadableValue(study.value)} days`);
  if (ownerReadableValue(row.expression_kind)) artFacts.push(`Expression: ${ownerReadableValue(row.expression_kind)}`);
  for (const key of ["state", "status", "learned_at_cl", "minimum_cl", "access_category"]) {
    const rendered = ownerSheetRunnableName(row[key]);
    if (rendered) facts.push(`${friendlyLabel(key)}: ${rendered}`);
  }
  let rules = ownerSheetRulesText(row);
  const blockText = ownerSheetRunnableName((row.execution_derivation || {}).source_block);
  if (blockText) rules = ownerHumanLines(blockText, {max: 10}) || rules;
  return ownerSheetRecordCard(row, {
    title: ownerSheetRunnableName(row.display_name || row.name),
    badges: [ownerSheetRunnableName(row.content_type || row.type || row.kind), ownerSheetRunnableName(row.state || row.status)],
    summary: ownerSheetShortText(row),
    facts: [...facts, ...artFacts],
    rules,
    fallback: "Manual or Recorded Art",
    children,
  });
}

function ownerRecordSurfaceContent(context, {surfaceIds = [], keys = [], title, empty, badgeKeys = [], rulesKeys = [], fallback = "Recorded detail"} = {}) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const documents = [];
  for (const surfaceId of surfaceIds) {
    const data = context.surfaceData(surfaceId);
    documents.push(...gmCompleteDocuments(data));
  }
  const rows = gmCompleteRows(documents, keys, {nested: true, objects: false, dedupe: true, identity: "record"});
  const cards = rows.map(row => {
    const facts = [];
    for (const key of badgeKeys) {
      const rendered = ownerSheetRunnableName(row[key]);
      if (rendered && rendered !== ownerSheetRunnableName(row.display_name || row.name)) facts.push(`${friendlyLabel(key)}: ${rendered}`);
    }
    let rules = rulesKeys.map(key => ownerSheetRunnableName(row[key])).find(Boolean) || ownerSheetRulesText(row);
    // A Recorded Art's printed rules are the exact quoted source block, not the
    // one-line "fixed expression" summary that lands in full_description.
    const artBlock = row && row.execution_derivation && row.execution_derivation.source_block;
    const artBlockText = ownerSheetRunnableName(artBlock);
    if (artBlockText) rules = ownerHumanLines(artBlockText, {max: 8}) || rules;
    // Technique, Sphere and learning DC are the facts that make an art usable.
    const artFacts = [];
    if (row && row.technique_name) artFacts.push(`Technique: ${ownerSheetRunnableName(row.technique_name)}`);
    if (row && Array.isArray(row.associated_sphere_record_ids) && row.associated_sphere_record_ids.length) {
      artFacts.push(`Sphere: ${row.associated_sphere_record_ids
        .map(id => ownerSheetRunnableName(String(id).split(".").pop().replace(/_/g, " "))).filter(Boolean).join(" / ")}`);
    }
    const artDcText = ownerLearningDcText(row && row.learning_dc);
    if (artDcText) artFacts.push(`Learning ${artDcText}`);
    const artStudy = (row && row.study_time) || {};
    if (ownerReadableValue(artStudy.value)) artFacts.push(`Study ${ownerReadableValue(artStudy.value)} days`);
    if (ownerReadableValue(row && row.expression_kind)) artFacts.push(`Expression: ${ownerReadableValue(row.expression_kind)}`);
    facts.push(...artFacts);
    return ownerSheetRecordCard(row, {
      title: ownerSheetRunnableName(row.display_name || row.name),
      badges: [ownerSheetRunnableName(row.state || row.status), ownerSheetRunnableName(row.type || row.kind)],
      summary: ownerSheetShortText(row),
      facts,
      rules,
      fallback,
    });
  });
  const noneState = gmCompleteNoneState(documents, []);
  content.appendChild(ownerSheetCountedGrid(cards.length, title, cards, {empty: noneState ? `Explicitly none: ${empty}` : empty}));
  return content;
}

function ownerResourcesContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const data = context.surfaceData("resources_states_suppression") || {};
  const viewModel = data["Tianxia_GM_Character_View_Model_v2.json"] || {};
  const suppression = data["Source_CL_and_Realm_Suppression.json"] || {};
  const stats = context.stats || {};
  const resource = stats.primary_resource || {};
  const lines = ownerResourcePools(resource).map(pool => `${pool.name}: ${pool.current}/${pool.maximum}`);
  for (const row of ownerSheetList(viewModel.resources || viewModel.resources_and_states)) lines.push(row);
  content.appendChild(gmInfoCard("Resources", lines));
  for (const [field, title] of [["states", "States"], ["active_states", "Active states"], ["suppressed_rules", "Suppressed rules"], ["suppression", "Suppression"]]) {
    const values = ownerSheetList(viewModel[field]);
    if (values.length) content.appendChild(gmInfoCard(title, values));
  }
  const suppressionLines = [];
  if (suppression && typeof suppression === "object") {
    for (const [key, value] of Object.entries(suppression)) {
      const rendered = ownerSheetRunnableName(value);
      if (rendered) suppressionLines.push(`${friendlyLabel(key)}: ${rendered}`);
    }
  }
  if (suppressionLines.length) content.appendChild(gmInfoCard("Realm suppression", suppressionLines.slice(0, 24)));
  return content;
}

// One readable line per field; list fields drop repeated entries.
function ownerDaoFieldText(value) {
  if (Array.isArray(value)) {
    const unique = [...new Set(value.map(entry => ownerSheetRunnableName(entry)).filter(Boolean))];
    return unique.join(" · ");
  }
  return ownerSheetRunnableName(value);
}

// Owner 2026-09-24: the tab showed only the provisional placeholder theme.
// The character's Dao and I Ching layer is shown from what the build really
// holds: the Foundation's Dao Principle, the Dao Aspects its combat lines and
// Immortal Arts correspond to, and each line's I Ching change rule.  GM-pass
// themes are shown when they were actually written; the placeholder is not.
const OWNER_PROVISIONAL_THEME = ".project.";

function ownerFoundationDaoPrinciple(context) {
  const chapter = Array.isArray(context.snapshot?.foundation?.printed_chapter) ? context.snapshot.foundation.printed_chapter : [];
  for (const part of chapter) {
    const match = /(?:^|\n)#{2,6}\s*Dao Principle\s*\n+([\s\S]*?)(?=\n#{2,6}\s|\n-{3,}|$)/.exec(String(part?.text || ""));
    if (match && ownerSheetRunnableName(match[1])) return ownerStripMarkdown(match[1]).trim();
  }
  return "";
}

function ownerPlaybookLabel(id) {
  const tail = String(id || "").split(".").pop();
  return tail ? ownerKeyLabel(tail) : "";
}

function ownerDaoContent(context) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const surface = context.surfaceData("dao_i_ching") || {};
  // The surface may carry an empty ``dao_i_ching`` wrapper beside the real
  // ``dao``/``i_ching`` rows; an empty object must not hide them.
  const wrapped = surface.dao_i_ching && typeof surface.dao_i_ching === "object" ? surface.dao_i_ching : {};
  const source = wrapped.dao || wrapped.i_ching ? wrapped : surface;
  const dao = source.dao || surface.dao || {};
  const iChing = source.i_ching || surface.i_ching || {};
  const authored = (block) => block && typeof block === "object" && Object.keys(block).length
    && !String(block.authoring_id || "").includes(OWNER_PROVISIONAL_THEME);
  // Model-authored guidance (CharacterGMDaoIChing.v1) uses these fields.
  const authoredFields = [
    ["core_theme", "Theme"], ["principles", "Principles"], ["strengths", "Strengths"], ["risks", "Risks"],
    ["tactical_expression", "In combat"], ["roleplay_expression", "Roleplay"], ["gm_usage_notes", "At the table"],
  ];
  const fieldLines = (block, fields) => fields
    .map(([field, label]) => [label, ownerDaoFieldText(block[field])])
    .filter(([, rendered]) => rendered)
    .map(([label, rendered]) => `${label}: ${rendered}`);
  const lineName = (row) => ownerSheetRunnableName(row.name).replace(/\s*->\s*/g, " → ");

  // ---- The character's Dao, built from its Spheres (owner 2026-09-24: the
  // Daos of the Spheres are the building blocks of personality and action).
  const built = context.sheet && context.sheet.character_dao && typeof context.sheet.character_dao === "object" ? context.sheet.character_dao : null;
  if (built && Array.isArray(built.layers) && built.layers.length) {
    const pct = (value) => `${Math.round(Number(value || 0) * 100)}%`;
    const layers = built.layers;
    const tempered = layers.slice(1, 3).map(layer => layer.name).filter(Boolean);
    const summary = gmInfoCard(`Primary Dao: ${ownerSheetRunnableName(built.primary_sphere)}${tempered.length ? `, tempered by ${tempered.join(" and ")}` : ""}`, [
      ownerSheetRunnableName(layers[0].reality_principle),
      Array.isArray(built.dao_verbs) && built.dao_verbs.length ? `Dao verbs: ${built.dao_verbs.join(", ")}.` : null,
      "Each Sphere the character knows adds a layer, weighted by investment (√(talents + 1)); the Dao is the pattern the layers make.",
      Array.isArray(built.draft_spheres) && built.draft_spheres.length
        ? `Draft profiles awaiting owner review: ${built.draft_spheres.join(", ")}.` : null,
    ]);
    const list = gmEl("div", "owner-talent-list");
    for (const layer of layers) {
      const lines = [
        ["Reality principle", layer.reality_principle], ["Dao trail", layer.dao_trail], ["Signs in play", layer.trial_signs],
        ["Shadow", layer.shadow], ["At the table", layer.gm_read], ["Keep distinct from", layer.keep_distinct_from],
        ["Verbs", Array.isArray(layer.dao_verbs) ? layer.dao_verbs.join(", ") : null],
      ].filter(([, value]) => ownerSheetRunnableName(value)).map(([label, value]) => `${label}: ${ownerSheetRunnableName(value)}`);
      list.appendChild(ownerCollapsible(layer.name, [
        pct(layer.share),
        `${layer.talents} ${layer.talents === 1 ? "talent" : "talents"} · ${layer.resonance}`,
        layer.status === "draft" ? "Draft profile" : null,
      ], [gmEl("p", "owner-sheet-rules-text", lines.join("\n"))]));
    }
    summary.appendChild(list);
    content.appendChild(ownerSheetSection("Dao — built from the character's Spheres", ownerSheetCardGrid([summary]),
      {subtitle: "What truth of reality this cultivator is becoming sensitive to, layer by layer."}));

    const hexagram = built.hexagram || {};
    const posture = built.posture || {};
    const trigramLine = (row, role) => row ? `${role}: ${row.symbol || ""} ${row.name} / ${row.image} — ${row.meaning}.` : null;
    const shadow = posture.shadow || null;
    const reading = gmInfoCard(`Hexagram ${hexagram.number} · ${ownerSheetRunnableName(hexagram.name)} ${hexagram.symbol || ""}`, [
      trigramLine(posture.natural, "Outer (where the Dao moves naturally)"),
      trigramLine(posture.testing, "Inner (what tests it)"),
      shadow ? `Shadow: ${shadow.symbol || ""} ${shadow.name}${shadow.line ? ` Line ${shadow.line} — excess` : ""} (${shadow.meaning}).` : null,
      built.excess && built.excess.becomes
        ? `In excess, line ${built.excess.line} changes and the hexagram becomes ${built.excess.becomes.number} · ${ownerSheetRunnableName(built.excess.becomes.name)} ${built.excess.becomes.symbol || ""}.` : null,
    ]);
    const pressure = built.trigram_pressure || {};
    const pressureLines = [["natural", "Moves naturally through"], ["testing", "Tested by"], ["shadow", "Distorts under"]]
      .map(([key, label]) => Array.isArray(pressure[key]) && pressure[key].length
        ? `${label}: ${pressure[key].slice(0, 4).map(row => `${row.name} ${pct(row.share)}`).join(", ")}` : null)
      .filter(Boolean);
    if (pressureLines.length) {
      reading.appendChild(ownerCollapsible("Trigram pressure across all layers", [],
        [gmEl("p", "owner-sheet-rules-text", pressureLines.join("\n"))]));
    }
    content.appendChild(ownerSheetSection("I Ching — how the character's change is positioned", ownerSheetCardGrid([reading]),
      {subtitle: "The configuration of change that places this Dao under pressure."}));
  }

  // ---- Dao
  const daoCards = [];
  const principle = ownerFoundationDaoPrinciple(context);
  if (principle) {
    daoCards.push(gmInfoCard(`Dao Principle — ${ownerSheetRunnableName(context.snapshot?.foundation?.display_name) || "Foundation"}`, [principle]));
  }
  const aspects = new Map();
  const noteAspect = (name, use) => {
    if (!name) return;
    if (!aspects.has(name)) aspects.set(name, []);
    aspects.get(name).push(use);
  };
  for (const art of Array.isArray(context.snapshot?.immortal_arts) ? context.snapshot.immortal_arts : []) {
    noteAspect(ownerSheetRunnableName(art?.dao_aspect?.display_name), `Immortal Art ${ownerSheetRunnableName(art.display_name || art.name)}`);
  }
  if (aspects.size) {
    const rows = [...aspects.entries()].sort((left, right) => (right[1].length - left[1].length) || left[0].localeCompare(right[0]));
    const card = gmInfoCard("Dao Aspects in play", [
      "The Dao Aspects the character's printed techniques correspond to (Core Rules 17.4), most frequent first.",
    ]);
    const list = gmEl("div", "owner-talent-list");
    for (const [name, uses] of rows) {
      list.appendChild(ownerCollapsible(name, [`${uses.length} ${uses.length === 1 ? "use" : "uses"}`],
        [gmEl("p", "owner-sheet-rules-text", uses.map(use => `• ${use}`).join("\n"))]));
    }
    card.appendChild(list);
    daoCards.push(card);
  }
  if (authored(dao)) {
    const lines = fieldLines(dao, [
      ...authoredFields,
      ["dao_phrase", "Dao phrase"], ["combat_doctrine", "Combat doctrine"], ["resource_policy", "Resource policy"],
      ["reaction_policy", "Reaction policy"], ["ai_turn_prompt", "AI turn prompt"], ["preferred_engagements", "Preferred engagements"],
      ["avoidance_rules", "Avoidance rules"], ["risk_thresholds", "Risk thresholds"], ["target_selection_logic", "Target selection"],
      ["failure_recovery", "Failure recovery"], ["forbidden_behaviors", "Forbidden behaviors"],
    ]);
    if (lines.length) daoCards.push(gmInfoCard(ownerSheetRunnableName(dao.display_name) || "GM Dao reading", lines));
  }
  content.appendChild(ownerSheetSection("Dao of the Foundation and techniques", daoCards.length
    ? ownerSheetCardGrid(daoCards)
    : gmEl("p", "gm-muted owner-sheet-empty", "No Dao is recorded for this character."),
    {subtitle: "What the character's cultivation holds to, from its Foundation and its techniques."}));

  // ---- I Ching
  const changeCards = [];
  if (authored(iChing)) {
    const lines = [
      ...(typeof iChing.enabled === "boolean" ? [`Enabled: ${iChing.enabled ? "Yes" : "No"}`] : []),
      ...fieldLines(iChing, [
        ...authoredFields,
        ["reading_name", "Reading"], ["hexagram_or_trigram", "Hexagram or trigram"], ["natural_tendency", "Natural tendency"],
        ["testing_tendency", "Testing tendency"], ["low_resource_shift", "Low-resource shift"],
        ["gm_generation_instruction", "GM instruction"], ["shift_triggers", "Shift triggers"],
        ["combat_state_interpretation", "Combat state interpretation"], ["composite_hooks", "Composite hooks"],
      ]),
    ];
    if (lines.length) changeCards.unshift(gmInfoCard(ownerSheetRunnableName(iChing.display_name) || "GM I Ching reading", lines));
  }
  content.appendChild(ownerSheetSection("Combat lines — when the character changes course", changeCards.length
    ? ownerSheetCardGrid(changeCards)
    : gmEl("p", "gm-muted owner-sheet-empty", "No I Ching reading is recorded for this character."),
    {subtitle: "Each combat line's natural tendency, and the condition that turns it into another line."}));

  if (!authored(dao) || !authored(iChing)) {
    content.appendChild(gmEl("p", "gm-muted owner-sheet-empty",
      "The character's own written Dao doctrine and I Ching reading come from the GM pass; this character was finalized without it, so this tab shows what the rules derive from its build."));
  }
  return content;
}

function ownerControllerCard(context) {
  const route = (((context.sheet || {}).workflow || {}).latest_run || {}).controller_route_status;
  if (!route || typeof route !== "object") {
    return gmInfoCard("Build controller", [
      "No controller route status is recorded for this character's latest run.",
    ]);
  }
  const state = ownerSheetRunnableName(route.state) || "not recorded";
  const mode = ownerSheetRunnableName(route.mode || route.route_mode) || "not recorded";
  const events = Number.isFinite(Number(route.event_count)) ? Number(route.event_count) : null;
  const lines = [
    `Mode: ${mode.replace(/_/g, " ")}`,
    `State: ${state.replace(/_/g, " ")}`,
    `Activation policy: ${(ownerSheetRunnableName(route.activation_policy) || "not recorded").toLowerCase()}`,
    events === null ? null : `${events.toLocaleString()} recorded advancement events in this run`,
  ].filter(Boolean);
  const card = gmInfoCard("Build controller", lines);
  // The route identity is technical material and goes into the tab's single
  // Technical disclosure (see ownerControllerTechnicalRows).
  return {card};
}

function ownerControllerTechnicalRows(context) {
  const route = (((context.sheet || {}).workflow || {}).latest_run || {}).controller_route_status;
  if (!route || typeof route !== "object") return [];
  const rows = [];
  for (const [key, value] of Object.entries(route)) {
    const rendered = ownerReadableValue(value) || ownerSheetRunnableName(value);
    if (!rendered) continue;
    rows.push(`${friendlyLabel(key)}: ${rendered}`);
  }
  return rows;
}

function ownerDiagnosticsContent(context, surface) {
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  const data = (surface && surface.data) || context.surfaceData("diagnostics") || {};
  const lines = [];
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      lines.push(`${friendlyLabel(key)}: ${value}`);
    }
  }
  const controller = ownerControllerCard(context);
  content.appendChild(controller.card);
  const guidance = gmInfoCard("Read-only GM guidance", [
    "Dao, I Ching, training sources, and advanced-art states are display-only.",
    "They grant no action, bonus, resource change, legality, or execution authority.",
  ]);
  guidance.classList.add("owner-guidance-boundary-card");
  content.appendChild(guidance);
  content.appendChild(gmInfoCard("Diagnostics", lines.length ? lines.slice(0, 40) : ["No diagnostic summary was recorded."]));
  return content;
}


function ownerSurfaceHumanContent(context, surface) {
  switch (surface.id) {
    case "overview_core_stats": return ownerOverviewContent(context);
    case "leveling": return ownerLevelingContent(context);
    case "background": return ownerBackgroundContent(context);
    case "paths_subpaths": return ownerPathsContent(context);
    case "spheres_talents": return ownerSpheresContent(context);
    case "insights": return ownerInsightsContent(context);
    case "actions": return ownerActionsContent(context);
    case "forged_techniques": return ownerRecordSurfaceContent(context, {
      surfaceIds: ["forged_techniques"], keys: ["forged_techniques"], title: "Forged Techniques",
      empty: "No forged techniques.", badgeKeys: ["state", "status", "grade", "type"], fallback: "Forged Technique",
    });
    case "manuals_recorded_arts": return ownerManualsAndArtsContent(context);
    case "immortal_arts": return ownerImmortalArtsContent(context);
    case "foundation": return ownerFoundationMethodContent(context, "foundation");
    case "method": return ownerFoundationMethodContent(context, "method");
    case "companions": return ownerRecordSurfaceContent(context, {
      surfaceIds: ["companions"], keys: ["companions", "spirits", "beasts"], title: "Companions, Spirits and Beasts",
      empty: "No companion, spirit, or beast is recorded.", badgeKeys: ["kind", "type", "state", "bond"], fallback: "Companion",
    });
    case "equipment": return ownerWithGivenItems(ownerStartingKitContent(context)) || ownerRecordSurfaceContent(context, {
      surfaceIds: ["equipment"], keys: ["equipment"], title: "Equipment",
      empty: "No equipment is recorded.", badgeKeys: ["type", "kind", "quantity", "state", "equipped"], fallback: "Equipment",
    });
    case "resources_states_suppression": return ownerResourcesContent(context);
    case "dao_i_ching": return ownerDaoContent(context);
    case "diagnostics": return ownerDiagnosticsContent(context, surface);
    default: return gmEl("p", "gm-muted owner-sheet-empty", "No human-facing records reported by the verified source.");
  }
}

function ownerCoinText(copper) {
  const value = Math.max(0, Number(copper) || 0);
  const gold = Math.floor(value / 100), silver = Math.floor((value % 100) / 10), cash = value % 10;
  return [gold ? `${gold} GT` : "", silver ? `${silver} ST` : "", cash ? `${cash} CC` : ""].filter(Boolean).join(" ") || "0 CC";
}

// Item Book rules text is authored in Markdown; the sheet shows plain text.
// A material property's own bold heading ("**Material Property — X.**") is
// dropped because the card already names the property.
function ownerItemBookText(text, heading) {
  let value = String(text || "").trim();
  if (heading) {
    const lead = /^\*\*[^*]*\*\*\s*/;
    const match = value.match(lead);
    if (match && match[0].includes(String(heading))) value = value.slice(match[0].length);
  }
  return value.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1");
}

// Items the owner gave on the Items tab (outside the sealed character; used in combat too).
function ownerWithGivenItems(content) {
  const projectId = selectedProject;
  if (!content || !projectId) return content;
  const block = gmEl("div", "owner-given-items");
  content.appendChild(block);
  api(`/api/items/owned/${encodeURIComponent(projectId)}`).then(({items = []}) => {
    if (!items.length) return;
    block.appendChild(gmEl("h4", "", "Given by you (Items tab)"));
    for (const item of items) {
      const card = gmEl("div", "owner-sheet-feature");
      card.appendChild(gmEl("strong", "", `${item.name}${item.kind === "armour" ? (item.equipped ? " — worn" : " — not worn") : ""}`));
      card.appendChild(gmEl("p", "", itemsDescribe(item)));
      block.appendChild(card);
    }
  }).catch(() => {});
  return content;
}

// The controller-built starting kit: printed Background kit plus the Path kit.
function ownerStartingKitContent(context) {
  const rows = Array.isArray(context.snapshot?.equipment) ? context.snapshot.equipment : [];
  const kitRow = rows.find(row => row && row.starting_kit && typeof row.starting_kit === "object");
  if (!kitRow) return null;
  const kit = kitRow.starting_kit;
  const content = gmEl("div", "gm-complete-surface-content owner-sheet-content");
  if (context.snapshot.starting_loadout?.note) {
    content.appendChild(gmInfoCard("Starting equipment", [context.snapshot.starting_loadout.note]));
  }
  const weapon = kit.resolved_treasure_weapon;
  if (weapon && typeof weapon === "object") {
    const chassis = weapon.chassis || {};
    const material = weapon.material || {};
    const card = gmEl("div", "owner-sheet-feature");
    const lines = [
      `${ownerSheetRunnableName(chassis.name) || "Weapon"} · ${chassis.damage || ""}${chassis.properties ? ` · ${chassis.properties}` : ""}`,
      `Refinement Bonus +${weapon.refinement_bonus} to attack and damage · total effective bonus +${weapon.total_effective_bonus} of ${Number(weapon.refinement_bonus) + Number(weapon.enchantment_capacity)}`,
      `Primary Material: ${material.name} (${(material.affinities || []).join(", ")}) — ${material.property_name}: ${ownerItemBookText(material.property_text, material.property_name)}`,
    ];
    for (const row of Array.isArray(weapon.enchantments) ? weapon.enchantments : []) {
      lines.push(`${row.name} (+${row.equivalent_bonus}, ${row.family}): ${ownerItemBookText(row.text)}`);
    }
    lines.push(`Appraised value: ${Number(weapon.value_gt || 0).toLocaleString()} GT`);
    card.appendChild(gmInfoCard(`${weapon.name} — ${weapon.grade_label}`, lines));
    content.appendChild(ownerSheetSection("Treasure weapon", card, {subtitle: "Built by Item Book Chapter 2: chassis, Primary Material, grade, enchantments."}));
  }
  const armor = kit.resolved_treasure_armor;
  if (armor && typeof armor === "object") {
    const chassis = armor.chassis || {};
    const material = armor.material || {};
    const card = gmEl("div", "owner-sheet-feature");
    const lines = [
      `${ownerSheetRunnableName(chassis.name) || "Armour"} · ${chassis.armor_category} · AC ${chassis.armor_class} +${armor.refinement_bonus} (Refinement Bonus) · Stealth ${chassis.stealth || "Normal"}${chassis.strength && chassis.strength !== "—" ? ` · ${chassis.strength}` : ""}`,
      `Primary Material: ${material.name} (${(material.affinities || []).join(", ")}) — ${material.property_name}: ${ownerItemBookText(material.property_text, material.property_name)}`,
    ];
    for (const row of Array.isArray(armor.enhancements) ? armor.enhancements : []) {
      lines.push(`${row.name} (+${row.equivalent_bonus}, ${row.family}): ${ownerItemBookText(row.text)}`);
    }
    lines.push(`Appraised value: ${Number(armor.value_gt || 0).toLocaleString()} GT`);
    card.appendChild(gmInfoCard(`${armor.name} — ${armor.grade_label}`, lines));
    content.appendChild(ownerSheetSection("Treasure armour", card, {subtitle: "Built by Item Book Chapter 3: profile, Primary Material, grade, enhancements."}));
  }
  const bought = kit.resolved_treasure_purchases;
  if (bought && typeof bought === "object") {
    const wondrous = Array.isArray(bought.wondrous) ? bought.wondrous : [];
    if (wondrous.length) {
      const wrap = gmEl("div", "owner-sheet-feature");
      for (const row of wondrous) {
        const attune = row.attunement_slots ? "Requires Attunement" : "No Attunement";
        wrap.appendChild(gmInfoCard(`${row.name} — ${row.grade} ${row.item_type}`, [`${row.family} · ${attune} · ${Number(row.value_gt || 0).toLocaleString()} GT`, ...ownerItemBookText(row.text).split("\n").filter(Boolean)]));
      }
      content.appendChild(ownerSheetSection(`Wondrous Treasures (${wondrous.length})`, wrap, {subtitle: "Item Book Chapter 4, bought from the treasure budget."}));
    }
    const consumables = Array.isArray(bought.consumables) ? bought.consumables : [];
    if (consumables.length) {
      const wrap = gmEl("div", "owner-sheet-feature");
      for (const row of consumables) {
        wrap.appendChild(gmInfoCard(`${row.name} ×${row.batch_quantity} ${row.batch_unit} — ${row.grade}`, [`${row.family} · ${row.activation} · ${Number(row.batch_price_gt || 0).toLocaleString()} GT per batch`, ...ownerItemBookText(row.text).split("\n").filter(Boolean)]));
      }
      content.appendChild(ownerSheetSection(`Consumables (${consumables.length} batches)`, wrap, {subtitle: "Item Book Chapter 5, bought from the treasure budget."}));
    }
  }
  const items = Array.isArray(kit.items) ? kit.items : [];
  const table = gmEl("table", "owner-action-table");
  const head = gmEl("tr");
  for (const label of ["Item", "Qty", "From", "Printed as", "Value"]) head.appendChild(gmEl("th", null, label));
  const thead = gmEl("thead"); thead.appendChild(head); table.appendChild(thead);
  const body = gmEl("tbody");
  for (const item of items) {
    const tr = gmEl("tr");
    tr.appendChild(gmEl("td", "owner-action-name", ownerSheetRunnableName(item.name) || "Item"));
    tr.appendChild(gmEl("td", null, String(item.quantity ?? 1)));
    tr.appendChild(gmEl("td", null, item.source === "path" ? "Path kit" : item.source === "purchase" ? "Bought with kit coin" : "Background kit"));
    tr.appendChild(gmEl("td", null, ownerSheetRunnableName(item.printed) || "—"));
    tr.appendChild(gmEl("td", null, ownerCoinText(item.value_cc)));
    body.appendChild(tr);
  }
  table.appendChild(body);
  const option = String(kit.path_option || "").replace("option_", "Option ").toUpperCase().replace("OPTION ", "Option ");
  content.appendChild(ownerSheetSection(`Starting kit (${items.length} items)`, table, {subtitle: `Printed Background kit plus the Path kit (${option}).`}));
  const trinkets = (Array.isArray(kit.trinkets) ? kit.trinkets : []).map(row => ownerSheetRunnableName(row.text)).filter(Boolean);
  if (trinkets.length) content.appendChild(gmInfoCard("Keepsakes", trinkets));
  const coinLines = [`Purse: ${ownerCoinText(kit.coin_cc)}`];
  for (const roll of Array.isArray(kit.printed_coin_rolls) ? kit.printed_coin_rolls : []) {
    coinLines.push(`“${ownerSheetRunnableName(roll.printed)}”: ${roll.dice} ${roll.unit} rolled ${(roll.rolls || []).join(", ")}`);
  }
  content.appendChild(gmInfoCard("Coin", coinLines));
  return content;
}

// Everything technical -- record ids, hashes, packet ids, source bindings and
// provenance -- lives in exactly one collapsed disclosure per tab.
function ownerSurfaceTechnicalDetails(context, surface, { extraCards = [] } = {}) {
  const details = document.createElement("details");
  details.className = "owner-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Technical: sources, hashes and provenance";
  details.appendChild(summary);
  const body = gmEl("div", "owner-technical-body");

  // Extra technical cards supplied by the tab's own builder (for example the
  // controller's route identity) belong inside this one disclosure.
  for (const extra of extraCards) {
    if (extra && extra.title && Array.isArray(extra.rows) && extra.rows.length) {
      body.appendChild(gmInfoCard(extra.title, extra.rows));
    }
  }

  const identity = context.snapshot.selected_record_identity_index || {};
  const identityRows = Object.entries(identity).map(([recordId, value]) => {
    if (value && typeof value === "object") return `${recordId} — ${ownerSheetRunnableName(value.record_hash || value.hash || value.sha256) || "hash not recorded"}`;
    return `${recordId} — ${ownerSheetRunnableName(value) || "no identity recorded"}`;
  });
  if (identityRows.length) body.appendChild(gmInfoCard("Selected record identities", identityRows.slice(0, 400)));

  const sections = context.snapshot.selected_record_sections || {};
  const sectionRows = Object.entries(sections).map(([kind, rows]) => `${kind}: ${Array.isArray(rows) ? rows.length : 0}`);
  if (sectionRows.length) body.appendChild(gmInfoCard("Selected record sections", sectionRows));

  const provenance = context.snapshot.section_provenance;
  if (provenance) body.appendChild(ownerSheetTextCard("Section provenance", pretty(provenance)));
  const authority = context.snapshot.authority_and_artifact_identity;
  if (authority) body.appendChild(ownerSheetTextCard("Authority and artifact identity", pretty(authority)));

  const content = gmCompleteSurfaceContent(surface, {
    actionDocuments: gmCompleteDocuments(context.surfaceData("actions")),
    pathDocuments: gmCompleteDocuments(context.surfaceData("paths_subpaths")),
  });
  for (const child of Array.from(content.children)) body.appendChild(child);

  const raw = document.createElement("details");
  raw.className = "developer-diagnostics";
  const rawSummary = document.createElement("summary");
  rawSummary.textContent = "Raw verified surface data";
  const rawPre = gmEl("pre", null, pretty(surface.data || {}));
  raw.append(rawSummary, rawPre);
  body.appendChild(raw);

  details.appendChild(body);
  return details;
}

function gmBuildCompleteCharacterSurfacePanel(model, sheet, id) {
  const labels = TianxiaSheetViewModel.COMPLETE_CHARACTER_SURFACE_LABELS || {};
  const label = labels[id] || id;
  const panel = gmPanelShell(id, label);
  panel.classList.add("gm-complete-surface-panel", "owner-sheet-surface");
  panel.dataset.completeSurface = id;
  const context = ownerSheetContext(sheet);
  const controllerTechnicalRows = id === "diagnostics" ? ownerControllerTechnicalRows(context) : [];
  const complete = model.completeCharacter;
  const surface = complete && complete.surfaces && complete.surfaces[id]
    ? complete.surfaces[id]
    : {id, label, available: false, reason: "No verified complete-character source was supplied."};

  const heading = gmEl("header", "owner-sheet-surface-heading");
  heading.appendChild(gmEl("h2", "owner-sheet-surface-title", surface.label || label));
  const subtitle = OWNER_SHEET_TAB_SUBTITLES[id];
  if (subtitle) heading.appendChild(gmEl("p", "owner-sheet-surface-subtitle", subtitle));
  panel.appendChild(heading);

  // The guidance note is rendered in Diagnostics only (owner decision
  // 2026-09-13); every other tab stays free of it.
  if (id === "diagnostics") {
    panel.appendChild(gmEl("p", "owner-guidance-note", OWNER_SHEET_GUIDANCE_NOTE));
  }

  if (!surface.available) {
    panel.appendChild(gmEl("p", "gm-complete-unavailable", surface.reason || "This surface is unavailable for the current verified character source."));
  } else {
    const content = ownerSurfaceHumanContent(context, surface);
    if (content && (content.childElementCount || content.tagName === "DIV")) panel.appendChild(content);
  }
  panel.appendChild(ownerSurfaceTechnicalDetails(context, surface, {
    extraCards: surface.id === "diagnostics" && controllerTechnicalRows.length
      ? [{title: "Build controller route identity", rows: controllerTechnicalRows}]
      : [],
  }));
  return panel;
}

function gmPanelShell(id, label) {
  const panel = gmEl("section", "gm-panel");
  panel.dataset.gmPanel = id;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-label", label);
  panel.id = `gmPanel-${id}`;
  return panel;
}

function gmBuildOverviewPanel(model, sheet) {
  const panel = gmPanelShell("overview", "Overview");
  const summaryLines = [
    model.backgroundLabel ? `Background: ${model.backgroundLabel}` : null,
    model.originLabel ? `Origin Insight: ${model.originLabel}` : null,
    model.pathLabel ? `Path: ${model.pathLabel}${model.subpathLabel ? ` · ${model.subpathLabel}` : ""}` : null,
    model.methodLabel ? `Primary Method: ${model.methodLabel}` : null,
    model.foundationLabel ? `Foundation: ${model.foundationLabel}` : null,
    model.counts.spheres || model.counts.talents || model.counts.insights || model.counts.automaticComponents
      ? `${model.counts.spheres} acquired Sphere${model.counts.spheres === 1 ? "" : "s"} · ${model.counts.talents} learned Talent${model.counts.talents === 1 ? "" : "s"}${model.counts.insights ? ` · ${model.counts.insights} Insight${model.counts.insights === 1 ? "" : "s"}` : ""}${model.counts.automaticComponents ? ` · ${model.counts.automaticComponents} automatic component${model.counts.automaticComponents === 1 ? "" : "s"}` : ""}`
      : null,
  ];
  panel.appendChild(gmInfoCard("Build summary", summaryLines));
  if (model.abilityChips.length) {
    const scores = gmEl("article", "gm-info-card");
    scores.appendChild(gmEl("h5", null, "Ability scores"));
    scores.appendChild(gmAbilityChipsGrid(model.abilityChips));
    panel.appendChild(scores);
  }
  panel.appendChild(gmInfoCard("Readiness", [model.plainSummary || "Saved character."]));
  const next = gmEl("section", "next-legal-action owner-sheet-next-action gm-next-action");
  next.append(gmEl("h4", null, "What happens next"), gmEl("p", null, ownerNextLegalAction(sheet)));
  panel.appendChild(next);
  if (model.advancementLevels.length) {
    const adv = gmEl("article", "gm-info-card");
    adv.appendChild(gmEl("h5", null, "Advancement"));
    const list = gmEl("ul", "gm-advancement-list");
    for (const level of model.advancementLevels) {
      const hpMax = level.hp && level.hp.max_after_level !== undefined && level.hp.max_after_level !== null ? ` · HP ${level.hp.max_after_level}` : "";
      list.appendChild(gmEl("li", null, `CL ${level.cl}${level.realm ? ` · ${level.realm}` : ""}${hpMax}`));
    }
    adv.appendChild(list);
    panel.appendChild(adv);
  }
  const workflow = sheet.workflow;
  const workflowRun = workflow?.active_run || workflow?.latest_run;
  if (workflowRun) {
    const workflowSection = gmEl("section", workflow.active_run ? "workflow-recovery-section owner-sheet-section" : "workflow-recovery-section owner-sheet-section gm-latest-run");
    workflowSection.appendChild(gmEl("h4", null, workflow.active_run ? "Incomplete build saved by the Factory" : "Latest complete-character build"));
    workflowSection.appendChild(gmEl("p", null, `${friendlyLabel(workflowRun.status)}. ${workflowRun.next_legal_action || "Review the saved build status."}`));
    const workflowActions = gmEl("div", "recovery-actions");
    if (workflow.active_run) workflowActions.appendChild(recoveryActionButton("Return to active build", async () => { showScreen("builder"); await restoreGuidedActiveBuild(sheet.project_id, workflowRun.run_id); }, true));
    workflowActions.appendChild(recoveryActionButton("Inspect Build / Errors", async () => { showScreen("builder"); await restoreGuidedActiveBuild(sheet.project_id, workflowRun.run_id, true); }));
    workflowSection.appendChild(workflowActions);
    panel.appendChild(workflowSection);
  }
  return panel;
}

function gmBuildCombatPanel(model, sheet) {
  const panel = gmPanelShell("combat", "Combat");
  const adjustedNote = (ownerSnapshotForDisplay(sheet).ability_scores_and_statistics || {}).table_adjustment_note;
  if (adjustedNote) panel.appendChild(gmEl("p", "owner-sheet-note", adjustedNote));
  if (model.abilityChips.length) {
    const scores = gmEl("article", "gm-info-card");
    scores.appendChild(gmEl("h5", null, "Ability scores"));
    scores.appendChild(gmAbilityChipsGrid(model.abilityChips));
    panel.appendChild(scores);
  }
  const snapshot = ownerSnapshotForDisplay(sheet);
  const stats = snapshot.ability_scores_and_statistics || {};
  const defenseLines = [];
  const ac = stats.armor_class || {};
  const defenseSummary = sheetArmorClassSummary(ac);
  if (defenseSummary !== null) defenseLines.push(`Armor Class ${defenseSummary}.`);
  if (ac.worn_note) defenseLines.push(ac.worn_note);
  const init = stats.initiative || {};
  if (init.bonus !== null && init.bonus !== undefined) defenseLines.push(`Initiative ${init.bonus >= 0 ? "+" : ""}${init.bonus} (1d20 + initiative bonus).`);
  const speed = stats.speed || {};
  if (speed.walking_ft !== null && speed.walking_ft !== undefined) defenseLines.push(`Walking speed ${speed.effective_walking_ft ?? speed.walking_ft} ft.`);
  if (speed.worn_note) defenseLines.push(speed.worn_note);
  if (stats.technique_attack_bonus !== null && stats.technique_attack_bonus !== undefined) defenseLines.push(`Technique attack ${stats.technique_attack_bonus >= 0 ? "+" : ""}${stats.technique_attack_bonus}.`);
  if (stats.technique_save_dc !== null && stats.technique_save_dc !== undefined) defenseLines.push(`Technique save DC ${stats.technique_save_dc}.`);
  if (defenseLines.length) panel.appendChild(gmInfoCard("Defenses and attacks", defenseLines));
  if (Array.isArray(stats.skills) && stats.skills.length) {
    const skillLines = stats.skills.map(row => `${row.skill}: ${row.bonus >= 0 ? "+" : ""}${row.bonus} (${row.proficiency}${row.ability ? `, ${row.ability}` : ""})`);
    panel.appendChild(gmInfoCard("Skills", skillLines));
  }
  if (model.actionsIndex.length) {
    const timings = new Map();
    for (const row of model.actionsIndex) {
      const key = row.timing_or_category || "Feature";
      if (!timings.has(key)) timings.set(key, []);
      timings.get(key).push(row.display_name);
    }
    for (const [timing, names] of timings) {
      panel.appendChild(gmInfoCard(timing, names));
    }
  }
  return panel;
}

function gmBuildCultivationPanel(model, sheet) {
  const panel = gmPanelShell("cultivation", "Cultivation");
  const pathRows = (model.pathsSummary.paths || []).map(row => {
    const name = row && typeof row === "object" ? row.name || row.display_name || row.path_id : row;
    const attainment = row && typeof row === "object" && row.attainment !== undefined && row.attainment !== null ? ` · attainment ${row.attainment}` : "";
    return `${name || "Path"}${attainment}`;
  });
  if (pathRows.length) panel.appendChild(gmInfoCard("Paths", pathRows));
  const subpathRows = (model.pathsSummary.subpaths || []).map(row => (row && typeof row === "object" ? row.name || row.subpath_id : row)).filter(Boolean);
  if (subpathRows.length) panel.appendChild(gmInfoCard("Subpaths / Traditions", subpathRows));
  if (model.methodLabel) panel.appendChild(gmInfoCard("Primary Method", [model.methodLabel]));
  if (model.foundationLabel) panel.appendChild(gmInfoCard("Foundation", [model.foundationLabel]));
  const sphereLines = [
    `${model.counts.spheres} acquired Sphere${model.counts.spheres === 1 ? "" : "s"}`,
    `${model.counts.talents} learned Talent${model.counts.talents === 1 ? "" : "s"}`,
    `${model.counts.insights} Cultivation Insight${model.counts.insights === 1 ? "" : "s"}`,
    `${model.counts.automaticComponents} automatic Sphere component${model.counts.automaticComponents === 1 ? "" : "s"}`,
  ];
  panel.appendChild(gmInfoCard("Spheres, Talents, and Insights", sphereLines));
  if (model.advancementLevels.length) {
    const adv = gmEl("article", "gm-info-card");
    adv.appendChild(gmEl("h5", null, "Advancement history"));
    const list = gmEl("ul", "gm-advancement-list");
    for (const level of model.advancementLevels) {
      const hpMax = level.hp && level.hp.max_after_level !== undefined && level.hp.max_after_level !== null ? ` · HP ${level.hp.max_after_level}` : "";
      list.appendChild(gmEl("li", null, `CL ${level.cl}${level.realm ? ` · ${level.realm}` : ""}${hpMax}${level.pb !== undefined && level.pb !== null ? ` · PB +${level.pb}` : ""}`));
    }
    adv.appendChild(list);
    panel.appendChild(adv);
  }
  return panel;
}

function gmBuildAbilitiesPanel(model) {
  const panel = gmPanelShell("abilities", "Abilities");
  for (const group of model.abilityGroups) {
    const section = gmEl("section", "gm-ability-group");
    section.appendChild(gmEl("h4", "gm-group-heading", group.label));
    const wrap = gmEl("div", "gm-ability-cards");
    for (const card of group.cards) wrap.appendChild(gmAbilityCard(card));
    section.appendChild(wrap);
    panel.appendChild(section);
  }
  return panel;
}

function gmBuildNotesGearPanel(model) {
  const panel = gmPanelShell("notes_gear", "Notes & Gear");
  const surface = model.notesGear || {notes: [], items: []};
  if (surface.notes.length) {
    panel.appendChild(gmInfoCard("Notes", surface.notes.map(row => row.name === "Note" ? row.summary : `${row.name}${row.summary ? ` — ${row.summary}` : ""}`)));
  }
  if (surface.items.length) {
    panel.appendChild(gmInfoCard("Equipment & Gear", surface.items.map(row => {
      const meta = [row.quantity ? `×${row.quantity}` : null, row.category].filter(Boolean).join(" · ");
      return `${row.name}${meta ? ` (${meta})` : ""}${row.summary ? ` — ${row.summary}` : ""}`;
    })));
  }
  return panel;
}

function gmGuidanceLines(row) {
  if (!row || typeof row !== "object") return [];
  const principles = Array.isArray(row.principles) && row.principles.length
    ? `Principles: ${row.principles.join(" · ")}`
    : null;
  return [
    row.core_theme,
    principles,
    row.roleplay_expression ? `Roleplay: ${row.roleplay_expression}` : null,
    row.tactical_expression ? `At the table: ${row.tactical_expression}` : null,
    row.gm_usage_notes,
  ].filter(Boolean);
}

// Owner 2026-09-24: the Daos of the character's Spheres are the building
// blocks of how it acts, at the table and in the built-in combat AI.
const GM_POSTURE_IN_COMBAT = {
  qian: "presses the strongest foe and seeks the decisive finish",
  zhen: "strikes first and accepts exposure to keep the initiative",
  kan: "keeps to cover, baits and ambushes, and withdraws when the ground turns",
  gen: "holds its ground, guards, and spends little",
  kun: "covers its allies before itself",
  xun: "works the angles and wears down the weakened",
  li: "fixes on one visible target until it falls",
  dui: "fights with and for the group",
};

function gmRoleplayFromDaoCard(dao) {
  if (!dao || !Array.isArray(dao.layers) || !dao.layers.length) return null;
  const layers = dao.layers;
  const posture = dao.posture || {};
  const pressure = dao.trigram_pressure || {};
  const stress = Array.isArray(pressure.natural) && pressure.natural.length > 1 ? pressure.natural[1] : posture.natural;
  const trigram = (row) => row ? `${row.name} / ${row.image}` : "";
  const lines = [
    `How they act: ${layers.slice(0, 3).map(layer => `${layer.name} — ${ownerSheetRunnableName(layer.dao_trail)}`).join(" ")}`,
    `What shows in play: ${layers.slice(0, 2).map(layer => ownerSheetRunnableName(layer.trial_signs)).join(" ")}`,
    posture.natural ? `Posture: moves naturally through ${trigram(posture.natural)} (${posture.natural.meaning}); pressed, shifts toward ${trigram(stress)}; tested by ${trigram(posture.testing)} (${posture.testing ? posture.testing.meaning : ""}).` : null,
    `Temptation: ${ownerSheetRunnableName(layers[0].shadow)}${posture.shadow ? ` Distorts under ${trigram(posture.shadow)}${posture.shadow.line ? ` Line ${posture.shadow.line} (excess)` : ""}.` : ""}`,
    posture.natural && GM_POSTURE_IN_COMBAT[posture.natural.trigram]
      ? `Built-in combat AI: ${GM_POSTURE_IN_COMBAT[posture.natural.trigram]}; when pressed it ${GM_POSTURE_IN_COMBAT[(stress || posture.natural).trigram]}.` : null,
    "Let the world notice who they keep becoming; do not tell the player what their Dao is.",
  ].filter(Boolean);
  return gmInfoCard(`Roleplay from the character's Dao (${dao.primary_sphere}${dao.secondary_sphere ? `, ${dao.secondary_sphere}` : ""})`, lines);
}

function gmBuildAuthoringPanel(model, sheet, {utility = false} = {}) {
  const panel = utility ? gmEl("section", "gm-sheet-utility") : gmPanelShell("gm_guidance", "GM Guidance");
  if (utility) panel.dataset.gmUtility = "gm_guidance";
  const view = sheet.gm_authoring_view || {};
  // Plan Part B: the orange "GM guidance only" banner is retired.  Dao, I
  // Dao and I Ching provide descriptive guidance; the workspace utility keeps this plain reminder.
  panel.appendChild(gmEl("p", "owner-guidance-note", "GM guidance only — not a combat macro. Dao, I Ching, training sources, and advanced-art states are display-only. They grant no action, bonus, resource change, legality, or execution authority."));
  const daoCard = gmRoleplayFromDaoCard(sheet && sheet.character_dao);
  if (daoCard) panel.appendChild(daoCard);
  if (view.available !== true) {
    panel.appendChild(gmInfoCard("GM authoring has not been prepared", [
      "Use Prepare Command 1–4 Workspace below the sheet. The Factory will derive read-only guidance from this character's exact selected records without changing advancement or mechanics.",
    ]));
    return panel;
  }

  // Until a model has written this character's GM guidance, the workspace
  // holds only a record-list template ("Selected Display Options",
  // "Project-Derived Cultivation Theme").  It says nothing about the
  // character, so it is not shown as guidance.
  if (view.gm_authoring_actual !== true && view.gm_authorship?.origin === "project_selected_record_template") {
    panel.appendChild(gmInfoCard("GM guidance has not been written yet", [
      "No model has authored this character's Dao or I Ching reading yet; the Factory only holds a placeholder list of the selected records.",
      "Author the GM candidate for this character to write them.",
    ]));
    return panel;
  }
  const dao = view.dao_i_ching?.dao || {};
  const iChing = view.dao_i_ching?.i_ching || {};
  panel.appendChild(gmInfoCard(dao.display_name || "Dao", gmGuidanceLines(dao)));
  panel.appendChild(gmInfoCard(iChing.display_name || "I Ching", gmGuidanceLines(iChing)));

  const sources = Array.isArray(view.training_sources) ? view.training_sources : [];
  if (sources.length) {
    // Constructed Manuals are named in the sheet's selected-record sections.
    const sections = ((sheet || {}).owner_character_sheet || {}).selected_record_sections || {};
    const namesById = new Map();
    for (const rows of Object.values(sections)) {
      for (const row of Array.isArray(rows) ? rows : []) {
        if (row && typeof row.record_id === "string" && typeof row.display_name === "string") namesById.set(row.record_id, row.display_name);
      }
    }
    panel.appendChild(gmInfoCard("Training Sources", sources.map(row => {
      const name = row.display_name || row.source_name || namesById.get(row.source_id) || row.source_id || "Source-backed training context";
      return `${name}${row.summary ? ` — ${row.summary}` : ""}`;
    })));
  }

  const advanced = view.advanced_systems || {};
  const forged = advanced.forged_techniques || {};
  const recorded = advanced.recorded_arts || {};
  const immortal = advanced.immortal_arts || {};
  panel.appendChild(gmInfoCard("Advanced Arts", [
    `Forged Techniques (custom technique authoring): ${friendlyLabel(forged.state || "not acquired")}.`,
    forged.note,
    `Recorded Arts / Manuals: ${friendlyLabel(recorded.state || "not acquired")}.`,
    recorded.note,
    `Immortal Arts: ${friendlyLabel(immortal.state || "not projected")}.`,
    immortal.note,
    "These states are informational. Authoring and combat execution require separate source-backed schemas and validation.",
  ]));
  return panel;
}

function wireGmTabs(nav, container) {
  // The vertical rail list and the hidden horizontal strip are two views of one
  // tablist, so selection updates every [data-gm-tab] in the sheet and the
  // click/keyboard handling is delegated from each list's own container.
  // container is the panels wrapper, so the tab lists are looked up from the
  // sheet that holds both the hidden strip and the vertical rail.
  const sheetRoot = container.closest(".owner-character-sheet") || document;
  const lists = [...new Set([nav, ...sheetRoot.querySelectorAll("[data-gm-tablists], .owner-rail-tabs")])]
    .filter(node => node && node.querySelector("[data-gm-tab]"));
  const select = tabId => {
    for (const list of lists) {
      for (const button of list.querySelectorAll("[data-gm-tab]")) {
        const active = button.dataset.gmTab === tabId;
        button.classList.toggle("active", active);
        if (button.getAttribute("role") === "presentation") continue;
        button.setAttribute("aria-selected", active ? "true" : "false");
      }
    }
    for (const panel of container.querySelectorAll("[data-gm-panel]")) {
      panel.classList.toggle("active", panel.dataset.gmPanel === tabId);
    }
  };
  const onActivate = (list, event) => {
    const button = event.target.closest("[data-gm-tab]");
    if (button) select(button.dataset.gmTab);
  };
  for (const list of lists) {
    list.addEventListener("click", event => onActivate(list, event));
  }
  nav.addEventListener("keydown", event => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const buttons = Array.from(nav.querySelectorAll("[data-gm-tab]"));
    const current = buttons.findIndex(button => button.classList.contains("active"));
    const next = event.key === "ArrowRight" ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length;
    buttons[next].focus();
    select(buttons[next].dataset.gmTab);
    event.preventDefault();
  });
  const first = nav.querySelector("[data-gm-tab]");
  if (first) select(first.dataset.gmTab);
}

function renderOwnerSheet(sheet, targetHost = null) {
  ownerCharacterSheet = sheet; selectedProject = sheet.project_id; lastGMExport = null;
  const host = targetHost || document.getElementById("ownerCharacterSheet"); clearNode(host);
  const model = TianxiaSheetViewModel.buildSheetViewModel(sheet, {
    characterListName: (gmLibraryJoin.characterListRows.get(sheet.project_id) || {}).name ?? sheet.name,
    resolvedWorkflowName: ownerResolvedWorkflowName(sheet),
    libraryName: (gmLibraryJoin.libraryRows.get(sheet.project_id) || {}).name,
  });
  gmNormalizeSheetSurfaces(sheet);

  const header = gmEl("header", "owner-sheet-header gm-sheet-header");
  const identityBlock = gmEl("div", "gm-identity-block");
  identityBlock.append(
    gmEl("p", "sheet-kicker", gmOwnerKicker(model)),
    gmEl("h3", "gm-name", model.name || "Unnamed character"),
  );
  if (model.title) identityBlock.appendChild(gmEl("p", "gm-title", model.title));
  const conceptLine = model.concept || model.plainSummary;
  if (conceptLine) identityBlock.appendChild(gmEl("p", "gm-concept", conceptLine));
  const pills = gmEl("div", "gm-identity-pills");
  for (const pill of [
    model.cl !== null && model.cl !== undefined ? `CL ${model.cl}` : null,
    model.realmLabel,
    model.pathSummary || model.pathLabel,
    model.pathSummary ? null : model.subpathLabel,
    model.methodLabel,
    model.foundationLabel,
    model.species,
    model.keyAbility ? `Key Ability ${model.keyAbility}` : null,
  ]) {
    if (pill) pills.appendChild(gmEl("span", pill === model.pathSummary ? "gm-pill gm-path-summary" : "gm-pill", pill));
  }
  if (pills.childElementCount) identityBlock.appendChild(pills);
  header.appendChild(identityBlock);
  header.appendChild(gmEl("span", `character-state-pill gm-state-${model.state.tone}`, model.state.label));
  host.appendChild(header);

  if (model.blockers.length) {
    const attention = gmEl("section", "gm-attention");
    attention.appendChild(gmEl("strong", null, "This character needs your attention before it is ready."));
    const blocker = model.blockers.find(row => row && (row.message || row.title)) || {};
    attention.appendChild(gmEl("p", null, blocker.message ? `${blocker.title ? `${blocker.title}: ` : ""}${blocker.message}` : ownerDiagnosticMessage(blocker, "Resolve the saved owner decision.")));
    attention.appendChild(recoveryActionButton("Resolve in the builder", async () => { showScreen("builder"); await restoreGuidedActiveBuild(sheet.project_id, sheet.workflow?.active_run?.run_id); }, true));
    host.appendChild(attention);
  }

  // Left rail, as in the GM Screen viewer: avatar initials and the identity
  // lines, then the quick-stat tiles as a 2 x 3 block, with the tab list under
  // them.  The rail is built here; renderOwnerSheet places it beside the panel
  // column once the tabs exist.
  const rail = gmEl("aside", "owner-sheet-rail");
  const railSummary = gmEl("section", "owner-rail-summary");
  railSummary.appendChild(ownerRailPortrait(model, sheet));
  railSummary.appendChild(gmEl("h4", null, model.name || "Unnamed character"));
  railSummary.appendChild(gmEl("p", null, [model.pathLabel, model.foundationLabel, model.cl !== null && model.cl !== undefined ? `CL ${model.cl}` : null].filter(Boolean).join(" | ") || "Path and Foundation pending"));
  rail.appendChild(railSummary);

  // One quick-stat band.  The Overview tab no longer repeats these as tiles.
  const seenTileLabels = new Set();
  const bandTiles = model.tiles.filter(tile => {
    const label = String(tile.label || "").toLowerCase();
    if (!label || seenTileLabels.has(label)) return false;
    seenTileLabels.add(label);
    return true;
  });
  if (bandTiles.length) {
    const tiles = gmEl("div", "gm-tiles owner-rail-stats");
    for (const tile of bandTiles) {
      const el = gmEl("div", "gm-tile");
      if (tile.tooltip) {
        if (tile.id === "ac") {
          el.dataset.tip = tile.tooltip;
          // The compact AC card (SOL192); index.html exposes the shared renderer from tabletop/rules.js.
          if (tile.card) el.tipCard = (doc, options) => window.TianxiaRenderTipCard?.(doc, tile.card, options) || null;
          el.setAttribute("data-tip-click", "");
          el.tabIndex = 0;
          el.setAttribute("role", "button");
          el.setAttribute("aria-label", `Armor Class ${tile.value}. Show breakdown.`);
        } else el.title = tile.tooltip;
      }
      el.append(gmEl("span", "gm-tile-label", tile.label), gmEl("strong", "gm-tile-value", tile.value));
      tiles.appendChild(el);
    }
    rail.appendChild(tiles);
  }


  // The primary owner navigation is the stable 18-surface mechanics
  // contract plus the GM Guidance tab inserted before Diagnostics (below).
  const nav = gmEl("nav", "gm-tabstrip");
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-label", "Character sheet mechanics");
  const panelsWrap = gmEl("div", "gm-panels");
  const sheetTabs = Array.isArray(model.tabs) && model.tabs.length
    ? model.tabs
    : TianxiaSheetViewModel.COMPLETE_CHARACTER_SURFACE_IDS.map(id => ({
      id, label: TianxiaSheetViewModel.COMPLETE_CHARACTER_SURFACE_LABELS[id],
    }));
  // Owner 2026-09-23: GM guidance (Dao and I Ching,
  // training sources, advanced-art states) is its own tab, not a block under
  // every tab.
  const guidanceTab = {id: "gm_guidance", label: "GM Guidance"};
  const tabsWithGuidance = [];
  for (const tab of sheetTabs) {
    if (tab.id === "diagnostics") tabsWithGuidance.push(guidanceTab);
    tabsWithGuidance.push(tab);
  }
  if (!tabsWithGuidance.includes(guidanceTab)) tabsWithGuidance.push(guidanceTab);
  for (const tab of tabsWithGuidance) {
    const button = gmEl("button", "gm-tab-button", tab.label);
    button.type = "button";
    button.dataset.gmTab = tab.id;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", "false");
    button.setAttribute("aria-controls", `gmPanel-${tab.id}`);
    if (tab.available === false) button.dataset.gmAvailability = "unavailable";
    nav.appendChild(button);
    panelsWrap.appendChild(tab === guidanceTab
      ? gmBuildAuthoringPanel(model, sheet)
      : gmBuildCompleteCharacterSurfacePanel(model, sheet, tab.id));
  }
  // The vertical tab list is the same buttons, so the existing delegated click
  // and arrow-key handling keeps working; the horizontal strip stays in the DOM
  // as the accessible tablist and is hidden from view.
  const railTabs = gmEl("div", "owner-rail-tabs");
  railTabs.setAttribute("role", "presentation");
  for (const button of nav.querySelectorAll("[data-gm-tab]")) {
    const clone = button.cloneNode(true);
    clone.removeAttribute("aria-controls");
    clone.setAttribute("role", "presentation");
    clone.tabIndex = -1;
    clone.classList.add("owner-rail-tab");
    railTabs.appendChild(clone);
  }
  rail.appendChild(railTabs);

  const column = gmEl("div", "owner-sheet-column");
  column.append(nav, panelsWrap);
  host.append(rail, column);
  wireGmTabs(nav, panelsWrap);

  const advanced = document.createElement("details");
  advanced.className = "sheet-technical-details developer-diagnostics gm-advanced";
  const techSummary = document.createElement("summary"); techSummary.textContent = "Advanced / Developer: IDs, receipts, authority evidence, and raw records";
  const advancedBody = gmEl("div", "gm-advanced-body");
  const provenance = gmEl("div", "provenance-strip");
  for (const item of [sheet.provenance.owner_locks, sheet.provenance.ai_blueprint, sheet.provenance.advancement_projection, sheet.provenance.character_sheet_projection]) { if (!item) continue; const badge = document.createElement("div"); badge.className = `provenance-badge ${item.status}`; const strong = document.createElement("strong"); strong.textContent = item.label; const small = document.createElement("small"); small.textContent = item.status === "not_compiled" ? "Not compiled yet" : friendlyLabel(item.status); badge.append(strong, small); provenance.appendChild(badge); }
  advancedBody.appendChild(provenance);
  const technicalPre = gmEl("pre", null, pretty(buildOwnerSheetTechnicalSummary(sheet)));
  advancedBody.appendChild(technicalPre);
  if (sheet.sections && sheet.sections.diagnostics) {
    const diagDetails = document.createElement("details");
    diagDetails.className = "developer-diagnostics sheet-diagnostics-details";
    const diagSummary = document.createElement("summary"); diagSummary.textContent = "Developer / Diagnostics: Character Sheet checks";
    const diagBody = document.createElement("div");
    if (sheet.sections.diagnostics.data) appendReadableValue(diagBody, sheet.sections.diagnostics.data);
    diagDetails.append(diagSummary, diagBody);
    advancedBody.appendChild(diagDetails);
  }
  // The generated sheet is ~19 MB.  An index is what a reader can use here;
  // each tab's Technical disclosure already carries that tab's raw surface.
  const rawSections = gmEl("details", "developer-diagnostics");
  const rawSectionsSummary = document.createElement("summary");
  rawSectionsSummary.textContent = "Generated sheet section index";
  const rawIndexLines = [];
  for (const [key, value] of Object.entries(sheet.sections || {})) {
    const label = (value && (value.label || value.status)) || "";
    let bytes = 0;
    try {
      bytes = JSON.stringify(value && value.data !== undefined ? value.data : value).length;
    } catch (_error) {
      bytes = 0;
    }
    rawIndexLines.push(`${key} — ${label ? `${label} · ` : ""}${bytes.toLocaleString()} characters`);
  }
  rawSections.append(
    rawSectionsSummary,
    gmInfoCard("Section index", rawIndexLines.length ? rawIndexLines : ["No generated section was recorded."]),
  );
  rawSections.open = false;
  advancedBody.appendChild(rawSections);
  if (sheet.advanced_details) {
    const advancedNested = document.createElement("details");
    advancedNested.className = "developer-diagnostics";
    const advancedNestedSummary = document.createElement("summary");
    advancedNestedSummary.textContent = "Advanced detail record (large)";
    advancedNested.append(advancedNestedSummary, gmEl("pre", null, pretty(sheet.advanced_details)));
    advancedNested.open = false;
    advancedBody.appendChild(advancedNested);
  }
  advanced.append(techSummary, advancedBody);
  host.appendChild(advanced);

  const exportPanel = document.getElementById("gmExportPanel"); exportPanel.hidden = false;
  const workspace = sheet.factory_workspace || {status: "NOT_ATTEMPTED"};
  const workspaceComplete = workspace.status === "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE";
  const workspaceRebuildPending = workspace.provider_free_rebuild_available === true;
  if (workspaceRebuildPending) gmAuthoringRatificationChallenge = null;
  const gmAuthoringProvisional = workspace.gm_authoring === "PROVISIONAL_GM_GUIDANCE_ONLY";
  const gmAuthoringActual = workspace.gm_authoring === "ACTUAL_GM_AUTHORING";
  const gmCandidateReady = workspace.command5 === "GM_MODEL_CANDIDATE_READY";
  document.getElementById("factoryWorkspaceExplanation").textContent = gmCandidateReady
    ? "The Character/GM Command 5 candidate and schema-valid GM model candidate are sealed. GM Screen consumer verification has not been attempted, export remains unavailable, and combat execution remains untyped."
    : workspaceRebuildPending
    ? "Actual model-authored GM guidance is stored in a verified receipt, but its provider-free Factory workspace rebuild is pending. Rebuild the workspace before owner ratification or Command 5."
    : gmAuthoringProvisional
    ? "Project-derived GM guidance is provisional. Actual model authorship, source binding, and owner ratification are required before Command 5."
    : gmAuthoringActual
    ? "Actual model-authored GM guidance is bound to its source artifact. Owner ratification and the separately authorized Command 5 checkpoint remain pending."
    : workspaceComplete
    ? "GM tactical authoring is complete and the deterministic Factory Command 1–4 input workspace is prepared for a separately authorized Command 5 checkpoint. GM Screen verification and combat execution remain unattempted."
    : workspace.status === "STALE"
      ? "The prior Factory workspace is stale and must be rebuilt before later compilation."
      : "Prepare source-backed training sources, Dao and I Ching guidance, and a descriptive AI behavior profile. This does not run Command 5 or Command 6.";
  const workspaceButton = document.getElementById("prepareFactoryWorkspace");
  workspaceButton.disabled = (!workspaceRebuildPending && workspaceComplete) || sheet.build_status !== "CHARACTER_SHEET_READY";
  workspaceButton.textContent = workspaceRebuildPending
    ? "Rebuild Command 1–4 workspace"
    : workspaceComplete
    ? (gmAuthoringProvisional ? "Provisional GM Guidance Prepared" : "Command 1–4 Workspace Prepared")
    : "Prepare Command 1–4 Workspace";
  const authorButton = document.getElementById("authorGmTactical");
  if (authorButton) {
    authorButton.disabled = sheet.build_status !== "CHARACTER_SHEET_READY";
    authorButton.textContent = gmAuthoringActual ? "Re-author GM guidance with Local AI" : "Author GM guidance with Local AI";
  }
  const challengeButton = document.getElementById("issueGmRatificationChallenge");
  if (challengeButton) challengeButton.disabled = !gmAuthoringActual || workspaceRebuildPending || workspace.gm_owner_ratified === true;
  const ratifyButton = document.getElementById("ratifyGmAuthoring");
  if (ratifyButton) ratifyButton.disabled = !gmAuthoringRatificationChallenge || workspaceRebuildPending || workspace.gm_owner_ratified === true;
  document.getElementById("factoryWorkspaceResult").textContent = gmCandidateReady
    ? "Character Sheet Ready · GM tactical authoring complete · Character/GM candidate built · GM Screen verification pending · Export unavailable · Combat not typed."
    : workspaceRebuildPending
    ? "Character Sheet Ready · Actual GM guidance is stored · Provider-free workspace rebuild pending · Owner ratification remains unavailable until rebuild."
    : gmAuthoringProvisional
    ? "Character Sheet Ready · Provisional GM guidance prepared · Actual model authorship and owner ratification pending · Export unavailable."
    : gmAuthoringActual
    ? "Character Sheet Ready · Actual GM authoring bound · Owner ratification and Command 5 pending · Export unavailable."
    : workspaceComplete
    ? "Character Sheet Ready · GM tactical authoring complete · Factory workspace prepared for Command 5 · GM Screen not verified · Combat not typed."
    : "GM tactical authoring has not been prepared.";
  document.getElementById("gmExportExplanation").textContent = sheet.gm_export.available ? "GM Screen source verification passed. Export one Character ZIP that can be dragged into either the Factory or the bundled GM Screen. Native owner acceptance remains pending." : `${sheet.gm_export.blockers.join(" ")} ${sheet.gm_export.next_step || "GM authoring is the next step."}`;
  const button = document.getElementById("gmExportCharacter"); button.disabled = !sheet.gm_export.available;
  document.getElementById("gmExportDownload").hidden = true;
  document.getElementById("gmExportResult").textContent = sheet.gm_export.available ? "Character Sheet Ready · GM Model Built · GM Screen Source Verified · Character ZIP Ready · Native acceptance pending · Combat pending." : gmCandidateReady ? "GM model candidate built; Command 6 consumer verification has not been run, so export remains unavailable." : gmAuthoringProvisional ? "Project-derived GM guidance is provisional; actual model authorship and owner ratification are required before export." : gmAuthoringActual ? "Actual GM authoring is bound; owner ratification and Command 5 remain pending, so export remains unavailable." : workspaceComplete ? "Command 5 and Command 6 have not been run. GM export remains unavailable." : "Character Sheet complete; GM authoring and export have not been attempted.";
}

function setSelectedCharacterWorkspaceVisible(visible) {
  for (const id of ["nonSphereAuthorityPanel", "ownerWorkflowPanel"]) {
    const panel = document.getElementById(id);
    if (panel) panel.hidden = !visible;
  }
}

function renderOwnerSheetPending() {
  // In-geometry loading state: keeps the viewer panel present without
  // inventing data while the sheet request is in flight.
  const host = document.getElementById("ownerCharacterSheet");
  if (!host) return;
  clearNode(host);
  const shell = gmEl("div", "gm-loading");
  shell.appendChild(gmEl("p", "gm-loading-line", "Opening this character's sheet..."));
  for (let index = 0; index < 3; index += 1) shell.appendChild(gmEl("div", "gm-skeleton"));
  host.appendChild(shell);
}

const FINAL_CHARACTER_REVIEW_COMPONENTS = Object.freeze([
  {id: "command4", label: "Command 4 Actions", summary: "Validated Command 4 Actions workspace"},
  {id: "composite_controller", label: "Composite controller", summary: "Validated default Composite controller"},
]);
const FINAL_CHARACTER_REVIEW_COMPONENT_IDS = new Set(FINAL_CHARACTER_REVIEW_COMPONENTS.map(component => component.id));
const FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA = "TianxiaFoundry.FinalCharacterReviewPreview.v1";
const FINAL_CHARACTER_REVIEW_CHALLENGE_SCHEMA = "TianxiaFoundry.FinalCharacterReviewApprovalChallenge.v1";
const FINAL_CHARACTER_REVIEW_SUMMARY_SCHEMA = "TianxiaFoundry.FinalCharacterReviewSummary.v1";
const FINAL_CHARACTER_REVIEW_MATERIALIZATION_SCHEMA = "TianxiaFoundry.FinalCharacterMaterializationSummary.v1";
const FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA = "TianxiaFoundry.FinalCharacterReviewedBinding.v2";
const FINAL_CHARACTER_CONSTRUCTED_IMMORTAL_ART_BINDING_SCHEMA = "TianxiaFoundry.ConstructedImmortalArtBinding.v1";
const FINAL_CHARACTER_CONSTRUCTED_IMMORTAL_ART_KEYS = Object.freeze([
  "immortal_art_id", "name", "cl_created", "action_id", "art_sha256", "action_sha256",
]);
const FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION = "final_character_reviewed_overlay_pair.approve";
const FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE = "final_character_reviewed_overlay_pair";
const FINAL_CHARACTER_REVIEW_BINDING_KEYS = Object.freeze([
  "schema_version", "project_id", "candidate_sha256", "projection_id",
  "source_workspace_sha256", "composite_overlay", "constructed_immortal_arts", "binding_sha256",
]);
const FINAL_CHARACTER_REVIEW_OVERLAY_KEYS = Object.freeze([
  "overlay_id", "artifact_sha256", "overlay_tree_sha256", "files_tree_sha256",
]);
const FINAL_CHARACTER_REVIEW_RECEIPT_KEYS = Object.freeze([
  "receipt_id", "receipt_sha256", "component", "project_id", "overlay_id",
  "artifact_sha256", "overlay_tree_sha256", "files_tree_sha256", "candidate_sha256",
  "projection_id", "source_workspace_sha256", "request_sha256", "response_sha256",
]);
const FINAL_CHARACTER_REVIEW_DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const FINAL_CHARACTER_REVIEW_PROJECT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
const FINAL_CHARACTER_REVIEW_IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$/;
const FINAL_CHARACTER_REVIEW_RECEIPT_PATTERN = /^component\.(command4|composite_controller)\.[0-9a-f]{64}$/;
const FINAL_CHARACTER_REVIEW_RECORD_PATTERN = /^final-review\.[0-9a-f]{64}$/;
const FINAL_CHARACTER_REVIEW_BINDING_OVERLAY_BY_COMPONENT = Object.freeze({
  composite_controller: "composite_overlay",
});
let finalCharacterReviewRequestSerial = 0;
let finalCharacterReviewOperationSerial = 0;
let finalCharacterReviewState = {
  projectId: null,
  requestSerial: 0,
  operationSerial: 0,
  panelVisible: false,
  preview: null,
  previewValidation: null,
  challenge: null,
  approval: null,
  materialization: null,
  busy: false,
  previewLoading: false,
  error: null,
};

function resetFinalCharacterReviewState(projectId = null) {
  finalCharacterReviewRequestSerial += 1;
  finalCharacterReviewOperationSerial += 1;
  finalCharacterReviewState = {
    projectId,
    requestSerial: finalCharacterReviewRequestSerial,
    operationSerial: finalCharacterReviewOperationSerial,
    panelVisible: false,
    preview: null,
    previewValidation: null,
    challenge: null,
    approval: null,
    materialization: null,
    busy: false,
    previewLoading: false,
    error: null,
  };
  const panel = document.getElementById("finalCharacterReviewPanel");
  if (panel) panel.hidden = true;
  renderFinalCharacterReviewPanel();
  return finalCharacterReviewState.requestSerial;
}

function finalCharacterReviewBeginOperation() {
  finalCharacterReviewOperationSerial += 1;
  finalCharacterReviewState.operationSerial = finalCharacterReviewOperationSerial;
  return finalCharacterReviewState.operationSerial;
}

function finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial) {
  return finalCharacterReviewState.projectId === projectId
    && finalCharacterReviewState.requestSerial === requestSerial
    && selectedProject === projectId
    && (operationSerial === undefined || finalCharacterReviewState.operationSerial === operationSerial);
}

function finalCharacterReviewIsRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function finalCharacterReviewHasKeys(value, required, optional = []) {
  if (!finalCharacterReviewIsRecord(value)) return false;
  const allowed = new Set([...required, ...optional]);
  const actual = Object.keys(value);
  return required.every(key => Object.prototype.hasOwnProperty.call(value, key))
    && actual.every(key => allowed.has(key));
}

function finalCharacterReviewSafeProjectId(value) {
  return typeof value === "string" && FINAL_CHARACTER_REVIEW_PROJECT_PATTERN.test(value);
}

function finalCharacterReviewSafeIdentifier(value) {
  return typeof value === "string" && FINAL_CHARACTER_REVIEW_IDENTIFIER_PATTERN.test(value);
}

function finalCharacterReviewDigest(value) {
  return typeof value === "string" && FINAL_CHARACTER_REVIEW_DIGEST_PATTERN.test(value);
}

function finalCharacterReviewOptionalDigest(value) {
  return value === null || value === undefined || finalCharacterReviewDigest(value);
}

function finalCharacterReviewTimestamp(value) {
  return typeof value === "string"
    && value.length <= 64
    && !/[\u0000\r\n]/.test(value)
    && Number.isFinite(Date.parse(value));
}

function finalCharacterReviewCanonicalJson(value) {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new Error("The reviewed binding contains an unsupported scalar.");
    return encoded;
  }
  if (Array.isArray(value)) return `[${value.map(item => finalCharacterReviewCanonicalJson(item)).join(",")}]`;
  if (finalCharacterReviewIsRecord(value)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${finalCharacterReviewCanonicalJson(value[key])}`).join(",")}}`;
  }
  throw new Error("The reviewed binding contains an unsupported value.");
}

async function finalCharacterReviewSha256(value) {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.subtle?.digest || typeof globalThis.TextEncoder !== "function") return null;
  const bytes = new globalThis.TextEncoder().encode(finalCharacterReviewCanonicalJson(value));
  const digest = await cryptoApi.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function finalCharacterReviewBindingShape(binding, projectId) {
  if (!finalCharacterReviewHasKeys(binding, FINAL_CHARACTER_REVIEW_BINDING_KEYS)
    || binding.schema_version !== FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA
    || !finalCharacterReviewSafeProjectId(binding.project_id)
    || binding.project_id !== projectId
    || !finalCharacterReviewDigest(binding.candidate_sha256)
    || !finalCharacterReviewSafeIdentifier(binding.projection_id)
    || !finalCharacterReviewDigest(binding.source_workspace_sha256)
    || !finalCharacterReviewDigest(binding.binding_sha256)) return null;
  const overlay = binding.composite_overlay;
  if (!finalCharacterReviewHasKeys(overlay, FINAL_CHARACTER_REVIEW_OVERLAY_KEYS)
    || !finalCharacterReviewSafeIdentifier(overlay.overlay_id)
    || !finalCharacterReviewDigest(overlay.artifact_sha256)
    || !finalCharacterReviewDigest(overlay.overlay_tree_sha256)
    || !finalCharacterReviewDigest(overlay.files_tree_sha256)) return null;
  const arts = binding.constructed_immortal_arts;
  if (!finalCharacterReviewHasKeys(arts, ["schema_version", "arts", "binding_sha256"])
    || arts.schema_version !== FINAL_CHARACTER_CONSTRUCTED_IMMORTAL_ART_BINDING_SCHEMA
    || !Array.isArray(arts.arts)
    || !finalCharacterReviewDigest(arts.binding_sha256)) return null;
  for (const art of arts.arts) {
    if (!finalCharacterReviewHasKeys(art, FINAL_CHARACTER_CONSTRUCTED_IMMORTAL_ART_KEYS)
      || !finalCharacterReviewSafeIdentifier(art.immortal_art_id)
      || typeof art.name !== "string" || !art.name.trim()
      || !Number.isInteger(art.cl_created) || art.cl_created < 15
      || !finalCharacterReviewSafeIdentifier(art.action_id)
      || !finalCharacterReviewDigest(art.art_sha256)
      || !finalCharacterReviewDigest(art.action_sha256)) return null;
  }
  return binding;
}

async function finalCharacterReviewValidatedBinding(binding, projectId) {
  const shaped = finalCharacterReviewBindingShape(binding, projectId);
  if (!shaped) return null;
  const unsigned = {};
  for (const key of [...FINAL_CHARACTER_REVIEW_BINDING_KEYS].sort()) {
    if (key !== "binding_sha256") unsigned[key] = shaped[key];
  }
  const expected = await finalCharacterReviewSha256(unsigned);
  return expected && expected === shaped.binding_sha256 ? shaped : null;
}

function finalCharacterReviewReceipts(preview, binding = null) {
  if (!preview || preview.status !== "READY_FOR_OWNER_APPROVAL" || preview.available !== true) return null;
  if (!finalCharacterReviewSafeProjectId(preview.project_id)
    || !Array.isArray(preview.components)
    || preview.components.length !== FINAL_CHARACTER_REVIEW_COMPONENTS.length) return null;
  const reviewedBinding = binding || finalCharacterReviewBindingShape(preview.binding, preview.project_id);
  if (!reviewedBinding) return null;
  const byId = new Map();
  for (const receipt of preview.components) {
    if (!finalCharacterReviewHasKeys(receipt, FINAL_CHARACTER_REVIEW_RECEIPT_KEYS)
      || receipt.project_id !== preview.project_id
      || !FINAL_CHARACTER_REVIEW_RECEIPT_PATTERN.test(receipt.receipt_id)
      || !finalCharacterReviewDigest(receipt.receipt_sha256)
      || !FINAL_CHARACTER_REVIEW_COMPONENT_IDS.has(receipt.component)
      || !finalCharacterReviewSafeIdentifier(receipt.overlay_id)
      || !finalCharacterReviewDigest(receipt.artifact_sha256)
      || !finalCharacterReviewDigest(receipt.overlay_tree_sha256)
      || !finalCharacterReviewDigest(receipt.files_tree_sha256)
      || !finalCharacterReviewOptionalDigest(receipt.candidate_sha256)
      || (receipt.projection_id !== null && receipt.projection_id !== undefined && !finalCharacterReviewSafeIdentifier(receipt.projection_id))
      || !finalCharacterReviewOptionalDigest(receipt.source_workspace_sha256)
      || !finalCharacterReviewOptionalDigest(receipt.request_sha256)
      || !finalCharacterReviewOptionalDigest(receipt.response_sha256)
      || byId.has(receipt.component)
      || !receipt.receipt_id.startsWith(`component.${receipt.component}.`)) return null;
    for (const field of ["candidate_sha256", "projection_id", "source_workspace_sha256"]) {
      if (receipt[field] !== undefined && receipt[field] !== null && receipt[field] !== reviewedBinding[field]) return null;
    }
    const bindingOverlayName = FINAL_CHARACTER_REVIEW_BINDING_OVERLAY_BY_COMPONENT[receipt.component];
    if (bindingOverlayName) {
      const overlay = reviewedBinding[bindingOverlayName];
      for (const field of ["overlay_id", "artifact_sha256", "overlay_tree_sha256", "files_tree_sha256"]) {
        if (receipt[field] !== overlay[field]) return null;
      }
    }
    byId.set(receipt.component, receipt);
  }
  const ordered = FINAL_CHARACTER_REVIEW_COMPONENTS.map(component => byId.get(component.id));
  return ordered.every(Boolean) ? ordered : null;
}

async function finalCharacterReviewValidatePreview(preview, projectId) {
  if (!finalCharacterReviewIsRecord(preview)
    || preview.schema_version !== FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA
    || preview.project_id !== projectId
    || !finalCharacterReviewSafeProjectId(preview.project_id)
    || preview.provider_calls !== 0) return null;
  if (preview.status === "NOT_READY") {
    return preview.available === false && finalCharacterReviewHasKeys(preview, ["schema_version", "project_id", "status", "available", "provider_calls", "details"])
      ? {binding: null, receipts: null}
      : null;
  }
  if (preview.status !== "READY_FOR_OWNER_APPROVAL"
    || preview.available !== true
    || !finalCharacterReviewHasKeys(preview, ["schema_version", "project_id", "status", "available", "provider_calls", "binding", "components"])) return null;
  const binding = await finalCharacterReviewValidatedBinding(preview.binding, projectId);
  const receipts = binding ? finalCharacterReviewReceipts(preview, binding) : null;
  return binding && receipts ? {binding, receipts} : null;
}

function finalCharacterReviewReady() {
  return Boolean(finalCharacterReviewState.preview
    && finalCharacterReviewState.previewValidation?.receipts
    && finalCharacterReviewState.preview.project_id === finalCharacterReviewState.projectId);
}

function finalCharacterReviewContextMatchesPreview(context, preview) {
  if (context === undefined || context === null) return true;
  const contextKeys = [
    "schema_version", "operation", "subject_type", "subject_id", "project_id",
    "candidate_sha256", "projection_id", "source_workspace_sha256", "binding_sha256",
  ];
  if (!finalCharacterReviewHasKeys(context, contextKeys)) return false;
  const binding = preview?.binding;
  const expected = {
    schema_version: "TianxiaFoundry.FinalCharacterReviewApprovalContext.v1",
    project_id: preview?.project_id,
    candidate_sha256: binding?.candidate_sha256,
    projection_id: binding?.projection_id,
    source_workspace_sha256: binding?.source_workspace_sha256,
    binding_sha256: binding?.binding_sha256,
    project_lock_hash: binding?.source_workspace_sha256,
    operation: FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION,
    subject_type: FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE,
    subject_id: binding?.binding_sha256,
  };
  for (const [field, value] of Object.entries(expected)) {
    if (Object.prototype.hasOwnProperty.call(context, field) && context[field] !== value) return false;
  }
  return true;
}

function finalCharacterReviewOptionalCorrelationMatches(result, preview) {
  if (!finalCharacterReviewIsRecord(result)) return false;
  const binding = preview?.binding;
  for (const field of ["project_id", "binding_sha256"]) {
    if (Object.prototype.hasOwnProperty.call(result, field) && result[field] !== (field === "project_id" ? preview.project_id : binding?.binding_sha256)) return false;
  }
  for (const field of ["binding", "reviewed_binding"]) {
    if (Object.prototype.hasOwnProperty.call(result, field)) {
      if (!finalCharacterReviewIsRecord(result[field]) || finalCharacterReviewCanonicalJson(result[field]) !== finalCharacterReviewCanonicalJson(binding)) return false;
    }
  }
  return finalCharacterReviewContextMatchesPreview(result.context, preview)
    && finalCharacterReviewContextMatchesPreview(result.evidence_context, preview);
}

async function finalCharacterReviewValidChallenge(result, preview, projectId) {
  const required = ["schema_version", "project_id", "status", "provider_calls", "challenge"];
  const envelopeKeys = ["challenge_id", "challenge_hash", "operation", "subject_type", "subject_id", "exact_bytes_hash", "binding_hash", "project_lock_hash", "issued_at", "expires_at", "nonce"];
  const challenge = result?.challenge;
  if (!finalCharacterReviewHasKeys(result, required, ["binding", "binding_sha256", "context", "evidence_context"])
    || result.schema_version !== FINAL_CHARACTER_REVIEW_CHALLENGE_SCHEMA
    || result.project_id !== projectId
    || result.status !== "ISSUED"
    || result.provider_calls !== 0
    || !finalCharacterReviewHasKeys(challenge, envelopeKeys, ["binding", "binding_sha256", "context", "evidence_context"])
    || !finalCharacterReviewSafeIdentifier(challenge.challenge_id)
    || !finalCharacterReviewSafeIdentifier(challenge.nonce)
    || !finalCharacterReviewDigest(challenge.challenge_hash)
    || challenge.operation !== FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION
    || challenge.subject_type !== FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE
    || challenge.subject_id !== preview?.binding?.binding_sha256
    || challenge.project_lock_hash !== preview?.binding?.source_workspace_sha256
    || !finalCharacterReviewTimestamp(challenge.issued_at)
    || !finalCharacterReviewTimestamp(challenge.expires_at)) return false;
  const issued = Date.parse(challenge.issued_at);
  const expires = Date.parse(challenge.expires_at);
  if (!Number.isFinite(issued) || !Number.isFinite(expires) || expires <= issued) return false;
  const fullBindingHash = await finalCharacterReviewSha256(preview.binding);
  if (!fullBindingHash || challenge.exact_bytes_hash !== fullBindingHash || challenge.binding_hash !== fullBindingHash) return false;
  return finalCharacterReviewOptionalCorrelationMatches(result, preview)
    && finalCharacterReviewOptionalCorrelationMatches(challenge, preview);
}

function finalCharacterReviewValidApproval(result, preview, projectId, challenge) {
  if (!finalCharacterReviewHasKeys(result, ["schema_version", "project_id", "status", "provider_calls", "challenge_id", "evidence_id", "review_record_id", "record_sha256", "binding_sha256"], ["binding", "reviewed_binding", "context", "evidence_context"])
    || result.schema_version !== FINAL_CHARACTER_REVIEW_SUMMARY_SCHEMA
    || result.project_id !== projectId
    || result.status !== "APPROVED"
    || result.provider_calls !== 0
    || result.challenge_id !== challenge?.challenge?.challenge_id
    || !finalCharacterReviewSafeIdentifier(result.evidence_id)
    || !FINAL_CHARACTER_REVIEW_RECORD_PATTERN.test(result.review_record_id)
    || !finalCharacterReviewDigest(result.record_sha256)
    || result.binding_sha256 !== preview?.binding?.binding_sha256) return false;
  return finalCharacterReviewOptionalCorrelationMatches(result, preview);
}

function finalCharacterReviewValidMaterialization(result, preview, projectId, reviewRecordId) {
  if (!finalCharacterReviewHasKeys(result, ["schema_version", "project_id", "status", "provider_calls", "idempotent", "review_record_id", "materialization_id", "binding_sha256", "output_tree_sha256"], ["binding", "reviewed_binding", "context", "evidence_context"])
    || result.schema_version !== FINAL_CHARACTER_REVIEW_MATERIALIZATION_SCHEMA
    || result.project_id !== projectId
    || !["MATERIALIZED", "ALREADY_MATERIALIZED"].includes(result.status)
    || result.provider_calls !== 0
    || typeof result.idempotent !== "boolean"
    || (result.status === "MATERIALIZED" && result.idempotent !== false)
    || (result.status === "ALREADY_MATERIALIZED" && result.idempotent !== true)
    || result.review_record_id !== reviewRecordId
    || !finalCharacterReviewSafeIdentifier(result.materialization_id)
    || result.binding_sha256 !== preview?.binding?.binding_sha256
    || !finalCharacterReviewDigest(result.output_tree_sha256)) return false;
  return finalCharacterReviewOptionalCorrelationMatches(result, preview);
}

function finalCharacterReviewBoundedMissingDetails(preview) {
  const missing = Array.isArray(preview?.details?.missing)
    ? preview.details.missing.filter(item => FINAL_CHARACTER_REVIEW_COMPONENT_IDS.has(item))
    : [];
  if (!missing.length) return "The three sealed component receipts are not all available yet.";
  const labels = FINAL_CHARACTER_REVIEW_COMPONENTS.filter(component => missing.includes(component.id)).map(component => component.label);
  return `Waiting for ${labels.join(", ")}. Nothing has been changed.`;
}

function finalCharacterReviewSafeChallenge(challenge) {
  const envelope = challenge?.challenge;
  if (!envelope || typeof envelope !== "object") return null;
  return {
    challenge_id: envelope.challenge_id,
    challenge_hash: envelope.challenge_hash,
    operation: envelope.operation,
    subject_type: envelope.subject_type,
    subject_id: envelope.subject_id,
    exact_bytes_hash: envelope.exact_bytes_hash,
    binding_hash: envelope.binding_hash,
    project_lock_hash: envelope.project_lock_hash,
    issued_at: envelope.issued_at,
    expires_at: envelope.expires_at,
  };
}

function finalCharacterReviewTechnicalSnapshot() {
  const state = finalCharacterReviewState;
  return {
    project_id: state.projectId,
    preview_status: state.preview?.status || null,
    provider_calls: state.preview?.provider_calls ?? 0,
    binding: state.preview?.binding || null,
    components: state.preview?.components || [],
    challenge: finalCharacterReviewSafeChallenge(state.challenge),
    approval: state.approval || null,
    materialization: state.materialization || null,
  };
}

function finalCharacterReviewChallengeExpired() {
  const expiresAt = finalCharacterReviewState.challenge?.challenge?.expires_at;
  if (!expiresAt) return true;
  const expires = Date.parse(expiresAt);
  return !Number.isFinite(expires) || Date.now() >= expires;
}

function finalCharacterReviewClearDownstream(message = null, {clearPreview = true} = {}) {
  finalCharacterReviewState.challenge = null;
  finalCharacterReviewState.approval = null;
  finalCharacterReviewState.materialization = null;
  finalCharacterReviewState.busy = false;
  finalCharacterReviewState.previewLoading = false;
  finalCharacterReviewState.error = message;
  if (clearPreview) {
    finalCharacterReviewState.preview = null;
    finalCharacterReviewState.previewValidation = null;
  }
  renderFinalCharacterReviewPanel();
}

function finalCharacterReviewStatusText(statusNode, text, state = "") {
  if (!statusNode) return;
  statusNode.textContent = text;
  statusNode.dataset.state = state;
}

function finalCharacterReviewRenderReceiptCards(host, receipts, binding = null) {
  const cards = document.createElement("div");
  cards.className = "final-character-review-receipts";
  for (const component of FINAL_CHARACTER_REVIEW_COMPONENTS) {
    const card = document.createElement("article");
    card.className = "final-character-review-receipt";
    card.dataset.component = component.id;
    card.append(
      gmEl("h4", null, component.label),
      gmEl("p", null, component.summary),
      gmEl("span", "receipt-state", "Sealed receipt present"),
    );
    cards.appendChild(card);
  }
  const arts = binding?.constructed_immortal_arts?.arts;
  if (Array.isArray(arts)) {
    // Immortal Arts are built by the creative controller inside the sealed
    // character; the review shows the rules-checked Arts it will compile.
    const card = document.createElement("article");
    card.className = "final-character-review-receipt";
    card.dataset.component = "immortal_arts";
    card.append(
      gmEl("h4", null, "Immortal Arts"),
      gmEl("p", null, arts.length
        ? arts.map(art => `${art.name} (CL ${art.cl_created})`).join("; ")
        : "None: the character is below CL 15."),
      gmEl("span", "receipt-state", "Rules-checked in the sealed character"),
    );
    cards.appendChild(card);
  }
  host.appendChild(cards);
  return receipts;
}

function renderFinalCharacterReviewPanel() {
  const panel = document.getElementById("finalCharacterReviewPanel");
  if (!panel) return;
  const state = finalCharacterReviewState;
  panel.hidden = !state.panelVisible || !state.projectId;
  const statusNode = document.getElementById("finalCharacterReviewStatus");
  const previewHost = document.getElementById("finalCharacterReviewPreview");
  const issueButton = document.getElementById("finalCharacterReviewIssueChallenge");
  const challengeStatus = document.getElementById("finalCharacterReviewChallengeStatus");
  const approvalStage = document.getElementById("finalCharacterReviewApprovalStage");
  const approvalConfirm = document.getElementById("finalCharacterReviewApprovalConfirm");
  const approveButton = document.getElementById("finalCharacterReviewApprove");
  const approvalStatus = document.getElementById("finalCharacterReviewApprovalStatus");
  const materializeStage = document.getElementById("finalCharacterReviewMaterializeStage");
  const materializeConfirm = document.getElementById("finalCharacterReviewMaterializeConfirm");
  const materializeButton = document.getElementById("finalCharacterReviewMaterialize");
  const materializeStatus = document.getElementById("finalCharacterReviewMaterializeStatus");
  const advanced = document.getElementById("finalCharacterReviewAdvanced");
  const technical = document.getElementById("finalCharacterReviewTechnical");
  if (previewHost) clearNode(previewHost);
  if (challengeStatus) challengeStatus.textContent = "";
  if (approvalStatus) approvalStatus.textContent = "";
  if (materializeStatus) materializeStatus.textContent = "";
  if (!state.projectId) {
    finalCharacterReviewStatusText(statusNode, "Select a character", "");
    if (issueButton) issueButton.disabled = true;
    if (approvalStage) approvalStage.hidden = true;
    if (materializeStage) materializeStage.hidden = true;
    if (approvalConfirm) { approvalConfirm.checked = false; approvalConfirm.disabled = true; }
    if (approveButton) approveButton.disabled = true;
    if (materializeConfirm) { materializeConfirm.checked = false; materializeConfirm.disabled = true; }
    if (materializeButton) materializeButton.disabled = true;
    if (advanced) advanced.hidden = true;
    if (technical) technical.textContent = "";
    return;
  }
  if (state.previewLoading) {
    finalCharacterReviewStatusText(statusNode, "Checking exact readiness…", "working");
    if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty", "Checking the selected character's current sealed inputs. No provider call or mutation is made."));
  } else if (state.error) {
    finalCharacterReviewStatusText(statusNode, "Review unavailable", "error");
    if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty error", state.error));
  } else if (!state.preview) {
    finalCharacterReviewStatusText(statusNode, "Preview unavailable", "error");
    if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty error", "A fresh preview is required before review controls are available."));
  } else if (state.preview.project_id !== state.projectId) {
    finalCharacterReviewStatusText(statusNode, "Review unavailable", "error");
    if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty error", "The preview did not match this selected character. Review controls remain disabled."));
  } else if (state.preview.status === "NOT_READY" || state.preview.available !== true) {
    finalCharacterReviewStatusText(statusNode, "Not ready", "warning");
    if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty", finalCharacterReviewBoundedMissingDetails(state.preview)));
  } else {
    const receipts = state.previewValidation?.receipts || null;
    if (!receipts) {
      finalCharacterReviewStatusText(statusNode, "Review unavailable", "error");
      if (previewHost) previewHost.appendChild(gmEl("p", "final-character-review-empty error", "The preview did not contain exactly three recognized component receipts. Review controls remain disabled."));
    } else {
      const binding = state.preview.binding || {};
      finalCharacterReviewStatusText(statusNode,
        state.materialization ? "Materialized" : state.approval ? "Approved" : state.challenge ? "Challenge issued" : "Ready to review",
        state.materialization ? "success" : state.approval ? "success" : state.challenge ? "warning" : "",
      );
      const summary = gmEl("p", "final-character-review-summary");
      summary.appendChild(gmEl("strong", null, "Exact binding ready for owner review"));
      summary.appendChild(gmEl("span", null, `Project ${state.projectId} is bound to one candidate, one projection, and one Command 4 workspace. Both component receipts are present and the Immortal Arts are rules-checked; provider calls: ${state.preview.provider_calls ?? 0}.`));
      if (previewHost) {
        previewHost.appendChild(summary);
        finalCharacterReviewRenderReceiptCards(previewHost, receipts, state.previewValidation?.binding);
      }
      if (challengeStatus && state.challenge) {
        const expiresAt = state.challenge.challenge?.expires_at;
        const expires = expiresAt && Number.isFinite(Date.parse(expiresAt)) ? new Date(expiresAt).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : null;
        challengeStatus.textContent = expires ? `Challenge issued. It expires at ${expires}.` : "Challenge issued for this exact review.";
      }
      if (approvalStatus && state.approval) approvalStatus.textContent = "Approved. Materialization is still a separate owner action.";
      if (materializeStatus && state.materialization) {
        materializeStatus.textContent = state.materialization.status === "ALREADY_MATERIALIZED"
          ? "Already materialized. No additional output was written."
          : "Materialized successfully. The bounded result receipt is recorded below.";
      }
      if (technical) technical.textContent = pretty(finalCharacterReviewTechnicalSnapshot());
      if (advanced) advanced.hidden = false;
      if (issueButton) {
        issueButton.disabled = state.busy || Boolean(state.approval || state.materialization);
        issueButton.textContent = state.challenge ? "Issue a new 5-minute challenge" : "Issue 5-minute review challenge";
      }
      if (approvalStage) approvalStage.hidden = !state.challenge || Boolean(state.approval || state.materialization);
      if (approvalConfirm) {
        if (!state.challenge || state.approval) approvalConfirm.checked = false;
        approvalConfirm.disabled = state.busy || !state.challenge;
      }
      if (approveButton) approveButton.disabled = state.busy || !state.challenge || Boolean(state.approval) || !approvalConfirm?.checked;
      if (materializeStage) materializeStage.hidden = !state.approval || state.approval.status !== "APPROVED";
      if (materializeConfirm) {
        if (!state.approval) materializeConfirm.checked = false;
        materializeConfirm.disabled = state.busy || !state.approval || Boolean(state.materialization);
      }
      if (materializeButton) materializeButton.disabled = state.busy || !state.approval || state.approval.status !== "APPROVED" || Boolean(state.materialization) || !materializeConfirm?.checked;
      return;
    }
  }
  if (issueButton) issueButton.disabled = true;
  if (approvalStage) approvalStage.hidden = true;
  if (materializeStage) materializeStage.hidden = true;
  if (approvalConfirm) { approvalConfirm.checked = false; approvalConfirm.disabled = true; }
  if (approveButton) approveButton.disabled = true;
  if (materializeConfirm) { materializeConfirm.checked = false; materializeConfirm.disabled = true; }
  if (materializeButton) materializeButton.disabled = true;
  if (advanced) advanced.hidden = true;
  if (technical) technical.textContent = "";
}

async function loadFinalCharacterReviewPreview(projectId, requestSerial = finalCharacterReviewState.requestSerial) {
  if (!projectId || !finalCharacterReviewIsCurrent(projectId, requestSerial)) return;
  const operationSerial = finalCharacterReviewBeginOperation();
  finalCharacterReviewState.panelVisible = true;
  finalCharacterReviewState.preview = null;
  finalCharacterReviewState.previewValidation = null;
  finalCharacterReviewState.challenge = null;
  finalCharacterReviewState.approval = null;
  finalCharacterReviewState.materialization = null;
  finalCharacterReviewState.busy = true;
  finalCharacterReviewState.previewLoading = true;
  finalCharacterReviewState.error = null;
  renderFinalCharacterReviewPanel();
  try {
    const preview = await api(`/api/characters/${encodeURIComponent(projectId)}/factory-workspace/final-character/preview`);
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    const validation = await finalCharacterReviewValidatePreview(preview, projectId);
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial) || !validation) throw new Error("The preview did not contain a complete reviewed binding.");
    finalCharacterReviewState.preview = preview;
    finalCharacterReviewState.previewValidation = validation;
    finalCharacterReviewState.busy = false;
    finalCharacterReviewState.previewLoading = false;
    finalCharacterReviewState.error = null;
    renderFinalCharacterReviewPanel();
  } catch (_error) {
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    finalCharacterReviewClearDownstream("The exact preview could not be loaded. Reopen this character sheet to fetch a fresh preview.");
  }
}

async function issueFinalCharacterReviewChallenge() {
  const state = finalCharacterReviewState;
  const receipts = state.previewValidation?.receipts || null;
  if (state.busy || !state.projectId || selectedProject !== state.projectId || !receipts) return;
  const projectId = state.projectId;
  const requestSerial = state.requestSerial;
  const operationSerial = finalCharacterReviewBeginOperation();
  state.challenge = null;
  state.approval = null;
  state.materialization = null;
  state.busy = true;
  state.error = null;
  renderFinalCharacterReviewPanel();
  try {
    const result = await api(`/api/characters/${encodeURIComponent(projectId)}/factory-workspace/final-character/approval-challenge`, {
      method: "POST", body: JSON.stringify({ttl_seconds: 300}),
    });
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    if (!await finalCharacterReviewValidChallenge(result, state.preview, projectId)) throw new Error("The challenge response did not match this reviewed binding.");
    state.challenge = result;
    state.busy = false;
    state.error = null;
    renderFinalCharacterReviewPanel();
  } catch (_error) {
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    finalCharacterReviewClearDownstream("The review challenge could not be issued. Reopen this character sheet to fetch a fresh preview.");
  }
}

async function approveFinalCharacterReview() {
  const state = finalCharacterReviewState;
  if (state.busy || !state.projectId || selectedProject !== state.projectId || !state.challenge || !document.getElementById("finalCharacterReviewApprovalConfirm")?.checked) return;
  const projectId = state.projectId;
  const requestSerial = state.requestSerial;
  if (finalCharacterReviewChallengeExpired()) {
    finalCharacterReviewClearDownstream("This review challenge has expired. Reopen this character sheet to fetch a fresh preview and issue a new challenge.");
    return;
  }
  const envelope = state.challenge.challenge;
  const operationSerial = finalCharacterReviewBeginOperation();
  state.busy = true;
  state.error = null;
  renderFinalCharacterReviewPanel();
  try {
    const result = await api(`/api/characters/${encodeURIComponent(projectId)}/factory-workspace/final-character/approve`, {
      method: "POST", body: JSON.stringify({challenge_id: envelope.challenge_id, nonce: envelope.nonce}),
    });
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    if (!finalCharacterReviewValidApproval(result, state.preview, projectId, state.challenge)) throw new Error("The approval response did not match this issued challenge.");
    state.approval = result;
    state.busy = false;
    state.error = null;
    renderFinalCharacterReviewPanel();
  } catch (_error) {
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    finalCharacterReviewClearDownstream("Approval could not be completed safely. Reopen this character sheet to fetch a fresh preview and challenge.");
  }
}

async function materializeFinalCharacterReview() {
  const state = finalCharacterReviewState;
  if (state.busy || !state.projectId || selectedProject !== state.projectId || !state.approval || state.approval.status !== "APPROVED" || !document.getElementById("finalCharacterReviewMaterializeConfirm")?.checked) return;
  const projectId = state.projectId;
  const requestSerial = state.requestSerial;
  const reviewRecordId = state.approval.review_record_id;
  if (!reviewRecordId) return;
  const operationSerial = finalCharacterReviewBeginOperation();
  state.busy = true;
  state.error = null;
  renderFinalCharacterReviewPanel();
  try {
    const result = await api(`/api/characters/${encodeURIComponent(projectId)}/factory-workspace/final-character/materialize`, {
      method: "POST", body: JSON.stringify({review_record_id: reviewRecordId}),
    });
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    if (!finalCharacterReviewValidMaterialization(result, state.preview, projectId, reviewRecordId)) throw new Error("The materialization response did not match this approved review.");
    state.materialization = result;
    state.challenge = null;
    state.busy = false;
    state.error = null;
    renderFinalCharacterReviewPanel();
  } catch (_error) {
    if (!finalCharacterReviewIsCurrent(projectId, requestSerial, operationSerial)) return;
    finalCharacterReviewClearDownstream("Materialization could not be completed safely. Reopen this character sheet to fetch a fresh preview and approval.");
  }
}

function wireFinalCharacterReviewControls() {
  const issue = document.getElementById("finalCharacterReviewIssueChallenge");
  const approvalConfirm = document.getElementById("finalCharacterReviewApprovalConfirm");
  const approve = document.getElementById("finalCharacterReviewApprove");
  const materializeConfirm = document.getElementById("finalCharacterReviewMaterializeConfirm");
  const materialize = document.getElementById("finalCharacterReviewMaterialize");
  if (issue) issue.onclick = () => { void issueFinalCharacterReviewChallenge(); };
  if (approvalConfirm) approvalConfirm.onchange = () => renderFinalCharacterReviewPanel();
  if (approve) approve.onclick = () => { void approveFinalCharacterReview(); };
  if (materializeConfirm) materializeConfirm.onchange = () => renderFinalCharacterReviewPanel();
  if (materialize) materialize.onclick = () => { void materializeFinalCharacterReview(); };
}

wireFinalCharacterReviewControls();

async function openOwnerCharacterSheet(projectId, refreshNonSphere = true) {
  const requestGeneration = ++gmSheetRequestGeneration;
  invalidateNonSpherePanelActions();
  const finalReviewRequestSerial = resetFinalCharacterReviewState(projectId);
  renderOwnerSheetPending();
  try {
    const sheet = await api(`/api/characters/${encodeURIComponent(projectId)}/sheet`);
    try {
      sheet.gm_authoring_view = await api(`/api/characters/${encodeURIComponent(projectId)}/factory-workspace/view`);
    } catch (gmError) {
      sheet.gm_authoring_view = {
        available: false,
        workspace_status: "UNAVAILABLE",
        blockers: [plainAPIError(gmError, "GM guidance could not be loaded.")],
      };
    }
    if (requestGeneration !== gmSheetRequestGeneration || selectedProject !== projectId) return;
    setSelectedCharacterWorkspaceVisible(true);
    renderOwnerSheet(sheet);
    void loadFinalCharacterReviewPreview(projectId, finalReviewRequestSerial);
    if (refreshNonSphere) void loadNonSphereAuthorityPanel(projectId);
  } catch (error) {
    if (requestGeneration !== gmSheetRequestGeneration || selectedProject !== projectId) return;
    setSelectedCharacterWorkspaceVisible(false);
    const host = document.getElementById("ownerCharacterSheet");
    clearNode(host);
    const box = gmEl("section", "gm-error");
    box.appendChild(gmEl("strong", null, "The Factory could not open this character's sheet."));
    box.appendChild(gmEl("p", null, plainAPIError(error, "The character sheet could not be loaded.")));
    box.appendChild(recoveryActionButton("Try again", () => { void openOwnerCharacterSheet(projectId, refreshNonSphere); }, true));
    const technical = document.createElement("details");
    technical.className = "developer-diagnostics";
    const techSummary = document.createElement("summary");
    techSummary.textContent = "Technical details";
    technical.append(techSummary, gmEl("pre", null, String(error?.message || error)));
    box.appendChild(technical);
    host.appendChild(box);
  }
}

function ownerStageLabel(character) {
  const summary = String(character?.plain_summary || "").toLowerCase();
  const build = String(character?.build_status || "").toUpperCase();
  if (summary.includes("stage 1") || summary.includes("blueprint") || build.includes("STAGE1") || build.includes("BLUEPRINT")) return "Stage 1 Plan Sealed";
  return character?.lifecycle?.display_label || "Saved / existing";
}

function gmFormatCharacterCardTimestamp(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/.exec(normalized);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] || 0);
  const daysInMonth = [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1] || hour > 23 || minute > 59 || second > 59) return null;
  if (match[7] !== "Z" && (Number(match[7].slice(1, 3)) > 23 || Number(match[7].slice(4, 6)) > 59)) return null;
  const timestamp = Date.parse(normalized);
  if (!Number.isFinite(timestamp)) return null;
  return new Date(timestamp).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function gmCharacterCardTimestamp(character, listRow) {
  const lifecycle = character?.lifecycle || listRow?.lifecycle;
  if (lifecycle?.lifecycle_source === "owner_save_draft") {
    const saved = gmFormatCharacterCardTimestamp(lifecycle.updated_at);
    if (saved) return `Saved ${saved}`;
  }
  for (const value of [character?.updated_at, listRow?.updated_at]) {
    const updated = gmFormatCharacterCardTimestamp(value);
    if (updated) return `Last updated ${updated}`;
  }
  return null;
}

function gmCharacterCardDetail(character, listRow) {
  if (character.summary_pending) return "Character details are loading…";
  return [
    listRow?.path_summary || character.path_summary || listRow?.path || character.path,
    listRow?.current_cl ? `CL ${listRow.current_cl}` : listRow?.target_cl ? `Target CL ${listRow.target_cl}` : character.current_cl ? `CL ${character.current_cl}` : character.target_cl ? `Target CL ${character.target_cl}` : null,
    gmCharacterCardTimestamp(character, listRow),
  ].filter(Boolean).join(" · ") || character.plain_summary;
}

function gmRenderLibraryEnrichmentDiagnostic() {
  const host = document.getElementById("characterCardList");
  const existing = host.querySelector(".gm-library-enrichment-diagnostic");
  if (existing) existing.remove();
  if (!gmLibraryJoin.enrichmentError) return;
  const details = document.createElement("details");
  details.className = "developer-diagnostics gm-library-enrichment-diagnostic";
  const summary = document.createElement("summary");
  summary.textContent = "Advanced / Developer: optional character metadata unavailable";
  details.append(summary, gmEl("p", "gm-muted", "Saved characters remain available. Finalized-name and metadata enrichment can be retried with Refresh Characters."));
  details.appendChild(gmEl("pre", null, gmLibraryJoin.enrichmentError));
  host.appendChild(details);
}

// Durable per-project source version, when the payload reports one.
function gmLibrarySourceRevision(row) {
  const value = Number(row?.source_revision);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

// Optional enrichment is read on its own slower request, so a response can be
// older than the summary a background poll has already completed. Comparing the
// source version before writing keeps a slow read from undoing a newer fact.
function gmCharacterEnrichmentIsStale(listRow, libraryRow) {
  const enrichmentRevision = gmLibrarySourceRevision(listRow);
  const libraryRevision = gmLibrarySourceRevision(libraryRow);
  return enrichmentRevision !== null && libraryRevision !== null && enrichmentRevision < libraryRevision;
}

function gmApplyCharacterEnrichment(requestGeneration, rows) {
  if (requestGeneration !== gmLibraryRequestGeneration || !Array.isArray(rows)) return;
  gmLibraryJoin.characterListRows = new Map();
  for (const row of rows) {
    if (!row || !row.project_id) continue;
    if (gmCharacterEnrichmentIsStale(row, gmLibraryJoin.libraryRows.get(row.project_id))) continue;
    gmLibraryJoin.characterListRows.set(row.project_id, row);
  }
  gmLibraryJoin.enrichmentError = null;
  const host = document.getElementById("characterCardList");
  for (const card of host.querySelectorAll("[data-character-project-id]")) {
    const projectId = card.dataset.characterProjectId;
    const character = gmLibraryJoin.libraryRows.get(projectId);
    const listRow = gmLibraryJoin.characterListRows.get(projectId) || null;
    if (!character || !listRow) continue;
    const displayName = TianxiaSheetViewModel.resolveOwnerFinalName({
      characterListName: listRow.name,
      resolvedWorkflowName: ownerResolvedWorkflowName({workflow: character.workflow}),
      libraryName: character.name,
    }) || character.working_name || "Unnamed character in progress";
    const name = card.querySelector(".character-card-name");
    const detail = card.querySelector(".character-card-detail");
    const main = card.querySelector(".card-main");
    if (name) name.textContent = displayName;
    if (detail) detail.textContent = character.deletion_status
    ? character.deletion_reason || "Hidden from character lists and fight setup. You can undo delete until the Factory next restarts. A complete backup will be kept."
    : gmCharacterCardDetail(character, listRow);
    if (main) {
    if (character.deletion_status) {
      main.removeAttribute("role"); main.removeAttribute("tabindex"); main.removeAttribute("aria-label");
      main.onclick = null; main.onkeydown = null;
    } else {
      main.tabIndex = 0; main.setAttribute("role", "button");
      main.setAttribute("aria-label", `Open Character Sheet for ${displayName}`);
      main.onclick = () => gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card));
      main.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card)); } };
    }
  }
  }
  if (ownerCharacterSheet && selectedProject === ownerCharacterSheet.project_id) {
    const listRow = gmLibraryJoin.characterListRows.get(selectedProject);
    const libraryRow = gmLibraryJoin.libraryRows.get(selectedProject);
    const displayName = TianxiaSheetViewModel.resolveOwnerFinalName({
      characterListName: listRow?.name ?? ownerCharacterSheet.name,
      resolvedWorkflowName: ownerResolvedWorkflowName(ownerCharacterSheet),
      libraryName: libraryRow?.name,
    });
    const heading = document.getElementById("ownerCharacterSheet")?.querySelector(".gm-name");
    if (heading && displayName) heading.textContent = displayName;
  }
  applyCharacterLibrarySearch();
  gmRenderLibraryEnrichmentDiagnostic();
}

function gmCancelCharacterEnrichment() {
  if (gmLibraryEnrichmentAttempt) gmLibraryEnrichmentAttempt.cancel();
  gmLibraryEnrichmentAttempt = null;
}

function gmStartCharacterEnrichment(requestGeneration) {
  gmCancelCharacterEnrichment();
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let timeoutId = null;
  let cancelled = false;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      if (controller) controller.abort();
      const error = new Error(`Optional /api/characters enrichment timed out after ${GM_LIBRARY_ENRICHMENT_TIMEOUT_MS} ms.`);
      error.code = "GM_LIBRARY_ENRICHMENT_TIMEOUT";
      reject(error);
    }, GM_LIBRARY_ENRICHMENT_TIMEOUT_MS);
  });
  const options = controller ? {signal: controller.signal} : {};
  const request = api("/api/characters", options);
  const attempt = {
    cancel() {
      cancelled = true;
      if (timeoutId !== null) clearTimeout(timeoutId);
      if (controller) controller.abort();
    },
  };
  gmLibraryEnrichmentAttempt = attempt;
  Promise.race([request, timeout]).then(rows => {
    if (timeoutId !== null) clearTimeout(timeoutId);
    if (cancelled || requestGeneration !== gmLibraryRequestGeneration) return;
    if (!Array.isArray(rows)) {
      gmLibraryJoin.characterListRows = new Map();
      gmLibraryJoin.enrichmentError = "Optional /api/characters enrichment returned an invalid payload.";
      gmRenderLibraryEnrichmentDiagnostic();
      return;
    }
    gmApplyCharacterEnrichment(requestGeneration, rows);
  }, error => {
    if (timeoutId !== null) clearTimeout(timeoutId);
    if (cancelled || requestGeneration !== gmLibraryRequestGeneration) return;
    gmLibraryJoin.characterListRows = new Map();
    gmLibraryJoin.enrichmentError = String(error?.message || error);
    gmRenderLibraryEnrichmentDiagnostic();
  }).then(() => {
    if (gmLibraryEnrichmentAttempt === attempt) gmLibraryEnrichmentAttempt = null;
  }, error => {
    if (!cancelled && requestGeneration === gmLibraryRequestGeneration) {
      gmLibraryJoin.enrichmentError = String(error?.message || error);
      gmRenderLibraryEnrichmentDiagnostic();
    }
    if (gmLibraryEnrichmentAttempt === attempt) gmLibraryEnrichmentAttempt = null;
  });
}

function gmRenderCharacterLibraryError(error) {
  setSelectedCharacterWorkspaceVisible(false);
  const host = document.getElementById("characterCardList");
  clearNode(host);
  const box = gmEl("section", "gm-error gm-library-error");
  box.appendChild(gmEl("strong", null, "Saved characters could not be loaded."));
  box.appendChild(gmEl("p", null, plainAPIError(error, "The character library could not be loaded.")));
  const retry = recoveryActionButton("Try again", () => { void renderCharacterLibrary().catch(() => {}); }, true);
  retry.className = `${retry.className || ""} gm-library-retry`.trim();
  box.appendChild(retry);
  const technical = document.createElement("details");
  technical.className = "developer-diagnostics";
  const summary = document.createElement("summary");
  summary.textContent = "Technical details";
  technical.append(summary, gmEl("pre", null, String(error?.message || error)));
  box.appendChild(technical);
  host.appendChild(box);
}

function activeBuildRecency(character) {
  const run = character?.workflow?.active_run;
  return String(run?.updated_at || run?.created_at || character?.updated_at || "");
}

// The latest row behind each rendered card. Card controls read it when they
// fire, so a background refresh never has to rebind a listener (re-adding one
// would make a single click run the action twice). Keyed weakly: a card that
// leaves the host is collected with its entry.
const gmLibraryCardRows = new WeakMap();

function gmNodeContains(parent, node) {
  if (!parent || !node) return false;
  if (typeof parent.contains === "function") return Boolean(parent.contains(node));
  for (let current = node; current; current = current.parentNode) if (current === parent) return true;
  return false;
}

function gmCharacterCardDisclosures(root) {
  const out = [];
  const walk = node => {
    for (const child of node.children || []) {
      if (String(child.tagName || "").toUpperCase() === "DETAILS") out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
}

// Can the owner put the keyboard on this node? A card holds buttons, the
// "Advanced details" summary, and any link or field a future card row adds, so
// the list is open rather than pinned to one control type. A plain text node is
// never focusable, and neither is a container that never asked for the keyboard.
function gmCharacterCardFocusable(node) {
  const name = String(node?.tagName || "").toUpperCase();
  if (["BUTTON", "SUMMARY", "A", "INPUT", "SELECT", "TEXTAREA"].includes(name)) return true;
  return Number(node?.tabIndex) >= 0;
}

// Find the card control the owner was using by the text they can see. Any
// focusable control qualifies -- a button, the "Advanced details" summary, a
// link, a field -- so a background poll can hand focus back to whatever was
// focused without this lookup knowing the card's control list in advance.
// `tag` breaks a tie between two controls that read the same and is optional.
function gmCharacterCardControl(card, label, tag = "") {
  const wanted = String(label || "").trim();
  const wantedTag = String(tag || "").trim().toUpperCase();
  let firstMatch = null;
  const stack = [...(card?.children || [])];
  while (stack.length) {
    const node = stack.shift();
    stack.unshift(...(node.children || []));
    if (String(node.textContent || "").trim() !== wanted) continue;
    if (String(node.tagName || "").toUpperCase() === wantedTag) return node;
    if (!firstMatch && gmCharacterCardFocusable(node)) firstMatch = node;
  }
  return firstMatch;
}

// Leave cards that are already in place alone instead of detaching every card
// on each poll. Ordinary insertBefore moves still remove/reinsert a subtree
// and can lose focus, even within this host; the capture/restore helpers below
// restore the focused control, open disclosures and scroll after reconciliation.
// Only leftovers (the "no characters match" note) are removed outright.
function gmOrderCharacterLibraryCards(host, cards) {
  const wanted = new Set(cards);
  for (const node of [...host.children]) {
    if (!wanted.has(node)) node.remove();
  }
  cards.forEach((card, index) => {
    if (host.children[index] === card) return;
    host.insertBefore(card, host.children[index] || null);
  });
}

// The card host is repainted automatically while any summary is still filling.
// Snapshot what the owner is using right now -- the focused control, the scroll
// position and which "Advanced details" they opened -- so a poll that only
// refreshes facts never takes those controls away mid-interaction.
function gmCaptureCharacterLibraryInteraction(host) {
  const state = {scrollTop: 0, focus: null, open: new Map()};
  if (!host) return state;
  state.scrollTop = Number(host.scrollTop) || 0;
  const focused = document.activeElement;
  for (const card of host.querySelectorAll("[data-character-project-id]")) {
    const opened = gmCharacterCardDisclosures(card).map(node => Boolean(node.open));
    if (opened.some(Boolean)) state.open.set(card.dataset.characterProjectId, opened);
    if (!focused || focused === card || !gmNodeContains(card, focused)) continue;
    state.focus = {
      projectId: card.dataset.characterProjectId,
      cardMain: focused === card.querySelector(".card-main"),
      tag: String(focused.tagName || "").toUpperCase(),
      label: String(focused.textContent || "").trim(),
    };
  }
  return state;
}

function gmRestoreCharacterLibraryInteraction(host, state) {
  if (!host || !state) return;
  // querySelectorAll answers with a NodeList, which has no .map().
  const cards = new Map(Array.from(host.querySelectorAll("[data-character-project-id]"), card => [card.dataset.characterProjectId, card]));
  for (const [projectId, opened] of state.open) {
    const card = cards.get(projectId);
    if (!card) continue;
    gmCharacterCardDisclosures(card).forEach((node, index) => { node.open = Boolean(opened[index]); });
  }
  if (state.focus) {
    const card = cards.get(state.focus.projectId);
    if (card) {
      const target = state.focus.cardMain ? card.querySelector(".card-main") : gmCharacterCardControl(card, state.focus.label, state.focus.tag);
      if (target && typeof target.focus === "function") target.focus();
    }
  }
  if (state.scrollTop) host.scrollTop = state.scrollTop;
}

async function gmOpenCharacterLibraryCard(character) {
  if (!character || character.deletion_status) return;
  selectedProject = character.project_id;
  stage1PromptData = null;
  stage1Attempt = null;
  document.getElementById("approveCommitStage1").disabled = true;
  updateAIProviderControls();
  document.getElementById("stage1Prompt").value = "";
  await openOwnerCharacterSheet(character.project_id);
  const stage = await api(`/api/projects/${character.project_id}/stage1/status`);
  if (stage.current_prompt_id) {
    stage1PromptData = {
      prompt_id: stage.current_prompt_id,
      project_id: stage.project_id,
      project_revision: stage.project_revision,
    };
  }
  document.getElementById("stage1Result").textContent = pretty(stage);
  renderSelectedStage1State(character, stage);
  await refreshSelectedProject();
  await refreshStage2Status();
  await renderCharacterLibrary();
}

function gmCharacterCardActionSignature(character) {
  if (!character) return "";
  return [
    character.deletion_status || "",
    character.archived_at || "",
    (character.lifecycle || character.builder_lifecycle || {}).persistence_state || "",
    gmCharacterLibraryIsResumableDraft(character) ? "resume" : "",
    character.workflow?.active_run ? "continue" : "",
  ].filter(Boolean).join("|");
}

function gmApplyCharacterLibraryCardFacts(card, character) {
  const listRow = gmLibraryJoin.characterListRows.get(character.project_id) || null;
  const displayName = TianxiaSheetViewModel.resolveOwnerFinalName({
    characterListName: listRow?.name,
    resolvedWorkflowName: ownerResolvedWorkflowName({workflow: character.workflow}),
    libraryName: character.name,
  }) || character.working_name || "Unnamed character in progress";
  card.classList.toggle("selected", selectedProject === character.project_id);
  const main = card.querySelector(".card-main");
  const name = card.querySelector(".character-card-name");
  const status = card.querySelector(".character-card-status");
  const detail = card.querySelector(".character-card-detail");
  const build = card.querySelector(".character-card-build-state");
  const combatState = card.querySelector(".character-card-combat-state");
  if (main) {
    if (character.deletion_status) {
      main.removeAttribute("role"); main.removeAttribute("tabindex"); main.removeAttribute("aria-label");
      main.onclick = null; main.onkeydown = null;
    } else {
      main.tabIndex = 0; main.setAttribute("role", "button");
      main.setAttribute("aria-label", `Open Character Sheet for ${displayName}`);
      main.onclick = () => gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card));
      main.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card)); } };
    }
  }
  if (name) name.textContent = displayName;
  if (status) status.textContent = character.deletion_status === "queued" ? "Will be deleted when the Factory next restarts"
    : character.deletion_status === "failed" ? "Deletion could not finish"
    : character.archived_at ? "Archived character" : ownerStageLabel(character);
  if (detail) detail.textContent = character.deletion_status
    ? character.deletion_reason || "Hidden from character lists and fight setup. You can undo delete until the Factory next restarts. A complete backup will be kept."
    : gmCharacterCardDetail(character, listRow);
  if (build) build.textContent = `Build status: ${friendlyLabel(character.build_status)}`;
  if (combatState) {
    combatState.textContent = character.portable_readiness
      ? "Combat package: ready. Fight setup still needs current resources, teams, battlefield, placement, initiative, and controllers."
      : "Combat package: not ready.";
  }
  return displayName;
}

// Only the controls themselves are rebuilt, and only when a project gains or
// loses an action; the card element and its disclosure are left alone.
function gmBuildCharacterLibraryCardActions(card, character) {
  const actions = card.querySelector(".character-card-actions");
  const advanced = card.querySelector(".character-card-advanced");
  if (actions) clearNode(actions);
  const inspect = card.querySelector(".character-card-inspect-actions");
  if (inspect) inspect.remove();
  if (!actions) return;
  if (character.deletion_status) {
    actions.appendChild(recoveryActionButton("Undo delete", async () => {
      try {
        await api(`/api/character-library/${encodeURIComponent(character.project_id)}/undo-delete`, {method: "POST"});
        await loadProjects();
      } catch (error) { window.alert(error.message || "Delete could not be undone."); }
    }, false));
    return;
  }
  actions.appendChild(recoveryActionButton("Open", () => void gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card)), true));
  const persistence = (character.lifecycle || character.builder_lifecycle || {}).persistence_state;
  if (character.archived_at || persistence === "temporary" || persistence === "saved_draft") {
    actions.appendChild(recoveryActionButton("Delete permanently", async () => {
      const displayName = card.querySelector(".character-card-name").textContent;
      if (!window.confirm(`Delete “${displayName}” permanently when the Factory next restarts? This hides the character now and removes this character and its build history at the next restart. Until then, choose “Show archived and hidden characters” and “Undo delete” to cancel. A complete backup is kept in backups/deleted-characters and can be restored by the owner.`)) return;
      try {
        await api(`/api/character-library/${encodeURIComponent(character.project_id)}/delete-permanently`, {
          method: "POST", body: JSON.stringify({confirm_project_id: character.project_id}),
        });
        if (selectedProject === character.project_id) {
          selectedProject = null;
          clearNode(document.getElementById("ownerCharacterSheet"));
        }
        await loadProjects();
      } catch (error) { window.alert(error.message || "The character could not be deleted."); }
    }, false));
  }
  if (gmCharacterLibraryIsResumableDraft(character)) {
    actions.appendChild(recoveryActionButton("Resume draft", () => resumeCharacterLibraryDraft(character.project_id), false));
  }
  if (!character.workflow?.active_run || !advanced) return;
  actions.appendChild(recoveryActionButton("Continue build", () => {
    const run = gmLibraryCardRows.get(card)?.workflow?.active_run;
    if (run) void restoreGuidedActiveBuild(character.project_id, run.run_id);
  }, false));
  const inspectActions = document.createElement("div");
  inspectActions.className = "recovery-actions character-card-inspect-actions";
  inspectActions.appendChild(recoveryActionButton("Inspect Build / Errors", () => {
    const run = gmLibraryCardRows.get(card)?.workflow?.active_run;
    if (run) void restoreGuidedActiveBuild(character.project_id, run.run_id, true);
  }, false));
  advanced.appendChild(inspectActions);
}

function gmCreateCharacterLibraryCard(character) {
  const listRow = gmLibraryJoin.characterListRows.get(character.project_id) || null;
  const displayName = TianxiaSheetViewModel.resolveOwnerFinalName({
    characterListName: listRow?.name,
    resolvedWorkflowName: ownerResolvedWorkflowName({workflow: character.workflow}),
    libraryName: character.name,
  }) || character.working_name || "Unnamed character in progress";
  const card = document.createElement("article");
  card.className = `character-library-card${selectedProject === character.project_id ? " selected" : ""}`;
  card.dataset.characterProjectId = character.project_id;
  gmLibraryCardRows.set(card, character);
  const main = document.createElement("div"); main.className = "card-main"; main.tabIndex = 0; main.setAttribute("role", "button"); main.setAttribute("aria-label", `Open Character Sheet for ${displayName}`);
  const name = document.createElement("strong"); name.className = "character-card-name"; name.textContent = displayName;
  const status = document.createElement("span"); status.className = "character-card-status"; status.textContent = ownerStageLabel(character);
  const detail = document.createElement("small"); detail.className = "character-card-detail";
  detail.textContent = gmCharacterCardDetail(character, listRow);
  const combatState = document.createElement("small");
  combatState.className = "character-card-combat-state";
  combatState.textContent = character.portable_readiness
    ? "Combat package: ready. Fight setup still needs current resources, teams, battlefield, placement, initiative, and controllers."
    : "Combat package: not ready.";
  main.append(name, status, detail);
  const advanced = document.createElement("details"); advanced.className = "character-card-advanced owner-advanced-disclosure";
  const advancedSummary = document.createElement("summary"); advancedSummary.textContent = "Advanced details";
  const build = document.createElement("span"); build.className = "character-card-build-state"; build.textContent = `Build status: ${friendlyLabel(character.build_status)}`;
  advanced.append(advancedSummary, build, combatState);
  const actions = document.createElement("div"); actions.className = "recovery-actions character-card-actions";
  // Returns the promise, as before: callers and tests await the opened sheet.
  main.onclick = () => gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card));
  main.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void gmOpenCharacterLibraryCard(gmLibraryCardRows.get(card)); } };
  card.append(main, actions, advanced);
  gmApplyCharacterLibraryCardFacts(card, character);
  gmBuildCharacterLibraryCardActions(card, character);
  return card;
}

function gmUpdateCharacterLibraryCard(card, character) {
  const previousSignature = gmCharacterCardActionSignature(gmLibraryCardRows.get(card));
  gmLibraryCardRows.set(card, character);
  gmApplyCharacterLibraryCardFacts(card, character);
  if (previousSignature !== gmCharacterCardActionSignature(character)) gmBuildCharacterLibraryCardActions(card, character);
  return card;
}

function gmRenderCharacterLibraryRows(characters) {
  // Several characters can sit at a review checkpoint; the startup
  // "Continue" must open the one the owner touched most recently, not the
  // first one in library order.
  const activeCharacter = characters
    .filter(character => character.workflow?.active_run)
    .sort((a, b) => activeBuildRecency(b).localeCompare(activeBuildRecency(a)))[0];
  guidedStartupRecovery.active = activeCharacter?.workflow?.active_run
    ? {project_id: activeCharacter.project_id, project_name: activeCharacter.name, active_run: activeCharacter.workflow.active_run}
    : null;
  const host = document.getElementById("characterCardList");
  renderActiveBuildRecovery(characters);
  setSelectedCharacterWorkspaceVisible(Boolean(selectedProject));
  if (!characters.length) {
    setSelectedCharacterWorkspaceVisible(false);
    clearNode(host);
    const empty = document.createElement("div");
    const message = document.createElement("p"); message.textContent = "No saved characters yet. Import a completed Character ZIP above or create a new character.";
    const button = document.createElement("button"); button.type = "button"; button.className = "empty-library-actions"; button.textContent = "Create a Character";
    button.addEventListener("click", () => startNewCharacter("quick")); empty.append(message, button); host.appendChild(empty); applyCharacterLibrarySearch(); return;
  }
  // An automatic poll repaints this host every second or two, so cards are
  // updated and reordered in place: a focused control and an opened
  // "Advanced details" survive instead of being replaced underneath the owner.
  const interaction = gmCaptureCharacterLibraryInteraction(host);
  // querySelectorAll answers with a NodeList, which has no .map().
  const existing = new Map(Array.from(host.querySelectorAll("[data-character-project-id]"), card => [card.dataset.characterProjectId, card]));
  const cards = characters.map(character => {
    const card = existing.get(character.project_id);
    return card ? gmUpdateCharacterLibraryCard(card, character) : gmCreateCharacterLibraryCard(character);
  });
  const kept = new Set(cards);
  for (const card of existing.values()) {
    if (kept.has(card)) continue;
    gmLibraryCardRows.delete(card);
    card.remove();
  }
  gmOrderCharacterLibraryCards(host, cards);
  gmRestoreCharacterLibraryInteraction(host, interaction);
  applyCharacterLibrarySearch();
  gmRenderLibraryEnrichmentDiagnostic();
}

function applyCharacterLibrarySearch() {
  const input = document.getElementById("characterSearchInput");
  const host = document.getElementById("characterCardList");
  const count = document.getElementById("characterSearchCount");
  const clear = document.getElementById("clearCharacterSearch");
  if (!input || !host || !count) return;
  const query = input.value;
  const cards = [...host.querySelectorAll("[data-character-project-id]")];
  let visible = 0;
  for (const card of cards) {
    const fields = [".character-card-name", ".character-card-detail", ".character-card-status"]
      .map(selector => card.querySelector(selector)?.textContent || "");
    const matches = globalThis.CharacterSearch?.matches(query, fields) ?? fields.some(value => !query.trim() || value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    card.hidden = !matches;
    if (matches) visible += 1;
  }
  count.textContent = `${visible} of ${cards.length} ${cards.length === 1 ? "character" : "characters"}`;
  if (clear) clear.hidden = !query;
  let empty = host.querySelector(".character-search-empty");
  if (query && visible === 0) {
    if (!empty) { empty = document.createElement("p"); empty.className = "character-search-empty"; host.appendChild(empty); }
    empty.textContent = `No characters match '${query}'`;
  } else if (empty) empty.remove();
}

document.getElementById("characterSearchInput")?.addEventListener("input", applyCharacterLibrarySearch);
document.getElementById("clearCharacterSearch")?.addEventListener("click", () => {
  const input = document.getElementById("characterSearchInput");
  input.value = "";
  applyCharacterLibrarySearch();
  input.focus();
});
document.addEventListener("keydown", event => {
  const screen = document.getElementById("screen-projects");
  if (!screen?.classList.contains("active")) return;
  const input = document.getElementById("characterSearchInput");
  if (event.key === "/" && !event.target?.closest?.("input, textarea, select, [contenteditable='true']")) {
    event.preventDefault(); input?.focus(); return;
  }
  if (event.key === "Escape" && input?.value) {
    input.value = ""; applyCharacterLibrarySearch();
  }
});
let showArchivedLibraryCharacters = false;
document.getElementById("showArchivedCharacters").onclick = async () => {
  showArchivedLibraryCharacters = !showArchivedLibraryCharacters;
  const button = document.getElementById("showArchivedCharacters");
  button.textContent = showArchivedLibraryCharacters ? "Hide archived and hidden characters" : "Show archived and hidden characters";
  button.setAttribute("aria-pressed", String(showArchivedLibraryCharacters));
  await renderCharacterLibrary();
};

async function renderCharacterLibrary() {
  // The library endpoint is authoritative for first paint. Character-list data
  // is optional enrichment and is isolated by generation, timeout, and abort.
  const requestGeneration = ++gmLibraryRequestGeneration;
  gmLibraryJoin.enrichmentError = null;
  gmStartCharacterEnrichment(requestGeneration);
  const host = document.getElementById("characterCardList");
  if (!host.querySelector(".character-library-card")) {
    clearNode(host);
    host.appendChild(gmEl("p", "gm-library-loading", "Loading saved characters…"));
  }
  try {
    const [visibleCharacters, archivedCharacters] = await Promise.all([
      api("/api/character-library"), showArchivedLibraryCharacters ? api("/api/character-library/archived") : Promise.resolve([]),
    ]);
    if (!Array.isArray(visibleCharacters) || !Array.isArray(archivedCharacters)) throw new Error("The character library returned an invalid payload.");
    const characters = [...visibleCharacters, ...archivedCharacters];
    if (requestGeneration !== gmLibraryRequestGeneration) return characters;
    if (!Array.isArray(characters)) throw new Error("The character library returned an invalid payload.");
    gmLibraryJoin.libraryRows = new Map();
    for (const row of characters) {
      if (row && row.project_id) gmLibraryJoin.libraryRows.set(row.project_id, row);
    }
    gmRenderCharacterLibraryRows(characters);
    gmPollPendingCharacterLibrary(requestGeneration, characters);
    return characters;
  } catch (error) {
    if (requestGeneration !== gmLibraryRequestGeneration) return [];
    gmCancelCharacterEnrichment();
    gmRenderCharacterLibraryError(error);
    throw error;
  }
}

// One request at a time, with a bounded delay. Generation checks discard old
// refreshes; partial cards remain available even if a poll or enrichment fails.
function gmPollPendingCharacterLibrary(requestGeneration, characters, delay = 1000) {
  if (!characters.some(row => row.summary_pending)) return;
  setTimeout(async () => {
    if (requestGeneration !== gmLibraryRequestGeneration) return;
    let rows = characters;
    try {
      const refreshed = await api("/api/character-library");
      if (requestGeneration !== gmLibraryRequestGeneration) return;
      if (!Array.isArray(refreshed)) throw new Error("Invalid character library payload.");
      for (const row of refreshed) {
        if (!row.summary_pending && gmLibraryJoin.libraryRows.get(row.project_id)?.summary_pending) {
          gmLibraryJoin.characterListRows.delete(row.project_id);
        }
      }
      rows = refreshed;
      gmLibraryJoin.libraryRows = new Map(rows.map(row => [row.project_id, row]));
      gmRenderCharacterLibraryRows(rows);
    } catch (_error) {
      // Keep the existing cards and retry without depending on /api/characters.
    }
    gmPollPendingCharacterLibrary(requestGeneration, rows, Math.min(delay * 2, 5000));
  }, delay);
}

// Keep the advanced table intact while making the owner-facing character library primary.
loadProjects = async function() {
  const [projectsResult, charactersResult] = await Promise.allSettled([api("/api/projects"), renderCharacterLibrary()]);
  const rows = projectsResult.status === "fulfilled" ? projectsResult.value : [];
  const body = document.getElementById("projectRows"); clearNode(body);
  for (const row of rows) {
    const tr = document.createElement("tr"); appendTextCell(tr, row.working_name); appendTextCell(tr, row.revision); appendTextCell(tr, `${row.builder_lifecycle?.display_label || "Saved / existing"} · ${row.status}`);
    tr.onclick = async () => {
      selectedProject = row.project_id; stage1PromptData = null; stage1Attempt = null;
      document.getElementById("approveCommitStage1").disabled = true; updateAIProviderControls();
      document.getElementById("stage1Prompt").value = "";
      const stage = await api(`/api/projects/${row.project_id}/stage1/status`);
      if (stage.current_prompt_id) stage1PromptData = {prompt_id: stage.current_prompt_id, project_id: stage.project_id, project_revision: stage.project_revision};
      document.getElementById("stage1Result").textContent = pretty(stage);
      renderSelectedStage1State(row, stage);
      await refreshSelectedProject(); await refreshStage2Status(); await openOwnerCharacterSheet(row.project_id);
    };
    body.appendChild(tr);
  }
  if (charactersResult.status === "rejected") {
    const host = document.getElementById("characterCardList");
    if (!host.querySelector(".gm-library-error")) gmRenderCharacterLibraryError(charactersResult.reason);
  }
  if (projectsResult.status === "rejected" && charactersResult.status === "rejected") throw projectsResult.reason;
  return rows;
};

document.getElementById("saveStage1Locks").onclick = async () => {
  if (!selectedProject) return;
  try {
    const locks = JSON.parse(document.getElementById("stage1Locks").value);
    const result = await api(`/api/projects/${selectedProject}/stage1/user-locks`, {method: "POST", body: JSON.stringify({locks})});
    document.getElementById("stage1Result").textContent = pretty(result.project);
    await loadProjects(); await refreshSelectedProject();
  } catch (e) { document.getElementById("stage1Result").textContent = e.message; }
};

document.getElementById("generateStage1Prompt").onclick = async () => {
  if (!selectedProject) return;
  try {
    stage1PromptData = await api(`/api/projects/${selectedProject}/stage1/prompt`, {method: "POST", body: "{}"});
    document.getElementById("stage1Prompt").value = stage1PromptData.prompt_text;
    document.getElementById("stage1Result").textContent = pretty({prompt_id: stage1PromptData.prompt_id, prompt_sha256: stage1PromptData.prompt_sha256, project_revision: stage1PromptData.project_revision, deterministic: stage1PromptData.deterministic});
    updateAIProviderControls();
  } catch (e) { document.getElementById("stage1Result").textContent = e.message; }
};

document.getElementById("copyStage1Prompt").onclick = async () => {
  const box = document.getElementById("stage1Prompt");
  if (!box.value) return;
  try {
    await navigator.clipboard.writeText(box.value);
    document.getElementById("stage1Result").textContent = "Prompt copied. The text area remains available as a manual fallback.";
  } catch (_e) {
    box.focus(); box.select();
    document.getElementById("stage1Result").textContent = "Automatic clipboard access was unavailable. The prompt is selected for manual copy.";
  }
};

document.getElementById("validateStage1Response").onclick = async () => {
  if (!stage1PromptData) return;
  try {
    stage1Attempt = await api(`/api/stage1/prompts/${encodeURIComponent(stage1PromptData.prompt_id)}/responses/validate`, {
      method: "POST", body: JSON.stringify({response_text: document.getElementById("stage1Response").value})
    });
    document.getElementById("stage1Result").textContent = pretty(stage1Attempt);
    document.getElementById("approveCommitStage1").disabled = !stage1Attempt.validation.valid;
  } catch (e) {
    document.getElementById("approveCommitStage1").disabled = true;
    document.getElementById("stage1Result").textContent = e.message;
  }
};

document.getElementById("saveAIProviderConfig").onclick = async () => {
  try {
    aiProviderStatus = await api("/api/ai-provider/configure", {
      method: "POST",
      body: JSON.stringify({
        enabled: document.getElementById("aiProviderEnabled").checked,
        model: document.getElementById("aiProviderModel").value.trim(),
        thinking_mode: document.getElementById("aiProviderThinking").value,
        max_output_tokens: Number(document.getElementById("aiProviderMaxTokens").value),
        timeout_seconds: Number(document.getElementById("aiProviderTimeout").value),
        data_sharing_acknowledged: document.getElementById("aiProviderAcknowledged").checked,
        acknowledged_by: document.getElementById("aiProviderActor").value.trim() || null
      })
    });
    await loadAIProviderStatus();
  } catch (e) { document.getElementById("aiProviderStatus").textContent = e.message; }
};

document.getElementById("saveAIProviderKey").onclick = async () => {
  const input = document.getElementById("aiProviderKey");
  try {
    aiProviderStatus = await api("/api/ai-provider/key", {
      method: "POST", body: JSON.stringify({api_key: input.value})
    });
    input.value = "";
    await loadAIProviderStatus();
  } catch (e) { input.value = ""; document.getElementById("aiProviderStatus").textContent = e.message; }
};

document.getElementById("deleteAIProviderKey").onclick = async () => {
  try {
    aiProviderStatus = await api("/api/ai-provider/key", {method: "DELETE"});
    document.getElementById("aiProviderKey").value = "";
    await loadAIProviderStatus();
  } catch (e) { document.getElementById("aiProviderStatus").textContent = e.message; }
};

["aiProviderEnabled", "aiProviderModel", "aiProviderThinking", "aiProviderMaxTokens", "aiProviderTimeout", "aiProviderAcknowledged", "aiProviderActor"].forEach(id => {
  const input = document.getElementById(id);
  const eventName = input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input";
  input.addEventListener(eventName, () => {
    aiProviderDirty = true;
    document.getElementById("aiProviderStatus").textContent = providerStatusMessage(aiProviderStatus, true);
    document.getElementById("runAIProvider").disabled = true;
  });
});

document.getElementById("runAIProvider").onclick = async () => {
  if (!stage1PromptData || !aiProviderStatus || !aiProviderStatus.ready) return;
  const button = document.getElementById("runAIProvider");
  button.disabled = true;
  const requestKey = `stage1.ui.${crypto.randomUUID()}`;
  try {
    const run = await api(`/api/stage1/prompts/${encodeURIComponent(stage1PromptData.prompt_id)}/ai-provider/run`, {
      method: "POST", body: JSON.stringify({idempotency_key: requestKey})
    });
    stage1Attempt = run.attempt || (run.stage1_attempt_id
      ? await api(`/api/stage1/attempts/${encodeURIComponent(run.stage1_attempt_id)}`)
      : null);
    document.getElementById("stage1Result").textContent = pretty({provider_run: run, stage1_attempt: stage1Attempt});
    document.getElementById("approveCommitStage1").disabled = !(stage1Attempt && stage1Attempt.validation.valid);
    await loadAIProviderStatus();
  } catch (e) {
    document.getElementById("stage1Result").textContent = e.message;
    await loadAIProviderStatus();
  } finally {
    updateAIProviderControls();
  }
};

document.getElementById("approveCommitStage1").onclick = async () => {
  if (!stage1Attempt || !stage1Attempt.validation.valid) return;
  try {
    const result = await api(`/api/stage1/attempts/${encodeURIComponent(stage1Attempt.attempt_id)}/approve-commit`, {
      method: "POST", body: JSON.stringify({approved_by: document.getElementById("stage1Approver").value})
    });
    stage1Attempt = result;
    document.getElementById("stage1Result").textContent = pretty(result);
    document.getElementById("approveCommitStage1").disabled = true;
    await loadProjects(); await refreshSelectedProject();
    const host = document.getElementById("stage1ProjectionDownloads"); clearNode(host);
    if (result.commit && result.commit.projection_id) {
      const note = document.createElement("span");
      note.textContent = `Blueprint intent projection ${result.commit.projection_id} is sealed with zero advancement-event delta.`;
      host.appendChild(note);
    }
  } catch (e) { document.getElementById("stage1Result").textContent = e.message; }
};



let selectedCharacterZip = null;
let selectedCharacterPreview = null;

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} bytes`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function setCharacterImportStatus(message, state = "") {
  const host = document.getElementById("characterZipProgress");
  host.textContent = message;
  host.classList.toggle("error", state === "error");
  host.classList.toggle("success", state === "success");
}

function renderPortableCharacterPreview(preview) {
  const host = document.getElementById("characterZipPreview");
  clearNode(host); host.hidden = false;
  const character = preview.character || {};
  const readiness = preview.readiness || {};
  const rows = [
    ["Character", character.name || "Unnamed character"],
    ["Cultivation", [`CL ${character.cultivation_level ?? "?"}`, character.realm].filter(Boolean).join(" · ")],
    ["Path / subpath", [character.path, character.subpath].filter(Boolean).join(" · ") || "Not recorded"],
    ["Project ID", character.project_id || "Not recorded"],
    ["Package hash", preview.package?.sha256 || "Not recorded"],
    ["Advancement", friendlyLabel(readiness.advancement || "PENDING")],
    ["Character Sheet", friendlyLabel(readiness.character_sheet || "PENDING")],
    ["GM Screen", friendlyLabel(readiness.gm_screen || "PENDING")],
    ["Combat Sheet", friendlyLabel(readiness.combat_sheet || "PENDING")],
    ["Combat runtime", friendlyLabel(readiness.combat_runtime || "PENDING")],
    ["Combat readiness", readiness.combat === "COMBAT_READY" ? "Combat Ready" : "Not Combat Ready"],
    ["Combat state", readiness.combat_ready_semantics === "RUNTIME_READY_PRE_ENCOUNTER" ? "Pre-encounter — encounter setup required" : friendlyLabel(readiness.combat_ready_semantics || readiness.combat || "PENDING")],
    ["Current Qi", readiness.current_qi_required ? "Required at encounter setup" : "Not required"],
    ["Current Martial Focus", readiness.current_martial_focus_required ? "Required at encounter setup" : "Not required"],
    ["Opponent / teams", readiness.opponent_team_completion_required ? "Completion required" : "Complete"],
    ["Battlefield choice", readiness.battlefield_owner_choice_committed ? "Committed" : "Owner choice not committed"],
    ["Token placement", readiness.token_placement_committed ? "Committed" : "Not committed"],
    ["Initiative", readiness.initiative_attempted ? "Attempted" : "Not attempted"],
    ["Controllers", friendlyLabel(readiness.controller_selection || "NOT_ATTEMPTED")],
    ["Product environment", preview.environment_ready ? "Ready" : "Blocked"],
    ["Install status", preview.disposition === "NEW" ? "New character" : preview.disposition === "IDENTICAL" ? "Already installed — identical package" : "Conflict — import blocked"]
  ];
  const dl = document.createElement("dl");
  for (const [label, value] of rows) {
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    dl.append(dt, dd);
  }
  host.appendChild(dl);
  document.getElementById("characterZipTechnical").textContent = pretty(preview);
  document.getElementById("characterZipDetails").hidden = false;
}

function selectCharacterZip(file) {
  selectedCharacterZip = file || null;
  selectedCharacterPreview = null;
  document.getElementById("characterZipPreview").hidden = true;
  document.getElementById("characterZipDetails").hidden = true;
  document.getElementById("importCharacterZip").disabled = true;
  const previewButton = document.getElementById("previewCharacterZip");
  if (!file) {
    document.getElementById("characterZipSelection").textContent = "No ZIP selected.";
    previewButton.disabled = true;
    setCharacterImportStatus("Select a package to begin.");
    return;
  }
  document.getElementById("characterZipSelection").textContent = `${file.name} · ${formatFileSize(file.size)}`;
  const extensionValid = file.name.toLowerCase().endsWith(".zip");
  const sizeValid = file.size > 0 && file.size <= 128 * 1024 * 1024;
  previewButton.disabled = !(extensionValid && sizeValid);
  if (!extensionValid) setCharacterImportStatus("Choose a file ending in .zip.", "error");
  else if (!sizeValid) setCharacterImportStatus("The package must be larger than 0 bytes and no more than 128 MB.", "error");
  else setCharacterImportStatus("Ready to validate. Preview will not change your saved characters.");
}

function clearCharacterZipSelection(message = "No ZIP selected. Choose or drop one audited Character ZIP.") {
  selectedCharacterZip = null;
  selectedCharacterPreview = null;
  document.getElementById("characterZipFile").value = "";
  selectCharacterZip(null);
  setCharacterImportStatus(message);
}

async function previewSelectedCharacterZip() {
  if (!selectedCharacterZip) return;
  const previewButton = document.getElementById("previewCharacterZip");
  const importButton = document.getElementById("importCharacterZip");
  previewButton.disabled = true; importButton.disabled = true;
  setCharacterImportStatus("Validating package safety, checksums, identity, and readiness…");
  try {
    const preview = await api("/api/characters/portable-preview", {
      method: "POST",
      headers: {"Content-Type": "application/zip", "X-Tianxia-Filename": selectedCharacterZip.name},
      body: selectedCharacterZip
    });
    selectedCharacterPreview = preview;
    renderPortableCharacterPreview(preview);
    if (!preview.can_import) {
      setCharacterImportStatus(preview.owner_message || "Import is blocked by a required product prerequisite. No data was changed.", "error");
      importButton.disabled = true;
    } else if (preview.disposition === "IDENTICAL") {
      setCharacterImportStatus(preview.owner_message || "Valid package. This exact character is already installed; Import will confirm the duplicate safely.", "success");
      importButton.disabled = false;
    } else {
      setCharacterImportStatus(preview.owner_message || "Preview complete. Review the summary, then choose Import Character.", "success");
      importButton.disabled = false;
    }
  } catch (error) {
    selectedCharacterPreview = null;
    document.getElementById("characterZipTechnical").textContent = error.message || String(error);
    document.getElementById("characterZipDetails").hidden = false;
    setCharacterImportStatus(plainAPIError(error, "The package could not be validated. No data was changed."), "error");
  } finally {
    previewButton.disabled = false;
  }
}

async function importSelectedCharacterZip() {
  if (!selectedCharacterZip || !selectedCharacterPreview || selectedCharacterPreview.disposition === "CONFLICT") return;
  const previewButton = document.getElementById("previewCharacterZip");
  const importButton = document.getElementById("importCharacterZip");
  previewButton.disabled = true; importButton.disabled = true;
  setCharacterImportStatus("Importing the verified character and rebuilding its saved sheet…");
  try {
    const result = await api("/api/characters/portable-import-upload", {
      method: "POST",
      headers: {"Content-Type": "application/zip", "X-Tianxia-Filename": selectedCharacterZip.name},
      body: selectedCharacterZip
    });
    document.getElementById("characterZipTechnical").textContent = pretty(result);
    if (result.status === "ALREADY_INSTALLED_IDENTICAL") {
      setCharacterImportStatus("Already installed — identical package. Your existing character was left unchanged.", "success");
    } else {
      setCharacterImportStatus("Character imported successfully. The saved sheet is open below.", "success");
    }
    selectedProject = result.project_id;
    await loadProjects();
    if (typeof loadCombatCatalog === "function") await loadCombatCatalog();
    if (result.project_id) await openOwnerCharacterSheet(result.project_id);
  } catch (error) {
    document.getElementById("characterZipTechnical").textContent = error.message || String(error);
    document.getElementById("characterZipDetails").hidden = false;
    setCharacterImportStatus(plainAPIError(error, "Import failed safely. Your existing character list was not changed."), "error");
    importButton.disabled = false;
  } finally {
    previewButton.disabled = false;
  }
}

const characterZipDropZone = document.getElementById("characterZipDropZone");
const characterZipFile = document.getElementById("characterZipFile");
document.getElementById("chooseCharacterZip").addEventListener("click", event => { event.stopPropagation(); characterZipFile.click(); });
characterZipDropZone.addEventListener("click", event => { if (event.target.id !== "chooseCharacterZip") characterZipFile.click(); });
characterZipDropZone.addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); characterZipFile.click(); }
});
for (const eventName of ["dragenter", "dragover"]) characterZipDropZone.addEventListener(eventName, event => { event.preventDefault(); characterZipDropZone.classList.add("drag-active"); });
for (const eventName of ["dragleave", "drop"]) characterZipDropZone.addEventListener(eventName, event => { event.preventDefault(); characterZipDropZone.classList.remove("drag-active"); });
characterZipDropZone.addEventListener("drop", event => selectCharacterZip(event.dataTransfer?.files?.[0] || null));
characterZipFile.addEventListener("change", () => selectCharacterZip(characterZipFile.files?.[0] || null));
document.getElementById("previewCharacterZip").addEventListener("click", previewSelectedCharacterZip);
document.getElementById("importCharacterZip").addEventListener("click", importSelectedCharacterZip);
document.getElementById("replaceCharacterZip").addEventListener("click", () => characterZipFile.click());
document.getElementById("removeCharacterZip").addEventListener("click", () => clearCharacterZipSelection());
document.getElementById("refreshCharacters").addEventListener("click", async () => {
  try { await loadProjects(); setCharacterImportStatus("Character library refreshed.", "success"); }
  catch (error) { setCharacterImportStatus(plainAPIError(error, "The character library could not be refreshed."), "error"); }
});

(async () => {
  try {
    token = (await api("/api/session")).token;
  } catch (error) {
    setGuidedStatus("The local Factory session could not start. Close and reopen the application.", true);
    setScreenState("statusScreenState", "error", "The local Factory session could not start.", null, error);
    return;
  }
  const projectRows = await loadProjects().catch(() => []);
  await loadCharacterBuilderOptions().catch(error => setGuidedStatus(plainAPIError(error, "Character choices could not be loaded."), true));
  renderGuidedStartupRecovery(projectRows);
  await Promise.allSettled([loadStatus(), loadCatalog(), loadPacks(), loadAIProviderStatus()]);
})();

let stage2Proposal = null;

function renderStage2Downloads(status) {
  const host = document.getElementById("stage2Downloads");
  if (!host) return;
  clearNode(host);
  for (const artifact of (status.artifacts || [])) {
    const a = document.createElement("a");
    a.href = `/api/projects/${encodeURIComponent(selectedProject)}/stage2/artifacts/${encodeURIComponent(artifact.artifact_name)}`;
    a.textContent = artifact.artifact_name;
    a.target = "_blank";
    host.appendChild(a);
  }
}

async function refreshStage2Status() {
  if (!selectedProject) return null;
  try {
    const result = await api(`/api/projects/${encodeURIComponent(selectedProject)}/stage2/status`);
    document.getElementById("stage2Result").textContent = pretty(result);
    renderStage2Downloads(result);
    return result;
  } catch (e) {
    document.getElementById("stage2Result").textContent = e.message;
    return null;
  }
}

document.getElementById("createStage2Proposal").onclick = async () => {
  if (!selectedProject) return;
  try {
    const project = await api(`/api/projects/${encodeURIComponent(selectedProject)}`);
    const canonical = project.project;
    const choices = JSON.parse(document.getElementById("stage2Choices").value);
    stage2Proposal = await api(`/api/projects/${encodeURIComponent(selectedProject)}/stage2/proposals`, {
      method: "POST",
      body: JSON.stringify({
        schema_version: "TianxiaFoundry.Stage2AdvancementProposal.v2",
        expected_project_revision: canonical.revision,
        expected_content_lock_hash: canonical.content_lock.lock_hash,
        target_cl: Number(document.getElementById("stage2TargetCL").value),
        idempotency_key: `stage2.ui.${crypto.randomUUID()}`,
        choices
      })
    });
    document.getElementById("stage2Result").textContent = pretty(stage2Proposal);
    document.getElementById("validateStage2Proposal").disabled = false;
    document.getElementById("approveStage2Proposal").disabled = true;
    document.getElementById("commitStage2Proposal").disabled = true;
  } catch (e) { document.getElementById("stage2Result").textContent = e.message; }
};

document.getElementById("validateStage2Proposal").onclick = async () => {
  if (!stage2Proposal) return;
  try {
    const result = await api(`/api/stage2/proposals/${encodeURIComponent(stage2Proposal.proposal_id)}/validate`, {method:"POST", body:"{}"});
    document.getElementById("stage2Result").textContent = pretty(result);
    document.getElementById("approveStage2Proposal").disabled = !result.valid;
  } catch (e) { document.getElementById("stage2Result").textContent = e.message; }
};

document.getElementById("approveStage2Proposal").onclick = async () => {
  if (!stage2Proposal) return;
  try {
    const challengeResult = await api(`/api/stage2/proposals/${encodeURIComponent(stage2Proposal.proposal_id)}/approval-challenge`, {
      method:"POST", body:"{}"
    });
    const challenge = challengeResult.challenge;
    const result = await api(`/api/stage2/proposals/${encodeURIComponent(stage2Proposal.proposal_id)}/approve`, {
      method:"POST", body:JSON.stringify({
        approved_by:document.getElementById("stage2Approver").value,
        challenge_id:challenge.challenge_id,
        nonce:challenge.nonce
      })
    });
    document.getElementById("stage2Result").textContent = pretty(result);
    document.getElementById("commitStage2Proposal").disabled = false;
  } catch (e) { document.getElementById("stage2Result").textContent = e.message; }
};

document.getElementById("commitStage2Proposal").onclick = async () => {
  if (!stage2Proposal) return;
  try {
    const result = await api(`/api/stage2/proposals/${encodeURIComponent(stage2Proposal.proposal_id)}/commit`, {
      method:"POST", body:JSON.stringify({confirm_atomic_commit:true})
    });
    document.getElementById("stage2Result").textContent = pretty(result);
    document.getElementById("commitStage2Proposal").disabled = true;
    await loadProjects();
    await refreshStage2Status();
  } catch (e) { document.getElementById("stage2Result").textContent = e.message; }
};

document.getElementById("rebuildStage2Ledger").onclick = async () => {
  if (!selectedProject) return;
  try {
    const result = await api(`/api/projects/${encodeURIComponent(selectedProject)}/stage2/rebuild`, {method:"POST", body:"{}"});
    document.getElementById("stage2Result").textContent = pretty(result);
    renderStage2Downloads(result);
  } catch (e) { document.getElementById("stage2Result").textContent = e.message; }
};

document.getElementById("refreshStage2Status").onclick = refreshStage2Status;

// ---------------------------------------------------------------------------
// Gate 5 combat integration
// ---------------------------------------------------------------------------
let combatCatalog = null;
let combatCandidateInventory = null;
let combatVisualAssets = null;
let combatMatch = null;
let combatHistory = null;
let combatHistoryIndex = null;
let combatDecision = null;
let combatPendingIntentDraft = null;
let combatInteractionDraft = null;
let combatInteractionMode = "inspect";
let combatPanPointer = null;
// M2 compatibility contract: const COMBAT_INTERACTION_MODES = new Set(["inspect", "pan", "select_target", "select_destination", "select_area", "measure", "review"]);
const COMBAT_INTERACTION_MODES = new Set(["inspect", "pan", "select_target", "select_destination", "select_area", "select_exact", "measure", "review"]);
let combatAutoRunning = false;
let combatAIValidationToken = null;
let combatSelectedCandidateId = null;
let combatProviderStatus = null;
let combatPresentation = null;
let combatSelectedActorId = null;
let combatPinnedActorId = null;
let combatFollowCurrentTurn = true;
let combatNameplatesVisible = true;
let combatGeometryOverlayMode = "subtle";
let combatViewportZoom = 1;
let combatMobileTab = "map";
let combatMobileSheetState = "medium";
let combatExpandedSheetSection = "summary";
let combatWorkspaceMode = "owner";
let combatAutoStepPromise = null;
let combatExecutionEpoch = 0;
let combatHistoryTransitionPending = false;
let combatHistoryTransitionSerial = 0;

const combatId = value => encodeURIComponent(value);
const combatIsHistorical = () => combatHistoryIndex !== null;
const combatSelectedBoundary = () => {
  if (!combatHistory?.boundaries?.length) return null;
  const index = combatHistoryIndex === null ? combatHistory.boundaries.length - 1 : combatHistoryIndex;
  return combatHistory.boundaries[index] || null;
};
const combatViewState = () => combatIsHistorical() ? combatSelectedBoundary()?.state : combatMatch?.state;
const combatActorById = actorId => combatPresentation?.actors?.find(actor => actor.entity_id === actorId) || combatViewState()?.actors?.find(actor => actor.entity_id === actorId) || combatMatch?.state?.actors?.find(actor => actor.entity_id === actorId) || null;
const combatActorName = actorId => combatActorById(actorId)?.display_name || combatCatalog?.projections?.find(row => row.runtime_entity_id === actorId)?.display_name || actorId || "—";
const combatCellKey = position => position ? `${position.x},${position.y}` : "";
const combatDecisionCandidates = () => combatDecision?.context?.legal_candidates || [];
const combatCandidateById = candidateId => combatDecisionCandidates().find(row => row.candidate_id === candidateId) || null;
const combatInteractionCandidates = () => {
  if (!combatInteractionDraft) return [];
  const allowed = new Set(combatInteractionDraft.remaining_candidate_ids || []);
  return combatDecisionCandidates().filter(row => allowed.has(row.candidate_id));
};
const combatInteractionDraftIsCurrent = () => {
  if (!combatInteractionDraft || combatIsHistorical() || !combatDecision?.manual_submit_allowed) return false;
  const currentIds = new Set(combatDecisionCandidates().map(row => row.candidate_id));
  const legalIds = combatInteractionDraft.legal_candidate_ids || [];
  const remainingIds = combatInteractionDraft.remaining_candidate_ids || [];
  return Boolean(
    combatInteractionDraft.match_id === combatMatch?.match_id
    && combatInteractionDraft.decision_id === combatDecision?.context?.decision_id
    && combatInteractionDraft.state_version === combatDecision?.context?.state_version
    && combatInteractionDraft.actor_id === combatDecision?.context?.active_actor_id
    && combatInteractionDraft.controller_mode === combatDecision?.control_mode
    && legalIds.length > 0
    && legalIds.every(id => currentIds.has(id))
    && remainingIds.length > 0
    && remainingIds.every(id => currentIds.has(id) && legalIds.includes(id))
    && combatInteractionCandidates().length === remainingIds.length
  );
};
const combatPendingIntentDraftIsCurrent = () => {
  if (!combatPendingIntentDraft || combatIsHistorical() || !combatDecision?.manual_submit_allowed) return false;
  const intent = combatPendingIntentDraft.intent;
  return Boolean(
    combatPendingIntentDraft.created_for_match_id === combatMatch?.match_id
    && combatPendingIntentDraft.created_for_decision_id === combatDecision?.context?.decision_id
    && combatPendingIntentDraft.created_for_state_version === combatDecision?.context?.state_version
    && combatPendingIntentDraft.created_for_actor_id === combatDecision?.context?.active_actor_id
    && combatPendingIntentDraft.created_for_controller_mode === combatDecision?.control_mode
    && intent?.actor_id === combatDecision?.context?.active_actor_id
    && combatDecisionCandidates().some(row => row.candidate_id === intent?.candidate_id)
  );
};

function combatSetInteractionMode(mode) {
  combatInteractionMode = COMBAT_INTERACTION_MODES.has(mode) ? mode : "inspect";
  const pan = document.getElementById("combatPanMode");
  if (pan) {
    const active = combatInteractionMode === "pan";
    pan.setAttribute("aria-pressed", active ? "true" : "false");
    pan.textContent = active ? "Inspect" : "Pan";
  }
}

function resetCombatInteractionState() {
  combatInteractionDraft = null;
  combatSetInteractionMode("inspect");
  combatPanPointer = null;
}

function cancelCombatMapSelection(message = null, rerender = true) {
  const hadDraft = Boolean(combatInteractionDraft) || ["select_target", "select_destination", "select_area", "select_exact", "pan"].includes(combatInteractionMode);
  resetCombatInteractionState();
  if (message && hadDraft) document.getElementById("combatDecisionStatus").textContent = message;
  if (rerender) {
    renderCombatInteractionBar();
    renderCombatBoard();
    renderCombatSheets();
  }
}

function combatCandidateMapShape(candidate) {
  return [
    candidate.area?.center ? "area" : "",
    candidate.target_ids?.length ? "target" : "",
    candidate.destination ? "destination" : ""
  ].filter(Boolean).join("+");
}

function combatMapCandidatesForPreferred(candidates, preferredCandidateId = null) {
  const preferred = candidates.find(row => row.candidate_id === preferredCandidateId) || candidates[0] || null;
  if (!preferred) return [];
  const shape = combatCandidateMapShape(preferred);
  if (!shape) return [];
  return candidates.filter(row => combatCandidateMapShape(row) === shape);
}

function combatMapSelectionSteps(candidates) {
  if (!candidates.length) return [];
  if (candidates.every(row => row.area?.center && Array.isArray(row.area?.affected_cells))) return ["select_area"];
  const steps = [];
  if (candidates.every(row => row.target_ids?.length)) steps.push("select_target");
  if (candidates.every(row => row.destination)) steps.push("select_destination");
  return steps;
}

// M3 compatibility contract: return {mode: "select_area", candidates: areaCandidates}
function combatMapCandidateKind(candidates) {
  const steps = combatMapSelectionSteps(candidates);
  return steps.length ? {mode: steps[0], steps, candidates} : null;
}

function combatFocusCurrentMapStep() {
  const selector = combatInteractionMode === "select_target"
    ? ".combat-token[data-map-target-eligible=\"true\"]"
    : combatInteractionMode === "select_area"
      ? ".board-cell[data-map-area-eligible=\"true\"]"
      : combatInteractionMode === "select_destination"
        ? ".board-cell[data-map-destination-eligible=\"true\"]"
        : "#combatInteractionChoice";
  requestAnimationFrame(() => document.querySelector(selector)?.focus({preventScroll: true}));
}

function beginCombatMapSelection(candidates, preferredCandidateId = null) {
  if (combatIsHistorical() || !combatDecision?.manual_submit_allowed || !combatMatch) {
    combatSetDiagnostic("Map selection is available only for the live active fighter under an owner-submittable controller.");
    return;
  }
  const exact = new Map(combatDecisionCandidates().map(row => [row.candidate_id, row]));
  const supplied = (candidates || []).map(row => exact.get(row.candidate_id)).filter(Boolean);
  const mapChoice = combatMapCandidateKind(supplied);
  if (!mapChoice?.candidates.length || mapChoice.candidates.some(row => row.actor_id !== combatDecision.context.active_actor_id)) {
    combatSetDiagnostic({
      code: "COMBAT_MAP_SELECTION_SHAPE_UNSUPPORTED",
      message: "The current authoritative candidate family does not expose a closed target, destination, or exact area-center map-selection shape.",
      candidate_ids: supplied.map(row => row.candidate_id)
    });
    return;
  }
  const preferred = mapChoice.candidates.some(row => row.candidate_id === preferredCandidateId)
    ? preferredCandidateId
    : mapChoice.candidates[0].candidate_id;
  combatInteractionDraft = {
    schema: "TianxiaCombatMapSelectionDraft.v2",
    // R6.6.9 M2 legacy documentary identity retained: schema: "TianxiaCombatMapSelectionDraft.v1"
    match_id: combatMatch.match_id,
    decision_id: combatDecision.context.decision_id,
    state_version: combatDecision.context.state_version,
    actor_id: combatDecision.context.active_actor_id,
    controller_mode: combatDecision.control_mode,
    interaction_mode: mapChoice.mode,
    selection_steps: mapChoice.steps,
    step_index: 0,
    legal_candidate_ids: mapChoice.candidates.map(row => row.candidate_id),
    remaining_candidate_ids: mapChoice.candidates.map(row => row.candidate_id),
    preferred_candidate_id: preferred,
    selected_candidate_id: preferred,
    selected_target_id: null,
    selected_destination: null,
    selected_area_center: null
  };
  combatSetInteractionMode(mapChoice.mode);
  renderCombatInteractionBar();
  renderCombatActors();
  renderCombatBoard();
  renderCombatSheets();
  combatFocusCurrentMapStep();
}

function completeCombatMapSelection(candidateId, message = null) {
  if (!combatInteractionDraftIsCurrent()) {
    cancelCombatMapSelection("The map choice became stale. Refresh the current decision.");
    return;
  }
  const candidate = combatCandidateById(candidateId);
  if (!candidate || !combatInteractionDraft.remaining_candidate_ids.includes(candidateId)) {
    combatSetDiagnostic("Only exact candidate IDs from the active map-selection draft can be selected.");
    return;
  }
  combatSelectedCandidateId = candidate.candidate_id;
  const selectedLabel = candidate.area?.center
    ? `area centered at ${candidate.area.center.x}, ${candidate.area.center.y}`
    : candidate.destination && candidate.target_ids?.length
      ? `target ${candidate.target_ids.map(combatActorName).join(", ")} at destination ${candidate.destination.x}, ${candidate.destination.y}`
      : candidate.destination
        ? `destination ${candidate.destination.x}, ${candidate.destination.y}`
        : candidate.target_ids?.length
          ? `target ${candidate.target_ids.map(combatActorName).join(", ")}`
          : "candidate";
  resetCombatInteractionState();
  document.getElementById("combatDecisionStatus").textContent = message || `Selected exact legal ${selectedLabel}. Review it in the active fighter's Combat Sheet.`;
  renderCombatInteractionBar();
  renderCombatActions();
  renderCombatBoard();
  renderCombatSheets();
  requestAnimationFrame(() => {
    const review = [...document.querySelectorAll(".combat-manual-action-control")]
      .find(control => (control.dataset.candidateIds || "").split(";").includes(candidate.candidate_id))
      ?.querySelector("button[data-combat-review-action]");
    review?.focus({preventScroll: false});
  });
}

function advanceCombatMapSelection(matches, selection) {
  if (!combatInteractionDraftIsCurrent() || !matches.length) return;
  const allowed = new Set(combatInteractionDraft.remaining_candidate_ids);
  const exactMatches = matches.filter(row => allowed.has(row.candidate_id));
  if (!exactMatches.length) return;
  combatInteractionDraft.remaining_candidate_ids = exactMatches.map(row => row.candidate_id);
  if (selection?.target_id) combatInteractionDraft.selected_target_id = selection.target_id;
  if (selection?.destination) combatInteractionDraft.selected_destination = selection.destination;
  if (selection?.area_center) combatInteractionDraft.selected_area_center = selection.area_center;
  const preferred = exactMatches.find(row => row.candidate_id === combatInteractionDraft.preferred_candidate_id);
  combatInteractionDraft.selected_candidate_id = (preferred || exactMatches[0]).candidate_id;
  const nextIndex = combatInteractionDraft.step_index + 1;
  if (exactMatches.length === 1) {
    completeCombatMapSelection(exactMatches[0].candidate_id);
    return;
  }
  if (nextIndex < combatInteractionDraft.selection_steps.length) {
    combatInteractionDraft.step_index = nextIndex;
    combatInteractionDraft.interaction_mode = combatInteractionDraft.selection_steps[nextIndex];
    combatSetInteractionMode(combatInteractionDraft.interaction_mode);
    document.getElementById("combatDecisionStatus").textContent = `Map step ${nextIndex + 1} of ${combatInteractionDraft.selection_steps.length}: choose only from the remaining exact candidate IDs.`;
  } else {
    combatInteractionDraft.step_index = combatInteractionDraft.selection_steps.length;
    combatInteractionDraft.interaction_mode = "select_exact";
    combatSetInteractionMode("select_exact");
    document.getElementById("combatDecisionStatus").textContent = "The map choices match multiple exact legal forms. Choose the exact server-issued candidate in the interaction bar.";
  }
  renderCombatInteractionBar();
  renderCombatActors();
  renderCombatBoard();
  renderCombatSheets();
  combatFocusCurrentMapStep();
}

function chooseCombatMapTarget(actorId) {
  if (combatInteractionMode !== "select_target" || !combatInteractionDraftIsCurrent()) return;
  const matches = combatInteractionCandidates().filter(row => row.target_ids?.includes(actorId));
  advanceCombatMapSelection(matches, {target_id: actorId});
}

function chooseCombatMapDestination(x, y) {
  if (combatInteractionMode !== "select_destination" || !combatInteractionDraftIsCurrent()) return;
  const matches = combatInteractionCandidates().filter(row => row.destination?.x === x && row.destination?.y === y);
  advanceCombatMapSelection(matches, {destination: {x, y}});
}

function chooseCombatMapArea(x, y) {
  if (combatInteractionMode !== "select_area" || !combatInteractionDraftIsCurrent()) return;
  const matches = combatInteractionCandidates().filter(row => row.area?.center?.x === x && row.area?.center?.y === y);
  advanceCombatMapSelection(matches, {area_center: {x, y}});
}

function renderCombatInteractionBar() {
  const bar = document.getElementById("combatInteractionBar");
  if (!bar) return;
  const activeModes = ["select_target", "select_destination", "select_area", "select_exact"];
  const active = combatInteractionDraftIsCurrent() && activeModes.includes(combatInteractionMode);
  bar.hidden = !active;
  const viewport = document.getElementById("combatBattlefieldViewport");
  viewport?.classList.toggle("combat-pan-active", combatInteractionMode === "pan");
  const board = document.getElementById("combatBoard");
  for (const mode of ["inspect", "pan", "select_target", "select_destination", "select_area", "select_exact", "measure", "review"]) {
    board?.classList.toggle(`interaction-${mode.replaceAll("_", "-")}`, combatInteractionMode === mode);
  }
  if (!active) return;
  const candidates = combatInteractionCandidates();
  const targetMode = combatInteractionMode === "select_target";
  const areaMode = combatInteractionMode === "select_area";
  const destinationMode = combatInteractionMode === "select_destination";
  const stepNumber = Math.min(combatInteractionDraft.step_index + 1, combatInteractionDraft.selection_steps.length);
  const stepSuffix = combatInteractionMode === "select_exact" ? "Exact form" : `Step ${stepNumber} of ${combatInteractionDraft.selection_steps.length}`;
  document.getElementById("combatInteractionTitle").textContent = targetMode
    ? `Choose a legal target · ${stepSuffix}`
    : areaMode
      ? `Choose a legal area center · ${stepSuffix}`
      : destinationMode
        ? `Choose a legal destination · ${stepSuffix}`
        : "Choose the exact legal form";
  document.getElementById("combatInteractionGuidance").textContent = targetMode
    ? "Highlighted tokens come only from the remaining engine-issued candidate IDs. Inspection remains separate; a later destination step may follow."
    : areaMode
      ? "Highlighted centers and affected squares come directly from exact server-issued area candidates. The browser does not calculate radius, range, line of sight, or affected cells."
      : destinationMode
        ? "Highlighted cells come only from the remaining engine-issued candidate IDs. The browser does not calculate path, range, cost, or legality."
        : "Several exact candidates remain after the map steps. Choose one server-issued form; the browser does not combine or rewrite candidates.";
  const chooser = document.getElementById("combatInteractionChoice"); clearNode(chooser);
  for (const candidate of candidates) {
    const option = document.createElement("option");
    option.value = candidate.candidate_id;
    option.textContent = `${combatCandidateLabel(candidate)} · ${candidate.display_name}`;
    option.selected = candidate.candidate_id === (combatInteractionDraft.selected_candidate_id || combatInteractionDraft.preferred_candidate_id);
    chooser.appendChild(option);
  }
  if (!chooser.value && candidates.length) chooser.value = candidates[0].candidate_id;
  combatInteractionDraft.selected_candidate_id = chooser.value || null;
}
const combatHumanizeId = value => String(value || "")
  .split(":").at(-1)
  .replaceAll("_", " ")
  .replace(/\b\w/g, letter => letter.toUpperCase());
const combatHasPersistentCharacterSheet = actor => Boolean(
  actor?.sheet_link?.available
  && actor.sheet_link.route
  && actor.sheet_link.route_kind === "PERSISTENT_CHARACTER_SHEET"
);
const combatHasCharacterAuthorityDetails = actor => Boolean(
  actor?.sheet_link?.available
  && actor.sheet_link.route
  && actor.sheet_link.route_kind === "CHARACTER_AUTHORITY_DETAILS"
);

function combatSetDiagnostic(value) {
  document.getElementById("combatDiagnostics").textContent = typeof value === "string" ? value : pretty(value);
}

function combatError(error) {
  if (parseAPIError(error).code === "COMBAT_SAVED_FIGHT_UNSUPPORTED" && combatMatch?.match_id) {
    void showUnavailableCombatFight(combatMatch.match_id);
    return;
  }
  const message = plainAPIError(error, error.message || String(error));
  combatSetDiagnostic(error.message || String(error));
  const setup = document.getElementById("combatSetupStatus");
  const auto = document.getElementById("combatAutoStatus");
  if (combatMatch && auto) { auto.textContent = message; auto.classList.add("error"); }
  else if (setup) { setup.textContent = message; setup.classList.add("error"); }
}

const combatControlLabels = {
  LOCAL_AUTO: "Local AI",
  API_AUTO: "API AI",
  MANUAL: "Manual",
  SUGGESTED: "Suggested with approval",
  MANUAL_AI_BRIDGE: "Manual AI bridge — advanced"
};

function combatModeSelect(actor, selectedMode = "MANUAL") {
  const label = document.createElement("label");
  label.className = "fighter-control-label";
  label.textContent = "Who controls this fighter?";
  const select = document.createElement("select");
  select.dataset.combatActor = actor.runtime_entity_id;
  for (const mode of combatCatalog.supported_control_modes) {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = combatControlLabels[mode] || combatHumanizeId(mode);
    if (mode === "API_AUTO" && !combatProviderStatus?.ready) {
      option.disabled = true;
      option.textContent += " — configure API first";
    }
    if (mode === selectedMode || (!combatCatalog.supported_control_modes.includes(selectedMode) && mode === "MANUAL")) option.selected = true;
    select.appendChild(option);
  }
  label.appendChild(select);
  return label;
}

function combatSelectedModes() {
  const modes = {};
  document.querySelectorAll("#combatTeamSetup select[data-combat-actor]").forEach(select => { modes[select.dataset.combatActor] = select.value; });
  return modes;
}

function combatOwnerSetupParticipant(row, controlModes) {
  const authority = combatCatalog.c3c_p1_setup_authority?.[row.runtime_entity_id] || {};
  const resourceValue = name => Number(document.querySelector(`[data-c3c-resource="${name}"][data-c3c-actor="${row.runtime_entity_id}"]`)?.value || 0);
  const placementValue = axis => Number(document.querySelector(`[data-c3c-placement="${axis}"][data-c3c-actor="${row.runtime_entity_id}"]`)?.value || 0);
  return {
    actor_id: row.runtime_entity_id,
    team_id: document.querySelector(`[data-c3c-team][data-c3c-actor="${row.runtime_entity_id}"]`)?.value || "team:1",
    qi_current: resourceValue("qi"), martial_focus_current: resourceValue("martial_focus"),
    stamina_current: resourceValue("stamina"), resonance_current: resourceValue("resonance"),
    controller_mode: controlModes[row.runtime_entity_id] || "MANUAL",
    token_asset_id: authority.token_asset_id || row.character_sheet_identity,
    footprint_width: authority.footprint?.width || 1, footprint_height: authority.footprint?.height || 1,
    placement: {x: placementValue("x"), y: placementValue("y")}
  };
}

function combatVisualPreview(asset, fallbackText) {
  const frame = document.createElement("div");
  frame.className = "fighter-token-preview-frame";
  if (asset?.public_url) {
    const image = document.createElement("img");
    image.src = asset.public_url;
    image.alt = "";
    image.draggable = false;
    frame.appendChild(image);
  } else {
    const fallback = document.createElement("span");
    fallback.className = "fighter-token-fallback";
    fallback.textContent = fallbackText;
    frame.appendChild(fallback);
  }
  return frame;
}

function renderCombatTeamSetup(preservedModes = null) {
  const host = document.getElementById("combatTeamSetup");
  if (!host || !combatCatalog) return;
  const modes = preservedModes || combatSelectedModes();
  clearNode(host);
  const teams = [
    {team_id: "team:1", display_name: document.getElementById("combatTeam1Name")?.value || "Team 1", team_index: 0},
    {team_id: "team:2", display_name: document.getElementById("combatTeam2Name")?.value || "Team 2", team_index: 1}
  ];
  const primary = combatCatalog.projections.filter(row => row.primary_combatant);
  const initialTeam = actor => actor.installed_character ? "team:1" : ((actor.team_index || 0) === 1 ? "team:2" : "team:1");
  for (const team of teams) {
    const teamCard = document.createElement("section");
    teamCard.className = `combat-team-card team-${team.team_index + 1}`;
    const heading = document.createElement("div");
    heading.className = "combat-team-title";
    const title = document.createElement("h4");
    title.textContent = `Team ${team.team_index + 1}: ${team.display_name}`;
    const count = document.createElement("span");
    count.textContent = `${primary.filter(row => initialTeam(row) === team.team_id).length} available`;
    heading.append(title, count);
    const fighterList = document.createElement("div");
    fighterList.className = "fighter-setup-list";
    for (const actor of primary.filter(row => initialTeam(row) === team.team_id)) {
      const fighter = document.createElement("article");
      fighter.className = "fighter-setup-card";
      fighter.dataset.actorId = actor.runtime_entity_id;
      const asset = combatVisualAssets?.tokens?.find(row => (row.stable_actor_ids || []).includes(actor.runtime_entity_id)) || null;
      const preview = combatVisualPreview(asset, actor.display_name.split(/\s+/).map(part => part[0]).join("").slice(0, 2).toUpperCase());
      const body = document.createElement("div");
      body.className = "fighter-setup-body";
      const name = document.createElement("h5");
      name.textContent = actor.display_name;
      const rosterRow = document.createElement("div"); rosterRow.className = "button-row";
      const selectedLabel = document.createElement("label");
      const selected = document.createElement("input"); selected.type = "checkbox"; selected.checked = !actor.installed_character; selected.dataset.c3cSelected = "true"; selected.dataset.c3cActor = actor.runtime_entity_id;
      selectedLabel.append(selected, document.createTextNode(" Primary Combatant"));
      const team = document.createElement("select"); team.dataset.c3cTeam = "true"; team.dataset.c3cActor = actor.runtime_entity_id;
      for (const [value, text] of [["team:1","Team 1"],["team:2","Team 2"]]) { const option=document.createElement("option"); option.value=value; option.textContent=text; if ((actor.team_index||0)===1 && value==="team:2") option.selected=true; team.appendChild(option); }
      rosterRow.append(selectedLabel, team);
      const link = document.createElement("p");
      link.className = "character-link-status";
      link.textContent = actor.installed_character
        ? "Installed Character · Combat Ready · Primary Combatant when selected"
        : `Linked to ${actor.display_name}'s character sheet authority by stable character ID`;
      const uploadRow = document.createElement("div");
      uploadRow.className = "button-row fighter-upload-row";
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/png,image/jpeg,image/webp";
      input.className = "visually-hidden-file";
      input.id = `combatTokenUpload-${actor.runtime_entity_id}`;
      const choose = document.createElement("label");
      choose.className = "button-link upload-button";
      choose.htmlFor = input.id;
      choose.textContent = asset?.source === "owner_upload" ? "Replace Token" : "Choose Token";
      const reset = document.createElement("button");
      reset.type = "button";
      reset.textContent = "Use Built-In";
      reset.disabled = asset?.source !== "owner_upload";
      input.addEventListener("change", async () => {
        const file = input.files?.[0];
        if (!file) return;
        await uploadCombatVisual("token", actor.runtime_entity_id, file);
        input.value = "";
      });
      reset.addEventListener("click", () => resetCombatVisual("token", actor.runtime_entity_id));
      uploadRow.append(choose, input, reset);
      const authority = combatCatalog.c3c_p1_setup_authority?.[actor.runtime_entity_id] || {};
      const setupGrid = document.createElement("div"); setupGrid.className = "fighter-owner-setup-grid";
      for (const resourceName of ["stamina", "qi", "martial_focus", "resonance"]) {
        const resource = authority.resources?.[resourceName];
        if (!resource) continue;
        const labelName = resourceName === "martial_focus" ? "Martial Focus" : `${resourceName[0].toUpperCase()}${resourceName.slice(1)}`;
        const field = document.createElement("label"); field.textContent = `${labelName} current`;
        const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.max = String(resource.maximum); input.value = resource.current == null ? "" : String(resource.current);
        input.dataset.c3cResource = resourceName; input.dataset.c3cActor = actor.runtime_entity_id;
        field.appendChild(input); setupGrid.appendChild(field);
      }
      for (const axis of ["x", "y"]) {
        const field = document.createElement("label"); field.textContent = `Grid ${axis.toUpperCase()}`;
        const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.value = String(authority.placement?.[axis] ?? 0);
        input.dataset.c3cPlacement = axis; input.dataset.c3cActor = actor.runtime_entity_id;
        field.appendChild(input); setupGrid.appendChild(field);
      }
      const footprint = document.createElement("p"); footprint.className = "field-note";
      footprint.textContent = `Typed footprint: ${authority.footprint?.width || 1}×${authority.footprint?.height || 1} (combat authority; read-only)`;
      const advanced = document.createElement("details"); advanced.className = "combat-candidate-advanced";
      const advancedSummary = document.createElement("summary"); advancedSummary.textContent = "Advanced Details";
      const advancedPre = document.createElement("pre");
      advancedPre.textContent = JSON.stringify(actor.installed_character ? {
        source_package_sha256: actor.source_package_sha256, project_id: actor.project_id, project_revision: actor.project_revision,
        combat_sheet_commitment_sha256: actor.combat_sheet_commitment_sha256, mechanics_lock_sha256: actor.mechanics_lock_sha256,
        primitive_registry_sha256: actor.primitive_registry_sha256, runtime_adapter_id: actor.runtime_adapter_id, runtime_engine_version: actor.runtime_engine_version
      } : {character_sheet_identity: actor.character_sheet_identity, projection_sha256: actor.projection_sha256}, null, 2);
      advanced.append(advancedSummary, advancedPre);
      body.append(name, rosterRow, link, combatModeSelect(actor, modes[actor.runtime_entity_id] || "MANUAL"), setupGrid, footprint, advanced, uploadRow);
      fighter.append(preview, body);
      fighterList.appendChild(fighter);
    }
    teamCard.append(heading, fighterList);
    host.appendChild(teamCard);
  }
}

function renderCombatBackgroundSetup() {
  const selected = combatVisualAssets?.maps?.find(row => row.asset_id === combatVisualAssets.default_map_asset_id) || combatVisualAssets?.maps?.[0];
  const image = document.getElementById("combatBackgroundPreview");
  if (selected?.public_url) image.src = selected.public_url;
  else image.removeAttribute("src");
  image.dataset.assetId = selected?.asset_id || "";
  const custom = selected?.source === "owner_upload";
  document.getElementById("combatBackgroundReset").disabled = !custom;
  const mode = document.getElementById("combatBackgroundCalibrationMode");
  if (selected?.calibration?.schema === "TianxiaBattleMapCalibration.v2") {
    mode.value = selected.calibration.fit_mode || "COVER_DECORATIVE";
  }
  const fit = selected?.calibration?.fit_mode;
  const alignment = !selected
    ? "The typed battlefield grid remains authoritative."
    : fit === "EXACT_PLAYABLE_RECT"
    ? "Exact gridless-map alignment is declared for new matches."
    : fit === "CONTAIN_DECORATIVE"
      ? "The image is decorative and may show margins."
      : "The image is decorative and may be cropped.";
  document.getElementById("combatBackgroundStatus").textContent = custom
    ? `Using uploaded background: ${selected.original_filename || "custom image"}. ${alignment} It will be copied into each new match.`
    : selected
      ? `Using the built-in arena. ${alignment} The application grid and typed mechanics remain authoritative.`
      : `No built-in artwork is published. Using the accessible CSS grid and generated fallback tokens. ${alignment}`;
}

function combatFileBase64(file) {
  return file.arrayBuffer().then(buffer => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode(...bytes.subarray(index, Math.min(index + chunk, bytes.length)));
    }
    return btoa(binary);
  });
}

async function uploadCombatVisual(kind, actorId, file) {
  const setupStatus = document.getElementById("combatSetupStatus");
  if (!file || file.size > 12 * 1024 * 1024) {
    setupStatus.textContent = "Choose a PNG, JPEG, or WebP image no larger than 12 MiB.";
    setupStatus.classList.add("error");
    return;
  }
  const preserved = combatSelectedModes();
  setupStatus.textContent = `Saving ${kind === "background" ? "background" : "fighter token"}…`;
  setupStatus.classList.remove("error");
  try {
    const body = {
      original_filename: file.name,
      media_type: file.type,
      data_base64: await combatFileBase64(file),
      calibration_mode: kind === "background"
        ? document.getElementById("combatBackgroundCalibrationMode").value
        : "COVER_DECORATIVE"
    };
    const path = kind === "background"
      ? "/api/combat/setup-visuals/background"
      : `/api/combat/setup-visuals/tokens/${encodeURIComponent(actorId)}`;
    combatVisualAssets = await api(path, {method: "POST", body: JSON.stringify(body)});
    renderCombatBackgroundSetup();
    renderCombatTeamSetup(preserved);
    setupStatus.textContent = kind === "background" ? "Battlefield background saved." : `Token saved and linked to ${combatActorName(actorId)}.`;
  } catch (error) {
    setupStatus.textContent = plainAPIError(error, "The image could not be saved.");
    setupStatus.classList.add("error");
  }
}

async function resetCombatVisual(kind, actorId = null) {
  const preserved = combatSelectedModes();
  try {
    const path = kind === "background"
      ? "/api/combat/setup-visuals/background"
      : `/api/combat/setup-visuals/tokens/${encodeURIComponent(actorId)}`;
    combatVisualAssets = await api(path, {method: "DELETE", body: "{}"});
    renderCombatBackgroundSetup();
    renderCombatTeamSetup(preserved);
    document.getElementById("combatSetupStatus").textContent = kind === "background" ? "Built-in arena restored." : `Built-in token restored for ${combatActorName(actorId)}.`;
  } catch (error) {
    document.getElementById("combatSetupStatus").textContent = plainAPIError(error, "The visual could not be reset.");
  }
}

function renderCombatTechnicalSetup() {
  const readiness = document.getElementById("combatReadinessList");
  clearNode(readiness);
  for (const record of combatCatalog.projections) {
    const card = document.createElement("div");
    card.className = "readiness-card";
    const name = document.createElement("strong"); name.textContent = record.display_name;
    const statusLine = document.createElement("span"); statusLine.className = "readiness-status"; statusLine.textContent = record.readiness_status;
    const reason = document.createElement("p"); reason.textContent = record.readiness_reason;
    card.append(name, statusLine, reason);
    readiness.appendChild(card);
  }
  const controls = document.getElementById("combatControlSetup");
  clearNode(controls);
  for (const actor of combatCatalog.projections.filter(row => row.primary_combatant)) {
    const card = document.createElement("div");
    card.className = "control-mode-card";
    const name = document.createElement("strong"); name.textContent = actor.display_name;
    const id = document.createElement("code"); id.textContent = actor.runtime_entity_id;
    const sheet = document.createElement("p"); sheet.textContent = actor.character_sheet_identity;
    card.append(name, id, sheet);
    controls.appendChild(card);
  }
}

function combatReadinessLine(label, ready = true) {
  const row = document.createElement("li");
  row.className = ready ? "ready" : "required";
  row.textContent = label;
  return row;
}

function renderCombatCandidateInventory() {
  const host = document.getElementById("combatCandidateLibrary");
  const status = document.getElementById("combatCandidateStatus");
  if (!host || !status) return;
  clearNode(host);
  const accepted = combatCandidateInventory?.accepted_candidates || [];
  if (!accepted.length) {
    const empty = document.createElement("p");
    empty.className = "honest-limit";
    empty.textContent = "No combat-ready characters are available yet. Finish or import one from Character Sheets.";
    host.appendChild(empty);
  }
  for (const candidate of accepted) {
    const card = document.createElement("article");
    card.className = "combat-candidate-card";
    card.dataset.candidateEntryId = candidate.entry_id;

    const heading = document.createElement("div");
    heading.className = "combat-candidate-card-heading";
    const title = document.createElement("div");
    const name = document.createElement("h4");
    name.textContent = candidate.display_name;
    const identity = document.createElement("p");
    identity.textContent = `HP ${candidate.hp_maximum} · AC ${candidate.armor_class} · Speed ${candidate.speed_ft} ft`;
    title.append(name, identity);
    const badge = document.createElement("span");
    badge.className = "readiness-badge";
    badge.textContent = "Ready for setup";
    heading.append(title, badge);
    card.appendChild(heading);

    const readiness = document.createElement("ul");
    readiness.className = "combat-candidate-readiness";
    readiness.append(
      combatReadinessLine("Character ready"),
      combatReadinessLine("GM ready"),
      combatReadinessLine("Combat runtime ready"),
      combatReadinessLine("Encounter setup required", false),
      combatReadinessLine("Current Qi required", false),
      combatReadinessLine("Current Martial Focus required", false),
      combatReadinessLine("Opponent / team completion required", false),
      combatReadinessLine("Battlefield owner choice not committed", false),
      combatReadinessLine("Token placement not committed", false),
      combatReadinessLine("Initiative not attempted", false),
      combatReadinessLine("Controllers not selected", false)
    );
    const readinessDetails = document.createElement("details");
    readinessDetails.className = "combat-candidate-readiness-details";
    const readinessSummary = document.createElement("summary"); readinessSummary.textContent = "Setup checklist";
    readinessDetails.append(readinessSummary, readiness); card.appendChild(readinessDetails);

    const form = document.createElement("div");
    form.className = "combat-candidate-fields";
    const qiLabel = document.createElement("label");
    qiLabel.textContent = `Current Qi (0–${candidate.resource_maxima["resource:core.qi"]})`;
    const qi = document.createElement("input");
    qi.type = "number"; qi.min = "0"; qi.max = String(candidate.resource_maxima["resource:core.qi"]); qi.step = "1";
    qi.dataset.field = "qi"; qi.placeholder = "Required";
    qiLabel.appendChild(qi);
    const focusLabel = document.createElement("label");
    focusLabel.textContent = `Current Martial Focus (0–${candidate.resource_maxima["resource:core.martial_focus"]})`;
    const focus = document.createElement("input");
    focus.type = "number"; focus.min = "0"; focus.max = String(candidate.resource_maxima["resource:core.martial_focus"]); focus.step = "1";
    focus.dataset.field = "focus"; focus.placeholder = "Required";
    focusLabel.appendChild(focus);
    const teamLabel = document.createElement("label");
    teamLabel.textContent = "Team assignment";
    const team = document.createElement("input");
    team.type = "text"; team.maxLength = 240; team.dataset.field = "team"; team.placeholder = "Required, for example Team Jade";
    teamLabel.appendChild(team);
    form.append(qiLabel, focusLabel, teamLabel);
    card.appendChild(form);

    const actions = document.createElement("div");
    actions.className = "button-row";
    const preview = document.createElement("button");
    preview.type = "button"; preview.textContent = "Check character setup";
    preview.addEventListener("click", () => previewCombatCandidateDraft(candidate.entry_id, card));
    actions.appendChild(preview);
    card.appendChild(actions);

    const details = document.createElement("details");
    details.className = "combat-candidate-advanced";
    const summary = document.createElement("summary");
    summary.textContent = "Advanced details";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify({
      entry_id: candidate.entry_id,
      character_project_id: candidate.character_project_id,
      source_package_sha256: candidate.source_package_sha256,
      combat_sheet_commitment_sha256: candidate.combat_sheet_commitment_sha256,
      mechanics_lock_sha256: candidate.mechanics_lock_sha256,
      primitive_registry_sha256: candidate.primitive_registry_sha256,
      runtime_adapter_id: candidate.runtime_adapter_id,
      runtime_adapter_version: candidate.runtime_adapter_version,
      runtime_engine_version: candidate.runtime_engine_version,
      encounter_status: candidate.encounter_status,
      controller_status: candidate.controller_status
    }, null, 2);
    details.append(summary, pre);
    card.appendChild(details);
    host.appendChild(card);
  }
  const blockedRows = combatCandidateInventory?.blocked_candidates || [];
  for (const blocked of blockedRows) {
    const card = document.createElement("article"); card.className = "combat-candidate-card blocked";
    const heading = document.createElement("div"); heading.className = "combat-candidate-card-heading";
    const title = document.createElement("div");
    const name = document.createElement("h4"); name.textContent = "Character unavailable";
    const message = document.createElement("p"); message.textContent = blocked.message || "This package is not available for combat.";
    const badge = document.createElement("span"); badge.className = "readiness-badge"; badge.textContent = "Unavailable";
    title.append(name, message); heading.append(title, badge); card.appendChild(heading);
    const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Advanced Details";
    const reason = document.createElement("p"); reason.className = "honest-limit"; reason.textContent = `Blocked: ${blocked.code || "EXACT_VALIDATION_FAILED"}`;
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify({package_sha256: blocked.package_sha256, installed_record: blocked.installed_record, details: blocked.details}, null, 2);
    details.append(summary, reason, pre); card.appendChild(details); host.appendChild(card);
  }
  const blocked = blockedRows.length;
  status.textContent = `${accepted.length} ${accepted.length === 1 ? "character is" : "characters are"} ready for combat.${blocked ? ` ${blocked} ${blocked === 1 ? "character is" : "characters are"} currently unavailable.` : ""}`;
}

function renderCombatDraftPreview(draft) {
  const host = document.getElementById("combatPreEncounterDraftResult");
  if (!host) return;
  clearNode(host);
  const panel = document.createElement("section");
  panel.className = "combat-draft-preview-card";
  const heading = document.createElement("h4");
  heading.textContent = draft.readiness_state === "DRAFT_VALIDATED_PRE_PLACEMENT"
    ? "Draft validated before placement"
    : `Draft blocked: ${friendlyLabel(draft.readiness_state)}`;
  const explanation = document.createElement("p");
  explanation.textContent = "This checksum-committed preview is not a match. It wrote no events, positions, initiative, controllers, journal, or combat history.";
  const requirements = document.createElement("ul");
  for (const item of draft.unresolved_requirements || []) {
    const row = document.createElement("li");
    row.textContent = item.message;
    requirements.appendChild(row);
  }
  const details = document.createElement("details");
  const summary = document.createElement("summary"); summary.textContent = "Draft identity and validation";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify({
    draft_id: draft.draft_id,
    draft_commitment_sha256: draft.draft_commitment_sha256,
    readiness_state: draft.readiness_state,
    validation_report: draft.validation_report,
    persisted_event_count: draft.persisted_event_count,
    is_match: draft.is_match,
    persistent: draft.persistent
  }, null, 2);
  details.append(summary, pre);
  const discard = document.createElement("button");
  discard.type = "button"; discard.textContent = "Discard Preview";
  discard.addEventListener("click", async () => {
    try {
      await api("/api/combat/pre-encounter-drafts/discard", {method: "POST", body: JSON.stringify({draft_id: draft.draft_id})});
      clearNode(host);
      const message = document.createElement("p");
      message.className = "friendly-status";
      message.textContent = "Preview discarded. It was never persisted, so no combat state was deleted or changed.";
      host.appendChild(message);
    } catch (error) { host.textContent = plainAPIError(error, "The preview could not be discarded."); }
  });
  panel.append(heading, explanation, requirements, details, discard);
  host.appendChild(panel);
}

async function previewCombatCandidateDraft(entryId, card) {
  const result = document.getElementById("combatPreEncounterDraftResult");
  const qiRaw = card.querySelector('[data-field="qi"]')?.value ?? "";
  const focusRaw = card.querySelector('[data-field="focus"]')?.value ?? "";
  const teamId = card.querySelector('[data-field="team"]')?.value?.trim() || null;
  const battlefield = combatCatalog?.battlefields?.[0];
  const body = {
    participants: [{
      candidate_entry_id: entryId,
      team_id: teamId,
      qi_current: qiRaw === "" ? null : Number(qiRaw),
      martial_focus_current: focusRaw === "" ? null : Number(focusRaw),
      provenance_kind: "ENCOUNTER_AUTHORITY",
      provenance_id: `owner-preview:${entryId}`
    }],
    battlefield_id: battlefield?.stable_id || null,
    battlefield_provenance_kind: battlefield ? "TEST_FIXTURE" : null,
    battlefield_provenance_id: battlefield ? `c3b-ui-preview:${battlefield.stable_id}` : null
  };
  if (result) result.textContent = "Validating the non-persistent draft…";
  try {
    const draft = await api("/api/combat/pre-encounter-drafts/preview", {method: "POST", body: JSON.stringify(body)});
    renderCombatDraftPreview(draft);
  } catch (error) {
    if (result) result.textContent = plainAPIError(error, "The draft could not be validated.");
  }
}

async function loadCombatCatalog() {
  try {
    const [status, catalog, visualAssets, candidateInventory] = await Promise.all([
      api("/api/combat/status"),
      api("/api/combat/catalog"),
      api("/api/combat/visual-assets"),
      api("/api/combat/candidates")
    ]);
    combatCatalog = catalog;
    combatCandidateInventory = candidateInventory;
    combatVisualAssets = visualAssets;
    combatProviderStatus = status.api_auto || {ready: false};
    const badge = document.getElementById("combatServiceStatus");
    badge.hidden = false;
    badge.textContent = status.available ? "Combat ready" : "Combat unavailable";
    document.getElementById("combatAPIStatus").textContent = combatProviderStatus.ready
      ? `API AI ready · ${combatProviderStatus.settings?.model || combatProviderStatus.provider_id}`
      : "API AI not configured · Local AI ready";
    const encounterSelect = document.getElementById("combatEncounter");
    clearNode(encounterSelect);
    for (const encounter of catalog.encounters) {
      const option = document.createElement("option");
      option.value = encounter.stable_id;
      option.textContent = `${encounter.display_name} — ${encounter.readiness_status}`;
      encounterSelect.appendChild(option);
      if (!document.getElementById("combatDisplayName").value) document.getElementById("combatDisplayName").placeholder = encounter.display_name;
    }
    renderCombatCandidateInventory();
    renderCombatBackgroundSetup();
    renderCombatTeamSetup();
    renderCombatTechnicalSetup();
    document.getElementById("combatKnownLimitations").textContent = catalog.known_limitations.join(" ");
    await loadCombatMatches();
  } catch (error) {
    const badge = document.getElementById("combatServiceStatus");
    badge.hidden = false;
    badge.textContent = "Combat unavailable";
    combatError(error);
  }
}

function setCombatSetupView(view) {
  const advanced = view === "advanced";
  document.getElementById("combatFriendlySetup").hidden = advanced;
  document.getElementById("combatAdvancedSetup").hidden = !advanced;
  for (const [id, active] of [["combatFriendlySetupTab", !advanced], ["combatAdvancedSetupTab", advanced]]) {
    const button = document.getElementById(id);
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }
}

function setCombatWorkspaceActive(active) {
  const workspace = document.getElementById("combatWorkspace");
  const setup = document.getElementById("combatSetup");
  const intro = document.getElementById("combatScreenIntro");
  workspace.hidden = !active;
  setup.hidden = active;
  intro.hidden = active;
  document.getElementById("screen-combat").classList.toggle("combat-match-open", active);
}

function combatUsesBottomSheet() {
  const viewport = document.getElementById("combatBattlefieldViewport");
  return window.matchMedia("(max-width: 760px)").matches || Boolean(viewport && viewport.clientWidth > 0 && viewport.clientWidth < 620);
}

function combatUpdateSheetLayoutMode() {
  const compact = combatUsesBottomSheet();
  document.getElementById("combatWorkspace")?.classList.toggle("combat-sheet-bottom-mode", compact);
  return compact;
}

function setCombatWorkspaceView(view) {
  const technical = view === "technical";
  combatWorkspaceMode = technical ? "technical" : "owner";
  document.getElementById("combatOwnerWorkspace").hidden = technical;
  document.getElementById("combatMobileTabs").hidden = technical;
  document.getElementById("combatAdvancedWorkspace").hidden = !technical;
  document.getElementById("combatOwnerView").classList.toggle("active", !technical);
  document.getElementById("combatTechnicalView").classList.toggle("active", technical);
  if (technical && combatInteractionDraft) cancelCombatMapSelection("Map selection canceled when Advanced view opened.", false);
  if (!technical) renderCombatMatch();
  else { renderCombatInteractionBar(); combatUpdateAuthorityDetailsControl(); }
}

// Owner 2026-09-25: build a fight from your own finished characters, team by team
// (replaces the fixed demo fighters as the main setup).
const FIGHT_BUILDER_MAX_PER_TEAM = 3;  // built-in maps provide three start spots per side
// Every fighter runs on the Local AI (its Dao policy).  Manual control is not offered yet: the fight view
// does not show the action picker for Factory fighters.

async function loadFactoryFighters() {
  const host = document.getElementById("combatFactoryPanel");
  if (!host) return;
  let characters = [];
  try { characters = await api("/api/combat/factory-characters"); } catch (error) { combatError(error); return; }
  // The saved-fight list refreshes after every fight; keep the owner's picks unless the roster changed.
  const signature = characters.map(character => character.project_id).join(",");
  if (host.dataset.signature === signature) return;
  host.dataset.signature = signature;
  clearNode(host);
  if (!characters.length) {
    host.appendChild(Object.assign(document.createElement("p"), {textContent: "No finished characters yet. Finalize a character and it appears here."}));
    return;
  }
  const label = character => [character.display_name, character.path, character.cultivation_level ? `CL ${character.cultivation_level}` : ""].filter(Boolean).join(" · ");
  const teams = [];
  const grid = document.createElement("div"); grid.className = "fight-builder-teams";
  for (const [index, title] of ["Team 1", "Team 2"].entries()) {
    const column = document.createElement("div"); column.className = "fight-builder-team";
    column.appendChild(Object.assign(document.createElement("h4"), {textContent: title}));
    const slots = document.createElement("div"); slots.className = "fight-builder-slots";
    const add = Object.assign(document.createElement("button"), {type: "button", textContent: "+ Add fighter"});
    const team = {slots: [], host: slots, add};
    const addSlot = () => {
      if (team.slots.length >= FIGHT_BUILDER_MAX_PER_TEAM) return;
      const row = document.createElement("div"); row.className = "fight-builder-slot";
      const who = document.createElement("select"); who.setAttribute("aria-label", `${title} fighter`);
      who.appendChild(Object.assign(document.createElement("option"), {value: "", textContent: "— choose a character —"}));
      for (const character of characters) who.appendChild(Object.assign(document.createElement("option"), {value: character.project_id, textContent: label(character)}));
      const remove = Object.assign(document.createElement("button"), {type: "button", textContent: "Remove", title: "Remove this fighter"});
      const slot = {who, row};
      remove.addEventListener("click", () => {
        if (team.slots.length <= 1) { who.value = ""; return; }
        team.slots.splice(team.slots.indexOf(slot), 1); row.remove(); add.disabled = false;
      });
      row.append(who, remove);
      slots.appendChild(row); team.slots.push(slot);
      add.disabled = team.slots.length >= FIGHT_BUILDER_MAX_PER_TEAM;
    };
    add.addEventListener("click", addSlot);
    addSlot();
    column.append(slots, add);
    grid.appendChild(column); teams.push(team);
  }
  const footer = document.createElement("div"); footer.className = "fight-builder-footer";
  const name = Object.assign(document.createElement("input"), {type: "text", maxLength: 240, placeholder: "Fight name (optional)"});
  name.setAttribute("aria-label", "Fight name");
  const arena = document.createElement("select"); arena.setAttribute("aria-label", "Arena");
  const arenaDescription = document.createElement("p");
  let arenaRows = [];
  const describeArena = () => { arenaDescription.textContent = arenaRows.find(row => row.arena_id === arena.value)?.description || ""; };
  arena.addEventListener("change", describeArena);
  try {
    arenaRows = await api("/api/combat/factory-arenas");
    for (const row of arenaRows) arena.appendChild(Object.assign(document.createElement("option"), {value: row.arena_id, textContent: row.display_name}));
    describeArena();
  } catch (error) { /* the server's default arena is used */ }
  const start = Object.assign(document.createElement("button"), {type: "button", className: "primary-action", textContent: "Create Fight"});
  start.addEventListener("click", async () => {
    const picked = teams.map(team => team.slots.filter(slot => slot.who.value).map(slot => ({pid: slot.who.value})));
    if (!picked[0].length || !picked[1].length) { combatError(new Error("Choose at least one character for each team.")); return; }
    const all = [...picked[0], ...picked[1]].map(row => row.pid);
    if (new Set(all).size !== all.length) { combatError(new Error("A character can only fight once per fight; choose different characters.")); return; }
    start.disabled = true;
    try {
      const view = await api("/api/combat/factory-matches", {method: "POST", body: JSON.stringify({
        project_ids: picked[0].map(row => row.pid), opponent_actor_ids: picked[1].map(row => `actor:factory.${row.pid}`),
        display_name: name.value.trim() || null, arena_id: arena.value || null})});
      await loadCombatMatches();
      await openCombatMatch(view.match_id);
    } catch (error) { combatError(error); } finally { start.disabled = false; }
  });
  footer.append(name, arena, arenaDescription, start);
  host.append(grid, footer);
}

async function loadCombatMatches() {
  if (!combatCatalog) return [];
  loadFactoryFighters();
  const rows = await api("/api/combat/matches");
  const host = document.getElementById("combatMatchList");
  clearNode(host);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No persistent combat matches yet.";
    host.appendChild(empty);
    return rows;
  }
  for (const row of rows) {
    const card = document.createElement("div"); card.className = "match-card";
    const copy = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = row.display_name || row.match_id;
    const detail = document.createElement("div"); detail.className = "action-meta";
    detail.textContent = row.unavailable_message || (row.state_version == null ? "Saved fight"
      : `${row.status || "Saved fight"} · state ${row.state_version} · ${row.paused ? "paused" : "ready"}`);
    copy.append(title, detail);
    const button = document.createElement("button"); button.type = "button"; button.textContent = "Open Fight";
    button.addEventListener("click", () => openCombatMatch(row.match_id));
    // Owner 2026-09-25: the same fight on the table (grid, fog, action buttons, dice).
    const table = Object.assign(document.createElement("a"), {href: `/tabletop?match=${encodeURIComponent(row.match_id)}`, target: "_blank", rel: "noopener", className: "button-link", textContent: "Open on table ↗"});
    const actions = document.createElement("div"); actions.className = "button-row"; actions.append(table, button);
    card.append(copy, actions); host.appendChild(card);
  }
  return rows;
}

async function loadCombatHistory(matchId) {
  const epoch = combatExecutionEpoch;
  const history = await api(`/api/combat/matches/${combatId(matchId)}/history`);
  if (epoch !== combatExecutionEpoch || combatMatch?.match_id !== matchId) return null;
  const presentation = await api(`/api/combat/matches/${combatId(matchId)}/presentation`);
  if (epoch !== combatExecutionEpoch || combatMatch?.match_id !== matchId) return null;
  combatHistory = history;
  combatHistoryIndex = null;
  combatPresentation = presentation;
  return combatHistory;
}

function closeCombatMatch() {
  combatAutoRunning = false;
  combatExecutionEpoch += 1;
  combatHistoryTransitionPending = false;
  combatHistoryTransitionSerial += 1;
  combatMatch = null; combatHistory = null; combatHistoryIndex = null; combatPresentation = null;
  combatDecision = null; combatAIValidationToken = null; combatSelectedCandidateId = null;
  combatSelectedActorId = null; combatPinnedActorId = null;
  cancelCombatPendingIntent();
  setCombatWorkspaceActive(false);
}

async function showUnavailableCombatFight(matchId) {
  closeCombatMatch();
  try {
    const {offerSavedFightRemoval} = await import("./saved_fight_unavailable.js?v=p20261010-06");
    await offerSavedFightRemoval(matchId);
  } catch (deleteError) { combatError(deleteError); }
  await loadCombatMatches().catch(combatError);
}

async function openCombatMatch(matchId) {
  closeCombatMatch();
  const openingEpoch = combatExecutionEpoch;
  try {
    const match = await api(`/api/combat/matches/${combatId(matchId)}`);
    if (openingEpoch !== combatExecutionEpoch) return;
    combatMatch = match;
    await loadCombatHistory(matchId);
    if (openingEpoch !== combatExecutionEpoch) return;
    cancelCombatPendingIntent();
    combatDecision = null; combatAIValidationToken = null; combatSelectedCandidateId = null;
    combatSelectedActorId = null; combatPinnedActorId = null; combatFollowCurrentTurn = true;
    combatAutoRunning = false; combatHistoryTransitionPending = false;
    setCombatWorkspaceActive(true);
    setCombatWorkspaceView("owner");
    renderCombatMatch();
    await refreshCombatDecision();
    if (openingEpoch !== combatExecutionEpoch || combatMatch?.match_id !== matchId) return;
    document.getElementById("combatWorkspace").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    if (openingEpoch !== combatExecutionEpoch) return;
    if (parseAPIError(error).code === "COMBAT_SAVED_FIGHT_UNSUPPORTED") return showUnavailableCombatFight(matchId);
    closeCombatMatch();
    combatError(error);
  }
}

function combatSetHistoricalMode() {
  const historical = combatIsHistorical();
  document.getElementById("combatHistoricalBanner").hidden = !historical;
  document.getElementById("combatReturnLive").hidden = !historical;
  document.getElementById("combatAutoPanel").hidden = historical;
  for (const panelId of ["combatDecisionPanel", "combatControllerPanel", "combatAIBridgePanel"]) {
    document.getElementById(panelId).hidden = historical;
  }
  for (const controlId of ["combatPause", "combatResume", "combatSnapshot"]) {
    document.getElementById(controlId).disabled = historical;
  }
}

function renderCombatHistoryControls() {
  const slider = document.getElementById("combatHistorySlider");
  const jump = document.getElementById("combatHistoryJump");
  const previous = document.getElementById("combatHistoryPrevious");
  const next = document.getElementById("combatHistoryNext");
  const status = document.getElementById("combatHistoryStatus");
  const boundaries = combatHistory?.boundaries || [];
  if (!boundaries.length) {
    slider.disabled = true; jump.disabled = true; previous.disabled = true; next.disabled = true;
    status.textContent = "No committed history is available for this match.";
    clearNode(jump);
    return;
  }
  const displayIndex = combatHistoryIndex === null ? boundaries.length - 1 : combatHistoryIndex;
  slider.min = "0"; slider.max = String(boundaries.length - 1); slider.value = String(displayIndex); slider.disabled = false;
  clearNode(jump);
  boundaries.forEach((boundary, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = boundary.step_label;
    option.selected = index === displayIndex;
    jump.appendChild(option);
  });
  jump.disabled = false;
  previous.disabled = displayIndex <= 0;
  next.disabled = displayIndex >= boundaries.length - 1;
  const boundary = boundaries[displayIndex];
  status.textContent = combatHistoryIndex === null
    ? `Live state · latest committed step ${displayIndex} · round ${boundary.round_number} · ${boundary.current_actor_name}`
    : `${boundary.step_label} · journal record ${boundary.record_sequence}`;
}

async function setCombatHistoryIndex(index) {
  const existingBoundaries = combatHistory?.boundaries || [];
  if (!existingBoundaries.length || !combatMatch) return;
  const requestedIndex = Math.max(0, Math.min(existingBoundaries.length - 1, Number(index)));
  const transitionSerial = ++combatHistoryTransitionSerial;
  combatAutoRunning = false;
  combatExecutionEpoch += 1;
  combatHistoryTransitionPending = true;
  combatHistoryIndex = requestedIndex;
  combatDecision = null;
  cancelCombatPendingIntent();
  combatSetHistoricalMode();
  renderCombatHistoryControls();
  document.getElementById("combatAutoStatus").textContent = "Automatic execution stopped. Loading the selected authoritative history boundary…";
  try {
    const pendingStep = combatAutoStepPromise;
    if (pendingStep) await pendingStep.catch(() => null);
    if (transitionSerial !== combatHistoryTransitionSerial || !combatMatch) return;
    const matchId = combatMatch.match_id;
    const history = await api(`/api/combat/matches/${combatId(matchId)}/history`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    combatHistory = history;
    const boundaries = combatHistory?.boundaries || [];
    if (!boundaries.length) {
      combatHistoryIndex = null;
      return;
    }
    combatHistoryIndex = Math.max(0, Math.min(boundaries.length - 1, requestedIndex));
    const presentation = await api(`/api/combat/matches/${combatId(matchId)}/presentation?boundary=${combatHistoryIndex}`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    combatPresentation = presentation;
    renderCombatMatch();
  } catch (error) {
    if (transitionSerial === combatHistoryTransitionSerial) combatError(error);
  } finally {
    if (transitionSerial === combatHistoryTransitionSerial) combatHistoryTransitionPending = false;
  }
}

async function returnCombatLive() {
  if (!combatMatch) return;
  const transitionSerial = ++combatHistoryTransitionSerial;
  combatAutoRunning = false;
  combatExecutionEpoch += 1;
  combatHistoryTransitionPending = false;
  combatHistoryIndex = null;
  try {
    const matchId = combatMatch.match_id;
    const match = await api(`/api/combat/matches/${combatId(matchId)}`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    combatMatch = match;
    await loadCombatHistory(matchId);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    renderCombatMatch();
    await refreshCombatDecision();
  } catch (error) { if (transitionSerial === combatHistoryTransitionSerial) combatError(error); }
}

function combatProjectionActor(actorId) {
  return combatPresentation?.actors?.find(actor => actor.entity_id === actorId) || null;
}

function combatEnsureSelectedActor() {
  const actorIds = new Set((combatPresentation?.actors || []).map(actor => actor.entity_id));
  if (combatPinnedActorId && !actorIds.has(combatPinnedActorId)) combatPinnedActorId = null;
  if (combatSelectedActorId && !actorIds.has(combatSelectedActorId)) combatSelectedActorId = null;
  if (combatPinnedActorId) {
    combatFollowCurrentTurn = false;
    combatSelectedActorId = combatPinnedActorId;
  } else if (combatFollowCurrentTurn && combatPresentation?.current_actor_id) {
    combatSelectedActorId = combatPresentation.current_actor_id;
  }
  if (!combatSelectedActorId && combatFollowCurrentTurn) combatSelectedActorId = combatPresentation?.current_actor_id || combatPresentation?.actors?.[0]?.entity_id || null;
}

function combatUpdateAuthorityDetailsControl() {
  const authorityButton = document.getElementById("combatCharacterAuthorityDetails");
  if (!authorityButton) return;
  const inspectedActor = combatProjectionActor(combatSelectedActorId);
  authorityButton.disabled = !combatHasCharacterAuthorityDetails(inspectedActor);
  authorityButton.textContent = inspectedActor ? `Character Authority Details: ${inspectedActor.display_name}` : "Character Authority Details";
}

function combatSetMobileTab(tab) {
  combatMobileTab = ["map", "teams", "feed", "history"].includes(tab) ? tab : "map";
  const workspace = document.getElementById("combatOwnerWorkspace");
  workspace.dataset.mobileTab = combatMobileTab;
  for (const button of document.querySelectorAll("[data-combat-mobile-tab]")) {
    const active = button.dataset.combatMobileTab === combatMobileTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  }
}

function combatControlLabel(mode) {
  return combatControlLabels[mode] || combatHumanizeId(mode);
}

function combatTurnPills(actor) {
  if (!actor) return [];
  return [
    actor.turn_state?.action ? "Action ready" : "Action used",
    actor.turn_state?.bonus_action ? "Bonus ready" : "Bonus used",
    actor.turn_state?.reaction ? "Reaction ready" : "Reaction used",
    `${actor.movement_remaining_ft} ft movement`
  ];
}

function renderCombatMatch() {
  if (!combatMatch || !combatPresentation) return;
  combatEnsureSelectedActor();
  const state = combatPresentation;
  const boundary = combatSelectedBoundary();
  document.getElementById("combatMatchTitle").textContent = state.display_name || combatMatch.metadata.display_name;
  document.getElementById("combatTurnSummary").textContent = state.mode === "HISTORY"
    ? `${state.boundary?.step_label || `Historical step ${combatHistoryIndex}`}`
    : state.terminal_result
      ? `Match complete · ${state.terminal_result.kind} · ${state.terminal_result.reason}`
      : `Round ${state.round_number} · ${combatActorName(state.current_actor_id)}`;
  const current = combatProjectionActor(state.current_actor_id);
  document.getElementById("combatControllerSummary").textContent = `${state.mode === "HISTORY" ? "History" : "Live"} · ${current ? combatControlLabel(current.controller) : "validated combat authority"}`;
  document.getElementById("combatExport").href = `/api/combat/matches/${combatId(combatMatch.match_id)}/export`;
  const autoStatus = document.getElementById("combatAutoStatus");
  const runButton = document.getElementById("combatLocalRun");
  if (state.terminal_result) {
    autoStatus.textContent = `Fight complete: ${state.terminal_result.reason}`;
    runButton.textContent = "Fight Complete";
    runButton.disabled = true;
  } else if (state.paused) {
    autoStatus.textContent = "Fight paused.";
    runButton.textContent = "Run Auto";
    runButton.disabled = true;
  } else {
    const mode = current?.controller || "MANUAL";
    autoStatus.textContent = `${current?.display_name || "Active fighter"} · ${combatControlLabel(mode)}`;
    // While Run Auto is playing, every turn re-renders; keep showing that it is running (owner 2026-09-25).
    runButton.textContent = combatAutoRunning ? "Auto Fight Running…" : "Run Auto";
    runButton.disabled = combatAutoRunning || combatIsHistorical() || !["LOCAL_AUTO", "API_AUTO"].includes(mode);
  }
  document.getElementById("combatResume").hidden = Boolean(state.terminal_result) || !state.paused;
  document.getElementById("combatPause").hidden = Boolean(state.terminal_result) || state.paused;
  if (state.terminal_result && combatMatch.final_summary) {
    const final = combatMatch.final_summary;
    const winner = final.terminal_result?.winning_team_id ? (final.teams?.[final.terminal_result.winning_team_id] || final.terminal_result.winning_team_id) : "Draw";
    document.getElementById("combatControllerSummary").textContent = `Fight Complete · ${winner} · ${final.counts.events} events · ${final.counts.rolls} rolls · verification ${final.verification.status}`;
  }
  combatUpdateAuthorityDetailsControl();
  const findingBanner = document.getElementById("combatPresentationFindingBanner");
  const visibleFindings = (state.findings || []).filter(row => ["WARNING", "ERROR"].includes(row.severity));
  findingBanner.hidden = !visibleFindings.length;
  findingBanner.dataset.severity = visibleFindings.some(row => row.severity === "ERROR") ? "ERROR" : "WARNING";
  findingBanner.textContent = visibleFindings.slice(0, 3).map(row => `${combatHumanizeId(row.code)}: ${row.message}`).join(" ");
  renderCombatHistoryControls();
  combatSetHistoricalMode();
  renderCombatActors();
  renderCombatCurrentTurn();
  renderCombatInitiative();
  renderCombatBoard();
  renderCombatSheets();
  renderCombatEvents();
  combatSetMobileTab(combatMobileTab);
  combatSetDiagnostic({
    diagnostics: combatMatch.diagnostics,
    presentation_findings: state.findings,
    presentation_schema: state.schema,
    history_read_only: combatHistory?.read_only,
    selected_boundary: boundary ? {boundary_index: boundary.boundary_index, record_sequence: boundary.record_sequence, canonical_state_sha256: boundary.canonical_state_sha256} : null,
    metadata: combatMatch.metadata,
    terminal_result: state.terminal_result
  });
}

function renderCombatActors() {
  const host = document.getElementById("combatActorCards");
  clearNode(host);
  for (const team of combatPresentation?.teams || []) {
    const section = document.createElement("section");
    section.className = `combat-roster-team team-index-${team.team_index}`;
    const title = document.createElement("h4");
    const mark = document.createElement("span");
    mark.className = "combat-team-mark";
    mark.textContent = String(team.team_index + 1);
    title.append(mark, document.createTextNode(team.display_name));
    section.appendChild(title);
    for (const actorId of team.actor_ids) {
      const actor = combatProjectionActor(actorId);
      if (!actor) continue;
      const row = document.createElement("button");
      row.type = "button";
      row.className = `combat-roster-row${actor.current_actor ? " current" : ""}${combatSelectedActorId === actor.entity_id ? " selected" : ""}${actor.active ? "" : " inactive"}`;
      row.dataset.actorId = actor.entity_id;
      const visual = document.createElement("span");
      visual.className = "combat-roster-token";
      if (actor.visual?.kind === "image" && actor.visual.public_url) {
        const image = document.createElement("img");
        image.src = actor.visual.public_url;
        image.alt = "";
        image.draggable = false;
        visual.appendChild(image);
      } else {
        visual.textContent = actor.visual?.initials || actor.display_name.slice(0, 2).toUpperCase();
      }
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = actor.display_name;
      const detail = document.createElement("small");
      detail.textContent = `${actor.hit_points.current} / ${actor.hit_points.maximum} HP${actor.current_actor ? " · Current" : ""}${actor.owner_display_name ? ` · Companion of ${actor.owner_display_name}` : ""}`;
      copy.append(name, detail);
      row.append(visual, copy);
      row.setAttribute("aria-label", `${actor.display_name}, ${detail.textContent}`);
      row.addEventListener("click", () => selectCombatActor(actor.entity_id));
      section.appendChild(row);
    }
    host.appendChild(section);
  }
}

function renderCombatCurrentTurn() {
  const actor = combatProjectionActor(combatPresentation?.current_actor_id);
  document.getElementById("combatCurrentTurnHeading").textContent = actor?.display_name || "Match complete";
  document.getElementById("combatCurrentTurnDetail").textContent = actor
    ? `${combatControlLabel(actor.controller)} is choosing from engine-validated actions.`
    : combatPresentation?.terminal_result?.reason || "No active actor.";
  const host = document.getElementById("combatCurrentTurnStats");
  clearNode(host);
  for (const label of combatTurnPills(actor)) {
    const pill = document.createElement("span");
    pill.textContent = label;
    host.appendChild(pill);
  }
}

function renderCombatInitiative() {
  const host = document.getElementById("combatInitiative");
  clearNode(host);
  for (const actorId of combatPresentation?.initiative_order || []) {
    const actor = combatProjectionActor(actorId);
    if (!actor) continue;
    const li = document.createElement("li");
    li.classList.toggle("active", actor.current_actor);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = actor.display_name;
    button.addEventListener("click", () => selectCombatActor(actor.entity_id));
    li.appendChild(button);
    host.appendChild(li);
  }
}

function renderCombatEvents() {
  const host = document.getElementById("combatEventFeed");
  clearNode(host);
  const feed = combatPresentation?.feed || [];
  if (!feed.length) {
    const empty = document.createElement("p");
    empty.textContent = "No events belong to this committed boundary.";
    host.appendChild(empty);
  }
  for (const item of feed) {
    const row = document.createElement("article");
    row.className = `event-row${item.detailed_breakdown_recorded ? "" : " feed-fallback"}`;
    const heading = document.createElement("strong");
    heading.textContent = item.label || `${item.event_sequence ?? "—"}. ${combatHumanizeId(item.event_type)}`;
    const detail = document.createElement("span");
    detail.textContent = item.summary;
    row.append(heading, detail);
    host.appendChild(row);
  }
  const boundary = combatSelectedBoundary();
  document.getElementById("combatHistoryRaw").textContent = boundary
    ? pretty({boundary_index: boundary.boundary_index, record_sequence: boundary.record_sequence, transaction_id: boundary.transaction_id, events: boundary.events, rolls: boundary.rolls})
    : "Live projection; select a historical boundary for raw committed records.";
}

function combatTerrainLookup() {
  const map = new Map();
  for (const region of combatPresentation?.battlefield?.terrain_regions || []) {
    for (const cell of region.cells || []) map.set(combatCellKey(cell), region);
  }
  return map;
}

function combatTokenAsset(actorId) {
  return combatProjectionActor(actorId)?.visual
    || combatMatch?.metadata?.visual_assets?.tokens?.[actorId]
    || combatVisualAssets?.tokens?.find(row => (row.stable_actor_ids || []).includes(actorId))
    || null;
}

function combatMapAsset() {
  return combatPresentation?.map_visual
    || combatMatch?.metadata?.visual_assets?.map
    || combatVisualAssets?.maps?.find(row => row.asset_id === combatVisualAssets.default_map_asset_id)
    || combatVisualAssets?.maps?.[0]
    || null;
}

function combatConditionBadges(actor) {
  const fragment = document.createDocumentFragment();
  const visible = (actor.conditions || []).slice(0, 3);
  for (const condition of visible) {
    const badge = document.createElement("span");
    badge.className = "combat-token-condition";
    badge.textContent = condition.display_name.slice(0, 1).toUpperCase();
    badge.title = condition.display_name;
    fragment.appendChild(badge);
  }
  if ((actor.conditions || []).length > 3) {
    const more = document.createElement("span");
    more.className = "combat-token-condition";
    more.textContent = `+${actor.conditions.length - 3}`;
    fragment.appendChild(more);
  }
  return fragment;
}

function combatMapCalibrationLabel(calibration) {
  const labels = {
    EXACT_REGISTERED: "Exact gridless-map registration",
    DECORATIVE_CONTAIN: "Decorative map · contain",
    DECORATIVE_COVER: "Decorative map · cover",
    LEGACY_DECORATIVE: "Legacy decorative map",
    MISSING: "Uncalibrated decorative map",
    INVALID: "Invalid map calibration"
  };
  return labels[calibration?.status] || "No map calibration";
}

function appendCombatMapLayer(host, mapAsset) {
  const status = document.getElementById("combatCalibrationStatus");
  const calibration = mapAsset?.calibration;
  const label = combatMapCalibrationLabel(calibration);
  status.textContent = label;
  status.dataset.calibrationStatus = calibration?.status || "MISSING";
  status.title = calibration?.message || "The background is presentation-only. Typed battlefield geometry remains authoritative.";
  host.dataset.mapCalibrationStatus = calibration?.status || "MISSING";
  host.dataset.mapAssetId = mapAsset?.asset_id || "none";
  if (!mapAsset?.public_url) return;

  const image = document.createElement("img");
  image.className = "combat-map-layer";
  image.src = mapAsset.public_url;
  image.alt = "";
  image.draggable = false;
  image.dataset.assetId = mapAsset.asset_id || "presentation-only";
  image.dataset.calibrationStatus = calibration?.status || "MISSING";

  if (calibration?.status === "EXACT_REGISTERED" && calibration.playable_rect_pixels) {
    const rect = calibration.playable_rect_pixels;
    const sourceWidth = calibration.source_pixel_width;
    const sourceHeight = calibration.source_pixel_height;
    image.classList.add("exact-map-layer");
    image.style.left = `${-rect.x / rect.width * 100}%`;
    image.style.top = `${-rect.y / rect.height * 100}%`;
    image.style.width = `${sourceWidth / rect.width * 100}%`;
    image.style.height = `${sourceHeight / rect.height * 100}%`;
  } else {
    image.classList.add("decorative-map-layer");
    image.style.objectFit = calibration?.fit_mode === "CONTAIN_DECORATIVE" ? "contain" : "cover";
    image.style.objectPosition = `${calibration?.position_x_percent ?? 50}% ${calibration?.position_y_percent ?? 50}%`;
  }
  host.appendChild(image);
}

function combatActorFootprint(actor) {
  const x = Number(actor.position?.x || 0);
  const y = Number(actor.position?.y || 0);
  return actor.footprint || {
    footprint_id: "footprint:legacy.1x1",
    anchor_x: x,
    anchor_y: y,
    width_cells: 1,
    height_cells: 1,
    mechanics_authoritative: true,
    in_bounds: true,
    collision_free: true,
    compatibility_mode: "LEGACY_SINGLE_CELL",
    occupied_cells: [{x, y}]
  };
}

function appendCombatTokenContent(token, actor) {
  const teamBadge = document.createElement("span");
  teamBadge.className = "combat-token-team-badge";
  teamBadge.textContent = String(actor.team_index + 1);
  token.appendChild(teamBadge);
  if (actor.visual?.kind === "image" && actor.visual.public_url) {
    const image = document.createElement("img");
    image.className = "combat-token-image";
    image.src = actor.visual.public_url;
    image.alt = "";
    image.draggable = false;
    token.appendChild(image);
    token.dataset.tokenAssetId = actor.visual.asset_id || "match-snapshot";
  } else {
    const initials = document.createElement("span");
    initials.className = "combat-token-initials";
    initials.textContent = actor.visual?.initials || actor.display_name.slice(0, 2).toUpperCase();
    token.appendChild(initials);
    token.dataset.tokenAssetId = "fallback:initials";
  }
  const hp = document.createElement("span");
  hp.className = "combat-token-hp";
  const hpFill = document.createElement("i");
  hpFill.style.width = `${Math.max(0, Math.min(100, actor.hit_points.current / Math.max(1, actor.hit_points.maximum) * 100))}%`;
  hp.appendChild(hpFill);
  token.appendChild(hp);
  if (actor.hit_points.temporary) {
    const temporary = document.createElement("span");
    temporary.className = "combat-token-temp-hp";
    temporary.textContent = `+${actor.hit_points.temporary}`;
    temporary.title = "Temporary HP";
    token.appendChild(temporary);
  }
  const conditions = document.createElement("span");
  conditions.className = "combat-token-conditions";
  conditions.appendChild(combatConditionBadges(actor));
  token.appendChild(conditions);
  const label = document.createElement("span");
  label.className = `combat-token-label${combatNameplatesVisible ? "" : " visually-hidden"}`;
  label.textContent = actor.display_name;
  token.appendChild(label);
}

function appendCombatTokenGroup(layer, actor, targetActors) {
  const footprint = combatActorFootprint(actor);
  const anchorX = Number(footprint.anchor_x ?? actor.position.x);
  const anchorY = Number(footprint.anchor_y ?? actor.position.y);
  const width = Number(footprint.width_cells || 1);
  const height = Number(footprint.height_cells || 1);
  const occupied = footprint.occupied_cells || [{x: anchorX, y: anchorY}];
  const rectangular = occupied.length === width * height;
  const group = document.createElement("div");
  const interactionTargets = combatInteractionMode === "select_target" && targetActors.has(actor.entity_id);
  const selectedMapCandidate = combatCandidateById(combatInteractionDraft?.selected_candidate_id);
  const selectedMapTarget = Boolean(selectedMapCandidate?.target_ids?.includes(actor.entity_id));
  group.className = `combat-token-group team-index-${actor.team_index}${width === 1 && height === 1 ? " single-cell-footprint" : " multicell-footprint"}${rectangular ? " rectangular-footprint" : " irregular-footprint"}${targetActors.has(actor.entity_id) ? " legal-target-group" : ""}${selectedMapTarget ? " selected-target-group" : ""}`;
  if ((actor.conditions || []).some(row => row.condition_id === "condition:typed.mounted")) group.classList.add("mounted-rider");  // sits on top of its mount's token (combat/ext/mounts.py)
  group.dataset.actorId = actor.entity_id;
  group.dataset.footprintId = footprint.footprint_id || "footprint:legacy.1x1";
  group.dataset.footprintWidth = String(width);
  group.dataset.footprintHeight = String(height);
  group.dataset.occupiedCells = occupied.map(cell => `${cell.x},${cell.y}`).join(";");
  group.style.gridColumn = `${anchorX + 1} / span ${width}`;
  group.style.gridRow = `${anchorY + 1} / span ${height}`;
  group.style.setProperty("--footprint-columns", String(width));
  group.style.setProperty("--footprint-rows", String(height));
  group.style.setProperty("--irregular-token-width", `${82 / width}%`);
  group.style.setProperty("--irregular-token-height", `${82 / height}%`);

  const mask = document.createElement("span");
  mask.className = "combat-footprint-mask";
  mask.setAttribute("aria-hidden", "true");
  for (const cell of occupied) {
    const relativeX = Number(cell.x) - anchorX;
    const relativeY = Number(cell.y) - anchorY;
    const segment = document.createElement("i");
    segment.className = "combat-footprint-cell";
    segment.dataset.x = String(cell.x);
    segment.dataset.y = String(cell.y);
    segment.style.gridColumn = String(relativeX + 1);
    segment.style.gridRow = String(relativeY + 1);
    mask.appendChild(segment);
  }
  group.appendChild(mask);

  const token = document.createElement("button");
  token.type = "button";
  token.className = `combat-token team-index-${actor.team_index}${width > 1 || height > 1 ? " multicell-token" : ""}${rectangular ? "" : " irregular-token"}${actor.current_actor ? " active-token" : ""}${combatSelectedActorId === actor.entity_id ? " selected-token" : ""}${actor.active ? "" : " inactive-token"}${actor.owner_id ? " companion-token" : ""}`;
  token.dataset.actorId = actor.entity_id;
  token.dataset.gridX = String(anchorX);
  token.dataset.gridY = String(anchorY);
  token.dataset.gridCell = `${anchorX},${anchorY}`;
  token.dataset.footprintId = footprint.footprint_id || "footprint:legacy.1x1";
  token.dataset.footprintWidth = String(width);
  token.dataset.footprintHeight = String(height);
  token.dataset.footprintAuthority = footprint.mechanics_authoritative ? "authoritative" : "unsupported";
  token.dataset.occupiedCells = group.dataset.occupiedCells;
  token.dataset.mapTargetEligible = interactionTargets ? "true" : "false";
  const renderable = Boolean(footprint.mechanics_authoritative && footprint.in_bounds !== false && footprint.collision_free !== false);
  if (!renderable) {
    token.classList.add("unsupported-footprint");
    token.disabled = true;
  }
  const conditionText = actor.conditions?.length ? `; conditions ${actor.conditions.map(row => row.display_name).join(", ")}` : "; no conditions";
  const inspectionStates = [
    actor.current_actor ? "current turn" : null,
    combatSelectedActorId === actor.entity_id ? "selected for inspection" : null,
    actor.active ? "active" : "inactive"
  ].filter(Boolean).join(", ");
  const footprintText = width === 1 && height === 1
    ? "one square footprint"
    : `${width} by ${height} bounding footprint occupying ${occupied.length} squares`;
  const interactionText = interactionTargets ? "; eligible target for the current exact candidate family" : "";
  const accessible = `${actor.display_name}, Team ${actor.team_index + 1}, anchor ${anchorX}, ${anchorY}; ${footprintText}; ${inspectionStates}; HP ${actor.hit_points.current} of ${actor.hit_points.maximum}${actor.hit_points.temporary ? ` plus ${actor.hit_points.temporary} temporary` : ""}${conditionText}${interactionText}`;
  token.setAttribute("aria-label", accessible);
  token.setAttribute("aria-pressed", combatSelectedActorId === actor.entity_id ? "true" : "false");
  token.title = `${accessible} · ${combatControlLabel(actor.controller)}`;
  appendCombatTokenContent(token, actor);
  token.addEventListener("click", event => {
    event.stopPropagation();
    if (combatInteractionMode === "select_target" && interactionTargets) {
      chooseCombatMapTarget(actor.entity_id);
      return;
    }
    if (combatInteractionMode === "pan") return;
    selectCombatActor(actor.entity_id, token);
  });
  group.appendChild(token);
  layer.appendChild(group);
}

function renderCombatBoard() {
  const host = document.getElementById("combatBoard");
  clearNode(host);
  const battlefield = combatPresentation?.battlefield;
  if (!battlefield) return;
  host.style.setProperty("--board-columns", battlefield.width_squares);
  host.style.setProperty("--board-rows", battlefield.height_squares);
  host.style.setProperty("--board-aspect", `${battlefield.width_squares} / ${battlefield.height_squares}`);
  host.style.width = `${Math.round(combatViewportZoom * 100)}%`;
  host.classList.toggle("geometry-hidden", combatGeometryOverlayMode === "off");
  host.classList.toggle("geometry-full", combatGeometryOverlayMode === "full");
  appendCombatMapLayer(host, combatMapAsset());
  document.getElementById("combatBoardLegend").textContent = `${battlefield.width_squares} × ${battlefield.height_squares} squares · ${battlefield.square_size_ft || 5} ft each`;
  renderCombatInteractionBar();
  const terrain = combatTerrainLookup();
  const interactionCandidates = combatInteractionDraftIsCurrent() ? combatInteractionCandidates() : [];
  const technicalCandidates = combatWorkspaceMode === "technical" && !combatIsHistorical() ? combatDecisionCandidates() : [];
  const boardCandidates = interactionCandidates.length ? interactionCandidates : technicalCandidates;
  const moveCells = new Set();
  const areaCenterCells = new Set();
  const targetActors = new Set();
  for (const candidate of boardCandidates) {
    if (candidate.area?.center) areaCenterCells.add(combatCellKey(candidate.area.center));
    else if (candidate.destination) moveCells.add(combatCellKey(candidate.destination));
    (candidate.target_ids || []).forEach(id => targetActors.add(id));
  }
  const selectedAreaCandidate = combatCandidateById(combatInteractionDraft?.selected_candidate_id || combatSelectedCandidateId);
  const areaPreviewCells = new Set((selectedAreaCandidate?.area?.affected_cells || []).map(combatCellKey));
  const targetCells = new Set();
  for (const actor of combatPresentation.actors || []) {
    if (!targetActors.has(actor.entity_id)) continue;
    for (const cell of combatActorFootprint(actor).occupied_cells || []) targetCells.add(combatCellKey(cell));
  }
  const zoneCells = new Set();
  for (const zone of combatPresentation.zones || []) {
    if (zone.active === false) continue;
    for (const cell of zone.affected_cells || []) zoneCells.add(combatCellKey(cell));
  }
  for (let y = 0; y < battlefield.height_squares; y += 1) {
    for (let x = 0; x < battlefield.width_squares; x += 1) {
      const key = `${x},${y}`;
      const cell = document.createElement("div");
      cell.className = "board-cell";
      cell.setAttribute("role", "gridcell");
      cell.dataset.x = String(x); cell.dataset.y = String(y); cell.tabIndex = -1;
      const region = terrain.get(key);
      if (region) {
        cell.classList.add(`terrain-${String(region.terrain_type).toLowerCase().replaceAll("_", "-")}`);
        if (String(region.region_id || "").startsWith("pillar.")) cell.classList.add("terrain-pillar");
        cell.title = `${region.terrain_type}: ${region.description}`;
      } else cell.title = `Open terrain (${x}, ${y})`;
      if (areaPreviewCells.has(key)) { cell.classList.add("area-preview-cell"); cell.title += " · exact server-issued affected area"; }
      if (areaCenterCells.has(key)) {
        cell.classList.add("legal-area-center");
        if (selectedAreaCandidate?.area?.center && combatCellKey(selectedAreaCandidate.area.center) === key) cell.classList.add("selected-area-center");
        const ownerAreaMode = combatInteractionMode === "select_area" && interactionCandidates.length;
        if (ownerAreaMode || technicalCandidates.length) {
          cell.tabIndex = 0; cell.setAttribute("role", "button");
          cell.dataset.mapAreaEligible = ownerAreaMode ? "true" : "false";
          cell.title += ownerAreaMode ? " · engine-issued legal area center" : " · legal area center";
          const choose = () => ownerAreaMode ? chooseCombatMapArea(x, y) : chooseCombatAreaTechnical(x, y);
          cell.addEventListener("click", choose);
          cell.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
        }
      } else if (moveCells.has(key)) {
        cell.classList.add("legal-move");
        const selectedCandidate = combatCandidateById(combatInteractionDraft?.selected_candidate_id || combatSelectedCandidateId);
        if (selectedCandidate?.destination && combatCellKey(selectedCandidate.destination) === key) cell.classList.add("selected-move");
        const ownerDestinationMode = combatInteractionMode === "select_destination" && interactionCandidates.length;
        if (ownerDestinationMode || technicalCandidates.length) {
          cell.tabIndex = 0; cell.setAttribute("role", "button");
          cell.dataset.mapDestinationEligible = ownerDestinationMode ? "true" : "false";
          cell.title += ownerDestinationMode ? " · engine-generated legal destination" : " · legal movement destination";
          const choose = () => ownerDestinationMode ? chooseCombatMapDestination(x, y) : chooseCombatMove(x, y);
          cell.addEventListener("click", choose);
          cell.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
        }
      }
      if (zoneCells.has(key)) { cell.classList.add("zone-cell"); cell.title += " · active zone"; }
      if (targetCells.has(key)) cell.classList.add("legal-target");
      host.appendChild(cell);
    }
  }
  const tokenLayer = document.createElement("div");
  tokenLayer.className = "combat-token-layer";
  tokenLayer.setAttribute("aria-label", "Combatant tokens positioned by authoritative grid coordinates");
  for (const actor of combatPresentation.actors || []) appendCombatTokenGroup(tokenLayer, actor, targetActors);
  host.appendChild(tokenLayer);
  requestAnimationFrame(positionCombatFloatingSheet);
}
function combatSheetButton(text, handler, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  if (className) button.className = className;
  button.addEventListener("click", handler);
  return button;
}

function combatSheetVisual(actor) {
  const visual = document.createElement("span");
  visual.className = "combat-sheet-portrait";
  if (actor.visual?.kind === "image" && actor.visual.public_url) {
    const image = document.createElement("img");
    image.src = actor.visual.public_url;
    image.alt = "";
    image.draggable = false;
    visual.appendChild(image);
  } else visual.textContent = actor.visual?.initials || actor.display_name.slice(0, 2).toUpperCase();
  return visual;
}

function combatSheetSummarySection(actor) {
  const section = document.createElement("section");
  section.className = "combat-sheet-section combat-sheet-summary";
  const vitals = document.createElement("div");
  vitals.className = "combat-sheet-vitals";
  const rows = [
    ["HP", `${actor.hit_points.current} / ${actor.hit_points.maximum}${actor.hit_points.temporary ? ` +${actor.hit_points.temporary} temp` : ""}`],
    [actor.defenses?.[0]?.display_name || "Defense", String(actor.defenses?.[0]?.value ?? "—")],
    ["Speed", `${actor.speed_ft} ft`],
    ["Position", `${actor.position.x}, ${actor.position.y}`]
  ];
  for (const [label, value] of rows) {
    const item = document.createElement("div");
    const name = document.createElement("span"); name.textContent = label;
    const strong = document.createElement("strong"); strong.textContent = value;
    item.append(name, strong); vitals.appendChild(item);
  }
  section.appendChild(vitals);
  const economy = document.createElement("div"); economy.className = "combat-sheet-economy";
  for (const label of combatTurnPills(actor)) { const pill = document.createElement("span"); pill.textContent = label; economy.appendChild(pill); }
  section.appendChild(economy);
  const condition = document.createElement("p"); condition.className = "combat-sheet-condition-line";
  condition.textContent = actor.conditions?.length ? `Conditions: ${actor.conditions.map(row => row.display_name).join(", ")}` : "Conditions: None";
  section.appendChild(condition);
  return section;
}

function combatManualDecisionAllowedFor(actor) {
  return Boolean(
    !combatIsHistorical()
    && combatDecision?.manual_submit_allowed
    && combatDecision?.context?.active_actor_id === actor?.entity_id
    && !combatMatch?.state?.terminal_result
  );
}

function combatRenderChoiceDomains(host, candidate) {
  clearNode(host);
  host.dataset.choiceAuthorityStatus = candidate.choice_authority_status || "NOT_APPLICABLE";
  if (candidate.choice_authority_status === "GAP") {
    const gap = document.createElement("p"); gap.className = "combat-choice-authority-gap";
    gap.textContent = "Owner composition is blocked: this candidate's option semantics lack complete typed authority.";
    host.appendChild(gap); return;
  }
  for (const domain of candidate.choice_domains || []) {
    const field = document.createElement("fieldset"); field.className = "combat-choice-domain";
    const legend = document.createElement("legend"); legend.textContent = domain.display_name; field.appendChild(legend);
    const defaults = new Set(domain.default_option_ids || []);
    if (domain.selection_rule === "EXACT_SET") {
      for (const optionId of domain.option_ids || []) {
        const input = document.createElement("input"); input.type = "hidden"; input.value = optionId; input.dataset.combatChoiceOption = "true"; field.appendChild(input);
        const fixed = document.createElement("span"); fixed.className = "combat-choice-fixed"; fixed.textContent = combatHumanizeId(optionId); field.appendChild(fixed);
      }
    } else if (domain.selection_rule === "ZERO_OR_ONE" && (domain.option_ids || []).length === 1) {
      const optionId = domain.option_ids[0]; const label = document.createElement("label");
      const input = document.createElement("input"); input.type = "checkbox"; input.value = optionId; input.dataset.combatChoiceOption = "true"; input.checked = defaults.has(optionId);
      const cost = domain.option_costs?.[optionId];
      label.append(input, document.createTextNode(`${combatHumanizeId(optionId)}${cost ? ` · ${Object.entries(cost).map(([id,value]) => `${value} ${combatHumanizeId(id)}`).join(", ")}` : ""}`)); field.appendChild(label);
    } else {
      const name = `choice-${candidate.candidate_id}-${domain.domain_id}`.replace(/[^a-zA-Z0-9_-]/g, "-");
      if (domain.minimum_selections === 0 && !(domain.default_option_ids || []).length) {
        const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = name; input.value = ""; input.checked = true; input.dataset.combatChoiceNone = "true";
        label.append(input, document.createTextNode("No optional selection")); field.appendChild(label);
      }
      for (const [index, optionId] of (domain.option_ids || []).entries()) {
        const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = name; input.value = optionId; input.dataset.combatChoiceOption = "true";
        input.checked = defaults.has(optionId) || (!defaults.size && domain.minimum_selections > 0 && index === 0);
        label.append(input, document.createTextNode(combatHumanizeId(optionId))); field.appendChild(label);
      }
    }
    host.appendChild(field);
  }
}

function combatSelectedChoiceIds(host) {
  return [...host.querySelectorAll("[data-combat-choice-option]")]
    .filter(input => input.type === "hidden" || input.checked)
    .map(input => input.value);
}

function combatManualActionControl(candidates) {
  const control = document.createElement("div"); control.className = "combat-manual-action-control";
  control.dataset.candidateIds = candidates.map(row => row.candidate_id).join(";");
  const chooser = document.createElement("select");
  chooser.setAttribute("aria-label", `Choose legal form of ${candidates[0].display_name}`);
  for (const candidate of candidates) {
    const option = document.createElement("option"); option.value = candidate.candidate_id; option.textContent = combatCandidateLabel(candidate); option.selected = candidate.candidate_id === combatSelectedCandidateId; chooser.appendChild(option);
  }
  if (!chooser.value) chooser.value = candidates[0].candidate_id;
  const optionHost = document.createElement("div"); optionHost.className = "combat-manual-option-list";
  const selectedCandidate = () => candidates.find(row => row.candidate_id === chooser.value) || candidates[0];
  const buttonRow = document.createElement("div"); buttonRow.className = "combat-manual-button-row";
  const review = document.createElement("button"); review.type = "button"; review.className = "primary-action"; review.textContent = "Review Action"; review.dataset.combatReviewAction = "true";
  const renderOptions = (updateSelection = false) => {
    const candidate = selectedCandidate(); if (updateSelection) combatSelectedCandidateId = candidate.candidate_id;
    combatRenderChoiceDomains(optionHost, candidate); review.disabled = candidate.choice_authority_status === "GAP";
    if (updateSelection) renderCombatBoard();
  };
  chooser.addEventListener("change", () => { renderOptions(true); updateMapButton(); });
  review.addEventListener("click", () => { const candidate = selectedCandidate(); beginCombatIntent(candidateIntent(candidate, combatSelectedChoiceIds(optionHost))); });
  const mapButton = document.createElement("button"); mapButton.type = "button"; mapButton.className = "combat-map-choice-button";
  const updateMapButton = () => {
    const exactFamily = combatMapCandidatesForPreferred(candidates, chooser.value);
    const plan = combatMapCandidateKind(exactFamily);
    mapButton.hidden = !plan?.candidates.length;
    mapButton.disabled = !plan?.candidates.length;
    mapButton.textContent = plan?.steps?.length > 1
      ? "Choose Target & Destination on Map"
      : plan?.mode === "select_target"
        ? "Choose Target on Map"
        : plan?.mode === "select_area"
          ? "Choose Area on Map"
          : "Choose Destination on Map";
  };
  mapButton.addEventListener("click", () => {
    const exactFamily = combatMapCandidatesForPreferred(candidates, chooser.value);
    beginCombatMapSelection(exactFamily, chooser.value);
  });
  buttonRow.appendChild(mapButton);
  buttonRow.appendChild(review);
  if (candidates.length > 1 || candidates[0].destination || candidates[0].target_ids?.length || candidates[0].area?.center) control.appendChild(chooser);
  control.append(optionHost, buttonRow); renderOptions(); updateMapButton(); return control;
}
function combatSheetActionsSection(actor) {
  const section = document.createElement("section"); section.className = "combat-sheet-section combat-sheet-actions";
  const heading = document.createElement("h4"); heading.textContent = "Engine-generated actions"; section.appendChild(heading);
  const guidance = document.createElement("p"); guidance.className = "combat-manual-guidance";
  if (combatIsHistorical()) guidance.textContent = "Historical action definitions are read-only.";
  else if (combatDecision?.context?.active_actor_id !== actor.entity_id) guidance.textContent = "Inspecting this fighter does not make them the acting fighter. Only the current turn can submit an action.";
  else if (!combatDecision?.manual_submit_allowed) guidance.textContent = `${combatControlLabels[combatDecision?.control_mode] || combatDecision?.control_mode || "Automatic control"} owns this turn. Owner submission is disabled.`;
  else guidance.textContent = "Choose only from the exact candidates issued for this decision. Review is non-authoritative until Commit Action.";
  section.appendChild(guidance);
  const availability = new Map((actor.action_availability || []).map(row => [row.action_definition_id, row]));
  const candidatesById = new Map((combatDecision?.context?.legal_candidates || []).map(row => [row.candidate_id, row]));
  const list = document.createElement("div"); list.className = "combat-sheet-action-list";
  for (const definition of actor.action_definitions || []) {
    const current = availability.get(definition.action_definition_id);
    const card = document.createElement("article");
    card.className = `combat-sheet-action${current?.legal_now ? " legal" : " unavailable"}`;
    const title = document.createElement("strong"); title.textContent = definition.display_name;
    const meta = document.createElement("small"); meta.textContent = `${combatHumanizeId(definition.source_category)} · ${combatHumanizeId(definition.economy)}`;
    const summary = document.createElement("p");
    summary.textContent = definition.descriptive_summary || `${combatHumanizeId(definition.target_kind)}${definition.range_ft ? ` · ${definition.range_ft} ft` : definition.reach_ft ? ` · ${definition.reach_ft} ft reach` : ""}`;
    const status = document.createElement("span"); status.className = "combat-action-status";
    status.textContent = current?.legal_now
      ? `${current.candidate_ids.length} legal candidate${current.candidate_ids.length === 1 ? "" : "s"}`
      : (current?.disabled_reason_codes || ["not_available"]).map(combatHumanizeId).join(" · ");
    card.append(title, meta, summary, status);
    if (current?.legal_now && combatManualDecisionAllowedFor(actor)) {
      const candidates = (current.candidate_ids || []).map(id => candidatesById.get(id)).filter(Boolean);
      if (candidates.length) card.appendChild(combatManualActionControl(candidates));
    }
    list.appendChild(card);
  }
  if (!list.childElementCount) { const empty = document.createElement("p"); empty.textContent = "No typed action definitions were exposed for this combatant."; list.appendChild(empty); }
  section.appendChild(list);
  return section;
}

function combatSheetResourcesSection(actor) {
  const section = document.createElement("section"); section.className = "combat-sheet-section";
  const heading = document.createElement("h4"); heading.textContent = "Resources"; section.appendChild(heading);
  const list = document.createElement("div"); list.className = "combat-sheet-resource-list";
  for (const resource of actor.resources || []) {
    const row = document.createElement("div");
    const label = document.createElement("span"); label.textContent = resource.display_name;
    const value = document.createElement("strong"); value.textContent = `${resource.current} / ${resource.maximum}`;
    row.append(label, value); list.appendChild(row);
  }
  if (!list.childElementCount) { const empty = document.createElement("p"); empty.textContent = "No expendable combat resources."; list.appendChild(empty); }
  section.appendChild(list);
  const featureHeading = document.createElement("h4"); featureHeading.textContent = "Combat features"; section.appendChild(featureHeading);
  const features = document.createElement("ul"); features.className = "combat-sheet-feature-list";
  for (const feature of (actor.features || []).slice(0, 16)) {
    const item = document.createElement("li");
    const name = document.createElement("strong"); name.textContent = feature.display_name;
    const type = document.createElement("span"); type.textContent = combatHumanizeId(feature.category);
    item.append(name, type); features.appendChild(item);
  }
  section.appendChild(features);
  return section;
}

function combatSheetCharacterSection(actor) {
  const section = document.createElement("section"); section.className = "combat-sheet-section";
  const heading = document.createElement("h4"); heading.textContent = "Persistent Character Sheet"; section.appendChild(heading);
  const character = actor.character_summary || {};
  const detail = document.createElement("dl"); detail.className = "combat-sheet-identity-list";
  const rows = [
    ["Path", character.path || "—"],
    ["Realm", character.realm || "—"],
    ["Cultivation level", character.cultivation_level ? `CL ${character.cultivation_level}` : "—"],
    ["Controller", combatControlLabel(actor.controller)]
  ];
  for (const [term, value] of rows) { const dt = document.createElement("dt"); dt.textContent = term; const dd = document.createElement("dd"); dd.textContent = value; detail.append(dt, dd); }
  section.appendChild(detail);
  if (combatHasPersistentCharacterSheet(actor)) {
    section.appendChild(combatSheetButton("Open Persistent Character Sheet", () => openCombatPersistentCharacterSheet(actor), "primary-action"));
  } else {
    const limitation = document.createElement("p");
    limitation.className = "honest-limit";
    limitation.textContent = actor.primary_combatant
      ? "This built-in combatant has exact pre-combat character authority, but this release does not expose a navigable full persistent Character Sheet. Combat values remain authoritative in this Combat Sheet."
      : "This companion has no independent persistent Character Sheet.";
    section.appendChild(limitation);
  }
  return section;
}

function combatFeedItemInvolvesActor(item, actorId) {
  const targets = Array.isArray(item.target_ids) ? item.target_ids : [];
  if (item.identity_scope === "SYSTEM" || (!item.actor_id && targets.length === 0)) return false;
  return item.actor_id === actorId || targets.includes(actorId);
}

function combatSheetHistorySection(actor) {
  const section = document.createElement("section"); section.className = "combat-sheet-section";
  const heading = document.createElement("h4"); heading.textContent = "Boundary history"; section.appendChild(heading);
  const status = document.createElement("p");
  status.textContent = combatPresentation.mode === "HISTORY" ? combatPresentation.boundary?.step_label : `Live after state version ${combatPresentation.state_version}`;
  section.appendChild(status);
  const list = document.createElement("ul");
  for (const item of (combatPresentation.feed || []).slice(-6)) {
    if (!combatFeedItemInvolvesActor(item, actor.entity_id)) continue;
    const li = document.createElement("li"); li.textContent = item.summary; list.appendChild(li);
  }
  if (!list.childElementCount) { const li = document.createElement("li"); li.textContent = "No actor-specific events in this boundary."; list.appendChild(li); }
  section.appendChild(list);
  return section;
}

function renderCombatSheetInto(host, actor, displayMode) {
  clearNode(host);
  host.dataset.actorId = actor.entity_id;
  host.dataset.displayMode = displayMode;
  host.dataset.mobileSheetState = combatMobileSheetState;
  const header = document.createElement("header"); header.className = "combat-sheet-header";
  const identity = document.createElement("div"); identity.className = "combat-sheet-identity";
  const copy = document.createElement("div");
  const team = document.createElement("span"); team.className = "combat-sheet-team-label"; team.textContent = `Team ${actor.team_index + 1} · ${actor.team_display_name}`;
  const name = document.createElement("h3"); name.textContent = actor.display_name;
  const summary = document.createElement("p");
  const character = actor.character_summary || {};
  summary.textContent = [character.path, character.realm, character.cultivation_level ? `CL ${character.cultivation_level}` : null, combatControlLabel(actor.controller)].filter(Boolean).join(" · ");
  copy.append(team, name, summary); identity.append(combatSheetVisual(actor), copy);
  const close = combatSheetButton("×", () => {
    if (displayMode === "pinned") combatPinnedActorId = null;
    else { combatSelectedActorId = null; combatFollowCurrentTurn = false; }
    renderCombatBoard(); renderCombatSheets(); renderCombatActors();
  }, "combat-sheet-close");
  close.setAttribute("aria-label", "Close Combat Sheet");
  const headerControls = document.createElement("div");
  headerControls.className = "combat-sheet-header-controls";
  const bottomSheet = combatUpdateSheetLayoutMode();
  if (bottomSheet && displayMode === "floating") {
    const stateOrder = ["collapsed", "medium", "expanded"];
    const toggle = combatSheetButton(
      combatMobileSheetState === "expanded" ? "Reduce" : "Expand",
      () => {
        const current = stateOrder.indexOf(combatMobileSheetState);
        combatMobileSheetState = stateOrder[(current + 1) % stateOrder.length];
        renderCombatSheets();
      },
      "combat-sheet-size-toggle"
    );
    toggle.setAttribute("aria-label", `Combat Sheet size: ${combatMobileSheetState}`);
    headerControls.appendChild(toggle);
  }
  headerControls.appendChild(close);
  header.append(identity, headerControls); host.appendChild(header);

  const expanded = displayMode === "pinned" || bottomSheet;
  if (expanded) {
    const tabs = document.createElement("div"); tabs.className = "combat-sheet-tabs"; tabs.setAttribute("role", "tablist");
    for (const sectionName of ["summary", "actions", "resources", "character", "history"]) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = combatHumanizeId(sectionName); button.classList.toggle("active", combatExpandedSheetSection === sectionName);
      button.setAttribute("role", "tab"); button.setAttribute("aria-selected", combatExpandedSheetSection === sectionName ? "true" : "false");
      button.addEventListener("click", () => { combatExpandedSheetSection = sectionName; renderCombatSheets(); });
      tabs.appendChild(button);
    }
    host.appendChild(tabs);
  }
  const body = document.createElement("div"); body.className = "combat-sheet-body";
  const sectionName = expanded ? combatExpandedSheetSection : "summary";
  if (sectionName === "actions") body.appendChild(combatSheetActionsSection(actor));
  else if (sectionName === "resources") body.appendChild(combatSheetResourcesSection(actor));
  else if (sectionName === "character") body.appendChild(combatSheetCharacterSection(actor));
  else if (sectionName === "history") body.appendChild(combatSheetHistorySection(actor));
  else body.appendChild(combatSheetSummarySection(actor));
  host.appendChild(body);

  const actions = document.createElement("footer"); actions.className = "combat-sheet-footer";
  actions.appendChild(combatSheetButton("Center Token", () => centerCombatActor(actor.entity_id)));
  if (combatHasPersistentCharacterSheet(actor)) actions.appendChild(combatSheetButton("Open Character Sheet", () => openCombatPersistentCharacterSheet(actor), "primary-action"));
  if (displayMode === "pinned") actions.appendChild(combatSheetButton("Unpin", () => { combatPinnedActorId = null; combatSelectedActorId = actor.entity_id; combatFollowCurrentTurn = false; renderCombatBoard(); renderCombatSheets(); renderCombatActors(); }));
  else if (!bottomSheet) actions.appendChild(combatSheetButton("Pin", () => { combatPinnedActorId = actor.entity_id; combatSelectedActorId = actor.entity_id; combatFollowCurrentTurn = false; combatExpandedSheetSection = "summary"; renderCombatBoard(); renderCombatSheets(); renderCombatActors(); }));
  host.appendChild(actions);
}

function renderCombatSheets() {
  const floating = document.getElementById("combatFloatingSheet");
  const pinned = document.getElementById("combatPinnedSheetPanel");
  const selected = combatProjectionActor(combatSelectedActorId);
  const pinnedActor = combatProjectionActor(combatPinnedActorId);
  if (pinnedActor) {
    pinned.hidden = false;
    renderCombatSheetInto(pinned, pinnedActor, "pinned");
    floating.hidden = true;
    document.getElementById("combatSheetConnector").hidden = true;
  } else {
    pinned.hidden = true;
    clearNode(pinned);
    if (selected) {
      floating.hidden = false;
      renderCombatSheetInto(floating, selected, "floating");
      requestAnimationFrame(positionCombatFloatingSheet);
    } else {
      floating.hidden = true;
      document.getElementById("combatSheetConnector").hidden = true;
    }
  }
}

function positionCombatFloatingSheet() {
  const sheet = document.getElementById("combatFloatingSheet");
  const viewport = document.getElementById("combatBattlefieldViewport");
  if (!sheet || sheet.hidden || !combatSelectedActorId || combatUpdateSheetLayoutMode()) {
    sheet?.style.removeProperty("left");
    sheet?.style.removeProperty("top");
    sheet?.style.removeProperty("width");
    document.getElementById("combatSheetConnector").hidden = true;
    return;
  }
  const token = document.querySelector(`.combat-token[data-actor-id="${CSS.escape(combatSelectedActorId)}"]`);
  if (!token) return;
  const viewportRect = viewport.getBoundingClientRect();
  const tokenRect = token.getBoundingClientRect();
  const width = Math.min(420, Math.max(320, viewportRect.width * .42));
  sheet.style.width = `${width}px`;
  const measured = sheet.getBoundingClientRect();
  const gap = 18;
  const tokenCenterX = tokenRect.left - viewportRect.left + viewport.scrollLeft + tokenRect.width / 2;
  const tokenCenterY = tokenRect.top - viewportRect.top + viewport.scrollTop + tokenRect.height / 2;
  const viewportLeft = viewport.scrollLeft;
  const viewportTop = viewport.scrollTop;
  const viewportRight = viewportLeft + viewport.clientWidth;
  const viewportBottom = viewportTop + viewport.clientHeight;
  let left = tokenCenterX + tokenRect.width / 2 + gap;
  if (left + measured.width > viewportRight - 8) left = tokenCenterX - tokenRect.width / 2 - measured.width - gap;
  left = Math.max(viewportLeft + 8, Math.min(left, viewportRight - measured.width - 8));
  let top = tokenCenterY - measured.height / 2;
  top = Math.max(viewportTop + 8, Math.min(top, viewportBottom - measured.height - 8));
  sheet.style.left = `${left}px`;
  sheet.style.top = `${top}px`;
  const connector = document.getElementById("combatSheetConnector");
  const targetX = left > tokenCenterX ? left : left + measured.width;
  const targetY = Math.max(top + 24, Math.min(tokenCenterY, top + measured.height - 24));
  const dx = targetX - tokenCenterX;
  const dy = targetY - tokenCenterY;
  connector.hidden = false;
  connector.style.left = `${tokenCenterX}px`;
  connector.style.top = `${tokenCenterY}px`;
  connector.style.width = `${Math.hypot(dx, dy)}px`;
  connector.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
}

function selectCombatActor(actorId, sourceElement = null) {
  if (!combatProjectionActor(actorId)) return;
  const restoreTokenFocus = Boolean(
    sourceElement
    && sourceElement.matches?.(".combat-token")
    && document.activeElement === sourceElement
  );
  combatSelectedActorId = actorId;
  combatFollowCurrentTurn = false;
  if (combatUsesBottomSheet() && combatMobileSheetState === "collapsed") combatMobileSheetState = "medium";
  renderCombatActors();
  renderCombatBoard();
  renderCombatSheets();
  combatUpdateAuthorityDetailsControl();
  if (restoreTokenFocus) {
    const replacement = document.querySelector(
      `.combat-token[data-actor-id="${CSS.escape(actorId)}"]`
    );
    replacement?.focus({preventScroll: true});
  } else if (sourceElement?.isConnected) {
    sourceElement.focus({preventScroll: true});
  }
}

function centerCombatActor(actorId) {
  const token = document.querySelector(`.combat-token[data-actor-id="${CSS.escape(actorId)}"]`);
  token?.scrollIntoView({behavior: "smooth", block: "center", inline: "center"});
}


function openCombatPersistentCharacterSheet(actor) {
  if (!combatHasPersistentCharacterSheet(actor)) return;
  const boundary = combatIsHistorical() ? combatHistoryIndex : "live";
  const separator = actor.sheet_link.route.includes("?") ? "&" : "?";
  window.location.assign(`${actor.sheet_link.route}${separator}return_match_id=${encodeURIComponent(combatMatch.match_id)}&return_boundary=${encodeURIComponent(boundary)}`);
}

async function openCombatCharacterAuthorityDetails(actor) {
  if (!combatHasCharacterAuthorityDetails(actor)) return;
  const dialog = document.getElementById("combatCharacterDialog");
  const body = document.getElementById("combatCharacterDialogBody");
  clearNode(body);
  document.getElementById("combatCharacterDialogTitle").textContent = actor.display_name;
  document.getElementById("combatCharacterDialogNote").textContent = "Advanced technical details for the exact accepted pre-combat character authority. This is not the full persistent Character Sheet. Current HP, resources, conditions, action economy, and position remain authoritative only in the Combat Sheet.";
  const loading = document.createElement("p"); loading.textContent = "Loading exact character authority…"; body.appendChild(loading);
  if (!dialog.open) dialog.showModal();
  try {
    const authority = await api(actor.sheet_link.route);
    clearNode(body);
    const projection = authority.projection || {};
    const identity = document.createElement("section"); identity.className = "combat-authority-section";
    const heading = document.createElement("h4"); heading.textContent = "Character identity";
    const detail = document.createElement("dl"); detail.className = "combat-sheet-identity-list";
    const rows = [
      ["Character ID", authority.source_character_id],
      ["Character sheet identity", authority.character_sheet_identity],
      ["Projection revision", authority.source_revision_sha256],
      ["Projection file", authority.projection_file_sha256],
      ["Realm", projection.realm || "—"],
      ["Cultivation level", String(projection.cultivation_level ?? "—")]
    ];
    for (const [term, value] of rows) { const dt = document.createElement("dt"); dt.textContent = term; const dd = document.createElement("dd"); dd.textContent = value; detail.append(dt, dd); }
    identity.append(heading, detail); body.appendChild(identity);
    for (const [key, label] of [["actions", "Actions"], ["reactions", "Reactions"], ["path_effects", "Path"], ["subpath_effects", "Subpath"], ["foundation_effects", "Foundation"], ["equipment_effects", "Equipment"], ["talents", "Talents"]]) {
      const values = projection[key] || [];
      if (!values.length) continue;
      const section = document.createElement("section"); section.className = "combat-authority-section";
      const title = document.createElement("h4"); title.textContent = label;
      const list = document.createElement("div"); list.className = "combat-authority-list";
      for (const row of values) {
        const card = document.createElement("article");
        const name = document.createElement("strong"); name.textContent = row.display_name || combatHumanizeId(row.stable_id);
        const source = document.createElement("small"); source.textContent = row.source || row.stable_id || "Typed authority";
        card.append(name, source); list.appendChild(card);
      }
      section.append(title, list); body.appendChild(section);
    }
  } catch (error) {
    clearNode(body);
    const message = document.createElement("p"); message.className = "error"; message.textContent = plainAPIError(error, "The exact character authority could not be loaded."); body.appendChild(message);
  }
}

async function refreshCombatDecision() {
  if (combatIsHistorical()) {
    combatDecision = null;
    document.getElementById("combatDecisionStatus").textContent = "Historical view is read-only. Return to Live to submit an action.";
    clearNode(document.getElementById("combatActionGroups"));
    renderCombatBoard();
    return;
  }
  if (!combatMatch || combatMatch.state.terminal_result) {
    combatDecision = null;
    document.getElementById("combatDecisionStatus").textContent = "The match is complete.";
    clearNode(document.getElementById("combatActionGroups"));
    renderCombatBoard();
    return;
  }
  const matchId = combatMatch.match_id, epoch = combatExecutionEpoch;
  const isCurrent = () => epoch === combatExecutionEpoch && combatMatch?.match_id === matchId;
  try {
    const decision = await api(`/api/combat/matches/${combatId(matchId)}/decision`);
    if (!isCurrent()) return;
    combatDecision = decision;
    if (combatInteractionDraft && !combatInteractionDraftIsCurrent()) cancelCombatMapSelection("The map choice became stale when combat authority advanced.", false);
    if (combatPendingIntentDraft && !combatPendingIntentDraftIsCurrent()) cancelCombatPendingIntent("The pending manual action was canceled because combat authority advanced or the controller changed.");
    if (!combatDecision.context.legal_candidates.some(row => row.candidate_id === combatSelectedCandidateId)) combatSelectedCandidateId = null;
    const manualState = combatDecision.manual_submit_allowed ? "owner action available" : "automatic controller owns turn";
    document.getElementById("combatDecisionStatus").textContent = `${combatActorName(combatDecision.context.active_actor_id)} · ${combatDecision.control_mode.replaceAll("_", " ")} · ${combatDecision.context.legal_candidates.length} legal candidates · ${manualState}`;
    renderCombatActions(); renderCombatBoard(); renderCombatSheets();
  } catch (error) { if (isCurrent()) combatError(error); }
}

function candidateIntent(candidate, optionIds = []) {
  return {
    decision_id: candidate.decision_id,
    state_version: candidate.state_version,
    candidate_id: candidate.candidate_id,
    actor_id: candidate.actor_id,
    target_ids: candidate.target_ids || [],
    destination: candidate.destination,
    option_ids: optionIds
  };
}

function combatCandidateLabel(candidate) {
  const parts = [];
  if (candidate.target_ids?.length) parts.push(`Target ${candidate.target_ids.map(combatActorName).join(", ")}`);
  if (candidate.area?.center) parts.push(`Area ${candidate.area.center.x}, ${candidate.area.center.y} · ${candidate.area.affected_cells?.length || 0} cells`);
  else if (candidate.destination) parts.push(`Destination ${candidate.destination.x}, ${candidate.destination.y}`);
  if (candidate.movement_cost_ft) parts.push(`${candidate.movement_cost_ft} ft movement`);
  const mode = candidate.metadata?.command_mode || candidate.metadata?.mode || candidate.metadata?.target_mode || candidate.metadata?.profile;
  if (mode) parts.push(combatHumanizeId(mode));
  if (candidate.option_ids?.length) parts.push(candidate.option_ids.map(combatHumanizeId).join(" + "));
  return parts.length ? parts.join(" · ") : "No target required";
}

function renderCombatActions() {
  const host = document.getElementById("combatActionGroups"); clearNode(host);
  if (!combatDecision?.context?.legal_candidates?.length) return;
  const kindGroups = new Map();
  for (const candidate of combatDecision.context.legal_candidates) {
    const kind = candidate.kind;
    if (!kindGroups.has(kind)) kindGroups.set(kind, new Map());
    const familyKey = `${candidate.source_definition_id || candidate.display_name}|${candidate.display_name}`;
    const family = kindGroups.get(kind);
    if (!family.has(familyKey)) family.set(familyKey, []);
    family.get(familyKey).push(candidate);
  }
  for (const [kind, families] of kindGroups) {
    const group = document.createElement("section"); group.className = "action-group";
    const heading = document.createElement("h4"); heading.textContent = combatHumanizeId(kind);
    const grid = document.createElement("div"); grid.className = "action-card-grid";
    for (const candidates of families.values()) {
      const card = document.createElement("div"); card.className = "action-card";
      const title = document.createElement("strong"); title.textContent = candidates[0].display_name;
      const summary = document.createElement("div"); summary.className = "action-meta";
      summary.textContent = candidates.length > 1 ? `${candidates.length} legal target, mode, or destination choices` : combatCandidateLabel(candidates[0]);
      const chooserLabel = document.createElement("label"); chooserLabel.className = "action-choice-label"; chooserLabel.textContent = kind === "MOVE" ? "Choose destination" : "Choose target or mode";
      const chooser = document.createElement("select"); chooser.setAttribute("aria-label", `${chooserLabel.textContent} for ${candidates[0].display_name}`);
      for (const candidate of candidates) {
        const option = document.createElement("option");
        option.value = candidate.candidate_id;
        option.textContent = combatCandidateLabel(candidate);
        if (candidate.candidate_id === combatSelectedCandidateId) option.selected = true;
        chooser.appendChild(option);
      }
      if (!candidates.some(candidate => candidate.candidate_id === chooser.value)) chooser.value = candidates[0].candidate_id;
      const options = document.createElement("div"); options.className = "action-options";
      const choose = document.createElement("button"); choose.type = "button"; choose.className = "primary-action"; choose.textContent = kind === "MOVE" ? "Confirm Movement" : "Confirm Choice";
      const selectedCandidate = () => candidates.find(candidate => candidate.candidate_id === chooser.value) || candidates[0];
      const renderOptions = (updateSelection = false) => {
        clearNode(options);
        const candidate = selectedCandidate();
        if (updateSelection) combatSelectedCandidateId = candidate.candidate_id;
        combatRenderChoiceDomains(options, candidate);
        choose.disabled = candidate.choice_authority_status === "GAP";
        if (updateSelection) renderCombatBoard();
      };
      chooser.addEventListener("change", () => renderOptions(true));
      choose.addEventListener("click", () => {
        const candidate = selectedCandidate();
        const optionIds = combatSelectedChoiceIds(options);
        beginCombatIntent(candidateIntent(candidate, optionIds));
      });
      card.append(title, summary);
      if (candidates.length > 1 || candidates[0].destination || candidates[0].target_ids?.length) {
        chooserLabel.appendChild(chooser); card.appendChild(chooserLabel);
      }
      card.append(options, choose); grid.appendChild(card);
      renderOptions();
    }
    group.append(heading, grid); host.appendChild(group);
  }
}

function chooseCombatAreaTechnical(x, y) {
  if (combatIsHistorical()) return;
  const candidate = combatDecision?.context?.legal_candidates?.find(row => row.area?.center?.x === x && row.area?.center?.y === y);
  if (!candidate) return;
  combatSelectedCandidateId = candidate.candidate_id;
  document.getElementById("combatDecisionStatus").textContent = `Selected exact server-issued area centered at ${x}, ${y}. Confirm it in the action card.`;
  renderCombatActions(); renderCombatBoard();
  document.getElementById("combatActionGroups").scrollIntoView({behavior: "smooth", block: "start"});
}

function chooseCombatMove(x, y) {
  if (combatIsHistorical()) return;
  const candidate = combatDecision?.context?.legal_candidates?.find(row => row.kind === "MOVE" && row.destination?.x === x && row.destination?.y === y);
  if (!candidate) return;
  combatSelectedCandidateId = candidate.candidate_id;
  document.getElementById("combatDecisionStatus").textContent = `Selected movement destination ${x}, ${y}. Confirm it in the Movement card.`;
  renderCombatActions(); renderCombatBoard();
  document.getElementById("combatActionGroups").scrollIntoView({behavior: "smooth", block: "start"});
}

function closeCombatDialog(id) {
  const dialog = document.getElementById(id);
  if (dialog?.open) dialog.close();
}

function cancelCombatPendingIntent(message = null) {
  combatPendingIntentDraft = null;
  resetCombatInteractionState();
  document.getElementById("combatReactionPrompt").hidden = true;
  closeCombatDialog("combatReactionDialog");
  closeCombatDialog("combatIntentReviewDialog");
  if (message) document.getElementById("combatDecisionStatus").textContent = message;
  renderCombatBoard();
  renderCombatSheets();
}

async function beginCombatIntent(intent) {
  if (combatIsHistorical()) {
    combatSetDiagnostic("Historical view is read-only. Return to Live before submitting an action.");
    return;
  }
  if (!combatDecision?.manual_submit_allowed || combatDecision.context.active_actor_id !== intent.actor_id) {
    combatSetDiagnostic("The active fighter's assigned controller does not accept an owner-submitted intent at this boundary.");
    return;
  }
  resetCombatInteractionState();
  combatPendingIntentDraft = {
    schema: "TianxiaCombatPendingIntentDraft.v1",
    intent,
    reaction_decisions: [],
    reaction_trace: [],
    created_for_match_id: combatMatch.match_id,
    created_for_decision_id: combatDecision.context.decision_id,
    created_for_state_version: combatDecision.context.state_version,
    created_for_actor_id: combatDecision.context.active_actor_id,
    created_for_controller_mode: combatDecision.control_mode,
    preview: null
  };
  combatSetInteractionMode("review");
  document.getElementById("combatReactionPrompt").hidden = true;
  await continueCombatPreview();
}

function renderCombatIntentReview(preview) {
  if (!combatPendingIntentDraft) return;
  combatPendingIntentDraft.preview = preview;
  const candidate = combatDecision?.context?.legal_candidates?.find(row => row.candidate_id === combatPendingIntentDraft.intent.candidate_id);
  document.getElementById("combatIntentReviewTitle").textContent = candidate?.display_name || "Review action";
  document.getElementById("combatIntentReviewSummary").textContent = "This is a deterministic preview. No HP, resources, positions, conditions, action economy, journal, or replay state changes until Commit Action.";
  const body = document.getElementById("combatIntentReviewBody"); clearNode(body);
  const identity = document.createElement("dl"); identity.className = "combat-sheet-identity-list";
  const rows = [
    ["Actor", combatActorName(combatPendingIntentDraft.intent.actor_id)],
    ["Action", candidate?.display_name || combatPendingIntentDraft.intent.candidate_id],
    ["Candidate ID", combatPendingIntentDraft.intent.candidate_id],
    ["Decision", `${combatPendingIntentDraft.intent.decision_id} · state ${combatPendingIntentDraft.intent.state_version}`],
    ["Target", combatPendingIntentDraft.intent.target_ids?.length ? combatPendingIntentDraft.intent.target_ids.map(combatActorName).join(", ") : "None"],
    ["Destination", combatPendingIntentDraft.intent.destination ? `${combatPendingIntentDraft.intent.destination.x}, ${combatPendingIntentDraft.intent.destination.y}` : "None"],
    ["Movement", candidate?.canonical_path?.length ? `${candidate.movement_cost_ft || 0} ft · ${candidate.canonical_path.length} exact path cells` : "None"],
    ["Area", candidate?.area?.center ? `center ${candidate.area.center.x}, ${candidate.area.center.y} · radius ${candidate.area.radius_cells} cells · ${candidate.area.affected_cells?.length || 0} affected cells` : "None"],
    ["Options", combatPendingIntentDraft.intent.option_ids?.length ? combatPendingIntentDraft.intent.option_ids.map(combatHumanizeId).join(", ") : "None"],
    ["Reaction decisions", `${combatPendingIntentDraft.reaction_decisions.length}`],
    ["State", `${preview.pre_state_version} → ${preview.post_state_version}`],
    ["Preview seal", preview.preview_id]
  ];
  for (const [term, value] of rows) { const dt = document.createElement("dt"); dt.textContent = term; const dd = document.createElement("dd"); dd.textContent = value; identity.append(dt, dd); }
  body.appendChild(identity);
  if (candidate?.choice_domains?.length) {
    const choiceHeading = document.createElement("h4"); choiceHeading.textContent = "Typed action choices"; body.appendChild(choiceHeading);
    const choiceList = document.createElement("ul"); choiceList.className = "combat-preview-choice-list";
    const selected = new Set(combatPendingIntentDraft.intent.option_ids || []);
    for (const domain of candidate.choice_domains) {
      const item = document.createElement("li");
      const chosen = (domain.option_ids || []).filter(id => selected.has(id));
      const costs = chosen.flatMap(id => Object.entries(domain.option_costs?.[id] || {}).map(([resource, amount]) => `${amount} ${combatHumanizeId(resource)}`));
      item.textContent = `${domain.display_name} · ${domain.selection_rule} · ${chosen.length ? chosen.map(combatHumanizeId).join(", ") : "none"}${costs.length ? ` · cost ${costs.join(", ")}` : ""}`;
      choiceList.appendChild(item);
    }
    body.appendChild(choiceList);
  }
  if (preview.resolved_reactions?.length) {
    const reactionHeading = document.createElement("h4"); reactionHeading.textContent = "Resolved controller reactions"; body.appendChild(reactionHeading);
    const reactionList = document.createElement("ul"); reactionList.className = "combat-preview-reaction-list";
    for (const reaction of preview.resolved_reactions) { const item = document.createElement("li"); item.textContent = `${combatActorName(reaction.reactor_id)} · ${combatHumanizeId(reaction.reaction_source_id)} · ${reaction.selection}${reaction.spend ? ` · spend ${reaction.spend}` : ""}${reaction.option_ids?.length ? ` · ${reaction.option_ids.map(combatHumanizeId).join(", ")}` : ""}`; reactionList.appendChild(item); }
    body.appendChild(reactionList);
  }
  const eventHeading = document.createElement("h4"); eventHeading.textContent = "Previewed committed events"; body.appendChild(eventHeading);
  const events = document.createElement("ol"); events.className = "combat-preview-event-list";
  for (const event of preview.events || []) {
    const item = document.createElement("li");
    const label = document.createElement("strong"); label.textContent = combatHumanizeId(event.event_type);
    const detail = document.createElement("span");
    const eventTargets = event.target_ids || (event.target_id ? [event.target_id] : []);
    const names = [event.actor_id, ...eventTargets].filter(Boolean).map(combatActorName);
    const payload = event.payload || {};
    const facts = [
      payload.hp_damage !== undefined ? `${payload.hp_damage} HP damage` : null,
      payload.remaining_hp !== undefined ? `${payload.remaining_hp} HP remains` : null,
      payload.amount !== undefined ? `amount ${payload.amount}` : null,
      payload.spend !== undefined && payload.spend ? `spend ${payload.spend}` : null,
      payload.pending_before !== undefined ? `${payload.pending_before} → ${payload.pending_after}` : null,
      payload.destination ? `to ${payload.destination.x}, ${payload.destination.y}` : null
    ].filter(Boolean);
    detail.textContent = [names.length ? names.join(" → ") : `event ${event.sequence ?? ""}`.trim(), ...facts].filter(Boolean).join(" · ");
    item.append(label, detail); events.appendChild(item);
  }
  if (!events.childElementCount) { const item = document.createElement("li"); item.textContent = "No journal events were produced by this preview."; events.appendChild(item); }
  body.appendChild(events);
  const dialog = document.getElementById("combatIntentReviewDialog");
  if (!dialog.open) dialog.showModal();
  document.getElementById("combatIntentCommit").focus();
}

async function continueCombatPreview() {
  if (!combatPendingIntentDraft || !combatMatch) return;
  if (!combatPendingIntentDraftIsCurrent()) {
    cancelCombatPendingIntent("The pending action became stale before preview. No combat state changed.");
    await refreshCombatDecision();
    return;
  }
  try {
    const preview = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/preview`, {
      method: "POST",
      body: JSON.stringify({intent: combatPendingIntentDraft.intent, reaction_decisions: combatPendingIntentDraft.reaction_decisions})
    });
    if (preview.status === "REACTION_REQUIRED") {
      combatPendingIntentDraft.reaction_context = preview.reaction_context;
      combatPendingIntentDraft.reaction_context_fingerprint = preview.reaction_context_fingerprint || null;
      combatPendingIntentDraft.resolved_reactions_before_prompt = preview.resolved_reactions_before_prompt || [];
      renderCombatReaction(preview);
      return;
    }
    renderCombatIntentReview(preview);
  } catch (error) {
    cancelCombatPendingIntent("The pending action was rejected or became stale. Refresh the current decision.");
    combatError(error);
    await refreshCombatDecision();
  }
}

async function commitCombatPendingIntent() {
  const draft = combatPendingIntentDraft;
  if (!draft?.preview || !combatMatch) return;
  if (!combatPendingIntentDraftIsCurrent()) {
    cancelCombatPendingIntent("The checked preview became stale before commit. No combat state changed.");
    await refreshCombatDecision();
    return;
  }
  const button = document.getElementById("combatIntentCommit"); button.disabled = true;
  try {
    const committed = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/intent`, {
      method: "POST",
      body: JSON.stringify({intent: draft.intent, reaction_decisions: draft.reaction_decisions, preview_id: draft.preview.preview_id})
    });
    combatMatch = committed.match;
    cancelCombatPendingIntent();
    await loadCombatHistory(combatMatch.match_id);
    renderCombatMatch(); await refreshCombatDecision(); await loadCombatMatches();
  } catch (error) {
    cancelCombatPendingIntent("The checked preview could not be committed. Refresh the decision and try again.");
    combatError(error);
    await refreshCombatDecision();
  } finally { button.disabled = false; }
}

function renderCombatReaction(preview) {
  const context = preview.reaction_context;
  closeCombatDialog("combatIntentReviewDialog");
  const panel = document.getElementById("combatReactionPrompt"); panel.hidden = false;
  const controller = preview.reaction_controller_mode ? ` Controller: ${combatControlLabels[preview.reaction_controller_mode] || preview.reaction_controller_mode}.` : "";
  const step = preview.reaction_step_number || (combatPendingIntentDraft.reaction_decisions.length + 1);
  const prior = preview.resolved_reactions_before_prompt?.length || 0;
  document.getElementById("combatReactionSummary").textContent = `Reaction step ${step}. ${combatActorName(context.reactor_id)} may use ${combatHumanizeId(context.reaction_source_id)}.${controller} ${context.pending_damage !== null ? `Pending damage: ${context.pending_damage}.` : ""} ${prior ? `${prior} earlier reaction decision${prior === 1 ? "" : "s"} resolved in this preview.` : ""}`;
  document.getElementById("combatReactionSuggestion").textContent = pretty(preview.local_suggestion);
  const spendLabel = document.getElementById("combatReactionSpendLabel");
  const spendSelect = document.getElementById("combatReactionSpend"); clearNode(spendSelect);
  spendLabel.hidden = !context.spend_options?.length;
  for (const value of context.spend_options || []) { const option = document.createElement("option"); option.value = String(value); option.textContent = String(value); spendSelect.appendChild(option); }
  const options = document.getElementById("combatReactionOptions"); clearNode(options); options.hidden = !context.legal_option_ids?.length;
  const suggested = new Set(preview.local_suggestion?.decision?.option_ids || []);
  for (const optionId of context.legal_option_ids || []) { const label = document.createElement("label"); const input = document.createElement("input"); input.type = "checkbox"; input.value = optionId; input.dataset.combatReactionOption = "true"; input.checked = suggested.has(optionId); label.append(input, document.createTextNode(combatHumanizeId(optionId))); options.appendChild(label); }
  const dialog = document.getElementById("combatReactionDialog"); if (!dialog.open) dialog.showModal(); document.getElementById("combatReactionUse").focus();
}
async function submitCombatReaction(selection) {
  if (!combatPendingIntentDraft?.reaction_context) return;
  if (!combatPendingIntentDraftIsCurrent()) {
    cancelCombatPendingIntent("The reaction window became stale. No combat state changed.");
    await refreshCombatDecision();
    return;
  }
  const context = combatPendingIntentDraft.reaction_context;
  const optionIds = selection === "USE"
    ? [...document.querySelectorAll("#combatReactionOptions [data-combat-reaction-option]:checked")].map(row => row.value)
    : [];
  combatPendingIntentDraft.reaction_trace.push({
    reaction_step_number: combatPendingIntentDraft.reaction_decisions.length + 1,
    context_fingerprint: combatPendingIntentDraft.reaction_context_fingerprint || null,
    checkpoint: context.checkpoint,
    reactor_id: context.reactor_id,
    reaction_source_id: context.reaction_source_id,
    selection
  });
  combatPendingIntentDraft.reaction_decisions.push({
    checkpoint: context.checkpoint,
    reactor_id: context.reactor_id,
    reaction_source_id: context.reaction_source_id,
    selection,
    spend: selection === "USE" && context.spend_options?.length ? Number(document.getElementById("combatReactionSpend").value) : 0,
    option_ids: optionIds
  });
  delete combatPendingIntentDraft.reaction_context;
  document.getElementById("combatReactionPrompt").hidden = true;
  closeCombatDialog("combatReactionDialog");
  await continueCombatPreview();
}
document.getElementById("combatReactionUse").onclick = () => submitCombatReaction("USE");
document.getElementById("combatReactionDecline").onclick = () => submitCombatReaction("DECLINE");
document.getElementById("combatIntentCommit").onclick = commitCombatPendingIntent;
document.getElementById("combatIntentCancel").onclick = () => cancelCombatPendingIntent("Manual action canceled. No combat state changed.");
document.getElementById("combatIntentReviewClose").onclick = () => cancelCombatPendingIntent("Manual action canceled. No combat state changed.");
document.getElementById("combatReactionDialogClose").onclick = () => cancelCombatPendingIntent("Pending action canceled at the reaction window. No combat state changed.");
for (const dialogId of ["combatIntentReviewDialog", "combatReactionDialog"]) {
  document.getElementById(dialogId).addEventListener("cancel", event => {
    event.preventDefault();
    cancelCombatPendingIntent("Manual action canceled. No combat state changed.");
  });
}

document.getElementById("combatCreateMatch").onclick = async () => {
  if (!combatCatalog) return;
  const status = document.getElementById("combatSetupStatus");
  status.textContent = "Running the read-only fight preflight…";
  status.classList.remove("error");
  const projections = combatCatalog.projections.filter(row => row.primary_combatant && document.querySelector(`[data-c3c-selected][data-c3c-actor="${row.runtime_entity_id}"]`)?.checked);
  const controlModes = combatSelectedModes();
  const battlefield = combatCatalog.battlefields[0];
  const payload = {
    encounter_id: document.getElementById("combatEncounter").value,
    display_name: document.getElementById("combatDisplayName").value.trim() || null,
    match_seed: document.getElementById("combatSeed").value.trim() || null,
    maximum_rounds: 20,
    battlefield_id: battlefield.stable_id,
    initiative_method: "DETERMINISTIC_ACCEPTED",
    grid_calibration: {mode: "AUTHORITATIVE_GATE2_GRID", width: battlefield.width_squares, height: battlefield.height_squares, square_size_ft: battlefield.square_size_ft, centered_tokens: true},
    participants: projections.map(row => combatOwnerSetupParticipant(row, controlModes)),
    team_names: {"team:1": document.getElementById("combatTeam1Name").value.trim() || "Team 1", "team:2": document.getElementById("combatTeam2Name").value.trim() || "Team 2"}
  };
  try {
    const preflight = await api("/api/combat/new-fight/preflight", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    if (!preflight.ready) {
      status.textContent = `Fight setup blocked: ${preflight.blockers.map(row => row.code).join(", ")}`;
      status.classList.add("error");
      return;
    }
    const creation = {
      ...payload,
      preflight_commitment: preflight.preflight_commitment,
      idempotency_key: `owner:${preflight.preflight_commitment}`,
      owner_confirmed: true
    };
    combatMatch = await api("/api/combat/new-fight/create", {
      method: "POST",
      body: JSON.stringify(creation)
    });
    setCombatWorkspaceActive(true);
    setCombatWorkspaceView("owner");
    await loadCombatHistory(combatMatch.match_id);
    renderCombatMatch(); await refreshCombatDecision(); await loadCombatMatches();
    status.textContent = "Fight created at the first legal decision point. Manual control is the default.";
    document.getElementById("combatWorkspace").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) { combatError(error); }
};

document.getElementById("combatRefreshMatches").onclick = () => loadCombatMatches().catch(combatError);
document.getElementById("combatRefreshDecision").onclick = refreshCombatDecision;

document.getElementById("combatHistorySlider").oninput = event => setCombatHistoryIndex(event.target.value);
document.getElementById("combatHistoryJump").onchange = event => setCombatHistoryIndex(event.target.value);
document.getElementById("combatHistoryPrevious").onclick = () => {
  const current = combatHistoryIndex === null ? (combatHistory?.boundaries?.length || 1) - 1 : combatHistoryIndex;
  setCombatHistoryIndex(current - 1);
};
document.getElementById("combatHistoryNext").onclick = () => {
  const current = combatHistoryIndex === null ? (combatHistory?.boundaries?.length || 1) - 1 : combatHistoryIndex;
  setCombatHistoryIndex(current + 1);
};
document.getElementById("combatReturnLive").onclick = returnCombatLive;
document.getElementById("combatHistoryPanel").addEventListener("keydown", event => {
  if (event.target.matches("select, input")) return;
  if (event.key === "ArrowLeft") { event.preventDefault(); document.getElementById("combatHistoryPrevious").click(); }
  if (event.key === "ArrowRight") { event.preventDefault(); document.getElementById("combatHistoryNext").click(); }
});

document.getElementById("combatPause").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return; combatAutoRunning = false;
  try {
    combatMatch = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/pause`, {method: "POST", body: "{}"});
    combatPresentation = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/presentation`);
    renderCombatMatch();
  }
  catch (error) { combatError(error); }
};

document.getElementById("combatResume").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return;
  try {
    combatMatch = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/resume`, {method: "POST", body: "{}"});
    combatPresentation = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/presentation`);
    renderCombatMatch(); await refreshCombatDecision();
  }
  catch (error) { combatError(error); }
};

document.getElementById("combatSnapshot").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return;
  try { combatSetDiagnostic(await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/snapshot`, {method: "POST", body: "{}"})); }
  catch (error) { combatError(error); }
};

document.getElementById("combatVerify").onclick = async () => {
  if (!combatMatch) return;
  try { combatSetDiagnostic(await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/verify`, {method: "POST", body: "{}"})); }
  catch (error) { combatError(error); }
};

document.getElementById("combatReplay").onclick = async () => {
  if (!combatMatch) return;
  try {
    const replay = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/replay`);
    combatSetDiagnostic({status: replay.status, match_id: replay.match_id, event_count: replay.events.length, roll_count: replay.rolls.length, terminal_result: replay.terminal_result, canonical_state_sha256: replay.canonical_state_sha256});
  } catch (error) { combatError(error); }
};

document.getElementById("combatSuggest").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return;
  try {
    const suggestion = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/suggest`, {method: "POST", body: "{}"});
    const record = suggestion.record;
    const selected = combatDecision?.context?.legal_candidates?.find(row => row.candidate_id === suggestion.intent.candidate_id);
    const box = document.getElementById("combatSuggestion"); clearNode(box);
    const summary = document.createElement("p"); summary.textContent = `${selected?.display_name || record.selected_candidate_id}: ${record.explanation}`;
    const components = document.createElement("p");
    const score = record.scored_alternatives?.find(row => row.candidate_id === record.selected_candidate_id);
    components.textContent = (score?.components || []).filter(row => row.value !== 0).slice(0, 5).map(row => `${row.component} ${row.value >= 0 ? "+" : ""}${row.value}`).join(" · ");
    const accept = document.createElement("button"); accept.type = "button"; accept.className = "primary-action"; accept.textContent = "Accept Suggestion";
    accept.addEventListener("click", () => beginCombatIntent({
      decision_id: suggestion.intent.decision_id,
      state_version: suggestion.intent.state_version,
      candidate_id: suggestion.intent.candidate_id,
      actor_id: suggestion.intent.actor_id,
      target_ids: suggestion.intent.target_ids || [],
      destination: suggestion.intent.destination || null,
      option_ids: suggestion.intent.option_ids || []
    }));
    box.append(summary, components, accept);
    document.getElementById("combatControllerTechnical").textContent = pretty(suggestion);
  } catch (error) { combatError(error); }
};

function combatDraftBlocksAutomaticExecution() {
  if (!combatPendingIntentDraft && !combatInteractionDraft) return false;
  document.getElementById("combatAutoStatus").textContent = "Cancel or complete the current non-authoritative manual draft before automatic execution.";
  document.getElementById("combatAutoStatus").classList.add("error");
  return true;
}

async function runOneLocalStep(executionEpoch = combatExecutionEpoch) {
  if (!combatMatch || combatIsHistorical() || combatHistoryTransitionPending || executionEpoch !== combatExecutionEpoch || combatDraftBlocksAutomaticExecution()) {
    return {status: "HISTORY_SELECTED"};
  }
  const currentActor = combatActorName(combatMatch?.state?.current_actor_id);
  const matchId = combatMatch.match_id;
  const autoStatus = document.getElementById("combatAutoStatus");
  autoStatus.textContent = `${currentActor} is choosing an action…`;
  autoStatus.classList.remove("error");
  const result = await api(`/api/combat/matches/${combatId(matchId)}/auto-step`, {method: "POST", body: "{}"});
  if (!combatMatch || combatMatch.match_id !== matchId) return {status: "FIGHT_CLOSED"};
  if (result.match) combatMatch = result.match;
  const historySelectedDuringStep = combatIsHistorical() || combatHistoryTransitionPending || executionEpoch !== combatExecutionEpoch;
  if (result.match && !historySelectedDuringStep) {
    await loadCombatHistory(combatMatch.match_id);
    renderCombatMatch();
    await refreshCombatDecision();
  }
  if (historySelectedDuringStep) {
    autoStatus.textContent = "Automatic execution stopped. The selected historical boundary remains active.";
  } else if (result.status === "COMMITTED") {
    const provider = result.provider?.model ? `API AI (${result.provider.model})` : "Local AI";
    autoStatus.textContent = `${provider} completed ${currentActor}'s decision.`;
  } else {
    autoStatus.textContent = `${combatActorName(result.actor_id)} is set to ${combatControlLabels[result.control_mode] || combatHumanizeId(result.control_mode)}. Automatic combat paused.`;
  }
  document.getElementById("combatControllerTechnical").textContent = pretty(result.record || result);
  return result;
}

function runTrackedCombatAutoStep(executionEpoch) {
  const promise = runOneLocalStep(executionEpoch);
  combatAutoStepPromise = promise;
  return promise.finally(() => {
    if (combatAutoStepPromise === promise) combatAutoStepPromise = null;
  });
}

document.getElementById("combatLocalStep").onclick = async () => {
  if (!combatMatch || combatIsHistorical() || combatHistoryTransitionPending || combatAutoStepPromise || combatDraftBlocksAutomaticExecution()) return;
  const executionEpoch = combatExecutionEpoch;
  try { await runTrackedCombatAutoStep(executionEpoch); } catch (error) { combatError(error); }
};

document.getElementById("combatLocalRun").onclick = async () => {
  if (!combatMatch || combatAutoRunning || combatIsHistorical() || combatHistoryTransitionPending || combatDraftBlocksAutomaticExecution()) return;
  combatAutoRunning = true;
  const executionEpoch = combatExecutionEpoch;
  const runButton = document.getElementById("combatLocalRun");
  runButton.disabled = true;
  runButton.textContent = "Auto Fight Running…";
  try {
    while (combatAutoRunning && combatMatch && !combatMatch.state.terminal_result && !combatIsHistorical() && !combatHistoryTransitionPending && executionEpoch === combatExecutionEpoch) {
      const result = await runTrackedCombatAutoStep(executionEpoch);
      if (result.status !== "COMMITTED" || combatIsHistorical() || combatHistoryTransitionPending || executionEpoch !== combatExecutionEpoch) break;
      await new Promise(resolve => setTimeout(resolve, 180));
    }
  } catch (error) { combatError(error); }
  finally {
    combatAutoRunning = false;
    runButton.disabled = combatIsHistorical() || combatHistoryTransitionPending || Boolean(combatMatch?.state?.terminal_result);
    runButton.textContent = combatMatch?.state?.terminal_result ? "Fight Complete" : "Run Auto";
    await loadCombatMatches();
  }
};

document.getElementById("combatLocalStop").onclick = () => {
  combatAutoRunning = false;
  document.getElementById("combatAutoStatus").textContent = "Auto fight will stop after the current decision finishes.";
};

document.getElementById("combatCopyAIFrame").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return;
  try {
    const result = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/ai-frame`);
    const box = document.getElementById("combatAIFrame"); box.value = result.frame_text;
    try { await navigator.clipboard.writeText(result.frame_text); combatSetDiagnostic("Decision request copied to the clipboard."); }
    catch (_error) { box.focus(); box.select(); combatSetDiagnostic("Automatic clipboard access was unavailable. The decision request is selected for manual copy."); }
  } catch (error) { combatError(error); }
};

document.getElementById("combatCheckAIIntent").onclick = async () => {
  if (!combatMatch || combatIsHistorical()) return;
  combatAIValidationToken = null; document.getElementById("combatExecuteAIIntent").disabled = true;
  try {
    const parsed = JSON.parse(document.getElementById("combatAIIntent").value);
    const result = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/ai-intent/validate`, {method: "POST", body: JSON.stringify(parsed)});
    combatAIValidationToken = result.validation_token;
    document.getElementById("combatAIResult").textContent = pretty(result);
    document.getElementById("combatExecuteAIIntent").disabled = false;
  } catch (error) { document.getElementById("combatAIResult").textContent = error.message; }
};

document.getElementById("combatExecuteAIIntent").onclick = async () => {
  if (!combatMatch || !combatAIValidationToken || combatIsHistorical()) return;
  try {
    const parsed = JSON.parse(document.getElementById("combatAIIntent").value);
    parsed.validation_token = combatAIValidationToken;
    const result = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/ai-intent/execute`, {method: "POST", body: JSON.stringify(parsed)});
    combatMatch = result.match; combatAIValidationToken = null; document.getElementById("combatExecuteAIIntent").disabled = true;
    await loadCombatHistory(combatMatch.match_id);
    document.getElementById("combatAIResult").textContent = pretty({status: "EXECUTED", preview_id: result.preview_id});
    renderCombatMatch(); await refreshCombatDecision(); await loadCombatMatches();
  } catch (error) { document.getElementById("combatAIResult").textContent = error.message; }
};

document.getElementById("combatFriendlySetupTab").onclick = () => setCombatSetupView("friendly");
document.getElementById("combatAdvancedSetupTab").onclick = () => setCombatSetupView("advanced");
document.getElementById("combatReturnSetup").onclick = async () => {
  combatAutoRunning = false;
  setCombatWorkspaceActive(false);
  await loadCombatMatches().catch(combatError);
  document.getElementById("combatSetup").scrollIntoView({behavior: "smooth", block: "start"});
};
document.getElementById("combatOwnerView").onclick = () => setCombatWorkspaceView("owner");
document.getElementById("combatTechnicalView").onclick = () => setCombatWorkspaceView("technical");
document.getElementById("combatCharacterAuthorityDetails").onclick = () => {
  const actor = combatProjectionActor(combatSelectedActorId);
  if (combatHasCharacterAuthorityDetails(actor)) openCombatCharacterAuthorityDetails(actor);
};
document.getElementById("combatZoomOut").onclick = () => {
  combatViewportZoom = Math.max(.65, Number((combatViewportZoom - .15).toFixed(2)));
  renderCombatBoard(); renderCombatSheets();
};
document.getElementById("combatZoomFit").onclick = () => {
  combatViewportZoom = 1;
  renderCombatBoard(); renderCombatSheets();
  document.getElementById("combatBattlefieldViewport").scrollTo({left: 0, top: 0, behavior: "smooth"});
};
document.getElementById("combatZoomIn").onclick = () => {
  combatViewportZoom = Math.min(1.9, Number((combatViewportZoom + .15).toFixed(2)));
  renderCombatBoard(); renderCombatSheets();
};
document.getElementById("combatCenterTurn").onclick = () => {
  const actorId = combatPresentation?.current_actor_id;
  if (!actorId) return;
  combatFollowCurrentTurn = true;
  combatSelectedActorId = actorId;
  renderCombatActors(); renderCombatBoard(); renderCombatSheets(); centerCombatActor(actorId);
};
document.getElementById("combatPanMode").onclick = () => {
  if (combatInteractionMode === "pan") {
    combatSetInteractionMode("inspect");
    document.getElementById("combatDecisionStatus").textContent = "Inspection mode. Token selection changes inspection state only.";
  } else {
    combatInteractionDraft = null;
    combatSetInteractionMode("pan");
    document.getElementById("combatDecisionStatus").textContent = "Pan mode. Drag the battlefield viewport; combat coordinates do not change.";
  }
  renderCombatInteractionBar(); renderCombatBoard();
};
document.getElementById("combatInteractionChoice").onchange = event => {
  if (combatInteractionDraft) combatInteractionDraft.selected_candidate_id = event.target.value;
  renderCombatBoard();
};
document.getElementById("combatInteractionUse").onclick = () => {
  const candidateId = document.getElementById("combatInteractionChoice").value;
  if (candidateId) completeCombatMapSelection(candidateId);
};
document.getElementById("combatInteractionCancel").onclick = () => cancelCombatMapSelection("Map choice canceled. No combat state changed.");
const combatViewport = document.getElementById("combatBattlefieldViewport");
combatViewport.addEventListener("pointerdown", event => {
  if (combatInteractionMode !== "pan" || event.button !== 0) return;
  combatPanPointer = {pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: combatViewport.scrollLeft, top: combatViewport.scrollTop};
  combatViewport.setPointerCapture?.(event.pointerId);
  combatViewport.classList.add("combat-panning");
  event.preventDefault();
});
combatViewport.addEventListener("pointermove", event => {
  if (!combatPanPointer || event.pointerId !== combatPanPointer.pointerId) return;
  combatViewport.scrollLeft = combatPanPointer.left - (event.clientX - combatPanPointer.x);
  combatViewport.scrollTop = combatPanPointer.top - (event.clientY - combatPanPointer.y);
});
const endCombatPan = event => {
  if (!combatPanPointer || event.pointerId !== combatPanPointer.pointerId) return;
  combatViewport.releasePointerCapture?.(event.pointerId);
  combatPanPointer = null;
  combatViewport.classList.remove("combat-panning");
};
combatViewport.addEventListener("pointerup", endCombatPan);
combatViewport.addEventListener("pointercancel", endCombatPan);
document.getElementById("combatToggleNameplates").onclick = event => {
  combatNameplatesVisible = !combatNameplatesVisible;
  event.currentTarget.setAttribute("aria-pressed", combatNameplatesVisible ? "true" : "false");
  renderCombatBoard(); renderCombatSheets();
};
document.getElementById("combatToggleGeometry").onclick = event => {
  const order = ["subtle", "full", "off"];
  combatGeometryOverlayMode = order[(order.indexOf(combatGeometryOverlayMode) + 1) % order.length];
  event.currentTarget.textContent = combatGeometryOverlayMode === "off" ? "Geometry Off" : combatGeometryOverlayMode === "full" ? "Geometry Full" : "Geometry";
  event.currentTarget.setAttribute("aria-pressed", combatGeometryOverlayMode === "off" ? "false" : "true");
  renderCombatBoard(); renderCombatSheets();
};
for (const button of document.querySelectorAll("[data-combat-mobile-tab]")) {
  button.addEventListener("click", () => setCombatMobileTab(button.dataset.combatMobileTab));
}
document.getElementById("combatCharacterDialogClose").onclick = () => document.getElementById("combatCharacterDialog").close();
document.getElementById("combatCharacterDialog").addEventListener("click", event => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
window.addEventListener("resize", () => {
  if (combatMatch && combatPresentation) {
    combatUpdateSheetLayoutMode();
    renderCombatSheets();
    requestAnimationFrame(positionCombatFloatingSheet);
  }
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  const dialog = document.getElementById("combatCharacterDialog");
  if (dialog.open) { dialog.close(); return; }
  if (combatPendingIntentDraft) { cancelCombatPendingIntent("Manual action canceled. No combat state changed."); return; }
  if (combatInteractionDraft || ["pan", "select_target", "select_destination", "select_area", "select_exact"].includes(combatInteractionMode)) { cancelCombatMapSelection("Map interaction canceled. No combat state changed."); return; }
  if (combatPinnedActorId) { combatPinnedActorId = null; renderCombatSheets(); return; }
  if (combatSelectedActorId) { combatSelectedActorId = null; combatFollowCurrentTurn = false; renderCombatBoard(); renderCombatSheets(); renderCombatActors(); }
});
document.getElementById("combatBackgroundUpload").addEventListener("change", async event => {
  const file = event.target.files?.[0];
  if (file) await uploadCombatVisual("background", null, file);
  event.target.value = "";
});
document.getElementById("combatBackgroundReset").onclick = () => resetCombatVisual("background");
document.getElementById("combatConfigureAPI").onclick = () => {
  showScreen("projects");
  document.getElementById("deepSeekHeading")?.scrollIntoView({behavior: "smooth", block: "start"});
};

for (const button of document.querySelectorAll('nav button[data-screen="combat"]')) {
  button.addEventListener("click", () => { if (!combatCatalog) loadCombatCatalog(); else loadCombatMatches().catch(combatError); });
}

const prepareFactoryWorkspaceButton = document.getElementById("prepareFactoryWorkspace");
if (prepareFactoryWorkspaceButton) prepareFactoryWorkspaceButton.onclick = async () => {
  if (!selectedProject) return;
  const result = document.getElementById("factoryWorkspaceResult");
  const pending = ownerCharacterSheet?.factory_workspace?.provider_free_rebuild_available === true;
  result.textContent = pending ? "Rebuilding the Factory workspace from the stored GM receipt…" : "Preparing deterministic GM tactical authoring and Factory workspace…";
  try {
    const built = await api(`/api/characters/${encodeURIComponent(selectedProject)}/factory-workspace/build`, {method: "POST", body: "{}"});
    result.textContent = `Prepared ${friendlyLabel(built.workspace_status)}. Command 5 and Command 6 were not run.`;
    await openOwnerCharacterSheet(selectedProject);
  } catch (error) { result.textContent = plainAPIError(error, "The Factory workspace could not be prepared."); }
};

const authorGmTacticalButton = document.getElementById("authorGmTactical");
if (authorGmTacticalButton) authorGmTacticalButton.onclick = async () => {
  if (!selectedProject) return;
  const result = document.getElementById("factoryWorkspaceResult");
  result.textContent = "Requesting one explicit Local AI GM authoring result…";
  try {
    const authored = await api(`/api/characters/${encodeURIComponent(selectedProject)}/factory-workspace/gm-author`, {method: "POST", body: "{}"});
    result.textContent = authored.status === "GM_AUTHORING_PERSISTED_REBUILD_PENDING"
      ? `Actual GM guidance stored in ${authored.receipt_id}. The provider-free workspace rebuild failed; use Rebuild Command 1–4 workspace. Owner ratification remains separate.`
      : `Actual GM guidance stored in ${authored.receipt_id}. Owner ratification remains separate.`;
    await openOwnerCharacterSheet(selectedProject);
  } catch (error) { result.textContent = plainAPIError(error, "Local GM authoring could not be completed."); }
};
const issueGmRatificationChallengeButton = document.getElementById("issueGmRatificationChallenge");
if (issueGmRatificationChallengeButton) issueGmRatificationChallengeButton.onclick = async () => {
  if (!selectedProject) return;
  const result = document.getElementById("factoryWorkspaceResult");
  result.textContent = "Preparing the exact-byte owner ratification challenge…";
  try {
    const issued = await api(`/api/characters/${encodeURIComponent(selectedProject)}/factory-workspace/gm-author/ratification-challenge`, {method: "POST", body: JSON.stringify({ttl_seconds: 300})});
    gmAuthoringRatificationChallenge = issued.challenge;
    const ratify = document.getElementById("ratifyGmAuthoring");
    if (ratify) ratify.disabled = false;
    result.textContent = `Review receipt ${issued.receipt_id}, then choose Ratify current GM guidance to record the owner decision.`;
  } catch (error) { result.textContent = plainAPIError(error, "The owner ratification challenge could not be issued."); }
};
const ratifyGmAuthoringButton = document.getElementById("ratifyGmAuthoring");
if (ratifyGmAuthoringButton) ratifyGmAuthoringButton.onclick = async () => {
  if (!selectedProject || !gmAuthoringRatificationChallenge) return;
  const result = document.getElementById("factoryWorkspaceResult");
  const currentWorkspace = ownerCharacterSheet?.factory_workspace || {};
  const workspaceRebuildPending = currentWorkspace.provider_free_rebuild_available === true || currentWorkspace.status === "REBUILD_PENDING";
  if (workspaceRebuildPending) {
    gmAuthoringRatificationChallenge = null;
    ratifyGmAuthoringButton.disabled = true;
    result.textContent = "The provider-free workspace rebuild is pending; owner ratification is unavailable until it completes.";
    return;
  }
  result.textContent = "Recording the explicit owner ratification decision…";
  try {
    const receiptId = (ownerCharacterSheet?.factory_workspace || {}).gm_receipt_id;
    if (!receiptId) throw new Error("The current sheet has no verified GM receipt.");
    const decided = await api(`/api/characters/${encodeURIComponent(selectedProject)}/factory-workspace/gm-author/ratify`, {method: "POST", body: JSON.stringify({receipt_id: receiptId, challenge_id: gmAuthoringRatificationChallenge.challenge_id, nonce: gmAuthoringRatificationChallenge.nonce})});
    gmAuthoringRatificationChallenge = null;
    ratifyGmAuthoringButton.disabled = true;
    result.textContent = `Owner ratification recorded for ${decided.receipt_id}. Command 5 remains separately authorized.`;
    await openOwnerCharacterSheet(selectedProject);
  } catch (error) { result.textContent = plainAPIError(error, "The owner ratification could not be recorded."); }
};


const refreshNonSphereButton = document.getElementById("refreshNonSphereAuthority");
if (refreshNonSphereButton) refreshNonSphereButton.onclick = () => loadNonSphereAuthorityPanel();
const setNonSphereMethodButton = document.getElementById("setNonSpherePrimaryMethod");
if (setNonSphereMethodButton) setNonSphereMethodButton.onclick = () => {
  const actionContext = currentNonSphereActionContext();
  if (!actionContext) return rejectStaleNonSphereAction();
  const methodId = document.getElementById("nonSpherePrimaryMethod").value;
  if (methodId) updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(actionContext.projectId)}/primary-method`, {method_id: methodId, evidence_ids: readNonSphereEvidence(actionContext)}, actionContext);
};
const setNonSphereAccessSourcesButton = document.getElementById("setNonSphereAccessSources");
if (setNonSphereAccessSourcesButton) setNonSphereAccessSourcesButton.onclick = () => {
  const actionContext = currentNonSphereActionContext();
  if (!actionContext) return rejectStaleNonSphereAction();
  try {
    updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(actionContext.projectId)}/access-sources`, {evidence_ids: readNonSphereEvidence(actionContext)}, actionContext);
  } catch (error) {
    document.getElementById("nonSphereTechnical").textContent = plainAPIError(error, "Committed evidence selection is invalid.");
  }
};
const setNonSphereFoundationButton = document.getElementById("setNonSphereFoundation");
if (setNonSphereFoundationButton) setNonSphereFoundationButton.onclick = () => {
  const actionContext = currentNonSphereActionContext();
  if (!actionContext) return rejectStaleNonSphereAction();
  updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(actionContext.projectId)}/foundation`, {foundation_id: document.getElementById("nonSphereFoundation").value || null}, actionContext);
};
loadNonSphereAuthorityPanel().catch(() => {});

// W3-P1 owner staging, Save As, continuation, and read-only demo boundary.
let ownerStagedArtifact = null;
const ownerArtifactResult = document.getElementById("ownerArtifactResult");
function renderSelectedStage1State(project, stage) {
  const name = project?.working_name || project?.name || "Selected character";
  const heading = document.getElementById("stage1ContinuationHeading");
  const summary = document.getElementById("stage1ContinuationSummary");
  const status = document.getElementById("xiangContinuationStatus");
  if (heading) heading.textContent = `${name} — Stage 1`;
  if (!summary || !status) return;
  if (stage.stage1_sealed) {
    summary.innerHTML = "<strong>Stage 1 plan sealed.</strong> This exact selected project can continue to the first legal advancement action.";
    status.textContent = `Sealed for project revision ${stage.project_revision}.`;
  } else if (stage.request_prepared) {
    summary.innerHTML = "<strong>Stage 1 request prepared.</strong> Reuse the sealed request, then import, validate, and approve one response before continuation.";
    status.textContent = `Request ready for project revision ${stage.project_revision}.`;
  } else {
    summary.innerHTML = "<strong>Ready to prepare Stage 1.</strong> Staging a Chat request will create one request for this exact project and revision.";
    status.textContent = `No Stage 1 request exists yet for project revision ${stage.project_revision}.`;
  }
}
function ownerSelectedMatchId() { return combatMatch?.match_id || document.querySelector("[data-match-id].selected")?.dataset.matchId || null; }
for (const button of document.querySelectorAll("[data-artifact-kind]")) {
  button.addEventListener("click", async () => {
    const kind = button.dataset.artifactKind;
    ownerArtifactResult.textContent = "Staging artifact through the existing Factory service…";
    try {
      const payload = {artifact_kind: kind, project_id: selectedProject || null, prompt_id: stage1PromptData?.prompt_id || null, match_id: ownerSelectedMatchId()};
      ownerStagedArtifact = await api("/api/owner-artifacts/stage", {method:"POST", body:JSON.stringify(payload)});
      document.getElementById("ownerSaveAs").disabled = false;
      ownerArtifactResult.textContent = `${friendlyLabel(kind)} staged: ${ownerStagedArtifact.filename}\n${ownerStagedArtifact.bytes} bytes\n${ownerStagedArtifact.sha256}`;
      if (kind === "chat_request" && selectedProject && ownerStagedArtifact.source_result?.prompt_id) {
        const [stage, projectEnvelope] = await Promise.all([
          api(`/api/projects/${encodeURIComponent(selectedProject)}/stage1/status`),
          api(`/api/projects/${encodeURIComponent(selectedProject)}`),
        ]);
        stage1PromptData = {
          prompt_id: ownerStagedArtifact.source_result.prompt_id,
          project_id: selectedProject,
          project_revision: stage.project_revision,
        };
        renderSelectedStage1State(projectEnvelope.project || projectEnvelope, stage);
        updateAIProviderControls();
      }
    } catch (error) {
      ownerStagedArtifact = null;
      document.getElementById("ownerSaveAs").disabled = true;
      ownerArtifactResult.textContent = plainAPIError(error, "The artifact could not be staged.");
    }
  });
}
const ownerSaveAs = document.getElementById("ownerSaveAs");
if (ownerSaveAs) ownerSaveAs.addEventListener("click", async () => {
  if (!ownerStagedArtifact) return;
  const destination = document.getElementById("ownerSaveAsPath").value.trim();
  if (!destination) { ownerArtifactResult.textContent = "Enter the full native .zip destination path."; return; }
  try {
    const result = await api("/api/owner-artifacts/save-as", {method:"POST", body:JSON.stringify({artifact_id:ownerStagedArtifact.artifact_id,destination_path:destination,overwrite:false})});
    ownerArtifactResult.textContent = `Saved: ${result.path}\n${result.bytes} bytes\n${result.sha256}`;
  } catch (error) { ownerArtifactResult.textContent = plainAPIError(error, "Save As did not complete."); }
});
const developerMode = document.getElementById("ownerDeveloperMode");
if (developerMode) developerMode.addEventListener("click", () => {
  const enabled = developerMode.getAttribute("aria-pressed") !== "true";
  developerMode.setAttribute("aria-pressed", String(enabled));
  developerMode.textContent = `Developer / Diagnostics mode: ${enabled ? "On" : "Off"}`;
  for (const node of document.querySelectorAll(".developer-only")) node.hidden = !enabled;
});
const xiangPrepare = document.getElementById("xiangPrepareAdvancement");
if (xiangPrepare) xiangPrepare.addEventListener("click", async () => {
  const status = document.getElementById("xiangContinuationStatus");
  if (!selectedProject) { status.textContent = "Select a character project first."; return; }
  try {
    const stage = await api(`/api/projects/${encodeURIComponent(selectedProject)}/stage1/status`);
    renderSelectedStage1State({working_name: document.getElementById("stage1ContinuationHeading")?.textContent?.split(" — ")[0]}, stage);
    if (!stage.stage1_sealed) {
      status.textContent = stage.request_prepared
        ? "The Stage 1 request is ready. Import, validate, and approve its response before continuing."
        : "Prepare or stage the Stage 1 request for this selected project first.";
      return;
    }
    showScreen("projects");
    document.getElementById("stage2Panel")?.scrollIntoView({behavior:"smooth",block:"start"});
    status.textContent = "Stage 1 Plan Sealed. Prepare the typed advancement choices below; no character data has been changed.";
  } catch (error) { status.textContent = plainAPIError(error, "The Stage 1 continuation could not be prepared."); }
});
const openAcceptedDemo = document.getElementById("combatOpenAcceptedDemo");
if (openAcceptedDemo) openAcceptedDemo.addEventListener("click", async () => {
  const host = document.getElementById("combatAcceptedDemoPreflight");
  try {
    const report = await api("/api/combat/accepted-demo/preflight");
    host.textContent = pretty(report);
    if (report.ready) await loadCombatMatches();
  } catch (error) { host.textContent = plainAPIError(error, "The accepted demo preflight could not be read."); }
});

// CG1-P1: one owner workflow over the existing Stage 1/provider pipeline.
let cgRun = null;
let cgFinalizeInFlight = false;
function cgSelectedProjectId() {
  if (typeof selectedProject === "string") return selectedProject;
  return selectedProject?.project_id || selectedProject?.project?.project_id || null;
}
function cgIsClean(run) {
  if (!run) return false;
  const reviewable = ["READY_FOR_REVIEW", "NEEDS_REVIEW"].includes(run.status);
  const ownerState = ownerViewFor(run);
  return reviewable && run.quality?.status === "CLEAN" && !(run.blockers || []).length
    && !(ownerState.decisions || []).length && !(ownerState.blockers || []).length;
}
function cgRender(run) {
  cgRun = run;
  const progress = document.getElementById("cgProgress");
  const labels = {
    PREPARING_REQUEST: "Preparing request",
    WAITING_FOR_RESPONSE: "Waiting for response",
    READY_FOR_REVIEW: "Ready for review",
    NEEDS_REVIEW: "Needs review",
    CLEAN_AND_FINALIZED: "Clean and finalized",
    BLOCKED: "Blocked",
    CANCELLED: "Cancelled",
    REVISION_REQUESTED: "Needs review"
  };
  progress.textContent = labels[run.status] || run.status;
  document.getElementById("cgResult").textContent = pretty(run);
  const reviewable = ["READY_FOR_REVIEW", "NEEDS_REVIEW"].includes(run.status);
  const clean = cgIsClean(run);
  document.getElementById("cgFinalize").disabled = !clean || cgFinalizeInFlight;
  document.getElementById("cgRevise").disabled = !reviewable;
  document.getElementById("cgCancel").disabled = !!run.commit || ["CANCELLED","CLEAN_AND_FINALIZED"].includes(run.status);
  document.getElementById("cgDownloadRequest").disabled = run.execution_mode !== "MANUAL_CHAT";
  const correctionDownload = document.getElementById("cgDownloadCorrection");
  const correctionAvailable = run.execution_mode === "MANUAL_CHAT" && run.manual_ai_correction?.required === true;
  if (correctionDownload) {
    correctionDownload.hidden = !correctionAvailable;
    correctionDownload.disabled = !correctionAvailable || !run.run_id;
  }
  document.getElementById("cgAutoOptIn").disabled = !clean || run.execution_mode !== "AUTO_FINALIZE_WHEN_CLEAN";
  const preview = run.dry_run?.preview || {};
  const identity = preview.identity?.identity || preview.identity || {};
  const readiness = Object.keys(preview.readiness || {}).sort();
  document.getElementById("cgCandidateSummary").textContent = [
    `Candidate: ${identity.name || identity.display_name || "Unnamed character"}`,
    `Concept: ${preview.identity?.concept || identity.concept || "Not supplied"}`,
    `Target CL: ${preview.target_cl ?? "Not compiled"}`,
    `Verified surfaces: ${readiness.length ? readiness.join(", ") : "None yet"}`,
    `Combat: ${preview.readiness?.combat ? "Verified for this candidate" : "Not requested or not supported for this new identity"}`
  ].join("\n");
  if (run.execution_mode === "MANUAL_CHAT" && run.request?.stage1_prompt?.prompt_id) {
    document.getElementById("cgProgress").textContent = "Waiting for response — use the existing Chat request ZIP or paste the structured response below.";
  }
}
document.getElementById("characterCreationMode")?.addEventListener("change", async (event) => {
  document.getElementById("cgManualLabel").hidden = event.target.value !== "MANUAL_CHAT";
  const projectId = cgSelectedProjectId();
  if (projectId) {
    try {
      await api(`/api/projects/${encodeURIComponent(projectId)}/character-creation/preference`, {method:"PUT", body:{execution_mode:event.target.value}});
    } catch (error) {
      document.getElementById("cgProgress").textContent = plainAPIError(error, "Execution-mode preference could not be saved.");
    }
  }
});
document.getElementById("cgBuild")?.addEventListener("click", async () => {
  const projectId = cgSelectedProjectId();
  if (!projectId) return void (document.getElementById("cgProgress").textContent = "Select a project first.");
  const mode = document.getElementById("characterCreationMode").value;
  document.getElementById("cgProgress").textContent = mode === "MANUAL_CHAT" ? "Preparing request" : "Waiting for response";
  try {
    const run = await api(`/api/projects/${encodeURIComponent(projectId)}/character-creation/runs`, {method:"POST", body:{execution_mode:mode,idempotency_key:`owner.${Date.now()}`}});
    cgRender(run);
    if (mode === "MANUAL_CHAT") {
      const text = document.getElementById("cgManualResponse").value.trim();
      if (text) cgRender(await api(`/api/character-creation/runs/${encodeURIComponent(run.run_id)}/manual-response`, {method:"POST", body:{response_text:text,request_sha256:run.request.request_sha256}}));
    }
  } catch (error) { document.getElementById("cgProgress").textContent = plainAPIError(error, "Character build could not start."); }
});
document.getElementById("cgFinalize")?.addEventListener("click", async () => {
  if (!cgRun?.run_id || cgFinalizeInFlight) return;
  const button = document.getElementById("cgFinalize");
  cgFinalizeInFlight = true;
  if (button) button.disabled = true;
  try {
    cgRender(await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/finalize`, {method:"POST", body:{}}));
  } catch (error) {
    document.getElementById("cgProgress").textContent = plainAPIError(error, "Character could not be finalized.");
  } finally {
    cgFinalizeInFlight = false;
    if (button && cgRun?.status !== "CLEAN_AND_FINALIZED") {
      button.disabled = !cgIsClean(cgRun);
    }
  }
});
document.getElementById("cgRevise")?.addEventListener("click", async () => {
  try { cgRender(await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/revise`, {method:"POST", body:{owner_notes:document.getElementById("cgRevisionNotes").value}})); }
  catch (error) { document.getElementById("cgProgress").textContent = plainAPIError(error, "Revision request could not be prepared."); }
});
document.getElementById("cgCancel")?.addEventListener("click", async () => {
  try { cgRender(await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/cancel`, {method:"POST", body:{}})); }
  catch (error) { document.getElementById("cgProgress").textContent = plainAPIError(error, "Build run could not be cancelled."); }
});
document.getElementById("cgDownloadRequest")?.addEventListener("click", () => {
  if (cgRun?.run_id) window.location.assign(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/complete-request.zip`);
});
document.getElementById("cgDownloadCorrection")?.addEventListener("click", () => {
  if (cgRun?.run_id && cgRun.execution_mode === "MANUAL_CHAT" && cgRun.manual_ai_correction?.required === true) {
    window.location.assign(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/manual-ai-correction.zip`);
  }
});
document.getElementById("cgAutoOptIn")?.addEventListener("click", async () => {
  try {
    const finalized = await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/auto-finalize-opt-in`, {method:"POST", body:{}});
    cgRender(finalized);
    document.getElementById("cgProgress").textContent = `Auto-Finalize consent recorded and candidate ${finalized.dry_run.candidate_identity.slice(0, 12)} finalized.`;
  } catch (error) {
    document.getElementById("cgProgress").textContent = plainAPIError(error, "Auto-Finalize opt-in could not be recorded.");
  }
});

// ------------------------------------------------ Preferred gear (builder)
// The owner's preferred weapons and armour steer the starting kit: pinned
// kit menus when the kit offers them, Option B purchases otherwise.
async function loadGearPreferenceOptions() {
  const select = document.getElementById("guidedGear");
  if (!select || select.dataset.loaded === "true") return;
  try {
    const catalog = await api("/api/character-builder/gear-catalog");
    const groups = {weapon: "Weapons", armor: "Armour", shield: "Shields"};
    for (const [category, label] of Object.entries(groups)) {
      const group = document.createElement("optgroup");
      group.label = label;
      for (const item of (catalog.items || []).filter(row => row.category === category)) {
        const option = document.createElement("option");
        option.value = item.item_id;
        option.textContent = item.name;
        group.appendChild(option);
      }
      if (group.childElementCount) select.appendChild(group);
    }
    select.dataset.loaded = "true";
  } catch (error) {
    recordGuidedDiagnostic?.(error, "gear_catalog");
  }
}

function selectedGearPreferences() {
  const select = document.getElementById("guidedGear");
  return select ? Array.from(select.selectedOptions).map(option => option.value).slice(0, 6) : [];
}

document.addEventListener("DOMContentLoaded", () => { loadGearPreferenceOptions(); });
if (document.readyState !== "loading") loadGearPreferenceOptions();
