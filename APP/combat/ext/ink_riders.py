"""Ink sphere riders (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed text: authority/typed_mechanics/rules_text.json. An Ink Mark is the typed mark "ink_mark"
(combat/typed_executor.py mark_condition_id); marks on objects, doorways and surfaces are not on this table. Every hook returns
early unless the creature owns the ability or holds a condition/mark one of these abilities put on it.

- Binding Script: "If the target already bears one of your Ink Marks, you may use Binding Script as a Bonus Action instead of an
  Action" -- a compiled Bonus Action copy offered only against a creature bearing your Ink Mark.
- Brushstroke Shield: "If the protected creature bears one of your Ink Marks, increase the reduction by your Proficiency Bonus"
  (its Proficiency Bonus row counts only then; reaction_amount).
- Soul-Staining Ink: failed save -> for 1 minute it "cannot benefit from being Invisible against you, and it cannot Hide from you
  while within 60 feet"; success -> "outlined until the start of your next turn and cannot benefit from being Invisible against
  you" (effect ``ink_stain``; masked_conditions).
- Revealing Script: "Invisible creatures bearing the Mark remain visible to you" (the benefit this table can run; masked_conditions).
- True Name Calligraphy: condition ``ink_true_name`` (cannot turn Invisible, cannot teleport, repeat Charisma save) and Disadvantage
  on its saves against your Ink talents (save hook).
- Black-Seal Edict: effect ``ink_edict`` -- the caster forbids teleporting or turning Invisible (asked), for the duration with a
  repeat Charisma save on a failure, until the start of the caster's next turn on a success; the target must bear your Ink Mark.
- Heaven-Sealing Writ: on a creature bearing your Ink Mark, a failed Charisma save suppresses its teleportation or invisibility
  (asked) for the duration (the same ``ink_edict`` choice, ``ink_edict_apply`` with "hold").
- Ink Step's "Space to Mark": the destination must be adjacent to a creature bearing your Ink Mark.
- Ink Domain: allies inside get +2 on checks to escape Grappled or Restrained (check_bonus on the escape Actions); enemies bearing
  your Ink Mark cannot benefit from Invisible inside it; once each turn, a free Press Mark (free_use on the Domain's state).
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .ability_source import mechanic_at, mechanic_of

BINDING, SHIELD = "tianxia.talent.ink.binding_script", "tianxia.talent.ink.brushstroke_shield"
WRIT, STEP = "tianxia.talent.ink.heaven_sealing_writ", "tianxia.talent.ink.ink_step"
REVEAL, STAIN, NAME, EDICT, DOMAIN = ("tianxia.talent.ink.revealing_script", "tianxia.talent.ink.soul_staining_ink",
                                      "tianxia.talent.ink.true_name_calligraphy", "tianxia.talent.ink.black_seal_edict", "tianxia.talent.ink.ink_domain")
STAINED, TRUE_NAME, INK = "condition:typed.ink_stain", "condition:typed.ink_true_name", "tianxia.sphere.ink"
INVISIBLE, HIDDEN = "condition:typed.invisible", "condition:typed.hidden"


def marked(actor: Any, owner_id: str) -> bool:
    """Whether ``actor`` bears an Ink Mark placed by ``owner_id``."""
    from ..typed_executor import bears_mark

    return bears_mark(actor, owner_id, "ink_mark")


# ------------------------------------------------------------------------------------------------ Binding Script, marked target
@hook("compile_actions")
def marked_binding(info: dict[str, Any]) -> list[Any] | None:
    if BINDING not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from ..decision_text import costs_text

    base = next((a for a in info["actions"] if mechanic_of(a) == BINDING and a.economy == EconomyKind.ACTION), None)
    if base is None:
        return None
    return [base.model_copy(update={"source_definition_id": f"{base.source_definition_id}#marked", "display_name": "Binding Script (marked target)",
                                    "economy": EconomyKind.BONUS_ACTION,
                                    "parameters": {**base.parameters, "ink_marked_only": True,
                                                   "description": "Bonus Action: bind one creature you can see within 60 feet that already bears your Ink Mark "
                                                   "(a sign you placed that anchors your Ink talents). It makes a Strength save; failure: Restrained; "
                                                   "success: Speed reduced by 10 feet. Either result lasts until the start of your next turn. "
                                                   f"Cost: {costs_text(base.costs) or 'no cultivation resources'}."}})]


@hook("candidate_allowed")
def marked_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    mechanic = mechanic_of(action) if action is not None else ""
    if mechanic == STEP and "Space to Mark" in str(getattr(action, "display_name", "")):
        aim = getattr(candidate, "destination", None)  # "to an unoccupied space adjacent to one of your visible Ink Marks within range"
        return None if aim is not None and any(other.active and marked(other, actor.entity_id)
                                                and engine.grid.distance_between_cell_sets_ft([(aim.x, aim.y)], engine._actor_cells(other)) <= 5
                                                for other in engine.state.actors.values()) else False
    if not (parameters.get("ink_marked_only") or mechanic in (EDICT, WRIT)):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    return None if targets and all(t is not None and marked(t, actor.entity_id) for t in targets) else False


# ------------------------------------------------------------------------------------------------ Brushstroke Shield
def _protected(engine: Any) -> Any:
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    target = engine.state.actors.get(str(packet.get("target") or ""))
    if target is not None:
        return target
    rolled = next((event for event in reversed(engine.events[-16:]) if event.event_type in ("DAMAGE_ROLLED", "ATTACK_ROLLED", "SAVE_ROLLED")), None)
    return engine.state.actors.get(next(iter(rolled.target_ids or ()), "")) if rolled is not None else None


@hook("reaction_amount")
def shield_mark_bonus(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any]) -> int | None:
    if row.get("feature_id") != SHIELD or not effect.get("if_protected_marked"):
        return None
    protected = _protected(engine)
    return None if protected is not None and marked(protected, actor.entity_id) else 0


# ------------------------------------------------------------------------------------------------ stains, reveals, True Name
@effect("ink_stain")
def stain(ctx: Any, row: dict[str, Any]) -> None:
    """{"mode": "stain" | "outline"} on the target, against the user (see the module docstring)."""
    target = ctx.target
    if target is None or not target.active:
        return
    stain_mode = str(row.get("mode") or "stain")
    from ..typed_executor import effect_expiry

    expires = "START_OF_SOURCE_NEXT_TURN" if stain_mode == "outline" else effect_expiry(ctx, row, target, condition=True) or "END_OF_HOLDER_NEXT_TURN"
    ctx.engine._apply_condition(target, STAINED, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"against": ctx.actor.entity_id, "mode": stain_mode,
                                      "label": (f"Soul-stained: cannot be Invisible to {ctx.actor.display_name} or Hide from it within 60 feet"
                                                if stain_mode == "stain" else f"Outlined: cannot be Invisible to {ctx.actor.display_name}")})


def _masks(engine: Any, who: Any, other: Any) -> set[str]:
    """The Invisible/Hidden rows of ``who`` that do not count against ``other``."""
    hide_too = False
    denied = False
    for condition in who.conditions.values():
        data = condition.data or {}
        if condition.condition_id == STAINED and data.get("against") == other.entity_id:
            denied = True
            hide_too = hide_too or (data.get("mode") == "stain" and engine._distance_actor_to_actor(who, other) <= 60)
        elif condition.condition_id.startswith("condition:typed.mark.ink_mark.") and condition.source_actor_id == other.entity_id \
                and mechanic_at(engine, condition.source_definition_id) == REVEAL:
            denied = True  # Revealing Script: "Invisible creatures bearing the Mark remain visible to you"
    if marked(who, other.entity_id) and _in_domain(engine, other, who) and who.team_id != other.team_id:
        denied = True  # Ink Domain: enemies bearing your Ink Mark cannot benefit from being Invisible inside it
    if not denied:
        return set()
    names = {INVISIBLE, HIDDEN} if hide_too else {INVISIBLE}
    return {key for key, c in who.conditions.items() if c.condition_id in names}


@hook("masked_conditions")
def ink_reveals(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out = {}
    for who, other in ((target, attacker), (attacker, target)):
        rows = _masks(engine, who, other)
        if rows:
            out[who.entity_id] = rows
    return out or None


@hook("save")
def true_name_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """True Name Calligraphy: "has Disadvantage on saving throws against your Ink talents"."""
    if not any(c.condition_id == TRUE_NAME and c.source_actor_id == ctx.actor.entity_id for c in subject.conditions.values()):
        return None
    action = ctx.engine.action_catalog.get(ctx.source)
    sphere = ((ctx.typed or {}).get("sphere") or (((action.parameters or {}).get("typed") or {}).get("sphere") if action is not None else None))
    return {"modes": ["DISADVANTAGE"]} if sphere == INK else None


# ------------------------------------------------------------------------------------------------ Black-Seal Edict
@effect("ink_edict")
def edict(ctx: Any, row: dict[str, Any]) -> None:
    """Chooses the forbidden act before the save (``ink_edict_apply`` rows in its save apply it)."""
    from .needle import CHOICE, ask, checkpoint_id

    target = ctx.target
    if target is None:
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ink_edict", ctx.actor.entity_id), ctx.actor, CHOICE + "ink_edict",
                 ["teleport", "invisible"], labels={"teleport": "Forbid it to teleport", "invisible": "Forbid it to turn Invisible"},
                 preferred=["teleport"], name="Black-Seal Edict",
                 prompt=f"Black-Seal Edict: choose the act {target.display_name} is forbidden (the other printed acts are the GM's).")
    ctx.damage_cache[("ink_edict", target.entity_id)] = chosen[0] if chosen else "teleport"


@effect("ink_edict_apply")
def edict_apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import block_condition

    target = ctx.target
    act = ctx.damage_cache.get(("ink_edict", target.entity_id)) if target is not None else None
    if not act:
        return
    name = "cannot_teleport" if act == "teleport" else "no_invisible"
    held = bool(row.get("repeat") or row.get("hold"))  # Heaven-Sealing Writ: "suppress for the duration" (no repeat save)
    block_condition(ctx, {"type": "condition", "condition": name, "applies_to": "target",
                          **({"repeat_save": {"ability": "CHA", "when": "end"}} if row.get("repeat") else {}),
                          **({"duration": "concentration"} if held else {"expires_on": "START_OF_SOURCE_NEXT_TURN"}),
                          "evidence": f"Black-Seal Edict: it cannot {'teleport' if act == 'teleport' else 'turn Invisible'}"})


# ------------------------------------------------------------------------------------------------ Ink Domain
def _in_domain(engine: Any, owner: Any, creature: Any) -> bool:
    from .. import zones

    return any(zone.owner_id == owner.entity_id and mechanic_at(engine, zone.source_definition_id) == DOMAIN
               and engine._footprint_intersects(creature, zone.affected_cells) for zone in zones.typed_zones(engine))


@hook("check_bonus")
def domain_escape(ctx: Any, actor: Any) -> int | None:
    """Ink Domain: allies "gain +2 to checks made to escape Grappled or Restrained" (an escape Action's own check)."""
    effects = (ctx.typed or {}).get("effects") or []
    parameters = (ctx.action.parameters or {}) if ctx.action is not None else {}
    escaping = bool(set(getattr(ctx, "escape_hazards", ())).intersection(("grappled", "restrained"))) or \
        parameters.get("sand_dig_free") or parameters.get("source_restraint_escape") or any(
        isinstance(row, dict) and row.get("type") in ("escape_grapple", "escape_source_restraint", "escape_binding", "sand_dig_free")
        for row in effects)
    if not escaping:
        return None
    for owner in ctx.engine.state.actors.values():
        if owner.entity_id != actor.entity_id and owner.team_id == actor.team_id and owner.active and _in_domain(ctx.engine, owner, actor):
            return 2
    return None
