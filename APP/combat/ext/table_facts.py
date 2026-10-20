"""Versioned native input dispatch; all schemas and authority remain shared."""
from . import hook
from ..table_facts import validate,execute


@hook('recorded_intent_validate')
def world_validate(engine,intent,binding):return validate(engine,intent,binding)


@hook('recorded_intent_execute')
def world_execute(engine,intent,binding):return execute(engine,intent,binding)


@hook('recorded_input_no_reactions')
def no_creature_decisions(binding):
    from ..table_facts import KIND
    return True if binding.get('kind')==KIND and set(binding)=={'kind','payload'} and isinstance(binding['payload'],dict) else None
