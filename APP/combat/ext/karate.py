"""Karate Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Karate (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "karate", "role": "focused" | "perfect_breath" | "mushin"}``; Precision Strike is a paid
unarmed-hit rider (path_riders ``paid_hit``) whose asked option is the target area; Isshun Sengeki is a typed action.

Focused Strike selects an identified Iron Fist die at the confirmed hit, before
any damage result is visible. Its paired draw is folded into that same packet.
Perfect Breath arms on committed Stomping Step and consumes on the first unarmed
attack, including a miss. Its hit bonus and player-owned rider share one use.
Mushin consumes committed scene Initiative and first-round attack events.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

PREFIX = "tianxia.subpath.body.karate.feature."
READY = "condition:typed.perfect_breath_ready"
GUARD = "condition:typed.perfect_breath_guard"


def _roles(engine: Any, actor: Any) -> set[str]:
    level = body_level(engine, actor)
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "karate" and not row.get("held_back")
            and int(row.get("required_cl") or 0) <= (int(row.get("cl") or 0) if level is None else level)}


def body_level(engine, actor):
    """The sealed native owning-Path profile, absent on historical bundles."""
    return next((int(row["cl"]) for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, ())
                 if row.get("block") == "karate_profile"), None)


def _stamp(engine: Any) -> str:
    current = engine.state.actors[engine.state.current_actor_id]
    return f"{current.entity_id}:{current.turns_started}"


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _kinds(ctx: Any) -> list[str]:
    weapon = ctx.typed.get("weapon") or {}
    return [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]


# ------------------------------------------------------------------------------------------------ Focused Strike
@hook("after_hit")
def karate_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None:
        return
    roles = _roles(engine, actor)
    if "perfect_breath" in roles and ctx.damage_cache.pop("karate.perfect_breath_hit", None) == target.entity_id:
        _perfect_breath(ctx, target)


@hook("damage_packet_selection")
def focused_pair(ctx: Any, target: Any, packet_kinds: Any) -> None:
    """Choose the normal Iron Fist die before either result is exposed.

    The native hit preparation carries an immutable attack provenance and the
    actual primary DiceSpec. Additional/critical dice never enter the menu.
    The second draw and original die settle in one pre-defense packet; there is
    no post-damage delta, extra hit, or second defense application.
    """
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id
    from ..typed_executor import on_hit_turn_key, on_hit_rider_available, spend_on_hit_rider

    engine, actor = ctx.engine, ctx.actor
    if 'focused' not in _roles(engine,actor):
        return
    target_id=getattr(target,'entity_id',None) or getattr(target,'object_id',None)
    if not target_id:
        return
    target_name=getattr(target,'display_name',None) or (getattr(target,'component',None) or {}).get('name') or 'the object'
    weapon = ctx.typed.get("weapon") or {}
    provenance, spec = ctx.attack_damage_context, ctx.attack_defense_spec
    if (provenance is None or provenance.kind != "unarmed"
            or weapon.get("damage_die_source") != "iron_fist"
            or not ctx.weapon_damage_dice or spec is None):
        return
    dice = spec.get("damage")
    if not isinstance(dice, DiceSpec) or dice.count < 1 or spec.get("fixed_damage") is not None:
        return
    key, turn = on_hit_turn_key(engine, actor, PREFIX + "focused_strike", "once per turn")
    if not on_hit_rider_available(engine, actor, key, turn, target_id):
        return
    options = [str(i) for i in range(min(dice.count, int(weapon.get("iron_fist_die_count") or 0)))]
    if not options:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "focused_strike", provenance.roll_id), actor,
        "choice:needle.focused_strike", options, allow_decline=True, target_id=target_id,
        name="Focused Strike", feature_id=PREFIX + "focused_strike",
        labels={i: f"Iron Fist die {int(i)+1}: roll d{dice.sides} twice, keep higher" for i in options},
        prompt=f"Focused Strike: {actor.display_name} hit {target_name}. Choose one Iron Fist die "
               "to roll twice and keep the higher result (once per turn; no Stamina cost).")
    if not picked or not spend_on_hit_rider(engine, actor, key, turn, target_id):
        return
    paired = engine.roller.roll(DiceSpec(count=1, sides=dice.sides, modifier=0), actor_id=actor.entity_id,
                               reason=f"FOCUSED_STRIKE:{ctx.source}")
    engine._record_roll(paired)
    spec["karate_focused_pair"] = {"die": int(picked[0]), "paired": int(paired.total)}
    engine._append_event("DAMAGE_ROLLED", PREFIX + "focused_strike", actor_id=actor.entity_id,
        target_ids=(target_id,), payload={**paired.model_dump(mode="json"), "paired_die": int(picked[0]),
                                              "attack_roll_id": provenance.roll_id})


@hook("confirmed_damage_roll_adjustment")
def focused_total(engine, actor, target, spec, intent, source, roll):
    paired = spec.pop("karate_focused_pair", None)
    if paired is None or "focused" not in _roles(engine, actor):
        return None
    original = int(roll.dice[paired["die"]])
    note(engine, PREFIX + "focused_strike", actor,
         f"Focused Strike: Iron Fist rolled {original} and {paired['paired']}; keep the higher result.",
         (getattr(target,'entity_id',None) or target.object_id,))
    return max(0, paired["paired"] - original)


# ------------------------------------------------------------------------------------------------ Perfect Breath
@hook("action_completed")
def stomping_step(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    action = engine.action_catalog.get(source_definition_id)
    origin = ((action.parameters or {}).get("typed") or {}).get("source") if action is not None else None
    if "perfect_breath" not in _roles(engine, actor) or origin != "tianxia.path.body_refining.feature.stomping_step":
        return
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == READY:
            engine._remove_condition_instance(actor, iid, PREFIX + "perfect_breath", expected=held)
    engine._apply_condition(actor, READY, PREFIX + "perfect_breath", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Perfect Breath: your next unarmed attack this turn ignores one source of Disadvantage"})


@hook("damage_roll_bonus")
def perfect_breath_damage(ctx, effect, kinds):
    """Flat PB belongs to the confirmed strike, before defenses and rounding."""
    from .attack_scope import current
    frame = current(ctx.engine)
    if (effect is not None or frame is None or frame["actor_id"] != ctx.actor.entity_id
            or frame["effect"].get("attack_kind") != "unarmed"
            or "perfect_breath" not in _roles(ctx.engine, ctx.actor)
            or not any(c.condition_id == READY for c in ctx.actor.conditions.values())
            or ctx.actor.turn_flags.get("_round_perfect_breath") == _stamp(ctx.engine)):
        return None
    ctx.actor.turn_flags["_round_perfect_breath"] = _stamp(ctx.engine)
    ctx.damage_cache["karate.perfect_breath_hit"] = ctx.target.entity_id
    return int(ctx.actor.proficiency_bonus or 2)


@hook("masked_conditions")
def breath_ignores_one(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    if not any(c.condition_id == READY for c in attacker.conditions.values()) or "perfect_breath" not in _roles(engine, attacker):
        return None
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame.get("actor_id") != attacker.entity_id or (frame.get("effect") or {}).get("attack_kind") != "unarmed":
        return None
    from ..typed_executor import CONDITION_PREFIX, rules

    table = rules()["conditions"]

    def rule(condition: Any) -> dict[str, Any]:
        return table.get(condition.condition_id[len(CONDITION_PREFIX):], {}) if condition.condition_id.startswith(CONDITION_PREFIX) else {}
    for iid, condition in sorted(attacker.conditions.items()):
        row = rule(condition)
        if row.get("attacks_have") == "DISADVANTAGE" or (row.get("attacks_others_have") == "DISADVANTAGE" and condition.source_actor_id != target.entity_id):
            return {attacker.entity_id: {iid}}
    for iid, condition in sorted(target.conditions.items()):
        row = rule(condition)
        near = engine._distance_actor_to_actor(attacker, target) <= 5
        if condition.condition_id == "condition:core.dodge" or row.get("attacked_with") == "DISADVANTAGE" \
                or (row.get("attacked_beyond_5ft") == "DISADVANTAGE" and not near) or (row.get("attacked_within_5ft") == "DISADVANTAGE" and near):
            return {target.entity_id: {iid}}
    return None


@hook("attack_resolved")
def breath_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if not _unarmed(ctx) or "perfect_breath" not in _roles(ctx.engine, ctx.actor):
        return
    for iid in [iid for iid, c in ctx.actor.conditions.items() if c.condition_id == READY]:
        ctx.actor.conditions.pop(iid)
        ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "perfect_breath", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"condition_id": READY, "instance_id": iid, "reason": "CONSUMED"})


def _perfect_breath(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    labels = {"guard": f"+1 AC against {target.display_name} until the start of {actor.display_name}'s next turn", "push": f"Push {target.display_name} 5 feet",
              "move": "Move 5 feet without provoking"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "perfect_breath", target.entity_id), actor, "choice:needle.perfect_breath", list(labels),
                 labels=labels, target_id=target.entity_id, name="Perfect Breath", prompt=f"Perfect Breath: {actor.display_name}'s {ctx.action.display_name} hit {target.display_name}. Choose one; no Action or Stamina cost.")
    choice = picked[0] if picked else "guard"
    if choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    elif choice == "move":
        from .rider_movement import routes, step

        paths = routes(engine, actor, 5)
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "perfect_breath_move", actor.entity_id), actor, "choice:needle.perfect_breath_move",
                   sorted(paths), labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline",
                   target_id=actor.entity_id, prompt="Perfect Breath: move up to 5 feet without provoking.") if paths else None
        if pick and pick[0] in paths:
            step(engine, actor, paths[pick[0]], PREFIX + "perfect_breath")
    else:
        for iid, held in list(actor.conditions.items()):
            if held.condition_id == GUARD:
                engine._remove_condition_instance(actor, iid, PREFIX + "perfect_breath", expected=held)
        engine._apply_condition(actor, GUARD, PREFIX + "perfect_breath", actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"against": target.entity_id, "label": f"Perfect Breath: +1 AC against {target.display_name}"})


@hook("hit_response")
def breath_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = next((c for c in target.conditions.values() if c.condition_id == GUARD and (c.data or {}).get("against") == attacker.entity_id), None)
    if held is None or "perfect_breath" not in _roles(engine, target) or natural == 20 or total >= effective_ac + 1:
        return None
    note(engine, PREFIX + "perfect_breath", target, f"Perfect Breath: +1 AC turns {attacker.display_name}'s attack into a miss.", (attacker,))
    return effective_ac + 1, False


# --------------------------------------------------------------------------------------------------------- Mushin
@hook("attack_roll_modes")
def mushin_first_attack(engine, actor, target):
    if (engine.state.round_number == 1 and "mushin" in _roles(engine, actor)
            and conscious(actor) and not actor.turn_flags.get("_round_mushin_first")):
        return ["ADVANTAGE"]
    return None


@hook("initiative_modes")
def mushin_initiative(engine, actor):
    return ["ADVANTAGE"] if "mushin" in _roles(engine, actor) and conscious(actor) else None


def conscious(actor):
    return actor.active and actor.current_hp > 0 and actor.life_state not in {"DYING", "STABLE", "DEAD"} and not any(
        c.condition_id in {"condition:typed.unconscious", "condition:core.unconscious"} for c in actor.conditions.values())


@hook("event")
def mushin_events(engine, event_type, kwargs):
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or "mushin" not in _roles(engine, actor):
        return
    if event_type == "ATTACK_ROLLED" and engine.state.round_number == 1:
        actor.turn_flags["_round_mushin_first"] = 1


@hook('match_start')
def mushin_scene_initiative(engine):
    """Settle the recorded scene Initiative after validated starting pools.

    Custom roster genesis applies its owner's starting resource choices after
    Initiative is drawn. Resolve this event-derived restoration before sealing
    genesis, rather than losing it when those starting pools are installed.
    It is independent of the four consciousness-qualified passive benefits.
    Reopening a fight restores its sealed state; it never creates Initiative.
    """
    rolled = {e.actor_id for e in engine.events if e.event_type == 'INITIATIVE_ROLLED'}
    for actor_id in sorted(rolled):
        actor = engine.state.actors.get(actor_id)
        if actor is None or 'mushin' not in _roles(engine, actor) or actor.turn_flags.get('_round_mushin_stamina'):
            continue
        profile=next((row for row in engine.typed_passive_rows.get(actor_id,()) if row.get('block')=='karate_profile'),{})
        if profile.get('scene_prior_initiative'):
            actor.turn_flags['_round_mushin_first']=1
            actor.turn_flags['_round_mushin_stamina']=1
            continue
        actor.turn_flags['_round_mushin_stamina'] = 1
        room = actor.resource_maximums.get('resource:core.stamina', 0) - actor.resources.get('resource:core.stamina', 0)
        if room > 0:
            engine._gain_resource(actor, 'resource:core.stamina', min(2, room), PREFIX + 'mushin')


@hook("condition_immune")
def mushin_surprise(engine, actor, name):
    if str(name).lower() == "surprised" and "mushin" in _roles(engine, actor) and conscious(actor):
        return True
    return None


@hook("save")
def mushin_movement_save(ctx, actor, ability, named):
    if (ctx is not None and "mushin" in _roles(ctx.engine, actor) and conscious(actor)
            and "category:immediate_bodily_control" in named):
        return {"modes": ["ADVANTAGE"]}
    return None


@hook('save_mode')
def mushin_native_movement_save(engine,actor,ability,dc,source_id,context):
    """Native source producers carry the same explicit purpose as typed saves."""
    if ('mushin' in _roles(engine,actor) and conscious(actor)
            and 'category:immediate_bodily_control' in (context.get('named') or ())):
        return 'ADVANTAGE'
    return None


@hook('compile_bundle')
def isshun_object_action(bundle, info):
    """Publish the same paid Action against an actual bounded, unattended object.

    A sibling candidate shares the original resource/use counters and unarmed
    profile; it grants no additional action, new weapon, or ownership of a prop.
    """
    from copy import deepcopy
    paths = info['owner_sheet'].get('path_and_subpath') or {}
    # Consume compiler-admitted ownership, including the native sheet's earned
    # feature occurrences. Historical sheets may instead list Path feature IDs.
    # The compiled rows already passed the ordinary ownership intake; this is
    # not a second grant or an invented acquisition receipt.
    owned = {row.get('feature_id') for row in bundle['typed_passives']
             if str(row.get('feature_id') or '').startswith(PREFIX)}
    owned.update((action.get('parameters', {}).get('typed') or {}).get('source')
                 for action in bundle['action_catalog']
                 if str((action.get('parameters', {}).get('typed') or {}).get('source') or '').startswith(PREFIX))
    if not owned:
        return bundle
    body = next((row for row in paths.get('paths') or [] if row.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None:
        cl = int(body.get('effective_cl') or 0)
    else:
        names_body = str((info['owner_sheet'].get('identity') or {}).get('path') or '').lower() == 'body refining'
        names_body = names_body or 'tianxia.path.body_refining' in (paths.get('path_record_ids') or [])
        cl = int(info['numbers']['cl']) if names_body else 0
    bundle['typed_passives'].append({'block': 'karate_profile', 'cl': cl})
    for passive in bundle['typed_passives']:
        if passive.get('feature_id') in owned:
            passive['cl'] = cl
    actions = bundle['action_catalog']
    for action in actions:
        typed = action.get('parameters', {}).get('typed') or {}
        if typed.get('source') in owned:
            typed['numbers']['cl'] = cl
        if typed.get('source') == PREFIX+'isshun_sengeki':
            # This is its own Action, never the ordinary Attack action. Shared
            # Extra Attack modifiers must not multiply the printed single strike.
            typed.pop('attack_action', None)
            for effect in typed.get('effects') or []:
                if effect.get('type') == 'attack':
                    effect['count'] = 1
                    effect.pop('count_by_cl', None)
    for original in list(actions):
        typed = original.get('parameters', {}).get('typed') or {}
        if typed.get('source') != PREFIX + 'isshun_sengeki' or original.get('target_kind') == 'OBJECT':
            continue
        row = deepcopy(original)
        row.update(source_definition_id=original['source_definition_id']+'#karate_object',
                   display_name='Isshun Sengeki (at an object or structure)', target_kind='OBJECT')
        row['parameters']['karate_object_strike'] = True
        row['parameters'].pop('player_only', None)
        actions.append(row)
        bundle['actor_template']['action_ids'].append(row['source_definition_id'])
    return bundle


@hook('object_targets')
def isshun_objects(engine, actor, action):
    if (action.owner_id != actor.entity_id or not action.parameters.get('karate_object_strike')
            or action.source_definition_id not in actor.action_ids):
        return None
    from ..object_rules import has_tag
    categories=('temporary_barrier','vehicle','structure','terrain_section','formation_anchor')
    return [obj.object_id for obj in engine.state.objects.values()
            if not obj.destroyed and obj.ac is not None and obj.current_hp is not None
            and (obj.unattended or any(has_tag(obj,tag) for tag in categories))]


@hook('object_action')
def isshun_at_object(engine, actor, action, obj, candidate, intent):
    if not action.parameters.get('karate_object_strike') or obj.object_id not in (isshun_objects(engine, actor, action) or []):
        return None
    from ..typed_executor import Context, resolve_attack_damage
    from ..gate2_runtime_models import DiceSpec
    from .objects import roll_technique_attack, prepare_damage_dice, deal

    ctx = Context(engine, actor, action, intent, action.parameters['typed'], [], None, {})
    ctx.damage_cache['_object'] = obj
    from . import run_strict
    from ..typed_executor import activation_reactions
    from ..attack_completion import can_continue
    run_strict('technique_accepted', engine, actor, action)
    if any(reply is True for reply in run_strict('technique_start', engine, actor, action)):
        return True
    if not can_continue(engine, actor) or not activation_reactions(ctx):
        return True
    obj = engine.state.objects.get(obj.object_id)
    if obj is None or obj.destroyed:
        return True  # a counter removed the target; the declared cost stays spent
    hit, natural = roll_technique_attack(ctx, obj)
    if not hit:
        run_strict('technique_used', ctx)
        return True  # declaration already spent Action, 8 Stamina and scene use
    attack = next(e for e in ctx.typed['effects'] if e['type'] == 'attack')
    dice, kinds, _, _, _ = resolve_attack_damage(ctx, attack)
    # Each printed component gets its own damage type; one combined instance is
    # submitted to native Immunity/Threshold/Resistance, then doubled once.
    packets = []
    if isinstance(dice, DiceSpec):
        # Bind the same family consumer to the actual native object attack
        # event. This is its recorded roll, not a caller-supplied hit receipt.
        from ..damage_context import AttackDamage
        event=next(event for event in reversed(engine.events)
            if event.event_type=='ATTACK_ROLLED' and event.actor_id==actor.entity_id
            and event.source_definition_id==ctx.source and event.target_ids==(obj.object_id,))
        payload=event.payload
        spec={'damage':dice}
        ctx.attack_damage_context=AttackDamage(ctx.source,actor.entity_id,obj.object_id,1,
            payload['roll_id'],natural,payload['modified_total'],natural==20,kind='unarmed')
        ctx.attack_defense_spec=spec
        focused_pair(ctx,obj,('weapon',))
        dice = prepare_damage_dice(ctx, dice, None, kinds)
        roll = engine.roller.roll(dice, actor_id=actor.entity_id, reason='DAMAGE:'+ctx.source, critical=natural == 20)
        engine._record_roll(roll)
        total=roll.total+(focused_total(engine,actor,obj,spec,intent,ctx.source,roll) or 0)
        engine._append_event('DAMAGE_ROLLED', ctx.source, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                            payload={**roll.model_dump(mode='json'), 'critical': natural == 20,'combined_total':total})
        packets.append((total, str(kinds[0]).upper()))
    force = engine.roller.roll(DiceSpec(count=10, sides=10, modifier=0), actor_id=actor.entity_id,
                               reason='DAMAGE:'+ctx.source+':Force', critical=natural == 20)
    engine._record_roll(force)
    engine._append_event('DAMAGE_ROLLED', ctx.source, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                        payload={**force.model_dump(mode='json'), 'critical': natural == 20})
    packets.append((force.total, 'FORCE'))
    # The native editor/producers explicitly record artifact protection. Never
    # infer it from a prop's display name or from how much damage it has taken.
    protected = bool((obj.component or {}).get('artifact'))
    deal(engine, actor, obj, packets, ctx.source, multiplier=2,
         ignore_resistance_types=() if protected else ('FORCE',))
    run_strict('technique_used', ctx)
    return True


@hook('reaction_redirect_allowed')
def isshun_redirection(engine, attacker, reactor, feature_id, source_cl, context):
    action = engine.action_catalog.get(context.get('source_id'))
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    if (typed.get('source') != PREFIX + 'isshun_sengeki' or action.owner_id != attacker.entity_id
            or type(source_cl) is not int):
        return None
    cl = int((typed.get('numbers') or {}).get('cl') or 0)
    return source_cl >= cl


@hook('candidate_allowed')
def karate_level_gate(engine, actor, candidate, action):
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    if typed.get('source') != PREFIX + 'isshun_sengeki':
        return None
    level = body_level(engine, actor)
    return level is None or level >= 18


@hook('compile_resource_definitions')
def karate_starting_stamina(resources, info):
    """Retain declared current Stamina; omitted current preserves legacy starts."""
    if not any(str(mid).startswith(PREFIX) for mid in info['owned_ids']):
        return resources
    pool = (info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('primary_resource') or {}
    paths = (info['owner_sheet'].get('path_and_subpath') or {}).get('paths') or []
    body = next((path for path in paths if path.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None and (body.get('resource') or {}).get('current') is not None:
        pool = body['resource']
    elif str(pool.get('name') or '').lower() != 'stamina':
        return resources
    if pool.get('current') is None:
        return resources
    current = pool['current']
    stamina = next((r for r in resources if r.resource_id == 'resource:core.stamina'), None)
    if stamina is None or type(current) is not int or not 0 <= current <= stamina.maximum:
        raise ValueError('Starting Stamina must be a whole number from 0 to its maximum.')
    return [r.model_copy(update={'initial': current}) if r is stamina else r for r in resources]


@hook('condition_application_attempt')
def precision_refresh(engine, target, condition_id, source_id, source_actor_id):
    """Reapplication refreshes this practitioner's same named impairment."""
    if source_id != PREFIX+'precision_strike' or condition_id not in {
            'condition:typed.next_weapon_attack_penalty','condition:typed.reaction_denied','condition:typed.save_against'}:
        return None
    for iid,held in list(target.conditions.items()):
        if held.condition_id == condition_id and held.source_definition_id == source_id and held.source_actor_id == source_actor_id:
            engine._remove_condition_instance(target, iid, source_id, expected=held)
    return None


@hook('state_event')
def karate_stamina_zero(engine, event):
    """Native positive spending to zero, using the shared Exhaustion implementation."""
    if event.event_type != 'RESOURCE_SPENT':
        return
    payload=event.payload or {}
    actor=engine.state.actors.get(event.actor_id)
    if (actor is None or body_level(engine,actor) is None or payload.get('resource_id') != 'resource:core.stamina'
            or type(payload.get('amount')) is not int or payload['amount'] <= 0 or payload.get('remaining') != 0):
        return
    from .forged_exhaustion import level, set_level
    set_level(engine, actor, level(actor)+1, 'tianxia.path.body_refining.stamina')
