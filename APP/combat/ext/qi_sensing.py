"""Qi Sensing (Qi Cultivation CL1, lane A2R09 2026-10-13).

The passive half is already typed in combat/rules/senses.json ("qi_sensing":
perceive the presence of active supernatural energy within 30 feet). This
plug-in automates the printed Analyze Qi Action: choose one detected creature
within 30 feet and learn its broad category, whether its supernatural effects
are active, its Cultivation Level relative to your own, and one active
supernatural tag. A target concealed by a Qi concealment effect needs a
Cultivation Check against its save DC (8 + Proficiency Bonus + key ability
modifier when it lists none); a failure knows only that it is present, and
the same concealment cannot be retried until the scene ends.

The reveal is limited to what the engine itself tracks: the target's active
conditions (its active supernatural properties, with their names as the
supernatural tag) and the two Cultivation Levels' relation. Conditions use the
saved source action's provenance, whoever owns it; explicitly mundane sources
are excluded using the shared ``zone_sources.mundane_rows`` classification.
Free-floating
effects, items and energy residues stay GM text: the engine tracks creatures,
not unanchored residues. AI actors may analyze only creatures they perceive;
the action does not grant access to hidden creatures or their statistics.

Hooks used: ``compile_actions``, ``candidate_allowed`` (both documented in
combat/ext/__init__.py). The Cultivation Check itself is the shared
``cultivation_check_detail`` (combat/ext/ability_source.py).
"""

from __future__ import annotations

import json
from typing import Any

from . import effect, hook

ANALYZE_QI = "tianxia.path.qi_cultivation.feature.qi_sensing"
RANGE_FT = 30


def _owns(engine: Any, actor: Any) -> bool:
    return any(row.get("feature_id") == ANALYZE_QI
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("compile_actions")
def compile_analyze_qi(info: dict[str, Any]) -> list[Any] | None:
    """The Analyze Qi action for a Qi Sensing owner (hash-bound: replacing authority
    with old typing removes it)."""
    if ANALYZE_QI not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.analyze_qi",
        display_name="Analyze Qi", owner_id=info["actor_id"], economy=EconomyKind("ACTION"),
        resolution_kind="TYPED", target_kind="ANY_CREATURE", range_ft=RANGE_FT,
        parameters={"typed": {"effects": [{"type": "analyze_qi"}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "source": ANALYZE_QI},
                    "expected_damage": 0})]


@hook("candidate_allowed")
def analyze_qi_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Analyze Qi reads one detected creature: within 30 feet and perceived (the
    passive sense's own range; the AI may only use what its creature perceives)."""
    if not str(getattr(action, "source_definition_id", "")).endswith(".analyze_qi"):
        return None
    target = None
    for target_id in (getattr(candidate, "target_ids", None) or ()):
        target = engine.state.actors.get(target_id)
        if target is not None:
            break
    if target is None:
        return None  # no chosen creature yet: the execution-time effect decides
    if not target.active:
        return False
    if engine.grid.distance_ft(actor.position, target.position) > RANGE_FT:
        return False
    return not _failed_for_current_concealment(engine, actor, target)


@effect("analyze_qi")
def analyze_qi(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import stealth
    from ..unmaking import cultivation_level
    from ..zone_sources import mundane_rows
    from .ability_source import cultivation_check_detail, numbers_of

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    fingerprint = _concealment_fingerprint(target)
    for condition in list(actor.conditions.values()):
        if (condition.condition_id == "condition:typed.analyze_qi_failed"
                and condition.data.get("target") == target.entity_id
                and condition.data.get("concealment") != fingerprint):
            engine._remove_condition_instance(actor, condition.instance_id, ctx.source)
    numbers = numbers_of(engine, actor)
    if not numbers:
        numbers = {"pb": int(actor.proficiency_bonus), "key_mod": 0}
    concealed = _concealed(engine, actor, target)
    success = True
    if concealed:
        dc = _concealment_dc(engine, target)
        success = cultivation_check_detail(engine, actor, numbers, dc, ctx.source,
                                               "Cultivation Check (Analyze Qi)")[1]
    if not success:
        markers = _concealment_fingerprint(target)
        engine._apply_condition(actor, "condition:typed.analyze_qi_failed", ctx.source, actor.entity_id,
                                expires_on="UNTIL_REMOVED", data={"target": target.entity_id,
                                "concealment": markers, "label": "Analyze Qi failed against this concealment"})
        ctx.rider(f"Analyze Qi: {target.display_name} is present, but its Qi concealment holds -- "
                  "you know it is there and nothing more. You cannot retry against this concealment "
                  "until the scene ends.")
        return
    # An active buff or curse keeps its caster's action source, even on a
    # recipient who does not own that action. Untyped and explicitly mundane
    # sources stay out.
    supernatural_sources = set()
    for action in engine.action_catalog.values():
        typed = action.parameters.get("typed") or {}
        if typed and mundane_rows(typed.get("effects") or [], typed.get("mundane")) is not True:
            supernatural_sources.add(action.source_definition_id)
    conditions = sorted({str((c.data or {}).get("label") or (c.data or {}).get("name"))
                         for c in target.conditions.values()
                         if c.source_definition_id in supernatural_sources
                         and ((c.data or {}).get("label") or (c.data or {}).get("name"))})
    mine, theirs = cultivation_level(engine, actor), cultivation_level(engine, target)
    relation = "equal to yours" if theirs == mine else ("higher than yours" if theirs > mine else "lower than yours")
    tag = conditions[0] if conditions else "none"
    ctx.rider(f"Analyze Qi: {target.display_name} is a creature; its supernatural effects are active"
              f"{' (' + ', '.join(conditions) + ')' if conditions else ' (none active)'}; its Cultivation Level "
              f" is {relation}; one active supernatural tag: {tag}.")


@hook("ai_candidate_allowed")
def analyze_qi_ai_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """AI Analyze Qi may select itself or a creature it can locate through ordinary perception."""
    if not str(getattr(action, "source_definition_id", "")).endswith(".analyze_qi"):
        return None
    from .. import stealth
    targets = [engine.state.actors.get(target_id) for target_id in (getattr(candidate, "target_ids", None) or ())]
    return any(target is not None and target.active
               and (target.entity_id == actor.entity_id or stealth.sees(engine, actor, target))
               for target in targets)


def _concealment_fingerprint(target: Any) -> str:
    markers = sorted(str(c.condition_id) + ":" + str(c.source_definition_id) + ":" + str(c.instance_id)
                     + ":" + json.dumps(c.data or {}, sort_keys=True, separators=(",", ":"), default=str)
                     for c in target.conditions.values()
                     if any(part in str(c.condition_id).lower() for part in ("conceal", "hidden", "invisible", "obscured", "veil")))
    return "|".join(markers)


def _failed_for_current_concealment(engine: Any, actor: Any, target: Any) -> bool:
    fingerprint = _concealment_fingerprint(target)
    for condition in list(actor.conditions.values()):
        if condition.condition_id != "condition:typed.analyze_qi_failed" or condition.data.get("target") != target.entity_id:
            continue
        if condition.data.get("concealment") == fingerprint:
            return True
        # A changed concealment permits a fresh check. Keep this query pure:
        # the receipt remains historical state until replaced at execution.
    return False


def _concealed(engine: Any, actor: Any, target: Any) -> bool:
    """A Qi concealment effect hides the target: the shared perception rules already
    fail, or the target carries a concealment-style condition."""
    from .. import stealth

    # Shared sight deliberately excludes self-targets. That is not a Qi
    # concealment effect; explicit concealment conditions below still apply.
    if actor.entity_id != target.entity_id and not stealth.sees(engine, actor, target):
        return True
    return any(marker in str(c.condition_id).lower()
               for c in target.conditions.values()
               for marker in ("conceal", "hidden", "invisible", "obscured", "veil"))


def _concealment_dc(engine: Any, target: Any) -> int:
    """The concealment's save DC: the target's own Cultivation Save DC when it has
    one, else the printed 8 + Proficiency Bonus + key ability modifier."""
    # A concealment cast by another creature uses that source, not its recipient.
    for condition in target.conditions.values():
        if not any(part in str(condition.condition_id).lower()
                   for part in ("conceal", "hidden", "invisible", "obscured", "veil")):
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        if action is not None:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
            source = engine.state.actors.get(action.owner_id) or target
            return int(numbers.get("save_dc") or (8 + int(source.proficiency_bonus) + int(numbers.get("key_mod") or 0)))
    best = 0
    own_numbers = {}
    for action in engine.action_catalog.values():
        if action.owner_id == target.entity_id:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
            if numbers:
                own_numbers = numbers
            best = max(best, int(numbers.get("save_dc") or 0))
    if best:
        return best
    return 8 + int(target.proficiency_bonus) + int(own_numbers.get("key_mod") or 0)
