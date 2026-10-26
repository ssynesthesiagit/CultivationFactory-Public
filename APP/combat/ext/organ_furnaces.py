"""Five-Viscera Immortal Furnace: the Organ Furnace state (rider lane C7, 2026-09-30: "i want everything we can automated").

Printed Organ Furnaces (Body Refining Subpath Compendium): at the start of each turn choose the active Furnace(s) until the start
of your next turn -- one at CL3 (Five-Viscera Circuit), two different ones at CL10 (Twin Furnace Circulation), all five at CL14
(Fivefold Organ Harmony); with no choice yet, Heart is active. Each Furnace has its own once-per-turn use:
  Heart   once per turn on a hit, +Proficiency Bonus Fire or Radiant (Inner Cosmos: +3d8 Fire, Radiant or Force).
  Lung    +1 AC against ranged attacks (Inner Cosmos: ranged attacks against you have Disadvantage).
  Liver   once per turn after a Stamina-spending activation, regain Proficiency Bonus Hit Points if above 0 (Inner Cosmos: 2d8 + CON).
  Kidney  once per turn after a Stamina-spending activation of your own turn, stand from Prone free and move 5 feet without
          provoking (Inner Cosmos: 15 feet); asked.
  Spleen  once per turn after Stamina Guard resolves or a successful save against forced movement, Temporary HP equal to
          Proficiency Bonus (Inner Cosmos: twice PB and forced movement against you 10 feet shorter until your next turn).
Twin Furnace Circulation: once per turn after spending Stamina, replace one active Furnace with another (asked, optional).
Inner Cosmos Furnace: its named state "inner_cosmos_furnace" makes all five active and improved; Refine the Impure then
costs 0 Stamina (a no-cost variant offered only while the state is on).
Refine the Impure (``refine_the_impure`` effect): Poisoned -- repeat the original save with Advantage, a success ends it, a
failure suppresses it until the start of your next turn; ongoing Acid or Poison -- repeat its save with Advantage, a success
ends it, a failure takes 2d8 + CON off its next damage. Disease and consumed-substance penalties are the GM's.
Owned rows: ``path_passive`` kind ``organ_furnaces`` with ``count``. State: condition ``condition:typed.organ_furnaces``
(data: active list of names). Every hook returns early for a creature without the rows.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.five_viscera_immortal_furnace.feature."
SOURCE = PREFIX + "five_viscera_circuit"
STATE = "condition:typed.organ_furnaces"
COSMOS = "inner_cosmos_furnace"
SUPPRESSED = "condition:typed.refine_suppressed"
REDUCTION = "condition:typed.refine_next_damage"
SPLEEN_SHORTER = "condition:typed.spleen_forced_shorter"
FURNACES = ("heart", "lung", "liver", "kidney", "spleen")
LABELS = {"heart": "Heart (Fire): +PB Fire or Radiant once per turn on a hit",
          "lung": "Lung (Metal): +1 AC against ranged attacks",
          "liver": "Liver (Wood): regain PB Hit Points after spending Stamina",
          "kidney": "Kidney (Water): stand and move 5 feet after spending Stamina",
          "spleen": "Spleen (Earth): Temporary HP after Stamina Guard or resisting forced movement"}
STAMINA = "resource:core.stamina"


def _count(engine: Any, actor: Any) -> int:
    rows = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "organ_furnaces"]
    return max([int(row.get("count") or 0) for row in rows] or [0])


def _cosmos(engine: Any, actor: Any) -> bool:
    from .states import active

    return bool(active(engine, actor, COSMOS))


def active_furnaces(engine: Any, actor: Any) -> tuple[str, ...]:
    count = _count(engine, actor)
    if count <= 0 or not actor.active or actor.life_state is not None:
        return ()  # dormant while down
    if count >= 5 or _cosmos(engine, actor):
        return FURNACES
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    chosen = tuple((held.data or {}).get("active") or ()) if held is not None else ()
    return chosen or ("heart",)


def _set(engine: Any, actor: Any, names: list[str], source: str) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": STATE, "instance_id": held.instance_id})
    engine._apply_condition(actor, STATE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"active": list(names), "label": "Organ Furnace: " + ", ".join(n.title() for n in names)})


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _once(actor: Any, engine: Any, name: str) -> bool:
    flag = "_round_furnace_" + name
    if actor.turn_flags.get(flag) == _stamp(engine):
        return False
    actor.turn_flags[flag] = _stamp(engine)
    return True


def _numbers(engine: Any, actor: Any) -> dict[str, int]:
    """PB and CL from the owning row; the key ability modifier (Constitution for Body Refining) from its compiled numbers."""
    row = next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                if row.get("kind") == "organ_furnaces"), {})
    key_mod = next((int(((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("key_mod") or 0)
                    for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                    and ((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("key_mod") is not None), 0)
    return {"pb": int(row.get("pb") or actor.proficiency_bonus or 2), "cl": int(row.get("cl") or 1), "key_mod": key_mod}


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ------------------------------------------------------------------------------------------------------ choosing
@hook("turn_start_choice")
def choose_furnaces(engine: Any, actor: Any) -> None:
    count = _count(engine, actor)
    if count <= 0 or count >= 5 or not actor.active or _cosmos(engine, actor):
        return
    from .needle import ask, checkpoint_id

    current = list(active_furnaces(engine, actor))
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "organ_furnaces", actor.entity_id), actor, "choice:needle.organ_furnaces",
                 list(FURNACES), labels=LABELS, minimum=count, maximum=count, preferred=(current + [f for f in FURNACES if f not in current])[:count],
                 prompt=f"Organ Furnaces: choose {count} active Furnace{'s' if count > 1 else ''} for {actor.display_name} until its next turn.",
                 target_id=actor.entity_id)
    if picked:
        _set(engine, actor, list(picked)[:count], SOURCE)


def _stamina_spent_by_this_action(engine: Any, actor: Any) -> bool:
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED" and event.actor_id == actor.entity_id:
            return False
        if event.event_type == "RESOURCE_SPENT" and event.actor_id == actor.entity_id and (event.payload or {}).get("resource_id") == STAMINA \
                and int((event.payload or {}).get("amount") or 0) > 0:
            return True
    return False


@hook("action_completed")
def after_stamina(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    names = active_furnaces(engine, actor)
    if not names or not actor.active or not _stamina_spent_by_this_action(engine, actor):
        return
    from .needle import ask, checkpoint_id

    cosmos = _cosmos(engine, actor)
    nums = _numbers(engine, actor)
    if "liver" in names and actor.current_hp > 0 and _once(actor, engine, "liver"):
        _heal(engine, actor, nums, cosmos)
    if "kidney" in names and engine.state.current_actor_id == actor.entity_id and _once(actor, engine, "kidney"):
        _kidney(engine, actor, 15 if cosmos else 5)
    count = _count(engine, actor)
    if count == 2 and not cosmos and actor.turn_flags.get("_round_furnace_swap") != _stamp(engine):
        current = list(active_furnaces(engine, actor))
        options = [f"{old}>{new}" for old in current for new in FURNACES if new not in current]
        picked = ask(engine, _intent(engine), checkpoint_id(engine, "furnace_swap", actor.entity_id), actor, "choice:needle.furnace_swap",
                     options, allow_decline=True, default="decline",
                     labels={o: f"Replace {o.split('>')[0].title()} with {o.split('>')[1].title()}" for o in options},
                     prompt=f"Twin Furnace Circulation: {actor.display_name} spent Stamina; replace one active Furnace?", target_id=actor.entity_id)
        if picked:
            actor.turn_flags["_round_furnace_swap"] = _stamp(engine)
            old, new = picked[0].split(">")
            _set(engine, actor, [new if name == old else name for name in current], PREFIX + "twin_furnace_circulation")


def _heal(engine: Any, actor: Any, nums: dict[str, int], cosmos: bool) -> None:
    from .. import typed_executor as te
    from .states import context

    ctx = context(engine, actor, SOURCE, [actor], nums)
    row = {"type": "healing", "applies_to": "self", "evidence": "Liver Furnace"}
    row.update({"dice": {"count": 2, "sides": 8, "bonus_formula": "key_ability_modifier"}} if cosmos else {"formula": "pb"})
    te.run_effects(ctx, [row])


def _kidney(engine: Any, actor: Any, feet: int) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == "condition:typed.prone":
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    paths = routes(engine, actor, feet)
    if not paths:
        return
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "kidney_step", actor.entity_id), actor, "choice:needle.kidney_step",
                 sorted(paths), allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                 prompt=f"Kidney Furnace: {actor.display_name} may move up to {feet} feet without provoking.", target_id=actor.entity_id)
    if picked and picked[0] in paths:
        step(engine, actor, paths[picked[0]], SOURCE)


# ------------------------------------------------------------------------------------------------------ Heart, Lung
@hook("after_hit")
def heart(ctx: Any, target: Any, kind: str) -> None:
    if target is None or not target.active or "heart" not in active_furnaces(ctx.engine, ctx.actor):
        return
    if not _once(ctx.actor, ctx.engine, "heart"):
        return
    from .. import typed_executor as te

    cosmos = _cosmos(ctx.engine, ctx.actor)
    row = {"type": "extra_damage", "applies_to": "target", "evidence": "Heart Furnace"}
    row.update({"dice": {"count": 3, "sides": 8}, "damage_types": ["fire", "radiant", "force"]} if cosmos else
               {"flat": int(_numbers(ctx.engine, ctx.actor)["pb"]), "damage_types": ["fire", "radiant"]})
    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}), [row])


def _ranged_against(engine: Any, target: Any) -> bool:
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame["target_id"] != target.entity_id:
        return False
    action = engine.action_catalog.get(frame["source"])
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    kind = str((frame.get("effect") or {}).get("attack_kind") or "")
    return "ranged" in kind or "thrown" in kind or int(typed.get("range_ft") or 0) > 10


@hook("ac")
def lung_ac(engine: Any, target: Any) -> int | None:
    if "lung" in active_furnaces(engine, target) and not _cosmos(engine, target) and _ranged_against(engine, target):
        return 1
    return None


@hook("attack_mode")
def lung_cosmos(ctx: Any, target: Any) -> str | None:
    if target is not None and _cosmos(ctx.engine, target) and _count(ctx.engine, target) > 0 and _ranged_against(ctx.engine, target):
        return "DISADVANTAGE"
    return None


# --------------------------------------------------------------------------------------------------------- Spleen
def _spleen(engine: Any, actor: Any) -> None:
    if "spleen" not in active_furnaces(engine, actor) or not _once(actor, engine, "spleen"):
        return
    pb = int(_numbers(engine, actor)["pb"])
    cosmos = _cosmos(engine, actor)
    engine._grant_temp_hp(actor, 2 * pb if cosmos else pb, PREFIX + "five_viscera_circuit", actor.entity_id)
    if cosmos:
        engine._remove_condition(actor, SPLEEN_SHORTER, SOURCE)
        engine._apply_condition(actor, SPLEEN_SHORTER, SOURCE, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Spleen Furnace: forced movement against you is 10 feet shorter"})
    note(engine, SOURCE, actor, f"Spleen Furnace: {actor.display_name} gains Temporary Hit Points.")


@hook("event")
def spleen_after_guard(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """After Stamina Guard resolves, the Temporary HP land once the guarded packet has committed (they do not absorb it)."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_spleen_pending")
    source = engine.events[-1].source_definition_id if engine.events else ""
    if event_type == "REACTION_RESOLVED" and str(source or "").endswith("feature.stamina_guard"):
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        if actor is not None and _count(engine, actor) > 0:
            engine.__dict__.setdefault("_spleen_pending", set()).add(actor.entity_id)
    elif event_type == "DAMAGE_COMMITTED":
        pending = engine.__dict__.get("_spleen_pending") or set()
        for target_id in kwargs.get("target_ids") or ():
            if target_id in pending:
                pending.discard(target_id)
                actor = engine.state.actors.get(target_id)
                if actor is not None and actor.active:
                    _spleen(engine, actor)


@hook("after_save_resolved")
def spleen_after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if subject is None or failed or "forced_movement" not in set(named or ()) or _count(ctx.engine, subject) <= 0:
        return
    _spleen(ctx.engine, subject)


@hook("forced_movement_reduction")
def spleen_forced(ctx: Any, subject: Any) -> int | None:
    return 10 if subject is not None and any(c.condition_id == SPLEEN_SHORTER for c in subject.conditions.values()) else None


# ------------------------------------------------------------------------------------------------ Inner Cosmos cost
@hook("compile_actions")
def free_refine(info: dict[str, Any]) -> list[Any] | None:
    if PREFIX + "inner_cosmos_furnace" not in info["owned_ids"]:
        return None
    from .states import PREFIX as STATE_PREFIX

    refine = next((a for a in info["actions"] if ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "refine_the_impure"), None)
    if refine is None:
        return None
    return [refine.model_copy(update={"source_definition_id": refine.source_definition_id + ".inner_cosmos",
                                      "display_name": refine.display_name + " (Inner Cosmos: no Stamina)", "costs": (),
                                      "parameters": {**refine.parameters, "requires_condition": STATE_PREFIX + COSMOS}})]


# ------------------------------------------------------------------------------------------------ Refine the Impure
@effect("refine_the_impure")
def refine(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .repeat_saves import repeatable, save_of

    engine, actor = ctx.engine, ctx.actor
    poisoned = repeatable(actor, ("poisoned",))
    ongoing = [(iid, c) for iid, c in actor.conditions.items() if save_of(c) is not None and any(
        isinstance(e, dict) and set(str(t).lower() for t in e.get("damage_types") or []) & {"acid", "poison"}
        for e in (c.data or {}).get("ongoing_effects") or [])]
    options = {**({"poisoned": "Poisoned: repeat its save with Advantage"} if poisoned else {}),
               **({"ongoing": "Ongoing Acid or Poison: repeat its save with Advantage"} if ongoing else {})}
    if not options:
        ctx.rider("Refine the Impure: nothing on you it can refine (Disease and consumed-substance penalties are the GM's).")
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "refine_the_impure", actor.entity_id), actor, "choice:needle.refine_the_impure",
                 list(options), labels=options, prompt=f"Refine the Impure: choose what {actor.display_name} purges.", target_id=actor.entity_id)
    if not picked:
        return
    iid, condition = (poisoned if picked[0] == "poisoned" else ongoing)[0]
    save = save_of(condition)
    dc = int(save["dc"])
    roll = engine._roll_save(actor, str(save["ability"]).upper(), dc, ctx.source, "ADVANTAGE")
    if roll is None:
        return
    if roll.total >= dc:
        if iid in actor.conditions:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})
        return
    if picked[0] == "poisoned":
        # "failure suppresses it until the start of your next turn": set aside now, restored at the start of that turn.
        actor.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "suppressed": True})
        engine._apply_condition(actor, SUPPRESSED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Poisoned (suppressed until the start of your next turn)",
                                      "restore": {"condition_id": condition.condition_id, "source": condition.source_definition_id,
                                                  "source_actor": condition.source_actor_id, "expires_on": condition.expires_on,
                                                  "data": dict(condition.data or {})}})
        return
    from ..gate2_runtime_models import DiceSpec

    amount = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=int(ctx.numbers.get("key_mod", 0) or 0)), actor_id=actor.entity_id,
                                reason=f"REDUCTION:{ctx.source}", critical=False)
    engine._record_roll(amount)
    engine._apply_condition(actor, REDUCTION, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Refine the Impure: the next damage from that effect is {amount.total} lower",
                                  "amount": int(amount.total), "from": condition.source_definition_id})


@hook("turn_start")
def restore_suppressed(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == SUPPRESSED]:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": SUPPRESSED, "instance_id": held.instance_id})
        restore = (held.data or {}).get("restore") or {}
        if restore.get("condition_id"):
            engine._apply_condition(actor, restore["condition_id"], restore["source"], restore["source_actor"],
                                    expires_on=restore.get("expires_on") or "UNTIL_REMOVED", data=dict(restore.get("data") or {}))


@hook("incoming_damage")
def refined_next_damage(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: Any) -> int | None:
    held = next((c for c in target.conditions.values() if c.condition_id == REDUCTION
                 and (c.data or {}).get("from") == source_definition_id), None)
    if held is None or amount <= 0:
        return None
    target.conditions.pop(held.instance_id)
    engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                         payload={"condition_id": REDUCTION, "instance_id": held.instance_id})
    return min(int(amount), int(held.data["amount"]))


@hook("ai_candidate_allowed")
def refine_only_with_something(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    if not any(isinstance(e, dict) and e.get("type") == "refine_the_impure" for e in typed.get("effects") or []):
        return None
    from .repeat_saves import repeatable, save_of

    ongoing = any(save_of(c) is not None and any(isinstance(e, dict) and set(str(t).lower() for t in e.get("damage_types") or []) & {"acid", "poison"}
                                                 for e in (c.data or {}).get("ongoing_effects") or []) for c in actor.conditions.values())
    return None if repeatable(actor, ("poisoned",)) or ongoing else False
