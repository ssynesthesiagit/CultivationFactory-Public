"""Barrage Blitz talents that change the Bonus Action attack, and Vigilant Sharpshooter (rider lane C10, 2026-09-30).

Owner text (authority/typed_mechanics/rules_text.json):
  Mixed Barrage (Blitz) -- "Replace the Bonus Action ranged attack from your Barrage with one: melee weapon attack; unarmed strike;
    Shove attempt."
  Spinning Shot (Blitz) -- "Expend Martial Focus. Make two Bonus Action attacks instead of one. Every attack in the Barrage must
    target a different creature."
  Vigilant Sharpshooter -- "While holding Martial Focus, make Opportunity Attacks with a ranged weapon you wield. Treat the weapon as
    though it had Reach for this purpose. You still require ammunition or a throwable weapon."

How it runs (the Barrage itself is combat/ext/docket_maneuvers.py: "Barrage: <weapon>" opens "Barrage follow-up: <weapon>";
combat/ext/barrage_hits.py counts the Barrage's hits for the other Blitz talents)
  * "apply only one Blitz talent to one Barrage": each of these is its own primary, "Barrage: <weapon> + Mixed Barrage" /
    "+ Spinning Shot" (Spinning Shot costs Martial Focus). It opens its own Bonus Action instead of the ordinary follow-up, so the
    Blitz chosen with the primary is the Barrage's one Blitz. Both are the same Barrage to barrage_hits (maneuver "barrage" /
    "barrage_follow_up" of the same weapon), so Blitz Focus, Blowback Barrage, Cascading Barrage and Court of Falling Stars count
    their hits.
  * Mixed Barrage's Bonus Action is one of: an attack with each melee weapon the character has, an Unarmed Strike (2024: 1 +
    Strength modifier), or a Shove (push 5 feet or Prone, the 2024 save) -- once, that turn, after the Mixed primary.
  * Spinning Shot's Bonus Action is "Spinning Shot: <weapon>": one attack at a creature the primary did not target, then the player
    chooses another creature (within the weapon's range, in sight) for the second attack. Extra Attack primaries also choose distinct creatures. Nobody left to choose: no second attack.
  * The Bonus Action attacks keep the Barrage follow-up's rule "does not add a positive ability modifier to damage" (they are the
    Barrage's Bonus Action attacks).
  * Vigilant Sharpshooter stays a printed rider: the pure opportunity hook has no weapon-choice transport.
Readings: the Unarmed Strike's Strength modifier is read from the compiled Shove option (its save DC is 8 + Strength + Proficiency
Bonus, factory_compiler._unarmed_options); the Mixed Barrage Shove is a single Shove (not the Attack action's other attacks).
"""

from __future__ import annotations

import copy
import json
from typing import Any

from . import effect, hook
from .barrage_common import follow_up, one_attack

SPHERE = "tianxia.sphere.barrage"
MIXED = "TAL_BARRAGE_MIXED_BARRAGE"
SPINNING = "TAL_BARRAGE_SPINNING_SHOT"
FOCUS = "resource:core.martial_focus"
BLOCK = "barrage_blitz"
SPIN_TARGET = "barrage_spin_target:"  # + weapon id -> the creature the Spinning Shot primary aimed at (turn flag)


def _short(name: str) -> str:
    return name[:-len(" attack")] if name.endswith(" attack") else name


def _primary(row: Any, typed: dict[str, Any], owned: list[str], talent: str, label: str, flag: str, costs: tuple[Any, ...]) -> Any:
    new_typed = copy.deepcopy(typed)
    new_typed.update(maneuver="barrage", maneuver_of=row.source_definition_id, opens=[flag],
                     barrage_owned=[mid for mid in owned if mid.startswith("TAL_BARRAGE_")],
                     modifier={"id": talent, "name": label, "precondition": ""})
    return row.model_copy(update={
        "source_definition_id": f"{row.source_definition_id}.barrage+{talent}", "display_name": f"Barrage: {_short(row.display_name)} + {label}",
        "costs": tuple(row.costs) + costs,
        "parameters": {**{k: v for k, v in row.parameters.items() if k != "typed"}, "typed": new_typed, BLOCK: talent}})


def _bonus(base: Any, typed: dict[str, Any], weapon_id: str, flag: str, owned: list[str], action_id: str, name: str,
           description: str, **extra: Any) -> Any:
    return follow_up(base, typed, weapon_id, flag, owned, action_id, name, description, **extra).model_copy(update={"costs": ()})


@hook("maneuvers")
def blitz_actions(info: dict[str, Any]) -> dict[str, Any] | None:
    from .weapon_actions import weapon_attacks

    owned = list(dict.fromkeys(info.get("owned") or []))
    if SPHERE not in set(info.get("spheres") or ()) or not {MIXED, SPINNING} & set(owned):
        return None
    actor_id = info["actor_id"]
    weapons = weapon_attacks(info["actions"], actor_id)
    ranged = [(row, typed) for row, typed, _attack, kind in weapons if kind in ("ranged", "thrown")]
    melee = [(row, typed) for row, typed, _attack, kind in weapons if kind == "melee"]
    shoves = [row for row in info["actions"] if row.owner_id == actor_id
              and ((row.parameters or {}).get("typed") or {}).get("unarmed_option") in ("shove_push", "shove_prone")]
    out = []
    for row, typed in ranged:
        weapon_id, name = row.source_definition_id, _short(row.display_name)
        if MIXED in owned:
            flag = f"barrage_mixed:{weapon_id}"
            out.append(_primary(row, typed, owned, MIXED, "Mixed Barrage", flag, ()))
            rule = "It adds no positive ability modifier to damage (the Barrage's Bonus Action attack)."
            for other, other_typed in melee:
                other_name = _short(other.display_name)
                out.append(_bonus(other, other_typed, weapon_id, flag, owned,
                                  f"{weapon_id}.barrage_mixed.{other.source_definition_id.rsplit('.', 1)[-1]}",
                                  f"Mixed Barrage: {other_name} attack",
                                  f"After Barrage: {name} + Mixed Barrage, spend your Bonus Action on one {other_name} attack. {rule}"))
            if shoves:
                numbers = dict(((shoves[0].parameters or {}).get("typed") or {}).get("numbers") or info["numbers"])
                pb = int(numbers.get("pb") or 2)
                strength = int(numbers.get("save_dc") or 8 + pb) - 8 - pb
                unarmed = {"effects": [{"type": "attack", "attack_kind": "unarmed", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": True}]}],
                           "numbers": {**numbers, "attack_bonus": pb + strength},
                           "weapon": {"damage": {"count": 1, "sides": 2, "modifier": min(0, strength)}, "fixed_damage": max(0, 1 + min(0, strength)),
                                      "damage_type": "BLUDGEONING", "damage_types": ["BLUDGEONING"]},
                           "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": "unarmed_strike"}
                out.append(_bonus(shoves[0].model_copy(update={"target_kind": "HOSTILE_ENTITY", "range_ft": 5}), unarmed, weapon_id, flag, owned,
                                  f"{weapon_id}.barrage_mixed.unarmed", "Mixed Barrage: Unarmed Strike",
                                  f"After Barrage: {name} + Mixed Barrage, spend your Bonus Action on an Unarmed Strike (1 bludgeoning "
                                  f"damage; no positive Strength modifier)."))
                for shove in shoves:
                    shove_typed = copy.deepcopy((shove.parameters or {}).get("typed") or {})
                    shove_typed["effects"] = [e for e in shove_typed.get("effects") or [] if e.get("type") == "save"][:1]  # one Shove
                    out.append(_bonus(shove, shove_typed, weapon_id, flag, owned,
                                      f"{weapon_id}.barrage_mixed.{shove_typed.get('unarmed_option')}", f"Mixed Barrage: {shove.display_name}",
                                      f"After Barrage: {name} + Mixed Barrage, spend your Bonus Action on a Shove: the target makes a Strength "
                                      "or Dexterity saving throw or is pushed 5 feet / knocked Prone."))
        if SPINNING in owned:
            flag = f"barrage_spin:{weapon_id}"
            primary = one_attack(typed)
            count = next(e.get("count", 1) for e in typed["effects"] if e.get("type") == "attack")
            primary["effects"].append({"type": "barrage_spinning_second", "weapon": weapon_id,
                                        "primary": True, "count": max(0, int(count) - 1)})
            out.append(_primary(row, primary, owned, SPINNING, "Spinning Shot", flag, ((FOCUS, 1),)))
            spin = one_attack(typed)
            spin["effects"] = [*spin["effects"], {"type": "barrage_spinning_second", "weapon": weapon_id,
                                                  "evidence": "Make two Bonus Action attacks instead of one. Every attack in the Barrage must target a different creature."}]
            out.append(_bonus(row, spin, weapon_id, flag, owned, f"{weapon_id}.barrage_spinning", f"Spinning Shot: {name}",
                              f"After Barrage: {name} + Spinning Shot, spend your Bonus Action on two {name} attacks, each at a different "
                              "creature, neither a creature already targeted by the primary attacks. They add no positive ability modifier to damage.",
                              spinning_of=weapon_id))
    return {"actions": out, "rows": []} if out else None


# ------------------------------------------------------------------------------------------------ Spinning Shot's targets
@hook("technique_used")
def remember_legacy_spin_target(ctx: Any) -> None:
    """Saved primaries without the target-selection effect still exclude their aim.

    New rows record every primary inside spinning_second; never overwrite that
    multi-target state here. Each legacy primary use replaces its earlier aim.
    """
    if ctx.typed.get("maneuver") != "barrage" or (ctx.typed.get("modifier") or {}).get("id") != SPINNING:
        return
    if any(e.get("type") == "barrage_spinning_second" and e.get("primary")
           for e in ctx.typed.get("effects") or [] if isinstance(e, dict)):
        return
    aimed = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if aimed is not None:
        ctx.actor.turn_flags[SPIN_TARGET + str(ctx.typed.get("maneuver_of"))] = aimed.entity_id


@hook("candidate_allowed")
def spin_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    weapon_id = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("spinning_of")) if action is not None else None
    if not weapon_id:
        return None
    used = spin_targets(actor, str(weapon_id))
    return False if used.intersection(getattr(candidate, "target_ids", ()) or ()) else None


def spin_targets(actor: Any, weapon_id: str) -> set[str]:
    """Read string-only turn state; tolerate the original saved single-target format."""
    value = actor.turn_flags.get(SPIN_TARGET + weapon_id)
    if not value:
        return set()
    return set(json.loads(value)) if str(value).startswith("[") else {str(value)}


@effect("barrage_spinning_second")
def spinning_second(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    key = SPIN_TARGET + str(row.get("weapon"))
    used = set() if row.get("primary") else spin_targets(actor, str(row.get("weapon")))
    used.update(t.entity_id for t in ctx.targets or [] if t is not None)
    actor.turn_flags[key] = json.dumps(sorted(used))
    for index in range(int(row.get("count", 1))):
        _next_spin_attack(ctx, used, key, index, bool(row.get("primary")))


def _next_spin_attack(ctx: Any, used: set[str], key: str, index: int, primary: bool) -> None:
    from dataclasses import replace
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import run_effects
    engine, actor = ctx.engine, ctx.actor
    reach = int(ctx.typed.get("long_range_ft") or ctx.typed.get("range_ft") or ctx.action.range_ft or 5)
    others = sorted((other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id
                     and other.entity_id not in used and engine._distance_actor_to_actor(actor, other) <= reach
                     and engine._line_of_sight_actor_to_actor(actor, other)),
                    key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))
    if not others:
        ctx.rider("Spinning Shot: no other creature in range and sight, so the remaining attack is lost.")
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SPINNING_SHOT", actor.entity_id, str(index)), actor, CHOICE + "spinning_shot",
                 [other.entity_id for other in others], labels={other.entity_id: other.display_name for other in others},
                 name="Spinning Shot", feature_id=SPINNING,
                 prompt=f"Spinning Shot: {actor.display_name}'s {'Extra Attack' if primary else 'second Bonus Action attack'} after attacking "
                        f"{', '.join(engine.state.actors[t].display_name for t in sorted(used))}. Choose a different creature.")
    target = next((other for other in others if other.entity_id in picked), None)
    if target is None:
        return
    used.add(target.entity_id)
    actor.turn_flags[key] = json.dumps(sorted(used))
    attack = next(e for e in ctx.typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack")
    # Keep the primary's damage and modifier semantics while joining its hit
    # sequence; run_effects otherwise starts a fresh Barrage for this attack.
    typed = {**ctx.typed, "barrage_sequence_continuation": True} if primary else ctx.typed
    run_effects(replace(ctx, typed=typed, targets=[target], target=target), [copy.deepcopy(attack)])
