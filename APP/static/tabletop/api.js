// Tabletop API helpers (owner 2026-09-25). Mutations carry the local session token.
import {playerError} from "./error-text.js?v=p20261010-06";
import {expandTableTexts} from './table-text-pool.js';
import {checkBuild} from './build-check.js';
let tokenPromise = null;

export function sessionToken() {
  if (!tokenPromise) {
    tokenPromise = fetch("/api/session", {cache: "no-store"})
      .then(response => response.json())
      .then(body => body.token)
      .catch(_error => { tokenPromise = null; throw new ApiError("Session connection failed", "NETWORK_ERROR", 0); });
  }
  return tokenPromise;
}

export class ApiError extends Error {
  constructor(message, code, status, validationErrors = null, requestBody = null, path = "") {
    super(playerError({code, status, validationErrors, requestBody, path}));
    this.diagnosticMessage = message;
    this.code = code;
    this.status = status;
  }
}

export async function api(path, options = {}) {
  try { return await request(path, options); }
  catch (error) {
    // The Factory issues a new session token each time it starts; a page opened before a restart still holds the old
    // one. Fetch the new one and try once more (owner 2026-09-29: "A valid local session token is required").
    if (error.status !== 403 || !/session token/i.test(error.diagnosticMessage)) throw error;
    tokenPromise = null;
    return request(path, options);
  }
}

async function request(path, {method, body, raw, contentType} = {}) {
  const verb = method || (body !== undefined || raw !== undefined ? "POST" : "GET");
  const headers = {};
  if (verb !== "GET") headers["X-Foundry-Token"] = await sessionToken();
  let payload;
  if (raw !== undefined) { payload = raw; headers["Content-Type"] = contentType || "application/octet-stream"; }
  else if (body !== undefined) { payload = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
  let response;
  try { response = await fetch(path, {method: verb, headers, body: payload, cache: "no-store"}); }
  catch (_error) { throw new ApiError("Connection failed", "NETWORK_ERROR", 0); }
  let text;
  try { text = await response.text(); }
  catch (_error) { throw new ApiError("Response interrupted", "NETWORK_ERROR", 0); }
  checkBuild(response.headers.get("X-Factory-Build"));
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_error) { data = {raw: text}; }
  if (!response.ok) {
    const error = data && data.error ? data.error : {};
    const detail = typeof error.details === "string" ? ` (${error.details})` : "";
    throw new ApiError((error.message || `Request failed (${response.status})`) + detail, error.code || "HTTP_ERROR", response.status,
      error.details, body, path);
  }
  return expandTableTexts(data);
}

export const enc = encodeURIComponent;
