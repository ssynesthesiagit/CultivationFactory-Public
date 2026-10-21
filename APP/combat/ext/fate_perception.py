"""Source-qualified fate observations used by Nudge's Marked Cause consumer.

Sources opt in with a reviewed fate_perception descriptor or register_source.
The registry supplies a capability to an already owned action; it grants no
new action, target or knowledge. Read the Thread is a printed fate observation.
"""
from . import hook, run_strict

SOURCES = set()


def subject_id(subject):
    return getattr(subject, 'entity_id', None) or subject.object_id


def subject_name(subject):
    return getattr(subject, 'display_name', None) or (getattr(subject, 'component', None) or {}).get('label') or 'the involved object'


def register_source(record_id):
    """Declare an existing printed fate-perception source (used by fate_nudge)."""
    SOURCES.add(record_id)


@hook('technique_used')
def observe_fate(ctx):
    from .spirit_traditions import feature_of
    if feature_of(ctx.action) not in SOURCES and not ctx.typed.get('fate_perception'):
        return
    for subject in ctx.targets:
        for fact in run_strict('fate_perception', ctx.engine, ctx.actor, subject, int(ctx.numbers.get('cl') or 1)):
            ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(subject_id(subject),), payload={'log': fact['description']})
