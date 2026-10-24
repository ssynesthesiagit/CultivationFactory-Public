"""Owned initiative/setup work, committed before the first turn starts.

Consumers declare tasks without changing state, then resolve their own task using
the ordinary choice transport and evented effects. No interactive constructor.
"""
from . import ext
from .alternative_payments import owned
from .gate2_runtime_models import FightSetupTask

SOURCE = 'system:combat.fight_setup'


def label(engine):
    """Optional source-owned plain captions; absence retains the legacy label."""
    captions = ext.query('fight_setup_label', engine)
    return '; '.join(caption for caption in captions if isinstance(caption, str) and caption) or 'Finish fight setup'


def collect(engine):
    tasks = []
    for rows in ext.run_strict('fight_setup_tasks', engine):
        for row in rows:
            task = FightSetupTask.model_validate(row)
            actor = engine.state.actors.get(task.actor_id)
            if actor is None or not actor.active or not owned(engine, actor, task.source_id):
                continue
            if task in tasks:
                raise ValueError('duplicate fight setup task')
            tasks.append(task)
    return tuple(tasks)


def resolve(engine, intent):
    for task in engine.state.setup_tasks:
        actor = engine.state.actors[task.actor_id]
        if not owned(engine, actor, task.source_id):
            raise ValueError('fight setup ability is no longer owned')
        results = ext.run_strict('fight_setup', engine, actor, task.source_id, intent)
        if results != [True]:
            raise ValueError('exactly one consumer must finish each fight setup task')
    engine.state.setup_tasks = ()
    engine._append_event('FIGHT_SETUP_COMPLETED', SOURCE,
                         payload={'log': 'Fight setup is complete. The first turn begins.'})
