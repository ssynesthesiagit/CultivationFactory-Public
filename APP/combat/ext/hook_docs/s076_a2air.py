"""Air altitude effects (A2AIR): air_downburst_descent(ctx, row) and
  air_cyclone_lift(ctx, row) return None and handle only their newly reviewed
  owning Air source rows. Downburst uses falling.displace without automatic
  settling, then the native supported test and condition path for landing.
  Cyclone attaches flight_suspended=1 to the native restrained condition before
  a two-square lift; native repeat saves/expiry release its suspension. Missing
  effect rows and other sources are inert; no new hook or saved lock is needed.
Explicit cylinder geometry (A2AIR): area.height_ft is an integer height above
  the aim plane with an exclusive top, independent of horizontal size_ft radius.
  in_area reads it; area_projection keys it; factory_compiler and zones carry
  it into sealed zone profiles. Both Cyclone Prison and Downburst Seal use this
  general seam. Missing height preserves the historical spherical interpretation.
  Air current membership and projectile intersections use the sealed volume
  only for height-stamped zones; unstamped zones keep their legacy plane tests.
Yang second pass (A2YANG): yang_recovery uses existing compile_passives,
  attack_completed, save_final and nested event hooks for Sunlit Opening.
  Only fresh owned Sunlit rows collect Complete Aim receipts. Final hit/save
  outcomes prompt the owner; attack-mode queries are pure, and actual attack
  events consume the target-specific benefit. Owner-turn tokens expire it.
  yang_bloom uses compile_action, effect, mark_applied and turn_end. Its
  selected zone has explicit start-only ally/enemy triggers; the area mark
  shares the normal Rising Mark cap through exact-instance removal and
  retained zone updates. Old rows and unrelated marks are inert. Neither
  module adds a hook or changes a saved catalog.
Observer-specific zone sight (A2SMOKE):
  zone_view_blocked(engine, zone, viewer, seen, *, sight_only=False) -> True or None is a strict pure
  opt-in query shared by zones.hidden_from and zones.attack_modes. It contributes
  a restriction for that observer only, never mutates zone density or geometry.
  Providers must support senses.cell_probe endpoints (PROBE_FIELDS). When
  sight_only=True, sense exceptions use senses.perception_senses(..., sight_only=True)
  so nonvisual combat sight cannot exempt ordinary vision. The default retains
  existing sense exceptions; absent conditions/providers remain inert. Existing
  walls/heavy-area contributions combine normally. With no matching condition
  or provider, historical sight/modes remain unchanged. zone_view_restriction
  stores a source prefix and preserved senses on its recipient with native expiry;
  independent pinpointing senses and solid-barrier LoS/LoE are untouched.
Shared opt-in response limits and pending technique outcomes (A2SMOKE):
  response_use {group, name} consumes one named allowance for the actual round.
  response_limits.available(engine, actor, group) is a pure query;
  consume(engine, actor, group, source, name) commits an already accepted use; row_allowed
  and candidate_allowed inspect only compiled response_use rows. The evented
  condition holds strings and an integer round. No row means legacy behavior.
  pending_technique_result {cancel: true} ends the accepted typed activation
  using the existing paid-counter protocol. Alternatively attack_mode/save_mode
  bind to that exact triggering intent and action ID. The existing attack_mode,
  save and technique_used hooks consume and retire those policies; unrelated
  uses and nested reaction saves cannot borrow them. No new core hook/schema.
  Black-Lung Cloud seals nonbreather_advantage on its choking wrapper; the save
  hook queries combat.physiology.trait. Its paid movement variant reuses the
  public area mover, native resource costs and same per-turn trigger IDs.
Surface-bound areas (A2MAGMA): reviewed area or top-level effect rows may opt in
with surface_bound=true. surface_areas uses candidate_allowed to require the
arena floor or a finite solid column, and zone_subject_allowed to restrict a
retained surface hazard to supported creatures on its own plane. Unmarked saved
actions are inert. surface_translation is a typed effect with source (sealed
technique id or owning action id), max_ft and optional min_ft (integer feet,
zero by default). min_ft=max_ft enforces an exact endpoint distance. Optional
ai_preference="hostiles" ranks perceived supported enemy exposure minus friendly
exposure and suppresses AI movement without a positive improvement; this is
future rider utility, never immediate damage. Manual/Ask-me owners retain every
legal destination and copy choice. Unknown/remembered bodies supply no current
positions to this preference. The matching action parameter
surface_translation gates destinations. Only the owner's active Concentration
area is moved, including held Concentration; every retained cell needs a legal
continuous route within the distance budget, with no diagonal corner cutting; both orthogonal swept footprints need support.
Multiple eligible copies ask the owner which area to move; readable copy numbers,
casting rounds and remaining round clocks distinguish overlapping areas without
exposing stored IDs. Copy numbering precedes destination/preference filtering. SELF buttons ask
for a perceived legal origin without inheriting the original casting range;
CELL buttons may also supply a destination. Neither path reads live authority.
Geometry translates rigidly, including a line's stored vertex; width, lifetime,
Concentration and trigger counters remain unchanged. retained_updates records
the existing zone snapshot and zones.sync_inside reconciles continuous effects.
No new state/event format, policy, or core ability branch is introduced.
Puppetry vessel thread-end receipt (A2PUPPETRY):
  vessel_thread_ended(engine, owner, zone, reason) -> None is a strict
  transactional receipt after a controlled vessel breaks or becomes inactive
  outside control range. The zone is the actual vessel whose thread ended;
  reasons are BROKEN, OUT_OF_RANGE, or SEVERED for an explicit line-cut provider.
  Ordinary expiry, dismissal and capacity replacement do not emit this receipt.
  Consumers own compiled-row admission, resource grants and scene limits.
  No subscribers leaves vessel behavior unchanged. No persisted format changes.
  puppetry_defenses uses this receipt for Severed Thread Recovery and the existing
  final_damage reduction/settle contract for Puppet Drinks the Blow. Protection
  pays one owned mark, no Reaction/CP; the vessel takes half the actual allocated
  reduction, rounded down. Automatic protection admits allies/self only and
  uses perceived mark bearers. Physical line-cut delivery remains unimplemented."""
