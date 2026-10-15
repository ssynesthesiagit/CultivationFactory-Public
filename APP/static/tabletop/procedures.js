// Out-of-combat sheet procedures. Providers supply every legal choice and own
// all rules; this renderer never caps option lists or invents external facts.
export function createProcedures({h, fetchJson, post, reloadSheet, projectId, toast}) {
  let menus = [], providers = [];
  const root = h('section', {class: 'def-block', 'aria-label': 'Table studies and formula choices'});
  async function load() {
    try {
      const result = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(projectId())}/procedures`);
      menus = result.procedures;
      providers = (await fetchJson('/api/tabletop/providers')).providers;
      render();
    } catch (error) {
      root.replaceChildren(h('p', null, `Could not load table studies: ${error.message}`));
    }
    return root;
  }
  function render() {
    root.replaceChildren(...menus.map(menu => h('details', {open: true},
      h('summary', null, menu.name),
      h('p', {class: 'def-note'}, menu.check_requirement),
      h('p', {class: 'def-note'}, menu.payment_help),
      ...(menu.projects || []).map(p => h('p', null,
        `${p.discovery_id}: ${p.studied_minutes} of ${p.required_minutes} study minutes; ${p.status.replaceAll('_', ' ')}.` +
        (p.check ? ` Check ${p.check.total} against DC ${p.check_dc}.` : ''))),
      ...(menu.forms || []).map(spec => makeForm(menu, spec)))));
  }
  function makeForm(menu, spec) {
    const inputs = new Map();
    const form = h('form', {class: 'def-block'}, h('h4', null, spec.label));
    for (const field of spec.fields) {
      const input = field.type === 'select'
        ? h('select', {class: 'input', name: field.name},
            ...field.options.map(o => h('option', {value: o.value}, o.label)))
        : h('input', {class: 'input', name: field.name, type: field.type === 'integer' ? 'number' : 'text',
            min: field.minimum, max: field.maximum, step: field.type === 'integer' ? '1' : null,
            maxlength: field.type === 'integer' ? null : '500', required: !field.optional || null});
      inputs.set(field.name, input);
      form.append(h('label', null, field.label, input));
    }
    const confirmed = spec.gm ? h('input', {type: 'checkbox', required: true}) : null;
    if (confirmed) form.append(h('label', null, confirmed, ' GM: I confirm these physical-table facts and this decision.'));
    const output = h('p', {class: 'def-note', 'aria-live': 'polite'});
    const submit = h('button', {type: 'submit', class: 'btn btn-accent'}, 'Record');
    const preview = h('button', {type: 'button', class: 'btn'}, 'Preview without saving');
    const cancel = h('button', {type: 'button', class: 'btn'}, 'Cancel / clear');
    let requestId = null, signature = null;
    async function send(isPreview) {
      if (!form.reportValidity()) return;
      const payload = {...spec.defaults};
      for (const field of spec.fields) {
        const value = inputs.get(field.name).value;
        if (value === '' && field.optional) continue;
        payload[field.name] = field.type === 'integer' ? Number(value) : value;
      }
      // A declined reroll reports no new die. Preserve the original failed roll.
      if (payload.decision === 'decline') { delete payload.d20; delete payload.roll_provenance; }
      const nextSignature = JSON.stringify(payload);
      if (signature !== nextSignature) { signature = nextSignature; requestId = crypto.randomUUID(); }
      submit.disabled = preview.disabled = true;
      try {
        const result = await post('procedures', {namespace: menu.id, action: spec.action, payload,
          revision: menu.revision, request_id: requestId, gm: Boolean(confirmed?.checked), preview: isPreview});
        output.textContent = isPreview ? 'Preview only. Nothing saved. Record to apply, or Cancel to discard.' : 'Recorded.';
        if (!isPreview) { await reloadSheet(); await load(); }
        return result;
      } catch (error) {
        output.textContent = error.message;
        toast('error', 'Not recorded', error.message, 4200);
      } finally { submit.disabled = preview.disabled = false; }
    }
    form.addEventListener('submit', event => { event.preventDefault(); void send(false); });
    preview.addEventListener('click', () => void send(true));
    cancel.addEventListener('click', () => { form.reset(); output.textContent = 'Cancelled. Nothing saved.'; });
    form.append(submit, preview, cancel);
    if (spec.fields.some(f => f.type === 'select')) {
      const provider = h('select', {class: 'input', 'aria-label': 'Preparation seat'},
        h('option', {value: 'builtin'}, 'Built-in AI'),
        ...providers.map(p => h('option', {value: p.id}, p.label || p.model || 'Model')));
      const suggest = h('button', {type: 'button', class: 'btn'}, 'Ask preparation seat to choose');
      suggest.addEventListener('click', async () => {
        suggest.disabled = true;
        try {
          const result = await post('procedures/suggest', {namespace: menu.id, form_id: spec.id,
            revision: menu.revision, provider_id: provider.value});
          for (const [name, value] of Object.entries(result.values)) inputs.get(name).value = value;
          output.textContent = 'Seat choices filled in. Supply any actual roll or GM facts, then Record.';
        } catch (error) { output.textContent = error.message; }
        finally { suggest.disabled = false; }
      });
      form.append(provider, suggest);
    }
    form.append(output);
    return form;
  }
  return {root, load};
}
