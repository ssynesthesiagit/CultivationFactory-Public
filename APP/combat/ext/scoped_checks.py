"""Scoped ability-check modes and explicit escape choices (Iron-Bone first user).

``check_against`` self-effect: abilities, optional skills, against, mode, ordinary duration fields.
An omitted skills list retains the legacy all-skills behavior for that ability.
Only a compiled owned source grants it. ``typed_executor.check_mode(..., hazards=)``
reads the stored rule before a matching check, never a save or unrelated check.
The existing compile_actions/candidate_allowed hooks offer Strength (Athletics)
and Dexterity (Acrobatics) escape actions only while a matching owned buff is active.
Players select the skill on their turn through the ordinary action menu; AI chooses
an action normally. No reaction, extra resource cost or new expiry is introduced.

``escape_modes`` is the shared public helper used by typed_executor and trap.
Explicit choices read only their own ability/skill; legacy mixed-skill escapes retain
their prior unscoped modes and bonus rather than borrowing STR Advantage for DEX.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook

CONDITION = "condition:typed.check_against"


@effect("check_against")
def check_against(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    if not ctx.typed.get("source") or eff.get("applies_to") != "self":
        return
    ctx.engine._apply_condition(ctx.actor, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, eff, ctx.actor, condition=True),
        data={"rule": {"check_against": {"abilities": list(eff.get("abilities") or []),
              **({"skills": list(eff["skills"])} if eff.get("skills") else {}),
              "against": list(eff.get("against") or []), "mode": str(eff.get("mode") or "ADVANTAGE")}},
              "label": str(eff.get("evidence") or "Scoped check mode")})


def escape_skill_metadata(eff: dict[str, Any]) -> dict[str, Any]:
    """Receipt metadata for the skill modes actually consulted by an escape.

    Shared escape_checks and Trap use this with the same effect passed to
    escape_modes. An explicit skill is authoritative; an ability-only check
    is unskilled. Legacy mixed-skill checks consult both named skill modes for
    one draw with their precompiled better bonus, so mode_skills discloses both
    inputs without claiming a player selected either or changing that roll.
    """
    if eff.get("check_ability"):
        return {"skill": eff.get("check_skill") or None}
    return {"skill": None, "mode_skills": ["Athletics", "Acrobatics"]}


def escape_modes(actor: Any, eff: dict[str, Any], against: tuple[str, ...], *, engine: Any = None) -> set[str]:
    from ..typed_executor import check_modes

    if eff.get("check_ability"):
        return check_modes(actor, str(eff["check_ability"]), eff.get("check_skill"), hazards=against, engine=engine)
    return (check_modes(actor, "STR", "Athletics", engine=engine)
            | check_modes(actor, "DEX", "Acrobatics", engine=engine))


def _effects(value: Any):
    if isinstance(value, dict):
        if value.get("type") == "check_against":
            yield value
        for child in value.values():
            yield from _effects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _effects(child)


@hook("compile_actions")
def escape_choices(info: dict[str, Any]) -> list[Any] | None:
    # Inspect owned typed data; this also supports later abilities using the effect.
    sources = [key for key in sorted(info["owned_ids"])
               if any(set(row.get("against") or []).intersection(("grappled", "restrained"))
                      for row in _effects(info["mechanics"].get(key) or {}))]
    if not sources:
        return None
    from ..factory_compiler import _skill_bonus
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .trap import NETTED

    out = []
    for key, name, held, hazards in (
        ("escape_grapple", "Escape grapple", "condition:typed.grappled", ("grappled", "restrained")),
        ("trap_escape", "Escape the net", NETTED, ("restrained",)),
    ):
        for ability, skill, label in (("STR", "Athletics", "Strength"), ("DEX", "Acrobatics", "Dexterity")):
            bonus = _skill_bonus(info["owner_sheet"], skill, info["mods"].get(ability, 0))
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.scoped.{key}.{ability.lower()}",
                display_name=f"{name}: {label} ({skill})", owner_id=info["actor_id"],
                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
                parameters={"typed": {"effects": [{"type": key, "bonus": bonus,
                    "check_ability": ability, "check_skill": skill}], "numbers": info["numbers"],
                    "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 1,
                    "requires_condition": held, "scoped_check_sources": sources,
                    "scoped_check_hazards": list(hazards)}))
    return out


@hook("candidate_allowed")
def active_escape_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:  # movement/end-turn candidates have no ActionDefinition
        return None
    sources = (action.parameters or {}).get("scoped_check_sources")
    if not sources:
        return None
    hazards = set(action.parameters["scoped_check_hazards"])
    for state in actor.conditions.values():
        if state.condition_id != CONDITION or state.source_actor_id != actor.entity_id:
            continue
        source = engine.action_catalog.get(state.source_definition_id)
        owned = ((source.parameters or {}).get("typed") or {}).get("source") if source else None
        rule = ((state.data or {}).get("rule") or {}).get("check_against") or {}
        if owned in sources and hazards.intersection(rule.get("against") or []):
            return None
    return False
