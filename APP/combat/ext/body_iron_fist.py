"""Iron Fist sphere mechanisms owned by the wave-2 "body" worker for the roster characters remaining after
auto-ironclad (Lianhui of the Tidal Veil, Lingfeng the Ember Artisan) -- and, since these three talents' printed
mechanics could not be expressed as data-only reviewed_final.d corrections (see the "why" on each feature_blocks.d
entry below), for every character who owns them, including Lingfeng Ironclad.

- Meridian Lock (CL10+, "when a creature fails its saving throw against Meridian-Sealing Palm, choose two seals
  instead of one"): Meridian-Sealing Palm is itself a modifier-derived variant of Unarmed Strike, not a standalone
  built action, so the generic named-modifier system cannot attach a second modifier onto it. Read Meridian-Sealing
  Palm's own Constitution save directly (matched by its typed["modifier"]["id"]) and add a second, mechanized seal.
- Falling Leaf Sweep (CL5+, "choose one other creature within 5 feet ... that second creature makes a Dexterity
  saving throw"): the previous typing put this save on the SAME creature Unarmed Strike's Shove option just felled.
  Read the Shove option's own save directly and sweep a DIFFERENT, nearby hostile creature instead.
- Dragon-Step Clinch (CL5+, "you may maintain the grapple with ... a body clinch instead of a free hand ... your
  Speed is reduced by 10 feet while maintaining it; the target has Advantage on checks made to escape unless it was
  Opened when the grapple began"): an eligible per-hold body choice activates maintenance and stores the
  pre-Grapple escape benefit. The old free Maintain/End actions remain compatible with saved fights.
- Iron Fist's damage types (Body Refining path, CL1; hunt53 2026-10-01): the natural weapon's Bludgeoning, Piercing or
  Slashing palette (merged with Iron Meridian Body's Force) and the per-strike choice, asked through the documented
  attack_damage_type_choice hook. Its attack ability stays the owner's 2026-09-30 ruling (combat/ext/attack_abilities.py):
  the highest of Strength, Dexterity and Constitution unless the sheet records a choice -- no per-attack ability prompt.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from ..typed_executor import CONDITION_PREFIX, bears_mark


IRON_FIST = "tianxia.path.body_refining.feature.iron_fist"
IRON_FIST_TYPES = ("BLUDGEONING", "PIERCING", "SLASHING")  # "may deal Bludgeoning, Piercing, or Slashing damage"
DAMAGE_TYPE_CHOICE = "iron_fist_damage_type"


@hook("maneuvers")
def natural_damage_types(info: dict[str, Any]) -> None:
    """The natural-strike damage palette, in one place so neither ability drops the other's types.

    Iron Fist (Body Refining path, CL1): "Your unarmed strike may deal Bludgeoning, Piercing, or Slashing damage.
    Choose the damage type when you make the attack." Its natural weapon (typed source == IRON_FIST) gets the three
    types and ``natural_source`` provenance, which travels with the weapon when a reaction borrows it (an Unarmed
    Strike counter, typed_reactions._generic_context) so iron_fist_damage_type below still asks.
    Iron Meridian Body: every natural strike may also deal Force."""
    meridian = "TAL_IRON_FIST_IRON_MERIDIAN_BODY" in info["owned"]
    for action in info["actions"]:
        typed = action.parameters.get("typed") or {}
        weapon = typed.get("weapon") if ".natural." in action.source_definition_id else None
        if not weapon:
            continue
        before = list(weapon.get("damage_types") or [weapon.get("damage_type") or "BLUDGEONING"])
        kinds, updated = list(before), dict(weapon)
        if typed.get("source") == IRON_FIST:
            kinds += [kind for kind in IRON_FIST_TYPES if kind not in [str(k).upper() for k in kinds]]
            updated["natural_source"] = IRON_FIST
        if meridian and "FORCE" not in [str(kind).upper() for kind in kinds]:
            kinds.append("FORCE")
        if kinds != before:
            updated["damage_types"] = kinds
        if updated != weapon:  # other natural weapons keep their compiled bytes
            typed["weapon"] = updated


@hook("attack_damage_type_choice")
def iron_fist_damage_type(ctx: Any, attack: dict[str, Any], target: Any, kinds: list[str], attack_index: int) -> str | None:
    """Iron Fist: the attacker chooses the damage type of each strike made with the Iron Fist weapon -- its own attack,
    each attack of an Attack action, and a reaction counter that borrows it. Asked of a player-controlled owner, on
    their turn or an AI creature's; an AI owner takes the type that lands hardest (typed_executor.choose_damage_type,
    the same pick the table made before this choice existed). Inert unless the weapon is an Iron Fist natural weapon
    and the strike deals that weapon's damage."""
    weapon = ctx.typed.get("weapon") or {}
    if weapon.get("natural_source") != IRON_FIST or target is None or len(kinds) < 2:
        return None
    damage = next((row for row in attack.get("on_hit") or [] if isinstance(row, dict) and row.get("type") == "damage"), None)
    if damage is not None and not damage.get("weapon_damage"):
        return None  # the attack deals its own printed damage, not the Iron Fist strike's
    from ..typed_executor import choose_damage_type
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    best = choose_damage_type(ctx, list(kinds), [target])
    count = int(attack.get("count") or 1)
    which = f" (attack {attack_index} of {count})" if count > 1 else ""
    picked = ask(engine, ctx.intent, checkpoint_id(engine, DAMAGE_TYPE_CHOICE, actor.entity_id, target.entity_id, attack_index),
                 actor, CHOICE + DAMAGE_TYPE_CHOICE, list(kinds), labels={kind: f"{kind.title()} damage" for kind in kinds},
                 preferred=[best], target_id=target.entity_id, name="Iron Fist", feature_id=IRON_FIST,
                 prompt=f"Iron Fist: choose the damage type of your {ctx.action.display_name}{which} against {target.display_name}. "
                        f"The strike's dice and bonus stay the same; only the type changes, which matters against Resistance.",
                 prompt_context=action_context(engine, actor, ctx.source, target))
    return picked[0] if picked else None

MERIDIAN_SEALING_PALM_ID = "TAL_IRON_FIST_MERIDIAN_SEALING_PALM"
MERIDIAN_LOCK_BLOCK = "body_meridian_lock"
FALLING_LEAF_SWEEP_BLOCK = "body_falling_leaf_sweep"
DRAGON_STEP_CLINCH_ID = "TAL_IRON_FIST_DRAGON_STEP_CLINCH"
DRAGON_STEP_CLINCH_BLOCK = "body_dragon_step_clinch"
MERCIFUL_HAND_ID = 'TAL_IRON_FIST_MERCIFUL_HAND'
MERCIFUL_HAND_BLOCK = 'body_merciful_hand'
CLINCH_SELF_CONDITION = CONDITION_PREFIX + "body_dragon_step_clinch"
CHECK_MODE_CONDITION = CONDITION_PREFIX + "check_mode"  # typed_executor.block_advantage's condition id (shared)


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block in (MERIDIAN_LOCK_BLOCK, FALLING_LEAF_SWEEP_BLOCK, DRAGON_STEP_CLINCH_BLOCK, MERCIFUL_HAND_BLOCK):
        if block == DRAGON_STEP_CLINCH_BLOCK:
            return [{**row, "choice_owner": True}]
        return [row]  # a bare marker row; the hooks below only check that it exists (typed_reactions._rows)
    return None


def _owns(engine: Any, actor_id: str, block: str) -> bool:
    from ..typed_reactions import _rows

    return bool(_rows(engine, actor_id, block))


def _merciful_grapple(engine, actor, target):
    """Use the compiled free-hand Grapple option, then check reach, size and occupied hands.

    Managed equipment uses the shared occupancy query, including shields and
    readied weapons. Historical catalogs retain their original hand policy.
    The ordinary escape DC and range are reused; no equipment is dropped.
    """
    option = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and (a.parameters.get('typed') or {}).get('unarmed_option') == 'grapple'), None)
    if (option is None or engine._distance_actor_to_actor(actor, target) > int(option.range_ft or 5)
            or engine._footprint(target).width_cells > engine._footprint(actor).width_cells + 1):
        return None
    from .hand_occupancy import free_hands, supports_grips
    if supports_grips(engine, actor) and not free_hands(engine, actor):
        return None
    from .weapon_hits import available_weapons
    from ..weapon_delivery import delivery_kind
    armed = any(any(delivery_kind(action.parameters['typed'], row, action.parameters) == 'weapon'
                    for row in action.parameters['typed'].get('effects', []) if row.get('type') == 'attack')
                for action in available_weapons(engine, actor).values())
    held = {other.entity_id for other in engine.state.actors.values() if other.active
            and any(c.condition_id in (CONDITION_PREFIX + 'grappled', 'condition:core.grappled')
                    and c.source_actor_id == actor.entity_id for c in other.conditions.values())}
    clinching = any(c.condition_id == CLINCH_SELF_CONDITION for c in actor.conditions.values())
    if not clinching and len(held) >= (1 if armed else 2):
        return None
    from ..typed_executor import condition_immune
    return None if condition_immune(engine, target, 'grappled') else option


@hook('damage_floor')
def merciful_hand(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    provenance = engine.damage_context()
    actor = engine.state.actors.get(source_actor_id)
    if (provenance is None or provenance.kind != 'unarmed' or provenance.component != 'primary'
            or provenance.attacker_id != source_actor_id or provenance.target_id != target.entity_id
            or actor is None or not actor.active or intent is None or not target.active or target.current_hp <= 0
            or amount < target.current_hp + target.temporary_hp
            or not _owns(engine, actor.entity_id, MERCIFUL_HAND_BLOCK)):
        return None
    from .needle import ask, checkpoint_id, CHOICE, regain_focus, say
    from .. import granted_movement, typed_executor

    labels = {'prone': 'Leave at 1 HP and knock Prone until they stand up',
              'reactions': 'Leave at 1 HP; no Reactions until the end of their next turn'}
    grapple = _merciful_grapple(engine, actor, target)
    if grapple is not None:
        labels['grapple'] = 'Leave at 1 HP and Grapple: Speed 0 until escape or release'
    moves = granted_movement.candidates(engine, actor, 5, intent, MERCIFUL_HAND_ID)
    for key, candidate in moves.items():
        labels[key] = (f'Leave at 1 HP and step to {candidate.destination.x},{candidate.destination.y} '
                       f'(up to 5 ft; no opportunity attack from {target.display_name})')
    picked = ask(engine, intent, checkpoint_id(engine, 'MERCIFUL_HAND', provenance.roll_id), actor,
        CHOICE + 'merciful_hand', list(labels), labels=labels, allow_decline=True, default='decline',
        target_id=target.entity_id, name='Merciful Hand', feature_id=MERCIFUL_HAND_ID,
        prompt=f"Merciful Hand: {actor.display_name}'s Unarmed Strike would reduce {target.display_name} to 0 HP. "
               'Leave them at 1 HP and choose an effect? This costs no resource, Action or Reaction and restores '
               'Martial Focus if absent. Separate follow-up damage still applies. Decline to deal this damage normally.')
    if not picked:
        return None
    choice = picked[0]
    action = grapple if choice == 'grapple' else engine.action_catalog.get(source_id)
    if action is None:
        from ..gate2_runtime_models import ActionDefinition
        action = ActionDefinition(source_definition_id=MERCIFUL_HAND_ID, display_name='Merciful Hand',
            owner_id=actor.entity_id, economy='NONE', resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=5)
    action = action.model_copy(update={'source_definition_id': MERCIFUL_HAND_ID})
    typed = dict((action.parameters.get('typed') or {}) if action else {})
    ctx = typed_executor.Context(engine, actor, action, intent, {**typed, 'source': MERCIFUL_HAND_ID}, [target], target)
    if choice == 'prone':
        typed_executor.block_condition(ctx, {'condition': 'prone', 'applies_to': 'target',
            'condition_label': 'Merciful Hand: Prone until you stand up'})
    elif choice == 'grapple':
        typed_executor.block_condition(ctx, {'condition': 'grappled', 'applies_to': 'target', 'until_escape': True,
            'condition_label': f'Merciful Hand: Grappled by {actor.display_name}; Speed 0 until escape or release'})
    elif choice == 'reactions':
        typed_executor.block_condition(ctx, {'condition': 'reaction_denied', 'applies_to': 'target', 'duration': 'target_next_turn',
            'condition_label': 'Merciful Hand: no Reactions until the end of your next turn'})
    else:
        engine._resolve_movement(actor, moves[choice], intent, granted_ft=5, ignore_oa_from=(target.entity_id,))
    regain_focus(engine, actor, MERCIFUL_HAND_ID, 'Merciful Hand')
    say(engine, MERCIFUL_HAND_ID, actor,
        f'{actor.display_name} uses Merciful Hand on {target.display_name}: {labels[choice]}.',
        (target.entity_id,), details={'attack_roll_id': provenance.roll_id})
    return 1


@hook("after_save")
def _after_save(ctx: Any, subject: Any, ability: str, named: set, failed: bool) -> None:
    if not failed:
        return
    from .. import typed_executor

    modifier_id = (ctx.typed.get("modifier") or {}).get("id")
    if modifier_id == MERIDIAN_SEALING_PALM_ID and ability == "CON" and _owns(ctx.engine, ctx.actor.entity_id, MERIDIAN_LOCK_BLOCK):
        from .iron_fist_riders import config
        if "meridian_lock" in config(ctx.engine, ctx.actor):
            return  # the failed branch now offers the actual seal choices
        # "choose two seals instead of one": Meridian-Sealing Palm's own on_fail already applies the Leg Seal
        # (Speed -15); add a second, mechanized half of the Breath Seal (reaction_denied is a real condition type;
        # "Disadvantage on the next Concentration saving throw it makes" is a future, unrelated save this engine has
        # no "flag the next save of kind X" hook for -- left as a GM-only rider rather than mistyped).
        typed_executor.run_effects(ctx, [
            {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
             "evidence": "Meridian Lock: Breath Seal -- cannot take Reactions"},
        ])
        ctx.rider("Meridian Lock: two seals chosen (Leg Seal + Breath Seal). Breath Seal's Disadvantage on the "
                  "target's next Concentration saving throw is GM-only: no hook flags a future, unrelated save.")
        return
    if ctx.typed.get("unarmed_option") == "shove_prone" and _owns(ctx.engine, ctx.actor.entity_id, FALLING_LEAF_SWEEP_BLOCK):
        _falling_leaf_sweep(ctx, subject)


def _falling_leaf_sweep(ctx: Any, target: Any) -> None:
    """Falling Leaf Sweep: sweep one other creature within 5 feet of the felled target (two if it was already
    Opened before this hit). No player-facing 'choose a creature' sub-prompt exists mid-resolution on this table, so
    the candidate(s) are the nearest other hostile creature(s) to the target, picked deterministically."""
    from .. import typed_executor
    from .iron_fist_riders import config, sweep
    if "falling_leaf" in config(ctx.engine, ctx.actor):
        sweep(ctx, target)
        return

    already_opened = bears_mark(target, ctx.actor.entity_id, "Opened")
    count = 2 if already_opened else 1
    candidates = [other for other in ctx.engine.state.actors.values()
                  if other.active and other.entity_id not in (ctx.actor.entity_id, target.entity_id)
                  and other.team_id != ctx.actor.team_id and ctx.engine._distance_actor_to_actor(target, other) <= 5]
    candidates.sort(key=lambda other: (ctx.engine._distance_actor_to_actor(target, other), other.entity_id))
    chosen = candidates[:count]
    if not chosen:
        return
    if len(candidates) > count:
        ctx.rider(f"Falling Leaf Sweep: {len(candidates)} creatures were within 5 feet; swept the nearest {count} "
                  "(no player 'choose a creature' sub-prompt exists mid-resolution on this table).")
    sub = typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, chosen, None, ctx.damage_cache)
    typed_executor.run_effects(sub, [
        {"type": "save", "ability": "dex", "applies_to": "target",
         "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target", "duration": "instant", "evidence": "It falls Prone"}],
         "on_success": [{"type": "speed", "applies_to": "target", "amount": -10, "duration": "until_start_of_next_turn",
                         "evidence": "Its Speed is reduced by 10 feet until the start of your next turn"}],
         "evidence": "Falling Leaf Sweep: that second creature makes a Dexterity saving throw"},
    ])


@hook("compile_actions")
def _clinch_actions(info: dict[str, Any]) -> list[Any] | None:
    if DRAGON_STEP_CLINCH_ID not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.dragon_step_clinch.{key}", display_name=f"Dragon-Step Clinch: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "body_dragon_step_clinch_toggle", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in (("maintain", "Maintain"), ("end", "End"))]


@effect("body_dragon_step_clinch_toggle")
def _clinch_toggle(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    engine, actor = ctx.engine, ctx.actor
    # A stable id for "the Advantage-to-escape this specific toggle action granted" -- always the Maintain action's
    # own id, whichever of Maintain/End is running now (both share one source_definition_id prefix).
    maintain_source = ctx.source.rsplit(".", 1)[0] + ".maintain"
    # Remove any Advantage-to-escape this toggle previously granted before re-deriving it (or ending the clinch).
    for other in engine.state.actors.values():
        for iid, condition in list(other.conditions.items()):
            if condition.condition_id == CHECK_MODE_CONDITION and condition.source_actor_id == actor.entity_id \
                    and condition.source_definition_id == maintain_source:
                del other.conditions[iid]
                engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(other.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    if eff.get("choice") != "maintain":
        engine._remove_condition(actor, CLINCH_SELF_CONDITION, ctx.source)
        from . import run
        run("grapple_eligibility_changed", engine, actor, ("body:dragon_step_clinch",))
        ctx.rider("Dragon-Step Clinch ended.")
        return
    if any(row.condition_id in (CONDITION_PREFIX + "prone", CONDITION_PREFIX + "restrained", CONDITION_PREFIX + "incapacitated")
           for row in actor.conditions.values()):
        ctx.rider("Dragon-Step Clinch cannot be maintained while Prone, Restrained, or Incapacitated.")
        return
    engine._apply_condition(actor, CLINCH_SELF_CONDITION, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Dragon-Step Clinch (Speed -10 while maintained)"})
    # "The target has Advantage on checks made to escape unless it was Opened when the grapple began": read at the
    # moment the clinch is (re)chosen, not frozen from the original grapple (Ironclad's per-grapple-instance state
    # was out of scope; this re-derives it whenever the toggle is used, which covers the common case of choosing the
    # clinch right after the grapple lands).
    for other in engine.state.actors.values():
        if other.entity_id == actor.entity_id or not other.active:
            continue
        grappled_by_me = any(condition.condition_id == CONDITION_PREFIX + "grappled" and condition.source_actor_id == actor.entity_id
                             for condition in other.conditions.values())
        if grappled_by_me and not bears_mark(other, actor.entity_id, "Opened"):
            sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [other], other, ctx.damage_cache)
            typed_executor.run_effects(sub, [
                {"type": "advantage", "applies_to": "target",
                 "on": "Strength (Athletics) checks and Dexterity (Acrobatics) checks made to escape this grapple",
                 "expires_on": "UNTIL_REMOVED",
                 "evidence": "Dragon-Step Clinch: the target has Advantage on checks made to escape"},
            ])
    ctx.rider("Dragon-Step Clinch maintained: Speed -10 while active; Advantage to escape granted to any creature you "
             "have Grappled that was not already Opened.")


@hook("grappling_body_parts")
def _clinch_grappling_part(engine: Any, actor: Any) -> list[dict[str, str]] | None:
    if not _owns(engine, actor.entity_id, DRAGON_STEP_CLINCH_BLOCK):
        return None
    from .needle import incapacitated

    if incapacitated(actor) or any(row.condition_id in (CONDITION_PREFIX + "prone", CONDITION_PREFIX + "restrained")
           for row in actor.conditions.values()):
        return None
    from .iron_fist_riders import config

    cost = ("Heaven-Seizing Clinch keeps your Speed unchanged. " if "heaven_clinch" in config(engine, actor)
            else "Your Speed drops by 10 feet while it lasts. ")
    return [{"id": "body:dragon_step_clinch", "label":
             "Dragon-Step Clinch: body hold; " + cost +
             "The creature has Advantage to escape unless it was Opened by you when the grapple began "
             "(your opening in its defenses). End at any time, with no Action or extra resource cost."}]


@hook("grappling_part_selected")
def _start_selected_clinch(ctx: Any, subject: Any, part: str) -> dict[str, int] | None:
    """Activate only the chosen body hold; freeze its escape benefit at creation."""
    if part != "body:dragon_step_clinch" or not _clinch_grappling_part(ctx.engine, ctx.actor):
        return None
    if not any(row.condition_id == CLINCH_SELF_CONDITION for row in ctx.actor.conditions.values()):
        ctx.engine._apply_condition(ctx.actor, CLINCH_SELF_CONDITION, ctx.source, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED",
                                    data={"label": "Dragon-Step Clinch (body hold)"})
    from ..typed_executor import opened_before

    before = opened_before(ctx.engine, ctx.actor.entity_id, subject.entity_id)
    opened = before if before is not None else bears_mark(subject, ctx.actor.entity_id, "Opened")
    return {"clinch_escape_advantage": int(not opened)}


@hook("escape_mode")
def _clinch_escape_mode(engine: Any, escaper: Any, grips: list[Any]) -> str | None:
    if any(row.data.get("grappling_part") == "body:dragon_step_clinch"
           and row.data.get("clinch_escape_advantage") == 1 for row in grips):
        return "ADVANTAGE"
    return None


@hook("event", nested=True)
def _end_released_clinch(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != CONDITION_PREFIX + "grappled":
        return
    # Escape, range, and explicit release all end the selected hold's Speed cost.
    for actor in engine.state.actors.values():
        if not any(row.condition_id == CLINCH_SELF_CONDITION
                   and row.source_definition_id in engine.action_catalog
                   and (engine.action_catalog[row.source_definition_id].parameters.get("typed") or {}).get("unarmed_option") == "grapple"
                   for row in actor.conditions.values()):
            continue  # preserve the legacy standalone Maintain toggle
        if not any(row.data.get("grappling_part") == "body:dragon_step_clinch"
                   and row.source_actor_id == actor.entity_id for other in engine.state.actors.values()
                   for row in other.conditions.values()):
            _clear_clinch(engine, actor)


@hook("candidate_allowed")
def _hide_illegal_clinch_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or "Dragon-Step Clinch: Maintain" not in str(action.display_name):
        return None
    if any(row.condition_id in (CONDITION_PREFIX + "prone", CONDITION_PREFIX + "restrained", CONDITION_PREFIX + "incapacitated",
                                CONDITION_PREFIX + "stunned", CONDITION_PREFIX + "paralyzed", CONDITION_PREFIX + "petrified",
                                CONDITION_PREFIX + "unconscious") for row in actor.conditions.values()):
        return False
    return None


@hook("speed")
def _clinch_speed(engine: Any, actor: Any) -> int | None:
    from ..speed_contributions import SpeedContribution

    condition = next((c for c in actor.conditions.values() if c.condition_id == CLINCH_SELF_CONDITION), None)
    if condition is not None:
        from .iron_fist_riders import config
        if "heaven_clinch" in config(engine, actor):
            return 0
        return SpeedContribution([(condition.source_definition_id, "Dragon-Step Clinch", -10)])
    return None


@hook("event", nested=True)
def _end_ineligible_clinch(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") not in {
            CONDITION_PREFIX + "prone", CONDITION_PREFIX + "restrained"}:
        return
    from . import run

    for actor_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(actor_id)
        if actor is not None:
            _clear_clinch(engine, actor, reconcile=True)


@hook("became_incapacitated")
def _end_incapacitated_clinch(engine: Any, actor: Any, event: dict[str, Any]) -> None:
    _clear_clinch(engine, actor)


def _clear_clinch(engine: Any, actor: Any, *, reconcile: bool = False) -> None:
    clinch = next((row for row in actor.conditions.values() if row.condition_id == CLINCH_SELF_CONDITION), None)
    if clinch is None:
        return
    maintain_source = clinch.source_definition_id
    actor.conditions.pop(clinch.instance_id, None)
    engine._append_event("CONDITION_REMOVED", maintain_source, actor_id=actor.entity_id,
                         target_ids=(actor.entity_id,), payload={"condition_id": clinch.condition_id,
                         "instance_id": clinch.instance_id, "reason": "BODY_HOLD_INELIGIBLE"})
    for other in engine.state.actors.values():
        for iid, condition in list(other.conditions.items()):
            if condition.condition_id == CHECK_MODE_CONDITION and condition.source_actor_id == actor.entity_id \
                    and condition.source_definition_id == maintain_source:
                other.conditions.pop(iid, None)
                engine._append_event("CONDITION_REMOVED", maintain_source, actor_id=actor.entity_id,
                                     target_ids=(other.entity_id,), payload={"condition_id": condition.condition_id,
                                     "instance_id": iid, "reason": "BODY_HOLD_INELIGIBLE"})
    if reconcile:
        from . import run
        run("grapple_eligibility_changed", engine, actor, ("body:dragon_step_clinch",))
@hook("speed_explanation")
def clinch_speed_explanation(engine: Any, actor: Any):
    delta = _clinch_speed(engine, actor)
    return [{"label": "Dragon-Step Clinch", "delta_ft": delta}] if delta else []
