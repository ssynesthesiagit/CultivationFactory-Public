"""reaction_roll_reasons(engine, reactor_id, reaction_id, target) -> list[dict] | None is a
pure, default-inert presentation query. roll_reasons.remember_reaction calls it
when a Reaction is accepted into an attack roll (core still applies the roll
mode). Each row is a roll_reasons.source(...) receipt; providers return None for
Reactions they do not own, so other characters see no change."""
