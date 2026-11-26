"""Walk action effects for the compiler, typed executor and hit-modifier delivery.

Follow ordinary outcome branches and nested effect lists. Persistent zone
triggers are separate activations, not children of the effect that creates them.
"""
from typing import Any, Iterator


def walk_effects(effects: Any) -> Iterator[dict[str, Any]]:
    for effect in effects or ():
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from walk_effects(effect.get(branch))
