"""A creature that cannot benefit from its Shield AC, or from cover, against some attacks (rider lane 3, 2026-09-29).

  break_guard  {"applies_to": "target", "shield": true, "cover": false, "next": true, "axe": true, "by": "source" | "anyone",
                "duration": "until_end_of_turn"}

"Until the end of your current turn, the target cannot benefit from Shield AC against the next axe attack you make against it" (Hewing Strike:
Split Guard; Shield-Catching Beard); "Until the start of your next turn, the target cannot benefit from Shield AC against your attacks"
(Shield-Catching Beard, failed save); "loses the benefit of Shield AC, Half Cover, or Three-Quarters Cover against the next attack made against
it before the start of your next turn" (Split the Shield Wall, ``by: "anyone"``).

The row puts ``condition:typed.guard_broken`` on the creature; its data says what is lost (``shield``, ``cover``), for how many attacks
(``next``: the first one it covers uses it up, hit or miss; otherwise every one until the condition ends), whose attacks (``by``: the creature that
put it on -- the default -- or anyone) and whether only an axe's (``axe``: the delivering item's weapon family is Axe).

The engine has no armour parts: a creature's Armor Class is one number.  A carried shield is a fact the compiler records as a passive row
(combat/factory_compiler.py, block "shield_ac", +2: the Shield's own bonus, ``_armor_class``); this plug-in takes that +2 off through the ``ac`` hook
for the attack in hand.  The hook is given only the target, so ``before_attack`` (called for every attack, before its d20) says who is attacking it
and with what.  Cover is the engine's own figure for a ranged attack (``_cover_bonus_actor_to_actor``); it is cancelled the same way.  A creature
with no shield row (a monster with a stat block, a fighter carrying none) loses nothing to the ``shield`` half.
"""
from typing import Any

from . import effect, hook, run_strict

CONDITION = "condition:typed.guard_broken"
CURRENT = "_guard_attack"


@effect("break_guard")
def break_guard(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    parts = " and ".join(name for name, on in (("Shield AC", row.get("shield", True)), ("cover", row.get("cover"))) if on)
    for subject in _default_subject(ctx, row, harmful=True):
        if subject.active:
            profile = dict(row)
            for update in run_strict("guard_break_profile", ctx, subject, dict(profile)):
                if update is not None:
                    profile.update(update)
            beneficiary = ctx.engine.state.actors.get(str(profile.get("beneficiary_id") or ""))
            ctx.engine._apply_condition(
                subject, CONDITION, ctx.source, ctx.actor.entity_id,
                expires_on=profile.get("expires_on") or effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                data={"shield": bool(profile.get("shield", True)), "cover": bool(profile.get("cover")), "next": bool(profile.get("next")),
                      "axe": bool(profile.get("axe")), "by": profile.get("by") or "source",
                      **({"beneficiary_id": beneficiary.entity_id} if beneficiary else {}),
                      "label": profile.get("label") or f"Loses {parts} against {'the next ' if profile.get('next') else ''}{'axe ' if profile.get('axe') else ''}attack"
                               f"{'s' if not profile.get('next') else ''}{' by ' + ctx.actor.display_name if (profile.get('by') or 'source') == 'source' else ''}"})


def _applies(held: Any, attack: dict[str, Any]) -> bool:
    data = held.data or {}
    if held.condition_id != CONDITION:
        return False
    if data.get("beneficiary_id"):
        return data["beneficiary_id"] == attack["attacker"] and not (data.get("axe") and not attack["axe"])
    if (data.get("by") or "source") == "source" and held.source_actor_id != attack["attacker"]:
        return False
    return not (data.get("axe") and not attack["axe"])


@hook("before_attack")
def note_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> None:
    from ..typed_executor import Context
    from .weapon_hits import weapon_has_family

    action = engine.action_catalog.get(str(context.get("source_id") or ""))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    engine.__dict__[CURRENT] = {"attacker": attacker.entity_id, "target": defender.entity_id, "ranged": typed.get("range_ft") is not None,
                                "axe": action is not None and any(c.condition_id == CONDITION and (c.data or {}).get('axe')
                                    for c in defender.conditions.values()) and weapon_has_family(
                                        Context(engine, attacker, action, intent, typed, [defender]), 'axe')}
    return None


@hook("ac")
def armor_class(engine: Any, target: Any) -> int | None:
    attack = engine.__dict__.get(CURRENT)
    if not attack or attack["target"] != target.entity_id:
        return None
    from .. import armour

    total = 0
    lost_shield = lost_cover = False
    for held in target.conditions.values():
        if not _applies(held, attack):
            continue
        if (held.data or {}).get("shield") and not lost_shield:
            lost_shield = True
            # Only the Shield Bonus the fighter is still earning: a shield already dropped or broken has been taken
            # off by combat/ext/shield_possession.py, and taking it twice would be a second -2.
            total -= armour.shield_bonus_earning(engine, target)
        if (held.data or {}).get("cover") and attack["ranged"] and not lost_cover:
            lost_cover = True
            attacker = engine.state.actors.get(attack["attacker"])
            if attacker is not None:
                total -= int(engine._cover_bonus_actor_to_actor(attacker, target) or 0)
    return total or None


@hook("event")
def spend(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    attack = engine.__dict__.pop(CURRENT, None)
    target = engine.state.actors.get(attack["target"]) if attack else None
    if target is None:
        return
    for instance_id, held in list(target.conditions.items()):
        if held.condition_id == CONDITION and (held.data or {}).get("next") and _applies(held, attack):
            # Only that instance: another creature's "next attack" break on the same target is a different one, and _remove_condition
            # takes every instance of the condition id.
            del target.conditions[instance_id]
            engine._append_event("CONDITION_REMOVED", "system:guard_broken.consumed", actor_id=held.source_actor_id,
                                 target_ids=(target.entity_id,), payload={"condition_id": CONDITION, "instance_id": instance_id})
