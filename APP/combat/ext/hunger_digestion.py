"""Common Hunger indigestion, consumed by the one Mantle implementation.

Only a real acquired Hunger bundle and an actual Mantle can create instability.
The ending save uses native defenses and owner choices. Lasting consequences
are ordinary permanent conditions with source-owned rest removal, never new
unrecognized expiry names. No declaration can supply an outcome or a charge.
"""
import json

from . import hook
from .needle import ask, checkpoint_id, CHOICE
from .retained_updates import record_instance_update

SOURCE = 'HUNGER_BASE_DIGESTIVE_MANTLE'
IMP = 'resource:named.impurity'
SAT = 'resource:named.satiety'
NO_SAT = 'condition:typed.hunger.indigestion_no_satiety'
MONSTROUS = 'condition:typed.hunger.indigestion_monstrous'
REST_KEY = 'hunger_indigestion_rest'


def profile(engine, actor):
    """The actor's own acquired, sealed Hunger statistics, or None."""
    return next((bundle['hunger_meals'] for bundle in engine.typed_bundle_documents
        if bundle['actor_id'] == actor.entity_id and 'hunger_meals' in bundle), None)


def begin_mantle(engine, actor, held):
    """Latch whether this actual activation is the next unstable Mantle."""
    config = profile(engine, actor)
    if config is None or actor.resources.get(IMP, 0) < config['pb']:
        return
    held.data['unstable'] = 1
    record_instance_update(engine, actor, 'condition', held.instance_id, held)


def end_mantle(engine, actor, held):
    """Settle once, within the Mantle owner's transaction and replay."""
    config = profile(engine, actor)
    if config is None or held.data.get('unstable') != 1:
        return
    from .ability_source import native_self_save
    from .hunger_riders import change_impurity
    from .forged_exhaustion import add
    dc = 8 + config['pb'] + config['key_mod']
    numbers = {key: config[key] for key in ('pb', 'key_mod', 'cl')}
    _, failed = native_self_save(engine, actor, numbers, 'CON', dc, SOURCE,
        name='Digestive Mantle: unstable nourishment', pending_effects=[
            {'type': 'condition', 'condition': 'poisoned', 'applies_to': 'self'},
            {'type': 'exhaustion', 'amount': 1, 'applies_to': 'self'},
            {'type': 'condition', 'condition': NO_SAT, 'applies_to': 'self'},
            {'type': 'condition', 'condition': MONSTROUS, 'applies_to': 'self'}])
    if not failed:
        change_impurity(engine, actor, -1, SOURCE,
            'Digestive Mantle: your Constitution save succeeds; reduce Impurity by 1.')
        return
    labels = {
        'poisoned': 'Become Poisoned until you finish a Short Rest.',
        'no_satiety': 'You cannot gain Satiety until you finish a Short Rest.',
        'exhaustion': 'Gain 1 level of Exhaustion from spiritual indigestion.',
        'monstrous': 'Your Hunger techniques look monstrous: Disadvantage on Charisma checks except Intimidation until you finish a Long Rest.',
    }
    picked = ask(engine, engine._active_intent,
        checkpoint_id(engine, 'HUNGER_INDIGESTION:' + held.instance_id, actor.entity_id), actor,
        CHOICE + 'hunger.indigestion', list(labels), labels=labels, preferred=['no_satiety'],
        target_id=actor.entity_id, name='Digestive Mantle: spiritual indigestion',
        feature_id='Digestive Mantle',
        prompt=f'Digestive Mantle: {actor.display_name} failed the ending Constitution save against Hunger DC {dc}. '
               'Choose one spiritual indigestion consequence. This choice costs no action or cultivation points.')
    if not picked:
        raise ValueError('Choose one printed spiritual indigestion consequence')
    choice = picked[0]
    if choice == 'exhaustion':
        add(engine, actor, 1, SOURCE)
    else:
        cid = {'poisoned': 'poisoned', 'no_satiety': NO_SAT, 'monstrous': MONSTROUS}[choice]
        engine._apply_condition(actor, cid, SOURCE, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={REST_KEY: 'long' if choice == 'monstrous' else 'short',
                'label': 'Digestive Mantle: ' + labels[choice]})


@hook('resource_gain_allowed')
def prevent_satiety(engine, actor, resource_id, amount, source_id):
    if resource_id == SAT and any(c.condition_id == NO_SAT for c in actor.conditions.values()):
        return False


@hook('ability_check_mode')
def monstrous_checks(engine, actor, ability, skill, against):
    if str(ability).upper() == 'CHA' and str(skill).lower() != 'intimidation' and any(
            c.condition_id == MONSTROUS for c in actor.conditions.values()):
        return 'DISADVANTAGE'


def rest(session, aid, kind):
    actor = session.state['actors'][aid]
    snapshot = actor.get('encounter_snapshot')
    if not snapshot:
        return
    for iid, raw in list(snapshot['conditions'].items()):
        row = json.loads(raw)
        required = row.get('data', {}).get(REST_KEY)
        if row['source_definition_id'] == SOURCE and row['source_actor_id'] == aid and (
                required == 'short' or required == 'long' and kind == 'long'):
            del snapshot['conditions'][iid]
            session.emit('HUNGER_INDIGESTION_ENDED', aid, source=SOURCE,
                instance_id=iid, condition_id=row['condition_id'], rest=kind,
                text='The completed rest ends this Digestive Mantle indigestion consequence.')


@hook('journey_short_rest')
def short_rest(session, aid):
    rest(session, aid, 'short')


@hook('journey_rest')
def long_rest(session, aid):
    rest(session, aid, 'long')


@hook('journey_options')
def rest_options(session, aid):
    actor = session.state['actors'][aid]
    if session.state['phase'] != 'travel' or actor['incapacitated']:
        return
    requirements = {json.loads(raw).get('data', {}).get(REST_KEY)
        for raw in actor.get('encounter_snapshot', {}).get('conditions', {}).values()
        if json.loads(raw)['source_definition_id'] == SOURCE}
    options = []
    if 'short' in requirements:
        options.append({'id': 'hunger:indigestion:short_rest', 'kind': 'short_rest', 'payload': {},
            'label': 'Rest for one hour: end Digestive Mantle’s Poisoned or blocked-Satiety consequence. No automatic HP or cultivation-point recovery.'})
    if 'long' in requirements or 'short' in requirements:
        options.append({'id': 'hunger:indigestion:long_rest', 'kind': 'long_rest', 'payload': {},
            'label': 'Rest for eight hours: end Digestive Mantle’s indigestion penalties, lose stored Satiety and reduce Impurity by your Proficiency Bonus. No automatic HP or cultivation-point recovery.'})
    return options or None
