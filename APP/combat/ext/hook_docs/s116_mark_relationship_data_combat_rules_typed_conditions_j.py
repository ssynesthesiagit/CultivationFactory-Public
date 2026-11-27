"""Mark relationship data (combat/rules/typed_conditions.json):
  mark_aliases maps normalized names to canonical slugs (one level; targets must be canonical).
  mark_counts_as maps a required canonical slug to special slugs that satisfy that requirement, one way.
  typed_executor.mark_condition_id uses the canonical spelling for new marks; bears_mark accepts all stored
  aliases of the requested group and its declared special marks, always scoped by source actor ID.
  mark_requirement_ids(name, owner_id) returns those accepted IDs for inspecting individual instances (Miko purification).
  Missing tables retain literal names and exact matching. Queries are pure and never migrate saved state."""
