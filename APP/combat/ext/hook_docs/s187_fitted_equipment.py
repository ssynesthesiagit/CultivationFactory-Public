"""Fitted equipment and preparation hook contracts.

  equipment_speed_penalty_exempt(info, penalty) -> True waives one Speed penalty (equipment_armor.py sure_harness:
                                                 Strength shortfall of worn armour, when the wearer is proficient). Compile-time;
                                                 None or False keeps the penalty. Inert without the owned talent.
  armor_penalty_exempt(bundle, penalty, item) -> True exempts the penalty a physical worn item imposes (penalty is
                                                 "stealth"); None keeps it. Pure compile-time query; providers check
                                                 their own owned talent, the item's category and training
                                                 (equipment_armor.py armor_ease). Never edits the item.
  equipment_check_mode(engine, actor, ability, skill) -> "ADVANTAGE"/"DISADVANTAGE" | None. Pure query folded into
                                                 typed_executor.check_modes, so a check-scoped exemption or penalty
                                                 uses the ordinary roll modes. Providers gate on the actor's own worn
                                                 source-qualified item (armor_subject.worn_armor_check: an untrained
                                                 suit's Dexterity (Stealth) Disadvantage, unless an exemption removes that
                                                 source). None adds nothing; other characters and checks are unchanged.

  Between-fight preparation contracts (combat/preparation.py; per-actor durable document under the roster lock).
  Nothing here invents a command or a rest: the gameplay reducer owns time and rest events, and providers own only
  their own source transitions. Every state value a provider stores is JSON with integers/strings (no floats/objects).
  preparation_reconcile(state, bundle) -> iterable | None. Runs under the actor lock on every read and before
                                                 publication, reconciling the durable document with the freshly compiled
                                                 bundle (lost training, replaced/destroyed items). A provider mutates the
                                                 state it is given; a truthy return means "persist this revision".
                                                 None means no change. Raising fails closed.
  preparation_options(state, bundle)  -> list[command] | None. Pure menu of every legal between-fight command for
                                                 humans and model seats: {"operation", "label", "parameters"} (labels
                                                 are player-facing). It never advances time, completes a rest or picks
                                                 for the owner.
  preparation_command(state, bundle, operation, parameters) -> True | None. Strict command transaction after
                                                 reconcile. True claims the operation; None leaves it to another
                                                 provider (the caller rejects an unclaimed command). Raise to refuse.
  preparation_before_activity(state, bundle, operation, parameters) -> None. Strict pre-check before the gameplay
                                                 reducer runs a rest/time operation; raise to refuse an ineligible rest.
  preparation_activity(state, bundle, operation, parameters, events) -> None. Strict post-step after the reducer;
                                                 commits the provider's own transitions for that operation and for the
                                                 reducer's committed rest events (e.g. a completed long rest).
  preparation_bundle(bundle, state)   -> bundle | None. During roster preparation, publishes compiled source state the
                                                 providers own (fitted suit identity/readiness, head protection,
                                                 concealment, spent rest uses) into the bundle that the match saves.
                                                 The returned bundle replaces the caller's copy; None leaves it.
  preparation_prior_fights(service, bundle, state) -> None. Strict hook immediately before a new match is published:
                                                 providers carry receipts forward from this character's earlier saved
                                                 fights (e.g. Helmet Discipline's spent rest number) and may refuse a
                                                 creation that would otherwise duplicate a shared allowance.
  preparation_committed(service, engine) -> None. Strict receipt after a manual, model or Local Auto commit; providers
                                                 persist what that committed turn spent, under the actor lock.

  Damage-defence packet seams (combat/typed_reactions.py; the card and resolution share the standing query).
  damage_defense_standing_eligible(engine, target, row) -> bool | None. Pure, packet-free qualification used by both
                                                 damage resolution and the defence card; any False hides/rejects the
                                                 row, None has no opinion. It never spends a once-per-round use and never
                                                 asks for consent, so a standing state (ownership, proficiency, worn
                                                 item, required condition) is the only thing it may judge.
  damage_defense_row_allowed(engine, target, row, kind, typed, source_actor_id) -> bool | None. Pure per-packet gate
                                                 used only by resolution (not the card); any False rejects the row for
                                                 this packet. None is inert.
  before_damage_defense_choices(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> None.
                                                 Strict notification at the actual packet, before one-packet defenses
                                                 are consumed; providers may open their own consent/once-per-round
                                                 choice or consume their own use. It must return None (a non-None
                                                 reply is a programming error and aborts the packet).
"""
