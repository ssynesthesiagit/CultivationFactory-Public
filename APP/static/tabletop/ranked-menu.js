// Shared slot contract from combat/menu_rank.py. No legality or scoring in UI.
import {movementVerb, routeText} from './flight-ui.js?v=rel6-2';
import {ECONOMY_SLOTS, economySlot} from './action-economy.js';
import {sourceRankId, rankedIds} from './assisted-menu.js';
const movementDetail = move => `${routeText(move)}${move.hazard_exposure ? ' · Warning: this route crosses a known hazard.' : ''}`;
export function slotRows(menu) {
  const groups = menu.actions || [];
  const rowsFor = slot => groups.filter(group => economySlot(group.economy) === slot).flatMap(group =>
    group.lazy ? [{id: sourceRankId(group), group, label: group.label,
      detail: [group.cost_label, 'Check targets before confirming'].filter(Boolean).join(' · ')}] :
    group.options.map(option => ({id: option.candidate_id, group, option,
      label: group.label, detail: [option.label, group.cost_label].filter(Boolean).join(' · ')})));
  return {
    Movement: (menu.moves || []).map(move => ({id: move.candidate_id, move,
      label: `${movementVerb(move)} to (${move.destination.x}, ${move.destination.y}), height ${(move.destination.z ?? 0) * 5} ft`,
      detail: movementDetail(move)})).concat(rowsFor('Movement')),
    ...Object.fromEntries([...new Set(Object.values(ECONOMY_SLOTS))].filter(slot => slot !== 'Movement').map(slot =>
      [slot, rowsFor(slot)])),
  };
}

export function renderRankedMenu(menu, {doc = document, onAct, onMove, onSource, onPreviewMove}) {
  const root = doc.createElement('div');
  root.className = 'tt-ab-groups';
  for (const [slot, rows] of Object.entries(slotRows(menu))) {
    if (!rows.length && !['Movement', 'Action', 'Bonus action'].includes(slot)) continue;
    const byId = new Map(rows.map(row => [row.id, row]));
    const ranked = rankedIds(menu, slot).map(id => byId.get(id)).filter(Boolean).slice(0, 5);
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
      button.addEventListener('click', async () => {
        if (button.disabled) return;
        if (row.group && !row.option) {
          button.disabled = true;
          try {
            const expanded = await onSource(row.group);
            if (!expanded) return;
            const options = expanded.options || [];
            if (!options.length) { detail.textContent = 'No legal targets right now. Choose another action.'; return; }
            for (const option of options) add({id: option.candidate_id, group: expanded, option,
              label: `Confirm ${expanded.label}`, detail: [option.label, expanded.cost_label].filter(Boolean).join(' · ')});
            button.remove();
          } catch (error) { detail.textContent = error.message; }
          finally { button.disabled = false; }
          return;
        }
        if (row.move?.deferred_route && !row.move.route_checked) {
          button.disabled = true;
          try {
            if (!await onPreviewMove(row.move)) return;
            label.textContent = `Confirm ${row.label}`;
            detail.textContent = movementDetail(row.move);
            button.dataset.tip = detail.textContent;
          } catch (error) { detail.textContent = error.message; }
          finally { button.disabled = false; }
          return;
        }
        return row.move ? onMove(row.move) : onAct(row.id);
      });
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
