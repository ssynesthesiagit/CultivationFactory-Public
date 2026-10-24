"""Bojutsu's source-owned Staff progression and native consumers.

Acquisition reuses the public Subpath advancement journal. Wielding uses the
shared drawn-weapon contract; strike choices preserve both ordinary weapon and
Constitution profiles, including each strike of an Attack action and OAs.
Flowing Spin records an actual own-turn Staff Attack-action roll and grants one
paid strike. Sweeping Strike uses the resolved hit's paid save and legal forced
routes. Deflection runs before HP loss and consumes one actual Reaction and
Stamina, retaining its separate once-per-round limit. Tracked fired ammunition
can be caught or placed through the public fired-unit lifecycle. Unknown
projectile identity never fabricates an item. Barrier uses the native duration,
round, movement, OA, cover and player-choice contracts. Upstream cultivation
availability replies make source-owned benefits dormant without refunding cost.
"""
from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any

from . import effect, hook

PREFIX = "tianxia.subpath.body.bojutsu.feature."
FEATURE_LEVELS = {PREFIX + name: level for name, level in (
    ('staff_form', 3), ('flowing_spin', 6), ('sweeping_strike', 10),
    ('staff_of_one', 14), ('heavenly_staff_barrier', 18))}
ATTACKED = "condition:typed.bojutsu_staff_attack_action"
SWEEP_USED = "condition:typed.bojutsu_sweep_used"
DEFLECT_USED = "condition:typed.bojutsu_deflect_used"
DEFLECT_PENDING = "condition:typed.bojutsu_deflect_packet_pending"
DEFLECT_COVER = "condition:typed.bojutsu_deflect_cover"
BARRIER = "condition:typed.bojutsu_barrier"
BARRIER_USED = "condition:typed.bojutsu_barrier_hit_used"
BARRIER_AC = "condition:typed.bojutsu_barrier_ac"


def _typed(action):
    return (action.parameters or {}).get("typed") or {}


def _staff(typed):
    if typed.get('object_attack_profile'):
        return _staff(typed['object_attack_profile'])
    from .integrated_weapons import printed_staff
    item_id = str(typed.get('bojutsu_item') or typed.get('source') or '')
    return (any(e.get('type') == 'attack' and e.get('attack_kind') == 'weapon'
                for e in typed.get('effects') or [])
            and printed_staff({**typed, 'source': item_id}))


def _rows(engine, actor, kind):
    from . import run_strict as query
    rows = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "bojutsu" and row.get("kind") == kind and row.get("feature_id") in FEATURE_LEVELS]
    out = []
    for row in rows:
        feature = row['feature_id']
        from .body_modes_scene_resources import available, effective_body_cl
        if (not available(engine, actor, feature, FEATURE_LEVELS[feature], requires_conscious=False)
                or False in query('cultivation_feature_available', engine, actor, feature)):
            continue
        levels = [int(v) for v in query('cultivation_effective_cl', engine, actor, 'tianxia.path.body_refining')
                  if type(v) is int]
        minimum = {'form': 3, 'flow': 6, 'sweep': 10, 'one': 14, 'deflect': 14, 'barrier': 18}.get(kind, 0)
        # Explicit availability and source-owned effective CL both gate the row.
        if levels and min(levels) < minimum:
            continue
        out.append({**row, 'numbers': {**row.get('numbers', {}), 'cl': effective_body_cl(engine, actor)}})
    return out


def _stamp(engine):
    actor = engine.state.actors[engine.state.current_actor_id]
    return f"{engine.state.round_number}:{engine.state.current_slot_index}:{actor.entity_id}:{actor.turns_started}"


def _wielded_staff(engine, actor):
    """Only a physically available, drawn Staff grants wielded benefits."""
    from ..weapon_delivery import ready_weapons
    from ..acquisition_inventory import read, controlled, location
    items = read(actor)
    def available_item(action):
        item = next((i for i in items.values() if action.source_definition_id in i.get('weapon_actions', [])), None)
        if item is None:
            return True
        place = location(actor, item.get('inventory_key'))
        return (controlled(actor, item) and item.get('quantity', 1) > 0
                and not any(item['profile']['flags'].get(k) for k in ('broken', 'consumed'))
                and (place is None or place == 'hand' or place.startswith('hand:')))
    return [action for action in ready_weapons(engine, actor).values()
            if action.economy.value == "ACTION" and _staff(_typed(action)) and available_item(action)]


@hook("ac")
def staff_of_one_ac(engine, actor):
    bonus = int(bool(_rows(engine, actor, "one") and _wielded_staff(engine, actor)))
    bonus += int(bool(_rows(engine, actor, "barrier")) and any(c.condition_id == BARRIER_AC for c in actor.conditions.values()))
    return bonus or None


@hook("attack_mode")
def staff_opportunity_advantage(ctx, target):
    if (_rows(ctx.engine, ctx.actor, "one") and _staff(ctx.typed)
            and ctx.typed.get("opportunity_of") in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)}
            and getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id):
        return "ADVANTAGE"
    return None


@hook("save")
def retain_staff_save(ctx, subject, ability, named):
    if "disarmed" not in named or not _rows(ctx.engine, subject, "one"):
        return None
    # Match the executor's selected weapon, including its prior-owner recovery
    # case. Wielding a Staff does not protect a different weapon from disarm.
    recovered = next((c for c in ctx.actor.conditions.values() if c.data.get('held_by') == subject.entity_id), None)
    if recovered is not None:
        weapon = recovered.data.get('disables_action')
        return ({'bonus': 0, 'modes': ['ADVANTAGE']} if any(
            a.parameters.get('requires_held_weapon') == weapon for a in _wielded_staff(ctx.engine, subject)) else None)
    from ..typed_executor import _best_weapon_action

    selected = _best_weapon_action(ctx.engine, subject)
    if selected in {a.source_definition_id for a in _wielded_staff(ctx.engine, subject)}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@effect("bojutsu")
def marker(ctx, row):
    """Owned Bojutsu marker; barrier activation starts its source clock."""
    if row.get("kind") == "barrier":
        from .effect_durations import round_token

        if ctx.typed.get('source') != PREFIX + 'heavenly_staff_barrier':
            raise ValueError('This activation does not own Heavenly Staff Barrier')
        rows = _rows(ctx.engine, ctx.actor, 'barrier')
        if not rows:
            raise ValueError('Heavenly Staff Barrier is unavailable at the current Body level')
        ctx.engine._remove_condition(ctx.actor, BARRIER, ctx.source)
        ctx.engine._apply_condition(ctx.actor, BARRIER, ctx.source, ctx.actor.entity_id,
            expires_on=round_token(ctx.engine, 10), data={"label": "Heavenly Staff Barrier", "source_cl": int(rows[0]["numbers"]["cl"])})


@hook("damage_pending")
def deflecting_staff(engine, target, pending, source_definition_id, source_actor_id):
    """Intercept a represented ranged weapon packet; unrepresented delivery is inert."""
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from .effect_durations import round_token
    from .needle import ask, checkpoint_id
    from .choice_costs import Payment

    packet = getattr(engine, "_typed_damage_packet", None)
    if packet is None:
        from ..attack_delivery import current
        packet = current(engine, source_actor_id, target.entity_id, source_definition_id, pending=True)
    packet = packet or {}
    if (pending <= 0 or not target.active
            or (packet.get("source"), packet.get("actor"), packet.get("target"))
            != (source_definition_id, source_actor_id, target.entity_id)):
        return None
    from ..relations import relation, ALLY
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return None
    incoming = engine.action_catalog.get(source_definition_id)
    action_name = incoming.display_name if incoming else "the incoming attack"
    for actor in engine.state.actors.values():
        rows = _rows(engine, actor, "deflect")
        if (not rows or not interceptable_packet(engine, actor, packet)
                or relation(engine, actor, target) != ALLY or not _wielded_staff(engine, actor)
                or engine._distance_actor_to_actor(actor, target) > 5
                or not typed_reactions.can_use_reaction(engine, actor, engine.state.actors.get(source_actor_id), rows[0])
                or not typed_reactions._holds(engine, actor, "resource:core.stamina", 1, context=rows[0])
                or any(c.condition_id == DEFLECT_USED and c.data.get("round") == engine.state.round_number
                       for c in actor.conditions.values())):
            continue
        from ..targeting import line_of_effect
        if not line_of_effect(engine, actor, target=target):
            continue
        row = rows[0]
        attacker = engine.state.actors.get(source_actor_id)
        threat = 'the incoming ranged weapon attack or material projectile'
        action_name = 'the incoming projectile'
        payment = Payment('resource:core.stamina', 1)
        prompt = (f"Deflecting Staff: spend 1 Stamina and one available Reaction to reduce {threat}'s damage "
                  f"to {target.display_name} by 2d10 + Constitution modifier? Once per round.")
        selected = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect", target.entity_id), actor,
                       "choice:needle.bojutsu_deflect", ["Use Deflecting Staff"], allow_decline=True,
                       prompt=prompt, target_id=target.entity_id, payment=payment)
        if not selected:
            continue
        with activation(engine, actor, row["feature_id"]):
            typed_reactions.open_reaction(engine, row, actor, (target.entity_id,), "DAMAGE_APPLICATION")
            engine._remove_condition(actor, DEFLECT_USED, row["feature_id"])
            engine._apply_condition(actor, DEFLECT_USED, row["feature_id"], actor.entity_id,
                                    expires_on=round_token(engine, 1), data={"round": engine.state.round_number})
            payment.pay(engine, actor, row['feature_id'])
            from ..activation_payments import reaction_completed
            if (not reaction_completed(engine, actor, row['feature_id'])
                    or not _wielded_staff(engine, actor) or engine._distance_actor_to_actor(actor, target) > 5):
                return None
            roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=int(row["con_mod"])),
                                      actor_id=actor.entity_id, reason=f"DAMAGE_REDUCTION:{row['feature_id']}")
            engine._record_roll(roll)
            reduced = max(0, pending - max(0, roll.total))
            from .attack_reduction import remember
            reduced = remember(engine, target, pending, reduced, [(max(0, roll.total), ())], feature=row['feature_id'], delivery='physical_projectile', reactor=actor)
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=actor.entity_id,
                                 target_ids=(target.entity_id,), payload={"checkpoint": "DAMAGE_APPLICATION",
                                 "pending_before": pending, "pending_after": reduced, "reduction": pending - reduced,
                                 "protects": target.entity_id, "name": "Deflecting Staff", "roll_id": roll.roll_id,
                                 "rolled_reduction": max(0, roll.total)})
            if packet.get('component') == 'payload':
                provenance = engine.damage_context()
                engine._apply_condition(actor, DEFLECT_PENDING, row['feature_id'], actor.entity_id,
                    expires_on='UNTIL_REMOVED', data={'roll_id': provenance.roll_id, 'target_id': target.entity_id,
                        'attacker_id': source_actor_id, 'zero': int(reduced == 0), 'label': 'Deflecting Staff packet settlement'})
                from ..paid_relocation import capture, retain
                retain(engine, ('bojutsu_deflect_packet', actor.entity_id, target.entity_id, provenance.roll_id), capture(engine))
            elif reduced == 0:
                if row.get("zero_choices"):
                    _deflect_result(engine, actor, target, intent, row, action_name)
                else:
                    engine._append_event("GM_RIDER", row["feature_id"], actor_id=actor.entity_id,
                    target_ids=(target.entity_id,), payload={"rider": "Deflecting Staff reduced damage to zero. Choose exactly one: "
                    "catch a holdable projectile with a free hand without duplicating it; deflect into an unoccupied space within "
                    "15 feet without attacking; move 5 feet along a legal route without provoking; or grant the protected ally "
                    "Half Cover until the start of your next turn. These follow-ups remain pending automation."})
            return reduced
    return None


def _deflect_routes(engine, actor, distance=5):
    """Bojutsu willing routes for Deflecting Staff and Heavenly Staff Barrier."""
    from ..granted_movement import routes, Route
    from .needle import cell_id
    return {cell_id(cell): Route(tuple(path), mode) for cell, (path, cost, mode) in routes(engine, actor, distance).items()}


def _deflect_result(engine, actor, target, intent, row, action_name):
    """Exactly one printed result; unresolved object choices never mint items."""
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    routes = _deflect_routes(engine, actor)
    options = []
    if target.entity_id != actor.entity_id:
        options.append("Grant Half Cover")
    if routes:
        options.append("Move 5 feet")
    from .projectile_items import current as current_projectile
    from .hand_occupancy import free_hands
    from ..object_placement import destinations
    projectile = current_projectile(engine, actor)
    hands = free_hands(engine, actor)
    places = destinations(engine, actor, 15)
    if projectile and projectile.get('holdable') == 1 and hands:
        options.append("Catch projectile")
    if places:
        options.append("Deflect projectile")
    prompt = f"Deflecting Staff: {action_name} against {target.display_name} reduced to zero; choose one result."
    picked = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect_result", target.entity_id), actor,
                 "choice:needle.bojutsu_deflect_result", options, prompt=prompt, target_id=target.entity_id)
    if not picked:
        return
    source = row["feature_id"]
    if picked[0] == "Grant Half Cover":
        for iid, old in list(target.conditions.items()):
            if old.condition_id == DEFLECT_COVER and old.source_actor_id == actor.entity_id:
                del target.conditions[iid]
                engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id,
                    target_ids=(target.entity_id,), payload={"condition_id": DEFLECT_COVER, "instance_id": iid})
        engine._apply_condition(target, DEFLECT_COVER, source, actor.entity_id,
            expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
            data={"label": "Deflecting Staff Half Cover", "cover": 2})
    elif picked[0] == "Move 5 feet":
        destination = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect_step", target.entity_id), actor,
            "choice:needle.bojutsu_deflect_step", sorted(routes), prompt=prompt + " Choose a legal destination.",
            labels={key: "Move to " + key.removeprefix("cell:") for key in routes},
            target_id=target.entity_id)
        if not destination:
            return
        _staff_step(engine, actor, routes[destination[0]], source)
    elif picked[0] == "Catch projectile":
        from .projectile_items import settle
        hand = ask(engine, intent, checkpoint_id(engine, "bojutsu_catch_hand", target.entity_id), actor,
            "choice:needle.bojutsu_catch_hand", list(hands),
            labels={h: "Catch in " + h.removeprefix("hand:") + " hand" for h in hands},
            name="Deflecting Staff", target_id=target.entity_id,
            prompt=f"Deflecting Staff: catch this fired {projectile['item_name']} in one free hand. No second item is created.")
        if hand:
            settle(engine, actor, projectile, source, hand=hand[0])
    elif picked[0] == "Deflect projectile":
        from .projectile_items import settle
        from .needle import cell_id
        locations = {cell_id(p): p for p in places}
        destination = ask(engine, intent, checkpoint_id(engine, "bojutsu_projectile_space", target.entity_id), actor,
            "choice:needle.bojutsu_projectile_space", sorted(locations),
            labels={key: "Deflect to " + key.removeprefix("cell:") for key in locations},
            name="Deflecting Staff", target_id=target.entity_id,
            prompt="Deflecting Staff: deflect this physical projectile into one unoccupied space within 15 feet. It makes no attack.")
        if destination:
            if projectile:
                settle(engine, actor, projectile, source, destination=locations[destination[0]])
            else:
                engine._append_event('PROJECTILE_DEFLECTED', source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                    payload={'destination': locations[destination[0]].model_dump(mode='json'),
                             'new_attack': 0, 'item_acquired': 0})


@hook("cover")
@hook("effect_cover")
def deflect_cover(engine, attacker, target, context=None):
    """The selected ally's Half Cover; the engine takes the best cover, not a sum."""
    return 2 if any(c.condition_id == DEFLECT_COVER and c.source_actor_id in engine.state.actors
        and _rows(engine, engine.state.actors[c.source_actor_id], "deflect")
        for c in target.conditions.values()) else None


def _staff_step(engine, actor, path, source, distance=5):
    """Commit willing movement for both Bojutsu menus without ordinary OAs."""
    from ..movement_paths import resolve
    resolve(engine, actor, path, source, kind='granted', feet=distance, provokes=False)


def _barrier_active(engine, actor):
    return bool(_rows(engine, actor, "barrier") and actor.active and _wielded_staff(engine, actor)
            and any(c.condition_id == BARRIER for c in actor.conditions.values()))


def _barrier_reach_active(engine, actor):
    return _barrier_active(engine, actor) and any(row.get("staff_reach") for row in _rows(engine, actor, "barrier"))


@hook("opportunity_profile")
def barrier_opportunity_profile(engine, actor, action):
    """Pure Staff-only OA profile; dormant without an active opted-in Barrier."""
    if not _barrier_reach_active(engine, actor) or not _staff(_typed(action)):
        return None
    staffs = _wielded_staff(engine, actor)
    staff = next((s for s in staffs if s.source_definition_id == _typed(action).get("opportunity_of")), None)
    if staff is None:
        return None
    reach = _staff_reach_base(engine, actor, staff, opportunity=True)
    return action.model_copy(update={"range_ft": reach})


@hook("after_hit")
def barrier_hit(ctx, target, kind):
    """Choose one after a Staff hit, once per current turn including AI turns."""
    if kind != "weapon" or not _staff(ctx.typed) or not _barrier_active(ctx.engine, ctx.actor):
        return
    if any(c.condition_id == BARRIER_USED for c in ctx.actor.conditions.values()):
        return
    from .. import typed_executor
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    routes = _deflect_routes(ctx.engine, ctx.actor, 10)
    options = (["Push 10 feet", "No Reactions"] if target.active else [])
    if routes:
        options.append("Move 10 feet")
    options.append("Gain +1 AC")
    prompt = f"Heavenly Staff Barrier: {ctx.action.display_name} hit {target.display_name}; choose one result."
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_barrier_hit", target.entity_id), ctx.actor,
        "choice:needle.bojutsu_barrier_hit", options, prompt=prompt + " No additional Stamina cost; once per turn.", target_id=target.entity_id,
        labels={"Push 10 feet": f"Push {target.display_name} 10 feet directly away",
                "No Reactions": f"No Reactions for {target.display_name} until its next turn starts",
                "Move 10 feet": "Move up to 10 feet along a legal route without provoking",
                "Gain +1 AC": "+1 AC until your next turn starts (does not stack)"})
    if not picked:
        return
    source = PREFIX + "heavenly_staff_barrier"
    current = ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    ctx.engine._apply_condition(ctx.actor, BARRIER_USED, source, ctx.actor.entity_id,
        expires_on=token("end", current.entity_id, int(current.turns_started)),
        data={"label": "Heavenly Staff Barrier hit result used"})
    sub = ctx.on_hit_context(target, action=ctx.action.model_copy(update={'source_definition_id': source}), typed=ctx.typed, damage_cache={})
    if picked[0] == "Push 10 feet":
        typed_executor.run_effects(sub, [{"type": "forced_movement", "direction": "away", "distance_ft": 10,
                                        "applies_to": "target"}])
    elif picked[0] == "No Reactions":
        typed_executor.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target",
                                        "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif picked[0] == "Gain +1 AC":
        ctx.engine._remove_condition(ctx.actor, BARRIER_AC, source)
        ctx.engine._apply_condition(ctx.actor, BARRIER_AC, source, ctx.actor.entity_id,
            expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
            data={"label": "Heavenly Staff Barrier +1 AC", "amount": 1})
    else:
        destination = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_barrier_step", target.entity_id), ctx.actor,
            "choice:needle.bojutsu_barrier_step", sorted(routes), prompt=prompt + " Choose a legal destination.",
            labels={key: "Move to " + key.removeprefix("cell:") for key in routes},
            target_id=target.entity_id)
        if destination:
            _staff_step(ctx.engine, ctx.actor, routes[destination[0]], source, distance=10)


@hook("compile_actions")
def compile_staff(info: dict[str, Any]):
    from ..gate2_runtime_models import EconomyKind

    if not set(info['owned_ids']).intersection(FEATURE_LEVELS):
        return None
    # Consume the existing explicit owning-Path profile without changing the
    # compiler's numbers for another source family.
    body = next((p for p in (info['owner_sheet'].get('path_and_subpath') or {}).get('paths') or []
                 if isinstance(p, dict) and p.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None:
        profile = acquire_bojutsu(PREFIX.removesuffix('.feature.'), info['owner_sheet'])
        numbers = {**info['numbers'], 'cl': profile['effective_cl']}
        key = str(body.get('key_ability') or 'CON').upper()[:3]
        numbers['key_mod'] = int(info['mods'].get(key, 0))
        numbers['attack_bonus'] = int(numbers['pb']) + numbers['key_mod']
        numbers['save_dc'] = 8 + numbers['attack_bonus']
        info = {**info, 'numbers': numbers}
    specs = []
    for mid in info["owned_ids"]:
        if mid not in FEATURE_LEVELS:
            continue
        mech = info["mechanics"].get(mid) or {}
        for spec in mech.get("effects") or []:
            if spec.get("type") == "bojutsu":
                row = {**copy.deepcopy(spec), "block": "bojutsu", "feature_id": mid, "name": mech["name"],
                       "numbers": copy.deepcopy(info["numbers"])}
                if row.get("kind") == "form":
                    row["fist_permissions"] = [fid for fid in (
                        "tianxia.path.body_refining.feature.refined_iron_fist",
                        "tianxia.path.body_refining.feature.heavenly_fist") if fid in info["owned_ids"]]
                info["passives"].append(row)
                if row.get("kind") == "deflect":
                    row["con_mod"] = int(info["mods"].get("CON", 0))
                    row["choice_owner"] = True
                if row.get("kind") in {"barrier", "sweep"}:
                    row["choice_owner"] = True
                if row.get("kind") in {"deflect", "barrier", "sweep"}:
                    row["trigger_owner"] = "bojutsu"
                specs.append(row)
    kinds = {row["kind"] for row in specs}
    if not kinds:
        return None
    out = []
    for base in info["actions"]:
        typed = _typed(base)
        if not _staff(typed) or typed.get("range_ft") or base.economy != EconomyKind.ACTION:
            continue
        # A normal Attack action only, not an off-hand, granted or maneuver variant.
        if "#" in base.source_definition_id:
            continue
        variants = [base]
        if "form" in kinds:
            typed["bojutsu_abilities"] = {
                "ordinary_attack": int(typed["numbers"]["attack_bonus"]),
                "ordinary_damage": int(typed["weapon"]["damage"].get("modifier") or 0),
                "con_attack": int(info["numbers"]["attack_bonus"]) + int(typed.get("magic_bonus") or 0),
                "con_damage": int(info["mods"].get("CON", 0)) + int(typed.get("magic_bonus") or 0)}
            from .attack_abilities import option_scopes
            permitted, _ = option_scopes([str(typed['weapon'].get('ability') or 'STR')],
                {**info, 'source': typed['source'], 'kind': 'weapon'})
            original = int(typed['weapon'].get('ability_modifier') or 0)
            typed['bojutsu_abilities']['ordinary_options'] = {
                ability: {'attack': int(typed['numbers']['attack_bonus']) + int(info['mods'].get(ability, 0)) - original,
                          'damage': int(typed['weapon']['damage'].get('modifier') or 0) + int(info['mods'].get(ability, 0)) - original}
                for ability in permitted if ability != 'CON' and ability != str(typed['weapon'].get('ability') or 'STR')}
            from .integrated_weapons import constitution_typed
            con = constitution_typed(info, typed)
            con["numbers"]["attack_bonus"] = typed["bojutsu_abilities"]["con_attack"]
            variants.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#bojutsu_con",
                "display_name": base.display_name + " (Constitution)", "parameters": {**base.parameters, "typed": con}}))
            out.append(variants[-1])
            for original in list(variants):
                extended = original.model_copy(update={"source_definition_id": original.source_definition_id + "#bojutsu_reach",
                    "display_name": original.display_name + " (on-turn reach)", "range_ft": int(original.range_ft or 5) + 5,
                    "parameters": {**original.parameters, "bojutsu_on_turn": True}})
                variants.append(extended)
                out.append(extended)
        if any(row.get("staff_reach") for row in specs if row["kind"] == "barrier"):
            for original in list(variants):
                extended = original.model_copy(update={
                    "source_definition_id": original.source_definition_id + "#bojutsu_barrier_reach",
                    "display_name": original.display_name + " (Barrier reach)",
                    "range_ft": int(original.range_ft or 5) + 5,
                    "parameters": {**original.parameters, "bojutsu_barrier_reach": True}})
                variants.append(extended)
                out.append(extended)
        if "flow" in kinds:
            for original in variants:
                flow = copy.deepcopy(_typed(original))
                flow["bojutsu_item"] = typed["source"]
                flow["source"] = PREFIX + "flowing_spin"
                flow["numbers"]["cl"] = int(info["numbers"]["cl"])
                flow.pop("opens", None)
                flow.pop("uses", None)
                flow["weapon"]["damage"]["sides"] = max(6, int(flow["weapon"]["damage"]["sides"]))
                attack = copy.deepcopy(next(e for e in flow["effects"] if e.get("type") == "attack"))
                attack.update(count=1, granted_attack_root=True)
                attack.pop("count_by_cl", None)
                flow["effects"] = [attack]
                flow["granted_attack"] = True
                out.append(original.model_copy(update={
                    "source_definition_id": f"action:typed.{info['short']}.flowing_spin#{original.source_definition_id}",
                    "display_name": f"Flowing Spin: {original.display_name}", "economy": EconomyKind.BONUS_ACTION,
                    "costs": (("resource:core.stamina", 1),), "parameters": {**original.parameters, "typed": flow,
                        "bojutsu_flow": True, "bojutsu_weapon": base.source_definition_id}}))
    return out


@hook("candidate_allowed")
def allowed(engine, actor, candidate, action):
    if action is None:
        return None
    typed, params = _typed(action), action.parameters or {}
    if _rows(engine, actor, "flow") and typed.get("source") == PREFIX + "flowing_spin" and not params.get("bojutsu_flow"):
        return False
    if "#bojutsu_con" in action.source_definition_id and not _rows(engine, actor, "form"):
        return False
    if params.get("bojutsu_flow") and not _rows(engine, actor, "flow"):
        return False
    if params.get("bojutsu_on_turn") and (not _rows(engine, actor, "form") or engine.state.current_actor_id != actor.entity_id):
        return False
    if params.get("bojutsu_barrier_reach") and not _barrier_reach_active(engine, actor):
        return False
    if params.get('object_source_weapon') and _staff(typed):
        parent = engine.action_catalog.get(params['object_source_weapon'])
        if parent is None or params['object_source_weapon'] not in {a.source_definition_id for a in _wielded_staff(engine, actor)}:
            return False
        obj = engine.state.objects.get(next(iter(candidate.target_ids), ''))
        if obj is not None:
            from ..object_geometry import target_cells
            reach = current_staff_reach(engine, actor, parent, _typed(parent))
            if min(engine._distance_actor_to_cell(actor, cell) for cell in target_cells(engine, obj)) > reach:
                return False
    if params.get("bojutsu_flow"):
        if params.get("bojutsu_weapon") not in {a.source_definition_id for a in _wielded_staff(engine, actor)}:
            return False
        if not any(c.condition_id == ATTACKED and c.data.get("stamp") == _stamp(engine) for c in actor.conditions.values()):
            return False
        if any(c.data.get("disables_action") == params["bojutsu_weapon"] for c in actor.conditions.values()):
            return False
    return None


@hook("event")
def record_attack_action(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    from .attack_scope import current
    frame = current(engine)
    if frame is None:
        return
    source = frame['source']
    action = engine.action_catalog.get(source)
    if actor is None or not _rows(engine, actor, "flow") or action is None:
        return
    typed = frame['context'].typed
    if typed.get('reaction_attack') or typed.get('granted_attack') or frame['effect'].get('granted_attack_root'):
        return
    if action.economy.value != "ACTION" or engine.state.current_actor_id != actor.entity_id or not _staff(typed):
        return
    engine._remove_condition(actor, ATTACKED, source)
    engine._apply_condition(actor, ATTACKED, source, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"stamp": _stamp(engine), "label": "Staff Attack action made"})


@hook("after_hit")
def sweeping_strike(ctx, target, kind):
    if kind != "weapon" or not target.active or not _staff(ctx.typed):
        return
    from .. import typed_executor
    from .needle import ask, checkpoint_id
    from .choice_costs import Payment
    from ..typed_reactions import _holds

    for row in _rows(ctx.engine, ctx.actor, "sweep"):
        if not _holds(ctx.engine, ctx.actor, "resource:core.stamina", 1, context=row) or any(
                c.condition_id == SWEEP_USED and c.data.get("stamp") == _stamp(ctx.engine) for c in ctx.actor.conditions.values()):
            continue
        payment = Payment("resource:core.stamina", 1)
        choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_sweep", target.entity_id), ctx.actor,
                     "choice:needle.bojutsu_sweep", ["Use Sweeping Strike"], allow_decline=True, target_id=target.entity_id,
                     prompt=f"Sweeping Strike: {ctx.action.display_name} hit {target.display_name}; spend 1 Stamina for a Dexterity save and a forced movement or control result (once per turn)?", payment=payment)
        if not choice:
            return
        payment.pay(ctx.engine, ctx.actor, row["feature_id"])
        ctx.engine._remove_condition(ctx.actor, SWEEP_USED, row["feature_id"])
        ctx.engine._apply_condition(ctx.actor, SWEEP_USED, row["feature_id"], ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"stamp": _stamp(ctx.engine), "label": "Sweeping Strike used this turn"})
        from ..weapon_delivery import weapon_identity
        bound = weapon_identity(ctx.engine, ctx.source, ctx.typed, ctx.action.parameters, owner_id=ctx.actor.entity_id)
        action = ctx.action.model_copy(update={'source_definition_id': row['feature_id'],
            'display_name': row['name'], 'range_ft': current_staff_reach(ctx.engine, ctx.actor, ctx.action, ctx.typed),
            'parameters': {**ctx.action.parameters, 'range_from_action': bound}})
        sub = ctx.on_hit_context(target, action=action,
            typed={**ctx.typed, 'source': row['feature_id'], 'numbers': row['numbers']}, damage_cache={})
        typed_executor.run_effects(sub, row["effects"])
        from .body_modes_scene_resources import notify_paid
        notify_paid(ctx.engine, ctx.actor, row['feature_id'], 'INTENT_ACCEPTED')


@effect("bojutsu_result")
def choose_result(ctx, row):
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    options = row["options"]
    choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_result", ctx.target.entity_id), ctx.actor,
                 "choice:needle.bojutsu_result", [r["label"] for r in options], target_id=ctx.target.entity_id,
                 prompt=f"Sweeping Strike: {ctx.action.display_name} hit {ctx.target.display_name}; choose the failed-save result.")
    if choice:
        typed_executor.run_effects(ctx, next(r["effects"] for r in options if r["label"] == choice[0]))


@effect("bojutsu_reposition")
def reposition(ctx, row):
    from .rider_movement import forced_routes
    from .needle import ask, checkpoint_id, cell_id

    engine, target = ctx.engine, ctx.target
    if target is None or not target.active:
        return
    reach = int(ctx.action.range_ft or 5)
    paths = {cell_id(cell): path for cell, path in forced_routes(engine, target, ctx.actor, ctx.actor, reach).items()}
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "bojutsu_reposition", target.entity_id), ctx.actor,
                 "choice:needle.bojutsu_reposition", list(paths), target_id=target.entity_id,
                 labels={key: "Move to " + key.removeprefix("cell:") for key in paths},
                 prompt=f"Sweeping Strike: {ctx.action.display_name} hit {target.display_name}; choose its destination within your reach.")
    if not chosen:
        return
    from ..movement_paths import resolve
    path = paths[chosen[0]]
    resolve(engine, target, path, ctx.source, kind='forced',
            feet=(len(path)-1)*engine.grid.square_size_ft, intent=ctx.intent, source_actor_id=ctx.actor.entity_id, ctx=ctx)


def _staff_opportunity(ctx):
    return (_staff(ctx.typed) and getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id
            and ctx.typed.get("opportunity_of") in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)})


@hook("cover")
def barrier_cover(engine, attacker, target):
    """Heavenly Staff Barrier: "You and allies within 10 feet gain Half Cover against ranged weapon attacks and physical
    projectiles" -- the aura moves with the wielder; a ranged weapon attack is read from the attack now resolving."""
    if attacker is None or target is None:
        return None
    from ..attack_delivery import current as native_current
    packet = native_current(engine, attacker.entity_id, target.entity_id) if target is not None else None
    if packet is None:
        from .attack_scope import current
        frame = current(engine)
        if target is None or frame is None or frame['actor_id'] != attacker.entity_id or frame['target_id'] != target.entity_id:
            return None
        from ..weapon_delivery import delivery_kind
        context = frame['context']
        effect = frame.get('effect') or {}
        from ..typed_executor import ranged_attack_now
        packet = {'weapon': delivery_kind(context.typed, effect, context.action.parameters) == 'weapon',
                  'ranged': ranged_attack_now(context), 'physical_projectile': effect.get('physical_projectile') is True}
    from ..relations import relation, ALLY
    for owner in engine.state.actors.values():
        profile = packet_profile(engine, owner, packet)
        qualifies = ((packet.get('weapon') and packet.get('ranged')) or packet.get('physical_projectile')
                     or profile is not None and profile['physical'])
        if qualifies and relation(engine, owner, target) == ALLY and _barrier_active(engine, owner) and (
                owner.entity_id == target.entity_id or engine._distance_actor_to_actor(owner, target) <= 10):
            return 2
    return None


@hook("after_hit")
def barrier_opportunity_hit(ctx, target, kind):
    """"A creature hit by your Opportunity Attack has its Speed reduced to 0 for the remainder of the turn"."""
    if target is None or not target.active or not _barrier_active(ctx.engine, ctx.actor) or not _staff_opportunity(ctx):
        return
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    typed_executor.run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN",
                                      "evidence": "Heavenly Staff Barrier: Speed 0 for the rest of the turn"}])


@hook('subpath_acquisition')
def acquire_bojutsu(source, sheet):
    """Open School progression, with no Sphere or sibling grants."""
    if source != PREFIX.removesuffix('.feature.'):
        return None
    import hashlib
    from .qiweaving_common import rules_text
    paths = sheet.get('path_and_subpath') or {}
    identity = sheet.get('identity') or {}
    ids = set(identity.get('path_ids') or paths.get('path_record_ids') or [])
    if paths.get('path_record_id'):
        ids.add(paths['path_record_id'])
    profile_rows = paths.get('paths') or []
    body = next((p for p in profile_rows if isinstance(p, dict) and p.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None:
        ids.add('tianxia.path.body_refining')
    legal = 'tianxia.path.body_refining' in ids if ids else identity.get('path') == 'Body Refining'
    level = int(identity.get('cultivation_level') or 1)
    if body is not None:
        # Existing Path profile fields: explicit effective CL is authoritative;
        # NS1R attainment otherwise caps the sheet's effective cultivation CL.
        attained = next((body[k] for k in ('effective_cl', 'attainment', 'owning_path_level') if k in body), None)
        if type(attained) is not int or attained < 0:
            legal, level = False, 0
        else:
            level = min(level, attained)
    elif profile_rows:
        legal, level = False, 0
    printed = rules_text()
    return {'name': 'Bojutsu', 'legal': legal, 'effective_cl': level,
        'reasons': [] if legal else ['Bojutsu requires an acquired Body Refining Path with a known effective level.'],
        'features': [{'id': PREFIX + name, 'minimum_cl': cl,
            'text_sha256': hashlib.sha256(printed[PREFIX + name].encode()).hexdigest()}
            for name, cl in [('staff_form', 3), ('flowing_spin', 6), ('sweeping_strike', 10),
                             ('staff_of_one', 14), ('heavenly_staff_barrier', 18)]]}


@hook('opportunity_choices')
def staff_opportunity_choices(engine, actor, default):
    """All wielded Staff ability profiles remain selectable for an actual OA."""
    if not (_rows(engine, actor, 'form') or _rows(engine, actor, 'one') or _barrier_active(engine, actor)):
        return None
    staffs = _wielded_staff(engine, actor)
    if not staffs:
        return None
    pending = actor.turn_flags.get("bojutsu_extra_transaction")
    extra_paid = bool(pending) and pending == getattr(engine, "_transaction_id", None)
    default_staff = _staff(_typed(default))
    if default_staff:
        normal = copy.deepcopy(_typed(default))
        for attack in normal.get('effects') or []:
            if attack.get('type') == 'attack':
                attack.update(count=1, granted_attack_root=True)
                attack.pop('count_by_cl', None)
        normal['granted_attack'] = True
        default = default.model_copy(update={'parameters': {**default.parameters, 'typed': normal}})
    choices = [default] if (not extra_paid or default_staff) else []
    from .hand_occupancy import weapon_allowed
    for staff in staffs:
        if weapon_allowed(engine, actor, staff) is False:
            continue
        bases = [staff]
        con = engine.action_catalog.get(staff.source_definition_id + '#bojutsu_con')
        if con is not None:
            bases.append(con)
        for base in bases:
            if base is staff and default_staff and _typed(default).get('opportunity_of') == staff.source_definition_id:
                continue
            typed = copy.deepcopy(_typed(base))
            typed['opportunity_of'] = staff.source_definition_id
            attack = copy.deepcopy(next(e for e in typed['effects'] if e.get('type') == 'attack'))
            attack.update(count=1, granted_attack_root=True)
            attack.pop('count_by_cl', None)
            typed['effects'] = [attack]
            typed['granted_attack'] = True
            reach = _staff_reach_base(engine, actor, staff, opportunity=True)
            choices.append(default.model_copy(update={'display_name': 'Opportunity Attack: ' + base.display_name,
                'range_ft': reach, 'reach_ft': reach, 'parameters': {**base.parameters, 'typed': typed}}))
    return choices


@hook('reaction_spend')
def barrier_extra_reaction(engine, actor, row, commit):
    """A restricted additional Staff Reaction, refreshed by the real round clock."""
    if actor.reaction_available or not _barrier_active(engine, actor):
        return None
    key = '_round_bojutsu_barrier_reaction'
    if actor.turn_flags.get(key) == engine.state.round_number:
        return None
    from ..alternative_payments import owned
    staff_feature = (row.get('feature_id') == PREFIX + 'staff_of_one'
                     or row.get('staff_feature') is True and owned(engine, actor, row.get('feature_id', '')))
    if row.get('block') == 'opportunity' or row.get('reaction_kind') == 'opportunity_attack':
        from .hand_occupancy import weapon_allowed
        staff_feature = any(weapon_allowed(engine, actor, a) is not False for a in _wielded_staff(engine, actor))
    if not staff_feature:
        return None
    if commit:
        actor.turn_flags[key] = int(engine.state.round_number)
        actor.turn_flags["bojutsu_extra_transaction"] = str(getattr(engine, "_transaction_id", ""))
    return 'free'


@hook('movement_step')
def barrier_entry(engine, mover, previous, nxt, intent):
    """Only committed voluntary entry provokes; forced moves use another hook."""
    from .. import typed_reactions as tr
    from ..relations import relation, ENEMY
    from ..movement_steps import opportunity_exempt
    for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not _barrier_active(engine, actor) or relation(engine, actor, mover) != ENEMY or opportunity_exempt(engine, mover, actor.entity_id):
            continue
        from ..target_knowledge import can_see
        from ..targeting import line_of_effect
        if not can_see(engine, actor, mover) or not line_of_effect(engine, actor, target=mover):
            continue
        if tr.opportunity_reach(engine, actor) is None:
            continue
        from .hand_occupancy import weapon_allowed
        reach = max((current_staff_reach(engine, actor, staff, _typed(staff), opportunity=True)
            for staff in _wielded_staff(engine, actor) if weapon_allowed(engine, actor, staff) is not False), default=0)
        if reach <= 0:
            continue
        before = engine._distance_actor_to_actor(mover, actor, actor_position=previous)
        after = engine._distance_actor_to_actor(mover, actor, actor_position=nxt)
        if not before > reach >= after or not tr.wants_opportunity_attack(engine, actor, mover):
            continue
        row = tr.opportunity_reaction_row(engine, actor)
        with activation(engine, actor, PREFIX + 'heavenly_staff_barrier', independent=True):
            tr.open_reaction(engine, row, actor, (mover.entity_id,), 'ENTER_REACH',
                reaction_notice=tr.opportunity_reaction_notice(engine, actor, (mover.entity_id,)))
            tr.spend_reaction(engine, actor, row)
            tr.opportunity_attack(engine, actor, mover, intent, reach_ft=reach, reaction_opened=True, trigger='movement')
        if not mover.active or engine._effective_speed(mover) == 0:
            return {'stop': True, 'source_id': PREFIX + 'heavenly_staff_barrier',
                'label': 'Heavenly Staff Barrier: the Staff Opportunity Attack hit; Speed is 0 for the rest of this turn.'}
    return None


@hook('attack_spec_choice')
def staff_strike_ability(ctx, target, attack, spec, attack_index):
    """Each Staff strike independently chooses its printed ability profile."""
    if not _rows(ctx.engine, ctx.actor, 'form') or not _staff(ctx.typed):
        return
    choices = ctx.typed.get('bojutsu_abilities')
    if not choices:
        return
    from ..weapon_delivery import weapon_identity
    identity = weapon_identity(ctx.engine, ctx.source, ctx.typed, ctx.action.parameters, owner_id=ctx.actor.entity_id)
    if identity not in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)}:
        return
    from .needle import ask, checkpoint_id
    preferred = 'Constitution' if choices['con_attack'] >= choices['ordinary_attack'] else 'Weapon ability'
    ability_names = {'STR': 'Strength', 'DEX': 'Dexterity', 'INT': 'Intelligence',
                     'WIS': 'Wisdom', 'CHA': 'Charisma'}
    ordinary = choices.get('ordinary_options') or {}
    options = ['Weapon ability', 'Constitution', *ordinary]
    labels = {'Weapon ability': 'The weapon’s usual ability', 'Constitution': 'Constitution with Cultivation Attack Modifier',
              **{a: ability_names.get(a, a) for a in ordinary}}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'bojutsu_ability', target.entity_id, attack_index),
        ctx.actor, 'choice:needle.bojutsu_ability', options, labels=labels, preferred=[preferred],
        name='Staff Form', feature_id=PREFIX+'staff_form', target_id=target.entity_id,
        prompt=f'Staff Form: choose the ability for strike {attack_index} of {ctx.action.display_name} against {target.display_name}. '
               'Constitution uses your Cultivation Attack Modifier and Constitution for damage. No additional cost.')
    if not picked:
        return
    selected = 'con' if picked[0] == 'Constitution' else 'ordinary'
    selected_attack = ordinary[picked[0]]['attack'] if picked[0] in ordinary else choices[selected+'_attack']
    selected_damage = ordinary[picked[0]]['damage'] if picked[0] in ordinary else choices[selected+'_damage']
    typed = copy.deepcopy(spec['typed'])
    attack_before = int(typed['numbers']['attack_bonus'])
    damage_before = int(typed['weapon']['damage'].get('modifier') or 0)
    spec['attack_bonus'] += selected_attack - attack_before
    if spec.get('damage') is not None:
        spec['damage'] = spec['damage'].model_copy(update={'modifier': spec['damage'].modifier + selected_damage - damage_before})
    typed['weapon']['damage']['modifier'] = selected_damage
    typed['numbers']['attack_bonus'] = spec['attack_bonus']
    typed['resolved_attack_ability'] = picked[0]
    spec['typed'] = typed


def staff_fist_permission(engine, actor, typed, permission):
    """Only an actually acquired, available core permission extends to a wielded Staff."""
    if not _staff(typed):
        return False
    rows = _rows(engine, actor, 'form')
    feature = 'tianxia.path.body_refining.feature.' + permission
    if not any(feature in row.get('fist_permissions', []) for row in rows):
        return False
    from . import run_strict as query
    if False in query('cultivation_feature_available', engine, actor, feature):
        return False
    levels = [v for v in query('cultivation_effective_cl', engine, actor, 'tianxia.path.body_refining') if type(v) is int]
    from .body_modes_scene_resources import available
    if not available(engine, actor, feature, 17 if permission == 'heavenly_fist' else 5, requires_conscious=False):
        return False
    if levels and min(levels) < (17 if permission == 'heavenly_fist' else 5):
        return False
    bound = typed.get('opportunity_of')
    if bound:
        return bound in {a.source_definition_id for a in _wielded_staff(engine, actor)}
    item = str(typed.get('bojutsu_item') or typed.get('source') or '')
    return any(_typed(a).get('source') == item for a in _wielded_staff(engine, actor))


@hook('attack_magical')
def integrated_staff_magical(engine, actor_id, typed):
    actor = engine.state.actors.get(actor_id)
    if actor is None:
        return None
    return True if any(staff_fist_permission(engine, actor, typed, p)
        for p in ('refined_iron_fist', 'heavenly_fist')) else None


@hook('attack_damage_type_choice')
def heavenly_staff_force(ctx, attack, target, kinds, attack_index):
    if not staff_fist_permission(ctx.engine, ctx.actor, ctx.typed, 'heavenly_fist'):
        return None
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'bojutsu_heavenly_type', target.entity_id, attack_index),
        ctx.actor, 'choice:needle.bojutsu_heavenly_type', list(dict.fromkeys([*kinds, 'FORCE'])),
        name='Heavenly Fist', target_id=target.entity_id,
        prompt=f'Heavenly Fist: choose the damage type of {ctx.action.display_name} against {target.display_name}. '
               'Force replaces the normal type; damage dice and cost stay the same.')
    return picked[0] if picked else None


@hook('attack_damage_types')
def heavenly_staff_palette(ctx, attack, kinds):
    if ctx.weapon_damage_dice and staff_fist_permission(ctx.engine, ctx.actor, ctx.typed, 'heavenly_fist'):
        return list(dict.fromkeys([*kinds, 'FORCE']))
    return None


@hook('weapon_variant_parent')
def flowing_spin_weapon_parent(parameters):
    """Flowing Spin borrows one bound Staff, preserving physical inventory identity."""
    if parameters.get('bojutsu_flow') and not parameters.get('object_source_weapon') and _staff(parameters.get('typed') or {}):
        return parameters.get('bojutsu_weapon')
    return None


@hook('check_hazard_mode')
def retain_staff_check(engine, actor, ability, skill, hazards):
    """Advantage only on a native check specifically retaining the selected Staff."""
    if not set(hazards).intersection({'disarm', 'disarmed'}) or not _rows(engine, actor, 'one'):
        return None
    from ..typed_executor import _best_weapon_action
    selected = _best_weapon_action(engine, actor)
    return 'ADVANTAGE' if selected in {a.source_definition_id for a in _wielded_staff(engine, actor)} else None


def current_staff_reach(engine, actor, action, typed, *, opportunity=False):
    """Actual Staff-feature reach, including its current native handling and state."""
    from ..weapon_delivery import weapon_identity
    identity = weapon_identity(engine, action.source_definition_id, typed, action.parameters, owner_id=actor.entity_id)
    staff = next((a for a in _wielded_staff(engine, actor) if a.source_definition_id == identity), None)
    if staff is None:
        return int(action.range_ft or 5)
    from ..attack_reach import maximum
    return maximum(engine, actor, staff,
        base=_staff_reach_base(engine, actor, staff, opportunity=opportunity), opportunity=opportunity)


def _staff_reach_base(engine, actor, staff, *, opportunity=False):
    from .reach_bonus import current_reach
    return (current_reach(engine, actor, staff, opportunity=opportunity)
            + (5 if _barrier_active(engine, actor) else 0)
            + (5 if engine.state.current_actor_id == actor.entity_id and _rows(engine, actor, 'form') else 0))


@hook('bound_weapon_reach_bonus')
def bound_staff_reach(engine, actor, action, linked, opportunity):
    if not _staff(_typed(linked)) or linked.source_definition_id not in {
            a.source_definition_id for a in _wielded_staff(engine, actor)}:
        return None
    return ((5 if _barrier_active(engine, actor) else 0)
            + (5 if engine.state.current_actor_id == actor.entity_id and _rows(engine, actor, 'form') else 0)) or None


@hook('attack_damage', priority=100)
def flowing_spin_damage_floor(ctx, dice):
    """Apply the floor after native grip/Versatile sizing, once to weapon dice."""
    if (ctx.typed.get('source') != PREFIX + 'flowing_spin' or not ctx.action.parameters.get('bojutsu_flow')
            or not ctx.weapon_damage_dice or not _rows(ctx.engine, ctx.actor, 'flow') or not _staff(ctx.typed)
            or dice is None or not hasattr(dice, 'sides') or int(dice.sides) >= 6):
        return None
    return dice.model_copy(update={'sides': 6})


@hook('attack_resolution_scope')
def delivery_scope(engine, attacker, target, spec, intent):
    """Publish native packet geometry only when this family has a live consumer."""
    interested = any(_wielded_staff(engine, actor)
        and (_rows(engine, actor, 'deflect') or _barrier_active(engine, actor))
        for actor in engine.state.actors.values())
    if not interested:
        return None
    from ..attack_delivery import resolving
    return resolving(engine, attacker, target, spec, buffer_attached=True)


@hook('opportunity_profile_selected')
def settle_barrier_reaction_profile(engine, actor, target, action):
    """The restricted grant controls this one paid OA, never another grant later."""
    pending = actor.turn_flags.get('bojutsu_extra_transaction')
    if not pending or pending != getattr(engine, '_transaction_id', None):
        return None
    actor.turn_flags['bojutsu_extra_transaction'] = ''
    return bool(_barrier_active(engine, actor) and _staff(_typed(action)))


@hook('save_bonus_details')
def deflect_cover_save(engine, target, ability, dc, source_id, intent):
    """Generic Half Cover's Dexterity bonus uses the actual spatial save origin."""
    if ability != 'DEX' or deflect_cover(engine, None, target) is None:
        return None
    context = engine.d20_context() or {}
    origins = context.get('effect_origin_cells') or []
    if not origins:
        return None
    bonus = engine.cover_from(origins, context.get('source_actor_id'), target)['bonus']
    return {'bonus': bonus, 'contributions': {'cover': bonus}} if bonus else None


@hook('body_mode_profiles')
def bojutsu_scene_profile(bundle):
    """One source-family continuation on Nine-Star's public Body contract."""
    owned = {r.get('feature_id') for r in bundle.get('typed_passives', [])}
    owned.update(((a.get('parameters') or {}).get('typed') or {}).get('source')
                 for a in bundle.get('action_catalog', []))
    if not owned.intersection(FEATURE_LEVELS):
        return None
    limits = sorted({cost[0] for action in bundle.get('action_catalog', [])
                     if ((action.get('parameters') or {}).get('typed') or {}).get('source') == PREFIX + 'heavenly_staff_barrier'
                     for cost in action.get('costs', [])
                     if cost[0].startswith('resource:uses.')})
    return [{'source': PREFIX.removesuffix('.feature.'), 'name': 'Bojutsu',
             'feature_levels': FEATURE_LEVELS, 'scene_limits': limits}]


@hook('journey_options')
def journey_barrier_options(session, aid):
    from .body_modes_scene_resources import feature_owned, journey_available
    actor = session.state['actors'][aid]
    source = PREFIX + 'heavenly_staff_barrier'
    profiles = bojutsu_scene_profile(actor['bundle'])
    if (not profiles or not feature_owned(actor['bundle'], source)
            or not journey_available(session, aid, source, 18)
            or actor['resources'].get('resource:core.stamina', 0) < 6
            or any(actor['resources'].get(r, 0) < 1 for r in profiles[0]['scene_limits'])):
        return None
    return [{'id': 'bojutsu_barrier', 'kind': 'bojutsu_barrier', 'payload': {},
             'label': actor['name'] + ': Heavenly Staff Barrier — spend 6 Stamina; Staff reach, defense and restricted extra Reaction for 1 minute, once this scene.'}]


@hook('journey_command')
def journey_barrier(session, aid, kind, payload):
    if kind != 'bojutsu_barrier':
        return None
    import json
    from ..journey import require
    from .body_modes_scene_resources import AUTHORITY, journey_body_cl, complete_journey_activation
    require(not payload and journey_barrier_options(session, aid), 'Heavenly Staff Barrier is unavailable or cannot be paid.')
    actor = session.state['actors'][aid]
    source = PREFIX + 'heavenly_staff_barrier'
    start = len(session.state['events'])
    actor['resources']['resource:core.stamina'] -= 6
    session.emit('RESOURCE_SPENT', aid, source=source, resource_id='resource:core.stamina', amount=6)
    managed = actor.setdefault('source_states', {}).setdefault(AUTHORITY, {})
    record = managed.setdefault('records', {}).get(PREFIX.removesuffix('.feature.'), {})
    balances = {}
    for resource in bojutsu_scene_profile(actor['bundle'])[0]['scene_limits']:
        actor['resources'][resource] -= 1
        balances[resource] = actor['resources'][resource]
        session.emit('RESOURCE_SPENT', aid, source=source, resource_id=resource, amount=1)
    record['scene_limits'] = balances
    model = {'condition_id': BARRIER, 'source_definition_id': source, 'source_actor_id': aid,
             'data': {'label': 'Heavenly Staff Barrier', 'source_cl': journey_body_cl(session, aid)}}
    effects = managed.setdefault('effects', [])
    effects[:] = [row for row in effects if not (row['kind'] == 'condition' and json.loads(row['model'])['condition_id'] == BARRIER)]
    effects.append({'kind': 'condition', 'model': json.dumps(model, sort_keys=True), 'remaining_num': 60, 'remaining_den': 1})
    session.emit('BOJUTSU_BARRIER_STARTED', aid, source=source, seconds=60, source_cl=model['data']['source_cl'])
    complete_journey_activation(session, aid, source, start)
    return True


@hook('object_attack_sources')
def staff_object_profiles(info):
    if PREFIX + 'staff_form' not in info['owned_ids']:
        return None
    return [a for a in info['actions'] if a.economy.value == 'ACTION'
            and '#' not in a.source_definition_id and _staff(_typed(a))]


@hook('weapon_variant_parent')
def staff_object_parent(parameters):
    profile = (parameters.get('typed') or {}).get('object_attack_profile')
    return parameters.get('object_source_weapon') if profile and _staff(profile) else None


@hook('object_strike_profile')
def staff_object_strike(ctx, obj, index):
    from dataclasses import replace
    from types import SimpleNamespace
    from ..gate2_runtime_models import DiceSpec
    original = ctx.typed.get('object_attack_profile')
    if not original or not _staff(original) or not _rows(ctx.engine, ctx.actor, 'form'):
        return None
    identity = ctx.action.parameters.get('object_source_weapon')
    if identity not in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)}:
        raise ValueError('This object strike requires its wielded Staff')
    from ..object_rules import label
    target = SimpleNamespace(entity_id=obj.object_id, display_name=label(obj))
    strike = replace(ctx, typed=original)
    spec = {'typed': original, 'attack_bonus': int(original['numbers']['attack_bonus']),
            'damage': DiceSpec(**original['weapon']['damage'])}
    staff_strike_ability(strike, target, {}, spec, index)
    from .hand_occupancy import versatile_die_sides
    physical = ctx.engine.action_catalog[identity]
    sides = versatile_die_sides(ctx.engine, ctx.actor, physical)
    if sides is not None:
        spec['damage'] = spec['damage'].model_copy(update={'sides': sides})
    if ctx.action.parameters.get('bojutsu_flow'):
        spec['damage'] = spec['damage'].model_copy(update={'sides': max(6, int(spec['damage'].sides))})
    weapon = copy.deepcopy(original['weapon'])
    weapon['damage'] = spec['damage'].model_dump(mode='json')
    kinds = [str(weapon.get('damage_type') or 'BLUDGEONING').upper()]
    if staff_fist_permission(ctx.engine, ctx.actor, original, 'heavenly_fist'):
        from .needle import ask, checkpoint_id
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'bojutsu_object_type', obj.object_id, index),
                     ctx.actor, 'choice:needle.bojutsu_object_type', list(dict.fromkeys([*kinds, 'FORCE'])),
                     prompt=f'Heavenly Fist: choose normal or Force damage against {label(obj)}; the Staff keeps its damage die.',
                     target_id=obj.object_id)
        weapon['damage_type'] = picked[0]
    return {'weapon': weapon, 'attack_bonus': spec['attack_bonus']}


@hook('object_hit_modifiers')
def staff_heavenly_object_permissions(ctx, obj, packets):
    original = ctx.typed.get('object_attack_profile')
    if not original or not staff_fist_permission(ctx.engine, ctx.actor, original, 'heavenly_fist'):
        return None
    component = obj.component or {}
    source_cl = component.get('source_cl')
    if (not obj.unattended or type(source_cl) is not int or not component.get('source_rule')
            or component.get('physical_force_immune')):
        return None
    from .body_modes_scene_resources import effective_body_cl
    if source_cl > effective_body_cl(ctx.engine, ctx.actor):
        return None
    protected = set(component.get('protected_defenses') or ())
    if component.get('artifact'):
        protected.update(('threshold', 'resistance'))
    result = {}
    if 'damage_multiplier' not in protected:
        result['multiplier'] = 2
    if 'threshold' not in protected:
        result['ignore_threshold'] = True
    if 'resistance' not in protected:
        result['ignore_resistance_types'] = ('BLUDGEONING', 'PIERCING', 'SLASHING', 'FORCE')
    return result or None


@hook('object_attack_max_reach')
def staff_object_range(info, action):
    if not _staff(_typed(action)) or PREFIX + 'staff_form' not in info['owned_ids']:
        return None
    return int(action.range_ft or 5) + 5 + (5 if PREFIX + 'heavenly_staff_barrier' in info['owned_ids'] else 0)


@hook('weapon_impairment_allowed')
def heavenly_staff_integrity(engine, holder, weapon_id, operation, source_id):
    if operation not in ('break', 'rust', 'dull', 'unusable', 'disarm'):
        return None
    weapon = engine.action_catalog.get(weapon_id)
    source = engine.action_catalog.get(source_id)
    if (weapon is None or source is None or not _typed(source).get('mundane')
            or not staff_fist_permission(engine, holder, _typed(weapon), 'heavenly_fist')):
        return None
    engine._append_event('PASSIVE_TRIGGERED', PREFIX + 'staff_form', actor_id=holder.entity_id,
        payload={'text': 'Heavenly Fist protects this wielded Staff from the mundane '+operation+' effect.'})
    return False



@hook('weapon_proficiency')
def staff_proficiency(info):
    if PREFIX + 'staff_form' not in info['owned_ids']:
        return None
    from .integrated_weapons import printed_staff
    return True if printed_staff({'source': info['weapon']['item_id'], 'weapon': info['weapon']}) else None



@hook('reaction_reduction_packet')
def deflect_whole_packet(engine, target, feature, before, after):
    if feature != PREFIX + 'staff_of_one' or after <= 0:
        return
    provenance = engine.damage_context()
    if provenance is None or provenance.component not in ('payload', 'primary'):
        return
    for actor in engine.state.actors.values():
        for condition in list(actor.conditions.values()):
            if (condition.condition_id == DEFLECT_PENDING and condition.data.get('roll_id') == provenance.roll_id
                    and condition.data.get('target_id') == target.entity_id and condition.data.get('zero')):
                data = {**condition.data, 'zero': 0}
                engine._remove_condition_instance(actor, condition.instance_id, feature, expected=condition)
                engine._apply_condition(actor, DEFLECT_PENDING, feature, actor.entity_id, expires_on='UNTIL_REMOVED', data=data)


@hook('attack_packet_resolved')
def deflect_completed_packet(engine, target, provenance, intent):
    for actor in engine.state.actors.values():
        for condition in list(actor.conditions.values()):
            if (condition.condition_id != DEFLECT_PENDING or condition.data.get('roll_id') != provenance.roll_id
                    or condition.data.get('target_id') != target.entity_id):
                continue
            from ..paid_relocation import take, causal_scope
            owner = take(engine, ('bojutsu_deflect_packet', actor.entity_id, target.entity_id, provenance.roll_id))
            with causal_scope(engine, owner):
                engine._remove_condition_instance(actor, condition.instance_id, condition.source_definition_id, expected=condition)
                rows = _rows(engine, actor, 'deflect')
                if condition.data.get('zero') and rows and actor.active and _wielded_staff(engine, actor):
                    _deflect_result(engine, actor, target, intent, rows[0], 'the incoming physical projectile')



@hook('attack_packet_buffer_enabled')
def physical_packet_consumer(engine, attacker, target, spec):
    from ..relations import relation, ALLY
    from ..attack_delivery import current
    from .. import typed_reactions as reactions
    delivery = current(engine, attacker.entity_id, target.entity_id)
    if not delivery:
        return None
    for actor in engine.state.actors.values():
        rows = _rows(engine, actor, 'deflect')
        if (rows and interceptable_packet(engine, actor, delivery)
                and relation(engine, actor, target) == ALLY and _wielded_staff(engine, actor)
                and engine._distance_actor_to_actor(actor, target) <= 5
                and not any(c.condition_id == DEFLECT_USED and c.data.get('round') == engine.state.round_number for c in actor.conditions.values())
                and reactions.can_use_reaction(engine, actor, attacker, rows[0])
                and reactions._holds(engine, actor, 'resource:core.stamina', 1, context=rows[0])):
            return True
    return None


FAMILY = PREFIX.removesuffix('.feature.')


def _profile_action(session, value):
    """Only a currently owned actual source action can receive an external classification."""
    from ..gate2_runtime_models import ActionDefinition
    engine = getattr(session, 'engine', None)
    if engine is not None:
        action = engine.action_catalog.get(value.get('attack_source'))
    else:
        actor = session.state['actors'].get(value.get('attacker_id'), {})
        raw = next((a for a in actor.get('bundle', {}).get('action_catalog', [])
                    if a.get('source_definition_id') == value.get('attack_source')), None)
        action = ActionDefinition.model_validate(raw) if raw is not None else None
    return action if action is not None and action.owner_id == value.get('attacker_id') else None


@hook('fact_admission_schema')
def interception_schema(session, source, subject, kind):
    if source != FAMILY or kind != 'projectile_profile':
        return None
    bundle = session.state['actors'][subject].get('bundle', {})
    if not bojutsu_scene_profile(bundle):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'description': 'Record an actual source action’s material delivery, interceptability, one-hand holdability and printed lifetime. No attack, item or anatomy is granted.'}


@hook('fact_admission_validate')
def validate_interception_profile(session, source, subject, kind, scope, value):
    if source != FAMILY or kind != 'projectile_profile':
        return None
    from ..journey import require
    from ..observer_information import attack_effects
    fields = {'source_rule', 'source_cl', 'attacker_id', 'attack_source', 'effect_index',
              'physical', 'interceptable', 'holdable', 'object_name', 'lifetime_rounds'}
    require(set(value) == fields, 'Record the exact source, physical delivery, holdability and lifetime fields.')
    require(type(value['source_rule']) is str and bool(value['source_rule'].strip()) and len(value['source_rule']) <= 2000,
            'Quote or identify the printed source and the table owner’s authority.')
    require(type(value['source_cl']) is int and value['source_cl'] >= 0, 'Record a nonnegative printed Source CL for otherwise unknown authority.')
    require(all(type(value[k]) is int and value[k] in (0, 1) for k in ('physical', 'interceptable', 'holdable')),
            'Material, interceptable and one-hand holdable must be explicit yes/no facts.')
    require(value['physical'] or not (value['interceptable'] or value['holdable']), 'An energetic ray or beam is not physically intercepted or caught.')
    require(type(value['object_name']) is str and len(value['object_name']) <= 200 and (not value['physical'] or bool(value['object_name'].strip())),
            'Describe the actual material projectile without inventing an item’s statistics.')
    require(type(value['lifetime_rounds']) is int and value['lifetime_rounds'] >= -1,
            'Record -1 for persistent physical matter, 0 for the attack only, or its printed whole-round lifetime.')
    action = _profile_action(session, value)
    require(action is not None, 'Choose an actual action owned by the recorded attacker.')
    nodes = attack_effects(action); index = value['effect_index']
    require(type(index) is int and (0 <= index < len(nodes) or index == -1 and not nodes and action.resolution_kind == 'ATTACK'),
            'Choose the actual source attack profile; a save-based area is not an attack projectile.')
    effect = nodes[index] if index >= 0 else {}
    require(not (effect.get('physical_projectile') is False and value['physical']), 'The source explicitly excludes material delivery.')
    require(not (effect.get('interceptable') is False and value['interceptable']), 'The source explicitly forbids physical interception.')
    return True


def projectile_profile(engine, viewer, source_actor, source, effect_index):
    from ..combat_world_facts import records, clock
    found = [r for r in records(engine) if r['source'] == FAMILY and r['kind'] == 'projectile_profile'
             and r['value']['attacker_id'] == source_actor and r['value']['attack_source'] == source
             and r['value']['effect_index'] == effect_index]
    # A replacement that expires does not resurrect an older declaration.
    return found[-1]['value'] if found and found[-1]['expires_at'] > clock(engine) else None


def packet_profile(engine, viewer, packet):
    if not packet:
        return None
    from ..attack_delivery import current
    actual = current(engine, packet.get('actor'), packet.get('target'), packet.get('source'))
    return projectile_profile(engine, viewer, packet.get('actor'), packet.get('source'), actual.get('effect_index') if actual else None)


def interceptable_packet(engine, viewer, packet):
    if not packet or not packet.get('interceptable'):
        return False
    profile = packet_profile(engine, viewer, packet)
    if profile is not None:
        return bool(profile['physical'] and profile['interceptable'])
    return bool(packet.get('physical_projectile') or
                packet.get('weapon') and packet.get('ranged') and packet.get('kind') == 'weapon')


@hook('projectile_instance')
def qualified_material_instance(engine, viewer):
    provenance = engine.damage_context()
    if provenance is None or provenance.component not in ('primary', 'payload'):
        return None
    from ..attack_delivery import current
    packet = current(engine, provenance.attacker_id, provenance.target_id, provenance.source_id, pending=True)
    profile = packet_profile(engine, viewer, packet)
    if not profile or not profile['physical']:
        return None
    return {'projectile_id': f'{provenance.attacker_id}:{provenance.roll_id}',
            'item_id': 'projectile:' + provenance.roll_id, 'item_name': 'material projectile',
            'shooter': provenance.attacker_id, 'source': provenance.source_id, 'target': provenance.target_id,
            'quantity': 1, 'unit': 'source_material', 'holdable': profile['holdable'],
            'source_cl': packet['source_cl'] if type(packet.get('source_cl')) is int else profile['source_cl'],
            'lifetime_rounds': profile['lifetime_rounds'], 'creating_roll': provenance.roll_id}


@hook('observer_information_rows')
def qualified_projectile_information(engine, viewer):
    from ..combat_world_facts import records, clock
    found = [r for r in records(engine) if r['source'] == FAMILY and r['kind'] == 'projectile_profile'
             and (r['subject'] == viewer.entity_id or viewer.entity_id in r['readers']) and r['expires_at'] > clock(engine)]
    if not found:
        return None
    return [{'viewer_id': viewer.entity_id, 'source_id': FAMILY, 'authority_actor_id': r['subject'], 'kind': 'declaration',
             'details': {'text': 'The table owner recorded a source-scoped projectile classification. It grants no attack, item, sight or identity.'}}
            for r in found]



@hook('attack_reduction_delivery')
def qualified_projectile_budget(engine, target, portion, delivery):
    if portion.get('feature') != PREFIX + 'staff_of_one' or portion.get('delivery') != 'physical_projectile':
        return None
    actor = engine.state.actors.get(portion.get('reactor'))
    if actor is None or not _rows(engine, actor, 'deflect'):
        return None
    return interceptable_packet(engine, actor, delivery)


@hook('maneuvers')
def flowing_spin_object_actions(info):
    """One granted Staff attack can select a legal native object as its target."""
    from ..gate2_runtime_models import EconomyKind
    actions, seen = [], set()
    for original in info['actions']:
        bound = original.parameters.get('object_source_weapon')
        if (original.economy != EconomyKind.ACTION or not original.parameters.get('object_attack')
                or _typed(original).get('source') != 'object_attack'):
            continue
        profile = _typed(original).get('object_attack_profile')
        if not bound or not profile or not _staff(profile) or original.owner_id != info['actor_id']:
            continue
        flow = next((row for row in info['actions'] if row.owner_id == info['actor_id'] and row.parameters.get('bojutsu_flow')
            and row.parameters.get('bojutsu_weapon') == bound
            and not row.parameters.get('bojutsu_on_turn') and not row.parameters.get('bojutsu_barrier_reach')), None)
        if flow is None:
            continue
        typed = copy.deepcopy(_typed(original))
        strike = copy.deepcopy(_typed(flow))
        typed.update(source=PREFIX+'flowing_spin', granted_attack=True,
            object_attack_profile=strike, object_weapon=copy.deepcopy(strike['weapon']),
            effects=[{'type':'object_attack','count':1}])
        rider = typed.get('object_rider')
        key = (bound, original.source_definition_id if rider else '')
        if key in seen:
            continue
        seen.add(key)
        # A native paid object rider stays a distinct, fully paid option. It
        # cannot collide with the plain granted attack or waive its own cost.
        costs = {}
        for resource, amount in (*flow.costs, *original.costs):
            costs[resource] = costs.get(resource, 0) + amount
        suffix = '#object+' + original.source_definition_id if rider else '#object'
        extra = (' Pay the selected object rider’s additional printed cost as well.' if rider else '')
        description = ('Use your Bonus Action and spend 1 Stamina for one additional Staff attack against a legal object. '
            'Requires a Staff attack made as part of this turn’s Attack action. Its normal weapon die has a d6 floor; '
            'it grants no further attack.' + extra)
        actions.append(original.model_copy(update={
            'source_definition_id':flow.source_definition_id+suffix,
            'display_name':'Flowing Spin (1 Stamina): '+original.display_name,
            'economy':EconomyKind.BONUS_ACTION,'costs':tuple(costs.items()),
            'parameters':{**original.parameters,'typed':typed,'bojutsu_flow':True,'bojutsu_weapon':bound,
                'description':description}}))
    return {'actions':actions,'rows':[]} if actions else None


@hook('object_hit')
def barrier_object_hit(ctx, obj, kind):
    """The printed self-results follow any actual Staff hit, including objects."""
    from dataclasses import replace
    from types import SimpleNamespace
    from ..object_rules import label
    profile = ctx.typed.get('object_attack_profile')
    if not profile or not _staff(profile):
        return
    barrier_hit(replace(ctx,typed=profile),
        SimpleNamespace(entity_id=obj.object_id,display_name=label(obj),active=False),'weapon')
