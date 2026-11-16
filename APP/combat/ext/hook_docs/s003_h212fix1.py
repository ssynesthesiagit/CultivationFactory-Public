"""Timed gain and declaration contracts (H212FIX1):
  gain_resource.resource_expires="end_of_next_turn" arms the holder's shared
  pressure clock only after an actual increase; absent metadata is inert.
  pressure.schedule_expiry(engine, actor, resource_id, expires) -> None is the
  same opt-in for plug-ins. Own-turn gains survive this end and expire at the
  next end; off-turn gains expire at the next holder end. Clock data is integer.
  typed_executor.pending_technique_context(engine) -> Context | None exposes
  only the currently resolving declaration to owned reaction effects. A legal
  redirect replaces its targets/target and sets _activation_redirect_recipient_id;
  the dispatcher then reopens the same declaration checkpoint once for each
  redirect recipient it has not visited yet (typed_reactions.on_technique_redirect),
  so that creature keeps its target-triggered reactions, and a visited guard ends
  any redirect cycle without asking a creature twice.
  declaration-local state is cleared on success, failure or a choice pause.
  Reaction effects may opt into answers_hostile=True for the existing adverse
  incoming-effect filter; omitted metadata preserves existing classification.
  resolve_opposed_check's check spec accepts proficient=True for an ability
  check adding the actor's PB once when no recorded skill total is selected.
  These seams contain no ability IDs and create no hooks for nonowners.
  typed_executor.named_hit_method(ctx, target, name) -> None notifies armed
  first-named-hit riders after an inline method actually runs. Source-feature
  hit packets publish the same notification after their effect executes.
  Ordinary per-turn hit gates deduplicate multiple methods on the same hit;
  no armed matching rider means no change. No catalog or fight state is added."""
