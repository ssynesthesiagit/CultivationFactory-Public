"""Owned initiative/setup work, committed before the first turn starts.

Consumers declare tasks without changing state, then resolve their own task using
the ordinary choice transport and evented effects. No interactive constructor.
"""
from . import ext
from .alternative_payments import owned
from .gate2_runtime_models import FightSetupTask

SOURCE = 'system:combat.fight_setup'


def authorized(engine, actor, task):
    """Owned setup or an exact native effect requiring transactional turn entry.

    The latter binds the affected creature and actual condition instance/source,
    not ownership of its creator's feature. It grants no action or source row.
    Without effect_instance_id the established ownership rule is unchanged.
    """
    if task.actor_id!=actor.entity_id:return False
    if task.effect_instance_id is None:return owned(engine,actor,task.source_id)
    effect=actor.conditions.get(task.effect_instance_id)
    return bool(effect and effect.target_id==actor.entity_id and effect.source_definition_id==task.source_id)


def collect(engine):
    tasks = []
    for rows in ext.run_strict('fight_setup_tasks', engine):
        for row in rows:
            task = FightSetupTask.model_validate(row)
            actor = engine.state.actors.get(task.actor_id)
            if actor is None or not actor.active or not authorized(engine, actor, task):
                continue
            if task in tasks:
                raise ValueError('duplicate fight setup task')
            tasks.append(task)
    return tuple(tasks)


def resolve(engine, intent):
    for task in engine.state.setup_tasks:
        actor = engine.state.actors[task.actor_id]
        if not authorized(engine, actor, task):
            raise ValueError('fight setup ability is no longer owned')
        results = ext.run_strict('fight_setup', engine, actor, task.source_id, intent)
        if results != [True]:
            raise ValueError('exactly one consumer must finish each fight setup task')
    engine.state.setup_tasks = ()
    engine._append_event('FIGHT_SETUP_COMPLETED', SOURCE,
                         payload={'log': 'Fight setup is complete. The first turn begins.'})
