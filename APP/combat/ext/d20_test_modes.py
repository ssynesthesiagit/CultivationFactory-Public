"""One-use modes for a source saying 'the next d20 Test', including Curse Word.

Native attack/check/save readers combine these ordinary rule fields before
Advantage/Disadvantage cancellation. Reading a menu never consumes the state;
the completed draw consumes it, including a roll whose modes cancelled.
"""
from . import hook

CONDITION = 'condition:typed.next_d20_test_mode'


def give_mode(ctx, effect, mode):
    from ..typed_executor import effect_subjects, effect_expiry, save_provenance
    for subject in effect_subjects(ctx, effect, harmful=mode == 'DISADVANTAGE'):
        ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, effect, subject, condition=True) or 'END_OF_HOLDER_NEXT_TURN',
            data={'label': f'{mode.title()} on the next attack roll, ability check or saving throw',
                  'mode': mode, 'rule': {'attacks_have': mode, 'check_mode': {'ALL': mode},
                                        'save_mode': {ability: mode for ability in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')},
                                        'death_save_mode': {'mode': mode}},
                  **({'origin_save': save_provenance(ctx)} if save_provenance(ctx) else {})})


@hook('d20_finalized')
def consume_mode(engine, roll, intent):
    if roll.natural_result is None:
        return
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None:
        return
    for held in list(actor.conditions.values()):
        if held.condition_id == CONDITION:
            engine._remove_condition_instance(actor, held.instance_id, held.source_definition_id)
