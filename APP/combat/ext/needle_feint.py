"""The Piercing Needle's Feint (task F, 2026-09-29: "Feint, Exploit and Footwork"). Rules text: the owner's Sphere Compendium,
"The Piercing Needle" (authority/typed_mechanics/rules_text.json).

  Feint            "When you take the Help action to use Assist an Attack Roll against an enemy within 5 feet of you, you may aid
                   yourself instead of an ally. If you aid yourself, the next attack roll you make against that enemy has
                   Advantage. This benefit expires at the end of your next turn. Whenever you use Help to grant Advantage on an
                   attack roll against an enemy, whether you aid yourself or an ally, you perform a Feint against that enemy."
                   Aiding an ally is the ordinary Help (2024): the ally's next attack roll against the enemy, before the start of
                   the helper's next turn. A fresh Feint against the same enemy replaces the beneficiary's unspent one.
  Expert Feint     "You may perform a Feint as a Bonus Action instead of taking the Help action."
  Three-Step Feint "When you perform a Feint as a Bonus Action, choose up to two enemies within 5 feet ... Resolve the Feint
                   separately against each ... each chosen enemy makes its own saving throw."
  Greater Feint    "When you perform a Feint against an enemy, you may expend Martial Focus. The target must make a Wisdom saving
                   throw against your Cultivation Save DC. Failed Save: The first attack roll made by each creature against the
                   target has Advantage. This benefit expires at the end of your next turn."
  Fencing Focus    "After you perform a Feint against a valid enemy or win a Disarm attempt, you may use a Bonus Action to regain
                   Martial Focus."
  Fatal Opening    "When you make an attack roll with Advantage granted by your own Feint, your attack scores a Critical Hit on a
                   roll of 19 or 20." The native critical-range hook doubles the attack dice once, before defenses.
  Group Cover      "When a hostile creature makes an attack roll against you, each other hostile creature adjacent to the attacker
                   has Disadvantage on attack rolls against you until the start of your next turn."
  Court of Measured Openings (combat/ext/needle.py needle_domain): "you may perform one Feint during each of your turns with no
                   Action required; when a hostile creature within your melee reach misses you with an attack, you may perform a
                   Feint against that creature with no Action required ... A no-Action Feint still follows the normal Feint rules."

A Feint is the Advantage modifier the Vex rules already use (typed_executor.block_vex: ``attack_mode_vs``, spent by the next attack
roll against that creature, hit or miss), filed under a "needle:feint:<feinter>" source so Fatal Opening can tell its own from an
ally's. Off-turn expiry uses exact turn names (combat/ext/effect_durations.py): "its next turn" is the feinter's turn counter + 1.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .needle import (CHOICE, ask, checkpoint_id, condition, court, focus, numbers_of, owns, regain_focus,
                     save_dc, spend_focus, sovereign, timed_condition, say as _say)

FEINT = "needle:feint:"
FEINTED = "needle_round_feinted"  # the turn counter the last Feint counts for ("this turn", or "next turn" when performed off-turn)
DISARMED = "needle_round_disarmed"  # the same, for a won Disarm (Fencing Focus)
COURT_FEINT = "needle_court_feint"  # this turn's no-Action Feint is used
GREATER = "condition:typed.needle_greater_feint"
GROUP_COVER = "condition:typed.needle_group_cover"
GREATER_SPENT = "needle_round_greater_feint"


# ------------------------------------------------------------------------------------------------ the Feint itself
def _own_turn(engine: Any, actor: Any) -> bool:
    return engine.state.current_actor_id == actor.entity_id


def _feint_marks(engine: Any, beneficiary: Any, enemy: Any) -> list[str]:
    return [mid for mid, modifier in beneficiary.modifiers.items() if modifier.target_field == "attack_mode_vs"
            and modifier.value == f"ADVANTAGE:{enemy.entity_id}" and str(modifier.source_definition_id).startswith(FEINT)]


def own_feint_advantage(actor: Any, target: Any) -> bool:
    """Whether ``actor`` holds an unspent Feint of its own against ``target`` (Fatal Opening)."""
    return any(modifier.target_field == "attack_mode_vs" and modifier.value == f"ADVANTAGE:{target.entity_id}"
               and str(modifier.source_definition_id) == FEINT + actor.entity_id for modifier in actor.modifiers.values())


def perform_feint(ctx: Any, actor: Any, enemy: Any, *, free: bool = False, why: str = "Feint") -> None:
    """One Feint by ``actor`` against ``enemy``: the Help choice (yourself or an ally), the Advantage it grants, Greater Feint's
    Wisdom save, and the bookkeeping Fencing Focus reads. ``ctx``: whatever Context the Feint ran in (its intent carries the choices)."""
    from .effect_durations import token

    engine = ctx.engine
    if enemy is None or not enemy.active or enemy.team_id == actor.team_id or not actor.active:
        return
    from .help_policy import allowed as help_allowed

    allies = [other for other in engine.state.actors.values() if other.active and other.team_id == actor.team_id and other.entity_id != actor.entity_id and help_allowed(engine, actor, other)]
    near = sorted(allies, key=lambda ally: (engine.grid.distance_ft(ally.position, enemy.position), ally.entity_id))
    # Aiding an ally pays when one already stands at the enemy; otherwise the fencer's own next attack is the one that lands.
    favoured = near[0] if near and engine.grid.distance_ft(near[0].position, enemy.position) <= 5 and ctx.action.economy.value == "ACTION" else actor
    options = [actor.entity_id, *[ally.entity_id for ally in allies]]
    labels = {actor.entity_id: "Yourself", **{ally.entity_id: ally.display_name for ally in allies}}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "FEINT", actor.entity_id, enemy.entity_id), actor, CHOICE + "feint_aid", options,
                 labels=labels, preferred=[favoured.entity_id], prompt=f"Feint {enemy.display_name}: whose next attack gets Advantage?",
                 target_id=enemy.entity_id, name="Feint: choose who benefits", feature_id="TAL_FENCING_FEINT",
                 prompt_context={"cost": f"{'No Action' if free else 'Bonus Action' if ctx.action.economy.value == 'BONUS_ACTION' else 'Action'} for the triggering Feint; no additional action or resource cost for choosing who gains Advantage."})
    beneficiary = engine.state.actors.get(picked[0]) if picked else favoured
    if beneficiary is None or not beneficiary.active:
        beneficiary = actor
    self_aid = beneficiary.entity_id == actor.entity_id
    # "expires at the end of your next turn" (aiding yourself); the ordinary Help, before the start of your next turn (an ally).
    expiry = token("end" if self_aid else "start", actor.entity_id, int(actor.turns_started) + 1)
    for mid in _feint_marks(engine, beneficiary, enemy):  # a fresh Feint replaces an unspent one
        modifier = beneficiary.modifiers.pop(mid)
        engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=beneficiary.entity_id, target_ids=(beneficiary.entity_id,),
                             payload={"modifier_id": mid, "reason": "REPLACED"})
    engine._add_modifier(beneficiary, FEINT + actor.entity_id, "attack_mode_vs", "SET", f"ADVANTAGE:{enemy.entity_id}", "NEXT_ATTACK", expires_on=expiry)
    actor.turn_flags[FEINTED] = int(actor.turns_started) + (0 if _own_turn(engine, actor) else 1)
    _say(engine, ctx.source, actor, f"{actor.display_name} {'Feints' if not free else 'Feints with no Action'} {enemy.display_name}: "
         f"{'their' if self_aid else beneficiary.display_name + chr(39) + 's'} next attack roll against it has Advantage.", (enemy.entity_id,))
    if owns(engine, actor, "greater_feint") and focus(actor) >= 1 and enemy.active:
        greater_feint(ctx, actor, enemy)


def greater_feint(ctx: Any, actor: Any, enemy: Any) -> None:
    """"You may expend Martial Focus": the Wisdom save against the Cultivation Save DC; on a failure the first attack roll made by
    each creature against the target has Advantage until the end of the feinter's next turn."""
    from ..typed_executor import Context, run_effects

    engine = ctx.engine
    taken = ask(engine, ctx.intent, checkpoint_id(engine, "GREATER_FEINT", actor.entity_id, enemy.entity_id), actor, CHOICE + "greater_feint",
                ["greater_feint"], labels={"greater_feint": f"Greater Feint: {enemy.display_name} makes a Wisdom save (expends Martial Focus)"},
                preferred=["greater_feint"], minimum=0, maximum=1, allow_decline=True, prompt=f"Greater Feint {enemy.display_name}?",
                target_id=enemy.entity_id, name="Greater Feint", feature_id="TAL_FENCING_GREATER_FEINT")
    if not taken or not spend_focus(engine, actor, ctx.source, "Greater Feint"):
        return
    typed = {"numbers": {**numbers_of(engine, actor), "save_dc": save_dc(engine, actor)}, "duration": {"kind": "instant"}, "riders": []}
    sub = Context(engine, actor, ctx.action, ctx.intent, typed, [enemy], enemy, {})
    run_effects(sub, [{"type": "save", "ability": "wis", "on_fail": [{"type": "needle_greater_feint"}]}])


@effect("needle_greater_feint")
def greater_feint_condition(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed Greater Feint save: the Feinted state, until the end of the feinter's next turn."""
    from .effect_durations import token

    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        if subject is None or not subject.active:
            continue
        timed_condition(ctx.engine, subject, GREATER, ctx.source, ctx.actor.entity_id,
                        token("end", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1), {"label": "Greater Feint: open to every first attack"})
        subject.turn_flags[GREATER_SPENT] = {"seq": condition(subject, GREATER).applied_sequence, "spent": []}
        _say(ctx.engine, ctx.source, ctx.actor, f"{subject.display_name} is fooled: the first attack roll each creature makes against it has Advantage.", (subject.entity_id,))


@hook("decision_text")
def feint_reading(engine: Any, context: dict[str, Any], printed_rules: dict) -> dict | None:
    choice = context.get("reaction_source_id")
    if choice not in {CHOICE + "feint_aid", CHOICE + "greater_feint", CHOICE + "three_step"}:
        return None
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not any(a.owner_id == actor.entity_id and (a.parameters.get("typed") or {}).get("feint")
                               for a in engine.action_catalog.values()):
        return None
    trigger = context.get("choice_trigger") or {}
    enemy = engine.state.actors.get(trigger.get("target_id"))
    name = enemy.display_name if enemy else "the selected enemy"
    if choice == CHOICE + "greater_feint":
        if not owns(engine, actor, "greater_feint"):
            return None
        return {"feature_id": "TAL_FENCING_GREATER_FEINT",
                "summary": f"Make {name} roll a Wisdom save against your Cultivation Save DC. On failure, each creature's first attack against it has Advantage until the end of your next turn. On success, your ordinary Feint still works.",
                "cost": "Expend Martial Focus (your readiness for focused martial abilities); no extra Action or Reaction.",
                "limits": "The benefit lasts until the end of your next turn; each creature benefits on only its first attack against this enemy.",
                "option_descriptions": {"greater_feint": "Spend Martial Focus for the Wisdom save and possible Advantage for every creature's first attack. Decline to keep Martial Focus and resolve the ordinary Feint."}}
    if choice == CHOICE + "three_step":
        if not owns(engine, actor, "three_step"):
            return None
        descriptions = {key: f"Also Feint {engine.state.actors[key].display_name}. Resolve its beneficiary choice and any saving throw separately; no additional action or resource cost for adding this enemy."
                        for key in trigger.get("needle_options") or [] if key in engine.state.actors}
        return {"feature_id": "TAL_FENCING_THREE_STEP_FEINT",
                "summary": f"Your Bonus Action Feint already targets {name}. You may choose one additional enemy within 5 feet; resolve its Feint and any saving throw separately.",
                "cost": "No additional cost for choosing the second enemy; the triggering Feint costs a Bonus Action. Greater Feint, if chosen, expends Martial Focus separately.",
                "limits": "Up to two enemies within 5 feet per Bonus Action Feint. Each beneficiary's next attack has Advantage, until the end of your next turn if you aid yourself, or the start if you aid an ally.",
                "option_descriptions": descriptions}
    descriptions = {}
    for option in trigger.get("needle_options") or []:
        beneficiary = engine.state.actors.get(option)
        if beneficiary is None:
            continue
        expiry = "the end of your next turn" if option == actor.entity_id else "the start of your next turn"
        descriptions[option] = f"{beneficiary.display_name}'s next attack roll against {name} has Advantage (roll two d20s and use the higher). Used on that roll, hit or miss; otherwise expires at {expiry}. No additional cost."
    return {"feature_id": "TAL_FENCING_FEINT",
            "summary": f"Distract {name} and choose whose next attack roll against it has Advantage (roll two d20s and use the higher). If you aid yourself, it expires at the end of your next turn; if you aid an ally, it expires at the start of your next turn.",
            "cost": trigger.get("cost", "No additional action or resource cost for this selection; the triggering Feint pays its own action cost."),
            "limits": "Applies only to the chosen creature's next attack against this enemy, hit or miss. A fresh Feint against the same enemy replaces that beneficiary's unspent benefit.",
            "option_descriptions": descriptions}


@hook("button_description")
def feint_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "needle_feint" for eff in effects):
        economy = "Bonus action" if row.get("economy") == "BONUS_ACTION" else "No action (Court of Measured Openings)"
        return (economy + ": distract an enemy within 5 feet so your next attack against it has advantage, until the end of your next turn. "
                "You can aid an ally instead, as with Help.\n\n" + printed_rule_text("TAL_FENCING_FEINT"))
    return None


@effect("needle_feint")
def feint_effect(ctx: Any, eff: dict[str, Any]) -> None:
    """The Feint action (and Expert Feint and Court's no-Action Feint): one enemy, or -- as a Bonus Action with Three-Step Feint --
    up to two enemies within 5 feet, each resolved separately."""
    engine, actor = ctx.engine, ctx.actor
    enemy = ctx.target or next(iter(ctx.targets or []), None)
    if enemy is None:
        return
    free = ctx.action.economy.value == "NONE"
    if free:
        actor.turn_flags[COURT_FEINT] = True
    perform_feint(ctx, actor, enemy, free=free)
    if ctx.action.economy.value == "BONUS_ACTION" and owns(engine, actor, "three_step"):
        others = [other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id and other.entity_id != enemy.entity_id
                  and engine.grid.distance_ft(actor.position, other.position) <= 5]
        if others:
            picked = ask(engine, ctx.intent, checkpoint_id(engine, "THREE_STEP", actor.entity_id, enemy.entity_id), actor, CHOICE + "three_step",
                         [other.entity_id for other in others], labels={other.entity_id: other.display_name for other in others},
                         preferred=[others[0].entity_id], minimum=0, maximum=1, allow_decline=True,
                         prompt=f"Three-Step Feint against {enemy.display_name}: also Feint a second enemy within 5 feet?",
                         target_id=enemy.entity_id, name="Three-Step Feint", feature_id="TAL_FENCING_THREE_STEP_FEINT")
            second = engine.state.actors.get(picked[0]) if picked else None
            if second is not None:
                perform_feint(ctx, actor, second, free=free)


@effect("needle_fencing_focus")
def fencing_focus_effect(ctx: Any, eff: dict[str, Any]) -> None:
    regain_focus(ctx.engine, ctx.actor, ctx.source, "Fencing Focus")


# ------------------------------------------------------------------------------------------------ the actions
@hook("compile_actions")
def feint_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []
    short, actor_id = info["short"], info["actor_id"]

    def make(key: str, name: str, economy: Any, target_kind: str, effects: list[dict[str, Any]], extra: dict[str, Any]) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy,
                                resolution_kind="TYPED", target_kind=target_kind, range_ft=5 if target_kind == "HOSTILE_ENTITY" else None,
                                parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], **extra},
                                            "expected_damage": 0})

    if "TAL_FENCING_EXPERT_FEINT" in owned:
        out.append(make("expert_feint", "Feint (Bonus Action)", EconomyKind.BONUS_ACTION, "HOSTILE_ENTITY", [{"type": "needle_feint"}], {"feint": True}))
    if "TAL_FENCING_COURT_OF_MEASURED_OPENINGS" in owned:
        out.append(make("court_feint", "Feint (Court of Measured Openings, no Action)", EconomyKind.NONE, "HOSTILE_ENTITY",
                        [{"type": "needle_feint"}], {"feint": True}))
    if "TAL_FENCING_FENCING_FOCUS" in owned:
        out.append(make("fencing_focus", "Fencing Focus", EconomyKind.BONUS_ACTION, "SELF", [{"type": "needle_fencing_focus"}], {}))
    return out or None


@hook("candidate_allowed")
def feint_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    key = str(getattr(action, "source_definition_id", "")).rsplit(".", 1)[-1]
    if key == "court_feint":
        return False if (not court(actor) or actor.turn_flags.get(COURT_FEINT)) else None  # "one Feint during each of your turns"
    if key == "fencing_focus":
        ready = int(actor.turns_started) in (actor.turn_flags.get(FEINTED), actor.turn_flags.get(DISARMED))
        return False if (focus(actor) >= 1 or not ready) else None  # "regain it only if it is currently absent"
    return None


@hook("event")
def disarm_won(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A Disarm won (a Disarmed condition put on the target by this fencer): Fencing Focus's trigger; Sovereign regains Martial Focus."""
    payload = kwargs.get("payload") or {}
    if event_type != "CONDITION_APPLIED" or not str(payload.get("condition_id") or "").endswith("disarmed"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not owns(engine, actor, "fencing_focus"):
        if actor is not None and sovereign(actor):
            regain_focus(engine, actor, "condition:typed.needle_sovereign", "Sovereign Needle Incarnation: a Disarm won")
        return
    actor.turn_flags[DISARMED] = int(actor.turns_started) + (0 if _own_turn(engine, actor) else 1)
    if sovereign(actor):
        regain_focus(engine, actor, "condition:typed.needle_sovereign", "Sovereign Needle Incarnation: a Disarm won")


# ------------------------------------------------------------------------------------------------ Court: a Feint when a hostile misses you
@hook("after_miss")
def court_riposte_feint(ctx: Any, target: Any) -> None:
    """"When a hostile creature within your melee reach misses you with an attack, you may perform a Feint against that creature
    with no Action required" (Court of Measured Openings)."""
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or target.entity_id == attacker.entity_id or target.team_id == attacker.team_id:
        return
    if not court(target) or not attacker.active or engine.grid.distance_ft(target.position, attacker.position) > 5:
        return
    from ..typed_executor import Context

    sub = Context(engine, target, next((engine.action_catalog[a] for a in target.action_ids if a.endswith(".court_feint") and a in engine.action_catalog), ctx.action),
                  ctx.intent, {"numbers": numbers_of(engine, target)}, [attacker], attacker, {})
    perform_feint(sub, target, attacker, free=True, why="Court of Measured Openings")


# ------------------------------------------------------------------------------------------------ attack modes: Greater Feint, Fatal Opening, Group Cover
@hook("attack_mode")
def feint_attack_mode(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None:
        return None
    found = condition(target, GREATER)
    mode = None
    if found is not None:  # "The first attack roll made by each creature against the target has Advantage."
        spent = target.turn_flags.get(GREATER_SPENT)
        spent = spent if isinstance(spent, dict) and spent.get("seq") == found.applied_sequence else {"seq": found.applied_sequence, "spent": []}
        if actor.entity_id not in spent["spent"]:
            target.turn_flags[GREATER_SPENT] = {"seq": found.applied_sequence, "spent": [*spent["spent"], actor.entity_id]}
            mode = "ADVANTAGE"
    covered = condition(target, GROUP_COVER)
    if covered is not None and actor.entity_id in ((covered.data or {}).get("affected") or []):
        return None if mode == "ADVANTAGE" else "DISADVANTAGE"  # they cancel
    return mode


@hook("event")
def group_cover(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Group Cover: a hostile creature's attack roll against the fencer puts Disadvantage (against the fencer) on every other
    hostile creature adjacent to that attacker, until the start of the fencer's next turn."""
    if event_type != "ATTACK_ROLLED":
        return
    attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        fencer = engine.state.actors.get(target_id)
        if attacker is None or fencer is None or not fencer.active or fencer.team_id == attacker.team_id or not owns(engine, fencer, "group_cover"):
            continue
        from .effect_durations import token

        found = condition(fencer, GROUP_COVER)
        affected = set((found.data or {}).get("affected") or []) if found is not None else set()
        affected |= {other.entity_id for other in engine.state.actors.values()
                     if other.active and other.team_id == attacker.team_id and other.entity_id != attacker.entity_id
                     and engine.grid.distance_ft(other.position, attacker.position) <= 5}
        if not affected or (found is not None and affected == set((found.data or {}).get("affected") or [])):
            continue
        timed_condition(engine, fencer, GROUP_COVER, "passive:TAL_FENCING_GROUP_COVER", fencer.entity_id,
                        token("start", fencer.entity_id, int(fencer.turns_started) + 1),
                        {"label": "Group Cover", "affected": sorted(affected)})


# ------------------------------------------------------------------------------------------------ Fatal Opening
@hook("attack_critical_range")
def fatal_opening(engine: Any, actor: Any, target: Any, spec: dict[str, Any]) -> int | None:
    """A qualifying Feint's actual Advantage widens this attack before damage."""
    if (spec.get("attack_roll_mode") == "ADVANTAGE" and owns(engine, actor, "fatal_opening")
            and own_feint_advantage(actor, target)):
        return 19
    return None
