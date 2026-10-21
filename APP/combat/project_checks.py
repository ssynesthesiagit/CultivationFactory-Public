"""Public project roll contract used by Technique Forging and Foundation Challenges.

The GM admits external scene facts through the protected record_fact endpoint.
An owned actor then chooses a project from their audience, rolls native recorded
statistics, and commits a result once. A success is a roll receipt, never an
automatic acquisition or a grant of a Sphere/technique. Consumers may adjust the
DC through project_check_dc; absent providers leave the printed DC unchanged.
"""
from . import ext
from .table_facts import records

SOURCE = 'system:combat.project_check'


def prepare(table, document):
    """Derive a forging plan's mechanical facts through the existing constructor.

    External Foundation Challenge DCs and subjective limitations stay explicit
    GM inputs. Forging Complexity/Spheres, access, components and Realm limits
    come from TabletopService.forge, not values supplied in the fact request.
    This preview does not save or grant the technique.
    """
    project = document.get('project_check') if isinstance(document, dict) else None
    if not project or project.get('kind') != 'technique_forging':
        return document
    from copy import deepcopy
    from .canonical import canonical_sha256
    from .tabletop_service import FACTORY_PREFIX
    actor_id = str(project.get('actor_id') or '')
    if not actor_id.startswith(FACTORY_PREFIX) or not isinstance(project.get('design'), dict):
        raise ValueError('Choose a character and complete the technique’s Forge design.')
    technique = table.forge(actor_id.removeprefix(FACTORY_PREFIX), project['design'], save=False)['technique']
    result = deepcopy(document)
    result['project_check'] = {**project, 'complexity': int(technique['complexity']['final']),
        'sphere_ids': list(technique['sphere_ids_used']), 'construction_sha256': canonical_sha256(technique)}
    return result


def owns_source(engine, actor_id, source_id, *, fact=None):
    """Exact project-roll identity, shared by fact admission and scope queries.

    With a fact, also require its actual project owner. Unrelated actions and
    another character cannot inherit a project's source interpretation.
    """
    if fact is not None and (fact.project_check is None or fact.project_check.actor_id != actor_id):
        return False
    action = engine.action_catalog.get(source_id)
    return bool(action is not None and action.owner_id == actor_id
                and (action.parameters.get('typed') or {}).get('source') == SOURCE)


def validate_project(engine, fact):
    project = fact.project_check
    if project.actor_id not in engine.state.actors:
        raise ValueError('The project owner must be present.')
    if project.pressure_source_actor_id is not None and (
            project.pressure_source_actor_id not in engine.state.actors
            or project.pressure_source_actor_id == project.actor_id):
        raise ValueError('Name the present creature that actually imposed this external pressure, separately from the creature making the check.')
    action = next((action for action in engine.action_catalog.values() if action.owner_id == project.actor_id
                   and (action.parameters.get('typed') or {}).get('source') == SOURCE), None)
    key = action.parameters.get('project_cultivation_ability') if action is not None else None
    if project.skill == 'Cultivation' and key is not None and project.ability != key:
        raise ValueError('A Cultivation Check uses the character’s actual Key Ability.')
    from .factory_compiler import TYPED_AUTHORITY
    import json
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())['mechanics']
    known_spheres = {row.get('sphere_id') for row in mechanics.values() if row.get('sphere_id')}
    if not set(project.sphere_ids) <= known_spheres:
        raise ValueError('Name canonical Spheres from the source catalogue.')


def available(engine, actor):
    consumed = {e.payload.get('project_record_id') for e in engine.events
                if e.event_type == 'CHECK_ROLLED' and e.source_definition_id.startswith(SOURCE + '.')}
    return {key: fact for key, fact in records(engine, actor).items()
            if fact.project_check is not None and fact.project_check.actor_id == actor.entity_id and key not in consumed}


def resolve(ctx, fact):
    from .ability_checks import ordinary_check_bonus
    from .ext.needle import numbers_of
    project = fact.project_check
    numbers = {**numbers_of(ctx.engine, ctx.actor), **(ctx.typed.get('numbers') or {})}
    modifier = (int(numbers['pb']) + int(numbers['key_mod']) if project.skill == 'Cultivation'
                else ordinary_check_bonus(ctx.engine, ctx.actor, project.ability, project.skill, numbers=numbers))
    if modifier is None:
        raise ValueError('No ability or skill bonus is recorded for that check. Check the character sheet.')
    modifier += sum(ext.run_strict('check_bonus', ctx, ctx.actor))
    base_dc = (10 + project.complexity + len(project.sphere_ids)
               if project.kind == 'technique_forging' else project.challenge_dc)
    delta = sum(ext.run_strict('project_check_dc', ctx.engine, ctx.actor, fact))
    dc = base_dc + delta
    scope = {'kind': 'check', 'actor_id': ctx.actor.entity_id, 'target_id': ctx.actor.entity_id,
             'source_id': ctx.source, 'source_actor_id': ctx.actor.entity_id,
             'ability': project.ability, 'skill': project.skill, 'dc': dc,
             'check_kind': project.kind, 'hazards': [project.kind, 'project:' + fact.record_id], 'named': []}
    pressure = ({'pressure_source_actor_id': project.pressure_source_actor_id,
                 'pressure_fact_record_id': fact.record_id} if project.pressure_source_actor_id else {})
    scope.update(pressure)
    with ctx.engine.d20_scope(scope):
        roll = ctx.engine.roll_check(modifier=modifier, actor_id=ctx.actor.entity_id,
            reason=f'CHECK:{ctx.source}', ability=project.ability, skill=project.skill,
            hazards=(project.kind,))
        roll = ext.floored(ctx.engine, ctx.actor, roll, dc, ability=project.ability, skill=project.skill)
    ctx.engine._record_roll(roll)
    ctx.engine._append_event('CHECK_ROLLED', ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
        payload={'project_record_id': fact.record_id, 'source_reference': fact.source_reference,
                 'project_kind': project.kind, 'base_dc': base_dc, 'dc_adjustment': delta, 'dc': dc,
                 'check': fact.subject_name, 'skill': project.skill,
                 'actor': roll.model_dump(mode='json'), 'success': roll.total >= dc,
                 **({'pressure_fact_record_id': fact.record_id} if pressure else {})})
