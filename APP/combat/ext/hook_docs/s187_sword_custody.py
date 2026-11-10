"""Sword custody and activation contracts.

journey_encounter_settled(session, actor_id, engine, creature) -> None strictly
notifies sources after terminal-fight health, resources and position import;
sources may import committed native ledgers. No provider changes nothing.
inventory_committed(engine, actor, inventory, source) -> None strictly notifies
providers after inventory commit and carry refresh; no provider changes nothing.
journey_source_sheet(sheet, session, actor_id) -> copied sheet | None projects
committed source progression; None preserves the sheet.
journey_acquisition(session, actor_id, source, payload, sheet) -> result | None
admits a source acquisition for recompilation; unrelated providers are inert.
journey_held_weapons(session, actor_id) -> list of {owner_action, row} | None
queries lawfully held physical implements from another bundle for holder
recompilation. Custody prevents simultaneous lender use; None is inert.
weapon_delivery_without_grip(engine, actor, weapon, action) -> True | None
admits only a qualifying delivery with that exact weapon without a readied grip;
None retains ordinary grip requirements.
compile_zone_spec(spec, action, mechanic) -> copied spec | False | None runs
after generic zone derivation; False delegates placement, None preserves it.
armament_control_range(engine, owner) -> nonnegative feet | None contributes
dynamic control range; the largest reply wins, no provider is inert.
armament_relocation_allowed(engine, owner, condition, point, feet) -> False |
None vetoes a source-restricted move; None preserves ordinary motion.
hand_occupants(engine, actor) -> {part_id: occupant_id} | None: Sword Array
contributes only owned projected swords actively wielded in persisted grips;
real swords use equipment readiness, floating swords occupy no hand.

activation_settlement(ctx, receipt) -> None strictly notifies after typed
effects and before technique_used; no subscriber is inert. The receipt contains
source provenance and committed damage recipients; damaged_ids contains only
positive HP or temporary HP loss. activation_effects_resolved(ctx, receipt)
is the preceding strict aftermath phase; the final receipt is rebuilt after it.
attack_damage_type_override(ctx, effect, target, printed_types, strike_index)
-> str | None strictly allows one source-authorized replacement type for the
1-based strike; None preserves the printed choice, conflicting replies fail.
journey_combat_setup(session, actor_id) -> dict | None strictly projects
persistent owned selections before genesis; no provider leaves setup unchanged.
"""
