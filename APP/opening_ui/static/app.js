(function () {
  "use strict";

  let state = null;
  let requestCounter = 0;
  let sessionToken = "";
  const API_PREFIX = "/api/opening";

  const $ = (id) => document.getElementById(id);
  const actionButtonIds = ["short-rest-button", "hit-die-button", "take-item-button", "drop-item-button"];
  let busy = false;

  function requestId(prefix) {
    requestCounter += 1;
    return "ui-" + prefix + "-" + Date.now().toString(36) + "-" + requestCounter.toString(36);
  }

  function showError(error) {
    $("error-box").classList.remove("hidden");
    const code = error && error.code ? error.code : "REQUEST_FAILED";
    const guidance = {
      STALE_REVISION: "Reload the saved campaign before trying that action again.",
      INVALID_REVISION: "Use the visible action controls so the server can supply the current revision.",
      INVALID_REQUEST_FIELDS: "Use one of the visible controls; the server rejected this request shape.",
      ITEM_UNAVAILABLE: "The item state changed; reload the saved campaign and try again.",
      HIT_DICE_UNAVAILABLE: "Complete a qualifying Short Rest before spending a remaining Hit Die.",
      NO_RECOVERY_WINDOW: "Complete a qualifying Short Rest before spending a remaining Hit Die.",
      NO_ACTIVE_ACTIVITY: "The saved campaign is idle; use a visible supported activity first.",
      SAVE_FAILED: "The canonical action was not published; retry the same supported action after reloading.",
    }[code] || "Refresh the saved campaign and retry a supported action.";
    $("error-code").textContent = code;
    $("error-message").textContent = " · " + ((error && error.message) || "The server rejected the request.");
    $("error-guidance").textContent = " — " + guidance;
  }

  function clearError() {
    $("error-box").classList.add("hidden");
  }

  async function getSession() {
    const response = await fetch(API_PREFIX + "/session", { credentials: "same-origin", cache: "no-store" });
    const result = await response.json();
    if (!response.ok || !result.ok) throw result.error || { code: "SESSION_FAILED", message: "Session unavailable" };
    sessionToken = result.token || sessionToken;
    if (!result.configured) {
      $("launch-button").disabled = true;
      $("entry-note").textContent = "The server is waiting for a validated mortal record.";
    } else {
      $("launch-button").disabled = false;
      $("entry-note").textContent = "Validated export · trusted admission · canonical campaign state";
    }
    return result;
  }

  async function mutate(path, body) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Foundry-Token": sessionToken },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw result.error || { code: "REQUEST_FAILED", message: "The server rejected the request" };
    return result;
  }

  function setBusy(value) {
    busy = value;
    applyActionAvailability();
    $("launch-button").disabled = value;
    $("reopen-button").disabled = value;
  }

  function applyActionAvailability() {
    if (!state) return;
    const actions = state.actions || {};
    const actionMap = {
      "short-rest-button": "short_rest",
      "hit-die-button": "spend_hit_die",
      "take-item-button": "take_starter_item",
      "drop-item-button": "drop_starter_item",
    };
    actionButtonIds.forEach((id) => { $(id).disabled = busy || !actions[actionMap[id]]; });
    const localActions = state.local_test_actions || {};
    document.querySelectorAll(".test-button").forEach((button) => {
      const detail = localActions[button.dataset.localAction] || {};
      button.disabled = busy || detail.enabled === false;
      if (detail.reason) {
        button.title = detail.reason;
        button.setAttribute("aria-label", button.textContent + ". " + detail.reason);
      } else {
        button.removeAttribute("title");
        button.removeAttribute("aria-label");
      }
    });
  }

  function showPlayer() {
    $("entry-screen").classList.add("hidden");
    $("player-screen").classList.remove("hidden");
  }

  function textOr(value, fallback) { return value === undefined || value === null ? fallback : String(value); }

  function renderConditions(conditions) {
    const list = $("conditions-list");
    list.replaceChildren();
    if (!conditions.length) {
      const item = document.createElement("li"); item.className = "muted"; item.textContent = "None recorded"; list.appendChild(item); return;
    }
    conditions.forEach((condition) => {
      const item = document.createElement("li"); item.textContent = condition.kind + (condition.levels > 1 ? " ×" + condition.levels : ""); list.appendChild(item);
    });
  }

  function renderList(id, values, empty) {
    const list = $(id); list.replaceChildren();
    if (!values.length) { const item = document.createElement("li"); item.className = "muted"; item.textContent = empty; list.appendChild(item); return; }
    values.forEach((value) => { const item = document.createElement("li"); item.textContent = value.label + (value.quantity > 1 ? " ×" + value.quantity : ""); list.appendChild(item); });
  }

  function render(next) {
    state = next;
    showPlayer();
    const actor = state.actor;
    $("character-name").textContent = actor.name;
    $("character-id").textContent = actor.actor_id;
    $("location-line").textContent = state.location.name;
    $("time-value").textContent = textOr(state.elapsed_seconds, "0");
    $("hp-value").textContent = actor.hp + " / " + actor.hp_max;
    $("hp-meter").style.width = Math.max(0, Math.min(100, (actor.hp / Math.max(1, actor.hp_max)) * 100)) + "%";
    const dice = Object.values(actor.hit_dice).map((die) => die.remaining + "/" + die.maximum + " d" + die.sides).join(" · ");
    $("dice-value").textContent = dice || "None";
    $("revision-value").textContent = "rev " + state.revision;
    $("activity-value").textContent = actor.activity ? actor.activity.kind + " · " + actor.activity.status + " · " + actor.activity.elapsed + "s" : "Idle";
    $("state-line").textContent = actor.dead ? "Unresolved zero-HP state" : "Canonical state saved";
    renderConditions(actor.conditions || []);
    renderList("inventory-list", state.inventory, "Empty hands");
    renderList("nearby-list", state.nearby_items, "Nothing visible");
    applyActionAvailability();
    $("local-test-controls").hidden = !state.local_test_controls;
    const localTime = (state.local_test_actions || {}).advance_time || {};
    $("local-test-guidance").textContent = localTime.enabled === false ? localTime.reason : "";
    const activity = actor.activity;
    let line = "The gate is quiet.";
    if (activity) {
      if (activity.status === "completed") line = activity.kind + " completed at the canonical time.";
      else if (activity.status === "interrupted") line = activity.kind + " was interrupted.";
      else line = "The host is observing " + activity.kind + ".";
    }
    $("journal-list").replaceChildren(Object.assign(document.createElement("li"), { textContent: line }));
    const nearbyToken = state.nearby_items.some((item) => item.instance_id === "starter-token");
    const ownedToken = state.inventory.some((item) => item.instance_id === "starter-token");
    $("scene-copy").textContent = nearbyToken
      ? "The gate is quiet. A woven token rests beside the path, and the campaign clock belongs to the host."
      : ownedToken
        ? "The gate is quiet. The woven token is in your inventory, and the campaign clock belongs to the host."
        : "The gate is quiet. The campaign clock belongs to the host.";
  }

  async function refresh() {
    try {
      clearError();
      const result = await getSession();
      if (result.started) render(result.state);
    } catch (error) { showError(error); }
  }

  async function launch() {
    try {
      setBusy(true); clearError(); $("notice").textContent = "Opening the validated mortal record…";
      const result = await mutate(API_PREFIX + "/launch", {}); render(result.state); $("notice").textContent = result.resumed ? "Saved campaign reopened." : "Campaign admitted and saved.";
    } catch (error) { showError(error); $("notice").textContent = ""; }
    finally { setBusy(false); }
  }

  async function reopen() {
    try {
      setBusy(true); clearError(); const result = await mutate(API_PREFIX + "/reopen", {}); render(result.state); $("notice").textContent = "Saved campaign reloaded.";
    } catch (error) { showError(error); }
    finally { setBusy(false); }
  }

  async function action(name, local) {
    if (!state) return;
    try {
      setBusy(true); clearError(); $("notice").textContent = "Submitting to the canonical controller…";
      const result = await mutate(local ? API_PREFIX + "/local-test" : API_PREFIX + "/action", { action: name, request_id: requestId(name), expected_revision: state.revision });
      render(result.state);
      $("notice").textContent = result.warning
        ? "Accepted and saved. " + result.warning
        : result.duplicate ? "Existing request receipt returned." : "Accepted and saved.";
    } catch (error) { showError(error); $("notice").textContent = ""; }
    finally { setBusy(false); }
  }

  $("launch-button").addEventListener("click", launch);
  $("reopen-button").addEventListener("click", reopen);
  actionButtonIds.forEach((id) => $(id).addEventListener("click", () => action($(id).dataset.action, false)));
  document.querySelectorAll(".test-button").forEach((button) => button.addEventListener("click", () => action(button.dataset.localAction, true)));
  refresh();
}());
