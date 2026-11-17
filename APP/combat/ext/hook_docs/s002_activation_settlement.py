"""activation_settlement(ctx, receipt) -> None, strict, after native typed effects
and before technique_used aftermath. combat.activation_settlement.profile is
the public source provenance query (engine, actor, action -> source_id,
source_cl, source_kind, qi_powered, weapon_delivery; integer/string leaves).
Receipt adds action_id, damage_types, damaged_ids, first_sequence and
last_sequence from committed packets of this exact actor/action. No callback
means no change. Consumers must gate ownership and preserve recipient privacy;
the receipt grants no knowledge of unactivated features. Explicit compiled
typed.activation_profile may supply source_cl/source_kind/qi_powered and
weapon_delivery; absent provenance remains unknown, never guessed from names.
recipient_ids includes every committed damage recipient, including damage
reduced to zero; damaged_ids contains only positive HP/Temporary HP loss.
activation_profiles seals zero-cost Sphere expressions on a Qi chassis as
qi_powered=True, preserving explicit exclusions and ordinary weapon attacks.
compile_passives info additionally exposes owner_sheet, matching compile_actions.
combat.activation_settlement.path_numbers(info, path_id) -> copied numbers uses
an explicit owning-Path effective CL/key/PB profile when present; otherwise it
preserves legacy numbers. It never grants ownership or changes another Path.
activation_effects_resolved(ctx, receipt) -> None is the preceding strict
mechanical aftermath phase. It may deliver a source-owned rider to recipients
actually damaged by the activation (for example, one chosen area recipient).
The final activation_settlement receipt is rebuilt afterward, so observers see
the additional damage too. combat.activation_settlement.receipt(ctx, event_index)
is the public pure projector used by both phases. Both phases default inert.
The additive dealt_damage_types list includes only types whose own committed
packet removed Hit Points or Temporary Hit Points. damage_types retains all
packet types, including fully prevented damage, for existing observers.
attack_damage_type_override(ctx, effect, target, printed_types, strike_index)
-> str | None is strict after the ordinary printed attack type choice. One
source-authorized converter may return a new named damage type for this strike;
multiple converters or invalid replies roll back. Unlike attack_damage_type_choice,
this admits a replacement beyond printed alternatives. Default None preserves
every existing attack. The 1-based strike index supports first-attack limits.
journey_combat_setup(session, actor_id) -> dict | None is a strict opt-in
projection before CombatService seals genesis. Unique setup fields only; absent
providers leave journey binding unchanged. A provider must copy only persistent
owned selections, never import a timed travel effect onto a combat clock.
journey_initialize(session, actor_id) -> None is a strict source initialization
after journey creation restores that actor's saved resources and health. Providers
own validation and source clocks; absent providers leave initialization unchanged.
JourneyStore dispatches it once per actor when it creates a journey, after the
retained balances and the retained actor.source_states document are restored, so a
source re-projects its own ledgers and clocks onto the new journey before anything
is offered.
journey_encounter_settled(session, actor_id, engine, creature) -> None strictly
notifies sources after terminal-fight health, resources and position are imported.
Providers may import their committed ledgers; absent providers change nothing.
journey_snapshot_actor(actor, session, actor_id, engine) -> ActorState | None
is a strict pure sequential transform before encounter health validation. A
provider may return a copy excluding only its own managed effects; None or absent
providers leave the snapshot unchanged.
journey_scene_end(session, old, new) -> None strictly notifies providers after
the table owner explicitly ends a journey scene. Providers reset only their own
per-scene state; absent providers make no source state changes.
H203FIX2: moon_sea uses compile_bundle to replace the owned Divine King Body
generic generation row with one pressure.generate row. Existing
effect_resolution_scope/save_final/opposed_check_resolved notifications settle
failed hostile rolls after their consequences; technique_used credits actual
CP debits and visible outward deliveries. Nested REACTION_RESOLVED receipts
credit positive, source-qualified self/ally protection, including native Water
Shield and generic guards. H203FIX2F1 adds two completed readers to the same
one generator: a typed reaction's own journal window (REACTION_WINDOW_OPENED
through its resolved receipt) credits a paid, meaningful generic reaction use,
and the documented damage_defended receipt credits an ongoing Aegis-type
protection that actually reduced matching damage, using the public
combat/ext/protection.py resisted_kinds reader instead of that plug-in's saved
data format. Native pressure owns cap/round/next-turn expiry and
prior_event_resources owns same-event payment. No owned generation row means
no behavior. Context-local roll scopes restore on pause/error and never persist."""
