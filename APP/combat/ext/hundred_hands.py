"""Hundred-Hand Battle Mandala (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, "35. Hundred-Hand Battle Mandala" (Battle Hands, Weapon Forms and the five
features, with their Normalized Procedures). Owned rows: ``{"type": "path_passive", "kind": "hundred_hands", "role": ...}``
(roles "four_hand", "weapon_wheel", "eight_limb"); Circle of Uncounted Arms is a compiled Reaction whose one effect is
``circle_hand``; Thousand-Hand Incarnation is the state "thousand_hand_incarnation".

Battle Hands   resource:named.battle_hand, maximum Proficiency Bonus (2 x PB while Thousand-Hand Incarnation lasts; the pool
               is compiled at that highest maximum for its owner, factory_compiler ``max_if_owned``): at the start of each of
               the owner's turns the unused Hands are gone and the pool is full again. Spending one takes no action.
Weapon Forms   every attack has one Form: Unarmed (unarmed strikes, natural weapons), Thrown (a weapon thrown), or its item's
               Form by the printed construction rules (integrated_weapons.FORMS: Blade, Hafted, Polearm, Flexible). A weapon the table has no
               Form for (improvised, bows, treasures) has none and never counts as a different Form.
Four-Hand Sequence  once per turn during the owner's Attack action, 1 Hand (asked): after a hit, + Proficiency Bonus damage of
               the attack's type, or move 5 feet without provoking, or +1 AC until the start of its next turn; after a miss, add
               Proficiency Bonus to the roll (a d20 rewrite rule, combat/ext/d20_rewrite.py: the natural result is raised by PB,
               to no more than 19, and is offered only when that makes the attack hit).
Weapon-Wheel Body  one-handed melee weapons it is proficient with get a "(Constitution)" variant (integrated_weapons.py group
               "one_handed_melee"; an unarmed strike is always the second Form); once per turn, after an attack with one Form,
               its next attack this turn with a different Form has Advantage.
Eight-Limb Battle Pattern  once per turn, when its Attack action has resolved, 2 Hands (1 during Thousand-Hand) for one more
               attack (asked: which attack with a Form different from the last one, against which creature); after hits with
               three different Forms in one turn, one Completion Effect (asked, once per turn).
Circle of Uncounted Arms  its Reaction's ``circle_hand`` asks for the Hand: Intercepting (a melee strike; a hit takes PB off
               the triggering attack roll), Seizing (a Grapple), Deflecting (+3 AC against the triggering attack; only when it is
               the one attacked), Silencing (an unarmed strike; a hit denies the creature's Reactions until its next turn).
Thousand-Hand Incarnation  Hands 2 x PB now and at each turn start; Eight-Limb costs 1; melee reach +5 feet (reach_bonus row);
               once per turn after its third hit on one creature this turn, + 5d8 Force; Mandala Completion once per turn after
               4 Hands were spent this turn (asked: move up to Speed without provoking, +3 AC, an unarmed strike, or two
               different Completion Effects). When it ends, Hands above Proficiency Bonus are gone.
Every hook returns early for a creature without these rows or that state.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.hundred_hand_battle_mandala.feature."
HANDS = "resource:named.battle_hand"
STATE = "thousand_hand_incarnation"
from .integrated_weapons import FORMS  # the catalog's Weapon Forms (shared with Kensei's Blade group)
COMPLETIONS = ("push", "prone", "no_reactions", "temp_hp", "move")


# --------------------------------------------------------------------------------------------------------- records
def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "hundred_hands"}


def _thousand(engine: Any, actor: Any) -> bool:
    from .states import active

    return bool(active(engine, actor, STATE))


def _pb(actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 2)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _turn(actor: Any, engine: Any, key: str) -> dict[str, Any]:
    """This turn's record under ``key`` (a fresh one once the turn has changed)."""
    held = actor.turn_flags.get(key)
    if not isinstance(held, dict) or held.get("stamp") != _stamp(engine):
        held = {"stamp": _stamp(engine)}
        actor.turn_flags[key] = held
    return held


def maximum(engine: Any, actor: Any) -> int:
    return min(int(actor.resource_maximums.get(HANDS, 0) or 0), 2 * _pb(actor) if _thousand(engine, actor) else _pb(actor))


def _set_hands(engine: Any, actor: Any, amount: int, source: str) -> None:
    held = int(actor.resources.get(HANDS, 0) or 0)
    if amount > held:
        engine._gain_resource(actor, HANDS, amount - held, source)
    elif amount < held:
        engine._spend_resource(actor, HANDS, held - amount, source)


def _hands(actor: Any) -> int:
    return int(actor.resources.get(HANDS, 0) or 0)


def _spend(engine: Any, actor: Any, amount: int, source: str) -> None:
    engine._spend_resource(actor, HANDS, amount, source)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def attack_action(action: Any) -> bool:
    """One attack of the Attack action (a weapon, natural or improvised attack), not a technique, reaction or granted strike."""
    typed = (action.parameters or {}).get("typed") or {}
    if str(getattr(action.economy, "value", action.economy)) != "ACTION" or typed.get("reaction_attack") or typed.get("opportunity_of") \
            or typed.get("granted_attack"):
        return False
    return bool(typed.get("attack_action")) or bool(re.search(r"\.(?:weapon|improvised)\.", action.source_definition_id))


def form_of(action: Any) -> str | None:
    typed = (action.parameters or {}).get("typed") or {}
    recorded = (typed.get("weapon") or {}).get("form")
    if recorded in {"Unarmed", "Blade", "Hafted", "Polearm", "Flexible", "Thrown", "Shield"}:
        return recorded
    attacks = [e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"]
    if ".natural." in action.source_definition_id or any(e.get("attack_kind") == "unarmed" for e in attacks):
        return "Unarmed"
    if not typed.get("weapon"):
        return None
    if "#thrown" in action.source_definition_id:
        return "Thrown"
    if "shield" in action.source_definition_id.lower():
        return "Shield"
    return FORMS.get(str(typed.get("source") or "").rsplit(".", 1)[-1])


@hook("turn_start")
def refresh_hands(engine: Any, actor: Any) -> None:
    """"All refresh at the start of your turn and unused Hands disappear": the pool is full again at the owner's turn start."""
    if HANDS in (actor.resources or {}) and actor.active and _roles(engine, actor) | ({"thousand"} if _thousand(engine, actor) else set()):
        actor.resource_maximums[HANDS] = 2 * _pb(actor) if _thousand(engine, actor) else _pb(actor)
        _set_hands(engine, actor, maximum(engine, actor), "system:battle_hands_refresh")


@hook("event")
def count_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Hands spent during the current turn (Mandala Completion's "after spending at least 4")."""
    payload = kwargs.get("payload") or {}
    if event_type != "RESOURCE_SPENT" or payload.get("resource_id") != HANDS or str(engine.events[-1].source_definition_id) == "system:battle_hands_refresh":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is not None:
        record = _turn(actor, engine, "_round_hands_spent")
        record["spent"] = int(record.get("spent") or 0) + int(payload.get("amount") or 0)


# ------------------------------------------------------------------------------------------------ Four-Hand Sequence
def _four_hand_ready(engine: Any, actor: Any, action: Any) -> bool:
    return ("four_hand" in _roles(engine, actor) and engine.state.current_actor_id == actor.entity_id and attack_action(action)
            and not _turn(actor, engine, "_round_four_hand").get("used") and _hands(actor) >= 1)


def _attack_types(ctx: Any) -> list[str]:
    weapon = ctx.typed.get("weapon") or {}
    return [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]


def _sub(ctx: Any, targets: list[Any]) -> Any:
    from .. import typed_executor as te

    return te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, dict(ctx.typed), list(targets), targets[0] if targets else None, {})


@hook("damage_packet_selection")
def _four_hand_hit(ctx: Any, target: Any, packet_kinds: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _four_hand_ready(engine, actor, ctx.action):
        return
    from .needle import ask, checkpoint_id

    labels = {"damage": f"+{_pb(actor)} damage to this hit", "move": "Move 5 feet without provoking", "ac": "+1 AC until your next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "four_hand", target.entity_id), actor, "choice:needle.four_hand_sequence", list(labels),
                 labels=labels, allow_decline=True, target_id=target.entity_id, name="Four-Hand Sequence",
                 prompt=f"Four-Hand Sequence: {ctx.action.display_name} hit {target.display_name}. Spend 1 Battle Hand?")
    if not picked or picked[0] not in labels:
        return
    _turn(actor, engine, "_round_four_hand")["used"] = True
    _spend(engine, actor, 1, PREFIX + "four_hand_sequence")
    from .. import typed_executor as te

    if picked[0] == "damage":
        spec = ctx.attack_defense_spec
        if spec is not None and spec.get("damage") is not None:
            damage = spec["damage"]
            spec["damage"] = damage.model_copy(update={"modifier": damage.modifier + _pb(actor)})
    elif picked[0] == "move":
        move(ctx, actor, 5, "choice:needle.four_hand_move", "Four-Hand Sequence")
    else:
        te.run_effects(_sub(ctx, [actor]), [{"type": "ac_bonus", "applies_to": "self", "flat": 1, "duration": "until_start_of_your_next_turn"}])
    mandala(ctx.engine, actor, ctx.intent)


def move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "hundred_hands_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "hundred_hands")


def _four_hand_guard(engine: Any, holder: Any, rctx: Any) -> bool:
    actor = holder.actor
    if rctx.roller is not actor or rctx.ac is None:
        return False
    action = engine.action_catalog.get(str(rctx.source_id or ""))
    if action is None or not _four_hand_ready(engine, actor, action):
        return False
    return rctx.natural != 1


def _four_hand_used(engine: Any, holder: Any, rctx: Any) -> None:
    _turn(holder.actor, engine, "_round_four_hand")["used"] = True


def _register_four_hand() -> None:
    from .d20_rewrite import Rule, register, row_holders

    register(Rule("four_hand_sequence", "Four-Hand Sequence (+ Proficiency Bonus to a missed attack)", feature=PREFIX + "four_hand_sequence",
                  rolls=("attack",), who="self", when="failed", op="bonus", costs=((("battle_hand", 1),),), checkpoint="D20_REWRITE_ROLL",
                  finder=row_holders("four_hand_sequence", PREFIX + "four_hand_sequence"), guard=_four_hand_guard, on_use=_four_hand_used,
                  bonus=lambda engine, holder, rctx: _pb(holder.actor),
                  say=lambda engine, holder, rctx, new: f"Four-Hand Sequence: {holder.actor.display_name} adds its Proficiency Bonus to the missed attack."))


_register_four_hand()


# ------------------------------------------------------------------------------------------------- Weapon-Wheel Body
@hook("attack_resolved")
def record_form(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or engine.state.current_actor_id != actor.entity_id:
        return
    form = form_of(ctx.action)
    record = _turn(actor, engine, "_round_hundred_forms")
    if form:
        record["last"] = form
        record.setdefault("first", form)
    if hit and form and target is not None:
        hits = list(record.get("hit_forms") or [])
        record["hit_forms"] = hits + ([form] if form not in hits else [])
        struck = dict(record.get("struck") or {})
        struck[target.entity_id] = int(struck.get(target.entity_id) or 0) + 1
        record["struck"] = struck


@hook("attack_mode")
def weapon_wheel_advantage(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or engine.state.current_actor_id != actor.entity_id or "weapon_wheel" not in _roles(engine, actor):
        return None
    record = _turn(actor, engine, "_round_hundred_forms")
    form = form_of(ctx.action)
    if not wheel_ready(engine, actor) or record.get("wheel_used") or not record.get("first") or not form or form == record.get("first"):
        return None
    record["wheel_used"] = True
    return "ADVANTAGE"


# ------------------------------------------------------------------------------------ Eight-Limb, Thousand-Hand hits
@hook("after_hit")
def hundred_hands_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if target is None or not (roles or _thousand(engine, actor)) or engine.state.current_actor_id != actor.entity_id:
        return
    form = form_of(ctx.action)
    record = _turn(actor, engine, "_round_hundred_forms")
    hits = list(record.get("hit_forms") or [])
    if form and form not in hits:  # attack_resolved records it too, after this; count it now for the Completion
        hits.append(form)
    struck = int((record.get("struck") or {}).get(target.entity_id) or 0) + 1
    if _thousand(engine, actor) and struck >= 3 and not record.get("force_used") and target.active:
        record["force_used"] = True
        from .. import typed_executor as te

        te.run_effects(_sub(ctx, [target]), [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 5, "sides": 8}, "damage_types": ["force"],
                                             "evidence": "Thousand-Hand Incarnation: third hit on the same creature this turn, + 5d8 Force"}])
    if "eight_limb" in roles and len(hits) >= 3 and not record.get("completion_used") and engine.state.current_actor_id == actor.entity_id:
        if completions(ctx, 1, "Eight-Limb Battle Pattern: three different Forms have hit this turn", extra_target=target):
            record["completion_used"] = True


def _hit_this_turn(engine: Any, actor: Any) -> list[Any]:
    struck = _turn(actor, engine, "_round_hundred_forms").get("struck") or {}
    return [engine.state.actors[i] for i in sorted(struck) if i in engine.state.actors and engine.state.actors[i].active]


def completions(ctx: Any, count: int, why: str, extra_target: Any = None) -> bool:
    """Choose ``count`` different Completion Effects (asked); target-based ones name a creature hit this turn."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    hit = _hit_this_turn(engine, actor)
    if extra_target is not None and extra_target.active and extra_target not in hit:
        hit.append(extra_target)
    options, labels = [], {}
    for creature in hit:
        for key, text in (("push", "Push {} 10 feet"), ("prone", "Knock {} Prone"), ("no_reactions", "{} cannot take Reactions until its next turn")):
            options.append(f"{key}|{creature.entity_id}")
            labels[options[-1]] = text.format(creature.display_name)
    options += ["temp_hp|", "move|"]
    labels.update({"temp_hp|": f"Gain {2 * _pb(actor)} Temporary Hit Points", "move|": "Move 15 feet without provoking"})
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "eight_limb_completion", actor.entity_id), actor, "choice:needle.eight_limb_completion", options,
                 labels=labels, minimum=1, maximum=count, allow_decline=True, target_id=actor.entity_id, name="Eight-Limb Battle Pattern",
                 prompt=f"{why}: choose {'one Completion Effect' if count == 1 else f'up to {count} different Completion Effects'}.")
    chosen = [o for o in options if o in (picked or [])]
    kinds = [o.split("|")[0] for o in chosen]
    if len(set(kinds)) != len(kinds):
        chosen = list({o.split("|")[0]: o for o in reversed(chosen)}.values())[::-1]  # different effects only
    for option in chosen[:count]:
        key, _, target_id = option.partition("|")
        target = engine.state.actors.get(target_id)
        if key == "push" and target is not None:
            te.run_effects(_sub(ctx, [target]), [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
        elif key == "prone" and target is not None:
            te.run_effects(_sub(ctx, [target]), [{"type": "condition", "applies_to": "target", "condition": "prone"}])
        elif key == "no_reactions" and target is not None:
            te.run_effects(_sub(ctx, [target]), [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
        elif key == "temp_hp":
            te.run_effects(_sub(ctx, [actor]), [{"type": "temp_hp", "applies_to": "self", "formula": "double_pb"}])
        elif key == "move":
            move(ctx, actor, 15, "choice:needle.eight_limb_move", "Eight-Limb Battle Pattern")

    return bool(chosen)


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, *, mandala_strike: bool = False, on_hit: Any = ()) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack["count"] = 1
    attack["on_hit"] = list(attack.get("on_hit") or []) + list(on_hit)
    attack["granted_attack_root"] = True  # this strike is the granted one; anything it would grant in turn is not
    granted = {**typed, "effects": [attack], "granted_attack": True, **({"mandala_strike": True} if mandala_strike else {})}
    te.run_effects(te.Context(engine, actor, action, intent, granted, [target], target, {}), [attack])


def _reachable(engine: Any, actor: Any, action: Any) -> list[Any]:
    typed = (action.parameters or {}).get("typed") or {}
    reach = max(int(action.range_ft or 5), int(typed.get("long_range_ft") or 0), int(typed.get("range_ft") or 0))
    return [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if a.active and a.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, a) <= reach and engine._line_of_sight_actor_to_actor(actor, a)]


def _attack_choices(engine: Any, actor: Any, not_form: str | None, *, unarmed_only: bool = False) -> dict[str, tuple[Any, Any]]:
    """{option id: (action, target)} for the owner's Attack-action attacks (one of each base weapon) with a Form other than ``not_form``."""
    from .hand_occupancy import weapon_allowed

    out: dict[str, tuple[Any, Any]] = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        params = action.parameters or {}
        if action.owner_id != actor.entity_id or not attack_action(action) or any(params.get(k) for k in ("setting_only", "player_only", "object_attack",
                                                                                                            "reach_bonus", "falcon_range")):
            continue
        if "#" in action.source_definition_id and not action.source_definition_id.endswith(("#thrown", "#integrated_con", "#mandala_con")):
            continue
        if weapon_allowed(engine, actor, action) is False:
            continue  # A granted attack still needs its physical weapon readied.
        form = form_of(action)
        if form is None or (not_form is not None and form == not_form) or (unarmed_only and form != "Unarmed"):
            continue
        for target in _reachable(engine, actor, action):
            out[f"{action.source_definition_id}|{target.entity_id}"] = (action, target)
    return out


@hook("action_completed")
def eight_limb(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    action = engine.action_catalog.get(source_definition_id)
    if action is None or not actor.active or not attack_action(action) or engine.state.current_actor_id != actor.entity_id:
        return
    roles = _roles(engine, actor)
    record = _turn(actor, engine, "_round_hundred_forms")
    cost = 1 if _thousand(engine, actor) else 2
    intent = _intent(engine)
    if "eight_limb" in roles and not record.get("eight_used") and _hands(actor) >= cost:
        choices = _attack_choices(engine, actor, record.get("last"))
        if choices:
            from .needle import ask, checkpoint_id

            picked = ask(engine, intent, checkpoint_id(engine, "eight_limb", actor.entity_id), actor, "choice:needle.eight_limb_attack", list(choices),
                         labels={k: f"{a.display_name} against {t.display_name}" for k, (a, t) in choices.items()}, allow_decline=True,
                         target_id=actor.entity_id, name="Eight-Limb Battle Pattern",
                         prompt=f"Eight-Limb Battle Pattern: spend {cost} Battle Hand{'s' if cost > 1 else ''} for one more attack with a different Form?")
            if picked and picked[0] in choices:
                record["eight_used"] = True
                _spend(engine, actor, cost, PREFIX + "eight_limb_battle_pattern")
                attack, target = choices[picked[0]]
                _granted(engine, actor, attack, target, intent)
    mandala(engine, actor, intent)


# -------------------------------------------------------------------------------------------------- Mandala Completion
def mandala(engine: Any, actor: Any, intent: Any) -> None:
    """Thousand-Hand Incarnation: once per turn after at least 4 Hands were spent this turn (asked)."""
    if not actor.active or not _thousand(engine, actor) or engine.state.current_actor_id != actor.entity_id:
        return
    record = _turn(actor, engine, "_round_hands_spent")
    if int(record.get("spent") or 0) < 4 or record.get("mandala_used"):
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    labels = {"strike": "Make one additional unarmed strike", "guard": "+3 AC until your next turn",
              "move": "Move up to your Speed without provoking", "double": "Apply two different Eight-Limb Completion Effects"}
    picked = ask(engine, intent, checkpoint_id(engine, "mandala", actor.entity_id), actor, "choice:needle.mandala_completion", list(labels),
                 labels=labels, allow_decline=True, target_id=actor.entity_id, name="Mandala Completion",
                 prompt="Mandala Completion: you have spent 4 Battle Hands this turn. Choose one.")
    choice = picked[0] if picked else None
    if choice is None:
        return
    record["mandala_used"] = True
    ctx = context(engine, actor, PREFIX + "thousand_hand_incarnation", [actor], {"pb": _pb(actor)})
    ctx.intent = intent
    if choice == "guard":
        te.run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": 3, "duration": "until_start_of_your_next_turn"}])
    elif choice == "move":
        move(ctx, actor, int(engine._effective_speed(actor)), "choice:needle.mandala_move", "Mandala Completion")
    elif choice == "double":
        completions(ctx, 2, "Mandala Completion")
    elif choice == "strike":
        choices = _attack_choices(engine, actor, None, unarmed_only=True)
        if choices:
            pick = ask(engine, intent, checkpoint_id(engine, "mandala_strike", actor.entity_id), actor, "choice:needle.mandala_strike", list(choices),
                       labels={k: f"{a.display_name} against {t.display_name}" for k, (a, t) in choices.items()}, target_id=actor.entity_id,
                       prompt="Mandala Completion: your additional unarmed strike.")
            if pick and pick[0] in choices:
                _granted(engine, actor, *choices[pick[0]], intent, mandala_strike=True)


@effect("hundred_hands_fill")
def thousand_hands_fill(ctx: Any, row: dict[str, Any]) -> None:
    """"Current and maximum Battle Hands immediately become 2 x Proficiency Bonus"."""
    if HANDS in ctx.actor.resources:
        ctx.actor.resource_maximums[HANDS] = 2 * _pb(ctx.actor)
        _set_hands(ctx.engine, ctx.actor, maximum(ctx.engine, ctx.actor), PREFIX + "thousand_hand_incarnation")


@hook("effect_expiring")
def thousand_hands_end(engine: Any, holder: Any, row: Any) -> None:
    """"Ending ... returns maximum Hands to Proficiency Bonus and removes current Hands above that maximum"."""
    from .states import PREFIX as STATE_PREFIX

    if getattr(row, "condition_id", None) == STATE_PREFIX + STATE:
        holder.resource_maximums[HANDS] = _pb(holder)
        if _hands(holder) > _pb(holder):
            _set_hands(engine, holder, _pb(holder), PREFIX + "thousand_hand_incarnation")


# --------------------------------------------------------------------------------------------- Circle of Uncounted Arms
@effect("circle_hand")
def circle_hand(ctx: Any, row: dict[str, Any]) -> None:
    """The reactor (ctx.actor) answers the triggering hostile creature (ctx.target); its Reaction and 2 Hands are already paid."""
    from .. import typed_executor as te
    from ..typed_reactions import triggered_context
    from .needle import ask, checkpoint_id

    engine, reactor, other = ctx.engine, ctx.actor, ctx.target
    if other is None or not other.active:
        return
    pending = getattr(engine, "_typed_pending_attack", None) or {}
    attacked = pending.get("attacker") == other.entity_id and pending.get("target") == reactor.entity_id
    labels = {"intercept": f"Intercepting Hand: strike {other.display_name}; a hit takes {_pb(reactor)} off its attack roll",
              "seize": f"Seizing Hand: Grapple {other.display_name}",
              "deflect": "Deflecting Hand: +3 AC against this attack",
              "silence": f"Silencing Hand: unarmed strike; a hit stops {other.display_name}'s Reactions until its next turn"}
    options = [k for k in ("deflect", "intercept", "seize", "silence") if k != "deflect" or attacked]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "circle_hand", other.entity_id), reactor, "choice:needle.circle_of_uncounted_arms", options,
                 labels={k: labels[k] for k in options}, target_id=other.entity_id, name="Circle of Uncounted Arms",
                 prompt=f"Circle of Uncounted Arms: {other.display_name} acts within your reach. Choose a Hand.")
    hand = picked[0] if picked else options[0]
    if hand == "deflect":
        other.turn_flags["_circle_against"] = {"target": reactor.entity_id, "amount": 3, "hand": "Deflecting Hand", "by": reactor.entity_id}
    elif hand == "seize":
        from .grapple_attempts import attempt

        attempt(engine, reactor, other, ctx.intent, ("grapple",), choice_id="choice:needle.circle_seize", prompt="")
    else:
        strike = {"type": "attack", "attack_kind": "unarmed" if hand == "silence" else "weapon", "count": 1,
                  "on_hit": [{"type": "circle_hit", "hand": hand, "against": pending.get("target") if pending.get("attacker") == other.entity_id else None}]}
        sub = triggered_context(engine, reactor, other, {"feature_id": PREFIX + "circle_of_uncounted_arms", "name": "Circle of Uncounted Arms",
                                                         "effects": [strike], "numbers": dict(ctx.numbers)}, ctx.intent)
        te.run_effects(sub, [strike])
    mandala(engine, reactor, ctx.intent)


@effect("circle_hit")
def circle_hit(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is None:
        return
    if row.get("hand") == "silence":
        from .. import typed_executor as te

        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif row.get("hand") == "intercept" and row.get("against"):
        target.turn_flags["_circle_against"] = {"target": row["against"], "amount": _pb(ctx.actor), "hand": "Intercepting Hand", "by": ctx.actor.entity_id}


@hook("hit_response")
def circle_turns_the_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = attacker.turn_flags.get("_circle_against")
    if not isinstance(held, dict) or held.get("target") != target.entity_id:
        return None
    attacker.turn_flags.pop("_circle_against", None)
    if natural == 20 or total >= effective_ac + int(held.get("amount") or 0):
        return None
    by = engine.state.actors.get(str(held.get("by") or ""))
    note(engine, PREFIX + "circle_of_uncounted_arms", by or attacker, f"Circle of Uncounted Arms ({held.get('hand')}): the attack on {target.display_name} misses.", (attacker,))
    return effective_ac + int(held.get("amount") or 0), False


@hook("attack_resolved")
def circle_clears(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """The Circle answer lasts for the triggering attack only."""
    if "_circle_against" in ctx.actor.turn_flags:
        ctx.actor.turn_flags.pop("_circle_against", None)


@hook("technique_declared")
def four_hand_opening(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Non-hit operations remain available even when every attack will miss."""
    if not _four_hand_ready(engine, actor, action):
        return
    from .needle import ask, checkpoint_id
    from .states import context
    from .. import typed_executor as te
    from .equipment_hands import set_weapon_readiness
    choices = equipment_pairs(engine, actor)
    labels = {"move": "Move 5 feet without provoking", "ac": "+1 AC until the start of your next turn", **{key: value[1] for key, value in choices.items()}}
    picked = ask(engine, intent, checkpoint_id(engine, "four_hand_opening", actor.entity_id), actor,
                 "choice:needle.four_hand_opening", list(labels), labels=labels, allow_decline=True, default="decline",
                 name="Four-Hand Sequence", feature_id=PREFIX + "four_hand_sequence",
                 prompt=f"{actor.display_name} takes {action.display_name}. Spend 1 Battle Hand now, or keep it for a hit or miss?",
                 prompt_context={"cost": "1 Battle Hand", "paying_pool": HANDS})
    if not picked or picked[0] not in labels:
        return
    _turn(actor, engine, "_round_four_hand")["used"] = True
    _spend(engine, actor, 1, PREFIX + "four_hand_sequence")
    ctx = context(engine, actor, PREFIX + "four_hand_sequence", [actor], {"pb": _pb(actor)})
    ctx.intent = intent
    if picked[0] == "move":
        move(ctx, actor, 5, "choice:needle.four_hand_move", "Four-Hand Sequence")
    elif picked[0] == "ac":
        te.run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": 1, "source_owned": True,
                              "duration": "until_start_of_your_next_turn"}])
    else:
        for weapon, held in choices[picked[0]][0]:
            set_weapon_readiness(engine, actor, weapon, held, source=PREFIX + "four_hand_sequence", source_actor_id=actor.entity_id)
    mandala(engine, actor, intent)


def equipment_pairs(engine: Any, actor: Any) -> dict[str, Any]:
    """Two owned physical items, validated together against actual hand occupancy.

    Uses the shared possession/readiness producer; neither grants items nor changes
    the ordinary object interaction. Stowing is evaluated before drawing.
    """
    from itertools import combinations
    from .hand_occupancy import weapon_grips, occupancy, hand_parts, resting_hands
    from .weapon_hits import available_weapons
    ready = weapon_grips(engine, actor)
    available = available_weapons(engine, actor, include_busy=True)
    options = {}
    for pair in combinations(sorted(available), 2):
        changes = [(key, key not in ready) for key in pair]
        proposed = dict(ready)
        for key, held in changes:
            if held:
                proposed[key] = resting_hands(available[key])
            else:
                proposed.pop(key, None)
        occupied = occupancy(engine, actor, grips=proposed)
        if sum(len(parts) for parts in occupied.values()) > len(hand_parts(engine, actor)):
            continue
        key = "equipment|" + "|".join(pair)
        ordered = sorted(changes, key=lambda value: value[1])
        label = "; ".join(("Draw " if held else "Stow ") + available[item].display_name.removesuffix(" attack") for item, held in ordered)
        options[key] = (ordered, label)
    return options


CIRCLE = PREFIX + "circle_of_uncounted_arms"


def circle_record(engine: Any, actor: Any) -> dict[str, Any]:
    """Round-scoped family record; turn identities survive cold reload."""
    key = "_round_circle_uses"
    held = actor.turn_flags.get(key)
    if not isinstance(held, dict) or held.get("round") != engine.state.round_number:
        held = {"round": engine.state.round_number, "turns": []}
        actor.turn_flags[key] = held
    return held


@hook("row_allowed")
def circle_native_only(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != CIRCLE:
        return None
    if row.get("native_checkpoint") != "CIRCLE_DECLARED":
        return False
    record = circle_record(engine, actor)
    limit = 2 if _thousand(engine, actor) else 1
    return len(record["turns"]) < limit and _stamp(engine) not in record["turns"]


def circle_reach(engine: Any, actor: Any) -> int:
    from ..attack_reach import maximum as attack_maximum
    return max([5] + [attack_maximum(engine, actor, action, base=int(action.reach_ft or action.range_ft or 5))
                     for action in engine.action_catalog.values() if action.owner_id == actor.entity_id
                     and form_of(action) and not (action.parameters.get("typed") or {}).get("range_ft")])


def circle_offer(engine: Any, other: Any, source: str, intent: Any, *, attack_target: Any = None,
                 movement: bool = False) -> bool:
    """Answer one committed activation before its roll, save or first willing step.

    Returns True only when Seizing Hand stopped this activation's movement.
    Admission/payment use the public reaction contract and actual owned bundle.
    """
    from ..typed_reactions import checkpoint_response, commit_checkpoint_response
    from .needle import ask, checkpoint_id
    from .states import context
    from .grapple_attempts import attempt, options as grapple_options
    from .. import typed_executor as te
    stopped = False
    for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if actor is other or actor.team_id == other.team_id or not actor.active or not other.active:
            continue
        if engine._distance_actor_to_actor(actor, other) > circle_reach(engine, actor):
            continue
        row = checkpoint_response(engine, actor, other, other, CIRCLE, "CIRCLE_DECLARED")
        if row is None:
            continue
        choices = {key: value for key, value in _attack_choices(engine, actor, None).items() if value[1] is other
                   and not (value[0].parameters.get("typed") or {}).get("range_ft")}
        unarmed = {key: value for key, value in choices.items() if form_of(value[0]) == "Unarmed"}
        labels = {}
        if choices:
            labels["intercept"] = f"Intercepting Hand: attack {other.display_name}; a hit subtracts {_pb(actor)} from its triggering attack roll or Cultivation Check"
        if grapple_options(engine, actor, ("grapple",)):
            labels["seize"] = f"Seizing Hand: Grapple {other.display_name}; success stops this activation's movement"
        if attack_target is actor:
            labels["deflect"] = "Deflecting Hand: +3 AC against this triggering attack"
        if unarmed:
            labels["silence"] = f"Silencing Hand: unarmed strike against {other.display_name}; a hit prevents Reactions until the start of its next turn"
        picked = ask(engine, intent, checkpoint_id(engine, "circle_declared", other.entity_id), actor,
                     "choice:needle.circle_of_uncounted_arms", list(labels), labels=labels, allow_decline=True,
                     name="Circle of Uncounted Arms", feature_id=CIRCLE,
                     prompt=f"{other.display_name} commits to {source}. Spend your Reaction and 2 Battle Hands?",
                     prompt_context={"cost": "Reaction and 2 Battle Hands", "paying_pool": HANDS})
        if not picked or picked[0] not in labels:
            continue
        # Reserve before a nested counterattack can open another declaration.
        commit_checkpoint_response(engine, actor, other, row, "CIRCLE_DECLARED")
        circle_record(engine, actor)["turns"].append(_stamp(engine))
        hand = picked[0]
        if hand == "deflect":
            other.turn_flags["_circle_against"] = {"target": actor.entity_id, "amount": 3, "hand": "Deflecting Hand", "by": actor.entity_id}
        elif hand == "seize":
            attempt(engine, actor, other, intent, ("grapple",), choice_id="choice:needle.circle_seize", prompt="")
            if movement and any(c.condition_id.endswith("grappled") and c.source_actor_id == actor.entity_id for c in other.conditions.values()):
                stopped = True
        else:
            available = unarmed if hand == "silence" else choices
            chosen = ask(engine, intent, checkpoint_id(engine, "circle_strike", other.entity_id), actor,
                         "choice:needle.circle_strike", list(available), labels={key: action.display_name for key, (action, _) in available.items()},
                         name="Circle of Uncounted Arms", prompt=f"Choose one attack against {other.display_name}.")
            if chosen and chosen[0] in available:
                action, target = available[chosen[0]]
                _granted(engine, actor, action, target, intent,
                         on_hit=[{"type": "circle_native_hit", "hand": hand, "trigger_source": source}])
        mandala(engine, actor, intent)
    return stopped


@effect("circle_native_hit")
def circle_native_hit(ctx: Any, row: dict[str, Any]) -> None:
    if row["hand"] == "silence":
        from .. import typed_executor as te
        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    else:
        ctx.target.turn_flags["_circle_roll_penalty"] = {"source": row["trigger_source"], "amount": _pb(ctx.actor), "by": ctx.actor.entity_id}


@hook("d20_bonus", priority=90)
def circle_roll_penalty(engine: Any, roll: Any, intent: Any) -> Any:
    context = engine.d20_context(roll)
    if not context or context.get("kind") not in ("attack", "check"):
        return None
    actor = engine.state.actors.get(context.get("actor_id"))
    held = actor.turn_flags.get("_circle_roll_penalty") if actor is not None else None
    if held and held["source"] == context.get("source_id"):
        actor.turn_flags.pop("_circle_roll_penalty", None)
        return [{"source_id": CIRCLE, "user_id": held["by"], "bonus": -held["amount"]}]
    return None


@hook("technique_declared", priority=10)
def circle_declaration(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> dict[str, Any] | None:
    typed = action.parameters.get("typed") or {}
    effects = list(typed.get("effects") or [])
    def physical_save(rows):
        return any(isinstance(row, dict) and (row.get("type") == "save" and str(row.get("ability") or "").upper()[:3] in ("STR", "DEX", "CON")
                   or physical_save(row.get("effects") or []) or physical_save(row.get("on_hit") or [])) for row in rows)
    attacks = any(row.get("type") == "attack" for row in effects) or str(action.resolution_kind) == "ATTACK"
    maneuver = typed.get("unarmed_option") in ("grapple", "shove_push", "shove_prone")
    moving = action.resolution_kind in ("DASH", "DISENGAGE")
    if not (attacks or maneuver or moving or physical_save(effects)):
        return None
    target = engine.state.actors.get(next(iter(candidate.target_ids), "")) if attacks else None
    stopped = circle_offer(engine, actor, action.source_definition_id, intent, attack_target=target, movement=moving or maneuver)
    if stopped:
        return {"source_id": CIRCLE, "label": "Seizing Hand stops the triggering movement", "movement_cap_ft": 0, "forced_cap_ft": 0}
    return None


@hook("movement_attempt", priority=-10)
def circle_movement(engine: Any, actor: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    from ..movement_steps import context
    if context(engine, actor).get("forced"):
        return None
    if circle_offer(engine, actor, "willing movement of at least 5 feet", intent, movement=True):
        return {"stop": True, "source_id": CIRCLE, "label": "Seizing Hand stops this movement"}
    return None


@hook("activation_end")
def circle_activation_end(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    actor.turn_flags.pop("_circle_roll_penalty", None)
    actor.turn_flags.pop("_circle_against", None)


def wheel_ready(engine: Any, actor: Any) -> bool:
    """Actual attack-capable Forms; carried inaccessible gear grants no integration."""
    from .hand_occupancy import weapon_allowed
    forms = {form_of(action) for action in engine.action_catalog.values()
             if action.owner_id == actor.entity_id and attack_action(action)
             and weapon_allowed(engine, actor, action) is not False
             and any(row.get("type") == "attack" for row in (action.parameters.get("typed") or {}).get("effects") or [])}
    forms.discard(None)
    return len(forms) >= 2


@hook("candidate_allowed")
def wheel_integration_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or "weapon_wheel" not in _roles(engine, actor):
        return None
    if action.source_definition_id.endswith(("#integrated_con", "#mandala_con")) and not wheel_ready(engine, actor):
        return False
    return None


@hook("compile_actions")
def wheel_constitution_attack(info: dict[str, Any]) -> list[Any]:
    """Optional ordinary Constitution attack beside the existing Cultivation modifier."""
    from .integrated_weapons import in_group
    from copy import deepcopy
    owned = any(row.get("kind") == "hundred_hands" and row.get("role") == "weapon_wheel"
                for mid in info["owned_ids"] for row in (info["mechanics"].get(mid) or {}).get("effects") or [])
    if not owned:
        return []
    out = []
    for action in info["actions"]:
        typed = action.parameters.get("typed") or {}
        if "#" in action.source_definition_id or not in_group(typed, "one_handed_melee"):
            continue
        variant = deepcopy(typed)
        con = int(info["mods"].get("CON") or 0)
        old = int(variant["weapon"].get("ability_modifier") or 0)
        variant["numbers"]["attack_bonus"] += con - old
        variant["weapon"]["damage"]["modifier"] = con + int(typed.get("magic_bonus") or 0)
        variant["weapon"]["ability_modifier"] = con
        out.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "#mandala_con",
            "display_name": action.display_name + " (Constitution and weapon proficiency)",
            "parameters": {**action.parameters, "typed": variant}}))
    return out
