"""Athletics movement and Dash contracts.

  action_dash_receipt(engine, actor, source_definition_id) -> True or None
  is the Dash-completion receipt: a typed Action whose printed trigger is
  the Dash Action itself answers True for its own owning actor's own
  action, and on_action_completed then treats its completion as that
  Dash's completion (the receipts a native Dash fires fire for it too).
  Pure read; default-inert -- no provider, no rewrite.
  dash_bonus_ft(engine, actor) -> nonnegative int or None is the extra
  feet an owned row adds when the Dash (or Disengage) is taken as the
  Action (Speed Boost's printed +10 feet); the feet sum into the
  dash_reach query. dash_reach is summed for EVERY Dash-replacement query,
  not only when the Dash is the Action: Flash Step's distance reads the same
  dash_reach, so a provider's bonus also applies there. Any other return
  (bool, float, negative) raises. Pure read; default-inert.
Dash-distance query (combat/flight.py dash_reach, the "distance you could move
  through the Dash"): dash_reach(engine, actor) -> nonnegative integer feet. The
  distance one Dash moves this creature, across the modes it owns: a Dash grants
  the creature its own Speed again in the mode it is taken in, so the printed
  bound is the largest Speed the creature actually owns right now -- its walking
  effective Speed, or the Fly or Climb Speed when that is the mode it would move
  through -- plus every Action-only Dash bonus (the dash_bonus_ft hook below).
  Pure read; nothing is granted, spent or persisted. Any plug-in may bound an
  effect by it (the distance_ft token "dash_reach" resolves it in
  combat/typed_executor.py movement_distance_ft, shared by execution and
  teleport_reach), so no ability hard-codes a multiplier. Self effects with
  this token require permission to Dash in both admission and execution.

Action-only Dash bonus hook (combat/ext/__init__.py dash_bonus_ft, answered by
  combat/ext/athletics.py): dash_bonus_ft(engine, actor) -> None or integer feet.
  A provider answers the extra feet its row adds when the Dash (or Disengage) is
  taken as the Action -- Speed Boost's printed "+10 feet". The feet sum into
  dash_reach; providers return early (None) for actors that do not own their row.

Dash-completion receipt seam (combat/typed_reactions.on_action_completed, answered
  by combat/ext/athletics.py): action_dash_receipt(engine, actor,
  source_definition_id) -> None or True. A typed Action whose printed trigger is
  the Dash Action itself ("When you take the Dash Action, ...") answers True for
  its own owning actor's own action, and its completion is then treated as that
  Dash's completion: the receipts a native Dash fires (Coordinated Movement's
  Focus regain, Speed Boost's extra feet, Meridian Threading's choice) fire for
  it too, through the same motion.after_action and action_completed dispatch.
  The dispatched source_definition_id classifies the completion trigger;
  engine._active_action_source_id retains the original executed Action's
  identity throughout both calls. Resource receipts bind to that execution
  identity and transaction, including when the trigger is classified as Dash.
  Completion receipts are separate from movement grants: a replacement
  teleport completes the Dash without granting unused movement or a typed
  Dash count. Default-inert: no provider, no rewrite.

Typed Dash subevent receipt (combat/flight.py dash): every typed Dash grant
  (a compiled movement row granting Dash movement, never a replacement
  teleport) appends the non-mutating TYPED_DASH_GRANTED event with the
  resulting native/typed Dash counts, so any provider can observe that a typed
  Dash was granted. The dash counts are turn flags, restored by the
  runtime-control snapshot like every other granted movement (combat/
  gate3_reducer.py NON_MUTATING_EVENT_TYPES).

Map altitude ceiling (combat/gate2_grid.py SquareGrid.altitude_ceiling_z): the
  highest authored standing altitude of the map, in 5-foot steps (0 on a flat
  map), read from the roof surfaces and the raised terrain heights. A general
  query for any altitude-aware enumeration: the shared teleport destination
  query (combat/ext/teleport_steps.py destinations) and the historical
  destination enumerator (combat/gate4_engine.py) offer every standing level of
  a map with authored altitudes, so a visible legal elevated endpoint is a real
  choice; a flat map keeps ground level only.

Per-activation Motion receipt (combat/ext/athletics.py): motion_applied_once(
  engine, actor, owner_id) -> bool and record_motion_application(engine, actor,
  owner_id) -> bool. The "apply each Motion talent only once" receipt of a
  capstone that opens a window for any number of Motion talents: the receipt is
  a current-turn flag keyed by the exact Motion talent's owner id, written only
  while that capstone's own condition runs, so it bounds one activation of one
  owner and never limits any other character's Motion talents. A Motion provider
  asks motion_applied_once before it applies and records with
  record_motion_application, which returns True when that talent had already
  applied this activation. Pure turn-flag state; it survives a table commit and
  reload like every other turn flag.

  Production consumers: Motion action candidates consult the receipt and accepted
  Motion actions record it; triggered Afterimage, Dizzying Tumble, Flowing
  Pursuit and Sudden Flank consult/record actual applications. Standing benefits retain their
  printed duration; pure capability/menu queries never spend an application.
  The capstone compiles owned printed Motion classifications into passive rows
  so admission also works after a cold reload.

motion_application_allowed(engine, actor, feature_id) -> bool | None:
  combat.motion.application_allowed asks before a triggered Motion application.
  False denies this application; None is inert. No state mutation.
motion_application_committed(engine, actor, feature_id) -> None:
  combat.motion.application_committed dispatches after an actual application,
  never a declined prompt or menu quote. Receipts belong to the subscriber.

Physical climbing aids (combat.roof_movement.climb_route_capability):
  climb_route_capability(engine, actor, path, speed_ft) is a context manager for
  one adjacent route and integer Climb Speed. Rope/ladder riders supply handholds
  along that route; native movement still checks geometry, posture, Speed, cost,
  voluntary restrictions, interruptions, opportunity attacks and hazards. The
  scope is transient, actor specific, default absent, and unwinds on errors and
  choice pauses. Pass Route(path, 'climb') to engine.move_path to spend ordinary
  movement allowance through native movement.

compile_final_actions(actions, info) -> list[ActionDefinition] | None:
  General immutable catalog transform after native weapon, natural/unarmed and
  improvised deliveries exist, before per-action transforms and publication.
  info contains owner_sheet, owned_ids, mechanics, numbers, short, actor_id,
  mods and pb. None is inert. Return the complete catalog, preserving unrelated
  deliveries; NONE-economy grants receive normal free-primary declarations.

Rope anchor point choice (combat/ext/athletics.py ask_anchor, the
  choice:needle.rope_anchor question): the Rope Swing Adept's anchor is asked
  through the bounded choice transport exactly as a teleport destination is --
  a real player decision, labelled with the ability and the creature, asked only
  of a person. An AI combatant automatically chooses the nearest legal square
  above the fighter (then lowest height and coordinates). Missing control
  metadata leaves the rope unchanged, as does a player seat without choice
  transport or a swing with nowhere to anchor. A recorded AI seat needs no
  transport. The anchor squares are the shared destination query's, filtered to
  squares above the fighter, and the square itself is picked on the map through
  the general choice_map_pick seam (this module answers only for the rope
  anchor question). The chosen anchor rides the swing condition's data as
  integer coordinates, so it survives a table commit and reload.

"""
