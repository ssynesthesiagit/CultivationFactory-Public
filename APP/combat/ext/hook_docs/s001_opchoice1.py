"""Printed pre-save operation choices (OPCHOICE1):
  operation_choice(ctx, operation, chooser) -> list[str] | None is a strict,
  transactional choice query, before any enclosing save roll, automatic-success
  query or save reactions. It must not apply the operation's consequences.
  An immediate outcome operation opts in with
  pre_save_choice={"key": "<decision name>", "chooser": "actor" | "target"}.
  ctx.target/targets name this save's recipient; failed_save is None.
  Providers gate on their owned operation and ask the supplied chooser using
  needle.ask/option_spec (manual and Ask me pause; AI chooses automatically).
  Exactly one owning provider returns option IDs (an empty list means no
  eligible selection). None declines ownership; missing/conflicting providers
  on marked rows are errors, never a silently skipped decision.
  Same operation type/key in both outcomes shares one answer for this save's
  recipient. The executor adds selected_options to fresh outcome rows; the
  operation consumes those IDs instead of asking again. Printed post-save
  choices stay inside the operation. Neither authority rows nor fight state
  are mutated; preview replay re-asks through the existing answer transport.
  Unmarked operations are unchanged. Nested saves prepare their own immediate
  choices only when reached. Keys must distinguish separate printed decisions."""
