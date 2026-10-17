"""Player-owned checkpoint enrollment shared by CombatService and journey activities.

This is a pure projection of existing compiled Ask me rows, setup tasks and
source-owned choice grants. Automatic actors stay automatic; absent grants are
inert. The native reaction provider still validates each actual reached choice.
"""

MANUAL_MODES = frozenset({'MANUAL', 'SUGGESTED', 'MANUAL_AI_BRIDGE'})


def condition_choice_owner(engine, actor, condition):
    from . import ext
    return bool(condition.data.get('choice_owner')) or any(
        value is True for value in ext.run('condition_choice_owner', engine, actor, condition))


def manual_choice_reactors(engine, modes):
    from . import ext
    rows = getattr(engine, 'typed_reaction_rows', {}) or {}
    passives = getattr(engine, 'typed_passive_rows', {}) or {}
    choices = {aid for ids in ext.run('choice_reactors', engine) for aid in ids}
    return frozenset(aid for aid, actor in engine.state.actors.items()
        if modes.get(aid) in MANUAL_MODES and (
            aid in choices or any(task.actor_id == aid for task in engine.state.setup_tasks)
            or any(row.get('ask') for row in rows.get(aid, ()))
            or any(row.get('choice_owner') for row in passives.get(aid, ()))
            or any(condition_choice_owner(engine, actor, c) for c in actor.conditions.values())))
