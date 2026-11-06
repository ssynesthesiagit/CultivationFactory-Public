// Refresh availability independently of the dialog; ignore obsolete fight reads.
export function sourceInputsButton({button, api, enc}) {
  let request = 0;
  const hide = () => { button.hidden = true; button.disabled = true; };
  return async matchId => {
    const current = ++request;
    if (!matchId) { hide(); return; }
    try {
      const data = await api(`/api/tabletop/matches/${enc(matchId)}/source-inputs`);
      if (current !== request) return;
      button.hidden = button.disabled = !Array.isArray(data.forms) || !data.forms.length;
    } catch {
      if (current === request) hide();
    }
  };
}
