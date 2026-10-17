"""Exorcist (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Exorcist: CL3 Ghost Sight and Name the Intruder, CL6 Banishment Strike, CL10
Purification Bell, CL14 Seal of Binding, CL18 Grand Exorcism). No Spheres 5e or D&D 5.5e counterpart.

Purification Bell and Seal of Binding use explicit persisted creature labels for their printed target categories.
The Bell still asks which eligible creatures to affect. Unlabelled creatures do not qualify.
Grand Exorcism's kind-specific results (forced out of a Host, banished, expelled) remain the GM's.

What runs:
  * Purification Bell (Action, 5 Resonance, 30-foot emanation): the hostile creatures you choose in it (asked; the AI chooses every
    hostile creature there) make a Wisdom save -- failed: 6d8 Radiant or Psychic (the better-landing one), Resonance Marked, Frightened
    of you until the end of your next turn; success: half and no Reactions until the start of its next turn. Resonant Exposure: an
    Invisible creature it damages cannot benefit from being Invisible, against anyone, until the end of your next turn. Each ally in
    the area may instead receive one purification benefit (asked): end one Frightened or Charmed, or remove one mark a hostile
    creature placed on it.
  * Seal of Binding (Action, 30 feet, 6 Resonance, the scene): the target makes a Charisma save. Failed: a Binding Seal Anchor object
    appears within 5 feet of it (AC your Cultivation Save DC, 5 x PB Hit Points, immune to Poison and Psychic; anyone can attack it
    with "Attack an object"); while it stands the target is Restrained, and it repeats the save at the end of each of its turns --
    three successes in all destroy the Anchor. Destroying the Anchor ends the binding. Success: Restrained until the start of your
    next turn and Resonance Marked.
  * Grand Exorcism (Action, 10 Resonance, 60-foot emanation): the hostile creatures you choose make a Charisma save -- failed: 10d10
    Radiant or Psychic; success: half, Resonance Marked and your chosen Spiritual Pressure. Allied Purification: each ally in the area
    may end one Frightened or Charmed (asked).
  * Name the Intruder keeps its button (Bonus Action, 1 Resonance, 60 feet); what it reveals and whether the mark lands depend on what
    the creature is (the GM's). Ghost Sight and Banishment Strike are the GM's for the same reason.

Plug-in surface: effects exorcist_rite, exorcist_seal; hooks turn_end, event. Shared helpers used: spirit_traditions (context/numbers/
save/remove), needle.ask, typed_executor (run_effects/block_condition/MARK_PREFIX), exposed (the "exposed" effect row).
"""

from __future__ import annotations

from .map_positions import offset_positions

import copy
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.exorcist.feature."
BELL = TRADITION + "purification_bell"
SEAL = TRADITION + "seal_of_binding"
GRAND = TRADITION + "grand_exorcism"
SEAL_STATE = "condition:typed.binding_seal"
ANCHOR = "object:typed.binding_seal:"
INVISIBLE = "condition:typed.invisible"
CALM = ("frightened", "charmed")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


# ------------------------------------------------------------------------------------------------ Purification Bell, Grand Exorcism
@effect("exorcist_rite")
def rite(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    radius = int(row.get("radius_ft") or 30)
    name = str(row.get("name") or "Exorcism")
    near = [c for c in engine.state.actors.values() if c.active and c is not actor and engine._distance_actor_to_actor(actor, c) <= radius]
    from .creature_kinds import matches
    hostiles = [c for c in near if c.team_id != actor.team_id
                and (not row.get("target_kinds") or matches(c, row["target_kinds"]))]
    if hostiles:
        ids = [c.entity_id for c in hostiles]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, f"{name.upper().replace(' ', '_')}_TARGETS", actor.entity_id), actor,
                            f"choice:needle.exorcist.{row.get('topic') or 'rite'}_targets", ids, labels={c.entity_id: c.display_name for c in hostiles},
                            preferred=ids, minimum=0, maximum=len(ids), default="all", allow_decline=True, name=name, feature_id=ctx.source,
                            prompt=(f"{name}: choose hostile creatures in the area to make the saving throw."
                                    if row.get("target_kinds") else f"{name}: which hostile creatures in the area does it answer? "
                                    "The GM confirms their spiritual kind."))
        for subject in [c for c in hostiles if c.entity_id in chosen]:
            if not subject.active:
                continue
            before = len(engine.events)
            sub = st.context(engine, actor, ctx.action, [subject], ctx.numbers, ctx.intent)
            _te().run_effects(sub, [copy.deepcopy(row["save"])])
            if row.get("exposure") and subject.active and any(c.condition_id == INVISIBLE for c in subject.conditions.values()) and any(
                    e.event_type == "DAMAGE_COMMITTED" and subject.entity_id in e.target_ids for e in engine.events[before:]):
                _te().run_effects(sub, [{"type": "exposed", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                         "benefits": "invisible", "against": "anyone",
                                         "evidence": "Resonant Exposure: it becomes visible as a spiritual outline until the end of your next turn"}])
    for ally in [c for c in near if c.team_id == actor.team_id]:
        _purify(engine, actor, ally, ctx.intent, name, marks=bool(row.get("remove_marks")))


def _purify(engine: Any, actor: Any, ally: Any, intent: Any, name: str, *, marks: bool) -> None:
    """One purification benefit for a willing ally in the area: end one Frightened or Charmed, or (the Bell) remove one mark a hostile
    creature placed on it."""
    from . import needle

    options: dict[str, tuple[str, Any]] = {}
    for iid, condition in sorted(ally.conditions.items()):
        if _name(condition) in CALM:
            options[f"end:{iid}"] = (f"End {_name(condition).title()} on {ally.display_name}", condition)
        elif marks and condition.condition_id.startswith(_te().MARK_PREFIX):
            source = engine.state.actors.get(condition.source_actor_id or "")
            if source is not None and source.team_id != ally.team_id:
                label = condition.condition_id[len(_te().MARK_PREFIX):].rsplit(".", 1)[0].split(".")[0].replace("_", " ").title()
                options[f"mark:{iid}"] = (f"Remove {source.display_name}'s {label} Mark from {ally.display_name}", condition)
    if not options:
        return
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "PURIFY", ally.entity_id), actor, "choice:needle.exorcist.purify", list(options),
                        labels={k: v[0] for k, v in options.items()}, preferred=list(options)[:1], allow_decline=True, name=name,
                        feature_id=BELL if marks else GRAND, target_id=ally.entity_id,
                        prompt=f"{name}: one purification benefit for {ally.display_name}?")
    if chosen and chosen[0] in options:
        st.remove(engine, ally, options[chosen[0]][1], "PURIFIED")
        note(engine, BELL if marks else GRAND, actor, f"{name}: {options[chosen[0]][0]}.", (ally,))


# ---------------------------------------------------------------------------------------------------------- Seal of Binding
def _anchor_square(engine: Any, target: Any) -> Any:
    from ..gate2_runtime_models import Position

    occupied = set(engine._occupied_cells_except(target.entity_id)) | set(engine._actor_cells(target))
    taken = {(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed}
    squares = list(offset_positions(engine, target.position, ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)))
    free = [p for p in squares if engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked and (p.x, p.y) not in occupied
            and (p.x, p.y) not in taken]
    return free[0] if free else target.position  # "or attach it visibly to the Host"


@effect("exorcist_seal")
def seal(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    failed = st.save(ctx, target, "cha", on_success=[
        {"type": "condition", "applies_to": "target", "condition": "restrained", "duration": {"kind": "until_start_of_your_next_turn"},
         "evidence": "The target is Restrained until the start of your next turn"},
        {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
         "evidence": "becomes Resonance Marked by you"}])
    if not failed or not target.active:
        return
    numbers = ctx.numbers or st.numbers(engine, actor)
    hp = 5 * int(numbers.get("pb") or 2)
    obj = RuntimeObjectState(object_id=f"{ANCHOR}{actor.entity_id}:{target.entity_id}:{engine.state.event_sequence}", object_kind="BINDING_SEAL_ANCHOR",
                             position=_anchor_square(engine, target), unattended=True, flammable=False, owner_id=actor.entity_id,
                             ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
                             component={"seal_target": target.entity_id, "label": "Binding Seal Anchor"})
    engine._update_object(obj, ctx.source, actor.entity_id)
    before = set(target.conditions)
    _te().block_condition(st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent),
                          {"type": "condition", "applies_to": "target", "condition": "restrained", "expires_on": "UNTIL_REMOVED",
                           "evidence": "While the Anchor remains: the target is Restrained"})
    restrained = [iid for iid in target.conditions if iid not in before]
    engine._apply_condition(target, SEAL_STATE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"anchor": obj.object_id, "restrained": restrained, "successes": 0,
                                  "label": "Binding Seal: Restrained while the Anchor stands; three successful repeat Charisma saves destroy it"})
    note(engine, SEAL, actor, f"A Binding Seal Anchor binds {target.display_name} (AC {obj.ac}, {hp} Hit Points).", (target,))


def _release(engine: Any, holder: Any, state: Any, reason: str, *, destroy: bool) -> None:
    anchor = engine.state.objects.get(str((state.data or {}).get("anchor") or ""))
    for iid in (state.data or {}).get("restrained") or []:
        condition = holder.conditions.get(iid)
        if condition is not None:
            st.remove(engine, holder, condition, reason)
    st.remove(engine, holder, state, reason)
    if destroy and anchor is not None and not anchor.destroyed:
        engine._update_object(anchor.model_copy(update={"destroyed": True, "current_hp": 0}), SEAL, state.source_actor_id)


def _seals(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == SEAL_STATE]


@hook("turn_end")
def repeat_save(engine: Any, actor: Any) -> None:
    """Printed: "The target repeats the Charisma saving throw at the end of each of its turns. Three total successful repeat saves
    destroy the Anchor and end the effect."."""
    for state in _seals(actor):
        owner = engine.state.actors.get(state.source_actor_id or "")
        if owner is None or not actor.active:
            continue
        ctx = st.context(engine, owner, st.feature_action(engine, owner, SEAL), [actor], st.numbers(engine, owner))
        if st.save(ctx, actor, "cha"):
            continue
        successes = int(st.data_of(actor, state).get("successes") or 0) + 1
        st.set_data(actor, state, successes=successes)
        if successes >= 3:
            _release(engine, actor, state, "THREE_SUCCESSES", destroy=True)
            note(engine, SEAL, owner, f"{actor.display_name} breaks the Binding Seal (third successful save).")


@hook("event")
def anchor_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Printed: "Destroying it ends the binding but does not harm the target."."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(ANCHOR) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    holder = engine.state.actors.get(str((obj.get("component") or {}).get("seal_target") or ""))
    if holder is None:
        return
    for state in _seals(holder):
        if (state.data or {}).get("anchor") == obj.get("object_id"):
            _release(engine, holder, state, "ANCHOR_DESTROYED", destroy=False)
