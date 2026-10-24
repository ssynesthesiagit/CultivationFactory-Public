"""The Piercing Needle's Martial Focus, Exploits and Martial Domains (task F, 2026-09-29: "Feint, Exploit and Footwork").

Rules text (owner's Sphere Compendium, "The Piercing Needle", authority/typed_mechanics/rules_text.json; the 5.5e Suffocation
hazard and the Exhaustion table are the fallback where a talent says "ordinary" and the owner's books say no more):

  Martial Focus  "You may hold one Martial Focus at a time. ... Expending Martial Focus is not an Action. You cannot expend it
                 if you do not currently hold it. If a talent says you regain it, regain it only if it is currently absent."
  Exploits       "Once per round, when you hit a creature with a melee attack, you may apply one Exploit talent you know if
                 the attack roll had Advantage, or did not have Disadvantage and an ally that is not Incapacitated is within
                 5 feet of the target. Choose the Exploit after the attack hits; no more than one Exploit to that attack; no
                 more than one during the same round." Each Exploit's own "Cost: Expend Martial Focus" is paid when it lands
                 (Face Strike, To the Hilt, Soul Strike, Bleed Air, Empty Hand, Open Meridian).
  Skewer         "When you apply an Exploit to an attack, you may expend Martial Focus to apply two different Exploits."
  Court of Measured Openings / Sovereign Needle Incarnation: a timed state (1 minute = 10 rounds) that ends early on
                 Incapacitated. Court: two different Exploits without expending Martial Focus for it; a Feint each turn and
                 one when a hostile in reach misses you with no Action; Footwork regains Martial Focus once a round.
                 Sovereign: Exploits twice a round (once per attack), Footwork once a round without Martial Focus, regain
                 Martial Focus on a Disarm win or when Parry and Riposte reduces the damage to 0, attacks count as magical.
  Returning Point "Once per turn, after you apply an Exploit to a creature, move up to 5 feet to an unoccupied space you can
                 reach", without Opportunity Attacks from that creature.

Ownership at fight time is the "needle" rows of combat/rules/feature_blocks.d/needle.json (kind = the talent) plus the
"exploits" row the compiler builds; the choices are the lock round's ``choice_options`` transport, so the table shows them as
buttons and the AI picks its preferred first option. Shared public helpers here serve needle_feint, needle_footwork,
needle_guards, counterstrike, fencing_needle_catching, mount_guard, redirect_reactions, shield_faces and tabik_ninpo
(Hidden Strike's rider/destination choices and free step). In particular,
say logs an event without changing its payload; cell_id names a grid choice without changing its encoding.
numbers_of also supplies sealed combat numbers to Core Tempering during reload and replay.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from . import effect, hook

FOCUS = "resource:core.martial_focus"
BLOCK = "needle"
COURT, SOVEREIGN = "condition:typed.needle_court", "condition:typed.needle_sovereign"
PENALTY = "condition:typed.needle_"  # + arm_strike / soul_strike / shadow_strike / bleed_air / choking
SKEWER = "condition:typed.skewer_pick"
CHOICE = "choice:needle."
MAGICAL = "condition:typed.needle_magical"


# ------------------------------------------------------------------------------------------------ ownership and Focus
def kinds(engine: Any, actor_id: str) -> dict[str, dict[str, Any]]:
    """The Needle talents this character owns, by kind (feature_blocks.d/needle.json)."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
    return {str(row.get("kind")): row for row in rows if row.get("block") == BLOCK and row.get("kind")}


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return kind in kinds(engine, actor.entity_id)


def focus(actor: Any) -> int:
    return int(actor.resources.get(FOCUS, 0))


def say(engine: Any, source: str, actor: Any, text: str, target_ids: tuple[str, ...] = (), *,
        details: dict[str, Any] | None = None) -> None:
    """Shared Needle-family log helper; optional primitive details correlate a trigger with its packet."""
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=target_ids,
                         payload={**(details or {}), "trigger": text, "text": text})


# Internal spelling retained; sibling plug-ins import the public API.
_say = say


def spend_focus(engine: Any, actor: Any, source: str, why: str, amount: int = 1) -> bool:
    """Expend Martial Focus (not an Action); False (nothing spent) when the actor does not hold enough."""
    if amount <= 0:
        return True
    if focus(actor) < amount:
        return False
    engine._spend_resource(actor, FOCUS, amount, source)
    _say(engine, source, actor, f"{actor.display_name} expends Martial Focus ({why}).")
    return True


def regain_focus(engine: Any, actor: Any, source: str, why: str) -> bool:
    """"Regain it only if it is currently absent" -- a one-point resource."""
    if FOCUS not in actor.resources or actor.resources.get(FOCUS, 0) >= actor.resource_maximums.get(FOCUS, 1):
        return False
    engine._gain_resource(actor, FOCUS, 1, source)
    _say(engine, source, actor, f"{actor.display_name} regains Martial Focus ({why}).")
    return True


def condition(actor: Any, condition_id: str) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)


def incapacitated(actor: Any) -> bool:
    """The Incapacitated condition, or any state that includes it (a condition rule that takes away Actions)."""
    from ..typed_executor import condition_rules

    return any(c.condition_id.endswith("incapacitated") for c in actor.conditions.values()) or any(row.get("no_actions") for row in condition_rules(actor))


def court(actor: Any) -> bool:
    return condition(actor, COURT) is not None


def sovereign(actor: Any) -> bool:
    return condition(actor, SOVEREIGN) is not None


def save_dc(engine: Any, actor: Any) -> int:
    """The actor's Cultivation Save DC, read from its own compiled abilities."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}
        if numbers.get("save_dc"):
            return int(numbers["save_dc"])
    return 8 + int(actor.proficiency_bonus) + 2


def numbers_of(engine: Any, actor: Any) -> dict[str, Any]:
    """Sealed action numbers used by Needle and Core Tempering, including cold reloads."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers")
        if numbers:
            return dict(numbers)
    return {"pb": int(actor.proficiency_bonus), "save_dc": save_dc(engine, actor)}


def pb_rounds(engine: Any, actor: Any, rounds: int) -> str:
    from .effect_durations import round_token

    return round_token(engine, max(1, int(rounds)))


def timed_condition(engine: Any, actor: Any, condition_id: str, source: str, source_actor_id: str, expires: str,
                    data: dict[str, Any]) -> None:
    """Put (or refresh: the same one again replaces the old) a condition, evented -- never edit a condition in place."""
    for iid, existing in list(actor.conditions.items()):
        if existing.condition_id == condition_id and existing.source_actor_id == source_actor_id:
            engine._remove_condition(actor, condition_id, source)
            break
    engine._apply_condition(actor, condition_id, source, source_actor_id, expires_on=expires, data=data)


# ------------------------------------------------------------------------------------------------ the choice transport
def option_spec(choice_id: str, context: dict[str, Any] | None, prefix: str = CHOICE) -> dict[str, Any] | None:
    """The ExtensionChoice spec for one ``ask()`` question, for a plug-in that owns its own choice namespace.

    ``ask()`` already publishes the whole question in the trigger context (``needle_options``, ``minimum``,
    ``maximum``, ``allow_decline``, ``automatic``, ``preferred``), so a plugin whose choice ids start with
    ``prefix`` only has to say which prefix is its own. Returns None for any other choice id, or for a
    question nobody put (``ask()`` with no options), which is the default-inert path: the table then falls
    back to its ordinary Use/Pass window. Used by needle's own ``choice_options`` and by
    scoundrel_riders, whose ``choice:scoundrel.*`` menus ask for the same options by name.
    """
    if not str(choice_id).startswith(prefix) or not (context or {}).get("needle_options"):
        return None
    spec = {"option_ids": list(context["needle_options"]), "minimum_selections": int(context.get("minimum", 1)),
            "maximum_selections": int(context.get("maximum", 1)), "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True))}
    if context.get("preferred"):
        spec["preferred_option_ids"] = list(context["preferred"])
    return spec


@hook("choice_options")
def _options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Every Needle choice (id "choice:needle.*"): the options and their bounds ride in the trigger context."""
    spec = option_spec(choice_id, context, CHOICE)
    if spec is not None and "automatic_options" in context:
        actor = engine.state.actors.get(reactor_id)
        mode = (getattr(engine, "typed_control_modes", {}) or {}).get(
            getattr(actor, "owner_id", None) or reactor_id, "MANUAL")
        # These are all player-submitted control modes. Restrict the recipient
        # set only when the service will make the choice automatically.
        if mode not in {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}:
            allowed = set(context["automatic_options"])
            spec["option_ids"] = [key for key in spec["option_ids"] if key in allowed]
            spec["preferred_option_ids"] = [key for key in spec.get("preferred_option_ids", []) if key in allowed]
            spec["minimum_selections"] = min(spec["minimum_selections"], len(spec["option_ids"]))
            spec["maximum_selections"] = min(spec["maximum_selections"], len(spec["option_ids"]))
            if not spec["option_ids"]:
                spec["automatic_use"] = False
                spec["allow_decline"] = True
    return spec


@hook("choice_reactors")
def manual_inline_choice_owners(engine: Any) -> tuple[str, ...]:
    """Enroll manual participants only when a compiled action opts into inline choices.

    The action row advertises ``typed.manual_inline_choice`` when execution can
    ask another participant for a transactional choice. The service probes
    these possible owners and prompts only at a reached checkpoint. A compiled
    scene check stays hidden for every seat until a provider opts it in
    (``scene_check_relevant``), so it must not enroll anyone while dormant.
    """
    from ..tabletop_service import MANUAL_MODES
    from . import run
    modes = getattr(engine, "typed_control_modes", None) or {}
    manual = sorted(actor_id for actor_id, mode in modes.items()
                    if mode in MANUAL_MODES and actor_id in engine.state.actors)
    if not manual:
        return ()
    actions = [action for action in (getattr(engine, "action_catalog", {}) or {}).values()
               if bool((((action.parameters or {}).get("typed")) or {}).get("manual_inline_choice"))]
    owners = []
    for actor_id in manual:
        actor = engine.state.actors[actor_id]
        for action in actions:
            purpose = (action.parameters or {}).get("scene_check_purpose")
            if purpose and not any(run("scene_check_relevant", engine, actor, purpose)):
                continue
            owners.append(actor_id)
            break
    return tuple(owners)


def riding_cost(engine: Any, chooser: Any) -> str:
    """The price of the action being resolved right now, as the table reads it.

    This is the *enclosing action's* cost, not the choice's own. A choice asked inside an
    action commits that action's payment (Spinning Shot's "Expend Martial Focus" is paid by
    the Barrage primary that asks for the second target), so a choice that pays nothing of
    its own quotes this rather than reading "none". Read from the same compiled action row
    the spending code charges, at the moment the choice is raised, while that action is
    still the one executing.

    Returns "" when the choice is not riding the chooser's own action -- a choice raised by
    someone else's action, or outside any action -- so those keep the table's default wording
    and a free action stays free.

    A choice that *does* pay for itself (see choice_costs.Payment) quotes its own price and
    this one apart; it must never adopt this figure as its own.

    Used by ask() to fill a choice prompt's cost; safe to call from any plugin."""
    source = getattr(engine, "_active_action_source_id", None)
    if not source:
        return ""
    action = (getattr(engine, "action_catalog", {}) or {}).get(str(source))
    if action is None or getattr(action, "owner_id", None) != getattr(chooser, "entity_id", None):
        return ""
    from .choice_costs import quote
    return quote(getattr(action, "costs", ()) or ())


def ask(engine: Any, intent: Any, checkpoint: str, chooser: Any, choice_id: str, options: list[str], *, labels: dict[str, str] | None = None,
        prompt: str = "", preferred: list[str] | None = None, minimum: int = 1, maximum: int = 1, allow_decline: bool = False,
        automatic: bool = True, target_id: str | None = None, default: str = "first", default_count: int | None = None,
        name: str = "", feature_id: str = "", prompt_context: dict[str, str] | None = None,
        payment: Any = None, automatic_options: list[str] | None = None,
        space_areas: dict[str, list[dict[str, int]]] | None = None, gm_adjudication: bool = False) -> list[str]:
    """Ask ``chooser`` to pick among ``options`` (transported by choice_checkpoints); the selection, in the order given.
    Shared with vessel/thread_object for creature and loose-object destination choices.
    With no answer (a fight nobody is answering: no provider, an old engine) the default is the preferred first option (or the
    first ``default_count`` options), or nothing when ``default`` is "decline". A declined choice is an empty list.
    A question is offered a Decline answer only when ``allow_decline`` is passed; that flag is transported with the
    choice spec so the extension-choice validation accepts the DECLINE row. A caller whose silent fallback is "decline"
    passes ``allow_decline=True`` too, so the table's explicit decline is a legal answer instead of being rejected.
    ``name`` labels the menu; ``feature_id`` supplies a feature-name fallback for the table.
    ``prompt_context`` adds display-only action metadata from choice_prompt.action_context,
    or the owning plugin's own cost and paying_pool (resource id); never changes payment.
    ``space_areas`` optionally captures native affected-square previews by option id
    at the pause. It is transported as a JSON string, like space_positions, and
    never changes choice authority or mechanical state.
    ``gm_adjudication`` asks the table's GM for this external scene fact even
    on an automatic seat. The owning action must opt into the GM preview with
    typed.gm_adjudication; ordinary AI choices still resolve automatically.
    ``payment`` is a choice_costs.Payment the caller spends itself once answered (Bloodletting
    Strike's 1 point, Crimson Feast's 2). Passing it states the choice's *own* price, so the
    enclosing action's price is quoted beside it rather than in place of it, and the caller
    pays with ``payment.pay(...)`` -- one object, quoted and spent, so they cannot disagree.
    With no payment of its own, a choice quotes the action it rides (see :func:`riding_cost`),
    so it never reads "no cost" for a payment the table is about to make.
    ``automatic_options`` optionally limits a computer-controlled chooser to a subset of
    the offered options. An empty subset selects nobody; human-controlled choosers retain
    the full menu. Preferences only order selections and never restrict the pool.
    ``affected_id`` records an explicit target (or empty for an unresolved choice);
    ``target_id`` also serves as transport routing and defaults to the chooser."""
    options = list(dict.fromkeys(options))
    if automatic_options is not None:
        from . import ai_controlled
        if ai_controlled(engine, chooser):
            options = [option for option in options if option in automatic_options]
            preferred = [option for option in (preferred or []) if option in options]
    if not options:
        return []
    order = [*(preferred or []), *[o for o in options if o not in (preferred or [])]]
    automatic_ids = None if automatic_options is None else [key for key in options if key in automatic_options]
    fallback_order = order if automatic_ids is None else [key for key in order if key in automatic_ids]
    fallback = [] if default == "decline" else fallback_order[:max(1, maximum if default == "all" else minimum, default_count or 0)]
    if intent is None:
        intent = getattr(engine, "_active_intent", None)
    if not hasattr(engine, "_gate4_reaction_cache") or intent is None:
        return fallback
    context = {"actor_id": intent.actor_id, "target_id": target_id or chooser.entity_id,
               "affected_id": target_id or "", "needle_options": options, "labels": labels or {},
               "prompt": prompt, "preferred": list(preferred or []), "minimum": min(minimum, len(options)),
               "maximum": min(maximum, len(options)), "allow_decline": allow_decline, "automatic": automatic}
    if gm_adjudication:
        context['gm_adjudication'] = True
    if automatic_ids is not None:
        context["automatic_options"] = automatic_ids
    if name:
        context["name"] = name
    if feature_id:
        context["feature_id"] = feature_id
    if prompt_context:
        for key in ("source_definition_id", "action_name", "action_actor_id", "affected_id", "cost", "paying_pool"):
            if key in prompt_context:
                context[key] = str(prompt_context[key])
    if payment is not None:
        # The choice pays for itself. Its own price leads; the action it rides, already
        # committed and already paid, is named beside it so the two are never confused.
        from .choice_costs import separating

        context.update(payment.context())
        context["cost"] = separating(riding_cost(engine, chooser), payment.quote())
    elif "cost" not in context:
        # The plugin declared no cost of its own, so describe the action this choice is part of.
        cost = riding_cost(engine, chooser)
        if cost:
            context["cost"] = cost
    # Presentation must describe positions at this pause, before transaction rollback.
    from ..choice_presentation import capture_space_positions
    space_positions = capture_space_positions(engine, options)
    if space_positions:
        context["space_positions"] = space_positions
    if space_areas:
        import json
        context['space_areas'] = json.dumps(space_areas, sort_keys=True)
    decision = engine._reaction_decision(intent, checkpoint, chooser.entity_id, choice_id, context=context)
    if decision is None:
        return fallback
    if decision.selection == "DECLINE":
        return []
    return list(decision.option_ids)


def answered(engine: Any, checkpoint: str, chooser: Any, choice_id: str) -> bool:
    """Whether a player answered this exact question, as opposed to nobody being there to answer it.

    ``ask`` returns an empty list both for a decline and for a fight nobody is answering (no transport, no
    provider, or a provider that had nothing to say). A caller that has to word its "nothing happened" line needs
    to tell those apart, because they are different events for the player. Reads the transport's own decision
    cache and the answers already carried on the active intent; a question that was never put is False.
    """
    key = (checkpoint, chooser.entity_id, choice_id)
    cache = getattr(engine, "_gate4_reaction_cache", None)
    if cache is None:
        return False
    if cache.get(key) is not None:
        return True
    intent = getattr(engine, "_active_intent", None)
    return any((answer.checkpoint, answer.reactor_id, answer.reaction_source_id) == key
               for answer in getattr(intent, "reaction_decisions", None) or [])


def ai_controlled(engine: Any, actor: Any) -> bool:
    """Current actor's controller, including companions, is either automatic mode.

    Perception gates use the chooser's mode, never the active turn's mode.
    Missing legacy metadata does not opt an old saved fight into a new gate.
    """
    modes = getattr(engine, "typed_control_modes", None) or {}
    controller = getattr(actor, "owner_id", None) if not getattr(actor, "primary_combatant", True) else None
    return modes.get(controller or actor.entity_id) in {"LOCAL_AUTO", "API_AUTO"}


def answerable(engine: Any, actor: Any) -> bool:
    """Whether ``actor``'s own choice is a player's to make, so a plug-in must not decide it.

    The table's recorded control mode is the authority, not whether a reaction provider happens to be
    installed: ``combat/gate5_service.py`` writes one mode per participant
    (``FactoryIntegration.json``'s ``participant_control_modes`` onto ``engine.typed_control_modes``)
    and reads it back for every question it routes -- ``_mode_for_actor`` resolves each reactor's mode
    before a preview or a commit, so the same dict decides who is asked and who decides alone.

      * Local AI and API AI decide for themselves (checklist item 9), so a free trigger may resolve
        one of their choices without asking -- including while a provider is installed for somebody
        else at the table.
      * Manual, Suggested and Manual AI Bridge (``combat/tabletop_service.py`` ``MANUAL_MODES``) are
        the player's own decisions; a plug-in that wants one has to put the question to them.
      * A fight with no recorded mode -- a bare engine, or a fight saved before modes were journalled
        -- carries no player authority at all, and keeps deciding for itself, which is exactly what
        those fights have always done.  A companion answers for its owner, as the service does.

    A plug-in that triggers outside an action (a turn boundary, a zone recovery) has no in-flight
    intent to attach its question to, so it reads this first and defers instead of choosing for a
    player.  Used by axes_execution; any free trigger that fires outside an action may use it the
    same way.
    """
    from ..tabletop_service import MANUAL_MODES

    modes = getattr(engine, "typed_control_modes", None) or {}
    controller = getattr(actor, "owner_id", None) if not getattr(actor, "primary_combatant", True) else None
    return str(modes.get(controller or getattr(actor, "entity_id", ""), "")) in MANUAL_MODES


def checkpoint_id(engine: Any, name: str, *parts: Any) -> str:
    """Unique per triggering event: the event count separates two uses in one intent."""
    return ":".join(["NEEDLE", name, str(engine.state.event_sequence), *[str(p) for p in parts]])


# ------------------------------------------------------------------------------------------------ compile
@hook("compile_block")
def needle_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}] if block == BLOCK else None


# ------------------------------------------------------------------------------------------------ Exploits
def _uses(actor: Any, engine: Any) -> int:
    value = str(actor.turn_flags.get("needle_round_exploits") or "")
    round_now, _, count = value.partition(":")
    return int(count) if round_now == str(engine.state.round_number) and count.isdigit() else 0


def _count_use(actor: Any, engine: Any) -> None:
    actor.turn_flags["needle_round_exploits"] = f"{engine.state.round_number}:{_uses(actor, engine) + 1}"
    actor.turn_flags["exploit_round_used"] = engine.state.round_number


def _qualifies(ctx: Any, target: Any) -> bool:
    """Advantage on the attack roll, or no Disadvantage and a conscious ally within 5 feet of the target."""
    engine, actor = ctx.engine, ctx.actor
    roll = next((event for event in reversed(engine.events) if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor.entity_id), None)
    mode = str((roll.payload or {}).get("mode") or "").upper() if roll is not None else ""
    if mode == "ADVANTAGE":
        return True
    if mode == "DISADVANTAGE":
        return False
    if getattr(engine, "_needle_riposte", None) == actor.entity_id:
        return True  # Parry and Riposte: "if the attack roll does not have Disadvantage, even if the attack would not otherwise satisfy the normal Exploit requirements"
    return any(other.active and other.team_id == actor.team_id and other.entity_id != actor.entity_id
               and engine._on_battlefield(other)
               and engine.grid.distance_ft(other.position, target.position) <= 5 and not incapacitated(other)
               for other in engine.state.actors.values())


def _exploit_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    from .. import typed_reactions

    rows = typed_reactions._rows(engine, actor.entity_id, "exploits")
    return list(rows[0].get("options") or []) if rows else []


@hook("decision_text")
def exploit_description(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Use each owned Exploit's printed effect, with this actor's actual numbers."""
    if context.get("reaction_source_id") != CHOICE + "exploit":
        return None
    actor = engine.state.actors.get(context.get("reactor_id"))
    options = _exploit_rows(engine, actor) if actor is not None else []
    if not options:
        return None
    numbers = numbers_of(engine, actor)
    trigger = context.get("choice_trigger") or {}
    action = engine.action_catalog.get(trigger.get("source_definition_id"))
    if action is not None:
        numbers = {**numbers, **action.parameters.get("typed", {}).get("numbers", {})}
    rounds = int(numbers.get("pb") or actor.proficiency_bonus)
    dc = int(numbers.get("save_dc") or save_dc(engine, actor))
    cost = "No additional action; pay each Exploit's own cost below."
    limits = "Normally one Exploit per round."
    if court(actor):
        cost += (" While Court of Measured Openings is active, selecting two different Exploits costs "
                 "no extra Martial Focus. Each Exploit's own cost still applies.")
        limits += " Court of Measured Openings allows two different Exploits on this hit."
    elif owns(engine, actor, "skewer"):
        cost += (" With Skewer, selecting two different Exploits costs one additional Martial Focus "
                 "(one available use), in addition to each Exploit's own cost.")
        limits += " Skewer allows two different Exploits on this hit if you can pay the combined cost."
    descriptions = {}
    for option in options:
        text = printed_rules.get(option["id"], "")
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        text = " ".join(lines)
        text = text.replace("a number of rounds equal to half your Proficiency Bonus, rounded up", f"{(rounds + 1) // 2} rounds")
        text = text.replace("a number of rounds equal to your Proficiency Bonus", f"{rounds} rounds")
        text = text.replace("your Cultivation Save DC", f"DC {dc}")
        text = text.replace("your Proficiency Bonus", str(rounds))
        text = text.replace("CP", "cultivation points (the Qi, Stamina or other pool that fuels techniques)")
        text = text.replace("CL ", "cultivation level ")
        payment = ("Expend your Martial Focus (one available use) for this Exploit itself."
                   if _cost(option) else "No resource cost for this Exploit itself.")
        descriptions[option["id"]] = f"{text} {payment}"
    return {"name": "Choose an Exploit", "summary": "After this melee attack hits, choose an Exploit for the creature hit, or pass. "
            "Each option below explains its penalties, saving throw and duration.",
            "cost": cost,
            "limits": limits,
            "table_note": "For limb-specific effects, identify the affected limb with the GM.",
            "option_descriptions": descriptions}


def _standing(actor: Any, condition_id: str, key: str) -> str | None:
    found = condition(actor, condition_id)
    value = (found.data or {}).get(key) if found is not None else None
    return str(value) if value else None


def _legal(engine: Any, actor: Any, target: Any, option: dict[str, Any]) -> bool:
    """Whether the Exploit could affect this target now (its own printed conditions, not the GM's anatomy calls)."""
    name = str(option.get("id") or "")
    if name.endswith("BLEED_AIR"):
        return int(target.current_hp) < int(target.maximum_hp)  # "If the target is below its Hit Point maximum"
    if name.endswith("REPOSITIONING_STRIKE"):
        return bool(_reposition_cells(engine, actor, target))
    if name.endswith("WIDE_OPEN"):
        return bool(_wide_open_allies(engine, actor))
    return True


def _cost(option: dict[str, Any]) -> int:
    return int(option.get("focus") or 0)


HEART_STOPPING = "TAL_FENCING_HEART_STOPPING_REVERSAL"


def apply_exploit(ctx: Any, target: Any, *, counted: bool = True, qualifying: bool = True, maximum: int | None = None,
                  exclude: tuple[str, ...] = (), reason: str = "") -> list[str]:
    """Apply the Exploit(s) this hit earns; the ids applied. ``counted``: it uses the once-per-round allowance; ``qualifying``:
    the Advantage / ally condition applies (Parry and Riposte waives it); ``maximum`` caps the number applied to this attack."""
    engine, actor = ctx.engine, ctx.actor
    if ctx.source == HEART_STOPPING:  # "apply one Exploit you know without counting that Exploit against your normal once-per-round limit"
        counted, maximum = False, 1
    guards = getattr(engine, "_needle_guards", None)  # Needle Through Ten Thousand Guards: "one different Exploit ... to each successful attack"
    if guards and guards.get("actor") == actor.entity_id:
        counted, maximum, exclude = False, 1, (*exclude, *guards["used"])
    options = _exploit_rows(engine, actor)
    if not options or not target.active or engine.state.terminal_result is not None:
        return []
    limit = 2 if sovereign(actor) else 1
    if counted and _uses(actor, engine) >= limit:
        return []
    if qualifying and not _qualifies(ctx, target):
        return []
    held = focus(actor)
    free_second = court(actor)
    can_double = free_second or ("skewer" in kinds(engine, actor.entity_id) and held >= 1)
    if getattr(engine, "_needle_riposte", None) == actor.entity_id and maximum is None:
        maximum = 1  # "You may apply one Exploit talent to this attack"
    cap = maximum if maximum is not None else (2 if can_double else 1)
    pool = [o for o in options if o["id"] not in exclude and _cost(o) <= held and _legal(engine, actor, target, o)]
    if not pool:
        return []
    by_id = {o["id"]: o for o in options}
    chosen: list[dict[str, Any]] = []
    first = _standing(actor, "condition:typed.exploit_pick", "exploit")  # the table's Exploit toggle: a standing choice
    if first and first in {o["id"] for o in pool}:
        chosen = [by_id[first]]
        second = _standing(actor, SKEWER, "pick")
        if cap >= 2 and second:
            other = next((o for o in pool if o["name"] == second and o["id"] != first), None)
            if other is not None:
                chosen.append(other)
    else:
        free = [o for o in pool if _cost(o) == 0]
        preferred = [o["id"] for o in (free or pool)]
        also = next((o["id"] for o in pool if cap >= 2 and o["name"] == _standing(actor, SKEWER, "pick")), None)  # Skewer's standing second pick
        if also and preferred and preferred[0] != also:
            preferred = [preferred[0], also]
        labels = {o["id"]: o["name"] + (" (expends Martial Focus)" if _cost(o) else "") for o in pool}
        from .choice_prompt import action_context

        picked = ask(engine, ctx.intent, checkpoint_id(engine, "EXPLOIT", actor.entity_id, target.entity_id), actor,
                     CHOICE + "exploit", [o["id"] for o in pool], labels=labels, preferred=preferred, minimum=1,
                     maximum=min(cap, len(pool)), allow_decline=True, automatic=True, target_id=target.entity_id,
                     prompt=f"Apply an Exploit to {target.display_name}" + (" (up to two different)" if cap >= 2 else ""),
                     prompt_context=action_context(engine, actor, ctx.source, target))
        chosen = [by_id[i] for i in picked if i in by_id][:cap]
    # The Focus this costs: each Exploit's own, plus Skewer's when two land and Court does not pay for it.
    while chosen:
        total = sum(_cost(o) for o in chosen) + (1 if len(chosen) == 2 and not free_second else 0)
        if total <= held:
            break
        chosen.pop()
    if not chosen:
        return []
    source = ctx.source
    if len(chosen) == 2 and not free_second:
        spend_focus(engine, actor, source, "Skewer: two Exploits on one attack")
    for option in chosen:
        if _cost(option):
            spend_focus(engine, actor, source, f"Exploit: {option['name']}", _cost(option))
    if counted:
        _count_use(actor, engine)
    names = " and ".join(o["name"] for o in chosen)
    _say(engine, source, actor, f"{actor.display_name} applies Exploit: {names} to {target.display_name}" + (f" ({reason})" if reason else "") + ".",
         (target.entity_id,))
    from ..typed_executor import Context, run_effects

    for option in chosen:
        if not target.active:
            break
        run_effects(ctx.on_hit_context(target).with_source(f"passive:{option['id']}"), json.loads(json.dumps(option["effects"])))
    ext_after = [o["id"] for o in chosen]
    if guards and guards.get("actor") == actor.entity_id:
        guards["used"].extend(ext_after)
    if "returning_point" in kinds(engine, actor.entity_id):
        returning_point(ctx, target)
    return ext_after


def melee_weapon_action(engine: Any, actor: Any) -> Any | None:
    """The fencer's own best melee weapon attack (the one its Opportunity Attack is made with), as the action a riposte or a
    charge attacks with: the real weapon action, not the synthesized "Opportunity Attack" (whose typed data marks the attack as an
    opportunity one and whose hooks would treat it so)."""
    from .. import typed_reactions

    row = typed_reactions._opportunity_row(engine, actor)
    action = engine.action_catalog.get(row["action_id"]) if row else None
    if action is None:
        return None
    return engine.action_catalog.get(str(((action.parameters or {}).get("typed") or {}).get("opportunity_of") or "")) or action


RIPOSTED = "needle:riposte_done"  # appended to the hit_absorbed hook's ``reduced_by`` list once the riposte has been made
PARRY_AND_RIPOSTE = "TAL_FENCING_PARRY_AND_RIPOSTE"


def parry_riposte(engine: Any, target: Any, attacker: Any, reduced_by: list[str]) -> None:
    """Parry and Riposte took a melee hit's damage to 0 (owner's Piercing Needle text): "immediately make one melee attack against
    the attacker if it is within your reach. You may apply one Exploit talent to this attack if the attack roll does not have
    Disadvantage, even if the attack would not otherwise satisfy the normal Exploit requirements." Then Sovereign Needle
    Incarnation: "when you ... reduce an attack's damage to 0 with Parry and Riposte, regain Martial Focus" (Needle-Catching
    Reversal's regain, combat/ext/fencing_needle_catching.py, follows the riposte too). Runs once per parried hit, whichever hook
    reaches it first."""
    if not isinstance(reduced_by, list) or RIPOSTED in reduced_by or not any(str(f).split("#")[0] == PARRY_AND_RIPOSTE for f in reduced_by):
        return
    from .attack_reduction import follow_up_scope
    guard_source = next(str(f) for f in reduced_by if str(f).split("#")[0] == PARRY_AND_RIPOSTE)
    with follow_up_scope(engine, target, getattr(attacker, "entity_id", None), guard_source):
        reduced_by.append(RIPOSTED)
        from .. import typed_reactions
        from ..typed_executor import Context, run_effects

        action = melee_weapon_action(engine, target)
        if action is not None and attacker is not None and attacker.active and target.active and attacker.team_id != target.team_id \
                and engine.grid.distance_ft(target.position, attacker.position) <= int(getattr(action, "range_ft", None) or 5):
            _say(engine, f"reaction:{PARRY_AND_RIPOSTE}", target, f"{target.display_name} ripostes {attacker.display_name}.", (attacker.entity_id,))
            typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
            previous, engine._needle_riposte = getattr(engine, "_needle_riposte", None), target.entity_id
            try:
                run_effects(Context(engine, target, action, engine._active_intent, typed, [attacker], attacker), copy.deepcopy(typed.get("effects") or []))
            finally:
                engine._needle_riposte = previous
        if sovereign(target):
            regain_focus(engine, target, SOVEREIGN, "Sovereign Needle Incarnation: Parry and Riposte reduced the damage to 0")


@hook("hit_absorbed")
def _parry_riposte_hook(engine: Any, target: Any, attacker: Any, reduced_by: list[str]) -> None:
    parry_riposte(engine, target, attacker, reduced_by)


@hook("apply_exploit")
def _apply_exploit_hook(ctx: Any, target: Any, **kwargs: Any) -> list[str]:
    return apply_exploit(ctx, target, **kwargs)


# ------------------------------------------------------------------------------------------------ movement helpers
def cell_id(position: Any, *, include_altitude: bool = False) -> str:
    """Shared movement option ID; preserve altitude and optionally spell out ground height."""
    altitude = int(getattr(position, "z", 0))
    return f"cell:{position.x},{position.y}" + (f",{altitude}" if include_altitude or altitude else "")


_cell_id = cell_id


def parse_cell(value: str) -> tuple[int, int, int]:
    """Read full coordinates, while accepting legacy two-coordinate IDs as ground cells."""
    parts = str(value).split(":", 1)[1].split(",")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3:
        raise ValueError(f"Invalid cell option: {value}")
    return tuple(map(int, parts))


_parse_cell = parse_cell


def free_cells(engine: Any, actor: Any, feet: int) -> dict[Any, int]:
    """Squares ``actor`` can step to within ``feet`` (a legal, unoccupied end), with the feet it takes."""
    found = engine.grid.reachable(actor.position, movement_ft=feet, occupied_cells=engine._occupied_cells_except(actor.entity_id),
                                  difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
    cells = {cell: int(cost) for cell, (_path, cost) in found.items() if cost <= feet}
    cells[actor.position] = 0  # staying put is always allowed
    return cells


def step_to(engine: Any, actor: Any, destination: Any, source: str, *, forced: bool = True) -> None:
    """Free, evented movement without Opportunity Attacks (Needle and Evasion).

    ``forced=False`` preserves willing-movement terrain triggers independently of
    Opportunity Attack immunity. The default retains existing callers' behavior.
    Callers moving along a path must revalidate after each step's zone effects.
    """
    start = actor.position
    if destination == start:
        return
    actor.position = destination
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
                         payload={"destination": destination.model_dump(mode="json"), "cost_ft": 0, "footprint_step": True,
                                  "path": [start.model_dump(mode="json"), destination.model_dump(mode="json")]})
    from .. import zones

    zones.on_moved(engine, actor, start, destination, forced=forced)


def cell_options(engine: Any, actor: Any, cells: dict[Any, int], reach_of: Any | None = None, cap: int = 16) -> tuple[list[str], dict[str, str]]:
    """Shared cell labels for Needle, Force, Shadow and Monkey movement choices."""
    ordered = sorted(cells, key=lambda cell: (cells[cell], cell.z, cell.y, cell.x))[:cap]
    labels = {cell_id(cell): f"Step to {cell.x},{cell.y}" + (f", {cell.z * engine.grid.square_size_ft} feet high" if cell.z else "") + (f" ({cells[cell]} ft)" if cells[cell] else " — stay where you are") for cell in ordered}
    return [cell_id(cell) for cell in ordered], labels


_cell_options = cell_options


def position_of(option: str) -> Any:
    from ..gate2_runtime_models import Position

    x, y, z = parse_cell(option)
    return Position(x=x, y=y, z=z)


def _reposition_cells(engine: Any, actor: Any, target: Any, reach: int = 5) -> list[Any]:
    """Unoccupied squares the target could be moved to: within 5 feet of it and within the fencer's reach (a melee attack's)."""
    return [cell for cell in free_cells(engine, target, 5) if cell != target.position
            and engine.grid.distance_ft(actor.position, cell) <= max(5, int(reach or 5))]


def _size_ok(engine: Any, actor: Any, target: Any, larger: int) -> bool:
    return engine._footprint(target).width_cells <= engine._footprint(actor).width_cells + larger


def _wide_open_allies(engine: Any, actor: Any) -> list[Any]:
    return [other for other in engine.state.actors.values()
            if other.active and other.team_id == actor.team_id and other.entity_id != actor.entity_id]


def returning_point(ctx: Any, target: Any) -> None:
    """Once per turn, after an Exploit lands: a free step of up to 5 feet, no Opportunity Attacks from that creature."""
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("needle_returning_point") or not actor.active or engine._effective_speed(actor) <= 0:
        return
    cells = free_cells(engine, actor, 5)
    if len(cells) <= 1:
        return
    actor.turn_flags["needle_returning_point"] = True
    options, labels = _cell_options(engine, actor, cells)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "RETURNING", actor.entity_id, target.entity_id), actor, CHOICE + "returning_point",
                 options, labels=labels, preferred=[o for o in options if o == cell_id(actor.position)], allow_decline=True, automatic=True,
                 prompt="Returning Point: step up to 5 feet", target_id=target.entity_id, default="first")
    if not picked or picked[0] == cell_id(actor.position):
        return
    step_to(engine, actor, position_of(picked[0]), "passive:TAL_FENCING_RETURNING_POINT")
    _say(engine, "passive:TAL_FENCING_RETURNING_POINT", actor, f"Returning Point: {actor.display_name} steps away from {target.display_name}.")


# ------------------------------------------------------------------------------------------------ Exploit effect ops
def _rounds(effect_row: dict[str, Any], numbers: dict[str, Any]) -> int:
    value = effect_row.get("rounds", "pb")
    pb = int(numbers.get("pb") or 2)
    if value == "half_pb_up":
        return max(1, (pb + 1) // 2)
    return pb if value == "pb" else int(value)


@effect("needle_rounds")
def rounds(ctx: Any, eff: dict[str, Any]) -> None:
    """The nested effects last a number of rounds -- "equal to your Proficiency Bonus" ("pb") or half of it rounded up
    ("half_pb_up") -- counted on the round clock (combat/ext/effect_durations.py)."""
    from ..typed_executor import run_effects

    expiry = pb_rounds(ctx.engine, ctx.actor, _rounds(eff, ctx.numbers))
    nested = [{**copy.deepcopy(row), "expires_on": expiry} for row in eff.get("effects") or [] if isinstance(row, dict)]
    run_effects(ctx, nested)


@effect("needle_condition")
def needle_condition(ctx: Any, eff: dict[str, Any]) -> None:
    """A Needle penalty on the subject (Arm Strike, Soul Strike, Shadow Strike): one from the same fencer refreshes rather than
    stacks ("multiple uses do not stack ... a later failed save refreshes the duration")."""
    key = str(eff["key"])
    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        if subject is None or not subject.active:
            continue
        data = {"label": eff.get("label") or key, "kind": key, **({"speed_delta": int(eff["speed_delta"])} if eff.get("speed_delta") else {}),
                **({"level": 1} if eff.get("temporary_exhaustion") else {})}
        timed_condition(ctx.engine, subject, PENALTY + key, ctx.source, ctx.actor.entity_id, eff.get("expires_on") or "UNTIL_REMOVED", data)
        _say(ctx.engine, ctx.source, ctx.actor, f"{subject.display_name}: {eff.get('label') or key}.", (subject.entity_id,))


def _bears(actor: Any, key: str) -> bool:
    return condition(actor, PENALTY + key) is not None


def _limb_attack(ctx: Any) -> bool:
    """Arm Strike's "attack rolls made with a weapon, natural weapon, or object held or controlled primarily by that limb": an attack
    with a weapon action (the character's weapons, improvised objects, a natural weapon) or an Unarmed Strike -- not a Cultivation
    Attack (rider lane 10, 2026-09-29; the penalty had landed on every typed attack)."""
    if (getattr(ctx, "typed", None) or {}).get("weapon") is not None:
        return True
    return any(isinstance(row, dict) and row.get("type") == "attack" and str(row.get("attack_kind") or "") in ("weapon", "unarmed", "natural")
               for row in (ctx.typed or {}).get("effects") or [])


def _limb_check(ctx: Any) -> bool:
    """Arm Strike's "Strength and Dexterity ability checks that rely primarily on that limb": the table's own Strength/Dexterity check,
    the Athletics or Acrobatics check to escape a grapple (typed_executor.block_escape_grapple)."""
    return any(isinstance(row, dict) and row.get("type") == "escape_grapple" for row in (getattr(ctx, "typed", None) or {}).get("effects") or [])


@hook("attack_bonus")
def _attack_penalty(ctx: Any, actor: Any) -> int | None:
    """Arm Strike: -2 to attack rolls with the affected limb's weapon; Shadow Strike: a temporary Exhaustion level (-2 to a d20 Test)."""
    penalty = (-2 if _bears(actor, "arm_strike") and _limb_attack(ctx) else 0) + (-2 if _bears(actor, "shadow_strike") else 0)
    return penalty or None


@hook("save")
def _save_penalty(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    penalty = (-2 if _bears(subject, "soul_strike") else 0) + (-2 if _bears(subject, "shadow_strike") else 0)
    return {"bonus": penalty} if penalty else None


@hook("check_bonus")
def _check_penalty(ctx: Any, actor: Any) -> int | None:
    penalty = (-2 if _bears(actor, "shadow_strike") else 0) + (-2 if _bears(actor, "arm_strike") and _limb_check(ctx) else 0)
    return penalty or None


@effect("needle_wide_open")
def wide_open(ctx: Any, eff: dict[str, Any]) -> None:
    """Wide Open: one ally other than yourself has Advantage on the next attack roll against the target, until the start of your next turn."""
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    allies = _wide_open_allies(engine, actor)
    if target is None or not allies:
        return
    ids = [ally.entity_id for ally in allies]
    near = sorted(allies, key=lambda ally: (engine.grid.distance_ft(ally.position, target.position), ally.entity_id))
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "WIDE_OPEN", actor.entity_id, target.entity_id), actor, CHOICE + "wide_open", ids,
                 labels={ally.entity_id: ally.display_name for ally in allies}, preferred=[near[0].entity_id],
                 prompt=f"Wide Open: which ally gets Advantage against {target.display_name}?", target_id=target.entity_id)
    ally = engine.state.actors.get(picked[0]) if picked else near[0]
    if ally is None:
        return
    from .effect_durations import token

    # "until the start of your next turn": the fencer's turn counter + 1, exact whether or not it is the one acting
    engine._add_modifier(ally, ctx.source, "attack_mode_vs", "SET", f"ADVANTAGE:{target.entity_id}", "NEXT_ATTACK",
                         expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1))
    _say(engine, ctx.source, actor, f"Wide Open: {ally.display_name} has Advantage on the next attack roll against {target.display_name}.", (ally.entity_id,))


@effect("needle_reposition")
def reposition(ctx: Any, eff: dict[str, Any]) -> None:
    """Repositioning Strike: if the target is no more than one size larger than you, move it up to 5 feet to an unoccupied space
    within your reach, without Opportunity Attacks."""
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    size_ok = _size_ok(engine, actor, target, 1)
    if eff.get("size_category_gate"):
        from ..dynamic_size import CATEGORIES, current_category
        size_ok = CATEGORIES.index(current_category(engine, target)) <= CATEGORIES.index(current_category(engine, actor)) + 1
    if not size_ok:
        return
    label = str(eff.get("label") or "Repositioning Strike")
    cells = _reposition_cells(engine, actor, target, ctx.action.range_ft)
    if not cells:
        from ..typed_executor import run_effects
        run_effects(ctx, eff.get("on_blocked") or [])
        return
    options = [cell_id(cell) for cell in sorted(cells, key=lambda cell: (cell.y, cell.x))][:16]
    away = max(cells, key=lambda cell: (engine.grid.distance_ft(actor.position, cell), -cell.y, -cell.x))
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "REPOSITION", actor.entity_id, target.entity_id), actor, CHOICE + "reposition", options,
                 labels={o: f"Move it to {o.split(':', 1)[1]}" for o in options}, preferred=[cell_id(away)] if cell_id(away) in options else [],
                 prompt=f"{label}: where does {target.display_name} go?", target_id=target.entity_id)
    if picked:
        previous = target.position
        step_to(engine, target, position_of(picked[0]), ctx.source)
        if target.position == previous:
            from ..typed_executor import run_effects
            run_effects(ctx, eff.get("on_blocked") or [])
            return
        _say(engine, ctx.source, actor, f"{label}: {actor.display_name} moves {target.display_name} to {picked[0].split(':', 1)[1]}.", (target.entity_id,))


# ------------------------------------------------------------------------------------------------ Bleed Air (5.5e Suffocation)
@effect("needle_bleed_air")
def bleed_air(ctx: Any, eff: dict[str, Any]) -> None:
    """Failed save: roll 1d4; after that many rounds the target begins choking (the ordinary 5.5e Suffocation hazard: it survives
    a number of rounds equal to its Constitution modifier, at least 1, then drops to 0 Hit Points), unless it is restored to its Hit
    Point maximum first. (A Wisdom (Medicine) Utilize action by a creature in reach ends it: the GM's.)"""
    from ..gate2_runtime_models import DiceSpec

    engine, actor = ctx.engine, ctx.actor
    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        if subject is None or not subject.active:
            continue
        roll = engine.roller.roll(DiceSpec(count=1, sides=4, modifier=0), actor_id=actor.entity_id, reason=f"BLEED_AIR:{ctx.source}")
        engine._record_roll(roll)
        begins = int(engine.state.round_number) + int(roll.total)
        timed_condition(engine, subject, PENALTY + "bleed_air", ctx.source, actor.entity_id, "UNTIL_REMOVED",
                        {"label": f"Bleed Air: begins choking in {int(roll.total)} rounds", "kind": "bleed_air", "begins_round": begins,
                         "dc": int(ctx.numbers.get("save_dc") or save_dc(engine, actor))})
        _say(engine, ctx.source, actor, f"Bleed Air: {subject.display_name} begins choking in {int(roll.total)} round(s) unless restored to full Hit Points.",
             (subject.entity_id,))


def _con_mod(actor: Any) -> int:
    return max(1, (int(actor.saving_throws.get("CON", 0)) if "CON" in actor.saving_throws else 0))


@hook("turn_start")
def _bleed_air_clock(engine: Any, actor: Any) -> None:
    if not actor.active:
        return
    for iid, found in list(actor.conditions.items()):
        if found.condition_id != PENALTY + "bleed_air":
            continue
        data = found.data or {}
        if actor.current_hp >= actor.maximum_hp:  # "The effect ends ... if the target is restored to its Hit Point maximum."
            engine._remove_condition(actor, found.condition_id, "system:needle.bleed_air")
            _say(engine, "system:needle.bleed_air", actor, f"Bleed Air ends on {actor.display_name}: restored to full Hit Points.")
            continue
        now = int(engine.state.round_number)
        if data.get("dies_round") is not None:
            if now >= int(data["dies_round"]):
                engine._remove_condition(actor, found.condition_id, "system:needle.bleed_air")
                _say(engine, "system:needle.bleed_air", actor, f"{actor.display_name} has been choking too long and drops to 0 Hit Points.")
                engine._commit_damage(actor, int(actor.current_hp) + int(actor.temporary_hp), "SUFFOCATION", "system:needle.bleed_air", found.source_actor_id, None, reaction_depth=0)
            continue
        if now >= int(data.get("begins_round") or 0):
            survive = _con_mod(actor)
            timed_condition(engine, actor, PENALTY + "bleed_air", "system:needle.bleed_air", found.source_actor_id, "UNTIL_REMOVED",
                            {"label": "Choking (Bleed Air)", "kind": "bleed_air", "dies_round": now + survive,
                             **({"dc": data["dc"]} if data.get("dc") else {})})
            _say(engine, "system:needle.bleed_air", actor, f"{actor.display_name} begins choking (Bleed Air): {survive} round(s) to breathe again.")


# ------------------------------------------------------------------------------------------------ Court and Sovereign
@effect("needle_domain")
def domain(ctx: Any, eff: dict[str, Any]) -> None:
    """Court of Measured Openings / Sovereign Needle Incarnation: "Duration: 1 minute" (10 rounds on the round clock); each ends early
    if its owner has the Incapacitated condition (the event hook below). The benefits are read by the plug-ins that grant them:
    apply_exploit (two Exploits without Skewer's Focus; twice a round), needle_feint (the free Feints), needle_footwork (Footwork),
    and the "attacks you make count as magical" marker below."""
    which = str(eff.get("domain") or "court")
    condition_id = COURT if which == "court" else SOVEREIGN
    label = "Court of Measured Openings" if which == "court" else "Sovereign Needle Incarnation"
    expires = pb_rounds(ctx.engine, ctx.actor, 10)
    timed_condition(ctx.engine, ctx.actor, condition_id, ctx.source, ctx.actor.entity_id, expires, {"label": label, "kind": which})
    if which != "court":
        # "attacks you make count as magical for the purpose of overcoming Resistance or Immunity to nonmagical attacks and
        # damage": its own condition, so the sheet shows the printed benefit and the attack_magical hook below reads it.
        timed_condition(ctx.engine, ctx.actor, MAGICAL, ctx.source, ctx.actor.entity_id, expires, {"label": label, "kind": "sovereign"})
    _say(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} enters {label} (1 minute).")


@hook("attack_magical")
def _attacks_are_magical(engine: Any, source_actor_id: str | None, typed: dict[str, Any]) -> bool:
    """Sovereign Needle Incarnation: "attacks you make count as magical for the purpose of overcoming Resistance or Immunity to
    nonmagical attacks and damage". Default-inert: True only while its owner bears the printed condition, and only for the core
    ``attack_magical`` seam in combat/typed_reactions.py (a defense printed against nonmagical attacks)."""
    actor = engine.state.actors.get(source_actor_id or "")
    return actor is not None and condition(actor, MAGICAL) is not None


@hook("event")
def domains_end_when_incapacitated(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"... ends early if you have the Incapacitated condition." Watched whenever a condition lands on a creature that holds one.
    Sovereign's "attacks count as magical" mark goes with it, so an Incapacitated fencer cannot keep fighting magically."""
    if event_type != "CONDITION_APPLIED":
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is None or not (court(holder) or sovereign(holder)) or not incapacitated(holder):
            continue
        for condition_id in (COURT, SOVEREIGN, MAGICAL):
            if condition(holder, condition_id) is not None:
                engine._remove_condition(holder, condition_id, "system:needle.domain")
                _say(engine, "system:needle.domain", holder, f"{holder.display_name} is Incapacitated: the Martial Domain ends.")


# ------------------------------------------------------------------------------------------------ rider lane 10 (2026-09-29)
FACE_STRIKE = PENALTY + "face_strike"


@effect("needle_face_strike_mark")
def face_strike_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """Face Strike's failed save has just made the target Blinded for 1 minute (the row before this one): "The target or a creature
    within its reach may take the Utilize action to wipe away blood, dust, or another obstruction and end the effect early." A marker
    with the same deadline names that Blinded instance, so the Utilize action (combat/ext/utilize_end.py) ends it and no other
    blindness."""
    engine = ctx.engine
    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        if subject is None or not subject.active:
            continue
        mine = [(iid, c) for iid, c in subject.conditions.items()
                if c.condition_id == "condition:typed.blinded" and c.source_actor_id == ctx.actor.entity_id]
        if not mine:
            continue  # the save succeeded, or the creature cannot be Blinded
        iid, blinded = mine[-1]
        timed_condition(engine, subject, FACE_STRIKE, ctx.source, ctx.actor.entity_id, blinded.expires_on or "UNTIL_REMOVED",
                        {"label": "Face Strike: Blinded (a Utilize action wipes it away)", "kind": "face_strike",
                         "linked": [iid], "linked_condition": "condition:typed.blinded"})


@hook("reaction_amount")
def parry_damage(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any] | None = None) -> int | None:
    """Parry and Riposte: "Roll the normal damage of that attack form and reduce the triggering attack's damage by the amount rolled":
    the fencer's own melee weapon (the one its Opportunity Attack uses) -- its damage dice and the modifier it adds (ability modifier,
    a magic weapon's bonus). "If you use an Unarmed Strike that has no damage die, reduce the triggering damage by 1 + the ability
    modifier ... The reduction cannot be less than 0." Extra dice from hits, criticals, resources or other triggers are not included:
    the weapon profile carries none of them."""
    from ..gate2_runtime_models import DiceSpec

    if effect is not None and not effect.get("weapon_damage"):
        return None

    action = melee_weapon_action(engine, actor)
    weapon = (((action.parameters or {}).get("typed") or {}).get("weapon") or {}) if action is not None else {}
    damage = weapon.get("damage") or {}
    count, sides, modifier = int(damage.get("count") or 0), int(damage.get("sides") or 0), int(damage.get("modifier") or 0)
    if count > 0 and sides > 1:
        roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=modifier), actor_id=actor.entity_id,
                                  reason=f"PARRY:{row.get('feature_id') or PARRY_AND_RIPOSTE}")
        engine._record_roll(roll)
        return max(0, int(roll.total))
    return max(0, 1 + (modifier if damage else int((row.get("numbers") or {}).get("key_mod") or 0)))
