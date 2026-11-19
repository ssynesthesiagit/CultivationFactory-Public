"""Explicit environment capabilities (MGR-T16-athletics-2):
  typed_reactions.wants_opportunity_attack accepts optional intent= for explicit
  movement consumers whose hook already carries the recorded intent. Consent
  uses it rather than requiring an engine-global active intent; missing intent
  preserves the previous fallback. Reaction plans, prohibitions, protection,
  payment and Ask-me keys remain unchanged. consent_display names the trigger.
  flight capability flight_hover_requires_physical_wings=True grants Hover
  only with positive effective flight supplied by native Fly Speed plus
  explicit physical_wings anatomy, or a granted flight row recording
  physical_wings=1. The general profile resolves all providers together;
  capability ordering cannot infer wings from unrelated flight. Missing data
  is inert. Existing unconditional flight_hover remains unchanged.
  Cover redirection uses the single cover_miss_recipient hook documented below,
  after miss correction/replacement against the declared target. Native and
  portable attacks record resolved_target_id; portable on-hit effects follow
  it. attack_scope.retarget publicly rebinds the typed frame and captures the
  new recipient's current marks before damage. Its damage packet, active/HP
  snapshots and target checks also follow the resolved recipient.
  Portable attack specs provide recipient_reach_check(candidate_actor) -> bool,
  a transient callback using the same action/reaction reach as the declared
  target. This preserves area/triggered attacks without a separate action reach.
  It changes no target allegiance rules and is never saved. Without a callback,
  cover_recipients uses the native spec reach/range maximum as before; without a
  cover provider no callback is consulted and no recipient change occurs.
  shared_occupancy replies may explicitly opt into contained=True. This permits
  equally sized map footprints (such as Tiny/Small); the engine still requires
  complete containment of the attached volume in the carrier volume at commit.
  No reply/flag preserves the historical strictly smaller rider contract.
  combat.creature_attachment owns integer carrier-relative offsets, contained
  pair receipts and movement_landed/committed-event following. Ability effects
  create the receipt; the helper has no ability IDs or automatic attachments.
  A contained carrier supplies support at its occupied volume. A self-teleport
  leaves an untransported clinger behind and ends their separated receipt;
  physical motion retains the integer offsets. release_path supplies the nearest
  collision-safe physical route outside a carrier for forced dislodging; it
  searches the six neighbouring placements, so a release may climb or drop into
  the clear space above or below a carrier whose sides are walled. A dislodge
  that finds no legal exit says so in the log instead of passing silently.
  climb_surfaces(engine, actor) -> None or sequence of immutable public
  combat.roof_movement.ClimbSurface(id, walk_ft, cells, climb_check='none',
  handholds=False, bottom_ft=0, catch_dc=None). An optional nonnegative integer
  catch_dc records an explicitly authored catch difficulty, like a RoofSurface;
  None leaves the scene's catch DC in control and invents no default check.
  The inclusive bottom/top altitude bounds apply
  to the climber's anchor; bottom_ft is a nonnegative integer no higher than
  walk_ft. Omitted bottom_ft preserves ground-rooted authored wall behavior.
  Pure strict providers opt into vertical surface routes beside those cells;
  native volume collision, fear, movement budget, OAs and hazards still apply.
  Empty providers preserve roof-only climbing. No provider grants occupancy.
  Carried attachments reconcile zone entry/leave through zones.on_moved with
  forced=True; willing-distance triggers remain excluded and player pauses
  propagate through the containing table transaction.
  climbing capability climb_as_difficult_ground=True prices actual climbing
  segments as ground with Difficult Terrain instead of the ordinary climbing
  surcharge, honoring motion.ignores_difficult for that nonmagical terrain.
  It never removes other costs. Missing/false preserves old prices.
  Wall map handholds is an optional explicit boolean; authored finite-wall
  regions retain it as 0/1. It is not inferred from texture or roof geometry.
  swimming(engine, actor) -> None or {swim_speed_ft: nonnegative integer} is
  a strict pure capability query. Conditions may provide the same field. WATER
  map regions require swimming and use the shared native movement transaction;
  swimming without a Swim Speed costs one extra foot per foot. A Swim Speed
  removes that surcharge only. Other terrain, occupancy, OAs, fear and payment
  remain native. Maps without WATER preserve existing paths and prices.
  breath_duration(engine, actor, normal_seconds, constitution_modifier) -> None
  or positive integer seconds is a strict pure query. combat.breath_clock.start
  creates an explicit integer-seconds receipt; no clock is inferred from lore,
  saves or drowning text. The largest independent duration applies. Each
  completed own turn subtracts six seconds; stop/expiry removes the receipt.
  Providers own their printed multiplier/replacement. No providers preserve
  the caller's ordinary duration, and no receipt makes turn_end inert."""
