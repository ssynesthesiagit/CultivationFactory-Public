// Build one pre-fight choice row. Kept separate so the rendered title can be
// checked without launching a browser or initializing the tabletop application.
export function createPrefightRow(option, cost, documentRef = document) {
  const row = documentRef.createElement("label");
  row.className = "tt-prefight-row";
  const tick = documentRef.createElement("input");
  tick.type = "checkbox";
  const text = documentRef.createElement("span");
  text.textContent = `${option.name} · ${cost} · ${option.duration}`;
  if (option.description) row.title = `${option.name} (${cost}; ${option.duration})\n\n${option.description}`;
  row.append(tick, text);
  return {row, tick};
}
