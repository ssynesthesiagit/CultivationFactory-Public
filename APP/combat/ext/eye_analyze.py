"""Hidden Eye talents that reach Analyzed without spending the Analyze action (lane 5, 2026-09-29).

Part-Breaker ("Trigger: You make a weapon attack or Unarmed Strike against a creature. Cost: Expend Martial Focus. Declare
Part-Breaker before making the attack roll. If the attack hits, resolve its normal damage and effects, then automatically
Analyze the target without making an ability check. Learn one Analyzable Characteristic; two on a Critical Hit"): a free
"Part-Breaker" declaration (costs the Martial Focus, offered to the player like Deadly Strike's toggle and never chosen by the
AI on its own) that stands until the end of the turn and is spent by the turn's next weapon attack or Unarmed Strike. A hit
then makes the target Analyzed by the attacker with no check (it was not a broad attack modifier: the authority scopes an
"any attack" modifier to the talent's own Sphere, and the Hidden Eye owns no attack). The "learn N Analyzable Characteristics"
half is GM information, handed over as a rider.

Rapid Analysis ("when you roll Initiative, you may immediately attempt to Analyze one creature you can see within Analyze
range without spending an Action or expending Martial Focus"): new bundles declare a pure fight-setup task.
Before the first turn the owner chooses a visible target (or declines), then an Analyze skill, in one saved
transaction. AI chooses a nearby eligible foe automatically. Reviewed lane 14 bundles count the check through
CHECK_ROLLED and use Far-Sight Analysis's range. Historical bundles retain their original first-turn hook;
loading a saved fight never creates or repeats an initiative task.

Hooks used: ``fight_setup_tasks``, ``fight_setup``, ``decision_text``, ``compile_actions``, ``candidate_allowed``,
``after_hit``, ``after_miss``, ``turn_start`` (all documented in
combat/ext/__init__.py). Ownership of Rapid Analysis at fight time is the "hidden_eye" passive row ``rapid_analysis``
(combat/rules/feature_blocks.d/auto_lane5.json).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .eye_common import has
from .mind_hidden_eye import analyze_against, analyzed_by, mark_analyzed

ANALYZE_RANGE_FT = 60
INITIATIVE_FLAG = "rapid_analysis_initiative_done"
RAPID = "TAL_THE_HIDDEN_EYE_RAPID_ANALYSIS"


def setup_owned(engine: Any, actor: Any) -> bool:
    """New bundles opt into setup; historical bundles keep their sealed turn hook."""
    return any(row.get("kind") == "rapid_analysis" and row.get("initiative_setup") == 1
               for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, []))


@hook("fight_setup_tasks")
def initiative_tasks(engine: Any) -> list[dict[str, str]] | None:
    return [{"actor_id": aid, "source_id": RAPID} for aid in engine.state.initiative_order
            if setup_owned(engine, engine.state.actors[aid])]


@hook("fight_setup")
def initiative_choice(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    if source_id != RAPID or not setup_owned(engine, actor):
        return None
    from .. import stealth
    from .riders14_eye import analyze_range, attempts_left
    from .needle import ask, CHOICE

    targets = [foe for foe in engine.state.actors.values()
               if foe.active and stealth.sees(engine, actor, foe)
               and engine.grid.distance_ft(actor.position, foe.position) <= analyze_range(engine, actor)
               and attempts_left(engine, actor, foe)]
    preferred = _initiative_target(engine, actor)
    selected = ask(engine, intent, f"RAPID_ANALYSIS:{actor.entity_id}", actor, CHOICE + "rapid_analysis_target",
        [foe.entity_id for foe in targets], labels={foe.entity_id: f"Analyze {foe.display_name}" for foe in targets},
        preferred=[preferred.entity_id] if preferred else [], allow_decline=True,
        automatic=preferred is not None, default='first' if preferred else 'decline',
        name="Rapid Analysis: choose a target", feature_id=RAPID,
        prompt=f"Rapid Analysis when {actor.display_name} rolls Initiative: choose one visible creature within "
               f"{analyze_range(engine, actor)} feet to Analyze, or pass. This costs no Action or Martial Focus; "
               "it uses one Analyze attempt against that creature.")
    if selected:
        target = engine.state.actors[selected[0]]
        engine._append_event("PASSIVE_TRIGGERED", RAPID, actor_id=actor.entity_id, target_ids=(target.entity_id,),
            payload={"trigger": f"Rapid Analysis: {actor.display_name} attempts to Analyze {target.display_name} "
                                "on rolling Initiative, without an Action or Martial Focus."})
        if analyze_against(engine, actor, target, RAPID):
            mark_analyzed(engine, actor, target, RAPID)
            engine._append_event("GM_RIDER", RAPID, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                payload={"rider": f"Rapid Analysis: {target.display_name} is Analyzed by {actor.display_name}; "
                                  "the GM supplies one learned characteristic."})
    return True


@hook("decision_text")
def initiative_description(engine: Any, context: dict[str, Any], printed_rules: Any) -> dict[str, Any] | None:
    if context.get("reaction_source_id") != "choice:needle.eye_approach":
        return None
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not any(task.actor_id == actor.entity_id and task.source_id == RAPID
                                for task in engine.state.setup_tasks):
        return None
    return {"name": "Rapid Analysis: choose a skill", "feature_id": RAPID,
            "summary": "Choose the skill for your free Initiative Analyze check against the selected creature's Analyze DC.",
            "cost": "No Action or Martial Focus; one Analyze attempt against the selected creature."}


PART_BREAKER = "TAL_THE_HIDDEN_EYE_PART_BREAKER"
DECLARED = "condition:typed.part_breaker_declared"
FOCUS = "resource:core.martial_focus"


def _declared(actor: Any) -> str | None:
    return next((iid for iid, condition in actor.conditions.items() if condition.condition_id == DECLARED), None)


@hook("compile_actions")
def part_breaker_declaration(info: dict[str, Any]) -> list[Any] | None:
    if PART_BREAKER not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.part_breaker", display_name="Part-Breaker",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
        parameters={"typed": {"effects": [{"type": "part_breaker_declare"}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": [], "source": PART_BREAKER},
                    "expected_damage": 0, "player_only": True})]


@hook("candidate_allowed")
def part_breaker_once(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if str(getattr(action, "source_definition_id", "")).endswith(".part_breaker") and _declared(actor) is not None:
        return False  # already declared for this turn's next attack
    return None


@effect("part_breaker_declare")
def part_breaker_declare(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, DECLARED, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Part-Breaker declared for the next weapon attack or Unarmed Strike"})
    ctx.rider("Part-Breaker: declared before the attack roll (Martial Focus expended); a hit Analyzes the target with no check.")


@hook("after_hit")
def part_breaker_hit(ctx: Any, target: Any, kind: str) -> None:
    """Part-Breaker's hit, after the attack's normal damage and effects: Analyze the target with no ability check."""
    engine, actor = ctx.engine, ctx.actor
    declared = _declared(actor)
    if kind not in ("weapon", "unarmed") or declared is None:
        return
    engine._remove_condition(actor, DECLARED, ctx.source)
    if not target.active:
        return
    critical = any(event.event_type == "DAMAGE_ROLLED" and event.actor_id == actor.entity_id and target.entity_id in (event.target_ids or ())
                   and bool((event.payload or {}).get("critical")) for event in engine.events[-12:])
    known = analyzed_by(target, actor.entity_id)
    mark_analyzed(engine, actor, target, ctx.source)
    ctx.rider(f"Part-Breaker: {target.display_name} is Analyzed by {actor.display_name} with no check"
              f"{' (it already was; the attempt still teaches)' if known else ''} (GM: learn "
              f"{'two Analyzable Characteristics, the hit being a Critical Hit' if critical else 'one Analyzable Characteristic'}).")


@hook("after_miss")
def part_breaker_miss(ctx: Any, target: Any) -> None:
    """A declared Part-Breaker is spent by the attack whether it hits or not."""
    if _declared(ctx.actor) is not None and (ctx.typed.get("weapon") is not None or ".natural." in ctx.source
                                              or any(e.get("attack_kind") == "unarmed" for e in ctx.typed.get("effects") or [])):
        ctx.engine._remove_condition(ctx.actor, DECLARED, ctx.source)


def _initiative_target(engine: Any, actor: Any) -> Any | None:
    from .. import stealth
    from .riders14_eye import analyze_range, attempts_left

    seen = [foe for foe in stealth.foes(engine, actor)
            if stealth.sees(engine, actor, foe) and engine.grid.distance_ft(actor.position, foe.position) <= analyze_range(engine, actor)
            and attempts_left(engine, actor, foe)]
    fresh = [foe for foe in seen if not analyzed_by(foe, actor.entity_id)]
    pool = fresh or seen
    return min(pool, key=lambda foe: (engine.grid.distance_ft(actor.position, foe.position), foe.entity_id)) if pool else None


@hook("turn_start")
def rapid_analysis_at_initiative(engine: Any, actor: Any) -> None:
    """Rapid Analysis's free Analyze, once, as the first turn of round 1 begins (see the module docstring)."""
    state = engine.state
    if state.round_number != 1 or not state.initiative_order or actor.entity_id != state.initiative_order[0]:
        return
    for entity_id in state.initiative_order:
        eye = state.actors.get(entity_id)
        if eye is None or not eye.active or setup_owned(engine, eye) or eye.turn_flags.get(INITIATIVE_FLAG) or not has(engine, entity_id, "rapid_analysis"):
            continue
        eye.turn_flags[INITIATIVE_FLAG] = True
        target = _initiative_target(engine, eye)
        if target is None:
            continue
        source = f"ext:{__name__}.rapid_analysis"
        engine._append_event("PASSIVE_TRIGGERED", source, actor_id=eye.entity_id, target_ids=(target.entity_id,),
                             payload={"trigger": f"Rapid Analysis: {eye.display_name} Analyzes {target.display_name} on rolling Initiative (no action, no Martial Focus)."})
        if analyze_against(engine, eye, target, source):
            mark_analyzed(engine, eye, target, source)
            engine._append_event("GM_RIDER", source, actor_id=eye.entity_id, target_ids=(target.entity_id,),
                                 payload={"rider": f"Rapid Analysis: {target.display_name} is Analyzed by {eye.display_name} (GM: pick one Analyzable Characteristic)."})
