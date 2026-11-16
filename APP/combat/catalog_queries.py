"""Catalog queries index compiled actions without storing anything in fight state.

Action parameters are fixed after compilation; a mid-fight change replaces the
action object. Identity therefore identifies the version used by both indexes.
"""
from .read_queries import invariant_memo


def owned_actions(engine, owner_id):
    """Return this owner's actions in original catalog order, as a tuple.

    The identity signature costs a C-level walk rather than repeatedly reading
    every foreign model's attributes. Retaining the action objects prevents ID
    recycling. Version/event keys also separate transactions and restored states.
    """
    return invariant_memo(engine, ('catalog_owner_index',), lambda: _owner_index(engine)).get(owner_id, ())


def _owner_index(engine):
    """Retain structural invalidation outside pure enumeration as before."""
    catalog = engine.action_catalog
    signature = (id(catalog), tuple(map(id, catalog.values())),
                 engine.state.state_version, engine.state.event_sequence)
    entry = engine.__dict__.get('_catalog_owner_index')
    if entry is None or entry[0] != signature:
        owners = {}
        for action in catalog.values():
            owners.setdefault(action.owner_id, []).append(action)
        entry = (signature, {owner: tuple(actions) for owner, actions in owners.items()})
        engine.__dict__['_catalog_owner_index'] = entry
    return entry[1]


def catalog_matches(engine, name, predicate):
    """Return matching actions in catalog order, rechecking replaced objects."""
    cache = engine.__dict__.setdefault('_catalog_matches', {}).setdefault(name, {})
    result = []
    for source_id, action in engine.action_catalog.items():
        entry = cache.get(source_id)
        if entry is None or entry[0] is not action:
            entry = (action, bool(predicate(action)))
            cache[source_id] = entry
        if entry[1]:
            result.append(action)
    for source_id in cache.keys() - engine.action_catalog.keys():
        del cache[source_id]
    return tuple(result)
