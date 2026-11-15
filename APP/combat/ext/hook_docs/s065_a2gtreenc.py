"""Treasure enchantment compilation (A2GTREENC): compile_weapon_enchantment(row)
-> list[typed effect] | None is a strict compile-time query for one resolved
weapon enchantment. None preserves the existing generic text parser; [] means
the provider has resolved it without on-hit effects. At most one provider may
claim a row. Providers must bind policies to reviewed printed text, return
JSON-compatible fresh effects, and perform no engine writes. A custom effect
may supply expected_damage (a nonnegative integer per-hit AI estimate); native
damage effects retain their dice-derived estimate. This estimate never rolls or
changes delivered damage. The same compiled
effects are copied into every weapon attack variant before sealing. No provider
means no change to compilation. treasure_enchantments uses this and the existing
effect dispatch for Frost's combined 15-foot cap with per-item/source expiry, Dreams-state bonus and printed
Spirit-Striking creature-kind dice. Native damage and source-owned expiry apply.
Flame-Vein uses compile_actions/candidate_allowed and an UNTIL_REMOVED condition
for its per-item Bonus Action toggle. Its condition key is the original
physical weapon action ID, so taking the weapon carries its lit state; ignition
removes that exact item's marker from any former bearer. The four damage bonuses use damage_packet_selection
before the primary damage packet, preserving bonuses on lethal hits and Dreams
eligibility before wake-up saves; their resolution-local roll-id receipts prevent
a second bonus on the ordinary on-hit pass. Because that pass is outside the
ordinary effect dispatch, each attached packet asks the general effect contract
for itself before it is delivered: effect_permitted is queried with the ORIGINAL
enchantment row and its recipient (never the converted damage row), and every
effect_resolution_scope published for that original row encloses the delivery, as
it would an ordinary effect block. A denied bonus is spent for that hit instead of
being deferred to the ordinary on-hit pass, which would otherwise deliver what the
contract just denied. No new state is serialized for this receipt."""
