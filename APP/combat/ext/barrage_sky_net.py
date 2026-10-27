"""Sky-Net Suppression's printed choice for the creature that enters its area of threatening projectiles.

Owner text (``APP/authority/typed_mechanics/rules_text.json``,
``TAL_BARRAGE_SKY_NET_SUPPRESSION``):

    "A hostile creature that enters the area for the first time on a turn or starts its turn inside chooses:
    Slow Down -- movement costs 2 feet for every 1 foot traveled; cannot Dash; attacks have a -2 penalty until
    the start of its next turn. Push Through -- Make one ranged weapon attack against that creature. On a hit,
    deal weapon damage normally and reduce Speed by 10 feet until the start of its next turn. Each creature
    triggers this attack once per turn."

The typing applied *both* branches to every hostile creature in the area, so each one lost 10 feet of Speed and
attacked at -2 whether it chose or not, and the printed choice was left to the GM. The reviewed zone now carries one
explicit trigger whose effect is :func:`sky_net` below; the area's own per-turn trigger clock
(``combat/zones.py`` ``_run``) already gives "for the first time on a turn" and "once per turn".

Whose decision it is: the printed line says the creature chooses, so the question is put to that creature's
controller. ``needle.ask`` routes to its explicit chooser, including on another actor's intent. The creature chooses
the branch; the area's creator chooses among usable weapons for Push Through. Each player's decision stays theirs,
and the built-in AI answers for its own actors.

Inert without the talent: the effect runs only from the compiled Sky-Net Suppression zone, so no other zone, area or
creature reaches it. Nothing is written to the fight outside the zone and the two printed conditions, and the choice is
not remembered (the printed choice is made each time the trigger fires, which is once per creature per turn).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

KEY = "TAL_BARRAGE_SKY_NET_SUPPRESSION"
SLOW = "condition:typed.sky_net_slow_down"
SLOWED_LABEL = "Slow Down (Sky-Net Suppression)"
EFFECT = "barrage_sky_net"


def _zones(engine: Any, owner: Any) -> Any:
    return [zone for zone in (getattr(engine.state, "zones", {}) or {}).values()
            if zone.owner_id == owner.entity_id and zone.active
            and str((zone.trigger_profile or {}).get("kind") or "") != "MAP_TERRAIN_USAGE"
            and str((zone.trigger_profile.get("source_profile") or {}).get("mechanic_id") or "") == KEY]


def _holds(actor: Any, condition_id: str) -> bool:
    return any(row.condition_id == condition_id for row in (actor.conditions or {}).values())


@hook("movement_step_surcharge")
def slowed_movement(engine: Any, actor: Any, mode: str) -> int | None:
    """"Slow Down: movement costs 2 feet for every 1 foot traveled." Each 5-foot step costs one square more.

    The printed surcharge is the movement-step query's own contract: feet added per adjacent grid step, before the
    dragging multiplier, read from a condition the printed effect applied.
    """
    if not _holds(actor, SLOW):
        return None
    return engine.grid.square_size_ft


@hook("attack_bonus")
def slowed_attack(ctx: Any, actor: Any) -> int | None:
    """Slow Down's other printed clause: "attacks have a -2 penalty until the start of its next turn".

    A flat penalty on the attacker's own roll is the engine's own ``attack_bonus`` seam (the one Exhaustion uses), so
    the printed number reaches the roll instead of waiting for the GM.
    """
    return -2 if _holds(actor, SLOW) else None


@hook("d20_bonus")
def slowed_native_attack(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Native attacks share the d20 checkpoint; typed attacks already paid the penalty above.

    Use the actual transient resolver spec, not actor membership or catalogue
    kind: compiled characters can own native attacks, and typed effects such as
    traps can call the native resolver without dispatching attack_bonus.
    """
    if not str(roll.reason).startswith("ATTACK:"):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not _holds(actor, SLOW):
        return None
    scopes = getattr(engine, "_d20_scopes", ())
    frame = scopes[-1] if scopes else {}
    spec = frame.get("spec") or {}
    if (frame.get("kind") == "attack" and frame.get("actor_id") == roll.actor_id
            and roll.reason == f"ATTACK:{frame.get('source_id')}:{frame.get('attack_index', 1)}"
            and spec.get("typed") is not None and callable(spec.get("before_attack_d20"))):
        return None  # block_attack already dispatched attack_bonus for this exact strike
    return {"source_id": KEY, "bonus": -2}


@effect(EFFECT)
def sky_net(ctx: Any, row: dict[str, Any]) -> None:
    """The creature that entered the area chooses Slow Down or Push Through, and only that branch happens."""
    from .needle import CHOICE, ask, checkpoint_id

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active or creature.team_id == owner.team_id or not owner.active:
        return
    if not _zones(engine, owner):
        return  # the area is gone (or this is not a Sky-Net area): nothing to answer for.
    options = ["slow_down", "push_through"]
    labels = {"slow_down": "Slow Down: each foot of movement costs 2 feet; cannot Dash; attacks take a -2 penalty "
                           "until the start of your next turn",
              "push_through": f"Push Through: {owner.display_name} makes one ranged weapon attack against "
                              f"{creature.display_name}; on a hit, normal weapon damage and Speed reduced by "
                              "10 feet until the start of your next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SKY_NET", owner.entity_id, creature.entity_id),
                 creature, CHOICE + "sky_net", options, labels=labels, name="Sky-Net Suppression", feature_id=KEY,
                 target_id=creature.entity_id,
                 prompt=f"Sky-Net Suppression: {creature.display_name} enters or starts its turn in "
                        f"{owner.display_name}'s net of projectiles. Choose Slow Down or Push Through. "
                        "This choice costs no Action or resource.")
    if "slow_down" in picked:
        _slow_down(ctx, creature)
    elif "push_through" in picked:
        _push_through(ctx, creature)


def _slow_down(ctx: Any, creature: Any) -> None:
    from ..typed_executor import run_effects

    ctx.rider(f"Sky-Net Suppression: {creature.display_name} slows down. Each foot it moves now costs 2 feet, it "
              f"cannot Dash, and its attacks are at -2 until the start of its next turn.")
    run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "sky_net_slow_down",
                       "duration": "until_start_of_next_turn",
                       "condition_data": {"rule": {"no_dash": True}},
                       "evidence": "Slow Down: movement costs 2 feet for every 1 foot traveled; cannot Dash; "
                                   "attacks have a -2 penalty until the start of its next turn"}])


def _push_through(ctx: Any, creature: Any) -> None:
    """One ranged weapon attack with the fighter's own weapon, and on a hit a 10-foot Speed loss."""
    from copy import deepcopy
    from ..typed_executor import Context, run_effects
    from .weapon_actions import weapon_attacks
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    from .ammunition import ammunition_choice
    from ..typed_reactions import attack_reaches
    from .needle import CHOICE, ask, checkpoint_id

    engine, owner = ctx.engine, ctx.actor
    if not engine._line_of_sight_actor_to_actor(owner, creature):
        ctx.rider(f"Sky-Net Suppression: {owner.display_name} has no clear line to {creature.display_name}, "
                  "so no weapon attack is made.")
        return
    available = available_weapons(engine, owner)
    rows = [(row, typed, attack) for row, typed, attack, kind in weapon_attacks(engine.action_catalog.values(), owner.entity_id)
            if kind in ("ranged", "thrown") and row.source_definition_id.split("#")[0] in available
            and weapon_allowed(engine, owner, row) is not False]
    rows = [(base, typed, attack) for base, typed, attack in rows
            if ammunition_choice(engine, owner, None, base) is not False
            and attack_reaches(engine, owner, creature, {**attack, "attack_kind": "weapon_ranged"},
                               typed.get("long_range_ft") or typed.get("range_ft") or base.range_ft, action=base)]
    if not rows:
        ctx.rider(f"Sky-Net Suppression: {creature.display_name} pushes through, but {owner.display_name} has no "
                  f"usable ranged or thrown weapon that can reach it with ammunition remaining.")
        return
    base, typed, attack = rows[0]
    if len(rows) > 1:
        options = [base.source_definition_id for base, _, _ in rows]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "SKY_NET_WEAPON", owner.entity_id, creature.entity_id),
                     owner, CHOICE + "sky_net_weapon", options,
                     labels={base.source_definition_id: f"{base.display_name.removesuffix(' attack')}: one attack against "
                             f"{creature.display_name}; normal weapon damage on a hit, Speed reduced by 10 feet "
                             "until the start of its next turn; uses one projectile" for base, _, _ in rows},
                     name="Sky-Net Suppression", feature_id=KEY, target_id=creature.entity_id,
                     prompt=f"Sky-Net Suppression: {creature.display_name} chose Push Through. "
                            f"Choose {owner.display_name}'s weapon for the attack. This costs no Action or Reaction.")
        if not picked:
            return
        base, typed, attack = next(entry for entry in rows if entry[0].source_definition_id == picked[0])
    attack = deepcopy(attack)
    attack.pop("count_by_cl", None)
    attack["count"] = 1
    attack["granted_attack_root"] = True
    attack["attack_kind"] = "weapon_ranged"
    attack["on_hit"] = [*(attack.get("on_hit") or []),
                        {"type": "speed", "applies_to": "target", "flat": -10,
                         "duration": "until_start_of_next_turn",
                         "evidence": "Push Through: reduce Speed by 10 feet until the start of its next turn"}]
    shot = {**deepcopy(typed), "effects": [attack], "reaction_attack": True, "granted_attack": True,
            "reaction_range_ft": int(typed.get("long_range_ft") or typed.get("range_ft") or base.range_ft or 0)}
    ctx.rider(f"Sky-Net Suppression: {creature.display_name} pushes through and is shot at with "
              f"{base.display_name.removesuffix(' attack')}.")
    run_effects(Context(engine, owner, base, ctx.intent, shot, [creature], creature, {}), shot["effects"])
