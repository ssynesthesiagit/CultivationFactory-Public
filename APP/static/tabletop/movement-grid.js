// Expand compact server endpoint quotes only at the browser presentation edge.
// These local handles are never submitted as candidate IDs. Only the desktop table
// asks for compact states (tabletop.js); /play and other clients receive full moves.
// A row is [x, y, z, cost_ft, movement_mode, can_jump_down, known_hazard].
export function compactStatePath(path) {
  if (!/^\/api\/tabletop\/matches\/[^/]+\/state(?:\?|$)/.test(path) || /[?&]compact=/.test(path)) return path;
  return path + (path.includes('?') ? '&' : '?') + 'compact=true';
}

export function expandMovementGrid(menu) {
  if (!menu?.movement_grid) return menu;
  let rows = menu.movement_grid;
  if (rows.format === 'layers-v1' || rows.format === 'layers-v2') {
    const withHazards = rows.format === 'layers-v2';
    rows = rows.layers.flatMap(layer => {
      const [z, cost, mode, drop] = layer;
      const hazard = withHazards ? layer[4] : false;
      const cells = layer[withHazards ? 5 : 4];
      const quotes = [];
      for (let i = 0; i < cells.length; i += 2) quotes.push([cells[i], cells[i + 1], z, cost, mode, drop, hazard]);
      return quotes;
    });
    const priority = {walk: 0, fly: 1, climb: 2, jump: 3, jump_down: 4};
    rows.sort((a, b) => a[3] - b[3] || (priority[a[4]] ?? 5) - (priority[b[4]] ?? 5));
  }
  return {...menu, moves: rows.map(([x, y, z, cost, mode, drop, hazard], index) => ({
    candidate_id: `route:${index}`, destination: {x, y, z}, cost_ft: cost,
    movement_mode: mode, can_jump_down: drop, hazard_exposure: Boolean(hazard), deferred_route: true, path: [],
  }))};
}
