"""Insights that rewrite a d20 after it is rolled, through the shared d20_rewrite owner (OPUS1 batch 2).

Each Insight is sealed into one passive row of block ``insight_rewrites`` (kind = the Insight id) with its plain
player outcome; the rules below find holders by that feature id (d20_rewrite.row_holders), so a creature without the
row is never a holder. Consent (Ask me / Auto), payment, limits and the log are the shared owner's.

Karmic Debt            once per fight ("once between Full Cultivation Sessions"; no rest happens inside a fight), when
                       the owner fails a saving throw or a Cultivation Check, it may turn the failure into a success. The
                       use is logged as a Karmic Debt; who the creditor is and what service it may demand stay with the
                       Game Master (outside fights).
Persistent Technique   once per turn, when a creature succeeds on a saving throw against one of the owner's Sphere
                       talents, the owner may spend 3 CP: the creature rerolls and uses the new result.
"""
from __future__ import annotations

from typing import Any

from . import hook
from .d20_rewrite import Rule, register

BLOCK = "insight_rewrites"
KARMIC_DEBT = "insight.legacy-karmic-debt"
PERSISTENT = "insight.legacy-persistent-technique"
OUTCOMES = {
    KARMIC_DEBT: "Once per fight, when you fail a saving throw or a Cultivation Check, you may turn the failure into a "
                 "success; each use records a Karmic Debt owed to the being that granted this Insight",
    PERSISTENT: "Once per turn, when a creature succeeds on a saving throw against one of your Sphere talents, you may "
                "spend 3 CP to make it reroll that save and use the new result",
}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


def _save_or_cultivation_check(engine: Any, holder: Any, rc: Any) -> bool:
    """"a saving throw or Cultivation Check": a check counts only when its roll context says it is a Cultivation Check."""
    if rc.kind == "save":
        return True
    context = engine.d20_context(rc.roll) or {}
    return rc.kind == "check" and context.get("check_kind") == "cultivation"


def _karmic_say(engine: Any, holder: Any, rc: Any, roll: Any) -> str:
    what = "saving throw" if rc.kind == "save" else "Cultivation Check"
    return (f"Karmic Debt: {holder.actor.display_name} turns a failed {what} into a success and now owes one Karmic Debt to "
            f"the being that granted this Insight (the Game Master records the creditor and the service owed).")


register(Rule("opus1_karmic_debt", "Karmic Debt", feature=KARMIC_DEBT, rolls=("save", "check"), when="failed",
              op="choose", choose=lambda engine, holder, rc: rc.natural, outcome="success", limit="fight",
              checkpoint="D20_REROLL_SAVE", guard=_save_or_cultivation_check, say=_karmic_say))


def _own_sphere_talent(engine: Any, holder: Any, rc: Any) -> bool:
    """The save is against an action the holder owns that is a Sphere talent (a typed action carrying its sphere)."""
    action = (getattr(engine, "action_catalog", None) or {}).get(rc.source_id or "")
    if action is None or action.owner_id != holder.actor.entity_id:
        return False
    typed = (action.parameters or {}).get("typed") or {}
    return bool(typed.get("sphere"))


def _persistent_say(engine: Any, holder: Any, rc: Any, roll: Any) -> str:
    return (f"Persistent Technique: {holder.actor.display_name} spends 3 CP and {rc.roller.display_name} must reroll the "
            f"saving throw it had passed.")


register(Rule("opus1_persistent_technique", "Persistent Technique", feature=PERSISTENT, rolls=("save",), who="enemy",
              when="succeeded", op="reroll", costs=((("cp", 3),),), limit="turn", checkpoint="D20_REWRITE_ROLL",
              guard=_own_sphere_talent, say=_persistent_say))
