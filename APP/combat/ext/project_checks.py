"""Native scene project intents, shared by Forging and Foundation Challenges."""
from . import hook, effect, run_strict
from .needle import ask, checkpoint_id, CHOICE
from .. import project_checks as projects


@hook('compile_actions')
def action(info):
    if (not any(str(fid).startswith('foundation.') for fid in info['owned_ids'])
            and not any(run_strict('project_check_access', info))):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=projects.SOURCE + '.' + info['short'],
        display_name='Resolve a project check', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'setting_only': True,
            'project_cultivation_ability': str((info['owner_sheet'].get('identity') or {}).get('key_ability') or 'INT').upper()[:3],
            'typed': {'source': projects.SOURCE, 'numbers': {**info['numbers'], 'ability_mods': dict(info['mods'])},
                      'effects': [{'type': 'scene_project_check'}], 'riders': []}, 'expected_damage': 0})]


@hook('candidate_allowed')
def allowed(engine, actor, candidate, action):
    if action and (action.parameters.get('typed') or {}).get('source') == projects.SOURCE:
        return bool(projects.available(engine, actor))
    return None


@effect('scene_project_check')
def roll(ctx, eff):
    options = projects.available(ctx.engine, ctx.actor)
    if not options:
        raise ValueError('No current project check has been admitted for this character.')
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'PROJECT_CHECK', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'project_check', list(options), name='Resolve a project check',
        labels={key: fact.subject_name for key, fact in options.items()}, preferred=list(options)[:1],
        prompt='Choose the admitted cultivation project, Foundation Challenge or scene check to roll. This costs no combat action and grants no technique by itself.')
    if pick:
        projects.resolve(ctx, options[pick[0]])
