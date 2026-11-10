"""reaction_resolved(engine, event) -> None is an observational, default-inert notification
called once for every accepted REACTION_RESOLVED event, after it is recorded.
Providers must gate on their own event source and only attach any scoped receipts
their reaction owns; unrelated reactions have no effect. During an accepted
reaction, provider failures propagate to the foreground/persistent-intent
checkpoint; they cannot be logged and skipped after mutating the fight. That
checkpoint restores all dependent work before persistence records one GM refusal.
Deferred response effects retain this failure contract after this hook returns.
No provider means no extra work or state changes."""
