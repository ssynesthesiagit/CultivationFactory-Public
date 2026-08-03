(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TianxiaCompleteRequestSave = api;
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function requestUrl(runId) {
    return `/api/character-creation/runs/${encodeURIComponent(runId)}/complete-request.zip`;
  }

  function createController({getRunId, getNativeSave, button, status, navigate}) {
    let active = false;
    return async function saveCompleteRequest() {
      const runId = getRunId();
      if (!runId) return {status: "unavailable"};
      if (active) return {status: "busy"};
      const nativeSave = getNativeSave();
      if (typeof nativeSave !== "function") {
        navigate(requestUrl(runId));
        return {status: "browser"};
      }
      active = true;
      button.disabled = true;
      if (status) {
        status.className = "availability-note";
        status.textContent = "Saving the validated complete request ZIP — choose a location in the save dialog…";
      }
      try {
        const result = await nativeSave(runId);
        if (result?.status === "cancelled") {
          if (status) status.textContent = "Save cancelled. No file was written.";
          return result;
        }
        if (!result || result.status !== "saved") {
          throw new Error(result?.message || "The validated request ZIP could not be saved.");
        }
        if (status) {
          status.className = "availability-note success";
          status.textContent = `Complete request saved to ${result.path} (${result.bytes} bytes, SHA-256 ${result.sha256}). ZIP CRC, contents, project, and revision binding passed.`;
        }
        return result;
      } catch (error) {
        if (status) {
          status.className = "availability-note error";
          status.textContent = error?.message || "The complete request ZIP could not be saved.";
        }
        return {status: "error", message: status?.textContent || "The complete request ZIP could not be saved."};
      } finally {
        active = false;
        button.disabled = false;
      }
    };
  }

  return {createController, requestUrl};
}));
