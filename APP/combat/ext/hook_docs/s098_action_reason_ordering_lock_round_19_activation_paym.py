"""Action-reason ordering (lock round 19): activation payment uses stage 0, target
checks stage 1, and final shape-payment filters stage 2. cannot_pay accepts the
caller stage, so a surviving target's real resource shortage takes precedence
over another target's earlier rejection. Candidate eligibility is unchanged.
Action availability:
  engine.action_availabilities(actor_id, source_ids) -> {source_id: answer} is
  the batch form of the single-source query below. Table and connected-sheet
  button explanations reuse diagnostics from CombatService's existing checked
  candidate pass on the live service engine during ordinary menu/decision
  construction. Without matching diagnostics, an independent query shares one
  fresh candidate pass on an isolated engine copy across the requested sources.
  Each source retains its own rejection stages, details and pure explanatory
  hook replies; an empty source list does no work. Diagnostic frames may survive
  a call in the transient engine/service derived cache, never in persisted fight
  state. Reuse requires the same actor and requested sources in the frame, plus
  a matching canonical signature of fight state, action catalogue and typed
  control modes; changes to any of these invalidate reuse. Returned cached
  answers are copied, and reuse does not invoke explanatory providers again.
  Neither form executes an intent, changes state, asks a player or reveals a
  hidden target. Exhausted-use answers retain the compiled per-fight reset text.
  TabletopService also projects unavailable reasons for explicitly player-usable
  shared system object actions (owner_id="*", system: source and
  parameters.player_only=true). Each entry comes from
  engine.action_target_availability(actor_id, source_id, target_id), so legality
  and refusals are checked for that exact target before projection under its
  source and object ID. This permits general shared interactions to explain why
  a particular map object has no issued choice without copying another object's
  answer, authorizing a choice or exposing another actor's reason.
  engine.action_availability(actor_id, source_id) -> {available: bool,
  reason: str | None, code?: str, details?: dict}. Read-only, exact source ID in
  the current decision context. It uses matching live-pass diagnostics when
  available; otherwise it observes the actual candidate checks on an isolated
  engine copy, so fallback temporary geometry/cache work cannot mutate the
  caller's state, events, rolls or caches. It executes no intent and asks no
  choices. A real surviving candidate is required for available=True. Rejections
  come from the checks themselves; among alternative targets/origins, the first
  rejection at the furthest reached candidate-filter stage is shown. Candidate
  ordering, identities, payment predicates and AI policy are unchanged.
  engine.action_target_availability(actor_id, source_id, target_id) returns the
  same answer shape for that exact object target. It uses an isolated engine
  copy and never borrows another target's candidate or refusal. An object the
  action's object_targets providers do not nominate has no projected refusal.
  engine.action_target_availabilities(actor_id, source_target_pairs) returns
  {(source_id, target_id): answer} for the requested pairs using one isolated
  candidate pass. Only action-economy and activation-payment refusals are shared
  across targets; target-specific refusals are not projected onto other objects.
  candidate_unavailability(engine, actor, candidate, action) -> str | None;
  target_unavailability(engine, actor, target, action) -> str | None;
  recipient_unavailability(engine, actor, target, action) -> str | None.
  These hooks run adjacent to a False result of candidate_allowed,
  target_eligibility, recipient_allowed respectively, either on the live service
  engine during its observed candidate pass or on the isolated engine during an
  independent query's fallback pass. Providers must be pure in both contexts
  and must not depend on being called for every read: replies may be reused.
  Each owner explains its own active denial in plain text, with no hidden creature
  identity/location, state mutation, cost, prompt or cache. None is default-inert
  and leaves a neutral restriction explanation. First non-None reply is shown.
  source_unavailable(engine, actor, action) -> str | None is a pure, default-inert
  source-wide check for a compact/lazy menu header. A header is an offer to inspect
  an action, not a legal choice: candidate_allowed vetoes run only on its expansion,
  so TabletopService asks this hook to explain a header that cannot expand at all.
  Providers must depend only on the actor, the action and saved state (no target,
  square or hidden creature), must not mutate state or ask a choice, and return
  None when the header is usable. The reply is the same plain button reason used by
  candidate_unavailability; it never adds, removes or reorders a menu option."""
