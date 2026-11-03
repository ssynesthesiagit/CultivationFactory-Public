"""Source-owned Bone Monarch progression and native table/journey consumers.

Restricted acquisition is projected by the shared acquisition adapter. A sealed
family profile supplies owning-Body numbers and access. Critical cancellation
precedes dice; Marrow choices name exact condition instances and retain source
authority; Bone Guard consumes the source-profiled Asset actor contract. The
cocoon is an independently damaged Body Asset, never the owner's Temporary HP.
Only the printed family and its own persisted states activate these consumers.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.bone_monarch.feature."
COCOON = "condition:typed.bone_cocoon"
PHYSICAL_TYPES = ("BLUDGEONING", "PIERCING", "SLASHING")
UNBROKEN_SAVE_CAUSES = frozenset({'broken_bone', 'crushed_limb', 'bodily_deformation',
                                'physical_paralysis', 'forced_bodily_transformation',
                                'body_breaking', 'body_liquefaction'})
BLOCK = 'bone_monarch'
LEVELS = {'bone_armor': 3, 'marrow_regeneration': 6, 'bone_guard_manifestation': 10,
          'unbroken_bones': 14, 'unbroken_bones#marrow_memory': 14, 'sovereign_reconstruction': 18}
SCENE_USE = 'condition:typed.bone_monarch_scene_use'


@hook('compile_bundle')
def family_profile(bundle, info):
    """Seal the acquired Body progression and owning Path numbers once.

    Runtime consumers use this persisted native profile; no character-sheet
    lookup on reload and no acquisition inferred from creature names or damage.
    """
    from copy import deepcopy
    from ..activation_settlement import path_numbers
    from ..subpath_acquisition import acquired_features
    from pathlib import Path
    found = {r.get('feature_id', '') for r in [*bundle.get('typed_reactions', []), *bundle.get('typed_passives', [])]}
    found.update((a.get('parameters', {}).get('typed') or {}).get('source', '') for a in bundle['action_catalog'])
    # No-Action replacements with a custom effect need no independently usable
    # catalogue action. Ownership comes from the same native acquisition adapter
    # as the compiler, rather than from whether a generic executor accepted it.
    found.update(acquired_features(info['owner_sheet'], Path(__file__).resolve().parents[2]))
    subpaths = info['owner_sheet'].get('path_and_subpath') or {}
    found.update(subpaths.get('path_feature_record_ids', []))
    # NS1R admission records the source-granted subpath records here; the compiler
    # reads the same list, so a custom-effect-only feature stays owned on reload.
    found.update(subpaths.get('source_granted_subpath_feature_record_ids', []))
    # The authority compiler splits the passive half from Marrow Memory.
    # Normalize only that passive atom; owning Memory alone grants no passive.
    passive_atom = PREFIX + 'unbroken_bones#bones'
    canonical = lambda fid: PREFIX + 'unbroken_bones' if fid == passive_atom else fid
    found = {canonical(f) for f in found if isinstance(f, str) and f.startswith(PREFIX)}
    if not found:
        return None
    bundle = deepcopy(bundle)
    mods = {r['ability']: int(r.get('modifier', (int(r['score']) - 10) // 2))
            for r in (info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('abilities', [])}
    numbers = path_numbers(info, 'tianxia.path.body_refining')
    numbers['key_mod'] = mods.get('CON', int(numbers.get('key_mod', 0)))
    owned = sorted(f for f in found if numbers['cl'] >= LEVELS.get(f.removeprefix(PREFIX), 100))
    for key in ('typed_reactions', 'typed_passives'):
        rows = []
        for row in bundle.get(key, []):
            fid = row.get('feature_id', '')
            if fid.startswith(PREFIX):
                if canonical(fid) not in owned:
                    continue
                row = {**row, 'numbers': dict(numbers), 'cl': numbers['cl']}
                if fid in {PREFIX + 'unbroken_bones#marrow_memory', PREFIX + 'sovereign_reconstruction'}:
                    row['kind'] = 'bone_zero_replacement'
            rows.append(row)
        bundle[key] = rows
    bundle['typed_passives'].append({'block': BLOCK, 'owned': owned, 'numbers': numbers})
    for action in bundle['action_catalog']:
        typed = action.get('parameters', {}).get('typed') or {}
        if typed.get('source') in owned:
            action['parameters']['typed'] = {**typed, 'numbers': dict(numbers)}
        if typed.get('source') == PREFIX + 'bone_guard_manifestation' and action.get('target_kind') == 'CELL':
            # The printed Source Rule requires an unoccupied space in range,
            # without adding a sight restriction.
            action['parameters']['cell_placement'] = {**action['parameters'].get('cell_placement', {}), 'require_sight': False}
    return bundle


def family(engine, actor):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, [])
                 if r.get('block') == BLOCK), {})


def owns(engine, actor, name):
    row = family(engine, actor)
    if PREFIX + name not in row.get('owned', []):
        return False
    from ..cultivation_access import effective_cl
    return effective_cl(engine, actor, row['numbers']['cl']) >= LEVELS[name]


@hook('candidate_allowed')
def family_access(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    source = str(typed.get('source') or '')
    if source.startswith(PREFIX) and source.removeprefix(PREFIX) in LEVELS:
        return None if owns(engine, actor, source.removeprefix(PREFIX)) else False
    if (actor.summon or {}).get('group') == 'bone_guard':
        owner = engine.state.actors.get(actor.owner_id)
        if owner is None or not owns(engine, owner, 'bone_guard_manifestation'):
            return False


@hook('row_allowed')
def dormant_guard_reaction(engine, actor, row):
    if (actor.summon or {}).get('group') == 'bone_guard':
        owner = engine.state.actors.get(actor.owner_id)
        if owner is None or not owns(engine, owner, 'bone_guard_manifestation'):
            return False


@hook('summon_turn_policy')
def dormant_guard_turn(engine, actor):
    if (actor.summon or {}).get('group') == 'bone_guard':
        owner = engine.state.actors.get(actor.owner_id)
        if owner is None or not owns(engine, owner, 'bone_guard_manifestation'):
            return {'skip': True}


@hook('choice_reactors')
def family_decisions(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if a.active and family(engine, a)) or None


@hook('summon_catalog')
def guard_profile(table, info):
    if PREFIX + 'bone_guard_manifestation' not in info['owned_ids']:
        return None
    source = table['sources'][PREFIX + 'bone_guard_manifestation']
    source['command_range_ft'] = None
    source['choose_visible_space'] = True
    source['actor_policy'] = {'basic_actions': ['Dash', 'Disengage', 'Dodge', 'Help'],
                              'printed_reactions_only': 1, 'owning_path': 'tianxia.path.body_refining',
                              'asset_kind': 'body_asset'}
    table['creatures']['bone_guard']['attacks'][0]['attack_kind'] = 'cultivation'
    return table


@hook('compile_summon')
def guard_reaction_clock(bundle, info):
    if info['group'] != 'bone_guard':
        return None
    for row in bundle.get('typed_reactions', []):
        if row.get('name') == 'Guard the Sovereign':
            row['once'] = 'round'
    return bundle


@hook('compile_bundle', priority=10)
def guard_command_surface(bundle, info):
    if not any((s.get('summon') or {}).get('group') == 'bone_guard' for s in bundle.get('summons', [])):
        return None
    from copy import deepcopy
    bundle = deepcopy(bundle)
    for action in bundle['action_catalog']:
        if (action.get('parameters') or {}).get('summon_command') == 'bone_guard':
            typed = action['parameters']['typed']
            typed['effects'] = [{'type': 'bone_guard_order'}, *typed['effects']]
    return bundle


@effect('bone_guard_order')
def guard_order(ctx, row):
    if not owns(ctx.engine, ctx.actor, 'bone_guard_manifestation'):
        return
    from ..summons import commandable
    from .needle import ask, checkpoint_id
    guards = commandable(ctx.engine, ctx.actor, 'bone_guard')
    if not guards:
        return
    choices = ['Attack', 'Dash', 'Disengage', 'Dodge', 'Help', 'Move', 'Guard']
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'bone_guard_order', ctx.actor.entity_id), ctx.actor,
        'choice:needle.bone_guard_order', choices,
        prompt=f'Bone Guard Manifestation: {ctx.actor.display_name} spends this Bonus Action to command the Bone Guard. Choose its action after your turn; it may also move up to 30 feet. Move takes no action; Guard prepares Guard the Sovereign. No additional Stamina cost.')
    if not selected:
        return
    details = {}
    if selected[0] == 'Guard':
        from ..target_knowledge import knowledge
        subjects = {a.entity_id: a.display_name for a in ctx.engine.state.actors.values()
                    if a.active and (a is ctx.actor or knowledge(ctx.engine, ctx.actor, a) is not None)}
        subjects.update({o.object_id: (o.component or {}).get('name') or 'Doorway'
                         for o in ctx.engine.state.objects.values() if not o.destroyed and o.object_kind == 'door'
                         and ctx.engine._line_of_sight_actor_to_cell(ctx.actor, o.position)})
        target = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'bone_guard_post', ctx.actor.entity_id), ctx.actor,
            'choice:needle.bone_guard_post', list(subjects), labels=subjects,
            # Guard must name one subject; the sovereign is the printed default so a
            # table that does not choose is never asked to decline a mandatory order.
            preferred=[ctx.actor.entity_id] if ctx.actor.entity_id in subjects else [],
            automatic_options=[key for key in subjects if key == ctx.actor.entity_id
                or key in ctx.engine.state.actors and knowledge(ctx.engine, ctx.actor, ctx.engine.state.actors[key]) is not None
                or key in ctx.engine.state.objects and ctx.engine._line_of_sight_actor_to_cell(ctx.actor, ctx.engine.state.objects[key].position)],
            prompt=f'Bone Guard Manifestation: {ctx.actor.display_name} commands Guard. Choose one creature or doorway to guard; it may move up to 30 feet. Guard the Sovereign protects you or an ally only while within 5 feet. No additional cost.')
        if target:
            details = {'guard_target': target[0]}
    for guard in guards:
        ctx.engine._apply_condition(guard, 'condition:typed.bone_guard_order', ctx.source, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'order': selected[0], **details, 'label': f'Bone Guard command: {selected[0]}'})


@hook('candidate_allowed')
def guard_order_legality(engine, actor, candidate, action):
    if (actor.summon or {}).get('group') != 'bone_guard' or action is None:
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == 'condition:typed.bone_guard_order'), None)
    if held is None:
        return None
    order = held.data['order']
    from ..gate2_runtime_models import CandidateKind
    if candidate.kind not in {CandidateKind.ACTION, CandidateKind.BONUS_ACTION}:
        return None
    if order == 'Attack':
        return None if action.display_name == 'Bone Strike' else False
    if order in {'Move', 'Guard'}:
        return False
    return None if action.display_name == order else False


@hook('healing_pending')
def guard_creature_healing(engine, subject, amount, healer, source, kind):
    if (subject.summon or {}).get('group') != 'bone_guard':
        return None
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get('typed') or {}) if action else {}
    return None if typed.get('affects_body_asset') else amount


@hook('command_reachable')
def guard_direct_control(engine, owner, group, creature):
    if group != 'bone_guard':
        return None
    from ..typed_executor import condition_rules
    if any(r.get('no_direct_cultivation_control') for r in condition_rules(owner)):
        return False


@hook('damage_context_pending_reaction_rank')
def armor_trigger(engine, actor, row, packet, intent):
    if row.get('feature_id') != PREFIX + 'bone_armor':
        return None
    attack = engine.damage_context()
    return {'allowed': bool(owns(engine, actor, 'bone_armor') and attack is not None
                            and attack.target_id == actor.entity_id and packet.amount > 0)}


@hook('row_allowed')
def armor_packet_permission(engine, actor, row):
    fid = row.get('feature_id')
    armor, guard = PREFIX + 'bone_armor', 'tianxia.path.body_refining.feature.stamina_guard'
    if fid not in {armor, guard}:
        return None
    if fid == armor and engine.damage_context() is None:
        return False
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine) or {}
    previous = scratch.get('bone_monarch:defense:' + actor.entity_id)
    from .attack_reduction import current_key
    hit = current_key(engine, actor)
    if previous is None and hit is not None:
        previous = (actor.turn_flags.get('bone_monarch_packet_defenses') or {}).get(hit)
    if previous is not None and previous != fid:
        # Extra Reaction capacity does not itself grant same-packet permission.
        permit = any(r.get('block') == 'same_packet_defense_permission'
                     and {armor, guard} <= set(r.get('features', []))
                     for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, []))
        if not permit:
            return False


@hook('event', nested=True)
def remember_packet_defense(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED' or (kwargs.get('payload') or {}).get('checkpoint') != 'DAMAGE_APPLICATION':
        return
    fid = kwargs.get('source_definition_id')
    if fid not in {PREFIX + 'bone_armor', 'tianxia.path.body_refining.feature.stamina_guard'}:
        return
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine)
    if scratch is not None:
        scratch['bone_monarch:defense:' + str(kwargs.get('actor_id'))] = fid
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is not None and owns(engine, actor, 'bone_armor'):
        from .attack_reduction import current_key
        hit = current_key(engine, actor)
        if hit is not None:
            actor.turn_flags.setdefault('bone_monarch_packet_defenses', {})[hit] = fid


@hook('save_effects')
def bodily_saves(ctx, subject, ability, fail_effects, success_effects, categories):
    if not owns(ctx.engine, subject, 'unbroken_bones'):
        return None
    from .bodily_effects import save_causes
    if save_causes(fail_effects) & UNBROKEN_SAVE_CAUSES or set(categories) & UNBROKEN_SAVE_CAUSES:
        return {'modes': ['ADVANTAGE']}


@hook('save_mode')
def bodily_repeat_saves(engine, actor, ability, dc, source, context):
    if not owns(engine, actor, 'unbroken_bones'):
        return None
    named = {str(tag).removeprefix('category:') for tag in (context or {}).get('named', [])}
    return 'ADVANTAGE' if named & UNBROKEN_SAVE_CAUSES else None


@hook('condition_attempt')
def permanent_bones(ctx, subject, row):
    if not owns(ctx.engine, subject, 'unbroken_bones') or 'bodily_effect' not in row:
        return None
    from .bodily_effects import validate
    p = validate(row['bodily_effect'])
    from ..cultivation_access import effective_cl
    if p.get('permanent_broken_bone') == 1 and int(ctx.numbers['cl']) < effective_cl(ctx.engine, subject, family(ctx.engine, subject)['numbers']['cl']):
        return False


def journey_family(session, aid):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives', [])
                 if r.get('block') == BLOCK), {})


@hook('journey_encounter_settled')
def retain_scene_use(session, aid, engine, actor):
    if not family(engine, actor):
        return
    session.state['actors'][aid].setdefault('source_states', {})[BLOCK] = {
        'uses': [c.data['feature'] for c in actor.conditions.values() if c.condition_id == SCENE_USE]}


@hook('journey_combat_bundle')
def restore_scene_use(bundle, session, aid):
    used = session.state['actors'][aid].get('source_states', {}).get(BLOCK, {}).get('uses', [])
    return {**bundle, 'bone_scene_uses': list(used)} if used and journey_family(session, aid) else None


@hook('match_initialize', priority=150)
def import_scene_use(engine):
    for bundle in getattr(engine, 'typed_bundle_documents', []):
        if not bundle.get('bone_scene_uses'):
            continue
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue  # The preliminary persistence constructor uses another roster.
        for feature in bundle.get('bone_scene_uses', []):
            if owns(engine, actor, feature) and not any(c.condition_id == SCENE_USE and c.data['feature'] == feature for c in actor.conditions.values()):
                engine._apply_condition(actor, SCENE_USE, PREFIX + feature, actor.entity_id, expires_on='UNTIL_REMOVED',
                    data={'feature': feature, 'label': 'Bone Monarch: used this scene'})


@hook('journey_scene_end')
def next_scene(session, previous, current):
    import json
    for actor in session.state['actors'].values():
        states = actor.get('source_states', {})
        if BLOCK in states:
            states[BLOCK]['uses'] = []
        snapshot = actor.get('encounter_snapshot') or {}
        snapshot['conditions'] = {iid: row for iid, row in snapshot.get('conditions', {}).items()
                                  if json.loads(row)['condition_id'] != SCENE_USE}


def journey_marrow_context(session, aid):
    """Hydrate only committed journey bundles and encounter condition records."""
    from types import SimpleNamespace
    from ..journey_assets import JourneyAssetContext
    from ..gate2_runtime_models import ActionDefinition
    from .bodily_effects import encounter_conditions
    engine = JourneyAssetContext(session)
    engine.action_catalog = {a['source_definition_id']: ActionDefinition.model_validate(a)
                             for person in session.state['actors'].values() for a in person['bundle']['action_catalog']}
    engine.typed_bundle_documents = [p['bundle'] for p in session.state['actors'].values()]
    for subject, actor in engine.state.actors.items():
        actor.conditions = encounter_conditions(session, subject)
    return SimpleNamespace(actor=engine.state.actors[aid], engine=engine,
                           numbers=journey_family(session, aid)['numbers'])


@hook('journey_options')
def marrow_travel_options(session, aid):
    state = session.state['actors'][aid]
    row = journey_family(session, aid)
    if PREFIX + 'marrow_regeneration' not in row.get('owned', []):
        return None
    pending = state.get('bone_marrow_pending')
    if pending:
        ctx = journey_marrow_context(session, aid)
        options = _options(ctx)
        return [{'id': 'bone_marrow_benefit:' + key, 'kind': 'bone_marrow_benefit',
                 'payload': {'benefit': key}, 'label': 'Marrow Regeneration: ' + label + ' (healing and 2 Stamina cost already resolved)'}
                for key, (label, _) in options.items()] or [
                    {'id': 'bone_marrow_benefit:none', 'kind': 'bone_marrow_benefit',
                     'payload': {'benefit': 'none'}, 'label': 'Marrow Regeneration: no eligible secondary benefit'}]
    if not state['incapacitated'] and state['resources'].get('resource:core.stamina', 0) >= 2:
        count = 3 if row['numbers']['cl'] >= 14 else 2
        return [{'id': 'bone_marrow', 'kind': 'bone_marrow', 'payload': {},
                 'label': f'Marrow Regeneration: spend 2 Stamina and a Bonus Action to heal {count}d10 + Constitution modifier, then choose one secondary benefit', 'auto_select': 0}]


@hook('journey_time_gate')
def finish_marrow_before_time(session, seconds):
    if seconds and any(a.get('bone_marrow_pending') for a in session.state['actors'].values()):
        raise ValueError('Finish the pending Marrow Regeneration secondary choice before advancing time.')


@hook('journey_command')
def marrow_travel(session, aid, kind, payload):
    if kind not in {'bone_marrow', 'bone_marrow_benefit'}:
        return None
    from ..journey import require
    from ..gate2_runtime_models import DiceSpec
    from ..gate2_rolls import DeterministicRollAuthority
    from .repeat_saves import save_of
    from .end_effect import known_source_cl
    actor = session.state['actors'][aid]
    row = journey_family(session, aid)
    require(PREFIX + 'marrow_regeneration' in row.get('owned', []), 'This creature has not acquired Marrow Regeneration.')
    source = PREFIX + 'marrow_regeneration'
    roller = DeterministicRollAuthority(f"{session.state['journey_id']}:{session.state['revision']}:{aid}:{source}")
    if kind == 'bone_marrow':
        require(not payload and not actor.get('bone_marrow_pending') and not actor['incapacitated'], 'Finish the current choice; Marrow Regeneration requires your Bonus Action.')
        require(actor['resources'].get('resource:core.stamina', 0) >= 2, 'Marrow Regeneration costs 2 Stamina.')
        session.tick(6)
        actor['resources']['resource:core.stamina'] -= 2
        snapshot = actor.get('encounter_snapshot')
        maximum = actor['bundle']['actor_template']['maximum_hp']
        if snapshot is None:
            snapshot = {'current_hp': maximum, 'maximum_hp': maximum, 'temporary_hp': 0, 'active': 1,
                        'life_state': '', 'conditions': {}, 'death_saves': {'ok': 0, 'bad': 0}}
            actor['encounter_snapshot'] = snapshot
        count = 3 if row['numbers']['cl'] >= 14 else 2
        roll = roller.roll(DiceSpec(count=count, sides=10, modifier=int(row['numbers']['key_mod'])), actor_id=aid, reason=source)
        before = snapshot['current_hp']
        snapshot['current_hp'] = min(snapshot['maximum_hp'], before + max(0, roll.total))
        actor['bone_marrow_pending'] = {'source': source, 'sequence': len(session.state['events']) + 1}
        session.emit('ROLL_RECORDED', aid, source=source, roll=roll.model_dump(mode='json'))
        session.emit('MARROW_HEALING', aid, source=source, before=before, after=snapshot['current_hp'], stamina_cost=2,
                     text='Marrow Regeneration heals first; choose one secondary benefit to finish this Bonus Action.')
        return True
    require(set(payload) == {'benefit'} and actor.get('bone_marrow_pending'), 'Choose the pending Marrow Regeneration benefit.')
    ctx = journey_marrow_context(session, aid)
    options = _options(ctx)
    key = payload['benefit']
    require(key in options or key == 'none' and not options, 'Choose one currently available secondary benefit.')
    ended = ''
    if key != 'none':
        iid, condition = options[key][1]
        category = key.split(':', 1)[0]
        if category in {'bleeding', 'speed'}:
            cl = known_source_cl(ctx, condition)
            if cl is not None and cl <= row['numbers']['cl']:
                ended = iid
        else:
            save = save_of(condition)
            # Preserve the original ability and DC. Only Poisoned gets Advantage.
            ability = str(save['ability']).upper()
            modifier = int(actor['bundle']['actor_template'].get('saving_throws', {}).get(ability, 0))
            roll = roller.d20(actor_id=aid, reason=source, modifier=modifier,
                              mode='ADVANTAGE' if category == 'poisoned' else 'NORMAL')
            session.emit('ROLL_RECORDED', aid, source=source, roll=roll.model_dump(mode='json'))
            if roll.total >= int(save['dc']) and condition.data.get('repeat_save'):
                ended = iid
    if ended:
        actor['encounter_snapshot']['conditions'].pop(ended, None)
    actor.pop('bone_marrow_pending')
    session.emit('MARROW_BENEFIT_RESOLVED', aid, source=source, selected=key, ended_instance=ended)
    return True


# ------------------------------------------------------------------------------------------------------------ Bone Armor
@hook("reaction_amount")
def dice_unless_types(engine: Any, actor: Any, row: dict[str, Any], eff: dict[str, Any]) -> int | None:
    rule = (eff or {}).get("dice_unless_types")
    if not rule:
        return None
    current = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    if current and current in {str(kind).upper() for kind in rule.get("types") or []}:
        return None  # the ordinary dice
    from ..gate2_runtime_models import DiceSpec

    numbers = row.get("numbers") or {}
    dice = rule.get("dice") or {}
    bonus = int(numbers.get("key_mod", 0)) if str(eff.get("formula") or "") == "key_ability_modifier" else 0
    roll = engine.roller.roll(DiceSpec(count=int(dice.get("count") or 1), sides=int(dice.get("sides") or 8), modifier=bonus),
                              actor_id=actor.entity_id, reason=f"REACTION:{row.get('feature_id')}", critical=False)
    engine._record_roll(roll)
    return int(roll.total)


# ---------------------------------------------------------------------------------------------------- Marrow Regeneration
def _options(ctx: Any) -> dict[str, tuple[str, Any]]:
    from . import end_effect, physical_holds
    from .repeat_saves import repeatable
    from .bodily_effects import profile, physical_temporary, speed_reduced

    actor, out = ctx.actor, {}
    from ..cultivation_access import effective_cl
    cl = effective_cl(ctx.engine, actor, int(ctx.numbers.get("cl") or 1))
    for iid, condition in actor.conditions.items():
        source_cl = end_effect.known_source_cl(ctx, condition)
        description_cl = str(source_cl) if source_cl is not None else 'unknown'
        harm = profile(condition, engine=ctx.engine, actor=actor)
        if any(harm.get(key) for key in ('hidden', 'foundation', 'soul', 'identity')):
            continue
        # Unknown source strength cannot certify an authority-gated removal.
        if condition.condition_id == "condition:typed.bleeding":
            out['bleeding:' + iid] = (f"End Bleeding: {condition.data.get('label') or 'Bleeding'} (Source CL {description_cl})", (iid, condition))
        elif physical_temporary(condition) and speed_reduced(ctx.engine, actor, condition):
            out['speed:' + iid] = (f"End temporary injury Speed reduction: {condition.data.get('label') or 'physical injury'} (Source CL {description_cl})", (iid, condition))
    poisoned = repeatable(actor, ("poisoned",))
    for iid, condition in poisoned:
        out['poisoned:' + iid] = (f"Repeat the saving throw against {condition.data.get('label') or 'Poisoned'} with Advantage", (iid, condition))
    held = [(iid, c) for iid, c in repeatable(actor, ("paralyzed", "restrained"))
            if (physical_holds.source(ctx.engine, c) or (False, None))[0]
            or profile(c, engine=ctx.engine, actor=actor).get('cause') in {'broken_bone', 'crushed_limb', 'physical_binding', 'bodily_deformation'}]
    for iid, condition in held:
        out['physical:' + iid] = (f"Repeat the saving throw against {condition.data.get('label') or condition.condition_id.removeprefix('condition:typed.').title()}", (iid, condition))
    return out


@effect('bone_marrow_healing', harmful=False)
def marrow_healing(ctx, row):
    """Ordinary self-healing, scaled by the currently available Body CL."""
    if not owns(ctx.engine, ctx.actor, 'marrow_regeneration'):
        return
    from dataclasses import replace
    from ..cultivation_access import effective_cl
    from ..typed_executor import block_healing
    level = effective_cl(ctx.engine, ctx.actor, int(ctx.numbers['cl']))
    current = replace(ctx, typed={**ctx.typed, 'numbers': {**ctx.numbers, 'cl': level}})
    block_healing(current, {**row, 'type': 'healing'})


@effect("marrow_regeneration_choice")
def marrow_choice(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .repeat_saves import save_of

    options = _options(ctx)
    if not options:
        return
    engine, actor = ctx.engine, ctx.actor
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "marrow_regeneration", actor.entity_id), actor,
                 "choice:needle.marrow_regeneration", list(options), labels={key: label for key, (label, _pair) in options.items()},
                 prompt=f"Marrow Regeneration: {actor.display_name} healed. Choose one secondary benefit; the 2 Stamina and Bonus Action are already paid. "
                        "Ending Bleeding or an injury’s Speed penalty works only if its originating cultivation level is no higher than your Body level. "
                        "A repeated save uses its original ability and difficulty; Poisoned grants Advantage.", target_id=actor.entity_id)
    if not picked:
        return
    key = picked[0]
    iid, condition = options[key][1]
    kind = key.split(':', 1)[0]
    if kind in {"bleeding", "speed"}:
        from .end_effect import known_source_cl
        source_cl = known_source_cl(ctx, condition)
        from ..cultivation_access import effective_cl
        if source_cl is None or source_cl > effective_cl(engine, actor, int(ctx.numbers['cl'])):
            ctx.rider('Marrow Regeneration: the selected state is not ended; its Source CL is unknown or higher than yours. This secondary choice is spent.')
            return
        if iid in actor.conditions:
            from .condition_ownership import remove_instance
            remove_instance(engine, actor, iid, ctx.source)
        return
    save = save_of(condition)
    dc = int(save["dc"])
    from .adaptations import ending_save_scope
    with ending_save_scope(engine, actor, condition):
        roll = engine._roll_save(actor, str(save["ability"]).upper(), dc, ctx.source,
                                 "ADVANTAGE" if kind == "poisoned" else None,
                                 roll_context={'source_actor_id': condition.source_actor_id,
                                               'named': [condition.condition_id.removeprefix('condition:typed.')]})
    # An originating save is enough to roll, but is not an invented removal
    # procedure. Native repeat_save sources end on success and publish their
    # original on_repeat_success riders through the removal event below.
    if roll is not None and roll.total >= dc and iid in actor.conditions and condition.data.get('repeat_save'):
        actor.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})


# --------------------------------------------------------------------------------------------------------- Unbroken Bones
def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == kind]


@hook("critical_cancel")
def critical_immunity(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], roll: Any,
                      intent: Any) -> bool | None:
    """Convert the hit before dice and critical-only riders, using the native seam."""
    rows = _rows(engine, target, "critical_immunity")
    if not rows or _cocoon(target) or not owns(engine, target, 'unbroken_bones'):
        return None
    engine._append_event("PASSIVE_TRIGGERED", rows[0]["feature_id"], actor_id=target.entity_id, target_ids=(target.entity_id,),
                         payload={"feature_id": rows[0]["feature_id"], "critical_turned_normal": True,
                                  "roll_id": roll.roll_id,
                                  "log": f"Unbroken Bones: the critical hit on {target.display_name} lands as a normal hit."})
    return True


# ---------------------------------------------------------------------------------------------- Sovereign Reconstruction
def _cocoon(actor: Any) -> Any:
    return next((c for c in getattr(actor, 'conditions', {}).values() if c.condition_id == COCOON), None)


@hook('recipient_allowed')
def contained_body_target(engine, actor, target, action):
    if _cocoon(target):
        typed = (action.parameters.get('typed') or {}) if action else {}
        # Single-target options use the actual object. Area options are geometric
        # and never reach the body as a creature: contained_body_area_subject
        # removes it from area save and damage subjects, and cocoon_area_damage
        # delivers the failed-save branch to the Asset.
        return None if typed.get('area') else False


@hook('effect_subject_allowed')
def contained_body_area_subject(ctx, row, subject):
    # A printed area whose cells cover the Cocoon targets the Cocoon itself, even
    # when worded "each creature" (lead ruling). The contained body is not a
    # separate creature recipient there: it makes no area save of its own and
    # takes no creature damage. The Asset takes the failed-save branch once.
    typed = getattr(ctx, 'typed', None) or {}
    if _cocoon(subject) and (typed.get('area') or {}).get('size_ft'):
        return False
    return None


@effect("bone_cocoon")
def bone_cocoon(ctx: Any, row: dict[str, Any]) -> None:
    from ..asset_anchor_runtime import create
    engine, actor = ctx.engine, ctx.actor
    if not owns(engine, actor, 'sovereign_reconstruction'):
        return
    dc = int(ctx.numbers.get("save_dc") or 10)
    cl = int(ctx.numbers['cl'])
    footprint = engine.actor_footprints.get(actor.entity_id)
    width = getattr(footprint, 'width_cells', 1)
    length = getattr(footprint, 'height_cells', 1)
    obj = create(engine, actor, ctx.source,
        {'name': f'{actor.display_name}’s Bone Cocoon', 'kind': 'body_asset', 'ac': dc, 'hp': 5 * cl,
         'source_cl': cl, 'height_ft': 5, 'group': 'bone_cocoon', 'resist': list(PHYSICAL_TYPES),
         'immune': ['POISON', 'PSYCHIC']}, actor.position,
        component={'body_asset': 1,
                   'blocks': False, 'structure': False, 'width_cells': width, 'length_cells': length}, containing=actor)
    engine._apply_condition(actor, COCOON, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Bone Cocoon: Incapacitated, Speed 0; the cocoon takes attacks and area damage instead of your body until your next turn",
                                  "asset_id": obj.object_id, "ac": dc, "cl": cl, "save_dc": dc,
                                  "rule": {"no_actions": True, "no_reactions": True, "speed_zero": True}})
    engine._apply_condition(actor, 'condition:typed.incapacitated', ctx.source, actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'bone_cocoon_asset': obj.object_id,
            'label': 'Sovereign Reconstruction: Incapacitated inside the bone cocoon until it opens or breaks'})
    if actor.concentration is not None:
        engine._end_concentration(actor, 'INCAPACITATED')


@hook('lethal_damage', priority=20)
def zero_replacement(engine, actor, amount, damage_type, source_id, source_actor_id, intent):
    from ..damage_allocation import available_temporary_hp
    if not actor.active or actor.current_hp <= 0 or _cocoon(actor):
        return None
    hp_loss = max(0, amount - available_temporary_hp(engine, actor, amount, source_actor_id))
    if hp_loss < actor.current_hp or hp_loss - actor.current_hp >= actor.maximum_hp:
        return None  # Not lethal, or killed outright: neither replacement is legal.
    used = {c.data.get('feature') for c in actor.conditions.values() if c.condition_id == SCENE_USE}
    from ..typed_executor import condition_rules
    denied = any(r.get('death_prevention_denied') for r in condition_rules(actor, engine=engine))
    costs = {'unbroken_bones#marrow_memory': 4, 'sovereign_reconstruction': 8}
    options = [name for name, cost in costs.items() if owns(engine, actor, name)
               and name not in used and actor.resources.get('resource:core.stamina', 0) >= cost
               and not (denied and name == 'unbroken_bones#marrow_memory')]
    if not options:
        return None
    from .needle import ask, checkpoint_id
    labels = {'unbroken_bones#marrow_memory': 'Marrow Memory: spend 4 Stamina and remain at 1 HP (once this scene)',
              'sovereign_reconstruction': 'Sovereign Reconstruction: spend 8 Stamina; at 0 HP enter a bone cocoon until your next turn (once this scene)'}
    picked = ask(engine, intent, checkpoint_id(engine, 'bone_zero', actor.entity_id), actor,
        'choice:needle.bone_zero', options, labels=labels,
        prompt=f'{actor.display_name} would be reduced to 0 HP by {damage_type.title()} damage. Choose one replacement or decline. Neither costs an Action or Reaction.',
        allow_decline=True, default='decline', target_id=actor.entity_id,
        name='Bone Monarch: replace falling to 0 HP', feature_id=PREFIX + options[-1])
    if not picked:
        return None
    feature = picked[0]
    source = PREFIX + feature
    engine._spend_resource(actor, 'resource:core.stamina', costs[feature], source)
    engine._apply_condition(actor, SCENE_USE, source, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'feature': feature, 'label': labels[feature] + ': used'})
    if feature == 'unbroken_bones#marrow_memory':
        return 1
    from .states import context
    ctx = context(engine, actor, source, [], family(engine, actor)['numbers'])
    ctx.effect_source = source
    ctx.action = ctx.action.model_copy(update={'source_definition_id': source, 'owner_id': actor.entity_id,
                                              'display_name': 'Sovereign Reconstruction'})
    bone_cocoon(ctx, {'type': 'bone_cocoon'})
    return {'hp_floor': 0, 'replace_zero': True}


@hook('zero_hp')
def cocoon_life(engine, actor, source_id, intent):
    return 'CONSCIOUS' if _cocoon(actor) else None


@hook('damage_asset_proxy')
def cocoon_damage(engine, actor, amount, damage_type, source_id, source_actor_id, intent):
    held = _cocoon(actor)
    if held:
        obj = engine.state.objects.get(held.data['asset_id'])
        if obj is not None and not obj.destroyed:
            return obj.object_id


@hook('technique_used', priority=50)
def cocoon_area_damage(ctx):
    """Failed-save area damage on a Cocoon's cells is delivered to the Asset.

    The body is not a creature recipient in that area (contained_body_area_subject),
    so the owner's save cannot change the Asset's damage. Objects have no saving
    throw: the failed branch is the Asset's applicable branch, scoped by the shared
    per-payload area policy. One delivery per Cocoon per activation. Cocoon assets
    carry no spirit TAG, so spirit_assets never admits them here.
    """
    from .. import typed_executor as te
    from ..action_geometry import point
    from ..object_geometry import target_cells
    from .objects import deal
    area = ctx.typed.get('area') or {}
    if not area.get('size_ft'):
        return
    aim = ctx.damage_cache.get('_checkpoint_aim') or point(ctx.engine, ctx.actor)
    cells = set(te.area_cells(ctx.engine, point(ctx.engine, ctx.actor), aim, area, include_altitude=True))
    admitted = []
    for obj in list(ctx.engine.state.objects.values()):
        if (obj.destroyed or (obj.component or {}).get('body_asset') != 1
                or (obj.component or {}).get('asset_anchor_runtime', {}).get('group') != 'bone_cocoon'
                or ctx.engine.state.actors.get(obj.owner_id) is None
                or not any(cell in cells for cell in target_cells(ctx.engine, obj))):
            continue
        admitted.append(obj)
    if not admitted:
        return
    rows_by_object = {}
    all_rows = {}
    for obj in admitted:
        owner = ctx.engine.state.actors.get(obj.owner_id)
        rows = te.area_damage_rows(ctx, ctx.typed.get('effects') or [], owner=owner,
                                   contains_owner=True)
        rows_by_object[obj.object_id] = rows
        all_rows.update({id(row): row for row in rows})
    packets_by_key, row_keys = {}, {}
    for row in all_rows.values():
        key = f"damage_bonus_roll:{row['damage_bonus_group']}" if row.get('damage_bonus_group') else id(row)
        row_keys[id(row)] = key
        packets_by_key.setdefault(key, te._damage_roll(ctx, row))
    if not packets_by_key:
        return
    for obj in admitted:
        keys = dict.fromkeys(row_keys[id(row)] for row in rows_by_object[obj.object_id])
        packets = [packets_by_key[key] for key in keys]
        if packets:
            # Every packet came from area_damage_rows with this object's owner;
            # that helper already applied the per-payload recipient policy.
            deal(ctx.engine, ctx.actor, ctx.engine.state.objects[obj.object_id], packets, ctx.source,
                 area_scope_resolved=True)


@hook('object_operation_gate')
def cocoon_operations(engine, actor, obj, operation, source, intent):
    if (obj.component or {}).get('asset_anchor_runtime', {}).get('group') != 'bone_cocoon' or operation == 'break':
        return None
    action = engine.action_catalog.get(source)
    if action is None:
        action = next((a for a in engine.action_catalog.values()
                       if (a.parameters.get('typed') or {}).get('source') == source), None)
    typed = (action.parameters.get('typed') or {}) if action else {}
    return None if 'body_asset' in typed.get('asset_targets', []) else False


@hook('condition_attempt')
def contained_condition(ctx, subject, row):
    if _cocoon(subject) and not row.get('affects_contained_body'):
        return False


@hook('healing_pending')
def contained_healing(engine, subject, amount, healer, source, kind):
    # Creature healing has no target while the body is contained. Asset repair
    # remains the Asset runtime's explicit permission, never ordinary healing.
    return amount if _cocoon(subject) else None


@hook('event', nested=True)
def broken_cocoon(engine, event_type, kwargs):
    if event_type != 'OBJECT_UPDATED':
        return
    row = (kwargs.get('payload') or {}).get('object') or {}
    if not row.get('destroyed'):
        return
    for actor in engine.state.actors.values():
        held = _cocoon(actor)
        if held and held.data.get('asset_id') == row['object_id']:
            _end_cocoon(engine, actor, held)
            from .life_state import fall_unconscious
            fall_unconscious(engine, actor, held.source_definition_id)


@hook("ac")
def cocoon_ac(engine: Any, target: Any) -> int | None:
    held = _cocoon(target)
    if held is None:
        return None
    return int(held.data["ac"]) - int(target.armor_class)


def _end_cocoon(engine: Any, actor: Any, held: Any) -> None:
    source = held.source_definition_id
    actor.conditions.pop(held.instance_id, None)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": COCOON, "instance_id": held.instance_id})
    from .condition_ownership import remove_instance
    for condition in list(actor.conditions.values()):
        if condition.data.get('bone_cocoon_asset') == held.data['asset_id']:
            remove_instance(engine, actor, condition.instance_id, source)


@hook("turn_boundary_start", priority=-200)
def emerge(engine: Any, actor: Any) -> None:
    held = _cocoon(actor)
    if held is None or not actor.active:
        return
    obj = engine.state.objects.get(held.data['asset_id'])
    intact = obj is not None and not obj.destroyed and int(obj.current_hp or 0) > 0
    source = held.source_definition_id
    if not intact:
        _end_cocoon(engine, actor, held)
        note(engine, source, actor, f"Sovereign Reconstruction: the bone cocoon was broken; {actor.display_name} is at 0 Hit Points.")
        from .life_state import fall_unconscious
        fall_unconscious(engine, actor, source)
        return
    from .. import typed_executor as te
    from .states import context

    ctx = context(engine, actor, source, [], {"pb": int(actor.proficiency_bonus or 2), "cl": int(held.data.get("cl") or 1),
                                               "save_dc": int(held.data.get("save_dc") or 10)})
    ctx.intent = getattr(engine, '_active_intent', None)
    ctx.effect_source = source
    ctx.action = ctx.action.model_copy(update={'source_definition_id': source, 'owner_id': actor.entity_id,
                                              'display_name': 'Sovereign Reconstruction'})
    from .needle import ask, checkpoint_id
    from .bodily_effects import physical_temporary
    from ..relations import ENEMY, relation
    from ..target_knowledge import knowledge
    from .condition_ownership import remove_instance
    choices = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.bleeding' or physical_temporary(c)]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'bone_emerge_cleanse', actor.entity_id), actor,
        'choice:needle.bone_emerge_cleanse', [c.instance_id for c in choices],
        labels={c.instance_id: c.data.get('label') or c.condition_id.removeprefix('condition:typed.').replace('_', ' ').title() for c in choices},
        prompt=f'Sovereign Reconstruction: {actor.display_name} emerges. End one Bleeding or temporary physical injury, at no additional cost.')
    foes = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
            if other.active and relation(engine, actor, other) == ENEMY and engine._distance_actor_to_actor(actor, other) <= 10]
    known = [f for f in foes if knowledge(engine, actor, f) is not None]
    target_options = [f.entity_id for f in known] + ['other_hostiles']
    targeted = ask(engine, ctx.intent, checkpoint_id(engine, 'bone_emerge_targets', actor.entity_id), actor,
        'choice:needle.bone_emerge_targets', target_options,
        labels={**{f.entity_id: f.display_name for f in known}, 'other_hostiles': 'Also affect any other hostile creatures in the burst (reveals no hidden creatures)'},
        minimum=0, maximum=len(target_options), allow_decline=True, default='all',
        automatic_options=target_options,
        prompt=f'Sovereign Reconstruction: {actor.display_name} chooses hostile creatures within 10 feet for 6d6 Piercing damage (Dexterity save for half; Prone on failure). No additional cost.')
    _end_cocoon(engine, actor, held)
    from ..asset_anchor_runtime import retire
    retire(engine, obj, source)
    heal = max(0, actor.maximum_hp // 2 - actor.current_hp)
    if heal:
        te.run_effects(ctx, [{'type': 'healing', 'applies_to': 'self', 'flat': heal}])
    for iid, condition in list(actor.conditions.items()):
        name = condition.condition_id.rsplit('.', 1)[-1]
        if name in ("prone", "grappled", "restrained") or iid in picked:
            remove_instance(engine, actor, iid, source)
    known_ids = {f.entity_id for f in known}
    foes = [f for f in foes if f.entity_id in targeted or 'other_hostiles' in targeted and f.entity_id not in known_ids]
    note(engine, source, actor, f"Sovereign Reconstruction: {actor.display_name} emerges from the bone cocoon at half its Hit Points.",
         foes)
    if foes:
        ctx.targets = foes
        ctx.target = foes[0] if len(foes) == 1 else None
        te.run_effects(ctx, [{"type": "save", "ability": "dex", "evidence": "Sovereign Reconstruction: Dexterity saving throw",
                              "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 6}, "damage_types": ["piercing"]},
                                          {"type": "condition", "applies_to": "target", "condition": "prone"}],
                              "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["piercing"]}]}])
    if actor.current_hp <= 0:
        from .life_state import fall_unconscious
        fall_unconscious(engine, actor, source)
