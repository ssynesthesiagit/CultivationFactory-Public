"""Dream Qi combat rules sealed in reviewed rows (A2GQISUB10).

Dream Ward uses native save_mode/d20_bonus, including typed saving throws.
Only explicit Dream/Illusion provenance or printed adverse conditions qualify.
The failed-roll rescue is optional, evented and once per explicit scene.
Lucid Strike uses ordinary typed damage, saves, expiry and delivery; the fifth
Distortion adds a source-owned visibility marker through existing sight hooks.
The source-scoped dream_qi_scene producer owns acquisition, elapsed rituals and
rest clocks; this provider consumes that state through native table intents.
"""
from . import effect, hook
from copy import deepcopy
from dataclasses import replace
import json
from . import dream_qi_scene as scene
from . import spirit_traditions as st
from .condition_ownership import remove_instance
from .needle import ask, checkpoint_id, cell_id, position_of

STRIKE, REFINE, CONCORD, ASCEND = scene.FEATURES[1:]
LEDGER = 'condition:typed.dream_qi_ledger'
LINK = 'condition:typed.dream_qi_link'
BOUND = 'condition:typed.dream_qi_bound'
BURDEN = 'condition:typed.dream_qi_burden'
REST = 'condition:typed.dream_sleep'

WARD = 'tianxia.subpath.qi.dream_qi_cultivator.feature.dreamer_s_rest'
BLOCK = 'dream_ward'
USED = 'condition:typed.dream_ward_used'
HORIZON = 'condition:typed.lucid_horizon'


@effect(BLOCK)
def ward_declaration(ctx, row):
    pass  # compiled passive declaration; not an activation


@hook('compile_actions')
def compile_ward(info):
    record = info['mechanics'].get(WARD) or {}
    if WARD in info['owned_ids'] and any(e.get('type') == BLOCK for e in record.get('effects') or []):
        info['passives'].append({'feature_id': WARD, 'block': BLOCK, 'numbers': dict(info['numbers'])})


def _ward(engine, actor):
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                 if r.get('block') == BLOCK), None)


def _qualifies(engine, source, named):
    names = {str(n).lower() for n in named or ()}
    if names & {'charmed', 'frightened', 'dream_sleep', 'asleep', 'category:dream', 'category:illusion', 'category:sleep'}:
        return True
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get('typed') or {}) if action else {}
    return (typed.get('sphere') in {'tianxia.sphere.dreams', 'tianxia.sphere.illusion'}
            or bool(set(typed.get('tags') or []) & {'dream', 'illusion'})
            or str(typed.get('option_of') or typed.get('source') or '').startswith('tianxia.subpath.qi.dream_qi_cultivator.feature.'))


@hook('save_mode')
def ward_mode(engine, actor, ability, dc, source, metadata):
    if _ward(engine, actor) and _qualifies(engine, source, metadata.get('conditions') or metadata.get('named')):
        return 'ADVANTAGE'


@hook('d20_bonus')
def ward_rescue(engine, roll, intent):
    metadata = engine.d20_context(roll) or {}
    # Signed save totals are valid; eligibility comes from the save context.
    if metadata.get('kind') != 'save' or not metadata.get('dc'):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    row = _ward(engine, actor) if actor else None
    if not row or not _qualifies(engine, metadata.get('source_id'), metadata.get('conditions') or metadata.get('named')):
        return None
    pb = int(row['numbers'].get('pb') or 2)
    if not roll.total < metadata['dc'] or any(c.condition_id == USED for c in actor.conditions.values()):
        return None
    from .needle import ask, checkpoint_id
    source_id = str(metadata.get('source_id') or getattr(engine, '_active_action_source_id', '') or '')
    reason = str(getattr(roll, 'reason', '') or '')
    if not source_id and reason.startswith('SAVE:'):
        source_id = reason[5:].rpartition(':')[0]
    action = engine.action_catalog.get(source_id)
    source_actor = engine.state.actors.get(action.owner_id) if action is not None else None
    from .choice_prompt import action_context
    prompt_context = action_context(engine, source_actor, source_id, actor, action=action)
    action_name = action.display_name if action is not None else 'the triggering effect'
    take = ask(engine, intent, checkpoint_id(engine, 'dream_ward', roll.roll_id), actor,
               'choice:needle.dream_ward', ['rescue'], minimum=0, maximum=1, allow_decline=True,
               labels={'rescue': f'Dream Ward: add {pb} to this failed save (once this scene)'}, preferred=['rescue'], automatic_options=(['rescue'] if roll.total+pb>=metadata['dc'] else []),
               prompt=f'Dream Ward: add {pb} to {actor.display_name}’s failed save against {action_name} (once this scene)?',
               prompt_context=prompt_context)
    if not take:
        return None
    engine._apply_condition(actor, USED, 'passive:'+WARD, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'label':'Dream Ward rescue used this scene'})
    return {'source_id':'passive:'+WARD, 'bonus':pb}


@effect('lucid_horizon', harmful=True)
def horizon(ctx, row):
    if ctx.target:
        ctx.engine._apply_condition(ctx.target, HORIZON, ctx.source, ctx.actor.entity_id,
                                    expires_on='START_OF_SOURCE_NEXT_TURN', data={'label':'Shifting Horizon: visible to the dreamer'})


def _horizon(subject, viewer):
    return subject is not None and viewer is not None and any(c.condition_id == HORIZON and (c.source_actor_id == viewer.entity_id or c.data.get('global_horizon'))
                                                              for c in subject.conditions.values())


def _ordinary_visual_hide(engine, viewer, seen):
    """Whether native Hide is supported by an ordinary visual obscurer here.

    Hidden remains meaningful behind physical sight barriers and in magical or
    superior concealment. Horizon lifts only an ordinary visual area; matching
    that area here removes the native Hide rider without changing line of sight.
    """
    from .. import zones
    from .darkness_scope import scope
    if zones.ordinary_visual_wall_between(engine, viewer, seen):
        return True
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile
        visual = profile.get('visual') or {}
        if not (profile.get('obscured') == 'heavy' or visual.get('darkness')) or scope(engine, zone) != 'ordinary':
            continue
        viewer_in, seen_in = zones._inside(engine, viewer, zone), zones._inside(engine, seen, zone)
        inward = visual.get('sees') == 'inward'
        if (viewer_in and seen_in) or (seen_in and not inward) or (viewer_in and inward):
            return True
    return False


@hook('masked_conditions')
def horizon_sight(engine, attacker, target):
    out = {}
    for who, viewer in ((target, attacker), (attacker, target)):
        if _horizon(who, viewer):
            out[who.entity_id] = {iid for iid, c in who.conditions.items()
                                  if c.condition_id.endswith('.invisible')
                                  or (c.condition_id.endswith('.hidden') and c.data.get('stealth_total') is not None
                                      and _ordinary_visual_hide(engine, viewer, who))}
    return out or None


@hook('darkness_lifted')
def horizon_concealment(engine, zone, viewer, seen):
    from .darkness_scope import scope
    if _horizon(seen, viewer) and scope(engine, zone) == 'ordinary':
        return True


@hook('zone_obscuration_ignored')
def horizon_ordinary_concealment(engine, zone, viewer, seen):
    from .darkness_scope import scope
    if _horizon(seen, viewer) and scope(engine, zone) == 'ordinary':
        return True


def ownership(engine, actor, feature):
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, ())
                 if r.get('block') == scene.STATE and r.get('feature_id') == feature), None) if actor else None


def receiver_numbers(engine, actor):
    """Actual native recipient statistics; no save proficiency becomes a check."""
    bundle = next((b for b in engine.typed_bundle_documents if b.get('actor_id') == actor.entity_id), {})
    return dict(bundle.get('dream_qi_receiver') or st.numbers(engine, actor))


def feature(action):
    typed = action.parameters.get('typed') or {} if action else {}
    return typed.get('option_of') or typed.get('source') or ''


def dream_tagged(engine, source):
    """Dream provenance only: an Illusion alone is not a Dream-tagged effect."""
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get('typed') or {}) if action else {}
    return feature(action) in scene.FEATURES or typed.get('sphere') == 'tianxia.sphere.dreams' or 'dream' in (typed.get('tags') or [])


def ledger(engine, actor):
    held = next((c for c in actor.conditions.values() if c.condition_id == LEDGER), None)
    return json.loads(held.data['state']) if held else {}


def store(engine, actor, data):
    for c in list(actor.conditions.values()):
        if c.condition_id == LEDGER:
            remove_instance(engine, actor, c.instance_id, scene.PARENT)
    engine._apply_condition(actor, LEDGER, scene.PARENT, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'state': scene.canonical(data), 'label': 'Dream Qi scene and ritual record'})


def select(ctx, who, name, options, labels, prompt, *, decline=False, maximum=1, automatic=None):
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'dream_qi', name, who.entity_id,
               ctx.target.entity_id if ctx.target else ''), who, 'choice:needle.dream_qi.' + name,
               list(options), labels=labels, prompt=prompt, minimum=0 if decline else 1,
               maximum=maximum, allow_decline=decline, preferred=list(options)[:1],
               automatic_options=list(options) if automatic is None else automatic,
               name=ctx.action.display_name, feature_id=feature(ctx.action),
               target_id=ctx.target.entity_id if ctx.target else None)


@hook('compile_actions')
def compile_native(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    numbers = dict(info['numbers'])
    qi_path = next((p for p in (info['owner_sheet'].get('path_and_subpath') or {}).get('paths', [])
                    if p.get('path_id') == 'tianxia.path.qi_cultivation'), None)
    if qi_path:
        numbers['cl'] = min(int(numbers['cl']), int(qi_path.get('attainment', numbers['cl'])),
                            int(qi_path.get('effective_cl', numbers['cl'])))
    for fid in scene.FEATURES:
        if fid in info['owned_ids']:
            info['passives'].append({'feature_id': fid, 'block': scene.STATE, 'numbers': dict(numbers)})
    if CONCORD in info['owned_ids']:
        for op, label in (('walk', 'Walk the Shared Dream'),):
            out.append(ActionDefinition(source_definition_id=f'action:typed.{info["short"]}.dream_qi.{op}',
                display_name=label, owner_id=info['actor_id'], economy='NONE', resolution_kind='TYPED',
                target_kind='SELF', parameters={'typed': {'source': CONCORD, 'effects': [{'type': 'dream_qi_' + op}],
                    'numbers': numbers, 'riders': [], 'manual_inline_choice': True}, 'dream_qi_operation': op,
                    'description': 'Choose a participant and the printed shared-dream benefit; no Qi cost; Walk is once during your turn.'}))
    if REFINE in info['owned_ids']:
        out.append(ActionDefinition(source_definition_id=f'action:typed.{info["short"]}.dream_qi.free_refine',
            display_name='Refine a Waking Dream: free Ascension use', owner_id=info['actor_id'], economy='ACTION',
            resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
            parameters={'typed': {'source': REFINE, 'effects': [{'type': 'dream_qi_waking', 'free': 1}],
                'numbers': numbers, 'riders': [], 'manual_inline_choice': True}, 'dream_qi_free': 1,
                'harmful': True, 'description': 'Once during Dream Ascension, deal 6d8 Psychic (Wisdom save for half) at 0 Qi; cannot restore Qi.'}))
    if STRIKE in info['owned_ids'] and ASCEND in info['owned_ids']:
        for action in info['actions']:
            if feature(action) == STRIKE:
                out.append(action.model_copy(update={'source_definition_id': action.source_definition_id + '.ascendant',
                    'economy': EconomyKind.BONUS_ACTION, 'display_name': action.display_name + ' (Ascendant Bonus Action)',
                    'parameters': {**action.parameters, 'dream_qi_bonus': 1}}))
    return out


@hook('compile_action')
def seal_native(action, info):
    fid = feature(action)
    if fid not in (STRIKE, REFINE, CONCORD, ASCEND):
        return action
    typed = deepcopy(action.parameters.get('typed') or {})
    if action.parameters.get('dream_qi_operation') or action.parameters.get('dream_qi_free'):
        return action
    typed.update(riders=[], manual_inline_choice=True)
    typed.pop('zone_spec', None)
    if fid == STRIKE:
        choices = {}
        for option in (info.get('mechanics', {}).get(STRIKE) or {}).get('options') or []:
            for attack in option.get('effects') or []:
                for save in attack.get('on_hit') or []:
                    if save.get('type') == 'save':
                        choices[option['label']] = deepcopy(save.get('on_fail') or [])
        if not choices:
            return action
        preferred = next((label for label in choices if label in action.display_name), next(iter(choices)))
        for attack in typed.get('effects') or []:
            for save in attack.get('on_hit') or []:
                if save.get('type') == 'save':
                    save['on_fail'] = [{'type': 'dream_qi_distortion', 'choices': choices, 'preferred': preferred}]
    elif fid == REFINE:
        typed['effects'] = [{'type': 'dream_qi_waking'}]
        # Choice follows the failed save; the three legacy option buttons share
        # one implementation and preserve every result in the transactional menu.
        # Each button names the printed sub-ability, not the parent heading.
        label = str(typed.get('option_label') or '').strip()
        action = action.model_copy(update={'display_name': 'Refine a Waking Dream' + (f': {label}' if label else '')})
    elif fid == CONCORD:
        typed.update(effects=[{'type': 'dream_qi_concord'}], duration={'kind': 'instant'})
    else:
        typed.update(effects=[{'type': 'dream_qi_ascend'}], duration={'kind': 'minutes', 'amount': 1, 'concentration': True})
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed},
        **({'target_kind': 'SELF', 'range_ft': None} if fid == CONCORD else {}),
        **({'target_kind': 'CELL', 'range_ft': 90} if fid == ASCEND else {}),
        **({'target_kind': 'ANY_CREATURE', 'range_ft': 60} if fid == REFINE else {})})


@effect('dream_qi_distortion', harmful=True)
def choose_distortion(ctx, row):
    if not ctx.target:
        return
    choices = row['choices']
    preferred = row['preferred']
    ordered = [preferred, *(key for key in choices if key != preferred)]
    descriptions = {'Stolen Reaction': 'Cannot take Reactions', 'Endless Corridor': 'Speed reduced by 10 feet',
                    'False Opening': 'Disadvantage on its next attack roll',
                    'Fractured Concentration': 'Disadvantage on its next Concentration saving throw',
                    'Shifting Horizon': 'Cannot benefit from Invisible or ordinary visual concealment against you'}
    picked = select(ctx, ctx.actor, 'lucid_distortion', ordered,
        {key: f'{key}: {descriptions.get(key, key)} until the start of your next turn' for key in ordered},
        f'Lucid Strike: {ctx.target.display_name} failed its Wisdom save. Choose one Lucid Distortion until the start of your next turn.')
    if picked:
        from .. import typed_executor as te
        te.run_effects(ctx, choices[picked[0]])


def owned_field(engine, owner):
    """The owner's active Dream Ascension field, wherever the owner stands.

    Dream Roads, Lucid Revision and the Concordance nesting clause name the
    effect's location, not the caster's; only personal benefits require the
    Ascendant Dreamer to be inside.
    """
    from .. import zones
    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id and
                 feature(engine.action_catalog.get(z.source_definition_id)) == ASCEND), None)


def field(engine, actor):
    from .. import zones
    zone = owned_field(engine, actor)
    return zone if zone and zones._inside(engine, actor, zone) else None


def dreaming(engine, owner, target):
    from .. import zones
    if any(m.source_actor_id == owner.entity_id and
           feature(engine.action_catalog.get(m.source_definition_id)) == STRIKE
           for m in target.modifiers.values()):
        return True
    if any(c.condition_id.rsplit('.', 1)[-1] in {'asleep', 'dream_sleep', 'charmed', 'frightened'} or
           c.condition_id in (LINK, BOUND) and c.source_actor_id == owner.entity_id or
           _qualifies(engine, c.source_definition_id, ()) and not c.data.get('overcome')
           for c in target.conditions.values()):
        return True
    return any(z.owner_id == owner.entity_id and feature(engine.action_catalog.get(z.source_definition_id)) == ASCEND
               and zones._inside(engine, target, z) for z in zones.typed_zones(engine))


@hook('candidate_allowed')
def native_allowed(engine, actor, candidate, action):
    fid = feature(action)
    if not action or fid not in scene.FEATURES:
        return None
    data = ledger(engine, actor)
    if action.parameters.get('dream_qi_operation'):
        if not data.get('concord'):
            return False
        return not (action.parameters['dream_qi_operation'] == 'walk' and data.get('walk_turn') == actor.turns_started)
    if fid == REFINE:
        if data.get('refine_turn') == actor.turns_started:
            return False
        if action.parameters.get('dream_qi_free') and (not field(engine, actor) or data.get('free_refine_used')):
            return False
        return all(dreaming(engine, actor, engine.state.actors[t]) for t in candidate.target_ids)
    if action.parameters.get('dream_qi_bonus'):
        return field(engine, actor) is not None and data.get('bonus_strike_turn') != actor.turns_started
    if fid == ASCEND:
        return not data.get('ascension_used')
    return None


@hook('technique_cost_discount')
def field_cost(engine, actor, source_id, cost_totals):
    action = engine.action_catalog.get(source_id)
    if field(engine, actor) and feature(action) in (REFINE, CONCORD) and scene.QI in cost_totals:
        return {scene.QI: 2}


def willing_failure(ctx, subject, purpose):
    from ..fact_consent_admission import admit_choice
    record = admit_choice(ctx, subject, feature(ctx.action), 'dream_consent', purpose + ':' + ctx.actor.entity_id,
        ['resist', 'fail'], labels={'resist': 'Make my normal Wisdom saving throw', 'fail': 'Willingly fail this Wisdom saving throw'},
        prompt=f'{subject.display_name}: {ctx.actor.display_name} uses {ctx.action.display_name}. Make your Wisdom save or willingly fail?',
        expires_on='END_OF_CURRENT_TURN', readers=(ctx.actor.entity_id,), automatic_options=['resist', 'fail'])
    return bool(record and record['value'] == 'fail')


def psychic(ctx, target, dice, *, half=False):
    from .. import typed_executor as te
    te.run_effects(replace(ctx, target=target, targets=[target], damage_divisor=2 if half else 1),
                   [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': dice, 'sides': 8}, 'damage_types': ['psychic']}])


@effect('dream_qi_waking', harmful=True)
def waking(ctx, row):
    target = ctx.target
    if not ownership(ctx.engine, ctx.actor, REFINE) or not target or not dreaming(ctx.engine, ctx.actor, target):
        return
    data = ledger(ctx.engine, ctx.actor)
    if data.get('refine_turn') == ctx.actor.turns_started:
        return
    data['refine_turn'] = ctx.actor.turns_started
    if row.get('free'):
        data['free_refine_used'] = 1
    store(ctx.engine, ctx.actor, data)
    failed = willing_failure(ctx, target, 'refine') or st.save(ctx, target, 'wis')
    psychic(ctx, target, 6, half=not failed)
    if not failed:
        return
    options = ['qi', 'temp_hp', 'remove']
    nature = data.get('known_inner_states', {}).get(target.entity_id) or {}
    independent = scene.qi_source(ctx.actor.entity_id, target.entity_id, nature)
    if not independent or row.get('free') or data.get('waking_round') == ctx.engine.state.round_number or int(data.get('waking_gains', 0)) >= int(ctx.numbers['pb']):
        options.remove('qi')
    eligible = [c for c in target.conditions.values() if c.source_actor_id == ctx.actor.entity_id and
                dream_tagged(ctx.engine, c.source_definition_id)
                and c.condition_id not in (LEDGER, USED)]
    modifiers = [m for m in target.modifiers.values() if m.source_actor_id == ctx.actor.entity_id and
                 feature(ctx.engine.action_catalog.get(m.source_definition_id)) == STRIKE]
    if not eligible and not modifiers:
        options.remove('remove')
    picked = select(ctx, ctx.actor, 'refinement_result', options,
        {'qi': 'Regain 2 Qi (once per round; at most PB times this scene)', 'temp_hp': f'Gain {3 * int(ctx.numbers["pb"])} Temporary Hit Points',
         'remove': f'Remove one of your Lucid Distortions or Dream conditions from {target.display_name}'},
        f'Dream Refinement: choose the benefit after {target.display_name} fails the Wisdom save.')
    if not picked:
        return
    from .. import typed_executor as te
    if picked[0] == 'qi':
        data = ledger(ctx.engine, ctx.actor)
        data.update(waking_round=ctx.engine.state.round_number, waking_gains=int(data.get('waking_gains', 0)) + 1)
        store(ctx.engine, ctx.actor, data)
        te.run_effects(ctx, [{'type': 'gain_resource', 'applies_to': 'self', 'flat': 2, 'on': 'Qi'}])
    elif picked[0] == 'temp_hp':
        te.run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'self', 'flat': 3 * int(ctx.numbers['pb'])}])
    else:
        labels = {c.instance_id: c.data.get('label') or 'Your Dream condition on ' + target.display_name for c in eligible}
        labels.update({m.modifier_id: (f'{target.display_name}: Endless Corridor (Speed reduced by 10 feet)' if m.target_field == 'speed_ft'
                       else f'{target.display_name}: False Opening (Disadvantage on its next attack)') for m in modifiers})
        chosen = select(ctx, ctx.actor, 'remove_distortion', list(labels), labels,
            f'Dream Refinement: which of your effects ends on {target.display_name}?')
        if chosen:
            if chosen[0] in target.modifiers:
                ctx.engine._remove_modifier_instance(target, chosen[0], ctx.source)
            else:
                remove_instance(ctx.engine, target, chosen[0], ctx.source)


def marker(ctx, target, cid, label, rule, **data):
    ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'label': label, 'rule': rule, **data})


def concord_targets(engine, owner):
    return [(a, c) for a in engine.state.actors.values() for c in a.conditions.values()
            if c.condition_id in (LINK, BOUND) and c.source_actor_id == owner.entity_id]


@effect('dream_qi_concord')
def concord(ctx, row):
    from .. import senses, asset_anchor_runtime as assets
    engine, owner = ctx.engine, ctx.actor
    if not ownership(engine, owner, CONCORD):
        return
    # The dreamer takes part in their own Concordance: senses.perceives is a
    # creature-to-creature question (it answers False for the viewer itself), so
    # the owner is admitted explicitly rather than dropped from the printed
    # "creatures you can perceive" list.
    choices = [a for a in engine.state.actors.values() if a.active and
               (a.entity_id == owner.entity_id or (engine._distance_actor_to_actor(owner, a) <= 30 and senses.perceives(engine, owner, a)))]
    selected = select(ctx, owner, 'concord_targets', [a.entity_id for a in choices],
        {a.entity_id: a.display_name for a in choices}, f'Shared Dream Concordance: choose up to {ctx.numbers["pb"]} creatures within 30 feet you can perceive (you may include yourself). Costs 5 Qi and lasts one minute.',
        maximum=int(ctx.numbers['pb']))
    targets = [engine.state.actors[t] for t in selected or []]
    if not targets:
        return
    data = ledger(engine, owner)
    if data.get('concord'):
        end_concord(engine, owner)
    from ..gate2_runtime_models import Position
    anchor_target = select(ctx, owner, 'anchor_target', [t.entity_id for t in targets],
        {t.entity_id: t.display_name for t in targets}, 'Shared Dream Concordance: choose the participant the Dream Anchor appears beside.')
    origin = engine.state.actors[anchor_target[0]].position
    locations = [Position(x=x, y=y, z=z) for x in range(max(0, origin.x - 1), min(engine.grid.width, origin.x + 2))
                 for y in range(max(0, origin.y - 1), min(engine.grid.height, origin.y + 2))
                 for z in range(max(0, origin.z - 1), origin.z + 2)
                 if engine.grid.distance_ft(Position(x=x, y=y, z=z), origin) <= 5]
    locations = [p for p in locations if assets.legal_placement(engine, [p], 1, require_support=False, occupies_space=False)
                 and engine.grid.line_of_sight(owner.position, p)]
    if not locations:
        raise ValueError('Dream Anchor needs a legal visible space within 5 feet of the chosen participant.')
    pick = select(ctx, owner, 'anchor', [cell_id(p) for p in locations], {cell_id(p): f'Dream Anchor at {p.x}, {p.y}, {p.z * 5} feet high' for p in locations},
                  'Shared Dream Concordance: place its visible, nonblocking Dream Anchor within 5 feet of that participant.')
    anchor = assets.create(engine, owner, ctx.source,
        {'name': 'Dream Anchor', 'kind': 'ANCHOR', 'ac': int(ctx.numbers['save_dc']), 'hp': 4 * int(ctx.numbers['cl']),
         'source_cl': int(ctx.numbers['cl']), 'height_ft': 1, 'group': 'dream_concord', 'immune': ['POISON', 'PSYCHIC'],
         'requires_support': False, 'occupies_space': False},
        position_of(pick[0]), component={'blocks': False, 'occupies_space': 0, 'dream_concord': owner.entity_id})
    from .. import zones
    nested = owned_field(engine, owner)
    inside = nested and all(zones._inside(engine, t, nested) for t in targets)
    if not inside:
        engine._start_concentration(owner, ctx.source)
    data = ledger(engine, owner)
    data['concord'] = {'anchor': anchor.object_id, 'source': ctx.source, 'round': engine.state.round_number,
                       'slot': engine.state.current_slot_index, 'cl': int(ctx.numbers['cl']), 'dc': int(ctx.numbers['save_dc']), 'nested': int(bool(inside))}
    store(engine, owner, data)
    for target in targets:
        sub = replace(ctx, target=target, targets=[target])
        linked = select(sub, target, 'link_consent', ['resist', 'link'],
            {'resist': 'Resist with a Wisdom save', 'link': 'Willingly link: shared speech and images, optional safe movement and Dream defenses for one minute'},
            f'{target.display_name}: join {owner.display_name}’s Shared Dream Concordance willingly, or resist?')
        if linked and linked[0] == 'link':
            marker(ctx, target, LINK, 'Lucid-Linked: share speech, symbols, images and emotions', {}, born=target.turns_started)
        elif st.save(sub, target, 'wis'):
            marker(ctx, target, BOUND, 'Dream-Bound: Restrained, no Reactions or willing teleport; aware and able to act',
                   {'no_reactions': True, 'no_teleport': True,
                    'concentration_mode': 'DISADVANTAGE'}, born=target.turns_started)
            # Use the actual standard condition as well as the source control
            # record, so other native features see a genuinely Restrained target.
            from .. import typed_executor as te
            if not te.condition_immune(engine, target, 'restrained'):
                engine._apply_condition(target, 'condition:typed.restrained', ctx.source, owner.entity_id,
                    expires_on='UNTIL_REMOVED', data={'label': 'Restrained by Shared Dream Concordance',
                                                    'dream_bound_owner': owner.entity_id})
        else:
            apply_burden(sub, target, 'reaction', 'START_OF_SOURCE_NEXT_TURN')
            from .. import typed_executor as te
            te.run_effects(sub, [{'type': 'speed', 'applies_to': 'target', 'flat': -10, 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}])


def end_concord(engine, owner):
    from .. import asset_anchor_runtime as assets
    data = ledger(engine, owner)
    active = data.pop('concord', None)
    if active is None:
        return
    # Remove the control record first: object-retirement observers cannot recur.
    store(engine, owner, data)
    for target, cond in list(concord_targets(engine, owner)):
        remove_instance(engine, target, cond.instance_id, CONCORD)
    anchor = engine.state.objects.get(active['anchor'])
    if anchor:
        assets.retire(engine, anchor, CONCORD)
    from .. import concentration
    for sequence in concentration.copies(owner, active['source']):
        concentration.end_copy(engine, owner, sequence, 'CONCORDANCE_ENDED')


BURDENS = {'reaction': 'Cannot take Reactions', 'speed': 'Speed reduced by 15 feet',
    'attack': 'Disadvantage on next attack', 'concentration': 'Disadvantage on next Concentration save',
    'teleport': 'Cannot willingly teleport', 'horizon': 'Cannot benefit from Invisible or ordinary visual concealment'}


def apply_burden(ctx, target, choice, expiry=None):
    from .. import typed_executor as te
    if feature(ctx.action) == ASCEND:
        fields = {z.zone_id for z in ctx.engine.state.zones.values() if z.active and z.owner_id == ctx.actor.entity_id
                  and feature(ctx.engine.action_catalog.get(z.source_definition_id)) == ASCEND}
        if any(c.condition_id == 'condition:typed.dream_qi_force' and c.data.get('field') in fields for c in target.conditions.values()):
            return
    expiry = expiry or f'START_OF_TURN_AT:{target.entity_id}:{target.turns_started + 1}'
    if choice == 'speed':
        te.run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'speed', 'applies_to': 'target', 'flat': -15, 'expires_on': expiry}])
    elif choice in ('attack', 'concentration'):
        te.run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'disadvantage', 'applies_to': 'target',
            'on': 'its next attack roll' if choice == 'attack' else 'its next Concentration saving throw', 'expires_on': expiry}])
    else:
        cid = HORIZON if choice == 'horizon' else BURDEN
        ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id, expires_on=expiry,
            data={'label': BURDENS[choice], 'global_horizon': int(choice == 'horizon'),
                  'rule': {'no_reactions': True} if choice == 'reaction' else {'no_teleport': True} if choice == 'teleport' else {}})


@effect('dream_qi_ascend')
def ascend(ctx, row):
    from .. import zones
    if not ownership(ctx.engine, ctx.actor, ASCEND):
        return
    expressions = ['moonlit_palace', 'endless_staircase', 'mist_forest', 'mirror_lake', 'starless_city', 'flowering_nightmare']
    labels = {s: s.replace('_', ' ').title() for s in expressions}
    custom = ledger(ctx.engine, ctx.actor).get('expression')
    if custom:
        expressions.append('custom')
        labels['custom'] = custom
    selected = select(ctx, ctx.actor, 'expression', expressions, labels,
        'Dream Ascension: choose the visible dream expression (8 Qi, Concentration, one minute).')
    # The visual has no mechanical classification beyond the printed Dream field.
    spec = {'name': 'Dream Ascension: ' + labels[selected[0]], 'shape': 'cylinder', 'size_ft': 30, 'height_ft': 30,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True}, 'difficult': {'who': 'hostile'},
        'triggers': [{'on': ['enter', 'start'], 'who': 'hostile', 'effects': [{'type': 'dream_qi_ground'}], 'once_per_turn': True}],
        'terrain': [], 'inside': []}
    zones.create(ctx, spec)
    data = ledger(ctx.engine, ctx.actor)
    data.update(ascension_used=1, free_refine_used=0)
    store(ctx.engine, ctx.actor, data)


@effect('dream_qi_ground', harmful=True)
def ground(ctx, row):
    from ..relations import relation, ENEMY
    target = ctx.target
    if not target or relation(ctx.engine, ctx.actor, target) != ENEMY:
        return
    # Native source/target turn key, including moves on someone else's turn.
    data = ledger(ctx.engine, ctx.actor)
    key = f'{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}:{target.entity_id}'
    if data.get('ground_receipts', {}).get(target.entity_id) == key:
        return
    data.setdefault('ground_receipts', {})[target.entity_id] = key
    store(ctx.engine, ctx.actor, data)
    failed = st.save(ctx, target, 'wis')
    psychic(ctx, target, 4, half=not failed)
    if failed:
        pick = select(ctx, ctx.actor, 'burden', list(BURDENS), BURDENS,
            f'Dream Ascension: choose one Dream Burden for {target.display_name} until the start of its next turn.')
        apply_burden(ctx, target, pick[0])


def move_choice(ctx, mover, feet, key, *, forced=False, inside=None, provokes=False):
    from .. import zones, senses
    from ..granted_movement import routes as granted_routes, Route
    routes = {mover.position: ((mover.position,), 0)}
    if forced:
        from ..gate2_runtime_models import Position
        from ..target_knowledge import actors_for
        occupied = {cell for other in actors_for(ctx.engine, ctx.actor) if other.entity_id != mover.entity_id and other.active
                    for cell in ctx.engine._actor_volume(other)}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if (dx or dy or dz) and mover.position.z + dz >= 0:
                        p = Position(x=mover.position.x + dx, y=mover.position.y + dy, z=mover.position.z + dz)
                        if ctx.engine.grid.volume_legal(p, footprint=ctx.engine._footprint(mover), occupied_cells=occupied) and ctx.engine.grid.volume_step_legal(mover.position, p, footprint=ctx.engine._footprint(mover), occupied_cells=occupied):
                            routes[p] = ((mover.position, p), int(ctx.engine.grid.distance_ft(mover.position, p)))
    else:
        routes.update({p: (Route(tuple(path), mode), cost) for p, (path, cost, mode) in granted_routes(ctx.engine, mover, feet).items()})
    routes = {p: value for p, value in routes.items() if (inside is None or
        zones._inside(ctx.engine, mover.model_copy(update={'position': p}), inside) and senses.perceives_cell(ctx.engine, mover, p))}
    ids = [cell_id(p) for p in sorted(routes, key=lambda p: (p != mover.position, p.z, p.y, p.x))]
    if not ids:
        return 0
    opportunity = 'Opportunity Attacks apply normally' if provokes else 'without Opportunity Attacks'
    chosen = select(ctx, ctx.actor if forced else mover, key, ids,
        {cell_id(p): f'Move {mover.display_name} to {p.x}, {p.y}, {p.z * 5} feet high ({value[1]} feet; {opportunity})' for p, value in routes.items()},
        f'{ctx.action.display_name}: {mover.display_name} may move up to {feet} feet to a legal space, {opportunity}.', decline=True,
        automatic=ids)
    if chosen:
        path = routes[position_of(chosen[0])][0]
        return ctx.engine.move_path(mover, path, ctx.source, kind='forced' if forced else 'granted', feet=feet,
                                    intent=ctx.intent, provokes=provokes, source_actor_id=ctx.actor.entity_id)
    return 0


@effect('dream_qi_walk')
def walk(ctx, row):
    participants = concord_targets(ctx.engine, ctx.actor)
    if not participants:
        return
    target_ids = list(dict.fromkeys(t.entity_id for t, _ in participants))
    chosen = select(ctx, ctx.actor, 'walk_target', target_ids, {t.entity_id: t.display_name for t, _ in participants},
        'Walk the Shared Dream: choose a linked or Dream-Bound participant (once on your turn, no Qi).')
    target = ctx.engine.state.actors[chosen[0]]
    bound = any(t is target and c.condition_id == BOUND for t, c in participants)
    options = ['self_move', 'temp_hp', 'armament'] + (['attack'] if bound else ['target_move', 'repeat'])
    picked = select(replace(ctx, target=target), ctx.actor, 'walk_result', options,
        {'self_move': 'Move yourself 10 feet without Opportunity Attacks', 'temp_hp': f'Give {target.display_name} {2 * int(ctx.numbers["pb"])} Temporary HP',
         'armament': 'Move your bound Domain Armament 20 feet', 'attack': f'{target.display_name} has Disadvantage on its next attack',
         'target_move': f'If willing, move {target.display_name} 5 feet', 'repeat': f'{target.display_name} repeats one Frightened, Illusion or Dream save with Advantage'},
        f'Walk the Shared Dream: choose the benefit for {target.display_name}.')
    from .. import typed_executor as te
    op = picked[0]
    if op in ('self_move', 'target_move'):
        move_choice(ctx, ctx.actor if op == 'self_move' else target, 10 if op == 'self_move' else 5, 'walk_move')
    elif op == 'temp_hp':
        te.run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'temp_hp', 'applies_to': 'target', 'flat': 2 * int(ctx.numbers['pb'])}])
    elif op == 'attack':
        apply_burden(ctx, target, 'attack', 'END_OF_HOLDER_NEXT_TURN')
    elif op == 'repeat':
        repeat_condition(ctx, target)
    else:
        move_armament(ctx)
    data = ledger(ctx.engine, ctx.actor)
    data['walk_turn'] = ctx.actor.turns_started
    store(ctx.engine, ctx.actor, data)


def repeat_condition(ctx, target):
    eligible = [c for c in target.conditions.values() if c.data.get('origin_save') and
                (c.condition_id.endswith('.frightened') or _qualifies(ctx.engine, c.source_definition_id, ()))]
    if not eligible:
        return
    selected = select(ctx, target, 'repeat_condition', [c.instance_id for c in eligible],
        {c.instance_id: c.data.get('label') or 'Repeat the save against this Dream effect' for c in eligible},
        f'Walk the Shared Dream: {target.display_name} may repeat one eligible save with Advantage.', decline=True)
    if selected:
        cond = next(c for c in eligible if c.instance_id == selected[0])
        origin = cond.data['origin_save']
        roll = ctx.engine._roll_save(target, str(origin.get('ability') or 'WIS').upper(), int(origin['dc']), cond.source_definition_id,
                                    extra_mode='ADVANTAGE')
        if roll.total >= int(origin['dc']):
            remove_instance(ctx.engine, target, cond.instance_id, ctx.source)


def move_armament(ctx):
    from .qi_path import armament_condition, armament_point, armament_control_range, move_armament as relocate
    if armament_condition(ctx.actor) is None:
        return
    from ..gate2_runtime_models import Position
    point = armament_point(ctx.actor)
    origin = Position(x=point[0], y=point[1])
    occupied = {c for a in ctx.engine.state.actors.values() if a.active for c in ctx.engine._actor_cells(a)}
    cells = [Position(x=x, y=y) for x in range(ctx.engine.grid.width) for y in range(ctx.engine.grid.height)]
    cells = [p for p in cells if ctx.engine.grid.distance_ft(origin, p) <= 20 and ctx.engine.grid.line_of_sight(origin, p)
             and ctx.engine.grid.distance_ft(ctx.actor.position, p) <= armament_control_range(ctx.engine, ctx.actor)
             and ctx.engine.grid.placement_legal(p, occupied_cells=occupied)]
    selected = select(ctx, ctx.actor, 'armament_position', [cell_id(p) for p in cells], {cell_id(p): f'Move armament to {p.x}, {p.y}' for p in cells},
                      'Move your Domain Armament up to 20 feet to a legal space.', decline=True)
    if selected:
        relocate(ctx.engine, ctx.actor, position_of(selected[0]), ctx.source, max_distance_ft=20, require_clear_route=True)


@effect('dream_qi_communicate')
def communicate(ctx, row):
    # Private information remains scoped to current participants; the controller
    # supplies content through the existing private information admission surface.
    from ..alternative_payments import owned
    from ..observer_information import publish
    content = ledger(ctx.engine, ctx.actor).get('message') or 'A shared image of the battlefield and a request to coordinate.'
    owners = {c.source_actor_id for c in ctx.actor.conditions.values() if c.condition_id == LINK}
    if ledger(ctx.engine, ctx.actor).get('concord'):
        owners.add(ctx.actor.entity_id)
    recipients = [(a, c) for a in ctx.engine.state.actors.values() for c in a.conditions.values()
                  if c.condition_id == LINK and c.source_actor_id in owners]
    for target, cond in recipients:
        if target is ctx.actor:
            continue
        # The link, not the supplemental menu action, authenticates the message:
        # publish records its actual owner (the Concordance's caster), while the
        # text names the participant who spoke.
        authority = ctx.engine.state.actors.get(cond.source_actor_id)
        if authority is None or not owned(ctx.engine, authority, CONCORD):
            continue
        publish(ctx.engine, target, CONCORD, authority, 'declaration',
                {'text': f'{ctx.actor.display_name}: {content}'}, 'END_OF_HOLDER_NEXT_TURN')


@hook('flight')
def ascendant_flight(engine, actor):
    if field(engine, actor):
        return {'fly_speed_ft': 30, 'flight_hover': True}


@hook('damage_defenses')
def ascendant_defense(engine, target, damage_type, typed, source_actor_id):
    if field(engine, target) and damage_type.upper() == 'PSYCHIC':
        return [{'kind': 'resistance', 'damage_types': ['PSYCHIC']}]


@hook('save_mode')
def linked_ward(engine, actor, ability, dc, source, metadata):
    named = {str(n).lower() for n in metadata.get('conditions') or metadata.get('named') or []}
    eligible = bool(named & {'frightened', 'dream_sleep', 'category:dream', 'category:illusion', 'category:sleep'}) or _qualifies(engine, source, ())
    if any(c.condition_id == LINK for c in actor.conditions.values()) and eligible:
        return 'ADVANTAGE'


@hook('effect_origins')
def dream_origins(engine, actor, action):
    from .. import zones, senses
    fid = feature(action)
    results = []
    zone = field(engine, actor)
    if fid == STRIKE and zone:
        for p in zone.affected_cells:
            if engine.grid.line_of_sight(actor.position, p):
                results.append({'id': 'dream_field:' + cell_id(p), 'label': 'Visible Dream Ascension point', 'position': p.model_dump(mode='json')})
    typed = action.parameters.get('typed') or {}
    if _qualifies(engine, action.source_definition_id, ()) and ledger(engine, actor).get('linked_origin_turn') != actor.turns_started:
        for target, cond in [(a, c) for a in engine.state.actors.values() for c in a.conditions.values()
                             if c.condition_id == LINK and a.entity_id != actor.entity_id]:
            shared = any(own.condition_id == LINK and own.source_actor_id == cond.source_actor_id for own in actor.conditions.values())
            if shared and senses.perceives(engine, actor, target):
                results.append({'id': 'dream_link:' + target.entity_id, 'label': 'Willing linked origin: ' + target.display_name,
                                'position': target.position.model_dump(mode='json')})
    return results or None


@hook('zone_obscuration_ignored')
def field_sight(engine, zone, viewer, seen):
    if zone.owner_id == viewer.entity_id and feature(engine.action_catalog.get(zone.source_definition_id)) == ASCEND:
        return True


@hook('save_final')
def lucid_revision(ctx, target, ability, named, failed):
    from .. import zones, senses
    if failed or not dream_tagged(ctx.engine, ctx.action.source_definition_id):
        return
    zone = owned_field(ctx.engine, ctx.actor)
    data = ledger(ctx.engine, ctx.actor)
    key = f'{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}'
    if not zone or not zones._inside(ctx.engine, target, zone) or data.get('revision_turn') == key:
        return
    result = select(replace(ctx, target=target), ctx.actor, 'revision', ['target', 'self', 'temp_hp', 'expression'],
        {'target': f'Move {target.display_name} 5 feet', 'self': 'Move yourself 10 feet', 'temp_hp': 'Give one ally PB Temporary HP',
         'expression': f'Change the dream around {target.display_name}: Disadvantage on its next Perception check until its next turn'},
        f'Lucid Revision: {target.display_name} succeeded against your Dream effect. Use your once-per-turn revision?', decline=True)
    if not result:
        return
    data['revision_turn'] = key
    store(ctx.engine, ctx.actor, data)
    if result[0] in ('target', 'self'):
        move_choice(ctx, target if result[0] == 'target' else ctx.actor, 5 if result[0] == 'target' else 10, 'revision_move', forced=result[0] == 'target', provokes=result[0] == 'self')
    elif result[0] == 'temp_hp':
        allies = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id and senses.perceives(ctx.engine, ctx.actor, a)]
        picked = select(ctx, ctx.actor, 'revision_ally', [a.entity_id for a in allies], {a.entity_id: a.display_name for a in allies}, 'Lucid Revision: choose an ally for PB Temporary HP.')
        if picked:
            from .. import typed_executor as te
            who = ctx.engine.state.actors[picked[0]]
            te.run_effects(replace(ctx, target=who, targets=[who]), [{'type': 'temp_hp', 'applies_to': 'target', 'flat': int(ctx.numbers['pb'])}])
    else:
        ctx.engine._apply_condition(target, 'condition:typed.dream_qi_perception', ctx.source, ctx.actor.entity_id,
            expires_on=f'START_OF_TURN_AT:{target.entity_id}:{target.turns_started + 1}', data={'label': 'Lucid Revision: Disadvantage on next Perception check', 'next': 1})


LINK_ACTIONS = {'linked_step': ('system:dream_qi.linked_step', 'Shared Dream: step 5 feet'),
                'linked_message': ('system:dream_qi.linked_message', 'Shared Dream: communicate')}
WAKE_ACTIONS = {'insight': ('system:dream_qi.wake.insight', 'Wake by Insight'),
                'force': ('system:dream_qi.wake.force', 'Wake by Force')}


@hook('match_start')
def install_wake_actions(engine):
    """Install the shared-dream and wake Actions once, for every participant to be offered.

    The ownership gate reads the compiled passive rows, never engine.state.actors:
    a reloaded fight replaces its state after match_start, so its roster is not
    final yet. Fixed ids keep one definition per purpose; additional_actions
    decides which creature is offered which.
    """
    from ..gate2_runtime_models import ActionDefinition
    if not any(r.get('block') == scene.STATE and r.get('feature_id') in (CONCORD, ASCEND)
               for rows in (getattr(engine, 'typed_passive_rows', {}) or {}).values() for r in rows):
        return
    for op, (sid, label) in LINK_ACTIONS.items():
        engine.action_catalog[sid] = ActionDefinition(source_definition_id=sid, display_name=label, owner_id='*',
            economy='NONE', resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'source': sid,
                'effects': [{'type': 'dream_qi_linked_step' if op == 'linked_step' else 'dream_qi_communicate'}],
                'numbers': {}, 'riders': []}, 'dream_qi_link_option': op,
                **({'free_primary': True} if op == 'linked_message' else {})})
    for kind, (sid, label) in WAKE_ACTIONS.items():
        engine.action_catalog[sid] = ActionDefinition(source_definition_id=sid, display_name=label, owner_id='*',
            economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'source': sid,
                'effects': [{'type': 'dream_qi_wake', 'kind': kind}], 'numbers': {}, 'riders': []}, 'dream_qi_wake': kind})


@hook('additional_actions')
def offer_wake(engine, actor):
    from .. import zones
    kinds = []
    if any(c.condition_id == BOUND for c in actor.conditions.values()):
        kinds.append('insight')
    if any(feature(engine.action_catalog.get(z.source_definition_id)) == ASCEND and zones._inside(engine, actor, z) for z in zones.typed_zones(engine)):
        kinds.append('force')
    result = [WAKE_ACTIONS[kind][0] for kind in kinds if WAKE_ACTIONS[kind][0] in engine.action_catalog]
    if any(c.condition_id == LINK for c in actor.conditions.values()):
        for op in ('linked_step', 'linked_message'):
            sid = LINK_ACTIONS[op][0]
            if sid in engine.action_catalog and (op != 'linked_step' or ledger(engine, actor).get('linked_step_turn') != actor.turns_started):
                result.append(sid)
    return result


@effect('dream_qi_linked_step')
def linked_step(ctx, row):
    if not any(c.condition_id == LINK for c in ctx.actor.conditions.values()) or ledger(ctx.engine, ctx.actor).get('linked_step_turn') == ctx.actor.turns_started:
        return
    if move_choice(ctx, ctx.actor, 5, 'linked_step'):
        data = ledger(ctx.engine, ctx.actor)
        data['linked_step_turn'] = ctx.actor.turns_started
        store(ctx.engine, ctx.actor, data)


@effect('dream_qi_wake')
def wake(ctx, row):
    from .. import zones, ability_checks, senses
    if row['kind'] == 'insight':
        controls = [(ctx.engine.state.actors.get(c.source_actor_id), c) for c in ctx.actor.conditions.values() if c.condition_id == BOUND]
    else:
        controls = [(ctx.engine.state.actors.get(z.owner_id), z) for z in zones.typed_zones(ctx.engine)
                    if feature(ctx.engine.action_catalog.get(z.source_definition_id)) == ASCEND and zones._inside(ctx.engine, ctx.actor, z)]
    if not controls:
        return
    options = ['wis', 'cultivation'] + (['int'] if row['kind'] == 'insight' else [])
    chosen = select(ctx, ctx.actor, 'wake_check', options, {'wis': 'Wisdom check', 'int': 'Intelligence check', 'cultivation': 'Cultivation Check'},
                    f'{ctx.action.display_name}: choose your Action’s check against the dreamer’s Cultivation Save DC.')
    kind = chosen[0]
    if len(controls) > 1:
        keys = [getattr(c, 'instance_id', None) or c.zone_id for owner, c in controls]
        picked = select(ctx, ctx.actor, 'wake_source', keys,
            {key: f'{owner.display_name}’s dream effect' for key, (owner, control) in zip(keys, controls) if owner},
            f'{ctx.action.display_name}: choose the one dream effect this Action opposes.')
        controls = [pair for key, pair in zip(keys, controls) if key == picked[0]]
    for owner, control in controls:
        if owner is None:
            continue
        dc = int((ownership(ctx.engine, owner, CONCORD if row['kind'] == 'insight' else ASCEND) or {}).get('numbers', {}).get('save_dc', 1000000))
        from .. import typed_executor as te
        sub = replace(ctx, target=owner, targets=[owner], typed={**ctx.typed, 'numbers': receiver_numbers(ctx.engine, ctx.actor),
                                                               'dream_cultivation_check': int(kind == 'cultivation')})
        result = te.resolve_opposed_check(sub, owner,
            {'kind': 'cultivation'} if kind == 'cultivation' else {'kind': 'check', 'ability': kind.upper()},
            {'kind': 'dc', 'dc': dc, 'label': owner.display_name + '’s Cultivation Save DC'})
        if not result.success:
            continue
        if row['kind'] == 'insight':
            remove_instance(ctx.engine, ctx.actor, control.instance_id, ctx.source)
            if result.margin >= 5:
                others = [(a, c) for a, c in concord_targets(ctx.engine, owner) if c.condition_id == BOUND and senses.perceives(ctx.engine, ctx.actor, a)]
                if others:
                    chosen = select(ctx, ctx.actor, 'wake_other', [a.entity_id for a, c in others], {a.entity_id: a.display_name for a, c in others}, 'Wake by Insight: free one other Dream-Bound creature you perceive.')
                    for a, c in others:
                        if a.entity_id == chosen[0]:
                            remove_instance(ctx.engine, a, c.instance_id, ctx.source)
        else:
            ctx.engine._apply_condition(ctx.actor, 'condition:typed.dream_qi_force', ctx.source, ctx.actor.entity_id,
                expires_on=f'START_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started + 1}', data={'label': 'Wake by Force: ignore this field’s difficult terrain and Dream Burdens', 'field': control.zone_id})
            for c in list(ctx.actor.conditions.values()):
                if c.source_definition_id == control.source_definition_id and c.condition_id in (BURDEN, HORIZON, 'condition:typed.concentration_mode'):
                    remove_instance(ctx.engine, ctx.actor, c.instance_id, ctx.source)
            for modifier in list(ctx.actor.modifiers.values()):
                if modifier.source_definition_id == control.source_definition_id and modifier.target_field in ('speed_ft', 'attack_mode'):
                    ctx.engine._remove_modifier_instance(ctx.actor, modifier.modifier_id, ctx.source)


@hook('turn_end')
def repeat_bound(engine, actor):
    for cond in list(actor.conditions.values()):
        if cond.condition_id != BOUND:
            continue
        owner = engine.state.actors.get(cond.source_actor_id)
        data = ledger(engine, owner) if owner else {}
        active = data.get('concord')
        if not active:
            continue
        bundle = next((b for b in engine.typed_bundle_documents if b.get('actor_id') == actor.entity_id), {})
        level = int(bundle.get('cl') or st.numbers(engine, actor)['cl'])
        gap = active['cl'] - level
        if gap >= 6 or 3 <= gap <= 5 and (actor.turns_started - int(cond.data['born'])) % 2:
            continue
        action = st.feature_action(engine, owner, CONCORD)
        ctx = st.context(engine, owner, action, [actor])
        if not st.save(ctx, actor, 'wis'):
            remove_instance(engine, actor, cond.instance_id, CONCORD)


@hook('turn_start_choice')
def start_choices(engine, actor):
    from .. import zones, senses
    for sleeper in engine.state.actors.values():
        if not any(c.condition_id == REST and c.data.get('dream_rest') for c in sleeper.conditions.values()):
            continue
        if actor.team_id != sleeper.team_id and senses.perceives(engine, sleeper, actor):
            awaken_rest(engine, sleeper, actor, engine._active_intent)
    for owner in engine.state.actors.values():
        zone = owned_field(engine, owner)
        if not zone or not zones._inside(engine, actor, zone) or actor.team_id != owner.team_id:
            continue
        ctx = st.context(engine, owner, st.feature_action(engine, owner, ASCEND), [actor])
        grant = select(ctx, owner, 'road_ally', ['grant'], {'grant': f'Choose {actor.display_name} for Dream Roads: optional 10-foot movement inside the field without Opportunity Attacks'},
                       f'Dream Roads: choose {actor.display_name} for this start-of-turn movement?', decline=True,
                       automatic=['grant'] if senses.perceives(engine, owner, actor) else [])
        if grant:
            move_choice(ctx, actor, 10, 'dream_roads', inside=zone)
    for owner, cond in [(engine.state.actors.get(c.source_actor_id), c) for c in actor.conditions.values() if c.condition_id == LINK]:
        if owner and ledger(engine, actor).get('linked_step_turn') != actor.turns_started:
            ctx = st.context(engine, owner, st.feature_action(engine, owner, CONCORD), [actor])
            if move_choice(ctx, actor, 5, 'linked_step'):
                data = ledger(engine, actor)
                data['linked_step_turn'] = actor.turns_started
                store(engine, actor, data)


@hook('event', nested=True)
def maintain_dreams(engine, event_type, kwargs):
    if event_type not in ('OBJECT_UPDATED', 'MOVEMENT_COMMITTED', 'CONCENTRATION_ENDED', 'ZONE_REMOVED', 'TURN_STARTED', 'CONDITION_REMOVED'):
        return
    if event_type == 'CONDITION_REMOVED' and (kwargs.get('ended_effect') or {}).get('condition_id') not in (LINK, BOUND):
        return
    from .. import asset_anchor_runtime as assets, zones, concentration
    for owner in engine.state.actors.values():
        data = ledger(engine, owner)
        active = data.get('concord')
        if not active or data.get('concord_transition'):
            continue
        anchor = engine.state.objects.get(active['anchor'])
        participants = [a for a, c in concord_targets(engine, owner)]
        nested = owned_field(engine, owner)
        if (not anchor or anchor.destroyed or (engine.state.round_number, engine.state.current_slot_index) >=
            (active['round'] + 10, active.get('slot', 0)) or not participants or
            not active['nested'] and not concentration.concentrating_on(owner, active['source'])):
            end_concord(engine, owner)
            continue
        can_nest = nested is not None and all(zones._inside(engine, t, nested) for t in participants)
        if active['nested'] and not can_nest:
            from ..typed_executor import condition_rules
            if not owner.active or owner.life_state in ('DYING', 'STABLE') or any(r.get('no_actions') for r in condition_rules(owner)):
                end_concord(engine, owner)
                continue
            active['nested'] = 0
            data['concord_transition'] = 1
            store(engine, owner, data)
            engine._start_concentration(owner, active['source'])
            data['concord_transition'] = 0
            store(engine, owner, data)
        elif not active['nested'] and can_nest:
            active['nested'] = 1
            data['concord_transition'] = 1
            store(engine, owner, data)
            for sequence in concentration.copies(owner, active['source']):
                concentration.end_copy(engine, owner, sequence, 'CONCORDANCE_HELD_BY_ASCENSION')
            data['concord_transition'] = 0
            store(engine, owner, data)
        if all(engine.grid.distance_ft(anchor.position, p.position) > 30 for p in participants):
            # A nonblocking symbol follows an existing participant, never shifts
            # a creature or grants a movement/teleportation effect.
            engine._update_object(anchor.model_copy(update={'position': participants[0].position}), CONCORD, owner.entity_id)


@hook('action_completed')
def remember_bonus_strike(engine, actor, economy, source_definition_id):
    action = engine.action_catalog.get(source_definition_id)
    if action and action.parameters.get('dream_qi_bonus'):
        data = ledger(engine, actor)
        data['bonus_strike_turn'] = actor.turns_started
        store(engine, actor, data)


@hook('technique_used')
def consume_linked_origin(ctx):
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.action.source_definition_id)
    if origin and str(origin.get('id', '')).startswith('dream_link:'):
        data = ledger(ctx.engine, ctx.actor)
        data['linked_origin_turn'] = ctx.actor.turns_started
        store(ctx.engine, ctx.actor, data)


@hook('match_initialize')
def import_scene(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        saved = bundle.get(scene.STATE)
        if actor is None or saved is None:
            continue
        store(engine, actor, saved)
        for rid, amount in saved.get('drained', {}).items():
            if rid in actor.resource_maximums:
                engine._set_resource_maximum(actor, rid, max(0, actor.resource_maximums[rid] - int(amount)), REFINE)
        if saved.get('ward_used'):
            engine._apply_condition(actor, USED, scene.FEATURES[0], actor.entity_id, expires_on='UNTIL_REMOVED', data={'label': 'Dream Ward already used this scene'})
        if saved.get('rest_mode') == 'sleeping':
            from .dreams_core import SLEEP_RULE
            engine._apply_condition(actor, REST, scene.FEATURES[0], actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'label': 'Sleeping during Dreamer’s Rest: aware through passive Perception; awaken before acting',
                                                'dream_rest': 1, 'retain_removal_data': 1, 'rule': dict(SLEEP_RULE)})


@hook('journey_encounter_settled')
def export_scene(session, actor_id, engine, creature):
    if ledger(engine, creature).get('concord'):
        end_concord(engine, creature)
    saved = ledger(engine, creature)
    if not saved and not ownership(engine, creature, WARD):
        return
    saved.pop('concord', None)
    for key in ('refine_turn', 'bonus_strike_turn', 'walk_turn', 'revision_turn', 'ground_receipts', 'waking_round'):
        saved.pop(key, None)
    if any(c.condition_id == USED for c in creature.conditions.values()):
        saved['ward_used'] = 1
    session.state['actors'][actor_id].setdefault('source_states', {})[scene.PARENT] = saved
    scene.sync(session)


@hook('journey_snapshot_actor')
def strip_scene(creature, session, actor_id, engine):
    if not any(c.condition_id == LEDGER for c in creature.conditions.values()):
        return None
    result = creature.model_copy(deep=True)
    for iid, c in list(result.conditions.items()):
        if c.condition_id in (LEDGER, USED):
            result.conditions.pop(iid)
    return result


@hook('damage_roll_bonus')
def resonance_damage(ctx, row, kinds):
    if not dream_tagged(ctx.engine, ctx.source):
        return None
    return spend_resonance(ctx, 'Dream-tagged damage')


def spend_resonance(ctx, label):
    data = ledger(ctx.engine, ctx.actor)
    if not data.get('resonance'):
        return None
    chosen = select(ctx, ctx.actor, 'resonance', ['spend'], {'spend': f'Spend Dream Resonance: add 1d8 to this {label} roll'},
                    f'Dream Resonance: add 1d8 to {ctx.action.display_name}’s {label} roll? Expires at the end of your next Long Rest.', decline=True)
    if not chosen:
        return None
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import _roll
    data.pop('resonance', None)
    store(ctx.engine, ctx.actor, data)
    return _roll(ctx, DiceSpec(count=1, sides=8), 'DREAM_RESONANCE')


@hook('difficult_zone_exempt')
def field_terrain(engine, actor, zone):
    if feature(engine.action_catalog.get(zone.source_definition_id)) != ASCEND:
        return None
    if actor.entity_id == zone.owner_id or any(c.condition_id == 'condition:typed.dream_qi_force'
            and c.data.get('field') == zone.zone_id for c in actor.conditions.values()):
        return True


def awaken_rest(engine, sleeper, threat, intent):
    row = ownership(engine, sleeper, WARD)
    if row is None or intent is None:
        return
    rests = [c for c in sleeper.conditions.values() if c.condition_id == REST and c.data.get('dream_rest')]
    if not rests:
        return
    # A native Hide's committed Stealth total is the opposing perception fact.
    # Names, damage types and narration never establish a perceived threat.
    stealth = max([0, *(int(c.data['stealth_total']) for c in threat.conditions.values() if c.data.get('stealth_total') is not None)])
    passive = 10 + int(sleeper.skills.get('Perception', row['numbers'].get('ability_mods', {}).get('WIS', 0)))
    if passive < stealth:
        return
    ctx = st.context(engine, sleeper, st.feature_action(engine, sleeper, WARD), [threat], row['numbers'], intent)
    if select(ctx, sleeper, 'awaken', ['awaken'], {'awaken': f'Awaken now: {threat.display_name} is a perceived threat; no action required'},
              f'Dreamer’s Rest: {sleeper.display_name} perceives {threat.display_name}. Awaken without using an action?', decline=True):
        for c in rests:
            remove_instance(engine, sleeper, c.instance_id, WARD)
        data = ledger(engine, sleeper)
        data['rest_mode'] = 'awake'
        store(engine, sleeper, data)


@hook('before_attack')
def rest_threat(engine, attacker, defender, intent, context):
    from .. import senses
    if any(c.condition_id == REST and c.data.get('dream_rest') for c in defender.conditions.values()) and senses.perceives(engine, defender, attacker):
        awaken_rest(engine, defender, attacker, intent)


@hook('event', nested=True)
def rest_damage(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    if int((kwargs.get('payload') or {}).get('hp_damage', 0)) + int((kwargs.get('payload') or {}).get('temporary_hp_absorbed', 0)) <= 0:
        return
    for aid in kwargs.get('target_ids') or []:
        actor = engine.state.actors.get(aid)
        if actor:
            for c in list(actor.conditions.values()):
                if c.condition_id == REST and c.data.get('dream_rest'):
                    remove_instance(engine, actor, c.instance_id, WARD)
                    data = ledger(engine, actor)
                    data['rest_mode'] = 'awake'
                    store(engine, actor, data)


@hook('event', nested=True)
def ended_dream_condition(engine, event_type, kwargs):
    if event_type != 'CONDITION_REMOVED':
        return
    ended = kwargs.get('ended_effect') or {}
    for aid in kwargs.get('target_ids') or []:
        actor = engine.state.actors.get(aid)
        if actor is None:
            continue
        if ended.get('condition_id') == BOUND:
            for c in list(actor.conditions.values()):
                if c.data.get('dream_bound_owner') == ended.get('source_actor_id'):
                    remove_instance(engine, actor, c.instance_id, CONCORD)
        if ended.get('condition_id') == REST and (ended.get('data') or {}).get('dream_rest'):
            data = ledger(engine, actor)
            data['rest_mode'] = 'awake'
            store(engine, actor, data)


@hook('ability_check_mode')
def revised_perception(engine, actor, ability, skill, against):
    if str(skill or '').lower() == 'perception' and any(c.condition_id == 'condition:typed.dream_qi_perception' for c in actor.conditions.values()):
        return 'DISADVANTAGE'


@hook('skill_check_mode')
def revised_skill(ctx, actor, ability, skill):
    return revised_perception(ctx.engine, actor, ability, skill, ctx.target)


@hook('event', nested=True)
def consume_revised_perception(engine, event_type, kwargs):
    if event_type != 'CHECK_ROLLED' or str((kwargs.get('payload') or {}).get('skill') or '').lower() != 'perception':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor:
        for c in list(actor.conditions.values()):
            if c.condition_id == 'condition:typed.dream_qi_perception':
                remove_instance(engine, actor, c.instance_id, ASCEND)


@hook('healing_roll_bonus')
def resonance_healing(ctx, row):
    if dream_tagged(ctx.engine, ctx.source):
        return spend_resonance(ctx, 'Dream-tagged healing')


@hook('check_bonus')
def resonance_check(ctx, actor):
    if actor is ctx.actor and (ctx.typed.get('dream_cultivation_check') or dream_tagged(ctx.engine, ctx.source) and any(
            'cultivation' in str(row.get('skill') or row.get('on') or '').lower()
            for row in ctx.typed.get('effects') or [])):
        return spend_resonance(ctx, 'Cultivation Check involving Dreams')
