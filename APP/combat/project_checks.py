"""Public project roll contract used by Technique Forging and Foundation Challenges.

The GM admits external scene facts through the protected record_fact endpoint.
An owned actor then chooses a project from their audience, rolls native recorded
statistics, and commits a result once. A success is a roll receipt, never an
automatic acquisition or a grant of a Sphere/technique. Consumers may adjust the
DC through project_check_dc; absent providers leave the printed DC unchanged.
"""
from . import ext
from . import engine_seam as seam
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
    if not project:
        return document
    from copy import deepcopy
    from .canonical import canonical_sha256
    from .tabletop_service import FACTORY_PREFIX
    actor_id = str(project.get('actor_id') or '')
    if project.get('kind') == 'foundation_challenge':
        # The admitted challenge is bound to the acquisition current at admission,
        # so a replacement Foundation cannot spend an earlier successful roll.
        from .foundation_attainment import acquisition_id
        if not actor_id.startswith(FACTORY_PREFIX):
            raise ValueError('Choose a Factory character for the Foundation Challenge.')
        result = deepcopy(document)
        result['project_check'] = {**project, 'foundation_acquisition_id': acquisition_id(
            table.combat._factory_owner_sheet(actor_id.removeprefix(FACTORY_PREFIX)))}
        return result
    if project.get('kind') != 'technique_forging':
        return document
    if not actor_id.startswith(FACTORY_PREFIX) or not isinstance(project.get('design'), dict):
        raise ValueError('Choose a Factory character and a complete native forging design.')
    technique = table.forge(actor_id.removeprefix(FACTORY_PREFIX), project['design'], save=False)['technique']
    result = deepcopy(document)
    result['project_check'] = {**project, 'complexity': int(technique['complexity']['final']),
        'sphere_ids': list(technique['sphere_ids_used']), 'construction_sha256': canonical_sha256(technique)}
    return result


def validate_project(engine, fact):
    project = fact.project_check
    if project.actor_id not in engine.state.actors:
        raise ValueError('The project owner must be present.')
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
    numbers = numbers_of(ctx.engine, ctx.actor)
    modifier = (int(numbers['pb']) + int(numbers['key_mod']) if project.skill == 'Cultivation'
                else ordinary_check_bonus(ctx.engine, ctx.actor, project.ability, project.skill, numbers=numbers))
    if modifier is None:
        raise ValueError('This character has no recorded modifier for that project check.')
    modifier += sum(ext.run_strict('check_bonus', ctx, ctx.actor))
    base_dc = (10 + project.complexity + len(project.sphere_ids)
               if project.kind == 'technique_forging' else project.challenge_dc)
    delta = sum(ext.run_strict('project_check_dc', ctx.engine, ctx.actor, fact))
    dc = max(1, base_dc + delta)
    scope = {'kind': 'check', 'actor_id': ctx.actor.entity_id, 'target_id': ctx.actor.entity_id,
             'source_id': ctx.source, 'source_actor_id': ctx.actor.entity_id,
             'ability': project.ability, 'skill': project.skill, 'dc': dc,
             'check_kind': project.kind, 'hazards': [project.kind, 'project:' + fact.record_id], 'named': []}
    with ctx.engine.d20_scope(scope):
        roll = ctx.engine.roll_check(modifier=modifier, actor_id=ctx.actor.entity_id,
            reason=f'CHECK:{ctx.source}', ability=project.ability, skill=project.skill,
            hazards=(project.kind,))
        roll = ext.floored(ctx.engine, ctx.actor, roll, dc, ability=project.ability, skill=project.skill)
    seam.record_roll(ctx.engine, roll)
    seam.append_event(ctx.engine, 'CHECK_ROLLED', ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
        payload={'project_record_id': fact.record_id, 'source_reference': fact.source_reference,
                 'project_kind': project.kind, 'base_dc': base_dc, 'dc_adjustment': delta, 'dc': dc,
                 'check': fact.subject_name, 'skill': project.skill,
                 'actor': roll.model_dump(mode='json'), 'success': roll.total >= dc,
                 **({'foundation_acquisition_id': project.foundation_acquisition_id}
                    if project.kind == 'foundation_challenge' else {})})
