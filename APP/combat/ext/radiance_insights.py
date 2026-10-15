"""Radiance Insights riding the Radiance sphere's own healing talents (OPUS1 batch 9).

Dawn Physician
  * "When you use Gentle Dawn or Purifying Radiance on a willing creature, you may also grant Temporary HP equal to your
    Proficiency Bonus": after either talent resolves on a willing recipient (the owner or an ally; Burning Purification's
    attack is not a use on a willing creature), the owner is asked (automatic for AI fighters) and the recipient gains
    that many Temporary Hit Points through the ordinary ``temp_hp`` effect.
  * "Once per scene, when you use Purifying Radiance to end Poisoned, Charmed, or Frightened, you may use it as a Bonus
    Action instead of an Action": the compiler adds Bonus Action copies of the owner's own "End Poisoned" and "End Charm
    or Fear" Purifying Radiance actions, sharing one once-per-fight use counter (a fight is one scene); their costs and
    effects are the talent's own.

Rows are sealed into block ``radiance_insights`` (kind = Insight id); every hook returns at once without one.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "radiance_insights"
DAWN = "insight.dawn-physician"
GENTLE_DAWN = "tianxia.talent.radiance.gentle_dawn"
PURIFYING = "tianxia.talent.radiance.purifying_radiance"
SWIFT_LABELS = ("End Poisoned", "End Charm or Fear")
USES = "resource:uses." + DAWN
OUTCOMES = {
    DAWN: "When your Gentle Dawn or Purifying Radiance helps a willing creature, you may also give it Temporary Hit Points "
          "equal to your Proficiency Bonus; once per fight you may use Purifying Radiance as a Bonus Action to end "
          "Poisoned, Charmed or Frightened",
}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


@hook("compile_actions")
def swift_purification(info: dict[str, Any]) -> list[Any] | None:
    """Bonus Action copies of the owner's own Purifying Radiance cleanses, sharing the once-per-fight counter."""
    if DAWN not in (info.get("owned_ids") or []):
        return None
    from ..gate2_runtime_models import EconomyKind

    made = []
    for action in info.get("actions") or []:
        typed = (action.parameters or {}).get("typed") or {}
        economy = getattr(action.economy, "value", action.economy)
        if typed.get("source") != PURIFYING or economy != "ACTION" or not any(label in action.display_name for label in SWIFT_LABELS):
            continue
        made.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + "#dawn_physician",
            "display_name": f"{action.display_name} (Dawn Physician: Bonus Action, once per fight)",
            "economy": EconomyKind.BONUS_ACTION,
            "costs": (*tuple(action.costs), (USES, 1)),
        }, deep=True))
    return made or None


def _purifying_cleanse(ctx: Any) -> bool:
    return not any(isinstance(row, dict) and row.get("type") == "attack" for row in ctx.typed.get("effects") or [])


@hook("technique_used")
def dawn_temporary_hp(ctx: Any) -> None:
    source = ctx.typed.get("source")
    if source not in (GENTLE_DAWN, PURIFYING) or (source == PURIFYING and not _purifying_cleanse(ctx)):
        return
    engine, owner = ctx.engine, ctx.actor
    row = row_of(engine, owner.entity_id, BLOCK, DAWN)
    recipient = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if row is None or recipient is None or not recipient.active or recipient.team_id != owner.team_id:
        return
    from .needle import ask, checkpoint_id

    pb = int(row["pb"])
    picked = ask(engine, ctx.intent, checkpoint_id(engine, DAWN, recipient.entity_id), owner, "choice:needle.radiance_insights",
                 ["grant"], allow_decline=True, name="Dawn Physician", feature_id=DAWN, target_id=recipient.entity_id,
                 labels={"grant": f"Give {recipient.display_name} {pb} Temporary Hit Points"},
                 prompt=(f"Dawn Physician: your {ctx.action.display_name} helped {recipient.display_name}. Also give it "
                         f"Temporary Hit Points equal to your Proficiency Bonus ({pb})? No extra cost."))
    if not picked:
        return
    from ..typed_executor import run_effects

    child = ctx.on_hit_context(recipient, effect_source=DAWN)
    run_effects(child, [{"type": "temp_hp", "applies_to": "target", "flat": pb, "formula": "none",
                         "evidence": "Dawn Physician: Temporary HP equal to your Proficiency Bonus"}])
    note(engine, f"passive:{DAWN}", owner, f"Dawn Physician: {recipient.display_name} gains {pb} Temporary Hit Points.", (recipient,))
