// Flight presentation consumes engine-issued routes. It never prices or grants movement.
export function heightFeet(actor) {
  return actor?.altitude_ft ?? (actor?.position?.z ?? 0) * 5;
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
    tip: `${flightText(actor) || "Height: 0 ft above the battlefield floor"}. Choose a height, then a blue square. Route cost appears on hover. Selected destination: ${chosen * 5} ft.`,
  };
}

// Board data already respects viewer visibility; decorations follow that token.
export function altitudeBadge(data) {
  return data.altitudeFt > 0 && !data.hidden && !data.item && !data.object
    ? `${data.altitudeFt} ft` : "";
}

export function flightText(actor) {
  const height = actor?.altitude_ft ?? heightFeet(actor);
  const speed = actor?.fly_speed_ft ?? 0;
  if (!speed && !height) return "";
  return `Height: ${height} ft above the battlefield floor` + (speed
    ? ` · Fly speed: ${speed} ft${actor.hover ? " (can hover)" : ""}` : " · No fly speed");
}

export function heightOptions(moves, current = 0) {
  return [...new Set([current, ...moves.map(row => row.destination.z ?? 0)])].sort((a, b) => a - b);
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
    destinations[key] = {...groundCard, available: true, explained_refusal: false, reasons: [...reasons, {message:
      `Move to height ${height * 5} ft above the battlefield floor. Costs ${move.cost_ft} ft of movement.`}]};
  }
  return {...explanation, destinations};
}

export function heightControl(moves, current, flying, onChange, actor = {position: {z: current}}) {
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
  for (const z of heightOptions(moves, current)) {
    const option = document.createElement("option");
    option.value = String(z);
    option.textContent = `${z * 5} ft`;
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
