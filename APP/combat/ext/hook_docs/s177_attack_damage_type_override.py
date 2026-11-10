"""attack_damage_type_override(ctx, effect, target, kinds, strike_number) -> str | None.
Strict per-strike query for source-authorized damage conversion; kinds is the
printed tuple and strike_number is one-based. At most one provider may return a
nonempty damage type. No answer preserves the chosen damage type.
journey_combat_setup(session, actor_id) -> dict | None. Strict query during combat
bundle creation; returned setup fields must be unique and not replace existing
fields. No answer leaves the journey setup unchanged.
activation_effects_resolved(ctx, receipt) -> None. Strict notification after the
activation effects resolve; receipt summarizes this activation's damage types,
recipients and event sequence bounds. Subscribers must return None; absent
subscribers make no changes.
reaction_admission(engine, row, reactor, attacker, intent, spec) -> False | None.
Runs before reaction consent/payment; False rejects the trigger, None preserves
ordinary admission. Providers must return None unless their owned row applies;
provider errors unwind the intent."""
