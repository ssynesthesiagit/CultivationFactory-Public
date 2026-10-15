// Owner/GM declarations stay separate from actor/model action selection.
// No form is submitted by default, including during automatic turns.
export async function openSourceInputs({api, matchId, doc = document, onSaved}) {
  const path = `/api/tabletop/matches/${encodeURIComponent(matchId)}/source-inputs`;
  const data = await api(path);
  const dialog = doc.createElement('dialog');
  const heading = doc.createElement('h2');
  heading.textContent = 'Private scene and character declarations';
  dialog.appendChild(heading);
  if (!data.forms.length) {
    const empty = doc.createElement('p');
    empty.textContent = 'No character in this fight needs a source declaration.';
    dialog.appendChild(empty);
  }
  for (const spec of data.forms) {
    const form = doc.createElement('form');
    const title = doc.createElement('h3'); title.textContent = spec.label;
    const description = doc.createElement('p'); description.textContent = spec.description;
    form.append(title, description);
    for (const field of spec.fields) {
      const label = doc.createElement('label'); label.textContent = field.label;
      const input = doc.createElement(field.options.length ? 'select' : 'textarea');
      input.name = field.name; input.required = true;
      if (field.options.length) {
        const empty = doc.createElement('option'); empty.value = ''; empty.textContent = 'Choose…';
        input.appendChild(empty);
        for (const value of field.options) {
          const option = doc.createElement('option'); option.value = value; option.textContent = value;
          input.appendChild(option);
        }
      } else input.maxLength = 2000;
      label.appendChild(input); form.appendChild(label);
    }
    const save = doc.createElement('button'); save.textContent = 'Record this private declaration';
    save.type = 'submit'; form.appendChild(save);
    const status = doc.createElement('p'); status.setAttribute('role', 'status'); form.appendChild(status);
    form.addEventListener('submit', async event => {
      event.preventDefault(); save.disabled = true;
      try {
        const values = Object.fromEntries(new FormData(form));
        await api(path, {body: {source_id: spec.source_id, actor_id: spec.actor_id,
          expected_state_version: data.state_version, values}});
        dialog.close(); dialog.remove(); await onSaved?.();
      } catch (error) { status.textContent = error.message; save.disabled = false; }
    });
    dialog.appendChild(form);
  }
  const close = doc.createElement('button'); close.textContent = 'Close';
  close.addEventListener('click', () => {dialog.close(); dialog.remove();});
  dialog.appendChild(close); doc.body.appendChild(dialog); dialog.showModal();
}
