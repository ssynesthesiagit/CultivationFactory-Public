"""Spear sphere core mechanics (worker martial, 2026-09-28, "automate every aspect before another playtest").
Mo Ruo owns almost all of this sphere; Wen Yaoxue, Nixian Weave, Chen Lan and Lingfeng the Ember Artisan share a
handful of records.

Spear Thrust, Dragon-Spear Charge, Flowers in the Storm and Intercepting Thrust all read "make one attack with
an approved Spear weapon" (or "make an attack using an approved Spear weapon") -- the same shape Wen Xue's
Sabers work found for "make one saber attack" (combat/ext/wenxue_sabers.py): it does not match
factory_authoring.typed_structure.weapon_delivery's regex (which wants "melee weapon attack"/"weapon attack",
not "an approved Spear weapon attack"), so none of these ever got the character's real weapon dice --
confirmed against the built authority (``weapon_delivery`` is null on all four). Fixed the same way: an
``attach_spear_weapon`` effect placed just before each "attack" effect in reviewed_final.d/martial.json's own
effects/options lists, so ``run_effects``'s shared Context has ``ctx.typed["weapon"]`` set before the "attack"
effect (whose on_hit already carries a plain ``{"type": "damage", "weapon_damage": true}``) resolves it.

Spear Guard's damage-reduction reaction needs no weapon of its own (it reduces an incoming hit, not delivering
one) and is untouched by this file.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .weapon_hits import available_weapons

SPEAR_WORDS = ("spear", "pike", "lance", "trident")


def spear_weapons(ctx: Any) -> dict[str, Any]:
    """One action per approved weapon; technique and thrown variants share its identity."""
    return available_weapons(ctx.engine, ctx.actor, SPEAR_WORDS)


def choose_spear(ctx: Any, *, require_ready: bool = False) -> Any:
    from . import needle

    from ..weapon_delivery import ready_weapons
    weapons = ready_weapons(ctx.engine, ctx.actor, SPEAR_WORDS) if require_ready else spear_weapons(ctx)
    if not weapons:
        ctx.rider("No approved Spear weapon found.")
        return None
    choices = list(weapons)
    picked = choices if len(choices) == 1 else needle.ask(
        ctx.engine, ctx.intent, f"SPEAR_WEAPON:{ctx.source}", ctx.actor, "choice:needle.spear_weapon", choices,
        labels={key: action.display_name for key, action in weapons.items()},
        prompt=f"{ctx.action.display_name}: choose the approved Spear weapon", preferred=choices[:1])
    return weapons.get(picked[0]) if picked else None


@effect("bind_spear_weapon")
def bind_spear_weapon(ctx: Any, effect_row: dict[str, Any]) -> None:
    weapon = choose_spear(ctx)
    # Empty binding must not silently broaden the bonus when no weapon exists.
    ctx.damage_cache["_on_hit_weapon_id"] = weapon.source_definition_id.split("#", 1)[0] if weapon else "NO_WEAPON"


@effect("attach_spear_weapon")
def attach_spear_weapon(ctx: Any, effect_row: dict[str, Any]) -> None:
    if ctx.typed.get("weapon"):
        return  # already resolved
    action = choose_spear(ctx, require_ready=bool(effect_row.get("require_ready")))
    if action is None:
        ctx.rider("No approved Spear weapon found to deliver this Spear attack's damage.")
        return
    ctx.typed["weapon"] = action.parameters["typed"]["weapon"]
    ctx.typed["weapon_source_id"] = action.source_definition_id.split("#", 1)[0]


# ------------------------------------------------------------------------------ Spear-Sovereign Incarnation
# The Incarnation prints one opening condition, "For the duration", over five riders plus the 3d10 Spear Thrust
# damage, so every hook below reads the timed "spear_sovereign_incarnation" state (combat/ext/states.py) from the
# creature running it and returns early for everybody else. That state carries the printed minute, so an expired,
# removed or never-cast Incarnation contributes nothing and no older saved fight changes.
SOVEREIGN = "TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION"
THRUST = "SPEAR_BASE_SPEAR_THRUST"
INCARNATION_STATE = "spear_sovereign_incarnation"
INTENT_MARK = "Spear Intent"
SPEAR_SPHERE = "tianxia.sphere.spear"
RIDE_USED = "spear_sovereign_ride"
LINE_BONUS_FT = 10
RIDE_CHOICE = "choice:needle.spear_sovereign_ride"
# The engine's own disarming condition (combat/rules/typed_conditions.json "disarmed", which the weapon-maneuvers
# table names "condition"). Matched by name, never by searching free text, so a rider that merely mentions
# disarming is untouched.
DISARMED_CONDITIONS = {"disarmed"}


def _state(engine: Any, actor: Any, *names: str) -> Any:
    from .states import active

    return active(engine, actor, *names) if actor is not None else None


def _hostile(actor: Any, other: Any) -> bool:
    return other is not None and getattr(other, "active", False) and other.team_id != actor.team_id


def _bears(engine: Any, owner: Any, target: Any) -> bool:
    """Whether target carries owner's Spear Intent mark."""
    if target is None or owner is None:
        return False
    from ..typed_executor import bears_mark

    return bears_mark(target, owner.entity_id, INTENT_MARK)


def _intent_ids(owner: Any) -> set[str]:
    from ..typed_executor import mark_requirement_ids

    return mark_requirement_ids(INTENT_MARK, owner.entity_id)


@hook("flight")
def spear_sovereign_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Spear-Sovereign Incarnation: Fly Speed 40 feet and Hover for the duration."""
    return {"fly_speed_ft": 40, "flight_hover": 1} if _state(engine, actor, INCARNATION_STATE) is not None else None


@hook("mark_applied")
def spear_sovereign_intent(ctx: Any, name: str, subject: Any) -> None:
    """Spear-Sovereign Incarnation: while it runs, your Spear Intent lasts to the END of your next turn.

    The printed upgrade moves the mark's own expiry (Spear Thrust types it "until the start of your next turn").
    "until the end of your next turn" is the end of the source's next turn, which the engine names
    END_OF_SOURCE_TURN_AT:<source turn + 1>: combat/gate2_engine.py _expire_typed_for_checkpoint reads that name as
    "the end of the source's Nth turn" and combat/typed_executor.py _turn_expiry writes the same number for "your
    next turn". One more turn would be a different printed rule.
    """
    engine, actor = ctx.engine, ctx.actor
    if name != INTENT_MARK or _state(engine, actor, INCARNATION_STATE) is None or not _hostile(actor, subject):
        return
    token = "END_OF_SOURCE_TURN_AT:" + str(int(actor.turns_started) + 1)
    wanted = _intent_ids(actor)
    for instance in list(subject.conditions.values()):
        if instance.condition_id in wanted and instance.source_actor_id == actor.entity_id and instance.expires_on != token:
            engine._remove_condition(subject, instance.condition_id, instance.source_definition_id)
            engine._apply_condition(subject, instance.condition_id, instance.source_definition_id, actor.entity_id,
                                    expires_on=token)


@hook("condition_attempt")
def spear_sovereign_disarm(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """Spear-Sovereign Incarnation: ordinary Disarm effects fail against the fighter running it.

    "subject" is the creature the condition would land on (combat/ext/__init__.py condition_attempt: "context
    supplies the source actor ... effect is the exact condition row"), and the printed protection belongs to the
    Incarnation's owner, so the state is read from the subject, never from the creature doing the disarming.
    """
    if not _is_disarming(effect):
        return None
    return False if _state(ctx.engine, subject, INCARNATION_STATE) is not None else None


def _is_disarming(effect: dict[str, Any]) -> bool:
    """Whether this condition row is an ordinary disarming effect (the dropped weapon cannot attack)."""
    names = effect.get("condition")
    rows = [names] if isinstance(names, str) else list(names or ())
    rows += list(effect.get("conditions") or ())
    return any(str(name or "").strip().lower() in DISARMED_CONDITIONS for name in rows)


@hook("attack_reach_bonus")
def spear_line_reach(engine: Any, actor: Any, action: Any, opportunity: bool) -> dict[str, Any] | None:
    """Spear-Sovereign Incarnation: +10 feet of Spear Line, through the general reach query (no attack is rewritten).

    The printed line grows "for Spear talents, opportunity attacks, and ordinary approved Spear weapon attacks", so
    a Spear-sphere action and an attack delivering an approved Spear weapon both qualify; an unarmed strike, a sword
    or a bow does not. The contribution is bound to the Incarnation state instance, so the reach query's own
    source/expiry re-read drops it the moment the minute ends, and opportunity=True reaches the bound opportunity
    attack exactly as it reaches a declared one.
    """
    held = _state(engine, actor, INCARNATION_STATE)
    if held is None or not spear_attack(action):
        return None
    return {"source_id": held.source_definition_id, "feet": LINE_BONUS_FT, "condition_id": held.instance_id,
            "stacking_group": "spear_line"}


def spear_attack(action: Any) -> bool:
    """Whether this attack profile is one the printed Spear Line covers: a Spear talent or a Spear weapon's own attack."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("sphere") == SPEAR_SPHERE:
        return True
    weapon = typed.get("weapon")
    if not isinstance(weapon, dict):
        return False
    from factory_authoring.starting_kits import item_definition

    item = item_definition(str(weapon.get("implement_id") or "")) or {}
    family = str(item.get("weapon_family") or "").lower()
    return any(word in family for word in SPEAR_WORDS)


@hook("after_hit_effects")
def spear_sovereign_thrust_damage(ctx: Any, target: Any, kind: str | None = None) -> None:
    """Spear-Sovereign Incarnation: Spear Thrust adds 3d10 Piercing or Force damage on a hit.

    The dice are the record's own typed row ("Spear Thrust adds 3d10 Piercing or Force damage on a hit"), and that
    row is what runs, so the printed number is never restated here. The row is marked "deferred" in the record
    because it belongs to a different activation from the Bonus Action that starts the Incarnation: the compiler
    skips deferred rows, so casting the Incarnation cannot damage its own user, and this hook runs it once per
    confirmed Spear Thrust hit. The hook point is after_hit_effects, which the executor reaches only for a
    confirmed hit, after the strike's own on-hit rows resolved, and never for a miss or a miss branch. Spear
    Thrust's printed limit is its own hit, so an ordinary Spear weapon attack or another Spear talent that hits
    deals this damage never.
    """
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _hostile(actor, target) or _state(engine, actor, INCARNATION_STATE) is None:
        return
    if not _is_thrust(ctx):
        return
    row = _thrust_damage(engine, actor)
    if row is None:
        ctx.rider("Spear-Sovereign Incarnation: no deferred Spear Thrust damage row in this bundle.")
        return
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{**row, "deferred": False, "applies_to": "target"}])


def _is_thrust(ctx: Any) -> bool:
    """Whether this strike is one of Spear Thrust's option attacks (the printed "on a hit" limit)."""
    source = str(ctx.source or "").split("#", 1)[0]
    return source.startswith("action:typed.") and source.endswith("." + THRUST)


def _thrust_damage(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The Incarnation's deferred extra-damage row, read from the fighter's own compiled action."""
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id or not str(action.source_definition_id).startswith("action:typed."):
            continue
        if not str(action.source_definition_id).split("#", 1)[0].endswith("." + SOVEREIGN):
            continue
        typed = (action.parameters or {}).get("typed") or {}
        for row in typed.get("effects") or ():
            if isinstance(row, dict) and row.get("type") == "extra_damage" and row.get("deferred"):
                return row
    return None


@hook("after_hit_effects")
def spear_sovereign_ride(ctx: Any, target: Any, kind: str | None = None) -> None:
    """Spear-Sovereign Incarnation: once per turn, hitting a creature bearing your Spear Intent moves 10 feet or pushes it 10.

    "once per turn when you hit a creature bearing your Spear Intent, move 10 feet toward it or push it 10 feet":
    the gate is the hit plus the mark (the shared if_marked block, reading the mark this strike left), the choice is
    the player's, and the turn flag is spent by the triggering hit itself, so a second hit in the same turn adds
    nothing. Both branches are the typed rows Spear Thrust's own menu uses for the identical wording (a self
    movement grant, a target forced_movement "away"), so the printed 10 feet is what the shared blocks read.
    """
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _hostile(actor, target) or _state(engine, actor, INCARNATION_STATE) is None:
        return
    if actor.turn_flags.get(RIDE_USED) or not _bears(engine, actor, target):
        return
    actor.turn_flags[RIDE_USED] = True
    from .needle import ask, checkpoint_id

    from .. import typed_executor as te

    picked = ask(engine, ctx.intent, checkpoint_id(engine, RIDE_CHOICE, target.entity_id), actor, RIDE_CHOICE,
                 ["move", "push"], labels={"move": "Move 10 feet toward " + str(target.display_name),
                                           "push": "Push " + str(target.display_name) + " 10 feet away"},
                 prompt=actor.display_name + " hit " + target.display_name + ", who bears your Spear Intent (the mark "
                        "Spear Thrust leaves, lasting until the end of your next turn): move 10 feet toward "
                        "them, or push them 10 feet away?",
                 target_id=target.entity_id, name="Spear-Sovereign Incarnation", feature_id=SOVEREIGN)
    inner = ({"type": "movement", "applies_to": "self", "distance_ft": 10, "evidence": "move 10 feet toward it"}
             if picked[:1] != ["push"] else
             {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
              "evidence": "push it 10 feet"})
    # The printed gate stays the shared mark check: it is re-read when the row runs, so a mark that expired between
    # the hit and this rider (or a target the strike swapped in) cannot be moved.
    te.run_effects(ctx, [{"type": "if_marked", "mark": INTENT_MARK, "effects": [inner]}])
