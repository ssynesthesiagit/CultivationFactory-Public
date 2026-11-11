"""- Reaction waivers: reaction_spend(engine, actor, row, commit) returns None or
  "free". commit=False is a pure eligibility query and may repeat during previews;
  commit=True consumes the provider's own entitlement through recorded events.
  Dispatch is strict and lazy: the first "free" wins, so other grants are not spent.
  Errors and player-choice pauses unwind the transaction. An absent hook preserves
  ordinary Reaction spending. The provider owns grant limits, expiry and eligibility;
  a waiver never overrides inactive/no-Reactions restrictions. Native Opportunity
  Attacks pass the compiled reaction row plus reaction_kind="opportunity_attack";
  action_id identifies its weapon action. Legacy rows use the ordinary Opportunity
  Attack feature id/name/block. typed_reactions.spend_reaction commits once only
  after consent; reads and declined offers never consume a grant. It leaves the
  ordinary Reaction unchanged on a waiver. Querying a grant must not reserve it.
- Dynamic growth: size_change typed effects call combat.dynamic_size.apply_growth.
  An expiring source-owned condition records the largest size that fits; native
  FOOTPRINT_CHANGED records both size and nearest legal anchor, including expiry.
  No growth leaves the original footprint and serialized state unchanged. Reach
  measures from its new occupied edge; growth grants no extra reach in feet.
  size_steps(engine, actor, role, purposes) -> int or {steps, additional}; C12's
  ext.effective_size.cells adds functional steps to the current footprint width.
  Roles are act/resist; purposes are forced, grapple, shove, prone. Plain steps
  take their maximum and printed additional steps add. These never grow geometry.
- Dodge attack eligibility uses target_knowledge.can_see(engine, defender, attacker).
  Read it before temporary attack-bonus condition masks: formation suppression of
  Invisible benefits does not itself grant sight. Actual special senses still do.
  Knowing a location alone does not grant Dodge's Disadvantage against an unseen
  attacker. Other Advantage/Disadvantage sources and Dexterity-save behavior are
  unchanged. This intentionally changes attacks where Dodge previously cancelled
  an unseen attacker's Advantage; ordinary visible attacks keep their bytes.
- Concentration after damage uses the final damage taken after defenses and the
  final_damage checkpoint, before Temporary HP absorption. Positive damage asks
  for the existing Constitution save at max(10, damage_taken // 2); zero does not.
  This intentionally adds/changes checks on Concentrating creatures protected
  by Temporary HP. Ordinary damage, damage receipts and HP loss remain unchanged.
- Typed cures: strict te.condition_removal(ctx, subject, name, cause) -> None is
  called immediately before block_remove_condition deletes a condition, including
  when the named condition is only pending and has no active instance to delete.
  name is trimmed/lowercase with condition:typed. removed; cause is the normalized
  effect.cause string, default "cure". Context supplies source, caster and intent.
  Providers may cancel only their matching delayed instances and release their
  reservations using recorded events. Durable and Cold Iron Call can use this
  point; do not couple ordinary typed cures to their storage layout. Other names,
  other targets and providers without owned pending instances remain inert.
  The point does not veto the cure. Invalid replies, errors and choice pauses
  unwind the containing transaction. No request event is added without a provider."""
