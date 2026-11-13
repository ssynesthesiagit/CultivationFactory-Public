"""A2GINS3 ownership and general healing contracts:
A2GINS3: insights3 uses existing compile_block/compile_passives to seal owned
Insight rows with PB/CL and plain player_outcome text. Existing defense and
standing rows retain their single providers; no second reaction or action is
registered. All new behavior requires the sealed insights3 ownership row.
save/save_mode and save_roll_tags use this save's established consequence or
category metadata. Mental tags are dream, illusion, emotional_manipulation and
forced_identity_alteration; bodily tags are bodily_corruption, mutation,
forced_transformation and disease. Furnace-Heart reads the actual damage packet
during native Concentration checks and uses damage_source_id for represented
smoke/environmental_heat provenance. Missing qualifiers do not guess a hazard.
The shared d20_rewrite owner supplies failed-save settlement, consent, one-reroll
enforcement, exact Qi/Reaction payment and the once-per-scene counter.
save_effects records this recipient's prior condition/modifier IDs; save_final
reserves one final failed-save trigger. effect_resolution_scope settles the rider
after actual save consequences, and technique_used completes defending contests.
Only an actually applied zero-Speed row or source-owned outcome qualifies for
Reaction denial; an inactive conditional branch does not. Speed modifiers carry
explicit source ownership and source-next-start expiry, including off-turn pulses. Damage history observes positive DAMAGE_COMMITTED packets, including
nested damage. The same first self-damage packet cannot serve as prior damage.
Round and scene counters use the retained _round_ namespace and actual round
integers, rather than being erased at the owner's turn start.
other_resistance is a pure source-qualified overlap query, excluding this
Insight's own row; active typed/native/condition defenses share nonstacking.
damage_reduction's applied=False stays pure; only applied=True spends a packet
allowance. Healing additions run once per real healing roll; one selected
activation may contain separate rolls, while shared recipient rolls do not
multiply the addition. Falling protection owns only positive falling damage;
the ordinary fall_landed/rider_step path supplies the optional landing movement,
with native Prone, movement costs, route legality and opportunity rules.
The general healing_roll_resolved seam below is added. Speed application identity
is persisted on modifier rows so separate applications keep independent expiry;
the core aggregation and set-Speed conversion remain general and ability-agnostic.
That identity names the enclosing intent and the actor who applied the row, and
the row is filed under that same applier. One table intent can carry deliveries
from several owners -- combat/zones.py dispatches each arriving area under the
active movement intent -- so without the applier two independently owned
Slows would share one identity, be added as a single activation, and cost the
creature a penalty neither owner earned alone. Rows of one activation still share
an identity and still combine.
General healing_roll_resolved(ctx, effect, rolled_amount) -> nonnegative int
or None runs strictly after the normal typed healing roll and before stored
reductions, recipient assignment, interception and caps. Additions compose;
malformed replies fail the transaction. Missing providers leave the roll and
all existing healing routes unchanged. Shared recipient rolls call it once;
independently rolled effects each call it once. No event or stored field is
introduced. This lets a printed post-roll healing addition refuse a zero roll
instead of changing whether the original roll restored HP at all.
insights3 combines this with a context-local effect_resolution_scope and actual
positive HEALING_APPLIED receipts. Full-HP, denied and zero-healing offers do not
spend its per-turn use; separate rolls of the selected activation retain the
addition. Frames restore on nested healing, pauses and failures, and are never
serialized. Other sources cannot consume the Flesh allowance from this frame."""
