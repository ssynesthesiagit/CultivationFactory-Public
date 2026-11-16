"""Subject repositioning (SOL176): subject_reposition(ctx, effect) -> True or None
  runs strictly before typed movement/teleport resolution. True means an owning
  provider handled the complete row; None retains the historical interpreter.
  subject_repositioning requires choose_subject_destination=true on each movement
  or teleport row, explicit non-self scope and a genesis integer policy;
  unstamped saves, self grants and actors without a matching row are inert.
  teleport_steps.destinations/destination_allowed accept optional viewer: the
  subject owns origin, footprint and occupancy; viewer owns sight. Absent viewer
  retains self-teleport queries. typed_executor.teleport_subject(ctx, subject,
  destination) shares landing gates, ledgers and zone arrivals without changing
  controller payment. Gate contexts use the moved creature's own compiled
  numbers for its escape checks. Physical rows explicitly choose_subject_destination=true
  use a legal continuous ground route and movement_paths' forced resolution;
  ordinary grants retain their semantics. Duplicate represented hops share one
  choice and landing within the resolution Context.
  zones.hazard_test(..., immediate_only=True) quotes entry/cross damage for
  safe-destination rules, excluding start-only damage. Default False retains
  all existing AI entry/start risk queries; no stored zone or policy changes.
  Scoundrel's existing event hook (nested=True) ends Bob and Weave on lost adjacency or an
  unavailable anchor. cover_anchor_expiry_policy=1 is recorded at match_start;
  absent policy retains old cover lifecycles and saves. No anchor is inert."""
