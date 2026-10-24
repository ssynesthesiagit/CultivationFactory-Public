"""Exhaustion (glossary, Tianxia_PHB_Manuscript_v0_3.md: "The normal game condition for severe fatigue and strain.
Tianxia adds CP exhaustion..."; the Sphere Compendium repeats, on dozens of spheres, "Use the 2024 meanings of
Action, Bonus Action, ... Exhaustion ... unless this sphere explicitly replaces or expands a rule"). Tianxia never
redefines it, so its printed rule IS the 2024 one (SRD 5.2): a d20 Test (ability check, attack roll, saving throw) is
reduced by 2 times the Exhaustion level, Speed by 5 feet per level, and a creature dies at level 6. Before this file the
table had no Exhaustion at all (combat/rules/typed_conditions.json's Choke Hold note; combat/ext/gu_wrestling.py's Choke Hold rider both say so
explicitly), so a Forged Technique's Exhausting Drawback ("gives 1 level of Exhaustion after the technique resolves",
combat/rules/forged_techniques.json) was only a GM line -- an AI that spammed an Exhausting technique paid nothing.

Speed needs no plug-in of its own: the condition's own "speed_delta" composes through the engine's existing
_effective_speed the same way carry.py's Encumbered does. Saving throws already have a hook shaped exactly right
("save" -> {"bonus": int} merged into the DC, so a negative bonus here reads as the exhausted creature's own -N).
Attack rolls and the handful of typed ability checks (escape a grapple, a wall breach, an R6 contest) had no such
hook, so this module adds the two smallest possible ones (documented in combat/ext/__init__.py's hook list) instead
of reaching into gate2_engine.py (out of bounds for this worker) -- combat/typed_executor.py calls them generically,
exactly like it already calls "save" and "attack_mode", so it never has to import this specific plug-in.
Shared Exhaustion API used by life_riders, fate_riders, life_state and other exhaustion effects: level queries the saved integer condition; set_level eventfully replaces it, updates movement and handles level-six death; add clamps an increment through that same setter.
Shared public helpers add and level are used by wrestling to track and recover
only Exhaustion caused by Choke Hold, preserving unrelated Exhaustion."""

from __future__ import annotations

from typing import Any

from . import effect, hook
from ..typed_executor import CONDITION_PREFIX, _default_subject

CONDITION_ID = CONDITION_PREFIX + "exhaustion"
MAX_LEVEL = 6


@hook("status_description")
def exhaustion_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if row.get("condition_id") != CONDITION_ID:
        return None
    lvl = int(data.get("level") or 0)
    action = engine.action_catalog.get(row.get("source_definition_id"))
    source_actor = engine.state.actors.get(getattr(action, "owner_id", None))
    return {**({"applied_by": source_actor.display_name} if source_actor is not None else {}),
            "text": (f"Exhaustion{f' level {lvl}' if lvl else ''}: each level reduces d20 Tests (attacks, ability checks and saves) by 2 "
                     "and Speed by 5 feet. At level 6 the creature dies."
                     + (f" {int(data['scene_locked_levels'])} level cannot be prevented, transferred or removed before the scene ends."
                        if int(data.get("scene_locked_levels") or 0) else "")),
            "handling": "The table applies the penalties and defeat at level 6."}


def level(actor: Any) -> int:
    """This actor's current Exhaustion level (0 if none)."""
    for condition in actor.conditions.values():
        if condition.condition_id == CONDITION_ID:
            return int((condition.data or {}).get("level") or 0)
    return 0


def locked_level(engine: Any, actor: Any) -> int:
    """Scene-protected levels shared by mandatory recovery costs and ordinary cures."""
    if engine.state.terminal_result is not None:
        return 0
    return max((int((c.data or {}).get("scene_locked_levels") or 0)
                for c in actor.conditions.values() if c.condition_id == CONDITION_ID), default=0)


@hook("effect_removal_allowed")
def protected_exhaustion(engine: Any, holder: Any, kind: str, row: Any, source: str) -> bool | None:
    """A whole-condition cure removes ordinary levels, retaining the protected cost."""
    if kind == "condition" and row.condition_id == CONDITION_ID and locked_level(engine, holder):
        if level(holder) > locked_level(engine, holder):
            set_level(engine, holder, locked_level(engine, holder), source)
        return False
    return None


def set_level(engine: Any, actor: Any, new_level: int, source: str, *, scene_locked_levels: int = 0) -> None:
    """Replace the Exhaustion condition with a fresh one carrying the new level (never edit a condition's data in
    place, combat/ext/__init__.py's rule); -5 ft Speed per level rides in "speed_delta" the same as carry.py's
    Encumbered, so _effective_speed picks it up with no engine change. Mid-turn, the bearer's movement left this
    turn moves by the same amount at once (carry.py's own pattern for a Speed change during the actor's own turn)."""
    protected = max(0, min(MAX_LEVEL, max(locked_level(engine, actor), int(scene_locked_levels))))
    new_level = max(protected, min(MAX_LEVEL, int(new_level)))
    before = level(actor)
    if new_level == before:
        return
    speed_before = engine._effective_speed(actor)
    old_conditions = list(actor.conditions.items())
    condition_data = {"level": new_level, "speed_delta": -5 * new_level,
                      **({"scene_locked_levels": protected} if protected else {})}
    if protected:
        # Apply before replacing the old row: ordinary prevention of a later,
        # unrelated Exhaustion increase must not erase the protected cost.
        old_ids = set(actor.conditions)
        engine._apply_condition(actor, CONDITION_ID, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data=condition_data, unavoidable=bool(scene_locked_levels or new_level < before))
        if set(actor.conditions) <= old_ids:
            return
    for iid, condition in old_conditions:
        if condition.condition_id == CONDITION_ID:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": CONDITION_ID, "instance_id": iid})
    if new_level and not protected:
        engine._apply_condition(actor, CONDITION_ID, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data=condition_data)
    from ..movement_budget import speed_changed
    speed_changed(engine, actor, engine._effective_speed(actor) - speed_before, source)
    from . import run_strict
    run_strict('exhaustion_changed',engine,actor,before,new_level,source)
    if new_level >= MAX_LEVEL and actor.active:
        from .life_state import die
        die(engine,actor,'Exhaustion level six',source)
        engine._check_victory()


def add(engine: Any, actor: Any, amount: int, source: str) -> None:
    """Give ``actor`` ``amount`` more levels of Exhaustion (never below 0, never above 6); other spheres' plug-ins
    (Wrestling's Choke Hold, currently a GM-only rider) can call this once their owner wants it automated too."""
    if actor.active and amount:
        set_level(engine, actor, level(actor) + int(amount), source)


@effect("exhaustion")
def _apply_exhaustion_effect(ctx: Any, effect_row: dict[str, Any]) -> None:
    """A typed effect ``{"type": "exhaustion", "amount": 1, "applies_to": "self"}`` (a Forged Technique's Exhausting
    Drawback, combat/forged.py mechanic_for) or "target" for a talent that inflicts it directly on a hit or a failed
    save (none yet; the shape is here for whoever needs it)."""
    harmful = effect_row.get("applies_to", "self") != "self"
    for subject in _default_subject(ctx, effect_row, harmful=harmful):
        if subject is not None:
            add(ctx.engine, subject, int(effect_row.get("amount") or 1), ctx.source)


@hook("save")
def _exhaustion_save_penalty(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    lvl = level(subject)
    return {"bonus": -2 * lvl} if lvl else None


@hook("attack_bonus")
def _exhaustion_attack_penalty(ctx: Any, actor: Any) -> int | None:
    lvl = level(actor)
    return -2 * lvl if lvl else None


@hook("check_bonus")
def _exhaustion_check_penalty(ctx: Any, actor: Any) -> int | None:
    lvl = level(actor)
    return -2 * lvl if lvl else None


def journey_level(session,aid):
    return int(session.state['actors'][aid].get('exhaustion',0))


def journey_add(session,aid,amount,source):
    """Native journey counterpart: same levels, penalties and level-six death.

    No time, healing, recovery or resurrection is implied. Retained encounter
    conditions and the journey scalar are updated together for cold binding.
    """
    import json
    from ..gate2_runtime_models import ConditionInstance
    from . import run_strict
    if type(amount) is not int or type(source) is not str or not source:raise ValueError('Exhaustion requires a whole level change and actual source.')
    actor=session.state['actors'][aid]
    before=journey_level(session,aid);after=max(0,min(MAX_LEVEL,before+amount))
    if before==after:return
    actor['exhaustion']=after
    health=actor.setdefault('encounter_snapshot',{'current_hp':actor['bundle']['actor_template']['maximum_hp'],
        'maximum_hp':actor['bundle']['actor_template']['maximum_hp'],'temporary_hp':0,'active':1,'life_state':'','conditions':{}})
    health['conditions']={k:v for k,v in health['conditions'].items() if json.loads(v).get('condition_id')!=CONDITION_ID}
    if after:
        condition=ConditionInstance(instance_id='journey-exhaustion:'+str(len(session.state['events'])),condition_id=CONDITION_ID,
            source_definition_id=source,source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events']),
            expires_on='UNTIL_REMOVED',data={'level':after,'speed_delta':-5*after})
        health['conditions'][condition.instance_id]=condition.model_dump_json()
    if after>=MAX_LEVEL:
        from .life_state import DEAD
        dead=ConditionInstance(instance_id='journey-death:'+str(len(session.state['events'])),condition_id=DEAD,
            source_definition_id=source,source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events']),
            expires_on='UNTIL_REMOVED',data={'label':'Dead: Exhaustion level six'})
        health['conditions'][dead.instance_id]=dead.model_dump_json()
        health.update(current_hp=0,active=0,life_state='');actor['incapacitated']=1
        session.emit('JOURNEY_DEATH_COMMITTED',aid,source=source,cause='Exhaustion level six')
    run_strict('journey_exhaustion_changed',session,aid,before,after,source)
    session.emit('EXHAUSTION_CHANGED',aid,source=source,before=before,after=after)
    run_strict('journey_state_changed',session,aid)
