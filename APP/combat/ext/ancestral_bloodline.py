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

The distinct Bloodline Cultivator Subpath uses the same module's completed-use
hook for Bloodline Strike, not the Insight's Demon-Blood rider. Its reviewed
path_passive row seals ownership and CL. A fixed bloodline_affinity construction
setting (or sheet preset) supplies the damage type. The construction field
path_and_subpath.bloodline_lineage records the Subpath lineage independently
of the Insight; without a preset the affinity action asks for it. The scene
pool starts empty at maximum PB. Lineage-specific recovery observes committed
combat outcomes through the existing event, save, attack and movement seams.
Lineage Resistance answers the shared ``damage_defenses`` hook; for a Force or
Psychic affinity the printed flat reduction uses ``final_damage`` instead.
The ordinary optional-choice
transport selects one actually damaged recipient and charges Ancestral Resonance;
the shared typed_once_turn namespace supplies the all-creature turn reset.
"""
from __future__ import annotations

import re
from typing import Any

from ..damage_allocation import lethal_threshold
from ..turn_uses import current_turn_key
from . import CheckpointError, effect, hook, note
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


# --------------------------------------------------------------------- Bloodline Cultivator (a separate Subpath record)
BLOODLINE = "tianxia.subpath.qi.bloodline_cultivator.feature.ancestral_bloodline_awakening"
AFFINITY = "condition:typed.bloodline_strike_affinity"
RESONANCE = "resource:named.ancestral_resonance"
STRIKE_CHOICE = CHOICE + "bloodline_strike"
# Subpath permissions are independent of the separate Insight's gift table.
LINEAGE_AFFINITIES = {
    "azure_dragon": ("acid", "cold", "fire", "lightning", "poison"),
    "vermilion_phoenix": ("fire", "radiant"),
    "jade_tortoise": ("earth", "force", "water"),
    "nine_tailed_fox": ("fire", "psychic", "radiant"),
    "kunpeng": ("cold", "lightning", "thunder", "force"),
    "qilin": ("lightning", "radiant", "fire"),
    "heavenly_serpent": ("acid", "cold", "poison", "psychic", "force"),
    "demon_ancestry": ("fire", "force", "necrotic", "psychic", "thunder"),
}
AFFINITY_TYPES = tuple(sorted({kind for kinds in LINEAGE_AFFINITIES.values() for kind in kinds}))
# Printed Lineage Resistance: Force and Psychic take a flat first-packet reduction,
# never Resistance.
REDUCED_AFFINITIES = ("force", "psychic")
# A key the engine's turn-start filter keeps ("once_per_round:"), because the printed
# limit is once each round, not once each turn.
RESIST_ROUND = "once_per_round:bloodline_lineage_resistance"


def affinity_damage_type(kind: str) -> str:
    """Earth/Water principles use physical Bludgeoning, as in Qi's Element Cycle."""
    return "bludgeoning" if kind in ("earth", "water") else kind


def bloodline_of(actor: Any) -> str:
    """Read the Subpath ancestry, never the independently selected Insight gift."""
    for condition in actor.conditions.values():
        if condition.condition_id == AFFINITY:
            return str(condition.data.get("lineage") or "")
    return ""


def compatible(lineage: str, kind: str) -> bool:
    return kind in LINEAGE_AFFINITIES.get(lineage, ())

LINEAGES = {
    "azure_dragon": "Azure Dragon", "vermilion_phoenix": "Vermilion Phoenix",
    "jade_tortoise": "Jade Tortoise", "nine_tailed_fox": "Nine-Tailed Fox",
    "kunpeng": "Kunpeng", "qilin": "Qilin", "heavenly_serpent": "Heavenly Serpent",
    "demon_ancestry": "Demon-Ancestry",
}


@hook("compile_resources")
def resonance_pool(info: dict[str, Any]) -> list[Any] | None:
    """The compendium's scene pool starts empty and has a maximum of PB."""
    if BLOODLINE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=RESONANCE, initial=0,
                               maximum=int(info["numbers"]["pb"]))]


def gain_resonance(engine: Any, actor: Any) -> None:
    """A meaningful lineage trigger grants one point, at most once per turn."""
    if (row_of(engine, actor.entity_id, "path_rider", "bloodline_strike") is None
            or RESONANCE not in actor.resources or not actor.active):
        return
    stamp = current_turn_key(engine)
    if actor.turn_flags.get("_bloodline_resonance_turn") == stamp:
        return
    actor.turn_flags["_bloodline_resonance_turn"] = stamp
    engine._gain_resource(actor, RESONANCE, 1, BLOODLINE)


@hook("event", nested=True)
def resonance_damage(engine: Any, event_type: str, kwargs: Any) -> None:
    """Observe real outcomes, not costs, quotes or harmless recovery loops."""
    if event_type not in ("DAMAGE_COMMITTED", "HEALING_APPLIED", "REACTION_RESOLVED",
                          "MOVEMENT_COMMITTED", "CONDITION_APPLIED", "CONDITION_REMOVED", "PASSIVE_TRIGGERED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    targets = [engine.state.actors[tid] for tid in kwargs.get("target_ids") or ()
               if tid in engine.state.actors]
    payload = kwargs.get("payload") or {}
    lineage = bloodline_of(actor) if actor else ""
    if event_type == "DAMAGE_COMMITTED":
        damage = int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0)
        for target in targets:
            hostile = actor is not None and actor.team_id != target.team_id
            if hostile and damage > 0:
                if lineage in ("azure_dragon", "vermilion_phoenix") and (
                        str(payload.get("damage_type") or "").lower() == strike_affinity(actor)):
                    gain_resonance(engine, actor)
                if lineage == "demon_ancestry":
                    for event in reversed(engine.events):
                        if event.event_type == "TURN_ENDED" and event.actor_id == actor.entity_id:
                            break
                        if (event.event_type == "DAMAGE_COMMITTED" and event.actor_id == target.entity_id
                                and actor.entity_id in event.target_ids
                                and int(event.payload.get("hp_damage") or 0)
                                + int(event.payload.get("temporary_hp_absorbed") or 0) > 0):
                            gain_resonance(engine, actor)
                            break
                if (bloodline_of(target) == "vermilion_phoenix" and target.current_hp > 0
                        and int(payload.get("hp_before") or 0) * 2 < target.maximum_hp):
                    gain_resonance(engine, target)
            if (hostile and bloodline_of(target) == "jade_tortoise"
                    and int(payload.get("rolled_or_pending_damage") or 0) > int(payload.get("reduced_to") or 0)):
                gain_resonance(engine, target)
            if hostile and int(payload.get("rolled_or_pending_damage") or 0) > int(payload.get("reduced_to") or 0):
                kind = str(payload.get("damage_type") or "").upper()
                for modifier in target.modifiers.values():
                    if modifier.target_field not in ("damage_resistance", "damage_immunity") or modifier.value != kind:
                        continue
                    action = engine.action_catalog.get(modifier.source_definition_id)
                    provider = engine.state.actors.get(action.owner_id) if action else None
                    if provider is not None and bloodline_of(provider) == "qilin" and provider.team_id == target.team_id:
                        gain_resonance(engine, provider)
    elif event_type == "HEALING_APPLIED":
        if (lineage == "vermilion_phoenix" and int(payload.get("after") or 0) > int(payload.get("before") or 0)
                and any(int(payload.get("before") or 0) * 2 < target.maximum_hp for target in targets)):
            gain_resonance(engine, actor)
    elif event_type == "REACTION_RESOLVED":
        before, after = payload.get("pending_before"), payload.get("pending_after")
        if (lineage in ("jade_tortoise", "qilin") and payload.get("checkpoint") == "DAMAGE_APPLICATION"
                and type(before) is int and type(after) is int and 0 <= after < before):
            gain_resonance(engine, actor)
    elif event_type == "MOVEMENT_COMMITTED" and lineage == "kunpeng":
        if not payload.get("forced") and not payload.get("teleport"):
            if (payload.get("movement_mode") in ("fly", "swim")
                    and len(payload.get("path") or ()) > 1):
                gain_resonance(engine, actor)
            elif engine.state.current_actor_id == actor.entity_id:
                feet = 0
                for event in reversed(engine.events):
                    if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
                        break
                    if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id:
                        p = event.payload or {}
                        if not p.get("forced") and not p.get("teleport"):
                            feet += max(0, len(p.get("path") or ()) - 1) * engine.grid.square_size_ft
                if feet >= 20:
                    gain_resonance(engine, actor)
    elif event_type == "CONDITION_APPLIED" and lineage == "heavenly_serpent":
        condition_id = str(payload.get("condition_id") or "")
        name = condition_id.split(".")[-1]
        if (name in ("grappled", "restrained", "poisoned") or ".mark." in condition_id) and any(
                target.team_id != actor.team_id for target in targets):
            gain_resonance(engine, actor)

    elif event_type == "PASSIVE_TRIGGERED" and payload.get("miss_chance_percent") and payload.get("missed"):
        for target in targets:
            if actor is not None and actor.team_id != target.team_id and bloodline_of(target) == "nine_tailed_fox":
                gain_resonance(engine, target)
    elif event_type == "CONDITION_REMOVED":
        action = engine.action_catalog.get(kwargs.get("source_definition_id"))
        provider = engine.state.actors.get(action.owner_id) if action else None
        from ..condition_tone import tone
        if (provider is not None and bloodline_of(provider) == "qilin"
                and not str(kwargs.get("source_definition_id") or "").startswith("system:")
                and tone(str(payload.get("condition_id") or "")) == "harmful"):
            gain_resonance(engine, provider)


@hook("forced_movement_reduced")
def resonance_resist_movement(ctx: Any, subject: Any, before_ft: int, after_ft: int) -> None:
    if (bloodline_of(subject) == "jade_tortoise" and before_ft > after_ft
            and ctx.actor.team_id != subject.team_id):
        gain_resonance(ctx.engine, subject)


@hook("forced_movement_committed")
def resonance_move_foe(engine: Any, actor: Any, target: Any, distance_ft: int, movement_kind: str) -> None:
    if bloodline_of(actor) == "kunpeng" and actor.team_id != target.team_id and distance_ft >= 10:
        gain_resonance(engine, actor)


@hook("save_final")
def resonance_save(ctx: Any, subject: Any, ability: Any, named: Any, failed: bool) -> None:
    if ctx.actor.team_id == subject.team_id:
        return
    tags = {str(tag).lower().removeprefix("category:").removeprefix("damage:") for tag in named or ()}
    if not failed:
        lineage = bloodline_of(subject)
        if lineage == "azure_dragon":
            from .eye_awareness import source_sphere
            tags.add(source_sphere(ctx.engine, ctx.action.source_definition_id).rsplit(".", 1)[-1])
        if ((lineage == "azure_dragon" and tags.intersection(
                {"acid", "cold", "fire", "lightning", "poison", "thunder", "elemental",
                 "earth", "water", "air", "metal", "wood"}))
                or (lineage == "demon_ancestry" and tags.intersection({"charmed", "frightened", "charm", "fear"}))
                or (lineage == "jade_tortoise" and ("forced_movement" in tags or (
                    "prone" in tags and not any(c.condition_id.endswith(".prone")
                                               for c in subject.conditions.values()))))):
            gain_resonance(ctx.engine, subject)
    elif bloodline_of(ctx.actor) == "nine_tailed_fox":
        from .eye_awareness import source_sphere
        tags.add(source_sphere(ctx.engine, ctx.action.source_definition_id).rsplit(".", 1)[-1])
        if tags.intersection({"illusion", "emotion", "charm", "charmed", "concealment", "misdirection"}):
            gain_resonance(ctx.engine, ctx.actor)


@hook("attack_completed")
def resonance_missed(engine: Any, notice: Any, intent: Any) -> None:
    target = engine.state.actors.get(notice.target_id)
    attacker = engine.state.actors.get(notice.attacker_id)
    if (target is None or attacker is None or bloodline_of(target) != "nine_tailed_fox"
            or target.team_id == attacker.team_id or notice.hit):
        return
    # Only final misses with an imposed effective Disadvantage qualify.
    roll = next((event for event in reversed(engine.events) if event.event_type == "ATTACK_ROLLED"
                 and event.actor_id == notice.attacker_id and notice.target_id in event.target_ids), None)
    if roll and str(roll.payload.get("mode") or "") == "DISADVANTAGE":
        payload = roll.payload
        discarded = payload.get("discarded") or ()
        natural = payload.get("natural_result")
        # If both dice miss, Disadvantage did not cause this miss.
        if discarded and natural is not None:
            alternative = int(payload.get("modified_total", payload.get("total", 0))) + max(discarded) - natural
            if max(discarded) == 20 or (max(discarded) != 1 and alternative >= int(payload.get("target_ac") or 0)):
                gain_resonance(engine, target)


@hook("opposed_check_resolved")
def resonance_tracking(ctx: Any, target: Any, result: Any, actor_check: Any, target_check: Any) -> None:
    """Only an explicit tracking check against this hostile creature qualifies."""
    if (bloodline_of(ctx.actor) == "heavenly_serpent" and ctx.actor.team_id != target.team_id
            and result.success and "tracking" in actor_check.get("hazards", ())):
        gain_resonance(ctx.engine, ctx.actor)


@hook("technique_accepted")
def resonance_technique(engine: Any, actor: Any, action: Any) -> None:
    """Demon: use HP at activation, not after a technique heals or harms its owner.

    The ordinary accepted-activation seam runs after payment, skips construction
    settings, and rolls back with the action on a pause or failure.
    """
    if bloodline_of(actor) != "demon_ancestry" or actor.current_hp * 2 > actor.maximum_hp:
        return
    typed = action.parameters.get("typed") or {}
    source = str(typed.get("source") or "")
    technique = typed.get("qi_powered") or source.startswith(
        ("tianxia.talent.", "tianxia.subpath.", "tianxia.path.", "insight.")) or any(
            str(pool).endswith(".qi") for pool, _amount in action.costs or ())
    if technique:
        gain_resonance(engine, actor)


def recorded_affinity(actor: Any) -> str:
    """The Bloodline affinity setting recorded once at construction. Never infer it from the triggering talent."""
    for condition in actor.conditions.values():
        if condition.condition_id == AFFINITY:
            return str((condition.data or {}).get("damage_type") or "").lower()
    return ""


def strike_affinity(actor: Any) -> str:
    """Prefer the Subpath's fixed affinity over the separate Insight's gift type.

    Insight-specific features still read their own type through chosen_damage().
    """
    recorded = recorded_affinity(actor)
    if recorded in AFFINITY_TYPES:
        return affinity_damage_type(recorded)
    gift_kind = chosen_damage(actor).lower()
    return gift_kind if gift_kind in AFFINITY_TYPES else ""


@hook("compile_actions", priority=10)
def strike_settings(info: dict[str, Any]) -> list[Any] | None:
    """Seal the lineage's construction choice, reusing the standard setting/preset seams."""
    if BLOODLINE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    construction = info["owner_sheet"].get("path_and_subpath") or {}
    preset = str(construction.get("bloodline_affinity") or "").lower()
    lineage = str(construction.get("bloodline_lineage") or "").lower()
    made = []
    if preset and lineage in LINEAGES and not compatible(lineage, preset):
        raise CheckpointError("The chosen Bloodline affinity is not permitted by this lineage.")
    for kind in (LINEAGE_AFFINITIES[lineage] if lineage in LINEAGES else AFFINITY_TYPES):
        data = {"damage_type": kind, "lineage": lineage, "label": f"Bloodline affinity: {kind.title()}"}
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.bloodline_affinity.{kind}",
            display_name=f"Bloodline affinity: {kind.title()}", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "player_only": True,
                        **({"ai_setting_default": {"condition_id": AFFINITY,
                             "source_definition_id": "passive:" + BLOODLINE, "data": data}}
                           if kind == preset and compatible(lineage, kind) else {}),
                        "typed": {"source": BLOODLINE, "numbers": dict(info["numbers"]),
                                  "duration": {"kind": "instant"}, "riders": [],
                                  "effects": [{"type": "bloodline_affinity", "damage_type": kind, "lineage": lineage}]},
                        "description": "Record your established lineage's affinity once; this is not a combat choice. "
                                       "Earth and Water affinity damage is Bludgeoning damage. "
                                       "Once per turn after a Qi-powered feature or weapon-delivered cultivation technique "
                                       "damages a creature, you may spend 1 Ancestral Resonance to add 1d8 affinity damage "
                                       "to one creature it damaged (2d8 at CL11, 3d8 at CL17)."}))
    # A provided sheet affinity is a construction fact, for manual and AI seats alike.
    for passive in info["passives"]:
        if passive.get("kind") == "bloodline_strike" and compatible(lineage, preset):
            passive["affinity"] = preset
            passive["lineage"] = lineage
    return made


@hook("match_start", priority=45)
def strike_sheet_affinity(engine: Any) -> None:
    for actor in engine.state.actors.values():
        row = row_of(engine, actor.entity_id, "path_rider", "bloodline_strike") or {}
        kind = row.get("affinity")
        if compatible(row.get("lineage"), kind) and not recorded_affinity(actor):
            engine._apply_condition(actor, AFFINITY, "passive:" + BLOODLINE, actor.entity_id,
                                    expires_on="UNTIL_REMOVED",
                                    data={"damage_type": kind, "lineage": row.get("lineage", ""),
                                          "label": f"Bloodline affinity: {kind.title()}"})


@hook("settings_batch_key")
def strike_preset(action: Any) -> tuple[str, ...] | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") == BLOODLINE and any(
            row.get("type") == "bloodline_affinity" for row in typed.get("effects") or []):
        return ("bloodline_strike_affinity",)
    return None


@hook("candidate_allowed")
def strike_affinity_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if any(row.get("type") == "bloodline_affinity" for row in typed.get("effects") or []):
        return row_of(engine, actor.entity_id, "path_rider", "bloodline_strike") is not None and not recorded_affinity(actor)
    return None


@effect("bloodline_affinity")
def record_strike_affinity(ctx: Any, row: dict[str, Any]) -> None:
    kind = row.get("damage_type")
    if row_of(ctx.engine, ctx.actor.entity_id, "path_rider", "bloodline_strike") is None or kind not in AFFINITY_TYPES:
        raise ValueError("Record the affinity of a lineage this character owns.")
    existing = recorded_affinity(ctx.actor)
    if existing:
        if existing == kind:
            return
        raise ValueError("Your lineage affinity cannot be changed in combat.")
    lineage = row.get("lineage")
    if lineage not in LINEAGES:
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bloodline_lineage", ctx.actor.entity_id),
                       ctx.actor, CHOICE + "bloodline_lineage", [key for key in LINEAGES if compatible(key, kind)], labels=LINEAGES,
                       preferred=[next(key for key in LINEAGES if compatible(key, kind))], name="Bloodline lineage", feature_id=BLOODLINE,
                       prompt=f"Bloodline lineage: record {ctx.actor.display_name}'s established ancestry. "
                              "This determines which events earn Ancestral Resonance; it costs nothing.")
        if not selected:
            return
        lineage = selected[0]
    if not compatible(lineage, kind):
        raise ValueError("The chosen Bloodline affinity is not permitted by this lineage.")
    ctx.engine._apply_condition(ctx.actor, AFFINITY, "passive:" + BLOODLINE, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"damage_type": kind, "lineage": lineage,
                                      "label": f"Bloodline affinity: {kind.title()}"})


# --------------------------------------------------------------------- Lineage Resistance
def _striking_char(engine: Any, actor: Any) -> bool:
    """Ownership of this Subpath record is the reviewed path_passive row."""
    return row_of(engine, actor.entity_id, "path_rider", "bloodline_strike") is not None


@hook("damage_defenses")
def lineage_resistance(engine: Any, target: Any, damage_type: Any, typed: Any,
                       source_actor_id: Any) -> list | None:
    """Lineage Resistance: Resistance to the lineage's chosen affinity damage type.

    A Force or Psychic affinity takes the printed flat reduction instead, so it
    never answers here.
    """
    if not _striking_char(engine, target):
        return None
    kind = recorded_affinity(target)
    if kind not in AFFINITY_TYPES or kind in REDUCED_AFFINITIES:
        return None
    resisted = affinity_damage_type(kind)
    if str(damage_type or "").lower() != resisted:
        return None
    return [{"kind": "resistance", "damage_types": [resisted.upper()]}]


@hook("final_damage")
def lineage_reduction(engine: Any, target: Any, amount: int, damage_type: Any,
                      source_id: Any, source_actor_id: Any, intent: Any) -> dict | None:
    """Lineage Resistance for a Force or Psychic affinity: reduce the first packet
    of that type each round by the bearer's Proficiency Bonus."""
    if not _striking_char(engine, target):
        return None
    kind = recorded_affinity(target)
    if kind not in REDUCED_AFFINITIES or amount <= 0 or str(damage_type or "").lower() != kind:
        return None
    round_number = int(engine.state.round_number)
    if target.turn_flags.get(RESIST_ROUND) == round_number:
        return None
    reduction = min(int(amount), int(getattr(target, "proficiency_bonus", 0) or 0))
    if reduction <= 0:
        return None

    def settle(applied: int) -> None:
        # A packet another defense prevented entirely was not a packet taken.
        if applied > 0:
            target.turn_flags[RESIST_ROUND] = round_number

    return {"reduction": reduction, "settle": settle}


@hook("zone_trigger_context")
def strike_zone_window(ctx: Any, zone: Any, creature: Any, moment: str) -> None:
    """A delayed zone trigger is its own activation, not the nondamaging cast."""
    if row_of(ctx.engine, ctx.actor.entity_id, "path_rider", "bloodline_strike") is not None:
        ctx.damage_cache["bloodline_zone_start"] = len(ctx.engine.events)


def _source_qi_powered(action: Any) -> bool:
    """Whether the activation that created a zone is itself Qi-powered, by its own printed typed source or Qi cost.

    A zone trigger's typed record names the trigger, not the cultivation that placed the area, so the creating
    action is the basis. A generic CP price alone does not establish Qi power;
    when compiled to this owner's Qi pool, its actual Qi cost does qualify."""
    from types import SimpleNamespace
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return action is not None and _qi_powered(SimpleNamespace(typed=typed, action=action))


@hook("damage_dealt")
def strike_zone_damage(ctx: Any, target: Any, amount: int) -> None:
    """Offer the same Strike after a Qi-powered zone actually damages its one trigger recipient."""
    start = ctx.damage_cache.get("bloodline_zone_start")
    if start is None or amount <= 0 or not _source_qi_powered(ctx.action):
        return
    from dataclasses import replace

    bloodline_strike(replace(ctx, technique_event_start=int(start)), qi_qualified=True)


REPEAT_PERMISSION = "condition:typed.repeated_lineage_strike"


def repeated_strike_permitted(actor: Any) -> bool:
    """A printed Source Rule that explicitly permits repeated lineage strikes (the Strike's exception to
    "once across a multiattack, Barrage, chain, or volley"). The permission is recorded as a condition only."""
    return any(condition.condition_id == REPEAT_PERMISSION for condition in actor.conditions.values())


def strike_flag(actor: Any, ctx: Any) -> str:
    """Once per turn. Without the Source Rule permission, a multiattack, Barrage, chain or volley shares this
    one turn flag, so the Strike applies once across it. With the permission, each activation has its own flag."""
    if repeated_strike_permitted(actor):
        return f"typed_once_turn:bloodline_strike:{ctx.technique_event_start}"
    return "typed_once_turn:bloodline_strike"


@hook("technique_used")
def bloodline_strike(ctx: Any, *, qi_qualified: bool = False) -> None:
    """Optional paid rider on one *actually damaged* recipient of a completed activation.

    The old broad modifier was a use effect, including buffs, and charged no resource.
    The activation window excludes HP payments (their source ends in .hp_cost) and other
    riders. The original action remains the damage delivery identity for defenses.
    """
    from .. import typed_executor as te
    from .choice_costs import payable

    engine, actor = ctx.engine, ctx.actor
    passive = row_of(engine, actor.entity_id, "path_rider", "bloodline_strike")
    if passive is None or not actor.active or not (qi_qualified or _qi_powered(ctx) or ctx.typed.get("delivered_by")):
        return
    kind = strike_affinity(actor)
    flag = strike_flag(actor, ctx)
    if kind not in {affinity_damage_type(value) for value in AFFINITY_TYPES} or actor.turn_flags.get(flag) or ctx.technique_event_start is None:
        return
    payment = payable(actor, RESONANCE, 1)
    if payment is None:
        return
    damaged = {}
    for event in engine.events[ctx.technique_event_start:]:
        if (event.event_type != "DAMAGE_COMMITTED" or event.actor_id != actor.entity_id
                or event.source_definition_id != ctx.action.source_definition_id
                or (event.payload or {}).get("display_source_id") not in (None, ctx.action.source_definition_id)):
            continue
        if int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) <= 0:
            continue
        for target_id in event.target_ids or ():
            if target_id in engine.state.actors:
                damaged[target_id] = engine.state.actors[target_id]
    if not damaged:
        return
    ranked = sorted(damaged.values(), key=lambda target: (target.team_id == actor.team_id, target.entity_id))
    count = 3 if int(passive.get("cl") or 1) >= 17 else 2 if int(passive.get("cl") or 1) >= 11 else 1
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "bloodline_strike", actor.entity_id),
                   actor, STRIKE_CHOICE, [target.entity_id for target in ranked],
                   labels={target.entity_id: f"{target.display_name}: +{count}d8 {kind.title()} damage"
                           for target in ranked}, allow_decline=True,
                   preferred=[ranked[0].entity_id], target_id=ranked[0].entity_id,
                   prompt=f"Bloodline Strike: after {ctx.action.display_name} damages "
                          + ", ".join(target.display_name for target in ranked)
                          + f", spend 1 Ancestral Resonance to deal {count}d8 {kind.title()} damage to one of them?",
                   name="Bloodline Strike", feature_id=BLOODLINE, payment=payment)
    if not selected or selected[0] not in damaged:
        return
    target = damaged[selected[0]]
    payment.pay(engine, actor, BLOODLINE)
    actor.turn_flags[flag] = 1
    # This is one recipient's extra packet, not another copy of the activation's
    # area/save/critical context or its once-per-activation Qi Potency bonus.
    rider = te.Context(engine, actor, ctx.action, ctx.intent,
                       {"source": BLOODLINE, "numbers": {**ctx.numbers, "key_mod": 0},
                        "duration": {"kind": "instant"}, "riders": []},
                       [target], target, {"_potency_used": True},
                       effect_source=BLOODLINE, explicit_self_recipient=target.entity_id == actor.entity_id)
    te.run_effects(rider, [{"type": "damage", "applies_to": "target",
                           "dice": {"count": count, "sides": 8}, "damage_types": [kind],
                           "damage_label": "Bloodline Strike"}])


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
