"""Resumable hit defenses (lock round 19): on_attack_hit's optional
correct_ac_miss(total, armor_class) callback returns an integer revised total.
The native caller owns one correction attempt, consent, payment and bonus damage.
After a successful explicit AC correction, only unvisited defenses continue;
prior AC and payments remain applied. No callback means the old defense flow.
hit_response may return {armor_class: int, hit: bool, miss_reason: "armor_class"
| "forced" | "natural_replaced", natural_result?: int 1..20}. Only an armor_class
miss with unchanged natural is correctable. Legacy (AC, hit) replies are terminal.
Forced/replaced-natural replies never become an AC deficit; original roll records
and the provider's replacement receipt remain intact. Declare a miss that compared
no AC as combat/attack_outcomes.unconditional_miss(), which is exactly that: it
carries no armor_class, so the fight keeps the AC the roll was made against and
publishes no outcome receipt (below) for a miss no number caused. Replies are transient.
ext.invoke(point, registered_callback, *args) is shared by run and the resumable
pipeline: it preserves observational error handling and propagates choice pauses.
The pipeline invokes one registered provider at a time with the current total.
Attack correction:
  attack_miss_correction(engine, attacker, target, spec, roll, intent, total, ac)
  -> None or {source_id: str, label: str, bonus: positive int, bonus_damage?:
  nonnegative int}. Strict transactional providers own consent and recorded
  payment. Called only for a rolled miss, never a natural 1, forced miss or
  canceled attack. Providers see the existing roll and current AC; bonuses do
  not roll again. The first bonus producing a hit stops dispatch. An initial
  corrected miss continues through ordinary hit defenses and damage; a miss
  caused by an already-run hit defense can be corrected without repeating that
  defense. At most one correction dispatch per attack. Bonus damage is part of
  that hit's ordinary damage packet/type, only if it remains a hit. PASSIVE_TRIGGERED
  records each accepted correction and the original roll ID. No providers/replies
  means no change, event, resource spend or saved-state field. Spec is transient.
Attack outcome replacement:
  attack_miss_outcome(engine, attacker, target, spec, roll, intent, total, ac)
    Called for an ordinary rolled miss and again only when an AC defense creates
    a miss from a previously successful hit. The engine guards the hook to one
    offer per attack attempt; forced misses never reach it. Providers still own
    their printed margin, consent and price.
  -> None or {force_hit: True, source_id: str, label: readable str} is an
  explicit provider-owned replacement of a rolled miss with a hit. It is queried
  after ordinary bonus corrections and includes natural 1 misses; it is never
  queried after a forced miss. If an AC defense later turns an already successful
  attack into a miss, the same guarded offer may run at that final AC. It changes
  the outcome without changing the roll total, and records PASSIVE_TRIGGERED with
  attack_outcome_replaced=miss_to_hit before damage.
  Providers enforce their own eligibility/margin and consent/payment rules. No
  provider/reply leaves existing natural-1 and ordinary miss rules intact."""
