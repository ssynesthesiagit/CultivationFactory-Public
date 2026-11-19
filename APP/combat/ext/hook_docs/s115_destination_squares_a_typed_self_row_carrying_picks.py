"""- Destination squares: a typed self row carrying "picks_destination": true (with distance_ft: feet | "speed" | "half_speed")
  makes its SELF action offer squares like a self-teleport (typed_executor.teleport_reach) and passes the chosen square as
  Context.destination; the row's own effect type does the moving (rider lane C8: Black Current's River-Cut route). Rows
  without the key are unchanged.
- Self-teleport destination (the other half of the same seam): when a self-scoped teleport row (applies_to null/self, type
  "teleport" or type "movement" with mode "teleport") has no square bound to the action, typed_executor.block_movement calls
  teleport_steps.ask_destination(ctx, reach, *, name="") -> teleport_steps.Destination, the shared "where do you want to land?"
  question behind every self-teleport. It enumerates teleport_steps.destinations(engine, actor, feet) -- unoccupied, in-grid,
  unblocked, visible squares within reach -- and rides the bounded choice transport, so the answer is a real player decision
  that pauses the fight, is labelled with the ability and the creature, and rides the intent, so a reaction interrupting
  between paying the cost and choosing does not drop it. Destination.square is the chosen cell or None to stay put;
  Destination.asked says a player was actually put on the spot, so the caller can word its "nothing happened" line truthfully
  instead of guessing from an empty selection. The question is asked once per represented hop, not once per row:
  teleport_steps.hop_key keys the answer on the use, the creature, the ability, the reach and the aimed target, and
  the resolved answer is kept on Context.hop_destination (resolution-local, never saved), so the teleport row and the
  parser's movement(mode=teleport) row for one hop ask once and land on the same square. Default-inert: an AI combatant,
  an engine with no recorded control mode, no transport, no reach or nowhere legal to land returns Destination(None, False)
  and the caller keeps its own previous behaviour, so AI fights and saved fights replay unchanged; a decline returns
  Destination(None, True) and the creature stays put, its cost already spent. Only self rows ask: a row that teleports
  another creature is not answered here and keeps its GM instruction.
  Context.hop_completed records the entire player-selected attempt after gates return, including a blocked result;
  duplicate rows do not retry it. A transaction pause never marks completion. Both memos are resolution-local.
  teleport_steps.payment_text(ctx) describes the compiled economy slot and amount/pool in prompts and declines.
  teleport_steps.hop_reach(ctx, row, reach) -> int resolves null-distance within_range parser rows to the
  unambiguous explicit self-teleport reach; explicit or ambiguous multi-hop distances remain separate.
  Unbound questions use teleport_steps.teleport_requirement(typed) -> str | None: top-level teleport_where
  takes precedence over teleport-row where, matching the bound menu contract. A "darkness" requirement
  checks both endpoints using motion.obscured/obscured_at. Absent metadata leaves ordinary teleports unchanged."""
