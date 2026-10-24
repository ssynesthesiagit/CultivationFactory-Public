"""Ancestral Bloodline Awakening (Tianxia Qi Cultivation Insight, CL3).

The recorded bloodline wakes and grants one of five gifts: Azure Dragon (Resistance
to a chosen lineage damage type; a once-per-turn Fly Speed), Vermilion Phoenix
(survive a drop to 0 Hit Points by spending 4 Qi and burst), Demon-Blood (a Qi-powered
feature deals +1d6 of a chosen type once per turn), Jade Tortoise (+1 Armor Class,
forced movement against the bearer is 5 feet shorter) or Nine-Tailed Fox (a Reaction
that imposes Disadvantage on a perceived attacker's roll within 30 feet).

General seams used (combat/ext/__init__.py catalog): the ``path_rider`` passive row
kind ``lineage_gift`` carries ownership and the compiled numbers; ``ac``,
``forced_movement_reduction``, ``damage_defenses``, ``final_damage``, ``technique_used``
and ``event`` hooks run the always-on and triggered clauses; a d20 rewrite ``Rule``
(combat/ext/d20_rewrite.py) runs the fox gift's reaction, with its Ask-me moment
named through the general checkpoint-label map in combat/tabletop_service.py.

The gift (and a gift's damage type) is a character-construction decision, so the
plug-in compiles one free, initial setting action per printed choice. Recorded
sheet presets take precedence; automatic owners without a preset receive the
first printed choice deterministically through setting_choices. The choice is
recorded as the ordinary ``condition:typed.lineage_gift`` condition (string data, so
it survives a table commit and a cold reload), and every gift hook returns early
unless the creature owns this Insight and has recorded the matching gift, so the
plug-in is inert for every other character.

An explicit Source Rule may extend Demon-Blood's three standard damage choices.
The owner's sheet supplies path_and_subpath.ancestral_lineage_source with
source_id, rules_text and damage_types, for example a published Fire lineage
records {"source_id": "lineage:ember", "rules_text": "Lineage damage: Fire.",
"damage_types": ["fire"]}. Each declared type must be a canonical damage name
printed in that source text. The compiler seals this source receipt into the
owned passive; both construction actions and execution use the same permissions.
With no source input only the three standard Demon-Blood choices are offered.
"""
from __future__ import annotations

import re
from typing import Any

from ..damage_allocation import lethal_threshold
from ..turn_uses import current_turn_key
from . import effect, hook, note
from .d20_rewrite import Holder, Rule, register
from .life_state import massive, wants_dying
from .needle import CHOICE, ask, checkpoint_id
from .passive_rows import row_of

INSIGHT = "insight.ancestral-bloodline-awakening"
GIFT = "condition:typed.lineage_gift"
# A permanent construction record is not an active use of Draconic Passage.
# Keep its provenance distinct so the shared AI self-buff restraint can tell
# the recorded lineage from a currently running activation of the Insight.
GIFT_SOURCE = "passive:" + INSIGHT
FLIGHT = "condition:typed.dragon_flight"
PHOENIX_USED = "condition:typed.phoenix_gift_used"
QI = "resource:core.qi"

FOX_RULE = "lineage_fox"
FOX_NAME = "Foxfire Misdirection"
FOX_CHECKPOINT = "D20_FOX_MISDIRECT"

# gift -> (printed label, the damage types the printed text lets that gift choose)
GIFTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "dragon": ("Azure Dragon", ("acid", "cold", "fire", "lightning", "poison", "radiant", "thunder")),
    "phoenix": ("Vermilion Phoenix", ("fire", "radiant")),
    "demon": ("Demon-Blood", ("necrotic", "psychic", "poison")),
    "tortoise": ("Jade Tortoise", ()),
    "fox": ("Nine-Tailed Fox", ()),
}

# Construction input: path_and_subpath.ancestral_lineage_source contains a
# source_id, rules_text and damage_types (a list of canonical damage names).
# This is an explicit Source Rule supplied with the owner's sheet, not a type
# inferred from another creature or a free-form combat choice. Require each
# declared type to occur in that source's text; preserve the receipt in the
# sealed passive so cold replay never consults a changed sheet or live source.
LINEAGE_DAMAGE_TYPES = frozenset((
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
))


def lineage_source(sheet: dict[str, Any]) -> dict[str, Any]:
    """Validate the optional, source-backed Demon-Blood construction input."""
    source = (sheet.get("path_and_subpath") or {}).get("ancestral_lineage_source")
    if source is None:
        return {}
    if not isinstance(source, dict):
        raise ValueError("The ancestral lineage source needs a source ID, rule text and damage types.")
    source_id, text, types = source.get("source_id"), source.get("rules_text"), source.get("damage_types")
    if (not isinstance(source_id, str) or not source_id.strip()
            or not isinstance(text, str) or not text.strip() or not isinstance(types, list)):
        raise ValueError("The ancestral lineage source needs a source ID, rule text and damage types.")
    allowed = []
    for value in types:
        kind = value.strip().lower() if isinstance(value, str) else ""
        if kind not in LINEAGE_DAMAGE_TYPES or not re.search(r"\b" + re.escape(kind) + r"\b", text, re.I):
            raise ValueError("Each ancestral lineage damage type must be printed in its recorded source rule.")
        if kind not in allowed:
            allowed.append(kind)
    return {"source_id": source_id.strip(), "rules_text": text, "damage_types": allowed}


def gift_damage_types(gift: str, source: dict[str, Any]) -> tuple[str, ...]:
    """Printed standard choices plus only this owner's sealed lineage types."""
    standard = GIFTS[gift][1]
    extra = source.get("damage_types", ()) if gift == "demon" else ()
    return tuple(dict.fromkeys((*standard, *extra))) or ("",)

BENEFITS = {
    "dragon": "Gain Resistance to {damage}. Bonus Action, 2 Qi: Fly Speed 30 feet until your turn ends.",
    "phoenix": "Once per scene, spend 4 Qi when reduced to 0 Hit Points without being killed outright to remain at 1; hostile creatures within 5 feet take 2d8 {damage} damage (Dexterity save for half).",
    "demon": "Once per turn, one damaging Qi-powered feature deals an extra 1d6 {damage} damage.",
    "tortoise": "Gain +1 AC and reduce forced movement applied to you by 5 feet (minimum 0).",
    "fox": "Reaction, 1 Qi: impose Disadvantage on an attack roll by a creature you perceive within 30 feet.",
}


# --------------------------------------------------------------------- ownership and the recorded gift
def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, "path_rider", "lineage_gift") is not None


def gift_of(actor: Any) -> str:
    """The recorded gift, or "" when none is recorded yet."""
    for condition in actor.conditions.values():
        if condition.condition_id == GIFT:
            return str((condition.data or {}).get("gift") or "")
    return ""


def chosen_damage(actor: Any) -> str:
    """The gift's recorded damage type, uppercased, or ""."""
    for condition in actor.conditions.values():
        if condition.condition_id == GIFT:
            return str((condition.data or {}).get("damage_type") or "").upper()
    return ""


def save_dc(engine: Any, actor: Any) -> int:
    row = row_of(engine, actor.entity_id, "path_rider", "lineage_gift")
    return int((row or {}).get("save_dc") or 10)


# --------------------------------------------------------------------- compiled actions: the gift choice, the dragon's passage
@hook("compile_actions", priority=10)
def gift_choices(info: dict[str, Any]) -> list[Any] | None:
    if INSIGHT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    try:
        source = lineage_source(info["owner_sheet"])
    except ValueError:
        # Invalid optional construction data grants no extra type. It must not
        # make this hook fail and thereby remove the standard gift actions.
        source = {}
    # path_riders.compile_passives (priority 0) owns this row. Annotate it
    # after construction rather than registering a second ownership record.
    for passive in info["passives"]:
        if passive.get("block") == "path_rider" and passive.get("kind") == "lineage_gift":
            passive["lineage_source"] = source
    made: list[Any] = []
    for gift, (label, _) in GIFTS.items():
        for damage_type in gift_damage_types(gift, source):
            suffix = f".{gift}.{damage_type}" if damage_type else f".{gift}"
            title = f"Ancestral Bloodline: {label}"
            if damage_type:
                title += f" -- {damage_type.title()}"
            made.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.lineage_gift{suffix}",
                display_name=title, owner_id=info["actor_id"], economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "player_only": True,
                            **({"ai_setting_default": {
                                "condition_id": GIFT, "source_definition_id": GIFT_SOURCE,
                                "data": {"gift": gift, "damage_type": damage_type,
                                         "label": f"{label} ({damage_type.title()})"}}}
                               if not made else {}),
                            "typed": {"source": INSIGHT, "numbers": dict(info["numbers"]),
                                      "duration": {"kind": "instant"}, "riders": [],
                                      "effects": [{"type": "lineage_gift_pick", "gift": gift,
                                                   "damage_type": damage_type}]},
                            "expected_damage": 0,
                            "description": ("Choose once to match your recorded lineage; this gift and damage type cannot be changed in combat. "
                                            + BENEFITS[gift].format(damage=damage_type.title()))}))
    made.append(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.dragon_flight",
        display_name="Draconic Passage: Fly 30 feet", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        costs=((QI, 2),),
        parameters={"typed": {"source": INSIGHT, "numbers": dict(info["numbers"]),
                              "duration": {"kind": "instant"}, "riders": [],
                              "effects": [{"type": "dragon_flight"}]},
                    "expected_damage": 0,
                    "description": "Bonus Action, 2 Qi: gain a Fly Speed of 30 feet until the end of your turn."}))
    return made


@hook("candidate_allowed")
def dragon_passage_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The dragon's passage only exists while the Azure Dragon gift is recorded."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if any(effect.get("type") == "lineage_gift_pick" for effect in typed.get("effects") or []):
        return owned(engine, actor) and not gift_of(actor)
    if any(effect.get("type") == "dragon_flight" for effect in typed.get("effects") or []):
        return gift_of(actor) == "dragon"
    return None


@hook("settings_batch_key")
def gift_preset(action: Any) -> tuple[str, ...] | None:
    """Let the existing roster sheet-preset seam install the construction choice."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") == INSIGHT and any(
            row.get("type") == "lineage_gift_pick" for row in typed.get("effects") or []):
        return ("ancestral_lineage_gift",)
    return None


# --------------------------------------------------------------------- effects: record the choice, grant the passage
@effect("lineage_gift_pick")
def record_gift(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    gift = str(row.get("gift") or "")
    damage_type = str(row.get("damage_type") or "")
    passive = row_of(engine, actor.entity_id, "path_rider", "lineage_gift")
    source = (passive or {}).get("lineage_source") or {}
    if passive is None or gift not in GIFTS or damage_type not in gift_damage_types(gift, source):
        raise ValueError("Choose a printed ancestral gift this character owns.")
    if gift_of(actor):
        if gift_of(actor) == gift and chosen_damage(actor) == damage_type.upper():
            return  # Applying the same recorded sheet preset is idempotent.
        raise ValueError("The ancestral gift and damage type are fixed when gained.")
    label = GIFTS.get(gift, (gift,))[0]
    if damage_type:
        label += f" ({damage_type.title()})"
    engine._apply_condition(actor, GIFT, GIFT_SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"gift": gift, "damage_type": damage_type, "label": label})
    note(engine, INSIGHT, actor,
         f"{actor.display_name} records the {label} ancestral gift.", (actor,))


@effect("dragon_flight")
def dragon_passage(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    engine._apply_condition(actor, FLIGHT, INSIGHT, actor.entity_id,
                            expires_on="END_OF_CURRENT_TURN",
                            data={"fly_speed_ft": 30,
                                  "label": "Draconic Passage (Fly Speed 30 feet until the end of your turn)"})
    note(engine, INSIGHT, actor,
         f"{actor.display_name} takes to the air on draconic wings (Fly Speed 30 feet until the end of the turn).",
         (actor,))


# --------------------------------------------------------------------- always-on gifts: tortoise, dragon resistance
@hook("ac")
def tortoise_armor(engine: Any, actor: Any) -> int:
    """Jade Tortoise: +1 Armor Class while the gift is recorded."""
    return 1 if owned(engine, actor) and gift_of(actor) == "tortoise" else 0


@hook("forced_movement_reduction")
def tortoise_shell(ctx: Any, subject: Any) -> int:
    """Jade Tortoise: forced movement applied to the bearer is 5 feet shorter."""
    return 5 if owned(ctx.engine, subject) and gift_of(subject) == "tortoise" else 0


@hook("damage_defenses")
def dragon_resistance(engine: Any, target: Any, damage_type: Any, typed: Any, source_actor_id: Any) -> list | None:
    """Azure Dragon: Resistance to the chosen lineage damage type."""
    if not owned(engine, target) or gift_of(target) != "dragon":
        return None
    chosen = chosen_damage(target)
    if not chosen or str(damage_type or "").upper() != chosen:
        return None
    return [{"kind": "resistance", "damage_types": [chosen]}]


# --------------------------------------------------------------------- the phoenix: survive the drop, then burst
@hook("final_damage")
def phoenix_continuity(engine: Any, actor: Any, amount: int, damage_type: Any,
                       source_id: Any, source_actor_id: Any, intent: Any) -> dict | None:
    """Vermilion Phoenix: spend 4 Qi to remain at 1 Hit Point when a hit would reduce
    the bearer to 0 without killing it outright; hostile creatures within 5 feet burst."""
    if not owned(engine, actor) or gift_of(actor) != "phoenix":
        return None
    if actor.current_hp <= 0 or amount <= 0:
        return None
    hp_damage = lethal_threshold(engine, actor, amount, source_actor_id,
                                 source_id=source_id, damage_type=damage_type)
    if hp_damage < actor.current_hp:
        return None
    # "without being killed outright": the excess beyond 0 Hit Points is less than
    # the engine's massive-damage threshold (life_state._on_damage dooms a hit whose
    # damage in excess of the current Hit Points reaches the creature's maximum).
    if wants_dying(engine, actor) and hp_damage - actor.current_hp >= massive(engine, actor):
        return None
    if any(condition.condition_id == PHOENIX_USED for condition in actor.conditions.values()):
        return None
    if int(actor.resources.get(QI, 0) or 0) < 4:
        return None
    from . import needle

    triggering_action = engine.action_catalog.get(str(source_id or ""))
    trigger = triggering_action.display_name if triggering_action is not None else "this damage"
    picked = needle.ask(engine, intent, checkpoint_id(engine, "phoenix_continuity", actor.entity_id),
                        actor, CHOICE + "phoenix_continuity", ["remain"],
                        labels={"remain": "Spend 4 Qi to remain at 1 Hit Point"},
                        prompt=(f"Ember Continuity: {actor.display_name} would be reduced to 0 Hit Points by {trigger}. "
                                "Spend 4 Qi to remain at 1 Hit Point and burst in Fire or Radiant damage "
                                "against hostile creatures within 5 feet?"),
                        preferred=["remain"], allow_decline=True, automatic=True,
                        target_id=actor.entity_id, name="Ember Continuity", feature_id=INSIGHT)
    if not picked:
        return None
    engine._spend_resource(actor, QI, 4, INSIGHT)
    engine._apply_condition(actor, PHOENIX_USED, INSIGHT, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Ember Continuity used this scene"})
    # The burst rides the damage packet this rescue floors; the event hook below
    # releases it once that packet commits, so the burst never lands before the
    # creature it belongs to is safely at 1 Hit Point.
    actor.turn_flags["_lineage_phoenix_burst"] = 1
    note(engine, INSIGHT, actor,
         f"{actor.display_name} spends 4 Qi to remain at 1 Hit Point (Ember Continuity).", (actor,))
    return {"hp_floor": 1}


@hook("event", nested=True)
def phoenix_burst(engine: Any, event_type: str, kwargs: Any) -> None:
    """Release the Ember Continuity burst once the rescued packet commits."""
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not actor.active or not actor.turn_flags.pop("_lineage_phoenix_burst", None):
            continue
        _burst(engine, actor)


def _burst(engine: Any, actor: Any) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    chosen = chosen_damage(actor) or "FIRE"
    foes = sorted((candidate for candidate in engine.state.actors.values()
                   if candidate.active and candidate.entity_id != actor.entity_id
                   and candidate.team_id != actor.team_id
                   and engine._distance_actor_to_actor(actor, candidate) <= 5),
                  key=lambda candidate: candidate.entity_id)
    if not foes:
        return
    action = ActionDefinition(source_definition_id=INSIGHT, display_name="Ember Continuity",
                              owner_id=actor.entity_id, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    burst = te.Context(engine, actor, action, engine._active_intent,
                       {"source": INSIGHT,
                        "numbers": {"cl": 15, "pb": 2, "save_dc": save_dc(engine, actor), "key_mod": 0},
                        "duration": {"kind": "instant"}, "riders": [],
                        "_area_centre": (actor.position.x, actor.position.y)}, foes, None, {})
    te.run_effects(burst, [{"type": "save", "ability": "dex",
                            "evidence": "Ember Continuity: Dexterity saving throw",
                            "on_fail": [{"type": "damage", "applies_to": "target",
                                         "dice": {"count": 2, "sides": 8}, "damage_types": [chosen.lower()]}],
                            "on_success": [{"type": "half_damage", "applies_to": "target",
                                            "damage_types": [chosen.lower()]}]}])
    note(engine, INSIGHT, actor,
         f"{actor.display_name} bursts in {chosen.title()} damage (Ember Continuity).", tuple(foes))


# --------------------------------------------------------------------- the demon's rider: a Qi-powered feature deals +1d6
@hook("technique_used")
def demon_rider(ctx: Any) -> None:
    """Demon-Blood: once per turn, one damaging Qi-powered feature deals an extra
    1d6 damage of the chosen type to one creature it damaged."""
    engine, actor = ctx.engine, ctx.actor
    if not owned(engine, actor) or gift_of(actor) != "demon":
        return
    chosen = chosen_damage(actor)
    if not chosen or not _qi_powered(ctx):
        return
    stamp = current_turn_key(engine)
    if actor.turn_flags.get("_lineage_demon_rider") == stamp:
        return
    first = ctx.technique_event_start
    if first is None:
        return
    damaged: dict[str, Any] = {}
    for event in engine.events[first:]:
        if (event.event_type != "DAMAGE_COMMITTED" or event.actor_id != actor.entity_id
                or event.source_definition_id != ctx.action.source_definition_id):
            continue
        if int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) <= 0:
            continue
        for target_id in event.target_ids or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.active and target_id != actor.entity_id:
                damaged[target_id] = target
    if not damaged:
        return
    # A rider harms, so an automatic choice picks an enemy first; a hand-controlled
    # owner names the creature when several were damaged.
    ranked = sorted(damaged.values(),
                    key=lambda target: (target.team_id == actor.team_id, target.entity_id))
    target = ranked[0]
    if len(ranked) > 1:
        target_id = ask(engine, ctx.intent, checkpoint_id(engine, "demon_rider", actor.entity_id),
                        actor, CHOICE + "demon_rider", [creature.entity_id for creature in ranked],
                        labels={creature.entity_id: creature.display_name for creature in ranked},
                        prompt=(f"Malicious Rider: {actor.display_name}'s Qi-powered feature deals "
                                f"1d6 {chosen.title()} damage to one creature it damaged. Choose the creature."),
                        preferred=[target.entity_id], target_id=target.entity_id,
                        name="Malicious Rider", feature_id=INSIGHT)
        if not target_id:
            return
        target = engine.state.actors.get(target_id[0]) or target
    actor.turn_flags["_lineage_demon_rider"] = stamp
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id,
                              reason=f"DAMAGE:{INSIGHT}:demon_rider")
    engine._record_roll(roll)
    engine._commit_damage(target, int(roll.total), chosen, INSIGHT, actor.entity_id, None, reaction_depth=0)
    note(engine, INSIGHT, actor,
         f"{actor.display_name}'s malicious rider deals {int(roll.total)} {chosen.title()} damage to "
         f"{target.display_name}.", (target,))


def _qi_powered(ctx: Any) -> bool:
    """The activation is Qi-powered: it says so, it spends Qi, or its printed source is a Qi path."""
    typed = ctx.typed or {}
    if typed.get("qi_powered"):
        return True
    for pool, _amount in (ctx.action.costs or ()):
        if str(pool).startswith("resource:") and str(pool).endswith(".qi"):
            return True
    return str(typed.get("source") or "").startswith(("tianxia.subpath.qi.", "tianxia.path.qi_cultivation."))


# --------------------------------------------------------------------- the fox's reaction: impose Disadvantage on a perceived attacker
def _fox_holders(engine: Any) -> list[Holder]:
    holders = []
    for actor in sorted(engine.state.actors.values(), key=lambda candidate: candidate.entity_id):
        if actor.active and owned(engine, actor) and gift_of(actor) == "fox":
            row = row_of(engine, actor.entity_id, "path_rider", "lineage_gift") or {}
            holders.append(Holder(actor, INSIGHT, {"gift": "fox"}, INSIGHT, row))
    return holders


def _fox_guard(engine: Any, holder: Holder, rc: Any) -> bool:
    return gift_of(holder.actor) == "fox"


register(Rule(
    FOX_RULE, FOX_NAME,
    rolls=("attack",), who="any", range_ft=30, see=True, when="any",
    op="disadvantage", reaction=True,
    costs=((("qi", 1),),), checkpoint=FOX_CHECKPOINT,
    feature=INSIGHT, guard=_fox_guard,
    ai=lambda engine, holder, rc: rc.roller.team_id != holder.actor.team_id,
))
