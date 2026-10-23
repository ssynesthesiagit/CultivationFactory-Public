"""Retribution second pass (A2RETRIBUT, 2026-10-10): the printed Counterstrike lines that had no reviewed typing.

Owner text: APP/authority/typed_mechanics/rules_text.json. Reviewed data: authority/typed_mechanics/reviewed_final.d/a2_retribution.json.

combat/ext/counterstrike.py owns the Counterstrike itself (prepare -> trigger -> strike -> Reaction restored) and raises
the documented ``counterstrike_hit`` seam once the strike has hit and the Reaction has been given back. This module
gives the remaining printed Counter talents something to do. No core file names an ability here: each line is reached
through its own reviewed modifier row on the compiled Counterstrike variant, or through its own effect row.

  Clinch             after the Counterstrike hits, spend the Reaction the strike restored to attempt a Grapple through an
                     Unarmed Strike (the shared combat/ext/grapple_attempts attempt, so the ordinary 2024 grapple save and
                     its Strength-or-Dexterity choice stay the engine's).
  Powerful Counter   at preparation, forgo one or more of the remaining attacks of the replaced Attack Action or
                     Multiattack; each forgone attack adds 1d8 to that Counterstrike on a hit. The table cannot track a
                     replaced action's remaining attacks, so it never awards these dice itself: it posts a plain GM
                     reminder (this is the one printed line the lane leaves to the GM; see the lane report).
  Read the Tell      at preparation, choose one creature you can see within 60 feet; until the start of your next turn you
                     have Advantage on Wisdom (Insight) checks made to recognize that creature's immediate intent, feints,
                     combat habits or emotional commitment.
  Set Up             at preparation, make one melee weapon attack or Unarmed Strike against one creature within your reach;
                     on a hit, no damage, and until the start of your next turn that creature must end any movement it
                     willingly makes in a space adjacent to you.

Movement handling
  * Set Up's printed endpoint rule is validated over the COMPLETE route before that route is accepted, never step by
    step. A willing Move candidate whose endpoint is not adjacent to the anchor -- while the mover can still legally
    end adjacent instead -- is refused as a whole through the documented ``candidate_allowed`` whole-route seam, so it
    is never offered and never committed part-way. A route that leaves adjacency and returns is accepted; the printed
    exception ("movement that cannot legally end adjacent to you") is unaffected; forced movement and teleportation are
    not willing moves and pass neither seam.
  * Movement an ability grants does not pass the native candidate list, so it is refused at its FIRST step through the
    documented ``movement_attempt`` seam (movement_steps.context now carries the route's own destination and the
    allowance and mode that actually govern the move). Refusing the first step refuses the whole route, so granted
    movement can no longer stop one square short of an illegal endpoint.
  * Set Up's printed exception ("movement that cannot legally end adjacent") is priced against the allowance that
    actually applies to THIS movement -- the grant's own budget (priced with the grant-aware route builder, terrain,
    dragging and flight included) when an ability granted it, the mover's ordinary allowance otherwise -- never the
    chosen route's geometric length. A granted candidate carries its grant budget in its metadata, so the menu filter
    (``candidate_allowed``) and the executor (``movement_attempt``) price it the same way.
  * An interrupted route is defined: a route cut short by another effect (an Opportunity Attack, a hazard, a forced
    stop) ends where that effect left the mover. That end is not the creature's own chosen endpoint, so Set Up does not
    move the creature back; the restriction simply governs the creature's next willing move.
  * Set Up uses the engine's 10-foot adjacency measurement, matching other printed adjacency checks in this catalogue.
  * The Escape: the creature may use a Bonus Action to attempt to break the Set Up. It makes a Strength (Athletics) or
    Dexterity (Acrobatics) check opposed by the anchor's Strength (Athletics) or Dexterity (Acrobatics) check, and each
    creature chooses which skill to use. The holder and the anchor are both asked through the shared choice transport
    (an AI combatant answers for itself); success ends the condition, failure keeps it.
  * Read the Tell's printed recipient is one creature YOU can see within 60 feet, so a player may name an ally. The
    built-in AI reads a hostile creature it perceives, because the printed purpose is to recognize that creature's
    intent and Court of the Awaiting Blade prints the same extension "to every hostile creature you can see inside
    the Domain rather than only one creature".
  * Powerful Counter is left to the GM, not automated. The printed line needs its Extra Attack or Multiattack
    prerequisite and then forgoes one or more of the REPLACED action's remaining attacks, but this table has no pool of a
    replaced Attack Action's remaining attacks (Counterstrike is its own Action button; Extra Attack/Multiattack are not a
    spendable pool). The plug-in therefore never offers an automated forgo choice and never awards an unearned 1d8: it
    posts a plain GM reminder naming the prerequisite, what to forgo and the 1d8-per-attack damage to apply.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import ask, checkpoint_id

CLINCH = "TAL_RETRIBUTION_CLINCH"
POWERFUL = "TAL_RETRIBUTION_POWERFUL_COUNTER"
TELL = "tianxia.talent.retribution.read_the_tell"
SET_UP = "TAL_RETRIBUTION_SET_UP"

C = "condition:typed."
SET_UP_CONDITION = C + "set_up"
TELL_CONDITION = C + "read_the_tell"
ADJACENT_FT = 10


def _holds(actor: Any, condition_id: str) -> list[Any]:
    return [row for row in actor.conditions.values() if row.condition_id == condition_id]


def _seen(engine: Any, actor: Any, other: Any, feet: int) -> bool:
    """The printed range and sight for one creature: active, within ``feet``, and visible to ``actor``."""
    from .. import stealth

    return bool(other is not None and other.active and other.entity_id != actor.entity_id
                and engine._distance_actor_to_actor(actor, other) <= feet
                and engine._line_of_sight_actor_to_actor(actor, other) and stealth.sees(engine, actor, other))


def _typed(action: Any) -> dict[str, Any]:
    return ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}


def _variant_uses(variant: Any, feature: str) -> bool:
    """Whether the compiled Counterstrike variant this fighter prepared carries one reviewed feature's modifier."""
    modifier = _typed(variant).get("modifier") or {}
    keys = str(modifier.get("id") or "") + "|" + str(modifier.get("name") or "")
    keys += "|" + "|".join(str(value) for value in (_typed(variant).get("modifiers") or []))
    keys += "|" + "|".join(str(value) for value in (getattr(variant, "modifiers", None) or []))
    return feature in keys


# --------------------------------------------------------------------------- Clinch
CLINCH_FLAG = "once_per_counterstrike:clinch"


@effect("retribution_clinch")
def clinch_armed(ctx: Any, eff: dict[str, Any]) -> None:
    """Choosing Clinch at preparation. The grapple itself waits for the hit, and spends the restored Reaction."""
    ctx.actor.turn_flags[CLINCH_FLAG] = "armed"


@hook("counterstrike_hit")
def clinch(engine: Any, actor: Any, variant: Any, other: Any, intent: Any) -> None:
    """Spend the Reaction the Counterstrike just restored to attempt a Grapple through an Unarmed Strike.

    Reached from combat/ext/counterstrike.py AFTER it sets ``reaction_available`` again, so the printed
    "spend the Reaction restored by Counterstrike" is exact rather than a second payment. The chosen
    preparation keeps Clinch armed until the start of the fighter's next turn: the printed talent has no
    once-per-preparation limit, so every Counterstrike hit while it stands may offer it (declining one hit
    does not spend the choice). Each offer is still gated on the struck variant carrying the reviewed Clinch
    modifier and on the Reaction actually being available.
    """
    from .grapple_attempts import attempt, options

    if actor.turn_flags.get(CLINCH_FLAG) != "armed" or not actor.active or not actor.reaction_available:
        return
    if not _variant_uses(variant, CLINCH):
        return
    if other is None or not other.active or other.team_id == actor.team_id:
        return
    if "grapple" not in options(engine, actor, ("grapple",)):
        return
    used = ask(engine, intent, checkpoint_id(engine, "retribution_clinch", other.entity_id), actor,
               "choice:needle.retribution_clinch", ["grapple"],
               labels={"grapple": f"Use Clinch: attempt to Grapple {other.display_name}"},
               prompt=(f"Your Counterstrike hit {other.display_name} and gave your Reaction back. Spend that Reaction to "
                       f"attempt to Grapple it through an Unarmed Strike?"),
               allow_decline=True, target_id=other.entity_id, name="Clinch", feature_id=CLINCH)
    if "grapple" not in used:
        return
    actor.reaction_available = False
    attempt(engine, actor, other, intent, ("grapple",), choice_id="choice:needle.retribution_clinch",
            prompt=f"Clinch: grapple {other.display_name}?")


@hook("counterstrike_prepare")
def powerful_prepare(engine: Any, actor: Any, variant: Any, intent: Any, reflexive: bool) -> None:
    """Explain Powerful Counter to the GM when an ordinary Action prepares it; never award its dice automatically."""
    if reflexive or not _variant_uses(variant, POWERFUL):
        return
    note(engine, POWERFUL, actor, _POWERFUL_REMINDER)


# --------------------------------------------------------------------------- Powerful Counter
# Powerful Counter is left to the GM. The printed line forgoes "one or more of the remaining attacks" of the replaced
# Attack Action or Multiattack and adds 1d8 per attack forgone; this table has no pool of a replaced action's remaining
# attacks (the compiled Counterstrike is its own Action button, and Extra Attack/Multiattack are not tracked as a spendable
# pool), so it can neither consume those attacks nor roll their dice honestly. Rather than award an unearned, uncounted
# 1d8, the plug-in says plainly what the GM must apply.
_POWERFUL_REMINDER = ("Powerful Counter (Prerequisite: Extra Attack or Multiattack): forgo one or more of the remaining "
                      "attacks of the Attack Action or Multiattack you replaced, then add 1d8 to this Counterstrike's "
                      "damage per attack forgone. This table does not track remaining attacks or roll these dice, so the "
                      "GM resolves them.")


@effect("retribution_powerful_counter_choose")
def powerful_choose(ctx: Any, eff: dict[str, Any]) -> None:
    """The same plain GM reminder, for a variant reached through this effect row."""
    note(ctx.engine, POWERFUL, ctx.actor, _POWERFUL_REMINDER)


@hook("attack_mode")
def powerful_focus_advantage(ctx: Any, target: Any) -> str | None:
    """The printed optional Martial Focus payment is offered on the actual Counterstrike roll."""
    if target is None or not _variant_uses(ctx.action, POWERFUL):
        return None
    from .needle import FOCUS, spend_focus

    if int(ctx.actor.resources.get(FOCUS, 0)) < 1:
        return None
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "retribution_powerful_counter_focus", target.entity_id),
                 ctx.actor, "choice:needle.retribution_powerful_counter_focus", ["advantage"],
                 labels={"advantage": "Expend Martial Focus for Advantage"},
                 prompt="Powerful Counter: expend Martial Focus to gain Advantage on this Counterstrike attack roll?",
                 allow_decline=True, target_id=target.entity_id, name="Powerful Counter", feature_id=POWERFUL)
    return "ADVANTAGE" if "advantage" in picked and spend_focus(ctx.engine, ctx.actor, POWERFUL,
                                                                  "Advantage on Powerful Counter") else None


@hook("after_hit")
def _settle_setup_strike(ctx: Any, target: Any, kind: str) -> None:
    probe = getattr(ctx.engine, "_retribution_setup_probe", None)
    if probe is not None and target is not None and target.entity_id == probe.get("target_id"):
        probe["hit"] = True


@effect("retribution_powerful_counter")
def powerful_hit(ctx: Any, eff: dict[str, Any]) -> None:
    """On the hit, remind the GM to apply the dice; the table never adds an unearned, uncounted 1d8 itself."""
    note(ctx.engine, POWERFUL, ctx.actor, _POWERFUL_REMINDER)


# --------------------------------------------------------------------------- Read the Tell
@effect("retribution_read_the_tell")
def read_the_tell(ctx: Any, eff: dict[str, Any]) -> None:
    """At preparation, name the one creature you will read; Advantage on Wisdom (Insight) about it until your next turn."""
    engine, actor = ctx.engine, ctx.actor
    visible = sorted((other for other in engine.state.actors.values() if _seen(engine, actor, other, 60)),
                     key=lambda other: (other.team_id == actor.team_id, engine._distance_actor_to_actor(actor, other),
                                        other.entity_id))
    if not visible:
        ctx.rider("Read the Tell: no creature you can see within 60 feet.")
        return
    preferred = next((other.entity_id for other in visible if other.team_id != actor.team_id), visible[0].entity_id)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "retribution_read_the_tell", actor.entity_id), actor,
                 "choice:needle.retribution_read_the_tell", [other.entity_id for other in visible],
                 labels={other.entity_id: f"Read {other.display_name}" for other in visible}, preferred=[preferred],
                 prompt=("Read the Tell: choose one creature you can see within 60 feet. Until the start of your next "
                         "turn, you have Advantage on Wisdom (Insight) checks about that creature's intent, feints, "
                         "combat habits, or emotional commitment."), target_id=actor.entity_id,
                 name="Read the Tell", feature_id=TELL)
    chosen = next((other for other in visible if picked and other.entity_id == picked[0]), None)
    if chosen is None:
        return
    from .effect_durations import token

    engine._apply_condition(actor, TELL_CONDITION, TELL, actor.entity_id,
                            expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
                            data={"target_id": chosen.entity_id,
                                  "label": f"Read the Tell: Advantage on Wisdom (Insight) checks about {chosen.display_name}"})


@hook("ability_check_mode")
def tell_advantage(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    """The printed scope: Wisdom (Insight) checks about the one creature chosen at preparation."""
    if str(ability or "").upper() != "WIS" or str(skill or "").lower() != "insight":
        return None
    for held in _holds(actor, TELL_CONDITION):
        if against is not None and (held.data or {}).get("target_id") == against.entity_id:
            return "ADVANTAGE"
    return None


@hook("status_description")
def tell_text(engine: Any, holder: Any, row: Any, data: dict[str, Any]) -> dict[str, str] | None:
    if str(getattr(row, "condition_id", "")) != TELL_CONDITION:
        return None
    label = str((data or {}).get("label") or "Read the Tell")
    return {"text": label,
            "handling": "Applies to Wisdom (Insight) checks about that one creature until the start of your next turn."}


# --------------------------------------------------------------------------- Set Up
@effect("retribution_set_up")
def set_up(ctx: Any, eff: dict[str, Any]) -> None:
    """At preparation: one melee weapon attack or Unarmed Strike; on a hit, no damage, and that creature must end its
    next willing movement adjacent to you."""
    engine, actor = ctx.engine, ctx.actor
    from . import counterstrike
    from .. import typed_executor as te

    weapons = counterstrike.weapons(engine, actor)
    if not weapons:
        ctx.rider("Set Up: no melee weapon attack or Unarmed Strike is available.")
        return
    pairs = [(weapon, other) for weapon in weapons for other in engine.state.actors.values()
             if other.active and other.entity_id != actor.entity_id
             and engine._distance_actor_to_actor(actor, other) <= int(weapon.reach_ft or weapon.range_ft or 5)]
    pairs.sort(key=lambda pair: (pair[1].team_id == actor.team_id,
                                 -int((pair[0].parameters or {}).get("expected_damage") or 0),
                                 engine._distance_actor_to_actor(actor, pair[1]), pair[0].source_definition_id,
                                 pair[1].entity_id))
    if not pairs:
        ctx.rider("Set Up: no creature within your reach.")
        return
    pair_ids = [f"{weapon.source_definition_id}|{other.entity_id}" for weapon, other in pairs]
    pair_by_id = {key: pair for key, pair in zip(pair_ids, pairs)}
    preferred = next((key for key, pair in pair_by_id.items() if pair[1].team_id != actor.team_id), pair_ids[0])
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "retribution_set_up", actor.entity_id), actor,
                 "choice:needle.retribution_set_up", pair_ids,
                 labels={key: f"Use {weapon.display_name.removesuffix(' attack')} against {other.display_name}"
                         for key, (weapon, other) in pair_by_id.items()}, preferred=[preferred],
                 prompt=("Set Up: choose a melee weapon attack or Unarmed Strike and a creature within its reach. "
                         "On a hit, it takes no damage and must end each willing movement adjacent to you until the "
                         "start of your next turn."),
                 target_id=actor.entity_id, name="Set Up", feature_id=SET_UP)
    pair = pair_by_id.get(picked[0]) if picked else None
    if pair is None:
        return
    weapon, target = pair
    weapon_typed = _typed(weapon)
    typed = {"weapon": weapon_typed.get("weapon"), "range_ft": None,
             "numbers": {"attack_bonus": int((weapon_typed.get("numbers") or {}).get("attack_bonus") or 0)}}
    probe = {"target_id": target.entity_id, "hit": False}
    engine._retribution_setup_probe = probe
    # "Hit: Deal no damage." The strike still makes its attack roll (it can miss, and it can be dodged), but the printed
    # effect is the Set Up itself, so the weapon's own damage is suppressed through the executor's documented flag.
    try:
        te.run_effects(te.Context(engine, actor, weapon, ctx.intent, typed, [target], target),
                       [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "deferred": False,
                         "no_damage": True, "on_hit": [], "on_miss": []}])
    finally:
        engine._retribution_setup_probe = None
    if not probe["hit"]:
        note(engine, SET_UP, actor, f"Set Up: the strike against {target.display_name} misses, so nothing is set up.")
        return
    from .effect_durations import token

    engine._apply_condition(target, SET_UP_CONDITION, SET_UP, actor.entity_id,
                            expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
                            data={"anchor_id": actor.entity_id,
                                  "label": f"Set Up: must end willing movement adjacent to {actor.display_name}"})


# --------------------------------------------------------------------------- Set Up: complete-route endpoint rule
def _set_up_hold(mover: Any) -> Any | None:
    """The Set Up condition ``mover`` bears, if any (one creature sets it up at a time)."""
    return next((row for row in mover.conditions.values() if row.condition_id == SET_UP_CONDITION), None)


def _set_up_anchor(engine: Any, held: Any) -> Any | None:
    anchor_id = (held.data or {}).get("anchor_id") or held.source_actor_id
    anchor = engine.state.actors.get(str(anchor_id or ""))
    return anchor if anchor is not None and anchor.active else None


def _adjacent(engine: Any, anchor: Any, mover: Any, position: Any) -> bool:
    return engine._distance_actor_to_actor(anchor, mover, target_position=position) <= ADJACENT_FT


def _can_end_adjacent(engine: Any, mover: Any, anchor: Any, allowance: int, *, granted: bool, mode: str = "walk") -> bool:
    """The printed exception: whether the mover can still legally end a willing movement adjacent to the anchor.

    Answered against the allowance that ACTUALLY governs this movement -- the grant's own budget when an ability
    granted the movement, the mover's ordinary allowance otherwise -- never the chosen route's geometric length.
    A granted movement is priced with the grant-aware route builder (``granted_movement.routes``), so terrain,
    dragging, footprint and flight are priced and the mover's ordinary pool is never touched; the builder is
    searched in the movement's own mode, so a walking grant is never told it can end adjacent only by flying. The
    mover's own movement is answered from the engine's native candidate list. Read-only; the answer is cached per (mover,
    position, allowance, kind, mode, anchor, event) so one menu pass asks it once. Never stored in saved state."""
    limit = int(allowance)
    key = (mover.entity_id, mover.position.x, mover.position.y, mover.position.z, limit, bool(granted), str(mode),
           anchor.entity_id, anchor.position.x, anchor.position.y, anchor.position.z, int(engine.state.event_sequence))
    cache = engine.__dict__.setdefault("_retribution_setup_reachable", {})
    if key in cache:
        return cache[key]
    if granted:
        from ..granted_movement import routes

        answer = any(_adjacent(engine, anchor, mover, cell) for cell in routes(engine, mover, limit, mode))
    else:
        answer = any(c.destination is not None and _adjacent(engine, anchor, mover, c.destination)
                     for c in engine._movement_candidates(mover))
    if len(cache) > 8192:
        cache.clear()
    cache[key] = answer
    return answer


def _forbidden_endpoint(engine: Any, mover: Any, destination: Any, allowance: int, *, granted: bool,
                        mode: str = "walk") -> Any | None:
    """The Set Up endpoint rule for one willing route: the held row that forbids ending at ``destination``, or None.

    A route may always end adjacent; it may end elsewhere only when the mover cannot legally end adjacent (the printed
    exception). Forced movement and teleportation never reach this query."""
    for held in _holds(mover, SET_UP_CONDITION):
        anchor = _set_up_anchor(engine, held)
        if anchor is None or _adjacent(engine, anchor, mover, destination):
            continue
        if _can_end_adjacent(engine, mover, anchor, allowance, granted=granted, mode=mode):
            return held
    return None


@hook("candidate_allowed")
def set_up_route_endpoint(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Whole-route Set Up enforcement (A2RETRIBUT review finding 1).

    The complete canonical path's endpoint is validated before the route is accepted, through the documented
    candidate_allowed seam the engine already consults both for the menu and for execution, so an illegal endpoint is
    never offered and never committed part-way. A granted candidate carries its grant budget in
    ``metadata['movement_allowance_ft']`` (``granted_movement.candidates``), so the rule is priced against the grant
    that built it, not the mover's unrelated ordinary allowance. Only MOVE candidates of a creature holding Set Up are
    touched; every other creature and every other candidate returns None."""
    if getattr(candidate.kind, "value", candidate.kind) != "MOVE" or candidate.destination is None:
        return None
    if not _holds(actor, SET_UP_CONDITION):
        return None
    metadata = candidate.metadata or {}
    grant_ft = metadata.get("movement_allowance_ft")
    if grant_ft is None:
        allowance, granted, mode = int(actor.movement_remaining_ft), False, "walk"
    else:
        allowance, granted, mode = int(grant_ft), True, str(metadata.get("movement_mode") or "walk")
    if _forbidden_endpoint(engine, actor, candidate.destination, allowance, granted=granted, mode=mode) is None:
        return None
    return False


@hook("movement_attempt")
def set_up_granted_route(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Set Up enforcement for movement that never passed the candidate list (movement an ability grants).

    movement_steps.context now carries the route's own destination AND the allowance/mode that actually govern the
    movement, so a granted route is judged against its grant's budget on its FIRST step and refused as a whole; a route
    is never stopped one square short of an illegal endpoint, and the mover's ordinary allowance is never borrowed. A
    route cut short by another effect (an Opportunity Attack, a hazard) ends where that effect left it -- not the
    creature's chosen endpoint -- so nothing here moves the creature back."""
    if getattr(intent, "forced", False) or bool((getattr(intent, "payload", None) or {}).get("forced")):
        return None
    from ..movement_steps import context

    movement = context(engine, mover)
    if int(movement.get("travelled_ft") or 0) != 0:
        return None
    destination = movement.get("destination")
    if destination is None:
        return None
    if movement.get("granted"):
        allowance, granted, mode = int(movement.get("allowance_ft") or 0), True, str(movement.get("mode") or "walk")
    else:
        allowance, granted, mode = int(mover.movement_remaining_ft), False, "walk"
    held = _forbidden_endpoint(engine, mover, destination, allowance, granted=granted, mode=mode)
    if held is None:
        return None
    anchor = _set_up_anchor(engine, held)
    return {"stop": True, "source_id": SET_UP_CONDITION,
            "label": f"Set Up: {mover.display_name} must end this movement adjacent to {anchor.display_name}."}


# --------------------------------------------------------------------------- Set Up: the printed Bonus Action escape
BREAK_ACTION = "system:combat.retribution_break_set_up"
_SET_UP_SKILLS = (
    {"kind": "check", "ability": "STR", "skill": "Athletics", "label": "Strength (Athletics)"},
    {"kind": "check", "ability": "DEX", "skill": "Acrobatics", "label": "Dexterity (Acrobatics)"},
)


@hook("match_start")
def _install_break_action(engine: Any) -> None:
    """A Bonus Action the Set Up text gives the held creature, offered only while it bears the condition."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[BREAK_ACTION] = ActionDefinition(
        source_definition_id=BREAK_ACTION, display_name="Break free from Set Up", target_kind="SELF",
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", owner_id="*",
        parameters={"typed": {"effects": [{"type": "retribution_break_set_up"}], "numbers": {},
                              "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "set_up_escape": True,
                    "description": "Use a Bonus Action to make a Strength (Athletics) or Dexterity (Acrobatics) check, "
                                   "opposed by the Set Up creature's check of the same two choices (each of you picks "
                                   "one). Win and the Set Up ends; lose and it stays."})


@hook("additional_actions")
def break_offered(engine: Any, actor: Any) -> list[str]:
    if BREAK_ACTION not in engine.action_catalog or _set_up_hold(actor) is None:
        return []
    return [BREAK_ACTION]


@hook("candidate_allowed")
def break_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or action.source_definition_id != BREAK_ACTION:
        return None
    return _set_up_hold(actor) is not None


@hook("button_description")
def break_button(action: Any) -> str | None:
    parameters = (action or {}).get("parameters") or {}
    return parameters.get("description") if parameters.get("set_up_escape") else None


@effect("retribution_break_set_up")
def break_set_up(ctx: Any, eff: dict[str, Any]) -> None:
    """The printed Bonus Action escape: an opposed Athletics/Acrobatics check, each creature choosing its skill.

    Both creatures are asked through the shared choice transport (contests.select_check), so a player's creature is put
    the question on the holder's turn or on its own, and an AI combatant answers for itself. Success ends the Set Up
    condition; failure keeps it. Nothing is spent beyond the Bonus Action the caller already paid."""
    from ..typed_executor import resolve_opposed_check
    from . import contests
    from .condition_ownership import remove_instance

    engine, holder = ctx.engine, ctx.actor
    held = _set_up_hold(holder)
    if held is None:
        return
    anchor = _set_up_anchor(engine, held)
    if anchor is None:
        remove_instance(engine, holder, held.instance_id, SET_UP)
        ctx.rider("Set Up: the creature keeping you in place is gone, so the Set Up ends.")
        return
    spec = {"options": [dict(row) for row in _SET_UP_SKILLS]}
    ours = contests.select_check(ctx, holder, anchor, spec, "actor", opposing=spec)
    theirs = contests.select_check(ctx, anchor, holder, spec, "target", opposing=ours)
    result = resolve_opposed_check(ctx, anchor, ours, theirs)
    mine_total = int(result.actor.total)
    theirs_total = int(result.target.total) if result.target is not None else 0
    check = f"{ours.get('label')} {mine_total} against {theirs.get('label')} {theirs_total}"
    if result.success:
        remove_instance(engine, holder, held.instance_id, SET_UP)
        note(engine, SET_UP, holder,
             f"Set Up: {holder.display_name} breaks free of {anchor.display_name}'s hold ({check}).", (anchor,))
    else:
        note(engine, SET_UP, holder,
             f"Set Up: {holder.display_name} fails to break free of {anchor.display_name}'s hold ({check}).", (anchor,))


@hook("status_description")
def set_up_text(engine: Any, holder: Any, row: Any, data: dict[str, Any]) -> dict[str, str] | None:
    if str(getattr(row, "condition_id", "")) != SET_UP_CONDITION:
        return None
    label = str((data or {}).get("label") or "Set Up")
    return {"text": label,
            "handling": ("Until the start of the Set Up creature's next turn, this creature must end any movement it "
                         "willingly makes in a space adjacent to it. It may use a Bonus Action to make a Strength "
                         "(Athletics) or Dexterity (Acrobatics) check, opposed by the Set Up creature's Strength "
                         "(Athletics) or Dexterity (Acrobatics) check (each picks one); a win ends the Set Up. Forced "
                         "movement, teleportation and movement that cannot legally end adjacent are unaffected.")}
