"""Actor-wide number provenance for shared checks and DCs.

Needle's public numeric helpers (used by save_dcs, ability_checks and other
plug-ins) read this opt-in bundle field before legacy action inference.
Compilers with per-talent key abilities can preserve the unmodified actor
numbers through compile_bundle. Missing fields preserve historical behavior.
"""
from typing import Any


def sealed_actor_numbers(engine: Any, actor: Any) -> dict[str, Any] | None:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id and isinstance(bundle.get("actor_numbers"), dict):
            return dict(bundle["actor_numbers"])
    return None
