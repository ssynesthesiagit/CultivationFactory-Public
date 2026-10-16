"""Hundred-Hand Battle Mandala: source-owned native coordination records.

Body Refining Subpath Compendium R8, parent 35 and its normalized procedures.
Owned path_rider/hundred_hands roles gate Four-Hand, Weapon-Wheel and Eight-Limb;
the owned Circle reaction row gates native pre-resolution responses. Incarnation
uses its ordinary timed state, source-owned Stamina/scene costs and reach rows.
No matching row/state means no family choices, resource edits or effects.

The native resource pool is resource:named.battle_hand. Primitive turn records
store spending, confirmed roll ids, distinct hit Forms/targets and operation
uses; round records store Circle uses and creature-turn identities. Confirmed
hit provenance is collected before nested riders, once per actual attack roll.
Draw/Stow uses the public possession, occupancy and readiness producers. The
Weapon-Wheel Attack action spends one ordinary Action and derives its attack
count from compiled ordinary attacks, choosing gear and a legal profile before
each strike. It creates no weapons, limbs, proficiency or extra attacks.

Four-Hand miss correction uses the shared additive d20 rule (unchanged natural
die); its hit damage joins the original packet. Completion/Force riders retain
their feature source. Circle uses public checkpoint admission/payment and native
attack, Grapple, movement and roll consumers. Granted strikes carry the engine's
granted_attack_root and cannot recursively grant attacks. Manual choices use the
journaled Needle transport on every creature's turn; AI has the same legal
profiles and its own owned equipment. Every stored record survives cold reload.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.hundred_hand_battle_mandala.feature."
HANDS = "resource:named.battle_hand"
BODY = "tianxia.path.body_refining"
LEVELS = dict(zip(("four_hand_sequence", "weapon_wheel_body", "eight_limb_battle_pattern", "circle_of_uncounted_arms", "thousand_hand_incarnation"), (3, 6, 10, 14, 18)))
ROLE_LEVELS = {"four_hand": 3, "weapon_wheel": 6, "eight_limb": 10}
STATE = "thousand_hand_incarnation"
from .integrated_weapons import FORMS  # the catalog's Weapon Forms (shared with Kensei's Blade group)
COMPLETIONS = ("push", "prone", "no_reactions", "temp_hp", "move")


# --------------------------------------------------------------------------------------------------------- records
def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "hundred_hands"
            and body_level(engine, actor) >= ROLE_LEVELS.get(str(row.get("role")), 99)}


def _thousand(engine: Any, actor: Any) -> bool:
    from .states import active

    owned = any(row.get('feature_id') == PREFIX + 'thousand_hand_incarnation'
                for row in engine.typed_passive_rows.get(actor.entity_id, []))
    return bool(owned and body_level(engine, actor) >= 18 and active(engine, actor, STATE))


def body_level(engine: Any, actor: Any) -> int:
    from .path_authority import effective_cl
    from .ability_source import numbers_of
    bundle = next((b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id), {})
    learned = int((bundle.get('hundred_hand_profile') or {}).get('body_cl', numbers_of(engine, actor).get('cl') or 0))
    return min(learned, effective_cl(engine, actor, BODY, learned))


def _pb(engine: Any, actor: Any) -> int:
    # Attainment gates access; it is not a replacement for the creature's PB.
    # A native Realm producer may change that actual statistic independently.
    value = getattr(actor, "proficiency_bonus", None)
    from .path_authority import effective_pb
    return effective_pb(engine, actor, BODY, int(value) if type(value) is int else 2)



def current_numbers(engine: Any, actor: Any, typed: dict[str, Any]) -> dict[str, Any]:
    """The source profile with an explicitly declared Realm PB, without catalog edits."""
    numbers = dict(typed.get('numbers') or {})
    delta = _pb(engine, actor) - actor.proficiency_bonus
    if delta:
        numbers['pb'] = _pb(engine, actor)
        for key in ('attack_bonus', 'save_dc'):
            if type(numbers.get(key)) is int:
                numbers[key] += delta
    return numbers


@hook('attack_bonus')
def wheel_realm_attack_bonus(ctx: Any, subject: Any) -> int | None:
    if subject is not ctx.actor or 'weapon_wheel' not in _roles(ctx.engine, ctx.actor) or not wheel_ready(ctx.engine, ctx.actor):
        return None
    if not any(tag in ctx.action.source_definition_id for tag in ('#integrated_con', '#mandala_con')):
        return None
    return _pb(ctx.engine, ctx.actor) - ctx.actor.proficiency_bonus


def _stamp(engine: Any) -> str:
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{int(getattr(current, 'turns_started', 0))}"


def _turn(actor: Any, engine: Any, key: str, *, create: bool = True) -> dict[str, Any]:
    """This turn's record under ``key`` (a fresh one once the turn has changed)."""
    held = actor.turn_flags.get(key)
    if not isinstance(held, dict) or held.get("stamp") != _stamp(engine):
        held = {"stamp": _stamp(engine)}
        if create:
            actor.turn_flags[key] = held
    return held


def maximum(engine: Any, actor: Any) -> int:
    return 2 * _pb(engine, actor) if _thousand(engine, actor) else _pb(engine, actor)


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
    mandala(engine, actor, _intent(engine))


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def attack_action(action: Any) -> bool:
    """One attack of the Attack action (a weapon, natural or improvised attack), not a technique, reaction or granted strike."""
    typed = (action.parameters or {}).get("typed") or {}
    if str(getattr(action.economy, "value", action.economy)) != "ACTION" or typed.get("reaction_attack") or typed.get("opportunity_of") \
            or (typed.get("granted_attack") and not typed.get("attack_action_parent")):
        return False
    return bool(typed.get("attack_action")) or bool(re.search(r"\.(?:weapon|improvised)\.", action.source_definition_id))


def form_of(action: Any) -> str | None:
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("unarmed_option"):
        return "Unarmed"  # The save replaces one Unarmed attack; attached weapon metadata is not its Form.
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
    from factory_authoring.starting_kits import item_definition
    if (item_definition(str(typed.get("source") or "")) or {}).get("armor_category") == "shield":
        return "Shield"
    return FORMS.get(str(typed.get("source") or "").rsplit(".", 1)[-1])


@hook("match_initialize")
def initialize_hands(engine: Any) -> None:
    """Normalize every acquired pool before the first creature's turn.

    Compiled capacity includes the potential Incarnation maximum. A creature
    waiting for its first turn has only its normal PB maximum until activation.
    The existing evented capacity producer makes genesis/replay agree.
    """
    for actor in engine.state.actors.values():
        if HANDS in actor.resources and any(str(r.get("feature_id") or "").startswith(PREFIX) for r in engine.typed_passive_rows.get(actor.entity_id, [])):
            engine._set_resource_maximum(actor, HANDS, maximum(engine, actor), "system:battle_hands_clamp")


@hook("turn_start")
def refresh_hands(engine: Any, actor: Any) -> None:
    """"All refresh at the start of your turn and unused Hands disappear": the pool is full again at the owner's turn start."""
    from .states import PREFIX as STATE_PREFIX
    raw = next((c for c in actor.conditions.values() if c.condition_id == STATE_PREFIX + STATE), None)
    owns_incarnation = any(row.get('feature_id') == PREFIX + 'thousand_hand_incarnation'
                           for row in engine.typed_passive_rows.get(actor.entity_id, []))
    if raw is not None and owns_incarnation:
        from .retained_updates import record_instance_update
        can_grant = _thousand(engine, actor) and raw.data.get('hundred_hand_extra_granted_round') != engine.state.round_number
        deadline = int(actor.turns_started) + (0 if can_grant else 1)
        changed = raw.data.get('hundred_hand_extra_after_turn') != deadline
        if can_grant:
            raw.data['hundred_hand_extra_granted_round'] = engine.state.round_number
            changed = True
        if changed:
            raw.data['hundred_hand_extra_after_turn'] = deadline
            record_instance_update(engine, actor, 'condition', raw.instance_id, raw)
    if HANDS in (actor.resources or {}) and actor.active and _roles(engine, actor) | ({"thousand"} if _thousand(engine, actor) else set()):
        from .states import active
        incarnation = active(engine, actor, STATE)
        if incarnation is not None and "hundred_hand_extra_after_turn" not in incarnation.data:
            from .retained_updates import record_instance_update
            incarnation.data["hundred_hand_extra_after_turn"] = int(actor.turns_started)
            record_instance_update(engine, actor, "condition", incarnation.instance_id, incarnation)
        engine._set_resource_maximum(actor, HANDS, 2 * _pb(engine, actor) if _thousand(engine, actor) else _pb(engine, actor), "system:battle_hands_refresh")
        _set_hands(engine, actor, maximum(engine, actor), "system:battle_hands_refresh")


@hook("event")
def count_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Hands spent during the current turn (Mandala Completion's "after spending at least 4")."""
    payload = kwargs.get("payload") or {}
    if event_type != "RESOURCE_SPENT" or payload.get("resource_id") != HANDS or str(engine.events[-1].source_definition_id) in ("system:battle_hands_refresh", "system:battle_hands_clamp"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is not None and (_roles(engine, actor) or _thousand(engine, actor)):
        record = _turn(actor, engine, "_round_hands_spent")
        record["spent"] = int(record.get("spent") or 0) + int(payload.get("amount") or 0)


# ------------------------------------------------------------------------------------------------ Four-Hand Sequence
def _four_hand_ready(engine: Any, actor: Any, action: Any) -> bool:
    typed = action.parameters.get('typed') or {}
    known_form = form_for(engine, actor, action) is not None or bool(typed.get('unarmed_option')) or any(
        row.get('type') == 'weapon_wheel_sequence' for row in typed.get('effects', []))
    return ("four_hand" in _roles(engine, actor) and engine.state.current_actor_id == actor.entity_id and attack_action(action) and known_form
            and not _turn(actor, engine, "_round_four_hand", create=False).get("used") and _hands(actor) >= 1)


def _attack_types(ctx: Any) -> list[str]:
    weapon = ctx.typed.get("weapon") or {}
    return [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]


def _sub(ctx: Any, targets: list[Any], *, feature: str = PREFIX + "eight_limb_battle_pattern") -> Any:
    from ..typed_reactions import triggered_context
    return triggered_context(ctx.engine, ctx.actor, targets[0] if targets else None,
                             {"feature_id": feature, "name": feature.rsplit(".", 1)[-1].replace("_", " ").title(),
                              "numbers": {**dict(ctx.numbers), "pb": _pb(ctx.engine, ctx.actor), "cl": body_level(ctx.engine, ctx.actor)}}, ctx.intent)


@hook("damage_packet_selection")
def _four_hand_hit(ctx: Any, target: Any, packet_kinds: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _four_hand_ready(engine, actor, ctx.action):
        return
    from .needle import ask, checkpoint_id

    pairs = equipment_pairs(engine, actor)
    labels = {"damage": f"+{_pb(engine, actor)} damage to this hit", "move": "Move 5 feet without provoking", "ac": "+1 AC until your next turn",
              **{key: value[1] for key, value in pairs.items()}}
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
        if spec is not None and spec.get("fixed_damage") is not None:
            spec["fixed_damage"] += _pb(engine, actor)
        elif spec is not None and spec.get("damage") is not None:
            damage = spec["damage"]
            spec["damage"] = damage.model_copy(update={"modifier": damage.modifier + _pb(engine, actor)})
    elif picked[0] == "move":
        move(_sub(ctx, [actor], feature=PREFIX + 'four_hand_sequence'), actor, 5, "choice:needle.four_hand_move", "Four-Hand Sequence")
    elif picked[0] == "ac":
        te.run_effects(_sub(ctx, [actor], feature=PREFIX + "four_hand_sequence"),
                       [{"type": "ac_bonus", "applies_to": "self", "flat": 1, "source_owned": True,
                         "duration": "until_start_of_your_next_turn"}])
    else:
        from .equipment_hands import set_weapon_readiness
        current = equipment_pairs(engine, actor).get(picked[0])
        for weapon, held in (current[0] if current and current[0] == pairs[picked[0]][0] else []):
            set_weapon_readiness(engine, actor, weapon, held, source=PREFIX + "four_hand_sequence", source_actor_id=actor.entity_id)
    mandala(ctx.engine, actor, ctx.intent)


def move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes, resolve_path, Route
    from .needle import cell_id

    paths = {cell_id(cell): Route(tuple(path), mode) for cell, (path, cost, mode) in routes(ctx.engine, mover, feet).items()}
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "hundred_hands_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        resolve_path(ctx.engine, mover, paths[picked[0]], ctx.source, feet=feet, intent=ctx.intent, provokes=False)


def _four_hand_guard(engine: Any, holder: Any, rctx: Any) -> bool:
    actor = holder.actor
    if rctx.roller is not actor or rctx.ac is None:
        return False
    action = engine.action_catalog.get(str(rctx.source_id or ""))
    if action is None or not _four_hand_ready(engine, actor, action):
        return False
    return True  # Adding PB is legal even when a natural 1 will still miss.


def _four_hand_used(engine: Any, holder: Any, rctx: Any) -> None:
    _turn(holder.actor, engine, "_round_four_hand")["used"] = True
    mandala(engine, holder.actor, _intent(engine))


def _register_four_hand() -> None:
    from .d20_rewrite import Rule, register, row_holders

    register(Rule("four_hand_sequence", "Four-Hand Sequence (+ Proficiency Bonus to a missed attack)", feature=PREFIX + "four_hand_sequence",
                  rolls=("attack",), who="self", when="failed", op="bonus", costs=((("battle_hand", 1),),), checkpoint="D20_REWRITE_ROLL",
                  finder=row_holders("four_hand_sequence", PREFIX + "four_hand_sequence"), guard=_four_hand_guard, on_use=_four_hand_used,
                  bonus=lambda engine, holder, rctx: _pb(engine, holder.actor),
                  say=lambda engine, holder, rctx, new: f"Four-Hand Sequence: {holder.actor.display_name} adds its Proficiency Bonus to the missed attack."))


_register_four_hand()


# ------------------------------------------------------------------------------------------------- Weapon-Wheel Body
@hook("attack_resolved")
def record_form(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles and not _thousand(engine, actor):
        return
    form = form_for(engine, actor, ctx.action)
    record = _turn(actor, engine, "_round_hundred_forms")
    if form and engine.state.current_actor_id == actor.entity_id:
        if "weapon_wheel" in roles and wheel_ready(engine, actor):
            if record.get("first") and form != record["first"]:
                record["wheel_used"] = True
            record.setdefault("first", form)
        if attack_action(ctx.action):
            record["last"] = form
            record["action_intent"] = str(getattr(ctx.intent, "intent_id", ""))



@hook("attack_mode")
def weapon_wheel_advantage(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or engine.state.current_actor_id != actor.entity_id or "weapon_wheel" not in _roles(engine, actor):
        return None
    record = _turn(actor, engine, "_round_hundred_forms", create=False)
    form = form_for(engine, actor, ctx.action)
    if not wheel_ready(engine, actor) or record.get("wheel_used") or not record.get("first") or not form or form == record.get("first"):
        return None
    return "ADVANTAGE"


# ------------------------------------------------------------------------------------ Eight-Limb, Thousand-Hand hits
@hook("after_hit_choice")
def hundred_hands_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if target is None or not (roles or _thousand(engine, actor)):
        return
    form = form_for(engine, actor, ctx.action)
    record = _turn(actor, engine, "_round_hundred_forms")
    roll = ctx.attack_damage_context.roll_id if ctx.attack_damage_context is not None else None
    windows = record.get('completion_rolls', [])
    if "eight_limb" in roles and roll in windows and not record.get("completion_used") and engine.state.current_actor_id == actor.entity_id:
        windows.remove(roll)
        if completions(ctx, 1, "Eight-Limb Battle Pattern: three different Forms have hit this turn", extra_target=target):
            record["completion_used"] = True


def _hit_this_turn(engine: Any, actor: Any, *, forms_only: bool = False) -> list[Any]:
    record = _turn(actor, engine, "_round_hundred_forms")
    struck = record.get("struck") or {}
    targets = {target for values in record.get('form_targets', {}).values() for target in values} if forms_only else set(struck)
    return [engine.state.actors[i] for i in sorted(targets) if i in engine.state.actors and engine.state.actors[i].active]


def completions(ctx: Any, count: int, why: str, extra_target: Any = None) -> bool:
    """Choose ``count`` different Completion Effects (asked); target-based ones name a creature hit this turn."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    hit = _hit_this_turn(engine, actor, forms_only=count == 1)
    if extra_target is not None and extra_target.active and extra_target not in hit:
        hit.append(extra_target)
    options, labels = [], {}
    for creature in hit:
        for key, text in (("push", "Push {} 10 feet"), ("prone", "Knock {} Prone"), ("no_reactions", "{} cannot take Reactions until its next turn")):
            options.append(f"{key}|{creature.entity_id}")
            labels[options[-1]] = text.format(creature.display_name)
    options += ["temp_hp|", "move|"]
    labels.update({"temp_hp|": f"Gain {2 * _pb(engine, actor)} Temporary Hit Points", "move|": "Move 15 feet without provoking"})
    pairs = {}
    if count == 2:
        from itertools import combinations
        pairs = {f"pair:{index}": (first, second) for index, (first, second) in enumerate(combinations(options, 2))
                 if first.partition("|")[0] != second.partition("|")[0]}
    offered = list(pairs) if pairs else options
    offered_labels = {key: labels[first] + "; " + labels[second] for key, (first, second) in pairs.items()} if pairs else labels
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "eight_limb_completion", actor.entity_id), actor, "choice:needle.eight_limb_completion", offered,
                 labels=offered_labels, allow_decline=True, target_id=actor.entity_id, name="Eight-Limb Battle Pattern",
                 prompt=f"{why}: choose {'one Completion Effect' if count == 1 else 'two different Completion Effects'}.")
    chosen = list(pairs.get(picked[0], ())) if pairs and picked else [o for o in options if o in (picked or [])]
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
            move(_sub(ctx, [actor]), actor, 15, "choice:needle.eight_limb_move", "Eight-Limb Battle Pattern")

    return bool(chosen)


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, *, mandala_strike: bool = False, on_hit: Any = (), part_of_attack_action: bool = False) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    maneuver = bool(typed.get('unarmed_option'))
    attack = next((dict(e) for e in typed.get('effects') or [] if isinstance(e, dict)
                   and e.get('type') == ('save' if maneuver else 'attack')), None)
    if attack is None:
        return
    if not maneuver:
        attack['count'] = 1
        attack['on_hit'] = list(attack.get('on_hit') or []) + list(on_hit)
        attack['granted_attack_root'] = True
    granted = {**typed, 'numbers': current_numbers(engine, actor, typed) if maneuver else typed.get('numbers', {}),
               'effects': [attack], 'granted_attack': True, 'attack_action_parent': part_of_attack_action,
               **({'mandala_strike': True} if mandala_strike else {})}
    updates = {'parameters': {**action.parameters, 'typed': granted}}
    if maneuver:
        from ..attack_reach import maximum
        updates['range_ft'] = maximum(engine, actor, action, base=action.range_ft or 5)
    child_action = action.model_copy(update=updates)
    te.run_effects(te.Context(engine, actor, child_action, intent, granted, [target], target, {}), [attack])


def _reachable(engine: Any, actor: Any, action: Any) -> list[Any]:
    typed = (action.parameters or {}).get("typed") or {}
    from ..attack_reach import maximum as attack_maximum
    from ..relations import relation, ENEMY
    reach = attack_maximum(engine, actor, action, base=max(int(action.range_ft or action.reach_ft or 5), int(typed.get("long_range_ft") or 0), int(typed.get("range_ft") or 0)))
    return [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if a.active and relation(engine, actor, a) == ENEMY
            and engine._distance_actor_to_actor(actor, a) <= reach and engine._line_of_sight_actor_to_actor(actor, a)]



def unarmed_operation(action: Any) -> bool:
    """A Form tag alone never grants the ordinary Unarmed Strike procedure."""
    typed = action.parameters.get('typed') or {}
    return bool(typed.get('unarmed_option')) or any(row.get('type') == 'attack' and row.get('attack_kind') == 'unarmed'
                                                  for row in typed.get('effects', []))


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
        from . import any_false
        if weapon_allowed(engine, actor, action) is False or wheel_integration_allowed(engine, actor, None, action) is False:
            continue  # Granted attacks retain profile, ammunition and readiness admission.
        form = 'Unarmed' if (action.parameters.get('typed') or {}).get('unarmed_option') else form_for(engine, actor, action)
        if form is None or (not_form is not None and form == not_form) or (unarmed_only and not unarmed_operation(action)):
            continue
        for target in _reachable(engine, actor, action):
            from ..attack_declaration import can_target
            if can_target(engine, actor, target, action.source_definition_id, action=action):
                out[f"{action.source_definition_id}|{target.entity_id}"] = (action, target)
    return out


def eight_limb(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    action = engine.action_catalog.get(source_definition_id)
    if action is None or not actor.active or not attack_action(action) or engine.state.current_actor_id != actor.entity_id:
        return
    roles = _roles(engine, actor)
    record = _turn(actor, engine, "_round_hundred_forms")
    cost = 1 if _thousand(engine, actor) else 2
    intent = _intent(engine)
    if "eight_limb" in roles and record.get("last") and record.get("action_intent") == str(getattr(intent, "intent_id", "")) and not record.get("eight_used") and _hands(actor) >= cost:
        choices = _attack_choices(engine, actor, record.get("last"))
        if choices:
            from .needle import ask, checkpoint_id

            picked = ask(engine, intent, checkpoint_id(engine, "eight_limb", actor.entity_id), actor, "choice:needle.eight_limb_attack", list(choices),
                         labels={k: f"{a.display_name} against {t.display_name}" for k, (a, t) in choices.items()}, allow_decline=True,
                         automatic_options=known_attacks(engine, actor, choices),
                         target_id=actor.entity_id, name="Eight-Limb Battle Pattern",
                         prompt=f"Eight-Limb Battle Pattern: spend {cost} Battle Hand{'s' if cost > 1 else ''} for one more attack with a different Form?")
            if picked and picked[0] in choices:
                record["eight_used"] = True
                _spend(engine, actor, cost, PREFIX + "eight_limb_battle_pattern")
                attack, target = choices[picked[0]]
                _granted(engine, actor, attack, target, intent, part_of_attack_action=True)
    mandala(engine, actor, intent)


@hook("attack_resolved", priority=20)
def eight_limb_checkpoint(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if ctx.typed.get("granted_attack"):
        return
    eight_limb(ctx.engine, ctx.actor, ctx.action.economy, ctx.action.source_definition_id)


# -------------------------------------------------------------------------------------------------- Mandala Completion
def mandala(engine: Any, actor: Any, intent: Any) -> None:
    """Thousand-Hand Incarnation: once per turn after at least 4 Hands were spent this turn (asked)."""
    if not actor.active or not _thousand(engine, actor):
        return
    record = _turn(actor, engine, "_round_hands_spent")
    if int(record.get("spent") or 0) < 4 or record.get("mandala_offered"):
        return
    record["mandala_offered"] = True
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from ..typed_reactions import triggered_context

    labels = {"strike": "Make one additional unarmed strike", "guard": "+3 AC until your next turn",
              "move": "Move up to your Speed without provoking", "double": "Apply two different Eight-Limb Completion Effects"}
    picked = ask(engine, intent, checkpoint_id(engine, "mandala", actor.entity_id), actor, "choice:needle.mandala_completion", list(labels),
                 labels=labels, allow_decline=True, target_id=actor.entity_id, name="Mandala Completion",
                 prompt="Mandala Completion: you have spent 4 Battle Hands this turn. Choose one.")
    choice = picked[0] if picked else None
    if choice is None:
        return
    record["mandala_used"] = True
    ctx = triggered_context(engine, actor, actor, {"feature_id": PREFIX + "thousand_hand_incarnation",
        "name": "Mandala Completion", "numbers": {"pb": _pb(engine, actor)}}, intent)
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
                       automatic_options=known_attacks(engine, actor, choices),
                       prompt="Mandala Completion: your additional unarmed strike.")
            if pick and pick[0] in choices:
                _granted(engine, actor, *choices[pick[0]], intent, mandala_strike=True)


@effect("hundred_hands_fill")
def thousand_hands_fill(ctx: Any, row: dict[str, Any]) -> None:
    """"Current and maximum Battle Hands immediately become 2 x Proficiency Bonus"."""
    if HANDS in ctx.actor.resources:
        from .states import active
        incarnation = active(ctx.engine, ctx.actor, STATE)
        if incarnation is not None:
            from .retained_updates import record_instance_update
            incarnation.data["hundred_hand_extra_after_turn"] = int(ctx.actor.turns_started) + 1
            incarnation.data["hundred_hand_extra_granted_round"] = 0
            incarnation.data["numbers"] = {"cl": body_level(ctx.engine, ctx.actor), "pb": _pb(ctx.engine, ctx.actor)}
            record_instance_update(ctx.engine, ctx.actor, "condition", incarnation.instance_id, incarnation)
        ctx.engine._set_resource_maximum(ctx.actor, HANDS, 2 * _pb(ctx.engine, ctx.actor), PREFIX + "thousand_hand_incarnation")
        _set_hands(ctx.engine, ctx.actor, maximum(ctx.engine, ctx.actor), PREFIX + "thousand_hand_incarnation")


@hook("effect_expiring")
def thousand_hands_end(engine: Any, holder: Any, row: Any) -> None:
    """"Ending ... returns maximum Hands to Proficiency Bonus and removes current Hands above that maximum"."""
    from .states import PREFIX as STATE_PREFIX

    if getattr(row, "condition_id", None) == STATE_PREFIX + STATE:
        engine._set_resource_maximum(holder, HANDS, _pb(engine, holder), "system:battle_hands_clamp")
        if _hands(holder) > _pb(engine, holder):
            _set_hands(engine, holder, _pb(engine, holder), "system:battle_hands_clamp")


# --------------------------------------------------------------------------------------------- Circle of Uncounted Arms
@effect("circle_hand")
def circle_hand(ctx: Any, row: dict[str, Any]) -> None:
    """Declaration marker retained for saved bundles; native checkpoints own delivery."""
    return None


@hook("hit_response")
def circle_turns_the_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = attacker.turn_flags.get("_circle_against")
    if not isinstance(held, dict) or held.get("target") != target.entity_id or held.get("source") not in (None, spec.get("source_definition_id")):
        return None
    attacker.turn_flags.pop("_circle_against", None)
    from ..critical_attacks import hits
    if hits(natural, total, effective_ac + int(held.get("amount") or 0), int(spec.get("critical_threshold") or 20)):
        return None
    by = engine.state.actors.get(str(held.get("by") or ""))
    note(engine, PREFIX + "circle_of_uncounted_arms", by or attacker, f"Circle of Uncounted Arms ({held.get('hand')}): the attack on {target.display_name} misses.", (attacker,))
    return effective_ac + int(held.get("amount") or 0), False


@hook("attack_resolved")
def circle_clears(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """The Circle answer lasts for the triggering attack only."""
    if "_circle_against" in ctx.actor.turn_flags:
        ctx.actor.turn_flags.pop("_circle_against", None)


def four_hand_opening(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Non-hit operations remain available even when every attack will miss."""
    if not _four_hand_ready(engine, actor, action):
        return
    from .needle import ask, checkpoint_id
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
    from ..typed_reactions import triggered_context
    ctx = triggered_context(engine, actor, actor, {"feature_id": PREFIX + "four_hand_sequence",
                            "name": "Four-Hand Sequence", "numbers": {"pb": _pb(engine, actor)}}, intent)
    if picked[0] == "move":
        move(_sub(ctx, [actor], feature=PREFIX + 'four_hand_sequence'), actor, 5, "choice:needle.four_hand_move", "Four-Hand Sequence")
    elif picked[0] == "ac":
        te.run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": 1, "source_owned": True,
                              "duration": "until_start_of_your_next_turn"}])
    else:
        current = equipment_pairs(engine, actor).get(picked[0])
        for weapon, held in (current[0] if current and current[0] == choices[picked[0]][0] else []):
            set_weapon_readiness(engine, actor, weapon, held, source=PREFIX + "four_hand_sequence", source_actor_id=actor.entity_id)
    mandala(engine, actor, intent)


@hook("effect_resolution_scope")
def four_hand_attack_scope(ctx: Any, row: dict[str, Any]):
    """Open during the paid Attack action, before each actual attack block."""
    primary_attack = row.get('type') == 'attack' or (row.get('type') == 'save' and ctx.typed.get('unarmed_option'))
    if not primary_attack or not _four_hand_ready(ctx.engine, ctx.actor, ctx.action):
        return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        four_hand_opening(ctx.engine, ctx.actor, ctx.action, None, ctx.intent)
        yield
    return scope()


def equipment_pairs(engine: Any, actor: Any) -> dict[str, Any]:
    """Two owned physical items, validated together against actual hand occupancy.

    Uses the shared possession/readiness producer; neither grants items nor changes
    the ordinary object interaction. Stowing is evaluated before drawing.
    """
    from itertools import combinations
    from .hand_occupancy import weapon_grips, occupancy, hand_parts, resting_hands
    from .weapon_hits import available_weapons
    ready = weapon_grips(engine, actor)
    available = {key: action for key, action in available_weapons(engine, actor, include_busy=True).items()
                 if ".weapon." in key and (action.parameters.get("typed") or {}).get("weapon")}
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
        if sum(len(parts) for parts in occupied.values()) > len(hand_parts(engine, actor)) or any(part not in hand_parts(engine, actor) for part in occupied):
            continue
        key = "equipment|" + "|".join(pair)
        ordered = sorted(changes, key=lambda value: value[1])
        label = "; ".join(("Draw " if held else "Stow ") + available[item].display_name.removesuffix(" attack") for item, held in ordered)
        options[key] = (ordered, label)
    return options


CIRCLE = PREFIX + "circle_of_uncounted_arms"


def circle_record(engine: Any, actor: Any, *, create: bool = True) -> dict[str, Any]:
    """Round-scoped family record; turn identities survive cold reload."""
    key = "_round_circle_uses"
    held = actor.turn_flags.get(key)
    if not isinstance(held, dict) or held.get("round") != engine.state.round_number:
        held = {"round": engine.state.round_number, "turns": []}
        if create:
            actor.turn_flags[key] = held
    return held


@hook("row_allowed")
def circle_native_only(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != CIRCLE:
        return None
    if row.get("native_checkpoint") != "CIRCLE_DECLARED":
        return False
    record = circle_record(engine, actor, create=False)
    limit = 2 if _thousand(engine, actor) else 1
    return len(record["turns"]) < limit and _stamp(engine) not in record["turns"]


def circle_reach(engine: Any, actor: Any) -> int:
    from ..attack_reach import maximum as attack_maximum, melee
    from .hand_occupancy import weapon_allowed
    from .reach_bonus import current_reach
    return max([5] + [attack_maximum(engine, actor, action, base=current_reach(engine, actor, action))
                     for action in engine.action_catalog.values() if action.owner_id == actor.entity_id
                     and melee(action) and form_for(engine, actor, action) and not action.parameters.get('reach_bonus')
                     and weapon_allowed(engine, actor, action) is not False])


def circle_offer(engine: Any, other: Any, source: str, intent: Any, *, attack_target: Any = None,
                 movement: bool = False, trigger_name: str = "", attack_roll: bool = False, granted_trigger: bool = False) -> bool:
    """Answer one committed activation before its roll, save or first willing step.

    Returns True only when Seizing Hand stopped this activation's movement.
    Admission/payment use the public reaction contract and actual owned bundle.
    """
    from ..typed_reactions import checkpoint_response, commit_checkpoint_response, publish_reaction_used
    from .needle import ask, checkpoint_id
    from .states import context
    from .grapple_attempts import attempt, options as grapple_options
    from .. import typed_executor as te
    from ..target_knowledge import located
    from ..relations import relation, ENEMY
    stopped = False
    for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if actor is other or relation(engine, actor, other) != ENEMY or not actor.active or not other.active:
            continue
        if engine._distance_actor_to_actor(actor, other) > circle_reach(engine, actor):
            continue
        row = checkpoint_response(engine, actor, other, other, CIRCLE, "CIRCLE_DECLARED")
        if row is None:
            continue
        activation_actor = getattr(intent, 'actor_id', None)
        root = getattr(engine, '_active_action_source_id', source) if activation_actor == other.entity_id else source
        identity = f"{getattr(intent, 'intent_id', '')}:{other.entity_id}:{root}"
        seen = _turn(actor, engine, '_round_circle_activations').setdefault('seen', [])
        if identity in seen:
            continue
        seen.append(identity)
        choices = {key: value for key, value in _attack_choices(engine, actor, None).items() if value[1] is other
                   and not (value[0].parameters.get("typed") or {}).get("range_ft")}
        unarmed = {key: value for key, value in choices.items() if unarmed_operation(value[0])}
        labels = {}
        if choices and not granted_trigger:
            labels["intercept"] = f"Intercepting Hand: attack {other.display_name}; a hit subtracts {_pb(engine, actor)} from its triggering attack roll or Cultivation Check"
        from ..attack_declaration import can_target
        from . import any_false
        if not granted_trigger and any(can_target(engine, actor, other, action.source_definition_id, action=action)
               for action in grapple_options(engine, actor, ("grapple",)).values()):
            labels["seize"] = f"Seizing Hand: Grapple {other.display_name}; success stops this activation's movement"
        if attack_roll:
            labels["deflect"] = "Deflecting Hand: +3 AC against this triggering attack"
        if unarmed and not granted_trigger:
            labels["silence"] = f"Silencing Hand: unarmed strike against {other.display_name}; a hit prevents Reactions until the start of its next turn"
        picked = ask(engine, intent, checkpoint_id(engine, "circle_declared", other.entity_id), actor,
                     "choice:needle.circle_of_uncounted_arms", list(labels), labels=labels, allow_decline=True,
                     name="Circle of Uncounted Arms", feature_id=CIRCLE,
                     automatic_options=list(labels) if located(engine, actor, other) else [],
                     prompt=f"{other.display_name} commits to {trigger_name or source}. Spend your Reaction and 2 Battle Hands?",
                     prompt_context={"cost": "Reaction and 2 Battle Hands", "paying_pool": HANDS})
        if not picked or picked[0] not in labels:
            continue
        # Reserve before a nested counterattack can open another declaration.
        commit_checkpoint_response(engine, actor, other, row, "CIRCLE_DECLARED")
        circle_record(engine, actor)["turns"].append(_stamp(engine))
        publish_reaction_used(engine, actor, {**row, "target_ids": (other.entity_id,)})
        mandala(engine, actor, intent)
        hand = picked[0]
        if hand == "deflect":
            other.turn_flags["_circle_against"] = {"target": actor.entity_id, "amount": 3, "hand": "Deflecting Hand", "by": actor.entity_id, "source": source}
        elif hand == "seize":
            attempt(engine, actor, other, intent, ("grapple",), choice_id="choice:needle.circle_seize", prompt="", numbers=current_numbers(engine, actor,
                (next(iter(grapple_options(engine, actor, ("grapple",)).values())).parameters.get('typed') or {})))
            if movement and any(c.condition_id.endswith("grappled") and c.source_actor_id == actor.entity_id for c in other.conditions.values()):
                stopped = True
        else:
            available = unarmed if hand == "silence" else choices
            chosen = ask(engine, intent, checkpoint_id(engine, "circle_strike", other.entity_id), actor,
                         "choice:needle.circle_strike", list(available), labels={key: action.display_name for key, (action, _) in available.items()},
                         automatic_options=known_attacks(engine, actor, available),
                         name="Circle of Uncounted Arms", prompt=f"Choose one attack against {other.display_name}.")
            if chosen and chosen[0] in available:
                action, target = available[chosen[0]]
                _granted(engine, actor, action, target, intent,
                         on_hit=[{"type": "circle_native_hit", "hand": hand, "trigger_source": source, "subtract_roll": True}])
        mandala(engine, actor, intent)
    return stopped


@effect("circle_native_hit")
def circle_native_hit(ctx: Any, row: dict[str, Any]) -> None:
    if row["hand"] == "silence":
        from .. import typed_executor as te
        te.run_effects(_sub(ctx, [ctx.target], feature=CIRCLE), [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif row.get('subtract_roll'):
        ctx.target.turn_flags["_circle_roll_penalty"] = {"source": row["trigger_source"], "amount": _pb(ctx.engine, ctx.actor), "by": ctx.actor.entity_id}


@hook("d20_bonus", priority=90)
def circle_roll_penalty(engine: Any, roll: Any, intent: Any) -> Any:
    context = engine.d20_context(roll)
    if not context or (context.get("kind") != "attack" and not (context.get("kind") == "check" and context.get("check_kind") == "cultivation")):
        return None
    actor = engine.state.actors.get(context.get("actor_id"))
    held = actor.turn_flags.get("_circle_roll_penalty") if actor is not None else None
    from .ability_source import mechanic_at
    source = context.get('source_id')
    matches = held and (held['source'] == source or
        (mechanic_at(engine, held['source']) or held['source']) == (mechanic_at(engine, source) or source))
    if matches:
        actor.turn_flags.pop("_circle_roll_penalty", None)
        return {"source_id": CIRCLE, "user_id": held["by"], "bonus": -held["amount"]}
    return None


@hook("technique_declared", priority=10)
def circle_declaration(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> dict[str, Any] | None:
    typed = action.parameters.get("typed") or {}
    effects = list(typed.get("effects") or [])
    def contains(rows, predicate):
        return any(isinstance(row, dict) and (predicate(row) or any(contains(row.get(key) or [], predicate)
                   for key in ('effects', 'on_hit', 'on_fail', 'on_success', 'on_failure', 'on_success_by_5')))
                   for row in rows)
    physical = contains(effects, lambda row: row.get('type') == 'save'
                        and str(row.get('ability') or '').upper()[:3] in ('STR', 'DEX', 'CON'))
    attacks = contains(effects, lambda row: row.get('type') == 'attack') or str(action.resolution_kind) == 'ATTACK'
    maneuver = typed.get("unarmed_option") in ("grapple", "shove_push", "shove_prone")
    moving = action.resolution_kind in ("DASH", "DISENGAGE")
    if not (attacks or physical or maneuver or moving):
        return None
    target = engine.state.actors.get(next(iter(candidate.target_ids), "")) if attacks else None
    stopped = circle_offer(engine, actor, action.source_definition_id, intent, attack_target=target, movement=moving or maneuver, trigger_name=action.display_name, attack_roll=attacks, granted_trigger=bool(typed.get('granted_attack')))
    if stopped:
        return {"source_id": CIRCLE, "label": "Seizing Hand stops the triggering movement", "movement_cap_ft": 0, "forced_cap_ft": 0}
    return None


@hook("movement_attempt", priority=-10)
def circle_movement(engine: Any, actor: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    from ..movement_steps import context
    if context(engine, actor).get("forced") or engine.grid.distance_ft(previous, nxt) < 5:
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
    forms = {form_for(engine, actor, action) for action in engine.action_catalog.values()
             if action.owner_id == actor.entity_id and attack_action(action)
             and not (action.parameters.get('typed') or {}).get('unarmed_option')
             and weapon_allowed(engine, actor, action) is not False
             and any(row.get("type") == "attack" for row in (action.parameters.get("typed") or {}).get("effects") or [])}
    forms.discard(None)
    return len(forms) >= 2


@hook("candidate_allowed")
def wheel_integration_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or "weapon_wheel" not in _roles(engine, actor):
        return None
    if (action.parameters.get('typed') or {}).get('unarmed_option'):
        return None  # A replacement Grapple/Shove is Unarmed, not the attached weapon profile.
    ready = wheel_ready(engine, actor)
    if any(tag in action.source_definition_id for tag in ("#integrated_con", "#mandala_con")):
        return None if ready else False
    from .integrated_weapons import in_group
    if ready and in_group(action.parameters.get("typed") or {}, "one_handed_melee"):
        return False  # Constitution replaces Strength/Dexterity; CAM remains optional.
    return None


@hook("compile_actions")
def wheel_constitution_attack(info: dict[str, Any]) -> list[Any]:
    """Ordinary Constitution attack beside the optional Cultivation modifier."""
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
        variant["numbers"]["key_mod"] = con
        variant["weapon"]["damage"]["modifier"] += con - old
        variant["weapon"]["ability_modifier"] = con
        variant["weapon"]["ability"] = 'CON'
        out.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "#mandala_con",
            "display_name": action.display_name + " (Constitution and weapon proficiency)",
            "parameters": {**action.parameters, "typed": variant}}))
    return out


@hook("after_miss")
def four_hand_after_miss(ctx: Any, target: Any) -> None:
    """A missed attack does not remove the non-roll operations from this action."""
    four_hand_opening(ctx.engine, ctx.actor, ctx.action, None, ctx.intent)


@hook("damage_packet_selection", priority=-20)
def record_confirmed_form_hit(ctx: Any, target: Any, packet_kinds: Any) -> None:
    """Derive hit totals from native confirmed-roll provenance before nested riders.

    A later granted strike sees this triggering hit already counted. Roll ids
    prevent mixed deliveries from creating a second hit for the same attack.
    """
    engine, actor = ctx.engine, ctx.actor
    if not (_roles(engine, actor) or _thousand(engine, actor)):
        return
    provenance = ctx.attack_damage_context
    if target is None or provenance is None:
        return
    record = _turn(actor, engine, "_round_hundred_forms")
    seen = record.setdefault("confirmed_rolls", [])
    if provenance.roll_id in seen:
        return
    seen.append(provenance.roll_id)
    form = form_for(engine, actor, ctx.action)
    if form:
        forms = record.setdefault("hit_forms", [])
        new_form = form not in forms
        previous_hit = record.get('last_hit_form')
        if new_form:
            forms.append(form)
        targets = record.setdefault('form_targets', {}).setdefault(form, [])
        if target.entity_id not in targets:
            targets.append(target.entity_id)
        if len(forms) >= 3 and (new_form or previous_hit is not None and form != previous_hit):
            record.setdefault('completion_rolls', []).append(provenance.roll_id)
        record['last_hit_form'] = form
        if engine.state.current_actor_id == actor.entity_id and "weapon_wheel" in _roles(engine, actor) and wheel_ready(engine, actor):
            if record.get("first") and form != record["first"]:
                record["wheel_used"] = True
            record.setdefault("first", form)
    struck = record.setdefault("struck", {})
    struck[target.entity_id] = int(struck.get(target.entity_id) or 0) + 1


@hook("compile_actions")
def weapon_wheel_sequence_action(info: dict[str, Any]) -> list[Any]:
    """One native Attack action with the normal number of attacks and live gear choices.

    The profile/attack count comes from the owner's ordinary compiled attacks.
    It grants no proficiency, gear, additional attacks or object interactions.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    roles = {row.get('role') for mid in info['owned_ids'] for row in (info['mechanics'].get(mid) or {}).get('effects', [])
             if row.get('kind') == 'hundred_hands'}
    if not roles.intersection({'four_hand', 'weapon_wheel'}):
        return []
    counts = [int(effect.get('count') or 1) for action in info['actions'] if attack_action(action)
              and '#' not in action.source_definition_id and not action.costs
              and re.search(r'\.(?:natural|weapon|improvised)\.', action.source_definition_id)
              for effect in (action.parameters.get('typed') or {}).get('effects') or []
              if effect.get('type') == 'attack' and type(effect.get('count', 1)) is int]
    if not counts:
        return []
    out = []
    for role, feature, name in (('four_hand', 'four_hand_sequence', 'Attack: Battle Hand sequence'),
                               ('weapon_wheel', 'weapon_wheel_body', 'Weapon-Wheel Body: Attack with weapon choices')):
        if role not in roles:
            continue
        out.append(ActionDefinition(source_definition_id=PREFIX + feature + '#sequence:' + info['short'],
            owner_id=info['actor_id'], display_name=name, economy=EconomyKind.ACTION,
            resolution_kind='TYPED', target_kind='SELF', parameters={'expected_damage': 0,
                'description': 'Take the ordinary Attack action. Choose any legal Four-Hand operation, then an attack and creature. Normal attack count, possession and hand limits apply.',
                'hundred_hand_sequence_role': role,
                'typed': {'source': PREFIX + feature, 'attack_action': True, 'numbers': info['numbers'],
                          'effects': [{'type': 'weapon_wheel_sequence', 'count': max(counts), 'gear_choices': role == 'weapon_wheel'}]}}))
    return out


def _gear_allowed(engine: Any, actor: Any, action: Any) -> bool:
    from ..gate2_runtime_models import CandidateKind
    from . import any_false
    candidate = engine._candidate(CandidateKind.ACTION, actor, action.source_definition_id, action.display_name)
    return not any_false("candidate_allowed", engine, actor, candidate, action)


@effect("weapon_wheel_sequence")
def weapon_wheel_sequence(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .equipment_hands import set_weapon_readiness
    from .hand_occupancy import hand_parts
    from .. import typed_executor as te
    from . import any_false
    engine, actor = ctx.engine, ctx.actor
    if not _roles(engine, actor).intersection({'four_hand', 'weapon_wheel'}):
        return
    for index in range(int(row["count"])):
        if not actor.active or engine.state.terminal_result is not None:
            break
        # A switch can stow the held weapons and draw one replacement. Every
        # intermediate change uses the ordinary public readiness admission.
        four_hand_opening(engine, actor, ctx.action, None, ctx.intent)
        changed = set()
        for _ in range(len(hand_parts(engine, actor)) + 1 if row.get('gear_choices') and 'weapon_wheel' in _roles(engine, actor) else 0):
            gear = {action.source_definition_id: action for action in engine.action_catalog.values()
                    if action.owner_id == actor.entity_id and action.parameters.get("equipment_grip")
                    and action.source_definition_id not in changed
                    and _gear_allowed(engine, actor, action)}
            if not gear:
                break
            picked = ask(engine, ctx.intent, checkpoint_id(engine, "wheel_gear", actor.entity_id), actor,
                         "choice:needle.weapon_wheel_gear", ["keep", *sorted(gear)],
                         labels={"keep": "Keep the current weapons and choose this attack", **{key: action.display_name for key, action in gear.items()}},
                         preferred=["keep"], name="Weapon-Wheel Body",
                         prompt=f"{actor.display_name}, attack {index + 1}: draw or switch weapons without spending an object interaction.")
            if not picked or picked[0] == "keep":
                break
            selected = gear.get(picked[0])
            if selected is None:
                raise ValueError("Choose an available carried weapon")
            grip = selected.parameters["equipment_grip"]
            set_weapon_readiness(engine, actor, grip["weapon"], bool(grip["held"]),
                                 source=PREFIX + "weapon_wheel_body", source_actor_id=actor.entity_id)
            changed.add(selected.source_definition_id)
        choices = _attack_choices(engine, actor, None)
        if not choices:
            break
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "wheel_attack", actor.entity_id), actor,
                     "choice:needle.weapon_wheel_attack", list(choices),
                     labels={key: action.display_name + " against " + target.display_name for key, (action, target) in choices.items()},
                     allow_decline=True, name=ctx.action.display_name, automatic_options=known_attacks(engine, actor, choices), prompt=f"{actor.display_name}, choose attack {index + 1} and its creature.")
        if not picked:
            break
        if picked[0] not in choices:
            raise ValueError("Choose a legal readied attack and target")
        action, target = choices[picked[0]]
        typed = dict(action.parameters["typed"])
        maneuver = bool(typed.get('unarmed_option'))
        attack = next(dict(effect) for effect in typed['effects'] if effect.get('type') == ('save' if maneuver else 'attack'))
        if not maneuver:
            attack['count'] = 1
        profile = {**typed, "numbers": current_numbers(engine, actor, typed) if maneuver else typed.get('numbers', {}),
                   "effects": [attack], "attack_action": True}
        updates = {'parameters': {**action.parameters, 'typed': profile}}
        if maneuver:
            from ..attack_reach import maximum
            updates['range_ft'] = maximum(engine, actor, action, base=action.range_ft or 5)
        selected = action.model_copy(update=updates)
        te.run_effects(te.Context(engine, actor, selected, ctx.intent, profile, [target], target, {}), [attack])


FORM_SOURCE = "tianxia.subpath.body.hundred_hand_battle_mandala"
FORM_NAMES = ("Unarmed", "Blade", "Hafted", "Polearm", "Flexible", "Thrown", "Shield")


def recorded_form_item(engine: Any, actor: Any, action: Any):
    """Find this actual physical weapon in the shared stable item ledger."""
    from ..acquisition_inventory import read
    from ..weapon_delivery import weapon_identity
    identity = action.parameters.get('requires_held_weapon') or weapon_identity(engine, action.source_definition_id, action.parameters.get('typed') or {}, action.parameters, owner_id=actor.entity_id)
    for holder in engine.state.actors.values():
        for uid, item in read(holder).items():
            if identity in item.get('weapon_actions', []):
                return holder, uid, item
    return None


def form_scope(engine: Any, actor: Any, action: Any) -> str:
    """Stable native item UID wins over a rebound action slot after acquisition."""
    item = recorded_form_item(engine, actor, action)
    if item:
        return 'item:' + item[1]
    from .weapon_hits import physical_weapon_id
    return physical_weapon_id(action.source_definition_id, action.parameters)


def form_record(engine: Any, actor: Any, action: Any) -> str | None:
    """Private, immutable owner declaration for an otherwise ambiguous item.

    The generic admission owner supplies validation, authority, hidden condition
    storage and replay commitments. Native physical identity scopes this record
    across attack modes; choosing another mode never chooses another Form.
    """
    item = recorded_form_item(engine, actor, action)
    if item:
        value = item[2]['profile'].get('facts', {}).get('weapon_form')
        if value in FORM_NAMES:
            return value
    from ..fact_consent_admission import combat_records
    scope = form_scope(engine, actor, action)
    records = combat_records(engine, actor, source=FORM_SOURCE, kind="weapon_form", scope=scope)
    return next((record["value"] for record in reversed(records) if record["value"] in FORM_NAMES), None)


def form_for(engine: Any, actor: Any, action: Any) -> str | None:
    return form_record(engine, actor, action) or form_of(action)


def admit_weapon_form(ctx: Any, weapon: Any) -> None:
    """One explicit controller input before first use; no AI inference from names."""
    from ..fact_consent_admission import admit_choice
    from .weapon_hits import available_weapons, physical_weapon_id
    identity = physical_weapon_id(weapon.source_definition_id, weapon.parameters)
    if form_of(weapon) or form_record(ctx.engine, ctx.actor, weapon):
        return
    if identity not in available_weapons(ctx.engine, ctx.actor, include_busy=True):
        raise ValueError("Record a Form only for a weapon you possess")
    record = admit_choice(ctx, ctx.actor, FORM_SOURCE, "weapon_form", form_scope(ctx.engine, ctx.actor, weapon), [form for form in FORM_NAMES if form not in ("Unarmed", "Shield")],
                 labels={form: form for form in FORM_NAMES},
                 prompt=f"{ctx.actor.display_name}: choose the single recorded Weapon Form for {weapon.display_name.removesuffix(' attack')}. It stays fixed across attacks and weapon modes.",
                 expires_on="UNTIL_REMOVED", readers=(), automatic_options=())
    item = recorded_form_item(ctx.engine, ctx.actor, weapon)
    if record and item:
        from ..acquisition_inventory import read, write
        holder, uid, _ = item
        inventory = read(holder)
        inventory[uid]['profile']['facts']['weapon_form'] = record['value']
        write(ctx.engine, holder, inventory, FORM_SOURCE)


@hook("compile_actions")
def weapon_form_record_actions(info: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from hashlib import sha256
    owned = any(mid.startswith(PREFIX) for mid in info["owned_ids"])
    if not owned:
        return []
    out = []
    for weapon in info["actions"]:
        if "#" in weapon.source_definition_id or not (weapon.parameters.get("typed") or {}).get("weapon") or form_of(weapon):
            continue
        out.append(ActionDefinition(source_definition_id="action:typed." + info["short"] + ".mandala_form." + sha256(weapon.source_definition_id.encode()).hexdigest()[:12],
            owner_id=info["actor_id"], display_name="Record Weapon Form: " + weapon.display_name.removesuffix(" attack"),
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "player_only": True, "mandala_form_weapon": weapon.source_definition_id,
                "description": "Choose one fixed Weapon Form for this ambiguous weapon before using it with Hundred-Hand Battle Mandala. Costs no Action or resource. The declaration remains private to its owner and lasts until removed.",
                "typed": {"source": FORM_SOURCE, "manual_inline_choice": True, "numbers": info["numbers"],
                          "effects": [{"type": "hundred_hand_form_record", "weapon": weapon.source_definition_id}]}}))
    return out


@effect("hundred_hand_form_record")
def record_weapon_form(ctx: Any, row: dict[str, Any]) -> None:
    if not (_roles(ctx.engine, ctx.actor) or _thousand(ctx.engine, ctx.actor)):
        return
    weapon = ctx.engine.action_catalog.get(row["weapon"])
    if weapon is None or weapon.owner_id != ctx.actor.entity_id:
        raise ValueError("Record a Form only for your own weapon")
    admit_weapon_form(ctx, weapon)


@hook("candidate_allowed")
def form_record_action_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    identity = action.parameters.get("mandala_form_weapon") if action is not None else None
    if not identity:
        return None
    from .weapon_hits import available_weapons
    weapon = engine.action_catalog.get(identity)
    return bool(weapon and identity in available_weapons(engine, actor, include_busy=True) and form_for(engine, actor, weapon) is None)


@hook("settings_batch_key")
def form_record_batch_key(action: Any) -> str | None:
    identity = action.parameters.get("mandala_form_weapon")
    return "hundred_hand_form:" + identity if identity else None


@hook("technique_declared", priority=-20)
def form_before_first_attack(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    if not (_roles(engine, actor) or _thousand(engine, actor)) or not (action.parameters.get("typed") or {}).get("weapon"):
        return
    if form_for(engine, actor, action) is not None:
        return
    from .. import typed_executor as te
    ctx = te.Context(engine, actor, action, intent, dict(action.parameters["typed"]), [actor], actor, {})
    admit_weapon_form(ctx, action)


@hook("choice_reactors")
def hundred_hand_manual_choices(engine: Any) -> list[str]:
    """Enroll possible manual holders during AI turns; actual triggers still gate."""
    return [actor.entity_id for actor in engine.state.actors.values()
            if _roles(engine, actor) or any(row.get("feature_id") == CIRCLE
                for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, []))]


@hook("row_allowed", priority=-100)
def hundred_hand_source_access(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = str(row.get('feature_id') or '')
    if feature.startswith(PREFIX):
        minimum = LEVELS.get(feature[len(PREFIX):])
        if minimum is not None and body_level(engine, actor) < minimum:
            return False
    return None


@hook("candidate_allowed", priority=-100)
def hundred_hand_action_access(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    source = str(typed.get('option_of') or typed.get('source') or '')
    minimum = LEVELS.get(source.removeprefix(PREFIX)) if source.startswith(PREFIX) else None
    if minimum is not None and body_level(engine, actor) < minimum:
        return False
    return None


@hook("compile_bundle")
def seal_body_attainment(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    from copy import deepcopy
    if not any(str(row.get('feature_id') or '').startswith(PREFIX) for row in bundle.get('typed_passives', [])):
        return None
    paths = info['owner_sheet'].get('path_and_subpath') or {}
    declared = next((row for row in paths.get('paths', []) if row.get('path_id') == BODY), {})
    attained = next((declared[key] for key in ('attained_cl', 'attainment', 'owning_path_level') if key in declared), bundle.get('cl', 0))
    if type(attained) is not int or not 0 <= attained <= int(bundle.get('cl') or 0):
        raise ValueError('Hundred-Hand requires bounded committed Body attainment')
    result = deepcopy(bundle)
    result['hundred_hand_profile'] = {'body_cl': attained}
    if any(row.get('kind') == 'hundred_hands' and row.get('role') == 'weapon_wheel' for row in result.get('typed_passives', [])):
        con = int(info['numbers'].get('con_mod', 0))
        key = int(info['numbers'].get('key_mod', 0))
        explicit = info['owner_sheet']['ability_scores_and_statistics'].get('technique_attack_bonus')
        for action in result['action_catalog']:
            if '#integrated_con' not in action['source_definition_id']:
                continue
            typed = action['parameters']['typed']
            typed['numbers']['attack_bonus'] = (int(info['numbers']['attack_bonus']) + con - key
                if explicit else int(info['numbers']['pb']) + con)
            typed['numbers']['key_mod'] = con
            typed['weapon']['ability'] = 'CON'
            typed['weapon']['ability_modifier'] = con
            text = 'This profile uses your Body Refining Cultivation Attack Modifier for the attack roll and Constitution for damage. It grants no proficiency or extra attack.'
            action['parameters']['description'] = str(action['parameters'].get('description') or '') + ' ' + text
    for row in result.get('typed_reactions', []):
        if row.get('feature_id') == CIRCLE:
            # The replacement checkpoint validates current native melee reach.
            # A generic synthetic reaction action has no weapon attack profile.
            row['source_within_reach'] = False
    if any((action.get('parameters', {}).get('typed') or {}).get('source') == PREFIX + 'thousand_hand_incarnation'
           for action in result['action_catalog']):
        unarmed = next((action['source_definition_id'] for action in result['action_catalog']
                        if '.natural.' in action['source_definition_id'] and not (action['parameters'].get('typed') or {}).get('weapon')), None)
        if unarmed:
            for action in result['action_catalog']:
                if (action.get('parameters', {}).get('typed') or {}).get('unarmed_option'):
                    action['parameters']['range_from_action'] = unarmed

    return result


@hook("damage_packet_selection", priority=-10)
def incarnation_force_selection(ctx: Any, target: Any, packet_kinds: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _thousand(engine, actor) or ctx.attack_damage_context is None:
        return
    record = _turn(actor, engine, '_round_hundred_forms')
    if record.get('force_used') or int(record.get('struck', {}).get(target.entity_id, 0)) < 3:
        return
    from .needle import ask, checkpoint_id
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'incarnation_force', target.entity_id), actor,
        'choice:needle.incarnation_force', ['damage'], labels={'damage': 'Add 5d8 Force damage to this hit'},
        allow_decline=True, feature_id=PREFIX + 'thousand_hand_incarnation', name='Thousand-Hand Incarnation',
        prompt=f"{actor.display_name} has hit {target.display_name} at least three times this turn. Add 5d8 Force once this turn, or keep it for a later hit?")
    if picked:
        record['force_used'] = True
        record['force_pending'] = {'roll': ctx.attack_damage_context.roll_id, 'target': target.entity_id}


@hook("attack_damage_final")
def incarnation_force_packet(engine: Any, actor: Any, target: Any, attack_context: Any, intent: Any) -> None:
    record = actor.turn_flags.get('_round_hundred_forms') or {}
    pending = record.get('force_pending')
    if not pending or pending['roll'] != attack_context.roll_id or pending['target'] != target.entity_id:
        return
    record.pop('force_pending', None)
    # This packet was attached at the confirmed hit. It completes even when
    # an earlier component defeats the recipient, and its dice never multiply.
    from ..typed_reactions import triggered_context
    from ..typed_executor import block_damage
    from dataclasses import replace
    ctx = triggered_context(engine, actor, target, {'feature_id': PREFIX + 'thousand_hand_incarnation',
        'name': 'Thousand-Hand Incarnation', 'numbers': {'pb': _pb(engine, actor)}}, intent)
    block_damage(replace(ctx, continue_after_defeat=True, critical_hit=False),
        {'type': 'damage', 'applies_to': 'target', 'dice': {'count': 5, 'sides': 8}, 'damage_types': ['force'],
         'evidence': 'Thousand-Hand Incarnation: add 5d8 Force to this confirmed third or later hit; no critical multiplication.'})


@hook("event", nested=True)
def reconcile_capacity(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or HANDS not in actor.resources:
        return
    if not any(str(r.get('feature_id') or '').startswith(PREFIX) for r in engine.typed_passive_rows.get(actor.entity_id, [])):
        return
    engine._set_resource_maximum(actor, HANDS, maximum(engine, actor), 'system:battle_hands_clamp')


def known_attacks(engine: Any, actor: Any, choices: dict[str, Any]) -> list[str]:
    """AI selects only currently located creatures in its own information."""
    from ..target_knowledge import located
    return [key for key, (action, target) in choices.items() if located(engine, actor, target)]


@hook("attack_resolution_scope")
def circle_native_attack_scope(engine: Any, actor: Any, target: Any, spec: dict[str, Any], intent: Any):
    from contextlib import contextmanager
    from ..technique_interception import frame
    source = str(spec.get('source_definition_id') or '')
    if not frame(engine, actor.entity_id, source):
        return None  # The resolver opens its native activation before reentering.
    @contextmanager
    def scope():
        circle_offer(engine, actor, source, intent, attack_target=target, attack_roll=True, trigger_name='attack',
                     granted_trigger=bool((spec.get('typed') or {}).get('granted_attack')))
        try:
            yield
        finally:
            actor.turn_flags.pop('_circle_roll_penalty', None)
            actor.turn_flags.pop('_circle_against', None)
    return scope()


@hook("effect_resolution_scope")
def circle_actual_physical_save(ctx: Any, row: dict[str, Any]):
    if row.get('type') != 'save' or str(row.get('ability') or '').upper()[:3] not in ('STR', 'DEX', 'CON'):
        return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        circle_offer(ctx.engine, ctx.actor, ctx.source, ctx.intent, trigger_name=ctx.action.display_name,
                     granted_trigger=bool(ctx.typed.get('granted_attack')))
        yield
    return scope()


@hook("attack_reach_bonus")
def incarnation_melee_reach(engine: Any, actor: Any, action: Any, opportunity: bool) -> dict[str, Any] | None:
    from .states import active
    if action.parameters.get('reach_bonus'):
        return None  # Saved historical menu variants already contain this increase.
    held = active(engine, actor, STATE) if _thousand(engine, actor) else None
    if held is None:
        return None
    return {'source_id': held.source_definition_id, 'condition_id': held.instance_id,
            'feet': 5, 'stacking_group': PREFIX + 'thousand_hand_incarnation'}


@hook('reaction_reach')
def circle_current_reach(engine: Any, actor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    if row.get('feature_id') == CIRCLE:
        return other is not None and engine._distance_actor_to_actor(actor, other) <= circle_reach(engine, actor)
    return None


@hook('save_effects_settled')
def unarmed_replacement_resolved(ctx: Any, target: Any, ability: str, failed: bool) -> None:
    """A Grapple/Shove is one Unarmed attack, with no invented hit receipt."""
    engine, actor = ctx.engine, ctx.actor
    if not ctx.typed.get('unarmed_option') or ctx.attack_damage_context is not None or not attack_action(ctx.action):
        return
    if engine.state.current_actor_id != actor.entity_id or not _roles(engine, actor):
        return
    record = _turn(actor, engine, '_round_hundred_forms')
    if 'weapon_wheel' in _roles(engine, actor) and wheel_ready(engine, actor):
        if record.get('first') not in (None, 'Unarmed'):
            record['wheel_used'] = True
        record.setdefault('first', 'Unarmed')
    record.update(last='Unarmed', action_intent=str(getattr(ctx.intent, 'intent_id', '')))
    if not ctx.typed.get('granted_attack'):
        eight_limb(engine, actor, ctx.action.economy, ctx.action.source_definition_id)


@hook('condition_state')
def incarnation_grapple_reach(ctx: Any, target: Any, effect: dict[str, Any]) -> dict[str, Any] | None:
    if effect.get('condition') != 'grappled' or not ctx.typed.get('unarmed_option') or not _thousand(ctx.engine, ctx.actor):
        return None
    from ..attack_reach import maximum
    bound = ctx.action.parameters.get('range_from_action')
    if not bound:
        return None
    return {'data': {'reach_ft': maximum(ctx.engine, ctx.actor, ctx.action, base=ctx.action.range_ft or 5),
                     'hundred_hand_reach_action': bound}}


@hook('event', nested=True)
def incarnation_hold_reach_changed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED'):
        return
    from ..attack_reach import maximum
    from .condition_ownership import remove_instance
    for target in engine.state.actors.values():
        for condition in list(target.conditions.values()):
            bound = condition.data.get('hundred_hand_reach_action')
            holder = engine.state.actors.get(condition.source_actor_id)
            action = engine.action_catalog.get(bound) if bound else None
            if holder is None or action is None:
                continue
            reach = maximum(engine, holder, action, base=action.range_ft or 5)
            if engine._distance_actor_to_actor(holder, target) > reach:
                remove_instance(engine, target, condition.instance_id, PREFIX + 'thousand_hand_incarnation')


@hook('candidate_allowed')
def sequence_progression_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.parameters.get('hundred_hand_sequence_role') == 'four_hand' and 'weapon_wheel' in _roles(engine, actor):
        return False
    return None


@hook('event', nested=True)
def reconcile_guard_dormancy(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Retain source-owned Guard instances and clocks while their Path is dormant.

    The native retained-update producer records numeric suspension/restoration;
    no new application, spend, expiry refresh or instance is created. Removing
    the underlying modifier also removes its saved value at the next boundary.
    """
    if event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED', 'MODIFIER_APPLIED', 'MODIFIER_REMOVED'):
        return
    from .retained_updates import record_instance_update
    for holder in engine.state.actors.values():
        stored = holder.turn_flags.get('_round_mandala_guard_values', {})
        for key in list(stored):
            if key not in holder.modifiers:
                stored.pop(key)
        for key, modifier in list(holder.modifiers.items()):
            if modifier.target_field != 'armor_class' or modifier.operation != 'ADD':
                continue
            source = modifier.source_definition_id
            minimum = LEVELS.get(source.removeprefix(PREFIX)) if source.startswith(PREFIX) else None
            owner = engine.state.actors.get(modifier.source_actor_id)
            if minimum is None or owner is None or not any(str(r.get('feature_id') or '').startswith(PREFIX)
                    for r in engine.typed_passive_rows.get(owner.entity_id, [])):
                continue
            if body_level(engine, owner) < minimum and key not in stored:
                holder.turn_flags['_round_mandala_guard_values'] = stored
                stored[key] = modifier.value
                modifier.value = 0
                record_instance_update(engine, holder, 'modifier', key, modifier)
            elif body_level(engine, owner) >= minimum and key in stored:
                modifier.value = stored.pop(key)
                record_instance_update(engine, holder, 'modifier', key, modifier)
