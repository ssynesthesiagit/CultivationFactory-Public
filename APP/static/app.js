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
let guidedCompleteResponseFile = null;
let ownerCharacterSheet = null;
let lastGMExport = null;
const sphereTalentLogic = globalThis.TianxiaSphereTalentLogic;
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

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  const bodyIsBinary = options.body instanceof Blob || options.body instanceof ArrayBuffer;
  if (options.body !== undefined && !bodyIsBinary && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (options.method && options.method !== "GET") headers["X-Foundry-Token"] = token;
  const response = await fetch(path, {...options, headers});
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; }
  catch (_error) { data = {error: {message: text || `Local service returned HTTP ${response.status}.`}}; }
  if (!response.ok) throw new Error(pretty(data));
  return data;
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach(x => x.classList.toggle("active", x.id === `screen-${name}`));
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle(
    "active",
    x.dataset.screen === name && (!x.dataset.builderMode || x.dataset.builderMode === creationMode)
  ));
}

document.querySelectorAll("nav button").forEach(btn => btn.addEventListener("click", async () => {
  if (btn.dataset.builderMode) await startNewCharacter(btn.dataset.builderMode);
  else showScreen(btn.dataset.screen);
}));

function setGuidedStep(step) {
  const panels = {
    1: document.getElementById("builderDescribe"),
    2: document.getElementById("builderAI"),
    3: document.getElementById("builderReview"),
    4: document.getElementById("builderDone")
  };
  Object.entries(panels).forEach(([number, panel]) => { panel.hidden = Number(number) !== step; });
  for (let number = 1; number <= 4; number += 1) {
    const marker = document.getElementById(`builderProgress${number}`);
    marker.classList.toggle("current", number === step);
    marker.classList.toggle("complete", number < step);
  }
  const active = panels[step];
  if (active) active.scrollIntoView({behavior: "smooth", block: "start"});
}

function setGuidedStatus(message, isError = false) {
  const status = document.getElementById("guidedStatus");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function resetGuidedBuilder() {
  guidedRun = null;
  guidedCompleteResponseFile = null;
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
  const submit = document.getElementById("guidedSubmitCompleteResponse");
  if (download) download.disabled = true;
  if (submit) submit.disabled = true;
  const consent = document.getElementById("guidedAutoFinalizeConsent");
  if (consent) consent.checked = false;
  const defaultMode = document.querySelector('input[name="guidedExecutionMode"][value="MANUAL_CHAT"]');
  if (defaultMode) defaultMode.checked = true;
  updateGuidedModeUI();
  setGuidedStatus("");
  setGuidedStep(1);
}

async function startNewCharacter(mode = "quick") {
  try {
    await discardGuidedTemporaryProject();
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The temporary character could not be discarded safely."), true);
    return;
  }
  selectedProject = null;
  guidedProjectId = null;
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
  try {
    const parsed = JSON.parse(error.message);
    return parsed?.error?.message || fallback;
  } catch (_ignored) {
    return error.message || fallback;
  }
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

function renderGuidedPersistence() {
  const panel = document.getElementById("guidedPersistencePanel");
  const label = document.getElementById("guidedPersistenceLabel");
  const explanation = document.getElementById("guidedPersistenceExplanation");
  const save = document.getElementById("guidedSaveDraft");
  if (!guidedProjectId || !guidedProjectLifecycle) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  label.textContent = guidedProjectLifecycle.display_label || "Saved / existing";
  explanation.textContent = guidedProjectLifecycle.plain_explanation || "This character is retained.";
  save.hidden = !guidedProjectLifecycle.is_temporary;
  save.disabled = !guidedProjectLifecycle.is_temporary;
}

async function discardGuidedTemporaryProject(reason = "owner_abandoned_or_started_over") {
  if (!guidedProjectId || !guidedProjectLifecycle?.is_temporary) return false;
  const projectId = guidedProjectId;
  await api(`/api/character-builder/projects/${encodeURIComponent(projectId)}/temporary`, {method: "DELETE"});
  if (selectedProject === projectId) selectedProject = null;
  guidedProjectId = null;
  guidedProjectLifecycle = null;
  renderGuidedPersistence();
  return true;
}

function setCreationMode(mode) {
  creationMode = mode === "detailed" ? "detailed" : "quick";
  const detailed = creationMode === "detailed";
  document.getElementById("characterSheetPanel").hidden = !detailed;
  for (const [id, active] of [["builderModeQuick", !detailed], ["builderModeDetailed", detailed]]) {
    const button = document.getElementById(id);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
  if (detailed) updatePointBuySummary();
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

function renderPathChoices() {
  const host = document.getElementById("sheetPaths");
  const category = categoryFor("path_choice");
  if (!host || !category) return;
  clearNode(host);
  const selected = selectedSet("path_choice");
  const maximum = Number(category.max || 3);
  for (const choice of category.choices || []) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = choice.choice_id;
    input.checked = selected.has(choice.choice_id);
    input.disabled = !input.checked && selected.size >= maximum;
    input.onchange = () => {
      if (input.checked) selected.add(choice.choice_id);
      else selected.delete(choice.choice_id);
      const currentMethod = methodChoiceFor();
      const required = selectedPathIds();
      if (currentMethod && !required.every(pathId => (currentMethod.related_choice_ids || []).includes(pathId))) {
        document.getElementById("sheetMethod").value = "";
        clearMethodAccessInputs();
        setGuidedStatus("The previous Method did not support every selected Path, so it was cleared.");
      }
      refreshMethodPathChoices({announce: true, preserve: true});
      evaluateGuidedReadiness();
    };
    label.append(input, document.createTextNode(choice.name));
    host.appendChild(label);
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
  const prior = select.value;
  const mode = methodPlanningMode();
  clearNode(select);
  const prompt = document.createElement("option");
  prompt.value = "";
  prompt.textContent = "Choose a Method";
  select.appendChild(prompt);
  const requiredPaths = selectedPathIds();
  const compatibleChoices = (category.choices || []).filter(choice =>
    requiredPaths.every(pathId => (choice.related_choice_ids || []).includes(pathId))
  );
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
  select.disabled = mode === "AUTO";
  const plan = methodChoiceFor()?.method_planning;
  const status = document.getElementById("sheetMethodAuthority");
  if (status) status.textContent = mode === "AUTO"
    ? "The Factory will choose a fitting Method."
    : !plan ? (requiredPaths.length && !compatibleChoices.length ? "No installed Method supports every selected Path." : "Choose a Method.")
      : mode === "PREFERENCE"
        ? "The Factory will treat this as a preference and may choose differently if the character needs it."
        : plan.exact_selection_available
          ? "The Factory will use this Method and keep its rules consistent."
          : (plan.owner_unavailable_reason || "This Method cannot be used during initial character creation.");
  populateMethodAccessPlan();
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
  host.textContent = `Category: ${authority.authority_type}. Requirements: ${authority.prerequisites || "None"}. ${authority.preference_only ? "This is a planning preference; it does not grant anything by itself." : ""}`;
}

function setMethodPathAuthorityNotice(message = "", isError = false) {
  const host = document.getElementById("sheetPathAuthorityNotice");
  if (!host) return;
  host.textContent = message;
  host.classList.toggle("error", isError);
}

function refreshMethodPathChoices({announce = false, preserve = true} = {}) {
  const subpathSelect = document.getElementById("sheetSubpath");
  if (!subpathSelect || !characterBuilderOptions) return;
  const previousPaths = selectedPathIds();
  const previousSubpath = subpathSelect.value;
  renderPathChoices();
  populateMethodPlanning();
  const compatibleCount = (categoryFor("method_choice")?.choices || []).filter(choice =>
    previousPaths.every(pathId => (choice.related_choice_ids || []).includes(pathId))
  ).length;
  setMethodPathAuthorityNotice(previousPaths.length
    ? `${compatibleCount} installed Method${compatibleCount === 1 ? "" : "s"} support every selected Path.`
    : "Choose one or more Paths; the Method list will show only compatible choices.", previousPaths.length > 0 && compatibleCount === 0);
  refreshPathSubpathChoices({announce, preferredValue: preserve ? previousSubpath : ""});
}

function refreshPathSubpathChoices({announce = false, preferredValue = null} = {}) {
  const subpathSelect = document.getElementById("sheetSubpath");
  if (!subpathSelect || !characterBuilderOptions) return;
  const oldValue = preferredValue === null ? subpathSelect.value : preferredValue;
  const pathIds = selectedPathIds();
  if (!pathIds.length) {
    clearNode(subpathSelect);
    const option = document.createElement("option"); option.value = ""; option.textContent = "Choose a Starting Path first.";
    subpathSelect.appendChild(option); subpathSelect.disabled = true;
    return;
  }
  const allowed = new Set(pathIds.flatMap(pathId => characterBuilderOptions.path_subpath_index?.[pathId] || []));
  const choices = (categoryFor("subpath_choice")?.choices || []).filter(choice => allowed.has(choice.choice_id));
  populateSheetSelect(subpathSelect, categoryFor("subpath_choice"), "Auto — let the Factory choose", choices);
  if (oldValue && allowed.has(oldValue)) subpathSelect.value = oldValue;
  else if (oldValue && announce) setGuidedStatus("The previous Subpath did not belong to the new Primary Path, so it was cleared.");
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
  const summary = document.createElement("summary"); summary.textContent = "Full description";
  const prose = document.createElement("p"); prose.textContent = talent.full_description || talent.description || "No full description is present in the authenticated source.";
  full.append(summary, prose);
  const state = document.createElement("small"); state.className = "talent-authority-state"; state.textContent = `${availability.status}: ${availability.reason}`;
  text.append(title, detail, meta, state, full);
  const controls = document.createElement("div"); controls.className = "talent-route-controls";
  const priorityButton = document.createElement("button"); priorityButton.type = "button"; priorityButton.className = "talent-toggle";
  priorityButton.textContent = selected ? "Remove Priority" : "Prioritize Talent";
  priorityButton.disabled = !availability.selectable;
  priorityButton.setAttribute("aria-pressed", selected ? "true" : "false");
  priorityButton.setAttribute("aria-label", `${selected ? "Remove priority" : "Prioritize"} ${talent.canonical_name || talent.name}${sphereContext ? ` for ${sphereContext}` : ""}`);
  priorityButton.title = availability.reason;
  priorityButton.onclick = () => toggleSheetTalent(talent.choice_id);
  controls.append(priorityButton);
  row.append(text, controls); host.appendChild(row);
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

  const sphereAdd = document.getElementById("sheetSphereAdd");
  if (sphereAdd && sphereCategory) {
    const unselected = sphereTalentLogic.uniqueChoices(sphereCategory.choices).filter(choice => !sphereIds.includes(choice.choice_id));
    populateSheetSelect(sphereAdd, sphereCategory, "Choose a Sphere priority", unselected);
    const available = unselected.filter(choice => choice.planning_priority_available !== false);
    sphereAdd.disabled = (categoryMaximum(sphereCategory) !== null && sphereIds.length >= categoryMaximum(sphereCategory)) || !available.length;
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
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${sphere.canonical_name || sphere.name}`);
      remove.onclick = () => removeSheetSphere(sphereId);
      const selectedForSphere = talentIds.filter(talentId => sphereTalentLogic.talentSphereIds(index, talentId).includes(sphereId));
      const associated = document.createElement("div");
      associated.className = "sphere-card-talents";
      const baseAbilities = sphere.automatic_base_abilities || [];
      associated.textContent = `Planning preference only — no Sphere acquisition or free grant. Talent priorities: ${selectedForSphere.length ? selectedTalentNames(selectedForSphere).join(", ") : "none"}.`;
      const grants = document.createElement("ul"); grants.className = "automatic-base-abilities";
      for (const ability of baseAbilities) {
        const item = document.createElement("li");
        item.dataset.baseAbilityId = ability.base_ability_id;
        item.textContent = `${ability.display_name} — Granted automatically; cannot be removed; costs 0 talent, advancement, or training slots.`;
        grants.appendChild(item);
      }
      card.append(activate, remove, associated, grants);
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
    const rows = sphereTalentLogic.talentIdsForSphere(index, activeSheetSphereId)
      .map(id => talentMap.get(id))
      .filter(Boolean)
      .filter(talent => !query || `${talent.canonical_name || talent.name} ${talent.description || ""}`.toLowerCase().includes(query));
    for (const talent of rows) appendTalentToggle(optionsHost, talent, selectedTalentSet.has(talent.choice_id), activeName);
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
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${talent ? (talent.canonical_name || talent.name) : (legacy?.name || talentId)}`);
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
    sphereHelp.textContent = `${audit.sphere_count || sphereCategory?.choices?.length || 0} canonical Spheres; ${unavailable} are not creator-ready because they have no legal free-talent authority. Prioritize up to ${categoryMaximum(sphereCategory) || 0}.`;
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
    for (const talentId of unassignedIds) {
      const talent = talentMap.get(talentId);
      if (!talent) continue;
      if (query && !`${talent.canonical_name || talent.name} ${talent.description || ""}`.toLowerCase().includes(query)) continue;
      appendTalentToggle(unassignedHost, talent, selectedTalentSet.has(talentId));
    }
  }
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
    label.textContent = choice.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${choice.name}`);
    remove.textContent = "×";
    remove.onclick = () => {
      selectedSet(slotId).delete(choiceId);
      renderChoiceChips(slotId);
    };
    chip.append(label, remove);
    host.appendChild(chip);
  }
}

function addSheetChoice(slotId) {
  const select = Array.from(document.querySelectorAll("[data-multi-slot]")).find(node => node.dataset.multiSlot === slotId);
  const category = categoryFor(slotId);
  if (!select || !category || !select.value) return;
  const values = selectedSet(slotId);
  const maximum = categoryMaximum(category);
  if (maximum !== null && values.size >= maximum) {
    setGuidedStatus(`This section can lock up to ${maximum} choices. Leave the rest on Auto.`, true);
    return;
  }
  const choice = choiceFor(slotId, select.value);
  if (slotId === "sphere_priorities" && choice?.planning_priority_available === false) {
    setGuidedStatus(`${choice.name} cannot be prioritized: ${choice.unavailable_reason || "not creator-ready"}`, true);
    select.focus();
    return;
  }
  values.add(select.value);
  if (slotId === "sphere_priorities") activeSheetSphereId = select.value;
  select.value = "";
  renderChoiceChips(slotId);
  setGuidedStatus("");
  evaluateGuidedReadiness();
}

function populateAbilitySelects() {
  const pointBuy = characterBuilderOptions?.point_buy;
  if (!pointBuy) return;
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
    select.onchange = updatePointBuySummary;
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
    if (select.value && (select.dataset.sheetSlot !== "method_choice" || methodPlanningMode() === "EXACT")) result[select.dataset.sheetSlot] = [select.value];
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
  setMethodPlanningMode("AUTO");
  if (insightFilter) insightFilter.value = "";
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
    select.value = values[0] || "";
  }
  sheetSelectedChoices.set("path_choice", new Set(locked.path_choice || []));
  if (planning.method_preference_id) document.getElementById("sheetMethod").value = planning.method_preference_id;
  if (planning.method_exact_choice_id) document.getElementById("sheetMethod").value = planning.method_exact_choice_id;
  populateMethodPlanning();
  const savedMethodPlan = locks["character_sheet.method_access_plan"] || {};
  const savedRoute = methodChoiceFor()?.method_planning?.owner_route_options?.find(option => option.description === savedMethodPlan.route_type);
  if (savedRoute) document.getElementById("sheetMethodRouteChoice").value = savedRoute.choice_id;
  const learningNote = document.getElementById("sheetMethodLearningNote");
  if (learningNote) learningNote.value = savedMethodPlan.owner_annotation || "";
  refreshMethodPathChoices({preserve: true});
  refreshPathSubpathChoices({preferredValue: (locked.subpath_choice || [])[0] || ""});
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
  updatePointBuySummary();
}

async function loadCharacterBuilderOptions() {
  const status = document.getElementById("sheetOptionsStatus");
  try {
    characterBuilderOptions = await api("/api/character-builder/options");
    populateAbilitySelects();
    for (const select of document.querySelectorAll("[data-sheet-slot]")) {
      populateSheetSelect(select, categoryFor(select.dataset.sheetSlot));
    }
    populateMethodPlanning();
    document.getElementById("sheetMethod").onchange = () => { clearMethodAccessInputs(); populateMethodPlanning(); evaluateGuidedReadiness(); };
    for (const option of document.querySelectorAll('input[name="sheetMethodMode"]')) option.onchange = () => { clearMethodAccessInputs(); populateMethodPlanning(); refreshMethodPathChoices({announce: true, preserve: true}); evaluateGuidedReadiness(); };
    document.getElementById("sheetMethodRouteChoice").onchange = evaluateGuidedReadiness;
    document.getElementById("guidedLevel").addEventListener("change", () => {
      renderSphereTalentWorkspace();
      evaluateGuidedReadiness();
    });
    refreshMethodPathChoices();
    refreshBackgroundChoiceLinks();
    document.getElementById("sheetBackground").onchange = () => { refreshBackgroundChoiceLinks({backgroundChanged: true}); evaluateGuidedReadiness(); };
    document.getElementById("sheetBackgroundSphere").onchange = () => { refreshBackgroundChoiceLinks({sphereChanged: true}); evaluateGuidedReadiness(); };
    document.getElementById("sheetBackgroundTalent").onchange = evaluateGuidedReadiness;
    document.getElementById("sheetOriginInsight").onchange = evaluateGuidedReadiness;
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
    document.getElementById("sheetInsightAuthorityFilter").onchange = event => {
      const category = categoryFor("insight_priorities");
      const authorityType = event.target.value;
      const filtered = (category?.choices || []).filter(choice => !authorityType || choice.insight_authority?.authority_type === authorityType);
      populateSheetSelect(document.getElementById("sheetInsightAdd"), category, "Choose an Insight preference", filtered);
      renderInsightAuthorityDetail();
    };
    document.getElementById("sheetInsightAdd").onchange = renderInsightAuthorityDetail;
    document.getElementById("sheetTalentSearch").oninput = renderSphereTalentWorkspace;
    document.getElementById("sheetUnassignedTalentSearch").oninput = renderSphereTalentWorkspace;
    renderSphereTalentWorkspace();
    const blocked = characterBuilderOptions.categories.filter(category => category.status !== "offered").map(category => category.label);
    const counts = characterBuilderOptions.owner_surface_counts || {};
    status.textContent = `${counts.canonical_spheres || 0} canonical Spheres, ${counts.canonical_talents || 0} canonical Talents, and ${counts.automatic_base_components || 0} automatic base components loaded. ${counts.zero_talent_spheres || 0} zero-talent Spheres are explicitly unavailable in character creation; ${counts.quarantined_records || 0} quarantined records remain unchanged.${blocked.length ? ` Auto remains required for: ${blocked.join(", ")}.` : ""}`;
    updatePointBuySummary();
    evaluateGuidedReadiness();
  } catch (error) {
    characterBuilderOptions = null;
    status.textContent = plainAPIError(error, "The Factory could not load the character-sheet choices.");
    status.classList.add("error");
  }
}

document.getElementById("builderModeQuick").onclick = () => setCreationMode("quick");
document.getElementById("builderModeDetailed").onclick = () => setCreationMode("detailed");
for (const id of ["guidedName", "guidedConcept", "guidedLevel", "guidedPower", "guidedSource"]) {
  document.getElementById(id)?.addEventListener("input", evaluateGuidedReadiness);
  document.getElementById(id)?.addEventListener("change", evaluateGuidedReadiness);
}
document.querySelectorAll("[data-add-slot]").forEach(button => {
  button.addEventListener("click", () => addSheetChoice(button.dataset.addSlot));
});

async function resumeGuidedDraft(projectRows) {
  let resumeStage = "finding the saved draft";
  try {
  const rows = Array.isArray(projectRows) ? projectRows : [];
  const candidate = rows.find(row => row.status === "draft" && row.revision === 0 && row.builder_persistence_state !== "temporary");
  if (!candidate) return;
  resumeStage = "reading the saved project";
  const detail = await api(`/api/projects/${encodeURIComponent(candidate.project_id)}`);
  resumeStage = "reading the saved character fields";
  const locks = Object.fromEntries((detail.project.user_locks || []).map(lock => [lock.field, lock.value]));
  const owns = key => Object.prototype.hasOwnProperty.call(locks, key);
  if (!owns("concept") || !owns("target_cl") || !owns("power_band")) return;

  resumeStage = "restoring the saved character fields";
  selectedProject = candidate.project_id;
  guidedProjectId = candidate.project_id;
  guidedProjectLifecycle = detail.builder_lifecycle || candidate.builder_lifecycle || {persistence_state: "legacy_persistent", is_temporary: false, display_label: "Saved / existing", plain_explanation: "This existing character is retained."};
  renderGuidedPersistence();
  document.getElementById("guidedName").value = candidate.working_name;
  document.getElementById("guidedConcept").value = String(locks.concept || "");
  document.getElementById("guidedSource").value = locks.source_reference === "Original character" ? "" : String(locks.source_reference || "");
  document.getElementById("guidedLevel").value = String(locks.target_cl);
  document.getElementById("guidedPower").value = String(locks.power_band);
  restoreCharacterSheet(locks);
  resumeStage = "opening complete-character build mode";
  const preference = await api(`/api/projects/${encodeURIComponent(selectedProject)}/character-creation/preference`);
  const preferredMode = document.querySelector(`input[name="guidedExecutionMode"][value="${preference.execution_mode || "MANUAL_CHAT"}"]`);
  if (preferredMode) preferredMode.checked = true;
  updateGuidedModeUI();
  setGuidedStatus(`Resumed ${candidate.working_name}. Choose a complete-character build mode.`);
  setGuidedStep(2);
  } catch (error) {
    const detail = error && error.message ? error.message : String(error);
    throw new Error(`${resumeStage}: ${detail.slice(0, 300)}`);
  }
}

document.getElementById("guidedCreate").addEventListener("submit", async event => {
  event.preventDefault();
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
        method_learning_note: detailed && methodPlanningMode() === "EXACT" ? (document.getElementById("sheetMethodLearningNote")?.value.trim() || null) : null
      })
    });
    selectedProject = created.project_id;
    guidedProjectId = created.project_id;
    guidedProjectLifecycle = created.builder_lifecycle || {persistence_state: "temporary", is_temporary: true, display_label: "Temporary", plain_explanation: "Disappears if abandoned or the Factory closes before you save it."};
    renderGuidedPersistence();
    await loadProjects();
    const lockedCount = Object.values(created.character_sheet?.locked_choices || {}).reduce((total, values) => total + (Array.isArray(values) ? values.length : 0), 0)
      + (created.character_sheet?.method_planning_mode === "EXACT" ? 1 : 0);
    const planning = created.character_sheet?.planning_preferences || {};
    const preferenceCount = (planning.sphere_priority_ids || []).length + (planning.talent_priority_ids || []).length
      + (planning.method_preference_id ? 1 : 0);
    setGuidedStatus(`${name} is temporary and ready. ${lockedCount} exact ${lockedCount === 1 ? "choice" : "choices"}; ${preferenceCount} planning ${preferenceCount === 1 ? "preference" : "preferences"}. Choose a complete-character build mode.`);
    setGuidedStep(2);
    updateGuidedModeUI();
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The Factory could not start this character. Send me a screenshot and I will fix it."), true);
  } finally {
    if (submit) submit.disabled = false;
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

function guidedExecutionMode() {
  return document.querySelector('input[name="guidedExecutionMode"]:checked')?.value || "MANUAL_CHAT";
}

function updateGuidedModeUI() {
  const mode = guidedExecutionMode();
  const consentPanel = document.getElementById("guidedAutoConsentPanel");
  const manual = document.getElementById("guidedManualTransfer");
  if (consentPanel) consentPanel.hidden = mode !== "AUTO_FINALIZE_WHEN_CLEAN";
  if (manual && !guidedRun) manual.hidden = true;
  const start = document.getElementById("guidedStartBuild");
  if (start) start.textContent = mode === "MANUAL_CHAT" ? "Prepare Complete Request" : "Build Character";
}

function evaluateGuidedReadiness() {
  const blockers = [];
  const name = document.getElementById("guidedName")?.value.trim() || "";
  const concept = document.getElementById("guidedConcept")?.value.trim() || "";
  const level = Number(document.getElementById("guidedLevel")?.value || 0);
  if (!characterBuilderOptions) blockers.push({fieldId: "guidedName", message: "Installed character choices are still loading."});
  if (!name) blockers.push({fieldId: "guidedName", message: "Enter a character name."});
  if (!concept) blockers.push({fieldId: "guidedConcept", message: "Describe the character concept."});
  if (!Number.isInteger(level) || level < 1 || level > 20) blockers.push({fieldId: "guidedLevel", message: "Intended level must be from 1 through 20."});
  if (creationMode === "detailed" && characterBuilderOptions) {
    const selectedMethod = methodPlanningMode() === "EXACT" ? methodChoiceFor() : null;
    if (methodPlanningMode() !== "AUTO" && !methodChoiceFor()) blockers.push({fieldId: "sheetMethod", message: "Choose a Method or choose for me."});
    if (selectedMethod && !selectedMethod.method_planning?.direct_initial_acquisition_available) {
      if (!methodRouteChoiceForSubmission()) blockers.push({fieldId: "sheetMethodRouteChoice", message: "Choose how this character learned the selected Method."});
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
  const button = document.getElementById("guidedBuildButton");
  if (button) button.disabled = !valid;
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

function renderGuidedCandidate(run) {
  guidedRun = run;
  const progress = document.getElementById("guidedBuildProgress");
  if (progress) progress.textContent = pretty({status: run.status, quality: run.quality, blockers: run.blockers, warnings: run.warnings, independent_compilations: run.dry_run?.independent_compilations, candidate_identity: run.dry_run?.candidate_identity});
  const reviewable = ["READY_FOR_REVIEW", "NEEDS_REVIEW"].includes(run.status);
  const commitPresent = hasSubstantiveCommit(run.commit);
  const clean = reviewable && run.quality?.status === "CLEAN" && !(run.blockers || []).length && !commitPresent;
  const finalized = run.status === "CLEAN_AND_FINALIZED" && commitPresent;
  if (finalized) {
    renderGuidedFinal(run);
    setGuidedStep(4);
    return;
  }
  if (run.status === "CLEAN_AND_FINALIZED" && !commitPresent) {
    setGuidedStatus("Finalized status was returned without a substantive canonical commit receipt. No finalized result can be displayed.", true);
    return;
  }
  if (!reviewable) return;
  const preview = run.dry_run?.preview || {};
  const compiled = preview.compiled || {};
  const identity = preview.identity?.identity || preview.identity || findNestedObject(compiled.character_sheet, "identity") || {};
  const sphereSurface = findNestedObject(compiled.character_sheet, "spheres_and_talents") || {};
  const host = document.getElementById("guidedCandidateSummary");
  clearNode(host);
  appendCandidateLine(host, "Character", identity.name || identity.display_name || document.getElementById("guidedName").value || "Unnamed character");
  appendCandidateLine(host, "Target CL", String(preview.target_cl ?? document.getElementById("guidedLevel").value));
  appendCandidateLine(host, "Two isolated builds", run.dry_run?.independent_compilations === 2 && run.dry_run?.deterministic ? "PASS — deterministic identities match" : "Not verified", run.dry_run?.deterministic ? "success" : "error");
  appendCandidateLine(host, "Canonical mutation before Finalize", commitPresent ? "Unexpected commit present" : "None", commitPresent ? "error" : "success");
  appendCandidateLine(host, "Quality gate", `${run.quality?.status || "Unknown"}${(run.warnings || []).length ? ` — ${(run.warnings || []).length} warning(s)` : ""}`, clean ? "success" : "warning");
  const acquiredSpheres = candidateList(sphereSurface.acquired_spheres || sphereSurface.spheres || sphereSurface.canonical_spheres);
  const freeTalents = candidateList(sphereSurface.free_sphere_talent_grants || sphereSurface.free_talents || sphereSurface.free_grants);
  const automatic = candidateList(sphereSurface.automatic_base_abilities || sphereSurface.base_sphere_abilities || sphereSurface.automatic_grants);
  const ordinary = candidateList(sphereSurface.ordinary_talents || sphereSurface.learned_talents || sphereSurface.acquired_talents);
  appendCandidateLine(host, "Acquired Spheres", acquiredSpheres.length ? acquiredSpheres.join("; ") : "See complete candidate evidence below");
  appendCandidateLine(host, "One free talent per acquired Sphere", freeTalents.length ? freeTalents.join("; ") : "See complete candidate evidence below");
  appendCandidateLine(host, "Automatic base abilities", automatic.length ? automatic.join("; ") : "None projected or see evidence below");
  appendCandidateLine(host, "Ordinary acquired talents", ordinary.length ? ordinary.join("; ") : "None projected or see evidence below");
  if ((run.blockers || []).length) appendCandidateLine(host, "Exact blockers", run.blockers.map(row => `${row.code}: ${row.message}`).join(" | "), "error");
  document.getElementById("guidedReviewDetail").textContent = pretty(run);
  document.getElementById("guidedFinalize").disabled = !clean;
  setGuidedStatus(clean ? "Complete candidate is clean and has not been committed. Review once, then Finalize, Revise, or Cancel." : "The complete candidate needs review. No canonical mutation occurred.", !clean);
  setGuidedStep(3);
}

function renderGuidedFinal(run) {
  const host = document.getElementById("guidedFinalSummary");
  clearNode(host);
  appendCandidateLine(host, "Status", "Clean and finalized", "success");
  appendCandidateLine(host, "Canonical commit", pretty(run.commit), "success");
  appendCandidateLine(host, "Approved candidate identity", run.commit?.approved_candidate_identity || run.dry_run?.candidate_identity || "Recorded");
  appendCandidateLine(host, "Approval authority", "Server-derived local principal");
  appendCandidateLine(host, "Portable Character", run.outputs?.portable_character ? "Produced and verified" : "See final output evidence");
  appendCandidateLine(host, "GM output", run.outputs?.gm_model || run.outputs?.gm_consumer ? "Produced and verified" : "See final output evidence");
  setGuidedStatus("Character finalized. The normal character and GM output surfaces are ready.");
}

async function startGuidedCompleteBuild() {
  if (!guidedProjectId) return void setGuidedStatus("Describe and continue the character first.", true);
  const mode = guidedExecutionMode();
  if (mode === "AUTO_FINALIZE_WHEN_CLEAN" && !document.getElementById("guidedAutoFinalizeConsent").checked) {
    document.getElementById("guidedAutoFinalizeConsent").focus();
    return void setGuidedStatus("Auto-Finalize is off by default. Check the explicit one-build consent box or choose another mode.", true);
  }
  document.getElementById("guidedStartBuild").disabled = true;
  const fallbackWarning = document.getElementById("guidedProviderFallbackWarning");
  if (fallbackWarning) {
    fallbackWarning.hidden = true;
    fallbackWarning.textContent = "";
  }
  setGuidedStatus(mode === "MANUAL_CHAT" ? "Preparing the complete CG1 request ZIP…" : "Building the complete candidate through the accepted shared pipeline…");
  try {
    guidedRun = await api(`/api/projects/${encodeURIComponent(guidedProjectId)}/character-creation/runs`, {method: "POST", body: JSON.stringify({execution_mode: mode, idempotency_key: `primary.${Date.now()}.${crypto.randomUUID()}`})});
    const returnedMode = document.querySelector(`input[name="guidedExecutionMode"][value="${guidedRun.execution_mode}"]`);
    if (returnedMode) {
      returnedMode.checked = true;
      updateGuidedModeUI();
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
      document.getElementById("guidedSubmitCompleteResponse").disabled = false;
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
    if (mode === "AUTO_FINALIZE_WHEN_CLEAN" && guidedRun.status === "READY_FOR_REVIEW" && guidedRun.quality?.status === "CLEAN" && !(guidedRun.blockers || []).length && !hasSubstantiveCommit(guidedRun.commit)) {
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/auto-finalize-opt-in`, {method: "POST", body: "{}"});
      renderGuidedCandidate(guidedRun);
    }
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The complete-character build could not start."), true);
  } finally {
    document.getElementById("guidedStartBuild").disabled = false;
  }
}

document.querySelectorAll('input[name="guidedExecutionMode"]').forEach(input => input.addEventListener("change", updateGuidedModeUI));
async function loadGuidedProviderStatus() {
  const host = document.getElementById("guidedProviderStatus");
  try {
    const status = await api("/api/ai-provider");
    const settings = status.settings || {};
    document.getElementById("guidedProviderEndpoint").value = settings.endpoint || "https://api.deepseek.com/chat/completions";
    document.getElementById("guidedProviderModel").value = settings.model || "deepseek-v4-flash";
    document.getElementById("guidedProviderEnabled").checked = !!settings.enabled;
    document.getElementById("guidedProviderAcknowledged").checked = !!settings.data_sharing_acknowledged;
    document.getElementById("guidedProviderActor").value = settings.acknowledged_by || "";
    host.textContent = `DeepSeek ${status.ready ? "ready" : "not ready"}; key ${status.secret?.present ? "stored" : "not stored"}; Manual Chat remains available without a key.`;
    return status;
  } catch (error) { host.textContent = plainAPIError(error, "Provider status could not be loaded."); return null; }
}
document.getElementById("guidedProviderSave").onclick = async () => {
  const host = document.getElementById("guidedProviderStatus");
  try {
    await api("/api/ai-provider/configure", {method: "POST", body: JSON.stringify({
      enabled: document.getElementById("guidedProviderEnabled").checked,
      model: document.getElementById("guidedProviderModel").value.trim(),
      thinking_mode: "disabled", max_output_tokens: 16384, timeout_seconds: 120,
      data_sharing_acknowledged: document.getElementById("guidedProviderAcknowledged").checked,
      acknowledged_by: document.getElementById("guidedProviderActor").value.trim() || null,
    })});
    await loadGuidedProviderStatus();
  } catch (error) { host.textContent = plainAPIError(error, "DeepSeek settings were not saved."); }
};
document.getElementById("guidedProviderSaveKey").onclick = async () => {
  const input = document.getElementById("guidedProviderKey");
  try { await api("/api/ai-provider/key", {method: "POST", body: JSON.stringify({api_key: input.value})}); input.value = ""; await loadGuidedProviderStatus(); }
  catch (error) { input.value = ""; document.getElementById("guidedProviderStatus").textContent = plainAPIError(error, "The DeepSeek key was not saved."); }
};
document.getElementById("guidedProviderDeleteKey").onclick = async () => {
  try { await api("/api/ai-provider/key", {method: "DELETE"}); document.getElementById("guidedProviderKey").value = ""; await loadGuidedProviderStatus(); }
  catch (error) { document.getElementById("guidedProviderStatus").textContent = plainAPIError(error, "The DeepSeek key was not deleted."); }
};
document.getElementById("guidedProviderTest").onclick = async () => {
  const host = document.getElementById("guidedProviderStatus");
  host.textContent = "Testing the configured DeepSeek connection once…";
  try { const result = await api("/api/ai-provider/test", {method: "POST", body: "{}"}); host.textContent = `Connection ${result.status}; model ${result.model}; no secret was returned.`; }
  catch (error) { host.textContent = plainAPIError(error, "DeepSeek connection test failed."); }
};
loadGuidedProviderStatus();
document.getElementById("guidedStartBuild").onclick = startGuidedCompleteBuild;
document.getElementById("guidedDownloadCompleteRequest").onclick = window.TianxiaCompleteRequestSave.createController({
  getRunId: () => guidedRun?.run_id,
  getNativeSave: () => window.pywebview?.api?.save_complete_request,
  button: document.getElementById("guidedDownloadCompleteRequest"),
  status: document.getElementById("guidedDownloadCompleteRequestStatus"),
  navigate: url => window.location.assign(url),
});

async function loadGuidedCompleteResponse(file) {
  if (!file) return;
  guidedCompleteResponseFile = file;
  document.getElementById("guidedCompleteReplyStatus").textContent = `${file.name} selected. Build Complete Candidate will bind it to the exact request and run both scratch builds.`;
}
const completeReplyFile = document.getElementById("guidedCompleteReplyFile");
document.getElementById("guidedChooseCompleteReply").onclick = event => { event.stopPropagation(); completeReplyFile.click(); };
completeReplyFile.onchange = async () => { await loadGuidedCompleteResponse(completeReplyFile.files[0]); completeReplyFile.value = ""; };
const completeDrop = document.getElementById("guidedCompleteReplyDrop");
completeDrop.onclick = event => { if (event.target.id !== "guidedChooseCompleteReply") completeReplyFile.click(); };
completeDrop.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); completeReplyFile.click(); } };
for (const type of ["dragenter", "dragover"]) completeDrop.addEventListener(type, event => { event.preventDefault(); completeDrop.classList.add("active"); });
for (const type of ["dragleave", "drop"]) completeDrop.addEventListener(type, event => { event.preventDefault(); completeDrop.classList.remove("active"); });
completeDrop.addEventListener("drop", async event => { await loadGuidedCompleteResponse(event.dataTransfer.files[0]); });

document.getElementById("guidedSubmitCompleteResponse").onclick = async () => {
  if (!guidedRun?.run_id) return void setGuidedStatus("Prepare the complete request first.", true);
  const pasted = document.getElementById("guidedCompleteResponseText").value.trim();
  if (!guidedCompleteResponseFile && !pasted) return void setGuidedStatus("Choose one complete response ZIP/JSON or paste the complete response JSON.", true);
  setGuidedStatus("Validating the response and running two isolated complete-character builds…");
  try {
    if (guidedCompleteResponseFile) {
      const response = await fetch(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/manual-response-file?filename=${encodeURIComponent(guidedCompleteResponseFile.name)}`, {method: "POST", headers: {"X-Foundry-Token": token, "Content-Type": "application/octet-stream"}, body: await guidedCompleteResponseFile.arrayBuffer()});
      const data = await response.json();
      if (!response.ok) throw new Error(pretty(data));
      guidedRun = data;
    } else {
      guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/manual-response`, {method: "POST", body: JSON.stringify({response_text: pasted, request_sha256: guidedRun.request.request_sha256})});
    }
    renderGuidedCandidate(guidedRun);
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The complete response could not be compiled."), true);
  }
};

document.getElementById("guidedFinalize").onclick = async () => {
  if (!guidedRun?.run_id) return;
  setGuidedStatus("Finalizing through the accepted atomic pipeline…");
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/finalize`, {method: "POST", body: "{}"});
    guidedProjectLifecycle = await api(`/api/character-builder/projects/${encodeURIComponent(guidedProjectId)}/lifecycle`);
    renderGuidedPersistence();
    await loadProjects();
    renderGuidedCandidate(guidedRun);
  } catch (error) {
    setGuidedStatus(plainAPIError(error, "The character could not be finalized."), true);
  }
};

document.getElementById("guidedRevise").onclick = async () => {
  if (!guidedRun?.run_id) return;
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/revise`, {method: "POST", body: JSON.stringify({owner_notes: document.getElementById("guidedRevisionNotes").value})});
    document.getElementById("guidedCompleteResponseText").value = "";
    guidedCompleteResponseFile = null;
    setGuidedStep(2);
    document.querySelector('input[name="guidedExecutionMode"][value="MANUAL_CHAT"]').checked = true;
    updateGuidedModeUI();
    document.getElementById("guidedManualTransfer").hidden = false;
    document.getElementById("guidedDownloadCompleteRequest").disabled = false;
    document.getElementById("guidedSubmitCompleteResponse").disabled = false;
    setGuidedStatus("Revision request prepared. Download the new complete request ZIP and submit one corrected complete response.");
  } catch (error) { setGuidedStatus(plainAPIError(error, "A revision request could not be prepared."), true); }
};

document.getElementById("guidedCancel").onclick = async () => {
  if (!guidedRun?.run_id) return;
  try {
    guidedRun = await api(`/api/character-creation/runs/${encodeURIComponent(guidedRun.run_id)}/cancel`, {method: "POST", body: "{}"});
    document.getElementById("guidedBuildProgress").textContent = pretty(guidedRun);
    setGuidedStatus("Build cancelled. No canonical character changes were committed.");
    setGuidedStep(2);
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

async function loadCatalog(event) {
  if (event) event.preventDefault();
  setScreenState("catalogScreenState", "loading", "Loading installed core rules…");
  try {
    const params = new URLSearchParams();
    const q = document.getElementById("catalogQuery").value.trim();
    const type = document.getElementById("catalogType").value.trim();
    const authority = document.getElementById("catalogAuthority").value;
    if (q) params.set("q", q); if (type) params.set("content_type", type); if (authority) params.set("authority", authority);
    if (document.getElementById("includeTest").checked) params.set("include_test", "true");
    const data = await api(`/api/catalog/records?${params}`);
    const body = document.getElementById("catalogRows"); clearNode(body);
    for (const row of (data.records || [])) {
      const tr = document.createElement("tr");
      appendTextCell(tr, row.record_id, true); appendTextCell(tr, row.display_name); appendTextCell(tr, row.content_type); appendTextCell(tr, row.authority);
      tr.onclick = async () => {
        try { document.getElementById("catalogDetail").textContent = pretty(await api(`/api/catalog/records/${encodeURIComponent(row.record_id)}?all_versions=true`)); }
        catch (error) { document.getElementById("catalogDetail").textContent = plainAPIError(error, "That rule could not be opened."); }
      };
      body.appendChild(tr);
    }
    if (!(data.records || []).length) setScreenState("catalogScreenState", "empty", q || type || authority ? "No installed rules match this search." : "Core rules are not initialized or no records are installed. Use Refresh after first-run initialization completes.", loadCatalog);
    else setScreenState("catalogScreenState", "loaded", `${data.records.length} rules loaded.`);
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
document.getElementById("refreshAll").onclick = async () => { await Promise.allSettled([loadStatus(), loadCatalog(), loadPacks(), loadProjects()]); };

let stage1PromptData = null;
let stage1Attempt = null;
let aiProviderStatus = null;

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
  document.getElementById("aiProviderStatus").textContent = pretty(aiProviderStatus);
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

async function loadNonSphereAuthorityPanel() {
  const statusNode = document.getElementById("nonSphereAuthorityStatus");
  const technical = document.getElementById("nonSphereTechnical");
  if (!statusNode || !technical) return;
  try {
    if (!nonSphereCatalogCache) {
      const [status, paths, foundations] = await Promise.all([
        api("/api/non-sphere/authority/status"), api("/api/non-sphere/paths"), api("/api/non-sphere/foundations")
      ]);
      nonSphereCatalogCache = {status, paths, foundations};
    }
    const {status, paths, foundations} = nonSphereCatalogCache;
    statusNode.textContent = `${friendlyLabel(status.status)} · ${status.method_count} Methods · ${status.orthodox_foundation_count} orthodox Foundations · ${status.operative_pairwise_authority_rows} operative pairwise rows`;
    if (!selectedProject) {
      document.getElementById("setNonSpherePrimaryMethod").disabled = true;
      document.getElementById("setNonSphereFoundation").disabled = true;
      document.getElementById("nonSpherePathTracks").innerHTML = "<p>Select a character to inspect its persistent Path tracks.</p>";
      technical.textContent = pretty(status); return;
    }
    const [state, methods, readiness, apEligibility, evidenceLedger, ...subpathCatalogs] = await Promise.all([
      api(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/state`),
      api(`/api/non-sphere/methods?project_id=${encodeURIComponent(selectedProject)}`),
      api(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/readiness`),
      api(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/ap-eligibility`),
      api(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/evidence`),
      ...paths.records.map(row => api(`/api/non-sphere/subpaths?path_id=${encodeURIComponent(row.path_id)}`))
    ]);
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
      setResource.onclick = () => updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/resource`, {path_id: path.path_id, current: current.value === "" ? null : Number(current.value), maximum: maximum.value === "" ? null : Number(maximum.value)});
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
      setSubpath.onclick = () => { if (subSelect.value) updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/subpath`, {path_id: path.path_id, selection_id: subSelect.value, evidence_ids: readNonSphereEvidence()}); };
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
        updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/advancement`, {
          allocations, evidence_id: source.value, idempotency_key: crypto.randomUUID()
        });
      };
      advanceHost.appendChild(button);
    } else {
      advanceHost.textContent = apEligibility.blocker?.message || "Choose an acquired Primary Method before allocating AP.";
    }

    const readyNode = document.getElementById("nonSphereReadiness");
    const ready = Boolean(readiness.ready);
    readyNode.className = `non-sphere-readiness ${ready ? "ready" : "blocked"}`;
    readyNode.textContent = ready ? "Non-Sphere authority is ready for this character." : `Blocked: ${(readiness.blockers || []).map(row => row.message || row.code).join(" · ") || "cultivation selections remain incomplete"}`;
    technical.textContent = pretty({state, readiness, ap_eligibility: apEligibility, authority: status});
  } catch (error) {
    statusNode.textContent = plainAPIError(error, "Non-Sphere authority could not be loaded.");
    technical.textContent = statusNode.textContent;
  }
}

async function updateNonSphere(url, body) {
  const technical = document.getElementById("nonSphereTechnical");
  try {
    technical.textContent = "Saving canonical cultivation state…";
    const result = await api(url, {method: "POST", body: JSON.stringify(body)});
    technical.textContent = pretty(result);
    await loadNonSphereAuthorityPanel();
    if (selectedProject) await openOwnerCharacterSheet(selectedProject, false);
  } catch (error) { technical.textContent = plainAPIError(error, "Cultivation state was not changed."); }
}

function renderOwnerSheet(sheet) {
  ownerCharacterSheet = sheet; selectedProject = sheet.project_id; lastGMExport = null;
  const host = document.getElementById("ownerCharacterSheet"); clearNode(host);
  const header = document.createElement("header"); header.className = "owner-sheet-header";
  const titleWrap = document.createElement("div"); const kicker = document.createElement("p"); kicker.className = "sheet-kicker"; kicker.textContent = friendlyLabel(sheet.build_status);
  const title = document.createElement("h3"); title.textContent = sheet.name || "Unnamed character";
  const summary = document.createElement("p"); summary.textContent = sheet.plain_summary;
  titleWrap.append(kicker, title, summary);
  const lifecycle = document.createElement("span"); lifecycle.className = "character-state-pill"; lifecycle.textContent = sheet.lifecycle.display_label || "Saved / existing";
  header.append(titleWrap, lifecycle); host.appendChild(header);
  const identity = document.createElement("section"); identity.className = "owner-sheet-section identity-sheet-section";
  const ih = document.createElement("h4"); ih.textContent = "Identity and cultivation"; identity.appendChild(ih); appendReadableValue(identity, sheet.identity); host.appendChild(identity);
  const provenance = document.createElement("div"); provenance.className = "provenance-strip";
  for (const item of [sheet.provenance.owner_locks, sheet.provenance.ai_blueprint, sheet.provenance.advancement_projection, sheet.provenance.character_sheet_projection]) { if (!item) continue; const badge = document.createElement("div"); badge.className = `provenance-badge ${item.status}`; const strong = document.createElement("strong"); strong.textContent = item.label; const small = document.createElement("small"); small.textContent = item.status === "not_compiled" ? "Not compiled yet" : friendlyLabel(item.status); badge.append(strong, small); provenance.appendChild(badge); }
  host.appendChild(provenance);
  const sections = document.createElement("div"); sections.className = "owner-sheet-sections";
  for (const [name, section] of Object.entries(sheet.sections || {})) { const card = document.createElement("section"); card.className = `owner-sheet-section ${section.status}`; const h = document.createElement("h4"); h.textContent = friendlyLabel(name); const state = document.createElement("span"); state.className = "section-state"; state.textContent = section.label; card.append(h, state); if (section.data) appendReadableValue(card, section.data); sections.appendChild(card); }
  host.appendChild(sections);
  const technical = document.createElement("details"); technical.className = "sheet-technical-details"; const techSummary = document.createElement("summary"); techSummary.textContent = "Technical provenance and committed IDs"; const pre = document.createElement("pre"); pre.textContent = pretty(sheet); technical.append(techSummary, pre); host.appendChild(technical);
  const exportPanel = document.getElementById("gmExportPanel"); exportPanel.hidden = false;
  const workspace = sheet.factory_workspace || {status: "NOT_ATTEMPTED"};
  const workspaceComplete = workspace.status === "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE";
  const gmCandidateReady = workspace.command5 === "GM_MODEL_CANDIDATE_READY";
  document.getElementById("factoryWorkspaceExplanation").textContent = gmCandidateReady
    ? "The Character/GM Command 5 candidate and schema-valid GM model candidate are sealed. GM Screen consumer verification has not been attempted, export remains unavailable, and combat execution remains untyped."
    : workspaceComplete
    ? "GM tactical authoring is complete and the deterministic Factory Command 1–4 input workspace is prepared for a separately authorized Command 5 checkpoint. GM Screen verification and combat execution remain unattempted."
    : workspace.status === "STALE"
      ? "The prior Factory workspace is stale and must be rebuilt before later compilation."
      : "Prepare source-backed training sources, non-executable composite playbooks, Dao and I Ching guidance, and a descriptive AI behavior profile. This does not run Command 5 or Command 6.";
  const workspaceButton = document.getElementById("prepareFactoryWorkspace");
  workspaceButton.disabled = workspaceComplete || sheet.build_status !== "CHARACTER_SHEET_READY";
  workspaceButton.textContent = workspaceComplete ? "Command 1–4 Workspace Prepared" : "Prepare Command 1–4 Workspace";
  document.getElementById("factoryWorkspaceResult").textContent = gmCandidateReady
    ? "Character Sheet Ready · GM tactical authoring complete · Character/GM candidate built · GM Screen verification pending · Export unavailable · Combat not typed."
    : workspaceComplete
    ? "Character Sheet Ready · GM tactical authoring complete · Factory workspace prepared for Command 5 · GM Screen not verified · Combat not typed."
    : "GM tactical authoring has not been prepared.";
  document.getElementById("gmExportExplanation").textContent = sheet.gm_export.available ? "GM Screen source verification passed. Export one Character ZIP that can be dragged into either the Factory or the bundled GM Screen. Native owner acceptance remains pending." : `${sheet.gm_export.blockers.join(" ")} ${sheet.gm_export.next_step || "GM authoring is the next step."}`;
  const button = document.getElementById("gmExportCharacter"); button.disabled = !sheet.gm_export.available;
  document.getElementById("gmExportDownload").hidden = true;
  document.getElementById("gmExportResult").textContent = sheet.gm_export.available ? "Character Sheet Ready · GM Model Built · GM Screen Source Verified · Character ZIP Ready · Native acceptance pending · Combat pending." : gmCandidateReady ? "GM model candidate built; Command 6 consumer verification has not been run, so export remains unavailable." : workspaceComplete ? "Command 5 and Command 6 have not been run. GM export remains unavailable." : "Character Sheet complete; GM authoring and export have not been attempted.";
}

async function openOwnerCharacterSheet(projectId, refreshNonSphere = true) {
  try {
    renderOwnerSheet(await api(`/api/characters/${encodeURIComponent(projectId)}/sheet`));
    if (refreshNonSphere) await loadNonSphereAuthorityPanel();
  } catch (error) { document.getElementById("ownerCharacterSheet").textContent = plainAPIError(error, "The character sheet could not be loaded."); }
}

function ownerStageLabel(character) {
  const summary = String(character?.plain_summary || "").toLowerCase();
  const build = String(character?.build_status || "").toUpperCase();
  if (summary.includes("stage 1") || summary.includes("blueprint") || build.includes("STAGE1") || build.includes("BLUEPRINT")) return "Stage 1 Plan Sealed";
  return character?.lifecycle?.display_label || "Saved / existing";
}

async function renderCharacterLibrary() {
  const characters = await api("/api/characters");
  const host = document.getElementById("characterCardList"); clearNode(host);
  if (!characters.length) {
    const empty = document.createElement("div");
    const message = document.createElement("p"); message.textContent = "No saved characters yet. Import a completed Character ZIP above or create a new character.";
    const button = document.createElement("button"); button.type = "button"; button.className = "empty-library-actions"; button.textContent = "Create a Character";
    button.addEventListener("click", () => startNewCharacter("quick")); empty.append(message, button); host.appendChild(empty); return characters;
  }
  for (const character of characters) {
    const card = document.createElement("button"); card.type = "button"; card.className = `character-library-card${selectedProject === character.project_id ? " selected" : ""}`;
    const name = document.createElement("strong"); name.textContent = character.name;
    const status = document.createElement("span"); status.className = "character-card-status"; status.textContent = ownerStageLabel(character);
    const build = document.createElement("span"); build.textContent = friendlyLabel(character.build_status);
    const detail = document.createElement("small"); detail.textContent = [character.path, character.current_cl ? `CL ${character.current_cl}` : character.target_cl ? `Target CL ${character.target_cl}` : null].filter(Boolean).join(" · ") || character.plain_summary;
    const portable = character.portable_readiness || null;
    const combatState = document.createElement("small");
    combatState.className = "character-card-combat-state";
    combatState.textContent = portable
      ? "Combat Sheet ready · Combat runtime ready · Pre-encounter · Setup required: current Qi, current Martial Focus, opponent/teams, battlefield choice, token placement, initiative, and controllers"
      : "No verified portable combat-runtime package installed";
    card.append(name, status, build, detail, combatState); card.onclick = () => openOwnerCharacterSheet(character.project_id); host.appendChild(card);
  }
  return characters;
}

// Keep the advanced table intact while making the owner-facing character library primary.
loadProjects = async function() {
  const [projectsResult, charactersResult] = await Promise.allSettled([api("/api/projects"), renderCharacterLibrary()]);
  const rows = projectsResult.status === "fulfilled" ? projectsResult.value : [];
  const body = document.getElementById("projectRows"); clearNode(body);
  for (const row of rows) {
    const tr = document.createElement("tr"); appendTextCell(tr, row.working_name); appendTextCell(tr, row.revision); appendTextCell(tr, `${row.builder_lifecycle?.display_label || "Saved / existing"} · ${row.status}`);
    tr.onclick = async () => { selectedProject = row.project_id; stage1PromptData = null; stage1Attempt = null; document.getElementById("approveCommitStage1").disabled = true; updateAIProviderControls(); document.getElementById("stage1Prompt").value = ""; document.getElementById("stage1Result").textContent = pretty(await api(`/api/projects/${row.project_id}/stage1/status`)); await refreshSelectedProject(); await refreshStage2Status(); await openOwnerCharacterSheet(row.project_id); };
    body.appendChild(tr);
  }
  if (charactersResult.status === "rejected") {
    const host = document.getElementById("characterCardList"); clearNode(host);
    const error = document.createElement("p"); error.textContent = plainAPIError(charactersResult.reason, "Saved characters could not be loaded. Use Refresh Characters to retry."); host.appendChild(error);
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
    document.getElementById("aiProviderStatus").textContent = pretty(aiProviderStatus);
    updateAIProviderControls();
  } catch (e) { document.getElementById("aiProviderStatus").textContent = e.message; }
};

document.getElementById("saveAIProviderKey").onclick = async () => {
  const input = document.getElementById("aiProviderKey");
  try {
    aiProviderStatus = await api("/api/ai-provider/key", {
      method: "POST", body: JSON.stringify({api_key: input.value})
    });
    input.value = "";
    document.getElementById("aiProviderStatus").textContent = pretty(aiProviderStatus);
    updateAIProviderControls();
  } catch (e) { input.value = ""; document.getElementById("aiProviderStatus").textContent = e.message; }
};

document.getElementById("deleteAIProviderKey").onclick = async () => {
  try {
    aiProviderStatus = await api("/api/ai-provider/key", {method: "DELETE"});
    document.getElementById("aiProviderKey").value = "";
    document.getElementById("aiProviderStatus").textContent = pretty(aiProviderStatus);
    updateAIProviderControls();
  } catch (e) { document.getElementById("aiProviderStatus").textContent = e.message; }
};

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
  try { await resumeGuidedDraft(projectRows); }
  catch (error) { setGuidedStatus(`Your saved character is safe. Resume failed while ${error.message}.`, true); }
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
  image.dataset.assetId = selected?.asset_id || "";
  const custom = selected?.source === "owner_upload";
  document.getElementById("combatBackgroundReset").disabled = !custom;
  const mode = document.getElementById("combatBackgroundCalibrationMode");
  if (selected?.calibration?.schema === "TianxiaBattleMapCalibration.v2") {
    mode.value = selected.calibration.fit_mode || "COVER_DECORATIVE";
  }
  const fit = selected?.calibration?.fit_mode;
  const alignment = fit === "EXACT_PLAYABLE_RECT"
    ? "Exact gridless-map alignment is declared for new matches."
    : fit === "CONTAIN_DECORATIVE"
      ? "The image is decorative and may show margins."
      : "The image is decorative and may be cropped.";
  document.getElementById("combatBackgroundStatus").textContent = custom
    ? `Using uploaded background: ${selected.original_filename || "custom image"}. ${alignment} It will be copied into each new match.`
    : `Using the built-in arena. ${alignment} The application grid and typed mechanics remain authoritative.`;
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
    empty.textContent = "No installed Character Package has passed the exact runtime-ready pre-encounter checks.";
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
    badge.textContent = "Pre-Encounter Runtime Ready";
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
    card.appendChild(readiness);

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
    preview.type = "button"; preview.textContent = "Validate Pre-Encounter Draft";
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
    const name = document.createElement("h4"); name.textContent = blocked.project_id ? `Installed Character ${blocked.project_id}` : "Installed Character";
    const message = document.createElement("p"); message.textContent = blocked.message || "This package is not available for combat.";
    const badge = document.createElement("span"); badge.className = "readiness-badge"; badge.textContent = "Not Combat Ready";
    title.append(name, message); heading.append(title, badge); card.appendChild(heading);
    const reason = document.createElement("p"); reason.className = "honest-limit"; reason.textContent = `Blocked: ${blocked.code || "EXACT_VALIDATION_FAILED"}`; card.appendChild(reason);
    const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Advanced Details";
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify({package_sha256: blocked.package_sha256, installed_record: blocked.installed_record, details: blocked.details}, null, 2);
    details.append(summary, pre); card.appendChild(details); host.appendChild(card);
  }
  const blocked = blockedRows.length;
  status.textContent = `${accepted.length} runtime-ready candidate${accepted.length === 1 ? "" : "s"} available. ${blocked ? `${blocked} installed package${blocked === 1 ? " was" : "s were"} blocked by exact validation.` : "No installed package conflicts detected."}`;
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
    badge.textContent = status.available ? `Combat service available · ${catalog.teams?.length || 0} demonstration teams · encounter setup remains explicit` : "Combat service unavailable";
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
    document.getElementById("combatServiceStatus").textContent = "Combat service unavailable";
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

async function loadCombatMatches() {
  if (!combatCatalog) return [];
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
    detail.textContent = `${row.status || "UNKNOWN"} · state ${row.state_version ?? "?"} · ${row.paused ? "paused" : "ready"}`;
    copy.append(title, detail);
    const button = document.createElement("button"); button.type = "button"; button.textContent = "Open Fight";
    button.addEventListener("click", () => openCombatMatch(row.match_id));
    card.append(copy, button); host.appendChild(card);
  }
  return rows;
}

async function loadCombatHistory(matchId) {
  combatHistory = await api(`/api/combat/matches/${combatId(matchId)}/history`);
  combatHistoryIndex = null;
  combatPresentation = await api(`/api/combat/matches/${combatId(matchId)}/presentation`);
  return combatHistory;
}

async function openCombatMatch(matchId) {
  try {
    combatMatch = await api(`/api/combat/matches/${combatId(matchId)}`);
    await loadCombatHistory(matchId);
    cancelCombatPendingIntent();
    combatDecision = null; combatAIValidationToken = null; combatSelectedCandidateId = null;
    combatSelectedActorId = null; combatPinnedActorId = null; combatFollowCurrentTurn = true;
    combatAutoRunning = false; combatExecutionEpoch += 1; combatHistoryTransitionPending = false; combatHistoryTransitionSerial += 1;
    setCombatWorkspaceActive(true);
    setCombatWorkspaceView("owner");
    renderCombatMatch();
    await refreshCombatDecision();
    document.getElementById("combatWorkspace").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) { combatError(error); }
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
    combatHistory = await api(`/api/combat/matches/${combatId(matchId)}/history`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    const boundaries = combatHistory?.boundaries || [];
    if (!boundaries.length) {
      combatHistoryIndex = null;
      return;
    }
    combatHistoryIndex = Math.max(0, Math.min(boundaries.length - 1, requestedIndex));
    combatPresentation = await api(`/api/combat/matches/${combatId(matchId)}/presentation?boundary=${combatHistoryIndex}`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
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
    combatMatch = await api(`/api/combat/matches/${combatId(matchId)}`);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    await loadCombatHistory(matchId);
    if (transitionSerial !== combatHistoryTransitionSerial) return;
    renderCombatMatch();
    await refreshCombatDecision();
  } catch (error) { combatError(error); }
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
    runButton.textContent = "Run Auto";
    runButton.disabled = combatIsHistorical() || !["LOCAL_AUTO", "API_AUTO"].includes(mode);
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
    const heading = document.createElement("h4"); heading.textContent = "Identity and match lock";
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
  try {
    combatDecision = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/decision`);
    if (combatInteractionDraft && !combatInteractionDraftIsCurrent()) cancelCombatMapSelection("The map choice became stale when combat authority advanced.", false);
    if (combatPendingIntentDraft && !combatPendingIntentDraftIsCurrent()) cancelCombatPendingIntent("The pending manual action was canceled because combat authority advanced or the controller changed.");
    if (!combatDecision.context.legal_candidates.some(row => row.candidate_id === combatSelectedCandidateId)) combatSelectedCandidateId = null;
    const manualState = combatDecision.manual_submit_allowed ? "owner action available" : "automatic controller owns turn";
    document.getElementById("combatDecisionStatus").textContent = `${combatActorName(combatDecision.context.active_actor_id)} · ${combatDecision.control_mode.replaceAll("_", " ")} · ${combatDecision.context.legal_candidates.length} legal candidates · ${manualState}`;
    renderCombatActions(); renderCombatBoard(); renderCombatSheets();
  } catch (error) { combatError(error); }
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
    const summary = preflight.participants.map(row => `${row.display_name} — ${row.team_id} — ${row.controller_mode}`).join("\n");
    const confirmed = window.confirm(
      `Create Fight?\n\nThis creates one persistent match, ControllerLock, initial snapshot/journal records, and deterministic initiative.\n\n${summary}\n\nSeed: ${preflight.match_seed || "generated after confirmation"}`
    );
    if (!confirmed) {
      status.textContent = "Creation canceled. The preflight made no match, lock, snapshot, roll, or combat event.";
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
  const autoStatus = document.getElementById("combatAutoStatus");
  autoStatus.textContent = `${currentActor} is choosing an action…`;
  autoStatus.classList.remove("error");
  const result = await api(`/api/combat/matches/${combatId(combatMatch.match_id)}/auto-step`, {method: "POST", body: "{}"});
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
  result.textContent = "Preparing deterministic GM tactical authoring and Factory workspace…";
  try {
    const built = await api(`/api/characters/${encodeURIComponent(selectedProject)}/factory-workspace/build`, {method: "POST", body: "{}"});
    result.textContent = `Prepared ${friendlyLabel(built.workspace_status)}. Command 5 and Command 6 were not run.`;
    await openOwnerCharacterSheet(selectedProject);
  } catch (error) { result.textContent = plainAPIError(error, "The Factory workspace could not be prepared."); }
};


const refreshNonSphereButton = document.getElementById("refreshNonSphereAuthority");
if (refreshNonSphereButton) refreshNonSphereButton.onclick = () => loadNonSphereAuthorityPanel();
const setNonSphereMethodButton = document.getElementById("setNonSpherePrimaryMethod");
if (setNonSphereMethodButton) setNonSphereMethodButton.onclick = () => {
  const methodId = document.getElementById("nonSpherePrimaryMethod").value;
  if (selectedProject && methodId) updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/primary-method`, {method_id: methodId, evidence_ids: readNonSphereEvidence()});
};
const setNonSphereAccessSourcesButton = document.getElementById("setNonSphereAccessSources");
if (setNonSphereAccessSourcesButton) setNonSphereAccessSourcesButton.onclick = () => {
  if (!selectedProject) return;
  try {
    updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/access-sources`, {evidence_ids: readNonSphereEvidence()});
  } catch (error) {
    document.getElementById("nonSphereTechnical").textContent = plainAPIError(error, "Committed evidence selection is invalid.");
  }
};
const setNonSphereFoundationButton = document.getElementById("setNonSphereFoundation");
if (setNonSphereFoundationButton) setNonSphereFoundationButton.onclick = () => {
  if (!selectedProject) return;
  updateNonSphere(`/api/non-sphere/projects/${encodeURIComponent(selectedProject)}/foundation`, {foundation_id: document.getElementById("nonSphereFoundation").value || null});
};
loadNonSphereAuthorityPanel().catch(() => {});

// W3-P1 owner staging, Save As, continuation, and read-only demo boundary.
let ownerStagedArtifact = null;
const ownerArtifactResult = document.getElementById("ownerArtifactResult");
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
  if (!selectedProject) { status.textContent = "Select Xiang Yahui’s Stage 1 project first."; return; }
  try {
    const stage = await api(`/api/projects/${encodeURIComponent(selectedProject)}/stage1/status`);
    if (!stage.blueprint_head) throw new Error("The selected project does not have a sealed Stage 1 plan.");
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
function cgSelectedProjectId() {
  if (typeof selectedProject === "string") return selectedProject;
  return selectedProject?.project_id || selectedProject?.project?.project_id || null;
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
  const clean = reviewable && run.quality?.status === "CLEAN" && !(run.blockers || []).length;
  document.getElementById("cgFinalize").disabled = !clean;
  document.getElementById("cgRevise").disabled = !reviewable;
  document.getElementById("cgCancel").disabled = !!run.commit || ["CANCELLED","CLEAN_AND_FINALIZED"].includes(run.status);
  document.getElementById("cgDownloadRequest").disabled = run.execution_mode !== "MANUAL_CHAT";
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
  try { cgRender(await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/finalize`, {method:"POST", body:{}})); }
  catch (error) { document.getElementById("cgProgress").textContent = plainAPIError(error, "Character could not be finalized."); }
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
document.getElementById("cgAutoOptIn")?.addEventListener("click", async () => {
  try {
    const finalized = await api(`/api/character-creation/runs/${encodeURIComponent(cgRun.run_id)}/auto-finalize-opt-in`, {method:"POST", body:{}});
    cgRender(finalized);
    document.getElementById("cgProgress").textContent = `Auto-Finalize consent recorded and candidate ${finalized.dry_run.candidate_identity.slice(0, 12)} finalized.`;
  } catch (error) {
    document.getElementById("cgProgress").textContent = plainAPIError(error, "Auto-Finalize opt-in could not be recorded.");
  }
});
