"""Read-only resource wording shared by generated and general status readings.

Use saved action costs first, related owned action costs second, and only an
unambiguous saved actor pool last. Never infer a paying pool from an ability name
or from the target's resources. Unknown or conflicting pools remain explicit.
"""
import re

POOLS = {"resource:core.qi": "Qi", "resource:core.stamina": "Stamina",
         "resource:core.resonance": "Resonance"}
POOL_IDS = {*POOLS, "resource:core.cp"}


def paying_pool(engine, holder, row, record=""):
    catalog = getattr(engine, "action_catalog", {})
    action = catalog.get(row.get("source_definition_id"))
    owner_id = action.owner_id if action else row.get("source_actor_id") or row.get("owner_id")
    owner = engine.state.actors.get(owner_id) if owner_id else None
    def pools(actions):
        return {r for a in actions for r, _ in getattr(a, "costs", ()) if r in POOL_IDS}
    bound = pools([action]) if action else set()
    if bound:
        return next(iter(bound)) if len(bound) == 1 else ""
    related = pools(a for a in catalog.values() if record and owner is not None
                    and a.owner_id == getattr(owner, "entity_id", owner_id)
                    and ((a.parameters or {}).get("typed") or {}).get("source") == record)
    if related:
        return next(iter(related)) if len(related) == 1 else ""
    retained = set(getattr(owner, "resources", {})) & POOL_IDS
    return next(iter(retained)) if len(retained) == 1 else ""


def expand_cp(text, pool):
    name = POOLS.get(pool)
    replacement = (name + " (points from the paying Path resource pool)" if name else
                   "cultivation points (paying Path resource pool unavailable in this saved fight)")
    return re.sub(r"\bCP\b", replacement, text)
