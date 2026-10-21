"""Actual carried-item location shared by Glass surfaces and Stars preparations.

Read the native quantity, possession and hand ledgers. Unknown or dropped items
have no inferred carrier or location; a stale recorded drop square is not a
placement on another map.
"""


def carried_item(engine, identity):
    """Return (carrier, possession, held), or None for an unknown identity."""
    from .ext.scoundrel_riders import possessions, held_possessions
    for actor in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        item = next((item for item in possessions(engine, actor) if item['object'] == identity), None)
        if item is not None:
            held = any(value['object'] == identity for value in held_possessions(engine, actor))
            return actor, item, held
    return None
