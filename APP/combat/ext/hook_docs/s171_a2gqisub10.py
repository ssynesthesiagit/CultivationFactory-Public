"""Accepted voluntary route context (A2GQISUB10): movement_steps.route(engine, actor)
returns a read-only mapping with actor_id, intent_id, ignore_oa_from and a tuple of Positions including
the starting position, or an empty mapping outside native route resolution.
The existing opportunity_policy scopes it across the complete route, nested
movement, errors, pauses and early returns. No new state/event schema, policy
or ability branch is stored. Flowing Passage consumes its first-hostile waiver
only at movement_attempt and only if the full accepted route is inside its own
placement; pure opportunity queries never consume it."""
