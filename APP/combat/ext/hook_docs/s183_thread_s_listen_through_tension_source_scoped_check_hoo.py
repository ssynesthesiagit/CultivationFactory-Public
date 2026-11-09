"""Thread's Listen Through Tension source-scoped check hooks:
  contextual_check_subjects(ctx, spec) -> {subject_id: {label, against}} | None
  supplies only the owned actor's current, explicitly connected Thread targets
  for a typed scoped check: each row's plain label, and the actual connected
  creature's entity id as ``against`` (None for an object line), so the check
  resolves through the same ability_check_mode hooks as any check against that
  creature; None adds no check subjects. A label without a current creature is
  inert; a named creature that is no longer on the battlefield is an error.
  contextual_check_modes(engine, actor, frame) -> ADVANTAGE | DISADVANTAGE | None
  contributes only the owned Thread check's printed mode; None is inert.
  personal_location(engine, viewer, target) -> bool | None strictly answers an
  explicitly requested personal location query from current owned Thread facts;
  None leaves ordinary location policy unchanged.
  private_information(engine, viewer) -> list[primitive reading] | None returns
  only that viewer's owned Thread reading; None adds no private information.
  event_audience(engine, native_event_or_journal_dict) -> iterable[actor_id] | None
  restricts history for events carrying owned Thread private facts; None leaves
  the ordinary audience unchanged, and an empty iterable withholds the event."""
