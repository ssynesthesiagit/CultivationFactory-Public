"""Save-result abilities using d20_rewrite's shared recheck contract.

Seal of Final Authority owns its typed row; Read the Killing Line extends the
existing Calamity plug-in. No engine patching or late outcome overrides.
"""
from typing import Any

from .d20_rewrite import Rule, register

SEAL = "foundation.golden_mandate_seal_v0_2B.seal_of_final_authority"


def seal_guard(engine: Any, holder: Any, rc: Any) -> bool:
    # Keep plug-in registration order unchanged during ext's sorted loading.
    from .talismans import formula_of

    action = engine.action_catalog.get(rc.source_id)
    # Retain the reviewed Foundation scope across normal and thrown deliveries.
    return (rc.source_actor is holder.actor and action is not None
            and formula_of(action) == "binding_talisman")


def seal_penalty(engine: Any, holder: Any, rc: Any) -> int:
    return -(int(holder.numbers.get("pb") or 2) + int(holder.numbers.get("key_mod") or 0))


def seal_after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    if rc.dc is not None and result.total < rc.dc:
        engine._apply_condition(rc.roller, "condition:typed.reaction_denied", holder.feature_id, holder.actor.entity_id,
                                expires_on="START_OF_TARGET_NEXT_TURN",
                                data={"label": "Seal of Final Authority: cannot take Reactions until the start of your next turn"})


register(Rule("seal_of_final_authority", "Seal of Final Authority", when="succeeded", who="enemy", range_ft=60,
              see=True, op="choose", choose=lambda engine, holder, rc: rc.natural,
              costs=((("edict_seal", 1),),), reaction=True, guard=seal_guard,
              bonus=seal_penalty, after=seal_after, checkpoint="D20_REWRITE_ROLL"))
