"""Split the Chain against a cultivated restraint (Axes; rider lane C10, 2026-09-30).

Owner text (TAL_AXES_SPLIT_THE_CHAIN): "When a creature within your reach is Grappled, Restrained, bound by chains, vines, ropes,
nets, thread, wax, webbing, or a comparable physical restraint, you may use Hewing Strike against the restraint instead of the
creature. ... If the restraint is created by a cultivation effect, make an Axes Check against the effect's save DC. On a success,
suppress the restraint on that creature until the start of your next turn. On a success by 5 or more, end the restraint on that
creature if the effect is not Secret, Domain-scale, or artifact-backed."

How it runs
  * An owner with Hewing Strike gets "Hewing Strike: Split the Chain" (the Hewing Strike's own economy and reach), aimed at an ally
    within reach that is Grappled or Restrained by a cultivation effect: a condition whose source is another fighter's sphere
    technique (a typed action with a sphere; a plain Grapple is not one).
  * It makes the Axes Check (d20 + Proficiency Bonus + key ability modifier, the shared riders_shared ``sphere_check``) against
    that technique's save DC. Success: the restraint comes off until the start of your next turn (benefit_suppression.suppress,
    "owner_turn"; it returns then unless its own time ran out). Success by 5 or more: it ends on that creature for good. With two
    such restraints the player picks one.
Readings: against a cultivated restraint the Axes Check is the whole of the strike (no attack roll against the restraint); the
Secret / Domain-scale / artifact exception is not tagged on this table and stays with the GM. Hitting a physical restraint (rope,
net) with the axe needs restraint objects the table does not have.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SPLIT = "TAL_AXES_SPLIT_THE_CHAIN"
HEWING = "TAL_AXES_HEWING_STRIKE"
HOLDS = ("condition:typed.grappled", "condition:typed.restrained")
KEY = "axes_split_chain"
AXE_WORDS = ("axe", "hatchet", "francisca", "tomahawk")  # the names martial_axes.py and objects.py read as axes


def _cultivated(engine: Any, holder: Any) -> list[tuple[str, Any, int]]:
    """(instance id, condition, save DC) for each Grappled/Restrained on ``holder`` made by a sphere technique of someone else."""
    out = []
    for iid, condition in sorted(holder.conditions.items()):
        if condition.condition_id not in HOLDS or condition.source_actor_id == holder.entity_id:
            continue
        action = engine.action_catalog.get(str(condition.source_definition_id or "")) or \
            engine.action_catalog.get(str(condition.source_definition_id or "").split("#", 1)[0])
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        dc = (typed.get("numbers") or {}).get("save_dc")
        if typed.get("sphere") and not typed.get("weapon") and isinstance(dc, int):
            out.append((iid, condition, int(dc)))
    return out


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    if SPLIT not in (info.get("owned_ids") or []):
        return None
    hewing = next((row for row in sorted(info.get("actions") or [], key=lambda row: row.source_definition_id)
                   if ((row.parameters or {}).get("typed") or {}).get("source") == HEWING), None)  # any of its riders: same reach
    if hewing is None:
        return None
    typed = {"effects": [{"type": KEY, "evidence": "If the restraint is created by a cultivation effect, make an Axes Check against the "
                                                   "effect's save DC."}],
             "numbers": dict(((hewing.parameters or {}).get("typed") or {}).get("numbers") or info["numbers"]),
             "duration": {"kind": "instant"}, "riders": [], "source": f"{KEY}:{SPLIT}", "coverage": "FULL", "sphere": "tianxia.sphere.axes"}
    return [hewing.model_copy(update={
        "source_definition_id": f"action:typed.{info['short']}.{KEY}", "display_name": "Hewing Strike: Split the Chain",
        "target_kind": "ALLY_OR_SELF",
        "parameters": {"typed": typed, "expected_damage": 0, "player_only": True, KEY: True,
                       "description": ("Swing at the cultivated restraint holding an ally within your reach: an Axes Check against the "
                                       "technique's save DC. Success: the Grappled or Restrained comes off until the start of your next "
                                       "turn. Success by 5 or more: it ends.")}})]


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get(KEY):
        return None
    from .weapon_hits import available_weapons

    if not available_weapons(engine, actor, words=AXE_WORDS):
        return False  # "You must be wielding an axe weapon" (Hewing Strike): not while it is dropped or knocked away
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", ()) or ()]
    return None if targets and all(t is not None and t.entity_id != actor.entity_id and _cultivated(engine, t) for t in targets) else False


@effect("axes_split_chain")
def split(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .needle import CHOICE, ask, checkpoint_id

    engine, target = ctx.engine, ctx.target
    held = _cultivated(engine, target) if target is not None else []
    if not held:
        return
    iid, condition, dc = held[0]
    if len(held) > 1:
        labels = {key: f"{c.condition_id.rsplit('.', 1)[-1].title()} from {engine.state.actors[c.source_actor_id].display_name} (save DC {d})"
                  for key, c, d in held if c.source_actor_id in engine.state.actors}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "SPLIT_CHAIN", ctx.actor.entity_id, target.entity_id), ctx.actor,
                     CHOICE + KEY, list(labels), labels=labels, name="Split the Chain", feature_id=SPLIT,
                     prompt=f"Split the Chain: which restraint on {target.display_name} does {ctx.actor.display_name} swing at?")
        iid, condition, dc = next((h for h in held if h[0] in picked), held[0])
    run_effects(ctx, [{"type": "sphere_check", "name": "Axes Check", "dc": dc,
                       "on_success": [{"type": KEY + "_result", "instance": iid, "end": False}],
                       "on_success_by_5": [{"type": KEY + "_result", "instance": iid, "end": True}]}])


@effect("axes_split_chain_result")
def result(ctx: Any, row: dict[str, Any]) -> None:
    from .benefit_suppression import SUPPRESSED, suppress

    engine, target = ctx.engine, ctx.target
    iid = str(row.get("instance") or "")
    if not row.get("end"):
        if iid in target.conditions:
            name = target.conditions[iid].condition_id.rsplit(".", 1)[-1].title()
            suppress(engine, ctx.actor, target, f"condition:{iid}", "owner_turn", ctx.source,
                     label=f"{name} suppressed by Split the Chain until the start of {ctx.actor.display_name}'s next turn")
            ctx.rider(f"Split the Chain: {target.display_name}'s {name} is suppressed until the start of {ctx.actor.display_name}'s next turn.")
        return
    for key, kept in list(target.conditions.items()):
        model = ((kept.data or {}).get("model") or {}) if kept.condition_id == SUPPRESSED else {}
        if model.get("instance_id") == iid:
            del target.conditions[key]
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": SUPPRESSED, "instance_id": key, "reason": "ENDED"})
            ctx.rider(f"Split the Chain: success by 5 or more -- the restraint on {target.display_name} ends.")
