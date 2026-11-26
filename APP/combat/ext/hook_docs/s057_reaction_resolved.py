"""reaction_resolved(engine, event) -> None is an observational, default-inert notification
called once for every accepted REACTION_RESOLVED event, after it is recorded.
Providers must gate on their own event source and only attach any scoped receipts
their reaction owns; unrelated reactions have no effect."""
