// A character's picture and token (owner 2026-09-27: "I think we should do a full picture in creation have it create one
// then retry if we dont like the first one, the token can be created from the main picture. Probably just a little circle
// frame we can put over the head part"; "have the icon location be like a profile where you can drag an image in or push a
// button to autogenerate with local model").
//
// The dialog shows the full picture -- made by the owner's local Anima Studio (combat/portraits.py) until one is liked, or
// uploaded, dropped or pasted -- with a circle frame over the head: drag it, resize it (edge, wheel or slider), and Save
// keeps the picture and the round 512 px token cut from the circle. It is self-contained so the builder's finished page can
// open it too (openPictureDialog); on the sheet the portrait opens it, takes a dropped picture, and ✨ makes both at once.

const TOKEN = 512;              // the saved token, in pixels
const BOX = { w: 360, h: 540 }; // the picture on screen, at most
// Where the head usually is, as fractions of the picture's width/height, for each framing Anima paints.
const HEAD = { portrait: { x: 0.5, y: 0.42, r: 0.36 }, upper: { x: 0.5, y: 0.21, r: 0.19 }, full: { x: 0.5, y: 0.11, r: 0.08 } };

let deps = null;   // the sheet's {h, $, fetchJson, toast, reloadSheet, projectId, sheet}
let view = null;   // the open dialog: {projectId, info, pic, circle, drag, dialog, onSaved}

// ------------------------------------------------------------------ small helpers (the builder page has none of the sheet's)
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false && kid !== "") el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const $ = (id) => document.getElementById(id);
async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) throw new Error(body?.error?.message || body?.detail || `${response.status} ${response.statusText}`);
  return body;
}
function toast(kind, title, message) {
  if (deps?.toast) deps.toast(kind, title, message, kind === "error" ? 5200 : 2600);
  else status(`${title}${message ? ` — ${message}` : ""}`);
}
async function call(projectId, path, body, method = "POST") {
  const session = await fetchJson("/api/session");
  return fetchJson(`/api/tabletop/characters/${encodeURIComponent(projectId)}/${path}`, {
    method, headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: body ? JSON.stringify(body) : undefined,
  });
}
function status(text) { const el = $("pic-status"); if (el) el.textContent = text; }
function loaded(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    if (/^https?:/.test(src) && !src.startsWith(location.origin)) image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("That picture could not be opened."));
    image.src = src;
  });
}
function readFile(file) {
  return new Promise((resolve, reject) => {
    if (file.size > 15 * 1024 * 1024) { reject(new Error("That picture is over 15 MB.")); return; }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("That file could not be read."));
    reader.readAsDataURL(file);
  });
}
// A dropped or pasted picture: a file, or an image address dragged from another page.
function picked(transfer) {
  const file = [...(transfer?.files || [])].find((row) => row.type.startsWith("image/"));
  if (file) return { file };
  const item = [...(transfer?.items || [])].find((row) => row.kind === "file" && row.type.startsWith("image/"));
  if (item) return { file: item.getAsFile() };
  const url = (transfer?.getData?.("text/uri-list") || "").split("\n").find((line) => /^https?:|^data:image\//.test(line.trim()));
  return url ? { url: url.trim() } : null;
}
function headCircle(image, framing) {
  const spot = HEAD[framing] || (Math.abs(image.naturalWidth - image.naturalHeight) < 8 ? HEAD.portrait : HEAD.upper);
  return { x: spot.x * image.naturalWidth, y: spot.y * image.naturalHeight, r: spot.r * image.naturalWidth };
}
function injectStyle() {
  if ($("pic-style")) return;
  document.head.append(h("style", { id: "pic-style" }, `
.pic-dialog { max-width: 820px; width: calc(100vw - 32px); border-radius: 12px; padding: 16px; color: var(--text, #e8e2d6);
  background: var(--panel, #1c2126); border: 1px solid var(--accent, #c9a45c); }
.pic-dialog::backdrop { background: rgba(0,0,0,.6); }
.pic-dialog h2 { margin: 0 0 10px; font-size: 18px; }
.pic-body { display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: start; }
.pic-stage { display: grid; gap: 8px; justify-items: center; }
#pic-canvas { border-radius: 8px; background: #15191c; touch-action: none; cursor: grab; max-width: 100%; }
#pic-canvas.is-drop { outline: 3px solid var(--accent, #c9a45c); }
.pic-zoom { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; width: 100%; }
.pic-zoom-controls { display: grid; gap: 4px; }
.pic-zoom .pic-row { flex-wrap: nowrap; }
#pic-size { flex: 1; min-width: 80px; }
#pic-smaller, #pic-bigger { padding: 2px 10px; font-size: 16px; line-height: 1.2; }
#pic-preview { width: 72px; height: 72px; border-radius: 50%; border: 2px solid var(--accent, #c9a45c); background: #15191c; }
.pic-side { display: grid; gap: 8px; align-content: start; font-size: 13px; }
.pic-side textarea, .pic-side select { width: 100%; box-sizing: border-box; }
.pic-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.pic-actions { display: flex; gap: 8px; margin-top: 14px; align-items: center; }
.pic-actions .grow { flex: 1; }
.pic-note { color: var(--muted, #9aa3ad); font-size: 12px; margin: 0; }
.pic-dialog button, .pic-dialog .pic-upload { cursor: pointer; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--line-strong, #555);
  background: var(--panel-2, #262c32); color: inherit; font: inherit; }
.pic-dialog .pic-primary { background: var(--accent, #c9a45c); color: var(--panel, #1c2126); border-color: var(--accent, #c9a45c); font-weight: 700; }
.pic-dialog button:disabled { opacity: .5; cursor: default; }
@media (max-width: 700px) { .pic-body { grid-template-columns: 1fr; } }`));
}

// ------------------------------------------------------------------ the sheet's portrait
export function initTokens(options) {
  deps = options;
  const portrait = deps.$("portrait");
  if (!portrait) return;
  portrait.addEventListener("click", (event) => { if (!event.target.closest("#portrait-gen")) openToken(); });
  portrait.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target === portrait) { event.preventDefault(); openToken(); }
  });
  for (const type of ["dragenter", "dragover"]) {
    portrait.addEventListener(type, (event) => { event.preventDefault(); portrait.classList.add("is-drop"); });
  }
  portrait.addEventListener("dragleave", () => portrait.classList.remove("is-drop"));
  portrait.addEventListener("drop", (event) => {
    event.preventDefault();
    portrait.classList.remove("is-drop");
    const dropped = picked(event.dataTransfer);
    if (dropped) openToken(dropped);
  });
  deps.$("portrait-gen")?.addEventListener("click", (event) => { event.stopPropagation(); void quickAnima(); });
}

export function showToken() {
  const url = deps?.sheet()?.token_url;
  const portrait = deps?.$("portrait");
  if (!portrait) return;
  portrait.style.backgroundImage = url ? `url("${url}")` : "";
  portrait.classList.toggle("has-token", Boolean(url));
}

export function openToken(start = null) {
  const sheet = deps.sheet() || {};
  return openPictureDialog({ projectId: deps.projectId(), info: sheet, start, onSaved: () => deps.reloadSheet() });
}

// ✨ on the portrait: Anima paints the character's picture (upper body); the token is cut over the head at once.
async function quickAnima() {
  const portrait = deps.$("portrait");
  if (portrait.classList.contains("is-busy")) return;
  portrait.classList.add("is-busy");
  toast("ok", "Anima is painting…", "About 10–20 seconds.");
  try {
    const projectId = deps.projectId();
    const result = await call(projectId, "token/generate", { look: deps.sheet()?.token_look || null, framing: "upper" });
    const image = await loaded(result.image);
    await savePicture(projectId, result.image);
    await saveToken(projectId, image, headCircle(image, "upper"));
    await deps.reloadSheet();
    toast("ok", "Picture and token made", "Click the portrait to move the circle, or make another.");
  } catch (error) {
    toast("error", "Nothing made", error.message);
  } finally {
    portrait.classList.remove("is-busy");
  }
}

// ------------------------------------------------------------------ the dialog
export async function openPictureDialog({ projectId, info = null, start = null, onSaved = null } = {}) {
  injectStyle();
  $("pic-dialog")?.close();
  if (!info) {
    try { info = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(projectId)}/sheet`); } catch { info = {}; }
  }
  const dialog = h("dialog", { class: "pic-dialog frame", id: "pic-dialog", "aria-labelledby": "pic-title" },
    h("h2", { id: "pic-title" }, `Picture and token${info?.summary?.name ? ` — ${info.summary.name}` : ""}`),
    h("div", { class: "pic-body" },
      h("div", { class: "pic-stage" },
        h("canvas", { id: "pic-canvas", width: String(BOX.w), height: String(BOX.h), tabindex: "0",
                      "aria-label": "The picture; drag the circle over the head, drag its edge or scroll to resize it" }),
        h("div", { class: "pic-zoom" },
          h("div", { class: "pic-zoom-controls" },
            h("span", { class: "pic-note" }, "Circle: smaller shows just the face, bigger more of the body"),
            h("div", { class: "pic-row" },
              h("button", { type: "button", id: "pic-smaller", title: "Smaller circle (less shown)", "aria-label": "Smaller circle" }, "−"),
              h("input", { type: "range", id: "pic-size", min: "0.03", max: "1", step: "0.005", value: "0.2", "aria-label": "Circle size", disabled: true }),
              h("button", { type: "button", id: "pic-bigger", title: "Bigger circle (more shown)", "aria-label": "Bigger circle" }, "+"))),
          h("canvas", { id: "pic-preview", width: "96", height: "96", title: "The token as it will look", "aria-label": "Token preview" }))),
      h("div", { class: "pic-side" },
        h("p", { class: "pic-note" }, "Make the picture with Anima Studio until you like one, or upload, drop or paste your own. Put the circle over the head: that is the token."),
        h("label", { for: "pic-look" }, "How they look (optional; Anima reads the sheet too)"),
        h("textarea", { id: "pic-look", rows: "3", maxlength: "300", placeholder: "e.g. young woman, short silver hair, scarred cheek, dark red robes" }, info?.token_look || ""),
        h("div", { class: "pic-row" },
          h("select", { id: "pic-framing", "aria-label": "Framing" },
            h("option", { value: "upper", selected: true }, "Upper body"), h("option", { value: "full" }, "Full body"),
            h("option", { value: "portrait" }, "Head and shoulders")),
          h("button", { type: "button", id: "pic-anima", class: "pic-primary" }, "Make with Anima")),
        h("label", { class: "pic-upload" }, "Upload a picture…", h("input", { type: "file", id: "pic-file", accept: "image/png,image/jpeg,image/webp", hidden: true })),
        h("p", { class: "pic-note", id: "pic-status" }, ""))),
    h("div", { class: "pic-actions" },
      h("button", { type: "button", id: "pic-remove" }, "Remove picture and token"),
      h("span", { class: "grow" }),
      h("button", { type: "button", id: "pic-cancel" }, "Close"),
      h("button", { type: "button", id: "pic-save", class: "pic-primary", disabled: true }, "Save picture and token")));
  document.body.append(dialog);
  view = { projectId, info, pic: null, circle: null, drag: null, dialog, onSaved };
  dialog.addEventListener("close", () => { dialog.remove(); view = null; });
  $("pic-cancel").addEventListener("click", () => dialog.close());
  $("pic-anima").addEventListener("click", () => void makeWithAnima());
  $("pic-file").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (file) void begin({ file }); });
  $("pic-save").addEventListener("click", () => void save());
  $("pic-remove").addEventListener("click", () => void remove());
  wireCanvas($("pic-canvas"), $("pic-size"));
  dialog.addEventListener("paste", (event) => { const got = picked(event.clipboardData); if (got) { event.preventDefault(); void begin(got); } });
  dialog.showModal();
  if (start) await begin(start);
  else if (info?.picture_url) await show(info.picture_url, false, null, info.token_circle);
  else if (info?.token_url) await show(info.token_url, false, "portrait");
  else { draw(); status("No picture yet: make one with Anima, or upload one."); }
  return dialog;
}

async function begin({ file, url }) {
  try {
    await show(file ? await readFile(file) : url, true, null);
    status("Put the circle over the head, then Save.");
  } catch (error) {
    status(error.message);
  }
}

// Show a picture; ``fresh`` pictures (made or uploaded now) are saved with the token; ``spot`` is a remembered circle.
async function show(src, fresh, framing, spot = null) {
  const image = await loaded(fresh ? src : `${src.split("?")[0]}?v=${Date.now()}`);
  if (!view) return;
  view.pic = { image, src, fresh };
  view.circle = spot && typeof spot.x === "number"
    ? { x: spot.x * image.naturalWidth, y: spot.y * image.naturalWidth, r: spot.r * image.naturalWidth }
    : headCircle(image, framing);
  const size = $("pic-size");
  size.disabled = false;
  size.value = String(view.circle.r / image.naturalWidth);
  $("pic-save").disabled = false;
  draw();
}

async function makeWithAnima() {
  const button = $("pic-anima");
  button.disabled = true;
  const framing = $("pic-framing").value;
  status("Anima is painting… (about 10–20 seconds)");
  try {
    const result = await call(view.projectId, "token/generate", { look: $("pic-look").value.trim() || null, framing });
    await show(result.image, true, result.framing || framing);
    status(`Made with Anima (seed ${result.seed}). Not it? Make another. Otherwise put the circle over the head and Save.`);
  } catch (error) {
    status(error.message);
  } finally {
    button.disabled = false;
  }
}

function geometry() {
  const image = view.pic.image;
  const scale = Math.min(BOX.w / image.naturalWidth, BOX.h / image.naturalHeight);
  return { scale, w: Math.round(image.naturalWidth * scale), h: Math.round(image.naturalHeight * scale) };
}

function draw() {
  const canvas = $("pic-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!view?.pic) {
    canvas.width = 300; canvas.height = 300;
    ctx.fillStyle = "#15191c"; ctx.fillRect(0, 0, 300, 300);
    ctx.fillStyle = "#6b7580"; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Drop a picture here", 150, 150);
    return;
  }
  const { scale, w, h: hgt } = geometry();
  canvas.width = w; canvas.height = hgt;
  ctx.drawImage(view.pic.image, 0, 0, w, hgt);
  const c = view.circle;
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,.55)";
  ctx.beginPath();
  ctx.rect(0, 0, w, hgt);
  ctx.arc(c.x * scale, c.y * scale, c.r * scale, 0, Math.PI * 2, true);
  ctx.fill("evenodd");
  ctx.restore();
  ctx.strokeStyle = "rgba(255,255,255,.9)";
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(c.x * scale, c.y * scale, c.r * scale, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = "#fff";
  ctx.beginPath(); ctx.arc(c.x * scale + c.r * scale * Math.SQRT1_2, c.y * scale + c.r * scale * Math.SQRT1_2, 5, 0, Math.PI * 2); ctx.fill();
  const preview = $("pic-preview");
  if (preview) cut(preview.getContext("2d"), preview.width, view.pic.image, c);
}

// The circle cut from the picture into a square of ``size`` pixels (the token, and its preview).
function cut(ctx, size, image, circle) {
  ctx.clearRect(0, 0, size, size);
  ctx.save();
  ctx.beginPath(); ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2); ctx.clip();
  const k = size / (2 * circle.r);
  ctx.drawImage(image, (circle.r - circle.x) * k, (circle.r - circle.y) * k, image.naturalWidth * k, image.naturalHeight * k);
  ctx.restore();
}

function wireCanvas(canvas, size) {
  const at = (event) => {
    const rect = canvas.getBoundingClientRect(), { scale } = geometry();
    return { x: (event.clientX - rect.left) * (canvas.width / rect.width) / scale, y: (event.clientY - rect.top) * (canvas.height / rect.height) / scale };
  };
  canvas.addEventListener("pointerdown", (event) => {
    if (!view?.pic) return;
    const p = at(event), c = view.circle, d = Math.hypot(p.x - c.x, p.y - c.y);
    view.drag = { mode: Math.abs(d - c.r) < 10 / geometry().scale ? "size" : "move", dx: c.x - p.x, dy: c.y - p.y };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!view?.drag) return;
    const p = at(event), c = view.circle, image = view.pic.image;
    if (view.drag.mode === "size") c.r = Math.max(12, Math.min(image.naturalWidth, Math.hypot(p.x - c.x, p.y - c.y)));
    else { c.x = p.x + view.drag.dx; c.y = p.y + view.drag.dy; }
    size.value = String(c.r / image.naturalWidth);
    draw();
  });
  canvas.addEventListener("pointerup", () => { if (view) view.drag = null; });
  canvas.addEventListener("wheel", (event) => {
    if (!view?.pic) return;
    event.preventDefault();
    const image = view.pic.image;
    view.circle.r = Math.max(12, Math.min(image.naturalWidth, view.circle.r * (event.deltaY < 0 ? 1.06 : 1 / 1.06)));
    size.value = String(view.circle.r / image.naturalWidth);
    draw();
  }, { passive: false });
  size.addEventListener("input", () => { if (view?.pic) { view.circle.r = Number(size.value) * view.pic.image.naturalWidth; draw(); } });
  const step = (factor) => {
    if (!view?.pic) return;
    const image = view.pic.image;
    view.circle.r = Math.max(12, Math.min(image.naturalWidth, view.circle.r * factor));
    size.value = String(view.circle.r / image.naturalWidth);
    draw();
  };
  $("pic-smaller").addEventListener("click", () => step(1 / 1.15));
  $("pic-bigger").addEventListener("click", () => step(1.15));
  for (const type of ["dragenter", "dragover"]) canvas.addEventListener(type, (event) => { event.preventDefault(); canvas.classList.add("is-drop"); });
  canvas.addEventListener("dragleave", () => canvas.classList.remove("is-drop"));
  canvas.addEventListener("drop", (event) => { event.preventDefault(); canvas.classList.remove("is-drop"); const got = picked(event.dataTransfer); if (got) void begin(got); });
}

// The picture as a PNG (an uploaded JPEG or WebP is redrawn), sent as the character's picture.
async function savePicture(projectId, src) {
  let data = src;
  if (!/^data:image\/png/.test(src)) {
    const image = await loaded(src), canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    canvas.getContext("2d").drawImage(image, 0, 0);
    try { data = canvas.toDataURL("image/png"); } catch { throw new Error("That picture came from another site and can't be used directly; save it and drop the file instead."); }
  }
  return call(projectId, "picture", { data_base64: data });
}

// The token: the circle cut from the picture at TOKEN pixels.
async function saveToken(projectId, image, circle) {
  const out = document.createElement("canvas");
  out.width = TOKEN; out.height = TOKEN;
  cut(out.getContext("2d"), TOKEN, image, circle);
  let data;
  try { data = out.toDataURL("image/png"); } catch { throw new Error("That picture came from another site and can't be used directly; save it and drop the file instead."); }
  const w = image.naturalWidth;
  return call(projectId, "token", { data_base64: data, circle: { x: circle.x / w, y: circle.y / w, r: circle.r / w } });
}

async function save() {
  if (!view?.pic) return;
  const button = $("pic-save");
  button.disabled = true;
  try {
    if (view.pic.fresh) await savePicture(view.projectId, view.pic.src);
    await saveToken(view.projectId, view.pic.image, view.circle);
    const done = view.onSaved;
    view.dialog.close();
    await done?.();
    toast("ok", "Picture and token saved", "The table shows the token on this character.");
  } catch (error) {
    status(error.message);
    button.disabled = false;
  }
}

async function remove() {
  try {
    await call(view.projectId, "token", null, "DELETE");
    await call(view.projectId, "picture", null, "DELETE");
    const done = view.onSaved;
    view.dialog.close();
    await done?.();
    toast("ok", "Picture and token removed", "");
  } catch (error) {
    status(error.message);
  }
}
