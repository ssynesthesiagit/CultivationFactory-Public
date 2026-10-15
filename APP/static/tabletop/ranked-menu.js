// Shared slot contract from combat/menu_rank.py. No legality or scoring in UI.
import {movementVerb, routeText} from './flight-ui.js?v=rel6-2';
export function slotRows(menu) {
  const groups = menu.actions || [];
  return {
    Movement: (menu.moves || []).map(move => ({id: move.candidate_id, move,
      label: `${movementVerb(move)} to (${move.destination.x}, ${move.destination.y}), height ${(move.destination.z ?? 0) * 5} ft`,
      detail: `${routeText(move)}${move.hazard_exposure ? ' · known hazard' : ''}`})),
    Action: groups.filter(group => group.economy !== 'BONUS_ACTION').flatMap(group =>
      group.options.map(option => ({id: option.candidate_id, group, option,
        label: group.label, detail: [option.label, group.cost_label].filter(Boolean).join(' · ')}))),
    'Bonus action': groups.filter(group => group.economy === 'BONUS_ACTION').flatMap(group =>
      group.options.map(option => ({id: option.candidate_id, group, option,
        label: group.label, detail: [option.label, group.cost_label].filter(Boolean).join(' · ')}))),
  };
}

export function renderRankedMenu(menu, {doc = document, onAct, onMove}) {
  const root = doc.createElement('div');
  root.className = 'tt-ab-groups';
  for (const [slot, rows] of Object.entries(slotRows(menu))) {
    const byId = new Map(rows.map(row => [row.id, row]));
    const ranked = (menu.ranked_slots?.[slot] || []).map(id => byId.get(id)).filter(Boolean).slice(0, 5);
    const group = doc.createElement('div');
    group.className = 'tt-ab-group';
    const heading = doc.createElement('h3');
    heading.textContent = slot;
    group.appendChild(heading);
    const buttons = doc.createElement('div');
    buttons.className = 'tt-ab-buttons';
    const add = row => {
      const button = doc.createElement('button');
      button.type = 'button';
      button.className = 'tt-btn';
      const label = doc.createElement('b');
      label.textContent = row.label;
      const detail = doc.createElement('small');
      detail.textContent = row.detail;
      button.appendChild(label); button.appendChild(detail);
      button.dataset.tip = row.move ? row.detail : (row.group.description || row.detail);
      button.addEventListener('click', () => row.move ? onMove(row.move) : onAct(row.id));
      buttons.appendChild(button);
    };
    ranked.forEach(add);
    const shown = new Set(ranked.map(row => row.id));
    const rest = rows.filter(row => !shown.has(row.id));
    if (rest.length) {
      const more = doc.createElement('button');
      more.type = 'button';
      more.textContent = `More… (+${rest.length})`;
      more.addEventListener('click', () => { more.remove(); rest.forEach(add); });
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
