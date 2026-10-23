"""Shared Protection runtime: own_wards(engine, owner) returns live owned Wards
without mutation; protection_second_pass uses it for activation and relief.

Sphere of Protection: Aegis, Ward and Succor (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going
until its only the non-combat ones left"). Printed text: authority/typed_mechanics/rules_text.json and the compendium's base
procedures. Before this module Aegis, Ward and Succor were definitions only: no Aegis or Ward could be made, so Bulwark (whose
compiled row already sacrifices a "Persistent Aegis" mark) could never fire.

An Aegis is a mark (typed_executor.block_mark storage, condition ``condition:typed.mark.<name>.<creator>``): "Persistent Aegis" for a
Persistent one, "Aegis" otherwise. Its data names the talent, the creator's numbers and (Energy Resistance) the chosen type, so
every reaction that "requires"/"spends" a Persistent Aegis (Bulwark, Punishment Succor, Luck) reads the same record.
  Aegis ("Action, Range: Touch, Target: One creature, Duration: Concentration, up to 1 hour, Cost: None. Grant the target one Aegis
  talent you know." "Persistent Aegis - Augment 2 CP: persists for its remaining duration without Concentration." "A creature may
  benefit from only one Aegis created by the same cultivator at a time."): compiled "Aegis: <talent>" and "Aegis: <talent>
  (Persistent)" actions (self or an ally within touch) for Armored Aegis and each Aegis talent known. A new Aegis from the same
  creator replaces the old one.
    "An unwilling creature may make a Wisdom saving throw to resist receiving an Aegis." (base Aegis record): the
                     selected creature is asked whether it will have the Aegis, and one that refuses resolves that
                     refusal with the printed Wisdom save against the creator's Cultivation Save DC -- the Aegis lands
                     on a failure and it resists on a success. ``aegis_effect`` reuses the documented refusal branch of
                     ``choose_willing`` (``unwilling_save``) and keeps the action's own selected creature
                     (``target_only``), so no second action and no second recipient appear; an AI creature answers for
                     itself from its own side of the fight.
    Armored Aegis    "base AC becomes equal to your Cultivation Save DC" (``ac`` hook: its AC is at least that DC).
    Shielded         "functions as an ordinary shield": +2 AC.
    Slippery         Advantage on saves against Restrained and forced movement, and on escape checks.
    Energy Resistance  Resistance to the chosen type (acid, cold, fire, lightning, radiant, thunder; asked when made).
    Protected Health Resistance to Poison; Advantage on saves against poison and disease.
    Punishment       "A creature that hits the bearer with an attack takes Psychic damage" (PB; 1d6/2d6/3d6 + PB at CL 5/11/17).
                     hit_snapshot captures the ward at the settled hit; hit_final retaliates exactly once, even if damage ends it.
    Peacebound       An attack or harmful technique aimed at the bearer: the attacker makes a Wisdom save; failure -> it fails
                     against the bearer; success -> the Aegis ends. The bearer's own attack or harmful technique ends it.
    Spell Ward       "Advantage on saving throws against supernatural effects" (a save forced by a technique, not by a weapon).
    Heaven-Sheltering Aegis (its own compiled action): "base AC becomes your Cultivation Save DC + 2"; "once during the duration,
                     when it would drop to 0 HP, it drops to 1 HP instead and the Aegis ends" (``would_drop``).
  Ward ("Action, Range: Self, Area: 20-foot-radius ... Duration: Concentration, up to 1 minute. Create one Ward talent you know. The
  Ward remains where it was created." "you may maintain only one Ward at a time"): compiled "Ward: <talent>" actions for Energy
  Resistance, Protected Health and Peacebound. The first two are the zone's "inside" rules (Resistance while inside); Peacebound:
  a creature inside that attacks or uses a harmful technique makes a Wisdom save; failure -> it fails; success -> the Ward ends
  and the creatures inside are immune to this cultivator's Peacebound Ward for the rest of the fight ("until the next dawn").
  Succor ("Reaction ... Range: 300 feet ... Cost: Sacrifice one Persistent Aegis you created on the target"):
    Bulwark     its existing generic row (ally_attacked, requires and spends the mark).
    Punishment  a generic ally_damaged row (reviewed_final.d/riders_c4.json); ``ally_row_allowed`` keeps it to damage from an attack.
    Luck        a d20_rewrite rule: the protected creature makes a save -> it rerolls and must use the new result.
  Community ("Whenever a creature benefiting from one of your Aegises takes damage, you may transfer up to half of that damage to
  another willing creature benefiting from one of your Aegises. No action is required."): ``damage_pending``; the creator is asked
  (Ask me), the AI transfers half when the other bearer stays standing and is better off than the one hit.
  Ward ("you may reduce its size when creating it"): the creator is asked how large the Ward is; the printed 20-foot radius is the
  default and 15, 10 and 5 feet are offered. The Ward's own edge rules keep their choices on the area (zones.create's ``profile``),
  recorded by its own ZONE_CREATED event like every other zone field.
  Shielded     "If the bearer uses the shield-hand to hold another object, the shield is suppressed until the start of the next turn in
               which that hand is free": the +2 AC needs a hand free for the shield (a bearer gripping with both hands -- a two-handed
               weapon, two readied weapons, a hold -- has no hand for it), and the suppression is stored as a condition
               (SHIELD_OFF) put on at a turn boundary and taken off at the start of the next turn in which a hand is free, so an AC
               query never writes and the printed "until the start of the next turn in which that hand is free" holds.
  Impedance    "A creature attempting to enter a space within 5 feet of the bearer makes a Wisdom saving throw. Failed Save: It cannot
               enter that space until the start of its next turn." (Aegis; "Augment - 1 CP: Increase the protected distance to 10 feet"
               is asked and paid as one quoted choice, and only there -- the printed augment is under the Aegis) and the Ward's
               once-a-turn version ("attempting to enter the Ward or move closer to the Ward's center"): ``movement_attempt`` rolls the
               printed save before the step is paid for and stops the move, and the barrier that save leaves is then enforced on every
               later voluntary step -- by the ``candidate_allowed`` filter over the whole canonical path the engine will walk, and by
               the same step gate, so ability-granted movement is refused as well. The barrier ends at the start of the failing
               creature's own next turn (``effect_durations.token``), never at an intervening turn of the caster's.
  Repel Spirit-Kin  "A chosen creature attempting to cross the Ward's edge makes a Charisma saving throw": the same crossing gate,
               with ``creature_kinds.matches`` for the printed families and ``spatial_areas.zone_contains`` -- the very volume query the
               crossing uses -- for "a creature already inside when the Ward appears is unaffected", recorded for every creature standing
               inside (of any team) at that moment; a paid crossing is kept as a condition keyed to the caster, because the printed
               immunity is to "your Repel Spirit-Kin Ward", not to one area.
  Status       "You always know: the direction and distance to creatures benefiting from one of your Aegises" and how each one fares:
               a readable line at the owner's turn start and again whenever a bearer's health, place or conditions change, until that
               bearer dies or leaves the plane.
Every hook returns early unless a creature bears one of these marks, stands in one of these Wards or owns the talent's row.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .ability_source import has_row

PROTECTION = "tianxia.sphere.protection"
T = "tianxia.talent.protection."
ARMORED, SHIELDED, SLIPPERY, ENERGY, HEALTH = "PROTECTION_BASE_ARMORED_AEGIS", T + "shielded", T + "slippery", T + "energy_resistance", T + "protected_health"
PUNISHMENT, PEACEBOUND, SPELL_WARD, LUCK, HEAVEN = T + "punishment", T + "peacebound", T + "spell_ward", T + "luck", T + "heaven_sheltering_aegis"
IMPE, REPEL, STATUS = T + "impedance", T + "repel_spirit_kin", T + "status"
AEGIS_MARK, PERSISTENT_MARK = "Aegis", "Persistent Aegis"
AEGIS_TALENTS = {ARMORED: "Armored Aegis", SHIELDED: "Shielded", SLIPPERY: "Slippery", ENERGY: "Energy Resistance", HEALTH: "Protected Health",
                 PUNISHMENT: "Punishment", PEACEBOUND: "Peacebound", SPELL_WARD: "Spell Ward", IMPE: "Impedance"}
WARD_TALENTS = {ENERGY: "Energy Resistance", HEALTH: "Protected Health", PEACEBOUND: "Peacebound", IMPE: "Impedance", REPEL: "Repel Spirit-Kin"}
WARD_READING = {ENERGY: "creatures inside take half damage of the energy type you choose while they remain inside",
                HEALTH: "creatures inside take half Poison damage and have Advantage on saves against poison and disease while they remain inside",
                PEACEBOUND: "a creature attempting an attack or harmful technique inside makes a Wisdom save; failure: its action fails and its cost is lost; "
                "success: the Ward ends and creatures inside are immune to your Peacebound Ward until the next dawn",
                IMPE: "a creature that tries to enter this Ward, or move closer to its centre, makes a Wisdom save the first time it tries on its "
                "turn; failure: it cannot enter or move closer to the centre until the start of its next turn; success: it moves normally",
                REPEL: "a creature of a family you chose makes a Charisma save to cross the edge; failure: it cannot cross; "
                "success: it crosses and is immune to your Repel Spirit-Kin Wards until the next dawn"}
ENERGY_TYPES = ("acid", "cold", "fire", "lightning", "radiant", "thunder")
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
FAMILIES = ("celestial", "fiend", "fey", "undead")
WARD_SIZES = (20, 15, 10, 5)          # "you may reduce its size when creating it" (the printed Ward is 20 feet of radius)
COMPASS = ((0.0, -1.0, "north"), (0.7071, -0.7071, "north-east"), (1.0, 0.0, "east"), (0.7071, 0.7071, "south-east"),
           (0.0, 1.0, "south"), (-0.7071, 0.7071, "south-west"), (-1.0, 0.0, "west"), (-0.7071, -0.7071, "north-west"))
READING = {ARMORED: "its AC is at least your Cultivation Save DC", SHIELDED: "+2 AC, as a shield",
           SLIPPERY: "Advantage on saves against Restrained and forced movement and on escape checks",
           ENERGY: "Resistance to one energy damage type", HEALTH: "Resistance to Poison damage, Advantage on saves against poison and disease",
           PUNISHMENT: "a creature that hits it with an attack takes Psychic damage", SPELL_WARD: "Advantage on saves against techniques",
           PEACEBOUND: "a creature attacking it must pass a Wisdom save or the attack fails; its own attack ends the Aegis",
           IMPE: "a creature that tries to step into a space within 5 feet of the bearer makes a Wisdom save; failure: it cannot enter that "
           "space until the start of its own next turn. Spend 1 more cultivation resource when you make it to keep creatures 10 feet off",
           HEAVEN: "AC at least your save DC + 2; once, it drops to 1 HP instead of 0 and the Aegis ends"}
PUNISHMENT_DICE = [[1, 4, 0, 6], [5, 10, 1, 6], [11, 16, 2, 6], [17, 20, 3, 6]]  # "CL 1-4: PB; 5-10: 1d6 + PB; 11-16: 2d6 + PB; 17-20: 3d6 + PB"
PEACE_IMMUNE = "protection_peace_round_immune"  # the Ward owner's turn flag ("_round_" keys survive the turn reset and are saved)


# ------------------------------------------------------------------------------------------------ the Aegis record
AEGIS_UNWILLING_SAVE = "An unwilling creature may make a Wisdom saving throw to resist receiving an Aegis."
AEGIS_RESIST_READING = (" If the creature would rather not have it, it can try to turn it away with a Wisdom"
                        " saving throw against your Cultivation Save DC.")


def aegis_effect(talent: str, persistent: bool) -> dict[str, Any]:
    """The row one compiled Aegis action runs, carrying the Aegis record's printed refusal path.

    "An Aegis is a protective cultivation effect placed on one creature. ... An unwilling creature may make a
    Wisdom saving throw to resist receiving an Aegis." The recipient's own answer is what "unwilling" means, so the
    recipient is asked (asking a creature on its own turn and on somebody else's; an AI recipient answers from its
    own side of the fight), and a refusal is resolved by the printed Wisdom save rather than guessed: the Aegis lands
    only when that save fails. ``target_only`` keeps the action's already selected creature, so this adds the refusal
    path without adding a second recipient or a second action, and ``unwilling_save`` is the documented refusal branch
    of ``choose_willing`` (combat/ext/willing_targets.py) -- reused here rather than reimplemented.

    Inert for a caster who owns no Aegis talent, because only ``protection_actions`` calls this.
    """
    return {"type": "choose_willing", "applies_to": "target", "range_ft": 5, "target_only": True,
            "unwilling_save": {"ability": "WIS", "evidence": AEGIS_UNWILLING_SAVE},
            "consent_text": "If it is unwilling, it may try to resist with a Wisdom saving throw.",
            "effects": [{"type": "protection_aegis", "talent": talent, "persistent": persistent, "applies_to": "ally"}]}


def _mark_ids(owner_id: str) -> tuple[str, str]:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(AEGIS_MARK, owner_id), mark_condition_id(PERSISTENT_MARK, owner_id)


def aegises(actor: Any, owner_id: str | None = None, *, persistent: bool | None = None) -> list[tuple[str, Any]]:
    """The Aegises ``actor`` bears as (instance id, condition): optionally one creator's, optionally only Persistent ones."""
    found = []
    for key, condition in actor.conditions.items():
        data = condition.data or {}
        if not data.get("aegis_talent"):
            continue
        if owner_id is not None and condition.source_actor_id != owner_id:
            continue
        if persistent is not None and (data.get("mark") == PERSISTENT_MARK) != persistent:
            continue
        found.append((key, condition))
    return found


def _with(actor: Any, talent: str) -> list[tuple[str, Any]]:
    return [(key, c) for key, c in aegises(actor) if (c.data or {}).get("aegis_talent") == talent]


def _dc(condition: Any) -> int:
    return int(((condition.data or {}).get("numbers") or {}).get("save_dc") or 10)


def end_aegis(engine: Any, holder: Any, key: str, reason: str) -> None:
    """End one Aegis: its mark and anything its ability put on the bearer (Heaven-Sheltering's Advantage and Resistance,
    Shielded's stored suppression)."""
    condition = holder.conditions.pop(key, None)
    if condition is None:
        return
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                         payload={"condition_id": condition.condition_id, "instance_id": key, "reason": reason})
    for mid, modifier in list(holder.modifiers.items()):
        if modifier.source_definition_id == condition.source_definition_id:
            del holder.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=condition.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"modifier_id": mid, "reason": "AEGIS_ENDED"})
    if (condition.data or {}).get("aegis_talent") == SHIELDED:
        _drop_shield_suppression(engine, holder, "AEGIS_ENDED")


# ------------------------------------------------------------------------------------------------ compiled Aegis / Ward actions
@hook("compile_actions")
def protection_actions(info: dict[str, Any]) -> list[Any] | None:
    if PROTECTION not in info["spheres"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    from ..action_variants import choice, with_variant

    owned = set(info["owned_ids"])
    pools = [p for p in ("qi", "stamina", "resonance") if p in (info.get("pools") or [])] or ["qi"]
    cp = f"resource:core.{pools[0]}"
    made = []

    def action(kind: str, talent: str, name: str, persistent: bool, extra_cp: int, target_kind: str, range_ft: Any, typed: dict[str, Any], text: str) -> None:
        cost = extra_cp + (2 if persistent else 0)
        slug = talent.rsplit(".", 1)[-1].lower()
        base = f"action:typed.{info['short']}.{kind}.{slug}"
        choices = [choice("duration", "persistent", "Persistent — no Concentration", ((cp, 2),))] if persistent else []
        made.append(with_variant(ActionDefinition(
            source_definition_id=base + (".persistent" if persistent else ""),
            display_name=f"{kind.title()}: {name}", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind=target_kind, range_ft=range_ft, costs=((cp, cost),) if cost else (), concentration=not persistent,
            parameters={"typed": {**typed, "numbers": dict(info["numbers"]), "riders": [], "sphere": PROTECTION,
                                  "duration": {**typed["duration"], "concentration": not persistent}},
                        "expected_damage": 0, f"protection_{kind}": talent,
                        "description": text + (" Lasts without Concentration." if persistent else " Requires Concentration.")
                        + (f" Cost: {cost} {pools[0].title()} from your cultivation resource pool"
                           + (f" ({extra_cp} base + 2 to make it Persistent)." if persistent else ".")
                           if cost else " Cost: no cultivation resources.")}), base, f"{kind.title()}: {name}", choices))

    for talent, name in AEGIS_TALENTS.items():
        if talent != ARMORED and talent not in owned:
            continue
        for persistent in (False, True):  # "Spell Ward - Aegis. Cost: 1 CP"
            action("aegis", talent, name, persistent, 1 if talent == SPELL_WARD else 0, "ALLY_OR_SELF", 5,
                   {"effects": [aegis_effect(talent, persistent)],
                    "duration": {"kind": "hours", "amount": 1}, "source": "PROTECTION_BASE_AEGIS", "range_ft": 5},
                   f"Action, touch: you or an ally gains the {name} Aegis ({READING[talent]}) for up to 1 hour; one Aegis from you per creature."
                   + AEGIS_RESIST_READING)
    for talent, name in WARD_TALENTS.items():
        if talent in owned:
            for persistent in (False, True):
                action("ward", talent, name, persistent, 0, "SELF", None,
                       {"effects": [{"type": "protection_ward", "talent": talent}], "duration": {"kind": "minutes", "amount": 1},
                        "source": "PROTECTION_BASE_WARD"},
                       f"Action: a {name} Ward fills a 20-foot radius around you and stays where it is made, for up to 1 minute; one Ward at a time. "
                       f"Within this protected area, {WARD_READING[talent]}.")
    # "An Aegis may be ended early by its creator without spending an action." (rider lane C13, 2026-09-30)
    made.append(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.aegis.end", display_name="End an Aegis you made", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=None,
        parameters={"typed": {"effects": [{"type": "protection_end_aegis", "applies_to": "ally"}], "numbers": dict(info["numbers"]), "riders": [],
                              "duration": {"kind": "instant"}, "source": "PROTECTION_BASE_AEGIS"},
                    "expected_damage": 0, "player_only": True, "protection_end_aegis": True,
                    "description": "No action: end an Aegis you created on yourself or an ally; its protection stops now."}))
    return made or None


@hook("candidate_allowed")
def end_aegis_needs_one(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("protection_end_aegis"):
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), actor.entity_id))
    return target is not None and bool(aegises(target, actor.entity_id))



@effect("protection_aegis")
def make_aegis(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry
    from .needle import CHOICE, ask, checkpoint_id

    talent = str(row["talent"])
    persistent = bool(row.get("persistent"))
    name = PERSISTENT_MARK if persistent else AEGIS_MARK
    subjects = _default_subject(ctx, row, harmful=False)
    if ctx.intent is not None and ctx.intent.target_ids == (ctx.actor.entity_id,):
        subjects = [ctx.actor]
    for subject in subjects:
        if subject is None or not subject.active:
            continue
        for key, _old in aegises(subject, ctx.actor.entity_id):  # "only one Aegis created by the same cultivator at a time"
            end_aegis(ctx.engine, subject, key, "REPLACED")
        label = f"{AEGIS_TALENTS.get(talent, 'Heaven-Sheltering')} Aegis from {ctx.actor.display_name}: {READING.get(talent, '')}"
        data = {"mark": name, "aegis_talent": talent,
                "numbers": {key: int(ctx.numbers.get(key) or default) for key, default in (("pb", 2), ("cl", 1), ("save_dc", 10))}}
        if talent == ENERGY:
            chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "protection_energy", subject.entity_id), ctx.actor, CHOICE + "protection_energy",
                         list(ENERGY_TYPES), labels={kind: f"Resistance to {kind.title()} damage" for kind in ENERGY_TYPES}, preferred=["fire"],
                         name="Energy Resistance", prompt=f"Energy Resistance Aegis on {subject.display_name}: choose the damage type it resists.")
            data["energy"] = (chosen[0] if chosen else "fire").upper()
            label = f"Energy Resistance Aegis from {ctx.actor.display_name}: Resistance to {data['energy'].title()} damage"
        if talent == IMPE:
            data["feet"] = _apron_distance(ctx, "protection_impedance_aegis", "Impedance Aegis",
                                           f"Impedance Aegis on {subject.display_name}: how far out does it keep other creatures?")
        data["label"] = label + (" (Persistent)" if persistent else "")
        ctx.engine._apply_condition(subject, _mark_ids(ctx.actor.entity_id)[1 if persistent else 0], ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, {}, subject, condition=True) or "UNTIL_REMOVED", data=data)


def _apron_distance(ctx: Any, name: str, menu: str, prompt: str) -> int:
    """The Aegis's own printed augment -- "Augment - 1 CP: Increase the protected distance to 10 feet", printed under the
    Aegis and nowhere else. The nearer 5 feet is printed; the wider one costs 1 cultivation resource more, asked and paid
    as one quoted choice, and is not offered at all to a caster who cannot pay. The Ward's Impedance has no such option:
    its printed reach is the Ward itself ("cannot enter or move closer to the center"), so there is nothing to pay to
    widen it and nothing here that would."""
    from .choice_costs import payable
    from .needle import CHOICE, ask, checkpoint_id

    pool = next((name for name in CP_POOLS if int(ctx.actor.resources.get(name, 0)) >= 1), None)
    price = payable(ctx.actor, pool, 1) if pool else None
    options = ["5", "10"] if price is not None else ["5"]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, name, ctx.actor.entity_id), ctx.actor, CHOICE + name,
                 options, labels={"5": "5 feet (printed)", "10": "10 feet (costs 1 more cultivation resource)"},
                 preferred=["5"], allow_decline=True, name=menu, prompt=prompt, payment=price)
    if (chosen or ["5"])[0] == "10" and price is not None:
        price.pay(ctx.engine, ctx.actor, IMPE)
        return 10
    return 5


@effect("protection_end_aegis")
def end_created_aegis(ctx: Any, row: dict[str, Any]) -> None:
    """Free creator control: remove the selected creature's Aegis benefits immediately."""
    from ..typed_executor import effect_subjects
    from .. import concentration

    # Existing sealed lane bundles may omit applies_to. Route those controls
    # to their selected bearer too, without rewriting their saved definitions.
    for subject in effect_subjects(ctx, {**row, "applies_to": "ally"}, harmful=False):
        if subject is None:
            continue
        ended_copies = set()
        for key, condition in aegises(subject, ctx.actor.entity_id):
            if condition.expires_on == "CONCENTRATION_END":
                started = concentration.owner_copy(condition.applied_sequence,
                    concentration.copies(ctx.actor, condition.source_definition_id))
                if started is not None:
                    ended_copies.add(started)
            end_aegis(ctx.engine, subject, key, "CREATOR_ENDED")
        for started in sorted(ended_copies):
            concentration.end_copy(ctx.engine, ctx.actor, started, "CREATOR_ENDED")


# ------------------------------------------------------------------------------------------------ Aegis benefits
SHIELD_OFF = "condition:typed.shield_suppressed"


def _spell_shield(engine: Any, bearer: Any) -> int:
    """"The shield functions as an ordinary shield" -- its +2 AC -- "If the bearer uses the shield-hand to hold another
    object, the shield is suppressed until the start of the next turn in which that hand is free."

    Two halves, because the printed sentence has two halves. A hand has to be free for the shield to exist at all: with both
    hands already holding something (a two-handed weapon, two readied weapons, a grip) it has no hand and stops working, and
    that is read live. Once the bearer *has* used a hand for something else, the suppression is a stored condition
    (SHIELD_OFF) that is remembered at the transaction that fills the hand and taken off at the start of the next turn in
    which a hand is free again -- the printed words -- so an AC query never writes, and a hand freed mid-turn does not hand
    the +2 back early. A mark saved before this rule carries no condition until a hand is actually occupied, which is the
    same reading it had, and picks the suppression up at its first such turn."""
    from . import hand_occupancy

    if any(held.condition_id == SHIELD_OFF for held in bearer.conditions.values()):
        return 0
    return 0 if not hand_occupancy.free_hands(engine, bearer) else 2


def _drop_shield_suppression(engine: Any, bearer: Any, reason: str) -> None:
    for key, held in list(bearer.conditions.items()):
        if held.condition_id != SHIELD_OFF:
            continue
        del bearer.conditions[key]
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                             target_ids=(bearer.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": key, "reason": reason})


def _record_shield_suppression(engine: Any, bearer: Any) -> None:
    """"If the bearer uses the shield-hand to hold another object" -- remember the suppression at the transaction that fills
    the hand, which is the only moment the printed words can be read honestly: every hand change in the engine is a
    condition put on or taken off this creature (a drawn or stowed weapon's grip, a hold on a grappling creature, a
    carried shield), and once both hands are occupied the shield stays suppressed however soon the hand frees again.
    Recording it here is what makes the *same-turn* transition honest -- a bearer who fills a hand and empties it again
    before its next turn starts must not get the +2 back. Only ever puts the condition on: recovery belongs to the next
    turn start, and an AC query stays pure."""
    from . import hand_occupancy

    held = _with(bearer, SHIELDED)
    if not held or any(row.condition_id == SHIELD_OFF for row in bearer.conditions.values()):
        return          # the cheap checks first: this reader runs for every condition event in the fight
    if hand_occupancy.free_hands(engine, bearer):
        return
    engine._apply_condition(bearer, SHIELD_OFF, held[0][1].source_definition_id, bearer.entity_id,
                            expires_on="UNTIL_REMOVED",
                            data={"label": "Its magic shield is suppressed: the shield-hand is holding something else, "
                                           "until the start of the next turn in which that hand is free"})


def _shield_boundary(engine: Any, bearer: Any) -> None:
    """"until the start of the next turn in which that hand is free": a turn boundary is the only place the remembered
    suppression ends. Hands occupied with nothing free -> the suppression is remembered (as it already is if a hand was
    filled mid-turn); a hand free again -> the remembered suppression ends here, at a turn start, which is what the
    printed rule asks for."""
    from . import hand_occupancy

    held = _with(bearer, SHIELDED)
    if not bearer.active or not held:
        return
    if hand_occupancy.free_hands(engine, bearer):
        _drop_shield_suppression(engine, bearer, "SHIELD_HAND_FREE")
    else:
        _record_shield_suppression(engine, bearer)


@hook("ac")
def aegis_ac(engine: Any, target: Any) -> int | None:
    if not aegises(target):
        return None
    # "base AC becomes equal to your Cultivation Save DC": a base AC, so a carried shield's +2 still counts on top (rider lane C13; the
    # compiled AC already holds the shield, so the floor is DC + the shield's own bonus; a broken shield's -2 comes off elsewhere).
    shield = sum(int(row.get("amount") or 0) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])
                 if row.get("block") == "shield_ac")
    floors = [_dc(c) + shield for _k, c in _with(target, ARMORED)] + [_dc(c) + 2 + shield for _k, c in _with(target, HEAVEN)]
    bonus = (max(0, max(floors) - int(target.armor_class)) if floors else 0) + (_spell_shield(engine, target) if _with(target, SHIELDED) else 0)
    return bonus or None


def _technique_save(engine: Any, source: str) -> bool:
    action = engine.action_catalog.get(source or "")
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    kinds = {e.get("attack_kind") for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"}
    return bool(typed) and not typed.get("weapon") and not (kinds & {"weapon", "unarmed"})


@hook("save")
def aegis_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    words = {str(n).lower() for n in named or ()}
    if _with(subject, SLIPPERY) and words & {"restrained", "forced_movement"}:
        return {"modes": ["ADVANTAGE"]}
    if words & {"poisoned", "poison", "disease", "diseased", "damage:poison"} and (_with(subject, HEALTH) or _in_ward(ctx.engine, subject, HEALTH)):
        return {"modes": ["ADVANTAGE"]}
    if _with(subject, SPELL_WARD) and _technique_save(ctx.engine, ctx.source):
        return {"modes": ["ADVANTAGE"]}
    return None


@hook("escape_mode")
def slippery_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _with(escaper, SLIPPERY) else None  # "checks made to escape a Grapple ... to escape bonds"


@hook("damage_defenses")
def aegis_resistance(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: str | None) -> list[dict[str, Any]] | None:
    """Mark-bound Resistance uses the ordinary defense path, including suppression and penetration."""
    kind = str(damage_type or "").upper()
    if not aegises(target):
        return None
    if not (any((c.data or {}).get("energy") == kind for _k, c in _with(target, ENERGY)) or (kind == "POISON" and _with(target, HEALTH))):
        return None
    return [{"kind": "resistance", "damage_types": [kind]}]


@hook('hit_snapshot')
def punishment_snapshot(engine, attacker, target, attack_context, intent):
    rows = [{'owner': c.source_actor_id, 'source': c.source_definition_id, 'numbers': dict(c.data['numbers'])}
            for _, c in _with(target, PUNISHMENT) if c.source_actor_id in engine.state.actors]
    return {PUNISHMENT: rows} if rows else None


@hook('hit_final')
def punishment(ctx, target, kind):
    from ..typed_executor import Context, run_effects

    for receipt in ctx.hit_snapshots.get(PUNISHMENT, ()):
        if not ctx.actor.active:
            break
        owner = ctx.engine.state.actors[receipt['owner']]
        action = ctx.engine.action_catalog.get(receipt['source'])
        if action is None:
            continue
        retaliation = Context(ctx.engine, owner, action, ctx.intent,
            {'numbers': receipt['numbers'], 'effects': [], 'riders': []}, [ctx.actor], ctx.actor)
        note(ctx.engine, action.source_definition_id, owner,
            f'Punishment Aegis: {ctx.actor.display_name} hit {target.display_name} and takes the ward’s Psychic retaliation.',
            (ctx.actor, target))
        run_effects(retaliation, [{'type': 'damage', 'applies_to': 'target', 'formula': 'pb',
            'dice_by_cl': PUNISHMENT_DICE, 'damage_types': ['psychic']}])



# ------------------------------------------------------------------------------------------------ Peacebound
def _offensive(action: Any) -> bool:
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return any(isinstance(e, dict) and (e.get("type") == "attack" or (e.get("type") in ("save", "damage") and e.get("applies_to") not in ("self", "ally")))
               for e in typed.get("effects") or [])


def _peace_save(engine: Any, creature: Any, dc: int, source: str) -> bool:
    roll = engine._roll_save(creature, "WIS", dc, source)
    return roll is not None and roll.total >= dc


def _peace_wards(engine: Any, creature: Any) -> list[Any]:
    return [zone for zone in _wards(engine, PEACEBOUND) if engine._footprint_intersects(creature, zone.affected_cells)
            and creature.entity_id not in ((engine.state.actors.get(zone.owner_id) or creature).turn_flags.get(PEACE_IMMUNE) or [])]


def _break_ward(engine: Any, zone: Any, breaker: Any) -> None:
    from .. import zones

    owner = engine.state.actors.get(zone.owner_id)
    inside = [a.entity_id for a in engine.state.actors.values() if a.active and engine._footprint_intersects(a, zone.affected_cells)]
    if owner is not None:
        owner.turn_flags[PEACE_IMMUNE] = sorted({*(owner.turn_flags.get(PEACE_IMMUNE) or []), *inside})
    zones.remove(engine, zone, "PEACEBOUND_BROKEN")
    note(engine, zone.source_definition_id, breaker, f"Peacebound Ward: {breaker.display_name} passes its Wisdom save; the Ward ends, and the creatures "
         "inside are immune to this Peacebound Ward for the rest of the fight.", (breaker,))


def _peace_verdict(engine: Any, attacker: Any, bearer: Any, cache: dict[Any, Any] | None) -> str | None:
    """"fails" when the Aegis or Ward stops this attack or effect on ``bearer``; None when nothing does (or a save broke it)."""
    if attacker.entity_id == bearer.entity_id:
        return None
    for key, aegis in _with(bearer, PEACEBOUND):
        passed = (cache or {}).get(("peace", key))
        if passed is None:
            passed = _peace_save(engine, attacker, _dc(aegis), aegis.source_definition_id)
            if cache is not None:
                cache[("peace", key)] = passed
        if passed:
            end_aegis(engine, bearer, key, "PEACEBOUND_BROKEN")
            note(engine, aegis.source_definition_id, attacker, f"Peacebound Aegis: {attacker.display_name} passes its Wisdom save; "
                 f"{bearer.display_name}'s Aegis ends.", (bearer,))
        else:
            note(engine, aegis.source_definition_id, attacker, f"Peacebound Aegis: {attacker.display_name} fails its Wisdom save; its attack "
                 f"on {bearer.display_name} fails.", (bearer,))
            return "fails"
    for zone in _peace_wards(engine, attacker):
        passed = (cache or {}).get(("peace", zone.zone_id))
        if passed is None:
            passed = _peace_save(engine, attacker, int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10), zone.source_definition_id)
            if cache is not None:
                cache[("peace", zone.zone_id)] = passed
            if passed:
                _break_ward(engine, zone, attacker)
            else:
                note(engine, zone.source_definition_id, attacker, f"Peacebound Ward: {attacker.display_name} fails its Wisdom save; "
                     "its violent action fails.", (bearer,))
        if not passed:
            return "fails"
    return None


@hook("hit_response")
def peacebound_attack(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    if not (_with(target, PEACEBOUND) or _peace_wards(engine, attacker)):
        return None
    if _peace_verdict(engine, attacker, target, None) == "fails":
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()  # "The action fails": no AC was compared
    return None


@hook("save_gate")
def peacebound_technique(ctx: Any, subject: Any) -> bool | None:
    if subject.team_id == ctx.actor.team_id or not (_with(subject, PEACEBOUND) or _peace_wards(ctx.engine, ctx.actor)):
        return None
    return False if _peace_verdict(ctx.engine, ctx.actor, subject, ctx.damage_cache) == "fails" else None


def _bearer_acts(engine: Any, actor: Any) -> None:
    for key, aegis in _with(actor, PEACEBOUND):  # "If the bearer takes an offensive action, the Aegis ends immediately."
        end_aegis(engine, actor, key, "BEARER_ATTACKED")
        note(engine, aegis.source_definition_id, actor, f"Peacebound Aegis: {actor.display_name} takes an offensive action; its Aegis ends.")


@hook("attack_sequence_start")
def peacebound_bearer_attacks(ctx: Any) -> None:
    if _with(ctx.actor, PEACEBOUND):
        _bearer_acts(ctx.engine, ctx.actor)


@hook("technique_start")
def peacebound_bearer_technique(engine: Any, actor: Any, action: Any) -> None:
    if _with(actor, PEACEBOUND) and _offensive(action):
        _bearer_acts(engine, actor)
    return None


# ------------------------------------------------------------------------------------------------ Ward
def _wards(engine: Any, talent: str) -> list[Any]:
    from .. import zones

    found = []
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        if action is not None and (action.parameters or {}).get("protection_ward") == talent:
            found.append(zone)
    return found


def _in_ward(engine: Any, creature: Any, talent: str) -> bool:
    return any(engine._footprint_intersects(creature, zone.affected_cells) for zone in _wards(engine, talent))


def _ward_profile(zone: Any) -> dict[str, Any]:
    """The creator's own configuration for this Ward (zones.create's ``profile``), or an empty record for an older one."""
    profile = (getattr(zone, "trigger_profile", None) or {}).get("profile")
    return dict(profile) if isinstance(profile, dict) else {}


def _ward_size(ctx: Any) -> int:
    """"you may reduce its size when creating it": the printed Ward is 20 feet of radius; any smaller one is asked."""
    from .needle import CHOICE, ask, checkpoint_id

    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "protection_ward_size", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "protection_ward_size", [str(size) for size in WARD_SIZES],
                 labels={str(size): f"{size} feet from the centre ({size * 2} feet across)" for size in WARD_SIZES},
                 preferred=["20"], name="Ward size",
                 prompt="How large should this Ward be? It reaches 20 feet from where you stand unless you make it smaller.")
    return int((chosen or ["20"])[0])


@effect("protection_ward")
def make_ward(ctx: Any, row: dict[str, Any]) -> None:
    from .. import spatial_areas, zones
    from .needle import CHOICE, ask, checkpoint_id

    for zone in zones.typed_zones(ctx.engine):  # "you may maintain only one Ward at a time"
        action = ctx.engine.action_catalog.get(zone.source_definition_id)
        if zone.owner_id == ctx.actor.entity_id and action is not None and (action.parameters or {}).get("protection_ward"):
            zones.remove(ctx.engine, zone, "REPLACED")
    talent = str(row["talent"])
    inside: list[dict[str, Any]] = []
    profile: dict[str, Any] = {}
    if talent == ENERGY:
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "protection_energy_ward", ctx.actor.entity_id), ctx.actor, CHOICE + "protection_energy",
                     list(ENERGY_TYPES), labels={kind: f"Resistance to {kind.title()} damage" for kind in ENERGY_TYPES}, preferred=["fire"],
                     name="Energy Resistance Ward", prompt="Energy Resistance Ward: choose the damage type creatures inside resist.")
        kind = (chosen[0] if chosen else "fire").upper()
        inside = [{"id": "protection_energy", "who": "any", "name": f"Energy Resistance Ward ({kind.title()})",
                   "modifiers": [{"field": "damage_resistance", "value": kind}], "reading": f"Resistance to {kind.title()} damage while inside."}]
    elif talent == HEALTH:
        inside = [{"id": "protection_health", "who": "any", "name": "Protected Health Ward", "modifiers": [{"field": "damage_resistance", "value": "POISON"}],
                   "reading": "Resistance to Poison damage and Advantage on saves against poison and disease while inside."}]
    size_ft = _ward_size(ctx)
    if talent == REPEL:
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "protection_repel", ctx.actor.entity_id), ctx.actor, CHOICE + "protection_repel",
                     list(FAMILIES), labels={family: f"{family.title()}s" for family in FAMILIES}, preferred=["undead"],
                     minimum=1, maximum=len(FAMILIES), name="Repel Spirit-Kin Ward",
                     prompt="Repel Spirit-Kin: which kinds of creature does this Ward turn away? Choose one or more.")
        families = chosen or ["undead"]
        # "A creature already inside when the Ward appears is unaffected" -- printed without "another" or "hostile", so every
        # creature standing inside when it appears is recorded, of any team. The membership test is the very volume query the
        # crossing below uses (spatial_areas.zone_contains against the prospective zone), so the exemption cannot disagree with
        # the sphere the Ward really becomes. Pure geometry: nothing is placed, spent or recorded until zones.create.
        prospective = zones.prospective_zone(ctx, _ward_spec(talent, size_ft, inside, {}), ctx.actor.position)
        profile["repel"] = {"families": families,
                            "inside": sorted(creature.entity_id for creature in ctx.engine.state.actors.values()
                                             if creature.active and spatial_areas.zone_contains(ctx.engine, creature, prospective))}
    zones.create(ctx, _ward_spec(talent, size_ft, inside, profile, duration=dict(ctx.typed.get("duration") or {"kind": "minutes", "amount": 1})))


def _ward_spec(talent: str, size_ft: int, inside: list[dict[str, Any]], profile: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """The Ward this talent makes, as zones.create takes it. One builder, so the geometry the initial exemptions were read
    against (zones.prospective_zone) is the geometry that is placed."""
    return {"name": f"{WARD_TALENTS.get(talent, 'Protection')} Ward", "shape": "sphere", "size_ft": size_ft, "centered_on_self": True,
            "duration": extra.pop("duration", {"kind": "minutes", "amount": 1}), "terrain": [], "difficult": None,
            "obscured": None, "color": "#8fb8de", "visual": {"material": "generic"}, "triggers": [], "inside": inside,
            **({"profile": profile} if profile else {}), **extra}


# ------------------------------------------------------------------------------------------------ the Ward's edge
# One crossing gate for every Protection rule that turns a voluntary step back. ``movement_attempt`` runs before the step is
# paid for, so a stop leaves the mover where it was and the rest of its path untouched (the same contract
# combat/ext/gravity_boundary.py's Event Horizon Prison uses). It is also the seam movement granted by an ability reaches,
# so it re-checks the barrier a failed save already left behind: the printed "It cannot enter that space until the start of
# its next turn" is a standing fact about the creature, not a one-off refusal of the step that happened to fail. The
# ``candidate_allowed`` filter below makes the same reading of a whole Move candidate, over the complete canonical path the
# engine will walk (obstacle detours included), so a detour to a square that ends no closer is still refused.
APRON = "condition:typed.ward_apron"          # cannot come within N feet of a bearer, or cannot enter a Ward / move closer to its centre
REPEL_BAR = "condition:typed.repel_spirit_kin"  # crossed this caster's Repel Spirit-Kin Ward and cannot be asked again ("until the next dawn")
KEEP_OUT, NO_CLOSER = "keep_out", "no_closer"


def _apron_anchor(engine: Any, condition: Any) -> tuple[Any, int, Any] | None:
    """The Ward this bar belongs to while it stands, else the living bearer of the Aegis: (zone or None, feet, centre)."""
    data = condition.data or {}
    feet = int(data.get("feet") or 0)
    zone = engine.state.zones.get(str(data.get("ward") or ""))
    if zone is not None and zone.active:
        return zone, feet, zone.center
    if feet <= 0:
        return None
    anchor = engine.state.actors.get(str(data.get("anchor") or ""))
    return (None, feet, anchor.position) if anchor is not None and anchor.active else None


def _bar_words(held: Any) -> str:
    """The printed restriction, in the words the rules use."""
    data = held.data or {}
    return (f"cannot come within {int(data.get('feet') or 0)} feet of the bearer" if data.get("bar") == KEEP_OUT
            else "cannot enter this Ward or move closer to its centre")


def _hold(engine: Any, mover: Any, source: str, owner_id: str, bar: str, *, feet: int = 0, ward: str = "", anchor: str = "") -> None:
    """"until the start of its next turn" -- the failing creature's own next turn, named exactly (combat/ext/effect_durations'
    ``token``), so an intervening turn of the Ward's creator cannot take the restriction away early."""
    from . import effect_durations

    where = "this Ward's centre" if ward else "the bearer"
    engine._apply_condition(mover, APRON, source, owner_id,
                            expires_on=effect_durations.token("start", mover.entity_id, int(mover.turns_started) + 1),
                            data={"feet": feet, "ward": ward, "anchor": anchor, "bar": bar,
                                  "label": (f"Cannot come within {feet} feet of {where} until the start of its next turn" if bar == KEEP_OUT
                                            else "Cannot enter this Ward or move closer to its centre until the start of its next turn")})


def _ward_step_breaks(engine: Any, mover: Any, zone: Any, previous: Any, nxt: Any) -> bool:
    """"attempts to enter the Ward or move closer to the Ward's center": the creature's own volume, before and after the
    step, against the Ward's own sphere (``spatial_areas.zone_contains``, the query the crossing below uses).

    The printed trigger has two halves and each is asked in its own right, so the two are not collapsed into one
    distance test. A square outside the Ward after the step is never refused: walking out of a Ward the creature was
    already standing in is not something the printed words reach, however close the step starts. A square inside it after
    the step, having been outside before, is "attempting to enter the Ward" at whatever distance the centre happens to
    be -- walking around the rim is still entering. Only a creature already inside is asked whether it closed on the
    centre, which is the other half of the printed sentence. One reader, shared with the stored barrier below, so the
    first step and every later one are read the same way."""
    from ..spatial_areas import zone_contains

    if not zone_contains(engine, mover, zone, at=nxt):
        return False
    if not zone_contains(engine, mover, zone, at=previous):
        return True
    return engine.grid.distance_ft(nxt, zone.center) < engine.grid.distance_ft(previous, zone.center)


def _ward_aprons(engine: Any, mover: Any, previous: Any, nxt: Any) -> list[Any]:
    """Impedance Wards this step enters or closes in on. Printed "A creature", so the Ward's own creator is asked like
    anyone else."""
    return [zone for zone in _wards(engine, IMPE) if _ward_step_breaks(engine, mover, zone, previous, nxt)]


def _aegis_aprons(engine: Any, mover: Any, nxt: Any) -> list[tuple[Any, Any, int]]:
    """Bearing Impedance Aegises this step would take the mover within reach of: "attempting to enter a space within N feet
    of the bearer" is about the square being entered, so a creature already inside that distance is asked again when it
    steps to another square inside it -- and so is the bearer, which is itself a creature within N feet of itself."""
    found = []
    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for _key, aegis in _with(holder, IMPE):
            feet = int((aegis.data or {}).get("feet") or 5)
            if feet > 0 and engine.grid.distance_ft(nxt, holder.position) <= feet:
                found.append((holder, aegis, feet))
    return found


def _repel_guards(engine: Any, mover: Any, previous: Any, nxt: Any) -> list[Any]:
    """Repel Spirit-Kin Wards this step crosses out of, for a creature of a family the Ward turns away."""
    from . import creature_kinds
    from ..spatial_areas import zone_contains

    found = []
    for zone in _wards(engine, REPEL):
        repel = _ward_profile(zone).get("repel") or {}
        if not creature_kinds.matches(mover, repel.get("families") or ()):
            continue
        if mover.entity_id in (repel.get("inside") or ()):
            continue  # "A creature already inside when the Ward appears is unaffected"
        if any(_repel_paid_for(held, zone) for held in mover.conditions.values()):
            continue  # it crossed once and paid for it ("your Repel Spirit-Kin Ward until the next dawn")
        if zone_contains(engine, mover, zone, at=previous) == zone_contains(engine, mover, zone, at=nxt):
            continue
        found.append(zone)
    return found


def _repel_paid_for(held: Any, zone: Any) -> bool:
    """Whether this creature has already paid to cross this caster's Repel Spirit-Kin Ward. Keyed to the caster, because
    the printed immunity is to "your Repel Spirit-Kin Ward": a Ward this caster makes again is the same Ward to the
    creature that already crossed it. The older "ward" key is still read, so a fight saved with it keeps its immunity."""
    data = held.data or {}
    return held.condition_id == REPEL_BAR and (str(data.get("caster") or "") == zone.owner_id
                                               or str(data.get("ward") or "") == zone.zone_id)


def _apron_blocks(engine: Any, mover: Any, previous: Any, nxt: Any) -> tuple[Any, Any] | None:
    """The stored barrier this one step breaks, as (condition, Ward or None), or None. One reader for both callers: the
    step gate, which walks the path the engine is walking, and the menu filter, which walks the whole candidate."""
    for held in mover.conditions.values():
        if held.condition_id != APRON:
            continue
        anchored = _apron_anchor(engine, held)
        if anchored is None:
            continue
        zone, feet, centre = anchored
        if (held.data or {}).get("bar") == NO_CLOSER:
            if zone is None or not _ward_step_breaks(engine, mover, zone, previous, nxt):
                continue
        elif engine.grid.distance_ft(nxt, centre) > feet:
            continue
        return held, zone
    return None


@hook("movement_attempt")
def ward_edge(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> Any:
    if not mover.active:
        return None
    blocked = _apron_blocks(engine, mover, previous, nxt)
    if blocked is not None:
        held, zone = blocked
        which = "Impedance Ward" if zone is not None else "Impedance Aegis"
        return {"stop": True, "source_id": zone.source_definition_id if zone is not None else held.source_definition_id,
                "label": f"{which}: {mover.display_name} already failed its Wisdom save, so it {_bar_words(held)} until "
                         "the start of its own next turn."}
    for zone in _ward_aprons(engine, mover, previous, nxt):
        key = f"protection_impedance_ward:{zone.owner_id}"  # one save a turn, and it survives the caster re-making the Ward
        if mover.turn_flags.get(key):
            continue  # "for the first time on a turn"
        mover.turn_flags[key] = True
        owner = engine.state.actors.get(zone.owner_id)
        dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or _dc(owner) if owner is not None else 10)
        roll = engine._roll_save(mover, "WIS", dc, zone.source_definition_id)
        if roll is None or roll.total >= dc:
            note(engine, zone.source_definition_id, mover, f"Impedance Ward: {mover.display_name} passes its Wisdom save and moves normally.")
            continue
        _hold(engine, mover, zone.source_definition_id, zone.owner_id, NO_CLOSER, ward=zone.zone_id)
        return {"stop": True, "source_id": zone.source_definition_id,
                "label": f"Impedance Ward: {mover.display_name} fails its Wisdom save, so it cannot enter this Ward or move closer to its "
                         "centre until the start of its own next turn."}
    for holder, aegis, feet in _aegis_aprons(engine, mover, nxt):
        dc = _dc(aegis)
        roll = engine._roll_save(mover, "WIS", dc, aegis.source_definition_id)
        if roll is None or roll.total >= dc:
            note(engine, aegis.source_definition_id, mover, f"Impedance Aegis: {mover.display_name} passes its Wisdom save and moves normally.",
                 (holder,))
            continue
        _hold(engine, mover, aegis.source_definition_id, aegis.source_actor_id, KEEP_OUT, feet=feet, anchor=holder.entity_id)
        return {"stop": True, "source_id": aegis.source_definition_id,
                "label": f"Impedance Aegis: {mover.display_name} fails its Wisdom save, so it cannot come within {feet} feet of "
                         f"{holder.display_name} until the start of its own next turn."}
    for zone in _repel_guards(engine, mover, previous, nxt):
        owner = engine.state.actors.get(zone.owner_id)
        dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
        roll = engine._roll_save(mover, "CHA", dc, zone.source_definition_id)
        if roll is None or roll.total >= dc:
            engine._apply_condition(mover, REPEL_BAR, zone.source_definition_id, zone.owner_id, expires_on="UNTIL_REMOVED",
                                    data={"caster": zone.owner_id, "ward": zone.zone_id,
                                          "label": "Immune to your Repel Spirit-Kin Wards until the next dawn"})
            note(engine, zone.source_definition_id, mover, f"Repel Spirit-Kin Ward: {mover.display_name} passes its Charisma save and crosses; "
                 "this caster's Repel Spirit-Kin Ward cannot turn it away again.", (owner,) if owner is not None else ())
            continue
        return {"stop": True, "source_id": zone.source_definition_id,
                "label": f"Repel Spirit-Kin Ward: {mover.display_name} fails its Charisma save and cannot cross this Ward's edge."}
    return None


@hook("candidate_allowed")
def apron_excludes_the_protected_space(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"It cannot enter that space until the start of its next turn" / "cannot enter or move closer to the center":
    the barrier a failed save leaves is honoured by every later path, not only the step that failed, and by the whole
    candidate -- every square of the canonical path the engine will walk, detours around obstacles included, so a route
    that happens to end no closer cannot be used to step in. Teleports and forced displacement are not willing moves and
    are untouched, exactly as for the crossing gate above."""
    if getattr(candidate.kind, "value", candidate.kind) != "MOVE" or candidate.destination is None:
        return None
    previous = actor.position
    for square in (*candidate.canonical_path, candidate.destination):
        if square == previous:
            continue
        if _apron_blocks(engine, actor, previous, square) is not None:
            return False
        previous = square
    return None


# ------------------------------------------------------------------------------------------------ Succor
@hook('ally_row_allowed')
def punishment_succor_attack_only(engine, reactor, subject, row):
    if row.get('feature_id') != PUNISHMENT:
        return None
    attack = engine.damage_context()
    return None if attack is not None and attack.target_id == subject.entity_id else False


@hook('mark_consume')
def sacrifice_aegis(ctx, row, subject):
    if row.get('mark') != PERSISTENT_MARK:
        return None
    mine = aegises(subject, ctx.actor.entity_id, persistent=True)
    if not mine:
        return None
    end_aegis(ctx.engine, subject, mine[0][0], 'SACRIFICED')
    # hit_final owns the hit's retaliation; consuming the mark never deals it again.
    return True


@hook('reaction_consent')
def punishment_consent(engine, row, reactor, checkpoint):
    if row.get('feature_id') != PUNISHMENT:
        return None
    from .needle import CHOICE, ask, checkpoint_id

    attack = engine.damage_context()
    if attack is None:
        return False
    target = engine.state.actors[attack.target_id]
    attacker = engine.state.actors[attack.attacker_id]
    numbers = row.get('numbers') or {}
    cl, pb = int(numbers.get('cl') or 1), int(numbers.get('pb') or 2)
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1 if cl >= 5 else 0
    amount = f'{count}d6 + {pb}' if count else str(pb)
    action = engine.action_catalog.get(attack.source_id)
    attack_name = action.display_name if action is not None else 'an attack'
    chosen = ask(engine, getattr(engine, '_active_intent', None),
        checkpoint_id(engine, 'punishment_succor', attack.roll_id, target.entity_id), reactor,
        CHOICE + 'punishment_succor', ['sacrifice'], allow_decline=True, preferred=['sacrifice'],
        name='Punishment Succor',
        labels={'sacrifice': f'Use your Reaction and end your persistent ward on {target.display_name}: '
                f'{attacker.display_name} takes {amount} Psychic damage; no cultivation-resource cost.'},
        prompt=f'Punishment Succor: {attacker.display_name} hit {target.display_name} with {attack_name}. '
               'Sacrifice your Persistent Aegis (the ward protecting this ally) for extra retaliation? '
               'The ward’s retaliation for this hit still happens.')
    return bool(chosen)


def _luck() -> None:
    from . import d20_rewrite as dr

    def guard(engine: Any, holder: Any, rc: Any) -> bool:
        return bool(aegises(rc.roller, holder.actor.entity_id, persistent=True))

    def sacrifice(engine: Any, holder: Any, rc: Any) -> None:
        for key, _aegis in aegises(rc.roller, holder.actor.entity_id, persistent=True)[:1]:
            end_aegis(engine, rc.roller, key, "SACRIFICED")  # "Sacrifice one Persistent Aegis on that creature"

    # The trigger is any save, even a success. Automatic allies keep a success;
    # Ask-me owners retain the printed option to risk replacing it.
    dr.register(dr.Rule(kind="protection_luck", name="Luck (Succor)", rolls=("save",), who="team", range_ft=300, when="any", op="reroll",
                        ai=lambda engine, holder, rc: rc.succeeded() is False,
                        reaction=True, feature=LUCK, guard=guard, on_use=sacrifice, checkpoint="D20_REROLL_ALLY",
                        say=lambda engine, holder, rc, new: f"Luck: {holder.actor.display_name} sacrifices a Persistent Aegis; "
                                                            f"{rc.roller.display_name} rerolls the saving throw and must use {new.total}."))


_luck()


# ------------------------------------------------------------------------------------------------ Status
# "whether they are unharmed, wounded, disabled, frightened, unconscious, dying, poisoned, diseased, stunned, or
# similarly afflicted", read from the bearer's own committed state. Printed condition names for the conditions the engine
# stores as ``condition:typed.<name>``; "disabled" is this system's own word for hurt badly and the line says so, because
# a player who knows only basic D&D has never heard of a disabled creature.
AFFLICTIONS = {"frightened": "frightened", "unconscious": "unconscious", "incapacitated": "unconscious", "paralyzed": "unable to move",
               "petrified": "petrified", "stunned": "stunned", "poisoned": "poisoned", "diseased": "diseased", "sickened": "sickened",
               "charmed": "charmed", "blinded": "blinded", "deafened": "deafened", "grappled": "grappled", "restrained": "restrained",
               "prone": "prone", "hidden": "hiding", "exhaustion": "exhausted"}
DISABLED = "hurt badly, below half its health, so it is disabled (it acts and moves at half speed and cannot act well)"


def _bearing(holder: Any) -> str:
    """"whether they are unharmed, wounded, disabled, ... dying ..." -- one plain phrase read from the creature's own
    stored state: its real hit points (temporary hit points are a cushion and do not make a creature unhurt), its real life
    state (a bearer at 0 HP with a life state is dying or stable, whichever the fight recorded), and the printed
    conditions it actually bears."""
    if not holder.active:
        return "gone from the fight"  # "This awareness ends if a target dies or leaves the plane."
    if holder.life_state == "DYING":
        return "dying (at 0 hit points, and it will die without help)"
    if holder.life_state == "STABLE":
        return "stable and will not die on its own, but it will not get up by itself"
    if holder.current_hp <= 0:
        return "at 0 hit points"
    said = [word for held in holder.conditions.values()
            for key, word in AFFLICTIONS.items() if held.condition_id == f"condition:typed.{key}"]
    if holder.current_hp * 2 <= holder.maximum_hp:
        said.insert(0, DISABLED)
    elif holder.current_hp < holder.maximum_hp:
        said.insert(0, "wounded")
    return ", ".join(dict.fromkeys(said)) if said else "unharmed"


def _where(engine: Any, watcher: Any, holder: Any) -> str:
    """"the direction and distance" -- the engine's own measured distance and the compass point whose own direction is
    nearest the true one (a bearer ten squares east and one square north is east, not north-east; picking the nearest unit
    step to the displacement made almost any displacement with two components read as a diagonal). Height is added when the
    fight tracks it, since a bearer overhead is not simply "to the east"."""
    feet = engine.grid.distance_ft(watcher.position, holder.position)
    if not feet:
        return "right here"
    dx, dy = float(holder.position.x - watcher.position.x), float(holder.position.y - watcher.position.y)
    toward = min(COMPASS, key=lambda step: _bearing_error(step, dx, dy))
    height = "" if not (engine.grid.finite_heights or holder.position.z or watcher.position.z) else (
        f", {abs(holder.position.z - watcher.position.z) * engine.grid.square_size_ft} feet "
        f"{'up' if holder.position.z > watcher.position.z else 'down'}")
    return f"{feet} feet {toward[2]} away{height}"


def _bearing_error(step: tuple[float, float, str], dx: float, dy: float) -> float:
    """Squared distance from the unit vector of a compass point to the displacement, scaled so a bearing is compared as an
    angle: a step's own length (1 for the four points on the axes, 1.4142 for the diagonals) divided out."""
    length = (step[0] * step[0] + step[1] * step[1]) ** 0.5
    return ((step[0] / length - dx) ** 2 + (step[1] / length - dy) ** 2)


@hook("turn_start")
def status_awareness(engine: Any, actor: Any) -> None:
    """"You always know: the direction and distance to creatures benefiting from one of your Aegises" and how each one
    fares -- one readable line at the start of the owner's turn, so the table is never asked to track it."""
    _status_line(engine, actor)


def _status_line(engine: Any, actor: Any) -> None:
    if not actor.active or not has_row(engine, actor.entity_id, "protection_status"):
        return
    bears = sorted(((holder, aegis) for holder in engine.state.actors.values() for _key, aegis in aegises(holder, actor.entity_id)
                    if holder.active),  # "This awareness ends if a target dies or leaves the plane."
                   key=lambda pair: (engine.grid.distance_ft(actor.position, pair[0].position), pair[0].entity_id))
    if not bears:
        return
    note(engine, "system:protection.status", actor, "Status: " + "; ".join(
        f"{holder.display_name} is {_where(engine, actor, holder)}, {_bearing(holder)}"
        for holder, _aegis in bears), tuple(holder for holder, _aegis in bears))


@hook("turn_start")
def shield_turn_start(engine: Any, actor: Any) -> None:
    """Shielded's "until the start of the next turn in which that hand is free" is decided at a turn boundary."""
    _shield_boundary(engine, actor)


@hook("event")
def shield_occupancy_changed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If the bearer uses the shield-hand to hold another object": the suppression is remembered at the hand change itself,
    not at the next turn boundary. Every way this engine fills or empties a hand is a condition put on or taken off the
    creature (a drawn or stowed weapon's grip, a hold on a grappling creature, a carried shield), so the recorded events
    are the transactions themselves. This is what makes a fill-then-free inside one turn honest: the bearer used the hand,
    so the +2 does not come back until the start of the next turn in which that hand is free. Inert without the Shielded
    Aegis, and it only ever records -- the condition it writes for itself is not occupancy, so it does not recurse."""
    if event_type not in ("CONDITION_APPLIED", "CONDITION_REMOVED"):
        return
    changed = set(kwargs.get("target_ids") or ()) | {str(kwargs.get("actor_id") or "")}
    for actor_id in sorted(changed):
        bearer = engine.state.actors.get(actor_id)
        if bearer is not None and bearer.active:
            _record_shield_suppression(engine, bearer)


@hook("event")
def status_live_awareness(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"You always know" is not a once-a-turn report: when a bearer's health, place or conditions change, the owner is told
    in the same breath, so a turn is never spent acting on what its Status line said at its start.

    Ordinary healing counts as health changing, and it is the commonest way a bearer stops being wounded without any
    condition or life state moving (the engine records it as its own event, HEALING_APPLIED, once the hit points are
    committed). The watcher's own steps count too: the line reports direction *and distance* from the owner, so the owner's
    move changes every bearer's line whether or not the creature that moved bears any of its Aegises."""
    if event_type not in ("DAMAGE_COMMITTED", "MOVEMENT_COMMITTED", "CONDITION_APPLIED", "CONDITION_REMOVED",
                          "LIFE_STATE_CHANGED", "TEMP_HP_GRANTED", "HEALING_APPLIED"):
        return
    changed = set(kwargs.get("target_ids") or ()) | {str(kwargs.get("actor_id") or "")}
    for owner in engine.state.actors.values():
        if not owner.active or not has_row(engine, owner.entity_id, "protection_status"):
            continue
        if owner.entity_id in changed or any(aegises(holder, owner.entity_id)
                                             for holder in engine.state.actors.values() if holder.entity_id in changed):
            _status_line(engine, owner)


# ------------------------------------------------------------------------------------------------ Community
@hook("damage_pending")
def community(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    from .needle import CHOICE, ask, checkpoint_id
    from .damage_transfer_scope import transfers_allowed

    if pending < 2 or engine.__dict__.get("_protection_community") or not target.active or not transfers_allowed(engine, target):
        return None
    for _key, aegis in aegises(target):
        owner = engine.state.actors.get(aegis.source_actor_id)
        if owner is None or not owner.active or not has_row(engine, owner.entity_id, "protection_community"):
            continue
        others = [a for a in engine.state.actors.values() if a.active and a.entity_id != target.entity_id and a.team_id == target.team_id
                  and aegises(a, owner.entity_id)]
        if not others:
            continue
        portion = pending // 2
        held = target.current_hp + target.temporary_hp
        best = max(others, key=lambda a: (a.current_hp + a.temporary_hp, a.entity_id))
        left = best.current_hp + best.temporary_hp - portion
        worth = left > 0 and (pending >= held or left / max(1, best.maximum_hp) > (held - pending) / max(1, target.maximum_hp))
        chosen = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "protection_community", target.entity_id), owner,
                     CHOICE + "protection_community", [a.entity_id for a in others], labels={a.entity_id: f"{a.display_name} takes {portion}" for a in others},
                     preferred=[best.entity_id] if worth else [], allow_decline=True, default="first" if worth else "decline", name="Community",
                     prompt=f"Community: {target.display_name} takes {pending} damage. Move half ({portion}) to another creature bearing your Aegis?")
        taker = engine.state.actors.get(chosen[0]) if chosen else None
        if taker is None:
            return None
        _transfer(engine, taker, target, portion, source_definition_id, source_actor_id, aegis)
        return pending - portion
    return None


def _transfer(engine: Any, taker: Any, target: Any, portion: int, source: str, source_actor_id: str, aegis: Any) -> None:
    """"Transferred damage keeps its original damage type, cannot be transferred again, cannot be redirected by another effect":
    the taker's own Resistance applies once (typed_reactions.defend), then it is committed with no reaction intent."""
    from .. import typed_reactions
    from .damage_transfer_scope import nonrecursive_transfer

    dtype = str(getattr(engine, "_typed_pending_damage_type", None) or "UNTYPED").upper()
    with nonrecursive_transfer(engine, taker) as transfer_flags:
        taken = typed_reactions.defend(engine, taker, portion, dtype, source, source_actor_id)
        previous = (getattr(engine, "_damage_unreduced", None), getattr(engine, "_damage_bonus_already_applied", None))
        engine._damage_unreduced, engine._damage_bonus_already_applied, engine._protection_community = taker.entity_id, taker.entity_id, True
        try:
            engine._commit_damage(taker, taken, dtype, source, source_actor_id or taker.entity_id, None,
                                  reaction_depth=2, source_flags=transfer_flags)
        finally:
            engine._damage_unreduced, engine._damage_bonus_already_applied = previous
            engine._protection_community = False
    note(engine, aegis.source_definition_id, taker, f"Community: {taker.display_name} takes {taken} of the damage in place of {target.display_name}.",
         (target,), taken=taken)


# ------------------------------------------------------------------------------------------------ Sanctuary Without Borders
SANCTUARY = "sanctuary_without_borders"
RELIEF = ("restrained", "grappled", "frightened")


def _sanctuary_offer(engine: Any, creature: Any) -> None:
    """"When a willing creature enters the Ward for the first time on a turn or starts its turn inside, it may immediately end one of
    the following: Frightened; Grappled; Restrained ... A creature may benefit once per activation." (the Sanctuary's owner's allies)"""
    from . import states
    from ..typed_executor import CONDITION_PREFIX
    from .needle import CHOICE, ask, checkpoint_id

    if not creature.active:
        return
    for owner in list(engine.state.actors.values()):
        running = states.active(engine, owner, SANCTUARY) if owner.team_id == creature.team_id else None
        if running is None or not any(engine._footprint_intersects(creature, zone.affected_cells) for zone in own_wards(engine, owner)):
            continue
        from .protection_second_pass import POLICY
        if (running.data or {}).get(POLICY) == 1:
            continue
        used_key = f"protection_sanctuary_round_used:{running.instance_id}"
        if creature.entity_id in (owner.turn_flags.get(used_key) or []):
            continue
        present = [name for name in RELIEF if any(c.condition_id == CONDITION_PREFIX + name for c in creature.conditions.values())]
        if not present:
            continue
        chosen = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "protection_sanctuary", creature.entity_id), creature,
                     CHOICE + "protection_sanctuary", present, labels={name: f"End {name.title()}" for name in present}, preferred=present[:1],
                     allow_decline=True, name="Sanctuary Without Borders", prompt=f"Sanctuary Without Borders: {creature.display_name} may end one condition.")
        if not chosen:
            continue
        owner.turn_flags[used_key] = sorted({*(owner.turn_flags.get(used_key) or []), creature.entity_id})
        engine._remove_condition(creature, CONDITION_PREFIX + chosen[0], str(running.source_definition_id))
        note(engine, str(running.source_definition_id), creature, f"Sanctuary Without Borders: {creature.display_name} ends {chosen[0].title()}.")


def own_wards(engine: Any, owner: Any) -> list[Any]:
    return [zone for talent in WARD_TALENTS for zone in _wards(engine, talent) if zone.owner_id == owner.entity_id]


@hook("candidate_allowed")
def sanctuary_needs_a_ward(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"Choose one Ward you create": Sanctuary Without Borders is offered only while you maintain a Ward."""
    from .ability_source import mechanic_of

    if action is None or mechanic_of(action) != T + SANCTUARY:
        return None
    return None if own_wards(engine, actor) else False


@hook("turn_start")
def sanctuary_turn_start(engine: Any, actor: Any) -> None:
    if any(c.condition_id.endswith("." + SANCTUARY) for a in engine.state.actors.values() for c in a.conditions.values()):
        _sanctuary_offer(engine, actor)


@hook("event")
def sanctuary_entered(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    if not any(c.condition_id.endswith("." + SANCTUARY) for a in engine.state.actors.values() for c in a.conditions.values()):
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is not None:
        _sanctuary_offer(engine, mover)


# ------------------------------------------------------------------------------------------------ Heaven-Sheltering Aegis
@hook("would_drop")
def heaven_sheltering(engine: Any, target: Any, pending: int, source_actor_id: str) -> int | None:
    held = _with(target, HEAVEN)
    if not held:
        return None
    key, aegis = held[0]
    end_aegis(engine, target, key, "SPENT")  # "it drops to 1 HP instead and the Aegis ends"
    note(engine, aegis.source_definition_id, target, f"Heaven-Sheltering Aegis: {target.display_name} drops to 1 HP instead of 0; the Aegis ends.")
    return max(0, target.current_hp + target.temporary_hp - 1)


@hook("compile_block")
def protection_blocks(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Community's and Status's owner markers (combat/rules/feature_blocks.d/riders_c4.json)."""
    if block in ("protection_community", "protection_status"):
        return [{**row, "block": block, "keeps_compiling": True}]
    return None
