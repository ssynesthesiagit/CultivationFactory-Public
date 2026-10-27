"""Qi instability: the Qiweaving Turbulence package (system E, sys/resources-states 2026-09-29).

Owner text (authority/typed_mechanics/rules_text.json; Tianxia Sphere Compendium, Qiweaving):
  * Turbulent Field (Action, Self, 5-foot-radius Emanation, Concentration up to 1 minute; radius 5 / 10 / 15 / 20 ft at CL 1-4 /
    5-10 / 11-16 / 17-20): "If the campaign does not use a separate instability system, use the following fallback. The first time on
    a turn that a creature inside the area activates a technique that costs CP or casts a spell using a spell slot, it makes a
    Constitution saving throw. Failed Save: The technique is Turbulent until it resolves. A Turbulent technique suffers one
    complication chosen by the GM or rolled from a campaign-appropriate table, such as visible backlash, noisy activation,
    reduced range, accidental self-exposure, or minor damage to an unattended nearby object. The fallback complication should be
    inconvenient but should not normally waste the technique unless another Turbulence talent says so."
  * Turbulent Backlash (CL 10+): "When a hostile creature fails its saving throw against your Turbulent Field, you may spend 1 CP.
    The creature takes Force damage equal to your Proficiency Bonus plus your Key Ability modifier, and it has Disadvantage on the
    next Concentration saving throw it makes before the start of its next turn."
  * Quiet the Flaw: "When a willing creature inside your Turbulent Field would suffer a wild Qi or Qi-deviation complication, you
    may use your Reaction and spend 1 CP. Reduce the severity ... or allow the creature to reroll the instability result ... If the
    campaign does not use an instability table, the creature gains Advantage on the saving throw against your Turbulent Field
    instead."  (This engine has no instability table, so the fallback is the one that runs.)
  * Friend in the Storm: "Choose a number of creatures up to your Key Ability modifier, minimum 1, when you create Turbulent
    Field. Chosen creatures are not affected by your Turbulent Field unless they choose to be. As a Bonus Action, you may change
    one chosen creature while the field lasts."
  * Regulated Breathing (CL 5+, Action, 30 ft): "choose one willing creature within 30 feet whose circulation is unstable,
    turbulent, poisoned by Qi deviation, or suffering from a temporary backlash effect. The target may immediately repeat one
    saving throw against that instability or backlash, adding your Key Ability modifier to the roll. A creature can benefit from
    your Regulated Breathing once per short rest."
  * Calm the Wild Meridian (CL 15+, Action, 60 ft, 4 CP): "Make a Qiweaving Check against the instability's DC or 10 + its Pattern
    Rank. Successful Check: Suppress the instability for 1 minute. If it was caused by an ongoing effect with Pattern Rank no
    higher than your Proficiency Bonus, you may end it instead. Failed Check: The instability remains, but creatures of your
    choice inside the affected area have Advantage on saving throws against it until the start of your next turn."
    (Its check, suppression and failure Advantage run through combat/ext/end_effect.py.)
  Spheres 5e and D&D 5.5e supply the Emanation rule: an Emanation extends from its origin creature, moves with it, and does not
  include the origin unless the text says so.

Plumbing.  The Field is a zone (combat/zones.py) whose trigger runs on a moment nothing else raises, "technique": the
``technique_start`` hook below (called by typed_executor.resolve_typed for every typed activation, after its costs are paid)
fires it for each such zone the activating creature stands in, once per creature per turn (zones._run's own limit).  The trigger
is the Constitution save (DC = the Field's technique save DC); a failure puts the ``turbulent`` marker on the creature until the
end of the Field owner's next turn (so Regulated Breathing and Calm have something to act on) and logs the GM complication.
Hooks used: technique_start, technique_used (Friend in the Storm's chosen creatures when the Field is created), save (Quiet the
Flaw), after_save (Turbulent Backlash), candidate_allowed / ai_candidate_allowed (Regulated Breathing, Calm), compile_block
("qi_turbulence": kinds backlash, quiet, friend).  Effect type "regulated_breathing".

Judgment calls (the printed text leaves them to the GM or names no number):
  * The Field's owner is not affected by its own Emanation, nor is a creature marked as Friend in the Storm.
  * "Activates a technique that costs CP": an activation whose costs include Qi, Stamina or Resonance.  The engine has no spell
    slots, so "casts a spell using a spell slot" cannot occur.
  * The complication is a log line for the GM (no table is printed).  The Turbulent marker is otherwise informational.
  * Friend in the Storm's chosen creatures are the nearest allies (up to the Key Ability modifier, minimum 1) at the moment the
    Field is created; changing one with a Bonus Action is left to the GM.  The marker ends with the Field's Concentration.
  * Quiet the Flaw is used on a willing creature (an ally) before its Field save, spending the owner's Reaction and 1 CP: the
    printed fallback is Advantage on that very save.
  * Regulated Breathing repeats the save the marker remembers (its origin save) with the helper's Key Ability modifier added;
    "once per short rest" is once per creature per fight.  A creature suffering no Turbulent marker is not a legal target.
  * The built-in AI never picks Regulated Breathing or Calm (the marker only changes a GM complication); a player may.
  * Not modeled: Pattern Rank ("or 10 + its Pattern Rank", ending an ongoing effect of low Pattern Rank instead of suppressing
    it), an object, Active Qi Pattern or 20-foot area as Calm's target, Lingering Turbulence (persisting without Concentration),
    a Friend choosing to be affected, Read Current (information only).  A Turbulent marker is only suppressed, never "ended".
Determinism: the evented roller and engine methods only; state changes are logged events.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

TURBULENT = "condition:typed.turbulent"
FRIEND = "condition:typed.storm_friend"
FIELD = "TAL_QIWEAVING_TURBULENT_FIELD"
BLOCK = "qi_turbulence"
BREATHING = "TAL_QIWEAVING_REGULATED_BREATHING"
CALM = "TAL_QIWEAVING_CALM_THE_WILD_MERIDIAN"
HELPED = "_round_regulated_breathing"  # on the helper: creatures it has steadied this fight ("_round_" keys survive turn resets)


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Feature block ``qi_turbulence``: {"kind": "backlash" | "quiet" | "friend"}; each row carries the owner's numbers."""
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0)}]


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    from .. import typed_reactions

    return [row for row in typed_reactions._rows(engine, actor.entity_id, BLOCK) if row.get("kind") == kind]


def _cp_pool(actor: Any) -> str | None:
    """The CP pool with the most CP left (the one the character can best afford), None when none holds any."""
    from ..typed_executor import CP_POOLS

    pools = [pool for pool in CP_POOLS if actor.resource_maximums.get(pool, 0) > 0 and actor.resources.get(pool, 0) >= 1]
    return max(pools, key=lambda pool: actor.resources.get(pool, 0), default=None)


def _costs_cp(action: Any) -> bool:
    from ..typed_executor import CP_POOLS

    return any(resource in CP_POOLS and int(amount) > 0 for resource, amount in getattr(action, "costs", None) or ())


def _is_friend(creature: Any, owner_id: str) -> bool:
    return any(c.condition_id == FRIEND and c.source_actor_id == owner_id for c in creature.conditions.values())


def _marked(creature: Any) -> list[tuple[str, Any]]:
    return [(key, c) for key, c in creature.conditions.items() if c.condition_id == TURBULENT]


# ------------------------------------------------------------------------------------------------- the Field's save
@hook("technique_start")
def turbulent_activation(engine: Any, actor: Any, action: Any) -> bool | None:
    """A creature inside a Turbulent Field activates a technique that costs CP: the Field's Constitution save (once a turn)."""
    if not actor.active or not _costs_cp(action):
        return None
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.owner_id == actor.entity_id or not any("technique" in (t.get("on") or []) for t in zone.trigger_profile.get("triggers") or []):
            continue
        if _is_friend(actor, zone.owner_id) or not zones._inside(engine, actor, zone):
            continue
        before = {key for key, _ in _marked(actor)}
        zones._fire(engine, zone, actor, "technique")
        if any(key not in before for key, _ in _marked(actor)):
            note(engine, zone.source_definition_id, engine.state.actors[zone.owner_id],
                 f"{actor.display_name}'s {action.display_name} is Turbulent: it suffers one complication the GM chooses (visible backlash, "
                 "noisy activation, reduced range, accidental self-exposure, or minor damage to an unattended nearby object); it is not wasted.",
                 (actor,))
        if not actor.active:
            return True
    return None


@hook("technique_used")
def storm_friends(ctx: Any) -> None:
    """Friend in the Storm: when the Field is created, the owner's chosen creatures (nearest allies, up to the Key Ability modifier)."""
    if _mechanic(ctx.action) != FIELD:
        return
    owner, engine = ctx.actor, ctx.engine
    if not _rows(engine, owner, "friend"):
        return
    count = max(1, int(ctx.numbers.get("key_mod") or 0))
    allies = sorted((a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and a.entity_id != owner.entity_id),
                    key=lambda a: (engine._distance_actor_to_actor(owner, a), a.entity_id))[:count]
    for ally in allies:
        engine._apply_condition(ally, FRIEND, ctx.source, owner.entity_id, expires_on="CONCENTRATION_END",
                                data={"label": "Friend in the Storm",
                                      "reading": f"{owner.display_name}'s Turbulent Field does not affect this creature (unless it chooses to be affected). "
                                                 "Ends with the Field's Concentration."})
    if allies:
        note(engine, ctx.source, owner, f"{owner.display_name}'s Turbulent Field spares {', '.join(a.display_name for a in allies)} (Friend in the Storm).",
             tuple(allies))


@hook("save")
def quiet_the_flaw(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Quiet the Flaw: the owner's Reaction and 1 CP give a willing creature Advantage on its Turbulent Field save."""
    if "turbulent" not in (named or ()):
        return None
    owner, engine = ctx.actor, ctx.engine
    if subject.entity_id == owner.entity_id or subject.team_id != owner.team_id:
        return None
    rows = _rows(engine, owner, "quiet")
    from .. import typed_reactions

    pool = _cp_pool(owner)
    if not rows or pool is None or not typed_reactions._can_react(engine, owner):
        return None
    if not typed_reactions._consent(engine, {"feature_id": rows[0]["feature_id"], "ask": True}, owner, "TURBULENT_SAVE"):
        return None
    with activation(engine, owner, rows[0]["feature_id"]):
        typed_reactions._open(engine, {"feature_id": rows[0]["feature_id"], "block": BLOCK}, owner, (subject.entity_id,), "TURBULENT_SAVE",
                              {"protects": subject.entity_id})
        engine._spend_resource(owner, pool, 1, rows[0]["feature_id"])
        owner.reaction_available = False
        note(engine, rows[0]["feature_id"], owner, f"{owner.display_name} quiets the flaw for {subject.display_name}: Advantage on its save against the Turbulent Field.",
             (subject,))
        return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("after_save")
def turbulent_backlash(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Turbulent Backlash: a hostile creature that fails the Field's save takes PB + Key Ability modifier Force damage for 1 CP and has
    Disadvantage on its next Concentration save before the start of its next turn."""
    if not failed or "turbulent" not in (named or ()) or not subject.active:
        return
    owner, engine = ctx.actor, ctx.engine
    rows = _rows(engine, owner, "backlash")
    pool = _cp_pool(owner)
    if not rows or pool is None or subject.team_id == owner.team_id:
        return
    from .. import typed_executor, typed_reactions

    feature = rows[0]["feature_id"]
    if not typed_reactions._consent(engine, {"feature_id": feature, "ask": True}, owner, "TURBULENT_BACKLASH"):
        return
    engine._spend_resource(owner, pool, 1, feature)
    amount = max(0, int(rows[0].get("pb") or 2) + int(rows[0].get("key_mod") or 0))
    note(engine, feature, owner, f"{owner.display_name} spends 1 CP: Turbulent Backlash hits {subject.display_name} for {amount} force damage "
         "and it has Disadvantage on its next Concentration saving throw before the start of its next turn.", (subject,))
    from dataclasses import replace
    typed_executor._deal(replace(ctx, damage_pressure_kind='backlash'), subject, amount, "FORCE")
    if subject.active:
        engine._apply_condition(subject, typed_executor.CONDITION_PREFIX + "concentration_mode", feature, owner.entity_id,
                                expires_on=typed_executor.stated_expiry(ctx, {"expires_on": "START_OF_TARGET_NEXT_TURN"}, subject, condition=True),
                                data={"rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                                      "label": "Disadvantage on its next Concentration saving throw (Turbulent Backlash)"})


# ------------------------------------------------------------------------------------------------- Regulated Breathing
@effect("regulated_breathing")
def regulated_breathing(ctx: Any, eff: dict[str, Any]) -> None:
    """The target repeats its save against the Turbulent marker with the helper's Key Ability modifier added."""
    from .. import typed_executor

    engine, helper = ctx.engine, ctx.actor
    for holder in typed_executor._default_subject(ctx, eff, harmful=False):
        if holder is None or not holder.active:
            continue
        marked = _marked(holder)
        if not marked:
            ctx.rider("The target's circulation is not unstable: there is nothing to steady.")
            continue
        if holder.entity_id in (helper.turn_flags.get(HELPED) or []):
            ctx.rider("A creature can benefit from Regulated Breathing only once per short rest.")
            continue
        helper.turn_flags[HELPED] = [*(helper.turn_flags.get(HELPED) or []), holder.entity_id]
        _key, condition = marked[0]
        remembered = (condition.data or {}).get("repeat_save") or (condition.data or {}).get("origin_save") or {"ability": "CON", "dc": 10}
        bonus, dc = int(ctx.numbers.get("key_mod") or 0), int(remembered.get("dc") or 10)
        from ..support_values import offered_bonus, settled
        original = bonus
        bonus += offered_bonus(engine, helper, holder, ctx.source, 'backlash', bonus, consume=True)
        roll = engine._roll_save(holder, str(remembered.get("ability") or "CON").upper(), dc - bonus, ctx.source)
        settled(engine, helper, holder, ctx.source, 'backlash', original, bonus, int(roll.total) + bonus)
        if roll.total >= dc - bonus:
            engine._remove_condition(holder, TURBULENT, ctx.source)  # every Turbulent marker it bears
            note(engine, ctx.source, helper, f"{helper.display_name}'s Regulated Breathing steadies {holder.display_name}: it repeats its "
                 f"{str(remembered.get('ability') or 'CON').upper()} save (+{bonus}) and the instability ends.", (holder,))
        else:
            note(engine, ctx.source, helper, f"{helper.display_name}'s Regulated Breathing does not settle {holder.display_name}: its repeated "
                 f"save (+{bonus}) fails and the instability remains.", (holder,))


def _mechanic(action: Any) -> str:
    """The authority id a compiled action came from (its own id is ``action:typed.<hash>.<mechanic id>``)."""
    return str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) or "")


@hook('save_pressure_kinds')
def field_pressure_receipt(ctx: Any, subject: Any, ability: str, named: Any):
    """The same Field that actually backlashed this creature is that source.

    Merely owning Turbulent Backlash is not evidence. A native committed
    packet from the actual Field/caster/subject must establish the provenance.
    """
    if _mechanic(ctx.action) != FIELD:
        return None
    from ..pressure_facts import committed_pressure_kinds
    kinds = committed_pressure_kinds(ctx.engine, subject.entity_id,
                                    ctx.damage_source, ctx.actor.entity_id)
    return ('backlash',) if 'backlash' in kinds else None


def _has_effect(action: Any, kind: str) -> bool:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    rows = [*(typed.get("effects") or []), *(e for option in typed.get("options") or [] for e in option.get("effects") or [])]
    return any(isinstance(row, dict) and row.get("type") == kind for row in rows)


@hook("candidate_allowed")
def steadied_only_when_unstable(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not _has_effect(action, "regulated_breathing"):
        return None
    helped = actor.turn_flags.get(HELPED) or []
    for target_id in candidate.target_ids or ():
        holder = engine.state.actors.get(target_id)
        if holder is not None and holder.active and _marked(holder) and holder.entity_id not in helped:
            return None
    return False


@hook("ai_candidate_allowed")
def ai_leaves_the_marker_alone(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The Turbulent marker only stands for a GM complication: the built-in AI does not spend an Action on it."""
    if _has_effect(action, "regulated_breathing") or _mechanic(action) == CALM:
        return False
    return None
