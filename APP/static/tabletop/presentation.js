// Shared server-layout reader for table buttons, sheet buttons and library rules.
export function layoutText(hover) {
  if (!hover) return "";
  // text includes this use's live cost/clocks as well as the record projection.
  if (hover.text && String(hover.text).trim() !== String(hover.title || "").trim()) return String(hover.text).trim();
  if (hover.player_card) return hover.player_card.text;
  if (!hover.summary && !(hover.fields || []).length && !(hover.body || []).length && !hover.footer) return "";
  const fields = (hover.fields || []).map(f => String(f.label ? `${f.label}: ${f.value || ""}` : f.value || "").trim());
  return [hover.title, hover.summary, ...fields, ...(hover.body || []), hover.footer]
    .map(line => String(line || "").trim()).filter(Boolean).join("\n");
}
