"""Contracts added on main since the catalogue was split.


Journey lifecycle and possession hooks:
  journey_initialize(session, actor_id) -> None restores an actor's owned
  source state during journey creation; journey_initialized(session) -> None
  runs after all actors initialize. No provider means no changes.
  journey_scene_end(session, previous, current) -> None observes a committed
  scene boundary and resets owned scene-limited state; default is inert.
  journey_source_sheet(sheet, session, actor_id) -> sheet | None transforms an
  owned source's acquisition sheet; None preserves the incoming sheet.
  journey_acquisition(session, actor_id, source, payload, owner_sheet) ->
  result | None handles an owned source acquisition; None declines it.
  journey_acquired(session, actor_id, source, acquisition_id, userdata_root) -> None observes
  a completed acquisition. Both hooks are inert for unrelated sources.
  possession_operation_allowed(engine, actor, holder, item, operation, source)
  -> bool | None gates a possession operation; None leaves it unchanged.


General runtime load query: carried_weight_delta(engine, actor) -> numeric
pounds as text | None. carry.weight adds these deltas to the current carried
load, never mutating sealed inventory. Providers gate their owned property and
current physical carrier; no reply preserves ordinary weight. treasure_armor
uses it to restore ordinary weight while Weightless Harness is suppressed.
Item-property receipt application/removal refreshes native encumbrance.
General runtime capacity query: carrying_capacity_delta(engine, actor) -> integer
pounds | None. carry.capacity_lb adds owned adjustments to sealed capacity (minimum
zero) before the printed multiplier; carry.status and refresh share this effective limit. Default-inert: no
reply preserves compiled capacity. treasure_armor removes its compiled doubling
while all owned Immovable Mountain Grand Shell properties are suppressed,
without changing independent capacity multipliers or the physical inventory.

Cultivated item-property provenance: factory_compiler tags each compiled
enchantment effect with item_property (the inscription's source ID). All effects
of one inscription share that tag, including pre-primary attached packets.
item_cultivation uses compile_bundle to seal named cultivated_properties beside
the existing physical inventory keys, and effect_allowed, attack_bonus,
attack_damage_bonus and ac to read per-item suppression receipts. Without a
receipt these readers return None and preserve physical item functions. Empty
Palm discovers these properties and live item-bound conditions through the
public carried_properties query; treasure_armor uses suppressed to gate its
named enhancements. These helpers never change inventory or sealed catalogs.
- Generic wall data: factory_compiler preserves height_ft, base_altitude_ft and
  placement in native wall profiles. docket_walls uses existing candidate_allowed
  and zone_creation_profile for placement="surface_or_anchors": every wall cell
  needs physical support, or both ends need solid anchors. It sets the real base
  altitude and journals the same finite geometry; no placement field is inert.
    landing_allowed(engine, actor, cell, feet, *, where=None, action=None,
    occupied_cells=None, viewer=None) -> bool is the pure geometry/perception
    half, without candidate-hook dispatch. Player candidate hooks retain action
    when calling it, avoiding recursive destination_allowed validation.
  map_object_components(engine, sealed_map_row) -> None or dict of extra object
                                                 component properties from sealed_map_row.properties.
                                                 Called strictly at map normalization (engine=None)
                                                 and once at seeding, before OBJECT_UPDATED.
                                                 Old scenery without properties loads no providers
                                                 during normalization. Providers validate their own
                                                 string/integer JSON schemas; keys must be disjoint.
                                                 No provider leaves historical objects unchanged.
                                                 object_properties owns inspection evidence and
                                                 afflictions; these are world truth, not revelations.
  object_inspection(ctx, typed_row, object) -> True for exactly one owning reader;
                                                 None for unrelated rows, without mutation. Strict,
                                                 transactional dispatch by inspect_object. Reader uses
                                                 object_properties.evidence/learn to expose ONLY its
                                                 printed facts through private observer_information,
                                                 never the entire component. Default-inert: no reader
                                                 offers no inspection action; resolving an unowned
                                                 inspection is an error. Shared object_properties is
                                                 used by Talismans reading/cleansing and objects.seed.
                                                 remove_object_affliction has kinds, grade and removes
                                                 one matching instance via the native choice channel.
opposed_check_final(ctx, target, result, actor_spec, target_spec, target_failure_effects, target_success_effects) -> None
  Strict notification after outcome rewrites and CHECK_ROLLED, with the selected
  check specs and declared target consequences. Subscribers may enqueue deferred
  choices; absent subscribers are inert. Returning Field uses resisting checks.
intent_settled(engine, actor, candidate, intent) -> None
  Strict notification after an accepted intent's complete effects, before active
  intent/controller routing is cleared. Deferred rewards retain their original
  round and owner-turn clocks. Absent subscribers are inert.
turn_effects_settled(engine, actor) -> None
  Strict notification after end-turn effects and repeat saves, before TURN_ENDED
  expiry and round advancement. The original transaction and intent remain active;
  absent subscribers are inert. Returning Field uses both settlement hooks.

"""
