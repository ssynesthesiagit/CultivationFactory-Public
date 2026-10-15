"""Opt-in native audible speech, using the intent's source-owned typed input.

Text is a controller declaration of its actor's actual speech, never a claim
about another actor's willingness, hidden state or a resolved mechanical event.
The normal voice eligibility and pre-payment interruption gates apply.
"""
from . import hook, effect, run_strict

SOURCE = 'system:combat.speak'


@hook('match_start')
def install(engine):
    if not any(run_strict('activity_declarations_enabled', engine)):
        return
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    engine.action_catalog[SOURCE] = ActionDefinition(source_definition_id=SOURCE,
        display_name='Speak audibly', owner_id='*', economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={
            'free_primary': True, 'requires_voice': True, 'expected_damage': 0,
            'source_input_schema': {SOURCE: {'text': {'type': 'string', 'min_length': 1, 'max_length': 500}}},
            'typed': {'effects': [{'type': 'audible_speech'}], 'numbers': {},
                      'riders': [], 'duration': {'kind': 'instant'}}})


@hook('additional_actions')
def actions(engine, actor):
    return [SOURCE] if SOURCE in engine.action_catalog else []


@hook('source_choice_admission')
def admit(engine, actor, candidate, source, value):
    if source != SOURCE:
        return None
    text = value.get('text')
    return (candidate.source_definition_id == SOURCE and set(value) == {'text'}
            and isinstance(text, str) and 0 < len(text.strip()) <= 500
            and all(ord(char) >= 32 or char in '\n\t' for char in text))


@effect('audible_speech')
def speak(ctx, effect):
    text = ctx.intent.source_choices.get(SOURCE, {}).get('text')
    if text is None:
        from .needle import ask, checkpoint_id, CHOICE
        words = {'hold': 'Hold your position.', 'challenge': 'Face me.', 'wait': 'Wait.'}
        chosen = ask(ctx.engine, ctx.intent,
            checkpoint_id(ctx.engine, 'spoken_words', ctx.actor.entity_id), ctx.actor,
            CHOICE + 'spoken_words', list(words), labels=words, preferred=['hold'],
            name='Speak audibly', prompt='Choose what you say aloud. No Action or resource cost. A prepared reaction to speech may interrupt you.')
        if not chosen:
            return
        text = words[chosen[0]]
    from ..activity_phases import begin, can_continue
    if begin(ctx.engine, ctx.actor, 'SPEECH_BEGUN', SOURCE, payload={'text': text}):
        # BEGIN is the real audible first words. A reaction can interrupt the
        # remainder; it cannot retroactively erase the trigger already heard.
        if can_continue(ctx.engine, ctx.actor):
            ctx.engine._append_event('SPEECH_FINISHED', SOURCE,
                actor_id=ctx.actor.entity_id, payload={'text': text})
