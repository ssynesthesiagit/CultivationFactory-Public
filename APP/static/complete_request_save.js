(function (root, factory) {
  const api = factory(root);
  // The desktop webview may expose CommonJS globals even though this file is
  // loaded as an ordinary page script. Always publish the browser global, and
  // also keep the Node export used by focused tests and native packaging.
  if (root && typeof root === "object") root.TianxiaCompleteRequestSave = api;
  if (typeof module === "object" && module.exports) module.exports = api;
}(typeof window !== "undefined" ? window : globalThis, function (root) {
  "use strict";

  function requestUrl(runId) {
    return `/api/character-creation/runs/${encodeURIComponent(runId)}/complete-request.zip`;
  }

  function downloadFilename(response, runId) {
    const disposition = response.headers?.get?.("Content-Disposition") || "";
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const ordinary = disposition.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\s]+)/i);
    let filename = encoded ? decodeURIComponent(encoded[1]) : (ordinary ? (ordinary[1] || ordinary[2]) : "");
    filename = String(filename || `CG1_COMPLETE_REQUEST_${runId}.zip`)
      .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
      .trim();
    return filename.toLowerCase().endsWith(".zip") ? filename : `${filename}.zip`;
  }

  async function saveWithBrowser(runId, environment = {}) {
    const fetchImpl = environment.fetch || root.fetch?.bind(root);
    const documentRef = environment.document || root.document;
    const urlApi = environment.URL || root.URL;
    const schedule = environment.schedule || root.setTimeout?.bind(root);
    if (typeof fetchImpl !== "function" || !documentRef || typeof urlApi?.createObjectURL !== "function") {
      throw new Error("This browser cannot prepare a local ZIP download.");
    }
    const response = await fetchImpl(requestUrl(runId), {credentials: "same-origin"});
    if (!response.ok) {
      let detail = "";
      try { detail = String(await response.text()).trim().slice(0, 300); } catch (_error) { /* no response body */ }
      throw new Error(`The complete request ZIP could not be prepared (HTTP ${response.status})${detail ? `: ${detail}` : "."}`);
    }
    const blob = await response.blob();
    const filename = downloadFilename(response, runId);
    const objectUrl = urlApi.createObjectURL(blob);
    try {
      const anchor = documentRef.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.hidden = true;
      (documentRef.body || documentRef.documentElement).appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      const revoke = () => urlApi.revokeObjectURL(objectUrl);
      if (typeof schedule === "function") schedule(revoke, 1000);
      else revoke();
    }
    const sha256 = response.headers?.get?.("X-Tianxia-Final-Zip-SHA256") || "";
    return {
      status: "saved",
      path: filename,
      bytes: Number(blob.size || 0),
      sha256,
      message: `Download started: ${filename} (${Number(blob.size || 0)} bytes).`,
    };
  }

  function createController({getRunId, getNativeSave, getBrowserSave, button, status, navigate}) {
    let active = false;
    return async function saveCompleteRequest() {
      const runId = getRunId();
      if (!runId) return {status: "unavailable"};
      if (active) return {status: "busy"};
      const nativeSave = getNativeSave();
      const browserSave = typeof getBrowserSave === "function" ? getBrowserSave() : undefined;
      if (typeof nativeSave !== "function" && typeof browserSave !== "function") {
        if (status) status.textContent = "Starting the browser download…";
        navigate(requestUrl(runId));
        return {status: "browser"};
      }
      const save = typeof nativeSave === "function" ? nativeSave : browserSave;
      const native = typeof nativeSave === "function";
      active = true;
      button.disabled = true;
      if (status) {
        status.className = "availability-note";
        status.textContent = native
          ? "Saving the validated complete request ZIP — choose a location in the save dialog…"
          : "Preparing the validated complete request ZIP… Large content sets can take about a minute.";
      }
      try {
        const result = await save(runId);
        if (result?.status === "cancelled") {
          if (status) status.textContent = "Save cancelled. No file was written.";
          return result;
        }
        if (!result || result.status !== "saved") {
          throw new Error(result?.message || "The validated request ZIP could not be saved.");
        }
        if (status) {
          status.className = "availability-note success";
          status.textContent = result.message || `Complete request saved to ${result.path} (${result.bytes} bytes, SHA-256 ${result.sha256}). ZIP CRC, contents, project, and revision binding passed.`;
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

  return {createController, downloadFilename, requestUrl, saveWithBrowser};
}));
