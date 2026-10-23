// Read-only table indicators. The caller supplies the same visibility decision
// as the map's fog; a hidden opponent's state never reaches these fragments.
export const concentrationHelp = "Concentration keeps an effect going for its duration. Normally you hold one effect at a time; starting another concentration effect ends it. Cultivation fighters can hold several effects, including copies of the same effect; duplicate bonuses do not stack. Older fights may limit how many you can hold; starting another at that limit ends the oldest. Taking damage calls for one Constitution saving throw: DC 10 or half the damage (rounded down), whichever is higher, up to DC 30. Failure ends the most recently started effect. Being incapacitated ends all your concentration effects. Each effect also ends when its duration runs out.";

function escape(text) {
  return String(text).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

export function concentrationLabel(actor, visible = true) {
  const effects = visible ? actor?.concentration_effects || [] : [];
  return effects.length ? `Concentrating on ${effects.join(", ")}` : "";
}

export function concentrationCard(actor, visible = true) {
  const label = concentrationLabel(actor, visible);
  return label ? `<div class="tt-sub tt-concentration-line" tabindex="0" data-tip="${escape(concentrationHelp)}">${escape(label)}</div>` : "";
}
