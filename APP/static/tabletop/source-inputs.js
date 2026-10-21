// Owner/GM declarations stay separate from actor/model action selection.
// No form is submitted by default, including during automatic turns.
//
// A live table keeps committing while a player writes private details, so a
// declaration always carries the state version it was read at. When that
// version is stale the server refuses it; this form then re-reads the current
// forms, keeps the text the player already typed, and asks them to confirm
// again against the current bearer and turn. It never resubmits by itself and
// never rebinds old text to a different turn.
export async function openSourceInputs({api, matchId, doc = document, onSaved}) {
  const path = `/api/tabletop/matches/${encodeURIComponent(matchId)}/source-inputs`;
  let data = await api(path);
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
    // Values live in the inputs, so keeping the form in place preserves typed text
    // across a stale refresh; only the state version and availability update.
    let live = spec; let version = data.state_version;
    const refresh = async () => {
      data = await api(path);
      version = data.state_version;
      return data.forms.find(row => row.source_id === spec.source_id && row.actor_id === spec.actor_id);
    };
    form.addEventListener('submit', async event => {
      event.preventDefault(); save.disabled = true; status.textContent = '';
      const values = Object.fromEntries(new FormData(form));
      try {
        await api(path, {body: {source_id: live.source_id, actor_id: live.actor_id,
          expected_state_version: version, values}});
        dialog.close(); dialog.remove(); await onSaved?.();
      } catch (error) {
        if (error.code === 'TABLETOP_STALE') {
          try {
            const current = await refresh();
            if (!current) {
              status.textContent = 'This character can no longer record this declaration this fight. '
                + 'Your text is kept above in case the fight changes back.';
              return;  // save stays disabled: nothing to record for this fighter now
            }
            live = current;
            status.textContent = 'The fight moved on. Your text is kept — check it, then choose '
              + '“Record this private declaration” again to confirm it for the current turn.';
          } catch (refreshError) { status.textContent = refreshError.message; }
          save.disabled = false;
          return;
        }
        status.textContent = error.message; save.disabled = false;
      }
    });
    dialog.appendChild(form);
  }
  const close = doc.createElement('button'); close.textContent = 'Close';
  close.addEventListener('click', () => {dialog.close(); dialog.remove();});
  dialog.appendChild(close); doc.body.appendChild(dialog); dialog.showModal();
}
