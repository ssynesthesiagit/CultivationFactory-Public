// Phone presentation only. The server owns all rules, legal candidates and perception.
import {resolveViewerIdentity, isPrimaryFighter} from '../tabletop/viewer-identity.js';
import {fogViewers} from '../tabletop/fog_view.js';
import {perceivedCells, tokenHiddenByFog, centerlineTerrain} from '../tabletop/vision.js';
import {movementVerb, routeText} from '../tabletop/flight-ui.js';
import {sourceRankId, rankedIds} from '../tabletop/assisted-menu.js';

export function playerView(binding, state, seats) {
  // /play never accepts a stored GM binding.
  const roster = state?.presentation?.actors || [];
  const view = resolveViewerIdentity(binding?.role === 'player' ? binding : null, roster, seats);
  const owned = view.ready ? roster.filter(view.isOwned) : [];
  const viewers = fogViewers('own', roster, {owned});
  const bf = state?.presentation?.battlefield || {};
  const seen = perceivedCells(bf.width_squares || 0, bf.height_squares || 0, viewers, state?.fog_perception || {});
  return {...view, viewers, seen, visible: actor => !!actor && view.ready && viewers.length > 0
    && !tokenHiddenByFog(actor, viewers, state?.fog_perception || {}, true)};
}

export function eligibleFighters(state, seats) {
  return (state?.presentation?.actors || []).filter(actor => isPrimaryFighter(actor)
    && playerView({version: 1, role: 'player', actor_ids: [actor.entity_id]}, state, seats).isOwned(actor));
}

export function ownedMenu(state, view) {
  const menu = state?.menu;
  return view.ready && menu?.manual && view.isOwned(menu.actor_id) && !state.presentation?.terminal ? menu : null;
}

export function ownPrompt(pending, view) {
  return view.ready && view.isOwned(pending?.reaction?.context?.reactor_id);
}

export const decisionKey = menu => JSON.stringify([menu?.actor_id, menu?.decision_id, menu?.state_version]);
export const promptKey = pending => pending ? JSON.stringify([pending.method, pending.request, pending.reactions, pending.reaction]) : '';

export function mapFromState(state) {
  const bf = state.presentation.battlefield, table = state.map || {}, bg = table.background || {}, scale = table.scale || 1;
  const regions = bf.terrain_regions || [];
  const cellsOf = name => regions.filter(r => r.terrain_type === name).flatMap(r => r.cells || []);
  return {width: bf.width_squares, height: bf.height_squares,
    background: bg.asset ? {url: `/api/tabletop/map-assets/${encodeURIComponent(bg.asset)}`, opacity: (bg.opacity_pct ?? 100) / 100, fit: bg.fit}
      : {url: null, style: bg.style || 'flagstone', seed: bg.seed || 1, opacity: 1},
    display: {gridOpacity: (table.display?.grid_opacity_pct ?? 35) / 100, detail: (table.display?.detail_pct ?? 100) / 100,
      gridColor: table.display?.grid_color, blend: (table.display?.blend_pct ?? 0) / 100},
    walls: (table.walls || []).map(w => ({...w, points: w.points.map(([x,y]) => [x / scale,y / scale])})),
    openings: table.openings || [], objects: table.objects || [], roofs: table.roofs, floors: table.floors || [],
    ruleTerrain: table.terrain || [], materials: table.materials || [], ground: state.ground || {}, trees: table.trees || [], decor: table.decor || [],
    centerlineCells: centerlineTerrain(regions, state.terrain_occlusion_policy),
    cells: {blocked: bf.blocked_cells || [], cover: bf.cover_cells || [], hazard: bf.hazard_cells || [], difficult: bf.difficult_cells || [],
      sight: cellsOf('SIGHT_BLOCKED'), sightGhost: cellsOf('SIGHT_BLOCKED').filter(c => !(state.presentation.zones || []).some(z =>
        z.trigger_profile?.visual?.material === 'bamboo' && (z.affected_cells || []).some(p => p.x === c.x && p.y === c.y)))}};
}

// A tap narrows candidates, never guesses among different routes, heights or augments.
export function optionsAt(options, cell, tokenId = null) {
  if (!cell && !tokenId) return [];
  return options.filter(option => (tokenId && option.target_ids?.includes(tokenId))
    || (cell && [option.area?.center, option.destination].some(p => p && p.x === cell.x && p.y === cell.y)));
}

export function optionText(option, state, view) {
  // Destination/area options can carry blind-target labels too. Preserve their
  // effects without naming creatures outside this viewer's perception.
  let label = option.label || '';
  for (const actor of state?.presentation?.actors || []) if (!view.visible(actor))
    label = label.replaceAll(actor.display_name, 'Unseen creature');
  label = label.replace(/(?:actor:|object:|act:)[\w.:-]+/g, 'target');
  if (option.destination) {
    const p = option.destination;
    if (option.cost_ft == null && !option.movement_mode && !option.intent?.movement_mode && !option.payload?.movement_mode)
      return `Square ${p.x + 1}, ${p.y + 1} · ${(p.z || 0) * 5} ft high${label ? ` · ${label}` : ''}`;
    const path = option.path || option.canonical_path || [];
    const route = path.length ? ` Route: ${path.map(c => `square ${c.x + 1}, ${c.y + 1}${c.z ? ` at ${c.z * 5} ft` : ''}`).join(' → ')}.` : '';
    return `${movementVerb(option)} to square ${p.x + 1}, ${p.y + 1}. ${routeText(option)}${route}${option.hazard_exposure ? ' Warning: this route crosses a known hazard.' : ''}`;
  }
  if (option.area?.center) return `Centre square ${option.area.center.x + 1}, ${option.area.center.y + 1} · ${label || 'Use area'}`;
  return label || 'Use';
}

// Same ordered consent contract as the table: decline earlier alternatives,
// select this one, and let resolution discover any subsequent decisions.
export function reactionMenuAnswers(prompt, index, answer = {selection: 'DECLINE'}) {
  const rows = prompt.alternatives || [prompt];
  return rows.slice(0, index < 0 ? rows.length : index + 1).map((row, i) =>
    ({...row.context, ...(i === index ? answer : {selection: 'DECLINE'})}));
}

// General spatial-choice snapshot formatter, following the table's descriptions.
// Only supplied snapshot tokens are used; the live roster cannot add unseen names.
export function spaceOptionText(option, map) {
  if (!map || !option.cell) return option.label;
  const cells = token => token.cells?.length ? token.cells : [token.position];
  const chooser = map.tokens.find(t => t.id === map.chooser_id);
  const large = chooser && cells(chooser).length > 1;
  const own = chooser && cells(chooser).some(c => c.x === option.cell.x && c.y === option.cell.y);
  const offset = (n, minus, plus) => n ? `${Math.abs(n)} square${Math.abs(n) === 1 ? '' : 's'} ${n < 0 ? minus : plus}` : '';
  const direction = [offset(option.cell.y - map.origin.y, 'north', 'south'), offset(option.cell.x - map.origin.x, 'west', 'east')].filter(Boolean).join(' and ');
  let where = direction ? `${direction} of ${large ? 'your current top-left square' : 'you'}${own ? ', currently part of your space' : ''}`
    : large ? 'your current top-left square' : 'your current square';
  const distance = t => Math.min(...cells(t).map(c => Math.max(Math.abs(c.x - option.cell.x), Math.abs(c.y - option.cell.y))));
  const others = map.tokens.filter(t => t.id !== map.chooser_id);
  const occupied = others.filter(t => distance(t) === 0), nearby = others.filter(t => distance(t) === 1);
  where += occupied.length ? `, occupied by ${occupied.map(t => t.name).join(', ')}` : nearby.length ? `, beside ${nearby.map(t => t.name).join(', ')}` : '';
  const coordinates = new RegExp(`(?<![\\d-])(?:cell:)?${option.cell.x}\\s*,\\s*${option.cell.y}(?!\\d)`, 'g');
  const label = !option.label || option.label === option.id ? where : option.label.replace(coordinates, where);
  return `Square ${option.cell.x + 1}, ${option.cell.y + 1} · ${label === option.label ? `${where}: ${label}` : label}`;
}

import {variantActionLabel} from '../tabletop/attack-groups.js?v=variants1';

// Server ranking is already constrained to the acting creature's knowledge.
// Keep the complete menu untouched; a proposal is only a shortcut to one candidate.
export function suggestedOption(menu, state, view) {
  const known = option => (!view || (option.target_ids || []).every(id =>
    view.visible(state.presentation.actors.find(a => a.entity_id === id))))
    && (!view || !option.destination || view.seen[option.destination.y * state.presentation.battlefield.width_squares + option.destination.x]);
  for (const slot of ['Action', 'Bonus action', 'Movement']) for (const id of rankedIds(menu, slot)) {
    for (const group of menu.actions || []) {
      if (group.lazy && sourceRankId(group) === id) return {group, label: variantActionLabel(group), unresolved: true};
      const option = group.options.find(o => o.candidate_id === id);
      if (option && (!group.expanded_from_lazy || known(option))) return {option, group, label: variantActionLabel(group)};
    }
    const option = menu.moves?.find(o => o.candidate_id === id);
    if (option) return {option, label: movementVerb(option)};
  }
  // Ranking is optional (CF_EMBED_MENU=0). A missing ranking must not strand
  // Assisted players. Preserve server order and propose only perceived targets;
  // this is a legal fallback, not a new client-side combat scoring policy.
  for (const group of menu.actions || []) {
    if (group.lazy) return {group, label:variantActionLabel(group), unresolved:true, fallback:true};
    const option = group.options.find(o => known(o));
    if (option) return {option, group, label:variantActionLabel(group), fallback:true};
  }
  const move = menu.moves?.find(known);
  if (move) return {option:move,label:movementVerb(move),fallback:true};
  // End turn remains confirmable even when no perceived action can be proposed.
  if (menu.end_turn) return {option:{candidate_id:menu.end_turn,label:'Finish your turn'},label:'End turn',fallback:true};
  return null;
}

export function reactionAnswer(prompt, ids) {
  const choice = prompt.choice;
  const minimum = choice?.minimum ?? 1, maximum = choice?.maximum ?? 1;
  if (choice && (ids.length < minimum || ids.length > maximum || new Set(ids).size !== ids.length
      || ids.some(id => !choice.options.some(o => o.id === id)))) throw new Error(`Choose ${minimum}–${maximum} options.`);
  return {...prompt.context, selection: 'USE', ...(choice ? {option_ids: ids} : {})};
}

// Spatial (map_pick) reaction choices: the phone answers by tapping a legal square.
export function mapPickOptions(pending, view) {
  if (!pending || !ownPrompt(pending, view)) return null;
  const choice = pending.reaction?.choice;
  if (!choice?.map_pick || !Array.isArray(choice.options)) return null;
  return choice.options.filter(option => option.cell);
}

export function mapPickAnswer(pending, ids) {
  return reactionAnswer(pending.reaction, ids);
}

export function pendingSubmission(pending, answer, after) {
  const {movement_path, ...request} = pending.request;
  return {endpoint: pending.method === 'auto_step' ? 'auto-step' : movement_path ? 'movement-path/commit' : 'act',
    body: {...request, ...(movement_path ? {waypoints: movement_path} : {}), after, reactions: [...(pending.reactions || []), ...(Array.isArray(answer) ? answer : [answer])]}};
}
