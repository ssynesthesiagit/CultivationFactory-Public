"""Read-only owner index shared by hand occupancy's policy and loadout queries.

ActionDefinition.owner_id is frozen. Only ownership is indexed: mutable action
parameters and fight state are still read by consumers on every call. A replaced,
inserted, removed or reordered action invalidates the index outside a pure
enumeration, even without a state version change. A pure pass has a fixed
catalog; later passes always recheck it. Nothing is stored in fight state.
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
