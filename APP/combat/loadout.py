"""Which augments the next use of an ability carries (owner 2026-09-27: "Can more than one augment apply to a single use
(e.g. Greater + Persistent Darkness together, paying both)?" -- "Yes, any number").

Every combination of an ability's augments is compiled once (combat/factory_compiler.py _augment_combinations). A
fighter's choice is a condition that stays until changed (a free toggle per augment); a fight then offers only the
chosen combination, so choosing among many augments does not multiply the squares an area ability can be aimed at. A
fighter that has not chosen -- the AI, or a player who never opens the panel -- is offered the ability and each single
augment, as before.
"""

from __future__ import annotations

from typing import Any

AUGMENTS = "condition:typed.augments"


def families(engine: Any) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """{owner id: [(ability id, its augment loadout)]}, read once from the action catalog."""
    cached = engine.__dict__.get("_augment_families")
    if cached is None:
        cached = {}
        for action in engine.action_catalog.values():
            loadout = (action.parameters or {}).get("augment_loadout")
            if loadout:
                cached.setdefault(action.owner_id, []).append((action.source_definition_id, loadout))
        engine.__dict__["_augment_families"] = cached
    return cached


def chosen(actor: Any, family: str) -> list[str] | None:
    for condition in actor.conditions.values():
        if condition.condition_id == AUGMENTS and (condition.data or {}).get("family") == family:
            return list((condition.data or {}).get("augments") or [])
    return None


def active_action(family: str, loadout: dict[str, Any], picked: list[str] | None) -> str | None:
    """The action a use of the ability runs with the chosen augments (None: not chosen)."""
    if picked is None:
        return None
    return loadout["combos"].get("|".join(sorted(picked)), family) if picked else family


def hidden(engine: Any, actor: Any) -> set[str]:
    """The augmented versions of its abilities it is not offered now."""
    out: set[str] = set()
    for family, loadout in families(engine).get(actor.entity_id, []):
        combos = loadout.get("combos") or {}
        every = {family, *combos.values()}
        picked = chosen(actor, family)
        if picked is None:
            allowed = {family, *(combos[row["key"]] for row in loadout.get("augments") or [] if row["key"] in combos)}
        else:
            allowed = {active_action(family, loadout, picked)}
        out |= every - allowed
    # General targeting variants share their original action's availability.
    # They cannot bypass a chosen augment loadout or create duplicate families.
    out |= {action.source_definition_id for action in engine.action_catalog.values()
            if (action.parameters or {}).get('targeting_variant_of') in out}
    return out


def toggle(engine: Any, actor: Any, family: str, augment: str | None, source: str) -> None:
    """Turn one augment on or off for the ability's next uses (None clears them all)."""
    loadout = next((row for fam, row in families(engine).get(actor.entity_id, []) if fam == family), None)
    if loadout is None:
        return
    picked = chosen(actor, family) or []
    if augment is None:
        picked = []
    elif augment in picked:
        picked = [key for key in picked if key != augment]
    else:
        picked = [*picked, augment]
    names = {row["key"]: row["name"] for row in loadout.get("augments") or []}
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == AUGMENTS and (condition.data or {}).get("family") == family:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    family_name = getattr(engine.action_catalog.get(family), "display_name", family)
    engine._apply_condition(actor, AUGMENTS, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"family": family, "family_name": family_name, "augments": picked,
                                  "label": " + ".join(names.get(key, key) for key in picked) or "no augments"})
