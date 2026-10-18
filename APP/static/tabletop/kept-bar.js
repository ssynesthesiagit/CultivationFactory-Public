// FD-6 option B (owner-confirmed 2026-10-18: "it still reloads the menu when you select something that modifies a
// talent or something and doesnt change the menu at all"). After a free choice, tabletop.js redraws the action bar
// into a detached footer and keeps the live buttons when both draw the same controls. These helpers do the compare
// and the in-place copy of the only things a free choice can change without changing the controls: the selection
// marker (active.js markActive) and an Options button's "now" detail (title and small text).
import {markActive} from "./active.js?v=c1-4";

// Everything a bar draws, minus the parts a free choice may change in place.
function stripped(root) {
  const clone = root.cloneNode(true);
  clone.querySelectorAll(".choice-active-tag").forEach(node => node.remove());
  clone.querySelectorAll(".is-choice-active").forEach(node => node.classList.remove("is-choice-active"));
  clone.querySelectorAll("[data-option-family]").forEach(node => {
    node.removeAttribute("title");
    const small = node.querySelector("small");
    if (small) small.textContent = "";
  });
  return clone;
}

export function barSignature(root) {
  return stripped(root).innerHTML;
}

// Copy the selection and the Options detail of `probe` (drawn from the new state) onto `live`.
// Call only when barSignature(live) === barSignature(probe): the buttons then pair up by position.
export function copySelection(live, probe) {
  const liveButtons = [...live.querySelectorAll("button")];
  const probeButtons = [...probe.querySelectorAll("button")];
  liveButtons.forEach((node, index) => {
    const other = probeButtons[index];
    if (!other) return;
    const on = other.classList.contains("is-choice-active");
    if (node.classList.contains("is-choice-active") !== on) markActive(node, on);
    if (node.dataset.optionFamily !== undefined) {
      node.title = other.title;
      const small = node.querySelector("small"), otherSmall = other.querySelector("small");
      if (small && otherSmall) small.textContent = otherSmall.textContent;
    }
  });
}
