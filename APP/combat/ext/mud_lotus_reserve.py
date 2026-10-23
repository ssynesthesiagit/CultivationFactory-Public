"""Mud Lotus Reserve: source-qualified alignment and hostile saving throws.

This replaces this row's old generic vessel reader, not the other Foundations'
readers. The native compiler seals legal technique provenance; a private,
table-owner world fact classifies that exact creature/action in this fight.
Neither affinity nor a source's name/damage supplies an expression. Unknown
facts are inert. Existing explicit pending-save categories remain authoritative.

alignment_receipt is the public permission query for Mud Lotus consumers.
technique_used journals the permission on an actual use, without creating Dew,
changing costs, or implementing the separately printed generation record.
"""
from . import hook, note

SOURCE = 'foundation.mud_lotus_dantian_v0_2A.mud_lotus_reserve'
BLOCK = 'mud_lotus_reserve'
PRESSURE = 'mud_lotus_pressure'
EXPRESSION = 'mud_lotus_expression'
SPHERES = frozenset('tianxia.sphere.' + name for name in (
    'water', 'life', 'verdant_growth', 'flowers', 'alchemy', 'protection',
    'harvesting_gathering', 'earth', 'disease', 'poison', 'music'))
EXPRESSIONS = frozenset((
    'humble_recovery', 'living_water_cleansing', 'lotus_root_medicine',
    'poison_disease_treatment', 'polluted_living_environment', 'shared_medicine',
    'recovery_after_hardship', 'growth_through_mud'))
CONTROLS = frozenset(('dry_fire', 'sterile_purity', 'direct_violence', 'social_pride', 'unrelated'))


@hook('compile_block')
def compile_reserve(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'abilities': list(spec['abilities']), 'against': list(spec['against'])}]
    return None


def reserve(engine, actor):
    """Only an installed, source-admitted Foundation owns this passive."""
    return next((row for row in engine.typed_passive_rows.get(actor.entity_id, ())
                 if row.get('block') == BLOCK and row.get('feature_id') == SOURCE), None)


@hook('compile_action')
def seal_technique(action, info):
    if SOURCE not in info['owned_ids']:
        return action
    typed = action.parameters.get('typed') or {}
    source = typed.get('source')
    # The Forge publishes its acquired Primary Sphere Effect as forged_from;
    # retain the derived action's identity rather than excluding legal designs.
    primary = typed.get('forged_from') or source
    record = info['mechanics'].get(primary) or {}
    if primary not in info['owned_ids'] or record.get('sphere_id') not in SPHERES:
        return action
    provenance = record.get('source') or {}
    if not provenance.get('text_sha256'):
        return action
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': {
        **typed, 'mud_lotus_source': {'source_id': source, 'sphere_id': record['sphere_id'],
                                     'text_sha256': provenance['text_sha256']}}}})


def source_action(session, subject, kind, value):
    """Validate identities against native sealed actors/actions, not supplied IDs."""
    from ..journey import require
    engine = session.engine
    owner = engine.state.actors.get(subject)
    require(owner is not None and reserve(engine, owner) is not None,
            'Mud Lotus Reserve must be installed on the affected creature.')
    actor = engine.state.actors.get(value.get('source_actor_id'))
    action = engine.action_catalog.get(value.get('source_definition_id'))
    require(actor is not None and action is not None and action.owner_id == actor.entity_id
            and action.source_definition_id in actor.action_ids,
            'Select an existing action belonging to its actual source creature.')
    if kind == EXPRESSION:
        provenance = (action.parameters.get('typed') or {}).get('mud_lotus_source') or {}
        require(actor is owner and provenance.get('sphere_id') in SPHERES,
                'Only your already-legal techniques in the listed spheres can qualify.')
    else:
        def saves(value):
            if isinstance(value, dict):
                return value.get('type') == 'save' or any(saves(v) for v in value.values())
            return isinstance(value, list) and any(saves(v) for v in value)
        require(action.save is not None or saves((action.parameters.get('typed') or {}).get('effects')),
                'Select an actual saving-throw source, not a damage or action name.')
    return action


@hook('combat_fact_admission_allowed')
def combat_admission(session, source, subject, kind):
    if source == SOURCE and kind in (PRESSURE, EXPRESSION):
        return True
    return None


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source != SOURCE or kind not in (PRESSURE, EXPRESSION):
        return None
    return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
            # Use the admission contract's default subject access: visibility
            # to extra readers must not gate an always-active passive.
            'combat_condition_data_paths': [],
            'description': ('Classify one exact source for Mud Lotus Reserve. This supplies no sphere access, '
                            'immunity, damage reduction, resource, or consent.')}


@hook('fact_admission_validate')
def validate(session, source, subject, kind, value):
    if source != SOURCE or kind not in (PRESSURE, EXPRESSION):
        return
    from ..journey import require
    require(hasattr(session, 'engine'), 'Classify this expression in its actual fight.')
    fields = {'source_actor_id', 'source_definition_id'}
    fields |= {'expression', 'preserves_rot'} if kind == EXPRESSION else {'category'}
    require(set(value) == fields and all(type(value[k]) is str and value[k] for k in fields - {'preserves_rot'}),
            'Supply the exact source creature, action, and printed classification.')
    source_action(session, subject, kind, value)
    if kind == EXPRESSION:
        require(value['expression'] in EXPRESSIONS | CONTROLS
                and type(value['preserves_rot']) is int and value['preserves_rot'] in (0, 1),
                'Name a printed recovery expression and whether it preserves rot.')
    else:
        row = reserve(session.engine, session.engine.state.actors[subject])
        require(value['category'] in set(row['against']) | CONTROLS,
                'Name a printed pressure category or an outside-scope control.')


def scope(engine, subject, kind, value):
    from ..fact_consent_admission import digest
    return digest([engine.state.match_id, kind, subject,
                   value['source_actor_id'], value['source_definition_id']])


@hook('fact_admitted')
def bind_source(session, record):
    if record['source'] != SOURCE or record['kind'] not in (PRESSURE, EXPRESSION):
        return
    from ..journey import require
    require(record['scope'] == scope(session.engine, record['subject'], record['kind'], record['value']),
            'Bind the classification to this fight, affected creature, source creature, and action.')


def classification(engine, actor, kind, source_actor_id, action_id):
    from ..fact_consent_admission import NativeFactSession, read
    if reserve(engine, actor) is None:
        return None
    identity = {'source_actor_id': source_actor_id, 'source_definition_id': action_id}
    record = read(NativeFactSession(engine), SOURCE, actor.entity_id, kind,
                  scope(engine, actor.entity_id, kind, identity), actor.entity_id)
    return record


def alignment_receipt(engine, actor, action_id):
    """Permission only; callers must separately check their own printed trigger.

    An explicit GM classification may qualify any legal technique in the eleven
    printed spheres, without limiting the legal option list to a reviewed roster.
    A newer outside-scope/rot-preserving declaration revokes the permission.
    """
    if reserve(engine, actor) is None:
        return None
    action = engine.action_catalog.get(action_id)
    if action is None or action.owner_id != actor.entity_id:
        return None
    provenance = (action.parameters.get('typed') or {}).get('mud_lotus_source') or {}
    if provenance.get('sphere_id') not in SPHERES:
        return None
    record = classification(engine, actor, EXPRESSION, actor.entity_id, action_id)
    if record is None or record['value']['preserves_rot'] or record['value']['expression'] not in EXPRESSIONS:
        return None
    return {**provenance, 'expression': record['value']['expression'],
            'grant_source': SOURCE, 'receipt_id': record['receipt_id']}


@hook('technique_used')
def record_alignment(ctx):
    receipt = alignment_receipt(ctx.engine, ctx.actor, ctx.action.source_definition_id)
    if receipt is not None:
        note(ctx.engine, SOURCE, ctx.actor,
             f'Mud Lotus Reserve: {ctx.action.display_name} qualifies as Foundation-aligned for this use. '
             'This permission costs nothing and generates no resource.',
             receipt_kind='mud_lotus_alignment', **receipt)


@hook('save_roll_tags')
def native_save_tags(ctx, subject, ability, named):
    if reserve(ctx.engine, subject) is not None:
        return sorted(named)
    return None


@hook('save_mode')
def save_advantage(engine, subject, ability, dc, source_id, context):
    row = reserve(engine, subject)
    source = engine.state.actors.get(context.get('source_actor_id'))
    # Preserve the original Foundation hostility contract. This record does not
    # redefine neutral diplomacy or change any sibling's hostility semantics.
    if (row is None or ability.upper()[:3] not in row['abilities'] or source is None
            or source.team_id == subject.team_id):
        return None
    tags = {str(t).lower().removeprefix('category:').removeprefix('damage:')
            for t in context.get('named') or context.get('conditions') or ()}
    record = classification(engine, subject, PRESSURE, source.entity_id, source_id)
    if record is not None:
        tags.add(record['value']['category'])
    return 'ADVANTAGE' if tags.intersection(row['against']) else None
