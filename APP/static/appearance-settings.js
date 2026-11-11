/* Settings > Appearance (owner 2026-10-04, OPUSUI1).
 *
 * Changes apply to the whole page at once as a live preview; "Save appearance" keeps them on this
 * device (window.TianxiaAppearance from /static/appearance-boot.js does the storing and applying).
 * "Undo changes" returns to the last saved look. Text that becomes hard to read (below the WCAG
 * 4.5:1 contrast ratio) is listed under the preview in plain words.
 */
(function () {
  "use strict";
  var A = window.TianxiaAppearance;
  var screen = document.getElementById("screen-settings");
  if (!A || !screen) return;

  var MIN_CONTRAST = 4.5;
  var draft = A.load();
  var saved = JSON.stringify(draft);
  var failed = null;  // the look the browser last refused to store (storage full or blocked)

  var cards = Array.prototype.slice.call(screen.querySelectorAll(".style-card"));
  var pickers = Array.prototype.slice.call(screen.querySelectorAll("input[data-colour]"));
  var fontSelect = document.getElementById("appearanceHeadingFont");
  var sizeSelect = document.getElementById("appearanceTextSize");
  var motionBox = document.getElementById("appearanceReduceMotion");
  var contrastBox = document.getElementById("appearanceContrast");
  var saveState = document.getElementById("appearanceSaveState");
  var saveButton = document.getElementById("appearanceSave");
  var undoButton = document.getElementById("appearanceUndo");

  // What each checked pair means to a player.
  var PAIRS = [
    ["text", "bg", "Main text on the page background"],
    ["text", "panel", "Main text on panels"],
    ["muted", "panel", "Secondary text on panels"],
    ["muted", "bg", "Secondary text on the page background"],
    ["faint", "panel", "Small labels and hints on panels"],
    ["faint", "bg", "Small labels and hints on the page background"],
    ["muted", "tile", "Hints under a builder step when the pointer is over it"],
    ["on-accent", "accent", "Button text on the accent colour"],
    ["on-accent-soft", "accent", "Hints under the highlighted step on the accent colour"],
    ["accent-text", "panel", "Accent-coloured words on panels"],
    ["debuff-text", "debuff-bg", "Debuff labels (harmful conditions)"],
    ["buff-text", "buff-bg", "Buff labels (helpful effects)"]
  ];

  function render() {
    cards.forEach(function (card) {
      var on = card.dataset.style === draft.style;
      card.classList.toggle("is-active", on);
      card.setAttribute("aria-checked", on ? "true" : "false");
      card.tabIndex = on ? 0 : -1;
      var note = card.querySelector(".style-card-active");
      if (on && !note) {
        note = document.createElement("span");
        note.className = "style-card-active";
        note.textContent = "Active";
        card.appendChild(note);
      } else if (!on && note) note.remove();
    });
    var base = A.baseColours();
    pickers.forEach(function (input) {
      var key = input.dataset.colour;
      input.value = draft.custom[key] || base[key] || "#000000";
      input.closest(".colour-field").classList.toggle("is-custom", Boolean(draft.custom[key]));
    });
    fontSelect.value = draft.headingFont;
    sizeSelect.value = draft.textSize;
    motionBox.checked = draft.reduceMotion;
    renderContrast();
    var dirty = JSON.stringify(draft) !== saved;
    var stored = null;
    try { stored = localStorage.getItem(A.KEY); } catch (e) { /* storage blocked */ }
    var refused = dirty && failed === JSON.stringify(draft);
    saveState.textContent = refused
      ? "Couldn't save on this device: the browser refused to store it (its storage may be full or blocked). You see this look only until you leave or reload this page; other tabs and your next visit still use the saved look."
      : dirty ? "Not saved yet: other tabs and your next visit still use the saved look."
      : (stored ? "Saved on this device." : "Using the default style (Night Lacquer). Nothing saved yet.");
    saveState.classList.toggle("is-dirty", dirty);
    undoButton.disabled = !dirty;
  }

  function renderContrast() {
    var t = A.tokens();
    var problems = PAIRS.map(function (pair) {
      var ratio = A.contrast(t[pair[0]], t[pair[1]]);
      return { label: pair[2], ratio: ratio };
    }).filter(function (p) { return p.ratio && p.ratio < MIN_CONTRAST; });
    contrastBox.replaceChildren();
    contrastBox.classList.toggle("has-problems", problems.length > 0);
    if (!problems.length) {
      var ok = document.createElement("p");
      ok.className = "contrast-ok";
      ok.textContent = "Text is easy to read with these colours (main, secondary and small text, buttons, builder step hints, accent words, buff and debuff labels).";
      contrastBox.appendChild(ok);
      return;
    }
    var head = document.createElement("p");
    head.className = "contrast-warning";
    head.textContent = "Hard to read with these colours:";
    var list = document.createElement("ul");
    problems.forEach(function (p) {
      var li = document.createElement("li");
      li.textContent = p.label + " (contrast " + p.ratio.toFixed(1) + " to 1; aim for at least 4.5 to 1)";
      list.appendChild(li);
    });
    contrastBox.append(head, list);
  }

  function update(change) {
    change(draft);
    draft = A.apply(draft);
    render();
  }

  cards.forEach(function (card) {
    card.addEventListener("click", function () {
      update(function (d) { d.style = card.dataset.style; d.custom = {}; });
    });
    card.addEventListener("keydown", function (event) {
      var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      var next = cards[(cards.indexOf(card) + step + cards.length) % cards.length];
      next.click();
      next.focus();
    });
  });
  pickers.forEach(function (input) {
    input.addEventListener("input", function () {
      update(function (d) { d.custom[input.dataset.colour] = input.value.toLowerCase(); });
    });
  });
  document.getElementById("appearanceResetColours").addEventListener("click", function () {
    update(function (d) { d.custom = {}; });
  });
  fontSelect.addEventListener("change", function () { update(function (d) { d.headingFont = fontSelect.value; }); });
  sizeSelect.addEventListener("change", function () { update(function (d) { d.textSize = sizeSelect.value; }); });
  motionBox.addEventListener("change", function () { update(function (d) { d.reduceMotion = motionBox.checked; }); });
  saveButton.addEventListener("click", function () {
    draft = A.clean(draft);
    if (A.store(draft)) { saved = JSON.stringify(draft); failed = null; }
    else failed = JSON.stringify(draft);
    draft = A.apply(draft);
    render();
  });
  undoButton.addEventListener("click", function () {
    draft = A.apply(A.load());
    render();
  });
  // Saved from another tab (for example the table's style picker): show it here.
  window.addEventListener("storage", function (event) {
    if (event.key !== A.KEY) return;
    draft = A.load();
    saved = JSON.stringify(draft);
    render();
  });

  render();
})();
