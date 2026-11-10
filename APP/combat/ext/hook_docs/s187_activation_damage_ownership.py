"""Activation damage ownership hooks and Qi potency integration.

Activation damage ownership (damage_activation.py; Qi potency and Barrage):
damage_activation_identity(ctx) -> nonempty str or None. A split delivery
provider may return its existing persisted sequence identity. Exactly one
provider may own an identity. Missing providers use the committed intent ID.
The helper stores per-provider choice/consumption receipts in existing turn
flags, so nested attacks and cold continuation share one activation receipt.
compile_bundle providers may seal typed.origin_feature_id to a real printed
source for plug-in actions whose typed.source is a local effect key. Consumers
validate that source against authority; names and character Path aren't proof.
The maneuvers compiler hook receives source actions after native weapon
delivery binding, so weapon_attacks sees a real sealed profile for both basic
attacks and weapon-delivered techniques. A second idempotent binding pass
handles new maneuver variants. No action is admitted from display text.
hit_feature_pre_damage(ctx, group) -> True or None opts an owned hit-feature
menu into confirmed-hit consent/payment before primary damage. paid_hit and
attack_modifiers otherwise retain their existing post-damage timing.
hit_feature_paid(ctx, target, source, costs, effects) -> None observes the
selected source and actual paid resource pairs before damage. Consumers may
publish activation-local delivery metadata in ctx.damage_cache. No payment,
choice or effects are invented by the notification. Qi potency uses both
hooks to admit a genuinely paid Qi rider and offer the weapon/technique
damage-roll choice before the weapon packet; decline leaves it unqualified.
Qi potency's zone_created seals its creating activation identity and signed
bonus in the journaled trigger_profile. zone_trigger_context opts only those
new zones into the creating activation's saved consumption receipt; old zones
retain delayed-area suppression. Receipts live in the engine-retained _round_
turn-flag namespace as per-fight history, not a timed condition or benefit.
Zone lifetime/concentration and trigger eligibility stay with the native zone.
numbers.activation_damage_bonus_v1=1 opts freshly compiled owned rows into
activation-owned roll modifiers. The executor's historical cached potency
path remains for unversioned sealed bundles, preserving their replay bytes.
The standalone cached packet allocator (ext/qi_technique_potency.py) serves
those unversioned bundles and stands down on the marker, so a sealed
activation is never asked or paid twice.
The marker alone grants no bonus or qualifying source; ordinary weapons only
qualify after an actual owned paid Qi hit feature has been selected and paid.

"""
