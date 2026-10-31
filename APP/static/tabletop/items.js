// The sheet's Items tab (owner 2026-09-27: "we should have a tab for items and equipment"): everything the character
// owns with its weight, the load against its capacity (15 x Strength), and which items it brings to its next fights --
// untick one to leave it behind (worn armour stays on). In a fight, the table's Items panel drops and picks things up.

let deps = null;  // {h, $, fetchJson, toast, reloadSheet, projectId, sheet}
let preparationGeneration = 0;

export function initItems(options) {
  deps = options;
  deps.$("items-root").addEventListener("change", (event) => {
    if (event.target.matches("[data-bring]")) void save();
    if (event.target.matches("[data-attune]")) void saveAttunement();
  });
}

export function renderItems() {
  const { h, $ } = deps;
  const sheet = deps.sheet() || {};
  const equipment = sheet.equipment || { items: [] };
  const load = sheet.carrying || {};
  const attune = equipment.attunement || { used: 0, max: 4 };
  const root = $("items-root");
  const rows = equipment.items.map((item) => h("div", { class: `items-row${item.left_behind ? " is-left" : ""}` },
    h("label", { class: "items-bring", title: item.worn ? "Worn armour stays on." : "Bring it to fights (untick to leave it behind)" },
      h("input", { type: "checkbox", dataset: { bring: item.key }, checked: !item.left_behind || null, disabled: item.worn || null }),
      h("span", { class: "items-name" }, item.name, item.quantity > 1 ? ` ×${item.quantity}` : "", item.treasure ? h("span", { class: "badge badge-auto" }, "Treasure") : null,
        item.worn ? h("span", { class: "items-tag" }, "worn") : item.left_behind ? h("span", { class: "items-tag" }, "left behind") : null)),
    h("span", { class: "items-weight" }, `${item.weight_lb} lb`),
    // Attunement (owner 2026-09-28): a treasure that needs a slot works as its base item until attuned.
    item.attunement_slots
      ? h("label", { class: `items-attune${item.attuned ? " is-on" : ""}`, title: `Takes ${item.attunement_slots} attunement slot${item.attunement_slots > 1 ? "s" : ""}. Unattuned, a treasure weapon or armour fights as its base item (no +N, no enchantments).` },
          h("input", { type: "checkbox", dataset: { attune: item.key }, checked: item.attuned ? true : null,
                       disabled: !item.attuned && (attune.used + item.attunement_slots > attune.max) ? true : null }),
          ` Attuned${item.attunement_slots > 1 ? ` (${item.attunement_slots})` : ""}`)
      : h("span")));
  root.replaceChildren(
    h("div", { class: "def-block" },
      h("div", { class: `items-load${load.over ? " is-over" : ""}` },
        h("strong", null, `${load.weight_lb ?? "?"} / ${load.capacity_lb ?? "?"} lb`),
        h("span", null, load.over ? " — over capacity: Speed at most 5 ft in fights. Leave something behind." : " carried to fights"),
        h("span", { class: "items-attune-count", title: "Attunement slots in use" }, ` · Attuned ${attune.used} / ${attune.max}`)),
      h("p", { class: "def-note" }, "Untick an item to leave it behind: new fights start without it (its weight, and a weapon's attacks). In a fight, the table's Items button drops things (free) and picks them back up. Attuned: a character has four slots; a treasure that needs attunement gives its bonuses only while attuned.")),
    h("div", { class: "items-list" }, ...rows),
    equipment.armor_note ? h("p", { class: "def-note" }, equipment.armor_note) : null,
    (load.unweighed || []).length ? h("p", { class: "def-note" }, `Not weighed: ${load.unweighed.join(", ")}.`) : null,
    h("div", { id: "preparation-root", class: "def-block" }, "Loading between-fight preparation…"));
  void loadPreparation(++preparationGeneration);
}

async function loadPreparation(generation) {
  const pid = deps.projectId();
  try {
    const menu = await deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(pid)}/preparation`);
    if (generation !== preparationGeneration || pid !== deps.projectId()) return;
    renderPreparation(menu);
  } catch (error) {
    if (generation === preparationGeneration) deps.$("preparation-root")?.replaceChildren(
      deps.h("p", { class: "def-note" }, `Preparation unavailable: ${error.message}`));
  }
}

function renderPreparation(menu) {
  const {h, $} = deps;
  const armor = menu.state.armor || {};
  const buttons = menu.commands.map((command) => {
    const button = h("button", { type: "button", class: "btn" }, command.label);
    button.addEventListener("click", () => void submitPreparation(menu, command));
    return button;
  });
  $("preparation-root")?.replaceChildren(
    h("h3", null, "Between-fight preparation"),
    h("p", {class: "def-note"}, "Finish this character's active fight first. Choices apply to the next fight for every control mode. Time buttons record time actually spent fitting or resting."),
    menu.state.armor ? h("p", null, armor.ready ? "Fitted Armor is ready." : "Fitted Armor is not ready. Choose a suit, then spend its fitting time or complete a long rest.") : null,
    h("div", {class: "preparation-commands"}, ...buttons));
}

async function submitPreparation(menu, command) {
  const pid = deps.projectId();
  const generation = ++preparationGeneration;
  for (const button of deps.$("preparation-root").querySelectorAll("button")) button.disabled = true;
  try {
    const session = await deps.fetchJson("/api/session");
    const next = await deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(pid)}/preparation`, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Foundry-Token": session.token},
      body: JSON.stringify({...command, label: undefined, expected_revision: menu.state.revision}),
    });
    if (generation === preparationGeneration && pid === deps.projectId()) renderPreparation(next);
  } catch (error) {
    deps.toast("error", "Preparation not saved", error.message, 3600);
    if (generation === preparationGeneration) void loadPreparation(generation);
  }
}

async function save() {
  const keys = [...deps.$("items-root").querySelectorAll("[data-bring]")].filter((box) => !box.checked && !box.disabled).map((box) => box.dataset.bring);
  try {
    const session = await deps.fetchJson("/api/session");
    await deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/equipment`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: JSON.stringify({ left_behind: keys }),
    });
    await deps.reloadSheet();
    renderItems();
    deps.toast("ok", "Items saved", "New fights use them.", 2000);
  } catch (error) {
    deps.toast("error", "Not saved", error.message, 3600);
    renderItems();
  }
}

async function saveAttunement() {
  const keys = [...deps.$("items-root").querySelectorAll("[data-attune]")].filter((box) => box.checked).map((box) => box.dataset.attune);
  try {
    const session = await deps.fetchJson("/api/session");
    await deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/attunement`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: JSON.stringify({ attuned: keys }),
    });
    await deps.reloadSheet();
    renderItems();
    deps.toast("ok", "Attunement saved", "New fights use it.", 2000);
  } catch (error) {
    deps.toast("error", "Not saved", error.message, 3600);
    renderItems();
  }
}
