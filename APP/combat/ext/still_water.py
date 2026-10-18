"""Still-Water Draw Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Still-Water Draw Body (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "still_water", "role": "first_cut" | "moon"}``; Drawn from Stillness also carries the
integrated-weapon row ``{"kind": "integrated_weapon", "group": "draw_blade", "choose": 1}`` (combat/ext/integrated_weapons.py), whose
source-owned bound weapon is the Draw Weapon (sheet record or the persisted player choice; historical catalogs retain their old pick). Empty-Scabbard Step's Reaction runs
``empty_scabbard_step``; Heaven Divided Before Sound's action runs ``heaven_divided``.

First Cut          a Draw Weapon hit produced by your first attack roll this turn (a Reaction on another creature's turn uses
                   that turn): + Proficiency Bonus Slashing or Force, then an asked move of up to 5 feet without provoking.
Empty-Scabbard Step  before a melee attack against you is rolled: an asked move of up to 10 feet (the executor re-checks reach
                   and sight, so an attack that no longer reaches misses); if that attack then misses while the attacker is
                   within your Draw Weapon's reach, one Draw Weapon attack against it (a Granted Attack).
One Breath, Three Horizons  "One Breath, Three Horizons (<Draw Weapon>)": an Attack action of at least two attacks spends two of
                   them (and 2 Stamina, once per turn) on a 30-foot line (its reviewed save row, with the Draw Weapon's die),
                   then an asked move of up to half your Speed to a space next to the line, then the Attack action's other
                   attacks against creatures you choose (combat/ext/attack_lines.py, the shared helper).
Still-Water Posture  at the start of your turn (asked): Speed 0 until your first Draw Weapon attack resolves; that attack has
                   Advantage, and on a hit + 3d8 Slashing or Force, no Reactions for the target until the start of its next
                   turn and an asked move of up to half your Speed. Willing movement or a teleport first ends the posture.
Heaven Divided Before Sound  a straight line to the aimed space (through hostile creatures, stopped by walls; a standing blocking
                   object on the line is attacked first and passed if destroyed): one Draw Weapon attack (+ 6d8 Slashing or
                   Force) against each creature chosen among those crossed or within 5 feet (up to Proficiency Bonus, barriers
                   counting), then a Constitution save for each creature hit: Speed 0 and no Reactions until the end of its
                   next turn, or Speed halved until the start of its next turn.
Every hook returns early for a creature without these rows or actions.
"""

from __future__ import annotations

import copy
from contextvars import ContextVar
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.still_water_draw_body.feature."
DRAWN = PREFIX + "drawn_from_stillness"
ONE_BREATH = PREFIX + "one_breath_three_horizons"
POSTURE = "condition:typed.still_water_posture"
STILLED = "heaven_divided_stilled"
STAMINA = "resource:core.stamina"
BINDING = "condition:typed.still_water_draw_weapon"
MOON = PREFIX + "moon_reflected_before_motion"
_HEAVEN_ROUTE = ContextVar("still_water_committed_heaven_route", default=None)
LEVELS = {DRAWN: 3, PREFIX + "empty_scabbard_step": 6, ONE_BREATH: 10,
          MOON: 14, PREFIX + "heaven_divided_before_sound": 18}


def _profile(engine: Any, actor: Any) -> dict[str, Any]:
    if actor is None:
        return {}
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                if r.get("block") == "still_water_profile" and r.get("feature_id") == DRAWN), None)
    return row or next((a.parameters["still_water_profile"] for a in engine.action_catalog.values()
                        if a.owner_id == actor.entity_id and a.parameters.get("still_water_profile")), {})


def _available(engine: Any, actor: Any, source: str) -> bool:
    profile = _profile(engine, actor)
    if not profile:
        # Historical catalogs retain their lifecycle, but a named effect is
        # never ownership. Require the actor's actual sealed source row/action.
        rows = [*(getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []),
                *(getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])]
        return any(row.get("feature_id") == source for row in rows) or any(
            action.owner_id == actor.entity_id and (action.parameters.get("typed") or {}).get("source") == source
            for action in engine.action_catalog.values())
    return source in profile["features"] and int(profile["body_cl"]) >= LEVELS[source]


@hook("compile_acquisition_ids")
def acquired_still_water_features(owner_sheet: dict[str, Any]) -> list[str] | None:
    """Consume this family's source-granted progression from the native sheet producer."""
    rows = (owner_sheet.get("path_and_subpath") or {}).get("source_granted_subpath_feature_record_ids")
    if rows is None:
        return None
    if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
        raise ValueError("Native subpath feature records must be a list of source IDs")
    return [row for row in rows if row in LEVELS]


@hook("compile_actions")
def source_profile(info: dict[str, Any]) -> list[Any] | None:
    """Seal actual Body numbers and a player-recorded item; never grant a feature.

    The ordinary sheet's source-granted feature/earned-occurrence producer owns
    progression. Explicit Body effective_cl wins; NS1R attainment is capped by
    sheet CL. Runtime selection uses owned physical actions, never a new item.
    """
    if DRAWN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .integrated_weapons import in_group
    paths = info["owner_sheet"].get("path_and_subpath") or {}
    if "source_granted_subpath_feature_record_ids" not in paths and not paths.get("still_water_draw_weapon"):
        return None  # Older sheets/catalogs retain their existing selection lifecycle.
    body_numbers = _body_numbers(info)
    cl = int(body_numbers["cl"])
    bases = [a for a in info["actions"] if "#" not in a.source_definition_id
             and a.economy == EconomyKind.ACTION and in_group(a.parameters.get("typed") or {}, "draw_blade")]
    recorded = str(paths.get("still_water_draw_weapon") or "")
    weapons = {a.source_definition_id: _item(a.parameters["typed"]) for a in bases}
    profile = {"body_cl": cl, "con": int(info["mods"].get("CON", 0)),
               "features": sorted(set(info["owned_ids"]) & LEVELS.keys()),
               "recorded": recorded, "weapons": weapons,
               "own_weapons": [a.source_definition_id for a in bases if not a.parameters.get("requires_held_weapon")],
               "refined": int("tianxia.path.body_refining.feature.refined_iron_fist" in info["owned_ids"] and cl >= 5),
               "heavenly": int("tianxia.path.body_refining.feature.heavenly_fist" in info["owned_ids"] and cl >= 17)}
    info["passives"].append({"block": "still_water_profile", "feature_id": DRAWN, **profile})
    out = []
    for base in bases:
        item = base.source_definition_id
        out.append(base.model_copy(update={
            "source_definition_id": base.source_definition_id + "#still_water_bind",
            "display_name": "Draw Weapon: choose " + base.display_name.removesuffix(" attack"),
            "economy": EconomyKind.NONE, "target_kind": "SELF", "range_ft": None, "costs": (),
            "parameters": {"player_only": True, "setting_only": True, "still_water_bind": item,
                           "still_water_profile": profile, "expected_damage": 0,
                           "description": "Record this carried Draw Blade as your one Draw Weapon. Costs no action or Stamina; the choice is fixed for this fight.",
                           "typed": {"source": DRAWN, "numbers": info["numbers"], "effects": [{"type": "still_water_bind", "item": item}]}}}))
    return out or None


@hook("candidate_allowed")
def source_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("still_water_bind"):
        from ..weapon_delivery import available_weapons
        return (_available(engine, actor, DRAWN) and not _profile(engine, actor).get("recorded")
                and not draw_item(engine, actor) and params["still_water_bind"] in available_weapons(engine, actor, include_carried=True))
    typed = params.get("typed") or {}
    source = str(typed.get("source") or "")
    if source in LEVELS and _profile(engine, actor):
        if not _available(engine, actor, source):
            return False
        if source != DRAWN and not _draw_attacks(engine, actor):
            return False
    if params.get("still_water_item"):
        if _profile(engine, actor):
            if params.get('still_water_remaining_line'):
                from .special_attacks import FLAG
                if int(actor.turn_flags.get(FLAG,0))<2:
                    return False
            if candidate.destination == actor.position:
                return False
            identity=draw_identity(engine,actor)
            from .hand_occupancy import weapon_grips,weapon_allowed
            base=engine.action_catalog.get(typed.get("attack_line_of"))
            return (identity==typed.get("attack_line_of") and identity in weapon_grips(engine,actor)
                    and base is not None and weapon_allowed(engine,actor,base) is not False)
        return draw_item(engine, actor) == params["still_water_item"]
    return None


@effect("still_water_bind")
def bind_weapon(ctx: Any, row: dict[str, Any]) -> None:
    from ..weapon_delivery import available_weapons
    from .integrated_weapons import in_group
    if (not _profile(ctx.engine, ctx.actor) or not _available(ctx.engine, ctx.actor, DRAWN)
            or _profile(ctx.engine, ctx.actor).get("recorded") or draw_item(ctx.engine, ctx.actor)):
        return
    identity = str(row.get("item") or "")
    weapon = available_weapons(ctx.engine, ctx.actor, include_carried=True).get(identity)
    if weapon is None or not in_group(weapon.parameters.get("typed") or {}, "draw_blade"):
        return
    ctx.engine._apply_condition(ctx.actor, BINDING, DRAWN, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"item": _item(weapon.parameters["typed"]), "weapon": identity,
                                      "label": "Draw Weapon recorded for this fight"})


@hook("integrated_weapon_selected")
def selected_weapon(engine: Any, actor: Any, source: str, item: str) -> bool | None:
    if source == DRAWN:
        return _available(engine, actor, DRAWN) and (draw_identity(engine, actor) if _profile(engine, actor) else draw_item(engine, actor)) == item
    return None


@hook("turn_start_choice")
def choose_weapon(engine: Any, actor: Any) -> None:
    if (not _profile(engine, actor) or _profile(engine, actor).get("recorded")
            or draw_item(engine, actor) or not _available(engine, actor, DRAWN)):
        return
    from .needle import ask, checkpoint_id
    from ..weapon_delivery import available_weapons
    available = available_weapons(engine, actor, include_carried=True)
    actions = {a.parameters["still_water_bind"]: a for a in engine.action_catalog.values()
               if a.owner_id == actor.entity_id and a.parameters.get("still_water_bind") in available}
    if not actions:
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "draw_weapon", actor.entity_id),
                 actor, "choice:needle.still_water_draw_weapon", sorted(actions),
                 labels={k: a.display_name.removeprefix("Draw Weapon: choose ") for k, a in actions.items()},
                 name="Drawn from Stillness", feature_id=DRAWN, target_id=actor.entity_id,
                 prompt="Drawn from Stillness: choose your one carried Draw Weapon. This costs no action or Stamina; the choice is recorded for this fight.")
    if picked:
        from ..typed_executor import Context
        a = actions[picked[0]]
        bind_weapon(Context(engine, actor, a, getattr(engine, "_active_intent", None), a.parameters["typed"], [actor], actor),
                    {"item": picked[0]})


@hook("attack_sequence_start")
def draw_constitution(ctx: Any) -> None:
    """Mandatory ordinary ability basis, before optional replacement methods.

    Only this resolution's Context is copied. Casting-Hand and other explicitly
    chosen replacement methods retain the single-provider public substitution
    seam after this ordinary STR/DEX-to-CON basis has been established.
    """
    if not _profile(ctx.engine, ctx.actor) or not _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return
    if ctx.action.source_definition_id.endswith("#integrated_dex"):
        return  # An independently owned, explicitly selected replacement method.
    profile = _profile(ctx.engine, ctx.actor)
    if profile.get("refined") or profile.get("heavenly"):
        ctx.typed = copy.deepcopy(ctx.typed)
        ctx.typed["mundane"] = False
        ctx.typed["weapon"]["cultivation_powered"] = True
        if profile.get("heavenly") and "adamantine" not in str(ctx.typed["weapon"].get("properties") or "").lower():
            ctx.typed["weapon"]["properties"] = str(ctx.typed["weapon"].get("properties") or "") + ", Adamantine"
    weapon = ctx.typed.get("weapon") or {}
    if weapon.get("ability") not in {"STR", "DEX"} or "ability_modifier" not in weapon:
        return
    new = int(_profile(ctx.engine, ctx.actor)["con"])
    old = int(weapon["ability_modifier"])
    typed = copy.deepcopy(ctx.typed)
    typed["numbers"]["attack_bonus"] += new-old
    typed["weapon"].update(ability="CON", ability_modifier=new)
    if typed["weapon"].get("damage"):
        typed["weapon"]["damage"]["modifier"] += (min(0,new)-min(0,old)
            if weapon.get("omits_ability_damage") else new-old)
    ctx.typed = typed


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "still_water"}


def _stamp(engine: Any) -> str:
    current = engine.state.actors[engine.state.current_actor_id]
    return f"{current.entity_id}:{current.turns_started}"


def _item(typed: dict[str, Any]) -> str:
    return str((typed or {}).get("source") or "").rsplit(".", 1)[-1]


def _resolve_draw_identity(profile: dict[str, Any], value: str) -> str | None:
    weapons = profile.get("weapons") or {}
    if value in weapons:
        return value
    # Historical sheet shorthand is accepted only when it names ONE physical
    # weapon. Two copies/profiles of the same chassis require the exact ID.
    matches = [key for key, item in weapons.items() if value in (item, "tianxia.mortal.weapon." + item)]
    own = [key for key in matches if key in profile.get("own_weapons", [])]
    matches = own or matches
    return matches[0] if len(matches) == 1 else None


def draw_identity(engine: Any, actor: Any) -> str | None:
    profile = _profile(engine, actor)
    if not profile:
        return None
    recorded = next((str(c.data.get("weapon") or c.data.get("item") or "") for c in actor.conditions.values()
                     if c.condition_id == BINDING and c.source_definition_id == DRAWN
                     and c.source_actor_id == actor.entity_id), None) or profile.get("recorded") or ""
    return _resolve_draw_identity(profile, recorded)


def draw_item(engine: Any, actor: Any) -> str | None:
    """The Draw Weapon's item (Drawn from Stillness owners only)."""
    if "first_cut" not in _roles(engine, actor):
        return None
    profile = _profile(engine, actor)
    if profile:
        return profile.get("weapons", {}).get(draw_identity(engine, actor))
    from .integrated_weapons import chosen_items

    mine = [a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and str(getattr(a.economy, "value", a.economy)) == "ACTION"]
    found = chosen_items(mine, "draw_blade", 1)
    return found[0] if found else None


def _is_draw(engine: Any, actor: Any, typed: dict[str, Any]) -> bool:
    item = draw_item(engine, actor)
    if not item or not (typed or {}).get("weapon") or not _available(engine, actor, DRAWN):
        return False
    if _profile(engine, actor):
        return typed.get("still_water_weapon_id") == draw_identity(engine, actor)
    actual = _item(typed)
    if actual != item:
        for key in ("weapon_source_id", "delivered_by", "opportunity_of", "maneuver_of"):
            parent = engine.action_catalog.get(typed.get(key))
            if parent is not None:
                actual = _item(parent.parameters.get("typed") or {})
                break
    return actual == item


def _draw_attacks(engine: Any, actor: Any) -> dict[str, Any]:
    """Actual Draw Weapon attack profiles, including legal ability/reach/thrown modes."""
    item = draw_item(engine, actor)
    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        effects = typed.get("effects") or []
        from ..weapon_delivery import delivery_kind
        if (typed.get("unarmed_option") or not effects or effects[0].get("type") != "attack"
                or delivery_kind(typed,effects[0],action.parameters) != "weapon"):
            continue
        if action.owner_id != actor.entity_id or not item or not _is_draw(engine, actor, typed) or not typed.get("weapon") \
                or (action.parameters or {}).get("player_only") or str(getattr(action.economy, "value", action.economy)) != "ACTION":
            continue
        if "#" in action.source_definition_id and not any(key in action.source_definition_id for key in ("#integrated", "#reach", "#thrown")) \
                and not action.parameters.get("reach_bonus") and not action.parameters.get("still_water_cultivation"):
            continue
        from .hand_occupancy import weapon_allowed
        if weapon_allowed(engine, actor, action) is False:
            continue
        if any(int(actor.resources.get(pool,0))<amount for pool,amount in action.costs):
            continue
        if any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            out[action.source_definition_id] = action
    return out


def _creature_name(engine: Any,viewer: Any,creature: Any) -> str:
    from ..target_knowledge import can_see
    return creature.display_name if creature is viewer or can_see(engine,viewer,creature) else "an unseen creature"


def _pick_draw(engine: Any, intent: Any, actor: Any, target: Any, name: str) -> Any:
    from .needle import ask, checkpoint_id

    attacks = _draw_attacks(engine, actor)
    if len(attacks) <= 1:
        return next(iter(attacks.values()), None)
    preferred = [k for k in attacks if k.endswith("#integrated_con")] or list(attacks)
    picked = ask(engine, intent, checkpoint_id(engine, "draw_attack", target.entity_id), actor, "choice:needle.draw_weapon_attack", sorted(attacks),
                 labels={k: a.display_name for k, a in attacks.items()}, preferred=preferred[:1], target_id=target.entity_id, name=name,
                 prompt=f"{name}: which Draw Weapon attack against {_creature_name(engine,actor,target)}?")
    return attacks.get(picked[0] if picked else preferred[0]) or attacks[preferred[0]]


def _admit_and_pay_granted(engine: Any, actor: Any, action: Any, *, planned: bool) -> bool:
    """Recheck a granted Draw strike's admission and complete its per-strike payment."""
    from .granted_attacks import allows_root
    if not allows_root(engine, permission=planned):
        return False
    if any(int(actor.resources.get(pool, 0)) < int(amount) for pool, amount in action.costs):
        return False
    for pool, amount in action.costs:
        if amount:
            engine._spend_resource(actor, pool, amount, action.source_definition_id)
    if action.costs:
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine, actor, action.source_definition_id, consumes_reaction=False):
            return False
    return True


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, extra_hits: list[dict[str, Any]] = (), *, heaven_activation: Any = None) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((copy.deepcopy(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    action = action.model_copy(update={"target_kind": "ANY_CREATURE", "parameters": {**action.parameters, "harmful": True}})
    typed = copy.deepcopy(typed)
    planned = (heaven_activation is not None and heaven_activation.actor is actor
        and heaven_activation.engine is engine and _profile(engine,actor)
        and _available(engine,actor,PREFIX + 'heaven_divided_before_sound')
        and (_heaven_route_frame(engine,actor) or {}).get('ctx') is heaven_activation)
    if not _admit_and_pay_granted(engine, actor, action, planned=bool(planned)):
        return
    if planned:
        # These are the same activation's preselected original roots, not a
        # response granting extra attacks from the preceding granted strike.
        typed['allow_granted_followup']=True
        typed["still_water_heaven_bonus"] = str(heaven_activation.damage_cache["still_water_heaven_type"])
    else:
        attack["on_hit"] = [*(attack.get("on_hit") or []), *copy.deepcopy(list(extra_hits))]
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])


def _free_move(engine: Any, intent: Any, mover: Any, feet: int, choice_id: str, name: str, *, near: Any = None) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    source = {"choice:needle.first_cut_move": DRAWN,
              "choice:needle.still_water_posture_move": MOON,
              "choice:needle.attack_line_move": ONE_BREATH}.get(choice_id, DRAWN)
    native = bool(_profile(engine, mover))
    if not native:
        source = PREFIX + "still_water"  # immutable historical event attribution
    if native:
        from ..granted_movement import Route, routes as native_routes
        from .needle import cell_id
        paths = {cell_id(cell): Route(tuple(route), mode) for cell, (route, _cost, mode) in native_routes(engine, mover, feet).items()}
    else:
        paths = routes(engine, mover, feet) if feet > 0 else {}
    if near is not None:
        paths = {k: p for k, p in paths.items() if any(engine.grid.distance_ft(p[-1], cell) <= engine.grid.square_size_ft for cell in near)}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "still_water_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 feature_id=source,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        if native:
            from ..granted_movement import resolve_path
            resolve_path(engine, mover, paths[picked[0]], source, feet=feet, intent=intent, provokes=False)
        else:
            step(engine, mover, paths[picked[0]], source)


def _rolls_this_turn(engine: Any, actor: Any) -> int:
    count = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor.entity_id:
            count += 1
    return count


def _end_posture(engine: Any, actor: Any, reason: str) -> bool:
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == POSTURE and held.source_definition_id == MOON and held.source_actor_id == actor.entity_id:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "moon_reflected_before_motion", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": POSTURE, "instance_id": iid, "reason": reason})
            return True
    return False


def _in_posture(actor: Any) -> bool:
    return any(c.condition_id == POSTURE and c.source_definition_id == MOON and c.source_actor_id == actor.entity_id
               for c in actor.conditions.values())


# ------------------------------------------------------------------------------------------- First Cut and the posture
@hook("attack_damage_bonus")
def draw_confirmed_packets(ctx: Any, target: Any, attack: Any) -> int | None:
    """Choose/roll attached riders at the confirmed hit, before its damage.

    Same-type additions join the primary packet before defenses. Other printed
    types retain this attack's provenance and finish even if its first portion
    defeats the target. Neither a menu estimate nor a save can enter this phase.
    """
    engine, actor = ctx.engine, ctx.actor
    if (not _profile(engine, actor) or not _is_draw(engine, actor, ctx.typed)
            or ctx.attack_damage_context is None):
        return None
    from .needle import ask, checkpoint_id
    from ..gate2_runtime_models import DiceSpec
    provenance = ctx.attack_damage_context
    key = "still_water_packets:" + provenance.roll_id
    if key in ctx.damage_cache:
        raise ValueError("Draw Weapon confirmed packet was prepared twice")
    packets, moves = [], []
    if (ctx.typed.get("still_water_heaven_bonus") and ctx.typed.get("granted_attack")
            and isinstance(actor.turn_flags.get("_still_water_dash"), list)
            and _available(engine, actor, PREFIX + "heaven_divided_before_sound")):
        source = PREFIX + "heaven_divided_before_sound"
        roll = engine.roller.roll(DiceSpec(count=6,sides=8),actor_id=actor.entity_id,
            reason=f"DAMAGE:{source}:{provenance.attack_index}",critical=bool(provenance.critical))
        engine._record_roll(roll)
        engine._append_event("DAMAGE_ROLLED",source,actor_id=actor.entity_id,target_ids=(target.entity_id,),
            payload={**roll.model_dump(mode="json"),"attack_roll_id":provenance.roll_id})
        packets.append((int(roll.total),str(ctx.typed["still_water_heaven_bonus"]).upper(),source))
        hits = actor.turn_flags.setdefault("_heaven_divided_hits", [])
        if target.entity_id not in hits:
            hits.append(target.entity_id)
    if (_rolls_this_turn(engine, actor) == 1
            and actor.turn_flags.get("_round_first_cut") != _stamp(engine)):
        chosen = ask(engine, ctx.intent, checkpoint_id(engine,"first_cut",target.entity_id), actor,
            "choice:needle.first_cut", ["slashing","force"], allow_decline=True, default="first",
            labels={k:f"Add {actor.proficiency_bonus} {k.title()} damage, then optionally move 5 feet without provoking" for k in ("slashing","force")},
            name="First Cut", feature_id=DRAWN, target_id=target.entity_id,
            prompt=f"First Cut: your first attack hit {_creature_name(engine,actor,target)}. Add Proficiency Bonus as Slashing or Force to this hit, then optionally move 5 feet without provoking? Costs no action or Stamina.")
        if chosen:
            actor.turn_flags["_round_first_cut"] = _stamp(engine)
            packets.append((int(actor.proficiency_bonus),chosen[0].upper(),DRAWN))
            moves.append((5,"choice:needle.first_cut_move","First Cut"))
    moon = (bool(ctx.damage_cache.get("still_water_posture_attack")) and _in_posture(actor)
            and _available(engine, actor, MOON))
    if moon:
        chosen = ask(engine, ctx.intent, checkpoint_id(engine,"posture_type",target.entity_id), actor,
            "choice:needle.still_water_posture_type", ["slashing","force"],
            labels={k:"3d8 "+k.title()+" damage" for k in ("slashing","force")},
            name="Moon Reflected Before Motion", feature_id=MOON,target_id=target.entity_id,
            prompt=f"Moon Reflected Before Motion: choose Slashing or Force for 3d8 additional damage to {_creature_name(engine,actor,target)}. It cannot take Reactions until its next turn starts; afterward optionally move half your restored Speed without provoking. No extra cost.") or ["slashing"]
        roll = engine.roller.roll(DiceSpec(count=3,sides=8),actor_id=actor.entity_id,
            reason=f"DAMAGE:{MOON}:{provenance.attack_index}",critical=bool(provenance.critical))
        engine._record_roll(roll)
        engine._append_event("DAMAGE_ROLLED",MOON,actor_id=actor.entity_id,target_ids=(target.entity_id,),
            payload={**roll.model_dump(mode="json"),"attack_roll_id":provenance.roll_id})
        packets.append((int(roll.total),chosen[0].upper(),MOON))
        moves.append((-1,"choice:needle.still_water_posture_move","Still-Water Posture"))
    kind = str(ctx.attack_defense_spec.get("damage_type") or "UNTYPED").upper()
    posture_cl=next((int(c.data['source_cl']) for c in actor.conditions.values()
                     if c.condition_id==POSTURE and c.source_definition_id==MOON and type(c.data.get('source_cl')) is int),
                    int(_profile(engine,actor)['body_cl']))
    ctx.damage_cache[key] = {"packets":[p for p in packets if p[1] != kind],"moon":int(moon),"moves":moves,
                            "moon_source_cl":posture_cl}
    return sum(amount for amount,damage_type,_ in packets if damage_type == kind)


def _finish_draw_packets(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    provenance = ctx.attack_damage_context
    if provenance is None:
        return
    held = ctx.damage_cache.pop("still_water_packets:" + provenance.roll_id, None)
    if held is None:
        return
    sub = ctx.on_hit_context(target, damage_cache={}, continue_after_defeat=True)
    for amount, kind, source in held["packets"]:
        te.run_effects(sub.with_source(source), [{"type":"extra_damage","applies_to":"target",
            "flat":amount,"damage_types":[kind],"evidence":"Attached Draw Weapon hit damage"}])
    if held["moon"]:
        if target.active:
            te.run_effects(sub.with_source(MOON),[{"type":"reaction_denied","applies_to":"target",
                "expires_on":"START_OF_TARGET_NEXT_TURN","still_water_source_cl":held['moon_source_cl']}])
        ctx.damage_cache["still_water_end_posture"] = 1
    ctx.damage_cache["still_water_followup_moves"] = held["moves"]


@hook("after_hit_choice")
def draw_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _is_draw(engine, actor, ctx.typed):
        return
    from .. import typed_executor as te

    if _profile(engine, actor):
        _finish_draw_packets(ctx, target)
        return
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    first_cut = _rolls_this_turn(engine, actor) == 1 and actor.turn_flags.get("_round_first_cut") != _stamp(engine)
    if first_cut and _profile(engine, actor):
        from .needle import ask, checkpoint_id
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "first_cut", target.entity_id), actor,
                     "choice:needle.first_cut", ["slashing", "force"], allow_decline=True, default="first",
                     labels={k: f"Add {actor.proficiency_bonus} {k.title()} damage, then optionally move 5 feet without provoking" for k in ("slashing", "force")},
                     name="First Cut", feature_id=DRAWN, target_id=target.entity_id,
                     prompt=f"First Cut: your first attack hit {_creature_name(engine,actor,target)}. Add Proficiency Bonus damage as Slashing or Force? Costs no action or Stamina.")
        first_cut = bool(chosen)
    else:
        chosen = None
    if first_cut:
        actor.turn_flags["_round_first_cut"] = _stamp(engine)
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": chosen or ["slashing", "force"],
                              "evidence": "First Cut: + Proficiency Bonus"}])
    posture = _in_posture(actor) and _available(engine, actor, MOON)
    if _profile(engine, actor):
        posture = posture and bool(ctx.damage_cache.get("still_water_posture_attack"))
    if posture:
        _end_posture(engine, actor, "ATTACK_RESOLVED")
        ctx.damage_cache.pop("still_water_posture_attack", None)
    moon_types = ["slashing", "force"]
    if posture and _profile(engine, actor):
        from .needle import ask, checkpoint_id
        moon_types = ask(engine, ctx.intent, checkpoint_id(engine, "posture_type", target.entity_id), actor,
            "choice:needle.still_water_posture_type", moon_types,
            labels={k: "3d8 " + k.title() + " damage" for k in moon_types},
            name="Moon Reflected Before Motion", feature_id=MOON, target_id=target.entity_id,
            prompt=f"Moon Reflected Before Motion: your Draw Weapon hit {target.display_name}. Choose Slashing or Force for 3d8 additional damage; the target has no Reactions until its next turn starts. Costs no action or Stamina.") or moon_types
    if posture and target.active:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": moon_types,
                              "evidence": "Still-Water Posture: + 3d8"},
                             {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    moves = [*([(5, "choice:needle.first_cut_move", "First Cut")] if first_cut else []),
             *([(int(engine._effective_speed(actor)) // 2, "choice:needle.still_water_posture_move", "Still-Water Posture")] if posture else [])]
    if _profile(engine, actor):
        # Resolution-local only: a nested attack owns a different Context/cache.
        # Move after all packets/riders, before this sequence's next attack.
        ctx.damage_cache["still_water_followup_moves"] = moves
        return
    dash = actor.turn_flags.get("_still_water_dash")
    if isinstance(dash, list):
        dash.extend(moves)
        return
    for feet, choice_id, name in moves:
        if actor.active:
            _free_move(engine, ctx.intent, actor, feet, choice_id, name)


@hook("attack_aftermath")
def draw_followup_movement(ctx: Any, target: Any, hit: bool, index: int) -> None:
    if not _profile(ctx.engine, ctx.actor):
        return
    moves = ctx.damage_cache.pop("still_water_followup_moves", [])
    if ctx.damage_cache.pop("still_water_end_posture", 0):
        _end_posture(ctx.engine, ctx.actor, "ATTACK_RESOLVED")
        ctx.damage_cache.pop("still_water_posture_attack", None)
    if not hit:
        return
    for feet, choice_id, name in moves:
        if ctx.actor.active:
            current_feet = int(ctx.engine._effective_speed(ctx.actor)) // 2 if feet == -1 else feet
            _free_move(ctx.engine, ctx.intent, ctx.actor, current_feet, choice_id, name)


@hook("attack_mode")
def posture_advantage(ctx: Any, target: Any) -> str | None:
    if _in_posture(ctx.actor) and _available(ctx.engine, ctx.actor, MOON) and _is_draw(ctx.engine, ctx.actor, ctx.typed):
        if (not _profile(ctx.engine, ctx.actor) or not ctx.actor.turn_flags.get("still_water_posture_attack")
                or ctx.damage_cache.get("still_water_posture_attack")):
            return "ADVANTAGE"
    return None


@hook("attack_attempt_tracking")
def native_attack_attempt(engine: Any, attacker: Any, defender: Any, source: str, intent: Any) -> bool | None:
    if ((_profile(engine, attacker) and _in_posture(attacker))
            or (_profile(engine, defender) and _available(engine, defender, PREFIX + "empty_scabbard_step"))):
        return True
    return None


@hook("attack_completed")
def posture_automatic_miss(engine: Any, notice: Any, intent: Any) -> None:
    actor = engine.state.actors.get(notice.attacker_id)
    if (actor is not None and _profile(engine, actor) and not notice.hit and notice.attack_attempt_id
            and actor.turn_flags.get("still_water_posture_attempt") == notice.attack_attempt_id):
        _end_posture(engine, actor, "ATTACK_RESOLVED")
        actor.turn_flags.pop("still_water_posture_attempt", None)


@hook("before_attack")
def posture_attack_committed(engine: Any, attacker: Any, defender: Any, intent: Any, trigger: dict[str, Any]) -> None:
    """Reserve the first real committed Draw attack, before reactive damage/movement.

    The public native declaration and attack_scope supply the actual Context;
    menu estimates never call this producer. A nested strike has a distinct
    Context/cache and cannot inherit the reserved posture benefit.
    """
    if (not _profile(engine, attacker) or not _in_posture(attacker)
            or attacker.turn_flags.get("still_water_posture_attack")):
        return
    from .attack_scope import current
    frame = current(engine)
    ctx = frame.get("context") if frame else None
    if ctx is None or ctx.actor.entity_id != attacker.entity_id or not _is_draw(engine, attacker, ctx.typed):
        return
    attacker.turn_flags["still_water_posture_attack"] = 1
    attacker.turn_flags["still_water_posture_attempt"] = str(trigger.get("attack_attempt_id") or "")
    ctx.damage_cache["still_water_posture_attack"] = 1


@hook("attack_resolved")
def posture_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """A missed Draw Weapon attack also restores the Speed (no damage, Reaction denial or move). Empty-Scabbard Step's watch
    ends with the attack it answered."""
    if (not hit and _in_posture(ctx.actor) and _is_draw(ctx.engine, ctx.actor, ctx.typed)
            and (not _profile(ctx.engine, ctx.actor) or ctx.damage_cache.get("still_water_posture_attack"))):
        _end_posture(ctx.engine, ctx.actor, "ATTACK_RESOLVED")
        ctx.damage_cache.pop("still_water_posture_attack", None)
    if hit and target is not None and not _profile(ctx.engine, target) and (target.turn_flags.get("_scabbard_watch") or {}).get("attacker") == ctx.actor.entity_id:
        target.turn_flags.pop("_scabbard_watch", None)


@hook("turn_start_choice")
def enter_posture(engine: Any, actor: Any) -> None:
    if ("moon" not in _roles(engine, actor) or not _available(engine, actor, MOON) or not actor.active
            or not _draw_attacks(engine, actor) or actor.turn_flags.get("_round_still_water_posture") == str(engine.state.round_number)):
        return
    from .needle import ask, checkpoint_id

    intent = getattr(engine, "_active_intent", None)
    picked = ask(engine, intent, checkpoint_id(engine, "still_water_posture", actor.entity_id), actor, "choice:needle.still_water_posture", ["enter"],
                 labels={"enter": "Enter Still-Water Posture: Speed 0 until your first Draw Weapon attack, which has Advantage (+ 3d8 on a hit)"},
                 allow_decline=True, default="decline", target_id=actor.entity_id, name="Moon Reflected Before Motion",
                 prompt="Moon Reflected Before Motion: enter Still-Water Posture this turn?")
    if picked:
        actor.turn_flags["_round_still_water_posture"] = str(engine.state.round_number)
        engine._apply_condition(actor, POSTURE, PREFIX + "moon_reflected_before_motion", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Still-Water Posture: Speed 0 until your first Draw Weapon attack (Advantage, + 3d8 on a hit)",
                                      "source_cl": int(_profile(engine, actor).get("body_cl") or 14)})


@hook("event")
def posture_broken(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Any willing movement, teleportation, or spatial relocation before that attack ends the posture immediately"."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if actor is not None and _in_posture(actor):
        willing = payload.get("forced") is False if _profile(engine, actor) else not payload.get("forced")
        if willing:
            _end_posture(engine, actor, "MOVED")


# ------------------------------------------------------------------------------------------------ Empty-Scabbard Step
@effect("empty_scabbard_step")
def empty_scabbard_step(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, me, attacker = ctx.engine, ctx.actor, ctx.target
    if attacker is None or not _available(engine, me, PREFIX + "empty_scabbard_step"):
        return
    native = bool(_profile(engine, me))
    if native:
        from ..granted_movement import Route, routes as native_routes
        from .needle import cell_id
        paths = {cell_id(cell): Route(tuple(route), mode) for cell, (route, _cost, mode)
                 in native_routes(engine, me, 10, block_creatures=True).items()}
    else:
        paths = routes(engine, me, 10)
    if paths:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "empty_scabbard", me.entity_id), me, "choice:needle.empty_scabbard_step", sorted(paths),
                     allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=me.entity_id,
                     name="Empty-Scabbard Step",
                     prompt=f"Empty-Scabbard Step: move up to 10 feet before {attacker.display_name}'s attack is rolled (out of its reach, it misses).")
        if picked and picked[0] in paths:
            if native:
                from ..granted_movement import resolve_path
                resolve_path(engine, me, paths[picked[0]], PREFIX + "empty_scabbard_step", feet=10,
                             intent=ctx.intent, provokes=False)
            else:
                step(engine, me, paths[picked[0]], PREFIX + "empty_scabbard_step")
    me.turn_flags["_scabbard_watch"] = {"attacker": attacker.entity_id, "after": len(engine.events)}


@hook("after_miss_choice")
def scabbard_counter(ctx: Any, target: Any, spec: Any = None) -> None:
    engine, attacker = ctx.engine, ctx.actor
    watch = (target.turn_flags.get("_scabbard_watch") or {}) if target is not None else {}
    if _profile(engine, target) or watch.get("attacker") != attacker.entity_id:
        return
    target.turn_flags.pop("_scabbard_watch", None)
    rolled = [e for e in engine.events[int(watch.get("after") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id]
    if len(rolled) > 1 or not target.active or not attacker.active:
        return  # not the attack the step answered
    action = _pick_draw(engine, ctx.intent, target, attacker, "Empty-Scabbard Step")
    if action is None or engine._distance_actor_to_actor(target, attacker) > int(action.range_ft or 5):
        return
    _granted(engine, target, action, attacker, ctx.intent)


# ------------------------------------------------------------------------------------------ One Breath, Three Horizons
@hook("compile_actions")
def one_breath_actions(info: dict[str, Any]) -> list[Any] | None:
    """The Draw Weapon's Attack action with two of its attacks spent on the line (combat/ext/attack_lines.py)."""
    if ONE_BREATH not in info["owned_ids"] or DRAWN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .attack_lines import line_variants
    from .integrated_weapons import chosen_items

    from .integrated_weapons import in_group
    bases = [a for a in info["actions"] if in_group((a.parameters or {}).get("typed") or {}, "draw_blade")
             and not ((a.parameters or {}).get("typed") or {}).get("range_ft")]
    made = line_variants(info, ONE_BREATH, bases, replace=2, area={"shape": "line", "size_ft": 30, "width_ft": 5}, stamina=2,
                         name="One Breath, Three Horizons", move="half_speed_beside_line")
    by_id = {a.source_definition_id: a for a in bases}
    for action in made:
        parent = by_id[action.parameters["typed"]["attack_line_of"]]
        action.parameters["still_water_item"] = _item(parent.parameters["typed"])
        action.parameters["typed"]["attack_line_turn_clock"] = "turn"
        if _body_numbers(info) is not None:
            # A nonattack technique uses its actual weapon's grip. Inherited
            # attack compile-time "two hands" is not a second free-hand cost.
            action.parameters.pop("requires_hands",None)
            action.parameters["weapon_grip_from_action"] = parent.source_definition_id
            action.parameters["typed"]["attack_line_altitude"] = True
            action.parameters["typed"]["area_aim_altitude"] = True
            action.parameters.update(any_cell=True,cell_aim_requires_sight=False,cell_aim_altitude=True)
        action.parameters["typed"]["numbers"]["key_mod"] = int(info["mods"].get("CON", 0))
        save = action.parameters["typed"]["effects"][0]
        save["nearest_first"] = True
        damage = copy.deepcopy(next(r for r in save["on_fail"] if r.get("type") == "damage" and not r.get("dice", {}).get("weapon")))
        damage["still_water_weapon_die"] = int(parent.parameters["typed"]["weapon"]["damage"]["sides"])
        save["on_fail"] = [damage, *[r for r in save["on_fail"] if r.get("type") != "damage"]]
        save["applies_to"] = "creatures_in_area"
        save["exclude_self"] = True
    return made or None


@hook("candidate_allowed")
def heaven_divided_square(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("heaven_divided") and getattr(candidate, "destination", None) is not None:
        if candidate.destination == actor.position:
            return False
        if not engine.grid.volume_legal(candidate.destination, footprint=engine._footprint(actor),
                occupied_cells=engine._occupied_volumes_except(actor.entity_id, observed=True)):
            return False  # "An unoccupied space within 120 feet"; no hidden-occupancy menu leak.
    return None


@hook("compile_actions")
def heaven_divided_aim(info: dict[str, Any]) -> None:
    """Heaven Divided Before Sound is aimed at any square in range and sight (gate4_engine any_cell), not only near a creature."""
    for action in info["actions"]:
        if ((action.parameters or {}).get("typed") or {}).get("source") == PREFIX + "heaven_divided_before_sound" and action.target_kind == "CELL":
            action.parameters["any_cell"] = True  # this character's own action, being compiled
            action.parameters["heaven_divided"] = True
            action.parameters["cell_aim_requires_sight"] = False
            action.parameters["cell_aim_altitude"] = True
            action.parameters["ai_empty_area_filter"] = False
            action.parameters["ai_allow_empty_area"] = True


# ----------------------------------------------------------------------------------------- Heaven Divided Before Sound
def _line(start: Any, end: Any) -> list[Any]:
    """The same integer 3-D center ray as native combat geometry."""
    from ..gate2_runtime_models import Position
    from ..space import ray
    return [Position(x=x, y=y, z=z) for x, y, z in ray(start, end)]


def _barrier(engine: Any, cell: Any) -> Any:
    from ..object_geometry import target_cells
    return next((o for o in engine.state.objects.values() if not o.destroyed and (o.component or {}).get("blocks")
                 and cell in target_cells(engine, o) and o.current_hp is not None), None)


def _cut_barrier(ctx: Any, action: Any, obj: Any) -> None:
    """"Make one Draw Weapon attack against it before moving through. On a hit, deal normal damage plus 6d8"."""
    from ..gate2_runtime_models import DiceSpec
    from .objects import deal

    engine, actor = ctx.engine, ctx.actor
    typed = (action.parameters or {}).get("typed") or {}
    weapon = typed.get("weapon") or {}
    from .objects import attack_object_roll, prepare_damage_dice
    from ..typed_executor import Context
    strike = Context(engine, actor, action, ctx.intent, typed, [], None, {})
    draw_constitution(strike)
    typed, weapon = strike.typed, strike.typed.get("weapon") or {}
    native = bool(_profile(engine, actor))
    if native and draw_object_prepare(strike,obj,0) is False:
        return
    frame = _heaven_route_frame(engine, actor)
    planned = bool(native and frame is not None and frame.get("ctx") is ctx)
    if not _admit_and_pay_granted(engine, actor, action, planned=planned):
        return
    posture = (bool(strike.damage_cache.get("still_water_posture_attack")) if native else
               _in_posture(actor) and _available(engine, actor, MOON) and not actor.turn_flags.get("still_water_posture_attack"))
    if posture and not native:
        actor.turn_flags["still_water_posture_attack"] = 1
    with engine.d20_scope({"kind": "attack", "actor_id": actor.entity_id, "target_id": obj.object_id,
                           "source_id": strike.source, "attack_index": 1, "ac": int(obj.ac or 10),
                           "reason": f"ATTACK:{strike.source}:object:1", "attack_name": action.display_name}):
        hit, natural = attack_object_roll(strike, obj, modes=("ADVANTAGE",) if posture else ())
    if not hit:
        if native:
            draw_object_resolved(strike,obj,False,0)
        elif posture:
            _end_posture(engine, actor, "ATTACK_RESOLVED")
        return
    main_kind = str(weapon.get("damage_type") or "SLASHING").upper()
    if native:
        from ..typed_executor import resolve_attack_damage
        attack = next(e for e in strike.typed["effects"] if e.get("type") == "attack")
        dice,kinds,main_kind,_damage,weapon = resolve_attack_damage(strike,attack)
        if _profile(engine,actor).get("heavenly"):
            kinds = [*kinds,"FORCE"]
        main_kind = _draw_weapon_type(strike,obj.object_id,kinds,1) or main_kind
    else:
        dice = prepare_damage_dice(strike, DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0))
    main = engine.roller.roll(dice,
                              actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object", critical=natural == 20)
    engine._record_roll(main)
    extra = engine.roller.roll(DiceSpec(count=6, sides=8, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object:6d8", critical=natural == 20)
    engine._record_roll(extra)
    packets = [(int(main.total), main_kind),
               (int(extra.total), str(ctx.damage_cache.get("still_water_heaven_type") or "force").upper())]
    if native:
        packets.extend(draw_object_packets(strike,obj,0,natural == 20) or [])
        deal(engine,actor,obj,packets,ctx.source)
        draw_object_resolved(strike,obj,True,0)
        return
    from .needle import ask, checkpoint_id
    moves = []
    if _rolls_this_turn(engine, actor) == 1 and actor.turn_flags.get("_round_first_cut") != _stamp(engine):
        selected = ask(engine, ctx.intent, checkpoint_id(engine, "first_cut", obj.object_id), actor,
                       "choice:needle.first_cut", ["slashing", "force"], allow_decline=True,
                       labels={k: f"Add {actor.proficiency_bonus} {k.title()} damage to the barrier hit" for k in ("slashing", "force")},
                       target_id=actor.entity_id, name="First Cut", feature_id=DRAWN,
                       prompt="First Cut: your first Draw Weapon attack hit the barrier. Add Proficiency Bonus damage as Slashing or Force, then optionally move 5 feet without provoking? Costs no action or Stamina.")
        if selected:
            actor.turn_flags["_round_first_cut"] = _stamp(engine)
            packets.append((int(actor.proficiency_bonus), selected[0].upper()))
            moves.append((5, "choice:needle.first_cut_move", "First Cut"))
    if posture:
        selected = ask(engine, ctx.intent, checkpoint_id(engine, "posture_type", obj.object_id), actor,
                       "choice:needle.still_water_posture_type", ["slashing", "force"],
                       labels={k: "3d8 " + k.title() + " damage to the barrier" for k in ("slashing", "force")},
                       target_id=actor.entity_id, name="Moon Reflected Before Motion", feature_id=MOON,
                       prompt="Moon Reflected Before Motion: choose Slashing or Force for 3d8 additional damage to the barrier. Restore Speed after this attack; on this hit you may then move half your Speed without provoking. Costs no action or Stamina.") or ["slashing"]
        bonus = engine.roller.roll(DiceSpec(count=3, sides=8), actor_id=actor.entity_id,
                                   reason=f"DAMAGE:{MOON}:object", critical=natural == 20)
        engine._record_roll(bonus)
        packets.append((int(bonus.total), selected[0].upper()))
        _end_posture(engine, actor, "ATTACK_RESOLVED")
        moves.append((int(engine._effective_speed(actor)) // 2, "choice:needle.still_water_posture_move", "Still-Water Posture"))
    deal(engine, actor, obj, packets, ctx.source)
    dash = actor.turn_flags.get("_still_water_dash")
    if isinstance(dash, list) and not _profile(engine, actor):
        dash.extend(moves)
    else:
        for feet, choice_id, name in moves:
            _free_move(engine, ctx.intent, actor, feet, choice_id, name)


@effect("heaven_divided_hit")
def heaven_divided_hit(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        hits = ctx.actor.turn_flags.setdefault("_heaven_divided_hits", [])
        if ctx.target.entity_id not in hits:
            hits.append(ctx.target.entity_id)


def _heaven_route_frame(engine: Any, actor: Any) -> Any:
    frame = _HEAVEN_ROUTE.get()
    return frame if frame is not None and frame["engine"] is engine and frame["actor"] is actor else None


@hook("movement_landed")
def heaven_displaced(engine: Any, actor: Any, previous: Any, destination: Any, intent: Any, forced: bool) -> None:
    frame = _heaven_route_frame(engine, actor)
    if frame is not None and forced:
        frame["broken"] = True


@hook("movement_step_completed")
def heaven_progress(engine: Any, actor: Any, previous: Any, destination: Any, intent: Any, forced: bool) -> None:
    """Continue the one declared line after an actual source-owned bonus step.

    Targets and attack budget are the original accepted activation's, not a new
    attack grant. A nested hit can move farther along the line, but cannot create
    another target/attack or resume after leaving the declared physical route.
    """
    frame = _heaven_route_frame(engine, actor)
    if frame is None or frame["broken"]:
        return
    scope = engine.movement_scope(actor.entity_id) or {}
    allowed = {DRAWN, MOON, PREFIX + "heaven_divided_before_sound"}
    if forced or scope.get("source_id") not in allowed:
        frame["broken"] = True
        return
    line = frame["line"]
    index = next((i for i,cell in enumerate(line) if cell == destination), -1)
    if index <= frame["cursor"] or actor.position != destination:
        frame["broken"] = True
        return
    frame["cursor"] = index
    frame["walked"].append(destination)
    for target_id in frame["chosen"]:
        if (frame["near"][target_id] != index or target_id in frame["attacked"]
                or frame["budget"] <= 0 or frame["broken"]):
            continue
        frame["attacked"].add(target_id)
        target = engine.state.actors[target_id]
        action = frame["action"]
        if not actor.active or not target.active or action is None:
            continue
        from ..attack_declaration import can_target
        recipient_action = action.model_copy(update={"target_kind":"ANY_CREATURE",
            "parameters":{**action.parameters,"harmful":True}})
        if not can_target(engine,actor,target,action.source_definition_id,action=recipient_action,
                range_ft=int(action.range_ft or action.reach_ft or 5)):
            continue
        frame["budget"] -= 1
        _granted(engine,actor,action,target,intent,heaven_activation=frame["ctx"])


def _native_heaven_traverse(ctx: Any, line: list[Any], chosen: list[str], near: dict[str,int], action: Any, budget: int) -> list[Any]:
    from .rider_movement import step
    from ..relations import ENEMY, relation
    engine, actor = ctx.engine, ctx.actor
    frame = {"engine":engine,"actor":actor,"ctx":ctx,"line":line,"chosen":chosen,"near":near,
             "action":action,"budget":budget,"cursor":0,"walked":[actor.position],"attacked":set(),"broken":False}
    token = _HEAVEN_ROUTE.set(frame)
    try:
        while frame["cursor"] + 1 < len(line) and not frame["broken"]:
            if (not actor.active or engine.state.terminal_result is not None
                    or actor.position != line[frame["cursor"]] or engine._effective_speed(actor) <= 0):
                break
            cell = line[frame["cursor"] + 1]
            occupied = {spot for other in engine.state.actors.values() if other.entity_id != actor.entity_id
                        and other.active and relation(engine,actor,other) != ENEMY for spot in engine._actor_volume(other)}
            legal = lambda: engine.grid.volume_step_legal(actor.position,cell,occupied_cells=occupied,footprint=engine._footprint(actor))
            if not legal():
                obj = _barrier(engine,cell)
                if obj is None or action is None or frame["budget"] < 1:
                    break
                frame["budget"] -= 1
                cursor = frame["cursor"]
                _cut_barrier(ctx,action,obj)
                if frame["broken"]:
                    break
                if frame["cursor"] != cursor:
                    continue  # a printed optional step already advanced this same line
                if not legal():
                    break
            before = actor.position
            cursor = frame["cursor"]
            step(engine,actor,[before,cell],PREFIX + "heaven_divided_before_sound",record_willing=True)
            if frame["cursor"] == cursor:
                break  # a real movement restriction prevented entry
        return frame["walked"]
    finally:
        _HEAVEN_ROUTE.reset(token)


@effect("heaven_divided")
def heaven_divided(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .effect_durations import token
    from .needle import ask, checkpoint_id
    from .rider_movement import step

    engine, actor = ctx.engine, ctx.actor
    if not _available(engine, actor, PREFIX + "heaven_divided_before_sound"):
        return
    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.destination
    if aim is None or aim == actor.position:
        return
    line = _line(actor.position, aim)[: int(row.get("range_ft") or 120) // engine.grid.square_size_ft + 1]
    pb = int(actor.proficiency_bonus or 2)
    kinds = ask(engine, ctx.intent, checkpoint_id(engine, "heaven_divided_type", actor.entity_id), actor,
                "choice:needle.heaven_divided_type", ["slashing", "force"],
                labels={k: "6d8 " + k.title() + " additional damage for this activation" for k in ("slashing", "force")},
                name="Heaven Divided Before Sound", feature_id=PREFIX + "heaven_divided_before_sound", target_id=actor.entity_id,
                prompt="Heaven Divided Before Sound: choose Slashing or Force for the additional 6d8 damage of this activation. This Action costs 7 Stamina and is usable once per scene.") or ["slashing"]
    ctx.damage_cache["still_water_heaven_type"] = kinds[0]
    near = {}
    for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not other.active or other.entity_id == actor.entity_id:
            continue
        from ..target_knowledge import knowledge
        known = knowledge(engine, actor, other)
        if known is None:
            continue
        seen = other.model_copy(update={"position": known.position})
        from ..spatial_areas import actor_positions
        spots = [(engine.grid.distance_ft(cell, spot), i) for i, cell in enumerate(line[1:], start=1) for spot in actor_positions(engine,seen)]
        best = min(spots) if spots else None
        if best is not None and best[0] <= 5:
            near[other.entity_id] = best[1]
    chosen: list[str] = []
    if near:
        order = sorted(near, key=lambda k: (near[k], k))
        from ..relations import ENEMY, relation
        automatic_targets = [key for key in order if relation(engine, actor, engine.state.actors[key]) == ENEMY]
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "heaven_divided", actor.entity_id), actor, "choice:needle.heaven_divided_targets", order,
                     labels={k: _creature_name(engine,actor,engine.state.actors[k]) for k in order}, minimum=1, maximum=min(pb, len(order)), allow_decline=True,
                     preferred=automatic_targets, automatic_options=automatic_targets,
                     default_count=min(pb, len(automatic_targets)), target_id=actor.entity_id, name="Heaven Divided Before Sound",
                     prompt=f"Heaven Divided Before Sound: choose up to {pb} creatures on or beside the line to cut.") or []
    first = next((engine.state.actors[k] for k in chosen), None)
    action = _pick_draw(engine, ctx.intent, actor, first or actor, "Heaven Divided Before Sound") if (chosen or any(_barrier(engine, c) for c in line)) else None
    budget = pb
    actor.turn_flags["_heaven_divided_hits"] = []
    extra = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 6, "sides": 8}, "damage_types": kinds,
              "evidence": "Heaven Divided Before Sound: + 6d8"}, {"type": "heaven_divided_hit"}]
    walked = [actor.position]
    native = bool(_profile(engine, actor))
    def transit_occupied():
        if not native:
            return set()
        from ..relations import ENEMY, relation
        return {cell for other in engine.state.actors.values() if other.entity_id != actor.entity_id
                and other.active and relation(engine, actor, other) != ENEMY
                for cell in engine._actor_volume(other)}
    actor.turn_flags["_still_water_dash"] = []
    if native:
        walked = _native_heaven_traverse(ctx,line,chosen,near,action,budget)
    else:
        for i, cell in enumerate(line[1:], start=1):
            if (not actor.active or engine.state.terminal_result is not None or actor.position != walked[-1]
                    or engine._effective_speed(actor) <= 0):
                break  # something else moved the user off the line
            if not engine.grid.volume_step_legal(actor.position, cell, occupied_cells=transit_occupied(), footprint=engine._footprint(actor)):
                obj = _barrier(engine, cell)
                if obj is None or action is None or budget < 1:
                    break  # a wall, total cover or a barrier it cannot cut: end before it
                budget -= 1
                _cut_barrier(ctx, action, obj)
                if actor.position != walked[-1]:
                    break  # an optional printed hit step moved the user off the declared line
                if not engine.grid.volume_step_legal(actor.position, cell, occupied_cells=transit_occupied(), footprint=engine._footprint(actor)):
                    break  # it survived
            step(engine, actor, [actor.position, cell], PREFIX + "heaven_divided_before_sound", record_willing=bool(_profile(engine, actor)))
            if actor.position != cell:
                break
            walked.append(cell)
            for foe_id in [k for k in chosen if near[k] == i]:
                foe = engine.state.actors[foe_id]
                if foe.active and action is not None and budget > 0:
                    budget -= 1
                    _granted(engine, actor, action, foe, ctx.intent, extra, heaven_activation=ctx if _profile(engine, actor) else None)
    # "cannot end in an occupied space": back to the last free square it crossed
    occupied = engine._occupied_volumes_except(actor.entity_id)
    if actor.active and not engine.grid.volume_legal(actor.position, footprint=engine._footprint(actor), occupied_cells=occupied):
        back = next((c for c in reversed(walked[:-1]) if engine.grid.volume_legal(c, footprint=engine._footprint(actor), occupied_cells=occupied)), None)
        if back is not None:
            if native:
                from ..creature_passage import finish
                previous = actor.position
                recovered = list(walked)
                finish(engine,actor,recovered,ctx.intent)
                engine._append_event("MOVEMENT_COMMITTED",PREFIX + "heaven_divided_before_sound",actor_id=actor.entity_id,
                    payload={"destination":actor.position.model_dump(mode="json"),"cost_ft":0,"forced":True,
                             "failed_passage":True,"path":[previous.model_dump(mode="json"),actor.position.model_dump(mode="json")]})
            else:
                idx = walked.index(back)
                step(engine, actor, list(reversed(walked[idx:])), PREFIX + "heaven_divided_before_sound")
    for feet, choice_id, name in actor.turn_flags.pop("_still_water_dash", None) or []:
        if actor.active:
            _free_move(engine, ctx.intent, actor, feet, choice_id, name)
    hits = [engine.state.actors[k] for k in actor.turn_flags.pop("_heaven_divided_hits", []) if k in engine.state.actors]
    for foe in hits:
        if not foe.active:
            continue
        sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [foe], foe, {})
        te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Heaven Divided Before Sound: Constitution saving throw",
                              "on_fail": [{"type": "condition", "applies_to": "target", "condition": STILLED,
                                           "expires_on": token("end", foe.entity_id, int(foe.turns_started) + 1)}],
                              "on_success": [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": "START_OF_TARGET_NEXT_TURN"}]}])
    if not hits and not chosen:
        note(engine, PREFIX + "heaven_divided_before_sound", actor, "Heaven Divided Before Sound: no creature was cut.")


@hook("effect_resolution_scope")
def draw_attack_resolution_hold(ctx: Any, row: dict[str,Any]) -> Any:
    if (_profile(ctx.engine,ctx.actor) and row.get("type") == "attack"
            and (_is_draw(ctx.engine,ctx.actor,ctx.typed)
                 or ctx.typed.get('attack_action') and _available(ctx.engine,ctx.actor,ONE_BREATH))):
        return ctx.engine.victory_deferred()
    return None


@hook("attack_line_movement")
def horizons_native_movement(ctx: Any, row: dict[str,Any], cells: Any) -> bool | None:
    if ctx.typed.get("source") != ONE_BREATH or not _profile(ctx.engine,ctx.actor):
        return None
    _free_move(ctx.engine,ctx.intent,ctx.actor,int(ctx.engine._effective_speed(ctx.actor))//2,
        "choice:needle.attack_line_move","One Breath, Three Horizons",
        near=ctx.damage_cache.get('still_water_horizons_line_cells',cells))
    return True


@hook("attack_line_profiles")
def horizons_remaining_profiles(ctx: Any, base_id: str) -> dict[str,Any] | None:
    if ctx.typed.get("source") != ONE_BREATH or not _profile(ctx.engine,ctx.actor):
        return None
    return _draw_attacks(ctx.engine,ctx.actor)


@hook("effect_resolution_scope")
def horizons_scope(ctx: Any, row: dict[str, Any]) -> Any:
    """Keep the native save visible to area previews, AI, Evasion and roll phases."""
    if (ctx.typed.get("source") != ONE_BREATH or row.get("type") != "save"
            or not any(r.get("still_water_weapon_die") for r in row.get("on_fail") or [])):
        return None
    from contextlib import contextmanager
    from .needle import ask, checkpoint_id

    @contextmanager
    def resolution():
        if _profile(ctx.engine,ctx.actor):
            from .attack_lines import reserve_use
            reserve_use(ctx.engine,ctx.actor,ONE_BREATH,ctx.typed.get("attack_line_turn_clock"))
            from ..typed_executor import area_cells
            aim=ctx.damage_cache.get('_checkpoint_aim')
            if aim is not None:
                ctx.damage_cache['still_water_horizons_line_cells']=area_cells(ctx.engine,ctx.actor.position,aim,
                    ctx.typed.get('area') or {},include_altitude=True)
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "horizons_type", ctx.actor.entity_id), ctx.actor,
            "choice:needle.still_water_horizons_type", ["slashing", "force"],
            labels={k: k.title() + " damage for the whole line" for k in ("slashing", "force")},
            name="One Breath, Three Horizons", feature_id=ONE_BREATH, target_id=ctx.actor.entity_id,
            prompt="One Breath, Three Horizons: choose Slashing or Force for the line. Replace two attacks and spend 2 Stamina; Dexterity save for half damage, with no Reactions on a failed save until their next turn starts.") or ["slashing"]
        changed = []
        for damage in row.get("on_fail") or []:
            if damage.get("type") == "damage":
                changed.append((damage, damage.get("resolved_damage_type")))
                damage["resolved_damage_type"] = selected[0]
        try:
            yield
        finally:
            for damage, before in changed:
                if before is None:
                    damage.pop("resolved_damage_type", None)
                else:
                    damage["resolved_damage_type"] = before
    return resolution()


@hook("damage_roll_bonus")
def horizons_weapon_dice(ctx: Any, row: Any, kinds: Any) -> int | None:
    """Mixed printed dice join the same native packet before save halving/defenses."""
    if not isinstance(row, dict) or not row.get("still_water_weapon_die") or ctx.typed.get("source") != ONE_BREATH:
        return None
    if not _available(ctx.engine, ctx.actor, ONE_BREATH):
        return None
    from ..gate2_runtime_models import DiceSpec
    from .hand_occupancy import versatile_die_sides
    base = ctx.engine.action_catalog.get(ctx.typed.get("attack_line_of"))
    sides = versatile_die_sides(ctx.engine, ctx.actor, base) if base is not None else None
    roll = ctx.engine.roller.roll(DiceSpec(count=2, sides=int(sides or row["still_water_weapon_die"]), modifier=0),
                                  actor_id=ctx.actor.entity_id, reason=f"DAMAGE:{ONE_BREATH}:weapon_dice")
    ctx.engine._record_roll(roll)
    ctx.engine._append_event("DAMAGE_ROLLED", ONE_BREATH, actor_id=ctx.actor.entity_id,
                             payload=roll.model_dump(mode="json"))
    return int(roll.total)


@hook("row_allowed")
def source_reactions(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != PREFIX + "empty_scabbard_step" or not _profile(engine, actor):
        return None
    # New source profiles use the public pre-roll declaration for typed AND
    # native attacks, so the old typed-only generic window must not also pay.
    return bool(row.get("still_water_native")) and _available(engine, actor, row["feature_id"]) \
        and actor.turn_flags.get("_round_empty_scabbard") != str(engine.state.round_number)


@hook("before_attack")
def scabbard_declared(engine: Any, attacker: Any, defender: Any, intent: Any, trigger: dict[str, Any]) -> dict[str, Any] | None:
    source = PREFIX + "empty_scabbard_step"
    if not _profile(engine, defender) or not _available(engine, defender, source) or trigger.get("ranged"):
        return None
    from .. import typed_reactions as tr
    from .needle import ask, checkpoint_id
    from .choice_costs import payable
    row = next((copy.deepcopy(r) for r in engine.typed_reaction_rows.get(defender.entity_id, [])
                if r.get("feature_id") == source), None)
    if row is None:
        return None
    row["still_water_native"] = 1
    payment = payable(defender, STAMINA, 1)
    if payment is None or not tr.can_use_reaction(engine, defender, attacker, row):
        return None
    selected = ask(engine, intent, checkpoint_id(engine, "empty_scabbard_use", defender.entity_id), defender,
                   "choice:needle.empty_scabbard_use", ["use"], allow_decline=True,
                   labels={"use": "Spend your Reaction and 1 Stamina; move up to 10 feet before this melee attack rolls"},
                   name="Empty-Scabbard Step", feature_id=source, target_id=attacker.entity_id, payment=payment,
                   prompt=f"Empty-Scabbard Step: {_creature_name(engine,defender,attacker)} committed a melee attack against you. Spend your Reaction and 1 Stamina to move up to 10 feet without provoking? If it misses and stays in Draw Weapon reach, counter after it resolves.")
    if not selected:
        return None
    tr.open_reaction(engine, row, defender, (attacker.entity_id,), "ATTACK_DECLARED")
    tr.spend_reaction(engine, defender, row)
    payment.pay(engine, defender, source)
    defender.turn_flags["_round_empty_scabbard"] = str(engine.state.round_number)
    from ..activation_payments import reaction_completed
    if not reaction_completed(engine, defender, source):
        return {}
    ctx = tr.generic_reaction_context(engine, defender, attacker, row, intent)
    empty_scabbard_step(ctx, {"type": "empty_scabbard_step"})
    defender.turn_flags["_scabbard_watch"].update(source=str(trigger.get("source_id") or ""),
        index=int(trigger.get("attack_index") or 1),
        attempt=str(trigger.get("attack_attempt_id") or ""),
        counter=int(not (trigger.get("typed") or {}).get("granted_attack")))
    engine._append_event("REACTION_RESOLVED", source, actor_id=defender.entity_id, target_ids=(attacker.entity_id,),
                         payload={"checkpoint": "ATTACK_DECLARED", "stamina": 1})
    return {}


@hook("attack_completed")
def scabbard_completed(engine: Any, notice: Any, intent: Any) -> None:
    """Only the committed attack's final boundary can consume the source watch."""
    defender = engine.state.actors.get(notice.target_id)
    attacker = engine.state.actors.get(notice.attacker_id)
    if defender is None or attacker is None or not _profile(engine, defender):
        return
    watch = defender.turn_flags.get("_scabbard_watch") or {}
    if (not notice.attack_attempt_id or watch.get("attempt") != notice.attack_attempt_id
            or (watch.get("attacker"), watch.get("source"), watch.get("index")) != (notice.attacker_id, notice.source_id, notice.attack_index)):
        return
    defender.turn_flags.pop("_scabbard_watch", None)
    if notice.hit or not watch.get("counter") or not defender.active or not attacker.active:
        return
    if _profile(engine,defender):
        base=engine.action_catalog.get(draw_identity(engine,defender))
        if base is None:return
        from .reach_bonus import current_reach
        from ..attack_reach import bonus
        reach=current_reach(engine,defender,base)+bonus(engine,defender,base)
        if engine._effect_distance(defender,attacker)>reach:return
    action = _pick_draw(engine, intent, defender, attacker, "Empty-Scabbard Step")
    if action is None:
        return
    from ..attack_declaration import can_target
    if not can_target(engine, defender, attacker, action.source_definition_id, action=action,
                      range_ft=int(action.range_ft or action.reach_ft or 5)):
        return
    _granted(engine, defender, action, attacker, intent)


@hook("weapon_attack_draw_allowed")
def draw_during_attack(engine: Any, actor: Any, action: Any, identity: str) -> bool | None:
    if _profile(engine, actor) and _is_draw(engine, actor, action.parameters.get("typed") or {}):
        return True
    return None


@hook("attack_spec_choice")
def draw_committed_weapon(ctx: Any, target: Any, attack: Any, spec: Any, index: int) -> None:
    """Commit only this attack's own item readiness, retaining all hand/possession gates."""
    if not _profile(ctx.engine, ctx.actor) or not _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return
    from .hand_occupancy import weapon_grips, weapon_allowed, supports_grips
    from .equipment_hands import set_weapon_readiness
    from ..weapon_delivery import weapon_identity
    identity = weapon_identity(ctx.engine, ctx.source, ctx.typed, ctx.action.parameters)
    if (supports_grips(ctx.engine, ctx.actor) and identity not in weapon_grips(ctx.engine, ctx.actor)
            and weapon_allowed(ctx.engine, ctx.actor, ctx.action, effect=attack)):
        set_weapon_readiness(ctx.engine, ctx.actor, identity, True, source=DRAWN, source_actor_id=ctx.actor.entity_id)


@hook("attack_aftermath")
def sheath_committed_weapon(ctx: Any, target: Any, hit: bool, index: int) -> None:
    engine, actor, action, intent = ctx.engine, ctx.actor, ctx.action, ctx.intent
    if not _profile(engine, actor) or not _is_draw(engine, actor, ctx.typed):
        return
    from .needle import ask, checkpoint_id
    from .equipment_hands import set_weapon_readiness
    from .hand_occupancy import weapon_grips
    from ..weapon_delivery import weapon_identity
    identity = weapon_identity(engine, action.source_definition_id, action.parameters.get("typed") or {}, action.parameters)
    if identity not in weapon_grips(engine, actor):
        return
    picked = ask(engine, intent, checkpoint_id(engine, "draw_weapon_sheath", actor.entity_id, index), actor,
                 "choice:needle.draw_weapon_sheath", ["sheath"], allow_decline=True, default="decline",
                 labels={"sheath": "Sheath your Draw Weapon as part of the resolved attack (no extra object interaction)"},
                 name="Drawn from Stillness", feature_id=DRAWN, target_id=actor.entity_id,
                 prompt="Drawn from Stillness: sheath your Draw Weapon as part of this attack? Costs no action or Stamina and frees its grip; this grants no interaction with another item.")
    if picked:
        set_weapon_readiness(engine, actor, identity, False, source=DRAWN, source_actor_id=actor.entity_id)


@hook("attack_magical")
def refined_draw_weapon(engine: Any, actor_id: str, typed: dict[str, Any]) -> bool | None:
    actor = engine.state.actors.get(actor_id)
    if actor is not None and _is_draw(engine, actor, typed):
        profile = _profile(engine, actor)
        return bool(profile.get("refined") or profile.get("heavenly")) or None
    return None


@hook("attack_damage_types")
def heavenly_draw_types(ctx: Any, attack: Any, kinds: list[str]) -> list[str] | None:
    if _profile(ctx.engine, ctx.actor).get("heavenly") and _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return list(dict.fromkeys([*kinds, "FORCE"]))
    return None


@hook("fight_setup_tasks")
def draw_weapon_setup(engine: Any) -> list[dict[str, str]]:
    """Defer the first turn to an accepted intent; constructors never pick for a human."""
    return [{"actor_id": actor.entity_id, "source_id": DRAWN} for actor in engine.state.actors.values()
            if actor.active and _profile(engine, actor) and _available(engine, actor, DRAWN)]


@hook("fight_setup")
def record_draw_weapon(engine: Any, actor: Any, source: str, intent: Any) -> bool | None:
    if source != DRAWN or not _profile(engine, actor):
        return None
    choose_weapon(engine, actor)
    return True



@hook("support_surface")
def heaven_route_support(engine: Any, actor: Any, position: Any) -> bool | None:
    """The printed open-air route supports only its current committed step.

    It grants neither flight nor a persistent surface. Native falling resumes
    when this same activation removes its dash frame; other actors are inert.
    """
    if _profile(engine,actor):
        frame = _heaven_route_frame(engine,actor)
        if (frame is not None and not frame["broken"] and position == actor.position
                and position in frame["line"] and _available(engine,actor,PREFIX + "heaven_divided_before_sound")):
            return True
    elif (position == actor.position and isinstance(actor.turn_flags.get("_still_water_dash"), list)
            and _available(engine, actor, PREFIX + "heaven_divided_before_sound")):
        return True
    return None


@hook("cell_candidate_metadata")
def heaven_line_estimate(engine: Any, actor: Any, action: Any, destination: Any) -> dict[str, Any] | None:
    """Pure estimates use only this actor's observed creatures, never hidden state."""
    if not (getattr(action, "parameters", None) or {}).get("heaven_divided"):
        return None
    from ..target_knowledge import knowledge
    line = _line(actor.position, destination)
    count = 0
    for other in engine.state.actors.values():
        if not other.active or other.team_id == actor.team_id:
            continue
        known = knowledge(engine, actor, other)
        if known is not None and min(engine.grid.distance_ft(cell, known.position) for cell in line) <= 5:
            count += 1
    count = min(count, int(actor.proficiency_bonus or 2))
    return {"expected_damage": count * 27, "hostiles_in_area": count, "empty_area": count == 0}


@hook("movement_step_capability")
def scabbard_occupied_step(engine: Any, actor: Any, previous: Any, destination: Any, mode: str) -> bool | None:
    """Recheck actual occupancy only during this native committed source route.

    Menus used observed geometry. An unseen occupant stops the actual native
    step, allowing the resolver's ordinary contact event instead of a menu leak.
    Other sources retain their own passage permissions.
    """
    scope = engine.movement_scope(actor.entity_id) or {}
    if (scope.get("source_id") == PREFIX + "empty_scabbard_step" and _profile(engine, actor)
            and not engine.grid.volume_step_legal(previous, destination, footprint=engine._footprint(actor),
                occupied_cells=engine._occupied_volumes_except(actor.entity_id))):
        return False
    return None


def _bound_sheet(sheet: dict[str, Any], retained: dict[str, Any]) -> dict[str, Any] | None:
    saved = (retained.get("source_states") or {}).get(DRAWN) or {}
    item = saved.get("draw_weapon")
    if not item:
        return None
    if type(item) is not str or not item.strip() or not isinstance(saved.get("acquisition_id"), str):
        raise ValueError("The recorded Draw Weapon has invalid source continuation state")
    result = copy.deepcopy(sheet)
    paths = result.setdefault("path_and_subpath", {})
    # A later sheet cannot silently replace a permanent acquired choice.
    if paths.get("still_water_draw_weapon") and paths["still_water_draw_weapon"] != item:
        raise ValueError("The installed sheet conflicts with this creature's recorded Draw Weapon")
    paths["still_water_draw_weapon"] = item
    return result


@hook("factory_source_sheet")
def retained_draw_weapon(sheet: dict[str, Any], service: Any, project_id: str) -> dict[str, Any] | None:
    return _bound_sheet(sheet, service.journeys.retained_actor("actor:factory." + project_id))


@hook("journey_source_sheet")
def journey_draw_weapon(sheet: dict[str, Any], session: Any, actor_id: str) -> dict[str, Any] | None:
    return _bound_sheet(sheet, session.state["actors"][actor_id])


@hook("journey_acquisition")
def record_permanent_draw_weapon(session: Any, actor_id: str, source: str, payload: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any] | None:
    """Choose the existing acquired feature's physical implement outside combat.

    This grants no feature, Path, weapon or proficiency. Native installed source
    progression and actual carried weapon compilation own eligibility; the
    source-scoped native acquisition command owns player choice and persistence.
    """
    if source != DRAWN:
        return None
    from ..journey import require
    from ..factory_compiler import compile_character
    from ..canonical import canonical_sha256
    from .integrated_weapons import in_group
    require(set(payload) == {"weapon"} and type(payload["weapon"]) is str,
            "Choose one carried Draw Blade as your Draw Weapon; costs no time, action or Stamina.")
    actor = session.state["actors"][actor_id]
    require(not actor["incapacitated"], "An incapacitated creature cannot record a Draw Weapon.")
    require(not (sheet.get("path_and_subpath") or {}).get("still_water_draw_weapon")
            and DRAWN not in (actor.get("source_states") or {}),
            "Your Draw Weapon is already recorded; this procedure cannot replace it or reset a use.")
    bundle = compile_character(sheet, actor_id=actor_id)
    profile = next((r for r in bundle.get("typed_passives", [])
                    if r.get("block") == "still_water_profile" and r.get("feature_id") == DRAWN), {})
    require(DRAWN in profile.get("features", []) and int(profile.get("body_cl", 0)) >= 3,
            "Acquire Drawn from Stillness with actual Body Refining CL 3 before recording its weapon.")
    item = _resolve_draw_identity(profile, payload["weapon"])
    carried = {r.get("weapon_action") for r in bundle["carrying"]["items"]}
    require(item in carried and any(a.get("owner_id") == actor_id
            and "#" not in a["source_definition_id"]
            and a["source_definition_id"] == item
            and in_group((a.get("parameters") or {}).get("typed") or {}, "draw_blade")
            for a in bundle["action_catalog"]), "Choose an actual carried Draw Blade; no item is created by this choice.")
    acquisition = canonical_sha256({"source": DRAWN, "actor_id": actor_id, "weapon": item,
                                   "journey": session.state["journey_id"], "revision": session.state["revision"]})
    actor.setdefault("source_states", {})[DRAWN] = {"draw_weapon": item, "acquisition_id": acquisition}
    session.emit("DRAW_WEAPON_RECORDED", actor_id, source=DRAWN, weapon=item, acquisition_id=acquisition,
                 text="Drawn from Stillness: this carried Draw Blade is permanently recorded as your one Draw Weapon. No time, action or Stamina is spent.")
    return {"sheet": _bound_sheet(sheet, actor), "acquisition_id": acquisition}


@hook("journey_scene_end")
def restore_heaven_scene_use(session: Any, previous: str, current: str) -> None:
    """Only the real world-owner scene boundary restores this printed scene use.

    Native journey encounter import already preserves every paid pool. Rest,
    finish/reopen and another encounter do not call this producer. No Stamina,
    health or unrelated use is recovered here.
    """
    source = PREFIX + "heaven_divided_before_sound"
    for actor_id, actor in session.state["actors"].items():
        bundle = actor["bundle"]
        profile = next((r for r in bundle.get("typed_passives", [])
                        if r.get("block") == "still_water_profile" and r.get("feature_id") == DRAWN), {})
        if source not in profile.get("features", []):
            continue
        pools = {pool for action in bundle["action_catalog"]
                 if ((action.get("parameters") or {}).get("typed") or {}).get("source") == source
                 for pool, amount in action.get("costs", []) if pool.startswith("resource:uses.") and amount == 1}
        for pool in sorted(pools):
            if pool in actor["resources"] and actor["resources"][pool] == 0:
                actor["resources"][pool] = 1
                session.emit("SOURCE_SCENE_USE_RESTORED", actor_id, source=source, resource=pool,
                             previous_scene=previous, scene=current,
                             text="Heaven Divided Before Sound is available again in the new scene. No Stamina is recovered.")


def _body_numbers(info: dict[str, Any]) -> dict[str, int] | None:
    """Owning Body R8 mathematics, using the existing native Path row.

    This is this family's consumer, not a competing shared Path profile format.
    Explicit effective_cl is authoritative; NS1R attainment is capped by sheet CL.
    Body's printed key is Constitution, irrespective of a secondary Path's key.
    """
    paths = info["owner_sheet"].get("path_and_subpath") or {}
    if "source_granted_subpath_feature_record_ids" not in paths and not paths.get("still_water_draw_weapon"):
        return None
    body = next((r for r in paths.get("paths", []) if isinstance(r, dict)
                 and r.get("path_id") == "tianxia.path.body_refining"), None)
    level = body.get("effective_cl", body.get("attainment", 0)) if body else 0
    if (type(level) is not int or level < 0 or (body and "effective_cl" not in body
            and body.get("status") in {"DORMANT", "SUPPRESSED", "INACTIVE"})):
        level = 0
    cl = min(int(info["numbers"].get("cl") or 1), level)
    con, pb = int(info["mods"].get("CON", 0)), int(info["numbers"]["pb"])
    return {"cl": cl, "key_mod": con, "attack_bonus": pb + con, "save_dc": 8 + pb + con}


@hook("compile_action")
def owning_body_numbers(action: Any, info: dict[str, Any]) -> Any:
    if DRAWN not in info["owned_ids"]:
        return None
    body = _body_numbers(info)
    if body is None:
        return None
    params = action.parameters or {}
    typed = params.get("typed") or {}
    bound = (params.get("integrated_selection_source") or typed.get("integrated_selection_source")) == DRAWN
    from ..weapon_delivery import physical_weapon_id
    from .integrated_weapons import in_group
    identity = typed.get("weapon_source_id") or typed.get("delivered_by") or typed.get("opportunity_of") or typed.get("maneuver_of") or physical_weapon_id(action.source_definition_id, params)
    identity = str(identity).split("#", 1)[0]
    weapon = bool(typed.get("weapon")) and in_group(typed, "draw_blade")
    if str(typed.get("source") or "") not in LEVELS and not bound and not weapon:
        return None
    result = action.model_copy(deep=True)
    actual = result.parameters["typed"]
    if weapon:
        actual["still_water_weapon_id"] = identity
    if bound:
        result.parameters["integrated_selection_item"] = identity
        actual["integrated_selection_item"] = identity
    ordinary_object = params.get("still_water_object_basis") == "weapon"
    if str(typed.get("source") or "") in LEVELS or bound:
        actual["hold_victory_until_resolved"] = True
        actual["numbers"].update({k:v for k,v in body.items() if k != "attack_bonus" or not ordinary_object})
    if body["cl"] >= 3:
        result.parameters["typed"]["manual_inline_choice"] = True
    if bound and not ordinary_object:
        result.parameters["typed"]["numbers"]["attack_bonus"] += int(typed.get("magic_bonus") or 0)
        weapon = result.parameters["typed"]["weapon"]
        weapon.update(ability="CON", ability_modifier=body["key_mod"])
    return result


@hook("compile_actions")
def independent_body_attack_profile(info: dict[str, Any]) -> list[Any] | None:
    """Retain another family's integration method beside the Body CAM option.

    Normally the shared source-bound Constitution variant already supplies it.
    An independent integration deliberately has no binding guard, so publish the
    distinct Body method rather than overwrite that other public profile.
    """
    if DRAWN not in info["owned_ids"] or _body_numbers(info) is None:
        return None
    from .integrated_weapons import integrated_bases, binding_metadata, constitution_typed, in_group
    out = []
    for base in integrated_bases(info):
        typed = base.parameters.get("typed") or {}
        if not in_group(typed, "draw_blade") or binding_metadata(info, typed).get("integrated_selection_source") == DRAWN:
            continue
        item = _item(typed)
        variant = constitution_typed(info, typed)
        guard = {"integrated_selection_source": DRAWN, "integrated_selection_item": item}
        variant.update(guard)
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#still_water_cultivation",
            "display_name": base.display_name + " (Body cultivation)",
            "parameters": {**base.parameters, **guard, "still_water_cultivation": True, "typed": variant}}))
    return out or None


@hook("ai_player_only_action_allowed")
def draw_object_ai_option(engine: Any, actor: Any, action: Any) -> bool | None:
    """Expose owned Draw Weapon object attacks to AI through ordinary legal candidates."""
    if (action.parameters.get("still_water_object") is True
            and _profile(engine, actor) and _available(engine, actor, DRAWN)):
        return True
    return None


@hook("compile_actions")
def draw_object_profiles(info: dict[str, Any]) -> list[Any] | None:
    """Publish the bound physical weapon's ordinary and Body-CAM object modes.

    Native object dispatch owns the attack sequence and destructible state. This
    preserves the actual weapon instead of borrowing the generic best chassis.
    No item, proficiency or additional attack is granted.
    """
    body = _body_numbers(info)
    if DRAWN not in info["owned_ids"] or body is None or body["cl"] < 3:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .integrated_weapons import in_group, constitution_typed
    out = []
    for base in info["actions"]:
        typed = base.parameters.get("typed") or {}
        attack = next((r for r in typed.get("effects", []) if r.get("type") == "attack"), None)
        if (base.economy != EconomyKind.ACTION or ("#" in base.source_definition_id and not base.source_definition_id.endswith('#thrown'))
                or attack is None or typed.get('unarmed_option') or not in_group(typed, "draw_blade")):
            continue
        for basis in ("weapon", "cultivation"):
            variant = copy.deepcopy(typed) if basis == "weapon" else constitution_typed(info, typed)
            variant.update(weapon_source_id=base.source_definition_id, object_weapon=copy.deepcopy(variant["weapon"]),
                object_weapon_group="weapon", object_melee=not variant.get("range_ft"), object_attack_scope=True,
                effects=[{"type":"object_attack", "count":int(attack.get("count") or 1)}])
            out.append(base.model_copy(update={"source_definition_id":base.source_definition_id+"#still_water_object_"+basis,
                "display_name":"Draw Weapon object attack: "+base.display_name.removesuffix(" attack")
                    + (" (Body cultivation)" if basis == "cultivation" else " (Constitution)"),
                "target_kind":"OBJECT", "parameters":{**base.parameters, "typed":variant, "object_attack":True,
                    "player_only":True, "still_water_object":True, "still_water_object_basis":basis,
                    "ai_player_only_action":True,
                    "integrated_selection_source":DRAWN, "integrated_selection_item":base.source_definition_id,
                    "description":"Attack an object with your recorded Draw Weapon, using the normal Attack action's attacks. Constitution replaces Strength or Dexterity; the Body cultivation option uses your Body attack modifier. No extra attacks or Stamina cost."}}))
    return out or None


def _draw_weapon_type(ctx: Any, target_id: str, kinds: list[str], index: int) -> str | None:
    if not _profile(ctx.engine, ctx.actor) or not _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return None
    kinds = list(dict.fromkeys(str(k).upper() for k in kinds))
    if len(kinds) <= 1:
        return kinds[0] if kinds else None
    from .needle import ask, checkpoint_id
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,"draw_weapon_type",target_id,index),ctx.actor,
        "choice:needle.still_water_weapon_damage_type",kinds,labels={k:k.title()+" weapon damage" for k in kinds},
        name="Drawn from Stillness",feature_id=DRAWN,target_id=target_id,
        prompt="Draw Weapon attack: choose the weapon damage type for this attack against the selected creature or object. This choice adds no action or Stamina cost.")
    return chosen[0] if chosen else kinds[0]


@hook("attack_damage_type_choice")
def draw_weapon_type(ctx: Any, attack: Any, target: Any, kinds: list[str], index: int) -> str | None:
    return _draw_weapon_type(ctx,target.entity_id,kinds,index)


@hook("object_attack_prepare")
def draw_object_prepare(ctx: Any, obj: Any, index: int) -> bool | None:
    if not _profile(ctx.engine, ctx.actor) or not _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return None
    from .objects import attack_reaches
    from .hand_occupancy import weapon_allowed
    if not attack_reaches(ctx.engine, ctx.actor, ctx.action, obj) or weapon_allowed(ctx.engine,ctx.actor,ctx.action) is False:
        return False
    draw_constitution(ctx)
    draw_committed_weapon(ctx,None,{}, {},index+1)
    ctx.typed["object_weapon"] = copy.deepcopy(ctx.typed["weapon"])
    from .hand_occupancy import versatile_die_sides
    sides = versatile_die_sides(ctx.engine,ctx.actor,ctx.action)
    if sides and ctx.typed["object_weapon"].get("damage"):
        ctx.typed["object_weapon"]["damage"]["sides"] = sides
    if (_in_posture(ctx.actor) and _available(ctx.engine,ctx.actor,MOON)
            and not ctx.actor.turn_flags.get("still_water_posture_attack")):
        ctx.actor.turn_flags["still_water_posture_attack"] = 1
        ctx.damage_cache["still_water_posture_attack"] = 1
    return True


@hook("object_attack_modes")
def draw_object_mode(ctx: Any, obj: Any, index: int) -> str | None:
    if (_profile(ctx.engine,ctx.actor) and _is_draw(ctx.engine,ctx.actor,ctx.typed)
            and ctx.damage_cache.get("still_water_posture_attack")):
        return "ADVANTAGE"
    return None


@hook("object_attack_damage_type")
def draw_object_type(ctx: Any, obj: Any, index: int, kind: str) -> str | None:
    from ..typed_executor import damage_choices
    kinds = damage_choices({},ctx.typed.get("weapon") or {}) or [kind]
    if _profile(ctx.engine,ctx.actor).get("heavenly"):
        kinds = [*kinds,"FORCE"]
    return _draw_weapon_type(ctx,obj.object_id,kinds,index+1)


@hook("object_attack_packets")
def draw_object_packets(ctx: Any, obj: Any, index: int, critical: bool) -> list[tuple[int,str]] | None:
    if not _profile(ctx.engine,ctx.actor) or not _is_draw(ctx.engine,ctx.actor,ctx.typed):
        return None
    from .needle import ask,checkpoint_id
    from ..gate2_runtime_models import DiceSpec
    packets,moves=[],[]
    actor,engine=ctx.actor,ctx.engine
    if _rolls_this_turn(engine,actor)==1 and actor.turn_flags.get("_round_first_cut")!=_stamp(engine):
        chosen=ask(engine,ctx.intent,checkpoint_id(engine,"first_cut",obj.object_id,index),actor,
            "choice:needle.first_cut",["slashing","force"],allow_decline=True,
            labels={k:f"Add {actor.proficiency_bonus} {k.title()} damage, then optionally move 5 feet without provoking" for k in ("slashing","force")},
            name="First Cut",feature_id=DRAWN,target_id=actor.entity_id,
            prompt="First Cut: your first attack hit this object. Add Proficiency Bonus as Slashing or Force, then optionally move 5 feet without provoking? Costs no action or Stamina.")
        if chosen:
            actor.turn_flags["_round_first_cut"]=_stamp(engine)
            packets.append((int(actor.proficiency_bonus),chosen[0].upper()))
            moves.append((5,"choice:needle.first_cut_move","First Cut"))
    if ctx.damage_cache.get("still_water_posture_attack") and _in_posture(actor) and _available(engine,actor,MOON):
        chosen=ask(engine,ctx.intent,checkpoint_id(engine,"posture_type",obj.object_id,index),actor,
            "choice:needle.still_water_posture_type",["slashing","force"],
            labels={k:"3d8 "+k.title()+" damage" for k in ("slashing","force")},name="Moon Reflected Before Motion",feature_id=MOON,target_id=actor.entity_id,
            prompt="Moon Reflected Before Motion: add 3d8 Slashing or Force to the object hit, restore Speed, then optionally move half your Speed without provoking. No extra cost.") or ["slashing"]
        ctx.damage_cache["still_water_end_posture"] = 1
        roll=engine.roller.roll(DiceSpec(count=3,sides=8),actor_id=actor.entity_id,reason=f"DAMAGE:{MOON}:object:{index+1}",critical=critical)
        engine._record_roll(roll)
        engine._append_event("DAMAGE_ROLLED",MOON,actor_id=actor.entity_id,target_ids=(obj.object_id,),payload=roll.model_dump(mode="json"))
        packets.append((int(roll.total),chosen[0].upper()))
        moves.append((-1,"choice:needle.still_water_posture_move","Still-Water Posture"))
    ctx.damage_cache["still_water_followup_moves"]=moves
    return packets


@hook("object_attack_resolved")
def draw_object_resolved(ctx: Any, obj: Any, hit: bool, index: int) -> None:
    if not _profile(ctx.engine,ctx.actor) or not _is_draw(ctx.engine,ctx.actor,ctx.typed):
        return
    if not hit and ctx.damage_cache.get("still_water_posture_attack"):
        _end_posture(ctx.engine,ctx.actor,"ATTACK_RESOLVED")
    ctx.damage_cache.pop("still_water_posture_attack",None)
    draw_followup_movement(ctx,None,hit,index+1)
    sheath_committed_weapon(ctx,None,hit,index+1)


# Explicit world-owner source authority; never infer it from material or names.
_OBJECT_KINDS = {'unattended_object','vehicle','structure','temporary_barrier','terrain_section','formation_anchor','other'}
_PROTECTIONS = {'permanent_artifact','immortal','void','physical_force_immune'}
_MOVEMENT_LOCKS = {'total_cover','sealed_formation','spatial_lock','higher_source_movement'}


@hook('fact_admission_schema')
def draw_world_schema(session: Any, source: str, subject: str, kind: str) -> dict[str,Any] | None:
    if source != DRAWN or kind not in {'object_authority','movement_authority'}:
        return None
    bundle = session.state['actors'].get(subject,{}).get('bundle',{})
    if not any(r.get('block')=='still_water_profile' and r.get('feature_id')==DRAWN
               for r in bundle.get('typed_passives',())):
        return None
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
        'description':'Explicit source authority for a real object or mapped movement restriction. This grants no feature, item, activity or activation.'}


@hook('fact_admission_validate')
def draw_world_validate(session: Any, source: str, subject: str, kind: str, scope: str, value: Any) -> bool | None:
    if source != DRAWN or kind not in {'object_authority','movement_authority'}:
        return None
    from ..journey import require,integer
    require(type(value) is dict and type(value.get('source_id')) is str and 0<len(value['source_id'])<=240
            and integer(value.get('source_cl')), 'Name the actual Source Rule and its nonnegative whole Source CL; leave unknown authority unrecorded.')
    if kind=='object_authority':
        require(set(value)=={'object_id','source_id','source_cl','target_kind','protections'}
                and value['object_id']==scope and value['target_kind'] in _OBJECT_KINDS
                and isinstance(value['protections'],list) and len(value['protections'])==len(set(value['protections']))
                and set(value['protections'])<=_PROTECTIONS, 'Record one actual object, its printed target class and explicit protected properties.')
        if hasattr(session,'engine'):
            require(scope in session.engine.state.objects,'Choose a real native battlefield object.')
        else:
            require(any('object:map.'+str(r['id'])==scope for r in session.state['battlefield'].get('map_objects',())),
                    'Choose an object actually placed in this journey.')
    else:
        require(set(value)=={'cells','source_id','source_cl','restriction'} and value['restriction'] in _MOVEMENT_LOCKS
                and isinstance(value['cells'],list) and value['cells'], 'Map the actual total cover, sealed Formation, spatial lock or higher-Source movement authority.')
        for cell in value['cells']:
            require(isinstance(cell,list) and len(cell)==3 and all(integer(v) for v in cell)
                    and session.grid.in_bounds(tuple(cell[:2])), 'Use actual whole mapped coordinates for the restriction.')
    return True


def draw_world_records(engine: Any, viewer: Any, kind: str, *, mechanical: bool = False) -> list[Any]:
    from ..combat_world_facts import records,clock
    latest={}
    for row in records(engine):
        if row['source']==DRAWN and row['kind']==kind:
            latest[row['scope']]=row
    return [r for r in latest.values() if r.get('authority')=='table_owner' and r['expires_at']>clock(engine)
            and (mechanical or viewer.entity_id in (r['subject'],*r['readers']))]


def _object_draw_authority(engine: Any,actor: Any,obj: Any) -> Any:
    row=next((r for r in draw_world_records(engine,actor,'object_authority',mechanical=True)
              if r['value']['object_id']==obj.object_id),None)
    return row['value'] if row else None


def _body_object_delivery(engine: Any,actor: Any,source: str) -> bool:
    if not _profile(engine,actor) or not _available(engine,actor,DRAWN):
        return False
    if source==PREFIX+'heaven_divided_before_sound':
        frame=_heaven_route_frame(engine,actor)
        return frame is not None and _available(engine,actor,source)
    action=engine.action_catalog.get(source)
    return action is not None and _is_draw(engine,actor,action.parameters.get('typed') or {})


@hook('object_damage_modifiers')
def heavenly_object_modifiers(engine: Any,actor: Any,obj: Any,packets: Any,source: str) -> Any:
    if not _profile(engine,actor).get('heavenly') or not _body_object_delivery(engine,actor,source):
        return None
    authority=_object_draw_authority(engine,actor,obj)
    if (authority is None or authority['source_cl']>int(_profile(engine,actor)['body_cl'])
            or authority['target_kind']=='other' or authority['protections']
            or (authority['target_kind']=='unattended_object' and not obj.unattended)):
        return None
    return {'multiplier':2,'ignore_threshold':True,
            'ignore_resistance_types':['BLUDGEONING','PIERCING','SLASHING','FORCE']}


@hook('object_damage_admission')
def protected_draw_object(engine: Any,actor: Any,obj: Any,packets: Any,source: str,**context: Any) -> bool | None:
    if not _body_object_delivery(engine,actor,source):
        return None
    authority=_object_draw_authority(engine,actor,obj)
    return False if authority and 'physical_force_immune' in authority['protections'] else None


@hook('movement_step_capability')
def heaven_source_authority(engine: Any,actor: Any,previous: Any,destination: Any,mode: str) -> bool | None:
    frame=_heaven_route_frame(engine,actor)
    if frame is None or not _profile(engine,actor):
        return None
    # Only this printed line claims the special crossing permissions. An
    # unrelated bonus step cannot borrow immunity to the world's movement locks.
    scope=engine.movement_scope(actor.entity_id) or {}
    if scope.get('source_id') != PREFIX+'heaven_divided_before_sound':
        return None
    cells=set(engine._actor_volume(actor,destination))
    for row in draw_world_records(engine,actor,'movement_authority',mechanical=True):
        value=row['value']
        if cells.intersection(map(tuple,value['cells'])) and (value['restriction']!='higher_source_movement'
                or value['source_cl']>int(_profile(engine,actor)['body_cl'])):
            return False
    return None


@hook('observer_information_rows')
def draw_known_authority(engine: Any,viewer: Any) -> Any:
    if not _profile(engine,viewer):
        return None
    result=[]
    for kind in ('object_authority','movement_authority'):
        for row in draw_world_records(engine,viewer,kind):
            value=row['value']
            result.append({'kind':'declaration','viewer_id':viewer.entity_id,'authority_actor_id':'table_owner',
                'source_id':DRAWN,'details':copy.deepcopy(value),
                'label':'Known object source authority' if kind=='object_authority' else 'Known movement restriction'})
    return result or None


@hook('held_weapon_impairment_allowed')
def heavenly_draw_remains_usable(ctx: Any,holder: Any,item: Any,operation: str,qualifiers: Any) -> bool | None:
    """Protect only the actual wielded Draw Weapon from the printed mundane causes.

    Ordinary Disarm may still drop it: the feature prevents break/uselessness,
    rather than granting immunity to every possession or equipment operation.
    """
    if (not _profile(ctx.engine,holder).get('heavenly') or not _available(ctx.engine,holder,DRAWN)
            or qualifiers.get('mundane') != 1 or qualifiers.get('cause') not in {'disarm','rust','dulling','weapon_breaking'}):
        return None
    selected=draw_identity(ctx.engine,holder)
    from .hand_occupancy import weapon_grips
    if selected not in item.get('weapon_actions',()) or selected not in weapon_grips(ctx.engine,holder):
        return None
    note(ctx.engine,DRAWN,holder,'Heavenly Fist keeps '+item['name']+' usable while you wield it; the mundane effect does not break or disable your Draw Weapon. The triggering use remains spent.')
    return False


@hook('maneuvers')
def horizons_attack_action_slots(info: dict[str,Any]) -> Any:
    """Reuse the public single-attack remainder ledger and actual compiled slots."""
    profile=next((r for r in info.get('passives',()) if r.get('block')=='still_water_profile'),None)
    if profile is None or ONE_BREATH not in profile['features'] or profile['body_cl']<10:
        return None
    from .special_attacks import replacement_actions,REST
    from ..gate2_runtime_models import EconomyKind
    from ..weapon_delivery import delivery_kind
    existing={a.source_definition_id for a in info['actions']}
    made=[a for a in replacement_actions(info) or [] if a.source_definition_id not in existing]
    for action in info['actions']:
        typed=action.parameters.get('typed') or {}
        rows=typed.get('effects') or []
        if (action.economy==EconomyKind.ACTION and '.weapon.' in action.source_definition_id
                and rows and rows[0].get('type')=='attack' and delivery_kind(typed,rows[0],action.parameters)=='weapon'):
            typed['attack_action']=True
        if typed.get('unarmed_option') and action.economy==EconomyKind.ACTION:
            identity=action.source_definition_id+'.remaining_attack'
            if identity not in existing:
                actual=copy.deepcopy(typed)
                actual['effects']=actual['effects'][:1]  # exactly one ordinary Grapple/Shove slot
                made.append(action.model_copy(update={'source_definition_id':identity,'economy':EconomyKind.NONE,
                    'display_name':action.display_name+' (remaining attack)',
                    'parameters':{**action.parameters,'typed':actual,REST:True,'expected_damage':0}}))
                existing.add(identity)
        if typed.get('source')==ONE_BREATH and action.parameters.get('attack_line')==ONE_BREATH:
            identity=action.source_definition_id+'.remaining_attack_line'
            if identity not in existing:
                actual=copy.deepcopy(typed)
                for row in actual['effects']:
                    if row.get('type')=='attack_line_after':row['remaining']=0
                made.append(action.model_copy(update={'source_definition_id':identity,'economy':EconomyKind.NONE,
                    'display_name':action.display_name+' (replace two remaining attacks)', 'costs':((STAMINA,2),),
                    'parameters':{**action.parameters,'typed':actual,'still_water_remaining_line':True,
                        'description':'Replace exactly two unspent attacks of your current Attack action with this line. Costs 2 Stamina; once per turn.'}}))
                existing.add(identity)
    return {'actions':made,'rows':[]} if made else None


@hook('technique_accepted')
def horizons_committed_use(engine: Any,actor: Any,action: Any) -> None:
    typed=action.parameters.get('typed') or {}
    if typed.get('source')!=ONE_BREATH or not _profile(engine,actor):
        return
    from .attack_lines import reserve_use
    from .special_attacks import FLAG
    reserve_use(engine,actor,ONE_BREATH,typed.get('attack_line_turn_clock'))
    if action.parameters.get('still_water_remaining_line'):
        remaining=int(actor.turn_flags.get(FLAG,0))
        if remaining<2:raise ValueError('One Breath needs two actual remaining attacks')
        actor.turn_flags[FLAG]=remaining-2
    elif not action.parameters.get('still_water_inline_line'):
        remaining=next((int(row.get('remaining',0)) for row in typed.get('effects',()) if row.get('type')=='attack_line_after'),0)
        actor.turn_flags[FLAG]=int(actor.turn_flags.get(FLAG,0))+remaining


@hook('attack_line_continuation')
def horizons_native_slots(ctx: Any,row: Any) -> bool | None:
    if ctx.typed.get('source')==ONE_BREATH and _profile(ctx.engine,ctx.actor):
        # Already installed at acceptance, even if the line was countered.
        # Actual native remainder candidates own individual choices/countdown.
        return True
    return None


@hook('attack_slot_replacement')
def horizons_during_attack(ctx: Any,attack: Any,target: Any,index: int,remaining: int) -> int | None:
    if (not _profile(ctx.engine,ctx.actor) or not _available(ctx.engine,ctx.actor,ONE_BREATH)
            or not ctx.typed.get('attack_action') or ctx.typed.get('granted_attack') or ctx.typed.get('reaction_attack')
            or remaining<2 or not ctx.actor.active):
        return None
    from .attack_lines import attack_line_once
    from .choice_costs import payable
    from .hand_occupancy import weapon_grips,weapon_allowed
    from .needle import ask,checkpoint_id,cell_id
    from ..gate2_runtime_models import Position,EconomyKind,CandidateKind
    payment=payable(ctx.actor,STAMINA,2)
    identity=draw_identity(ctx.engine,ctx.actor)
    base=ctx.engine.action_catalog.get(identity)
    action=next((a for a in ctx.engine.action_catalog.values() if a.owner_id==ctx.actor.entity_id
        and a.economy==EconomyKind.ACTION and a.parameters.get('attack_line')==ONE_BREATH
        and (a.parameters.get('typed') or {}).get('attack_line_of')==identity),None)
    if (payment is None or base is None or action is None or identity not in weapon_grips(ctx.engine,ctx.actor)
            or weapon_allowed(ctx.engine,ctx.actor,base) is False
            or attack_line_once(ctx.engine,ctx.actor,None,action) is False):
        return None
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'horizons_replace',ctx.source,index),ctx.actor,
        'choice:needle.still_water_horizons_replace',['replace'],allow_decline=True,default='decline',
        labels={'replace':f'Replace attacks {index} and {index+1} with a 30-foot line; spend 2 Stamina'},
        feature_id=ONE_BREATH,target_id=ctx.actor.entity_id,payment=payment,
        prompt=f'One Breath, Three Horizons: {remaining} attacks remain in this Attack action. Replace the next two with the line? Costs 2 Stamina; once per turn.')
    if not chosen:return None
    origin=ctx.actor.position
    aims={}
    for z in range(max(0,origin.z-6),origin.z+7):
        for y in range(max(0,origin.y-6),min(ctx.engine.grid.height,origin.y+7)):
            for x in range(max(0,origin.x-6),min(ctx.engine.grid.width,origin.x+7)):
                p=Position(x=x,y=y,z=z)
                if p!=origin and ctx.engine.grid.distance_ft(origin,p)<=30:aims[cell_id(p)]=p
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'horizons_aim',ctx.source,index),ctx.actor,
        'choice:needle.still_water_horizons_aim',sorted(aims),minimum=1,maximum=1,
        labels={key:f'Toward grid ({p.x}, {p.y}), {p.z*5} feet high' for key,p in aims.items()},
        feature_id=ONE_BREATH,target_id=ctx.actor.entity_id,payment=payment,
        prompt='One Breath, Three Horizons: choose the line direction from your current space. Every other creature intersected saves; total cover stops the line. The replacement costs 2 Stamina.')
    if not chosen:raise ValueError('Choose a line direction')
    from .. import typed_executor as te
    actual=action.model_copy(deep=True)
    actual.parameters['still_water_inline_line']=True
    for row in actual.parameters['typed']['effects']:
        if row.get('type')=='attack_line_after':row['remaining']=0
    aim=aims[chosen[0]]
    candidate=ctx.engine._candidate(CandidateKind.ACTION,ctx.actor,actual.source_definition_id,actual.display_name,destination=aim)
    payment.pay(ctx.engine,ctx.actor,actual.source_definition_id)
    te.resolve_typed(ctx.engine,ctx.actor,None,actual,candidate,ctx.intent)
    return 2


@hook('condition_data_additions')
def draw_condition_source(ctx: Any,subject: Any,row: Any) -> Any:
    profile=_profile(ctx.engine,ctx.actor)
    source=ctx.source if ctx.source in LEVELS else ctx.typed.get('source')
    if not profile or source not in LEVELS:
        return None
    level=row.get('still_water_source_cl',profile['body_cl'])
    if type(level) is not int or level<0:
        raise ValueError('A Still-Water condition needs its actual activation Source CL')
    return {'source_cl':level,'source_feature_id':source,'source_feature_level':LEVELS[source]}
