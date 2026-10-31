// Show the native setup transaction before ordinary turn controls.
export function renderFightSetup(bar, owners, menu, actorById, useGroup, busy) {
  const group = menu?.actions?.find(row => row.source_definition_id === "system:combat.fight_setup");
  if (!owners?.length || !group) return false;
  const doc = bar.ownerDocument;
  const panel = doc.createElement("div");
  panel.className = "tt-ab-who";
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", "Fight setup");
  const title = doc.createElement("strong");
  title.textContent = "Finish fight setup";
  const detail = doc.createElement("span");
  detail.textContent = `Before the first turn, finish setup for ${owners.map(id => actorById(id)?.display_name || "a fighter").join(", ")}.`;
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "tt-tool tt-primary";
  button.textContent = "Choose fight setup";
  button.disabled = !!busy;
  button.addEventListener("click", () => useGroup(group));
  panel.append(title, detail, button);
  bar.replaceChildren(panel);
  return true;
}
