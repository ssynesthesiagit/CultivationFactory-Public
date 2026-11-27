"""Movement cost query (lock round 22):
  movement_step_surcharge(engine, actor, mode) -> None or nonnegative integer
  feet added per adjacent grid step, before the existing dragging multiplier.
  Pure strict query; independent providers add. Walking terrain and crawling
  costs add rather than multiply. Return None for nonowners/inapplicable modes.
  Walking/flight/granted menus and native step execution use the same query;
  execution rechecks after reactions. No reply leaves costs/paths/events intact.
  In a mixed high-jump route, flight.step_cost passes "walk" for the level
  approach and "jump" for the rising steps. Jump quotes use that same step-cost
  function for ascent, including terrain, surcharges and dragging. The route's
  movement_mode stays "jump"; no per-segment field is stored in saved fights.
  No Speed, state or allowance is changed by the query. Actual spending remains
  recorded in MOVEMENT_COMMITTED. Grid reachable(extra_step_cost_ft=0) is the
  optional default-inert path-search input; it retains canonical tie ordering."""
