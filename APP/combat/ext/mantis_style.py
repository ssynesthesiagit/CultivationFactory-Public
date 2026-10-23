"""Mantis Style Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Mantis Style (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "mantis", "role": "hooks" | "pincer"}``; Joint Lock runs ``joint_lock``; Eye of the Mantis runs
``eye_of_the_mantis``; Death of a Thousand Cuts is a paid unarmed-hit rider (path_riders ``paid_hit``).

Mantis Hooks     unarmed strikes may deal Piercing (path_riders unarmed_types add). Once per turn after an unarmed hit, a free
                 Grapple attempt (asked): the target's Strength or Dexterity save against your Cultivation Save DC, Grappled
                 on a failure. When that strike's damage is about to land, you may instead deal only your ability modifier
                 (asked; the table has already rolled the dice, which are then ignored) -- the Grapple save then has Disadvantage.
Joint Lock       (Bonus Action, 1 Stamina, a creature you Grapple) Dexterity save: failure, Restrained until the start of your
                 next turn or until that Grapple ends; success, no Reactions until the start of your next turn.
Rapid Pincer     an "(Rapid Pincer)" variant of your Unarmed Strike with one more strike, once per turn.
Eye of the Mantis  (Bonus Action, 60 ft, 3 Stamina, 1 minute) the log lists the target's Hit Points, Armor Class, Resistances,
                 Immunities, Concentration, conditions and lowest physical save; while it lasts, your first attack roll against
                 it each turn has Advantage, its saves against your Grapples have Disadvantage, and its first save against
                 Joint Lock during each of your turns has Disadvantage.
Every hook returns early for a creature without these rows or the Eye.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.mantis_style.feature."
EYE = "condition:typed.eye_of_the_mantis"
LOCK = "condition:typed.joint_lock"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "mantis"}


def _row(engine: Any, actor: Any) -> dict[str, Any]:
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if r.get("block") == "path_rider" and r.get("kind") == "mantis"), {})


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _grip(target: Any, owner: Any) -> Any:
    return next((c for c in target.conditions.values() if c.condition_id.endswith(".grappled") and c.source_actor_id == owner.entity_id), None)


def _eye(target: Any, owner: Any) -> Any:
    return next((c for c in target.conditions.values() if c.condition_id == EYE and c.source_actor_id == owner.entity_id), None)


# ------------------------------------------------------------------------------------------------ Mantis Hooks
@hook("damage_pending")
def hooks_light_blow(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    actor = engine.state.actors.get(str(source_actor_id or ""))
    if actor is None or packet.get("actor") != actor.entity_id or packet.get("target") != target.entity_id or packet.get("kind") != "unarmed":
        return None
    if packet.get("source") != source_definition_id or "hooks" not in _roles(engine, actor) or target.team_id == actor.team_id:
        return None
    if actor.turn_flags.get("_round_mantis_hooks") == _stamp(engine) or engine.__dict__.get("_mantis_light") == (actor.entity_id, target.entity_id):
        return None
    action = engine.action_catalog.get(source_definition_id)
    modifier = max(0, int((((action.parameters or {}).get("typed") or {}).get("weapon") or {}).get("ability_modifier") or 0)) if action else 0
    from .needle import ask, checkpoint_id

    picked = ask(engine, _intent(engine), checkpoint_id(engine, "mantis_light", target.entity_id), actor, "choice:needle.mantis_hooks_light", ["light"],
                 labels={"light": f"Deal only {modifier} damage; the Grapple save has Disadvantage"}, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Mantis Hooks", prompt=f"Mantis Hooks: your unarmed strike hit {target.display_name}.")
    if not picked:
        return None
    engine.__dict__["_mantis_light"] = (actor.entity_id, target.entity_id)
    return min(pending, modifier)


@hook("after_hit")
def mantis_hooks(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    light = engine.__dict__.get("_mantis_light") == (actor.entity_id, getattr(target, "entity_id", None))
    engine.__dict__["_mantis_light"] = None
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id or "hooks" not in _roles(engine, actor):
        return
    if actor.turn_flags.get("_round_mantis_hooks") == _stamp(engine) or _grip(target, actor) is not None:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "mantis_hooks", target.entity_id), actor, "choice:needle.mantis_hooks", ["grapple"],
                 labels={"grapple": f"Grapple {target.display_name} (its Strength or Dexterity save)"}, allow_decline=True, target_id=target.entity_id,
                 name="Mantis Hooks", prompt=f"Mantis Hooks: {ctx.action.display_name} hit {target.display_name}. Attempt a Grapple?")
    if not picked:
        return
    actor.turn_flags["_round_mantis_hooks"] = _stamp(engine)
    from .. import typed_executor as te

    dc = int(_row(engine, actor).get("save_dc") or (ctx.typed.get("numbers") or {}).get("save_dc") or 10)
    save = {"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1, "evidence": "Mantis Hooks: Strength or Dexterity save (the target's choice)",
            "on_fail": [{"type": "condition", "condition": "grappled", "applies_to": "target", "until_escape": True}]}
    engine.__dict__["_mantis_hooked"] = target.entity_id if light else None
    try:
        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'effects': [save], 'numbers': {**(ctx.typed.get('numbers') or {}), 'save_dc': dc}}, damage_cache={}), [save])
    finally:
        engine.__dict__["_mantis_hooked"] = None


def _grapple_save(ctx: Any) -> bool:
    return any(isinstance(row, dict) and row.get("type") == "save" and row.get("max_size_larger") is not None
               and any(isinstance(f, dict) and f.get("condition") == "grappled" for f in row.get("on_fail") or []) for row in ctx.typed.get("effects") or [])


@hook("save")
def mantis_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or ctx.actor is subject:
        return None
    engine, owner = ctx.engine, ctx.actor
    modes = []
    if engine.__dict__.get("_mantis_hooked") == subject.entity_id:
        modes.append("DISADVANTAGE")  # the light blow
    eye = _eye(subject, owner)
    if eye is not None and _grapple_save(ctx):
        modes.append("DISADVANTAGE")  # Eye of the Mantis: Advantage on your attempts to Grapple it
    if eye is not None and ctx.source.endswith(PREFIX + "joint_lock") and eye.data.get("lock_turn") != _stamp(engine) \
            and engine.state.current_actor_id == owner.entity_id:
        eye.data["lock_turn"] = _stamp(engine)
        modes.append("DISADVANTAGE")  # its first save against Joint Lock during each of your turns
    return {"bonus": 0, "modes": modes} if modes else None


# ------------------------------------------------------------------------------------------------- Joint Lock
@hook("candidate_allowed")
def lock_needs_your_grapple(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    if not any(isinstance(e, dict) and e.get("type") == "joint_lock" for e in typed.get("effects") or []):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    return None if targets and all(t is not None and _grip(t, actor) is not None for t in targets) else False


@effect("joint_lock")
def joint_lock(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    grip = _grip(target, ctx.actor) if target is not None else None
    if grip is None:
        return
    te.run_effects(ctx, [{"type": "save", "ability": "dex", "evidence": "Joint Lock: Dexterity saving throw",
                          "on_fail": [{"type": "joint_lock_hold", "grip": grip.instance_id}],
                          "on_success": [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}])


@effect("joint_lock_hold")
def joint_lock_hold(ctx: Any, row: dict[str, Any]) -> None:
    """Restrained until the start of your next turn or until that Grapple ends (never longer: a new one replaces it)."""
    target = ctx.target
    if target is None or not target.active or row.get("grip") not in target.conditions:
        return
    from ..typed_executor import condition_immune
    if condition_immune(ctx.engine, target, "restrained") or condition_immune(ctx.engine, target, "joint_lock"):
        return
    for iid, held in list(target.conditions.items()):
        if held.condition_id == "condition:typed.restrained" and (held.data or {}).get("joint_lock_grip") and held.source_actor_id == ctx.actor.entity_id:
            del target.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REFRESHED"})
    ctx.engine._apply_condition(target, "condition:typed.restrained", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"joint_lock_grip": row["grip"], "label": "Joint Lock: Restrained while the Grapple lasts"})


@hook("event")
def lock_ends_with_the_grapple(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED":
        return
    ended = (kwargs.get("payload") or {}).get("instance_id")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        for iid, held in list((target.conditions if target is not None else {}).items()):
            if (held.data or {}).get("joint_lock_grip") == ended:
                del target.conditions[iid]
                engine._append_event("CONDITION_REMOVED", PREFIX + "joint_lock", actor_id=held.source_actor_id, target_ids=(target_id,),
                                     payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "GRAPPLE_ENDED"})


# ----------------------------------------------------------------------------------------------- Rapid Pincer
@hook("compile_actions")
def rapid_pincer(info: dict[str, Any]) -> list[Any] | None:
    mechanic = info["mechanics"].get(PREFIX + "rapid_pincer") or {}
    if PREFIX + "rapid_pincer" not in info["owned_ids"] or not any(isinstance(e, dict) and e.get("kind") == "mantis" and e.get("role") == "pincer"
                                                                  for e in mechanic.get("effects") or []):
        return None
    import copy

    from ..gate2_runtime_models import EconomyKind

    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        if base.economy != EconomyKind.ACTION or ".natural." not in base.source_definition_id or "#" in base.source_definition_id \
                or (base.parameters or {}).get("player_only") or not typed.get("weapon"):
            continue
        variant = copy.deepcopy(typed)
        for eff in variant.get("effects") or []:
            if isinstance(eff, dict) and eff.get("type") == "attack":
                eff["count"] = int(eff.get("count") or 1) + 1
                break
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#rapid_pincer",
                                           "display_name": base.display_name + " (Rapid Pincer)",
                                           "parameters": {**base.parameters, "rapid_pincer": True, "typed": variant,
                                                          "expected_damage": int(base.parameters.get("expected_damage") or 0) * 2}}))
    return out or None


@hook("candidate_allowed")
def pincer_once_per_turn(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("rapid_pincer"):
        return None
    return False if actor.turn_flags.get("_round_rapid_pincer") == _stamp(engine) else None


@hook("action_completed")
def pincer_used(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if str(source_definition_id).endswith("#rapid_pincer"):
        actor.turn_flags["_round_rapid_pincer"] = _stamp(engine)


# --------------------------------------------------------------------------------------------- Eye of the Mantis
@effect("eye_of_the_mantis")
def eye_of_the_mantis(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .. import typed_reactions

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    for iid, held in list(target.conditions.items()):
        if held.condition_id == EYE and held.source_actor_id == owner.entity_id:
            engine._remove_condition_instance(target, iid, PREFIX + "eye_of_the_mantis", expected=held)
    expires = te.clock_expiry(engine, "minutes", 1) or "UNTIL_REMOVED"
    engine._apply_condition(target, EYE, PREFIX + "eye_of_the_mantis", owner.entity_id, expires_on=expires,
                            data={"label": f"Eye of the Mantis ({owner.display_name})"})
    resist = sorted(k for k in ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC", "RADIANT", "SLASHING", "THUNDER")
                    if typed_reactions.damage_factor(engine, target, k, None, owner.entity_id) == 0.5)
    immune = sorted(k for k in ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC", "RADIANT", "SLASHING", "THUNDER")
                    if typed_reactions.damage_factor(engine, target, k, None, owner.entity_id) == 0.0)
    saves = {ab: int((target.saving_throws or {}).get(ab, 0) or 0) for ab in ("STR", "DEX", "CON")}
    lowest = [{"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution"}[ab] for ab, v in saves.items() if v == min(saves.values())]
    concentrating = any("concentration" in c.condition_id for c in target.conditions.values())
    conditions = sorted({c.condition_id.rsplit(".", 1)[-1] for c in target.conditions.values() if c.condition_id.startswith("condition:typed.")
                         and c.condition_id.rsplit(".", 1)[-1] in ("grappled", "restrained", "prone", "poisoned", "stunned", "paralyzed", "blinded",
                                                                  "deafened", "frightened", "exhaustion", "burning", "bleeding", "slowed")})
    note(engine, PREFIX + "eye_of_the_mantis", owner,
         f"Eye of the Mantis on {target.display_name}: {target.current_hp}/{target.maximum_hp} HP, AC {target.armor_class + engine._ac_modifier(target)}, "
         f"Resistances {', '.join(resist) or 'none'}, Immunities {', '.join(immune) or 'none'}, "
         f"{'maintaining' if concentrating else 'not maintaining'} Concentration, conditions {', '.join(conditions) or 'none'}, "
         f"lowest physical save {'/'.join(lowest)}.", (target,))


@hook("attack_mode")
def eye_first_attack(ctx: Any, target: Any) -> str | None:
    if target is None:
        return None
    eye = _eye(target, ctx.actor)
    if eye is None or eye.data.get("attack_turn") == _stamp(ctx.engine):
        return None
    eye.data["attack_turn"] = _stamp(ctx.engine)
    return "ADVANTAGE"
