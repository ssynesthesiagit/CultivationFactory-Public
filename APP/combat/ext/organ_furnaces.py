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
    if actor is None:return 0
    rows = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "organ_furnaces"]
    from .body_modes_scene_resources import available
    levels = {1: (SOURCE, 3), 2: (PREFIX + 'twin_furnace_circulation', 10), 5: (PREFIX + 'fivefold_organ_harmony', 14)}
    return max([int(row.get('count') or 0) for row in rows
                if int(row.get('count') or 0) in levels and available(engine, actor, *levels[int(row['count'])])] or [0])


def _cosmos(engine: Any, actor: Any) -> bool:
    from .states import active

    from .body_modes_scene_resources import available
    from ..alternative_payments import owned
    return owned(engine,actor,PREFIX+'inner_cosmos_furnace') and bool(active(engine, actor, COSMOS)) and available(engine, actor, PREFIX + 'inner_cosmos_furnace', 18)


def active_furnaces(engine: Any, actor: Any) -> tuple[str, ...]:
    count = _count(engine, actor)
    if count <= 0 or not actor.active or actor.life_state is not None:
        return ()  # dormant while down
    if count >= 5 or _cosmos(engine, actor):
        return FURNACES
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    chosen = tuple((held.data or {}).get("active") or ()) if held is not None else ()
    legal = tuple(dict.fromkeys(n for n in chosen if n in FURNACES))[:count]
    return legal if len(legal) == count else tuple([*legal, *(n for n in FURNACES if n not in legal)][:count])


def _set(engine: Any, actor: Any, names: list[str], source: str, source_cl: int | None = None) -> None:
    from .body_modes_scene_resources import effective_body_cl
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": STATE, "instance_id": held.instance_id})
    engine._apply_condition(actor, STATE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"active": list(names), "source_cl": effective_body_cl(engine, actor) if source_cl is None else source_cl, "label": "Organ Furnace: " + ", ".join(n.title() for n in names)})


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


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
    from .body_modes_scene_resources import constitution_modifier
    key_mod = constitution_modifier(engine,actor)
    from .body_modes_scene_resources import effective_body_pb,effective_body_cl
    held=next((c for c in actor.conditions.values() if c.condition_id==STATE),None)
    source_cl=int((held.data if held else {}).get("source_cl") or effective_body_cl(engine,actor))
    return {"pb": effective_body_pb(engine,actor), "cl": effective_body_cl(engine,actor), "source_cl":source_cl, "key_mod": key_mod}


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ------------------------------------------------------------------------------------------------------ choosing
@hook("turn_start_choice", priority=-100)
def choose_furnaces(engine: Any, actor: Any) -> None:
    count = _count(engine, actor)
    if count <= 0 or count >= 5 or not actor.active or _cosmos(engine, actor):
        return
    from .needle import ask, checkpoint_id

    current = list(active_furnaces(engine, actor))
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "organ_furnaces", actor.entity_id), actor, "choice:needle.organ_furnaces",
                 list(FURNACES), labels=LABELS, minimum=count, maximum=count, allow_decline=True, preferred=(current + [f for f in FURNACES if f not in current])[:count],
                 prompt=f"Organ Furnaces: choose {count} active Furnace{'s' if count > 1 else ''} for {actor.display_name} until its next turn.",
                 target_id=actor.entity_id)
    held=next((c for c in actor.conditions.values() if c.condition_id==STATE),None)
    retained=int(held.data.get("source_cl") or 0) if held is not None and not picked else None
    _set(engine, actor, list(picked)[:count] if picked else current, SOURCE,source_cl=retained or None)


@hook("paid_activation_resolved")
def after_paid_activation(engine: Any, actor: Any, receipt: dict[str, Any]) -> None:
    names = active_furnaces(engine, actor)
    if not names or receipt['paid'] <= 0:
        return
    from .ability_source import is_path_or_subpath_feature
    _stamina_benefits(engine, actor, receipt['source'], is_path_or_subpath_feature(receipt['source']))


def _stamina_benefits(engine: Any, actor: Any, source_definition_id: str, path_activation: bool) -> None:
    names = active_furnaces(engine, actor)
    from .needle import ask, checkpoint_id

    cosmos = _cosmos(engine, actor)
    nums = _numbers(engine, actor)
    if "liver" in names and path_activation and actor.current_hp > 0 and _once(actor, engine, "liver"):
        _heal(engine, actor, nums, cosmos)
    if "kidney" in names and actor.turn_flags.get('_round_furnace_kidney') != _stamp(engine):
        if _kidney(engine, actor, 15 if cosmos else 5):
            _once(actor, engine, "kidney")
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

    ctx = context(engine, actor, SOURCE, [actor], nums).with_source(SOURCE)
    ctx.intent = _intent(engine)
    row = {"type": "healing", "applies_to": "self", "evidence": "Liver Furnace"}
    row.update({"dice": {"count": 2, "sides": 8, "bonus_formula": "key_ability_modifier"}} if cosmos else {"formula": "pb"})
    te.run_effects(ctx, [row])


def _kidney(engine: Any, actor: Any, feet: int) -> bool:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step
    prone = [c for c in actor.conditions.values() if c.condition_id.rsplit('.', 1)[-1] == 'prone']
    paths = routes(engine, actor, feet)
    can_stand = bool(prone) and engine._effective_speed(actor) > 0
    options = (["stand"] if can_stand else []) + (["move"] if paths else []) + (["stand_move"] if can_stand and paths else [])
    if not options:return False
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "kidney_operation", actor.entity_id), actor,
        "choice:needle.kidney_operation", options, allow_decline=True, default="decline",
        labels={"stand":"Stand from Prone without spending movement", "move":f"Move up to {feet} feet without provoking",
                "stand_move":f"Stand and then move up to {feet} feet without provoking"},
        prompt=f"Kidney Furnace: {actor.display_name} finished spending Stamina. Choose either operation, both, or decline; no action or movement is spent.", target_id=actor.entity_id)
    if not picked:return False
    operation = picked[0]
    performed = False
    if operation in ('stand','stand_move'):
        for condition in prone:engine._remove_condition_instance(actor,condition.instance_id,SOURCE,expected=condition)
        performed = bool(prone)
    if operation in ('move','stand_move'):
        # Standing may change route cost. Re-derive every legal route afterward.
        paths = routes(engine, actor, feet)
        if paths:
            destination = ask(engine, _intent(engine), checkpoint_id(engine, "kidney_step", actor.entity_id), actor,
                "choice:needle.kidney_step", sorted(paths), allow_decline=True, default='decline',
                labels={k:"Move to "+k.removeprefix('cell:') for k in paths},
                prompt=f"Kidney Furnace: choose {actor.display_name}'s legal destination up to {feet} feet away; no Opportunity Attacks.",target_id=actor.entity_id)
            if destination and destination[0] in paths:
                before = actor.position
                step(engine,actor,paths[destination[0]],SOURCE)
                performed = performed or actor.position != before
    return performed


# ------------------------------------------------------------------------------------------------------ Heart, Lung
@hook("after_hit")
def heart(ctx: Any, target: Any, kind: str) -> None:
    if target is None or not target.active or "heart" not in active_furnaces(ctx.engine, ctx.actor):
        return
    if ctx.actor.turn_flags.get('_round_furnace_heart') == _stamp(ctx.engine):return
    from .needle import ask, checkpoint_id
    choices = ['fire','radiant','force'] if _cosmos(ctx.engine,ctx.actor) else ['fire','radiant']
    picked = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'furnace_heart',target.entity_id),ctx.actor,
        'choice:needle.furnace_heart',choices,labels={k:k.title()+' damage' for k in choices},allow_decline=True,
        prompt=f'Heart Furnace: {ctx.actor.display_name} hit {target.display_name}. Add the Furnace damage to this hit once this turn? No cost.',target_id=target.entity_id)
    if not picked:return
    _once(ctx.actor,ctx.engine,'heart')
    from .. import typed_executor as te

    cosmos = _cosmos(ctx.engine, ctx.actor)
    row = {"type": "extra_damage", "applies_to": "target", "evidence": "Heart Furnace"}
    row.update({"dice": {"count": 3, "sides": 8}, "damage_types": ["fire", "radiant", "force"]} if cosmos else
               {"flat": int(_numbers(ctx.engine, ctx.actor)["pb"]), "damage_types": ["fire", "radiant"]})
    row['damage_types'] = [picked[0]]
    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}), [row])


def _ranged_against(engine: Any, target: Any) -> bool:
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame["target_id"] != target.entity_id:
        return False
    action = engine.action_catalog.get(frame["source"])
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    kind = str((frame.get("effect") or {}).get("attack_kind") or "")
    # Attack kind/weapon delivery is authoritative; long reach is never ranged.
    weapon = typed.get('weapon') or {}
    return 'ranged' in kind or 'thrown' in kind or (kind == 'weapon' and (weapon.get('ranged') is True or (action is not None and action.range_ft is not None)))


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
    if subject is None or failed or ctx.actor is subject or ctx.actor.team_id == subject.team_id or "forced_movement" not in set(named or ()) or _count(ctx.engine, subject) <= 0:
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


@hook('body_mode_profiles')
def circuit_profile(bundle):
    if not any(r.get('feature_id')==SOURCE for r in bundle.get('typed_passives',())):return
    return [{'source':PREFIX.removesuffix('.feature.'),'name':'Organ Furnaces','feature_levels':{SOURCE:3},'separate_conditions':[BREATH]}]


@hook('fight_setup_tasks')
def circuit_tasks(engine):
    return [{'actor_id':a.entity_id,'source_id':SOURCE} for a in engine.state.actors.values()
            if 0<_count(engine,a)<5 and not _cosmos(engine,a)] or None


@hook('fight_setup')
def circuit_setup(engine,actor,source,intent):
    if source != SOURCE:return
    choose_furnaces(engine,actor)
    return True


@hook('compile_actions')
def signs_actions(info):
    if SOURCE not in info['owned_ids']:return
    from .body_modes_scene_resources import setting_action
    return [setting_action(info,SOURCE,'furnace_signs.'+str(value),'Organ Furnaces: '+('Reveal' if value else 'Suppress')+' cosmetic signs',
        {'type':'organ_furnace_signs','visible':value},'Change only visible Furnace signs, without an action or resource cost. It does not hide a detectable activation.') for value in (0,1)]


@effect('organ_furnace_signs')
def furnace_signs(ctx,row):
    if _count(ctx.engine,ctx.actor)<=0:return
    ctx.engine._remove_condition(ctx.actor,'condition:typed.organ_furnace_signs',SOURCE)
    ctx.engine._apply_condition(ctx.actor,'condition:typed.organ_furnace_signs',SOURCE,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'visible':int(row['visible']),'label':'Organ Furnace cosmetic signs '+('revealed' if row['visible'] else 'suppressed')})


BREATH_HAZARDS={'category:inhalation','category:suffocation','inhaled_poison','gas','smoke','suffocation','breathing_interference'}

@hook('save')
def lung_save(ctx,subject,ability,named):
    if 'lung' in active_furnaces(ctx.engine,subject) and (set(named or ()) & BREATH_HAZARDS or ctx.typed.get('smoke_nonbreather_advantage') is True):
        return {'bonus':0,'modes':['ADVANTAGE']}


@hook('ability_check_hazards')
def lung_check(engine,actor,ability,skill,hazards):
    if 'lung' in active_furnaces(engine,actor) and set(hazards or ()) & BREATH_HAZARDS:return 'ADVANTAGE'


@hook('opposed_check_resolved')
def spleen_check(ctx,target,result,actor_check,target_check):
    # The target actually succeeded against a hostile forced-movement check.
    spec=target_check
    if target is not None and ctx.actor.team_id!=target.team_id and not result.success and 'forced_movement' in set(spec.get('hazards') or ()):
        _spleen(ctx.engine,target)


FAMILY=PREFIX.removesuffix('.feature.')
BREATH='condition:typed.furnace_breath'


def _journey_names(session,aid,at=None):
    import json
    from .body_modes_scene_resources import AUTHORITY,journey_available
    actor=session.state['actors'][aid]
    if not any(p['source']==FAMILY for p in circuit_profile(actor['bundle']) or []):return ()
    if not journey_available(session,aid,SOURCE,3,at=at):return ()
    stored=actor.get('source_states',{}).get(AUTHORITY,{}).get('effects',[])
    record=next((json.loads(r['model']) for r in stored if r['kind']=='condition' and json.loads(r['model']).get('condition_id')==STATE),None)
    return tuple(n for n in ((record or {}).get('data',{}).get('active') or ['heart']) if n in FURNACES)[:1]


def _journey_breath_state(session,aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(FAMILY,{})


def _ordinary_breath_seconds(bundle):
    template=bundle['actor_template']
    con=next((int((a.get('parameters',{}).get('typed') or {}).get('numbers',{}).get('con_mod') or 0)
              for a in bundle.get('action_catalog',[]) if (a.get('parameters',{}).get('typed') or {}).get('numbers',{}).get('con_mod') is not None),0)
    return max(30,(1+con)*60),max(1,con)*6


@hook('journey_options')
def furnace_travel_options(session,aid):
    if not _journey_names(session,aid):return
    return ([{'id':'furnace:'+name,'kind':'furnace_select','payload':{'furnace':name},'label':f'Organ Furnaces: choose {name.title()} for this outside-combat turn; no cost.'} for name in FURNACES]+
            [{'id':'furnace:hold_breath','kind':'furnace_breath','payload':{'operation':'hold'},'label':'Hold your breath. Lung Furnace permits one hour; holding does not permit speech, spellcasting or sound without air.'},
             {'id':'furnace:resume_breath','kind':'furnace_breath','payload':{'operation':'breathe'},'label':'Resume breathing if breathable air is available; no action or resource cost.'}])


@hook('journey_command')
def furnace_travel_command(session,aid,kind,payload):
    if kind not in ('furnace_select','furnace_breath'):return
    import json
    from .body_modes_scene_resources import AUTHORITY,profiles
    from ..journey import require
    actor=session.state['actors'][aid]
    require(_journey_names(session,aid),'This creature cannot use its Organ Furnace system now.')
    state=_journey_breath_state(session,aid)
    if kind=='furnace_select':
        require(set(payload)=={'furnace'} and payload['furnace'] in FURNACES,'Choose one legal Organ Furnace.')
        tick=int(session.clock())//6
        require(state.get('selection_tick')!=tick,'Choose the Furnace once at the start of this six-second outside-combat turn.')
        state['selection_tick']=tick
        managed=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
        effects=managed.setdefault('effects',[])
        effects[:]=[r for r in effects if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')==STATE)]
        model={'condition_id':STATE,'source_definition_id':SOURCE,'source_actor_id':aid,
               'data':{'active':[payload['furnace']],'source_cl':actor['bundle']['cl'],'label':'Organ Furnace: '+payload['furnace'].title()}}
        effects.append({'kind':'condition','model':json.dumps(model,sort_keys=True)})
        session.emit('FURNACE_SELECTED',aid,furnace=payload['furnace'],source=SOURCE)
    else:
        require(set(payload)=={'operation'} and payload['operation'] in ('hold','breathe'),'Choose holding or resuming breath.')
        no_air=any(r['kind']=='breathing_exposure' and r['expires_at']>session.clock() and r['value'].get('no_air')==1
                   for r in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values())
        if payload['operation']=='breathe':
            require(not no_air,'There is no breathable air; resuming breath cannot reset this clock.')
            state.pop('held_num',None);state.pop('held_den',None)
        elif 'held_num' not in state:
            state['held_num']=0;state['held_den']=1
        session.emit('BREATH_CONTROL_CHANGED',aid,operation=payload['operation'],source=SOURCE)
    return True


@hook('journey_elapsed')
def lung_travel_clock(session,aid,before,seconds,moving):
    from fractions import Fraction
    from .body_modes_scene_resources import AUTHORITY
    actor=session.state['actors'][aid]
    state=actor.get('source_states',{}).get(FAMILY,{})
    no_air=any(r['kind']=='breathing_exposure' and r['expires_at']>before and r['value'].get('no_air')==1
               for r in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values())
    if no_air and 'held_num' not in state:
        state=_journey_breath_state(session,aid);state['held_num']=0;state['held_den']=1
    if 'held_num' not in state:return
    held_before=Fraction(state['held_num'],state['held_den'])
    held=held_before+seconds
    state['held_num'],state['held_den']=held.numerator,held.denominator
    normal,buffer=_ordinary_breath_seconds(actor['bundle'])
    records=list(actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values())
    boundaries=sorted({before,before+seconds,*(Fraction(r['expires_at']) for r in records if before<r['expires_at']<before+seconds)})
    suffocated=False
    for start,end in zip(boundaries,boundaries[1:]):
        airless=any(r['kind']=='breathing_exposure' and r['expires_at']>start and r['value'].get('no_air')==1 for r in records)
        limit=3600 if 'lung' in _journey_names(session,aid,at=start) else normal
        if airless and held_before+(end-before)>=limit+buffer:
            suffocated=True
            break
    if suffocated and not state.get('suffocated'):
        # Genuine elapsed-time loss, not a test/GM damage receipt. The journey
        # health snapshot will bind the same zero-HP state in the next encounter.
        from ..gate2_runtime_models import ActorState
        snapshot=actor.get('encounter_snapshot')
        if snapshot is None:
            maximum=actor['bundle']['actor_template']['maximum_hp']
            snapshot={'current_hp':maximum,'maximum_hp':maximum,'temporary_hp':0,'active':1,'life_state':'','conditions':{}}
        snapshot.update(current_hp=0,life_state='DYING')
        actor['encounter_snapshot']=snapshot;actor['incapacitated']=1;state['suffocated']=1
        session.emit('SUFFOCATION_COMMITTED',aid,source=SOURCE,held_num=held.numerator,held_den=held.denominator)


@hook('journey_properties')
def furnace_breath_properties(session,aid):
    actor=session.state['actors'][aid]
    state=actor.get('source_states',{}).get(FAMILY,{})
    if not state and not _journey_names(session,aid):return
    normal,buffer=_ordinary_breath_seconds(actor['bundle'])
    return {'hold_breath_seconds':3600 if 'lung' in _journey_names(session,aid) else normal,
            'breath_held_num':state.get('held_num',0),'breath_held_den':state.get('held_den',1),
            'speech_without_air':0,'sound_without_air':0}


@hook('fact_admission_schema')
def breathing_exposure_schema(session,source,subject,kind):
    from .body_modes_scene_resources import AUTHORITY
    if source!=AUTHORITY or kind!='breathing_exposure' or not circuit_profile(session.state['actors'][subject]['bundle']):return
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
            'description':'The printed breath hazard, actual air availability and source authority.'}


@hook('compile_actions')
def breath_actions(info):
    if SOURCE not in info['owned_ids']:return
    from .body_modes_scene_resources import setting_action
    return [setting_action(info,SOURCE,'furnace_breath.'+operation,'Organ Furnaces: '+('Hold breath' if operation=='hold' else 'Resume breathing'),
        {'type':'furnace_breath_control','operation':operation},'Hold or resume breath without an action. Lung Furnace allows one hour; the elapsed clock never resets by switching Furnaces.',batch=False) for operation in ('hold','breathe')]


def _no_air(engine,actor):
    return any(c.condition_id=='condition:typed.qualified_body_source' and c.data.get('kind')=='breathing_exposure'
               and c.data.get('no_air')==1 for c in actor.conditions.values())


@effect('furnace_breath_control')
def breath_control(ctx,row):
    engine,actor=ctx.engine,ctx.actor
    if _count(engine,actor)<=0:return
    held=next((c for c in actor.conditions.values() if c.condition_id==BREATH),None)
    if row['operation']=='breathe':
        if _no_air(engine,actor):raise ValueError('No breathable air is available; this cannot reset the breath clock.')
        if held:engine._remove_condition_instance(actor,held.instance_id,SOURCE,expected=held)
    elif held is None:
        engine._apply_condition(actor,BREATH,SOURCE,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'held_num':0,'held_den':1,'round':engine.state.round_number,'slot':engine.state.current_slot_index,
                  'label':'Holding breath: Lung Furnace allows one hour; no speech or sound without air',
                  'rule':{'silenced':True} if _no_air(engine,actor) else {}})


@hook('turn_start',priority=-180)
def breath_clock(engine,current_actor):
    from fractions import Fraction
    from .body_modes_scene_resources import bundle_of
    slots=max(1,len(engine.state.initiative_order))
    for actor in engine.state.actors.values():
        if not circuit_profile(bundle_of(engine,actor)):continue
        held=next((c for c in actor.conditions.values() if c.condition_id==BREATH),None)
        if held is None:continue
        data=dict(held.data)
        elapsed=Fraction(((engine.state.round_number-data['round'])*slots+engine.state.current_slot_index-data['slot'])*6,slots)
        total=Fraction(data['held_num'],data['held_den'])+elapsed
        normal,buffer=_ordinary_breath_seconds(bundle_of(engine,actor))
        limit=3600 if 'lung' in active_furnaces(engine,actor) else normal
        if _no_air(engine,actor) and total>=limit+buffer and actor.current_hp>0:
            before=actor.current_hp;actor.current_hp=0
            engine._append_event('SUFFOCATION_COMMITTED',SOURCE,actor_id=actor.entity_id,
                payload={'before':before,'after':0,'log':actor.display_name+' runs out of air and falls to 0 Hit Points.'})
            engine._set_life_state(actor,'DYING',SOURCE)


@hook('journey_combat_bundle')
def bind_breath(bundle,session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(FAMILY,{})
    if 'held_num' in state:bundle['organ_furnaces_breath']={'held_num':state['held_num'],'held_den':state['held_den']}


@hook('match_start',priority=-170)
def restore_breath(engine):
    from .body_modes_scene_resources import bundle_of
    for actor in engine.state.actors.values():
        data=bundle_of(engine,actor).get('organ_furnaces_breath')
        if data is not None and circuit_profile(bundle_of(engine,actor)):
            engine._apply_condition(actor,BREATH,SOURCE,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={**data,'round':engine.state.round_number,'slot':engine.state.current_slot_index,
                      'label':'Holding breath: elapsed time retained from travel',
                      'rule':{'silenced':True} if _no_air(engine,actor) else {}})


@hook('journey_encounter_settled')
def export_breath(session,aid,engine,creature):
    from fractions import Fraction
    held=next((c for c in creature.conditions.values() if c.condition_id==BREATH),None)
    if held is None:return
    d=held.data;slots=max(1,len(engine.state.initiative_order))
    elapsed=Fraction(((engine.state.round_number-d['round'])*slots+engine.state.current_slot_index-d['slot'])*6,slots)
    total=Fraction(d['held_num'],d['held_den'])+elapsed
    state=_journey_breath_state(session,aid)
    state['held_num']=total.numerator;state['held_den']=total.denominator


@hook('journey_options')
def signs_travel_options(session,aid):
    if not _journey_names(session,aid):return
    return [{'id':'furnace_signs:'+str(value),'kind':'furnace_signs','payload':{'visible':value},
             'label':'Organ Furnaces: '+('reveal' if value else 'suppress')+' cosmetic signs; no action, resource or time cost.'} for value in (0,1)]


@hook('journey_command')
def signs_travel_change(session,aid,kind,payload):
    if kind!='furnace_signs':return
    from ..journey import require
    import json
    from .body_modes_scene_resources import AUTHORITY
    require(_journey_names(session,aid) and set(payload)=={'visible'} and type(payload['visible']) is int and payload['visible'] in (0,1),'Choose cosmetic signs for an available Organ Furnace system.')
    actor=session.state['actors'][aid]
    effects=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault('effects',[])
    condition='condition:typed.organ_furnace_signs'
    effects[:]=[r for r in effects if not (r['kind']=='condition' and json.loads(r['model']).get('condition_id')==condition)]
    effects.append({'kind':'condition','model':json.dumps({'condition_id':condition,'source_definition_id':SOURCE,'source_actor_id':aid,
        'data':{'visible':payload['visible'],'label':'Organ Furnace cosmetic signs '+('revealed' if payload['visible'] else 'suppressed')}})})
    session.emit('FURNACE_SIGNS_CHANGED',aid,visible=payload['visible'],source=SOURCE)
    return True
