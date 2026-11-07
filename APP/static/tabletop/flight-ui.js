// Flight presentation consumes engine-issued routes. It never prices or grants movement.
import {creatureHeightFt, onRoof, roofLevelsAt} from './roof-regions.js?v=rel6-2';

export function heightFeet(actor) {
  return actor ? (actor.altitude_ft ?? creatureHeightFt(actor)) : 0;
}

// The height picker starts at the creature's current height (owner 2026-10-12), in 5-ft levels.
// Table rows carry altitude_ft without position.z, so read the height, not z.
export function startHeightLevel(actor) {
  return Math.round(heightFeet(actor) / 5);
}

// Current height stays separate from the destination selected for the next move.
export function heightControlText(actor, chosen, flying) {
  return {
    caption: flying ? "Fly to height:" : "Move to height:",
    current: `Now ${heightFeet(actor)} ft`,
    tip: `${flightText(actor) || "Height: 0 ft above the battlefield floor"}. Choose a height, then a blue square. Route cost appears on hover. Selected destination: ${chosen * 5} ft. Roof levels are marked; each route spends the movement shown on hover.`,
  };
}

// Board data already respects viewer visibility; decorations follow that token.
export function altitudeBadge(data) {
  return data.altitudeFt > 0 && !data.hidden
    ? `↑${data.altitudeFt} ft` : "";
}

export function flightText(actor, map = null) {
  const height = actor?.altitude_ft ?? heightFeet(actor);
  const speed = actor?.fly_speed_ft ?? 0;
  if (!speed && !height) return "";
  const roof = map ? onRoof(map, actor) : actor?.on_roof === true;
  return (roof ? `Standing on the roof (${height} ft)` : `Height: ${height} ft above the battlefield floor`) + (speed
    ? ` · Fly speed: ${speed} ft${actor.hover ? " (can hover)" : ""}` : " · No fly speed");
}

export function heightOptions(moves, current = 0, roofLevels = []) {
  return [...new Set([current, ...roofLevels, ...moves.map(row => row.destination.z ?? 0)])].sort((a, b) => a - b);
}

export {roofLevelsAt};

export function movementVerb(move) {
  const mode = move?.movement_mode ?? move?.intent?.movement_mode ?? move?.payload?.movement_mode;
  return mode === 'climb' ? 'Climb' : mode === 'jump_down' ? 'Jump down' : mode === 'fly' ? 'Fly' : 'Move';
}

export function routeText(move, height = move.destination.z ?? 0) {
  const mode = movementVerb(move);
  if (mode === 'Jump down') return `Jump down from height ${height * 5} ft. The route to the edge costs ${move.cost_ft} ft of movement.`
    + ' Fall to the first support below. Falling can cause damage and knock you prone.';
  return `${mode} to height ${height * 5} ft above the battlefield floor. Costs ${move.cost_ft} ft of movement.`
    + (mode === 'Climb' ? ' The quoted cost includes climbing.' : '');
}

export function movementControl(flying, current, canJumpDown, onChange) {
  const label = document.createElement('label');
  label.className = 'tt-flight-control tt-movement-control';
  const caption = document.createElement('span');
  caption.textContent = 'Movement: ';
  label.appendChild(caption);
  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Movement mode');
  for (const [value, text] of [['native', flying ? 'Move / Fly' : 'Move'], ['jump_down', 'Jump down']]) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    option.disabled = value === 'jump_down' && !canJumpDown;
    select.appendChild(option);
  }
  select.value = current;
  select.addEventListener('change', () => onChange(select.value));
  label.appendChild(select);
  label.title = 'Move normally, or deliberately step off the roof and fall. Jump down is available only for the routes the fight offers.';
  return label;
}

export function movesAtHeight(moves, height) {
  return moves.filter(row => (row.destination.z ?? 0) === height);
}

export function heightMovement(explanation, moves, height) {
  if (!explanation) return null;
  const destinations = Object.fromEntries(Object.entries(explanation.destinations || {}).map(([key, card]) =>
    [key, {...card, available: false, ...(height ? {reasons: [], explained_refusal: false} : {})}]));
  for (const move of movesAtHeight(moves, height)) {
    const key = `${move.destination.x},${move.destination.y}`;
    // Ground diagnostics describe walking, not the air above the same square.
    // Keep the service's legal-ground cost explanations alongside the route quote.
    const groundCard = height === 0 ? explanation.destinations?.[key] : null;
    const reasons = groundCard?.available ? (groundCard.reasons || []) : [];
    destinations[key] = {...groundCard, available: true, explained_refusal: false, reasons: [...reasons, {message: routeText(move, height)}]};
  }
  return {...explanation, destinations};
}

// Append a movement note to a control's shared hover card (data-tip + aria-description) instead of a visible paragraph:
// wrapped text in the narrow Move group stretched the whole action bar (owner 2026-10-13).
export function appendTip(control, text) {
  const target = control?.querySelector?.('select') || control?.querySelector?.('button');
  if (!target || !text) return null;
  const tip = [target.dataset.tip, text].filter(Boolean).join(' ');
  target.dataset.tip = tip;
  target.setAttribute('aria-description', tip);
  return target;
}

export function heightControl(moves, current, flying, onChange, actor = {position: {z: current}}, roofLevels = []) {
  const text = heightControlText(actor, current, flying);
  const label = document.createElement("label");
  label.className = "tt-flight-control";
  const caption = document.createElement("span");
  caption.textContent = text.caption;
  label.appendChild(caption);
  const select = document.createElement("select");
  select.setAttribute("aria-label", flying ? "Fly to height" : "Move to height");
  select.dataset.tip = text.tip;
  select.setAttribute("aria-description", text.tip);
  for (const z of heightOptions(moves, current, roofLevels)) {
    const option = document.createElement("option");
    option.value = String(z);
    option.textContent = `${z * 5} ft${roofLevels.includes(z) ? ' · roof' : ''}`;
    select.appendChild(option);
  }
  select.value = String(current);
  select.addEventListener("change", () => onChange(Number(select.value)));
  label.appendChild(select);
  const now = document.createElement("small");
  now.className = "tt-flight-now";
  now.textContent = text.current;
  label.appendChild(now);
  return label;
}
