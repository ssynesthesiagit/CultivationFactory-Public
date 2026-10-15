// Server-qualified facts belonging to the bound fighter, regardless of fog mode.
export function renderObserverInformation(host, actors, information, ownedIds) {
  const owned = new Set(ownedIds);
  const rows = actors.filter(actor => owned.has(actor.entity_id))
    .flatMap(actor => (information?.[actor.entity_id] || [])
      .filter(row => typeof row.text === 'string' && row.text.trim())
      .map(row => ({name: actor.display_name, text: row.text +
        (Number.isInteger(row.approximate_distance_ft) ? ` About ${row.approximate_distance_ft} feet away.` : '')})));
  if (!rows.length) return;
  const doc = host.ownerDocument;
  const section = doc.createElement('section');
  section.className = 'tt-observer-information';
  section.setAttribute('aria-label', 'What your fighters sense');
  const title = doc.createElement('h3');
  title.textContent = 'What your fighters sense';
  section.appendChild(title);
  for (const row of rows) {
    const line = doc.createElement('p');
    line.textContent = `${row.name}: ${row.text}`;
    section.appendChild(line);
  }
  host.appendChild(section);
}
