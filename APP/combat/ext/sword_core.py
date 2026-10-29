"""Sword sphere core mechanics (lane OCF8, owner 2026-10-04: "we are still lacking automation on various attacks.

Sword Beyond Hand looks to be not automated"; the fight log showed four GM reminders on every use; review fixes OCF8f1).

Rules text (owner's Sphere Compendium, authority/typed_mechanics/rules_text.json):

  SWORD_BASE_SWORD_TRAINING    "When you learn Sword: gain proficiency with shortswords, longswords, and
                               greatswords; if already proficient with all three, gain +2 to attack rolls made
                               with approved Sword weapons. This bonus does not stack with another Sword-sphere
                               feature granting the same benefit."
  TAL_SWORD_IRON_SWORD_BODY    "While wielding a Sword: use Constitution for Sword attack and damage rolls if
                               higher; use Constitution as your Sword key ability; spend Stamina instead of CP on
                               Sword talents; gain +1 AC; gain Advantage on saving throws against forced Disarm
                               effects."
  TAL_SWORD_LIFE_SEVERING_SWORD "Trigger: You deal Sword damage to a creature. Cost: 2 CP or 2 Stamina. Use Limit:
                               Once per turn. Until the start of your next turn: reduce healing received by the
                               target by your Proficiency Bonus; the target cannot gain Temporary HP. If the target
                               bears your Sword Intent, choose one additional effect: halve healing received
                               instead; impose Disadvantage on its next Concentration saving throw; prevent ordinary
                               regeneration until the start of your next turn."

Owned rows (combat/rules/feature_blocks.d/sword.json, block "sword", one ``kind`` each; every hook returns early
for a creature without its row, so other spheres, other characters and fights saved before this change are
unchanged):

  training       Sword Training's "+2 to attack rolls made with approved Sword weapons". Two printed limits, both
                 enforced here. The bonus is scoped to an attack made with an approved Sword weapon (the sword
                 proficiency group in combat/rules/weapon_specials.json, read through the shared ``in_group``
                 helper), never to a weaponless Sword technique; and the printed "if already proficient with all
                 three" is a build fact, so the +2 is paid only when the build affirms it
                 (``already_proficient`` on this feature's data row, off until a character creator records the
                 fighter had proficiency with all three swords BEFORE Sword Training -- nothing in this system
                 records that today). "Does not stack" holds: one row pays +2 once.
  iron_body      Iron Sword Body's standing "+1 AC" while an approved Sword weapon is in hand. sword_sphere owns
                 its Constitution rolls and Stamina-for-CP payment; both modules share sword_attack/wielding_sword
                 so a historical catalog (no Draw/Stow of its own) keeps its original weapon policy.
  life_severing  Life-Severing Sword's "If the target bears your Sword Intent, choose one additional effect" --
                 the only printed clause of the talent with no typed row. ``keeps_compiling``: the talent's own
                 cost, use limit, healing reduction and Temporary HP denial are its compiled modifier on the Sword
                 attacks it changes, and must keep compiling alongside this row. All three clauses last until the
                 START OF ITS USER'S next turn, as printed: the choice replaces this strike's own healing reduction
                 ("halved instead"), gives Disadvantage on the next Concentration save (which that save uses up),
                 and prevents ordinary regeneration (combat/ext/regeneration.py).

Not automated here: Iron Sword Body's "Advantage on saving throws against forced Disarm effects" is not compiled,
because no printed ability on this table makes a Disarm saving throw for anything to defend against (its text stays
on the character sheet).
"""

from __future__ import annotations

from typing import Any

from . import hook
from .integrated_weapons import in_group
from .needle import ask, checkpoint_id

BLOCK = "sword"
SWORD_SPHERE = "tianxia.sphere.sword"
SWORD_INTENT = "Sword Intent"
LIFE_SEVERING = "TAL_SWORD_LIFE_SEVERING_SWORD"
TURN_KEY = "_ocf8_sword_life_severing"
PAID_HIT_KEY = "_ocf8_sword_paid_hit"
SOURCE_TURN = "START_OF_SOURCE_NEXT_TURN"

# The printed "choose one additional effect", in the order the owner's text lists them. Each label says what happens,
# to which creature, and until when (checklist 13); the code names are transport only.
HALVE_HEALING = "halve_healing"
CON_DISADVANTAGE = "con_disadvantage"
NO_REGENERATION = "no_regeneration"
EXTRA_OPTIONS = (
    (HALVE_HEALING, "Halved healing: instead of having its healing reduced by your Proficiency Bonus, this creature "
                    "receives half of any healing, until the start of your next turn."),
    (CON_DISADVANTAGE, "Broken concentration: the next Concentration saving throw this creature has to make is at a "
                       "Disadvantage. If it makes that save after the start of your next turn, it is wasted."),
    (NO_REGENERATION, "No regeneration: this creature cannot regain Hit Points from its own regeneration feature "
                      "(Immortal Regeneration, Marrow Regeneration, Demon Bone Regeneration) until the start of your "
                      "next turn."),
)


# ------------------------------------------------------------------------------------------------------ ownership
@hook("compile_block")
def sword_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """This module's own feature block. ``typed_reactions.compile_blocks`` keys every fight hook off these rows, so
    a creature that does not own the feature never reaches any code below."""
    kind = str(spec.get("kind") or "")
    if block != BLOCK or not kind:
        return None
    return [{**row, "block": BLOCK, "kind": kind, "flat": int(spec.get("flat") or 0),
             "already_proficient": bool(spec.get("already_proficient")),
             "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """The one owned row of this kind, or None."""
    for row in (getattr(engine, "typed_passive_rows", None) or {}).get(actor.entity_id, ()):
        if row.get("block") == BLOCK and row.get("kind") == kind:
            return row
    return None


def _approved_sword(ctx: Any) -> bool:
    """Whether the weapon this attack is made with is an approved Sword weapon (the sword proficiency group Sword
    Training grants in combat/rules/weapon_specials.json, read through the shared ``in_group`` helper)."""
    from .weapon_hits import weapon_identity

    try:
        identity = weapon_identity(ctx)
    except Exception:  # noqa: BLE001 - an unusual catalog must never break a roll
        return False
    action = (getattr(ctx.engine, "action_catalog", None) or {}).get(identity)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return in_group(typed, "sword") or in_group(ctx.typed, "sword")


def _sword_weapon_attack(ctx: Any) -> bool:
    """Whether this attack is made with an approved Sword weapon. This is the printed scope of Sword Training's
    "+2 to attack rolls made with approved Sword weapons": a Dao in the same hands earns none, and neither does
    Sword Beyond Hand's wave of Sword Qi, which carries no weapon."""
    return bool(ctx.typed.get("weapon")) and _approved_sword(ctx)


def sword_attack(ctx: Any) -> bool:
    """Whether this attack is a Sword attack (Iron Sword Body's "Sword attack and damage rolls if higher"). Wider
    than the training bonus: a Sword sphere technique that carries no weapon is a Sword attack of its own right.
    Shared with sword_sphere's Iron Sword Body roll and payment integration."""
    if ctx.typed.get("weapon"):
        return _approved_sword(ctx)
    return str(ctx.typed.get("sphere") or "") == SWORD_SPHERE


def wielding_sword(engine: Any, actor: Any) -> bool:
    """Whether an approved Sword weapon is in the creature's hands right now ("While wielding a Sword").

    Read through the shared readied-grip query, so a sword that is stowed grants nothing while a spare in the
    pack does not. A catalog compiled before Draw/Stow grips existed has no grip actions and keeps its original
    weapon policy: there, possession is the only record of what is in hand.
    Shared with sword_sphere so AC, rolls and payment use the same readiness rule."""
    from .hand_occupancy import supports_grips, weapon_grips

    if supports_grips(engine, actor):
        return any(identity in engine.action_catalog and in_group((engine.action_catalog[identity].parameters or {}).get("typed") or {}, "sword")
                   for identity in weapon_grips(engine, actor))
    from .weapon_hits import available_weapons

    return any(in_group(((action.parameters or {}).get("typed") or {}), "sword")
               for action in available_weapons(engine, actor).values())


# ------------------------------------------------------------------------------------- Sword Training / Iron Sword Body
@hook("attack_bonus")
def sword_roll_bonus(ctx: Any, actor: Any) -> int | None:
    """Sword Training's "+2 to attack rolls made with approved Sword weapons", paid only when the build affirms the
    printed "if already proficient with all three". Iron Sword Body's rolls are owned by sword_sphere,
    including its historical compiled Constitution variants; never pay that bonus twice."""
    training = _row(ctx.engine, actor, "training")
    if not training:
        return None
    bonus = 0
    if training and training.get("already_proficient") and _sword_weapon_attack(ctx):
        bonus += int(training.get("flat") or 0)
    return bonus or None


@hook("ac")
def iron_sword_body_ac(engine: Any, actor: Any) -> int | None:
    """Iron Sword Body's standing "+1 AC" while a Sword is in hand. The printed row is an always-on passive, so it is
    answered on the Armor Class itself rather than on one action's roll."""
    if not _row(engine, actor, "iron_body") or not wielding_sword(engine, actor):
        return None
    return 1


# --------------------------------------------------------------------------------------------------- Life-Severing Sword
@hook("after_hit_choice")
def life_severing_opportunity_hit(ctx: Any, target: Any, kind: str, *, confirmed=False) -> None:
    """Offer the owned paid rider on an approved Sword Opportunity Attack.

    The generic core-weapon compiler does not capture Sword's any-attack rider.
    Reuse its already compiled Sword loadout, including effects and payment
    alternatives, rather than inventing another version of the talent. Catalogs
    that already captured this choice keep the shared paid-hit owner's route.
    """
    if (confirmed or kind != "weapon" or not ctx.typed.get("reaction_attack")
            or not _row(ctx.engine, ctx.actor, "life_severing") or not _approved_sword(ctx)):
        return
    if any(choice.get("id") == LIFE_SEVERING for choice in ctx.typed.get("paid_hit_choices") or []):
        return
    if ctx.attack_damage_context is not None:
        target = ctx.engine.state.actors[ctx.attack_damage_context.target_id]
    if not target.active:
        return
    current = ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    turn = f"{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    if ctx.actor.turn_flags.get(TURN_KEY) == turn:
        return
    group = next((group for action in ctx.engine.action_catalog.values() if action.owner_id == ctx.actor.entity_id
                  for group in (action.parameters.get("typed") or {}).get("attack_modifier_loadout") or []
                  if group.get("id") == LIFE_SEVERING), None)
    if group is None:
        return  # older saved catalogs without paid metadata remain unchanged
    from .attack_modifiers import effect_can_apply

    hit_ctx = ctx.on_hit_context(target)
    options = {}
    for option in group["options"]:
        if not any(effect_can_apply(hit_ctx, effect) for effect in option["effects"]):
            continue  # An unmarked earlier hit can exhaust the compiled use gate.
        for index, payment in enumerate(option["payments"]):
            if all(ctx.actor.resources.get(resource, 0) >= amount for resource, amount in payment):
                key = f"{option['id']}:{index}"
                price = ", ".join(f"{amount} {'Stamina' if resource.endswith('stamina') else 'Cultivation Points (CP)'}"
                                  for resource, amount in payment)
                options[key] = (payment, option["effects"],
                                f"Life-Severing Sword: pay {price} for this Opportunity Attack against {target.display_name}. "
                                "Reduce its healing by your Proficiency Bonus and prevent temporary hit points until "
                                "the start of your next turn; if it carries your Sword Intent, choose an extra effect.")
    if not options:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sword_opportunity_paid", target.entity_id),
                 ctx.actor, "choice:needle.sword_opportunity_paid", list(options),
                 labels={key: value[2] for key, value in options.items()}, allow_decline=True,
                 target_id=target.entity_id, name="Life-Severing Sword", feature_id=LIFE_SEVERING,
                 prompt=f"Life-Severing Sword: your Opportunity Attack hit {target.display_name}. "
                        "Pay for this hit, or decline to keep the ordinary hit.")
    if picked and picked[0] in options:
        from .paid_hit import apply_paid_effects

        payment, effects, _ = options[picked[0]]
        if any(effect_can_apply(ctx.on_hit_context(target), effect) for effect in effects):
            apply_paid_effects(ctx, target, LIFE_SEVERING, payment, effects)


@hook("paid_hit_applied")
def remember_life_severing_hit(ctx: Any, target: Any, source: str) -> None:
    """Remember an actually paid persistent activation until this attack completes.

    The shared paid-hit seam also serves other loadouts; this owner is inert for
    other riders, non-owners and effects without explicit attack provenance.
    """
    if source != LIFE_SEVERING or not _row(ctx.engine, ctx.actor, "life_severing"):
        return
    attack = ctx.attack_damage_context
    if attack is not None:
        ctx.actor.turn_flags[PAID_HIT_KEY] = f"{attack.roll_id}:{target.entity_id}"


@hook("attack_damage_final")
def life_severing_extra(engine: Any, attacker: Any, target: Any, attack_context: Any, intent: Any) -> None:
    """"If the target bears your Sword Intent, choose one additional effect": the player picks (an AI fighter takes the
    first option), inside the talent's own once-per-turn limit, and the answer is delivered with the engine's own typed
    rows so the durations are ones the engine already removes.

    ``attack_damage_final`` is the documented seam for a rider of a completed attack: it runs after every packet this
    attack attached, so the Sword Intent mark the same hit placed is already on the creature (combat/typed_executor
    runs a typed attack's non-damage on-hit rows after ``after_hit``, so ``after_hit`` cannot see that mark yet).
    The cost must have been paid by the talent's own compiled form or by the shared
    paid-hit executor for this exact roll and target; merely enabling a setting is insufficient."""
    if not _row(engine, attacker, "life_severing"):
        return
    action = (getattr(engine, "action_catalog", None) or {}).get(getattr(attack_context, "source_id", "") or "")
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    paid = attacker.turn_flags.get(PAID_HIT_KEY) == f"{attack_context.roll_id}:{target.entity_id}"
    if paid:
        attacker.turn_flags.pop(PAID_HIT_KEY, None)
    if not target.active:
        return
    if not paid and str((typed.get("modifier") or {}).get("id") or "") != LIFE_SEVERING:
        return
    from ..typed_executor import bears_mark

    if not bears_mark(target, attacker.entity_id, SWORD_INTENT):
        return
    current = engine.state.actors.get(engine.state.current_actor_id)
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    if attacker.turn_flags.get(TURN_KEY) == turn:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "sword_life_severing", target.entity_id), attacker,
                 "choice:needle.sword_life_severing", [key for key, _ in EXTRA_OPTIONS],
                 labels=dict(EXTRA_OPTIONS), allow_decline=False, target_id=target.entity_id,
                 name="Life-Severing Sword", feature_id=LIFE_SEVERING,
                 prompt=f"Life-Severing Sword: your Sword strike hit {target.display_name}, who carries your "
                        f"{SWORD_INTENT} (the mark your Sword attacks leave on what they hit). Choose one extra effect "
                        f"for that creature. It lasts until the start of your next turn, and you choose one each turn "
                        f"while this talent's cost is paid.")
    choice = picked[0] if picked and picked[0] in dict(EXTRA_OPTIONS) else HALVE_HEALING
    attacker.turn_flags[TURN_KEY] = turn
    _deliver(engine, attacker, action, intent, typed, target, choice,
             reduction_source=LIFE_SEVERING if paid else None)


def _replace_own_reduction(engine: Any, attacker: Any, target: Any, source: str) -> None:
    """The printed choice replaces the healing reduction this very strike applied ("halve healing received
    instead"), so that reduction goes before the halving is: at Proficiency Bonus 4 a 20-point heal is 10, not
    (20 - 4) halved again. Only this activation's own reduction is taken off the target; another creature's
    reduction on the same creature, and the talent's separate Temporary HP denial, are untouched."""
    # The completed-hit hook runs immediately after this strike's effects. The
    # newest matching record is therefore this activation's reduction. Modifiers
    # are filed under the active actor, including when the attacker is a reactor;
    # source_actor_id alone is not attacker provenance on an Opportunity Attack.
    for mid, modifier in reversed(list(target.modifiers.items())):
        if (modifier.target_field == "healing_reduction" and modifier.source_definition_id == source
                and modifier.source_actor_id == engine.state.current_actor_id):
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=attacker.entity_id,
                                 target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": "REPLACED"})
            break


def _deliver(engine: Any, actor: Any, action: Any, intent: Any, typed: dict[str, Any], target: Any, choice: str,
             *, reduction_source: str | None = None) -> None:
    """Apply the chosen clause with combat/typed_executor's own effect rows. All three last until the start of the
    user's next turn, which is what the printed sentence says for the whole choice."""
    from ..typed_executor import Context, run_effects

    source = f"passive:{LIFE_SEVERING}"
    if choice == HALVE_HEALING:
        _replace_own_reduction(engine, actor, target,
                               reduction_source or str(getattr(action, "source_definition_id", "") or ""))
        row = {"type": "healing_reduction", "applies_to": "target", "evidence": "healing received is halved",
               "harmful": True, "duration": {"kind": "until_start_of_your_next_turn"}}
    elif choice == CON_DISADVANTAGE:
        row = {"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw",
               "evidence": "Disadvantage on its next Concentration saving throw", "expires_on": SOURCE_TURN}
    else:
        # "it cannot benefit from ordinary regeneration": combat/ext/regeneration.py owns that effect, which places a
        # condition on the creature and refuses a regeneration healing row until this turn comes round again.
        row = {"type": "suppress_regeneration", "applies_to": "target", "name": "Life-Severing Sword",
               "evidence": "it cannot benefit from ordinary regeneration until the start of your next turn",
               "expires_on": SOURCE_TURN}
    child = Context(engine, actor, action, intent, typed, [target], target, {}).with_source(source)
    run_effects(child, [row])
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"trigger": "Life-Severing Sword", "text": dict(EXTRA_OPTIONS)[choice]})
