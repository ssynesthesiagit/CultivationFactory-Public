// The server owns selection state; every view uses the same accent and explicit tag.
export function markActive(element, active) {
  element.classList.toggle("is-choice-active", active === true);
  const old = element.querySelector(".choice-active-tag");
  if (active !== true) { old?.remove(); return; }
  if (old) return;
  const tag = element.ownerDocument.createElement("span");
  tag.className = "choice-active-tag";
  tag.textContent = "Active";
  (element.querySelector(".arow-flags") || element.querySelector("b") || element.querySelector("span") || element).appendChild(tag);
}
