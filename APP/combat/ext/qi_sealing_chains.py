"""Source-owned Cultivator of Seals bindings and native release actions.

New qi5_chain rows opt in through condition_state. Native Restrained owns the
condition's combat rules and Concentration/finite clock. Repeat saves and
escape checks release the exact instance, preserving other casters' holds.

A forced Core Seal downgrade (first successful Break the Seal, or a 3+ CL-higher
application) keeps the Mark but asks its source to pick one printed Meridian
scope; the Meridian scope replaces the Core scope until the start of the
target's next turn, then the stored Core scope applies again with its success
count intact (lead rules ruling, MGR-T14-sol-seam-cultivator-of-seals-4).
"""
from . import hook, effect
from .condition_ownership import remove_instance
from .passive_rows import known_level
from . import needle, run_strict
from copy import deepcopy
from pathlib import Path

SOURCE = 'tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'
PREFIX = 'tianxia.subpath.qi.cultivator_of_seals.feature.'
MINOR, MARK, PRISON, EDICT = [PREFIX + key for key in
    ('minor_seal', 'sealing_mark', 'prison_of_law', 'heaven_sealing_edict')]
LEVELS = {MINOR: 3, SOURCE: 6, MARK: 10, PRISON: 14, EDICT: 18}
SEAL = 'condition:typed.qi_seal'


@hook('feature_access_policy')
def access_policy(feature):
    if feature in LEVELS:
        return {'path': 'tianxia.path.qi_cultivation', 'minimum_cl': LEVELS[feature],
                'classification': 'Restricted Scripture',
                'source_kinds': ['scripture', 'teacher', 'inheritance']}


def seals(engine, subject=None):
    """Live source-owned bindings; no ability ownership is inferred from names."""
    actors = [subject] if subject is not None else engine.state.actors.values()
    return [(a, c) for a in actors for c in list(a.conditions.values())
            if c.condition_id == SEAL and c.data.get('seal_feature') in LEVELS]


def choose(ctx, who, key, labels, prompt, preferred=None):
    picked = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'QI_SEAL_' + key, ctx.source, who.entity_id),
        who, 'choice:needle.qi_seal.' + key, list(labels), labels=labels,
        name=ctx.action.display_name, target_id=getattr(ctx.target, 'entity_id', None),
        prompt=prompt, preferred=preferred or list(labels)[:1])
    return picked[0] if picked else None


def source_feature(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return typed.get('option_of') or typed.get('source')


def native_action(original, feature, numbers, *, grade='functional'):
    """Replace this family's old declaration rows with one native implementation."""
    costs = {MINOR: 1, SOURCE: 3, PRISON: 6, EDICT: 8, MARK:
             {'functional': 5, 'meridian': 7, 'core': 10}[grade]}
    params = deepcopy(original.parameters)
    typed = params.setdefault('typed', {})
    typed.update(source=feature, numbers=dict(numbers), seal_native=1,
        manual_inline_choice=True, effects=[{'type': 'qi_seal_native', 'feature': feature, 'grade': grade}],
        riders=[], duration={'kind': 'minutes', 'amount': 1, 'concentration': True}
        if feature in {PRISON, EDICT} else {'kind': 'instant'})
    if feature == EDICT:
        typed['requires_seen_target'] = True
    params['expected_damage'] = 0
    params.pop('gm_only', None)
    target = 'OBJECT' if feature == MINOR else 'ANY_CREATURE'
    if feature == MINOR:
        params['qi_minor_target'] = 1
    limit = next((key for key, _ in original.costs if key.startswith('resource:uses.')),
                 f'resource:uses.qi_seal.{original.owner_id}.{feature}.scene')
    payment = [('resource:core.qi', costs[feature])]
    if feature == EDICT or feature == MARK and grade == 'core':
        payment.append((limit, 1))
    return original.model_copy(update={'parameters': params, 'target_kind': target,
        'range_ft': {MINOR: 30, MARK: 5, PRISON: 60, EDICT: 90}[feature],
        'costs': tuple(payment), 'resolution_kind': 'TYPED'})


@hook('compile_action')
def native_compilation(action, info):
    feature = source_feature(action)
    if feature not in LEVELS:
        return None
    from ..subpath_acquisition import acquired_features
    native = acquired_features(info['owner_sheet'], Path(__file__).resolve().parents[2])
    params = deepcopy(action.parameters)
    typed = params.setdefault('typed', {})
    numbers = dict(typed.get('numbers') or {})
    numbers['cl'] = native.get(feature, {}).get('cl', numbers.get('cl', 1))
    typed.update(numbers=numbers, min_cl=LEVELS[feature])
    action = action.model_copy(update={'parameters': params})
    if feature == SOURCE or typed.get('seal_native'):
        return action
    return native_action(action, feature, numbers)


@hook('compile_actions')
def seal_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..subpath_acquisition import acquired_features
    native = acquired_features(info['owner_sheet'], Path(__file__).resolve().parents[2])
    out = []
    for feature in sorted({MINOR, MARK, PRISON, EDICT} & set(info['owned_ids'])):
        numbers = {**info['numbers'], 'cl': native.get(feature, {}).get('cl', info['numbers']['cl'])}
        if numbers['cl'] < LEVELS[feature]:
            continue
        originals = [a for a in info['actions'] if source_feature(a) == feature]
        base = originals[0] if originals else ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{feature}", owner_id=info['actor_id'],
            display_name=info['mechanics'][feature]['name'], economy=EconomyKind.ACTION,
            resolution_kind='TYPED', target_kind='ANY_CREATURE', parameters={})
        if not originals:
            out.append(native_action(base, feature, numbers))
        if feature == MARK:
            for grade in ('meridian', 'core'):
                variant = base.model_copy(update={'source_definition_id': base.source_definition_id + '.' + grade,
                    'display_name': 'Sealing Mark: ' + grade.title() + ' Seal'})
                out.append(native_action(variant, feature, numbers, grade=grade))
    return out


@hook('match_start')
def install_release_actions(engine):
    """Install universal release procedures only in a fight containing this family."""
    from ..gate2_runtime_models import ActionDefinition
    if not any(source_feature(a) in LEVELS for a in engine.action_catalog.values()):
        return
    for key, label in [('break', 'Break the Seal'), ('aid', 'Remove a nearby seal')]:
        source = 'system:qi_seal_' + key
        engine.action_catalog[source] = ActionDefinition(source_definition_id=source,
            owner_id='*', display_name=label, economy='ACTION', resolution_kind='TYPED', target_kind='SELF',
            parameters={'qi_seal_release': key, 'expected_damage': 0, 'typed': {'source': source,
                'manual_inline_choice': True, 'numbers': {}, 'effects': [{'type': 'qi_seal_release', 'kind': key}], 'riders': []}})


@hook('additional_actions')
def release_actions(engine, actor):
    out = []
    if breakable_bindings(engine, actor):
        out.append('system:qi_seal_break')
    if nearby_anchors(engine, actor):
        out.append('system:qi_seal_aid')
    return [source for source in out if source in engine.action_catalog]


SCOPES = {
    'functional': {'teleportation': 'Teleportation', 'flight': 'Flight', 'incorporeal': 'Becoming Incorporeal',
        'transformation': 'Shapechanging', 'summons': 'Creating new summoned creatures or Cultivation Assets',
        'audible': 'Activating Audible techniques', 'spirit_domain': 'Manifesting a Spirit Awakening Domain',
        'sphere': 'One named Sphere', 'path_feature': 'One named Path feature',
        'subpath_feature': 'One named Subpath feature', 'item_property': 'One named item property',
        'weapon_delivery': 'Weapon-delivered cultivation techniques', 'armament': 'Domain Armament attacks, movement or remote origins'},
    'meridian': {'sphere': 'One named Sphere and all its techniques', 'resource_recovery': 'One Cultivation Point resource’s recovery',
        'expenditure_limit': 'Voluntary Cultivation Point expenditure above the seal creator’s Proficiency Bonus per turn',
        'qi_channel': 'One recorded elemental or conceptual Qi channel', 'weapon_delivery': 'All weapon-delivered cultivation techniques',
        'armament': 'Domain Armament manifestation, attacks, movement and remote origins',
        'summons': 'One complete category of summons', 'transformation': 'One complete category of transformations',
        'formation_commands': 'One complete category of Formation commands'},
    'core': {'path': 'One complete Path’s active features and Cultivation Point expenditure',
        'subpath': 'One Subpath and all its features', 'method': 'One Method and all its benefits',
        'core': 'One Golden Core Form or equivalent Core engine', 'soul': 'Nascent Soul or equivalent autonomous cultivation structure',
        'foundation': 'One Foundation’s active, triggered and resource-spending benefits',
        'all_spheres': 'All Spheres known by the target', 'all_items_armament': 'All cultivated-item activations and Domain Armament functions'},
    'prison': {'planar': 'Teleportation and planar movement', 'possession': 'Incorporeal movement and possession',
        'sphere': 'One named Sphere', 'assets': 'Domain and Cultivation Asset manifestation',
        'resource': 'One named Cultivation Point resource', 'weapon_delivery': 'Weapon-delivered cultivation techniques',
        'transformation': 'One named transformation or body-changing system'},
}


def fact_answers(engine, viewer, target, category):
    from ..table_facts import records
    return [answer for fact in records(engine, viewer).values() if fact.subject_id == target.entity_id
            for key, answer in fact.answers.items() if key == category and answer.category == category]


def subdued(ctx, target, willing=False):
    from .cp_pools import all_of
    if willing or target.life_state == 'STABLE' and target.current_hp == 0:
        return True
    if needle.incapacitated(target):
        return True
    pools = all_of(target)
    if pools and sum(target.resources.get(pool, 0) for pool in pools) == 0:
        return True
    if any(c.source_actor_id == ctx.actor.entity_id for c in holds(target)):
        return True
    if any(c.source_actor_id == ctx.actor.entity_id and c.data.get('seal_feature') == PRISON
           and c.data.get('imprisoned') for _, c in seals(ctx.engine, target)):
        return True
    return bool(fact_answers(ctx.engine, ctx.actor, target, 'complete_defeat_and_sealing_authority'))


def prepared(engine, actor, target):
    return any(c.source_actor_id == actor.entity_id for c in holds(target)) or any(
        c.source_actor_id == actor.entity_id and c.data.get('imprisoned') for _, c in seals(engine, target))


def scope_choice(ctx, grade):
    labels = SCOPES[grade]
    who = ctx.target or ctx.actor
    kind = choose(ctx, ctx.actor, 'scope', labels,
        f'{ctx.action.display_name}: choose the exact function to suppress on {who.display_name}.')
    value = ''
    if kind in {'sphere', 'path_feature', 'subpath_feature', 'path', 'subpath', 'method', 'core', 'soul',
                'foundation', 'item_property', 'qi_channel', 'formation_commands', 'resource', 'resource_recovery'} or (
            kind in {'transformation', 'summons'} and grade != 'functional'):
        options = named_options(ctx, kind)
        if not options:
            raise ValueError('Record the named cultivation system and its printed source before sealing it.')
        value = choose(ctx, ctx.actor, 'named_' + kind, options,
            f'{ctx.action.display_name}: name the exact {labels[kind].lower()} to suppress on {who.display_name}.')
    return {'kind': kind, 'value': value}


def downgrade_scope_choice(ctx, chooser):
    """The seal's source picks one printed Meridian scope for a forced Core
    downgrade, with the same named-option rules as a normal Meridian Seal.
    The Meridian Requirement is a new-casting gate and does not apply here
    (lead rules ruling, MGR-T14-sol-seam-cultivator-of-seals-4)."""
    from dataclasses import replace
    return scope_choice(replace(ctx, actor=chooser), 'meridian')


def current_scope(actor, condition):
    """Effective scope right now. During a forced Core downgrade window the
    chosen Meridian scope replaces the stored Core scope; after the target's
    next turn starts the Core scope applies again."""
    data = condition.data
    downgrade = data.get('downgrade_scope')
    if downgrade and actor.turns_started < int(data.get('downgraded_until_turn', 0)):
        return downgrade
    return data.get('scope') or {}


def named_options(ctx, kind):
    """Public catalogue choices, or witnessed source facts; never hidden sheet inspection."""
    from ..typed_numbers import authority_mechanics
    from .cp_pools import path_pool_ids
    mechanics = authority_mechanics()
    if kind in {'resource', 'resource_recovery'}:
        from ..resource_labels import resource_name
        return {pool: resource_name(pool) for pool in path_pool_ids()}
    if kind == 'sphere':
        return {row['sphere_id']: row['sphere_id'].split('.')[-1].replace('_', ' ').title()
                for row in mechanics.values() if row.get('sphere_id')}
    prefix = {'path': 'tianxia.path.', 'subpath': 'tianxia.subpath.', 'method': 'tianxia.method.',
              'core': 'tianxia.golden_core.', 'soul': 'tianxia.nascent_soul.',
              'foundation': 'tianxia.foundation.', 'path_feature': 'tianxia.path.',
              'subpath_feature': 'tianxia.subpath.'}.get(kind)
    if prefix:
        out = {}
        for key, row in mechanics.items():
            if key.startswith(prefix):
                if kind.endswith('_feature'):
                    out[key] = row.get('name') or key
                else:
                    parent = key.split('.feature.')[0]
                    out[parent] = parent.split('.')[-1].replace('_', ' ').title()
        return out
    return {answer.fact: answer.visible_sign for answer in fact_answers(ctx.engine, ctx.actor, ctx.target, kind)}


def new_binding(ctx, subject, *, feature, scope=None, grade='', duration=10, short=False, **extra):
    from .effect_durations import round_token
    expiry = 'START_OF_SOURCE_NEXT_TURN' if short else (
        'CONCENTRATION_END' if feature in {PRISON, EDICT} else round_token(ctx.engine, duration))
    gap = int(ctx.numbers['cl']) - int(known_level(ctx.engine, subject) or ctx.numbers['cl'])
    data = {'seal_feature': feature, 'scope': scope or {}, 'grade': grade,
        'source_cl': int(ctx.numbers['cl']), 'save_dc': int(ctx.numbers['save_dc']),
        'source_pb': int(ctx.numbers['pb']), 'first_turn': subject.turns_started - int(ctx.engine.state.current_actor_id == subject.entity_id),
        'owner_turn': ctx.actor.turns_started,
        'repeat_every': 0 if short or gap >= 6 or feature == PRISON and gap in (1, 2) else 2 if gap >= 3 else 1,
        'deadline': round_token(ctx.engine, duration), 'label': ctx.action.display_name,
        **extra}
    before = set(subject.conditions)
    ctx.engine._apply_condition(subject, SEAL, ctx.source, ctx.actor.entity_id, expires_on=expiry, data=data)
    return next((c for key, c in subject.conditions.items() if key not in before), None)


def anchor(ctx, subject, condition, name, ac, hp, *, position=None, physical_resistance=False):
    from .bound_objects import place
    if condition is None:
        return None
    obj = place(ctx, {'name': name, 'kind': 'seal_anchor', 'ac': ac, 'hp': hp, 'native_lifecycle': True,
        'resist': ['BLUDGEONING', 'PIERCING', 'SLASHING'] if physical_resistance else []},
        holder=subject, instance_ids=[condition.instance_id], position=position or subject.position)
    if obj:
        data = {**obj.component, 'qi_seal_anchor': 1, 'seal_feature': condition.data['seal_feature'],
                'source_cl': int(ctx.numbers['cl']), 'save_dc': int(ctx.numbers['save_dc']),
                'owner_id': ctx.actor.entity_id, 'holder_id': subject.entity_id}
        ctx.engine._update_object(obj.model_copy(update={'component': data}), ctx.source, ctx.actor.entity_id)
    return obj


def save_failed(ctx, target, *, willing=False, automatic=False):
    if willing or automatic:
        return True
    roll = ctx.engine._roll_save(target, 'CHA', int(ctx.numbers['save_dc']), ctx.source)
    return roll is not None and roll.total < int(ctx.numbers['save_dc'])


@effect('qi_seal_native', harmful=True)
def apply_seal(ctx, row):
    feature = row['feature']
    if feature == MINOR:
        return  # OBJECT candidates resolve through object_action below.
    target = ctx.target
    if target is None:
        return
    if False in run_strict('save_gate', ctx, target):
        return
    grade = row.get('grade', 'functional')
    if feature == MARK:
        willing = choose(ctx, target, 'consent', {'resist': 'Resist: make the saving throw',
            'accept': 'Willingly accept the Sealing Mark without a saving throw'},
            f'{ctx.actor.display_name} is placing {ctx.action.display_name} on {target.display_name}. '
            'Do you willingly accept this Seal, or resist it?', preferred=['resist']) == 'accept'
        sub = subdued(ctx, target, willing)
        if grade == 'meridian' and not (prepared(ctx.engine, ctx.actor, target) or
                fact_answers(ctx.engine, ctx.actor, target, 'identified_circulation')):
            raise ValueError('Meridian Seal needs your Chains, your Prison, or circulation identified in this scene.')
        if grade == 'core' and not sub:
            raise ValueError('Core Seal requires a Completely Subdued target or your Prison of Law.')
        gap = int(ctx.numbers['cl']) - int(known_level(ctx.engine, target) or ctx.numbers['cl'])
        automatic = grade == 'core' and gap >= 6 and sub and not fact_answers(
            ctx.engine, target, target, 'anti_sealing_authority')
        failed = save_failed(ctx, target, willing=willing, automatic=automatic)
        scope = scope_choice(ctx, grade)
        if grade == 'core' and gap <= -3:
            from ..typed_executor import resolve_opposed_check
            result = resolve_opposed_check(ctx, target, {'kind': 'cultivation'},
                {'kind': 'dc', 'dc': needle.save_dc(ctx.engine, target)})
            if not result.success:
                grade = 'meridian'
                scope = downgrade_scope_choice(ctx, ctx.actor)
        for _, old in seals(ctx.engine, target):
            if old.source_actor_id == ctx.actor.entity_id and old.data.get('seal_feature') == MARK:
                remove_instance(ctx.engine, target, old.instance_id, ctx.source)
        hours = failed and (grade == 'core' or grade == 'meridian' and sub)
        condition = new_binding(ctx, target, feature=feature, scope=scope, grade=grade,
            duration=600 if hours else 10, short=not failed, repeat_every=0 if hours or willing else (
                0 if gap >= 6 else 2 if gap >= 3 else 1))
        anchor(ctx, target, condition, 'Sealing Mark Anchor', 17, 4 * int(ctx.numbers['cl']), physical_resistance=True)
    elif feature == PRISON:
        scope = scope_choice(ctx, 'prison')
        failed = save_failed(ctx, target)
        condition = new_binding(ctx, target, feature=feature, scope=scope, short=not failed,
            imprisoned=int(failed), rule={'speed_zero': True, 'no_teleport': True} if failed else {'no_teleport': True})
        if failed:
            anchor(ctx, target, condition, 'Prison of Law', int(ctx.numbers['save_dc']), 8 * int(ctx.numbers['cl']))
        else:
            from ..typed_executor import run_effects
            run_effects(ctx, [{'type': 'speed', 'halved': True, 'duration': 'until_start_of_your_next_turn'}])
    elif feature == EDICT:
        edict(ctx)


def pillar_spaces(engine, target):
    from ..gate2_runtime_models import Position
    occupied = {cell for actor in engine.state.actors.values() if actor.active
                for cell in engine._actor_volume(actor)}
    occupied.update((obj.position.x, obj.position.y, obj.position.z)
                    for obj in engine.state.objects.values() if not obj.destroyed)
    found = []
    for dx in range(-6, 7):
        for dy in range(-6, 7):
            x, y = target.position.x + dx, target.position.y + dy
            if not engine.grid.in_bounds((x, y)):
                continue
            cell = Position(x=x, y=y, z=0)
            if engine.grid.distance_ft(target.position, cell) <= 30 and engine.grid.volume_legal(cell, occupied_cells=occupied):
                found.append(cell)
    return found


def triangle(a, b, c):
    return (b.x-a.x)*(c.y-a.y) != (b.y-a.y)*(c.x-a.x)


def edict_binds_all(ctx):
    """Authority and current preparation for a failed Edict save."""
    gap = int(ctx.numbers['cl']) - int(known_level(ctx.engine, ctx.target) or ctx.numbers['cl'])
    return gap >= 3 or subdued(ctx, ctx.target) or any(
        c.source_actor_id == ctx.actor.entity_id and c.data.get('grade') == 'core'
        for _, c in seals(ctx.engine, ctx.target))


def edict(ctx):
    target = ctx.target
    points = []
    names = ['Outer Heaven Pillar', 'Meridian Pillar', 'Core Pillar']
    for index, name in enumerate(names):
        choices = {needle.cell_id(p): p for p in pillar_spaces(ctx.engine, target)
                   if p not in points and (index < 2 or triangle(points[0], points[1], p))}
        if not choices:
            raise ValueError('Heaven-Sealing Edict needs three legal unoccupied Pillar spaces forming a triangle.')
        key = choose(ctx, ctx.actor, f'pillar_{index}', {key: f'{name} at ({p.x}, {p.y}, {p.z})' for key, p in choices.items()},
            f'Heaven-Sealing Edict against {target.display_name}: place {name} within 30 feet of the target.')
        points.append(choices[key])
    failed = save_failed(ctx, target)
    all_three = edict_binds_all(ctx)
    for index, (point, name) in enumerate(zip(points, names)):
        active = index == 0 or failed and (index == 1 or all_three)
        condition = new_binding(ctx, target, feature=EDICT, short=False, pillar=index,
            binding_active=int(active), initial_success=int(not failed), bind_on_failure=int(index < 2 or all_three),
            binding_short=int(not failed and index == 0), group=str(ctx.intent.intent_id),
            rule={'speed_zero': True, 'no_teleport': True} if active and index == 0 else {})
        anchor(ctx, target, condition, name, int(ctx.numbers['save_dc']), 6 * int(ctx.numbers['cl']), position=point)


def active_bindings(engine, target):
    for _, condition in seals(engine, target):
        data = condition.data
        if data.get('seal_feature') == EDICT and (not data.get('binding_active') or data.get('broken_binding') or
                data.get('suppressed_until_turn', -1) >= target.turns_started):
            continue
        yield condition


def breakable_bindings(engine, actor):
    """Marks and currently active Pillars only; never dormant, suppressed or broken links."""
    return [c for c in active_bindings(engine, actor) if c.data.get('seal_feature') in {MARK, EDICT}]


def profile(action_or_row):
    """Read the public activation-profile contract; explicit metadata only."""
    row = action_or_row if isinstance(action_or_row, dict) else (action_or_row.parameters.get('typed') or {})
    from .activation_profiles import function_profile
    return function_profile(row)


def matches(scope, source):
    kind, value = scope.get('kind'), scope.get('value')
    sid = source.get('source', '')
    if kind == 'sphere':
        return source.get('sphere') == value
    if kind in {'path_feature', 'subpath_feature', 'item_property'}:
        return sid == value or source.get('item_property') == value
    if kind in {'path', 'subpath', 'method', 'core', 'soul', 'foundation'}:
        return sid == value or sid.startswith(value + '.') or source.get(kind) == value
    if kind == 'all_spheres':
        return source.get('source_kind') == 'Sphere'
    if kind == 'all_items_armament':
        return source.get('source_kind') == 'item' or source.get('domain_armament') is True
    if kind == 'weapon_delivery':
        return source.get('weapon_delivery') is True
    if kind == 'audible':
        return source.get('audible') is True
    if kind in {'planar', 'possession', 'assets', 'armament', 'teleportation', 'flight', 'incorporeal', 'spirit_domain'}:
        keys = {'planar': ['teleportation', 'planar_movement'], 'possession': ['incorporeal', 'possession'],
                'assets': ['domain_manifestation', 'asset_manifestation'], 'armament': ['domain_armament']}.get(kind, [kind])
        return any(source.get(key) is True for key in keys)
    if kind in {'qi_channel', 'formation_commands', 'transformation', 'summons'}:
        return source.get(kind) == value or source.get(kind) is True and not value
    return False


def suppressed_activation(engine, actor, source):
    for condition in active_bindings(engine, actor):
        data = condition.data
        if matches(current_scope(actor, condition), source):
            return True
        if data.get('seal_feature') == EDICT:
            index = data['pillar']
            if index == 0 and any(source.get(key) is True for key in
                    ('teleportation', 'flight', 'incorporeal', 'possession', 'remote_origin')):
                return True
            if index == 1 and (source.get('source_kind') == 'Sphere' or source.get('weapon_delivery') is True or source.get('domain_armament') is True):
                return True
            if index == 2 and (source.get('source_kind') in {'Path', 'Subpath', 'Method', 'Foundation', 'Core', 'Soul', 'item', 'Recorded', 'Forged', 'Immortal'} or source.get('transformation')):
                return True
    return False


@hook('candidate_allowed')
def native_candidates(engine, actor, candidate, action):
    if action is None:
        return None
    release = action.parameters.get('qi_seal_release')
    if release:
        if release == 'break':
            return bool(breakable_bindings(engine, actor))
        return bool(nearby_anchors(engine, actor))
    if suppressed_activation(engine, actor, profile(action)):
        return False
    for pool, amount in action.costs:
        if resource_spending(engine, actor, pool, amount, action.source_definition_id) is False:
            return False
    feature = source_feature(action)
    target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
    if feature == EDICT and target:
        cells = pillar_spaces(engine, target)
        if len(cells) < 3 or not any(triangle(cells[0], cells[1], cell) for cell in cells[2:]):
            return False
    if feature == MARK and target:
        grade = action.parameters['typed']['effects'][0].get('grade', 'functional')
        if grade == 'meridian' and not prepared(engine, actor, target) and not fact_answers(engine, actor, target, 'identified_circulation'):
            return False
        if grade == 'core':
            # Consent is collected from the target during resolution, never inferred from alliance.
            from ..typed_executor import Context
            ctx = Context(engine, actor, action, None, action.parameters['typed'], [target], target)
            if not subdued(ctx, target) and (getattr(engine, 'typed_control_modes', {}) or {}).get(target.entity_id) not in {'MANUAL', 'SUGGESTED', 'MANUAL_AI_BRIDGE'}:
                return False
    # Prison blocks harmful direct targeting across its boundary, not areas.
    typed = action.parameters.get('typed') or {}
    if target and target is not actor and not typed.get('area'):
        from ..effect_harm import classify_effect
        harmful = any(classify_effect(e) is True for e in typed.get('effects') or [])
        attack = any(e.get('type') == 'attack' for e in typed.get('effects') or [])
        inside = any(c.data.get('imprisoned') for c in active_bindings(engine, actor))
        outside_target = any(c.data.get('imprisoned') for c in active_bindings(engine, target))
        if inside and harmful or outside_target and (harmful or attack):
            return False
    return None


@hook('row_allowed')
def sealed_reaction(engine, actor, row):
    return False if suppressed_activation(engine, actor, profile(row)) else None


@hook('teleport_gate')
def seal_teleport(ctx, start, destination):
    for condition in active_bindings(ctx.engine, ctx.actor):
        if condition.data.get('seal_feature') == PRISON or condition.data.get('pillar') == 0 or condition.data.get('scope', {}).get('kind') in {'teleportation', 'planar'}:
            return False
    return None


def passage_triangles(engine):
    """Live physical Pillars define a table-footprint boundary, independently of
    target-binding suppression. Group, Source CL, DC and anchor positions are
    journalled already; destroyed/displaced Pillars cannot leave a ghost triangle.
    """
    groups = {}
    for _, condition in seals(engine):
        if condition.data.get('seal_feature') != EDICT:
            continue
        for obj in engine.state.objects.values():
            if not obj.destroyed and condition.instance_id in (
                    (obj.component or {}).get('bound') or {}).get('conditions', []):
                group = groups.setdefault(condition.data['group'], {})
                group[condition.data['pillar']] = (obj.position, condition)
    for group, pillars in groups.items():
        if set(pillars) == {0, 1, 2}:
            points = [pillars[i][0] for i in range(3)]
            if triangle(*points):
                yield group, points, pillars[0][1]


def through_triangle(start, end, points):
    """Cross the triangle boundary, including an outside-to-outside traversal.
    Travel wholly on one side (including wholly inside) is not passage through it.
    Strict intersections exclude a ray merely touching a vertex/tangent edge.
    """
    def side(a, b, p):
        return (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x)
    def inside(p):
        signs = [side(points[i], points[(i+1) % 3], p) for i in range(3)]
        return all(n >= 0 for n in signs) or all(n <= 0 for n in signs)
    if inside(start) != inside(end):
        return True
    if inside(start):
        return False
    # Clip the segment to the triangle's strict interior. This also handles
    # crossing exactly through a vertex, without treating tangency as entry.
    from fractions import Fraction
    low, high = Fraction(0), Fraction(1)
    orientation = 1 if side(*points) > 0 else -1
    for i in range(3):
        a, b = points[i], points[(i+1) % 3]
        first, last = orientation * side(a, b, start), orientation * side(a, b, end)
        delta = last - first
        if not delta:
            if first <= 0:
                return False
        elif delta > 0:
            low = max(low, Fraction(-first, delta))
        else:
            high = min(high, Fraction(-first, delta))
    return low < high


def passage_allowed(engine, actor, start, destination, source, *, ctx=None):
    """Resolve only actual teleport/phase/summon/projection crossings.
    Menus never roll or inspect another creature's hidden abilities.
    """
    from ..typed_executor import Context, resolve_opposed_check
    from . import note
    action = engine.action_catalog.get(source)
    authored = profile(action) if action else {}
    cl = int(authored.get('source_cl') or known_level(engine, actor) or 1)
    for group, points, condition in passage_triangles(engine):
        if not through_triangle(start, destination, points):
            continue
        allowed = False
        if cl >= int(condition.data['source_cl']):
            if ctx is None:
                if action is None:
                    from ..gate2_runtime_models import ActionDefinition
                    action = ActionDefinition(source_definition_id=source, owner_id=actor.entity_id,
                        display_name='Pass through Heaven-Sealing Edict', economy='NONE',
                        resolution_kind='TYPED', target_kind='SELF')
                ctx = Context(engine, actor, action, getattr(engine, '_active_intent', None),
                              {'numbers': needle.numbers_of(engine, actor)}, [], None)
            # All packets of the same projected delivery share its one check;
            # a different crossing/activation must make its own.
            receipt = ('qi_edict_passage', group, actor.entity_id,
                       start.x, start.y, destination.x, destination.y)
            if receipt not in ctx.damage_cache:
                owner = engine.state.actors.get(condition.source_actor_id, actor)
                ctx.damage_cache[receipt] = resolve_opposed_check(ctx, owner, {'kind': 'cultivation'},
                    {'kind': 'dc', 'dc': int(condition.data['save_dc'])}).success
            allowed = ctx.damage_cache[receipt]
        if not allowed:
            note(engine, source, actor,
                 f"Heaven-Sealing Edict prevents {actor.display_name} from passing through the Seal Pillars.")
            return False
    return None


@hook('subject_teleport_attempt')
def passage_teleport(ctx, subject, start, destination):
    # Keep the effect's Source CL for a transported subject, not the subject's CL.
    return passage_allowed(ctx.engine, ctx.actor, start, destination, ctx.source, ctx=ctx)


@hook('summon_check')
def passage_summon(engine, owner, creature, spot, was_active, source):
    return passage_allowed(engine, owner, owner.position, spot, source)


@hook('movement_attempt')
@hook('forced_movement_attempt')
def passage_phase(engine, mover, previous, nxt, intent):
    if not any(c.condition_id.endswith(('.incorporeal', '.phasing')) for c in mover.conditions.values()):
        return None
    source = getattr(intent, 'source_definition_id', None) or 'system:qi_seal_phase'
    if passage_allowed(engine, mover, previous, nxt, source) is False:
        return {'stop': True, 'source_id': source, 'label': 'Heaven-Sealing Edict'}
    return None


def projected(action):
    p = profile(action)
    # Movement, summoning and self transformations have their own destination
    # gates; ordinary weapons/bodily actions are not projected cultivation.
    return not any(p.get(k) for k in ('teleportation', 'summons', 'transformation')) and bool(
        p.get('source_kind') or p.get('sphere') or p.get('remote_origin')) and not (
        action.parameters.get('typed') or {}).get('weapon')


@hook('technique_start')
def passage_origin(engine, actor, action):
    if not projected(action):
        return None
    from ..action_geometry import point
    origin = point(engine, actor)
    intent = getattr(engine, '_active_intent', None)
    destination = getattr(intent, 'destination', None)
    # A remote origin is projected from the caster; a placed area/zone is
    # projected from that origin to its chosen cell before any zone is created.
    for start, end in ((actor.position, origin), (origin, destination)):
        if end is not None and passage_allowed(engine, actor, start, end, action.source_definition_id) is False:
            return True
    return None


@hook('before_target_reactions')
def passage_recipients(ctx):
    if not projected(ctx.action):
        return None
    from ..action_geometry import point
    origin = point(ctx.engine, ctx.actor)
    # Areas retain recipients on the unblocked side; never cancel a whole area
    # just because one of its creatures is beyond the triangle.
    ctx.targets = [target for target in ctx.targets if passage_allowed(
        ctx.engine, ctx.actor, origin, target.position, ctx.source, ctx=ctx) is not False]


@hook('condition_attempt')
def seal_form(ctx, subject, row):
    if row.get('condition') not in {'incorporeal', 'possessing', 'flying'}:
        return None
    for condition in active_bindings(ctx.engine, subject):
        data = condition.data
        if data.get('seal_feature') == PRISON and row['condition'] != 'flying' or data.get('pillar') == 0:
            return False
        if data.get('scope', {}).get('kind') in {'incorporeal', 'possession'} and row['condition'] != 'flying':
            return False
    return None


@hook('resource_spend_allowed')
def resource_spending(engine, actor, pool, amount, source):
    from ..typed_executor import CP_POOLS
    if pool not in CP_POOLS or amount <= 0 or source == 'system:qi_seal_break':
        return None
    for condition in active_bindings(engine, actor):
        data = condition.data
        scope = current_scope(actor, condition)
        kind = scope.get('kind')
        if data.get('pillar') == 1 or kind == 'resource' and pool == scope['value']:
            return False
        if kind == 'expenditure_limit':
            from ..turn_uses import current_turn_key
            spent = int(data.get('spent_cp', 0)) if data.get('spend_turn') == current_turn_key(engine) else 0
            if spent + amount > int(data['source_pb']):
                return False
        if kind == 'path':
            action = engine.action_catalog.get(source)
            if action and matches(scope, profile(action)):
                return False
    return None


@hook('resource_gain_allowed')
def resource_recovery(engine, actor, pool, amount, source):
    from ..typed_executor import CP_POOLS
    if pool not in CP_POOLS or amount <= 0:
        return None
    for condition in active_bindings(engine, actor):
        data = condition.data
        scope = current_scope(actor, condition)
        if data.get('pillar') == 1 or scope.get('kind') in {'resource', 'resource_recovery'} and scope['value'] == pool:
            return False
    return None


def minor_eligible(engine, obj):
    from ..object_geometry import target_cells
    data = obj.component or {}
    return (obj.unattended and not obj.destroyed and data.get('size') in {'tiny', 'small', 'medium'}
        and len(target_cells(engine, obj)) == 1 and (obj.height_ft or 5) <= 5
        and not data.get('living_creature') and not data.get('secret_law')
        and not data.get('artifact') and not data.get('held_by'))


@hook('object_targets')
def minor_targets(engine, actor, action):
    if action.parameters.get('qi_minor_target'):
        return [obj.object_id for obj in engine.state.objects.values() if minor_eligible(engine, obj)]


def minor_end_label(engine, condition):
    """Player-facing name of one Minor Seal in the 'end a Seal' choice: the object's
    name, never its internal id."""
    sealed = engine.state.objects.get(condition.data.get('object_id', ''))
    name = (sealed.component or {}).get('name') if sealed else None
    return f'End Minor Seal on {name or "the sealed object"}'


@hook('object_action')
def place_minor(engine, actor, action, obj, candidate, intent):
    if not action.parameters.get('qi_minor_target'):
        return None
    if not minor_eligible(engine, obj):
        raise ValueError('Minor Seal requires an unattended object no larger than a 5-foot cube, without superior or Secret authority.')
    from ..typed_executor import Context
    ctx = Context(engine, actor, action, intent, action.parameters['typed'], [], None)
    kinds = {'lock': 'Lock Seal: ordinary opening, unlocking, unfolding, unsheathing and disassembly are blocked',
        'still': 'Still Seal: voluntary movement of this object is blocked',
        'dormancy': 'Dormancy Seal: suppress one named non-Secret activated property; passive properties continue',
        'closed_voice': 'Closed-Voice Seal: active properties cannot make audible sound; ordinary impacts can',
        'bound_hand': 'Bound-Hand Seal: unauthorized creatures cannot use one named handling mode'}
    if (obj.component or {}).get('moving'):
        kinds.pop('still')
    kind = choose(ctx, actor, 'minor_function', kinds,
        f'Minor Seal on {obj.component.get("name", "this object")}: choose its function. Costs 1 Qi and your Action; lasts 8 hours.')
    scope = {'kind': kind, 'value': ''}
    if kind == 'dormancy':
        props = {key: prop['name'] for key, prop in (obj.component.get('activated_properties') or {}).items()
                 if not prop.get('secret')}
        if not props:
            raise ValueError('Record the object’s non-Secret activated properties before choosing Dormancy Seal.')
        scope['value'] = choose(ctx, actor, 'minor_property', props,
            'Minor Seal: choose the one non-Secret activated property to suppress for 8 hours.')
    elif kind == 'bound_hand':
        mode = choose(ctx, actor, 'minor_handling', {key: key.title() for key in
            ('drawing', 'wielding', 'drinking', 'wearing', 'reading', 'activating')},
            'Bound-Hand Seal: choose the ordinary handling mode unauthorized creatures cannot use for 8 hours.')
        scope['value'] = mode
    owned = [(holder, c) for holder, c in seals(engine) if c.source_actor_id == actor.entity_id and c.data.get('seal_feature') == MINOR]
    if len(owned) >= actor.proficiency_bonus:
        choices = {c.instance_id: minor_end_label(engine, c) for _, c in owned}
        key = choose(ctx, actor, 'minor_limit', choices,
            f'Minor Seal: you can maintain {actor.proficiency_bonus}. Choose one previous Seal to end before placing this Seal.')
        holder, old = next((h, c) for h, c in owned if c.instance_id == key)
        remove_instance(engine, holder, old.instance_id, action.source_definition_id)
    condition = new_binding(ctx, actor, feature=MINOR, scope=scope, duration=4800,
        object_id=obj.object_id, authorized_ids=[actor.entity_id], repeat_every=0)
    anchor(ctx, actor, condition, 'Minor Seal Anchor', 15, 5 * int(ctx.numbers['cl']), position=obj.position)
    return True


@hook('object_operation_gate')
def minor_operation(engine, actor, obj, operation, source, intent):
    for _, condition in seals(engine):
        data = condition.data
        if data.get('seal_feature') != MINOR or data.get('object_id') != obj.object_id:
            continue
        scope = data['scope']; kind = scope['kind']
        if kind == 'lock' and operation in {'open', 'unlock', 'unfold', 'unsheathe', 'disassemble'}:
            return False
        if kind == 'still' and operation == 'move':
            return False
        if kind == 'bound_hand' and operation == scope['value'] and actor.entity_id not in data['authorized_ids']:
            return False
        if kind == 'dormancy' and operation == 'activate:' + scope['value']:
            return False
        if kind == 'closed_voice' and operation == 'active_sound':
            return False
    return None


def nearby_anchors(engine, actor):
    return [obj for obj in engine.state.objects.values() if not obj.destroyed and (obj.component or {}).get('qi_seal_anchor')
            and engine.grid.distance_ft(actor.position, obj.position) <= 5]


@effect('qi_seal_release')
def release_seal(ctx, row):
    engine, actor = ctx.engine, ctx.actor
    from dataclasses import replace
    ctx = replace(ctx, typed={**ctx.typed, 'numbers': needle.numbers_of(engine, actor)})
    if row['kind'] == 'break':
        held = breakable_bindings(engine, actor)
        if not held:
            raise ValueError('Break the Seal requires an active binding.')
        options = {c.instance_id: c.data.get('label', 'Seal') +
                   (' — ' + ['Outer Heaven', 'Meridian', 'Core'][c.data['pillar']] if 'pillar' in c.data else '') for c in held}
        key = choose(ctx, actor, 'break_binding', options,
            f'Break the Seal: choose a binding on {actor.display_name}. This uses your Action and one payable price.')
        condition = next((c for c in breakable_bindings(engine, actor) if c.instance_id == key), None)
        if condition is None:
            raise ValueError('Break the Seal requires an active binding.')
        from .cp_pools import all_of
        prices = {'force': 'Take 4d10 Force damage that the sealed structure cannot reduce', 'exhaustion': 'Accept one level of Exhaustion'}
        for pool in all_of(actor):
            if actor.resources.get(pool, 0) >= condition.data['source_pb']:
                prices[pool] = f'Spend {condition.data["source_pb"]} Cultivation Points from {pool.split(".")[-1].title()}'
        price = choose(ctx, actor, 'break_price', prices,
            f'Break the Seal on {actor.display_name}: choose your price, then repeat the Charisma save with Advantage.')
        if price == 'force':
            from ..typed_executor import _roll
            from ..gate2_runtime_models import DiceSpec
            damage = _roll(ctx, DiceSpec(count=4, sides=10, modifier=0), 'DAMAGE')
            engine._commit_damage(actor, damage, 'FORCE', ctx.source, actor.entity_id, None, reaction_depth=0)
        elif price == 'exhaustion':
            from .forged_exhaustion import add
            add(engine, actor, 1, ctx.source)
        else:
            engine._spend_resource(actor, price, condition.data['source_pb'], ctx.source)
        roll = engine._roll_save(actor, 'CHA', condition.data['save_dc'], ctx.source, extra_mode='ADVANTAGE')
        if not roll or roll.total < condition.data['save_dc']:
            if condition.data.get('pillar') is not None:
                engine._update_condition_data(actor, condition, {**condition.data, 'break_successes': 0}, ctx.source)
            return
        successes = int(condition.data.get('break_successes', 0)) + 1
        if condition.data['seal_feature'] == EDICT:
            engine._update_condition_data(actor, condition, {**condition.data, 'break_successes': successes,
                'suppressed_until_turn': actor.turns_started + 1, 'broken_binding': int(successes >= 2), 'rule': {}}, ctx.source)
        elif condition.data.get('grade') == 'core' and successes == 1:
            # The placer picks the replacement Meridian scope at this moment; the
            # count stays at 1 so the next success ends the Mark outright.
            source = engine.state.actors.get(condition.source_actor_id)
            if source is None:
                # The placer has left the fight, so nobody can pick the Meridian scope:
                # the Core scope stays and the next successful Break still ends the Mark.
                engine._update_condition_data(actor, condition, {**condition.data, 'break_successes': 1}, ctx.source)
            else:
                scope = downgrade_scope_choice(ctx, source)
                engine._update_condition_data(actor, condition, {**condition.data, 'break_successes': 1,
                    'downgrade_scope': scope, 'downgraded_until_turn': actor.turns_started + 1}, ctx.source)
        else:
            remove_instance(engine, actor, condition.instance_id, ctx.source)
    else:
        objects = {obj.object_id: obj for obj in nearby_anchors(engine, actor)}
        key = choose(ctx, actor, 'aid_anchor', {key: obj.component.get('name', 'Seal Anchor') for key, obj in objects.items()},
            f'{actor.display_name}: choose an adjacent Seal Anchor to remove with your Action.')
        obj = objects[key]; data = obj.component
        record = data['bound']; holder = engine.state.actors.get(record['holder'])
        condition = next((holder.conditions[key] for key in record['conditions'] if key in holder.conditions), None) if holder else None
        if condition is None:
            return
        methods = {'cultivation': 'Cultivation Check with compatible seal-breaking authority'}
        if data['seal_feature'] == MINOR:
            methods['tools'] = 'Dexterity check with suitable script-removal tools'
            if condition.data['scope']['kind'] in {'lock', 'still', 'bound_hand'}:
                methods['strength'] = 'Strength check to tear away the Seal'
        method = choose(ctx, actor, 'aid_method', methods,
            f'{obj.component["name"]}: choose a legal removal check against DC {data["save_dc"]}.')
        from ..typed_executor import resolve_opposed_check
        owner = engine.state.actors[data['owner_id']]
        check = {'kind': 'cultivation'} if method == 'cultivation' else {'kind': 'check', 'ability': 'DEX' if method == 'tools' else 'STR'}
        result = resolve_opposed_check(ctx, owner, check, {'kind': 'dc', 'dc': data['save_dc']})
        if not result.success:
            return
        if data['seal_feature'] in {MINOR, MARK}:
            remove_instance(engine, holder, condition.instance_id, ctx.source)
        else:
            from .objects import deal
            deal(engine, actor, obj, [(5 * actor.proficiency_bonus, 'FORCE')], ctx.source, ignore_resistance=True)
            if data['seal_feature'] == PRISON and not obj.destroyed:
                save = engine._roll_save(holder, 'CHA', data['save_dc'], ctx.source)
                if save and save.total >= data['save_dc']:
                    remove_instance(engine, holder, condition.instance_id, ctx.source)


@hook('object_damage_defenses')
def seal_defenses(engine, actor, obj, packets, source):
    data = obj.component or {}
    if not data.get('qi_seal_anchor'):
        return None
    if data.get('seal_feature') == MARK:
        return None  # unconditional physical resistance is already on this Anchor.
    if data.get('seal_feature') == PRISON:
        if actor is not None and actor.entity_id != data['holder_id']:
            return [{'kind': 'resistance', 'damage_types': sorted({kind for _, kind in packets})}]
    else:
        action = engine.action_catalog.get(source)
        p = profile(action) if action else {}
        if not p.get('source_kind') and not p.get('weapon_delivery'):
            return [{'kind': 'resistance', 'damage_types': ['BLUDGEONING', 'PIERCING', 'SLASHING']}]
    return None


@hook('turn_end')
def seal_repeat_saves(engine, actor):
    resolved_groups = set()
    for _, condition in list(seals(engine, actor)):
        data = condition.data
        if data.get('seal_feature') == MINOR:
            continue
        cadence = data.get('repeat_every', 0)
        if not cadence or (actor.turns_started - data['first_turn']) % cadence:
            continue
        if data['seal_feature'] == EDICT:
            if data['group'] in resolved_groups:
                continue
            resolved_groups.add(data['group'])
        roll = engine._roll_save(actor, 'CHA', data['save_dc'], condition.source_definition_id)
        if not roll or roll.total < data['save_dc']:
            if roll and data['seal_feature'] == EDICT:
                # Re-evaluate preparation when the later failure actually happens.
                # Suppressed/destroyed links are not recreated by this transition.
                from ..typed_executor import Context
                source = engine.state.actors.get(condition.source_actor_id)
                action = engine.action_catalog[condition.source_definition_id]
                full = edict_binds_all(Context(engine, source, action, getattr(engine, '_active_intent', None),
                    {**action.parameters['typed'], 'numbers': {'cl': data['source_cl']}}, [actor], actor)) if source else False
                for _, other in list(seals(engine, actor)):
                    if other.data.get('group') == data['group']:
                        updated = {**other.data, 'initial_success': 0, 'binding_short': 0,
                                   'binding_active': int(other.data.get('binding_active') or
                                       other.data['bind_on_failure'] or full)}
                        updated['rule'] = {'speed_zero': True, 'no_teleport': True} if (
                            updated['binding_active'] and updated['pillar'] == 0
                            and not updated.get('broken_binding')
                            and updated.get('suppressed_until_turn', -1) < actor.turns_started) else {}
                        engine._update_condition_data(actor, other, updated, other.source_definition_id)
            continue
        if data['seal_feature'] == EDICT:
            # One save per Edict activation, one player-owned Pillar choice.
            group = data['group']
            if any(other.data.get('repeat_resolved_turn') == actor.turns_started
                   for _, other in seals(engine, actor) if other.data.get('group') == group):
                continue
            active = [other for other in active_bindings(engine, actor) if other.data.get('group') == group]
            if not active:
                continue
            from ..typed_executor import Context
            action = engine.action_catalog[condition.source_definition_id]
            ctx = Context(engine, actor, action, getattr(engine, '_active_intent', None),
                          action.parameters['typed'], [actor], actor)
            key = choose(ctx, actor, 'edict_repeat', {c.instance_id: ['Outer Heaven Pillar', 'Meridian Pillar', 'Core Pillar'][c.data['pillar']] for c in active},
                f'{actor.display_name} resisted Heaven-Sealing Edict. Choose one active Pillar to suppress until the end of your next turn.')
            picked = next(c for c in active if c.instance_id == key)
            engine._update_condition_data(actor, picked, {**picked.data, 'suppressed_until_turn': actor.turns_started + 1,
                'repeat_resolved_turn': actor.turns_started, 'rule': {}}, picked.source_definition_id)
        else:
            remove_instance(engine, actor, condition.instance_id, condition.source_definition_id)


@hook('event')
def seal_lifecycle(engine, event_type, kwargs):
    if event_type == 'RESOURCE_SPENT':
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        if actor:
            from ..typed_executor import CP_POOLS
            payload = kwargs.get('payload') or {}
            if payload.get('resource_id') in CP_POOLS:
                from ..turn_uses import current_turn_key
                turn = current_turn_key(engine)
                for c in list(active_bindings(engine, actor)):
                    if current_scope(actor, c).get('kind') == 'expenditure_limit':
                        spent = int(c.data.get('spent_cp', 0)) if c.data.get('spend_turn') == turn else 0
                        engine._update_condition_data(actor, c, {**c.data, 'spend_turn': turn,
                            'spent_cp': spent + int(payload['amount'])}, c.source_definition_id)
    if event_type not in {'OBJECT_UPDATED', 'CONDITION_REMOVED', 'MOVEMENT_COMMITTED', 'TURN_STARTED'} or engine.__dict__.get('_qi_seal_sweep'):
        return
    engine.__dict__['_qi_seal_sweep'] = True
    try:
        for holder, condition in list(seals(engine)):
            data = condition.data
            for obj in list(engine.state.objects.values()):
                record = (obj.component or {}).get('bound') or {}
                if obj.destroyed or condition.instance_id not in record.get('conditions', []):
                    continue
                target = engine.state.objects.get(data.get('object_id', '')) if data['seal_feature'] == MINOR else holder
                if data['seal_feature'] in {MINOR, MARK, PRISON} and target is not None and obj.position != target.position:
                    engine._update_object(obj.model_copy(update={'position': target.position}), condition.source_definition_id,
                                          condition.source_actor_id)
            if data['seal_feature'] == EDICT:
                for obj in engine.state.objects.values():
                    record = (obj.component or {}).get('bound') or {}
                    if condition.instance_id in record.get('conditions', []) and not obj.destroyed and engine.grid.distance_ft(obj.position, holder.position) > 60:
                        remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)
            if data['seal_feature'] == MINOR:
                target = engine.state.objects.get(data['object_id'])
                if target is None or target.destroyed:
                    remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)
    finally:
        engine.__dict__.pop('_qi_seal_sweep', None)


@hook('turn_start')
def finite_seals(engine, actor):
    from .effect_durations import due
    for holder, condition in list(seals(engine)):
        data = condition.data
        if due(engine, data['deadline']):
            remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)
        elif data.get('binding_short') and condition.source_actor_id == actor.entity_id and actor.turns_started > data['owner_turn']:
            engine._update_condition_data(holder, condition, {**data, 'binding_active': 0, 'binding_short': 0, 'rule': {}}, condition.source_definition_id)
    # Separate pass: the window clear must run even when a binding timer fired above.
    for holder, condition in list(seals(engine)):
        data = condition.data
        if data.get('downgrade_scope') and holder.turns_started >= int(data.get('downgraded_until_turn', 0)):
            # The downgrade window closed at the target's turn start; the stored
            # Core scope applies again with its success count untouched.
            data = {key: value for key, value in data.items() if key != 'downgrade_scope'}
            data.pop('downgraded_until_turn', None)
            engine._update_condition_data(holder, condition, data, condition.source_definition_id)


@hook('turn_end', priority=-100)
def resume_pillars(engine, actor):
    for _, condition in list(seals(engine, actor)):
        data = dict(condition.data)
        deadline = data.get('suppressed_until_turn')
        if deadline is not None and actor.turns_started >= deadline:
            data.pop('suppressed_until_turn', None)
            data['rule'] = {'speed_zero': True, 'no_teleport': True} if data.get('pillar') == 0 and not data.get('broken_binding') else {}
            engine._update_condition_data(actor, condition, data, condition.source_definition_id)


def holds(actor):
    return [c for c in actor.conditions.values() if c.data.get('qi5_chain')]


@hook('condition_state')
def chain_state(ctx, subject, row):
    if not row.get('qi5_chain'):
        return None
    cl=int(ctx.numbers['cl']); level=known_level(ctx.engine,subject)
    gap=cl-level if level is not None else 0
    every=0 if gap>=6 else 2 if gap>=3 else 1
    return {'data':{'qi5_chain':1,'source_cl':cl,'save_dc':int(ctx.numbers['save_dc']),
        'repeat_every':every,'first_turn':subject.turns_started-int(ctx.engine.state.current_actor_id==subject.entity_id),
        'prepared_for_sealing':True,'rule':{'no_teleport':True},'label':'Chains of Qi: Restrained; teleportation, phasing and possession blocked'}}


@hook('turn_end')
def repeated_escape(engine,actor):
    for c in holds(actor):
        cadence=int(c.data['repeat_every'])
        if not cadence or (actor.turns_started-int(c.data['first_turn']))%cadence:
            continue
        rolled=engine._roll_save(actor,'DEX',int(c.data['save_dc']),c.source_definition_id)
        if rolled and rolled.total>=int(c.data['save_dc']):
            remove_instance(engine,actor,c.instance_id,c.source_definition_id)


@hook('compile_actions')
def break_action(info):
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    # Anyone may try to escape a hold placed later in this fight.
    return [ActionDefinition(source_definition_id='action:typed.'+info['short']+'.qi5_break_chains',
        owner_id=info['actor_id'],display_name='Break Chains of Qi',economy=EconomyKind.ACTION,
        resolution_kind='TYPED',target_kind='SELF',parameters={'qi5_escape':1,'expected_damage':0,
        'typed':{'source':'system:qi5.break_chains','numbers':info['numbers'],
        'effects':[{'type':'qi5_escape_chains'}],'riders':[]}})]


@hook('candidate_allowed')
def chain_candidates(engine,actor,candidate,action):
    if action is not None and (action.parameters or {}).get('qi5_escape'):
        return bool(holds(actor))
    if not holds(actor):
        return None
    # Gate4 marks these destination candidates only for self-teleports. Keep
    # the held creature from choosing one; ally teleportation and conditional
    # teleport branches are governed by teleport_gate when the subject moves.
    if candidate.metadata.get('teleport'):
        return False
    return None


@hook('teleport_gate')
def chains_teleport(ctx,start,destination):
    # All explicit teleport routes still pass the shared no_teleport rule.
    return False if holds(ctx.actor) else None


@effect('qi5_escape_chains')
def escape(ctx,row):
    from .needle import ask,checkpoint_id
    held=holds(ctx.actor)
    if not held:
        return
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'QI5_ESCAPE'),ctx.actor,
        'choice:needle.qi5_escape',[c.instance_id for c in held],preferred=[held[0].instance_id],
        labels={c.instance_id:'Break the chains from '+ctx.engine.state.actors[c.source_actor_id].display_name for c in held},
        name='Break Chains of Qi',prompt='Choose one set of chains to break. Use a Strength check or Cultivation Check against its creator’s save DC; this costs your Action.')
    c=next((c for c in held if chosen and c.instance_id==chosen[0]),held[0])
    picks=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'QI5_ESCAPE_KIND'),ctx.actor,
        'choice:needle.qi5_escape_kind',['strength','cultivation'],preferred=['cultivation'],
        labels={'strength':'Strength check','cultivation':'Cultivation Check'},name='Break Chains of Qi',
        prompt=f'Choose your check against DC {c.data["save_dc"]}. Success ends these Chains of Qi.')
    from ..typed_executor import resolve_opposed_check
    owner=ctx.engine.state.actors[c.source_actor_id]
    check={'kind':'check','ability':'STR','label':'Strength check'} if picks and picks[0]=='strength' else {'kind':'cultivation'}
    result=resolve_opposed_check(ctx,owner,check,{'kind':'dc','dc':int(c.data['save_dc'])})
    if result.success:
        remove_instance(ctx.engine,ctx.actor,c.instance_id,ctx.source)


@hook('condition_attempt')
def chain_phase(ctx,subject,row):
    if holds(subject) and row.get('condition') in {'incorporeal','possessing'}:
        return False
    return None


@effect('qi5_chain_lock',harmful=True)
def short_lock(ctx,row):
    from ..typed_executor import effect_expiry
    if ctx.target:
        ctx.engine._apply_condition(ctx.target,'condition:typed.qi5_chain_lock',ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,ctx.target,condition=True),
            data={'rule':{'no_teleport':True},'label':'Chains of Qi: voluntary teleportation blocked'})
