"""Movement presentation query:
  speed_explanation(engine, actor) -> list[{label: str, delta_ft: int,
  source_id?: str}]. Pure, optional provenance for that provider's speed hook;
  labels name the player-facing cause. Return []/None for nonowners. These rows
  never alter Speed, candidates or saved state. Terrain step costs use the grid's
  newly entered footprint cells, only for adjacent destinations; summaries do
  not claim an exact path cost.
  engine.movement_explanation(actor_id, destination: Position | None = None)
  -> {actor_id, effective_speed_ft, movement_remaining_ft, reasons, explained_refusal}.
  Reasons have code/message/blocks_destination and optional source IDs, distances,
  speed deltas or difficult-terrain cells/cost. With no destination, Frightened is
  a summary (blocks_destination=None). Only observed fear sources are exposed,
  matching native movement. An empty list does not establish legality. This
  opt-in read-only query never runs during candidate generation or execution;
  saved state, RNG and events are unchanged.
  Terrain step_cost_ft is optional: only an adjacent destination supplies an
  exact step cost via SquareGrid.movement_step_multiplier (entered footprint
  cells, base costs, zone costs and drag). Other queries summarize terrain,
  without quoting a cost for an unspecified path."""
