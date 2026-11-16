// Shared plain-text filtering for character lists in the Factory and tabletop sheet.
(function (root) {
  const api = {
    matches(query, fields) {
      const needle = String(query ?? "").trim().toLocaleLowerCase();
      if (!needle) return true;
      return (Array.isArray(fields) ? fields : [fields]).some(value => String(value ?? "").toLocaleLowerCase().includes(needle));
    },
    filter(rows, query, fieldsForRow = row => row) {
      return (Array.isArray(rows) ? rows : []).filter(row => api.matches(query, fieldsForRow(row)));
    },
  };
  root.CharacterSearch = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
