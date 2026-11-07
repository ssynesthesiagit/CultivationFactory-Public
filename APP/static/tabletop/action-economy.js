// Mirror of combat/action_economy.py; parity is checked by the audit regression.
export const ECONOMY_SLOTS = {ACTION: 'Action', BONUS_ACTION: 'Bonus action', REACTION: 'Reaction',
  FREE: 'Free', MOVE: 'Movement', NONE: 'No action'};
export const ECONOMY_GROUPS = {ACTION: 'actions', BONUS_ACTION: 'bonus', REACTION: 'reactions',
  FREE: 'free', MOVE: 'movement', NONE: 'no_action'};
// The slot words a use prints for the economy it spent (mirror of combat/action_economy.py SPEND).
export const ECONOMY_SPEND = {ACTION: 'Action', BONUS_ACTION: 'Bonus Action', REACTION: 'Reaction'};
export const economySlot = economy => ECONOMY_SLOTS[economy] || 'Action';
export const economyLabel = economy => ECONOMY_SPEND[economy] || ECONOMY_SLOTS[economy] || 'Action';
export const spendClause = economy => (ECONOMY_SPEND[economy] ? `used your ${ECONOMY_SPEND[economy]}` : '');

// One builder for the three turn-economy pills on every surface (action bar, mini card,
// pop-out pip). Each pill says in words whether the slot is ready or spent, and Reaction is
// never dropped. Mirrors the engine's turn_state flags; presentation only.
export function economyPills(turn = {}) {
  const pill = (label, ready) => `<span class="tt-pill ${ready ? "is-ready" : "is-used"}"`
    + ` title="${label}: ${ready ? "ready" : "spent"}">${label}: ${ready ? "ready" : "used"}</span>`;
  return pill("Action", Boolean(turn.action)) + pill("Bonus Action", Boolean(turn.bonus_action))
    + pill("Reaction", Boolean(turn.reaction));
}

export function economySections(rows) {
  const sections = new Map();
  for (const row of rows) {
    const slot = economySlot(row.economy);
    if (!sections.has(slot)) sections.set(slot, []);
    sections.get(slot).push(row);
  }
  return [...sections];
}
