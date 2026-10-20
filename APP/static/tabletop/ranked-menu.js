// Shared slot contract from combat/menu_rank.py. No legality or scoring in UI.
import {movementVerb, routeText} from './flight-ui.js?v=rel6-2';
import {ECONOMY_SLOTS, economySlot} from './action-economy.js';
import {bindPress} from './kept-bar.js?v=speedreuse2-3';
export function slotRows(menu) {
  const groups = menu.actions || [];
  const rowsFor = slot => groups.filter(group => economySlot(group.economy) === slot).flatMap(group =>
    group.options.map(option => ({id: option.candidate_id, group, option,
      label: group.label, detail: [option.label, group.cost_label].filter(Boolean).join(' · ')})));
  return {
    Movement: (menu.moves || []).map(move => ({id: move.candidate_id, move,
      label: `${movementVerb(move)} to (${move.destination.x}, ${move.destination.y}), height ${(move.destination.z ?? 0) * 5} ft`,
      detail: `${routeText(move)}${move.hazard_exposure ? ' · known hazard' : ''}`})).concat(rowsFor('Movement')),
    ...Object.fromEntries([...new Set(Object.values(ECONOMY_SLOTS))].filter(slot => slot !== 'Movement').map(slot =>
      [slot, rowsFor(slot)])),
  };
}

export function renderRankedMenu(menu, {doc = document, onAct, onMove}) {
  const root = doc.createElement('div');
  root.className = 'tt-ab-groups';
  for (const [slot, rows] of Object.entries(slotRows(menu))) {
    if (!rows.length && !['Movement', 'Action', 'Bonus action'].includes(slot)) continue;
    const byId = new Map(rows.map(row => [row.id, row]));
    const ranked = (menu.ranked_slots?.[slot] || []).map(id => byId.get(id)).filter(Boolean).slice(0, 5);
    const group = doc.createElement('div');
    group.className = 'tt-ab-group';
    const heading = doc.createElement('h3');
    heading.textContent = slot;
    group.appendChild(heading);
    const buttons = doc.createElement('div');
    buttons.className = 'tt-ab-buttons';
    const makeButton = row => {
      const button = doc.createElement('button');
      button.type = 'button';
      button.className = 'tt-btn';
      const label = doc.createElement('b');
      label.textContent = row.label;
      const detail = doc.createElement('small');
      detail.textContent = row.detail;
      button.appendChild(label); button.appendChild(detail);
      button.dataset.tip = row.move ? row.detail : (row.group.description || row.detail);
      bindPress(button, () => row.move ? onMove(row.move) : onAct(row.id));
      return button;
    };
    ranked.forEach(row => buttons.appendChild(makeButton(row)));
    const shown = new Set(ranked.map(row => row.id));
    const rest = rows.filter(row => !shown.has(row.id));
    if (rest.length) {
      const more = doc.createElement('button');
      more.type = 'button';
      more.textContent = `More… (+${rest.length})`;
      // A kept bar copies this handler from the newest menu (copySelection) and runs it on the live button (`this`),
      // so the revealed rows go into the bar that holds that button and carry the newest candidate ids.
      bindPress(more, function () { const box = this.parentNode; this.remove(); rest.forEach(row => box.appendChild(makeButton(row))); });
      buttons.appendChild(more);
    }
    if (!rows.length) {
      const none = doc.createElement('small');
      none.textContent = 'No choices available in this slot.';
      buttons.appendChild(none);
    }
    group.appendChild(buttons); root.appendChild(group);
  }
  return root;
}
