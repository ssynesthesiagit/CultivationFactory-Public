"""The Thread Sphere's follow-ups that hang on a Thread Line or a mark (riders lane 4, 2026-09-29).

Source (owner text: authority/typed_mechanics/rules_text.json THREAD_BASE_* and tianxia.talent.thread.*; the Sphere Compendium's
Thread chapter -- there is no Spheres 5e or D&D 5.5e equivalent to fall back on):
  Thread Attacks: "When a Thread talent calls for a Thread Attack, use either a melee weapon attack with a thread-eligible weapon,
  a ranged weapon attack with a needle or thrown thread tool, or a Cultivation Attack roll."  So a Thread Attack is the attack a
  Thread ability makes; the plug-in reads it from the ability the attack belongs to (a Thread Sphere id) and never from the
  weapon.
  Threaded Strike -- Draw the Guard: "Your next Thread Attack against the target before the end of your next turn has advantage."
  Threaded Strike -- Tighten the Wrist: "The target has disadvantage on the next Opportunity Attack it makes before the start of
  your next turn."
  Needle Guide: "If the target is connected by this line, your next Thread Attack against it before the end of your next turn
  gains a +2 bonus."
  Meridian Snare -- Repeat Use: "A creature affected by Meridian Snare has advantage on saves against your Meridian Snare until
  the end of your next turn."  (Affected = it failed the save: the option's failed save places the mark.)
  Meridian Stitch: "Touch, or 30 feet through an active Qi Thread"; Hostile Use: "target an unwilling creature with an active
  Thread Line".  The mark cannot tell a Qi Thread from an ordinary line, so any of the user's Thread Lines counts.

Each is a mark (typed ``mark`` effect: combat/typed_executor.py block_mark) that this module reads when the roll is made and
removes once it has been used ("next").  The marks are ordinary conditions, so a saved fight replays them.

Binding Sleeve Method (a modifier of Binding Knot): "When you hit with Binding Knot, you may choose to bind a limb ... instead of
imposing the Grappled condition. Until the target escapes, one chosen mode is impaired.  Weapon Hand: Disadvantage on attacks
using that hand or manipulator.  Footwork: Speed reduced by 15 feet.  Wing: Flying speed reduced by 20 feet ...  Tail or Balance:
Disadvantage on Dexterity saving throws.  The target may escape as normal for Binding Knot."  Effect type ``bind_limb`` puts the
mode's condition (combat/rules/typed_conditions.json bound_footwork / bound_balance) and a ``bound_limb`` marker on
the target, until removed; an "Escape the binding" action (any creature's, offered while bound) is the same Action check as
escaping a grapple, against the binder's save DC.  Wing records a keyed 20-foot Fly Speed reduction; native flight/falling resolves it.
Weapon Hand retains the binding/escape and logs the hand-specific penalty for the
GM; without attack-hand provenance it never imposes blanket attack Disadvantage.

Every Thread mark is read through the one shared lookup of combat/ext/thread_common.py (mark_held_by), and the
Thread Line's own cells -- at the height the thread is really at, so a creature above or below it is not on it --
through thread_common.thread_line_cells.  The module below holds no second copy, so a Thread Line means one thing
to every Thread talent (change standard, modularity 4).
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook
from .thread_common import LINE, cell_of, mark_held_by, thread_line_cells

GUARD = "Draw the Guard"
WRIST = "Tightened Wrist"
NEEDLE = "Needle Guide"
SNARE = "Meridian Snare"
SNARE_ID = "TAL_THREAD_MERIDIAN_SNARE"
STITCH_ID = "TAL_THREAD_MERIDIAN_STITCH"


def _mechanic(action: Any) -> str:
    """The authority id a compiled action came from (its own id is ``action:typed.<hash>.<mechanic id>``)."""
    return str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) or "")


def is_thread_attack(action: Any) -> bool:
    """An attack made by a Thread ability (a Thread Attack)."""
    source = _mechanic(action).lower()
    return source.startswith(("thread_base_", "tal_thread_")) or ".talent.thread." in source


def _held(actor: Any, owner_id: str, mark: str) -> str | None:
    """The condition id of ``mark`` placed by ``owner_id`` on ``actor``, when it bears it (the shared Thread mark
    lookup of combat/ext/thread_common.py)."""
    return mark_held_by(actor, owner_id, mark)


def _spend(engine: Any, holder: Any, owner_id: str, mark: str, source: str) -> bool:
    condition_id = _held(holder, owner_id, mark)
    if condition_id is None:
        return False
    engine._remove_condition(holder, condition_id, source)
    return True


@hook("attack_mode")
def attack_mode(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    engine._tl_attack_target = target.entity_id  # attack_bonus below is given no target; this runs just before it for the same roll
    # Tighten the Wrist: the creature the mark sits on makes its next Opportunity Attack with Disadvantage.
    if getattr(engine, "_typed_oa_attacker", None) == actor.entity_id:
        owners = [row.source_actor_id for row in actor.conditions.values() if row.condition_id.startswith("condition:typed.mark.tightened_wrist.")]
        if owners and _spend(engine, actor, owners[0], WRIST, ctx.source):
            return "DISADVANTAGE"
    # Draw the Guard: the marker's next Thread Attack against the marked creature has Advantage.
    if is_thread_attack(ctx.action) and _spend(engine, target, actor.entity_id, GUARD, ctx.source):
        return "ADVANTAGE"
    return None


@hook("attack_bonus")
def attack_bonus(ctx: Any, actor: Any) -> int | None:
    engine = ctx.engine
    target = engine.state.actors.get(getattr(engine, "_tl_attack_target", None) or "")
    engine._tl_attack_target = None
    if target is None or target.team_id == actor.team_id or not is_thread_attack(ctx.action):
        return None
    # Needle Guide: connected by the line the needle made, the next Thread Attack against the target gains +2.
    if _held(target, actor.entity_id, LINE) and _spend(engine, target, actor.entity_id, NEEDLE, ctx.source):
        return 2
    return None


@hook("save")
def repeat_snare(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Meridian Snare's Repeat Use: a creature it already affected saves against it with Advantage."""
    if _mechanic(ctx.action) == SNARE_ID and _held(subject, ctx.actor.entity_id, SNARE):
        return {"modes": ["ADVANTAGE"]}
    return None


@hook("candidate_allowed")
def stitch_reach(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Meridian Stitch is a touch (5 feet) ability, or reaches 30 feet through the user's Thread Line; its Hostile Use needs the line."""
    if _mechanic(action) != STITCH_ID:
        return None
    hostile = str(getattr(action, "display_name", "")).endswith("Hostile Use")
    for target_id in candidate.target_ids or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        if not _held(target, actor.entity_id, LINE) and (hostile or engine._distance_actor_to_actor(actor, target) > 5):
            return False
    return None


# ------------------------------------------------------------------------------------------------ Binding Sleeve Method
BOUND = "condition:typed.bound_limb"
MODES = {"hand": ("bound_hand", "Weapon hand bound"), "footwork": ("bound_footwork", "Footwork bound (Speed -15 ft)"),
         "balance": ("bound_balance", "Balance bound (Disadvantage on Dexterity saves)"),
         "wing": ("bound_wing", "Wing bound (Fly Speed -20 ft)")}
FOOTWORK_FT = 15


def _is_bound_condition(condition_id: str) -> bool:
    return condition_id == BOUND or condition_id in {"condition:typed." + name for name, _ in MODES.values()}


def _release(engine: Any, holder: Any, source: str, binder_id: str, binding_source: str | None = None) -> None:
    from .riders_shared import remove_benefit_condition

    for condition in list(holder.conditions.values()):
        if (_is_bound_condition(condition.condition_id) and condition.source_actor_id == binder_id
                and (binding_source is None or condition.source_definition_id == binding_source)):
            remove_benefit_condition(engine, holder, condition, "BINDING_ENDED")


@effect("bind_limb")
def bind_limb(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import CONDITION_PREFIX, _default_subject, condition_immune

    name, label = MODES[str(eff.get("mode") or "hand")]
    dc = int((ctx.numbers or {}).get("save_dc") or 10)
    for subject in _default_subject(ctx, eff, harmful=True):
        if condition_immune(ctx.engine, subject, "grappled"):
            continue  # a limb bound with a Thread Line is held like a grapple
        # "instead of imposing the Grappled condition": the modifier's rows run after the base ability's, so the grapple this very
        # use put on the target is taken off again.
        for condition in list(subject.conditions.values()):
            if condition.condition_id == CONDITION_PREFIX + "grappled" and condition.source_actor_id == ctx.actor.entity_id \
                    and condition.source_definition_id == ctx.source:
                from .riders_shared import remove_benefit_condition
                remove_benefit_condition(ctx.engine, subject, condition, "BOUND_LIMB_REPLACED_GRAPPLE")
        _release(ctx.engine, subject, ctx.source, ctx.actor.entity_id)  # "one chosen mode": a new binding replaces the last
        # Hand provenance is absent: retain the binding/escape, but leave the
        # hand-specific attack penalty to the GM instead of penalizing every attack.
        if eff.get("mode") == "hand":
            ctx.engine._append_event("GM_RIDER", ctx.source, actor_id=ctx.actor.entity_id,
                                    target_ids=(subject.entity_id,), payload={"rider":
                f"Binding Sleeve Method: {subject.display_name} has Disadvantage only on attacks using the bound hand or manipulator (GM: attack hand provenance)."})
        for condition_id in ((BOUND,) if eff.get("mode") == "hand" else (CONDITION_PREFIX + name, BOUND)):
            ctx.engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"label": label, "escape_dc": dc, "mode": eff.get("mode"),
                                              **({"fly_speed_reduction_ft": 20,
                                                  "fly_speed_reduction_key": f"binding:{ctx.actor.entity_id}:{ctx.source}",
                                                  "binding_replacement_intent": ctx.intent.intent_id if ctx.intent else None}
                                                 if eff.get("mode") == "wing" else {})})


@hook("speed")
def bound_footwork(engine: Any, actor: Any) -> int | None:
    if any(condition.condition_id == "condition:typed.bound_footwork" for condition in actor.conditions.values()):
        return -FOOTWORK_FT
    return None


@hook("compile_actions")
def escape_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import _skill_bonus
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    mods, sheet = info["mods"], info["owner_sheet"]
    bonus = max(_skill_bonus(sheet, "Athletics", mods.get("STR", 0)), _skill_bonus(sheet, "Acrobatics", mods.get("DEX", 0)))
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.escape_binding", display_name="Escape the binding", owner_id=info["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "escape_binding", "bonus": bonus}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": []},
                    "expected_damage": 1, "requires_condition": BOUND})]


@hook("button_description")
def escape_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    eff = next((eff for eff in effects if eff.get("type") == "escape_binding"), None)
    if eff is not None:
        return (f"Action: escape a Binding Sleeve Method affecting you. Normally, the check uses the higher of your "
                "Strength (Athletics) and Dexterity (Acrobatics) bonuses against the binder's Cultivation Save DC. "
                "If you are grounded inside a hostile Heaven-Net Casting, you may choose either skill; the check uses "
                "that skill's bonus, and Acrobatics has Disadvantage. "
                "Success ends the chosen binding and its impairment; failure leaves it in place.")
    return None


@effect("escape_binding")
def escape_binding(ctx: Any, eff: dict[str, Any]) -> None:
    """Escaping a Binding Sleeve: the same check as escaping a grapple (Athletics or Acrobatics, against the binder's save DC)."""
    from .escape_checks import resolve_escape_check

    engine, actor = ctx.engine, ctx.actor
    held = [c for c in actor.conditions.values() if c.condition_id == BOUND]
    if not held:
        return
    from .needle import CHOICE, ask, checkpoint_id

    binding = held[0]
    if len(held) > 1 and getattr(ctx, "intent", None) is not None:
        labels = {c.instance_id: "Binding Sleeve Method from " + engine.state.actors[c.source_actor_id].display_name
                  for c in held}
        selected = ask(engine, ctx.intent, checkpoint_id(engine, "binding_escape", actor.entity_id), actor,
                       CHOICE + "binding_escape", list(labels), labels=labels, name="Binding Sleeve Method",
                       prompt=f"Escape the binding: {actor.display_name} chooses which Binding Sleeve Method to escape.")
        if not selected:
            return
        binding = next(c for c in held if c.instance_id == selected[0])
    dc = int((binding.data or {}).get("escape_dc") or 10)
    if resolve_escape_check(ctx, eff, dc, [binding], check_name="Escape"):
        _release(engine, actor, ctx.source, binding.source_actor_id, binding.source_definition_id)


# ----------------------------------------------------------------------------------------------- Snaring Crossing
SNARING = "tianxia.talent.thread.snaring_crossing"
SNARING_BLOCK = "thread_snare"
# "A creature can be affected by your Snaring Crossing only once per round."  A turn flag on the Thread user,
# keyed to the creature that crossed, so two creatures crossing in one round are each snared once.  The key starts
# with "once_per_round:", the one spelling gate2_engine._system_start_turn keeps when it clears a turn's flags --
# a Thread user whose own turn comes round again must not lose the limit it already spent.
_ONCE = "once_per_round:thread_snaring"


@hook("compile_block")
def snaring_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Ownership row: the printed trigger is a creature crossing one of the user's Thread Lines, which the generic
    ``moved`` reaction cannot read (it sees only that somebody moved, and never which squares).  The moment is
    answered from the per-step movement checkpoint instead, against the printed line geometry."""
    if block != SNARING_BLOCK:
        return None
    return [{**row, "block": SNARING_BLOCK}]


def _snarers(engine: Any) -> list[Any]:
    return [actor for actor in engine.state.actors.values()
            if actor.active and any(r.get("block") == SNARING_BLOCK
                                   for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))]


def _pays_with(engine: Any, user: Any, intent: Any, mover: Any) -> str | None:
    """"Cost: Expend Martial Focus or spend 1 CP."  A player picks which they spend, or passes and nothing happens;
    with nobody answering (an AI fight) Martial Focus is spent first, then 1 CP (the printed order)."""
    from ..typed_executor import CP_POOLS
    from .needle import CHOICE, ask, checkpoint_id

    focus = int(user.resources.get("resource:core.martial_focus", 0))
    pools = [pool for pool in CP_POOLS if user.resource_maximums.get(pool, 0) > 0]
    cp = max(pools, key=lambda pool: user.resources.get(pool, 0), default="")
    options = [key for key, held in (("focus", focus > 0), ("cp", bool(cp) and user.resources.get(cp, 0) >= 1)) if held]
    if not options:
        return None
    choice = checkpoint_id(engine, "snaring_crossing", f"{user.entity_id}:{mover.entity_id}")
    labels = {"focus": f"Expend Martial Focus ({focus} held)",
              "cp": f"Spend 1 CP ({user.resources.get(cp, 0)} held)"}
    picked = ask(engine, intent, choice, user, CHOICE + "snaring_crossing", options, labels=labels,
                 preferred=options[:1], allow_decline=True, name="Snaring Crossing", target_id=mover.entity_id,
                 prompt=f"Snaring Crossing (your Reaction): {mover.display_name} is stepping across one of your Thread Lines. "
                        f"On a failed Dexterity saving throw its Speed becomes 0 until the end of its current turn, so it "
                        f"stops there; on a success it loses 10 feet of Speed instead. Each creature can be snared only "
                        f"once per round. Using it costs your Reaction and either your Martial Focus or 1 CP (cultivation "
                        f"points from your Qi, Stamina or other pool). Use your Reaction?")
    if not picked:
        # An empty answer is the player pressing Pass, not nobody answering: the printed cost and the printed
        # limit are then both untouched.
        return None
    return "resource:core.martial_focus" if picked[0] == "focus" else (cp or None)


def _crosses_a_line(engine: Any, user: Any, mover: Any, previous: Any, nxt: Any) -> bool:
    """"moves across a space containing one of your Thread Lines": does this five-foot step leave or enter one of
    the cells a Thread Line of ``user`` runs through (combat/ext/thread_common.thread_line_cells, which reads
    Draw the Line's own "a Thread Line between yourself or an anchor you control and the target").  The cell is
    compared in three dimensions, so a creature that passes over or under the thread has not stepped on it."""
    cells = thread_line_cells(engine, user)
    return bool(cells & {cell_of(previous), cell_of(nxt)})


def _still_crossing(engine: Any, mover: Any, previous: Any) -> bool:
    """Whether this step can still be charged, so a printed reaction at it is still worth asking about: the mover
    is still standing in the square it was in, still has Speed left to cross with, and the fight has not ended.

    The first cut of this hook returned after answering for the first eligible Thread user, which also meant a
    second user whose own line the same step crossed was never offered their printed Reaction, and there was no
    later checkpoint to recover it on a one-step move.  So the loop keeps asking -- and stops exactly here, once
    a preceding answer has left the creature with nothing to cross with: Speed taken away, pushed out of the
    square, knocked down, or the fight over."""
    return (mover.active and mover.position == previous and engine._effective_speed(mover) > 0
            and (engine.state.terminal_result is None or bool(getattr(engine, "_final_rider_active", False))))


@hook("movement_attempt")
def snaring_crossing(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Snaring Crossing, at the printed moment and not a moment later: "A creature you can see moves across a space
    containing one of your Thread Lines or moves out of a space adjacent to an anchor you control."

    The per-step checkpoint runs before the step is charged and before the mover leaves the square it is in, so a
    failed save (Speed becomes 0) stops the creature on the near edge of the line instead of letting it walk the
    whole submitted path first.  A successful save only takes 10 feet of Speed away, so the creature goes on.

    Two Thread users' lines can cover the same step, and the printed once-per-creature limit is each user's own, so
    every eligible owner is offered their own Reaction for it while the step remains possible (see
    ``_still_crossing``).  The printed effect speaks for itself: a successful save never stops the move.

    The second printed alternative -- a fixed anchor you control -- is not a thing the table keeps track of, so it
    stays a GM reminder on the reviewed record rather than an unearned claim of full coverage.
    """
    from ..target_knowledge import can_see

    if not mover.active:
        return None
    for user in _snarers(engine):
        if not _still_crossing(engine, mover, previous):
            break  # a preceding owner has already stopped, moved or floored the creature: no crossing is left
        if user.entity_id == mover.entity_id or not user.reaction_available:
            continue
        if user.turn_flags.get(f"{_ONCE}:{mover.entity_id}") == engine.state.round_number:
            continue  # "only once per round"
        if not can_see(engine, user, mover) or not _crosses_a_line(engine, user, mover, previous, nxt):
            continue
        payment = _pays_with(engine, user, intent, mover)
        if payment is None:
            continue
        from ..typed_numbers import authority_mechanics
        from ..typed_reactions import spend_reaction, triggered_context
        from ..typed_executor import run_effects
        from .needle import numbers_of

        effects = (authority_mechanics().get(SNARING) or {}).get("effects") or []
        if not effects:
            continue
        with activation(engine, user, SNARING):
            engine._spend_resource(user, payment, 1, SNARING)
            spend_reaction(engine, user, {"feature_id": SNARING})
            user.turn_flags[f"{_ONCE}:{mover.entity_id}"] = engine.state.round_number
            run_effects(triggered_context(engine, user, mover, {
                "feature_id": SNARING, "name": "Snaring Crossing", "effects": effects,
                "numbers": numbers_of(engine, user)}, intent), effects)
    return None
