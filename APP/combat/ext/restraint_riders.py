"""Action escapes and grapple-qualified riders, without controller changes.

``action_restraint`` applies ordinary Restrained with an ``action_escape``
record carrying the printed ability and DC. Every affected character has an
Action to attempt each represented escape; candidate filtering keeps it off
the menu otherwise. A success removes only the chosen source's instance.
``unless_grappling_user`` runs its nested effects only when the subject is not
currently the user's grappler. These are opt-in effect types; old typings and
ordinary restraints are unaffected.
"""
from __future__ import annotations

from . import effect, hook
from ..ability_checks import ability_modifier

RESTRAINED = "condition:typed.restrained"
ESCAPE = "system:combat.source_restraint_escape"


def _held(actor):
    return [(key, condition) for key, condition in actor.conditions.items()
            if condition.condition_id == RESTRAINED and (condition.data or {}).get("action_escape")]


@hook("condition_state")
def action_escape_state(ctx, subject, row):
    """Opt-in escape metadata, preserving ordinary defenses and repeat saves."""
    escape = row.get("action_escape")
    if row.get("condition") != "restrained" or not isinstance(escape, dict):
        return None
    ability = str(escape.get("ability") or "STR").upper()
    name = str(escape.get("name") or "Source restraint")
    ability_name = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(ability, ability)
    return {"data": {"action_escape": {"ability": ability, "dc": int(ctx.numbers["save_dc"]), "name": name},
                     "label": f"{name}: Restrained; use an Action for a {ability_name} check to escape"}}


@effect("action_restraint")
def restrain(ctx, row):
    from .. import typed_executor

    for subject in typed_executor._default_subject(ctx, row, harmful=True):
        if not subject.active or typed_executor.condition_immune(ctx.engine, subject, "restrained"):
            continue
        ctx.engine._apply_condition(subject, RESTRAINED, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, row, subject, condition=True),
            data={"action_escape": {"ability": row["ability"], "dc": int(ctx.numbers["save_dc"])},
                  "label": "Restrained (Action: Strength check to escape)"})


@hook("match_start")
def escape_action(engine):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[ESCAPE] = ActionDefinition(source_definition_id=ESCAPE,
        display_name="Escape source restraint", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF", parameters={"typed": {
            "effects": [{"type": "escape_source_restraint"}], "numbers": {},
            "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0,
            "requires_condition": RESTRAINED, "source_restraint_escape": True})


@hook("additional_actions")
def affected_actions(engine, actor):
    # Old Factory bundles already contain the compiler-provided escape.
    if not _held(actor) or any((engine.action_catalog[a].parameters or {}).get("source_restraint_escape")
                              for a in actor.action_ids if a in engine.action_catalog):
        return []
    return [ESCAPE]


@hook("candidate_allowed")
def escape_allowed(engine, actor, candidate, action):
    if action is not None and (action.parameters or {}).get("source_restraint_escape"):
        return bool(_held(actor))
    return None


@effect("escape_source_restraint")
def escape(ctx, row):
    from .. import typed_executor
    from . import floored, run
    from .needle import ask, checkpoint_id

    held = _held(ctx.actor)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "restraint_escape", ctx.actor.entity_id), ctx.actor,
                 "choice:needle.restraint_escape", [key for key, _c in held],
                 labels={key: f"{c.data['action_escape'].get('name', 'Impaling Garden')} restraint from {ctx.engine.state.actors[c.source_actor_id].display_name}"
                         for key, c in held},
                 prompt=f"{ctx.action.display_name}: {ctx.actor.display_name} uses an Action to attempt a check against the selected restraint's save DC.")
    selected = next(((key, c) for key, c in held if key in chosen), None)
    if selected is None:
        return
    key, condition = selected
    rule = condition.data["action_escape"]
    ability = str(rule["ability"]).upper()
    dc = int(rule["dc"])
    modifier = ability_modifier(ctx.actor, ability, numbers=ctx.numbers) + sum(run("check_bonus", ctx, ctx.actor))
    roll = ctx.engine.roller.d20(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f"CHECK:{ctx.source}",
                                 mode=typed_executor.check_mode(ctx.actor, ability, engine=ctx.engine))
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, dc)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "ability": ability})
    if success:
        del ctx.actor.conditions[key]
        ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": key})


@effect("unless_grappling_user")
def unless_grappling(ctx, row):
    from .. import typed_executor

    if ctx.target is not None and any(c.condition_id == "condition:typed.grappled" and c.source_actor_id == ctx.target.entity_id
                                      for c in ctx.actor.conditions.values()):
        return
    typed_executor.run_effects(ctx, row.get("effects") or [])
