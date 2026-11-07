// Refresh availability independently of the dialog; ignore obsolete fight reads.
// `allowed` keeps the owner's declarations to the Game Master view (as the GM scene control is): no read, no entry.
export function sourceInputsButton({button, api, enc, allowed = () => true}) {
  let request = 0;
  const hide = () => { button.hidden = true; button.disabled = true; };
  return async matchId => {
    const current = ++request;
    if (!matchId || !allowed()) { hide(); return; }
    try {
      const data = await api(`/api/tabletop/matches/${enc(matchId)}/source-inputs`);
      if (current !== request) return;
      button.hidden = button.disabled = !Array.isArray(data.forms) || !data.forms.length;
    } catch {
      if (current === request) hide();
    }
  };
}
