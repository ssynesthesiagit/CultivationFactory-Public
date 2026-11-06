"""Shared source-restraint escape resolution and grapple-qualified riders, without controller changes.

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
_ABILITY_NAME = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
                 "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


def _held(actor):
    return [(key, condition) for key, condition in actor.conditions.items()
            if condition.condition_id == RESTRAINED and (condition.data or {}).get("action_escape")]


@hook("condition_state")
def action_escape_state(ctx, subject, row):
    """Opt-in escape metadata, preserving ordinary defenses and repeat saves."""
    escape = row.get("action_escape")
    if row.get("condition") != "restrained" or not isinstance(escape, dict):
        return None
    ability = str(escape.get("ability") or "str").lower()
    name = str(escape.get("name") or "Source restraint")
    ability_name = _ABILITY_NAME.get(ability.upper(), ability.upper())
    return {"data": {"action_escape": {"ability": ability, "dc": int(ctx.numbers["save_dc"]), "name": name},
                     "label": f"{name}: Restrained; use an Action for a {ability_name} check to escape"}}


@effect("action_restraint")
def restrain(ctx, row):
    from .. import typed_executor

    for subject in typed_executor._default_subject(ctx, row, harmful=True):
        if not subject.active or typed_executor.condition_immune(ctx.engine, subject, "restrained"):
            continue
        ability = str(row.get("ability") or "str").lower()  # compiled rows carry the lowercase ability
        ability_name = _ABILITY_NAME.get(ability.upper(), ability.upper())
        ctx.engine._apply_condition(subject, RESTRAINED, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, row, subject, condition=True),
            data={"action_escape": {"ability": ability, "dc": int(ctx.numbers["save_dc"])},
                  "label": f"Restrained (Action: {ability_name} ability check to escape)"})


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
    resolve_action_escape(ctx, key, condition)


def resolve_action_escape(ctx, key, condition):
    """Apply the source restraint's stored check and remove only that exact instance on success.

    Used by both its ordinary Action and Bonus Action features that change only the action economy.
    The source rule still owns ability, DC, check modes and success scope.
    """
    from .escape_checks import resolve_escape_check
    from .condition_ownership import remove_instance
    from .hold_escapes import escaped, how_for

    rule = (condition.data or {}).get("action_escape") or {}
    ability = str(rule.get("ability") or "STR").upper()
    dc = int(rule.get("dc") or 10)
    bonus = ability_modifier(ctx.actor, ability, numbers=ctx.numbers)
    name = str(rule.get("name") or "Source restraint")
    success = resolve_escape_check(ctx, {"bonus": bonus}, dc, [condition],
        (condition.condition_id.rsplit(".", 1)[-1],), check_ability=ability,
        check_name=f"{name}: {ability}")
    if success:
        remove_instance(ctx.engine, ctx.actor, key, ctx.source)
        escaped(ctx.engine, ctx.actor, [condition], how_for(ability, ctx.actor),
                by=ctx.actor, source=ctx.source, way="check")
    return success


@effect("unless_grappling_user")
def unless_grappling(ctx, row):
    from .. import typed_executor

    if ctx.target is not None and any(c.condition_id == "condition:typed.grappled" and c.source_actor_id == ctx.target.entity_id
                                      for c in ctx.actor.conditions.values()):
        return
    typed_executor.run_effects(ctx, row.get("effects") or [])
