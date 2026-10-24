"""Gravity sphere (rider lane C2, 2026-09-30: "i want everything we can automated"): Weight Shift's modes, Weighted Strike and
the talents that change it, and Gravity's defensive answers to a missed melee attack.  Rules text: the owner's Sphere Compendium,
"Sphere of Gravity" (authority/typed_mechanics/rules_text.json); Weighted Strike's printed text is GRAVITY_BASE_WEIGHTED_STRIKE
(authority/typed_mechanics/base_ability_sources.json: the catalog had no row for it).

Modes.  Weight Shift's Body Lightening / Body Heavying rows carry a ``state`` (combat/ext/states.py) inside a ``singleton_benefit``
(combat/ext/riders_shared.py): a new mode ends the old mode's benefits, and Incapacitated ends the mode (Neutral Weight).
``mode(engine, actor, name)`` is the public question ("body_lightening" / "body_heavying"); Moon-Weight Incarnation counts as
both.  "Weight Shift: Neutral Weight" is a free action that ends the mode, offered once a mode is on and not after a mode change
this turn ("You may change modes only once on each of your turns"); the AI never takes it.

Owned rows: combat/rules/feature_blocks.d/riders_c2.json, block "gravity", one ``kind`` per ability (compile_block below).  Every
hook returns at once for a creature without that row or without one of this module's conditions, so other characters and fights
saved before are unchanged.

  weight_shift            Body Lightening: after moving 10 feet on your turn, a melee attack with an Unarmed Strike, a simple melee
                          weapon, a spear, a blade, a saber or a staff uses the Gravity key ability for its attack roll
                          (``attack_bonus``: the key ability modifier minus the weapon's own, when higher).  Body Heavying: the
                          first melee weapon attack or Unarmed Strike that hits before the mode ends deals Proficiency Bonus
                          extra damage of the attack's own type, unless you moved more than half your Speed on your turn.
  weighted_strike         ``after_hit_choice``: once per turn, a melee weapon attack or Unarmed Strike that hits while a mode is on;
                          pay 1 (Stamina or the Path pool) and choose Heavying Blow or Lightening Blow (1d6 Force; 2d6 at CL 5,
                          3d6 at CL 11, 4d6 at CL 17).  Heavying: Strength save; fail: pushed 5 ft, pulled 5 ft or Prone (your
                          pick); success: no Reactions until the start of its next turn.  Lightening: step up to 10 feet, no
                          Opportunity Attack from the target.
  heavy_weapon_body       Heavying Blow dice are d8 with a two-handed melee weapon or an Unarmed Strike.
  gravitic_armor          while Gravitic Armor is on: Heavying Blow dice one step larger; Body Lightening Speed +10 more.
  anchor_breaking_palm    a Heavying Blow may disrupt footing instead: fail -- no Gravity forced-movement reduction until the start
                          of your next turn; success -- Speed -10 until the start of its next turn.
  ten_thousand_weight_body  at the start of your turn with Body Heavying on, pay 5: until the start of your next turn you cannot be
                          moved against your will by a known Core Formation-or-lower (CL 14 or less) creature, melee attackers
                          that hit you take Proficiency Bonus Force damage, and a failed Heavying Blow save means Prone and a
                          10-foot push or pull; afterwards Speed -10 until the end of that turn.
  size steps              (``size_steps``, combat/ext/effective_size.py) Body Heavying: one size larger when resisting Shove, Grapple,
                          forced movement and being knocked Prone; Mountain Body at CL 5: two sizes against forced movement;
                          Moon-Weight Incarnation while on: two sizes against forced movement and Prone (largest counts).
  moon_weight_incarnation both modes count; Heavying does not lower Speed; one free Weighted Strike on each of your turns; once a
                          round both blows on one hit.
  light_body_flurry       once a fight, a free Lightening Blow after moving 10 feet on your turn with Body Lightening on.
  light_body_rush         Body Lightening: "Light Body Rush: Dash / Disengage" Bonus Actions for 1; a hit after moving 20 feet on
                          your turn may take a free Lightening Blow.
  anchor_stance           ``forced_movement_reduction`` 10 while Body Heavying; CL 5: a free action shares it with one adjacent
                          ally until the start of your next turn.
  orbiting_guard          after a hostile melee miss, once a round, a free 5-foot step with no Opportunity Attack from that
                          attacker; CL 5: +1 more AC while a mode is on (``ac``).
  orbit_breaking_guard    Reaction (free once a round with Gravitic Armor) after a hostile melee miss while Orbiting Guard is on:
                          move the attacker next to you, step 10 feet without Opportunity Attacks, or Dexterity save or Prone.
  moon_falling_counter    Reaction and 1 after a hostile melee miss with Body Lightening on: step 10 feet (no OA from the
                          attacker), one melee attack against it; a hit may take a free Lightening Blow.
  mountain_crushing_step  a free action for 1 with Body Heavying on, before moving: ignore nonmagical difficult terrain and the first
                          creature hit in melee after moving 10 feet makes a Strength save or is knocked Prone or pushed 10 feet.
  (Gravity Well)          ``gravity_center_prone``: a creature this activation pulled into the area's centre makes a Dexterity save
                          or falls Prone.
  (Black-Star Grip)       ``turn_start``: a creature Grappled by it takes Proficiency Bonus Force damage at the start of its turn.
  (Event Horizon Prison)  ``teleport_gate``: teleporting out of the prison needs an opposed Cultivation Check (a tie fails).
  (Shared Weight)         ``gravity_share_weight``: the chosen mode's own benefit rows on one or two willing creatures you touch.
  flight_suppression     ``turn_start``: a creature that is off the ground, can fly and starts its turn inside the area makes
                          the area's own Strength save; a failed save gives ``gravity_no_flight`` (its Fly Speed is 0, so the
                          engine's own fall check drops a creature that cannot Hover and leaves one that can) and a
                          successful one ``gravity_half_flight`` (half Fly Speed).
  (Gravity Domain)        ``flight``: a hostile creature inside the Domain has no Fly Speed unless it can Hover.
  (Weight of the Mountain, Heaven's Weight)  ``gravity_no_flight``: "its Fly Speed becomes 0" / "it cannot fly", for a
                          creature that could fly at all; the engine's own fall check drops it only if it cannot Hover.
  falling_hammer         a fall, jump down or drop of 10 feet or more earlier this turn (``descent_steps``, the shared descent
                          stamp) lets a melee hit use Weighted Strike with no mode on, and adds 1d6 Force (2d6 at CL 11).
  weight_borrowing_throw after a successful Shove or Grapple with Body Heavying on, pay 1: put the target on any square up to
                          5 feet away in any horizontal direction or knock it Prone, 10 feet when it is already Grappled by you
                          (``forced_destination``, the shared forced-move choice).
  reverse_gravity_step   ``gravity_reverse_step``: a recorded condition carrying the engine's own no-falling-damage reading,
                          expiring with the turn the printed Duration names.
  feather_body           ``stand_cost`` 5 feet while Body Lightening is on; ``falling_damage`` makes a drop of 30 feet or less
                          free, the first 30 feet it names.
  gravity_sense          ``check_bonus``: +2 on a Cultivation Check made to resist a Gravity effect (the resolver names the
                          effect it is answered on).
  (Gravitic Armor, Moon-Weight Incarnation, Body Lightening)  ``falling_damage``: no falling damage while Gravitic Armor or
                          Moon-Weight Incarnation is on, and 5 x Proficiency Bonus off any fall while Body Lightening is on.
Falling damage, Fly Speed and standing from Prone are the engine's own records (combat/falling, combat/flight, ``stand_cost``), so
those printed lines are answered here rather than left to the GM. Jumping distances, carrying capacity, wall and ceiling running,
liquid surfaces and damage to structures and objects have no table rule and stay printed text.
Every Gravity technique's "Cost: N CP or Stamina" is typed data (reviewed_final), not this module.
"""

from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any

from . import effect, hook
from .descent_steps import held as _held

BLOCK = "gravity"
WEIGHT_SHIFT = "TAL_GRAVITY_WEIGHT_SHIFT_BASE"
LIGHT, HEAVY = "body_lightening", "body_heavying"
MOON, ARMOR, ORBIT = "moon_weight_incarnation", "gravitic_armor", "orbiting_guard"
TEN, CRUSH = "ten_thousand_weight", "mountain_crushing_step"
FOOTING = "condition:typed.gravity_footing_disrupted"
ANCHOR_SHARE = "condition:typed.gravity_anchor_share"
POOLS = (("resource:core.stamina", "Stamina"), ("resource:core.qi", "Qi"), ("resource:core.resonance", "Resonance"))
POOL_NAMES = {"resource:core.stamina": "stamina", "resource:core.qi": "qi", "resource:core.resonance": "resonance"}
# Turn flags: a key with "_round_" survives the owner's turn reset (combat/ext/__init__.py), for limits counted per any turn.
WS_TURN = "gravity_round_weighted_strike"
MOON_FREE = "gravity_round_moon_free"
MOON_BOTH = "gravity_round_moon_both"
FLURRY = "gravity_round_flurry_used"
HEAVY_HIT = "gravity_round_heavy_hit"
LAST_MOVED = "gravity_round_last_moved"
ORBIT_STEP = "gravity_round_orbit_step"
ORBIT_FREE = "gravity_round_orbit_free"
CRUSH_HIT = "gravity_crush_hit"
MODE_CHANGED = "gravity_mode_changed"
COUNTER_FREE = "_gravity_free_lightening"


# ------------------------------------------------------------------------------------------------ shared questions
def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """The actor's compiled Gravity row of this kind (combat/rules/feature_blocks.d/riders_c2.json), or None."""
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


def mode(engine: Any, actor: Any, name: str) -> bool:
    """Whether Body Lightening / Body Heavying (``name``) is on for the actor; Moon-Weight Incarnation counts as both."""
    from .states import active

    return bool(active(engine, actor, name) or (name in (LIGHT, HEAVY) and active(engine, actor, MOON)))


def _on(engine: Any, actor: Any, name: str) -> Any:
    from .states import active

    return active(engine, actor, name)



@hook("size_steps")
def heavy_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    """Body Heavying "count as one size larger when resisting Shove, Grapple, forced movement, and effects that would knock you
    Prone"; Mountain Body "At CL 5, you count as two sizes larger rather than one size larger for resisting forced movement";
    Moon-Weight Incarnation "count as two sizes larger for resisting forced movement and being knocked Prone" (rider lane C12)."""
    if role != "resist" or creature is None:
        return None
    if not purposes:
        return None
    steps = 0
    if mode(engine, creature, HEAVY) and purposes & {"shove", "grapple", "forced", "prone"}:
        steps = 1
        mountain = row(engine, creature, "mountain_body")
        if mountain is not None and "forced" in purposes and _cl(mountain) >= 5:
            steps = 2
    if row(engine, creature, MOON) is not None and _on(engine, creature, MOON) and purposes & {"forced", "prone"}:
        steps = 2
    return steps or None


def _turn(engine: Any) -> int:
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


def _own_turn(engine: Any, actor: Any) -> bool:
    return engine.state.current_actor_id == actor.entity_id


def _moved(engine: Any, actor: Any) -> int:
    from .hold_still import moved_ft

    return moved_ft(engine, actor)


def _cl(row_: dict[str, Any], ctx: Any = None) -> int:
    return int(row_.get("cl") or (ctx.numbers.get("cl") if ctx is not None else 0) or 1)


def _melee(ctx: Any) -> bool:
    """A melee attack: not ranged, not thrown, no shooting range."""
    attack = getattr(ctx, "attack_effect", None) or {}
    if "ranged" in str(attack.get("attack_kind") or ""):
        return False
    return not str(ctx.action.source_definition_id).endswith("#thrown") and not (ctx.typed.get("range_ft") or ctx.typed.get("long_range_ft"))


def _hostile(a: Any, b: Any) -> bool:
    return a.team_id != b.team_id


def payable(actor: Any, amount: int = 1) -> list[tuple[str, str]]:
    """The pools that can pay a Gravity "CP or Stamina" cost of ``amount``, as (resource id, name)."""
    return [(rid, name) for rid, name in POOLS if rid in actor.resources and int(actor.resources.get(rid) or 0) >= amount]


def _say(engine: Any, source: str, actor: Any, text: str, targets: Any = ()) -> None:
    from . import note

    note(engine, source, actor, text, targets)


def save_dc(engine: Any, actor: Any, fallback: Any = None) -> int:
    """The actor's Cultivation Save DC as its own Gravity techniques carry it (a weapon attack's numbers carry 8 + PB + the key
    ability, which a sheet's technique DC can differ from)."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        if typed.get("sphere") == "tianxia.sphere.gravity" and (typed.get("numbers") or {}).get("save_dc"):
            return int(typed["numbers"]["save_dc"])
    from .needle import save_dc as any_dc

    return int(fallback) if fallback else any_dc(engine, actor)


def _ctx(ctx: Any, target: Any) -> Any:
    """The attacker's Context aimed at ``target``, with its Gravity save DC."""
    from .. import typed_executor as te

    typed = {**ctx.typed, "numbers": {**ctx.numbers, "save_dc": save_dc(ctx.engine, ctx.actor, ctx.numbers.get("save_dc"))}}
    return te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, [target], target, {})


def _owner_ctx(engine: Any, actor: Any, source: str, target: Any, intent: Any = None, name: str = "") -> Any:
    """A Context for ``actor`` outside its own action (an answer to another creature's attack): source ``source`` (the feature),
    the actor's own numbers and Gravity save DC (typed_reactions.triggered_context, the public independent-trigger context)."""
    from ..typed_reactions import triggered_context
    from .needle import numbers_of

    numbers = {**numbers_of(engine, actor), "save_dc": save_dc(engine, actor)}
    return triggered_context(engine, actor, target, {"feature_id": source, "name": name or source, "numbers": numbers, "effects": []}, intent)


# ------------------------------------------------------------------------------------------------ compile
@hook("compile_block")
def gravity_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             **({"choice_owner": True} if spec.get("kind") == "ten_thousand_weight_body" else {}),
             "key_mod": int(numbers.get("key_mod") or 0), **({"first_thirty_feet": True} if spec.get("first_thirty_feet") else {}), **({"stopped_focus": True} if spec.get("stopped_focus") else {}), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


def _ways(info: dict[str, Any]) -> list[tuple[str, str]]:
    """The ways to pay "1 CP or Stamina": the Path pool and Stamina, as (resource id, name), without duplicates."""
    from ..factory_compiler import RESOURCE_IDS

    names = [str(info.get("primary") or ""), "stamina"]
    pools = {str(pool).lower() for pool in info.get("pools") or ()}
    out = []
    for name in dict.fromkeys(names):
        if name in RESOURCE_IDS and (name in pools or name == str(info.get("primary") or "")):
            out.append((RESOURCE_IDS[name], name.title()))
    return out


def _action(info: dict[str, Any], key: str, name: str, economy: Any, effects: list[dict[str, Any]], *, costs: tuple = (),
            params: dict[str, Any] | None = None, target_kind: str = "SELF", range_ft: int | None = None) -> Any:
    from ..gate2_runtime_models import ActionDefinition

    return ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.gravity.{key}", display_name=name, owner_id=info["actor_id"],
        economy=economy, resolution_kind="TYPED", target_kind=target_kind, range_ft=range_ft, costs=costs,
        parameters={"typed": {"effects": effects, "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
                              "source": key}, "expected_damage": 0, "gravity": True, **(params or {})})


@hook("compile_actions")
def gravity_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import EconomyKind

    owned = set(info.get("owned_ids") or ())
    cl = int((info.get("numbers") or {}).get("cl") or 1)
    ways = _ways(info)
    out = []
    if WEIGHT_SHIFT in owned:
        out.append(_action(info, "neutral_weight", "Weight Shift: Neutral Weight", EconomyKind.NONE,
                           [{"type": "gravity_neutral", "evidence": "Neutral Weight: you return to normal weight."}],
                           params={"player_only": True, "gravity_neutral": True}))
    if "TAL_GRAVITY_ANCHOR_STANCE" in owned and cl >= 5:
        out.append(_action(info, "anchor_share", "Anchor Stance: Steady an Adjacent Ally", EconomyKind.NONE,
                           [{"type": "gravity_anchor_share"}], params={"player_only": True, "gravity_requires": [HEAVY]}))
    if "tianxia.talent.gravity.light_body_rush" in owned:
        for rid, label in ways:
            suffix = f" ({label})" if len(ways) > 1 else ""
            out.append(_action(info, f"light_body_rush.dash.{label.lower()}", f"Light Body Rush: Dash{suffix}", EconomyKind.BONUS_ACTION,
                               [{"type": "movement", "applies_to": "self", "distance_ft": "speed", "evidence": "Light Body Rush: the Dash action"}],
                               costs=((rid, 1),), params={"gravity_requires": [LIGHT]}))
            out.append(_action(info, f"light_body_rush.disengage.{label.lower()}", f"Light Body Rush: Disengage{suffix}", EconomyKind.BONUS_ACTION,
                               [{"type": "movement", "applies_to": "self", "distance_ft": 0, "no_opportunity_attacks": True,
                                 "evidence": "Light Body Rush: the Disengage action"}],
                               costs=((rid, 1),), params={"gravity_requires": [LIGHT], "blocked_by_turn_flag": "disengaged"}))
    if "tianxia.talent.gravity.mountain_crushing_step" in owned:
        for rid, label in ways:
            suffix = f" ({label})" if len(ways) > 1 else ""
            out.append(_action(info, f"mountain_crushing_step.{label.lower()}", f"Mountain-Crushing Step{suffix}", EconomyKind.NONE,
                               [{"type": "state", "name": CRUSH, "label": "Mountain-Crushing Step", "duration": "until_end_of_turn"},
                                {"type": "condition", "condition": "ignore_difficult", "applies_to": "self", "expires_on": "END_OF_CURRENT_TURN",
                                 "evidence": "Your movement ignores ordinary difficult terrain until the end of your turn."}],
                               costs=((rid, 1),), params={"gravity_requires": [HEAVY], "gravity_before_moving": True,
                                                          "blocked_by_turn_flag": CRUSH_HIT + "_bought"}))
    return out or None


@hook("candidate_allowed")
def gravity_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    typed = parameters.get("typed") or {}
    if typed.get("source") == WEIGHT_SHIFT and actor.turn_flags.get(MODE_CHANGED):
        return False  # "You may change modes only once on each of your turns"
    if not parameters.get("gravity"):
        return None
    if parameters.get("gravity_neutral"):
        return bool((_on(engine, actor, LIGHT) or _on(engine, actor, HEAVY)) and not actor.turn_flags.get(MODE_CHANGED))
    needs = parameters.get("gravity_requires") or []
    if needs and not any(mode(engine, actor, name) for name in needs):
        return False
    if parameters.get("gravity_before_moving") and _moved(engine, actor) > 0:
        return False  # "you may spend 1 CP or Stamina before moving"
    return None


# ------------------------------------------------------------------------------------------------ modes
@effect("gravity_mode_change")
def mode_change(ctx: Any, eff: dict[str, Any]) -> None:
    """A Weight Shift use: the one mode change this turn."""
    ctx.actor.turn_flags[MODE_CHANGED] = 1


@effect("gravity_neutral")
def neutral(ctx: Any, eff: dict[str, Any]) -> None:
    """Neutral Weight: end the Weight Shift mode and its benefits (the same replacement a new mode makes)."""
    from .. import typed_executor as te

    ctx.actor.turn_flags[MODE_CHANGED] = 1
    typed = {**ctx.typed, "source": WEIGHT_SHIFT, "duration": {"kind": "until_start_of_next_turn"}}
    te.run_effects(te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, [ctx.actor], ctx.actor, {}),
                   [{"type": "singleton_benefit", "mechanic_id": WEIGHT_SHIFT, "effects": [], "duration": "until_start_of_next_turn"}])
    _say(ctx.engine, ctx.source, ctx.actor, f"Weight Shift: {ctx.actor.display_name} returns to Neutral Weight.")


def _lightening_modifier(ctx: Any, actor: Any) -> int | None:
    """The eligible attack-only key modifier, including a player's lower choice."""
    engine = ctx.engine
    owned = row(engine, actor, "weight_shift")
    if owned is None or not mode(engine, actor, LIGHT) or not _own_turn(engine, actor) or not _melee(ctx):
        return None
    weapon = ctx.typed.get("weapon") or {}
    if not weapon or _moved(engine, actor) < 10 or not _light_weapon(ctx):
        return None
    return int(ctx.numbers.get("key_mod") if ctx.numbers.get("key_mod") is not None else owned.get("key_mod") or 0)


@hook("attack_bonus")
def lightening_key_ability(ctx: Any, actor: Any) -> int | None:
    """Body Lightening's legacy automatic delta; a resolved choice takes precedence."""
    from .attack_abilities import resolved_strike_ability

    if resolved_strike_ability(ctx):
        return None
    key = _lightening_modifier(ctx, actor)
    if key is None:
        return None
    bonus = key - int((ctx.typed.get("weapon") or {}).get("ability_modifier") or 0)
    return bonus if bonus > 0 else None


@hook("attack_only_ability_options")
def lightening_ability_option(ctx: Any) -> dict[str, dict[str, Any]] | None:
    """Body Lightening shares its eligibility with per-strike choices.

    The printed permission has no 'if higher' requirement: a player's lower
    legal key choice stays available. The named option never grants a damage
    substitution. Sealed old rows already contain the key modifier, so no sheet
    recompilation or guessed ability identity is needed on cold load.
    """
    key = _lightening_modifier(ctx, ctx.actor)
    if key is None:
        return None
    return {"gravity_key": {"modifier": key, "label": "your Gravity key ability"}}


def _light_weapon(ctx: Any) -> bool:
    """An Unarmed Strike, a simple melee weapon, a spear, a blade (sword), a saber or a staff (the printed list; "other GM-approved
    mobile martial weapon" stays the GM's)."""
    from .weapon_hits import weapon_has_family, weapon_identity, weapon_item

    attack = getattr(ctx, "attack_effect", None) or {}
    if attack.get("attack_kind") == "unarmed" or ".natural." in weapon_identity(ctx) or ".unarmed." in weapon_identity(ctx):
        return True
    if any(weapon_has_family(ctx, word) for word in ("spear", "staff", "blade", "saber")):
        return True
    item = weapon_item(ctx)
    return str(item.get("proficiency") or "").lower() == "simple"


@hook("turn_end")
def remember_movement(engine: Any, actor: Any) -> None:
    """Body Heavying's "If you do not move more than half your Speed on your turn" for a hit made on another creature's turn."""
    if row(engine, actor, "weight_shift") is not None and _own_turn(engine, actor):
        actor.turn_flags[LAST_MOVED] = f"{_moved(engine, actor)}:{engine._effective_speed(actor)}"


def _moved_too_far(engine: Any, actor: Any) -> bool:
    if _own_turn(engine, actor):
        return _moved(engine, actor) > engine._effective_speed(actor) // 2
    moved, _, speed = str(actor.turn_flags.get(LAST_MOVED) or "0:0").partition(":")
    return int(moved or 0) > int(speed or 0) // 2


@hook("after_hit")
def heavying_first_hit(ctx: Any, target: Any, kind: str) -> None:
    """Body Heavying: "the first melee weapon attack or Unarmed Strike you hit with before the start of your next turn deals
    additional damage equal to your Proficiency Bonus" (the attack's own damage type)."""
    engine, actor = ctx.engine, ctx.actor
    if row(engine, actor, "weight_shift") is None or kind not in ("unarmed", "weapon") or not _melee(ctx) or not target.active:
        return
    state = _on(engine, actor, HEAVY) or _on(engine, actor, MOON)
    if state is None or actor.turn_flags.get(HEAVY_HIT) == state.instance_id:
        return
    if _moved_too_far(engine, actor):
        return
    actor.turn_flags[HEAVY_HIT] = state.instance_id
    weapon = ctx.typed.get("weapon") or {}
    kind_of = str(weapon.get("damage_type") or "bludgeoning").lower() if kind == "weapon" else "bludgeoning"
    from .. import typed_executor as te

    te.run_effects(_ctx(ctx, target), [{"type": "extra_damage", "applies_to": "target", "formula": "pb", "damage_types": [kind_of],
                                        "evidence": "Body Heavying: the first melee hit deals extra damage equal to your Proficiency Bonus"}])


@hook("speed")
def mode_speed(engine: Any, actor: Any) -> int | None:
    """Gravitic Armor: Body Lightening's Speed +10 more.  Moon-Weight Incarnation: Body Heavying does not reduce Speed.  Feather Body:
    Body Lightening's increase is 15 feet."""
    extra = 0
    if row(engine, actor, "gravitic_armor") is not None and _on(engine, actor, ARMOR) and _on(engine, actor, LIGHT):
        extra += 10
    if row(engine, actor, "moon_weight_incarnation") is not None and _on(engine, actor, MOON) and _on(engine, actor, HEAVY):
        extra += 5
    if row(engine, actor, "feather_body") is not None and _on(engine, actor, LIGHT):
        extra += 5  # Feather Body: "Your Speed increase becomes 15 feet" (Body Lightening's own is 10)
    return extra or None


# ------------------------------------------------------------------------------------------------ Weighted Strike
def dice_count(cl: int) -> int:
    return 4 if cl >= 17 else 3 if cl >= 11 else 2 if cl >= 5 else 1


def _free_lightening(ctx: Any, actor: Any) -> str:
    """Why this hit's Lightening Blow costs nothing, or ''."""
    engine = ctx.engine
    if ctx.damage_cache.get(COUNTER_FREE):
        return "Moon-Falling Counter"
    if not mode(engine, actor, LIGHT) or not _own_turn(engine, actor):
        return ""
    moved = _moved(engine, actor)
    if row(engine, actor, "light_body_rush") is not None and moved >= 20:
        return "Light Body Rush"
    if row(engine, actor, "light_body_flurry") is not None and moved >= 10 and not actor.turn_flags.get(FLURRY):
        return "Light-Body Flurry"
    return ""


def _heavy_sides(ctx: Any, actor: Any, kind: str) -> int:
    sides = 6
    weapon = ctx.typed.get("weapon") or {}
    if row(ctx.engine, actor, "heavy_weapon_body") is not None and (kind == "unarmed" or "two-handed" in str(weapon.get("properties") or "").lower()):
        sides = 8  # Heavy Weapon Body: "from d6s to d8s" with a two-handed melee weapon or an Unarmed Strike
    if row(ctx.engine, actor, "gravitic_armor") is not None and _on(ctx.engine, actor, ARMOR):
        sides = {6: 8, 8: 10}[sides]  # Gravitic Armor: "damage dice increase by one step, from d6 to d8 or from d8 to d10"
    return sides


@hook("after_hit_choice")
def weighted_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    owned = row(engine, actor, "weighted_strike")
    if owned is None or kind not in ("unarmed", "weapon") or not _melee(ctx) or not target.active:
        return
    hammer = row(engine, actor, "falling_hammer") is not None and _held(engine, actor, DESCENT)
    if not (hammer or mode(engine, actor, LIGHT) or mode(engine, actor, HEAVY)) or actor.turn_flags.get(WS_TURN) == _turn(engine):
        return
    moon = row(engine, actor, "moon_weight_incarnation") is not None and _on(engine, actor, MOON)
    moon_free = moon and _own_turn(engine, actor) and actor.turn_flags.get(MOON_FREE) != _turn(engine)
    light_free = _free_lightening(ctx, actor)
    blows = [("heavying", "Heavying Blow")]
    if row(engine, actor, "anchor_breaking_palm") is not None:
        blows.append(("disrupt", "Heavying Blow, disrupting its footing (Anchor-Breaking Palm)"))
    blows.append(("lightening", "Lightening Blow"))
    if moon and actor.turn_flags.get(MOON_BOTH) != int(engine.state.round_number):
        blows.append(("both", "Heavying and Lightening Blow (Moon-Weight Incarnation)"))
    options, labels = [], {}
    pools = payable(actor)
    for key, name in blows:
        why = "Moon-Weight Incarnation" if moon_free else (light_free if key == "lightening" else "")
        if why:
            options.append(f"{key}:free")
            labels[f"{key}:free"] = f"{name}: no cost ({why})"
            continue
        for rid, pool in pools:
            option = f"{key}:{POOL_NAMES[rid]}"
            options.append(option)
            labels[option] = f"{name}: pay 1 {pool}"
    if not options:
        return
    from .needle import ask, checkpoint_id

    n, heavy_sides = dice_count(_cl(owned, ctx)), _heavy_sides(ctx, actor, kind)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Weighted Strike", actor.entity_id, target.entity_id), actor,
                 "choice:needle.gravity_weighted_strike", options, labels=labels, preferred=[options[0]], allow_decline=True,
                 target_id=target.entity_id, name="Weighted Strike", feature_id=str(owned.get("feature_id") or ""),
                 prompt=(f"Weighted Strike: {actor.display_name}'s {ctx.action.display_name} hit {target.display_name}. "
                         f"Heavying Blow adds {n}d{heavy_sides} Force damage and a Strength save (fail: pushed or pulled 5 feet or "
                         f"knocked Prone, your pick; success: no Reactions until the start of its next turn). Lightening Blow adds "
                         f"{n}d6 Force damage and lets you step up to 10 feet with no Opportunity Attack from {target.display_name}. "
                         f"Once per turn."),
                 prompt_context={"source_definition_id": ctx.action.source_definition_id, "action_name": ctx.action.display_name,
                                 "action_actor_id": actor.entity_id, "affected_id": target.entity_id})
    if not picked:
        return
    blow, _, pay = picked[0].partition(":")
    actor.turn_flags[WS_TURN] = _turn(engine)
    source = str(owned.get("feature_id") or "GRAVITY_BASE_WEIGHTED_STRIKE")
    if pay == "free":
        if moon_free:
            actor.turn_flags[MOON_FREE] = _turn(engine)
        elif light_free == "Light-Body Flurry":
            actor.turn_flags[FLURRY] = 1
    else:
        rid = next(r for r, name in POOL_NAMES.items() if name == pay)
        engine._spend_resource(actor, rid, 1, f"passive:{source}")
    if blow == "both":
        actor.turn_flags[MOON_BOTH] = int(engine.state.round_number)
    sub = _ctx(ctx, target)
    if row(engine, actor, "crushing_focus") is not None:
        sub = sub.with_source("GRAVITY_BASE_WEIGHTED_STRIKE")
    if hammer:
        from .. import typed_executor as te

        extra = 2 if _cl(row(engine, actor, "falling_hammer"), ctx) >= 11 else 1
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": extra, "sides": 6},
                              "damage_types": ["force"],
                              "evidence": "Falling Hammer: extra Force damage because the attack came out of a fall"}])
    if blow in ("heavying", "disrupt", "both"):
        _heavying(sub, actor, target, n, heavy_sides, disrupt=blow == "disrupt")
    if blow in ("lightening", "both") and actor.active:
        _lightening(sub, n)


def _heavying(sub: Any, actor: Any, target: Any, n: int, sides: int, *, disrupt: bool) -> None:
    from .. import typed_executor as te

    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": n, "sides": sides}, "damage_types": ["force"],
                          "evidence": "Weighted Strike: Heavying Blow"}])
    if not target.active:
        return
    if disrupt:
        te.run_effects(sub, [{"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target",
                              "on_fail": [{"type": "gravity_footing", "applies_to": "target"}],
                              "on_success": [{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": "START_OF_TARGET_NEXT_TURN",
                                              "evidence": "Anchor-Breaking Palm: Speed -10 until the start of its next turn"}],
                              "evidence": "Anchor-Breaking Palm: Strength saving throw"}])
        return
    dense = row(sub.engine, actor, "ten_thousand_weight_body") is not None and _on(sub.engine, actor, TEN)
    feet = 10 if dense else 5
    moves = {"type": "rider_menu", "id": "gravity_heavying_move" if dense else "gravity_heavying", "count": 1,
             "label": f"Heavying Blow: push or pull {target.display_name} {feet} feet" + ("" if dense else ", or knock it Prone"),
             "options": [{"id": "push", "label": f"Push it {feet} feet away", "effects": [
                             {"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}]},
                         {"id": "pull", "label": f"Pull it {feet} feet toward you", "effects": [
                             {"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "toward"}]}]}
    prone = {"type": "condition", "condition": "prone", "applies_to": "target", "evidence": "Heavying Blow: knocked Prone"}
    if dense:  # Ten-Thousand-Weight Body: "knocks a target Prone on a failed save and pushes or pulls it 10 feet"
        on_fail = [prone, moves]
    else:
        moves["options"].append({"id": "prone", "label": "Knock it Prone", "effects": [prone]})
        on_fail = [moves]
    te.run_effects(sub, [{"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target", "on_fail": on_fail,
                          "on_success": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target",
                                          "expires_on": "START_OF_TARGET_NEXT_TURN",
                                          "evidence": "Heavying Blow: it cannot take Reactions until the start of its next turn"}],
                          "evidence": "Heavying Blow: Strength saving throw"}])


def _lightening(sub: Any, n: int) -> None:
    from .. import typed_executor as te

    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": n, "sides": 6}, "damage_types": ["force"],
                          "evidence": "Weighted Strike: Lightening Blow"},
                         {"type": "rider_step", "distance_ft": 10, "label": "Lightening Blow"}])


@effect("gravity_footing")
def footing(ctx: Any, eff: dict[str, Any]) -> None:
    """Anchor-Breaking Palm's failed save: no Gravity forced-movement reduction until the start of the user's next turn."""
    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        ctx.engine._remove_condition(subject, FOOTING, ctx.source)
        ctx.engine._apply_condition(subject, FOOTING, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"label": "Footing disrupted"})


# ------------------------------------------------------------------------------------------------ Anchor Stance, Ten-Thousand-Weight
@hook("forced_movement_reduction")
def anchor_reduction(ctx: Any, subject: Any) -> int | None:
    engine = ctx.engine
    if any(c.condition_id == FOOTING for c in subject.conditions.values()):
        return None  # Anchor-Breaking Palm: it cannot benefit from features that reduce forced movement
    if row(engine, subject, "ten_thousand_weight_body") is not None and _on(engine, subject, TEN) and ctx.actor is not subject \
            and _core_or_lower(engine, ctx.actor):
        return 10000  # "You cannot be moved against your will by effects of Core Formation or lower"
    anchor = row(engine, subject, "anchor_stance")
    if anchor is not None and mode(engine, subject, HEAVY):
        from ..falling import supported
        if anchor.get("stopped_focus") and not supported(engine, subject):
            return None
        reduction = 10 + (5 if _mountain_stance(engine, subject) else 0)
        return reduction
    shared = next((c for c in subject.conditions.values() if c.condition_id == ANCHOR_SHARE), None)
    if shared is not None:
        from ..falling import supported
        if shared.data.get("stopped_focus") and not supported(engine, subject):
            return None
        reduction = 10 + (5 if _mountain_stance(engine, subject) else 0)
        return reduction
    return 5 if _mountain_stance(engine, subject) else None


def _core_or_lower(engine: Any, creature: Any) -> bool:
    """A creature whose Cultivation Level the table knows, at Core Formation or below (CL 14 or less: combat/table_advance.py)."""
    from .passive_rows import known_level

    level = known_level(engine, creature)
    return level is not None and level <= 14


@effect("gravity_anchor_share")
def anchor_share(ctx: Any, eff: dict[str, Any]) -> None:
    """Anchor Stance, CL 5: extend the reduction to one willing adjacent ally until the start of your next turn."""
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    allies = sorted((other for other in engine.state.actors.values() if other.active and other is not actor and not _hostile(actor, other)
                     and engine._distance_actor_to_actor(actor, other) <= 5), key=lambda other: other.entity_id)
    if not allies:
        ctx.rider("Anchor Stance: no willing ally is adjacent.")
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Anchor Stance", actor.entity_id), actor, "choice:needle.gravity_anchor_share",
                 [ally.entity_id for ally in allies], labels={ally.entity_id: ally.display_name for ally in allies},
                 allow_decline=True, name="Anchor Stance",
                 prompt=f"Anchor Stance: choose one adjacent ally; forced movement against it is 10 feet shorter until the start of "
                        f"{actor.display_name}'s next turn.")
    for other in engine.state.actors.values():  # one ally at a time
        for condition in list(other.conditions.values()):
            if condition.condition_id == ANCHOR_SHARE and condition.source_actor_id == actor.entity_id:
                engine._remove_condition(other, ANCHOR_SHARE, condition.source_definition_id)
    if picked:
        ally = engine.state.actors[picked[0]]
        engine._apply_condition(ally, ANCHOR_SHARE, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Anchored (Anchor Stance)", **({"stopped_focus": 1} if (row(engine, actor, "anchor_stance") or {}).get("stopped_focus") else {})})
        _say(engine, ctx.source, actor, f"Anchor Stance: {actor.display_name} steadies {ally.display_name}.", (ally,))


def _heavy_lapsed_now(engine: Any, actor: Any) -> bool:
    """Body Heavying lasts "until the start of your next turn": at that same moment it still counts for "When Body Heavying is
    active, you may spend 5 CP or Stamina at the start of your turn" (the sweep may already have taken it off)."""
    from .states import PREFIX

    for event in reversed(engine.events):
        if event.event_type == "TURN_ENDED":
            return False  # the sweep that starts this turn runs after the last turn ended (gate2_engine._system_start_turn)
        if event.event_type == "CONDITION_REMOVED" and (event.payload or {}).get("condition_id") == PREFIX + HEAVY \
                and actor.entity_id in (event.target_ids or ()):
            return True
    return False


@hook("turn_start_choice")
def ten_thousand_weight(engine: Any, actor: Any) -> None:
    """Ten-Thousand-Weight Body: "When Body Heavying is active, you may spend 5 CP or Stamina at the start of your turn"."""
    owned = row(engine, actor, "ten_thousand_weight_body")
    if owned is None or not actor.active or not (mode(engine, actor, HEAVY) or _heavy_lapsed_now(engine, actor)):
        return
    pools = payable(actor, 5)
    if not pools:
        return
    from .needle import ask, checkpoint_id

    options = [POOL_NAMES[rid] for rid, _ in pools]
    picked = ask(engine, None, checkpoint_id(engine, "Ten-Thousand-Weight Body", actor.entity_id), actor, "choice:needle.gravity_ten_thousand",
                 options, labels={POOL_NAMES[rid]: f"Pay 5 {name}" for rid, name in pools}, allow_decline=True, default="decline",
                 name="Ten-Thousand-Weight Body", feature_id=str(owned.get("feature_id") or ""),
                 prompt=(f"Ten-Thousand-Weight Body: {actor.display_name} may become impossibly dense until the start of its next turn: "
                         "it cannot be moved against its will by creatures with a known cultivation level of 14 or lower, creatures that hit it in melee take "
                         "Force damage equal to its Proficiency Bonus, and its Heavying Blow knocks Prone and pushes or pulls 10 feet. "
                         "Afterwards its Speed is 10 feet lower until the end of that turn."))
    if not picked:
        return
    rid = next(r for r, name in POOL_NAMES.items() if name == picked[0])
    source = str(owned.get("feature_id"))
    engine._spend_resource(actor, rid, 5, f"passive:{source}")
    from .states import PREFIX
    from .owned_effects import remove_conditions
    from .effect_durations import token

    remove_conditions(engine, actor, source, actor.entity_id, PREFIX + TEN)
    engine._apply_condition(actor, PREFIX + TEN, source, actor.entity_id,
                            expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
                            data={"label": f"Ten-Thousand-Weight Body: melee attackers take {int(owned.get('pb') or 2)} Force damage; "
                                           "melee damage to objects doubles; Heavying Blow knocks Prone and pushes or pulls 10 feet; "
                                           "blocks forced movement from creatures with known cultivation level 14 or lower. "
                                           "Ends at the start of your next turn, then Speed is 10 feet lower until that turn ends. "
                                           "Paid 5 CP or Stamina (your technique energy); no extra cost for these benefits",
                                  "name": TEN})
    _say(engine, source, actor, f"Ten-Thousand-Weight Body: {actor.display_name} gains the dense-body benefits until the start of its next turn, "
                              f"spending 5 {POOL_NAMES[rid]} technique-energy points; its Speed is then 10 feet lower until that turn ends.")


@hook("effect_expiring")
def ten_thousand_after(engine: Any, holder: Any, row_: Any) -> None:
    """"After the effect ends, your Speed is reduced by 10 feet until the end of your next turn" (its end is your next turn's start)."""
    from .states import PREFIX

    if getattr(row_, "condition_id", None) != PREFIX + TEN or row(engine, holder, "ten_thousand_weight_body") is None:
        return
    engine._add_modifier(holder, row_.source_definition_id, "speed_ft", "ADD", -10, "ALWAYS", expires_on="END_OF_CURRENT_TURN")
    if engine.state.current_actor_id == holder.entity_id:
        holder.movement_remaining_ft = max(0, int(holder.movement_remaining_ft) - 10)


@hook("after_hit")
def ten_thousand_retort(ctx: Any, target: Any, kind: str) -> None:
    """"Creatures that hit you with melee attacks take Force damage equal to your Proficiency Bonus.\""""
    engine, attacker = ctx.engine, ctx.actor
    if row(engine, target, "ten_thousand_weight_body") is None or not _on(engine, target, TEN) or not _melee(ctx) or not attacker.active:
        return
    from .. import typed_executor as te

    owned = row(engine, target, "ten_thousand_weight_body")
    sub = _owner_ctx(engine, target, str(owned.get("feature_id")), attacker, ctx.intent, str(owned.get("name") or ""))
    te.run_effects(sub, [{"type": "damage", "applies_to": "target", "flat": int(owned.get("pb") or 2), "damage_types": ["force"],
                          "evidence": "Ten-Thousand-Weight Body: a melee attacker takes Force damage equal to your Proficiency Bonus"}])


# ------------------------------------------------------------------------------------------------ answers to a missed melee attack
def _missed_in_melee(ctx: Any, target: Any, spec: dict[str, Any]) -> bool:
    from .needle import incapacitated

    if not target.active or incapacitated(target) or not ctx.actor.active or not _hostile(target, ctx.actor):
        return False
    if "ranged" in str((getattr(ctx, "attack_effect", None) or {}).get("attack_kind") or ""):
        return False
    return spec.get("range_ft") is None or int(spec.get("range_ft") or 0) <= 5 or ctx.engine._distance_actor_to_actor(target, ctx.actor) <= 10


@hook("after_miss_choice")
def orbiting_step(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    """Orbiting Guard: "Once per round when a creature misses you with a melee attack, you may move 5 feet without provoking
    Opportunity Attacks from that creature.\""""
    engine = ctx.engine
    owned = row(engine, target, "orbiting_guard")
    if owned is None or not _on(engine, target, ORBIT) or not _missed_in_melee(ctx, target, spec):
        return
    if target.turn_flags.get(ORBIT_STEP) == int(engine.state.round_number):
        return
    target.turn_flags[ORBIT_STEP] = int(engine.state.round_number)
    from .. import typed_executor as te

    te.run_effects(_owner_ctx(engine, target, str(owned.get("feature_id")), ctx.actor, ctx.intent, str(owned.get("name") or "")),
                   [{"type": "rider_step", "distance_ft": 5, "label": "Orbiting Guard"}])


@hook("ac")
def orbiting_ac(engine: Any, target: Any) -> int | None:
    """Orbiting Guard, CL 5: "the AC bonus becomes +2 while Body Lightening or Body Heavying is active" (+1 more)."""
    owned = row(engine, target, "orbiting_guard")
    if owned is None or _cl(owned) < 5 or not _on(engine, target, ORBIT):
        return None
    return 1 if mode(engine, target, LIGHT) or mode(engine, target, HEAVY) else None


@hook("after_miss_choice")
def orbit_breaking_guard(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    engine, attacker = ctx.engine, ctx.actor
    owned = row(engine, target, "orbit_breaking_guard")
    if owned is None or not _on(engine, target, ORBIT) or not _missed_in_melee(ctx, target, spec):
        return
    round_now = int(engine.state.round_number)
    free = row(engine, target, "gravitic_armor") is not None and _on(engine, target, ARMOR) and target.turn_flags.get(ORBIT_FREE) != round_now
    from ..typed_executor import condition_rules

    reacts = target.reaction_available and not any(r.get("no_reactions") for r in condition_rules(target))
    if not free and not reacts:
        return
    from .needle import ask, checkpoint_id

    cost = "no Reaction (Gravitic Armor, once per round)" if free else "your Reaction"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Orbit-Breaking Guard", target.entity_id, attacker.entity_id), target,
                 "choice:needle.gravity_orbit_breaking", ["pull", "step", "trip"], allow_decline=True, default="decline",
                 labels={"pull": f"Move {attacker.display_name} 10 feet to a space next to you",
                         "step": "Move yourself 10 feet without provoking Opportunity Attacks",
                         "trip": f"{attacker.display_name} makes a Dexterity save or falls Prone"},
                 name="Orbit-Breaking Guard", feature_id=str(owned.get("feature_id") or ""), target_id=attacker.entity_id,
                 prompt=f"Orbit-Breaking Guard ({cost}): {attacker.display_name}'s {ctx.action.display_name} missed {target.display_name}.",
                 prompt_context={"source_definition_id": ctx.action.source_definition_id, "action_name": ctx.action.display_name,
                                 "action_actor_id": attacker.entity_id, "affected_id": target.entity_id})
    if not picked:
        return
    with activation(engine, target, str(owned.get("feature_id"))):
        if free:
            target.turn_flags[ORBIT_FREE] = round_now
        else:
            target.reaction_available = False
        engine._append_event("PASSIVE_TRIGGERED", str(owned.get("feature_id")), actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                             payload={"feature_id": owned.get("feature_id"), "choice": picked[0], "reaction": not free})
        from .. import typed_executor as te

        sub = _owner_ctx(engine, target, str(owned.get("feature_id")), attacker, ctx.intent, str(owned.get("name") or ""))
        if picked[0] == "pull":
            _pull_next_to(sub, target, attacker)
        elif picked[0] == "step":
            te.run_effects(sub, [{"type": "rider_step", "distance_ft": 10, "no_oa": True, "label": "Orbit-Breaking Guard"}])
        else:
            te.run_effects(sub, [{"type": "save", "ability": "dex", "dc": "technique_save_dc", "applies_to": "target",
                                  "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target",
                                               "evidence": "Orbit-Breaking Guard: knocked Prone"}],
                                  "evidence": "Orbit-Breaking Guard: Dexterity saving throw"}])


def _pull_next_to(ctx: Any, me: Any, other: Any) -> None:
    """"Move the attacker 10 feet to an unoccupied space adjacent to you": a legal open space next to you that it can reach in
    10 feet (forced_destination.routes), moved by the engine's own forced path (so it is reduced, resisted and stopped the ordinary
    way) without Opportunity Attacks, chosen by you."""
    from . import forced_destination
    from .needle import checkpoint_id

    cells = forced_destination.routes(ctx.engine, other, 10,
                                      want=lambda cell: ctx.engine.grid.distance_ft(me.position, cell) <= 5)
    if not cells:
        ctx.rider(f"Orbit-Breaking Guard: no open space next to {me.display_name} within 10 feet of {other.display_name}.")
        return
    forced_destination.ask(ctx.engine, ctx.intent, me, other, cells, source=ctx.source, ctx=ctx,
                           checkpoint=checkpoint_id(ctx.engine, "Orbit-Breaking Guard move", me.entity_id, other.entity_id),
                           choice_id="choice:needle.gravity_orbit_breaking_space", name="Orbit-Breaking Guard",
                           prompt=f"Orbit-Breaking Guard: where next to {me.display_name} does {other.display_name} go?")


@hook("after_miss_choice")
def moon_falling_counter(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    engine, attacker = ctx.engine, ctx.actor
    owned = row(engine, target, "moon_falling_counter")
    if owned is None or not mode(engine, target, LIGHT) or not _missed_in_melee(ctx, target, spec):
        return
    from ..typed_executor import condition_rules

    if not target.reaction_available or any(r.get("no_reactions") for r in condition_rules(target)):
        return
    pools = payable(target)
    weapon = _melee_weapon(engine, target)
    if not pools or weapon is None:
        return
    from .needle import ask, checkpoint_id

    options = [POOL_NAMES[rid] for rid, _ in pools]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Moon-Falling Counter", target.entity_id, attacker.entity_id), target,
                 "choice:needle.gravity_moon_falling_counter", options, labels={POOL_NAMES[rid]: f"Use it: Reaction and 1 {name}" for rid, name in pools},
                 allow_decline=True, default="first", name="Moon-Falling Counter", feature_id=str(owned.get("feature_id") or ""),
                 target_id=attacker.entity_id,
                 prompt=(f"Moon-Falling Counter: {attacker.display_name}'s {ctx.action.display_name} missed {target.display_name}. "
                         f"Move up to 10 feet without provoking Opportunity Attacks from {attacker.display_name}, then make one melee "
                         f"attack against it; a hit may add a Lightening Blow at no cost."),
                 prompt_context={"source_definition_id": ctx.action.source_definition_id, "action_name": ctx.action.display_name,
                                 "action_actor_id": attacker.entity_id, "affected_id": target.entity_id})
    if not picked:
        return
    source = str(owned.get("feature_id"))
    with activation(engine, target, source):
        target.reaction_available = False
        rid = next(r for r, name in POOL_NAMES.items() if name == picked[0])
        engine._spend_resource(target, rid, 1, f"reaction:{source}")
        engine._append_event("PASSIVE_TRIGGERED", source, actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                             payload={"feature_id": source, "reaction": True})
        from .. import typed_executor as te
        from ..typed_reactions import attack_reaches, triggered_context

        te.run_effects(_owner_ctx(engine, target, source, attacker, ctx.intent, str(owned.get("name") or "")),
                       [{"type": "rider_step", "distance_ft": 10, "label": "Moon-Falling Counter"}])
        attack = {"type": "attack", "attack_kind": "weapon", "strike_with": "weapon", "count": 1}
        if not attacker.active or not target.active or not attack_reaches(engine, target, attacker, attack, None):
            return
        inner = triggered_context(engine, target, attacker, {"feature_id": weapon.source_definition_id + ".moon_falling_counter",
                                                             "name": "Moon-Falling Counter",
                                                             "numbers": copy.deepcopy(weapon.parameters["typed"]["numbers"]),
                                                             "effects": [attack]}, ctx.intent)
        inner.damage_cache[COUNTER_FREE] = True
        te.run_effects(inner, [attack])


def _melee_weapon(engine: Any, actor: Any) -> Any:
    """Use the same available, readied attack as the shared triggered context."""
    from .weapon_hits import triggered_melee_weapon
    return triggered_melee_weapon(engine, actor)


@hook("damage_source_alias")
def counter_alias(engine: Any, source: str | None) -> str | None:
    """Moon-Falling Counter's attack keeps its weapon's typing (damage type, defenses)."""
    if source and source.endswith(".moon_falling_counter"):
        parent = source[:-len(".moon_falling_counter")]
        return parent if parent in engine.action_catalog else None
    return None


# ------------------------------------------------------------------------------------------------ Mountain-Crushing Step
@hook("after_hit")
def mountain_crushing_hit(ctx: Any, target: Any, kind: str) -> None:
    """"The first creature you hit with a melee attack after moving at least 10 feet must make a Strength saving throw. On a
    failed save, it falls Prone or is pushed 10 feet, chosen by you.\""""
    engine, actor = ctx.engine, ctx.actor
    if row(engine, actor, "mountain_crushing_step") is None or not _on(engine, actor, CRUSH) or not _melee(ctx) or not target.active:
        return
    if actor.turn_flags.get(CRUSH_HIT) or _moved(engine, actor) < 10:
        return
    actor.turn_flags[CRUSH_HIT] = 1
    from .. import typed_executor as te

    sub = _ctx(ctx, target)
    if row(engine, actor, "crushing_focus") is not None:
        sub = sub.with_source("tianxia.talent.gravity.mountain_crushing_step")
    te.run_effects(sub, [{"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target",
                                        "on_fail": [{"type": "rider_menu", "id": "gravity_mountain_step", "count": 1,
                                                     "label": f"Mountain-Crushing Step: knock {target.display_name} Prone or push it 10 feet",
                                                     "options": [{"id": "prone", "label": "Knock it Prone", "effects": [
                                                                     {"type": "condition", "condition": "prone", "applies_to": "target"}]},
                                                                 {"id": "push", "label": "Push it 10 feet away", "effects": [
                                                                     {"type": "forced_movement", "applies_to": "target", "distance_ft": 10,
                                                                      "direction": "away"}]}]}],
                                        "evidence": "Mountain-Crushing Step: Strength saving throw"}])


@hook("technique_used")
def crush_bought(ctx: Any) -> None:
    """Mountain-Crushing Step is bought once a turn."""
    if str(ctx.action.source_definition_id).startswith(f"action:typed.") and ".gravity.mountain_crushing_step." in ctx.action.source_definition_id:
        ctx.actor.turn_flags[CRUSH_HIT + "_bought"] = 1


# ------------------------------------------------------------------------------------------------ Shared Weight
@effect("gravity_share_weight")
def share_weight(ctx: Any, eff: dict[str, Any]) -> None:
    """Shared Weight: "apply the same mode to one willing creature you touch" (two at CL 11).  The mode's own benefit rows, aimed
    at the chosen allies; they end when yours would (the start of your next turn)."""
    from dataclasses import replace

    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    wrapper = next((e for e in ctx.typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "singleton_benefit"), None)
    if wrapper is None:
        return
    rows = []
    for inner in copy.deepcopy(wrapper.get("effects") or []):
        if not isinstance(inner, dict) or inner.get("type") in ("state", "gravity_mode_change"):
            continue
        if inner.get("applies_to") in (None, "self"):
            inner["applies_to"] = "target"
        rows.append(inner)
    allies = sorted((other for other in engine.state.actors.values() if other.active and other is not actor and not _hostile(actor, other)
                     and engine._distance_actor_to_actor(actor, other) <= 5), key=lambda other: other.entity_id)
    if not allies or not rows:
        ctx.rider("Shared Weight: no willing creature is within reach.")
        return
    count = 2 if int(ctx.numbers.get("cl") or 1) >= 11 else 1
    mode_name = str(ctx.typed.get("option_label") or "the same mode")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Shared Weight", actor.entity_id), actor, "choice:needle.gravity_shared_weight",
                 [ally.entity_id for ally in allies], labels={ally.entity_id: ally.display_name for ally in allies},
                 minimum=1, maximum=count, allow_decline=True, name="Shared Weight",
                 prompt=f"Shared Weight: {actor.display_name} gives {mode_name} to up to {count} willing creature(s) it touches.")
    for ally_id in picked:
        ally = engine.state.actors[ally_id]
        te.run_effects(replace(ctx, targets=[ally], target=ally), rows)
        _say(engine, ctx.source, actor, f"Shared Weight: {ally.display_name} gains {mode_name}.", (ally,))


# ------------------------------------------------------------------------------------------------ presentation
@hook("status_description")
def gravity_status(engine: Any, holder: Any, row_: Any, data: Any) -> dict[str, str] | None:
    condition = str((row_ or {}).get("condition_id") or "") if isinstance(row_, dict) else str(getattr(row_, "condition_id", "") or "")
    if condition == FOOTING:
        return {"text": "Footing disrupted (Anchor-Breaking Palm): it gets no benefit from Gravity abilities that shorten forced "
                        "movement against it (Anchor Stance, Ten-Thousand-Weight Body), until the start of the Gravity user's next turn."}
    if condition == ANCHOR_SHARE:
        return {"text": "Anchored (Anchor Stance): pushes and pulls against this creature are 10 feet shorter, until the start of the "
                        "anchoring creature's next turn."}
    return None


# ------------------------------------------------------------------------------------------------ Gravity Well
@effect("gravity_center_prone")
def center_prone(ctx: Any, eff: dict[str, Any]) -> None:
    """Gravity Well: "A creature pulled into the center falls Prone unless it succeeds on a Dexterity saving throw" -- each of the
    activation's creatures whose space now holds the area's centre point makes the save."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position

    centre = ctx.typed.get("_area_centre")
    if not centre:
        return
    point = Position(x=int(centre[0]), y=int(centre[1]))
    moved = set()
    for event in reversed(ctx.engine.events):  # the pulls this activation made
        if event.event_type == "INTENT_ACCEPTED":
            break
        if event.event_type == "MOVEMENT_COMMITTED" and (event.payload or {}).get("forced") and len((event.payload or {}).get("path") or []) > 1:
            moved.add(event.actor_id)
            moved.update(event.target_ids or ())
    pulled = [subject for subject in (ctx.targets or ([ctx.target] if ctx.target else []))
              if subject.active and subject.entity_id in moved and ctx.engine._footprint_intersects(subject, {(point.x, point.y)})]
    if pulled:
        from dataclasses import replace

        te.run_effects(replace(ctx, targets=pulled, target=pulled[0]),
                       [{"type": "save", "ability": "dex", "dc": "technique_save_dc", "applies_to": "target",
                         "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target",
                                      "evidence": "Gravity Well: pulled into the center, it falls Prone"}],
                         "evidence": "Gravity Well: Dexterity saving throw for a creature pulled into the center"}])


# ------------------------------------------------------------------------------------------------ Black-Star Grip, Event Horizon Prison
BLACK_STAR = "tianxia.talent.gravity.black_star_grip"
EVENT_HORIZON = "tianxia.talent.gravity.event_horizon_prison"


def _typed_source(engine: Any, source_id: str) -> str:
    action = engine.action_catalog.get(source_id)
    return str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) or "") if action is not None else ""


@hook("turn_start")
def black_star_pressure(engine: Any, actor: Any) -> None:
    """Black-Star Grip: "While Grappled this way, the target takes Force damage equal to your Proficiency Bonus at the start of each of
    its turns" -- only a Grapple this talent made, while it lasts (its Concentration or the escape ends it)."""
    from .. import typed_executor as te

    for condition in list(actor.conditions.values()):
        if condition.condition_id != "condition:typed.grappled" or _typed_source(engine, condition.source_definition_id) != BLACK_STAR:
            continue
        grappler = engine.state.actors.get(condition.source_actor_id)
        action = engine.action_catalog.get(condition.source_definition_id)
        if grappler is None or not grappler.active or not actor.active:
            continue
        typed = {**(action.parameters.get("typed") or {}), "effects": []}
        te.run_effects(te.Context(engine, grappler, action, None, typed, [actor], actor, {}),
                       [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["force"],
                         "evidence": "Black-Star Grip: Force damage equal to the grappler's Proficiency Bonus at the start of its turn"}])


@hook("teleport_gate")
def event_horizon_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Event Horizon Prison: "Teleportation out of the prison requires a successful opposed Cultivation Check against you. If the
    teleportation fails, the action and resource are spent but the creature remains inside" (a tie keeps it inside)."""
    from .. import zones

    engine, actor = ctx.engine, ctx.actor
    for zone in zones.typed_zones(engine):
        if zone.owner_id == actor.entity_id or _typed_source(engine, zone.source_definition_id) != EVENT_HORIZON:
            continue
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        if (start.x, start.y) not in cells or (destination.x, destination.y) in cells:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active:
            continue
        from copy import copy as copy_ctx

        from . import run as run_hooks
        from .needle import numbers_of

        theirs = numbers_of(engine, owner)
        # The prison is the Gravity effect this check resists, so Gravity Sense's +2 answers here and nowhere else.
        check_ctx = copy_ctx(ctx)
        check_ctx.resists_gravity = zone.source_definition_id
        mine = int(ctx.numbers.get("pb") or actor.proficiency_bonus) + int(ctx.numbers.get("key_mod") or 0) + sum(run_hooks("check_bonus", check_ctx, actor))
        roll = engine.roll_check(modifier=mine, actor_id=actor.entity_id, reason=f'CHECK:{ctx.source}')
        engine._record_roll(roll)
        against = engine.roll_check(
            modifier=int(theirs.get('pb') or owner.proficiency_bonus) + int(theirs.get('key_mod') or 0),
            actor_id=owner.entity_id,
            reason=f'CHECK:{zone.source_definition_id}',
        )
        engine._record_roll(against)
        success = roll.total > against.total
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(owner.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "opponent": against.model_dump(mode="json"),
                                      "success": success, "check": "Cultivation Check (opposed)"})
        _say(engine, zone.source_definition_id, owner,
             f"Event Horizon Prison: {actor.display_name}'s teleport out " + ("breaks free" if success else "fails and it stays inside")
             + f" (opposed Cultivation Check {roll.total} against {against.total}).", (actor,))
        if not success:
            return False
    return None


# ------------------------------------------------------------------------------------------------ flight and falling
# Printed flight and falling lines are read from the native capability tables: a recorded capability (combat/flight.profile,
# combat/falling.settings) is the engine's own way to say "it cannot fly" or "it takes no falling damage", so these rows are
# the same ones Wind-Borne Body and Featherfall already use. Every question below is answered for the creature that owns the
# printed line only, so a creature without a Gravity talent is untouched.
SUPPRESS = "TAL_GRAVITY_FLIGHT_SUPPRESSION"
DOMAIN = "tianxia.talent.gravity.gravity_domain"
HAMMER = "TAL_GRAVITY_FALLING_HAMMER"
REVERSE = "tianxia.talent.gravity.reverse_gravity_step"
SENSE = "tianxia.talent.gravity.gravity_sense"
BORROW = "tianxia.talent.gravity.weight_borrowing_throw"
NO_FLY = "condition:typed.gravity_no_flight"
DIFFICULT = "condition:typed.gravity_difficult_terrain"
HALVED = "condition:typed.gravity_fly_speed_halved"
REVERSED = "condition:typed.gravity_reverse_step"
DESCENT = "gravity_round_descent"  # this turn's own fall, jump down or drop of 10 feet or more (Falling Hammer)
GRAPPLED = "condition:typed.grappled"
FREE_DROP_FT = 30  # Feather Body and Falling Hammer both print "the first 30 feet" of a drop
# A flight provider may ask whether a creature Hovers, which asks the very hook it is running; this set is the one nesting
# depth that answers from what the engine keeps on the creature instead (process state, never saved).
_HOVER_QUERY: set[str] = set()


def _flying(engine: Any, creature: Any) -> bool:
    """Whether the creature can fly right now (its Fly Speed is above 0)."""
    from ..flight import profile

    return profile(engine, creature).speed_ft > 0


def _airborne(engine: Any, creature: Any) -> bool:
    """Whether the creature is off the ground and standing on nothing -- what "a creature flying inside the area" asks for.
    Reads no flight capability, so it never asks the flight hook that is running."""
    from ..falling import supported

    return bool(creature.position.z) and not supported(engine, creature)


def _hover(engine: Any, creature: Any) -> bool:
    """Whether the creature can Hover, without asking the flight hook that is running."""
    from ..flight import profile

    if creature.entity_id in _HOVER_QUERY:
        return bool(creature.hover) or any(c.data.get("flight_hover") for c in creature.conditions.values())
    _HOVER_QUERY.add(creature.entity_id)
    try:
        return profile(engine, creature).hover
    finally:
        _HOVER_QUERY.discard(creature.entity_id)


@hook("flight")
def domain_weight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """"Hostile creatures cannot fly unless they can Hover" inside a Gravity Domain: the pure flight query, so a creature that
    tries to take off inside one has no Fly Speed at all, and the engine drops one that cannot Hover."""
    from .. import zones

    if not actor.active or actor.entity_id in _HOVER_QUERY:
        return None
    for zone in zones.typed_zones(engine):
        if not zone.active or _typed_source(engine, zone.source_definition_id) != DOMAIN:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or owner.team_id == actor.team_id or not engine._in_zone(actor, zone):
            continue
        return None if _hover(engine, actor) else {"flight_disabled": 1}
    return None


def _capability(ctx: Any, subject: Any, eff: dict[str, Any], condition_id: str, data: dict[str, Any], label: str) -> None:
    """Give one creature one recorded capability, replacing this source's earlier copy of the same condition. The row's own
    duration names when it ends (``effect_expiry``, the shared reading of a printed duration)."""
    from ..typed_executor import effect_expiry

    engine = ctx.engine
    for held in list(subject.conditions.values()):
        if held.condition_id == condition_id and held.source_actor_id == ctx.actor.entity_id:
            engine._remove_condition(subject, condition_id, held.source_definition_id)
    engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id,
                            expires_on=effect_expiry(ctx, eff, subject, condition=True),
                            data={**data, "label": label})


@effect("gravity_no_flight")
def no_flight(ctx: Any, eff: dict[str, Any]) -> None:
    """"Its Fly Speed becomes 0" (Flight Suppression) and "it cannot fly" (Heaven's Weight, Weight of the Mountain's line that a
    flying creature that fails the save falls if it cannot Hover): a recorded flight capability, so the engine's own fall check
    drops the creature only when it cannot Hover, exactly as the printed line says. A creature that could not fly anyway is
    left alone."""
    engine = ctx.engine
    label = str(eff.get("label") or "Its Fly Speed is 0 while this lasts, so a creature that cannot Hover falls.")
    for subject in (ctx.targets or ([ctx.target] if ctx.target else [])):
        if not getattr(subject, "active", False) or not _flying(engine, subject):
            continue
        _capability(ctx, subject, eff, NO_FLY, {"fly_speed_zero": 1}, label)


@effect("gravity_half_flight")
def half_flight(ctx: Any, eff: dict[str, Any]) -> None:
    """"Its Fly Speed is halved": the same recorded capability, read by combat/flight.profile as a share of the Fly Speed."""
    label = str(eff.get("label") or "Fly Speed halved while this lasts.")
    for subject in (ctx.targets or ([ctx.target] if ctx.target else [])):
        if getattr(subject, "active", False):
            _capability(ctx, subject, eff, HALVED, {"fly_speed_percent": 50}, label)


def _deferred(engine: Any, source_id: str, kind: str) -> dict[str, Any] | None:
    """One of an ability's own typed rows, kept out of the activation until its printed trigger arrives."""
    action = engine.action_catalog.get(source_id)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return next((dict(row) for row in typed.get("effects") or []
                 if isinstance(row, dict) and row.get("type") == kind and row.get("deferred")), None)


@hook("turn_start")
def flight_suppression(engine: Any, actor: Any) -> None:
    """"Creatures inside the area cannot fly easily. A creature flying inside the area makes a Strength saving throw at the start of
    each of its turns": the area's own save row, run for each creature that starts its turn inside it, off the ground and able
    to fly. A creature standing on the ground is never asked."""
    from .. import typed_executor as te
    from .. import zones

    if not actor.active or not _airborne(engine, actor):
        return
    for zone in zones.typed_zones(engine):
        if not zone.active or _typed_source(engine, zone.source_definition_id) != SUPPRESS:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or not engine._in_zone(actor, zone) or not _flying(engine, actor):
            continue
        save_row = _deferred(engine, zone.source_definition_id, "save")
        if save_row is not None:
            save_row.pop("deferred", None)
            te.run_effects(_owner_ctx(engine, owner, zone.source_definition_id, actor), [save_row])


@hook("falling_damage")
def fall_protection(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """What the Gravity sphere prints about falling damage: Gravitic Armor and Moon-Weight Incarnation make a creature immune
    while they last, Body Lightening takes 5 x Proficiency Bonus off any fall, and Feather Body and Falling Hammer make a drop
    of 30 feet or less free (the first 30 feet they both name). Every answer is bounded by the fall the engine rolled."""
    if getattr(fall, "actor_id", None) != target.entity_id or not target.active or int(defended or 0) <= 0:
        return None
    if (row(engine, target, "gravitic_armor") is not None and _on(engine, target, ARMOR)) \
            or (row(engine, target, MOON) is not None and _on(engine, target, MOON)):
        return {"amount": 0, "land_prone": False}
    if int(getattr(fall, "distance_ft", 0) or 0) <= FREE_DROP_FT and (
            (row(engine, target, "feather_body") is not None and mode(engine, target, LIGHT))
            or (row(engine, target, "falling_hammer") is not None and target.turn_flags.get(DESCENT))):
        return {"amount": 0, "land_prone": False}
    if row(engine, target, "weight_shift") is not None and mode(engine, target, LIGHT):
        off = 5 * int(target.proficiency_bonus or 0)
        if off > 0:
            return {"amount": max(0, int(defended) - off)}
    return None


@effect("gravity_reverse_step")
def reverse_step(ctx: Any, eff: dict[str, Any]) -> None:
    """Reverse Gravity Step: "Until the end of your turn, gravity treats that direction as down for you only ... At the end of the
    turn, normal gravity returns." A recorded condition carrying the engine's own no-falling-damage reading, expiring with the
    turn the printed Duration names, so normal gravity really does return and nothing survives the table commit."""
    label = ("Reverse Gravity Step: this turn's own drops cost no falling damage, because until the end of your turn gravity "
             "treats the direction you move toward as down for you only.")
    _capability(ctx, ctx.actor, eff, REVERSED, {"fall_damage_immune": 1}, label)
    _say(ctx.engine, ctx.source, ctx.actor,
         f"Reverse Gravity Step: {ctx.actor.display_name} treats one direction of their choosing as down until the end of this turn "
         f"(the one they move toward), and this turn's own drops cost no falling damage.")


@hook("stand_cost")
def feather_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Feather Body: "You may stand from Prone by spending only 5 feet of movement" while Body Lightening is active."""
    if row(engine, actor, "feather_body") is None or not mode(engine, actor, LIGHT):
        return None
    return min(5, int(normal_cost))


@hook("check_bonus")
def sense_bonus(ctx: Any, actor: Any) -> int | None:
    """Gravity Sense: "+2 bonus to Cultivation Checks made to identify or resist Gravity effects". Only a check that resists a
    Gravity effect carries the bonus: the resolver names the effect it is answered on (ctx.resists_gravity, the documented
    check_bonus scope field), so an offensive or ability check of the Gravity sphere's own keeps its printed total. There is no
    check to identify an effect on this table, and that half of the line stays printed."""
    if row(ctx.engine, actor, "gravity_sense") is None:
        return None
    resisted = str(getattr(ctx, "resists_gravity", "") or "")
    action = ctx.engine.action_catalog.get(resisted)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return 2 if resisted and typed.get("sphere") == "tianxia.sphere.gravity" else None


@hook("event", nested=True)
def record_descent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Falling Hammer's trigger: "When you fall or descend at least 10 feet before hitting a creature with a melee attack on the
    same turn" -- the shared descent stamp, asked for the printed 10 feet (a five-foot step down is not enough)."""
    from .descent_steps import FALL_FT, stamp
    from .descent_steps import dropped as descended

    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active or row(engine, mover, "falling_hammer") is None:
        return
    if descended(kwargs.get("payload") or {}, minimum_ft=FALL_FT):
        stamp(engine, mover, DESCENT)


@hook("after_save_resolved")
def weight_borrowing_throw(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"When you successfully Shove or Grapple a creature while Body Heavying is active, you may spend 1 CP or Stamina to move the
    target 5 feet in any horizontal direction or knock it Prone" -- 10 feet when the target is already Grappled by you. A Shove or
    Grapple option resolves as one saving throw the target makes, so a failed save is a successful throw and this rides the
    engine's own report of that outcome. The move is forced movement: every legal square the target could land on within that
    distance is offered (forced_destination.routes), so any direction on the grid -- at the target's own height -- is a choice,
    and the engine's own forced path carries it out, so the target's forced-movement defenses and per-step checkpoints apply just
    as they do to the Shove that bought it. It costs the target no movement and provokes no Opportunity Attack."""
    engine, actor = ctx.engine, ctx.actor
    owned = row(engine, actor, "weight_borrowing_throw")
    target = subject
    if owned is None or not failed or not target.active or not mode(engine, actor, HEAVY):
        return
    if str(ctx.typed.get("unarmed_option") or "") not in ("grapple", "shove_push", "shove_prone"):
        return
    pools = payable(actor)
    if not pools:
        return
    from .. import typed_executor as te
    from . import forced_destination
    from .needle import ask, checkpoint_id

    held = any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id for c in target.conditions.values())
    feet = 10 if held else 5
    options, labels = [], {}
    for rid, pool in pools:
        options.append(POOL_NAMES[rid])
        labels[POOL_NAMES[rid]] = f"Pay 1 {pool}: move it {feet} feet or knock it Prone"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Weight-Borrowing Throw", actor.entity_id, target.entity_id), actor,
                 "choice:needle.gravity_weight_borrowing", options, labels=labels, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Weight-Borrowing Throw", feature_id=str(owned.get("feature_id") or ""),
                 prompt=(f"Weight-Borrowing Throw: {actor.display_name}'s {ctx.action.display_name} moved {target.display_name}. Spend 1 CP "
                         f"or Stamina to move it {feet} feet in any horizontal direction, or knock it Prone"
                         + (f" (it is already Grappled by you, so the move is {feet} feet)." if held else ".")))
    if not picked:
        return
    rid = next(rid for rid, name in POOL_NAMES.items() if name == picked[0])
    engine._spend_resource(actor, rid, 1, f"passive:{owned.get('feature_id')}")
    sub = _ctx(ctx, target)
    # "This movement is forced movement": the target's own reductions, reactions and per-step checkpoints are the
    # engine's, so they are asked by the forced path that carries the move out, not here.
    cells = forced_destination.routes(engine, target, feet)

    def knock_prone() -> None:
        te.run_effects(sub, [{"type": "condition", "condition": "prone", "applies_to": "target",
                             "evidence": "Weight-Borrowing Throw: or knock it Prone"}])

    choice = forced_destination.ask(
        engine, ctx.intent, actor, target, cells, source=ctx.source,
        checkpoint=checkpoint_id(engine, "Weight-Borrowing Throw move", actor.entity_id, target.entity_id),
        choice_id="choice:needle.gravity_weight_borrowing_move", name="Weight-Borrowing Throw",
        target_id=target.entity_id, ctx=sub,
        prompt=(f"Weight-Borrowing Throw: {actor.display_name}'s {ctx.action.display_name} moved {target.display_name}. Which square "
                f"does {target.display_name} end on, up to {feet} feet from where it is, or is it knocked Prone?"),
        also=(("prone", "Knock it Prone", knock_prone),))
    if choice is None and cells:
        sub.rider(f"Weight-Borrowing Throw: nothing moves {target.display_name}.")


@effect("gravity_difficult_terrain")
def difficult_terrain(ctx: Any, eff: dict[str, Any]) -> None:
    """"it treats the area as difficult terrain until the start of its next turn" (Local Down's successful save): each walking
    step inside that area costs twice as much, which is what ``movement_step_surcharge`` already charges a crawling mount.
    Nothing about the area is stored on the creature -- the condition already names the ability that made the ground
    difficult, and the surcharge is asked again for every step."""
    label = str(eff.get("label") or "Difficult terrain: while it stands in this area, each step of walking costs double.")
    for subject in (ctx.targets or ([ctx.target] if ctx.target else [])):
        if getattr(subject, "active", False):
            _capability(ctx, subject, eff, DIFFICULT, {}, label)


@hook("movement_step_surcharge")
def difficult_ground(engine: Any, actor: Any, mode: str) -> int | None:
    """The cost of walking where an effect has made the ground difficult: one extra foot per foot walked, and only while the
    creature stands inside the area that made it difficult -- the printed rule limits the difficult ground to that area, so a
    creature that walks out of it, or is moved elsewhere, walks at its ordinary cost again."""
    if mode != "walk":
        return None
    from .. import zones

    for condition in actor.conditions.values():
        if condition.condition_id != DIFFICULT:
            continue
        for zone in zones.typed_zones(engine):
            if zone.active and zone.source_definition_id == condition.source_definition_id and engine._in_zone(actor, zone):
                return engine.grid.square_size_ft
    return None


# A2GRAVITY: these providers are inert without their newly sealed passive rows.
def _mountain_stance(engine: Any, actor: Any) -> bool:
    from ..falling import supported
    return bool(actor.active and row(engine, actor, "mountain_stance") is not None
                and mode(engine, actor, HEAVY) and supported(engine, actor))


@hook("size_steps")
def mountain_stance_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role == "act" and creature is not None and purposes and purposes & {"grapple", "shove"} and _mountain_stance(engine, creature):
        return 1
    return None


@hook("save")
def mountain_stance_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if named and set(named) & {"forced_movement", "prone"} and _mountain_stance(ctx.engine, subject):
        return {"modes": ["ADVANTAGE"]}
    return None


@hook("falling_damage_distance")
def hammer_fall_distance(engine: Any, actor: Any, distance_ft: int, fall: Any, intent: Any) -> int | None:
    """Printed first-thirty-feet protections, before dice and ordinary defenses; opt-in sealed on new rows."""
    hammer = row(engine, actor, "falling_hammer") or {}
    feather = row(engine, actor, "feather_body") or {}
    protected = hammer.get("first_thirty_feet") or (feather.get("first_thirty_feet") and mode(engine, actor, LIGHT))
    if actor.active and protected and fall.actor_id == actor.entity_id:
        return max(0, distance_ft - 30)
    return None


@hook("after_save_resolved")
def crushing_focus(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Final failure only; one use across all recipients and all Gravity talents each actual turn."""
    engine, actor = ctx.engine, ctx.actor
    owned = row(engine, actor, "crushing_focus")
    flag = "once_per_turn:gravity_crushing_focus"
    if owned is None or not failed or subject is None or not subject.active or actor.turn_flags.get(flag):
        return
    source = str(ctx.effect_source or ctx.typed.get("source") or "")
    weight_melee = source in {"GRAVITY_BASE_WEIGHTED_STRIKE", "tianxia.talent.gravity.mountain_crushing_step"} and _melee(ctx)
    native_gravity = not ctx.typed.get("sphere") and (source.startswith("tianxia.talent.gravity.")
                     or source.startswith("TAL_GRAVITY_"))
    if not weight_melee and ctx.typed.get("sphere") != "tianxia.sphere.gravity" and not native_gravity:
        return
    from .needle import ask, checkpoint_id, regain_focus, FOCUS
    from .. import typed_executor as te
    from dataclasses import replace
    benefit = "damage"
    if weight_melee and FOCUS in actor.resources and actor.resources[FOCUS] < actor.resource_maximums.get(FOCUS, 1):
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "Crushing Focus", actor.entity_id, subject.entity_id), actor,
                     "choice:needle.gravity_crushing_focus", ["damage", "focus"],
                     labels={"damage": f"Deal {actor.proficiency_bonus} extra Force damage", "focus": "Regain Martial Focus instead"},
                     preferred=["damage"], allow_decline=False, name="Crushing Focus", feature_id="insight.crushing-focus",
                     target_id=subject.entity_id,
                     prompt=f"Crushing Focus: {subject.display_name} failed the save against the Weight Art delivered by {actor.display_name}'s {ctx.action.display_name}. Deal {actor.proficiency_bonus} extra Force damage, or regain Martial Focus instead. Once per turn.")
        benefit = picked[0] if picked else "damage"
    actor.turn_flags[flag] = 1
    _say(engine, "insight.crushing-focus", actor, "Crushing Focus used for this turn.", (subject,))
    if benefit == "focus":
        regain_focus(engine, actor, "insight.crushing-focus", "Crushing Focus")
    else:
        # This independent fixed packet is not the talent's damage roll. Suppress
        # activation potency in a separate cache, leaving the talent's allowance intact.
        te.run_effects(replace(ctx, targets=[subject], target=subject,
                               damage_cache={"_potency_used": True}).with_source("insight.crushing-focus"),
                       [{"type": "damage", "applies_to": "target", "flat": int(actor.proficiency_bonus),
                         "damage_types": ["force"], "evidence": "Crushing Focus: additional Force damage equal to Proficiency Bonus"}])


@hook("forced_movement_reduced")
def _anchor_stopped_focus(ctx: Any, subject: Any, before_ft: int, after_ft: int) -> None:
    """After every reduction, not from a pure quote: an Anchor contribution helped stop this push."""
    if before_ft <= 0 or after_ft != 0:
        return
    from ..falling import supported
    anchor = row(ctx.engine, subject, "anchor_stance")
    shared = any(c.condition_id == ANCHOR_SHARE and c.data.get("stopped_focus") for c in subject.conditions.values())
    own = anchor is not None and anchor.get("stopped_focus") and mode(ctx.engine, subject, HEAVY)
    if not (own or shared) or not supported(ctx.engine, subject) or any(c.condition_id == FOOTING for c in subject.conditions.values()):
        return
    if row(ctx.engine, subject, "ten_thousand_weight_body") is not None and _on(ctx.engine, subject, TEN) \
            and ctx.actor is not subject and _core_or_lower(ctx.engine, ctx.actor):
        return
    distance = before_ft
    from .. import typed_reactions
    from .needle import FOCUS, ask, checkpoint_id, regain_focus
    feature = {"feature_id": "TAL_GRAVITY_ANCHOR_STANCE", "name": "Anchor Stance"}
    if FOCUS not in subject.resources or subject.resources[FOCUS] >= subject.resource_maximums.get(FOCUS, 1) \
            or not typed_reactions.can_use_reaction(ctx.engine, subject, ctx.actor, feature):
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "Anchor Stance focus", subject.entity_id), subject,
                 "choice:needle.gravity_anchor_focus", ["focus"], labels={"focus": "Use your Reaction to regain Martial Focus"},
                 allow_decline=True, default="decline", name="Anchor Stance", feature_id=feature["feature_id"],
                 target_id=subject.entity_id,
                 prompt=f"Anchor Stance stopped the {distance}-foot forced movement against {subject.display_name} from {ctx.action.display_name}. Use your Reaction to regain Martial Focus?")
    if not picked:
        return
    typed_reactions.spend_reaction(ctx.engine, subject, feature)
    ctx.engine._append_event("REACTION_RESOLVED", feature["feature_id"], actor_id=subject.entity_id,
                             target_ids=(subject.entity_id,), payload={"name": "Anchor Stance", "regained_focus": True})
    regain_focus(ctx.engine, subject, feature["feature_id"], "Anchor Stance stopped the forced movement")


@hook("repeat_save_scope")
def crushing_focus_repeat(engine: Any, resolution: dict[str, Any]) -> Any:
    """Native condition repeats settle after their outcome rewrites and exact-instance removal."""
    actor = engine.state.actors.get(resolution.get("source_actor_id"))
    target = engine.state.actors.get(resolution.get("holder_id"))
    if actor is None or target is None or row(engine, actor, "crushing_focus") is None:
        return None
    source_id = str(resolution.get("source_definition_id") or "")
    action = engine.action_catalog.get(source_id)
    typed = (action.parameters.get("typed") or {}) if action is not None else {}
    source = str(typed.get("source") or source_id)
    if typed.get("sphere") != "tianxia.sphere.gravity" and not (source.startswith("tianxia.talent.gravity.") or source.startswith("TAL_GRAVITY_")):
        return None
    from contextlib import contextmanager
    from .. import typed_executor as te

    @contextmanager
    def settled():
        yield
        if resolution.get("success") is not False or not actor.active or not target.active:
            return
        intent = getattr(engine, "_active_intent", None)
        ctx = te.Context(engine, actor, action, intent, typed, [target], target, {}) if action is not None else _owner_ctx(engine, actor, source, target, intent)
        crushing_focus(ctx, target, str(resolution.get("ability") or ""), set(resolution.get("named") or ()), True)
    return settled()


@hook("save_mode")
def mountain_stance_native_save(engine: Any, target: Any, ability: str, dc: int, source_id: str, roll_context: Any) -> str | None:
    """The same supported stance covers source-aware native Prone/forced-movement saves."""
    named = set((roll_context or {}).get("named") or ())
    if named & {"prone", "forced_movement"} and _mountain_stance(engine, target):
        return "ADVANTAGE"
    return None
