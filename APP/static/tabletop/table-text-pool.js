// Lossless inverse of combat/table_text_pool.py, before UI consumers run.
export function expandTableTexts(state) {
  if (!Array.isArray(state?.table_texts)) return state;
  const texts = state.table_texts;
  function expand(value) {
    if (Array.isArray(value)) return value.map(expand);
    if (value && typeof value === 'object') {
      if (Object.keys(value).length === 1 && Number.isInteger(value.$table_text)
          && value.$table_text >= 0 && value.$table_text < texts.length) return texts[value.$table_text];
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, expand(item)]));
    }
    return value;
  }
  const {table_texts, ...body} = state;
  return expand(body);
}
