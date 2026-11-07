"""Printed Iron Fist follow-ups, compiled from hash-bound ``iron_fist_rider`` rows.
Shared public helpers serve Iron Fist riders, Forms, Diagnosis and their placement/menu consumers.

Rows carry ``kind`` and an optional choose-N ``menu``. compile_actions freezes the
owned rows on the fighter's actions; old bundles without them retain old behavior.
Falling Leaf uses the existing extension choice transport for actual targets;
Hammer-and-Anvil offers all three printed options; Meridian Lock offers two seals
or one seal plus Body-Locked. Heaven-Seizing upgrades clinch size and speed.
No saved-fight model, controller or persistence changes are needed.
Rooting Stance uses ``iron_rooting`` (reduction: 5 or paid 10) and the pure
``forced_movement_reduction(ctx, subject)`` hook before a typed push or pull.
Its missed-melee step uses core paths and exempts only that attacker from OAs.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, menus

FOCUS = "resource:core.martial_focus"
SOVEREIGN_COUNTER_USED = "once_per_round:iron_sovereign_counterstrike"


@hook("history_event_metadata")
def gate_history_metadata(event: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Read-only adapter for saved Opening outcomes predating display metadata."""
    source = str(event.get("source_definition_id") or "")
    kind = event.get("event_type")
    if source.endswith(".open_the_gate"):
        mode = {"DAMAGE_COMMITTED": "Centerline Impact", "MOVEMENT_GRANTED": "Hooking Step",
                "CONDITION_APPLIED": "Breath-Checking Strike"}.get(kind)
        return {"display_name": "Open the Gate" + (f": {mode}" if mode else "")}
    rider = str((event.get("payload") or {}).get("rider") or "")
    if kind != "GM_RIDER" or not rider.startswith("Open the Gate:"):
        return None
    for outcome in reversed(events):
        if (outcome.get("source_definition_id") == source + ".open_the_gate"
                and outcome.get("event_type") in {"DAMAGE_COMMITTED", "MOVEMENT_GRANTED", "CONDITION_APPLIED"}
                and outcome.get("actor_id") == event.get("actor_id")
                and outcome.get("trigger_or_intent_id") == event.get("trigger_or_intent_id")
                and outcome.get("sequence", 0) < event.get("sequence", 0)
                and (outcome.get("event_type") == "MOVEMENT_GRANTED" or
                     set(event.get("target_ids") or []).issubset(outcome.get("target_ids") or []))):
            return {"completed_outcome_sequence": outcome["sequence"]}
    return None


@hook("event")
def gate_display_metadata(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Persist Opening presentation on its owned events, without changing mechanics."""
    event = engine.events[-1]
    source = str(event.source_definition_id or "")
    if not (source.endswith(".open_the_gate") or
            (event_type == "GM_RIDER" and str(event.payload.get("rider") or "").startswith("Open the Gate:"))):
        return
    from ..typed_reactions import _rows

    if not _rows(engine, event.actor_id, "opening"):
        return
    prior = [row.model_dump(mode="json") for row in engine.events
             if row.source_definition_id == source + ".open_the_gate"] if event_type == "GM_RIDER" else []
    event.payload.update(gate_history_metadata(event.model_dump(mode="json"), prior) or {})


@hook("after_miss_choice")
def sovereign_counterstrike(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    """An owned active Sovereign independently answers a hostile melee miss."""
    from .needle import ask, checkpoint_id, incapacitated
    from ..typed_reactions import attack_reaches, triggered_context
    from ..typed_executor import run_effects

    if "sovereign_counterstrike" not in config(ctx.engine, target):
        return
    if not target.active or incapacitated(target) or not ctx.actor.active or target.team_id == ctx.actor.team_id:
        return
    # Generic reaction contexts carry their range separately; the resolved
    # effect is authoritative even when spec.range_ft is absent.
    if "ranged" in str((ctx.attack_effect or {}).get("attack_kind") or ""):
        return
    if spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5:
        return
    if not any(c.condition_id == "condition:typed.sovereign_iron_body" and c.source_actor_id == target.entity_id
               for c in target.conditions.values()):
        return
    if target.turn_flags.get(SOVEREIGN_COUNTER_USED) == ctx.engine.state.round_number:
        return
    natural = next((action for action in ctx.engine.action_catalog.values()
                    if action.owner_id == target.entity_id and ".natural." in action.source_definition_id
                    and "#" not in action.source_definition_id and action.parameters.get("typed", {}).get("weapon")), None)
    if natural is None:
        return
    attack = {"type": "attack", "attack_kind": "unarmed", "strike_with": "unarmed", "count": 1,
              "reach_ft": int(natural.range_ft or natural.reach_ft or 5) + 10,
              "on_hit": [{"type": "iron_form_on_hit"}]}
    if not attack_reaches(ctx.engine, target, ctx.actor, attack, None):
        return
    name = "Sovereign Iron-Body Incarnation"
    picked = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, "Sovereign counterstrike", target.entity_id, ctx.actor.entity_id), target,
                 "choice:needle.sovereign_counterstrike", ["strike"], labels={"strike": "Make one Unarmed Strike"},
                 allow_decline=True, target_id=ctx.actor.entity_id,
                 prompt=f"{name} after {ctx.actor.display_name}'s {ctx.action.display_name} misses {target.display_name}: strike {ctx.actor.display_name} or decline")
    if picked != ["strike"]:
        return
    target.turn_flags[SOVEREIGN_COUNTER_USED] = ctx.engine.state.round_number
    inner = triggered_context(ctx.engine, target, ctx.actor,
                              {"feature_id": natural.source_definition_id + ".sovereign_counterstrike",
                               "name": name, "numbers": copy.deepcopy(natural.parameters["typed"]["numbers"]),
                               "effects": [attack]}, ctx.intent)
    run_effects(inner, [attack])


def weakest_physical_saves(target: Any) -> list[str]:
    """Represented base-save minima for Eight-Gate Diagnosis and Sovereign insight.

    These reveals compare STR/DEX/CON save bonuses, including ties, rather than
    situational modifiers for a particular saving-throw roll.
    """
    saves = {ability: int(target.saving_throws.get(ability, 0)) for ability in ("STR", "DEX", "CON")}
    return [ability for ability, bonus in saves.items() if bonus == min(saves.values())]


@hook("mark_applied")
def sovereign_insight(ctx: Any, name: str, target: Any) -> None:
    """Active, source-bound Sovereign learns physical-save minima on each Opening."""
    if name.lower() != "opened" or "sovereign_insight" not in config(ctx.engine, ctx.actor):
        return
    if not any(c.condition_id == "condition:typed.sovereign_iron_body"
               and c.source_actor_id == ctx.actor.entity_id for c in ctx.actor.conditions.values()):
        return
    from .placed import note

    labels = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution"}
    weakest = weakest_physical_saves(target)
    note(ctx.engine, ctx.source, ctx.actor,
         f"Sovereign Iron-Body Incarnation after {ctx.action.display_name} Opens {target.display_name}: "
         f"weakest physical saving throw: {', '.join(labels[ability] for ability in weakest)}"
         + (" (tied)." if len(weakest) > 1 else "."), targets=(target,))


@hook("damage_source_alias")
def gate_damage_alias(engine: Any, source: str | None) -> str | None:
    """Centerline and Sovereign's independent strike retain their owner's strike typing."""
    if source and source.endswith(".sovereign_counterstrike"):
        parent = source[:-len(".sovereign_counterstrike")]
        action = engine.action_catalog.get(parent)
        actor = engine.state.actors.get(action.owner_id) if action is not None else None
        if actor is not None and "sovereign_counterstrike" in config(engine, actor):
            return parent
        return None
    if not source or not source.endswith(".open_the_gate"):
        return None
    parent = source[:-len(".open_the_gate")]
    if parent.endswith(".sovereign_counterstrike"):
        parent = gate_damage_alias(engine, parent) or parent
    action = engine.action_catalog.get(parent)
    if action is None:
        return None
    from ..typed_reactions import _rows

    if not _rows(engine, action.owner_id, "opening"):
        return None
    return parent


def config(engine: Any, actor: Any) -> dict[str, Any]:
    for aid in actor.action_ids:
        action = engine.action_catalog.get(aid)
        rows = (getattr(action, "parameters", None) or {}).get("iron_riders")
        if rows:
            return rows
    return {}


@effect("iron_fist_rider")
def marker(ctx: Any, row: dict[str, Any]) -> None:
    pass  # ownership is captured at compilation, not guessed from live sheets


@hook("compile_actions")
def compile_actions(info: dict[str, Any]) -> list[Any]:
    rows = {row["kind"]: copy.deepcopy(row)
            for key in info["owned_ids"] for row in (info["mechanics"].get(key) or {}).get("effects") or []
            if row.get("type") == "iron_fist_rider"}
    if not rows:
        return []
    out = []
    for row in rows.values():
        if row.get("menu"):
            out.extend(menus.toggle_actions(info, row["menu"], carry=True))
    for action in [*info["actions"], *out]:
        action.parameters["iron_riders"] = rows
    return out


@hook("maneuvers")
def clinch_sizes(info: dict[str, Any]) -> dict[str, Any] | None:
    # Unarmed options are constructed after compile_actions. Upgrade their actual
    # saves here, after those actions and modifier variants exist.
    kit = next((a.parameters.get("iron_riders") for a in info["actions"] if a.parameters.get("iron_riders")), {})
    if "heaven_clinch" not in kit:
        return None
    for action in info["actions"]:
        typed = action.parameters.get("typed") or {}
        if typed.get("unarmed_option") == "grapple":
            for index, eff in enumerate(typed.get("effects") or []):
                if eff.get("type") == "save":
                    typed["effects"][index] = {"type": "heaven_clinch_save", "save": copy.deepcopy(eff)}
    return None


@effect("heaven_clinch_save")
def heaven_clinch_save(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import block_save
    from .body_iron_fist import CLINCH_SELF_CONDITION

    save = copy.deepcopy(row["save"])
    if any(c.condition_id == CLINCH_SELF_CONDITION for c in ctx.actor.conditions.values()):
        save["max_size_larger"] = 2
    block_save(ctx, save)


def choose(ctx: Any, name: str, options: list[str], *, count: int = 1, chooser: Any = None,
           labels: dict[str, str] | None = None, feature_id: str = "", meaning: str = "") -> list[str]:
    from .needle import ask, checkpoint_id

    return ask(ctx.engine, ctx.intent or getattr(ctx.engine, "_active_intent", None),
               checkpoint_id(ctx.engine, name, ctx.target.entity_id if ctx.target else ""), chooser or ctx.actor,
               "choice:needle.iron_fist." + name, options, minimum=min(count, len(options)), maximum=count,
               target_id=ctx.target.entity_id if ctx.target else None,
               labels={**{a.entity_id: a.display_name for a in ctx.engine.state.actors.values()}, **(labels or {})},
               name=name, feature_id=feature_id, prompt=f"{name} after {ctx.action.display_name}"
               + (f" affects {ctx.target.display_name}" if ctx.target else "") + (f": {meaning}" if meaning else ""))


def sweep(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    was = te.opened_before(engine, actor.entity_id, target.entity_id)
    count = 2 if (was if was is not None else te.bears_mark(target, actor.entity_id, "Opened")) else 1
    candidates = sorted((a for a in engine.state.actors.values() if a.active and a.entity_id != target.entity_id
                         and engine.grid.distance_ft(a.position, target.position) <= 5),
                        key=lambda a: (a.team_id == actor.team_id, engine.grid.distance_ft(a.position, target.position), a.entity_id))
    policy = config(engine, actor).get("falling_leaf", {}).get("recipient_policy")
    if policy == "perceived_enemy_auto":
        from ..target_knowledge import can_see
        from ..targeting import line_of_effect
        from ..zones import uses_default_shape

        candidates = [a for a in candidates if can_see(engine, actor, a)
                      and line_of_effect(engine, target, target=a)]
        if uses_default_shape(engine, actor):
            candidates = [a for a in candidates if a.team_id != actor.team_id]
    chosen = choose(ctx, "Falling Leaf Sweep targets", [a.entity_id for a in candidates], count=count,
                    feature_id="TAL_IRON_FIST_FALLING_LEAF_SWEEP")
    targets = [a for a in candidates if a.entity_id in chosen]
    # The secondary Dexterity save is not another Unarmed Shove. Keeping the
    # option tag here would recursively trigger Sweep and Open each extra target.
    typed = {**ctx.typed, "unarmed_option": None}
    sub = te.Context(engine, actor, ctx.action, ctx.intent, typed, targets, None, ctx.damage_cache,
                     save_geometry={"origin_ids": [target.entity_id], "range_ft": 5} if policy else None)
    te.run_effects(sub, [{"type": "save", "ability": "dex", "on_fail": [{"type": "condition", "condition": "prone"}],
                          "on_success": [{"type": "speed", "amount": -10, "duration": "until_start_of_your_next_turn"}]}])


@effect("iron_seals")
def seals(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    kit = config(ctx.engine, ctx.actor)
    lock = kit.get("meridian_lock")
    body = False
    count = 1
    if lock:
        mode = menus.picks(ctx.engine, ctx.actor, lock["menu"]["id"])
        was = te.opened_before(ctx.engine, ctx.actor.entity_id, ctx.target.entity_id)
        body = "Body-Locked" in mode and (was if was is not None else te.bears_mark(ctx.target, ctx.actor.entity_id, "Opened"))
        count = 1 if body else 2
    choices = choose(ctx, "Meridian-Sealing Palm seals", ["Leg Seal", "Breath Seal", "Voice Seal", "Arm Seal"], count=count,
                     feature_id="TAL_IRON_FIST_MERIDIAN_SEALING_PALM")
    for label in choices:
        if label == "Leg Seal":
            te.run_effects(ctx, [{"type": "speed", "amount": -15, "duration": "until_end_of_next_turn"}])
        elif label == "Breath Seal":
            te.run_effects(ctx, [{"type": "reaction_denied", "duration": "until_end_of_next_turn"},
                                 {"type": "disadvantage", "on": "next Concentration saving throw", "duration": "until_end_of_next_turn"}])
        elif label == "Voice Seal":
            te.run_effects(ctx, [{"type": "condition", "condition": "silenced", "duration": "until_end_of_next_turn"}])
        else:
            ctx.rider("Arm Seal: Disadvantage on the next attack using the chosen arm or comparable limb; limb identity is not tracked.")
    if body:
        te.run_effects(ctx, [{"type": "speed", "becomes": 0, "duration": "until_start_of_next_turn"},
                             {"type": "disadvantage", "on": "Dexterity saving throws", "duration": "until_start_of_next_turn"}])


@hook("after_hit")
def observed_rhythm(ctx: Any, target: Any, kind: str) -> None:
    from .iron_forms import court_active

    if not court_active(ctx.actor):
        rhythm(ctx, target, kind)


@hook("after_hit_choice")
def court_rhythm(ctx: Any, target: Any, kind: str) -> None:
    from .iron_forms import court_active

    if court_active(ctx.actor):
        rhythm(ctx, target, kind)


def rhythm(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te

    kit = config(ctx.engine, ctx.actor)
    if kind != "unarmed" or "rhythm" not in kit or ctx.engine.state.current_actor_id != ctx.actor.entity_id:
        return
    actor = ctx.actor
    key = "riders_hammer_hits:" + target.entity_id
    actor.turn_flags[key] = int(actor.turn_flags.get(key) or 0) + 1
    if actor.turn_flags[key] < 2 or actor.turn_flags.get("riders_hammer_used"):
        return
    row = kit["rhythm"]["menu"]
    option = menus.picks(ctx.engine, actor, row["id"])[0]
    actor.turn_flags["riders_hammer_used"] = True
    ctx.rider(f"Hammer-and-Anvil Rhythm: {option} (two hits on the same creature this turn).")
    if option == "Regain Martial Focus":
        if actor.resources.get(FOCUS, 0) <= 0:
            ctx.engine._gain_resource(actor, FOCUS, 1, "TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM")
    elif option == "Extend Opening":
        te.block_mark(te.Context(ctx.engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target),
                      {"mark": "Opened", "duration": {"kind": "until_end_of_your_next_turn"}})
    else:
        used = actor.turn_flags.pop("open_the_gate", None)
        before = getattr(ctx.engine, "_typed_opened_before", None)
        te.open_guard(ctx, target, damaged=True)
        ctx.engine._typed_opened_before = before
        if used is not None:
            actor.turn_flags["open_the_gate"] = used


@hook("after_hit")
def observed_flowing(ctx: Any, target: Any, kind: str) -> None:
    from .iron_forms import court_active

    if not court_active(ctx.actor):
        flowing(ctx, target, kind)


@hook("after_hit_choice")
def court_flowing(ctx: Any, target: Any, kind: str) -> None:
    from .iron_forms import court_active

    if court_active(ctx.actor):
        flowing(ctx, target, kind)


def flowing(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id, say

    row = config(ctx.engine, ctx.actor).get("flowing")
    current = ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    stamp = f"{ctx.engine.state.round_number}:{current.entity_id}:{current.turns_started}"
    if not row or kind != "unarmed" or ctx.actor.turn_flags.get("riders_flowing_used") == stamp or not target.active:
        return
    actions = {a.display_name: a for aid in ctx.actor.action_ids for a in [ctx.engine.action_catalog.get(aid)]
               if a and a.display_name in ("Grapple", "Shove: Push 5 ft", "Shove: Prone")
               and ctx.engine._target_in_range(ctx.actor, target, a)}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "Flowing Combination", target.entity_id), ctx.actor,
                 "choice:needle.flowing_combination", list(actions), allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Flowing Combination",
                 prompt=f"Flowing Combination after {ctx.actor.display_name}'s {ctx.action.display_name} hits {target.display_name}: "
                        "Grapple (Speed becomes 0 until the grapple ends), push 5 feet away, "
                        "or knock Prone (until standing up), or decline. "
                        "Once per turn; no additional attack, action, Reaction or resource cost.")
    if not chosen:
        return
    ctx.actor.turn_flags["riders_flowing_used"] = stamp
    action = actions[chosen[0]]
    typed = copy.deepcopy(action.parameters.get("typed") or {})
    # Grapple/Shove replace one attack of an ordinary Attack action. This free
    # follow-up grants just that option, never that action's remaining attacks.
    typed["effects"] = [eff for eff in typed.get("effects") or [] if eff.get("type") != "attack"]
    adept = "flowing_adept" in config(ctx.engine, ctx.actor)
    if adept:
        typed["numbers"] = {**typed["numbers"], "save_dc": int(typed["numbers"]["save_dc"]) + 1}
    was = te.opened_before(ctx.engine, ctx.actor.entity_id, target.entity_id)
    opened = was if was is not None else te.bears_mark(target, ctx.actor.entity_id, "Opened")
    for eff in typed.get("effects") or []:
        while eff.get("type") in ("iron_tiger_save", "heaven_clinch_save"):
            eff = eff["save"]
        if eff.get("type") == "save":
            eff["disadvantage_if_marked"] = "Opened"
            if adept:
                eff.setdefault("on_fail", []).append({"type": "iron_flowing_adept_outcome"})
    sub = te.Context(ctx.engine, ctx.actor, action, ctx.intent, typed, [target], target, ctx.damage_cache)
    sub = sub.with_source("passive:TAL_IRON_FIST_FLOWING_COMBINATION")
    say(ctx.engine, sub.source, ctx.actor,
        f"{ctx.actor.display_name} uses Flowing Combination after {ctx.action.display_name} hits {target.display_name}: "
        f"{action.display_name}, without spending another attack.", (target.entity_id,))
    te.run_effects(sub, typed.get("effects") or [])
    # The printed Opening prerequisite applies independently of the save.
    # Only movement belongs to the failed-save branch. The parent's consumed
    # once-turn token also bounds this recovery, including off-turn attempts.
    if adept and opened:
        from .needle import regain_focus

        regain_focus(ctx.engine, ctx.actor, "insight.flowing-combination-adept", "Flowing Combination Adept")


@effect("iron_flowing_adept_outcome")
def flowing_adept_outcome(ctx: Any, row: dict[str, Any]) -> None:
    # Only the failed save permits movement; Focus recovery is independent
    # and belongs to the parent free attempt after either save outcome.
    step(ctx, ctx.actor, ctx.target, 5, name="Flowing Combination Adept")


@effect("iron_sweeping_kick")
def sweeping_kick(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if ctx.target is None or ctx.typed.get("unarmed_option") != "shove_prone":
        return
    natural = next((a for a in ctx.engine.action_catalog.values()
                    if a.owner_id == ctx.actor.entity_id and ".natural." in a.source_definition_id
                    and "#" not in a.source_definition_id and (a.parameters.get("typed") or {}).get("source")
                    in {"tianxia.sphere.iron_fist", "tianxia.path.body_refining.feature.iron_fist"}), None)
    # Shove may carry a held weapon's delivery numbers. The printed bonus uses
    # the owner's sealed Iron Fist ability, not a different Cultivation key.
    modifier = ((natural.parameters["typed"].get("weapon") or {}).get("damage") or {}).get("modifier") \
        if natural is not None else ctx.numbers.get("key_mod")
    te.run_effects(ctx, [{"type": "damage", "flat": max(1, int(modifier or 0)),
                         "damage_types": ["bludgeoning"], "applies_to": "target"},
                        {"type": "if_marked", "mark": "Opened", "effects": [
                            {"type": "standing_burden", "extra_ft": 10,
                             "duration": "until_end_of_next_turn"}]}])


@effect("iron_rooting")
def root(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    ctx.engine._remove_condition(ctx.actor, te.CONDITION_PREFIX + "iron_rooting", ctx.source)
    ctx.engine._apply_condition(ctx.actor, te.CONDITION_PREFIX + "iron_rooting", ctx.source, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"reduction": int(row.get("reduction") or 5)})


@hook("forced_movement_reduction")
def root_reduction(ctx: Any, target: Any) -> int:
    root = max((int((c.data or {}).get("reduction") or 0) for c in target.conditions.values()
                if c.condition_id == "condition:typed.iron_rooting"), default=0)
    world = 15 if "world_body" in config(ctx.engine, target) and target.resources.get(FOCUS, 0) > 0 else 0
    return root + world


def step(ctx: Any, mover: Any, exempt: Any, feet: int, *, name: str = "Iron Fist step") -> None:
    """Resolve the actual legal path; only the printed creature's OA is exempt.

    Use core movement to preserve other creatures' reactions, zones and dragging.
    Unused immediate movement is removed rather than stored for a later action.
    """
    from .needle import ask, checkpoint_id

    engine = ctx.engine
    before = mover.movement_remaining_ft
    mover.movement_remaining_ft += feet
    engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=mover.entity_id, payload={"distance_ft": feet})
    candidates = {f"cell:{c.destination.x},{c.destination.y}": c for c in engine._movement_candidates(mover)
                  if c.destination and c.movement_cost_ft <= feet}
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "Iron Fist step", mover.entity_id), mover,
                 "choice:needle.iron_fist_step", list(candidates), allow_decline=True, default="decline",
                 target_id=mover.entity_id, name=name,
                 labels={key: f"Space ({c.destination.x}, {c.destination.y})" for key, c in candidates.items()},
                 prompt=f"{name} after {ctx.action.display_name} involving {exempt.display_name}: {mover.display_name} may move up to {feet} feet")
    if chosen:
        candidate = candidates[chosen[0]]
        prior_exempt = mover.turn_flags.get("iron_step_from")
        mover.turn_flags["iron_step_from"] = exempt.entity_id
        try:
            path = candidate.canonical_path
            # A missed OA can itself grant another Rooting step. Resolve OAs
            # first, then recheck the origin instead of committing a stale path
            # after nested movement has already moved this actor elsewhere.
            if len(path) == 2:
                engine._resolve_leave_reach(mover, path[0], path[1], ctx.intent)
                if mover.active and mover.position == path[0]:
                    credit = mover.turn_flags.get("oa_free_ft")
                    mover.turn_flags["oa_free_ft"] = int(credit or 0) + feet
                    try:
                        engine._resolve_movement(mover, candidate, ctx.intent)
                    finally:
                        if credit is None:
                            mover.turn_flags.pop("oa_free_ft", None)
                        else:
                            mover.turn_flags["oa_free_ft"] = credit
            else:
                engine._resolve_movement(mover, candidate, ctx.intent)
        finally:
            if prior_exempt is None:
                mover.turn_flags.pop("iron_step_from", None)
            else:
                mover.turn_flags["iron_step_from"] = prior_exempt
    unused = max(0, mover.movement_remaining_ft - before)
    mover.movement_remaining_ft -= unused
    engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=mover.entity_id, payload={"distance_ft": -unused})


@hook("opportunity_allowed")
def step_exemption(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if mover.turn_flags.get("iron_step_from") == reactor.entity_id else None


@hook("attack_resolved")
def rooting_miss(ctx: Any, target: Any, hit: bool, attack: dict[str, Any]) -> None:
    from ..typed_executor import ranged_attack_now

    if hit or ranged_attack_now(ctx) or not target.active:
        return
    if any(c.condition_id == "condition:typed.iron_rooting" for c in target.conditions.values()):
        step(ctx, target, ctx.actor, 5, name="Rooting Stance")


def held_weapons(engine: Any, actor: Any) -> dict[str, Any]:
    """Compiled weapons still in hand; other held objects lack runtime identities."""
    dropped = {c.data.get("disables_action") for c in actor.conditions.values()}
    return {aid: engine.action_catalog[aid] for aid in actor.action_ids if aid in engine.action_catalog and ".weapon." in aid
            and "#" not in aid and not aid.endswith((".pickup", ".drop")) and aid not in dropped
            and not engine.action_catalog[aid].parameters.get("requires_held_weapon")
            and not engine.action_catalog[aid].parameters.get("typed", {}).get("variant_of")
            and engine.action_catalog[aid].parameters.get("typed", {}).get("weapon")}


@effect("iron_wrist")
def wrist(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if ctx.typed.get("unarmed_option") != "grapple" or ctx.target is None:
        return
    weapons = held_weapons(ctx.engine, ctx.target)
    selected = choose(ctx, "Wrist-Trapping Hand held weapon", list(weapons),
                      feature_id="TAL_IRON_FIST_WRIST_TRAPPING_HAND",
                      meaning="Choose a held weapon. Attacks with it against anyone other than you have Disadvantage "
                              "until the start of your next turn. If the creature already had your Opened mark, it also "
                              "cannot make Opportunity Attacks with that weapon for that duration. No additional cost.",
                      labels={aid: f"{action.display_name}: Disadvantage against other creatures until the start of your next turn"
                              for aid, action in weapons.items()})
    if not selected:
        return
    weapon = weapons[selected[0]]
    was = te.opened_before(ctx.engine, ctx.actor.entity_id, ctx.target.entity_id)
    opened = was if was is not None else te.bears_mark(ctx.target, ctx.actor.entity_id, "Opened")
    ctx.engine._apply_condition(ctx.target, te.CONDITION_PREFIX + "iron_wrist", ctx.source, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"weapon_action": selected[0],
                                "weapon_source": weapon.parameters.get("typed", {}).get("source"), "no_oa": opened})


@hook("decision_text")
def wrist_choice_reading(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Explain only the held-object choice emitted by the owning Wrist effect."""
    if context.get("reaction_source_id") != "choice:needle.iron_fist.Wrist-Trapping Hand held weapon":
        return None
    trigger = context.get("choice_trigger") or {}
    if trigger.get("feature_id") != "TAL_IRON_FIST_WRIST_TRAPPING_HAND":
        return None
    labels = trigger.get("labels") or {}
    return {"option_descriptions": {
        option: f"{labels.get(option, 'This held weapon')}. Attacks with this object against anyone other than you "
                "have Disadvantage until the start of your next turn. If the creature was already Opened by you, "
                "it also cannot make Opportunity Attacks with this object for that duration. No additional cost."
        for option in trigger.get("needle_options") or []}}


def _wrist_matches(held: Any, source: str, typed: dict[str, Any]) -> bool:
    return source == held.data.get("weapon_action") or typed.get("variant_of") == held.data.get("weapon_action") \
        or (bool(held.data.get("weapon_source")) and typed.get("source") == held.data["weapon_source"])


@hook("attack_mode")
def wrist_attack(ctx: Any, target: Any) -> str | None:
    for held in ctx.actor.conditions.values():
        if held.condition_id == "condition:typed.iron_wrist" and target.entity_id != held.source_actor_id \
                and _wrist_matches(held, ctx.source, ctx.typed):
            return "DISADVANTAGE"
    return None


@hook("opportunity_allowed")
def wrist_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    from ..typed_reactions import _opportunity_row

    row = _opportunity_row(engine, reactor)
    action = engine.action_catalog.get((row or {}).get("action_id"))
    typed = (action.parameters or {}).get("typed") if action else {}
    if any(c.condition_id == "condition:typed.iron_wrist" and c.data.get("no_oa")
           and _wrist_matches(c, action.source_definition_id if action else "", typed or {}) for c in reactor.conditions.values()):
        return False
    return None
