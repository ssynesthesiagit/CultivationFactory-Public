"""Stone Fist riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Stone Fist (Breaking Fist, Overwhelming Blow, Shattering Palm, Earth-Shattering Fist,
Heaven-Cracking Blow and their Normalized Procedures). The hit riders are path_riders.py ``paid_hit`` rows (asked, paid, limited
there); this module supplies their effects:

stone_fist_mark        marks the activation (Overwhelming Blow's collisions belong to it alone)
overwhelming_step_in   "Push the target 5 feet and enter its former space": the push, then, if it left, you move into the space
                       (Opportunity Attacks from other creatures still apply; the target's do not)
heaven_cracking        + 10d10 Bludgeoning or Force; against a target whose established Source CL is no higher than yours
                       it ignores Resistance to both types; absent cultivation numbers are not evidence of mundane origin
break_the_guard        Shattering Palm's creature form: a Constitution save; failure: AC - 2 for 1 minute, repeating the save at
                       the end of each of its turns; success: AC - 1 until the start of your next turn. Never stacks: a new
                       failure replaces the old reduction, a success never shortens or weakens a standing failure.
Overwhelming Blow's collisions (hook ``collision``): stopped by a solid surface, the target takes Proficiency Bonus Bludgeoning;
driven into a creature, that creature makes a Dexterity save: on a failure both take it, on a success only the target. Each
creature takes it once per activation. Every hook returns early without a matching marker, modifier or flag.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.stone_fist.feature."
PALM = PREFIX + "shattering_palm"
GUARD_FLAG = "_round_shattering_palm_guard"  # kept across turns ("_round_" keys survive the turn reset)


@effect('stone_fist_choose_damage')
def choose_damage(ctx: Any, row: dict[str, Any]) -> None:
    """Earth-Shattering Fist commits its type before any recipient saves."""
    from ..typed_executor import choose_damage_type
    choose_damage_type(ctx, ['BLUDGEONING', 'FORCE'], ctx.targets)


@hook('damage_type_choice')
def damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    source = str(ctx.typed.get('source') or '')
    feature = str(getattr(ctx, 'source', '') or source)
    eligible = {PALM, PREFIX+'earth_shattering_fist', PREFIX+'heaven_cracking_blow'}
    if feature not in eligible and source not in eligible:
        return None
    if not {'BLUDGEONING', 'FORCE'}.issubset(set(kinds)):
        return None
    if 'stone_fist_damage_type' in ctx.damage_cache:
        return ctx.damage_cache['stone_fist_damage_type']
    from .needle import ask, checkpoint_id
    from .. import senses, typed_reactions
    known = [target for target in targets if senses.perceives(ctx.engine, ctx.actor, target)]
    preferred = max(kinds, key=lambda kind: sum(typed_reactions.damage_factor(
        ctx.engine, target, kind, ctx.damage_source, ctx.actor.entity_id) for target in known))
    if feature not in eligible:feature=source
    name,cost,limit={PALM:('Shattering Palm — Fracture the Structure',3,'once per turn'),
        PREFIX+'earth_shattering_fist':('Earth-Shattering Fist',4,'Action'),
        PREFIX+'heaven_cracking_blow':('Heaven-Cracking Blow',7,'once per scene')}[feature]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'stone_fist_damage', ctx.actor.entity_id),
                 ctx.actor, 'choice:needle.stone_fist_damage', kinds,
                 labels={kind: kind.title()+' damage' for kind in kinds}, preferred=[preferred],
                 prompt=f'{ctx.actor.display_name}: {name} ({cost} Stamina; {limit}). Choose Bludgeoning or Force for this activation’s instant damage.')
    ctx.damage_cache['stone_fist_damage_type'] = chosen[0] if chosen else preferred
    note(ctx.engine, feature, ctx.actor,
         f'{ctx.actor.display_name} chooses {ctx.damage_cache["stone_fist_damage_type"].title()} damage for {name}.',
         damage_type=ctx.damage_cache['stone_fist_damage_type'])
    return ctx.damage_cache['stone_fist_damage_type']


def _cl(engine: Any, actor_id: str) -> int | None:
    """Read committed cultivation numbers; an unprofiled creature is unknown."""
    from ..observer_information import source_numbers
    value = source_numbers(engine, '', actor_id).get('cl')
    if value is None:
        # Native summoned Assets inherit the creating feature's Source CL,
        # not a guess from their names, damage types or current attacks.
        record = getattr(engine, 'summon_records', {}).get(actor_id) or {}
        if record.get('source') and record.get('owner'):
            value = source_numbers(engine, record['source'], record['owner']).get('cl')
    return value if type(value) is int and value >= 0 else None


def admitted_source_comparison(ctx: Any, target: Any, feature: str, own: int) -> bool:
    """Collect an unprofiled defender's native owner input for this activation.

    This cannot override committed cultivation numbers. The controller supplies
    the missing defending profile, not consent or a new feature grant. An AI
    with no profile has no known automatic answer; refusal establishes no CL.
    Values above the supported Body progression are a comparison bound, never
    a fabricated exact CL. Native accepted choices, conditions and replay own
    the declaration, and only its subject and the feature owner may read it.
    """
    from ..fact_consent_admission import admit_choice
    from .effect_durations import token
    current=ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    options=[str(level) for level in range(21)]+['above_20']
    labels={str(level):f'Defending Source CL {level}'+(' (mundane)' if level==0 else '') for level in range(21)}
    labels['above_20']='Defending Source CL above 20'
    record=admit_choice(ctx,target,feature,'stone_fist_defending_source_cl',ctx.intent.intent_id,
        options,labels=labels,
        prompt=f"{target.display_name}'s controller: supply its missing defending Source CL for Stone Fist (feature Source CL {own}); 0 means mundane. Decline if unknown. This does not replace committed cultivation numbers.",
        expires_on=token('end',current.entity_id,current.turns_started),readers=(ctx.actor.entity_id,),
        automatic_options=())
    return bool(record and record['value']!='above_20' and int(record['value'])<=own)


@effect("stone_fist_mark")
def stone_fist_mark(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_stone_fist"] = str(row.get("feature") or "")


# -------------------------------------------------------------------------------------------------- Overwhelming Blow
@effect("overwhelming_step_in")
def overwhelming_step_in(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..movement_paths import resolve

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    former = target.position
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    if target.position == former or not actor.active:
        return  # "only if the target actually leaves that space"
    if not engine.grid.placement_legal(former, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    start = actor.position
    if engine.grid.distance_ft(start, former) > engine.grid.square_size_ft:
        return
    from ..granted_movement import path_cost
    path=[start,former]
    try:
        cost=path_cost(engine,actor,path)
    except ValueError:
        return  # the push remains resolved if self-movement is illegal
    # The printed grant enters that space; it does not limit the self-move's
    # terrain/drag price to five feet or spend ordinary movement.
    resolve(engine,actor,path,PREFIX+'overwhelming_blow',kind='granted',feet=cost,
            intent=ctx.intent,provokes=True,ignore_oa_from=(target.entity_id,))



@hook("collision")
def overwhelming_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    if ctx.damage_cache.get("_stone_fist") != "overwhelming" or target is None or not target.active:
        return
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    pb = int(actor.proficiency_bonus or 2)
    done = ctx.damage_cache.setdefault("_stone_fist_collided", [])
    spot = (blocked_at.x, blocked_at.y)
    other = next((c for c in engine.state.actors.values() if c.active and c.entity_id != target.entity_id and spot in engine._actor_cells(c)), None)
    slam = {"type": "damage", "applies_to": "target", "flat": pb, "damage_types": ["bludgeoning"], "evidence": "Overwhelming Blow: collision"}
    if other is None:
        from .objects import blocker_at
        if not engine.grid.in_bounds(spot):
            return  # the edge of a mapped scene does not establish a wall
        physical = (blocker_at(engine,blocked_at) is not None
                    or engine.grid.terrain_at(blocked_at,'BLOCKED')
                    or not engine.grid.line_of_physical_transmission(target.position,blocked_at))
        if not physical:
            return
        if target.entity_id not in done:
            done.append(target.entity_id)
            note(engine, PREFIX + "overwhelming_blow", actor, f"Overwhelming Blow: {target.display_name} slams into a solid surface.", (target.entity_id,))
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}), [slam])
        return
    note(engine, PREFIX + "overwhelming_blow", actor, f"Overwhelming Blow: {target.display_name} is driven into {other.display_name}.",
         (target.entity_id, other.entity_id))
    box: dict[str, Any] = {}
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [other], other, box)
    te.run_effects(sub, [{"type": "save", "ability": "dex", "evidence": "Overwhelming Blow: the second creature's Dexterity saving throw",
                          "on_fail": [{"type": "stone_fist_flag"}], "on_success": []}])
    for creature in ([target, other] if box.get("_stone_fist_failed") else [target]):
        if creature.active and creature.entity_id not in done:
            done.append(creature.entity_id)
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {}), [slam])


@effect("stone_fist_flag")
def stone_fist_flag(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_stone_fist_failed"] = True  # the second creature failed its Dexterity save


# ------------------------------------------------------------------------------------------------ Heaven-Cracking Blow
# Per-delivery scope, restored on nested reactions and human controller pauses.
from contextvars import ContextVar
_PACKET = ContextVar('stone_fist_packet', default=None)


def _additional(ctx, row, count, sides, *, heaven=False):
    from dataclasses import replace
    from .. import typed_executor as te
    from .creature_kinds import matches
    from .objects import deal, recipient_context
    obj = ctx.engine.state.objects.get(row.get('recipient_object_id'))
    target = obj or ctx.target
    if target is None or (obj is not None and obj.destroyed):
        return
    feature = PREFIX + ('heaven_cracking_blow' if heaven else 'shattering_palm')
    # A body refinement's feature Source CL is its effective Body level, never
    # a defender's display name, armor, damage type or absence of combat activity.
    own = body_level(ctx.engine, ctx.actor)
    target_cl = ((obj.component or {}).get('source_cl', None if (obj.component or {}).get('artifact') or (obj.component or {}).get('created_by') else 0) if obj is not None
                 else _cl(ctx.engine, target.entity_id))
    pierce = type(target_cl) is int and target_cl <= own
    if obj is None and target_cl is None:
        pierce=admitted_source_comparison(ctx,target,feature,own)
    protected = obj is not None and bool((obj.component or {}).get('artifact'))
    # Attached damage retains the real attack's catalog/defense identity;
    # with_source carries the named feature only in native display metadata.
    typed = {**ctx.typed, 'numbers': {**ctx.numbers, 'cl': own}}
    sub = replace(ctx, typed=typed, damage_cache={}).with_source(feature)
    if ctx.target is not None:
        sub = ctx.on_hit_context(ctx.target, typed=typed, damage_cache={}).with_source(feature)
    effect = {'type': 'extra_damage', 'applies_to': 'target', 'dice': {'count': count, 'sides': sides},
              'damage_types': ['bludgeoning', 'force'], 'evidence': 'Heaven-Cracking Blow' if heaven else 'Fracture the Structure'}
    if obj is not None:
        sub = recipient_context(sub,obj)
        # One additional packet: the triggering attack retains its own threshold.
        amount, kind = te._damage_roll(sub, effect)
        deal(ctx.engine, ctx.actor, obj, [(amount, kind)], sub.damage_source, display_source_id=feature,
             ignore_threshold=pierce and not protected,
             ignore_resistance_types=('BLUDGEONING','FORCE') if pierce and not protected else (),
             multiplier=2 if (heaven and pierce) or breaking_object(ctx.engine,ctx.actor,obj) else 1)
    else:
        frame = (ctx.engine, ctx.actor.entity_id, target.entity_id, sub.damage_source, pierce,
                 getattr(sub.attack_damage_context,'roll_id',None))
        token = _PACKET.set(frame)
        try:
            if heaven and pierce and matches(target, 'construct'):
                amount, kind = te._damage_roll(sub, effect)
                te._deal(sub, target, amount*2, kind)
            else:
                te.run_effects(sub, [effect])
        finally:
            _PACKET.reset(token)


@effect('stone_fist_fracture')
def fracture(ctx, row):
    _additional(ctx, row, 7 if body_level(ctx.engine,ctx.actor) >= 17 else 5, 8)


@effect('heaven_cracking')
def heaven_cracking(ctx, row):
    _additional(ctx, row, 10, 10, heaven=True)


@hook('resistance_ignored')
def heaven_cracking_pierces(engine, kind, typed, source_actor_id, target=None):
    from .damage_delivery import identity
    frame = _PACKET.get()
    attack = engine.damage_context()
    if (frame and frame[0] is engine and frame[1] == source_actor_id
            and target is not None and frame[2] == target.entity_id
            and identity(engine) in ('',frame[3]) and frame[4]
            and (attack is None or (attack.roll_id==frame[5] and attack.component=='rider'))
            and str(kind).upper() in ('BLUDGEONING','FORCE')):
        return True
    return None


@effect('stone_fist_heaven_control')
def heaven_control(ctx, row):
    if ctx.target is not None:
        from ..typed_executor import run_effects
        run_effects(ctx, row['effects'])


# ------------------------------------------------------------------------------------------ Shattering Palm: Break the Guard
def _guard(target: Any) -> list[tuple[str, Any]]:
    return [(mid, m) for mid, m in target.modifiers.items() if m.source_definition_id == PALM and m.target_field == "armor_class"]


def _drop_guard(engine: Any, target: Any, reason: str) -> None:
    for mid, _m in _guard(target):
        del target.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", PALM, actor_id=target.entity_id, target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": reason})
    target.turn_flags.pop(GUARD_FLAG, None)


@effect("break_the_guard")
def break_the_guard(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Shattering Palm (Break the Guard): Constitution saving throw",
                          "on_fail": [{"type": "break_the_guard_result", "failed": True}], "on_success": [{"type": "break_the_guard_result", "failed": False}]}])


@effect("break_the_guard_result")
def break_the_guard_result(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .effect_durations import token

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    failed = bool(row.get("failed"))
    standing = [m for _mid, m in _guard(target)]
    if not failed and any(int(m.value) <= -2 for m in standing):
        from .effect_durations import parse_round, token
        from .retained_updates import record_instance_update
        slot=engine.state.initiative_order.index(owner.entity_id)
        next_start=(engine.state.round_number+int(slot<=engine.state.current_slot_index),slot)
        for modifier in standing:
            old=parse_round(modifier.expires_on)
            if old is not None and next_start>old:
                modifier.expires_on=token('start',owner.entity_id,int(owner.turns_started)+1)
                record_instance_update(engine,target,'modifier',modifier.modifier_id,modifier)
        return  # retain the stronger magnitude and its repeated-save procedure
    _drop_guard(engine, target, "REPLACED")
    if failed:
        engine._add_modifier(target, PALM, "armor_class", "ADD", -2, "ALWAYS", expires_on=te.clock_expiry(engine, "minutes", 1), source_actor_id=owner.entity_id)
        target.turn_flags[GUARD_FLAG] = {"dc": int(ctx.numbers.get("save_dc") or 10), "owner": owner.entity_id, "cl": int(ctx.numbers.get("cl") or 0)}
    else:
        expires = "START_OF_SOURCE_NEXT_TURN" if engine.state.current_actor_id == owner.entity_id else token("start", owner.entity_id, int(owner.turns_started) + 1)
        engine._add_modifier(target, PALM, "armor_class", "ADD", -1, "ALWAYS", expires_on=expires, source_actor_id=owner.entity_id)


@hook("turn_end")
def guard_repeat_save(engine: Any, actor: Any) -> None:
    """"It repeats the save at the end of each turn, ending the reduction on a success" (the affected creature's turns)."""
    record = actor.turn_flags.get(GUARD_FLAG)
    if not record:
        return
    if not any(int(m.value) <= -2 for _mid, m in _guard(actor)):
        actor.turn_flags.pop(GUARD_FLAG, None)  # it ran out
        return
    from .. import typed_executor as te
    from .states import context

    owner = engine.state.actors.get(str(record.get("owner") or "")) or actor
    ctx = context(engine, owner, PALM, [actor], {"save_dc": int(record.get("dc") or 10)}).with_source(PALM)
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Shattering Palm: repeated Constitution saving throw",
                          "on_fail": [], "on_success": [{"type": "break_the_guard_end"}]}])


@effect("break_the_guard_end")
def break_the_guard_end(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        _drop_guard(ctx.engine, ctx.target, "SAVED")


PARENT = PREFIX.removesuffix('.feature.')
LEVELS = dict(zip(('breaking_fist','overwhelming_blow','shattering_palm','earth_shattering_fist','heaven_cracking_blow'),(3,6,10,14,18)))


def body_level(engine, actor):
    """The source-scoped effective Body level sealed from the actual sheet."""
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, ()) if r.get('block') == 'stone_fist_profile'), None)
    return int(row['cl']) if row is not None else _cl(engine,actor.entity_id)


@hook('compile_bundle')
def stone_profile(bundle, info):
    paths = info['owner_sheet'].get('path_and_subpath') or {}
    owned = [r for r in bundle.get('typed_passives',()) if str(r.get('feature_id') or '').startswith(PREFIX)]
    actions = [a for a in bundle['action_catalog'] if str((a['parameters'].get('typed') or {}).get('source') or '').startswith(PREFIX)]
    if not owned and not actions:
        return bundle
    body = next((r for r in paths.get('paths',()) if r.get('path_id') == 'tianxia.path.body_refining'), None)
    # Legacy typed builds already admitted the feature and use their one CL.
    # Native multi-Path sheets always bind the independent Body attainment.
    level = int(body.get('effective_cl', body.get('attainment',0))) if body is not None else int(info['numbers']['cl'])
    from .stone_fist_acquisition import body_parents
    if body_parents(paths)-{PARENT}:
        # A committed different Body school owns the slot. Stale or forged
        # feature IDs cannot keep the previous school's active progression.
        bundle['typed_passives']=[r for r in bundle['typed_passives']
            if not str(r.get('feature_id') or '').startswith(PREFIX)]
        removed={a['source_definition_id'] for a in actions}
        bundle['action_catalog']=[a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]
        bundle['actor_template']['action_ids']=[mid for mid in bundle['actor_template']['action_ids'] if mid not in removed]
        return bundle
    bundle['typed_passives'].append({'block':'stone_fist_profile','cl':level})
    if level>=10:
        # The unprofiled defender's human controller must also be reachable
        # when the feature owner is acting on an automatic/AI turn.
        from .path_riders import is_unarmed_attack
        for action in bundle['action_catalog']:
            typed=action['parameters'].get('typed') or {}
            if is_unarmed_attack(typed):typed['manual_inline_choice']=True
    for row in owned:
        row['cl'] = level
        if row.get('kind') == 'paid_hit':
            row['save_dc'] = int(info['numbers']['save_dc'])
    # Realm suppression removes availability, preserving the earned source IDs.
    bundle['typed_passives'] = [r for r in bundle['typed_passives']
        if not str(r.get('feature_id') or '').startswith(PREFIX)
        or level >= LEVELS.get(r['feature_id'].removeprefix(PREFIX),0)]
    removed={a['source_definition_id'] for a in actions
             if level < LEVELS.get(a['parameters']['typed']['source'].removeprefix(PREFIX),0)}
    bundle['action_catalog']=[a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]
    bundle['actor_template']['action_ids']=[mid for mid in bundle['actor_template']['action_ids'] if mid not in removed]
    return bundle


@hook('paid_hit_allowed')
def stone_hit_allowed(ctx, target, row):
    feature = row.get('feature_id','')
    if feature.startswith(PREFIX):
        if hasattr(target,'object_id') and any((target.component or {}).get(key) for key in ('world_scale','unattackable')):
            return False
        return body_level(ctx.engine,ctx.actor) >= LEVELS.get(feature.removeprefix(PREFIX),99)
    return None


@hook('paid_hit_options')
def stone_forms(options, ctx, target, row):
    if row.get('feature_id') != PALM:
        return None
    from .creature_kinds import matches
    obj = hasattr(target,'object_id')
    return [option for option in options if
        (option['label'] == 'Break the Guard' and not obj)
        or (option['label'] == 'Fracture the Structure' and (obj or matches(target,'construct')))]


@hook('object_hit')
def stone_object_hit(ctx, obj, kind):
    if kind != 'unarmed':
        return
    from .path_riders import offer_paid_hit
    offer_paid_hit(ctx, obj, kind, object_recipient=True)


def breaking_object(engine, actor, obj):
    """The existing Breaking Fist ownership row and explicit bounded profile."""
    from ..object_rules import has_tag
    return (any(r.get('feature_id') == PREFIX+'breaking_fist' for r in engine.typed_passive_rows.get(actor.entity_id,()))
            and not any(has_tag(obj,t) for t in ('world_scale','unattackable'))
            and (obj.unattended or has_tag(obj,'formation_anchor')))


@hook('event')
def stone_stamina_empty(engine,event_type,kwargs):
    """Consume actual zero transitions for this family's acquired Body profile."""
    payload=kwargs.get('payload') or {}
    source=kwargs.get('source_definition_id') or kwargs.get('source_id') or ''
    if (event_type!='RESOURCE_SPENT'
            or payload.get('resource_id')!='resource:core.stamina'
            or not payload.get('amount') or payload.get('remaining')!=0):
        return
    actor=engine.state.actors.get(kwargs.get('actor_id'))
    if actor is not None and any(r.get('block')=='stone_fist_profile' for r in engine.typed_passive_rows.get(actor.entity_id,())):
        from .forged_exhaustion import add
        add(engine,actor,1,source)
