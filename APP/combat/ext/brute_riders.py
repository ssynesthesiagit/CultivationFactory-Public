"""Brute sphere riders (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Brutal Shove is the Athletics contest of combat/ext/brute_shove.py (rider lane C16; a success fires its
shove_succeeded hook, read below); combat/ext/gu_brute.py owns Hammer's Impact Collision (the ``collision`` hook) and combat/ext/lane4_brute.py Takedown and
Follow-Through. This adds the lines that were still read to the GM. Ownership comes from each talent's compiled feature row
(combat/rules/feature_blocks.d/riders_c4.json) or its own ``state`` (combat/ext/states.py), so other creatures are untouched.

- Crushing Collision ("When Hammer creates an Impact Collision, choose one: the shoved creature makes a Constitution save or becomes
  Dazed until the start of its next turn; the secondary creature makes a Strength save or falls Prone; increase collision damage by
  your Proficiency Bonus; break one ordinary unsecured object ...". "Dazed ... cannot take Reactions and has Disadvantage on its next
  attack roll before the state ends."): asked on the same collision Hammer answers (holding Martial Focus); the object choice is the GM's.
- Dominoes ("When a shove pushes a creature into another creature, immediately attempt one free shove against the second creature to
  knock it Prone. The second creature need not be within your reach. You cannot apply a Manhandle talent to the free shove.") and
  Battlefield Bowling ("attempt the free shove against each creature in a contiguous line until one shove fails ... knocks Prone
  only"): the free shove is the same Athletics contest, Prone only, no damage, no Manhandle, reach not needed.
- Court of the Moving Mountain (state ``court_of_the_moving_mountain``, ending if Incapacitated): "reduce forced movement affecting
  you by 10 feet"; "when Brutal Shove succeeds, move the target 5 additional feet"; "once per turn when a creature collides with
  terrain or another creature, regain Martial Focus".
- Sovereign Weight Incarnation (state ``sovereign_weight_incarnation``): "ignore ordinary forced movement unless you choose to move";
  "Brutal Shove damage becomes 2d8 + Strength modifier"; "once per turn when you successfully shove, move the target 10 additional
  feet"; "Hammer collision damage gains +2d8".
- Rooted Stance: "While holding Martial Focus: ... reduce forced movement affecting you by 5 feet".
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .ability_source import attack_target_key, has_row

BRUTAL_SHOVE, FOCUS = "BRUTE_BASE_BRUTAL_SHOVE", "resource:core.martial_focus"
DAZED = "condition:typed.brute_dazed"


def _state(engine: Any, actor: Any, name: str) -> Any:
    from . import states

    return states.active(engine, actor, name)


def _shove(ctx: Any) -> bool:
    return str((ctx.typed or {}).get("source") or "") == BRUTAL_SHOVE


def _legacy(ctx: Any) -> bool:
    """A Brutal Shove compiled before rider lane C16: an attack roll (a saved fight's sealed bundle). Its riders keep the attack-roll
    path (after_hit, attack_damage, the attack-roll free shove) so a saved fight replays exactly; new bundles use the contest."""
    return any(isinstance(e, dict) and e.get("type") == "attack" for e in (ctx.typed or {}).get("effects") or [])


def _push(ctx: Any, target: Any, feet: int, why: str, direction: str = "away") -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    if target.active and feet > 0:
        run_effects(replace(ctx, target=target, targets=[target]),
                    [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": direction, "evidence": why}])


def _damage(ctx: Any, targets: list[Any], dice: int, sides: int, why: str) -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    for target in targets:
        if target is not None and target.active:
            run_effects(replace(ctx, target=target, targets=[target]),
                        [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": sides}, "damage_types": ["bludgeoning"],
                          "evidence": why}])


# ------------------------------------------------------------------------------------------------ being shoved: reductions
@hook("forced_movement_reduction")
def resist_shoves(ctx: Any, subject: Any) -> int | None:
    total = 0
    if _state(ctx.engine, subject, "sovereign_weight_incarnation") is not None:
        from .needle import CHOICE, ask, checkpoint_id
        from .choice_prompt import action_context

        # The base shove has two push rows. Consent belongs to this action,
        # rather than asking again for each row of the same shove.
        key = f"brute_sovereign_consent:{attack_target_key(ctx, subject)}"
        if key not in ctx.damage_cache:
            chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sovereign_move", subject.entity_id),
                         subject, CHOICE + "sovereign_move", ["stay", "move"],
                         labels={"stay": "Ignore this forced movement", "move": "Allow this forced movement"},
                         preferred=["stay"], name="Sovereign Weight Incarnation",
                         prompt=f"Sovereign Weight Incarnation: {ctx.actor.display_name}'s {ctx.action.display_name} would move "
                                f"{subject.display_name}. Ignore it or allow it? No action or resource cost.",
                         prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, subject))
            ctx.damage_cache[key] = "move" if chosen == ["move"] else "stay"
        if ctx.damage_cache[key] != "move":
            return 10000
    if _state(ctx.engine, subject, "court_of_the_moving_mountain") is not None:
        total += 10
    if has_row(ctx.engine, subject.entity_id, "brute_rooted") and subject.resources.get(FOCUS, 0) >= 1:
        total += 5
    return total or None


# ------------------------------------------------------------------------------------------------ a successful Brutal Shove
@hook("attack_damage")
def sovereign_shove_damage_legacy(ctx: Any, dice: Any) -> Any:
    """A saved fight's attack-roll Brutal Shove (see _legacy)."""
    return sovereign_shove_damage(ctx, None) if _shove(ctx) and _legacy(ctx) else None


@hook("shove_damage")
def sovereign_shove_damage(ctx: Any, target: Any) -> Any:
    """One state-gated replacement: 2d8 + Strength, not extra paid shove variants (combat/ext/brute_shove.py's shove_damage hook)."""
    if _state(ctx.engine, ctx.actor, "sovereign_weight_incarnation") is None:
        return None
    from . import brute_shove
    from ..gate2_runtime_models import DiceSpec

    return DiceSpec(count=2, sides=8,
                    modifier=brute_shove.strength_modifier(ctx.engine, ctx.actor, ctx.numbers,
                                                            marker=brute_shove.DAMAGE_SCORE))


@hook("after_hit")
def shove_extras_legacy(ctx: Any, target: Any, kind: str) -> None:
    """A saved fight's attack-roll Brutal Shove (see _legacy): a hit stood for the success."""
    if _shove(ctx) and _legacy(ctx):
        shove_extras(ctx, target, None)


@hook("shove_succeeded")
def shove_extras(ctx: Any, target: Any, result: Any) -> None:
    """A successful Brutal Shove contest (combat/ext/brute_shove.py's shove_succeeded hook; rider lane C16). The extra
    movement moves the creature the same way the shove did (``result["direction"]``), so a Get Over Here pull is not
    immediately undone by these pushes."""
    if not _shove(ctx) or not target.active:
        return
    actor = ctx.actor
    direction = str((result or {}).get("direction") or "away")
    if _state(ctx.engine, actor, "court_of_the_moving_mountain") is not None:
        _push(ctx, target, 5, "Court of the Moving Mountain: when Brutal Shove succeeds, move the target 5 additional feet", direction)
    if _state(ctx.engine, actor, "sovereign_weight_incarnation") is not None:
        flag = f"brute_sovereign_push_{ctx.engine.state.round_number}_{ctx.engine.state.current_slot_index}"
        if not actor.turn_flags.get(flag):
            actor.turn_flags[flag] = True
            _push(ctx, target, 10, "Sovereign Weight Incarnation: once per turn when you successfully shove, move the target 10 additional feet",
                  direction)


# ------------------------------------------------------------------------------------------------ collisions
def _hammer_applies(ctx: Any) -> bool:
    return _shove(ctx) and has_row(ctx.engine, ctx.actor.entity_id, "brute_hammer_owned") and ctx.actor.resources.get(FOCUS, 0) >= 1


@hook("collision")
def brute_collisions(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    gate = f"brute_c4_collision:{attack_target_key(ctx, target)}"
    if ctx.damage_cache.get(gate):
        return
    ctx.damage_cache[gate] = True
    blocker = next((other for other in engine.state.actors.values() if other.active and other.entity_id != target.entity_id
                    and engine._footprint_intersects(other, (blocked_at,))), None)
    court = _state(engine, actor, "court_of_the_moving_mountain")
    turn_key = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    if court is not None and actor.turn_flags.get("brute_court_focus_turn") != turn_key and actor.resources.get(FOCUS, 0) < 1:
        actor.turn_flags["brute_court_focus_turn"] = turn_key
        engine._gain_resource(actor, FOCUS, 1, str(court.source_definition_id))  # "once per turn when a creature collides ... regain Martial Focus"
    if _hammer_applies(ctx):
        if _state(engine, actor, "sovereign_weight_incarnation") is not None:
            _damage(ctx, [target, blocker], 2, 8, "Sovereign Weight Incarnation: Hammer collision damage gains +2d8")
        if has_row(engine, actor.entity_id, "brute_crushing"):
            _crushing(ctx, target, blocker)
    if blocker is not None and blocker.team_id != actor.team_id and has_row(engine, actor.entity_id, "brute_dominoes") and _shove(ctx):
        _dominoes(ctx, target, blocker, blocked_at)


def _crushing(ctx: Any, target: Any, blocker: Any) -> None:
    from dataclasses import replace

    from ..typed_executor import block_save, stated_expiry
    from .needle import CHOICE, ask, checkpoint_id

    options = {"dazed": f"{target.display_name} makes a Constitution save or is Dazed until the start of its next turn",
               "extra": "Increase the collision damage by your Proficiency Bonus"}
    if blocker is not None:
        options["prone"] = f"{blocker.display_name} makes a Strength save or falls Prone"
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "brute_crushing", ctx.actor.entity_id), ctx.actor, CHOICE + "brute_crushing",
                 list(options), labels=options, preferred=["dazed"], name="Crushing Collision",
                 prompt=f"Crushing Collision: {target.display_name} was driven into an obstacle; choose one (breaking an object is the GM's).")
    pick = chosen[0] if chosen else "dazed"
    if pick == "dazed":
        one = replace(ctx, target=target, targets=[target])
        block_save(one, {"type": "save", "ability": "con", "on_fail": [{"type": "brute_daze", "applies_to": "target"}], "on_success": []})
    elif pick == "prone" and blocker is not None:
        one = replace(ctx, target=blocker, targets=[blocker])
        block_save(one, {"type": "save", "ability": "str", "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}], "on_success": []})
    else:
        from ..typed_executor import run_effects

        for who in (target, blocker):
            if who is not None and who.active:
                run_effects(replace(ctx, target=who, targets=[who]), [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["bludgeoning"],
                                                                      "evidence": "Crushing Collision: collision damage increased by your Proficiency Bonus"}])


@effect("brute_daze")
def daze(ctx: Any, row: dict[str, Any]) -> None:
    """Dazed until the start of its next turn: no Reactions (the condition's rule) and Disadvantage on its next attack roll."""
    from ..typed_executor import stated_expiry

    target = ctx.target
    if target is None or not target.active:
        return
    until = stated_expiry(ctx, {"expires_on": "START_OF_TARGET_NEXT_TURN"}, target, condition=True)
    ctx.engine._apply_condition(target, DAZED, ctx.source, ctx.actor.entity_id, expires_on=until,
                                data={"label": "Dazed: no Reactions, Disadvantage on its next attack roll, until its next turn starts"})
    target.reaction_available = False
    ctx.engine._add_modifier(target, "TAL_BRUTE_CRUSHING_COLLISION", "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on=until)


def _dominoes(ctx: Any, first: Any, second: Any, blocked_at: Any = None) -> None:
    """The free shove(s): the Brutal Shove contest (combat/ext/brute_shove.py), Prone only, no damage, no Manhandle, reach not needed."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context
    from .brute_shove import shove

    modern = any(r.get('perceived_chain') for r in (getattr(ctx.engine, 'typed_passive_rows', {}) or {}).get(ctx.actor.entity_id, ())
                 if r.get('block') == 'brute_bowling')
    if modern:
        from ..target_knowledge import located
        from ..targeting import line_of_effect
        if not located(ctx.engine, ctx.actor, second) or not line_of_effect(ctx.engine, ctx.actor, target=second):
            return

    # String keys survive the executor's per-hit cache copy: a Court push
    # in after_hit and the original on-hit push must not offer two free shoves
    # against the same creature from this one successful shove.
    gate = f"brute_dominoes:{attack_target_key(ctx, first)}:{second.entity_id}"
    if ctx.damage_cache.get(gate):
        return
    ctx.damage_cache[gate] = True

    # A separate shove, not another hit of Brutal Shove. Copy only the
    # character's roll numbers: no shove riders, weapon, payment or cache.
    row = {"type": "brutal_shove", "mode": "prone_only", "no_damage": True, "no_manhandle": True, "ignore_size": False,
           "evidence": "Dominoes: a free shove to knock the second creature Prone"}
    typed = {"source": "TAL_BRUTE_DOMINOES", "numbers": dict(ctx.numbers), "effects": [row]}
    action = ActionDefinition(
        source_definition_id=f"action:typed.{ctx.actor.entity_id}.granted.dominoes",
        display_name="Dominoes: free shove to knock Prone (no cost)", owner_id=ctx.actor.entity_id,
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE",
        parameters={"typed": typed})

    line = [second]
    if modern:
        # Follow the actual collision ray through complete occupied volumes.
        # A Large body occupies multiple cells; a creature above the ray is
        # not part of the contiguous line merely because its map square fits.
        contact = blocked_at or second.position
        point = (contact.x, contact.y, contact.z)
        start = first.position
        step = tuple((a > b) - (a < b) for a, b in zip(point, (start.x, start.y, start.z)))
        cursor = second
        while any(step):
            occupied = set(ctx.engine._actor_volume(cursor))
            while point in occupied:
                point = tuple(a + b for a, b in zip(point, step))
            if not ctx.engine.grid.in_bounds(point[:2]):
                break
            nxt = next((other for other in ctx.engine.state.actors.values()
                        if other.active and other.team_id != ctx.actor.team_id
                        and other.entity_id not in {a.entity_id for a in line}
                        and other.entity_id != first.entity_id
                        and point in ctx.engine._actor_volume(other)), None)
            if nxt is None or not located(ctx.engine, ctx.actor, nxt) or not line_of_effect(ctx.engine, ctx.actor, target=nxt):
                break
            line.append(nxt)
            cursor = nxt
    elif has_row(ctx.engine, ctx.actor.entity_id, "brute_bowling"):
        dx, dy = second.position.x - first.position.x, second.position.y - first.position.y
        step = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
        cursor = second
        while True:
            nxt = next((other for other in ctx.engine.state.actors.values() if other.active and other.team_id != ctx.actor.team_id
                        and other.entity_id not in {a.entity_id for a in line} and other.entity_id != first.entity_id
                        and (other.position.x - cursor.position.x, other.position.y - cursor.position.y) == step), None)
            if nxt is None or len(line) > 12:
                break
            line.append(nxt)
            cursor = nxt
    legacy = _legacy(ctx)
    attack = {"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "continues_hit": True,
              "evidence": "Dominoes: a free shove to knock the second creature Prone",
              "on_hit": [{"type": "condition", "condition": "prone", "applies_to": "target"}], "on_miss": []}
    if legacy:  # a saved fight's attack-roll shove keeps its attack-roll free shove (see _legacy)
        typed = {"source": "TAL_BRUTE_DOMINOES", "numbers": dict(ctx.numbers), "effects": [attack]}
        action = action.model_copy(update={"parameters": {"typed": typed}})
    for creature in line:
        intent = ctx.intent.model_copy(update={"target_ids": (creature.entity_id,), "destination": None}) if ctx.intent is not None else None
        sub = Context(ctx.engine, ctx.actor, action, intent, typed, [creature], creature)
        if legacy:
            from ..typed_executor import run_effects

            before = len(ctx.engine.events)
            run_effects(sub, [attack])
            succeeded = any(e.event_type == "ATTACK_ROLLED" and creature.entity_id in (e.target_ids or ()) and (e.payload or {}).get("provisional_hit")
                            for e in ctx.engine.events[before:])
        else:
            result = shove(sub, creature, row)
            succeeded = bool(result and result["success"])
        if not succeeded:
            break  # Battlefield Bowling: "until one shove fails"


@hook("compile_block")
def brute_blocks(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Markers for passive Brute talents read above (combat/rules/feature_blocks.d/riders_c4.json)."""
    if block in ("brute_crushing", "brute_dominoes", "brute_bowling", "brute_rooted", "brute_hammer_owned"):
        return [{**row, "block": block, "keeps_compiling": True,
                 **({'perceived_chain': True} if spec.get('perceived_chain') else {})}]
    return None
