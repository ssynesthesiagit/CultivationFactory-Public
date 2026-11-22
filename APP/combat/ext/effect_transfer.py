"""Moving an ongoing effect from one creature to another (system G, sys/resources-states 2026-09-29).

Owner text (authority/typed_mechanics/rules_text.json):
  * Steal Ongoing Technique (Scoundrel, Empty-Sleeve, CL 15+; Action, expend Martial Focus, "once per long rest per creature"):
    "Choose one creature benefiting from a non-Secret ongoing magical, martial, or supernatural effect. Make a Scoundrel Check
    against the creature's Cultivation Save DC. A stronger protected effect may instead require an opposed Cultivation Check.
    Success: Transfer one eligible beneficial effect from the target to yourself for up to 1 minute. the target ceases benefiting
    while the effect is stolen; time spent stolen counts against the effect's duration; take over Concentration when applicable;
    if the effect ends while stolen, it does not return; if it remains active when this theft ends, it returns to the original
    creature for its remaining duration; you must be a legal recipient of the effect. You may maintain only one stolen ongoing
    technique at a time. ... does not steal curses, harmful effects, a Path, a Realm, an inherent body, artifact attunement, a
    Legendary transformation, or a Secret Inheritance."
  * The Heartbinder's Bear It With Me (Borrowed Courage): "Transfer one ordinary Frightened, Charmed, grief, despair, or
    emotional-wound expression from the target to yourself for 1 minute. You are affected as though you were the original target,
    using the original source's DC and Source CL. At the end of each of your turns, you may repeat any save normally allowed. If
    you are immune, the effect is not erased; it remains suppressed on the original creature until the end of your next turn,
    then returns unless lawfully removed."

Effect type "transfer_effect" (an ability's typed effect):
  {"type": "transfer_effect", "applies_to": "target" | "ally",
   "mode": "steal" | "bear",
   "conditions": ["frightened", "charmed"], "categories": [...], "select": "beneficial" | "hostile",   # what may be moved (end_effect.py)
   "rounds": 10,            # "1 minute"
   "returns": true}         # what is still there at the end goes back to where it came from (Steal); Bear It With Me's ends
"steal" rolls the Scoundrel Check (Sleight of Hand, the modifier tabik_scoundrel.py uses) against the target's own Cultivation
Save DC (the best save DC of its techniques; 8 + its Proficiency Bonus if it has none); a failure moves nothing.  "bear" needs no
roll; if the user is immune to the condition it is suppressed on the original until the end of the user's next turn instead
(end_effect.suppress).
The effect keeps its own source, duration token and data (a condition's repeat_save, so the engine rolls the save again at the end
of the new bearer's turns with the original DC), so time stolen counts against its duration and an effect that ends while stolen
is simply gone.  The choice among several eligible effects is the strongest kind first (AC, resistance, immunity, Speed, then
conditions), oldest first.

Not modeled (GM riders): taking over Concentration -- a Concentration-bound effect stays bound to its caster's Concentration; a
"legal recipient" test beyond the thief being able to bear it; opposed Cultivation Checks for "stronger protected effects";
"non-Secret", "not a Path/Realm/inherent body/artifact/Legendary transformation" (nothing typed as one of these is a condition
or modifier here, so none can be picked); grief, despair and emotional-wound expressions of the Bear It With Me text that are not
typed as Frightened / Charmed / Captivated.  "Once per long rest per creature" is per creature per fight (flag below).

Hook use: candidate_allowed (a steal / bear ability is offered only against something it can move, and a thief holding one
already may not take another); turn_end (the theft ends at the end of the thief's 10th turn: what is still there goes back or
ends).  Determinism: the evented roller and events only; state moves are logged CONDITION / MODIFIER events.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note
from .end_effect import BENEFIT_FIELDS, found, name, cultivation_dc, suppress

FLAG = "_round_moved_effects"  # on the bearer: rows {"kind","key","from","turn","returns"}; "_round_" keys survive turn resets
STOLEN_FROM = "_round_stolen_from"  # on the thief: creatures it has stolen from this fight ("once per long rest per creature")


def _rows(actor: Any) -> list[dict[str, Any]]:
    return list(actor.turn_flags.get(FLAG) or [])


def _live(actor: Any) -> list[dict[str, Any]]:
    """The effects this creature still holds that it took from another."""
    return [row for row in _rows(actor) if (actor.conditions if row["kind"] == "condition" else actor.modifiers).get(row["key"]) is not None]


def _move(engine: Any, source: str, actor: Any, frm: Any, to: Any, kind: str, key: str, item: Any, reason: str) -> str:
    """Take ``item`` off ``frm`` and put a copy on ``to``, both logged; the copy's key is returned."""
    from .effect_durations import transfer_expiry_clock
    if kind == "condition":
        del frm.conditions[key]
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(frm.entity_id,),
                             payload={"condition_id": item.condition_id, "instance_id": key, "reason": reason})
        new = f"condition-instance:{item.condition_id}:{to.entity_id}:{engine.state.event_sequence + 1}"
        to.conditions[new] = item.model_copy(update={"instance_id": new, "target_id": to.entity_id, "data": copy.deepcopy(item.data)})
        transfer_expiry_clock(frm, item, to, to.conditions[new])
        engine._append_event("CONDITION_APPLIED", source, actor_id=actor.entity_id, target_ids=(to.entity_id,),
                             payload={"condition_id": item.condition_id, "instance_id": new, "expires_on": item.expires_on, "moved_from": frm.entity_id})
        return new
    del frm.modifiers[key]
    engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(frm.entity_id,), payload={"modifier_id": key, "reason": reason})
    new = f"modifier:{item.source_definition_id}:{to.entity_id}:{engine.state.event_sequence + 1}"
    to.modifiers[new] = item.model_copy(update={"modifier_id": new, "target_id": to.entity_id})
    transfer_expiry_clock(frm, item, to, to.modifiers[new])
    engine._append_event("MODIFIER_APPLIED", source, actor_id=actor.entity_id, target_ids=(to.entity_id,),
                         payload={"modifier_id": new, "target_field": item.target_field, "operation": item.operation, "value": item.value,
                                  "expires_on": item.expires_on, "moved_from": frm.entity_id})
    return new


def _strongest(found: list[tuple[str, str, Any]]) -> tuple[str, str, Any]:
    rank = {name: index for index, name in enumerate(BENEFIT_FIELDS)}
    return min(found, key=lambda row: (0 if row[0] == "modifier" else 1, rank.get(getattr(row[2], "target_field", ""), 99)))


def _scoundrel_check(ctx: Any, target: Any) -> bool:
    from . import floored
    from .tabik_scoundrel import modifier, skill

    actor, engine = ctx.actor, ctx.engine
    bonus = max(skill(engine, actor, "Sleight of Hand", 0), modifier(actor.dexterity_score) + int(actor.proficiency_bonus))
    dc = cultivation_dc(engine, target)
    roll = engine.roll_check(
        modifier=bonus,
        actor_id=actor.entity_id,
        reason=f'CHECK:{ctx.source}:SLEIGHT_OF_HAND',
        ability='DEX',
        skill='Sleight of Hand',
        against_creature=target,
    )
    engine._record_roll(roll)
    roll = floored(engine, actor, roll, dc)
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": "Scoundrel Check",
                                  "against": "Cultivation Save DC"})
    return success


def _row_select(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "select": row.get("select") or ("beneficial" if (row.get("mode") or "steal") == "steal" else "hostile")}


@effect("transfer_effect")
def transfer_effect(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    engine, actor = ctx.engine, ctx.actor
    mode = str(eff.get("mode") or "steal")
    for holder in typed_executor._default_subject(ctx, eff, harmful=False):
        if holder is None or not holder.active or holder.entity_id == actor.entity_id:
            continue
        eligible = found(engine, holder, _row_select(eff))
        if not eligible:
            ctx.rider("There is no such effect on the target to take.")
            continue
        if mode == "steal":
            if _live(actor):
                ctx.rider("A stolen technique is already held: only one at a time.")
                return
            actor.turn_flags[STOLEN_FROM] = [*(actor.turn_flags.get(STOLEN_FROM) or []), holder.entity_id]
            if not _scoundrel_check(ctx, holder):
                note(engine, ctx.source, actor, f"{actor.display_name}'s Scoundrel Check fails to lift anything from {holder.display_name}.", (holder,))
                return
            kind, key, item = _strongest(eligible)
        else:
            kind, key, item = eligible[0]
            if not eff.get("choose_instance") and kind == "condition" and typed_executor.condition_immune(engine, actor, name(item, kind).replace(" ", "_")):
                suppress(holder, kind, key, item, engine=engine, rounds=1, by=actor)
                note(engine, ctx.source, actor, f"{actor.display_name} is immune to {name(item, kind)}: it stays suppressed on {holder.display_name} "
                     f"until the end of {actor.display_name}'s next turn, then returns.", (holder,))
                return
        if eff.get("choose_instance"):
            from . import needle
            from .end_effect import describe
            selected = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TRANSFER_EFFECT", holder.entity_id), actor,
                "choice:needle.transfer_effect.instance", [key for kind, key, item in eligible],
                labels={key: describe(engine, kind, item) for kind, key, item in eligible},
                preferred=[key], prompt=f"{ctx.action.display_name}: which effect on {holder.display_name} will you bear?",
                name=ctx.action.display_name, target_id=holder.entity_id)
            if not selected:
                continue
            kind, key, item = next(row for row in eligible if row[1] == selected[0])
            if mode == "bear" and kind == "condition" and typed_executor.condition_immune(engine, actor, name(item, kind).replace(" ", "_")):
                suppress(holder, kind, key, item, engine=engine, rounds=1, by=actor)
                note(engine, ctx.source, actor, f"{actor.display_name} is immune to {name(item, kind)}: it stays suppressed on {holder.display_name} "
                     f"until the end of {actor.display_name}'s next turn, then returns.", (holder,))
                return
        label = name(item, kind)
        new = _move(engine, ctx.source, actor, holder, actor, kind, key, item, "STOLEN" if mode == "steal" else "BORNE")
        actor.turn_flags[FLAG] = [*_rows(actor), {"kind": kind, "key": new, "from": holder.entity_id,
                                                  "turn": int(actor.turns_started) + int(eff.get("rounds") or 10), "returns": bool(eff.get("returns"))}]
        note(engine, ctx.source, actor, f"{actor.display_name} {'takes' if mode == 'steal' else 'bears'} {holder.display_name}'s {label}"
             + (" for up to 1 minute." if mode == "steal" else " for 1 minute."), (holder,))
        if getattr(item, "expires_on", None) == "CONCENTRATION_END":
            ctx.rider(f"The {label} is still bound to its caster's Concentration; taking over the Concentration is not automated.")


@hook("candidate_allowed")
def offered_only_when_something_can_move(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    rows = [row for row in [*(typed.get("effects") or []), *(e for option in typed.get("options") or [] for e in option.get("effects") or [])]
            if isinstance(row, dict) and row.get("type") == "transfer_effect"]
    if not rows:
        return None
    holders = [engine.state.actors[t] for t in candidate.target_ids or () if t in engine.state.actors and t != actor.entity_id]
    if not holders:
        return False
    for holder in holders:
        for row in rows:
            steals = (row.get("mode") or "steal") == "steal"
            if steals and (_live(actor) or holder.entity_id in (actor.turn_flags.get(STOLEN_FROM) or [])):
                continue
            if found(engine, holder, _row_select(row)):
                return None
    return False


@hook("turn_end")
def held_effects_go_back(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    rows = _rows(actor)
    if not rows:
        return
    later = []
    for row in rows:
        if not custom_turn_due(actor, row["turn"], actor.turn_flags, "transfer:" + row["key"], nominal=nominal):
            later.append(row)
            continue
        store = actor.conditions if row["kind"] == "condition" else actor.modifiers
        item = store.get(row["key"])
        if item is None:
            continue  # it ended while held: it does not return
        origin = engine.state.actors.get(row["from"])
        if row.get("returns") and origin is not None and origin.active:
            _move(engine, "system:effect_transfer", actor, actor, origin, row["kind"], row["key"], item, "RETURNED")
            note(engine, "system:effect_transfer", actor, f"{name(item, row['kind']).capitalize()} goes back to {origin.display_name}.", (origin,))
        else:
            del store[row["key"]]
            engine._append_event("CONDITION_REMOVED" if row["kind"] == "condition" else "MODIFIER_REMOVED", "system:effect_transfer",
                                 actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={("instance_id" if row["kind"] == "condition" else "modifier_id"): row["key"], "reason": "ENDED"})
            note(engine, "system:effect_transfer", actor, f"The borne {name(item, row['kind'])} ends on {actor.display_name}.", (actor,))
    actor.turn_flags[FLAG] = later


@hook("nominal_slot_boundary")
def nominal_transfer(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        held_effects_go_back(engine, actor, nominal=True)
