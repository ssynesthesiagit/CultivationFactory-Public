"""Escape check resolver shared by grapples, bindings and granted escape options.

Callers supply the held instances and hazard scope, and retain their own removal
semantics. Modes, bonuses, evented roll, check floors and ally Auspice Release are
resolved once here. The sealed-to-current skill bonus also lives here:
escape_roll_bonus prepares the bonus of every rolled escape (grapples,
bindings, traps and the granted escape options), and escape_choice_bonus quotes
one sealed choice for the shared escape seam's choice labels and the Thread
Heaven-Net provider. No state or ability-specific policy is stored by this helper.
"""
from __future__ import annotations

from typing import Any


def resolve_escape_save(engine: Any, escaper: Any, ability: str, dc: int, source: str,
                        grips: list[Any]) -> bool:
    """Roll a hold's printed escape save, then notify its settled escape outcome once."""
    from . import run, run_strict

    modes = {mode for mode in run("escape_save_mode", engine, escaper, grips)
             if mode in ("ADVANTAGE", "DISADVANTAGE")}
    result = engine._roll_save(escaper, str(ability).upper(), int(dc), source,
                               extra_mode=next(iter(modes)) if len(modes) == 1 else None)
    success = result.total >= int(dc)
    run_strict("escape_roll_resolved", engine, escaper, grips, success, "save", source)
    return success


def escape_hook_modes(engine: Any, escaper: Any, grips: list[Any],
                      ability: str | None = None, skill: str | None = None) -> set[str]:
    """Pure query combining unscoped and ability-scoped hold escape benefits.

    Unknown legacy mixed-skill checks pass None; scoped providers must decline
    rather than lend one ability's benefit to another. Opposing modes cancel at
    the roll. This query is also used when ranking automatic escape choices.
    """
    from . import run

    return {mode for point, args in (
        ("escape_mode", (engine, escaper, grips)),
        ("escape_check_mode", (engine, escaper, grips, ability, skill)),
    ) for mode in run(point, *args) if mode in ("ADVANTAGE", "DISADVANTAGE")}


def sealed_escape_choices(ctx: Any, effect: dict[str, Any]) -> dict[str, Any]:
    """Own compiled physical skills, including runtime actions without a sheet."""
    choices = effect.get("escape_check_choices") or ctx.typed.get("escape_check_choices")
    if choices:
        return choices
    for action_id in ctx.actor.action_ids:
        action = ctx.engine.action_catalog.get(action_id)
        typed = ((action.parameters or {}).get("typed") or {}) if action else {}
        if typed.get("escape_check_choices"):
            return typed["escape_check_choices"]
    return {}


def escape_choice_bonus(ctx: Any, choice: dict[str, Any], *, skill: str) -> int:
    """One sealed choice's current own-skill total, for labels and AI preference.

    A choice is quoted, never rolled. The resolver adjusts the sealed bonus
    once, at resolution, so a quoted total never reaches a die twice.
    """
    from ..ability_checks import adjusted_skill_bonus

    return adjusted_skill_bonus(ctx.engine, ctx.actor, skill, int(choice["bonus"]))


def escape_check_bonus(ctx: Any, effect: dict[str, Any], *,
                       ability: str | None = None, skill: str | None = None) -> int:
    """Adjust a sealed skill total once; mixed checks recompare both skills.

    This is the only place that applies the sealed-to-current adjustment, and
    escape_roll_bonus is the only caller. Keep any escape-specific flat
    contribution above the compiled better skill. Missing skill provenance
    preserves the caller's total. Callers with an already-current bonus must not
    opt into this sealed-total helper.
    """
    from ..ability_checks import adjusted_skill_bonus

    bonus = int(effect.get("bonus", ctx.numbers.get("escape_bonus") or 0))
    ability = ability or effect.get("check_ability")
    skill = skill or effect.get("check_skill")
    if ability:
        return adjusted_skill_bonus(ctx.engine, ctx.actor, skill, bonus) if skill else bonus
    choices = sealed_escape_choices(ctx, effect)
    if not choices:
        return bonus
    compiled = [int(info["bonus"]) for info in choices.values()]
    current = [adjusted_skill_bonus(ctx.engine, ctx.actor, info["skill"], int(info["bonus"]))
               for info in choices.values()]
    return bonus + max(current) - max(compiled)


def escape_roll_bonus(ctx: Any, effect: dict[str, Any], *, ability: str | None = None,
                      skill: str | None = None, adjust: bool | None = None,
                      plain: int | None = None) -> int:
    """The bonus one escape roll uses; the one place the adjustment is applied.

    ``adjust`` says whether the sealed-to-current adjustment applies: a caller
    that already holds a current total passes False, and ``plain`` is that
    total. Every escape roll prepares its bonus here, so the adjustment is
    applied once per roll.
    """
    if adjust is None:
        adjust = bool(effect.get("sealed_skill_bonus"))
    if adjust:
        return escape_check_bonus(ctx, effect, ability=ability, skill=skill)
    if plain is not None:
        return int(plain)
    return int(effect.get("bonus", ctx.numbers.get("escape_bonus") or 0))


def resolve_escape_check(ctx: Any, effect: dict[str, Any], dc: int,
                         grips: list[Any], against: tuple[str, ...] = (), *, check_name: str = "",
                         target_id: str | None = None, source_id: str | None = None,
                         source_actor_id: str | None = None, check_ability: str | None = None,
                         check_skill: str | None = None, escape_hooks: bool = True) -> bool:
    """Resolve one check; ctx.actor rolls and callers remove their own holds.

    Explicit check_ability/check_skill keywords use that check's unresolved modes
    and hazard scope. Effect check_ability/check_skill fields are the fallback;
    checks without either retain legacy mixed-skill resolution.
    Optional metadata identifies a helped creature and the hold's origin; defaults
    preserve existing callers' roll scope and event payload exactly.
    Ordinary ability checks must set escape_hooks=False: benefits granted only
    for escaping a hold cannot contribute to those checks.
    Mixed physical escapes recompare their sealed skills. sealed_skill_bonus
    opts explicit compiled totals into adjustment; explicit callers that already
    calculated a current bonus omit it to avoid applying the adjustment twice.
    """
    from . import floored, run
    from .scoped_checks import escape_modes, escape_skill_metadata
    from ..typed_executor import check_modes
    from copy import copy

    # A provider can request an explicit skill choice only for a mixed-skill
    # physical escape. No answer preserves the historical bonus/mode/event.
    ability = check_ability or effect.get("check_ability")
    if escape_hooks and not ability and not effect.get("check_ability"):
        answer = choose_escape_check(ctx, effect, dc, grips, against)
        if answer:
            ability, check_skill = answer["ability"], answer["skill"]
            effect = {**effect, "bonus": answer["bonus"], "sealed_skill_bonus": True}
            against = tuple(answer.get("hazards", against))
    selected_skill = check_skill or effect.get("check_skill")
    skill = str(selected_skill or ability) if ability else "Athletics or Acrobatics"
    modes = (check_modes(ctx.actor, str(ability), selected_skill,
                         engine=ctx.engine, hazards=against) if ability else escape_modes(ctx.actor, effect, against, engine=ctx.engine))
    if escape_hooks:
        modes.update(escape_hook_modes(ctx.engine, ctx.actor, grips, ability, selected_skill))
    bonus_ctx = copy(ctx)
    bonus_ctx.escape_hazards = against
    bonus = escape_roll_bonus(ctx, effect, ability=ability, skill=selected_skill,
                              adjust=bool(effect.get("sealed_skill_bonus")) or (escape_hooks and not ability))
    modifier = bonus + sum(run("check_bonus", bonus_ctx, ctx.actor))
    target_id = ctx.actor.entity_id if target_id is None else target_id
    # The hold's originator is the pressure's source: an escape
    # check names that grip's originator in its roll context, so
    # roll hooks (foundation guards, surges) see who the escape
    # opposes. A caller that already names the source keeps it.
    originator = source_actor_id
    if originator is None:
        for grip in (grips or []):
            grip_actor = getattr(grip, "source_actor_id", None)
            if grip_actor and grip_actor != ctx.actor.entity_id:
                originator = grip_actor
                break
    with ctx.engine.d20_scope({"kind": "check", "actor_id": ctx.actor.entity_id,
                               "target_id": target_id, "source_id": ctx.source if source_id is None else source_id,
                               "source_actor_id": originator if originator is not None else ctx.actor.entity_id,
                               **({'ability': str(ability).upper()} if ability else {}),
                               "skill": skill, "dc": dc, "named": list(against), "reason": f"CHECK:{ctx.source}"}):
        roll = ctx.engine.roller.d20(modifier=modifier, actor_id=ctx.actor.entity_id,
                                     reason=f"CHECK:{ctx.source}", mode=modes.pop() if len(modes) == 1 else "NORMAL")
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, dc)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
                             target_ids=(target_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                      **({"ability": ability, "skill": selected_skill} if ability else escape_skill_metadata(effect)),
                                      **({"check": check_name} if check_name else {})})
    if escape_hooks:
        from . import run_strict
        run_strict("escape_roll_resolved", ctx.engine, ctx.actor, grips, success, "check", ctx.source)
    return success


from . import hook


@hook("compile_action")
def seal_escape_choices(action, info):
    """Record both physical escape skill bonuses; never read a live sheet."""
    from copy import deepcopy
    from ..factory_compiler import _skill_bonus
    parameters = deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    effects = [row for row in typed.get("effects", [])
               if row.get("type") in {"escape_grapple", "escape_binding", "trap_escape"}]
    if not effects:
        return action
    for row in effects:
        row["sealed_skill_bonus"] = True
    typed["escape_check_choices"] = {
        ability: {"skill": skill, "bonus": _skill_bonus(info["owner_sheet"], skill, info["mods"].get(ability, 0))}
        for ability, skill in (("STR", "Athletics"), ("DEX", "Acrobatics"))}
    parameters["typed"] = typed
    return action.model_copy(update={"parameters": parameters})


def choose_escape_check(ctx, effect, dc, grips, hazards):
    """Ask opt-in providers; default None leaves a caller's legacy roll intact."""
    from . import run_strict
    sealed = {**effect, "escape_check_choices": sealed_escape_choices(ctx, effect)}
    answers = [answer for answer in run_strict("escape_check_choice", ctx, sealed, dc, grips, hazards)
               if answer is not None]
    if len(answers) > 1:
        raise ValueError("Conflicting escape check choices")
    if answers:
        return answers[0]
    # Existing specialized choices (Thread bindings) keep their own transport.
    # Other owned benefits may request this shared physical-skill choice.
    requests = list(run_strict('escape_check_choice_required', ctx, sealed, dc, grips, hazards))
    choices = sealed.get('escape_check_choices') or {}
    if not requests or not grips or not choices:
        return None
    from . import ai_controlled
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import check_modes
    options = list(choices)
    if not options:
        return None
    labels, scores = {}, {}
    for ability in options:
        info = choices[ability]
        skill = info['skill']
        modes = check_modes(ctx.actor, ability, skill, engine=ctx.engine, hazards=tuple(hazards))
        modes.update(escape_hook_modes(ctx.engine, ctx.actor, grips, ability, skill))
        mode = next(iter(modes)) if len(modes) == 1 else 'NORMAL'
        bonus = escape_choice_bonus(ctx, info, skill=skill)
        scores[ability] = bonus + (5 if mode == 'ADVANTAGE' else -5 if mode == 'DISADVANTAGE' else 0)
        ability_name = {'STR': 'Strength', 'DEX': 'Dexterity', 'CON': 'Constitution',
                        'INT': 'Intelligence', 'WIS': 'Wisdom', 'CHA': 'Charisma'}.get(ability, ability)
        labels[ability] = f'{ability_name} ({skill}), {bonus:+d}' + (
            ', with Advantage' if mode == 'ADVANTAGE' else ', with Disadvantage' if mode == 'DISADVANTAGE' else '')
    names = ', '.join(dict.fromkeys(request['name'] for request in requests))
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'physical_escape_skill', ctx.actor.entity_id, ctx.source),
                 ctx.actor, CHOICE + 'physical_escape_skill', options, labels=labels,
                 preferred=sorted(options, key=lambda a: -scores[a]), minimum=1, maximum=1,
                 allow_decline=False, automatic=ai_controlled(ctx.engine, ctx.actor),
                 name=names, feature_id=requests[0]['feature_id'], target_id=ctx.actor.entity_id,
                 prompt=f'{names}: {ctx.actor.display_name} uses {ctx.action.display_name} to try to break free. '
                        'Choose the escape’s ability and skill. '
                        'This uses the escape action’s existing cost; choosing a skill costs nothing extra.')
    ability = picked[0]
    # The answer carries the sealed (compiled) bonus; the resolver adjusts it once.
    return {'ability': ability, 'skill': choices[ability]['skill'], 'bonus': int(choices[ability]['bonus']),
            'hazards': list(hazards)}
