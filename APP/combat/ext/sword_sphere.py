"""Sword sphere printed effects the engine did not resolve (automation lane AUTO54, owner 2026-09-30:
"i want everything we can automated"; owner 2026-10-05: "every talent and ability of the Sword Sphere").

Rules text: the owner's Sphere Compendium, the Sword section, read from APP/authority/typed_mechanics/rules_text.json
through the reviewed authority (APP/authority/typed_mechanics/reviewed_final.d/review_sw-spirit_companions.json holds the
reviewed rows for these abilities; combat/rules/feature_blocks.d/wenxue.json-style ``covers`` retires the GM lines the table
now resolves).

Why a plug-in and not reviewed_final alone: the printed effects below are triggers with per-turn limits, weapon rules,
per-damage-type overrides and an area mode. ``reviewed_final`` can replace an effect list, but not the compiled weapon
metadata (Iron Sword Body's Constitution swap), not a damage-time override, not a cost substitution (spend Stamina instead
of CP) and not a critical range extension. Each of those already has a documented general seam in combat/ext/__init__.py,
so nothing is added to a core file here and no ability id is named in one.

Timed states (combat/ext/states.py ``{"type": "state"}`` rows, written in the reviewed authority):
  sword_qi_infusion           Sword-Qi Infusion: once per turn when the infused wielded Sword hits, extra Slashing
                              or Force damage by Cultivation Level, a reminder that the Sword counts as a magic
                              weapon where a rule distinguishes magical from nonmagical attacks (no engine rule
                              reads that flag yet -- see the lane report's lock-round item), and the target bears
                              your Sword Intent until the start of your next turn.
  sword_drawing_stance        Sword Drawing Stance: Advantage on the one Sword attack roll it is spent on, your
                              Proficiency Bonus on that damage (typed), Sword Intent on a hit, then the stance
                              ends after that attack resolves -- hit or miss.
  sword_sovereign_incarnation  Sword-Sovereign Incarnation: Fly Speed 40 feet and Hover, Resistance (typed), Sword Intent
                              lasts to the END of your next turn, a 10-foot move without provoking once per turn after
                              applying Sword Intent (whatever applied it, a hit or a save), a Reaction Sword attack or
                              Sword Qi Wave when a creature bearing your Sword Intent misses you, and ordinary
                              disarming effects fail.

The Sword Pressure failed save is deliberately NOT automated. Its printed text is "Failed Save: **Choose one:**"
with five alternatives, and the engine has no seam that asks a player to pick between the on-fail effects of a
zone's save, so the reviewed row carries no on-fail effect at all and leaves the whole printed choice to the
adjudicator as a reminder (the successful save's Sword Intent is printed unconditionally and is automated). The
plug-in also leaves Sword Pressure's own technique_save_dc alone: nothing public substitutes one ability for
another in a save DC.
  sword_manifestation         Sword Intent Manifestation: which of the three printed manifestations is running. The area
                              itself is the typed zone effect with ``menu_parts`` (combat/ext/menus.py); this records the
                              choice so the crit range, the cover and the cut-line damage can read it.

Iron Sword Body prints one opening condition, "While wielding a Sword", over all of its benefits, so
``_wields_sword`` answers it once -- possession through the shared query (``combat/ext/weapon_hits.py``
``available_weapons``) and, for catalogs that manage their grips, readiness through the shared hand model
(``combat/ext/hand_occupancy.py``) -- and the Constitution attack/damage swaps and the Stamina-for-CP substitution
all read it: a Sword fighter who is unarmed, whose Sword was knocked out of hand, or who has stowed their Sword gets
none of them. Historical bundles carry no Draw/Stow, so they keep the possession-only answer. Its Constitution swap
is the printed "if higher", and the modifier an attack already rolls with is the weapon's own whenever it has one --
0 is a real weapon modifier, not a missing one.

Every hook returns early for a creature that does not own the state or the area, so no other character and no older saved
fight changes.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook

INFUSION = "TAL_SWORD_SWORD_QI_INFUSION"
DRAWING = "TAL_SWORD_SWORD_DRAWING_STANCE"
INCARNATION = "TAL_SWORD_SWORD_SOVEREIGN_INCARNATION"
IRON_BODY = "TAL_SWORD_IRON_SWORD_BODY"
PRESSURE = "TAL_SWORD_SWORD_PRESSURE"
MYRIAD = "TAL_SWORD_MYRIAD_SWORD_PROCESSION"
MANIFESTATION = "TAL_SWORD_SWORD_INTENT_MANIFESTATION"
GUARD = "TAL_SWORD_SWORD_GUARD"
INFUSION_STATE = "sword_qi_infusion"
DRAWING_STATE = "sword_drawing_stance"
INCARNATION_STATE = "sword_sovereign_incarnation"
MANIFESTATION_STATE = "sword_intent_manifestation"
MAGICAL = "condition:typed.sword_magical_sword"
INTENT_MARK = "Sword Intent"
SWORD_SPHERE = "tianxia.sphere.sword"
MODE_KEYS = {"River of Edges": "river", "Forest of Swords": "forest", "Silent Killing Line": "silent"}
# The compiler's own reading of a Sword weapon (combat/factory_compiler.py _FAMILY_WORDS["sword"]).
SWORD_FAMILY = ("sword", "jian")
IRON_VARIANT = "#iron_sword_con"
# The engine's cover bonuses: combat/effect_cover.py ``ray_bonus`` scores ordinary cover cells 2 and only cells in
# ``engine._cover_three_quarters`` 5, and combat/effect_cover.py ``query`` accepts 0, 2 or 5. "Half Cover" is therefore 2.
HALF_COVER = 2
# The engine's own disarming condition (combat/rules/typed_conditions.json "disarmed"; the weapon maneuvers file it
# ``condition``). Matched by name, never by searching free text, so a rider that merely mentions disarming is untouched.
DISARMED_CONDITIONS = {"disarmed"}
# Player-facing names for the printed abilities this module asks about, so a prompt never shows a record id.
ABILITY_NAMES = {PRESSURE: "Sword Pressure", MYRIAD: "Myriad Sword Procession", INCARNATION: "Sword-Sovereign Incarnation"}


def _state(engine: Any, actor: Any, *names: str) -> Any:
    from .states import active

    return active(engine, actor, *names) if actor is not None else None


def _hostile(actor: Any, other: Any) -> bool:
    return other is not None and getattr(other, "active", False) and other.team_id != actor.team_id


def _bears(engine: Any, owner: Any, target: Any) -> bool:
    """Whether ``target`` carries ``owner``'s Sword Intent mark."""
    if target is None or owner is None:
        return False
    from ..typed_executor import bears_mark

    return bears_mark(target, owner.entity_id, INTENT_MARK)


def _intent_ids(owner: Any) -> set[str]:
    from ..typed_executor import mark_requirement_ids

    return mark_requirement_ids(INTENT_MARK, owner.entity_id)


def _sword_source(ctx: Any, kind: str | None = None) -> bool:
    """Whether this attack came from one of the fighter's Sword abilities or Sword-weapon attacks.

    The compiled rows carry the sphere or the printed Sword reach, so a Sword talent's own attack and a wielded Sword's
    weapon attack both qualify. Nothing here names an ability id.
    """
    typed = ctx.typed if isinstance(ctx.typed, dict) else {}
    if kind not in (None, "weapon", "other"):
        return False
    if typed.get("sphere") == SWORD_SPHERE:
        return True
    reach = typed.get("range")
    if isinstance(reach, dict) and str((reach.get("weapon_delivery") or {}).get("family") or "") == "sword":
        return True
    from .integrated_weapons import in_group

    if kind != "weapon" or not in_group(typed, "blade"):
        return False
    name = str((typed.get("weapon") or {}).get("name") or typed.get("source") or "").lower()
    return any(word in name for word in SWORD_FAMILY)


def _sword_areas(engine: Any, owner: Any) -> list[Any]:
    """This fighter's own live Sword areas (Sword Pressure, Myriad Sword Procession, Sword Intent Manifestation)."""
    from .. import zones

    wanted = {PRESSURE, MYRIAD, MANIFESTATION}
    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == getattr(owner, "entity_id", None) and zone.active
            and any(str(getattr(zone, "source_definition_id", "")).endswith(source) for source in wanted)]


def _inside(engine: Any, actor: Any, zone: Any) -> bool:
    from ..spatial_areas import zone_contains

    return bool(zone_contains(engine, actor, zone))


def _domain_areas(engine: Any, actor: Any) -> list[Any]:
    """The Sword Pressure / Myriad Sword Procession areas that actually stand around ``actor``.

    Both abilities print their free step (and Myriad its Half Cover) under a "You and Allies" / "Allies" heading, so
    the areas searched are the caster's own and its living allies' -- but a printed block about the allies in the
    area only reaches the allies standing in it. Team membership alone is not eligibility, so every candidate is
    checked for real membership (``spatial_areas.zone_contains``) and a fighter on the far side of the battlefield,
    or outside a Myriad sphere cast away from it, is given nothing.
    """
    out: list[Any] = []
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not getattr(owner, "active", False) or owner.team_id != actor.team_id:
            continue
        out += [zone for zone in _sword_areas(engine, owner)
                if str(zone.source_definition_id).endswith((PRESSURE, MYRIAD)) and _inside(engine, actor, zone)]
    return out


def _free_move(ctx: Any, mover: Any, feet: int, choice_id: str, ability: str, prompt: str) -> None:
    """A printed "move N feet without provoking Opportunity Attacks" step, asked of a player.

    ``ability`` is the printed ability's own record id, carried on the choice as its ``feature_id`` so the prompt
    is named after the ability that is actually running (Sword Pressure and Myriad Sword Procession share one
    transport) rather than whichever one the shared choice id was registered under.
    """
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sword_step", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={key: "Move to " + key.removeprefix("cell:") for key in paths},
                 target_id=mover.entity_id, name=ABILITY_NAMES.get(ability, "Sword art"), prompt=prompt, feature_id=ability)
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], ability)


# ------------------------------------------------------------------------------------------------- plain decision text
STEP_CHOICES = {"choice:needle.sword_pressure_step": (PRESSURE, 5), "choice:needle.sword_sovereign_step": (INCARNATION, 10),
                "choice:needle.sword_sovereign_answer": (INCARNATION, 0)}


@hook("decision_text")
def sword_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Name and explain this module's own choices in plain words.

    The shared choice transport carries a decision under an internal id (``choice:needle.sword_pressure_step`` and
    its two Incarnation siblings), which is not something a player should have to read, so each one is given its
    printed ability's name, the moment it is asked, what it costs, and a description for every button -- a map square
    for a printed free step, and the Sword attack a button makes for the printed Reaction. Presentation only, and
    inert for any choice this module does not own.
    """
    choice = str(context.get("reaction_source_id") or "")
    if choice not in STEP_CHOICES:
        return None
    default_ability, feet = STEP_CHOICES[choice]
    trigger = context.get("choice_trigger") or {}
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not trigger.get("needle_options"):
        return None
    # Sword Pressure and Myriad Sword Procession share one transport, so the choice id only says which kind of
    # decision this is. The ability that is actually running is the one the plug-in recorded on the choice
    # (``feature_id``), read here so a Myriad user is never told they are being offered Sword Pressure or that
    # the step follows a Sword attack.
    ability = str(trigger.get("feature_id") or "") or default_ability
    if ability not in ABILITY_NAMES:
        ability = default_ability
    name = ABILITY_NAMES.get(ability, "Sword art")
    labels = trigger.get("labels") or {}
    creature = engine.state.actors.get(str(trigger.get("target_id") or ""))
    # The triggering moment already names the ability, the action that fired it and the creature it landed on;
    # it is kept verbatim rather than replaced by generic wording that drops both details.
    moment = str(trigger.get("prompt") or "").strip()
    if feet:
        when = moment or (f"{name} lets {actor.display_name} move up to {feet} feet without provoking Opportunity "
                          f"Attacks, once per turn after hitting with a Sword attack.")
        summary = (f"Move {actor.display_name} to a square within {feet} feet. This costs none of {actor.display_name}'s "
                   "movement and no creature gets an Opportunity Attack for it. You may also decline and skip this.")
        descriptions = {option: str(labels.get(option) or option)
                        + ": move here, without provoking an Opportunity Attack."
                        for option in trigger["needle_options"]}
    else:
        who = creature.display_name if creature is not None else "that creature"
        when = moment or (f"{name} lets {actor.display_name} spend a Reaction to attack {who}, which just missed "
                          f"{actor.display_name} while carrying its Sword Intent.")
        summary = (f"Choose which Sword attack {actor.display_name} makes against {who} with a Reaction. "
                   "You may also decline and keep the Reaction. Declining costs nothing.")
        descriptions = {option: str(labels.get(option) or option)
                        + f": attack {who} with this Sword attack. It costs your Reaction and nothing else."
                        for option in trigger["needle_options"]}
    return {"feature_id": ability, "name": name, "trigger": when, "summary": summary,
            "cost": "No cost of its own" if feet else "Spends your Reaction", "option_descriptions": descriptions}


# ------------------------------------------------------------------------------------------- Sword-Qi Infusion
@effect("sword_magical_weapon")
def sword_magical_weapon(ctx: Any, row: dict[str, Any]) -> None:
    """Sword-Qi Infusion: the wielded Sword counts as a magic weapon until the infusion ends.

    A visible reminder, not a rule the table applies: no engine rule reads this flag yet (the typed rows that
    distinguish magical from nonmagical attacks read ``typed["mundane"]``, and there is no documented seam for an
    infusion to change it), so the wording tells the player exactly that.
    """
    from .owned_effects import remove_conditions

    engine, actor = ctx.engine, ctx.actor
    remove_conditions(engine, actor, ctx.source, actor.entity_id, MAGICAL)
    engine._apply_condition(actor, MAGICAL, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Sword-Qi Infusion: count this Sword as a magical weapon when a rule "
                                           "tells magical attacks from nonmagical ones"})


def _infusion_dice(cl: int) -> int:
    """1d6, 2d6 from Cultivation Level 11, 3d6 from 17."""
    return 3 if cl >= 17 else 2 if cl >= 11 else 1


def _wielded_sword(ctx: Any, kind: str | None = None) -> bool:
    """Whether this attack is made with a wielded Sword, the weapon Sword-Qi Infusion was cast on.

    The printed text is "Infuse one wielded Sword ... once per turn when **the Sword** hits", so the bonus belongs
    to that weapon and not to every Sword-sphere attack the fighter owns. This is deliberately narrower than
    ``_sword_source``, which also answers True for a Sword talent that carries no weapon (Sword Beyond Hand,
    Sword Qi Wave): those are the fighter's own Sword-Qi, not the infused blade, and must not spend the printed
    once-per-turn bonus or its dice. Matched on the compiled weapon row, so nothing here names an ability id.
    """
    typed = ctx.typed if isinstance(ctx.typed, dict) else {}
    if kind not in (None, "weapon"):
        return False
    weapon = typed.get("weapon")
    if not isinstance(weapon, dict) or not weapon:
        return False
    handle = " ".join(str(part or "") for part in (weapon.get("name"), weapon.get("implement_id"), typed.get("source"))).lower()
    return any(word in handle for word in SWORD_FAMILY)


@hook("after_hit")
def sword_infusion_hit(ctx: Any, target: Any, kind: str) -> None:
    """Once per turn when the infused Sword hits: extra Slashing or Force damage, and Sword Intent on the target."""
    engine, actor = ctx.engine, ctx.actor
    held = _state(engine, actor, INFUSION_STATE)
    if held is None or not _hostile(actor, target) or actor.turn_flags.get("sword_qi_infusion_hit"):
        return
    if not _wielded_sword(ctx, kind):
        return
    actor.turn_flags["sword_qi_infusion_hit"] = True
    from .. import typed_executor as te

    count = _infusion_dice(int((held.data or {}).get("numbers", {}).get("cl") or 1))
    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}), [
        {"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 6},
         "damage_types": ["slashing", "force"],
         "evidence": f"Sword-Qi Infusion: {count}d6 Slashing or Force damage"},
        {"type": "mark", "mark": INTENT_MARK, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}},
    ])


# ----------------------------------------------------------------------------------------- Sword Drawing Stance
@hook("attack_mode")
def drawing_stance_mode(ctx: Any, target: Any) -> str | None:
    """Sword Drawing Stance: Advantage on the one Sword attack roll the stance was spent on."""
    return "ADVANTAGE" if _state(ctx.engine, ctx.actor, DRAWING_STATE) is not None and _sword_source(ctx) else None


@hook("attack_resolved")
def drawing_stance_spent(ctx: Any, target: Any, hit: bool, effect: Any) -> None:
    """Sword Drawing Stance: "After the attack resolves, the stance ends." -- on a miss as well as a hit.

    The printed sentence is not conditional on landing, so the stance is spent by the attack resolving either
    way. Only a hit applies Sword Intent (``drawing_stance_hit``); this is the consumer for the miss, which
    would otherwise leave the stance standing until its duration ran out. The one attack roll the stance
    bought (Advantage, ``drawing_stance_mode``) is the attack that spends it, so a non-Sword attack does not.
    """
    engine, actor = ctx.engine, ctx.actor
    held = _state(engine, actor, DRAWING_STATE)
    if held is None or hit or not _hostile(actor, target) or not _sword_source(ctx):
        return
    from .owned_effects import remove_conditions

    # The stance was opened by its own Bonus Action, so it ends under that source, not the attack's.
    remove_conditions(engine, actor, held.source_definition_id, actor.entity_id, held.condition_id)


@hook("after_hit")
def drawing_stance_hit(ctx: Any, target: Any, kind: str) -> None:
    """Sword Drawing Stance: apply Sword Intent on a hit, then the stance ends after the attack resolves."""
    engine, actor = ctx.engine, ctx.actor
    held = _state(engine, actor, DRAWING_STATE)
    if held is None or not _hostile(actor, target) or not _sword_source(ctx, kind):
        return
    from .owned_effects import remove_conditions
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "mark", "mark": INTENT_MARK, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])
    # The stance was opened by its own Bonus Action, so it ends under that source, not the attack's.
    remove_conditions(engine, actor, held.source_definition_id, actor.entity_id, held.condition_id)


# ------------------------------------------------------------------------------- Sword-Sovereign Incarnation
@hook("flight")
def sovereign_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Sword-Sovereign Incarnation: Fly Speed 40 feet and Hover for the duration."""
    return {"fly_speed_ft": 40, "flight_hover": 1} if _state(engine, actor, INCARNATION_STATE) is not None else None


@hook("mark_applied")
def sovereign_intent(ctx: Any, name: str, subject: Any) -> None:
    """Sword-Sovereign Incarnation: while it runs, your Sword Intent lasts to the END of your next turn.

    "until the end of your next turn" is the end of the source's *next* turn, which the engine names
    ``END_OF_SOURCE_TURN_AT:<source turn + 1>``: combat/gate2_engine.py ``_expire_typed_for_checkpoint`` reads that
    name as "the end of the source's Nth turn" and combat/typed_executor.py ``_turn_expiry`` writes the same number
    for "your next turn". One more turn would be a different printed rule.
    """
    engine, actor = ctx.engine, ctx.actor
    if name != INTENT_MARK or _state(engine, actor, INCARNATION_STATE) is None or not _hostile(actor, subject):
        return
    token = f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}"
    wanted = _intent_ids(actor)
    for instance in list(subject.conditions.values()):
        if instance.condition_id in wanted and instance.source_actor_id == actor.entity_id and instance.expires_on != token:
            engine._remove_condition(subject, instance.condition_id, instance.source_definition_id)
            engine._apply_condition(subject, instance.condition_id, instance.source_definition_id, actor.entity_id,
                                    expires_on=token)


@hook("condition_attempt")
def sovereign_disarm(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """Sword-Sovereign Incarnation: ordinary disarming effects fail against the fighter running it.

    ``subject`` is the creature the condition would land on (combat/ext/__init__.py ``condition_attempt``: "context
    supplies the source actor ... effect is the exact condition row"), and the printed protection belongs to the
    Incarnation owner, so the state is read from the subject and never from the creature doing the disarming.
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


@hook("mark_applied")
def sovereign_step(ctx: Any, name: str, subject: Any) -> None:
    """Sword-Sovereign Incarnation: once per turn after applying Sword Intent, move 10 feet without provoking.

    The printed trigger is "**after applying Sword Intent**", so this runs where an Intent is applied (which
    includes one placed by a failed or successful save, not only by an attack) rather than on a hit at a
    creature that merely already carries the mark. Once per turn, and the step is the player's decision.
    """
    engine, actor = ctx.engine, ctx.actor
    if name != INTENT_MARK or _state(engine, actor, INCARNATION_STATE) is None:
        return
    if not _hostile(actor, subject) or actor.turn_flags.get("sword_sovereign_step"):
        return
    actor.turn_flags["sword_sovereign_step"] = True
    _free_move(ctx, actor, 10, "choice:needle.sword_sovereign_step", INCARNATION,
               f"Sword-Sovereign Incarnation: after marking {subject.display_name} with Sword Intent, "
               f"{actor.display_name} may move up to 10 feet without provoking Opportunity Attacks.")


@hook("after_miss")
def sovereign_answer(ctx: Any, target: Any) -> None:
    """Sword-Sovereign Incarnation: a creature bearing your Sword Intent that misses you grants one Reaction Sword attack."""
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not _hostile(attacker, target) or not getattr(attacker, "active", False):
        return
    if not target.reaction_available or _state(engine, target, INCARNATION_STATE) is None or not _bears(engine, target, attacker):
        return
    from ..typed_executor import condition_rules

    if any(rule.get("no_reactions") for rule in condition_rules(target)):
        return
    action = _sword_strike(engine, ctx.intent, target, attacker, "choice:needle.sword_sovereign_answer",
                           f"Sword-Sovereign Incarnation: {attacker.display_name} missed you while bearing your Sword "
                           "Intent. Spend your Reaction to make one Sword attack or Sword Qi Wave against it?")
    if action is None:
        return
    from .. import typed_reactions

    with activation(engine, target, INCARNATION):
        typed_reactions._open(engine, {"feature_id": INCARNATION}, target, (attacker.entity_id,), "ATTACK_MISSED")
        target.reaction_available = False
        _granted_attack(engine, target, action, attacker, ctx.intent)


def _sword_strikes(engine: Any, reactor: Any, target: Any) -> dict[str, Any]:
    """The reactor's own Sword attack actions that reach ``target``."""
    from ..typed_reactions import attack_reaches

    out: dict[str, Any] = {}
    for source_id, action in sorted(engine.action_catalog.items()):
        if action.owner_id != reactor.entity_id or not str(action.source_definition_id).startswith("action:typed."):
            continue
        if not str(source_id).endswith(("SWORD_BASE_SWORD_IN_HAND", "SWORD_BASE_SWORD_BEYOND_HAND")):
            continue
        typed = (action.parameters or {}).get("typed") or {}
        reach = engine._distance_actor_to_actor(reactor, target)
        if reach > int(action.range_ft or 5) and not attack_reaches(engine, reactor, target, typed):
            continue
        out[source_id] = action
    return out


def _sword_strike(engine: Any, intent: Any, reactor: Any, target: Any, choice_id: str, prompt: str) -> Any:
    from .needle import ask, checkpoint_id

    strikes = _sword_strikes(engine, reactor, target)
    if not strikes:
        return None
    picked = ask(engine, intent, checkpoint_id(engine, choice_id, target.entity_id), reactor, choice_id, list(strikes),
                 labels={key: action.display_name for key, action in strikes.items()}, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Sword-Sovereign Incarnation", feature_id=INCARNATION, prompt=prompt)
    return strikes.get(picked[0]) if picked else None


def _granted_attack(engine: Any, reactor: Any, action: Any, target: Any, intent: Any) -> None:
    """Run one attack the printed Reaction grants, without spending an Action of the reactor's own."""
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(row) for row in typed.get("effects") or []
                   if isinstance(row, dict) and row.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, reactor, action, intent, {**typed, "effects": [attack], "granted_attack": True},
                             [target], target, {}), [attack])


# ---------------------------------------------------------------------------------- Sword Pressure / Myriad Procession
@hook("after_hit")
def pressure_step(ctx: Any, target: Any, kind: str) -> None:
    """Sword Pressure and Myriad Sword Procession: a 5-foot move without provoking after hitting, once per turn.

    Sword Pressure prints "after hitting **with a Sword attack**", so there the hit must be a Sword attack; Myriad Sword
    Procession prints "after hitting" with no weapon named, so any hit offers it. Both print the step under a "You and
    Allies" heading, so an ally of the caster's own team gets it from the caster's area.
    """
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("sword_pressure_step") or not _hostile(actor, target):
        return
    areas = _domain_areas(engine, actor)
    # Myriad Sword Procession prints "after hitting" with no weapon named, so any hit offers the step; Sword Pressure
    # prints "after hitting **with a Sword attack**", so there the hit must be a Sword attack.
    ability = MYRIAD if any(str(row.source_definition_id).endswith(MYRIAD) for row in areas) else None
    if ability is None:
        if not _sword_source(ctx, kind):
            return
        ability = PRESSURE if any(str(row.source_definition_id).endswith(PRESSURE) for row in areas) else None
    if ability is None:
        return
    actor.turn_flags["sword_pressure_step"] = True
    _free_move(ctx, actor, 5, "choice:needle.sword_pressure_step", ability,
               f"{ABILITY_NAMES[ability]}: after {ctx.action.display_name} hits {target.display_name}, "
               f"{actor.display_name} may move 5 feet without provoking Opportunity Attacks from the target.")


@hook("cover")
def myriad_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Myriad Sword Procession, and Forest of Swords: allies standing in the area gain Half Cover.

    Half Cover is this engine's +2 (combat/effect_cover.py ``ray_bonus`` scores an ordinary cover cell 2 and reserves 5
    for three-quarters cover), so the printed word "Half" is answered with 2 and never with the 5.
    """
    return HALF_COVER if _covered(engine, target) else None


def _covered(engine: Any, target: Any) -> bool:
    """Whether ``target`` stands inside a Sword area one of its own allies laid down that grants Half Cover."""
    if target is None or not getattr(target, "active", False):
        return False
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not getattr(owner, "active", False) or owner.team_id != target.team_id:
            continue
        for zone in _sword_areas(engine, owner):
            source = str(zone.source_definition_id)
            if not source.endswith(MYRIAD) and not (source.endswith(MANIFESTATION)
                                                    and _mode(engine, owner, "forest") is not None):
                continue
            if _inside(engine, target, zone):
                return True
    return False


# ------------------------------------------------------------------------------------- Sword Intent Manifestation
@effect("sword_manifestation")
def sword_manifestation(ctx: Any, row: dict[str, Any]) -> None:
    """Sword Intent Manifestation: record which of the three printed manifestations this activation chose."""
    from .. import typed_executor as te

    label = str(row.get("option") or row.get("label") or "River of Edges")
    mode = MODE_KEYS.get(label, str(row.get("mode") or "river"))
    engine, actor = ctx.engine, ctx.actor
    from .owned_effects import remove_conditions

    condition_id = f"condition:typed.state.{MANIFESTATION_STATE}"
    remove_conditions(engine, actor, ctx.source, actor.entity_id, condition_id)
    engine._apply_condition(actor, condition_id, ctx.source, actor.entity_id,
                            expires_on=te.effect_expiry(ctx, row, actor, condition=True) or "UNTIL_REMOVED",
                            data={"label": f"Sword Intent Manifestation: {label}", "name": MANIFESTATION_STATE,
                                  "mode": mode, "numbers": {"pb": int(ctx.numbers.get("pb") or 0),
                                                             "cl": int(ctx.numbers.get("cl") or 1)}})


def _mode(engine: Any, actor: Any, mode: str) -> Any:
    """The owner's active Sword Intent Manifestation, when it is running the named printed mode."""
    held = _state(engine, actor, MANIFESTATION_STATE)
    return held if held is not None and str((held.data or {}).get("mode") or "") == mode else None


@hook("critical_range")
def silent_killing_line(ctx: Any, target: Any) -> int | None:
    """Silent Killing Line: Sword and Sword-Qi attacks score a critical hit on 19-20 against Sword Intent targets."""
    engine, actor = ctx.engine, ctx.actor
    if _mode(engine, actor, "silent") is None or not _sword_source(ctx):
        return None
    return 19 if _bears(engine, actor, target) else None


@hook("after_miss")
def forest_of_swords(engine_ctx: Any, target: Any) -> None:
    """Forest of Swords: a hostile creature that misses an ally with a melee attack takes your Proficiency Bonus in
    Slashing or Force damage.

    "with a melee attack" is read with the shared classification (combat/ext/thunder_charges.py ``melee_attack``),
    which answers from the attack's own kind and aim, so a plain 5-foot melee swing is a melee attack -- the
    previous reading rejected any attack carrying a range at all, and a Sword's 5-foot reach is exactly that.

    The ally is checked against **this owner's own** Forest of Swords area, so a fighter whose Manifestation is
    running elsewhere on the field cannot answer for an area that is not theirs and its rival cannot be silenced
    by a different caster's area covering the same ally.
    """
    from .thunder_charges import melee_attack

    engine, attacker = engine_ctx.engine, engine_ctx.actor
    if target is None or not _hostile(attacker, target) or not getattr(attacker, "active", False):
        return
    if not melee_attack(engine_ctx):
        return
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if owner.team_id != target.team_id or owner is target or not getattr(owner, "active", False):
            continue
        if _mode(engine, owner, "forest") is None or not _in_own_forest(engine, owner, target):
            continue
        engine._commit_damage(attacker, int(owner.proficiency_bonus or 2), "SLASHING", f"{MANIFESTATION}#forest_of_swords",
                              owner.entity_id, engine_ctx.intent, reaction_depth=2)
        break


def _in_own_forest(engine: Any, owner: Any, ally: Any) -> bool:
    """Whether ``ally`` stands inside this owner's own Forest of Swords area (its Manifestation running that mode)."""
    return any(str(zone.source_definition_id).endswith(MANIFESTATION) and _inside(engine, ally, zone)
               for zone in _sword_areas(engine, owner))


# ------------------------------------------------------------------------------------------------ Sword Guard
@hook("damage_reduction_bonus")
def sword_guard_bonus(engine: Any, owner: Any, protected: Any, attacker: Any, reaction_row: Any) -> int | None:
    """Sword Guard: add your Proficiency Bonus when the attacker bears your Sword Intent."""
    feature = reaction_row.get("feature_id") if isinstance(reaction_row, dict) else getattr(reaction_row, "feature_id", None)
    if str(feature or "") != GUARD:
        return None
    return int(owner.proficiency_bonus or 2) if _bears(engine, owner, attacker) else None


# ------------------------------------------------------------------------------------------- Iron Sword Body
@hook("compile_actions")
def iron_sword_body(info: dict[str, Any]) -> list[Any] | None:
    """"While wielding a Sword: use Constitution for Sword attack and damage rolls if higher."

    A "(Constitution)" variant of each Sword-weapon attack the character owns, added only when the Constitution modifier
    is actually higher than the weapon's own -- the printed "if higher". The printed "+1 AC" and "Advantage against a
    forced Disarm" are typed rows. The original action always stays.
    """
    import copy

    from ..gate2_runtime_models import EconomyKind

    if IRON_BODY not in info["owned_ids"]:
        return None
    constitution = int((info.get("mods") or {}).get("CON", 0) or 0)
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        if base.economy != EconomyKind.ACTION or "#" in base.source_definition_id or not typed.get("weapon"):
            continue
        weapon_name = str((typed.get("weapon") or {}).get("name") or typed.get("source") or "").lower()
        if not any(word in weapon_name for word in SWORD_FAMILY) or constitution <= int((typed.get("weapon") or {}).get("ability_modifier") or 0):
            continue
        if not any(isinstance(row, dict) and row.get("type") == "attack" for row in typed.get("effects") or []):
            continue
        variant = copy.deepcopy(typed)
        variant["weapon"]["damage"]["modifier"] = constitution + int(typed.get("magic_bonus") or 0)
        variant["weapon"]["ability_modifier"] = constitution
        variant["numbers"]["attack_bonus"] = int(typed["numbers"].get("attack_bonus") or 0) \
            - int(typed["weapon"].get("ability_modifier") or 0) + constitution
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#iron_sword_con",
                                           "display_name": base.display_name + " (Constitution)",
                                           "parameters": {**base.parameters, "typed": variant}}))
    return out or None


def _wields_sword(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` has a Sword in hand right now: the printed "While wielding a Sword" condition.

    Every one of Iron Sword Body's printed benefits hangs off that opening line, so eligibility is asked in one
    place and shared by all of them. It answers "which Sword is this creature actually wielding right now", in two
    documented public steps that are the same ones the engine's own weapon rules, hand occupancy and delivery use:

    * possession, from ``combat/ext/weapon_hits.py`` ``available_weapons`` -- the same query the engine's
      weapon-required effects use. A character that was never equipped with a Sword, a Sword that was dropped or
      knocked out of the fighter's hand, a Sword another creature is holding, and a Sword whose use any condition
      disables all answer False;
    * readiness, from the public shared hand model ``combat/ext/hand_occupancy.py`` -- a Sword that is carried but
      stowed is in the fighter's inventory, not in its hands, so it is not "wielding" one. Draw/Stow updates the
      actor's event-sourced equipment-readiness state, so this survives a table commit and reload exactly as the
      weapon state it reads does.

    Readiness is asked only for catalogs that opted into managed grips (``hand_occupancy.supports_grips``). Those
    are the bundles compiled with the equipment policy, and they own real Draw/Stow actions. Historical bundles are
    immutable, carry no grip actions, and ``weapon_grips`` is deliberately default-inert for them (it reports nothing
    readied), so they fall back to possession alone -- otherwise every saved fight's Sword fighter would read as
    having stowed its Sword and would silently lose all five printed benefits. Sword-core's public query matches
    the approved Sword weapon group and is also used by the AC benefit, so all benefits use the same definition.
    """
    from .sword_core import wielding_sword

    return wielding_sword(engine, actor)


def _iron_key_delta(ctx: Any, actor: Any) -> int | None:
    """What Iron Sword Body's printed Constitution key ability is worth on this attack, if anything.

    "use Constitution as your Sword key ability" is read as the printed "if higher" that governs the line
    above it: the difference between the Constitution modifier and the modifier the attack already rolls with,
    and only when Constitution is the higher of the two. A wielded Sword's own weapon roll is already carried by
    the compiled "(Constitution)" attack, which is skipped here so the two never stack.

    The modifier the attack already rolls with is the weapon's own when the attack carries one, and the Path key
    ability otherwise. Only a *missing* weapon modifier falls back: 0 is a real modifier (a balanced Sword rolls
    with no ability at all), so reading it as "absent" would let the Path modifier stand in for it and hand out
    the Path modifier twice -- or, when Path equals Constitution, no Constitution at all.
    """
    from .attack_abilities import resolved_strike_ability
    if resolved_strike_ability(ctx):
        return None
    typed = ctx.typed if isinstance(ctx.typed, dict) else {}
    from .sword_core import sword_attack

    if not sword_attack(ctx) or not _owns_iron_sword_body(ctx.engine, actor):
        return None
    if not _wields_sword(ctx.engine, actor):
        return None
    if str(getattr(getattr(ctx, "action", None), "source_definition_id", "")).endswith(IRON_VARIANT):
        return None
    numbers = typed.get("numbers") or {}
    constitution = int(numbers.get("con_mod") or 0)
    weapon = typed.get("weapon") if isinstance(typed.get("weapon"), dict) else {}
    rolled = weapon.get("ability_modifier")
    current = int(rolled) if rolled is not None else int(numbers.get("key_mod") or 0)
    return constitution - current if constitution > current else None


@hook("attack_ability_options")
def iron_sword_body_options(ctx: Any) -> dict[str, int] | None:
    """Offer the legal Constitution substitution to a shared per-strike picker.

    The same ownership, wielding and printed 'if higher' checks govern the
    legacy automatic delta and this ordinary option. Once selected, the shared
    resolved contract suppresses that delta for both attack and damage.
    """
    if _iron_key_delta(ctx, ctx.actor) is not None:
        return {"CON": int(ctx.numbers.get("con_mod") or 0)}
    return None


@hook("attack_bonus")
def iron_sword_body_attack(ctx: Any, actor: Any) -> int | None:
    """Iron Sword Body: the Constitution key ability on the Sword attacks the compiler cannot rewrite.

    The printed rule covers "Sword attack and damage rolls", not only a wielded Sword's weapon roll, so the Sword
    talents that carry no weapon row of their own (Sword Beyond Hand, Sword Qi Wave) are answered here through
    the shared flat-attack-bonus seam -- but only while a Sword is actually in hand, which is the printed
    "While wielding a Sword" that opens every benefit of this ability. General seam, no ability id in core, inert
    for a fighter without the talent.
    """
    return _iron_key_delta(ctx, actor)


@hook("attack_damage_bonus")
def iron_sword_body_damage(ctx: Any, target: Any, effect: Any) -> int | None:
    """Iron Sword Body: the same Constitution key ability on the matching damage roll."""
    return _iron_key_delta(ctx, ctx.actor)


@hook("payment_substitution")
def iron_sword_body_payment(engine: Any, actor: Any, source: str, costs: Any, missing: Any) -> Any:
    """"While wielding a Sword: spend Stamina instead of CP on Sword talents." Iron Sword Body.

    A voluntary substitution covering the printed CP cost of one of this fighter's Sword talents; Stamina must cover
    it. Nothing else in the fight changes, and a decline pays normally.
    """
    from ..alternative_payments import PaymentAlternative

    action = engine.action_catalog.get(source)
    if action is None or action.owner_id != actor.entity_id:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    # Ownership: Iron Sword Body is a passive, so it is the compiled character bundle -- saved with the match and read
    # back by combat/gate4_persistence.py -- that records the fighter owning it. Only the Constitution swap above is
    # printed "if higher"; the Stamina substitution is not, so it must not be read off the "(Constitution)" variant.
    if typed.get("sphere") != SWORD_SPHERE or not _owns_iron_sword_body(engine, actor):
        return None
    # The printed line is "While wielding a Sword", and this is the fourth benefit it opens, so it is gated by the same
    # shared eligibility check as the attack and damage swaps: no Sword in hand, no Stamina-for-CP quote.
    if not _wields_sword(engine, actor):
        return None
    stamina = int(actor.resources.get("resource:core.stamina") or 0)
    covered = {}
    for resource, amount in costs.items():
        if resource == "resource:core.qi" and amount > 0 and stamina >= amount:
            covered[resource] = amount
    if not covered or any(resource not in covered for resource in missing):
        return None
    return PaymentAlternative(IRON_BODY, "Iron Sword Body: spend Stamina instead of CP", tuple(covered.items()),
                             costs=(("resource:core.stamina", sum(covered.values())),))


def _owns_iron_sword_body(engine: Any, actor: Any) -> bool:
    """Whether this fighter's compiled character carries Iron Sword Body.

    New bundles carry an owned passive block in ``engine.typed_passive_rows``. Historical bundles instead use
    ``engine.typed_bundle_documents``, which holds each compiled character bundle (the record combat/gate3_storage.py writes
    with the match), keyed by its ``actor_id``; a bundle lists every owned ability that contributed a modifier row under
    ``modifiers`` by that ability's own record id. Reading ownership from the bundle, rather than from the "(Constitution)"
    attack variant, keeps the printed Stamina substitution available to a Sword fighter whose Constitution is lower than
    their own key ability.
    """
    # Newer Sword-core bundles replace the modifier with an owned passive block.
    # Keep the saved modifier representation as a fallback, without rewriting old bundles.
    if any(row.get("feature_id") == IRON_BODY for row in
           (getattr(engine, "typed_passive_rows", None) or {}).get(actor.entity_id, ())):
        return True
    bundle = next((row for row in (getattr(engine, "typed_bundle_documents", ()) or ())
                   if str(row.get("actor_id") or "") == str(actor.entity_id)), None)
    if bundle is None:
        return False
    return any(str(row.get("id") or "") == IRON_BODY for row in bundle.get("modifiers") or ())
