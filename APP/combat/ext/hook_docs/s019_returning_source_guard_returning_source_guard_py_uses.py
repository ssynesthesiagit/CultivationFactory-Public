"""Returning Source Guard (returning_source_guard.py) uses the public immutable
pending_damage receipt, reaction_geometry_allowed, nested REACTION_RESOLVED,
save_mode, contest_check_mode, ability_check_hazard_mode and d20_finalized.
Native Concentration is an explicit save producer; scoped contests supply
their declared hazards. Missing purpose/source facts do not match. Queries
are pure; the finalized eligible d20 consumes the persisted allowance even
when Disadvantage cancels it. Expiry uses effect_durations.token on the donor.
General explicit pressure metadata: damage/extra_damage rows may carry a
nonempty string pressure_kind. typed_executor transports it through Context
to the native pending_damage packet; absent metadata remains 'damage'. Pending
typed saves expose pressure:<kind> from their actual failure damage rows.
Soul Warden's Soul Drain produces 'drain'; Qi turbulence's accepted Turbulent
Backlash produces 'backlash'. Unknown names are retained, never guessed into
either category. Returning Source Guard consumes only established drain/backlash
save facts with the exact damaging action and creature identity.
The public formations.formation_check(..., hazards=()) keeps purpose separate
from display labels and supplies a matching d20_scope through finalization.
The shipped unstable-array turn-start caller produces maintain:formation;
other formation checks omit it and do not consume a maintenance allowance.
Temporary beneficial condition producers may set data.temporary_benefit=1
and a plain label. benefit_suppression.benefits then includes the bounded
condition in ordinary cancellation/suppression choices. Missing metadata is
inert. Guard marks each paid donor/source allowance; finalized eligible rolls
use the documented _remove_condition_instance transport so suppression does
not postpone a next-roll benefit. Unmatched donors/sources remain independent
and their original donor-turn expiry is retained on restoration. Multiple
matching allowances contribute one Advantage mode and consume on that roll.
Reviewed generic reactions may set allow_self_source=true to transport the
existing runtime admission opt-in through builder and compiler. Absent fields
preserve existing rows. Guard uses it only with its owned source/geometry gate:
nonhostile/self damage requires actual maintained native Concentration. Native
cost_available/prior_event_resources owns earlier-event payment; packet resource
snapshots do not replace that shared causal policy or reject nested prior events.
Generic defensive effects may set hostile_source_only=true. Both self and
ally damage consumers then apply that effect only to a native hostile pending
packet for the protected subject; other effects and the reaction's admission
remain independent. Missing metadata is inert. Guard's maintenance trigger
can grant an ally allowance against nonhostile damage without reducing damage
that its printed numeric clause limits to hostile sources.
Published pressure provenance: native DAMAGE_COMMITTED adds pressure_kind
only when an explicit packet producer supplies a non-default kind. Ordinary
damage receipts remain unchanged. pressure_facts.committed_pressure_kinds
(engine, subject_id, source_id, source_actor_id) returns only kinds actually
committed by that exact source to that subject; unknown strings stay unknown.
Strict save_pressure_kinds(ctx, subject, ability, named) -> sequence of nonempty
strings or None lets a real save producer describe this save's pressure.
typed_save_modifiers invokes it for typed saves and defending contests before
mode resolution, exposing pressure:<kind> in native d20 context. Default-inert.
Qi instability consumes its actual Field/caster/subject backlash receipt to
publish the next Field save's kind; ownership alone is insufficient. Guard
consumes that matching source-bound Constitution save once."""
