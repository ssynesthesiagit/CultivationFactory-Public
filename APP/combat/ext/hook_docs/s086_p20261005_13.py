"""Reviewed reaction adapter (P20261005-13):
  compile_reactions(rows, info) -> new reaction-row list; strict pure transform
  immediately before the shared Auto / Ask me / Off reaction plan, after every
  generic reaction row is compiled. info supplies owned_ids, mechanics, the
  default numbers and numbers_by_source overrides (per source CL/PB/key
  modifier). A provider may replace its own source's generic interpretation or
  add that source's native admission row when free-text trigger classification
  cannot read the printed trigger, and must return the list unchanged for
  sources it does not own. Rows keep the ordinary shape (feature_id, block,
  name, kind, range_ft, once, costs, effects, numbers, reaction_attack,
  target_kind); admission, range, once-per-round limits, Auto / Ask me / Off
  and priority stay with the shared plan and typed_reactions. No provider, or
  no owned row, means the input list unchanged and every character unaffected."""
