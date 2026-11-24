"""Hook catalogue (default-inert; each detailed contract is in the comments below):
observer_information(engine, observer) -> list[dict] | None. Pure private fact
projection for the observer's perception; None grants nothing.
pass_through_stop(engine, mover, occupant) -> True | None. Pure opt-in shared-space
query; None retains the occupant's collision.
shared_space(engine, left, right) -> True | None. Validates a live explicit sharing
relationship; None keeps rider/mount validation.
cover_miss_recipient(engine, attacker, target, spec, roll, intent, total, cover)
-> another active actor id | None. Runs once for a cover-caused miss; None keeps the miss.
attack_target_interception(engine, attacker, target, source_id, intent, index)
-> {source_id, recipient_object_id, condition_instance_id} | None. Strict pre-d20
checkpoint; None leaves the attack intact.
scene_end(engine) -> None. Strict transactional notice before MATCH_ENDED; no
provider is inert.
diagnosis_reveal(ctx, subject) -> str | None. Observational query asked by a
diagnosis effect while it writes its own plain notice (Soul Gaze's
soul_gaze_reveal, and any later Read the Spirit or dream-diagnosis reveal
provider). ctx is the diagnosis context: ctx.actor is the creature making the
diagnosis and ctx.source is the diagnosis ability. A provider returns one
readable sentence naming what that diagnosis learns about the provider's own
condition on ``subject``, and owns any contest, DC and roll it needs (recorded
as ordinary events). It never changes the examined creature's state. No
subscriber, or a None reply, leaves the diagnosis notice exactly as it was.
Read the Spirit has no table producer today (its reveal is narrative, so the GM
adjudicates that route): the query fires only from producers that exist.
concentration_save_modes(engine, subject, pending_damage) -> None | collection["ADVANTAGE" | "DISADVANTAGE"].
Pure proposal for modes bound to the current damage packet's Concentration save; no condition or later-save
state is installed. None is inert.
concentration_save_sources(engine, subject) -> None | list[{actor_id, source_id}]. Pure proposal
before a native Concentration roll; names only a benefit the provider actually supplies. None is inert.
concentration_save_resolved(engine, subject, roll, dc, maintained, sources) -> None. Runs after final
Concentration settlement; absent subscribers change nothing.
support_value_resolved(engine, proposal, selected, result) -> None. Settles the
selected support scalar after native caps; no provider is inert.
teleport_begin(ctx, subject, previous, destination, movement_context, unwilling, forced, feature_id)
-> None. Strict pre-landing selection callback; no provider is inert.
feature_access_policy(feature_id) -> {kind, classification, path, min_cl, ...} | None.
Pure acquisition-policy query consulted by combat.feature_access.acquire before it
records a scoped declaration; None (the default for every feature without a
provider) leaves the feature's access exactly as it was. A provider answers only
for the feature it owns and states the Path, minimum Cultivation Level, source
kinds and classification the printed record requires.
intent_resolved(engine, actor, candidate, intent, start_sequence) -> None. Strict
notification after a native candidate has actually completed and been accepted,
carrying the sequence number from before acceptance so the provider can read only
the events this resolution produced. The default (no provider) is inert and adds
no event, condition or movement; a provider must not change the acceptance or
re-resolve the candidate.
technique_cost_surcharge(engine, actor, source_id, listed) -> {resource_id: int} | None.
Pure quote of extra resources a printed surcharge adds to this activation, called by
combat.technique_costs.effective before affordability and payment so both use one
number. None (the default) adds nothing; every named pool must already be owned by
the actor and the amount is a nonnegative integer. It never spends or discounts.
activation_settlement(ctx, receipt) -> None. Notification after an activation's
effects and before its aftermath; the receipt carries only this actor/action's
committed DAMAGE_COMMITTED events and their types/recipients. Every subscriber
(iter_strict_all) must return None. With no subscriber nothing changes; a provider
reacts only to its own paid states and never rewrites the receipt or other actors."""
