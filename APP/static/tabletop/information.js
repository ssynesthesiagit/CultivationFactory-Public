// Only explicit owned observers contribute private findings. Fog allies and
// selected enemy tokens never become an information audience. Text is server
// authored from observer-entitled facts and is always inserted as textContent.
export function renderInformation(host, state, owned) {
  host.replaceChildren();
  for (const actor of owned) {
    const lines = (state?.observer_information || state?.fog_perception)?.[actor.entity_id]?.information_text || [];
    if (!lines.length) continue;
    const heading = host.ownerDocument.createElement('h3');
    heading.textContent = `${actor.display_name}: what you sense`;
    host.append(heading);
    for (const line of lines) {
      const paragraph = host.ownerDocument.createElement('p');
      paragraph.textContent = line;
      host.append(paragraph);
    }
  }
  host.hidden = !host.childNodes.length;
}
