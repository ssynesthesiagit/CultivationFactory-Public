"""Blood-Moon Execution Saber: one source-owned mark and sentence provider.

Acquisition uses feature_access; subjective anatomy/authority uses TableFact
RelationshipFact declarations through TabletopService.record_fact. Information
uses observer_information, costs use technique_costs, and all stored effects
use native condition events. No character without the acquired row is changed.
"""
from copy import deepcopy
from dataclasses import replace

from . import effect, hook

PARENT = 'tianxia.subpath.qi.blood_moon_execution_saber_cultivator'
PREFIX = PARENT + '.feature.'
ROWS = dict(zip((3, 6, 10, 14, 18), (
    PREFIX + 'write_the_first_sentence', PREFIX + 'sever_the_returning_breath',
    PREFIX + 'execution_threshold', PREFIX + 'sever_body_and_cultivation',
    PREFIX + 'blood_moon_falls_on_the_condemned')))
QI = 'resource:core.qi'
MARK = 'condition:typed.blood_moon_mark'
STATE = 'condition:typed.blood_moon_sentence'


@hook('feature_access_policy')
def access(feature_id):
    for cl, source in ROWS.items():
        if feature_id == source:
            return {'path': 'tianxia.path.qi_cultivation', 'minimum_cl': cl,
                    'classification': 'Restricted Scripture',
                    'source_kinds': ['scripture', 'teacher', 'explicit_permission']}


@hook('compile_passives')
def ownership(rows, info):
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    return [*rows, *[{'feature_id': source, 'block': 'blood_moon', 'tier': cl,
                     'numbers': numbers, 'trigger_owner': 'blood_moon'}
                    for cl, source in ROWS.items() if source in info['owned_ids']
                    and int(numbers['cl']) >= cl]]


def owned(engine, actor, tier=3):
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get('block') == 'blood_moon' and r.get('feature_id') == ROWS[tier]), None)
    if row is None:
        return None
    from ..typed_executor import condition_rules
    # Consume both committed upstream cap contracts while their owners align
    # them; this family does not establish a third suppression representation.
    caps = [rule[key] for rule in condition_rules(actor)
            for key in ('effective_cl', 'cultivation_cl_cap') if type(rule.get(key)) is int]
    return row if min([int(row['numbers']['cl']), *caps]) >= tier else None


def numbers(engine, actor):
    row = owned(engine, actor)
    return row['numbers'] if row else {}


def marks(actor, owner):
    return [c for c in actor.conditions.values() if c.condition_id == MARK
            and c.source_actor_id == owner.entity_id and not c.data.get('suppressed')]


def states(actor, kind=None):
    return [c for c in actor.conditions.values() if c.condition_id == STATE
            and (kind is None or c.data.get('kind') == kind)]


def remove(engine, actor, conditions):
    from .condition_ownership import remove_instance
    for c in conditions:
        remove_instance(engine, actor, c.instance_id, c.source_definition_id)


def pick(ctx, options, prompt, *, key, maximum=1, optional=False, labels=None, preferred=None):
    from .needle import ask, checkpoint_id
    if not options:
        return []
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'blood_moon', key,
        ctx.source, ctx.target.entity_id if ctx.target else ''), ctx.actor,
        'choice:needle.blood_moon_' + key, list(options), labels=labels,
        minimum=0 if optional else 1, maximum=maximum, allow_decline=optional,
        preferred=list(options)[:1] if preferred is None else preferred,
        target_id=ctx.target.entity_id if ctx.target else None,
        name='Blood-Moon Execution Saber', prompt=prompt)


def saber(typed):
    from factory_authoring.starting_kits import item_definition
    import re
    item = item_definition(str(typed.get('source') or ''))
    # Same catalog weapon-name classification as native weapon delivery. The
    # catalog's proficiency family calls the Dao a Cutting Blade, not a saber.
    return bool(typed.get('weapon')) and bool({'saber', 'dao'} & set(re.findall(r'[a-z]+', str(item.get('name') or '').lower())))


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..activation_settlement import path_numbers
    source_numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    owned_ids = set(info['owned_ids'])
    if ROWS[3] not in owned_ids:
        return []
    result = [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.blood_moon.read",
        display_name='Read the Execution Line', owner_id=info['actor_id'],
        economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=120,
        parameters={'typed': {'source': ROWS[3], 'numbers': info['numbers'],
            'effects': [{'type': 'blood_moon_read'}], 'riders': [],
            'duration': {'kind': 'instant'}}, 'expected_damage': 0})]
    for tier, name, cost in ((10, 'Moon-Edged Sentence', 5), (18, 'Blood Moon Falls on the Condemned', 8)):
        if ROWS[tier] not in owned_ids:
            continue
        bound = ActionDefinition(source_definition_id=f"action:typed.{info['short']}.blood_moon.bound_saber_{tier}",
            display_name=f'Bound Execution Saber ({30 if tier == 10 else 60} ft)', owner_id=info['actor_id'],
            economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='ANY_CREATURE',
            range_ft=30 if tier == 10 else 60,
            parameters={'typed': {'source': ROWS[tier], 'sphere': 'tianxia.sphere.sabers', 'qi_powered': True,
                'range_ft': 30 if tier == 10 else 60, 'numbers': {**source_numbers,
                    'attack_bonus': int(info['numbers'].get('attack_bonus', 0))},
                'effects': [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1, 'on_hit': []}],
                'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0})
        # A carried saber keeps its own reach; the bound saber's printed 30/60 ft attack is always offered.
        for base in [*info['actions'], bound]:
            typed = (base.parameters or {}).get('typed') or {}
            if not (saber(typed) or typed.get('sphere') == 'tianxia.sphere.sabers') or '#' in base.source_definition_id:
                continue
            attack = next((e for e in typed.get('effects') or [] if e.get('type') == 'attack'), None)
            if not attack:
                continue
            per_hit = int(base.parameters.get('expected_damage') or 0) // max(1, int(attack.get('count') or 1))
            attack = {**deepcopy(attack), 'count': 1,
                      'on_hit': [*deepcopy(attack.get('on_hit') or []), {'type': 'blood_moon_execution', 'tier': tier}]}
            result.append(base.model_copy(update={
                'source_definition_id': base.source_definition_id + f'#blood_moon_{tier}',
                'display_name': name + ': ' + base.display_name, 'costs': ((QI, cost),),
                'economy': EconomyKind.ACTION, 'attack_count': 1, 'target_kind': 'ANY_CREATURE',
                'parameters': {**base.parameters, 'expected_damage': per_hit + (22 if tier == 10 else 55),
                    'typed': {**deepcopy(typed), 'source': ROWS[tier],
                    'numbers': {**source_numbers, 'attack_bonus': typed['numbers']['attack_bonus']},
                    'delivered_by': base.source_definition_id, 'blood_moon_tier': tier, 'effects': [attack], 'riders': []}}}))
    return result


@hook('candidate_allowed')
def eligible(engine, actor, candidate, action):
    typed = (action.parameters.get('typed') or {}) if action else {}
    tier = typed.get('blood_moon_tier')
    reading = any(e.get('type') == 'blood_moon_read' for e in typed.get('effects') or [])
    if not tier and not reading:
        return None
    if not owned(engine, actor, tier or 3):
        return False
    if tier == 18 and states(actor, 'final_used'):
        return False
    return bool(candidate.target_ids) and all(len(marks(engine.state.actors[t], actor)) >= (3 if tier else 1)
        for t in candidate.target_ids)


def facts(engine, target, viewer=None):
    from ..table_facts import records, FactAnswer, RelationshipFact
    result = [(f.record_id + ':' + key, answer, answer.relationship)
        for f in records(engine, viewer).values() if f.subject_id == target.entity_id
        for key, answer in f.answers.items() if answer.relationship and answer.relationship.active]
    if viewer is not None:
        from ..observer_information import readings
        for reading in readings(engine, viewer):
            details = reading.get('details') or {}
            sphere = details.get('observed_sphere')
            if details.get('target_id') != target.entity_id or not sphere:
                continue
            key = 'native:sphere:' + sphere
            if any(k == key for k, _, _ in result):
                continue
            sources = tuple(a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == target.entity_id and (a.parameters.get('typed') or {}).get('sphere') == sphere)
            name = sphere.rsplit('.', 1)[-1].replace('_', ' ').title() + ' Sphere'
            relationship = RelationshipFact(key=key, kind='system', name=name,
                source_reference=details['used_source_id'], category='sphere', source_ids=sources)
            answer = FactAnswer(fact=f'{target.display_name} used {name} during this scene.', category='system',
                visible_sign='Observed native activation', source_cl=details['source_cl'], relationship=relationship)
            result.append((key, answer, relationship))
    return result


def declaration(ctx, key):
    return next(((a, r) for k, a, r in facts(ctx.engine, ctx.target, ctx.actor) if k == key), None)


def publish(ctx, details):
    from ..observer_information import publish
    text = f"Blood-Moon reading of {ctx.target.display_name}: {details.get('answer', '')}"
    if 'regeneration' in details:
        words = {0: 'No', 1: 'Yes', 'unknown': 'Unknown'}
        text += (f" Active regeneration or automatic healing: {words[details['regeneration']]}."
                 f" Active death-prevention cultivation: {words[details['death_prevention']]}."
                 f" Body: {str(details['body_mode']).replace('_', ' ')}.")
    publish(ctx.engine, ctx.actor, ROWS[3], ctx.actor, 'declaration',
            {'target_id': ctx.target.entity_id, 'text': text, **details}, 'UNTIL_REMOVED')


def authority_reading(ctx):
    """A reading of the target's own Source authority: concealed from a lower-CL reader unless the check succeeds."""
    return type('Reading', (), {'check_dc': 15, 'source_cl': target_cl(ctx.engine, ctx.target)})()


def know(ctx, key, answer):
    from .ability_source import cultivation_check
    if answer.check_dc and answer.source_cl > int(ctx.numbers['cl']):
        if not cultivation_check(ctx.engine, ctx.actor, ctx.numbers, answer.check_dc,
                                 ctx.source, 'Read the Execution Line', ()):
            publish(ctx, {'answer': 'The answer is concealed.'})
            return False
    publish(ctx, {'identified': key, 'answer': 'The selected reading succeeds.'})
    return True


@effect('blood_moon_read')
def read(ctx, row):
    if ctx.target is None or not owned(ctx.engine, ctx.actor) or not marks(ctx.target, ctx.actor):
        return
    options = ['Hit Points', 'Cultivation Points', 'Bodily or cultivation weakness',
               'Survival authority Source CL', 'Survival after bodily destruction']
    chosen = pick(ctx, options, f'Read the Execution Line: learn one fact about {ctx.target.display_name}; '
        'Bonus Action, no Qi cost.', key='read')[0]
    if chosen == options[0]:
        answer = authority_reading(ctx)
        if know(ctx, 'current_hit_points', answer):
            publish(ctx, {'answer': f'{ctx.target.current_hp} current Hit Points.'})
    elif chosen == options[1]:
        from ..typed_executor import CP_POOLS
        value = sum(ctx.target.resources.get(pool, 0) for pool in CP_POOLS)
        answer = authority_reading(ctx)
        if know(ctx, 'current_cultivation_points', answer):
            publish(ctx, {'answer': f'{value} current Cultivation Points.'})
    else:
        kinds = ({'weakness'} if chosen == options[2] else {'survival', 'regeneration', 'death_prevention'})
        pool = [(k, a, r) for k, a, r in facts(ctx.engine, ctx.target, ctx.actor) if r.kind in kinds]
        selected = pick(ctx, [k for k, _, _ in pool], f'{chosen}: choose an authority on {ctx.target.display_name}.',
                        key='read_fact', labels={k: a.visible_sign for k, a, _ in pool})
        if not selected:
            publish(ctx, {'answer': 'The answer is unknown. The GM must establish this fact about the creature.'})
            return
        key, answer, relation = next(x for x in pool if x[0] == selected[0])
        if know(ctx, key, answer):
            if chosen == options[2]:
                publish(ctx, {'answer': answer.fact})
            elif chosen == options[3]:
                publish(ctx, {'answer': f'The identified authority has Source CL {answer.source_cl}.'})
            elif chosen == options[4]:
                publish(ctx, {'answer': 'Survives: ' + ', '.join(s.replace('_', ' ') for s in relation.survives)})


def condition(ctx, kind, label, *, expiry='UNTIL_REMOVED', rule=None, **data):
    return ctx.engine._apply_condition(ctx.target, STATE, ctx.source, ctx.actor.entity_id,
        expires_on=expiry, data={'kind': kind, 'label': label,
            'source_cl': int(ctx.numbers['cl']), **({'rule': rule} if rule else {}), **data})


def expiry(ctx, who, edge='start'):
    from .effect_durations import holder_next_turn
    return holder_next_turn(who, edge)


def damage(ctx, count, sides, *, half=False, flat=0):
    from ..typed_executor import run_effects
    kind = pick(ctx, ['Slashing', 'Necrotic'],
        f'Blood-Moon cut on {ctx.target.display_name}: choose Slashing or Necrotic damage; no additional cost.', key='damage_type')[0]
    row = {'type': 'damage', 'applies_to': 'target', 'damage_types': [kind.lower()], 'flat': flat}
    if count:
        row['dice'] = {'count': count, 'sides': sides}
    run_effects(replace(ctx, damage_divisor=2) if half else ctx, [row])


def saber_context(ctx, target):
    from .weapon_hits import weapon_item
    from ..activation_settlement import profile
    item = weapon_item(ctx)
    physical = saber({'source': item.get('item_id'), 'weapon': ctx.typed.get('weapon')})
    qi_saber = ctx.typed.get('sphere') == 'tianxia.sphere.sabers' and profile(ctx.engine, ctx.actor, ctx.action)['qi_powered']
    if not owned(ctx.engine, ctx.actor) or not (physical or qi_saber):
        return None
    return replace(ctx, target=target, targets=[target],
                   typed={**ctx.typed, 'numbers': numbers(ctx.engine, ctx.actor)})


def used(engine, actor, key):
    from ..turn_uses import current_turn_key
    return actor.turn_flags.get('once_per_turn:' + key) == current_turn_key(engine)


def spend(engine, actor, key):
    from ..turn_uses import current_turn_key
    actor.turn_flags['once_per_turn:' + key] = current_turn_key(engine)


@hook('damage_dealt')
def marked_cut(ctx, target, amount):
    # This notification already proves positive committed HP/Temporary HP
    # damage. Do not infer it from a bounded tail of unrelated log events.
    if amount <= 0:
        return
    ctx = saber_context(ctx, target)
    if ctx is None:
        return
    existing = marks(target, ctx.actor)
    if existing and not used(ctx.engine, ctx.actor, 'blood_moon_cut'):
        spend(ctx.engine, ctx.actor, 'blood_moon_cut')
        damage(ctx, 0, 0, flat=int(ctx.numbers['pb']) + len(existing))


@hook('damage_packet_selection')
def mark_on_confirmed_hit(ctx, target, packet_kinds):
    ctx = saber_context(ctx, target)
    if ctx is None:
        return
    existing = marks(target, ctx.actor)
    if len(existing) < 3 and ctx.actor.resources.get(QI, 0) >= 1 and not used(ctx.engine, ctx.actor, 'blood_moon_mark'):
        if pick(ctx, ['Apply Blood-Moon Mark'], f'{ctx.action.display_name} hit {target.display_name}. '
                'Spend 1 Qi to apply one Blood-Moon Mark until the scene ends?', key='mark', optional=True):
            ctx.engine._spend_resource(ctx.actor, QI, 1, ROWS[3])
            ctx.engine._apply_condition(target, MARK, ROWS[3], ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'label': 'Blood-Moon Mark: remains until the scene ends',
                    'source_cl': int(ctx.numbers['cl'])})
            spend(ctx.engine, ctx.actor, 'blood_moon_mark')
            info = facts(ctx.engine, target, ctx.actor)
            publish(ctx, {'answer': 'At or below half maximum Hit Points.' if target.current_hp * 2 <= target.maximum_hp
                         else 'Above half maximum Hit Points.',
                'regeneration': next((int(r.present) for _, _, r in info if r.kind == 'regeneration'), 'unknown'),
                'death_prevention': next((int(r.present) for _, _, r in info if r.kind == 'death_prevention'), 'unknown'),
                'body_mode': next((r.category for _, _, r in info if r.kind == 'body_mode'), 'not yet recorded')})


@hook('after_hit_effects')
def after_damage_sentences(ctx, target, kind):
    from .weapon_hits import weapon_item
    item = weapon_item(ctx)
    if kind != 'weapon' or not saber({'source': item.get('item_id'), 'weapon': ctx.typed.get('weapon')}):
        return
    ctx = saber_context(ctx, target)
    if ctx is not None and owned(ctx.engine, ctx.actor, 6) and marks(target, ctx.actor):
        sentences(ctx)


def sentences(ctx):
    from .qi_subpaths_four import walk
    from ..technique_alignment import eligible
    available = ['Close the Wound', 'Cut the Step', 'Cut the Hand', 'Cut the Breath']
    types = set()
    for e in walk(ctx.typed.get('effects') or []):
        types.update(e.get('damage_types') or [])
    if (ctx.typed.get('weapon') or {}).get('damage_type'):
        types.add(ctx.typed['weapon']['damage_type'])
    channels = eligible(ctx.typed)
    channel_options = {**{'damage:' + k.lower(): k.title() + ' damage' for k in types},
                       **{'tag:' + k: k.title() + ' elemental channel' for k in channels}}
    if channel_options:
        available.append('Cut the Channel')
    chosen = pick(ctx, available, f'Sever the Returning Breath: spend one of your marks on '
        f'{ctx.target.display_name} for each different Sentence after damage; no Qi cost.', key='sentences',
        maximum=min(3, len(marks(ctx.target, ctx.actor))), optional=True)
    if not chosen:
        return
    remove(ctx.engine, ctx.target, marks(ctx.target, ctx.actor)[:len(chosen)])
    for name in chosen:
        if name == 'Close the Wound':
            condition(ctx, 'healing', name + ': cannot regain Hit Points or gain Temporary Hit Points',
                expiry=expiry(ctx, ctx.target, 'end') if len(chosen) >= 2 else expiry(ctx, ctx.actor),
                rule={'healing_denied': True, 'temp_hp_denied': True})
        elif name == 'Cut the Step':
            condition(ctx, 'speed', name + ': Speed reduced by 15 feet', expiry=expiry(ctx, ctx.actor), speed=-15)
        elif name == 'Cut the Hand':
            condition(ctx, 'hand', name + ': no Reactions; next weapon attack has Disadvantage',
                expiry=expiry(ctx, ctx.target), rule={'no_reactions': True}, next_attack=1)
        elif name == 'Cut the Breath':
            condition(ctx, 'surcharge', name + ': next Qi feature costs 2 extra Qi',
                expiry=expiry(ctx, ctx.target, 'end'), amount=2, resource=QI)
        else:
            selected = pick(ctx, list(channel_options), f'Cut the Channel: choose a type used by '
                f'{ctx.action.display_name}; {ctx.target.display_name} cannot activate a feature requiring only that channel '
                'until your next turn starts.', key='channel', labels=channel_options)[0]
            channel_kind, channel = selected.split(':', 1)
            condition(ctx, 'channel', 'Cut the Channel: ' + channel_options[selected],
                expiry=expiry(ctx, ctx.actor), channel=channel, channel_kind=channel_kind)
    if len(chosen) >= 2:
        roll = ctx.engine._roll_save(ctx.target, 'CON', int(ctx.numbers['save_dc']), ctx.source)
        if roll is not None and roll.total >= int(ctx.numbers['save_dc']):
            from ..typed_executor import run_effects
            run_effects(ctx, [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 1, 'sides': 8}, 'damage_types': ['necrotic']}])
        else:
            condition(ctx, 'hemorrhage', 'Moonlit Hemorrhage: 2d8 Necrotic damage at your next turn start',
                      due_turn=ctx.target.turns_started + 1)


def threshold(ctx):
    from ..typed_executor import CP_POOLS, condition_rules
    target = ctx.target
    pools = [p for p in CP_POOLS if p in target.resources]
    return len(marks(target, ctx.actor)) == 3 and (
        target.current_hp * 2 <= target.maximum_hp
        or any(c.condition_id in {'condition:typed.incapacitated', 'condition:typed.unconscious'}
               or c.condition_id == 'condition:typed.restrained' and c.source_actor_id == ctx.actor.entity_id
               for c in target.conditions.values())
        or any(r.get('no_reactions') for r in condition_rules(target))
        or bool(pools) and all(target.resources[p] == 0 for p in pools)
        or bool(states(target, 'system'))
        or any(c.data.get('suppressed') and c.data.get('major_system')
               for c in target.conditions.values())
        or int(ctx.numbers['cl']) >= target_cl(ctx.engine, target) + 6)


def target_cl(engine, target):
    from .passive_rows import known_level
    level = known_level(engine, target)
    return int(level) if level is not None else 99


def identified_relations(ctx, kinds, *, category=None):
    return [(key, answer, relation) for key, answer, relation in facts(
        ctx.engine, ctx.target, ctx.actor)
        if relation.kind in kinds and (category is None or relation.category == category)]


def has_survival_authority(ctx):
    # An unrelated or lower-authority note is not protection against this sentence.
    return any(answer.source_cl is not None and int(answer.source_cl) >= int(ctx.numbers['cl'])
        and 'bodily_execution' in relation.survives
        for _, answer, relation in identified_relations(ctx, {'survival'}))


def execution_wound_options(ctx):
    options = ['Closed Meridian', 'Broken Weapon Channel', 'Moon-Sealed Healing']
    structures = identified_relations(ctx, {'structure'})
    if structures:
        options.append('Severed Limb')
    if any(relation.ordinary_vital for _, _, relation in structures):
        options.append('Ruined Organ')
    return options


def death_save_required(ctx, within):
    return not (within and int(ctx.numbers['cl']) >= target_cl(ctx.engine, ctx.target) + 6
                and not has_survival_authority(ctx))


def save(ctx, ability, *, disadvantage=False):
    roll = ctx.engine._roll_save(ctx.target, ability, int(ctx.numbers['save_dc']), ctx.source,
        extra_mode='DISADVANTAGE' if disadvantage else 'NORMAL')
    return roll is not None and roll.total >= int(ctx.numbers['save_dc'])


def wound(ctx, name, *, temporary=False, repeat=True):
    end = expiry(ctx, ctx.target, 'end') if temporary else 'UNTIL_REMOVED'
    if name in {'Severed Limb', 'Ruined Organ', 'Moonlit Dismemberment'}:
        pool = [(k, a, r) for k, a, r in facts(ctx.engine, ctx.target, ctx.actor)
                if r.kind == 'structure' and (name != 'Ruined Organ' or r.ordinary_vital)]
        if not pool:
            raise ValueError(f'The GM must record an identified bodily structure of {ctx.target.display_name} before {name}.')
        chosen = pick(ctx, [k for k, _, _ in pool], f'{name}: choose identified structures on '
            f'{ctx.target.display_name}. Physical injuries require suitable treatment.', key='structures',
            maximum=1 if temporary or name != 'Moonlit Dismemberment' else min(3, len(pool)),
            labels={k: r.name for k, _, r in pool})
        for key in chosen:
            answer, relation = declaration(ctx, key)
            condition(ctx, 'structure', f'{relation.name}: disabled' if temporary else f'{relation.name}: severed or destroyed',
                expiry=end, relationship=key, source_ids=list(relation.source_ids),
                physical=int(not temporary), recovery_rule=relation.recovery_rule)
    else:
        rule = {'healing_denied': True} if name == 'Moon-Sealed Healing' else None
        data = {'repeat_save': {'ability': 'CON', 'dc': int(ctx.numbers['save_dc'])}} if repeat else {}
        if name == 'Moon-Sealed Healing' and not temporary:
            from ..typed_executor import effect_expiry
            end = effect_expiry(ctx, {'duration': {'kind': 'minutes', 'amount': 1}}, ctx.target, condition=True)
        condition(ctx, 'cp_recovery' if name == 'Closed Meridian' else 'weapon_channel' if name == 'Broken Weapon Channel'
            else 'healing', name, expiry=end, rule=rule, **data)


def severe_dying(ctx):
    from .life_state import reduce_to_dying
    reduce_to_dying(ctx.engine, ctx.target, ctx.source, ctx.actor.entity_id, failures=2)


@effect('blood_moon_execution', harmful=True)
def execution(ctx, row):
    tier = row['tier']
    if ctx.target is None or not owned(ctx.engine, ctx.actor, tier) or len(marks(ctx.target, ctx.actor)) != 3:
        return
    within = threshold(ctx)
    if tier == 10:
        options = execution_wound_options(ctx)
        if owned(ctx.engine, ctx.actor, 14) and ctx.actor.resources.get(QI, 0) >= 3:
            if identified_relations(ctx, {'system'}, category='sphere'):
                options.append('Sever Sphere')
            if identified_relations(ctx, {'system'}, category='method'):
                options.append('Sever Method')
            if identified_relations(ctx, {'system'}):
                options.append('Sever Core Function')
            if identified_relations(ctx, {'vessel'}):
                options.append('Sever Soul from Vessel')
            if within:
                options.append('Sever Life from Body')
        wound_labels = {
            'Closed Meridian': 'Closed Meridian — no Cultivation Point recovery until repaired',
            'Broken Weapon Channel': 'Broken Weapon Channel — no weapon-delivered cultivation techniques',
            'Moon-Sealed Healing': 'Moon-Sealed Healing — cannot regain Hit Points for 1 minute',
            'Severed Limb': 'Severed Limb — disables one identified bodily structure until treated',
            'Ruined Organ': 'Ruined Organ — destroys one identified ordinary vital organ until repaired',
        }
        chosen = pick(ctx, options, f'Moon-Edged Sentence hit {ctx.target.display_name}. Choose an Execution Wound '
            'or spend 3 additional Qi for Cultivation Severance.', key='execution', labels=wound_labels,
            preferred=['Closed Meridian'])[0]
        severance = chosen.startswith('Sever ') and chosen != 'Severed Limb'
        if severance:
            ctx.engine._spend_resource(ctx.actor, QI, 3, ROWS[14])
        success = save(ctx, 'CON', disadvantage=within)
        damage(ctx, 5, 8, half=success)
        if success:
            condition(ctx, 'healing', 'Cannot regain Hit Points until your next turn starts',
                expiry=expiry(ctx, ctx.target), rule={'healing_denied': True})
        elif severance:
            sever(ctx, chosen)
        else:
            wound(ctx, chosen)
    else:
        final_options = final_sentence_options(ctx)
        chosen = pick(ctx, final_options,
            f'Blood Moon Falls on the Condemned hit {ctx.target.display_name}: choose a Final Sentence.', key='final')[0]
        no_save_death = chosen == 'Death' and not death_save_required(ctx, within)
        success = False if no_save_death else save(ctx, 'CHA' if chosen in {'Core Execution', 'End the Return'} else 'CON')
        damage(ctx, 10, 10, half=success)
        if chosen == 'Death':
            if success:
                condition(ctx, 'healing', 'Cannot regain Hit Points until your next turn ends',
                    expiry=expiry(ctx, ctx.target, 'end'), rule={'healing_denied': True})
            elif within:
                from .life_state import die
                if not has_survival_authority(ctx):
                    die(ctx.engine, ctx.target, 'bodily_execution', ctx.source)
            else:
                severe_dying(ctx)
                condition(ctx, 'healing', 'Cannot regain Hit Points until the executioner’s next turn starts',
                    expiry=expiry(ctx, ctx.actor), rule={'healing_denied': True})
        elif chosen == 'Moonlit Dismemberment':
            wound(ctx, chosen, temporary=success, repeat=False)
        else:
            sever(ctx, chosen, final=True, success=success)
    remove(ctx.engine, ctx.target, marks(ctx.target, ctx.actor))


def final_sentence_options(ctx):
    """Return only final sentences backed by the target's identified fact pools."""
    available_facts = facts(ctx.engine, ctx.target, ctx.actor)
    options = ['Death']
    if any(relation.kind == 'system' for _, _, relation in available_facts):
        options.append('Core Execution')
    if any(relation.kind in {'survival', 'regeneration', 'death_prevention'}
           for _, _, relation in available_facts):
        options.append('End the Return')
    if identified_relations(ctx, {'structure'}):
        options.insert(1, 'Moonlit Dismemberment')
    return options


def sever(ctx, name, *, final=False, success=False):
    if name == 'Sever Life from Body':
        severe_dying(ctx)
        return
    kinds = {'vessel'} if name == 'Sever Soul from Vessel' else {'survival', 'regeneration', 'death_prevention'} if name == 'End the Return' else {'system'}
    pool = [(k, a, r) for k, a, r in facts(ctx.engine, ctx.target, ctx.actor) if r.kind in kinds
        and (name != 'Sever Sphere' or r.category == 'sphere')
        and (name != 'Sever Method' or r.category == 'method')]
    if not pool:
        raise ValueError(f'The GM must record an identified system or authority of {ctx.target.display_name} before {name}.')
    chosen = pick(ctx, [k for k, _, _ in pool], f'{name}: choose an identified active relationship of '
        f'{ctx.target.display_name}; ordinary rest cannot repair severance.', key='system',
        labels={k: r.name for k, _, r in pool})
    if not chosen:
        return
    key = chosen[0]
    answer, relation = declaration(ctx, key)
    from ..typed_executor import effect_expiry
    weaker = target_cl(ctx.engine, ctx.target) <= int(ctx.numbers['cl']) - 6
    until_scene = name == 'Sever Sphere' and weaker and not success
    end = ('UNTIL_REMOVED' if final and name == 'Core Execution' and not success or until_scene
        else expiry(ctx, ctx.actor) if name == 'End the Return' and success
        else expiry(ctx, ctx.target, 'end') if success
        else effect_expiry(ctx, {'duration': {'kind': 'minutes', 'amount': 1}}, ctx.target, condition=True))
    condition(ctx, 'system', f'{name}: {relation.name}',
        expiry=end,
        relationship=key, source_ids=list(relation.source_ids),
        category=relation.category, physical=int(final and not success and relation.supports_destruction),
        until_scene_end=int(until_scene),
        recovery_rule=relation.recovery_rule,
        **({'repeat_save': {'ability': 'CHA', 'dc': int(ctx.numbers['save_dc'])}}
           if name == 'Sever Sphere' and not success and not weaker else {}))
    if name == 'Sever Soul from Vessel':
        from ..action_geometry import distance
        heir = vessel_heir(ctx.engine, ctx.target, distance)
        condition(ctx, 'vessel_control', 'Controlling identity transferred to the nearest surviving vessel',
            expiry='UNTIL_REMOVED', controller_id=heir.entity_id if heir else None)
    if final and success and name == 'Core Execution':
        condition(ctx, 'surcharge', 'Core Execution: next Cultivation Point feature costs 5 extra', amount=5, resource='CP')


@hook('attack_mode')
def final_advantage(ctx, target):
    return 'ADVANTAGE' if ctx.typed.get('blood_moon_tier') == 18 else None


@hook('cover_reduction')
def execution_cover(engine, attacker, target, cover):
    if not owned(engine, attacker, 10) or len(marks(target, attacker)) != 3:
        return None
    from ..shot_geometry import action
    current = action(engine, attacker)
    final = bool(current and (current.parameters.get('typed') or {}).get('blood_moon_tier') == 18)
    if cover == 2 or final and cover == 5:
        return 2 if final else 1


@hook('attack_mode_removed')
def execution_accuracy(engine, attacker, target, ranged):
    if owned(engine, attacker, 10) and len(marks(target, attacker)) == 3:
        return ['DISADVANTAGE:invisible']


@hook('resistance_ignored')
def execution_resistance(engine, kind, typed, source_actor_id, target):
    actor = engine.state.actors.get(source_actor_id)
    if (actor is not None and owned(engine, actor, 18) and typed.get('blood_moon_tier') == 18
            and str(kind).lower() in {'slashing', 'necrotic'}):
        return True


@hook('attack_result')
def final_attempt(ctx, target, hit, critical):
    if ctx.typed.get('blood_moon_tier') != 18:
        return
    condition(replace(ctx, target=ctx.actor), 'final_used', 'Blood Moon used this scene')
    if not hit:
        remove(ctx.engine, target, marks(target, ctx.actor)[:1])


@hook('speed')
def speed(engine, actor):
    return sum(int(c.data.get('speed', 0)) for c in states(actor)) or None


@hook('attack_mode')
def hand(ctx, target):
    if ctx.typed.get('weapon') and any(c.data.get('next_attack') for c in states(ctx.actor, 'hand')):
        return 'DISADVANTAGE'


@hook('attack_result')
def consume_hand(ctx, target, hit, critical):
    if ctx.typed.get('weapon'):
        for c in states(ctx.actor, 'hand'):
            if c.data.get('next_attack'):
                ctx.engine._update_condition_data(ctx.actor, c, {**c.data, 'next_attack': 0}, ctx.source)


@hook('resource_gain_allowed')
def recovery(engine, actor, resource_id, amount, source_id):
    from ..typed_executor import CP_POOLS
    if resource_id in CP_POOLS and states(actor, 'cp_recovery'):
        return False


@hook('technique_cost_surcharge')
def surcharge(engine, actor, source_id, listed):
    from ..typed_executor import CP_POOLS
    from ..activation_settlement import profile
    action = engine.action_catalog.get(source_id)
    if action is None:
        return None
    qi_powered = bool(profile(engine, actor, action)['qi_powered'])
    from ..typed_executor import CP_POOLS
    result = {}
    for c in states(actor, 'surcharge'):
        amount = int(c.data['amount'])
        if c.data['resource'] == 'CP':
            # Core Execution's printed +5 CP attaches to the next feature that pays a Cultivation Point pool:
            # quote it against that listed pool (Qi, stamina or resonance), so affordability and payment agree.
            pools = [r for r, n in listed.items() if r in CP_POOLS and n > 0 and r in actor.resources]
            if pools:
                result[pools[0]] = result.get(pools[0], 0) + amount
        elif c.data['resource'] == QI and qi_powered and QI in actor.resources:
            # Cut the Breath is explicitly a surcharge on Qi-powered features only;
            # a non-Qi feature must neither fail nor pay the surcharge in CP.
            result[QI] = result.get(QI, 0) + amount
    return result or None


@hook('activation_settlement')
def paid(ctx, receipt):
    action = ctx.action
    from ..typed_executor import CP_POOLS
    from ..activation_settlement import profile
    resources = {p for p, n in action.costs if n > 0}
    if profile(ctx.engine, ctx.actor, action)['qi_powered']:
        resources.add(QI)
    remove(ctx.engine, ctx.actor, [c for c in states(ctx.actor, 'surcharge')
        if c.data['resource'] in resources or c.data['resource'] == 'CP' and resources.intersection(CP_POOLS)])


@hook('activation_settlement')
def observe_sphere(ctx, receipt):
    sphere = ctx.typed.get('sphere')
    if not sphere:
        return
    from ..observer_information import publish
    from ..target_knowledge import can_see
    for observer in ctx.engine.state.actors.values():
        if owned(ctx.engine, observer, 14) and can_see(ctx.engine, observer, ctx.actor):
            publish(ctx.engine, observer, ROWS[14], observer, 'declaration',
                {'target_id': ctx.actor.entity_id, 'observed_sphere': sphere,
                 'used_source_id': ctx.source, 'source_cl': int(receipt['source_cl'] or ctx.numbers['cl']),
                 'text': f"{ctx.actor.display_name} used the {sphere.rsplit('.', 1)[-1].replace('_', ' ').title()} Sphere in this scene."},
                'UNTIL_REMOVED')


@hook('candidate_allowed')
def suppressed(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if any(c.data.get('kind') == 'system' and severed_action(c, action, typed) for c in states(actor)):
        return False
    for c in states(actor):
        if action.source_definition_id in c.data.get('source_ids', []):
            return False
        if c.data['kind'] == 'weapon_channel':
            from .qi_subpaths_four import walk
            from ..activation_settlement import profile
            from ..weapon_delivery import delivery_kind
            cultivation = profile(engine, actor, action)
            delivered = any(delivery_kind(typed, e, action.parameters) == 'weapon'
                            for e in walk(typed.get('effects') or []) if e.get('type') == 'attack')
            if typed.get('qi_weapon_delivery') or delivered and (
                    cultivation['qi_powered'] or cultivation['source_kind'] in {
                        'Path', 'Subpath', 'Sphere', 'Recorded', 'Forged', 'Immortal'}):
                return False
        if c.data['kind'] == 'channel':
            from .qi_subpaths_four import walk
            from ..activation_settlement import profile
            if profile(engine, actor, action)['source_kind'] not in {'Path', 'Subpath', 'Sphere', 'Forged', 'Recorded', 'Immortal', 'item'}:
                continue
            channel = c.data['channel'].lower()
            kinds = {str(k).lower() for e in walk(typed.get('effects') or []) for k in e.get('damage_types') or []}
            if (typed.get('weapon') or {}).get('damage_type'):
                kinds.add(str(typed['weapon']['damage_type']).lower())
            if (c.data['channel_kind'] == 'damage' and kinds == {channel}
                    or c.data['channel_kind'] == 'tag' and channel in typed.get('required_channels', [])):
                return False


def severed_action(condition, action, typed):
    """A severed Sphere/Method/system stops every action it delivers, not only the action it first named."""
    fields = {action.source_definition_id, typed.get('sphere'), typed.get('method'), typed.get('source')}
    return any(sid in fields for sid in condition.data.get('source_ids', []))


def vessel_heir(engine, target, distance):
    """The nearest living combatant other than the severed target: the surviving vessel that takes the controlling identity."""
    living = [a for a in engine.state.actors.values() if a is not target and a.current_hp > 0]
    return min(living, key=lambda a: (distance(engine, target, a), a.entity_id), default=None)


def _row_severed(row, severed):
    """A passive row belongs to a severed source when its block, feature, or source names one of the severed IDs."""
    return bool(severed) and any(row.get(k) in severed for k in ('block', 'feature_id', 'source', 'source_definition_id'))


@hook('event', nested=True)
def sever_passive_rows(engine, event_type, kwargs):
    """Passive benefits of a severed Sphere, Method or system stop feeding every consumer while the severance holds.

    Only actors with a severance are touched: their matching rows move to a stash and come back when the severance ends.
    Every other runtime row (other plug-ins' rows and mutations) is left exactly as it is."""
    rows_by_actor = getattr(engine, 'typed_passive_rows', None)
    if rows_by_actor is None:
        return
    hidden = getattr(engine, '_blood_moon_hidden_rows', None)
    if hidden is None:
        hidden = {}
        setattr(engine, '_blood_moon_hidden_rows', hidden)
    for actor_id, actor in engine.state.actors.items():
        severed = {sid for c in actor.conditions.values() if c.condition_id == STATE and c.data.get('kind') == 'system'
                   for sid in c.data.get('source_ids', [])}
        rows = rows_by_actor.get(actor_id) or []
        if severed:
            gone = [r for r in rows if _row_severed(r, severed)]
            if gone:
                hidden.setdefault(actor_id, []).extend(gone)
                rows_by_actor[actor_id] = [r for r in rows if not _row_severed(r, severed)]
        elif hidden.get(actor_id):
            rows_by_actor[actor_id] = [*rows, *hidden.pop(actor_id)]


@hook('event', nested=True)
def scene_boundary(engine, event_type, kwargs):
    """Only the existing protected GM fact command establishes a scene end."""
    if event_type != 'TABLE_FACT_RECORDED' or not (kwargs.get('payload') or {}).get('fact', {}).get('scene_ended'):
        return
    for actor in engine.state.actors.values():
        remove(engine, actor, [c for c in actor.conditions.values()
            if c.condition_id == MARK or c.condition_id == STATE and (
                c.data.get('kind') == 'final_used' or c.data.get('until_scene_end'))
            or c.condition_id == 'condition:information.reading' and c.source_definition_id in ROWS.values()])


@hook('turn_start')
def hemorrhage(engine, actor):
    for c in list(states(actor, 'hemorrhage')):
        if actor.turns_started >= c.data['due_turn']:
            from ..gate2_runtime_models import DiceSpec
            roll = engine.roller.roll(DiceSpec(count=2, sides=8), actor_id=actor.entity_id, reason='Moonlit Hemorrhage')
            engine._record_roll(roll)
            engine._commit_damage(actor, roll.total, 'NECROTIC', c.source_definition_id, c.source_actor_id,
                                  engine._active_intent, reaction_depth=0)
            remove(engine, actor, [c])


@hook('observer_information')
def directions(engine, viewer):
    if not owned(engine, viewer):
        return None
    from ..observer_information import direction
    return [{'kind': 'direction', 'source_id': ROWS[3], 'viewer_id': viewer.entity_id,
             'ability': 'Blood-Moon Mark',
             'text': f'Direction to a creature bearing your mark: {direction(viewer.position, target.position)}.',
             'details': {'target_id': target.entity_id, 'direction': direction(viewer.position, target.position)}}
            for target in engine.state.actors.values() if marks(target, viewer)
            and engine._distance_actor_to_actor(viewer, target) <= 5280]
