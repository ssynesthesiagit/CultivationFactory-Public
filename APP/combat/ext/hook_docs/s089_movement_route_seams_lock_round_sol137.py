"""Movement route seams (lock round SOL137):
  opportunity_allowed(engine, reactor, mover) -> False or None is strictly
  observational: no choices, spending, conditions, concentration or event writes.
  It observes existing protection for menus, route quotes and execution.
  opportunity_response(engine, reactor, mover) -> False or None runs only
  during an accepted attack, after eligibility and before OA consent. Native
  steps and ability-granted OAs share the typed reaction selector; legacy native
  reactors use the step seam directly. ask=False never invokes this response.
  It may ask the mover to release protection or choose a witness, and commit
  the resulting costs, saves and effects;
  False cancels this attack. No providers means no change. Guiding Star uses
  this response seam; its released protection remains an observational veto.
  Unrecorded Movement also chooses/saves only in this response or the accepted
  movement event; its observational veto reads existing witness protection.
  native_route_selection(engine, actor) -> None or pure selector callable.
  selector(start_cell, cost_optimal_predecessors, native_costs, legacy_parents)
  -> mapping. legacy_parents is None on the ground; spatial searches provide
  the original single-parent traversal for existing selector contracts. Default
  spatial routes minimize horizontal steps, then deviation from the start-goal
  line (combat/spatial_routes.py). The shared safe selector compares against
  that same default path so equal safety scores retain its short projection.
  destination_cell -> ordered adjacent cell tuples. Ground search cells are
  (x,y); spatial and rooftop-walking cells are (x,y,z); climbing cells are
  (x,y,z,has_climbed), where the trailing boolean records whether the route has
  already left support to climb the face or keep a grip. That boolean is part of
  the search state: two routes reaching one (x,y,z) with different booleans are
  different cells, so it must be preserved. A provider needing only coordinates
  projects cell[:3]; every cell it returns must be a node copied unchanged from
  the supplied maps, never rebuilt shorter, so the engine can bind the chosen
  equal-cost path. Maps and predecessor sets are immutable views.
  Receipt-aware searches use (x,y,z,inventory,has_climbed,runup_heading) nodes;
  trailing fields are opaque search state and must be preserved. A returned
  mapping may expose .ranks[node] = (OA_count, hazardous_steps), allowing equally
  priced states at one destination to retain the same native safety preference.
  Every returned edge must belong to the native DAG;
  omitted destinations retain the original route. At most one provider applies.
  Called once per movement search before candidate binding. Inputs are read-only;
  no provider retains native costs/destinations and the default route chooser.
  The unlocked movement_routes provider applies only to Factory fighters. It
  minimizes OA crossings then hazardous squares among equal-cost native paths.
  Memoization lives for one actor query, never across state changes or execution.
  Gate2Engine.opportunity_eligible(mover, previous, next, ignore_oa_from=(),
  free_ft=None, reactors=None, cache=None) -> sorted reactor IDs is the shared
  pure routing/execution query. previous is a projected mover position; optional
  reactors is the observed set for previews, live set for execution. cache is
  caller-owned and valid for one unchanged actor/menu query only. Ask-me reports
  eligibility without asking or spending; execution keeps its reaction pauses.
  It reuses typed_reactions eligibility, waivers, perception and reaction plans.
  ActionIntent.movement_path/movement_mode are optional, omitted from old dumps.
  A supplied full adjacent route is rebuilt and priced with granted_movement's
  validator and flight.step_cost. Its path and mode enter candidate identity;
  legacy destination-only identity stays unchanged. Native step execution still
  rechecks costs/occupancy/altitude, forced stops and checkpoints after reactions.
  Recovery validates recorded MOVE candidate bindings and consumes the original
  path through the existing one-use prepared-candidate seam, without rerouting.
  movement_routes.context_for_payload is the general preview/commit service seam;
  TabletopService.preview_move_path/commit_move_path expose it to UI callers.
  Metadata expected_opportunity_attack_count/expected_opportunity_attacks lists
  observed potential reactors by actor_id/display_name, not guaranteed attacks.
  No route is a promise that hazards/reactions will allow reaching its endpoint."""
