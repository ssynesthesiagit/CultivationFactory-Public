"""Demon-Subduing Tag: one shared repeat save ends a prepared site seal.

The ordinary and pre-established site deliveries use the same printed save.
Site status is declared by choosing that action, rather than invented by AI:
the site action is player-only. No automatic trigger or site project is built.
"""
from copy import deepcopy
from typing import Any

from . import effect, hook, note
from .condition_ownership import remove_instance
from .talismans import TALENT

SOURCE = TALENT + "demon_subduing_tag"
HOLD = "condition:typed.demon_subduing_site"


@hook("compile_actions")
def site_action(info: dict) -> list | None:
    if SOURCE not in (info.get("owned_ids") or []):
        return None
    out = []
    for action in info.get("actions") or []:
        if not str(action.source_definition_id).endswith(SOURCE):
            continue
        typed = deepcopy(action.parameters.get("typed") or {})
        for row in typed.get("effects") or []:
            if row.get("type") != "save":
                continue
            for hold in row.get("on_fail") or []:
                if hold.get("type") == "talisman_demon_hold":
                    hold["site"] = True
                    for child in hold["effects"]:
                        child.pop("expires_on", None)
                        child["duration"] = "one_minute"
        out.append(action.model_copy(update={
            "source_definition_id": f"action:typed.{info['short']}.site.{SOURCE}",
            "display_name": "Demon-Subduing Tag (prepared site seal)",
            "parameters": {**action.parameters, "typed": typed, "player_only": True,
                           "description": "Activate one talisman already part of a prepared site seal. "
                                          "Uses your Action and one prepared talisman. A failed Charisma save "
                                          "restrains the creature and prevents teleporting and turning invisible "
                                          "for 1 minute; one repeat save at the end of each turn ends these effects. "
                                          "A successful save prevents Reactions until the start of your next turn. "
                                          "This action does not prepare a site."}}))
    return out


@effect("talisman_demon_hold")
def hold(ctx: Any, row: dict) -> None:
    from ..typed_executor import clock_expiry, run_effects

    before = {target.entity_id: set(target.conditions) for target in ctx.targets}
    effects = deepcopy(row.get("effects") or [])
    expiry = clock_expiry(ctx.engine, "minutes", 1) if row.get("site") else None
    if expiry:
        # The ordinary branch's evidence names the caster's next turn. An
        # explicit shared clock prevents that text overriding the site's minute.
        for child in effects:
            child["expires_on"] = expiry
    run_effects(ctx, effects)
    if not row.get("site"):
        return
    for target in ctx.targets:
        ids = sorted(set(target.conditions) - before[target.entity_id])
        if not ids:
            continue
        ctx.engine._apply_condition(target, HOLD, ctx.source, ctx.actor.entity_id,
                                    expires_on=expiry,
                                    data={"instances": "|".join(ids), "dc": int(ctx.numbers.get("save_dc") or 10),
                                          "label": "Demon-Subduing site seal: repeat a Charisma save at the end "
                                                   "of each turn to end its restraint and other restrictions"})


@hook("turn_end")
def repeat_site_save(engine: Any, actor: Any) -> None:
    for iid, row in list(actor.conditions.items()):
        if row.condition_id != HOLD:
            continue
        dc = int(row.data["dc"])
        instances = str(row.data["instances"]).split("|")
        # Use the native repeat-save contract: defensive reactions need both
        # the caster and the hazards imposed by this seal's retained instances.
        named = sorted({actor.conditions[instance].condition_id.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
                        for instance in instances if instance in actor.conditions})
        roll = engine._roll_save(actor, "CHA", dc, row.source_definition_id,
                                 roll_context={"source_actor_id": row.source_actor_id, "named": named})
        if roll is None or int(roll.total) < dc:
            continue
        for instance in instances:
            remove_instance(engine, actor, instance, row.source_definition_id)
        remove_instance(engine, actor, iid, row.source_definition_id)
        note(engine, row.source_definition_id, actor,
             f"Demon-Subduing Tag: {actor.display_name} succeeds on the end-of-turn Charisma save "
             f"({roll.total} against DC {dc}); the site seal's restraint and restrictions end.")
