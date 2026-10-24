"""Talismans in a fight (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium, Talismans (owner's
text first, authority/typed_mechanics/rules_text.json and LocalSources/04_spheres_talents): nothing here is invented.

Shared helpers: formula_of and the TALENT/SPHERE identifiers are used by
talisman_affinity, talisman_seals and save_recheck to extend formula deliveries
and recognize their reactions independently of the delivery's display name.

  Prepared Talisman Limit  "You may carry many talismans, but only a limited number are immediately prepared for combat use. Your Prepared
                           Talisman Limit equals your Proficiency Bonus + Intelligence modifier, minimum 1."  Hidden Sleeve Preparation
                           +2, Hidden Sleeve Adept +1.  A fighter starts a fight with that many prepared talismans (the pool
                           ``resource:named.prepared_talismans``; the table does not list which formulae they are, so any formula
                           the character knows may be used from it -- the Gate 2 Lee Jia profile was modelled the same way).
  Consumed: yes            Every formula printed "Consumed: yes" (Ember, Binding, Healing, Purifying, Warding, Ghost-Warding, Revealing,
                           Message, Qi Storage, Demon-Subduing, Dao-Sealing, Shield) is offered only while a talisman is prepared and
                           uses one up (technique_start; the Shield Talisman and Talisman Reflection reactions on REACTION_WINDOW_OPENED).
  Ready a talisman         "Retrieving and readying an unprepared talisman requires an Action": an Action, one more prepared talisman,
                           up to the limit (the character "may carry many": what it carries beyond them is not on the sheet).
  Emergency Stroke         "You quickly draw a temporary Common talisman you know" (1 CP): one emergency talisman
                           (``resource:named.emergency_talismans``), usable only by a Common formula, which a Common formula spends
                           first.  "You may use Emergency Stroke a number of times equal to your Proficiency Bonus per long rest.
                           Additional uses cost 2 CP each": PB uses a fight at 1 CP, then 2 CP.  Battle Stroke Scripture (3 CP, a
                           Bonus Action, 1 minute): the Bonus Action strokes.  Talisman God Body: PB strokes a fight without CP.
  Talisman Wall            "Cost: 1 CP per talisman used ... For each talisman consumed, the wall gains 10 hit points": the wall asks how
                           many prepared talismans go into it (at least one), spends them and that much CP, and its hit points are
                           10 each (combat/rules/terrain.json "talisman wall": "10*talismans").
  Dao-Sealing Talisman     (Secret Formula) the failed save's "cannot spend that Path's resource" and the successful save's "cannot
                           spend CP": ``cp_sealed`` conditions whose data lists the pools; actions and reactions paid from them are not
                           offered while they last (candidate_allowed, row_allowed).
  Which pool "CP" is      "CP" is the fighter's own Path pool, which is Stamina for a Body Refining fighter and Resonance for a
                           Spirit Awakening one -- not always Qi.  Every printed-CP site here (Qi Storage Talisman, Talisman Wall,
                           Dao-Sealing Talisman) resolves the holder's real pool through ``combat/ext/cp_pools.py``; assuming Qi
                           raised ``ValueError("unknown resource")`` mid-turn for a fighter without a Qi pool (HUNT112, MMX118).

AUTO10 (round 25) added the printed effects that were still doing nothing, each keyed on its own record:
  Featherfall Talisman  "Reaction, triggered when the bearer or a creature within 30 feet begins falling ... descends safely
                         and takes no falling damage": the native falling checkpoint asks which falling creature within 30 feet
                         to protect, spends one talisman ("Consumed: yes") and the Reaction, and records the one-minute safe
                         descent -- the same shape Qi Cultivation's Featherfall uses, so a creature already safe is left alone.
  Talisman Recall       "Choose one talisman you crafted and can perceive ... If unattended, it flies to your hand or a legal
                          space within your reach ... If held or worn by another creature, that creature makes a Strength
                          saving throw": a talisman only exists out there if the fighter's fight setup declared one
                          (prefight_setup_choices, one integer, the same "records earlier crafting" pattern as the Qi Storage
                          charges), so Recall is off the menu with none. The fighter then names where it is -- lying
                          unattended, or held or worn by a creature the fighter perceives (any creature, hostile or
                          allied) -- and that creature, not the first enemy on the field, answers the printed Strength saving
                          throw. "It flies to your hand or a legal space within your reach" is bringing it back, not readying
                          it: the printed Prepared Talisman Limit is the only thing that makes a talisman ready to use, so a
                          recalled talisman joins the prepared ones only while there is room, and at the limit it waits in the
                          fighter's hand for the printed "Ready a talisman" (one Action) instead of the limit being exceeded.
  Remote Activation    "activate a prepared talisman you crafted within 60 feet as if you were holding it": every formula its
                          owner learned compiles at 60 feet, and the fighter names which creature within 60 feet is holding the
                          talisman (or keeps it at hand). That holder -- not the caster, and not the formula's target -- is asked
                          whether it allows the activation, and an unwilling holder's printed Wisdom save runs before the talisman
                          is spent, so a success leaves it unspent. "As if you were holding it" is kept: the formula's own reach
                          is measured from the talisman, not from the caster, so a target beyond the formula's printed range of
                          the talisman is refused rather than silently widened.
  Elemental Talisman   "Choose Acid, Cold, Fire, Lightning, or Thunder when you craft a compatible Attack formula ... When
                          you spend at least 1 CP while crafting the talisman, add your Proficiency Bonus to one damage
                          roll the talisman makes ... You may learn this talent multiple times, choosing a different
                          damage type each time": the damage type and the crafting payment belong to one crafted talisman,
                          not to the fighter, and the sheet records neither. The free "Elemental Talisman: choose a damage
                          type" button therefore records what this fighter's learnings let them craft with -- every printed
                          damage type not yet chosen is offered, and one is taken per learning, "a different damage type each
                          time" -- and that standing record is kept and reused:
                          choosing a type does not use it up, so a later talisman may be crafted for any of them again. Which
                          of those types this very talisman was crafted for is asked when the talisman is activated (the
                          engine holds no talisman objects, so the activation is the only moment one formula names one
                          talisman), as is the printed crafting payment, and both answers last that activation only. The
                          printed Proficiency Bonus then reaches ONE damage roll of that talisman, never a second roll.
  Living Scripture      "hit points become 10 x your Proficiency Bonus; duration becomes 10 minutes": combat/rules/summons.json
                         'improvements' adds the spirit's own 5 x PB again for its owner, and this module extends the
                         spirit's lifetime; the printed carrying and telepathy remain a reminder.
  Read the Script      "Make an Intelligence check using Arcana, Investigation, Calligrapher's Supplies, or another relevant
                          proficiency ... On a success, learn one: ... Success by 5 or more reveals an additional fact": the roll
                          is real (Advantage from the four talents that print it now applies), the fighter names which fact of the
                          writing they are reading, and exactly one fact is revealed -- two when the check beats the DC by 5.
                          What the inspected writing actually says is not on the sheet, so that one fact is a GM rider rather
                          than an invented value. The print sets no Difficulty Class, so the fighter names how hard the writing
                          is to read; that is the one judgement this lane had to leave to the table.
    Talisman Bomb        "Cost: 6 CP plus consumed talismans ... Bundle up to your Proficiency Bonus compatible talismans ...
                          All talismans in the bomb are consumed": 6 CP is a priced cost on the button (the fighter's own
                          Path pool, as the printed "CP" means), and bomb_talismans asks how many prepared talismans go in
                          (up to the Proficiency Bonus) and spends them.  Before this the bomb cost nothing and used no
                          talisman at all -- a 20-foot sphere for free.

Deferred to the table (AUTO10f1 review): the two printed arrays whose placement the engine cannot hold.

    Talisman Array       "Setup Time: 1 minute / Cost: 3 CP plus the talismans used / Place up to your Proficiency Bonus
                          compatible talismans inside the area ... When one activates, consume the supporting talismans ...": the
                          printed trigger is a talisman activating, and the engine knows neither which formulae the fighter
                          prepared nor where a prepared talisman is, so there is nothing to detect, nothing to consume and
                          nothing to refund. Spending the talismans at setup made them unrecoverable and used up Ten Thousand
                          Tags Obey's benefit before any array triggered, so the printed lines stay riders (see
                          authority/typed_mechanics/reviewed_final.d/auto10_talismans.json).
    Ten Thousand Tags    "up to twice your Proficiency Bonus talismans ... once per long rest ... prevent that talisman from
    Obey                 being consumed": it changes the Talisman Array's own placement, so it waits with the array.
"""

from __future__ import annotations

from ..paid_relocation import activation

import re
from typing import Any

from ..resource_costs import parts as cost_parts
from . import effect, hook

SPHERE = "tianxia.sphere.talismans"
PREPARED = "resource:named.prepared_talismans"
EMERGENCY = "resource:named.emergency_talismans"
STROKES = "resource:named.emergency_strokes"          # the PB uses per long rest (a fight is inside one rest)
GOD_STROKES = "resource:named.god_body_strokes"       # Talisman God Body: PB strokes without CP
BATTLE = "condition:typed.battle_stroke"
SEALED = "condition:typed.cp_sealed"
TALENT = "tianxia.talent.talismans."
BASE_STROKE = "TALISMANS_BASE_EMERGENCY_STROKE"
# Formulae printed "Consumed: yes", and their rank ("A temporary Common talisman" fits only a Common formula).
FORMULAS = {"ember_talisman": "common", "binding_talisman": "uncommon", "healing_talisman": "common", "purifying_talisman": "common",
            "warding_talisman": "common", "ghost_warding_talisman": "uncommon", "revealing_talisman": "common", "message_talisman": "common",
            "qi_storage_talisman": "uncommon", "demon_subduing_tag": "rare", "secret_formula": "secret", "shield_talisman": "common",
            "featherfall_talisman": "common",
            "talisman_spirit": "crafted"}  # Talisman Spirit animates "one prepared talisman you crafted" (not an emergency one)
REACTIONS = {"shield_talisman", "talisman_reflection"}  # reactions that use up a prepared talisman ("5 CP and one compatible prepared talisman")
QI_STORAGE = "condition:typed.qi_storage_talisman"
# Featherfall Talisman's safe descent, and the two conditions that mean "already descending safely".
FEATHERFALL_CONDITION = "condition:typed.featherfall_talisman"
# Elemental Talisman: the damage type the fighter chose when crafting, as a sticky condition on them.
ELEMENT = "condition:typed.elemental_talisman"
ELEMENTS = ("acid", "cold", "fire", "lightning", "thunder")
REMOTE = "remote_activation"
# Scratch for one atomic activation, never catalog data or persisted fight state.
# Every activation resets it (including after a countered technique); the effect consumes it.
QI_ACTIVATION = "_qi_storage_activation_cp"


def _owned(ids: Any) -> set[str]:
    return {str(key).rsplit(".", 1)[-1].replace("-", "_") for key in ids or []
            if str(key).startswith(TALENT) or str(key) == "insight.hidden-sleeve-adept"}


@hook("compile_actions")
def binding_throw(info: dict[str, Any]) -> list[Any] | None:
    """Offer Binding's printed thrown delivery without changing its 30-foot use.

    This formula calls for a Strength save, not an attack roll. The 20/60-foot
    thrown range therefore adds no attack-roll Disadvantage to that save.
    Both versions consume one talisman through the existing formula hook.
    """
    if TALENT + "binding_talisman" not in (info.get("owned_ids") or []):
        return None
    out = []
    for action in info.get("actions") or []:
        if not str(action.source_definition_id).endswith(TALENT + "binding_talisman"):
            continue
        # compile_actions runs before compile_action. Compose the same remote
        # holder/consent route before widening the alternate delivery to 60 feet;
        # otherwise the later remote transform sees 60 feet and skips it.
        remote = compile_remote_activation(action, info)
        parameters = {**(remote or action).parameters, "description":
                      "Throw one Binding Talisman up to 60 feet (normal thrown range 20 feet). "
                      "The creature makes a Strength saving throw: failure restrains it for 1 minute, "
                      "with a repeat save at the end of each turn; success reduces its Speed by 10 feet "
                      "until the start of your next turn. Uses one prepared talisman and your Action."}
        if parameters.get("remote_activation"):
            # "As if holding it" uses this delivery's reach, not the normal
            # version's 30-foot reach copied from the original formula.
            parameters[REMOTE_REACH] = 60
        out.append(action.model_copy(update={
            "source_definition_id": f"action:typed.{info['short']}.thrown.{TALENT}binding_talisman",
            "display_name": "Binding Talisman (throw, 20/60 feet)", "range_ft": 60, "parameters": parameters}))
    return out


def limit(pb: int, int_mod: int, owned: set[str]) -> int:
    return max(1, int(pb) + int(int_mod)) + (2 if "hidden_sleeve_preparation" in owned else 0) + (1 if "hidden_sleeve_adept" in owned else 0)


def _is_talisman_user(info: dict[str, Any]) -> bool:
    return SPHERE in (info.get("spheres") or []) or any(str(key).startswith(TALENT) for key in info.get("owned_ids") or [])


@hook("compile_resources")
def resources(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ResourceDefinition

    if not _is_talisman_user(info):
        return None
    owned = _owned(info.get("owned_ids"))
    pb = int(info.get("pb") or 2)
    most = limit(pb, int((info.get("mods") or {}).get("INT", 0)), owned)
    out = [ResourceDefinition(resource_id=PREPARED, initial=most, maximum=most), ResourceDefinition(resource_id=EMERGENCY, initial=0, maximum=most),
           ResourceDefinition(resource_id=STROKES, initial=pb, maximum=pb)]
    if "talisman_god_body" in owned:
        out.append(ResourceDefinition(resource_id=GOD_STROKES, initial=pb, maximum=pb))
    return out


def _stroke_action(info: dict[str, Any], sid: str, name: str, economy: str, costs: tuple[Any, ...], variant: str, description: str) -> Any:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "talisman_stroke", "variant": variant, "evidence": "Emergency Stroke: a temporary Common talisman you know"}],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": BASE_STROKE, "sphere": SPHERE,
             "typing_status": "talisman_plugin", "coverage": "FULL"}
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.talisman.{sid}", display_name=name, owner_id=info["actor_id"],
                            economy=EconomyKind[economy], resolution_kind="TYPED", target_kind="SELF", range_ft=None, costs=costs,
                            parameters={"typed": typed, "expected_damage": 0, "player_only": True, "talisman": variant, "description": description})


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS

    if not _is_talisman_user(info):
        return None
    owned = _owned(info.get("owned_ids"))
    pb = int(info.get("pb") or 2)
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out = [_stroke_action(info, "ready", "Ready a talisman", "ACTION", (), "ready",
                          "Retrieve and ready one of the talismans you carry: one more prepared talisman, up to your Prepared Talisman Limit.")]
    out[0] = out[0].model_copy(update={"parameters": {**out[0].parameters,
        "talisman_sleeve_adept": "hidden_sleeve_adept" in owned,
        "talisman_library": "formula_library" in owned}})
    if BASE_STROKE in (info.get("owned_ids") or []) or SPHERE in (info.get("spheres") or []):
        # The compiled base action (1 CP) is the first PB uses; after them each costs 2 CP ("Additional uses cost 2 CP each").
        out.append(_stroke_action(info, "stroke.extra", "Emergency Stroke (2 CP)", "ACTION", ((pool, 2),), "extra",
                                  "Emergency Stroke past your Proficiency Bonus uses this long rest: 2 CP."))
        if "talisman_god_body" in owned:
            out.append(_stroke_action(info, "stroke.free", "Emergency Stroke (Talisman God Body, no CP)", "ACTION", ((GOD_STROKES, 1),), "free",
                                      "Talisman God Body: Proficiency Bonus times per long rest, an Emergency Stroke for a Common talisman without CP."))
        if "battle_stroke_scripture" in owned:
            out.append(_stroke_action(info, "stroke.bonus", "Emergency Stroke (Bonus Action)", "BONUS_ACTION", ((pool, 1),), "bonus",
                                      "Battle Stroke Scripture: Emergency Stroke as a Bonus Action while it lasts."))
            out.append(_stroke_action(info, "stroke.bonus_extra", "Emergency Stroke (Bonus Action, 2 CP)", "BONUS_ACTION", ((pool, 2),), "bonus_extra",
                                      "Battle Stroke Scripture: Emergency Stroke as a Bonus Action past your uses this long rest: 2 CP."))
            if "talisman_god_body" in owned:
                out.append(_stroke_action(info, "stroke.bonus_free", "Emergency Stroke (Bonus Action, no CP)", "BONUS_ACTION", ((GOD_STROKES, 1),),
                                          "bonus_free", "Battle Stroke Scripture with Talisman God Body: a Bonus Action stroke without CP."))
    if "elemental_talisman" in owned:
        # Elemental Talisman: "Choose Acid, Cold, Fire, Lightning, or Thunder when you craft a compatible Attack formula ...
        # You may learn this talent multiple times, choosing a different damage type each time."  Each learning of the talent
        # lets the fighter choose one damage type, and what they have chosen is a standing record of what they may craft
        # with -- kept, not used up (a later talisman may be crafted for any type already chosen).  Which of those types
        # one talisman was crafted for is asked when that talisman is used; see elemental_crafting_choices.
        learnings = sum(1 for key in info.get("owned_ids") or [] if str(key).rsplit(".", 1)[-1] == "elemental_talisman")
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.talisman.elemental",
                                    display_name="Elemental Talisman: choose a damage type", owner_id=info["actor_id"],
                                    economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                                    parameters={"typed": {"effects": [{"type": "talisman_element", "evidence": ELEMENT_EVIDENCE}],
                                                          "numbers": dict(info["numbers"]), "duration": {"kind": "instant"},
                                                          "riders": [], "source": TALENT + "elemental_talisman", "sphere": SPHERE,
                                                          "typing_status": "talisman_plugin", "coverage": "FULL"},
                                                 "expected_damage": 0, "player_only": True,
                                                 "talisman_learnings": max(1, int(learnings or 1)),
                                                 "description": "Each time you learn Elemental Talisman you choose one damage type "
                                                               "for the talismans you craft: Acid, Cold, Fire, Lightning or "
                                                               "Thunder, and any type you have not chosen yet is offered. A "
                                                               "talisman you craft for a chosen damage type deals that type "
                                                               "instead of its normal one, and it stays one of the types you "
                                                               "may craft for. Take this once for each learning of the "
                                                               "talent."}))
    return out


ELEMENT_EVIDENCE = ("Choose Acid, Cold, Fire, Lightning, or Thunder when you craft a compatible Attack formula. The formula deals "
                    "that damage type instead of its normal elemental damage. When you spend at least 1 CP while crafting the "
                    "talisman, add your Proficiency Bonus to one damage roll the talisman makes. You may learn this talent "
                    "multiple times, choosing a different damage type each time.")
ELEMENTAL_TALENT = TALENT + "elemental_talisman"
CRAFTED_ELEMENT = "_talisman_crafted_element"   # scratch for one activation: the damage type THIS talisman was crafted for
CRAFTING_PAID = "_talisman_crafting_paid"       # scratch for one activation: the printed crafting payment was made
ONE_ROLL = "talismans:elemental_bonus"          # key in the executor's activation-local damage cache


def _elements(actor: Any) -> set[str]:
    """Every damage type this fighter's Elemental Talisman learnings have let them choose.

    One condition's ``elements`` list is the standing record of what this fighter may craft with; a fight saved while
    the first learning was all that was kept holds the single ``element`` instead, and still reads.
    """
    for row in actor.conditions.values():
        if row.condition_id != ELEMENT:
            continue
        data = row.data or {}
        chosen = {str(name) for name in data.get("elements") or [] if str(name) in ELEMENTS}
        if data.get("element") in ELEMENTS:
            chosen.add(str(data["element"]))
        if chosen:
            return chosen
    return set()


def _element_label(learned: set[str]) -> str:
    """The condition pill: which damage types this fighter may craft their talismans for."""
    return "Elemental Talisman: " + ", ".join(name.capitalize() for name in sorted(learned))


@effect("talisman_element")
def talisman_element(ctx: Any, eff: dict[str, Any]) -> None:
    """Record the damage types this fighter's Elemental Talisman learnings let them craft with.

    "Choose Acid, Cold, Fire, Lightning, or Thunder" and "You may learn this talent multiple times, choosing a
    different damage type each time": the menu offers every printed damage type the fighter has not chosen yet, so
    which one a learning takes is the fighter's own, and one press records one type.  The button stays on the menu
    until every learning has a type of its own (``elemental_candidate``), which is what "one per remaining learning"
    means; a type already chosen is never offered again.  What they have chosen is kept rather than used up, so
    every talisman they craft afterwards may be crafted for any of these types (the one talisman uses is asked in
    ``elemental_crafting_choices``).
    """
    from . import note
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    chosen_elements = _elements(actor)
    outstanding = max(1, int((ctx.action.parameters or {}).get("talisman_learnings") or 1)) - len(chosen_elements)
    # Every printed damage type still unchosen is offered, whatever order ELEMENTS holds them in: the print names
    # five, not "the first one or two", so a fighter with two learnings may take Fire and Thunder and a fighter
    # with one may take any of the five.
    options = [name for name in ELEMENTS if name not in chosen_elements]
    if outstanding <= 0 or not options:
        note(engine, ctx.source, actor,
             f"{actor.display_name} has already chosen every damage type these learnings of Elemental Talisman allow "
             f"({'a different damage type each time'}).")
        return
    labels = {name: f"Elemental Talisman: you may craft talismans that deal {name.capitalize()} damage" for name in options}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "talisman_element", actor.entity_id), actor,
                 CHOICE + "talisman_element", options, labels=labels, preferred=options[:1],
                 prompt=f"Elemental Talisman: which damage type are you choosing? You may choose Acid, Cold, Fire, "
                        f"Lightning or Thunder, as long as you have not chosen it before, and you have {outstanding} more "
                        f"learning{'s' if outstanding != 1 else ''} of this talent to choose for. A talisman you craft for a "
                        f"damage type deals that type instead of its normal one, and it stays one of the damage types you "
                        f"may craft for.",
                 name="Elemental Talisman", feature_id=ELEMENTAL_TALENT)
    if not picked:
        return
    learned = {*chosen_elements, str(picked[0])} & set(ELEMENTS)
    for instance, row in list(actor.conditions.items()):
        if row.condition_id != ELEMENT:
            continue
        del actor.conditions[instance]
        engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": ELEMENT, "instance_id": instance})
    engine._apply_condition(actor, ELEMENT, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"elements": sorted(learned), "label": _element_label(learned)})
    types = ", ".join(name.capitalize() for name in sorted(learned))
    note(engine, ctx.source, actor,
         f"{actor.display_name} chooses {str(picked[0]).capitalize()} damage for a talisman they craft: that talisman deals "
         f"{str(picked[0]).capitalize()} damage instead of its normal damage type (may craft for: {types}).")


def _attack_formula(action: Any) -> bool:
    """"when you craft a compatible Attack formula": the action's own typed rows make an attack."""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return any(row.get("type") == "attack" for row in typed.get("effects") or [])


def elemental_crafting_choices(engine: Any, actor: Any, action: Any) -> None:
    """"The formula deals that damage type instead of its normal elemental damage ... When you spend at least 1 CP while
    crafting the talisman, add your Proficiency Bonus to one damage roll the talisman makes." (Elemental Talisman)

    Both answers belong to one crafted talisman, not to the fighter: the damage type is which of the types this fighter's
    learnings let them choose was chosen for *this* talisman, and the CP was spent on *this* talisman's crafting.  The
    engine holds no talisman objects, so the only moment one formula names one talisman is the activation, and both
    answers last that activation only.  A fighter with one learned damage type is not asked to choose it, and a formula
    that makes no attack gets neither question, because the print's lines are about a crafted Attack formula.
    """
    engine.__dict__.pop(CRAFTED_ELEMENT, None)
    engine.__dict__.pop(CRAFTING_PAID, None)
    learned = _elements(actor)
    if not learned or not _attack_formula(action):
        return
    from .needle import CHOICE, ask, checkpoint_id

    intent = getattr(engine, "_active_intent", None)
    offered = sorted(learned)
    crafted = offered[0] if len(offered) == 1 else _crafted_type(engine, actor, intent, offered)
    engine.__dict__[CRAFTED_ELEMENT] = crafted
    paid, unpaid = "spent_cp", "spent_no_cp"
    options = [paid, unpaid]
    labels = {paid: f"You spent 1 CP or more crafting this talisman: it adds your Proficiency Bonus ({actor.proficiency_bonus:+d}) "
                   f"to one damage roll",
              unpaid: "You spent no CP crafting this talisman: it adds no bonus to its damage"}
    picked = ask(engine, intent, checkpoint_id(engine, "talisman_crafting", actor.entity_id),
                 actor, CHOICE + "talisman_crafting", options, labels=labels, preferred=[paid],
                 prompt="Elemental Talisman: while you were crafting this talisman, did you spend at least 1 Cultivation "
                        "Point (CP)? It adds your Proficiency Bonus to one damage roll when you did.",
                 name="Elemental Talisman", feature_id=ELEMENTAL_TALENT, target_id=actor.entity_id)
    engine.__dict__[CRAFTING_PAID] = bool(picked) and picked[0] == paid


def _crafted_type(engine: Any, actor: Any, intent: Any, offered: list[str]) -> str:
    """Which of the damage types this fighter has learned was chosen for the talisman being activated."""
    from .needle import CHOICE, ask, checkpoint_id

    labels = {name: f"Elemental Talisman: this talisman deals {name.capitalize()} damage instead of its normal damage type"
              for name in offered}
    picked = ask(engine, intent, checkpoint_id(engine, "talisman_crafted_element", actor.entity_id), actor,
                 CHOICE + "talisman_crafted_element", offered, labels=labels, preferred=offered[:1],
                 prompt="Elemental Talisman: which damage type did you choose for this talisman when you crafted it? It deals "
                        "that damage type instead of its normal elemental damage.",
                 name="Elemental Talisman", feature_id=ELEMENTAL_TALENT, target_id=actor.entity_id)
    return str(picked[0]) if picked and str(picked[0]) in ELEMENTS else ""


@hook("attack_damage_types")
def elemental_damage_type(ctx: Any, attack: Any, kinds: list[str]) -> list[str] | None:
    """"The formula deals that damage type instead of its normal elemental damage" (Elemental Talisman).

    Only a strike by one of the fighter's own talisman formulae changes, and only the damage type this activation's
    talisman was crafted for; every other attack keeps the executor's own choice, and a strike with no elemental type
    to replace is left alone.
    """
    chosen = _element_strike(ctx, kinds)
    return [chosen.upper()] if chosen else None


@hook("damage_roll_bonus")
def elemental_proficiency_bonus(ctx: Any, effect: Any, kinds: list[str]) -> int | None:
    """"add your Proficiency Bonus to one damage roll the talisman makes" (Elemental Talisman).

    Every printed condition is required: a talisman formula of this fighter's own ("a compatible Attack formula", so an
    action whose compiled rows include an attack), a damage type chosen when this talisman was crafted ("The formula
    deals that damage type instead of its normal elemental damage"), the crafting payment for this very talisman
    ("When you spend at least 1 CP while crafting the talisman"), and ONE damage roll -- the first roll the talisman
    makes in this activation, never a second row of the same formula.  A weapon's own damage is never one of the
    talisman's rolls.
    """
    if not _one_elemental_roll_available(ctx):
        return None
    if effect is None:
        return None if ctx.weapon_damage_dice else _one_elemental_roll(ctx)
    if effect.get("type") != "damage" or effect.get("weapon_damage"):
        return None
    return _one_elemental_roll(ctx)


def _one_elemental_roll_available(ctx: Any) -> bool:
    """Whether this activation is a talisman Attack formula crafted for a chosen damage type, and paid for."""
    return (formula_of(ctx.action) is not None and _attack_formula(ctx.action)
            and _crafted_element(ctx) is not None and bool(ctx.engine.__dict__.get(CRAFTING_PAID)))


def _one_elemental_roll(ctx: Any) -> int | None:
    """"one damage roll the talisman makes": the executor's activation-local cache remembers that it has been used."""
    if ctx.damage_cache.get(ONE_ROLL):
        return None
    ctx.damage_cache[ONE_ROLL] = True
    return int(ctx.actor.proficiency_bonus)


def _crafted_element(ctx: Any) -> str | None:
    """The damage type this activation's talisman was crafted for, or None when nothing was chosen for it."""
    chosen = str((getattr(ctx.engine, "__dict__", None) or {}).get(CRAFTED_ELEMENT) or "")
    return chosen if chosen in ELEMENTS else None


def _element_strike(ctx: Any, kinds: list[str]) -> str | None:
    """The crafted damage type when this strike is one of the fighter's talisman formulae that deals elemental damage."""
    chosen = _crafted_element(ctx)
    if chosen is None or formula_of(ctx.action) is None:
        return None
    return chosen if any(str(kind).lower() in ELEMENTS for kind in kinds) else None


@hook("candidate_allowed")
def elemental_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The Elemental Talisman button stays on the menu while a learning of the talent has no damage type chosen yet."""
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    if not any(eff.get("type") == "talisman_element" for eff in typed.get("effects") or []):
        return None
    permitted = max(1, int((action.parameters or {}).get("talisman_learnings") or 1))
    return False if len(_elements(actor)) >= permitted else None


# Remote Activation: "activate a prepared talisman you crafted within 60 feet as if you were holding it".  The
# talisman's location and the creature the formula affects are two different things, so the action carries the formula's
# own printed reach (``remote_range_ft``) as well as the 60 feet the talent prints, and the gate below works from both.
REMOTE_TALISMAN = "remote_talisman"       # the holder's id, or "" for the caster's own hand
REMOTE_REACH = "remote_range_ft"          # the formula's own printed range, measured from the talisman


@hook("compile_action")
def compile_remote_activation(action: Any, info: dict[str, Any]) -> Any | None:
    """"You may activate a prepared talisman you crafted within 60 feet as if you were holding it" (Remote Activation).

    Only a talisman formula its owner learned is reached, and only when the printed range is shorter than
    60 feet. The widened action keeps the formula's own printed reach in ``remote_range_ft`` and carries
    ``remote_activation`` so the gate in ``remote_activation_gate`` can ask the talisman's actual holder and
    measure the formula's reach from the talisman rather than from the caster.
    """
    if REMOTE not in _owned(info.get("owned_ids")) or formula_of(action) is None:
        return None
    own_range = int(getattr(action, "range_ft", 0) or 0)
    if own_range >= 60:
        return None
    parameters = {**(action.parameters or {}), "remote_activation": True, "remote_perception_required": True,
                  REMOTE_REACH: own_range}
    return action.model_copy(update={"range_ft": 60, "parameters": parameters})


def remote_activation_gate(engine: Any, actor: Any, action: Any) -> str | None:
    """The reason a Remote Activation must not resolve, or None when it may.

    Three printed checks, in the print's own order:

      * the talisman is within the printed 60 feet of the caster, held or worn by the creature the fighter names;
      * "as if you were holding it": the formula's own printed reach is measured from the talisman, so a creature the
        talisman cannot reach is not the talisman's target however far away from the caster it is;
      * the holder, not the caster and not the formula's target, is asked whether it allows the activation, and an
        unwilling holder's printed Wisdom saving throw can end it before the talisman is spent.

    No choice in a pre-fight construction (``_active_intent`` is absent), so a catalog build is unaffected.
    """
    parameters = action.parameters or {}
    if not parameters.get("remote_activation"):
        return None
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return None
    from . import note
    from .needle import CHOICE, ask, checkpoint_id

    reach = int(parameters.get(REMOTE_REACH) or 0)
    targets = [engine.state.actors[key] for key in intent.target_ids if key in engine.state.actors]
    holders = [other for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
               if other.active and other.entity_id != actor.entity_id
               and engine._distance_actor_to_actor(actor, other) <= 60]
    if parameters.get("remote_perception_required"):
        from ..senses import perceives
        holders = [other for other in holders if perceives(engine, actor, other)]
    labels = {other.entity_id: f"Remote Activation: {other.display_name} is holding or wearing the talisman" for other in holders}
    at_hand = ""
    labels[at_hand] = f"Remote Activation: you activate the talisman in your own hand"
    options = [at_hand, *[other.entity_id for other in holders]]
    preferred = [other.entity_id for other in holders if other.team_id != actor.team_id][:1] or [at_hand]
    chosen = ask(engine, intent, checkpoint_id(engine, "talisman_remote_holder", actor.entity_id), actor,
                 CHOICE + "talisman_remote_holder", options, labels=labels, preferred=preferred,
                 prompt="Remote Activation: which creature within 60 feet is holding the talisman you activate?"
                        " Choose yourself to activate the talisman in your own hand.",
                 name="Remote Activation", feature_id=TALENT + REMOTE, target_id=actor.entity_id)
    holder = engine.state.actors.get(chosen[0]) if chosen and chosen[0] else None
    engine.__dict__[REMOTE_TALISMAN] = holder.entity_id if holder is not None else ""
    if holder is None:  # the talisman is in the caster's own hand: its reach is the caster's reach
        for target in targets:
            if reach and engine._distance_actor_to_actor(actor, target) > reach:
                return _remote_out_of_reach(engine, actor, action, actor, target, reach)
        return None
    for target in targets:
        if reach and engine._distance_actor_to_actor(holder, target) > reach:
            return _remote_out_of_reach(engine, actor, action, holder, target, reach)
    decision = ["lets it happen", "refuses"]
    answers = {"lets it happen": f"{holder.display_name} lets {actor.display_name} activate the talisman",
               "refuses": f"{holder.display_name} refuses (makes a Wisdom saving throw)"}
    picked = ask(engine, intent, checkpoint_id(engine, "talisman_remote", actor.entity_id, holder.entity_id), holder,
                 CHOICE + "talisman_remote", decision, labels=answers,
                 preferred=["lets it happen"] if holder.team_id == actor.team_id else ["refuses"],
                 prompt=f"{holder.display_name} is holding or wearing the talisman {actor.display_name} is activating "
                        f"with {action.display_name}. Remote Activation: does the holder allow it?",
                 target_id=holder.entity_id, name="Remote Activation", feature_id=TALENT + REMOTE)
    if not picked or picked[0] == "lets it happen":
        return None
    dc = int((((parameters.get("typed") or {}).get("numbers") or {}).get("save_dc")) or 10)
    roll = engine._roll_save(holder, "WIS", dc, action.source_definition_id)
    saved = roll is not None and int(roll.total) >= dc
    note(engine, action.source_definition_id, actor,
         f"Remote Activation: {holder.display_name} makes a Wisdom saving throw ({roll.total if roll else 0} against DC {dc})"
         f" and {'refuses the activation; the talisman is not used' if saved else 'cannot stop the talisman'}.")
    return "the holder saved" if saved else None


def _remote_out_of_reach(engine: Any, actor: Any, action: Any, holder: Any, target: Any, reach: int) -> str:
    """"As if you were holding it" keeps the formula's own reach: the reach is measured from the talisman."""
    from . import note

    where = "your own hand" if holder.entity_id == actor.entity_id else f"{holder.display_name}, who holds the talisman"
    feet = int(engine._distance_actor_to_actor(holder, target))
    note(engine, action.source_definition_id, actor,
         f"Remote Activation: {action.display_name} reaches {reach} feet from the talisman, and {target.display_name} is "
         f"{feet} feet from it (in {where}), so the talisman cannot affect it.")
    return "out of the formula's reach of the talisman"


@hook("compile_action")
def compile_qi_storage(action: Any, info: dict[str, Any]) -> Any | None:
    """Replace the maximum-CP placeholder with the stored amount for owners of the formula.

    The pool is deliberately NOT recorded here.  ``compile_action`` is called with an info dict that
    has no ``primary`` (and no ``pools``), so any pool chosen at this point is a guess: the old
    ``RESOURCE_IDS.get(info.get("primary") or "qi")`` therefore always produced ``resource:core.qi``,
    and a Stamina or Resonance fighter pressed a button that raised
    ``ValueError("unknown resource")``.  ``qi_storage_restore`` resolves the fighter's real Path pool
    at use time through ``cp_pools``; catalogs saved before this change keep the parameter they were
    compiled with and ``cp_pools.restore_pool`` honours it whenever that fighter really has it.
    """
    if not str(getattr(action, "source_definition_id", "")).endswith(TALENT + "qi_storage_talisman"):
        return None
    import copy
    replacement = copy.deepcopy(action)
    typed = replacement.parameters["typed"]
    typed["effects"] = [{"type": "qi_storage_restore", "evidence": "Qi Storage Talisman restores the CP stored in it"}]
    return replacement


# ------------------------------------------------------------------------------------------------ which action is which
def formula_of(action: Any) -> str | None:
    """The "Consumed: yes" formula an action uses, or None."""
    source = str(getattr(action, "source_definition_id", "") or "")
    found = re.search(r"tianxia\.talent\.talismans\.([a-z_]+)", source)
    return found.group(1) if found and found.group(1) in FORMULAS else None


def available(actor: Any, formula: str) -> bool:
    from .talisman_preparation import library_available

    common = FORMULAS.get(formula) == "common"
    return actor.resources.get(PREPARED, 0) >= 1 or (common and actor.resources.get(EMERGENCY, 0) >= 1) or library_available(actor, formula)


def use_up(engine: Any, actor: Any, formula: str, source: str) -> bool:
    """Spend the talisman a formula is written on: an emergency one first for a Common formula, else a prepared one."""
    if FORMULAS.get(formula) == "common" and actor.resources.get(EMERGENCY, 0) >= 1:
        engine._spend_resource(actor, EMERGENCY, 1, source)
        return True
    from .talisman_preparation import LIBRARY_SLOT, library_available

    if library_available(actor, formula):
        engine._spend_resource(actor, LIBRARY_SLOT, 1, source)
        return True
    if actor.resources.get(PREPARED, 0) >= 1:
        engine._spend_resource(actor, PREPARED, 1, source)
        return True
    return False


def _sealed_pools(actor: Any) -> set[str]:
    return {str(pool) for row in actor.conditions.values() if row.condition_id == SEALED for pool in (row.data or {}).get("pools") or []}


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from . import cp_pools

    if action is None:
        return None
    sealed = _sealed_pools(actor) if actor.conditions else set()
    if sealed and any(resource in sealed and int(amount) > 0 for resource, amount in action.costs):
        return False  # Dao-Sealing Talisman: that Path's resource cannot be spent
    formula = formula_of(action)
    if formula is not None and PREPARED in actor.resources and not available(actor, formula):
        return False
    if PREPARED in actor.resources and not available(actor, BOMB) and _printed_bundle(action, BOMB):
        return False  # a printed bundle of talismans needs one to put in it
    if formula == "qi_storage_talisman" and cp_pools.of(actor) is None:
        return False  # no Path pool to restore into: do not offer a button that cannot work
    variant = (action.parameters or {}).get("talisman")
    if variant is None:
        if str(action.source_definition_id).endswith("." + BASE_STROKE) and actor.resources.get(STROKES, 1) < 1:
            return False  # past the Proficiency Bonus uses: "Emergency Stroke (2 CP)"
        return None
    if variant == "ready":
        return None if actor.resources.get(PREPARED, 0) < _maximum(engine, actor, PREPARED) else False
    if variant in ("extra", "bonus_extra") and actor.resources.get(STROKES, 0) >= 1:
        return False
    if variant == "bonus" and actor.resources.get(STROKES, 0) < 1:
        return False
    if variant.startswith("bonus") and not any(row.condition_id == BATTLE for row in actor.conditions.values()):
        return False
    if actor.resources.get(EMERGENCY, 0) >= _maximum(engine, actor, EMERGENCY):
        return False
    return None


def _maximum(engine: Any, actor: Any, resource_id: str) -> int:
    return int((getattr(actor, "resource_maximums", None) or {}).get(resource_id) or 0)


@hook("technique_start")
def consume(engine: Any, actor: Any, action: Any) -> bool | None:
    formula = formula_of(action)
    if formula is None or PREPARED not in actor.resources:
        return None
    engine.__dict__.pop(REMOTE_TALISMAN, None)
    engine.__dict__.pop(CRAFTED_ELEMENT, None)
    engine.__dict__.pop(CRAFTING_PAID, None)
    if formula == "qi_storage_talisman":
        engine.__dict__.pop(QI_ACTIVATION, None)
    if remote_activation_gate(engine, actor, action):
        return True  # "your remote activation fails but the talisman is not consumed": stop before it is spent
    if not use_up(engine, actor, formula, f"talisman:{formula}"):
        from . import note

        note(engine, f"talisman:{formula}", actor, f"{actor.display_name} has no prepared talisman left for {action.display_name}.")
        return True
    if formula == "qi_storage_talisman":
        stored = _stored_talismans(actor)
        # Ready adds unrecorded carried inventory. Preserve its existing PB assumption,
        # as for predecessor fights with no crafting records; zero is a recorded amount.
        engine.__dict__[QI_ACTIVATION] = int(stored[0].data["stored_cp"] if stored else actor.proficiency_bonus)
        if stored:
            engine._remove_condition(actor, stored[0].condition_id, stored[0].source_definition_id)
    elemental_crafting_choices(engine, actor, action)
    return None


@hook("technique_used")
def used_clean_up(ctx: Any) -> None:
    """Drop the activation-local Remote Activation and Elemental Talisman records once the action has resolved."""
    ctx.engine.__dict__.pop(REMOTE_TALISMAN, None)
    ctx.engine.__dict__.pop(CRAFTED_ELEMENT, None)


def _stored_talismans(actor: Any) -> list[Any]:
    return sorted((row for row in actor.conditions.values()
                   if row.condition_id == QI_STORAGE or row.condition_id.startswith(QI_STORAGE + ":")),
                  key=lambda row: row.applied_sequence)


@hook("prefight_setup_choices")
def qi_storage_setup_choice(bundle: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Offer one stored-CP range per prepared charge, only to owners of the formula."""
    formula_id = TALENT + "qi_storage_talisman"
    if not any(str(row.get("source_definition_id") or "").endswith(formula_id)
               for row in bundle.get("action_catalog") or []):
        return None
    resources = (bundle.get("actor_template") or {}).get("resources") or []
    prepared = next((int(row.get("maximum") or row.get("initial") or 0)
                     for row in resources if row.get("resource_id") == PREPARED), 0)
    pb = int((bundle.get("actor_template") or {}).get("proficiency_bonus") or 2)
    return [{"id": "qi_storage_charges", "label": "CP stored in each prepared Qi Storage Talisman",
             "help": "Cultivation Points (CP) you stored when you crafted each Qi Storage Talisman (up to your Proficiency Bonus). "
                     "This records earlier crafting; it does not spend your starting CP. Using one takes a Bonus Action and consumes it, "
                     "restoring that much CP to its holder, up to their normal maximum.",
             "kind": "integer_range_list", "count": prepared, "item_label": "Talisman",
             "minimum": 0, "maximum": pb, "unit": "CP", "default": [pb] * prepared}]


@hook("match_start")
def seed_qi_storage(engine: Any) -> None:
    """Create prepared Qi Storage charges from sealed pre-fight choices; unrelated fighters are untouched."""
    bundles = {bundle.get("actor_id"): bundle for bundle in (getattr(engine, "typed_bundle_documents", ()) or ())}
    for actor_id, bundle in bundles.items():
        actor = engine.state.actors.get(actor_id)
        if actor is None or not any(str(action.source_definition_id).endswith(TALENT + "qi_storage_talisman")
                                    and action.owner_id == actor_id for action in engine.action_catalog.values()):
            continue
        prefight = bundle.get("prefight") or {}
        prepared = int(actor.resource_maximums.get(PREPARED, actor.resources.get(PREPARED, 0)))
        charges = (prefight.get("setup_choices") or {}).get("qi_storage_charges")
        if charges is None:
            # Bundles created by the preceding fix-up recorded this legacy field directly.
            charges = prefight.get("qi_storage_charges")
        if not isinstance(charges, list):
            continue  # Older saved fights have no crafting record; activation retains its PB fallback.
        for slot, amount in enumerate(charges[:prepared], start=1):
            amount = max(0, min(int(actor.proficiency_bonus or 2), int(amount)))
            engine._apply_condition(actor, f"{QI_STORAGE}:prepared:{slot}", TALENT + "qi_storage_talisman", actor_id,
                expires_on="UNTIL_REMOVED", data={"stored_cp": amount, "label": f"Qi Storage Talisman: {amount} CP stored"})


@effect("qi_storage_restore")
def qi_storage_restore(ctx: Any, eff: dict[str, Any]) -> None:
    """"A creature holding the talisman may activate it to regain CP equal to the amount stored, up to its
    normal maximum."  CP is the holder's own Path pool, so it is resolved from the holder (see
    ``combat/ext/cp_pools.py``); a holder with no Path pool has nothing to restore and is told so."""
    from . import cp_pools, note
    from ..resource_labels import resource_name

    amount = int(ctx.engine.__dict__.pop(QI_ACTIVATION, ctx.actor.proficiency_bonus))
    recorded = (ctx.action.parameters or {}).get("qi_storage_resource")
    resource = cp_pools.restore_pool(ctx.actor, recorded)
    if resource is None:
        note(ctx.engine, ctx.source, ctx.actor,
             f"{ctx.actor.display_name} has no Cultivation Points (CP) pool, so the Qi Storage Talisman "
             f"stored in it ({amount} CP) cannot be restored.")
        return
    before = int(ctx.actor.resources.get(resource, 0))
    ctx.engine._gain_resource(ctx.actor, resource, amount, ctx.source)
    actual = int(ctx.actor.resources.get(resource, 0)) - before
    # The Qi sentence is kept verbatim so fights already played against a Qi fighter replay unchanged.
    label = "Cultivation Points (CP)" if resource == cp_pools.QI else resource_name(resource)
    note(ctx.engine, ctx.source, ctx.actor,
         f"{ctx.actor.display_name} regains {actual} {label} from a Qi Storage Talisman ({amount} CP stored).")


@hook("row_allowed")
def reaction_allowed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    sealed = _sealed_pools(actor) if actor.conditions else set()
    if sealed and any(str(resource) in sealed and int(amount or 0) > 0 for resource, amount in (cost_parts(cost) for cost in row.get("costs") or [])):
        return False
    name = str(row.get("feature_id") or "").rsplit(".", 1)[-1]
    if name in REACTIONS and PREPARED in actor.resources and not available(actor, name if name in FORMULAS else "talisman_reflection"):
        return False
    return None


@hook("event")
def reaction_spends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "REACTION_WINDOW_OPENED":
        return
    source = str(engine.events[-1].source_definition_id if engine.events else "")  # (the source is not among the hook's kwargs)
    name = source.rsplit(".", 1)[-1]
    if not source.startswith(TALENT) or name not in REACTIONS:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is not None and PREPARED in actor.resources:
        use_up(engine, actor, name, source)


# ------------------------------------------------------------------------------------------------ Emergency Stroke and readying
@effect("talisman_stroke")
def talisman_stroke(ctx: Any, eff: dict[str, Any]) -> None:
    from . import note

    engine, actor = ctx.engine, ctx.actor
    variant = str(eff.get("variant") or "base")
    if variant == "ready":
        engine._gain_resource(actor, PREPARED, 1, ctx.source)
        note(engine, ctx.source, actor, f"{actor.display_name} readies a talisman ({actor.resources.get(PREPARED, 0)} prepared).")
        return
    if variant in ("base", "bonus") and actor.resources.get(STROKES, 0) >= 1:
        engine._spend_resource(actor, STROKES, 1, ctx.source)  # one of the Proficiency Bonus uses this long rest
    engine._gain_resource(actor, EMERGENCY, 1, ctx.source)
    note(engine, ctx.source, actor, f"{actor.display_name} draws a temporary Common talisman (Emergency Stroke).")


@effect("talisman_battle_stroke")
def talisman_battle_stroke(ctx: Any, eff: dict[str, Any]) -> None:
    """Battle Stroke Scripture: "For the duration (1 minute), you may use Emergency Stroke as a Bonus Action instead of an Action"."""
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "condition", "condition": "battle_stroke", "applies_to": "self", "duration": "one_minute",
                       "evidence": eff.get("evidence") or "Battle Stroke Scripture: Emergency Stroke as a Bonus Action for 1 minute"}])


# ------------------------------------------------------------------------------------------------ printed bundles of talismans
# Talisman Wall ("Cost: 1 CP per talisman used") and Talisman Bomb ("Cost: 6 CP plus consumed talismans") both spend a
# bundle of the fighter's prepared talismans.  bundle_talismans is the one owner of that question and payment, so the two
# printed lines cannot drift apart.  (The Talisman Array printed a third bundle; its placement is the table's, see the
# module docstring.)
WALL_PARKED = "_talisman_wall_count"
BOMB_BUNDLE = "_talisman_bomb_count"


def bundle_talismans(engine: Any, actor: Any, action: Any, feature: str, *, cp_each: int = 0, cap: int | None = None,
                     extra: Any = None) -> int:
    """Ask how many prepared talismans go into a printed bundle, then spend them.  Returns how many were spent.

    ``cp_each`` is the printed CP per talisman (the Wall's "1 CP per talisman used"); the Bomb pays its flat 6 CP as the
    action's own typed cost.  ``cap`` is the printed maximum ("up to your Proficiency Bonus"), or None for "as many as the
    fighter has prepared and can pay for".  ``extra`` labels each option with what that many talismans buy.  Returns 0 when
    the bundle cannot be paid at all, and the caller stops the action.
    """
    from . import cp_pools, note
    from .needle import CHOICE, ask, checkpoint_id

    if PREPARED not in actor.resources:
        return 0
    short = feature.rsplit(".", 1)[-1]
    name = str(action.display_name)
    # pool is None when the fighter has no Path pool at all: nothing to pay with.
    pool = cp_pools.of(actor, at_least=1)
    cp = int(actor.resources.get(pool, 0)) if pool else 0
    most = int(actor.resources.get(PREPARED, 0))
    from .talisman_preparation import library_available

    most += int(library_available(actor, short))
    if cap is not None:
        most = min(most, int(cap))
    if cp_each:
        most = min(most, cp // int(cp_each))
    if most < 1:
        note(engine, action.source_definition_id, actor,
             f"{actor.display_name} has no prepared talisman left to go into {name}.")
        return 0
    if cp_each and cp < int(cp_each):
        note(engine, action.source_definition_id, actor,
             f"{name} costs {cp_each} CP (your Path's resource) for each talisman, which {actor.display_name} cannot pay.")
        return 0
    options = [str(n) for n in range(most, 0, -1)]
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, short.upper(), actor.entity_id), actor,
                 CHOICE + short, options,
                 labels={n: f"{name}: {n} talisman{'s' if n != '1' else ''}" + (extra(int(n)) if extra else "") for n in options},
                 preferred=[options[0]],
                 prompt=f"{name}: how many prepared talismans does {actor.display_name} spend?"
                        + (f" Each costs {cp_each} CP (your Path's resource)." if cp_each else ""),
                 name=name, feature_id=feature, target_id=actor.entity_id)
    requested = int(picked[0]) if picked else most
    # Prepared talismans only: temporary Emergency Stroke talismans are reserved for Common formulas, as in use_up().
    count = sum(use_up(engine, actor, short, action.source_definition_id) for _ in range(requested))
    if cp_each and count:
        engine._spend_resource(actor, pool, count * int(cp_each), action.source_definition_id)
    return count


@hook("technique_start")
def wall_talismans(engine: Any, actor: Any, action: Any) -> bool | None:
    """Talisman Wall: "Cost: 1 CP per talisman used ... For each talisman consumed, the wall gains 10 hit points"."""
    if not str(action.source_definition_id).endswith(TALENT + "talisman_wall"):
        return None
    count = bundle_talismans(engine, actor, action, TALENT + "talisman_wall", cp_each=1,
                             extra=lambda n: f" ({n} CP, {10 * n} hit points)")
    if count < 1:
        return True
    engine.__dict__[WALL_PARKED] = count
    return None


@hook("technique_used")
def wall_hit_points(ctx: Any) -> None:
    count = ctx.engine.__dict__.pop(WALL_PARKED, None)
    if not count or not str(ctx.source).endswith(TALENT + "talisman_wall"):
        return
    from .. import zones as Z

    for zone in Z.typed_zones(ctx.engine):
        if zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source and zone.trigger_profile.get("wall"):
            profile = {**zone.trigger_profile, "numbers": {**(zone.trigger_profile.get("numbers") or {}), "talismans": int(count)}}
            zone.trigger_profile = profile
            ctx.engine._append_event("ZONE_CREATED", ctx.source, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
            ctx.rider(f"Talisman Wall: {count} talisman{'s' if count != 1 else ''} consumed; the wall has {10 * int(count)} hit points and AC 15.")


# ------------------------------------------------------------------------------------------------ Talisman Bomb
# "Cost: 6 CP plus consumed talismans": the flat CP is the action's own typed cost, so the compiler prices the button and
# the engine takes the payment; bundle_talismans spends the printed talismans.  The printed mode lines (Focused Bomb /
# Layered Bomb) stay riders: choosing which formula a bomb resolves is the table's call, and no option promises an
# improvement the engine does not make.
BOMB = "talisman_bomb"


def _printed_bundle(action: Any, short: str) -> bool:
    """True for the printed ability named ``short``, under either spelling of its id."""
    source = str(getattr(action, "source_definition_id", "") or "")
    return source.endswith(TALENT + short) or source.endswith(f".talisman.{short}")


@hook("technique_start")
def bomb_talismans(engine: Any, actor: Any, action: Any) -> bool | None:
    """"Bundle up to your Proficiency Bonus compatible talismans ... All talismans in the bomb are consumed."
    (Talisman Bomb)"""
    if not _printed_bundle(action, BOMB) or PREPARED not in actor.resources:
        return None
    count = bundle_talismans(engine, actor, action, TALENT + BOMB, cap=actor.proficiency_bonus,
                             extra=lambda n: " in the bomb")
    if count < 1:
        return True
    engine.__dict__[BOMB_BUNDLE] = count
    from . import note

    note(engine, action.source_definition_id, actor,
         f"{actor.display_name}'s Talisman Bomb bundles {count} talisman{'s' if count != 1 else ''}; all of them are consumed.")
    return None


# ------------------------------------------------------------------------------------------------ Dao-Sealing Talisman (Secret Formula)
@effect("talisman_dao_seal")
def talisman_dao_seal(ctx: Any, eff: dict[str, Any]) -> None:
    """"Failed Save: Choose Body Refining, Qi Cultivation, or Spirit Awakening. For 1 minute, the target cannot spend that Path's resource ...
    Successful Save: The target cannot spend CP until the start of your next turn."  ``mode``: "path" (the failed save; the user picks the
    Path among the target's pools, the AI its fullest) or "cp" (every Path pool)."""
    from . import cp_pools
    from .needle import CHOICE, ask, checkpoint_id

    engine = ctx.engine
    target = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if target is None:
        return
    pools = list(cp_pools.all_of(target))
    if not pools:
        return
    if eff.get("mode") == "path":
        names = {cp_pools.QI: "Qi Cultivation (Qi)", cp_pools.STAMINA: "Body Refining (Stamina)",
                 cp_pools.RESONANCE: "Spirit Awakening (Resonance)"}
        best = max(pools, key=lambda pool: int(target.resources.get(pool, 0)))
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "DAO_SEAL", ctx.actor.entity_id, target.entity_id), ctx.actor, CHOICE + "dao_seal",
                     pools, labels={pool: f"Dao-Sealing Talisman: seal {names[pool]}" for pool in pools}, preferred=[best],
                     prompt=f"Which Path does the Dao-Sealing Talisman seal in {target.display_name}?", target_id=target.entity_id)
        sealed = [picked[0] if picked else best]
        engine._apply_condition(target, SEALED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"pools": sealed, "dao_repeat": True})
        target.turn_flags[f"dao_seal_round_ends:{ctx.actor.entity_id}"] = int(engine.state.round_number) + 10
        ctx.rider(f"Dao-Sealing Talisman: {target.display_name} cannot spend {names[sealed[0]].split(' (')[1].rstrip(')')} for 1 minute (Charisma save at the end of each of its turns ends it).")
        return
    engine._apply_condition(target, SEALED, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"pools": pools})
    ctx.rider(f"Dao-Sealing Talisman: {target.display_name} cannot spend CP until the start of your next turn.")


@hook("turn_end")
def dao_seal_repeat_save(engine: Any, actor: Any) -> None:
    for iid, row in list(actor.conditions.items()):
        if row.condition_id != SEALED or not (row.data or {}).get("dao_repeat"):
            continue
        ends = actor.turn_flags.get(f"dao_seal_round_ends:{row.source_actor_id}")
        source = engine.state.actors.get(row.source_actor_id or "")
        dc = _save_dc(engine, source)
        done = ends is not None and int(engine.state.round_number) >= int(ends)
        if not done:
            roll = engine._roll_save(actor, "CHA", dc, row.source_definition_id)
            done = roll is not None and int(roll.total) >= dc
        if done:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", row.source_definition_id, actor_id=row.source_actor_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": SEALED, "instance_id": iid})


def _save_dc(engine: Any, source: Any) -> int:
    if source is None:
        return 10
    for action in engine.action_catalog.values():
        if action.owner_id == source.entity_id and str(action.source_definition_id).endswith(TALENT + "secret_formula"):
            return int((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 10)
    return 10


# ------------------------------------------------------------------------------------------------ Featherfall Talisman
FEATHERFALL_TALENT = TALENT + "featherfall_talisman"
# Qi Cultivation's own Featherfall (combat/ext/altitude_abilities.py) already records a safe descent; a
# creature that has one must not pay a second talisman for the same fall.
from .altitude_abilities import FEATHER_CONDITION as QI_FEATHERFALL  # noqa: E402  (both spellings of one printed effect)

BLOCK = "talismans"


@hook("compile_block")
def compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The Featherfall Talisman formula's reaction row (combat/rules/feature_blocks.d), read by ``falling`` below."""
    if block == BLOCK:
        return [{**row, "kind": spec["kind"], "numbers": dict(numbers)}]
    return None


def _reaction_row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return next((row for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == kind), None)


def _descending(actor: Any) -> bool:
    return any(row.condition_id in (FEATHERFALL_CONDITION, QI_FEATHERFALL) for row in actor.conditions.values())


@hook("falling")
def featherfall_talisman(engine: Any, actors: list[Any], intent: Any) -> None:
    """"Reaction, triggered when the bearer or a creature within 30 feet begins falling ... descends safely
    and takes no falling damage from the triggering fall" (Featherfall Talisman, "Consumed: yes").

    One talisman protects one falling creature within 30 feet, exactly as Qi Cultivation's Featherfall
    asks and pays through the native falling checkpoint (combat/falling.py); the safe descent itself is
    recorded in the same recorded protection data.
    """
    from ..falling import required  # the native check for a creature that is actually falling
    from ..typed_executor import clock_expiry
    from ..typed_reactions import can_use_reaction, open_reaction
    from . import note
    from .needle import ask, checkpoint_id

    for owner in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        row = _reaction_row(engine, owner, "featherfall")
        if row is None or not available(owner, "featherfall_talisman") or not can_use_reaction(engine, owner, None, row):
            continue
        options = [other.entity_id for other in actors
                   if not _descending(other) and required(engine, other)
                   and engine._distance_actor_to_actor(owner, other) <= 30]
        if not options:
            continue
        checkpoint = checkpoint_id(engine, "talisman_featherfall", owner.entity_id)
        friendly = [key for key in options if engine.state.actors[key].team_id == owner.team_id][:1]
        chosen = ask(engine, intent, checkpoint, owner, "choice:needle.talisman_featherfall", options,
                     labels={key: engine.state.actors[key].display_name for key in options},
                     prompt="Featherfall Talisman: which falling creature do you protect? One talisman is used up.",
                     preferred=friendly, allow_decline=True, default="decline" if not friendly else "first",
                     name="Featherfall Talisman", feature_id=FEATHERFALL_TALENT)
        if not chosen:
            continue
        with activation(engine, owner, FEATHERFALL_TALENT):
            if not use_up(engine, owner, "featherfall_talisman", FEATHERFALL_TALENT):
                note(engine, FEATHERFALL_TALENT, owner, f"{owner.display_name} has no talisman left to spend on Featherfall.")
                continue
            open_reaction(engine, row, owner, tuple(chosen), checkpoint)
            for key in chosen:
                target = engine.state.actors[key]
                engine._apply_condition(target, FEATHERFALL_CONDITION, FEATHERFALL_TALENT, owner.entity_id,
                                        expires_on=clock_expiry(engine, "minutes", 1),
                                        data={"fall_speed_ft": 30, "fall_damage_immune": 1, "fall_lands_upright": 1})
            engine._append_event("REACTION_RESOLVED", FEATHERFALL_TALENT, actor_id=owner.entity_id, target_ids=tuple(chosen),
                                 payload={"log": f"{owner.display_name} uses a Featherfall Talisman: "
                                                  f"{', '.join(engine.state.actors[key].display_name for key in chosen)} descend safely "
                                                  f"and take no falling damage for 1 minute."})


# ------------------------------------------------------------------------------------------------ Talisman Recall
# "Choose one talisman you crafted and can perceive, or whose resonance you can clearly sense."  A talisman is not an
# object on this table, so a talisman that is out in the world exists only because the fighter's fight setup declared one
# (the same "records earlier crafting" pattern as the Qi Storage charges): recall_talismans_outside is one integer, and
# with none declared the printed ability has nothing to recall and stays off the menu.
RECALL_TALENT = TALENT + "talisman_recall"
IN_THE_WORLD = "condition:typed.talisman_recall"      # data: {"outside": int}
WORLD_CHOICE = "talismans_out_in_the_world"
RECALL_REACH = 120                                     # the printed "Range: 120 feet"


def _outside(actor: Any) -> int:
    """How many of this fighter's crafted talismans are out in the world, as their fight setup declared."""
    for row in actor.conditions.values():
        if row.condition_id == IN_THE_WORLD:
            return max(0, int((row.data or {}).get("outside") or 0))
    return 0


def _set_outside(engine: Any, actor: Any, count: int) -> None:
    for row in [row for row in actor.conditions.values() if row.condition_id == IN_THE_WORLD]:
        engine._remove_condition(actor, row.condition_id, row.source_definition_id)
    if count > 0:
        engine._apply_condition(actor, IN_THE_WORLD, RECALL_TALENT, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"outside": int(count),
                                      "label": f"Talisman Recall: {count} talisman of yours out in the world"})


@hook("prefight_setup_choices")
def recall_setup_choice(bundle: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Ask how many crafted talismans the fighter has out in the world, so Recall has a talisman to recall."""
    if not any(str(row.get("source_definition_id") or "").endswith(RECALL_TALENT)
               for row in bundle.get("action_catalog") or []):
        return None
    resources = (bundle.get("actor_template") or {}).get("resources") or []
    prepared = next((int(row.get("maximum") or row.get("initial") or 0)
                     for row in resources if row.get("resource_id") == PREPARED), 0)
    return [{"id": WORLD_CHOICE, "label": "Your crafted talismans that are out in the world",
             "help": "How many of the talismans you crafted are out in the world right now, rather than in your hand: "
                     "stuck to a door, carried by an ally, dropped on the ground. Talisman Recall brings one of them "
                     "back to you, and can only bring back what you say is out there. This is your own note for the "
                     "fight: it costs you nothing and does not change how many talismans you are carrying.",
             "kind": "integer_range_list", "count": 1, "item_label": "Talismans",
             "minimum": 0, "maximum": max(1, prepared), "unit": "Talismans", "default": [0]}]


@hook("match_start")
def seed_recall_world(engine: Any) -> None:
    """Record the talismans the fighter's fight setup declared; fighters with no record own none out there."""
    bundles = {bundle.get("actor_id"): bundle for bundle in (getattr(engine, "typed_bundle_documents", ()) or ())}
    for actor_id, bundle in bundles.items():
        actor = engine.state.actors.get(actor_id)
        if actor is None or not any(action.owner_id == actor_id and str(action.source_definition_id).endswith(RECALL_TALENT)
                                    for action in engine.action_catalog.values()):
            continue
        sealed = dict(bundle.get("prefight") or {})
        declared = (sealed.get("setup_choices") or {}).get(WORLD_CHOICE)
        values = list(declared) if isinstance(declared, list) else []
        _set_outside(engine, actor, int(values[0]) if values and str(values[0]).lstrip("-").isdigit() else 0)


@hook("candidate_allowed")
def recall_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Recall needs a talisman that really is out there.

    It does not need room in hand: "it flies to your hand or a legal space within your reach" brings the talisman
    back, and only the printed Prepared Talisman Limit decides how many of the fighter's talismans are ready to use
    (a recalled talisman over the limit waits in the hand for the printed "Ready a talisman", one Action).
    """
    if action is None or not str(action.source_definition_id).endswith(RECALL_TALENT) or actor.conditions is None:
        return None
    return False if _outside(actor) < 1 else None


@effect("talisman_recall")
def talisman_recall(ctx: Any, eff: dict[str, Any]) -> None:
    """"Choose one talisman you crafted and can perceive ... If unattended, it flies to your hand or a legal space
    within your reach. If held or worn by another creature, that creature makes a Strength saving throw. On a
    failed save, the talisman returns to you. On a success, it remains where it is."

    The talisman has to exist: it is one of the talismans the fighter's fight setup declared out in the world, and each
    recall takes one of them back out of the world.  Its holder is the creature the fighter names -- any creature within
    the printed 120 feet, hostile or allied, not "the first enemy on the field" -- and that creature alone answers the
    printed Strength saving throw.  Bringing it back is not readying it: the talisman becomes one of the prepared ones
    only while the fighter's room under the printed Prepared Talisman Limit allows it, and never past that limit.
    """
    from . import note
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    if PREPARED not in actor.resources:
        return
    if _outside(actor) < 1:
        note(engine, ctx.source, actor, f"{actor.display_name} has no talisman out in the world to recall.")
        return
    holders = [other.entity_id for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
               if other.active and other.entity_id != actor.entity_id
               and engine._distance_actor_to_actor(actor, other) <= RECALL_REACH]
    unattended = ""
    options = [unattended, *holders]
    labels = {unattended: "It is lying unattended: it flies to your hand"}
    labels.update({key: f"{engine.state.actors[key].display_name} is holding or wearing it: that creature makes a "
                        f"Strength saving throw" for key in holders})
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "talisman_recall", actor.entity_id), actor,
                 CHOICE + "talisman_recall", options, labels=labels, preferred=[unattended],
                 prompt="Talisman Recall: where is the talisman you crafted? Choose yourself if it is lying unattended.",
                 name="Talisman Recall", feature_id=RECALL_TALENT)
    if not picked:
        return
    if picked[0] != unattended:
        holder = engine.state.actors[picked[0]]
        dc = int(ctx.numbers.get("save_dc") or 10)
        roll = engine._roll_save(holder, "STR", dc, ctx.source)
        saved = roll is not None and int(roll.total) >= dc
        note(engine, ctx.source, actor,
             f"{holder.display_name} makes a Strength saving throw to hold the talisman "
             f"({roll.total if roll else 0} against DC {dc}): it "
             f"{'stays where it is' if saved else 'is pulled to your hand'}.")
        if saved:
            return  # "On a success, it remains where it is": the talisman is still out there
    _set_outside(engine, actor, _outside(actor) - 1)
    room = _maximum(engine, actor, PREPARED) - int(actor.resources.get(PREPARED, 0))
    if room > 0:
        engine._gain_resource(actor, PREPARED, 1, ctx.source)
    note(engine, ctx.source, actor,
         f"The talisman flies to {actor.display_name}'s hand and is ready to use again "
         f"({actor.resources.get(PREPARED, 0)} prepared)." if room > 0 else
         f"The talisman flies to {actor.display_name}'s hand, but the Prepared Talisman Limit "
         f"({_maximum(engine, actor, PREPARED)}) is already full, so it is not ready to use: ready it with Ready a "
         f"talisman (one Action), or use one of the {actor.resources.get(PREPARED, 0)} talismans already ready.")


# ------------------------------------------------------------------------------------------------ Read the Script
# The printed list of facts, in its own order: "On a success, learn one: formula family; approximate rank; activation
# method; whether it is cracked, unstable, reusable, or permanent; whether it is connected to a Formation, corpse, spirit,
# door, object, or creature; whether it is safe to touch."  A success reveals exactly one of them, a success by 5 or more
# reveals exactly one more ("an additional fact"), and the fighter names which fact they are reading.
SCRIPT_FACTS = ("its formula family", "its approximate rank", "its activation method",
                "whether it is cracked, unstable, reusable or permanent",
                "whether it is connected to a Formation, corpse, spirit, door, object or creature",
                "whether it is safe to touch")
SCRIPT_SKILLS = ("Arcana", "Investigation", "Calligrapher's Supplies")
# The print sets no Difficulty Class, so the fighter names how hard the writing is to read.
SCRIPT_DIFFICULTY = {"clear and deliberate": 10, "worn or smudged": 10, "hidden, damaged or foreign": 15,
                     "sealed or warded": 20}


def _printed_check_modes(ctx: Any) -> set[str]:
    """Advantage or Disadvantage printed on this very action and naming a check (Seal Breaker's Eye, Talisman Scribe).

    A talent that grants Advantage on someone else's check is delivered by the compiler as a row on that
    ability's own action, so the row is read here rather than searched for by ability id.

    Talisman Scribe's row is the one that needs a second step: it prints Advantage only on a formula "you
    personally know", which no sheet records, so its rows are held back here and released by
    ``combat/ext/talisman_scribe.py`` once the fighter answers that printed question. Every other printed row
    is still unconditional, exactly as before.
    """
    from . import talisman_scribe

    modes = set()
    for row in ctx.typed.get("effects") or []:
        if row.get("type") not in ("advantage", "disadvantage"):
            continue
        if not re.search(r"check", f"{row.get('on') or ''} {row.get('evidence') or ''}", re.I):
            continue
        if row.get("source_modifier") == talisman_scribe.SCRIBE:
            continue  # the printed knowledge boundary decides this one, below
        modes.add(str(row["type"]).upper())
    if talisman_scribe.applies(ctx):
        modes.add("ADVANTAGE")
    return modes


def _script_fact(engine: Any, intent: Any, actor: Any, taken: list[str], skill: str) -> str | None:
    """Which printed fact the fighter is reading, from the ones a previous reading has not settled."""
    from .needle import CHOICE, ask, checkpoint_id

    options = [fact for fact in SCRIPT_FACTS if fact not in taken]
    if not options:
        return None
    labels = {fact: f"Read the Script: read {fact}" for fact in options}
    picked = ask(engine, intent, checkpoint_id(engine, "read_script_fact", actor.entity_id, len(taken)), actor,
                 CHOICE + "read_script_fact", options, labels=labels, preferred=options[:1],
                 prompt=f"Read the Script: which fact of this writing are you reading with {skill}?",
                 name="Read the Script", target_id=actor.entity_id)
    return picked[0] if picked else None


@effect("read_the_script")
def read_the_script(ctx: Any, eff: dict[str, Any]) -> None:
    """"Make an Intelligence check using Arcana, Investigation, Calligrapher's Supplies, or another relevant
    proficiency. On a success, learn one: formula family; approximate rank; activation method; whether it is
    cracked, unstable, reusable, or permanent; whether it is connected to a Formation, corpse, spirit, door,
    object, or creature; whether it is safe to touch. Success by 5 or more reveals an additional fact."

    The check is real and Advantage/Disadvantage from the four talents that print it applies. The print
    gives no Difficulty Class and no skill list to close, so the fighter picks the proficiency and how hard
    the writing is to read. On a success exactly one fact is revealed, two when the check beats the DC by 5;
    the fighter names each one, and what the inspected writing actually says is the table's call, so the
    content rides a GM rider instead of an invented value.
    """
    from ..ability_checks import ability_modifier
    from ..typed_executor import check_modes
    from . import note, run
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    skill = ask(engine, ctx.intent, checkpoint_id(engine, "read_script_skill", actor.entity_id), actor,
                CHOICE + "read_script_skill", list(SCRIPT_SKILLS),
                labels={name: f"Read the Script: use {name}" for name in SCRIPT_SKILLS}, preferred=["Arcana"],
                prompt="Read the Script: which proficiency do you use to read this writing?", name="Read the Script")
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "read_script_dc", actor.entity_id), actor,
                 CHOICE + "read_script_dc", list(SCRIPT_DIFFICULTY),
                 labels={name: f"Read the Script: the writing is {name} (DC {SCRIPT_DIFFICULTY[name]})"
                         for name in SCRIPT_DIFFICULTY},
                 preferred=["worn or smudged"],
                 prompt="Read the Script: how hard is this writing to read? The printed rules set no Difficulty Class.",
                 name="Read the Script")
    if not skill or not chosen:
        return
    dc = SCRIPT_DIFFICULTY[chosen[0]]
    ability = ability_modifier(actor, "INT")
    from .tabik_scoundrel import skill as skill_bonus  # the fighter's real proficiency in the skill they name

    bonus = ability + skill_bonus(engine, actor, skill[0], 0)
    modes = check_modes(actor, "INT", skill[0], engine=engine)
    modes.update(m for m in run("skill_check_mode", ctx, actor, "INT", skill[0]) if m in ("ADVANTAGE", "DISADVANTAGE"))
    modes.update(_printed_check_modes(ctx))
    from .talisman_preparation import library_read_mode

    modes.update(library_read_mode(ctx))
    mode = next(iter(modes)) if len(modes) == 1 else "NORMAL"
    roll = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:{skill[0]}", mode=mode)
    engine._record_roll(roll)
    from . import floored  # Complete Mandala Auspice (combat/ext/d20_floor.py)

    roll = floored(engine, actor, roll, dc)
    margin = int(roll.total) - dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": margin >= 0, "skill": skill[0]})
    if margin < 0:
        note(engine, ctx.source, actor,
             f"{actor.display_name} reads the script with {skill[0]} ({roll.total} against DC {dc}) and learns nothing.")
        return
    # "learn one ... Success by 5 or more reveals an additional fact": one fact, or exactly two.
    learned = [_script_fact(engine, ctx.intent, actor, [], skill[0])]
    if margin >= 5:
        learned.append(_script_fact(engine, ctx.intent, actor, [fact for fact in learned if fact], skill[0]))
    facts = [fact for fact in learned if fact]
    if not facts:
        return
    note(engine, ctx.source, actor,
         f"{actor.display_name} reads the script with {skill[0]} ({roll.total} against DC {dc}) and learns "
         f"{'one fact' if len(facts) == 1 else 'two facts'}: {'; '.join(facts)}.")
    ctx.rider("Read the Script: what this writing shows about "
              + (" and ".join(facts) if len(facts) > 1 else facts[0])
              + " is the table's to state. Secret formulae, hidden command words and full schematics stay hidden.")


# ------------------------------------------------------------------------------------------------ Living Scripture Servitor
@hook("compile_action")
def compile_servitor_lifetime(action: Any, info: dict[str, Any]) -> Any | None:
    """"duration becomes 10 minutes" (Living Scripture Servitor) for the Talisman Spirit its owner already has."""
    if "living_scripture_servitor" not in _owned(info.get("owned_ids")):
        return None
    if not str(getattr(action, "source_definition_id", "")).endswith(TALENT + "talisman_spirit"):
        return None
    typed = dict((action.parameters or {}).get("typed") or {})
    if str((typed.get("duration") or {}).get("kind")) != "minutes":
        return None
    parameters = {**(action.parameters or {}), "typed": {**typed, "duration": {"kind": "minutes", "amount": 10}}}
    return action.model_copy(update={"parameters": parameters})
