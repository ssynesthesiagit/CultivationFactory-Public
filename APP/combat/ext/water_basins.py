"""Water's Cleansing Basin (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed (Sphere Compendium, Water, Shape Current): "Cleansing Basin. The first time each round you or an ally
enters the area or starts its turn there, it may end the Soaked state on itself, extinguish ordinary flames on itself, or gain Advantage
on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination."

``water_cleansing`` is the Basin's enter/start trigger (once per creature per round: the zone trigger's ``per_round``); the creature
itself chooses (its player is asked; the built-in AI ends Burning first, then Soaked, else takes the Advantage): end every Soaked mark on
it, end its Burning (the table's ordinary flames), or Advantage on its next save against Poisoned or a disease until the start of its
next turn. Shape Current's other forms are typed zone rows (authority/typed_mechanics/reviewed_final.d/elements.json); moving a Basin
is combat/ext/zone_mover.py. The compile_action hook also replaces Flowing
Current's ordinary initial push in newly compiled Wave Burst variants; their
reviewed effect uses the shared chosen-area recipient selector. Saved catalogs
are unchanged. Cleansing is inert outside a Cleansing Basin.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

SOAKED_PREFIX = "condition:typed.mark.soaked."
BURNING = "condition:typed.burning"


@hook("compile_action")
def wave_burst_replaces_current_save(action: Any, info: dict[str, Any]) -> Any:
    """The burst replaces the current's initial one-creature push, not two pushes."""
    typed = (action.parameters or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != "TAL_WATER_WAVE_BURST":
        return None
    effects = [e for e in typed.get("effects") or []
               if not (e.get("type") == "save" and e.get("cast_only") and not e.get("source_modifier"))]
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})


@effect("water_cleansing")
def cleansing(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .condition_ownership import remove_instance
    from .rider_choices import pick

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active or creature.team_id != owner.team_id:
        return
    soaked = [iid for iid, row in creature.conditions.items() if row.condition_id.startswith(SOAKED_PREFIX)]
    burning = [iid for iid, row in creature.conditions.items() if row.condition_id == BURNING]
    labels = {"save": "Advantage on its next saving throw against Poisoned or a disease before the start of its next turn"}
    if soaked:
        labels = {"soaked": "End the Soaked state on itself", **labels}
    if burning:
        labels = {"flames": "Put out the flames on itself (end Burning)", **labels}
    options = list(labels)
    chosen = pick(engine, creature, "water_cleansing", "Cleansing Basin", options, subject=creature, labels=labels, preferred=[options[0]],
                  trigger=f"{creature.display_name} is in your Cleansing Basin")
    if not chosen:
        return
    if chosen[0] == "flames":
        for iid in burning:
            remove_instance(engine, creature, iid, ctx.source)
    elif chosen[0] == "soaked":
        for iid in soaked:
            remove_instance(engine, creature, iid, ctx.source)
    else:
        run_effects(ctx, [{"type": "advantage", "applies_to": "target", "on": "the next saving throw against Poisoned or a disease",
                           "duration": "until_start_of_next_turn",
                           "evidence": "gain Advantage on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination"}])
    note(engine, ctx.source, owner, f"Cleansing Basin: {creature.display_name} -- {labels[chosen[0]].lower()}.", (creature,))
