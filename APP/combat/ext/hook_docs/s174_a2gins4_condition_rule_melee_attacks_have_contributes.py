"""A2GINS4: condition rule melee_attacks_have contributes ADVANTAGE or DISADVANTAGE
only when the native attack profile declares ranged=False. All typed, native,
and reaction strikes use this profile before cancellation. Presentation queries
with unknown range receive no melee contribution. It never consumes the state.
compile_resource_definitions(resources, info) -> replacement ResourceDefinition
list is a sequential compilation transform after ordinary pools/use counters.
info carries owner_sheet, owned_ids, numbers, mechanics and pb. Providers must
preserve unowned pools and can only adjust pools granted by their printed rule.
No subscriber preserves the original list; saved bundles are not recompiled.
insights_four uses existing typed effects, turn_end, compile_actions and
damage_dice_reroll. Blood Boil's condition clock owns its one-minute duration;
its native damage commit is unreduced. Distant siblings preserve all original
payments/limits/materials. Empowered uses one resolution-local choice per
activation and the engine's recorded replacement dice, including shared areas.
confirmed_damage_roll_adjustment(engine, attacker, target, spec, intent, source_id, roll) -> signed integer, DieReplacement or None runs strictly after a
confirmed native/typed/reaction attack's original damage roll is recorded and
before damage delivery. It cannot change hit/critical outcome. Providers own
any optional payment/choice and record replacement dice; errors/pauses roll
back with the enclosing attack. No subscribers leave totals/events unchanged.
Both damage-roll adjustment hooks are sequential strict transforms through
combat.damage_roll_replacements.settle: each provider receives an effective
RollRecord with preceding replacements and flat adjustments already applied,
retaining original die indices and roll_id. Providers return None (inert), a
signed integer (flat adjustment), or DieReplacement({index: positive_int},
bonus=0) to replace indexed current dice. No original journal roll is mutated;
effective copies are transaction-local, never persisted as another random draw.
Replacement dice must be drawn/recorded normally; pauses/errors roll back the
whole activation. Typed damage_dice_reroll settles before the typed adjustment
hook, exposing its new dice just as native Empowered replacements do. Every
Red Execution die/result choice remains available and labels show current values.
insights_four restricts its replacement to the exact typed attack_scope and
owned Empowered Technique row, never ordinary weapon attacks or fixed damage.
Hook Master extends its existing typed reaction modifier and uses the pure
generic_reaction_costs query to replace CP with its once-per-scene counter;
declining the reaction spends neither, and other costs remain intact.
Iron-Blood Circulation accepts established Disease consequences or explicit
save_categories=disease/physical_injury_exhaustion; unrelated Exhaustion is
unchanged. Hollow Script Custodian records its fight-wide use in a condition,
not a transient turn flag, and extends Hollowed through condition_state.
Generic named reaction modifiers now honor unconditional add_range_ft on each
attached reaction row, in addition to attaching their existing effects. Optional
range modifiers keep their earlier path. With no geometry field, reactions retain their old ranges.
Generic moved reactions opt into movement_measure="turn" only when the printed
trigger says "during a/the/this turn". ext/movement_clock.willing_distance is a
pure shared query over committed physical paths since the latest TURN_STARTED;
forced moves and teleports are excluded, and off-turn movers share that clock.
Unstamped reactions keep their per-activation moved_ft reading.
A2GINS8 general escape/movement contracts:
All runtime engines expose typed_passive_rows as an actor-id mapping of sealed
passive dictionaries. Portable runtimes without Factory-typed rows expose an
empty mapping, so shared ownership queries preserve their native behavior.
compile_reaction_action(action, info) -> ActionDefinition | None is a pure
replacement hook for the derived opportunity attack, which is held separately
from the normal action list. Its compile info matches compile_action; preserve
owner, source identity and economy. No provider leaves the reaction unchanged.
Insights8 carries the printed Iron Fist Slashing palette and natural provenance
through this hook, so its actual reaction attack uses the same player choice.
escape_roll_resolved(engine, escaper, grips, success, way, source) -> None
is a strict notification after one selected hold's final actual roll. `grips`
carries the pre-roll hold instances; reactions may have removed them by this
checkpoint. The roller must be the held creature to qualify for its own
failed-escape riders. Checks with escape_hooks=False do not notify. Native
repeat escapes, granted escape saves, Flowing Evasion and shared escape checks
all report; pure probability/mode queries never report. Consumers own limits
and attribution. passive_traits.is_grapple(hold) recognizes actual Grappled
rule copies, never mere restraint. Unyielding Grip delivers a non-attack PB
packet once per turn per holder; damage cannot recursively trigger this seam.
size_context_purposes(ctx, role, purposes) -> set[str] | None is a pure query
adding qualified purposes to this typed size comparison. No consumer changes
ordinary footprint size. effective_size.rank and typed_executor.size_rank
compare printed categories for relative limits; absolute max_size_cells retains
size_width/cells. Tiny/Small/Medium thus remain distinct for Grapple eligibility
and Wrestling relative size limits. scoped_size_purposes qualifies both query
forms without changing space/reach. The generic carrying purpose is used by the native
grapple drag-cost comparison, using current size categories rather than occupied
squares so Tiny/Small/Medium remain distinct; neither purpose changes space or reach. The
existing passive trait adapter accepts carrying and wrestling. Insights8 adds
wrestling only for printed Wrestling sources; eligibility, carrying and
talent comparisons each count Wrestling-Body's same single size step once.
Native/portable settled attack notifications now deliver after_hit_choice and
after_miss_choice strictly, with the same Context/target/kind or spec as typed
attacks, before observational hooks. No matched row means no choice/state.
Sword-Bone uses the shared attack damage context for its Slashing component,
retaining one hit's reductions, attribution and life-state decisions. Its
slow/reaction benefit ends at START_OF_SELF_NEXT_TURN on the actual recipient.
Wine-Gourd's post-miss route uses rider_movement, legal supported destinations
and no ordinary movement/OA payment. Declining preserves the round allowance.
Both free-step routes restrict automatic destinations to terrain the mover
can perceive; manual owners choose any legal destination. Persistent limits
use the native retained round-flag namespace, including fight-long retention.
Tempered Reflexes consumes its same next-DEX grant through save_mode for native
saves and through the existing save_against reader for typed saves.
movement_action_resolved(ctx, movement_action) -> None is a strict aftermath
notification from the generic Dash-or-Disengage effect after its chosen
Disengage commits. Consumers inspect exact sealed source identity; prior
Disengage flags and a later Dash are not a new Disengage receipt. Tempered
Reflexes grants one next-DEX-save benefit and uses d20_rewrite's existing
one-rewrite-per-die, once-per-fight failed-save reroll contract.
resource_spend_reduction(engine, actor, resource_id, amount, source_id) ->
nonnegative int | None is a strict pre-debit checkpoint. Providers may offer
optional retention, owning consent/limits. The largest reduction wins and is
clamped to the debit; negative/malformed replies abort. No reply preserves
ordinary payment/events. Affordability remains unchanged: retaining an owned
resource does not create it. A reduced debit records its actual amount.
Two-Moons applies only to owned Focus spent on a sealed Dual Wielding talent,
once per fight. Optional decline and pure cost queries do not spend its use.

  jujutsu_redirect_or_throw(engine, owner, creature, feature_id, ctx) -> None.
  Transactional effect notification after Jujutsu successfully redirects or
  throws a creature. owner is the Jujutsu user; creature is the resolved subject;
  feature_id names the triggering feature and ctx is its live effect Context.
  Subscribers own their ability and usage gates. No subscribers preserve the
  underlying resolution without extra state or events. Dispatch with run_checkpoint:
  subscriber errors become CheckpointError and escape outer observational hooks,
  so the enclosing session transaction rolls back
  the resolution and every follow-up benefit, payment and usage receipt together."""
