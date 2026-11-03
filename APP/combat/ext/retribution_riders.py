"""Retribution lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium,
Retribution (owner's text: authority/typed_mechanics/rules_text.json).  combat/ext/counterstrike.py plays Counterstrike and runs each Counter
talent's typed effects on the hit; this module gives those effects something to do where their typed rows did nothing.  Rows: feature block
"lane9_retribution" (combat/rules/feature_blocks.d/riders_lane9.json); typed effects "retribution_*".

  Haymaker              failed Dexterity save: its speech and breath channel is damaged (for the fight -- magical healing or a rest ends it):
                        each time it uses an ability that needs its voice (combat/speech.py) it makes a Constitution save or the attempt
                        fails, the action spent. A creature whose printed record says it has no mouth, throat, breath channel or equivalent
                        anatomy is immune (combat/physiology.trait, voice_and_breath_channel); an unstated one is not read as absent.
  Intense Conditioning  (expend Martial Focus) failed Charisma save: for 1 minute, attempting the same category of action as the one that
                        provoked the Counterstrike (an attack roll, or a technique) needs a new Charisma save or it fails before it resolves.
                        A creature immune to Frightened is immune.
  Spell Breaker         a Counterstrike that damages a creature while it activates a technique: Constitution save, DC 10 or half the damage
                        (at most 30); on a failure the activation fails and what it committed is lost.
  Dug-In Blow           you have Resistance to one Bludgeoning, Piercing or Slashing damage instance the target deals you before the start of
                        your next turn. Newly compiled choose_instance rows ask on each eligible packet; declining keeps
                        the protection for a later packet. Older sealed rows retain their automatic first-packet behavior.
  Headfake              while you hold Martial Focus, Opportunity Attacks against you have Disadvantage.
  Court of the          it ends early when you become Incapacitated.
  Awaiting Blade

Judgment calls: a failed Intense Conditioning or Haymaker attempt stops the activation after its costs are paid (technique_start runs after
them), so a CP cost is lost with it; "movement" as Intense Conditioning's category is the GM's (a move cannot be refused mid-way here).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

BLOCK = "lane9_retribution"
T = "TAL_RETRIBUTION_"
FOCUS = "resource:core.martial_focus"
C = "condition:typed."
HAYMAKER, CONDITIONED, DUG_IN = C + "speech_damaged", C + "conditioned", C + "dug_in"
COURT = T + "COURT_OF_THE_AWAITING_BLADE"
INCAPACITATING = ("incapacitated", "stunned", "paralyzed", "unconscious", "petrified")


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _dc(ctx: Any) -> int:
    return int(ctx.numbers.get("save_dc") or 10)


def _attack(action: Any) -> bool:
    from ..typed_executor import _walk_rows

    typed = (action.parameters or {}).get("typed") or {}
    return any(isinstance(row, dict) and row.get("type") == "attack" for row in _walk_rows(typed.get("effects")))


def _provoking(engine: Any, creature: Any) -> Any:
    """The action ``creature`` has begun (the Counterstrike answers its INTENT_ACCEPTED)."""
    last = next((e for e in reversed(engine.events[-60:]) if e.event_type == "INTENT_ACCEPTED" and e.actor_id == creature.entity_id), None)
    return engine.action_catalog.get(str(last.source_definition_id)) if last is not None else None


# ------------------------------------------------------------------------------------------------ the Counter talents' effects
@effect("retribution_haymaker")
def haymaker(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import physiology

    for target in ctx.targets or []:
        if target is not None and target.active:
            if physiology.trait(target, "voice_and_breath_channel") is False:
                # "A creature without a meaningful mouth, throat, breath channel, or equivalent anatomy is immune."
                # Only that printed fact answers it (combat/physiology.trait reads the creature's explicit
                # physiology labels first and its creature-kind defaults second). Not needing to breathe is a
                # different fact: an undead that still has a mouth can be silenced by this hit, so silence is
                # never inferred, and an unstated record leaves the creature vulnerable.
                note(ctx.engine, T + "HAYMAKER", ctx.actor,
                     f"Haymaker: {target.display_name}'s creature record says it has no mouth, throat or breath channel, "
                     f"so there is nothing to damage. The hit lands as normal.", (target,))
                continue
            ctx.engine._apply_condition(target, HAYMAKER, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"dc": _dc(ctx), "label": "Haymaker: its speech and breath channel is damaged"})


@effect("retribution_conditioning")
def conditioning(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import condition_immune

    engine, actor = ctx.engine, ctx.actor
    if actor.resources.get(FOCUS, 0) < 1:
        ctx.rider("Intense Conditioning: no Martial Focus to expend.")
        return
    engine._spend_resource(actor, FOCUS, 1, T + "INTENSE_CONDITIONING")
    dc = _dc(ctx)
    for target in ctx.targets or []:
        if target is None or not target.active or condition_immune(engine, target, "frightened"):
            continue
        roll = engine._roll_save(target, "CHA", dc, T + "INTENSE_CONDITIONING")
        if roll is None or int(roll.total) >= dc:
            continue
        provoking = _provoking(engine, target)
        category = "attack" if provoking is not None and _attack(provoking) else "technique"
        from .effect_durations import token

        engine._apply_condition(target, CONDITIONED, T + "INTENSE_CONDITIONING", actor.entity_id,
                                expires_on=token("start", actor.entity_id, int(actor.turns_started) + 10),
                                data={"dc": dc, "category": category, "label": f"Intense Conditioning: {'an attack roll' if category == 'attack' else 'a technique'} needs a Charisma save"})


@effect("retribution_spell_breaker")
def spell_breaker(ctx: Any, eff: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_retribution_broken")
    engine, actor = ctx.engine, ctx.actor
    for target in ctx.targets or []:
        if target is None or not target.active:
            continue
        provoking = _provoking(engine, target)
        typed = ((provoking.parameters or {}).get("typed") or {}) if provoking is not None else {}
        if provoking is None or typed.get("weapon") is not None or not typed:
            continue  # "while it is casting a spell, activating a sphere talent, or using another interruptible supernatural effect"
        dealt = next((int((e.payload or {}).get("reduced_to") or 0) for e in reversed(engine.events[-30:])
                      if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor.entity_id and target.entity_id in (e.target_ids or ())), 0)
        if dealt <= 0:
            continue
        dc = min(30, max(10, dealt // 2))
        roll = engine._roll_save(target, "CON", dc, T + "SPELL_BREAKER")
        if roll is not None and int(roll.total) < dc:
            engine.__dict__.setdefault("_retribution_broken", {})[target.entity_id] = provoking.source_definition_id
            note(engine, T + "SPELL_BREAKER", target, f"Spell Breaker: {target.display_name}'s {provoking.display_name} breaks apart.")


@effect("retribution_dug_in")
def dug_in(ctx: Any, eff: dict[str, Any]) -> None:
    for target in ctx.targets or []:
        if target is not None:
            chosen = bool(eff.get("choose_instance"))
            data = {"from": target.entity_id,
                    "label": (f"Dug-In Blow: choose one physical damage instance from {target.display_name} before your next turn"
                              if chosen else f"Dug-In Blow: Resistance to {target.display_name}'s next physical hit")}
            if chosen:
                data["choose_instance"] = 1
            ctx.engine._apply_condition(ctx.actor, DUG_IN, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data=data)


# ------------------------------------------------------------------------------------------------ what they do later
@hook("technique_start")
def refuse(engine: Any, actor: Any, action: Any) -> bool | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_retribution_broken")
    from .. import speech

    broken = engine.__dict__.get("_retribution_broken") or {}
    if broken.get(actor.entity_id) == action.source_definition_id:
        del broken[actor.entity_id]
        return True  # Spell Breaker: "The triggering activation fails."
    for held in _held(actor, HAYMAKER):
        if speech.needs_voice(action):
            dc = int((held.data or {}).get("dc") or 10)
            roll = engine._roll_save(actor, "CON", dc, T + "HAYMAKER")
            if roll is not None and int(roll.total) < dc:
                note(engine, T + "HAYMAKER", actor, f"Haymaker: {actor.display_name}'s voice fails; {action.display_name} does not happen.")
                return True
    for held in _held(actor, CONDITIONED):
        category = "attack" if _attack(action) else "technique"
        if category == (held.data or {}).get("category"):
            dc = int((held.data or {}).get("dc") or 10)
            roll = engine._roll_save(actor, "CHA", dc, T + "INTENSE_CONDITIONING")
            if roll is not None and int(roll.total) < dc:
                note(engine, T + "INTENSE_CONDITIONING", actor, f"Intense Conditioning: {actor.display_name} flinches; {action.display_name} fails.")
                return True
    return None


@hook("incoming_damage")
def dug_in_resistance(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 0 or str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING"):
        return None
    for held in _held(target, DUG_IN):
        if (held.data or {}).get("from") == source_actor_id:
            if (held.data or {}).get("choose_instance") == 1:
                from .needle import ask, checkpoint_id

                attacker = engine.state.actors.get(source_actor_id)
                action = engine.action_catalog.get(source_definition_id)
                origin = attacker.display_name if attacker is not None else "the creature you countered"
                activity = action.display_name if action is not None else "its damage"
                chosen = ask(engine, getattr(engine, "_active_intent", None),
                             checkpoint_id(engine, "dug_in_instance", target.entity_id), target,
                             "choice:needle.dug_in_instance", ["resist"],
                             labels={"resist": "Use Dug-In Blow on this damage instance"},
                             prompt=(f"Dug-In Blow: {origin}'s {activity} deals {amount} {str(damage_type).lower()} damage to "
                                     f"{target.display_name}. Use your one protection now, or keep it until your next turn?"),
                             preferred=["resist"], allow_decline=True, target_id=target.entity_id,
                             name="Dug-In Blow", feature_id=T + "DUG_IN_BLOW",
                             prompt_context={"cost": "No extra cost or Reaction.", "action_name": activity,
                                             "action_actor_id": source_actor_id or "", "affected_id": target.entity_id})
                if "resist" not in chosen:
                    return None
                # Each successful Counter supplies one protection. A second held
                # protection (Two Answers) must survive consuming this instance.
                target.conditions.pop(held.instance_id, None)
                engine._append_event("CONDITION_REMOVED", T + "DUG_IN_BLOW", actor_id=held.source_actor_id,
                                     target_ids=(target.entity_id,),
                                     payload={"condition_id": DUG_IN, "instance_id": held.instance_id})
                return amount - amount // 2
            engine._remove_condition(target, DUG_IN, T + "DUG_IN_BLOW")  # "one instance"
            return amount - amount // 2
    return None


@hook("attack_mode")
def headfake(ctx: Any, target: Any) -> str | None:
    engine = ctx.engine
    if rows(engine, target, "headfake") and target.resources.get(FOCUS, 0) >= 1 and getattr(engine, "_typed_oa_attacker", None) == ctx.actor.entity_id:
        return "DISADVANTAGE"  # "While you hold Martial Focus, Opportunity Attacks against you have Disadvantage."
    return None


@hook("event")
def court_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Court of the Awaiting Blade: "The Court ends early if you become Incapacitated.\""""
    if event_type != "CONDITION_APPLIED" or not any(str((kwargs.get("payload") or {}).get("condition_id") or "").endswith("." + n) for n in INCAPACITATING):
        return
    from .. import zones

    for target_id in kwargs.get("target_ids") or ():
        for zone in list(zones.typed_zones(engine)):
            action = engine.action_catalog.get(zone.source_definition_id)
            source = str((((action.parameters or {}).get("typed") or {}).get("source") or "")) if action is not None else ""
            if zone.active and zone.owner_id == target_id and source == COURT:
                zones.remove(engine, zone, "INCAPACITATED")
