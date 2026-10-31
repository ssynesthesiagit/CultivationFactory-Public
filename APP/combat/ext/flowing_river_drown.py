"""Drown the Killing Intent (Flowing River, CL 17+): a melee miss while Dodging forces the attacker's Wisdom save.

Printed (authority/typed_mechanics/rules_text.json): "When a creature misses you with a melee attack while you are
benefiting from Dodge, you may force that creature to make a Wisdom saving throw. Failed Save: Until the start of its
next turn, the creature cannot willingly make another attack against you unless you are the only creature it can
perceive as a legal target. Successful Save: The creature has Disadvantage on the next attack roll it makes against you
before the start of its next turn. A creature immune to the Frightened condition has Advantage on this saving throw,
but the effect is not the Frightened condition."

Why it needed a plug-in: the creature that saves is the attacker, the creature that decides is the defender, and the
question is asked after the attack has already resolved. That is the off-turn shape Turning Guard and Current Between
Steps already use (combat/ext/bodyb_choices.py, combat/ext/flowing_second_pass.py), and no typed row of its own can
ask a third party's owner first.

What stays data. The record's own save row is run here unchanged: its ability, ``basis: cultivation`` (the defender's
Cultivation Save DC, combat/save_dcs.py) and ``advantage_if_immune: frightened``, which combat/typed_executor.py
already reads. Its success branch is the general ``attack_bar`` (combat/ext/move_limits.py) with ``avoid: "source"``,
so the "Disadvantage on the next attack roll it makes against you" is the same ``attack_mode_vs`` row Headsman's Red
Line writes, spent by that one roll. The printed "Prerequisite: CL 17+" is the record's own ``min_cl``, which gates
the character's admission to the talent; this file does not repeat the number.

Why the failure branch is not the general ``creature_bar``. Every other "cannot willingly attack you" row uses
``creature_bar` with ``{"attack": "source"}`` and combat/ext/charm_rules.py vetoes the attack outright. This talent's
printed rule carries an exception -- "unless you are the only creature it can perceive as a legal target" -- and a bar
that cannot be lifted would forbid an attack the printed rule allows, so the bar is its own condition and both of its
vetoes read the exception (below) instead.

How the ban runs. A failed save puts one condition on the attacker; the creature that imposed it is the condition's
source, so the marker itself carries the whole rule and no fight state is added. ``candidate_allowed`` then leaves an
attack aimed at that defender out of what the attacker is offered, and ``opportunity_allowed`` refuses its Opportunity
Attack against the defender -- both only while the attacker perceives some other creature it could legally attack. The
The existing ``attack_allowed`` seam rechecks the ban at each typed strike. Native multi-attack actions
re-enter their per-strike resolver, which consults the same seam, so a failed save can stop the next strike without
rebuilding candidates or interrupting the declared attack sequence.

The one reading the printed words leave to the table, declared on the record's rider: "the only creature it can
perceive as a legal target" is answered from the engine's own perception query (sight or a pinpointing sense,
combat/target_knowledge.py) over the other active creatures on a different side. A creature the attacker cannot
perceive therefore never lifts the ban, and a multi-target attack that would also catch the defender is omitted whole
rather than split.

The declaration row (``river_second_pass`` with this talent's ``kind``) is what makes the talent visible to a compiled
character: it emits the ``typed_passive_rows`` entry read here, exactly as Ten Thousand Edges Find No Center does, so
this file needs no feature block and no core dispatch. Without ownership nothing is asked and no row is written.
"""

from __future__ import annotations

from typing import Any
from contextvars import ContextVar

from . import effect, hook

_LEGALITY_QUERY = ContextVar("drown_legality_query", default=False)

FEATURE = "TAL_FLOWING_RIVER_DROWN_THE_KILLING_INTENT"
KIND = "drown_the_killing_intent"
BAR = "condition:typed.river_drowning_intent"
BAR_EFFECT = "drown_kill_intent"
DODGE = "condition:core.dodge"
ASK = "choice:needle.river_drown"
NAME = "Drown the Killing Intent"


def records(engine: Any, holder: Any) -> list[dict[str, Any]]:
    """The bans this talent holds on ``holder``, newest last; empty for every other creature.

    Public so a shared helper or a test can read the ban without touching a private function.
    """
    if holder is None:
        return []
    return [{"instance_id": key, "blocker_id": str(condition.source_actor_id or ""), **(condition.data or {})}
            for key, condition in holder.conditions.items() if condition.condition_id == BAR]


def _record() -> dict[str, Any]:
    """This talent's reviewed record in the built authority, so the save and its gate stay data."""
    from ..typed_numbers import authority_mechanics

    return dict(authority_mechanics().get(FEATURE) or {})


def _save_row(record: dict[str, Any]) -> dict[str, Any] | None:
    return next((dict(row) for row in record.get("effects") or []
                 if isinstance(row, dict) and row.get("type") == "save"), None)


def _owns(engine: Any, holder: Any) -> bool:
    """Whether this talent's compiled declaration is on ``holder`` (see flowing_second_pass.compile_declarations)."""
    return any(row.get("block") == "river_second_pass" and row.get("kind") == KIND
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(holder.entity_id, []))


def _other_legal_target(engine: Any, actor: Any, blocker: Any) -> bool:
    """Whether the shared candidate pipeline offers any perceived attack on another creature."""
    from ..target_knowledge import located, is_attack

    alternatives = [other for other in engine.state.actors.values()
                    if other.active and other is not actor and other is not blocker
                    and other.team_id != actor.team_id and located(engine, actor, other)]
    if not alternatives:
        return False
    actions = [action for source, action in engine.action_catalog.items()
               if source in actor.action_ids and is_attack(action)]
    pairs = [(action.source_definition_id, other.entity_id)
             for action in actions for other in alternatives]
    if not pairs:
        return False
    # The shared availability query evaluates geometry, range, battlefield
    # eligibility, condition bars and every other candidate gate for this actor.
    from ..action_legality import available_targets_for_actor

    token = _LEGALITY_QUERY.set(True)
    try:
        available = available_targets_for_actor(
            engine, actor.entity_id, (action.source_definition_id for action in actions),
            during_attack=True)
    finally:
        _LEGALITY_QUERY.reset(token)
    alternative_ids = {other.entity_id for other in alternatives}
    return any(target_id in alternative_ids for _, target_id in available)


def barred(engine: Any, actor: Any, target: Any) -> bool:
    """True when ``actor`` may not willingly attack ``target`` right now: the printed ban, exception included."""
    if target is None or actor is None:
        return False
    return any(record.get("blocker_id") == target.entity_id and _other_legal_target(engine, actor, target)
               for record in records(engine, actor))


@hook("after_miss_choice")
def drown_the_killing_intent(ctx: Any, target: Any, attack: dict[str, Any]) -> None:
    """Ask the Dodging defender on any resolved melee miss, then run its Wisdom save."""
    engine, attacker = ctx.engine, ctx.actor
    from .flowing_second_pass import melee, missed_attack

    if target is None or not target.active or not attacker.active or attacker.team_id == target.team_id:
        return
    if not _owns(engine, target) or not melee(ctx):
        return
    if not any(condition.condition_id == DODGE for condition in target.conditions.values()):
        return
    save = _save_row(_record())
    if save is None:
        return
    from . import needle

    picked = needle.ask(engine, ctx.intent,
                        needle.checkpoint_id(engine, "river_drown", target.entity_id, attacker.entity_id),
                        target, ASK, ["use"], labels={"use": f"Force {attacker.display_name}'s Wisdom saving throw"},
                        name=NAME, feature_id=FEATURE, target_id=attacker.entity_id, allow_decline=True,
                        prompt=f"{NAME}: {missed_attack(ctx, target)} Force {attacker.display_name} to make a Wisdom "
                               "saving throw? On a failure it cannot willingly make another attack against you until "
                               "the start of its next turn; on a success its next attack roll against you has "
                               "Disadvantage.")
    if not picked:
        return
    needle.say(engine, FEATURE, target,
               f"{NAME}: {attacker.display_name} makes a Wisdom saving throw against "
               f"{target.display_name}'s Cultivation Save DC.", (attacker.entity_id,))
    from .. import typed_executor as core

    core.block_save(core.Context(engine, target, ctx.action, ctx.intent, ctx.typed, [attacker], attacker,
                                 ctx.damage_cache, effect_source=FEATURE), save)


@hook("choice_reactors")
def defending_choice_owners(engine: Any) -> tuple[str, ...]:
    """"You may": enroll a manually played defender so its own decision can be put to it.

    The table asks a creature that is not the acting one only when something enrolls it, and a
    plug-in's question defaults to its first option for anyone it cannot reach. Without this list a
    player's own "you may" would be decided for them on the attacking creature's turn. Enrolled only
    while the talent is compiled, the creature is Dodging, and a person is playing it: an AI defender
    answers exactly as it did before. An AI defender's automatic first option is "use", and that is its
    best choice rather than a forced rule: both branches of the save only ever help the defender (a failed
    save bans the attack, a successful one gives Disadvantage on the next attack), so declining gains
    nothing. Nothing here reads or writes fight state.
    """
    from ..tabletop_service import MANUAL_MODES

    modes = getattr(engine, "typed_control_modes", None) or {}
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if actor.active and str(modes.get(actor.entity_id, "")) in MANUAL_MODES
                 and _owns(engine, actor) and any(condition.condition_id == DODGE for condition in actor.conditions.values()))


@effect(BAR_EFFECT)
def drown_kill_intent(ctx: Any, row: dict[str, Any]) -> None:
    """Failed Save: the creature cannot willingly make another attack against you until the start of its next turn."""
    from ..typed_executor import default_subjects, effect_expiry
    from .turn_words import until_words

    for subject in default_subjects(ctx, row, harmful=True):
        if not subject.active:
            continue
        expires = effect_expiry(ctx, row, subject, condition=True) or "START_OF_TARGET_NEXT_TURN"
        until = until_words(ctx.engine, expires, actor=ctx.actor, holder=subject)
        label = f"Cannot willingly attack {ctx.actor.display_name}"
        ctx.engine._apply_condition(subject, BAR, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                    data={"label": label, "until": until,
                                          "reading": f"{label} {until}" if until else label})


@hook("candidate_allowed")
def no_further_attacks(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Leave an attack on the creature named by the ban out of the menu, unless it is the only target perceived."""
    from ..target_knowledge import is_attack

    if _LEGALITY_QUERY.get() or action is None or not is_attack(action) or not records(engine, actor):
        return None
    for target_id in candidate.target_ids or ():
        if barred(engine, actor, engine.state.actors.get(target_id)):
            return False
    return None


@hook("attack_allowed")
def no_later_strike_against_blocker(ctx: Any, target: Any, effect: dict[str, Any]) -> bool | None:
    """Stop an already-running attack sequence before its next strike when the failed-save ban applies."""
    if ctx.typed.get("reaction_attack"):
        return None
    return False if barred(ctx.engine, ctx.actor, target) else None


@hook("opportunity_allowed")
def no_opportunity_attack(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """An Opportunity Attack on the creature named by the ban is "another attack against you" too."""
    return False if barred(engine, reactor, mover) else None


@hook("status_description")
def drown_kill_intent_text(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Say on the condition pill what the ban does, how long it lasts, and whether it holds right now."""
    if str(row.get("condition_id") or "") != BAR:
        return None
    blocker = engine.state.actors.get(str(row.get("source_actor_id") or ""))
    if blocker is None:
        return None
    until = str((data or {}).get("until") or "").strip()
    text = f"Cannot willingly attack {blocker.display_name}" + (f" {until}" if until else "") + "."
    if _other_legal_target(engine, holder, blocker):
        return {"text": text,
                "handling": "Choose another creature, move, or wait: an attack on that creature is not offered while "
                            "another creature it could legally attack is in sight."}
    return {"text": text,
            "handling": "It perceives no other creature it could legally attack, so the ban does not hold and an "
                        "attack on that creature is offered as usual."}
