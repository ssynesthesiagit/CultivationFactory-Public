"""Sovereign Shield-Soul Incarnation and Shield Soul Never Falls (AUTO55, 2026-10-05).

Sphere Compendium, Shield (owner's text: ``APP/authority/typed_mechanics/rules_text.json``):

  Sovereign Shield-Soul Incarnation, TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION
    "For the duration: gain a Fly Speed of 40 feet and Hover; increase Projected Shield Face dimensions by 20 feet
     in width and 10 feet in height; increase Cover Ally range to 60 feet when a clear legal route exists; use
     Active Defense once per round without spending a Reaction or expending Martial Focus; gain one additional
     Reaction each round, usable only for Shield talents; when Active Defense applies, reduce damage from the
     triggering attack by your Proficiency Bonus before Resistance, whether or not you know Interposing Shield;
     Shield Faces created by your talents count as Barriers against physical crossing unless you choose otherwise
     when creating them; ... regain Martial Focus whenever a hostile attack misses because of your Active Defense,
     once per round."
  Shield Soul Never Falls, TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS
    "When you would drop to 0 HP, lose Concentration on a Shield talent, or have your Shield destroyed, choose one:
     drop to 1 HP instead of 0 HP; maintain Concentration until the end of your next turn; suppress the Shield's
     destruction until the end of your next turn; immediately establish one projected Shield Face without spending
     an Action."

What the table did before: the Incarnation's record typed one marker effect, and its two GM lines said the rest was
"not implemented by this face marker" -- no flight, no Hover, no wider Cover Ally, no free Active Defense, no extra
Shield-only Reaction, no damage reduction, no Focus recovery. Wider Faces and their optional Barrier cover were
already played (``shield_faces.py`` reads this Incarnation); this module owns the rest. Shield Soul Never Falls
played only its first of four printed results.

Shared helpers: shield_riders uses available to route destruction through this rescue.

Data does most of the work, so no plug-in logic is duplicated per talent:

* the free Active Defense and the additional Shield-only Reaction are ``reaction_economy`` grants
  (combat/rules/feature_blocks.d/auto55_shield.json), the same rows Adamant Guardian Incarnation and Sovereign of
  Ten Thousand Empty Sleeves use;
* the 60-foot Cover Ally is the Incarnation's own ``state`` effect with ``range_for`` (combat/ext/states.py);
* the wider Faces are the existing ``sovereign_shield_soul`` effect in ``shield_faces.py``.

Documented seams this module answers: ``flight`` (40-foot Fly Speed and Hover), ``incoming_damage`` (the Proficiency
Bonus reduction, taken before Resistance as printed), ``after_miss`` (the Focus recovery, once per round),
``condition_attempt`` (Shield Soul Never Falls' destruction suppression) and ``shield_faces.raise_face`` (its
"immediately establish one projected Shield Face without spending an Action"). Modern 0-HP and destruction
rescues share the existing generic row's persisted once-per-Long-Rest resource.
Inert for a fighter without the
Incarnation's own condition, and without each talent's compiled row
(combat/rules/feature_blocks.d/auto55_shield.json).

Not played, and why: "maintain Concentration until the end of your next turn" needs a seam at the moment a
Concentration save fails. The engine's own rescue path (``save_rescue`` rows in combat/typed_reactions.py) can only
add a numeric bonus that turns a known failure into a success; it cannot say "the save succeeds", and re-granting
Concentration after the fact would not replay from the event log. The failed-save
decision is in locked gate2_engine.py; it needs a rescue seam there.
"""

from __future__ import annotations

from typing import Any

from . import hook, note
from .needle import CHOICE, ask, checkpoint_id
from .shield_faces import SOVEREIGN

INCARNATION = "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION"
NEVER_FALLS = "TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS"
BLOCK = "auto55_shield"
SUPPRESSED = "condition:typed.shield_destruction_suppressed"
HELD = "condition:typed.shield_soul_holds"
ROUND = "shield_soul_round_recovery"
FOCUS = "resource:core.martial_focus"
BROKEN = "shield_broken"
COVER_ALLY = "TAL_SHIELD_COVER_ALLY"


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == kind), None)


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Shield Soul Never Falls' own marker, and the Incarnation's marker plus its two ``reaction_economy`` rows.

    One feature carries one block (combat/typed_reactions.compile_blocks), so the Incarnation's two Reaction grants
    ride out of the same handler rather than a second key: ``combat/ext/reaction_economy.py`` reads rows by ``block``,
    and its own ``while_state`` is what ties them to the Incarnation running.
    """
    if block != BLOCK or spec.get('kind') not in ('incarnation', 'never_falls'):
        return None
    compiled = [{**row, 'block': BLOCK, 'kind': spec['kind'], 'keeps_compiling': True}]
    for grant in spec.get("reaction_grants") or []:
        compiled.append({**row, "block": "reaction_economy", "keeps_compiling": True, **grant,
                         "while_state": str(spec.get("while_state") or ""),
                         "name": "Sovereign Shield-Soul Incarnation"})
    return compiled


def incarnate(engine: Any, actor: Any) -> bool:
    """Whether the Incarnation is running and this fighter owns it (``shield_faces``'s own marker)."""
    return _row(engine, actor, "incarnation") is not None and any(c.condition_id == SOVEREIGN for c in actor.conditions.values())


# --------------------------------------------------------------------------- the Incarnation
@hook("flight")
def incarnated_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """"gain a Fly Speed of 40 feet and Hover" (the native engine owns the movement, the collisions and the expiry)."""
    return {"fly_speed_ft": 40, "flight_hover": 1} if incarnate(engine, actor) else None


@hook("incoming_damage")
def active_defense_reduction(engine: Any, target: Any, pending: int, damage_type: str,
                            source_definition_id: Any, source_actor_id: Any) -> int | None:
    """"when Active Defense applies, reduce damage from the triggering attack by your Proficiency Bonus before
    Resistance, whether or not you know Interposing Shield".

    Reduced from the pending packet, so it lands before the ordinary Resistance step, and only when Active Defense
    answered this very attack roll -- the same question ``shield_riders`` asks.
    """
    if pending <= 0:
        return None
    attack = engine.damage_context()
    if (attack is None or attack.source_id != source_definition_id
            or attack.attacker_id != source_actor_id or attack.target_id != target.entity_id):
        return None  # a standing defense never turns a save or unrelated packet into an attack
    attacker = engine.state.actors.get(str(source_actor_id or ""))
    if attacker is None:
        return None
    from .shield_riders import defender_of

    defender = defender_of(engine, attacker, target)
    if defender is None or not incarnate(engine, defender):
        return None
    return min(pending, int(defender.proficiency_bonus or 0))


@hook("after_miss")
def regain_martial_focus(ctx: Any, target: Any) -> None:
    """"regain Martial Focus whenever a hostile attack misses because of your Active Defense, once per round"."""
    engine, attacker = ctx.engine, ctx.actor
    from .shield_riders import caused_miss, defender_of

    defender = defender_of(engine, attacker, target)
    if (defender is None or not incarnate(engine, defender)
            or attacker.team_id == defender.team_id
            or defender.turn_flags.get(ROUND) == int(engine.state.round_number)
            or not caused_miss(engine, attacker, target)):
        return
    defender.turn_flags[ROUND] = int(engine.state.round_number)
    engine._gain_resource(defender, FOCUS, 1, INCARNATION)
    note(engine, INCARNATION, defender,
         f"Sovereign Shield-Soul Incarnation: {defender.display_name}'s Active Defense protecting {target.display_name} turned {attacker.display_name}'s attack "
         f"aside, so they regain 1 Martial Focus.")


@hook("reaction_reach")
def cover_ally_reaches_sixty(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """"increase Cover Ally range to 60 feet when a clear legal route exists".

    The record's own ``range_for`` only widens compiled *actions*; Cover Ally is a generic Reaction row, so its reach
    is answered here instead. A clear legal route is the engine's own line of sight (the same query that answers
    whether the attack could reach the ally at all), so nothing new is decided here.
    """
    if str(row.get("feature_id") or "") != COVER_ALLY or not incarnate(engine, reactor):
        return None
    return True if engine._distance_actor_to_actor(reactor, other) <= 60 and _clear_route(engine, reactor, other) else None


def _clear_route(engine: Any, reactor: Any, other: Any) -> bool:
    from .. import stealth
    from ..targeting import line_of_effect

    return bool(stealth.sees(engine, reactor, other) and line_of_effect(engine, reactor, target=other))


# --------------------------------------------------------------------------- Shield Soul Never Falls
def available(engine: Any, actor: Any) -> bool:
    """Whether the printed "Once you use Shield Soul Never Falls, you cannot use it again until you finish a Long
    Rest" allows it now. shield_riders uses this to route actual breakage through prevention."""
    return response(engine, actor) is not None


def response(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Use the existing saved generic row's once-per-Long-Rest resource for every trigger."""
    if _row(engine, actor, 'never_falls') is None or any(c.condition_id == HELD for c in actor.conditions.values()):
        return None
    from ..typed_reactions import checkpoint_response

    return checkpoint_response(engine, actor, actor, None, NEVER_FALLS, 'SHIELD_SOUL_RESCUE')


@hook('row_allowed')
def native_rescue_only(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Modern ownership uses one native selection; unmarked saved rows keep their original path."""
    if row.get('feature_id') == NEVER_FALLS and _row(engine, actor, 'never_falls') is not None:
        return None if row.get('native_checkpoint') == 'SHIELD_SOUL_RESCUE' else False
    return None


def use(engine: Any, actor: Any, what: str, *, choices: tuple[str, ...] = ("destruction", "face")) -> str | None:
    """Ask the printed question and carry out the chosen result. None when unavailable or declined."""
    row = response(engine, actor)
    if row is None:
        return None
    labels = {"one_hp": "Drop to 1 Hit Point instead of 0",
              "destruction": "Stop the Shield's destruction until the end of your next turn",
              "face": "Establish one projected Shield Face right away (costs no Action)"}
    from .choice_prompt import action_context

    intent = getattr(engine, '_active_intent', None)
    source = getattr(engine, '_active_action_source_id', '') or ''
    context = action_context(engine, engine.state.actors.get(getattr(intent, 'actor_id', '')), source, actor)
    context['cost'] = 'No Action or resource cost; once per Long Rest'
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "SHIELD_SOUL_NEVER_FALLS", actor.entity_id),
                 actor, CHOICE + "shield_soul_never_falls", list(choices), labels=labels, allow_decline=True,
                 target_id=actor.entity_id,
                 prompt=f"{what} -- Shield Soul Never Falls: choose one rescue (costs no Action)",
                 name="Shield Soul Never Falls", feature_id=NEVER_FALLS, prompt_context=context)
    if not picked:
        return None
    choice = picked[0]
    from ..typed_reactions import commit_checkpoint_response

    commit_checkpoint_response(engine, actor, actor, row, 'SHIELD_SOUL_RESCUE')
    if choice == "destruction":
        from .effect_durations import next_owner_turn, token
        engine._apply_condition(actor, SUPPRESSED, NEVER_FALLS, actor.entity_id, expires_on=token("end", actor.entity_id, next_owner_turn(actor)),
                                data={"label": "Shield Soul Never Falls: the Shield cannot be destroyed until the end of your next turn"})
        text = "keeps the Shield from being destroyed until the end of their next turn"
    elif choice == "face":
        from .shield_faces import pick_edge, raise_face

        edge = pick_edge(engine, getattr(engine, "_active_intent", None), actor,
                         "Shield Soul Never Falls: which side of you does the projected Shield Face stand on?")
        if edge:
            raise_face(engine, actor, edge, NEVER_FALLS, moving=True)
            text = "establishes a projected Shield Face right away, at no cost"
        else:
            text = "declines to establish a projected Shield Face"
    else:
        text = "drops to 1 Hit Point instead of 0"
    note(engine, NEVER_FALLS, actor, f"Shield Soul Never Falls: {actor.display_name} {text}.")
    return choice


@hook('final_damage')
def survive_zero_hp(engine: Any, actor: Any, amount: int, damage_type: str,
                    source_id: str, source_actor_id: str | None, intent: Any) -> dict[str, int] | None:
    """Choose a supported rescue at the real HP boundary, after defenses and before HP commits."""
    from ..damage_allocation import lethal_threshold
    if actor.current_hp <= 0 or lethal_threshold(engine, actor, amount, source_actor_id, source_id=source_id, damage_type=damage_type) < actor.current_hp or amount <= 0:
        return None
    if use(engine, actor, f'{actor.display_name} would drop to 0 Hit Points', choices=('one_hp', 'face')) == 'one_hp':
        return {'hp_floor': 1}
    return None


@hook("condition_attempt")
def suppress_a_broken_shield(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """Shield Soul Never Falls' printed "suppress the Shield's destruction until the end of your next turn".

    Also the already-suppressed case: while the rescue is up, nothing breaks the Shield.
    """
    if str((effect or {}).get("condition") or "") != BROKEN:
        return None
    if effect.get('shield_rescue_excluded') == NEVER_FALLS:
        return None
    if any(c.condition_id == SUPPRESSED for c in subject.conditions.values()):
        return False
    if use(ctx.engine, subject, effect.get('shield_breakage_trigger') or
           f"{subject.display_name}'s Shield would be destroyed") != "destruction":
        return None
    return False


@hook('effect_expiring_choice')
def destruction_resumes(engine: Any, holder: Any, condition: Any) -> None:
    """Suppression delays destruction; it does not repair the Shield permanently."""
    if getattr(condition, 'condition_id', None) != SUPPRESSED:
        return
    from .shield_breakage import resume

    resume(engine, holder, condition, NEVER_FALLS)
