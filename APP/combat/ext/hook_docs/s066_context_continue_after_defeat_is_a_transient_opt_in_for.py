"""Context.continue_after_defeat is a transient opt-in for damage packets already
attached to one confirmed hit. It lets the typed resolver finish those packets if
an earlier packet in that same hit defeats the target; it does not reopen the
fight or enable later actions. Ordinary damage contexts keep the default false.
General paid self-relocation guard (P20261010-02, lock round 27):
  activation_accounting(engine) -> bool or None is a strict pure query at the
  start of paid_relocation.transaction, before accepted activation effects.
  True enables the causal activation/payment tracker even without a relocation
  guard; False or None does not request it. Replies must be exactly bool or None;
  malformed replies abort the transaction. Any True enables tracking; False
  never vetoes another provider or a registered paid_relocation_guard. Providers
  must not mutate, spend, roll, emit events or ask a controller. No request and
  no guard is default-inert. Tracking snapshots are transient, never serialized;
  current_activation exposes the accepted owner's actual payments to consumers.

  paid_relocation_guard(engine, actor, previous, destination) ->
  combat.paid_relocation.Restriction(reason, resource_ids) or None is a strict,
  pure query for owned self assignments. The observer runs BEFORE every changed
  Position assignment to an exact live ActorState during a foreground transaction.
  It includes direct/custom writes, silent
  move-and-return, x/y/z movement, teleport, swap and causally attributed falling.
  Copies used for previews are not live actors, even if entity_id is identical.
  Providers must not mutate state, spend, roll, emit events or ask a controller.
  A restriction has a nonempty readable reason and a nonempty frozenset of exact
  resource IDs. The rule provider decides which pools count as CP and when its
  restriction applies; core has no ability ID, CP alias or action-name classifier.
  None contributes no restriction. Multiple restrictions are all enforced.
  No registered consumer means no tracker or position callback, no additional
  rule queries and no change to native movement, costs, events or saved state.

  The observer accepts a restriction only when the current causal activation
  owner IS the exact moving actor object. Actual positive _spend_resource debits
  by that owner count, including costs paid inline or after movement. A restriction
  is retained as it applied before each assignment: removing it or returning to
  the original position before a later debit does not erase the earlier move.
  Refunds do not erase payment. A restriction covering CP but excluding Focus
  therefore permits free/Focus-only relocation. A matching paid use raises
  RelocationVeto (CheckpointError) and the existing foreground transaction rolls
  back positions, economy, resources, effects, events and dice. Observational
  extension dispatch must propagate this exception just like other checkpoints.

  combat.paid_relocation.activation(engine, actor, source_id) scopes an accepted
  INDEPENDENT reaction or environmental activation, before its first debit or
  effect through its last aftermath. actor=None denotes an environmental owner.
  Independent hostile displacement is not the displaced creature's self-use.
  Native and typed accepted reactions, Ready, persistent zone triggers and manual
  plugin responses use this scope. A foreground effect merely spending Reaction
  as an additional cost keeps its enclosing owner. Contexts restore that owner
  on return, exceptions and ControllerPause. independent=False joins an existing
  activation only if both its exact actor object and source ID already match;
  adapters use this to preserve payments made by the accepted caller.
  continuation=True explicitly joins the same live actor's existing activation
  even for a different source ID. Named free own_ability follow-ups use this
  option because they ride the original ability; independent free reactions do
  not. Without a matching actor owner it creates a new activation normally.

  current_activation(engine) returns an immutable actor/source/payments snapshot
  for diagnostics and pure consumers. capture(engine) returns an opaque transient
  owner receipt. causal_scope(engine, receipt) resumes THAT owner's payment ledger
  for delayed effects. With an active tracker, a None receipt denotes an unowned
  effect; it never borrows the foreground owner. retain/take keep receipts under
  transient keys; retain_effect/take_effect bind them to exact retained effect
  objects. retained_owner/effect_owner read these receipts without consuming
  them when several aftermath callbacks share one accepted effect. Receipts
  belong to one transaction, are never serialized, and cannot
  be reused in another fight/transaction. Mixed deferred effect lists retain each
  effect's own receipt. preserve_pending(engine, attribute) enrolls a deferred
  engine-side binding in rollback; call it BEFORE creating, editing or removing
  that marker/queue. It snapshots dict/list/tuple/set structure while retaining
  actor/context object identities; native MatchState rollback already covers
  actor flags. An aborted guarded transaction restores these enrolled bindings
  and discards all observer/ownership context. Successful uses keep native data.

  Falling keeps native eligibility, timing, landing and damage. The tracker
  samples falling.required for exact live actors at transaction start, event
  boundaries, before child scope entry, before child scope exit and before
  settlement. A false-to-true transition retains the then-current owner; a fall
  already due at transaction start is unowned. true-to-true retains the earlier
  cause; true-to-false clears it. Settlement resumes the retained owner even if
  the causative scope has ended. A later unrelated event does not claim the fall.
  Explicit plugin scopes must encompass silent eligibility changes as well as
  movement. No state, event, action, intent, candidate or lock schema is added.
  Tests install a synthetic consumer; this seam does not itself install Meridian
  Lock or claim a complete Thread ability implementation.
Healing plug-in compatibility (A2BLOODr3):
  healing_preparation_policy(engine, subject) -> bool | None
  is a pure recipient opt-in query used by healing_policy.ordinary_preparation.
  Providers run in registration order; any True opts the recipient into shared
  ordinary healing preparation at plug-in paths that historically bypassed it.
  False/None and missing providers retain each caller's historical HP, receipt,
  restriction and reaction route. No allowance is consumed, bonus is quoted,
  event is synthesized or saved state is written. Errors and non-boolean replies
  fail the transaction through CheckpointError. A provider must select policy
  from sealed live state independently of whether its bonus remains available.
  Current Court opts in only eligible allies in its sealed new-marker zone;
  legacy Court and recipients outside that policy keep historical paths."""
