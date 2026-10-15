"""Public Foundation source and settled-event context transport.

Consumers: Funeral Ash generation; Ash Strike/Garden/Mercy can use the same
public queries. Method membership is sealed from exact compiled source records,
not affinity spheres, action labels or damage colours. Scene judgments come from
the native table choice transport, are event-scoped and journaled, and remain
unknown when no person has established them. An automatic seat cannot invent facts.
For an automatic owner, a conscious human-controlled witness may attest the
public event at the table. This is factual testimony, not an Ash spending choice.
Explicit public encounter facts can also be recorded through pre-fight setup;
absent declarations never establish danger, residue, or meaningful endings.
"""
from . import hook
from .needle import ask, checkpoint_id

ASH = 'foundation.red_lotus_ash_returning_v0_2B.'
CONTEXT = 'choice:needle.foundation_event_context'
UNCONSCIOUS = frozenset(('unconscious', 'life_unconscious', 'asleep', 'dream_sleep'))
SCENE_SOURCE = 'foundation:public_scene_context'
SCENE_CHOICES = {
    'circumstances': ('unknown', 'real', 'staged', 'harmless', 'voluntary', 'training'),
    'residue': ('unknown', 'battlefield', 'fresh'),
    'ending': ('unknown', 'defeat'),
}


@hook('prefight_setup_choices')
def public_scene_choices(bundle):
    """Record encounter adjudication through the existing fight-setup controls.

    These are public facts known to this creature, never an AI judgment from
    damage colours, team membership, or another creature's private information.
    Every default is unknown; recording facts neither grants Ash nor pays costs.
    """
    if not any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
               for row in bundle.get('typed_passives', ())):
        return None
    descriptions = {
        'circumstances': ('Funeral Ash: public encounter circumstances',
            'Record only circumstances established publicly and known to this creature for this encounter: '
            '0 = unknown; 1 = real hostile danger, not staged, harmless, voluntary, or training; '
            '2 = staged; 3 = harmless; 4 = voluntary harm; 5 = training.'),
        'residue': ('Funeral Ash: public battlefield residue',
            'For this creature\'s methods in this encounter, record only an established public fact: '
            '0 = unknown; 1 = the methods work through battlefield residue; '
            '2 = no battlefield residue is involved. Damage alone does not establish residue.'),
        'ending': ('Funeral Ash: public meaning of enemy defeats',
            'Record an established public encounter ruling known to this creature: '
            '0 = unknown; 1 = enemy defeats here are meaningful endings under real danger. '
            'An actual observed enemy defeat is still required; this does not establish mercy or cautery.'),
    }
    return [{'id': 'ash_public_' + key, 'kind': 'integer_range_list', 'count': 1,
             'label': descriptions[key][0], 'item_label': descriptions[key][0],
             'help': descriptions[key][1] + ' This record lasts for this encounter and costs no action or resource. '
                     'Leave it unknown if circumstances may vary or are private. Helpless targets never qualify.',
             'minimum': 0, 'maximum': len(values) - 1, 'default': [0]}
            for key, values in SCENE_CHOICES.items()]


@hook('match_start')
def record_public_scene(engine):
    for bundle in getattr(engine, 'typed_bundle_documents', ()):
        if bundle.get('actor_id') not in engine.state.actors or not public_scene_choices(bundle):
            continue
        choices = (bundle.get('prefight') or {}).get('setup_choices') or {}
        facts = {}
        for key, values in SCENE_CHOICES.items():
            picked = choices.get('ash_public_' + key, [0])
            index = picked[0] if isinstance(picked, list) and len(picked) == 1 else 0
            facts[key] = values[index] if type(index) is int and 0 <= index < len(values) else 'unknown'
        if all(value == 'unknown' for value in facts.values()):
            continue
        engine._append_event('PASSIVE_TRIGGERED', SCENE_SOURCE, actor_id=bundle['actor_id'],
            payload={'fact_kind': 'foundation_public_scene', **facts,
                     'log': 'Funeral Ash: public encounter facts recorded at fight setup. '
                            'They cost no action or resource and do not grant Funeral Ash.'})


def public_scene_context(engine, owner):
    """Sealed, journaled setup facts known to this owner; absent facts are unknown.

    Consumers: adjudicated_event_context and Foundation conversion plug-ins.
    Only this actor's public declaration is consulted, never an enemy's bundle.
    """
    return next((dict(event.payload, setup_sequence=event.sequence)
                 for event in reversed(engine.events)
                 if event.source_definition_id == SCENE_SOURCE and event.actor_id == owner.entity_id
                 and event.payload.get('fact_kind') == 'foundation_public_scene'), {})


def unconscious_condition(condition_id):
    """Supported unconscious states, including Dreams' damage-ending sleep.

    Shared by the live owner query and the immutable pre-damage target snapshot;
    incapacitated alone does not imply unconsciousness or helplessness.
    """
    return condition_id.rsplit('.', 1)[-1] in UNCONSCIOUS


@hook('choice_reactors')
def context_witnesses(engine):
    """Enroll potential human factual witnesses only in Ash-generator fights."""
    from ..tabletop_service import MANUAL_MODES
    if not any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
               for rows in getattr(engine, 'typed_passive_rows', {}).values() for row in rows):
        return ()
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if conscious(a) and (getattr(engine, 'typed_control_modes', {}) or {}).get(
                     getattr(a, 'owner_id', None) or a.entity_id, 'MANUAL') in MANUAL_MODES)

# Reviewed against the complete printed records. These are method categories,
# NOT unconditional Ash alignment. Meridian additionally requires context.
METHODS = {
    'FIRE_TAL_FIREBALL_ART': ('fire', '3e09583d71bf13d8cb81045fd2b3f6834c1fe77be7a3ee931692b0f3530a6e75'),
    'DISEASE_BASE_SOW_THE_FEVER_SEED': ('disease', 'bad2b38124ecf015ee13a1e6651b52d784300b3509002487c74bc63aa430357e'),
    'BLOOD_BASE_COAGULATE': ('blood', '736c3a45e34fccf35d2ede00bdd85e741dc7205c85147108b2987e6128af0104'),
}


@hook('compile_passives')
def seal_meridian_ownership(rows, info):
    source = ASH + 'ash_returning_meridian'
    if source not in info['owned_ids']:
        return rows
    return [*rows, {'block': 'foundation_context_meridian', 'feature_id': source}]


@hook('damage_receipt_facts')
def ash_target_facts(engine, target, source_id, source_actor_id):
    if not any(any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
                   for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))
               for actor in engine.state.actors.values()):
        return None
    from ..senses import perceives
    observers = [actor.entity_id for actor in engine.state.actors.values()
                 if any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
                        for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))
                 and perceives(engine, actor, target)]
    return {'target_active_before': int(target.active), 'target_perceived_by': sorted(observers),
            'target_context_witnesses_before': sorted(aid for aid in context_witnesses(engine)
                if perceives(engine, engine.state.actors[aid], target)),
            'target_conditions_before': sorted(c.condition_id for c in target.conditions.values())}


@hook('compile_action')
def seal_source_method(action, info):
    typed = dict(action.parameters.get('typed') or {})
    source = typed.get('source')
    method = METHODS.get(source)
    mechanic = info['mechanics'].get(source) or {}
    if method and (mechanic.get('source') or {}).get('text_sha256') == method[1]:
        typed['foundation_source_method'] = {
            'category': method[0], 'mechanic_id': source, 'text_sha256': method[1]}
        return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})
    return action


def source_method_facts(engine, source_id):
    """Return sealed public method provenance, or None for an unknown source."""
    action = engine.action_catalog.get(source_id)
    return (action.parameters.get('typed') or {}).get('foundation_source_method') if action else None


def settled_execution_events(engine, first_sequence):
    """Receipts in this fully resolved accepted execution, including reactions.

    Call only from transaction_settled. No backwards scan across another accepted
    execution, and no persistent/transient packet cache requiring cold repair.
    """
    return tuple(e for e in engine.events if e.sequence > first_sequence)


def conscious(actor):
    """Positive HP alone does not make a sleeping/unconscious owner conscious."""
    return (actor is not None and actor.active and actor.current_hp > 0
            and actor.life_state not in ('DYING', 'STABLE')
            and not any(unconscious_condition(c.condition_id)
                        for c in actor.conditions.values()))


def helpless_before(event):
    """Mechanical helplessness at the event's start, not its defeat consequence."""
    payload = event.payload or {}
    return (int(payload.get('hp_before') or 0) <= 0
            or not payload.get('target_active_before', 1)
            or any(unconscious_condition(c) or c.rsplit('.', 1)[-1] == 'paralyzed'
                   for c in payload.get('target_conditions_before') or ()))


def ash_aligned(engine, owner, event, facts):
    """Public context-qualified Meridian query for generation/Strike/Garden.

    Exact-source method membership and attested battlefield residue are both
    required. Wounded means wounded BEFORE the packet, never a fresh target
    made eligible by that packet. Unknown/private facts do not qualify.
    """
    method = source_method_facts(engine, event.source_definition_id)
    target = engine.state.actors.get(next(iter(event.target_ids), ''))
    owns = any(row.get('feature_id') == ASH + 'ash_returning_meridian'
               for row in engine.typed_passive_rows.get(owner.entity_id, ()))
    from ..relations import relation, ENEMY
    return bool(owns and method and facts.get('circumstances') == 'real'
                and facts.get('residue') == 'battlefield'
                and event.actor_id == owner.entity_id and target
                and relation(engine, owner, target) == ENEMY and not helpless_before(event)
                and 0 < int(event.payload.get('hp_before') or 0) < target.maximum_hp)


def adjudicated_event_context(engine, owner, event, intent, *, route, damage_receipt=None):
    """Get public event facts through actual native controller/table answers.

    A single answer attests ALL listed exclusion boundaries. A second answer
    supplies a fact whose meaning is not inferable from HP/damage (residue,
    real attrition or an ending). Each receipt binds source, target, packet,
    execution and declarant. Automatic actors preserve unknown judgments, but
    can consume their sealed public setup facts or testimony from a human
    witness captured before damage.
    Ending callers supply their matched damage receipt for witness provenance
    and the causal source/creature instead of the system defeat wrapper.
    """
    receipt = damage_receipt if damage_receipt is not None else event
    # Defeat wrappers may deliberately name system:damage. The correlated
    # committed packet is the causal source, including on terminal actions.
    source_id = (receipt.source_definition_id if damage_receipt is not None else
                 (event.payload or {}).get('defeating_source') or receipt.source_definition_id)
    action = engine.action_catalog.get(source_id)
    action_name = action.display_name if action else 'the resolved event'
    subject = engine.state.actors.get(next(iter(receipt.target_ids), event.actor_id))
    subject_name = subject.display_name if subject else 'the affected creature'
    from . import ai_controlled
    established = public_scene_context(engine, owner) if ai_controlled(engine, owner) else {}
    declarant = owner
    if ai_controlled(engine, owner):
        witnesses = set(receipt.payload.get('target_context_witnesses_before') or ())
        declarant = next((engine.state.actors[aid] for aid in sorted(witnesses)
                          if aid in context_witnesses(engine)), owner)
    base = dict(name='Funeral Ash', feature_id=ASH + 'generate_funeral_ash',
                target_id=subject.entity_id if subject else owner.entity_id,
                prompt_context={'action_name': action_name, 'source_definition_id': source_id,
                    'affected_id': subject.entity_id if subject else '', 'cost': 'No action or resource cost'})
    labels = {
        'real': 'Real hostile danger: not staged, harmless, voluntary, training, or a helpless-target event',
        'staged': 'Staged event', 'harmless': 'Harmless event', 'voluntary': 'Voluntary harm',
        'training': 'Training event', 'helpless': 'Helpless-target event', 'unknown': 'Circumstances are unknown',
    }
    # Stabilization alone establishes neither cautery nor the exclusion boundary
    # for a helpless target. Do not invite a positive assertion contrary to the
    # mechanical receipt. A source-qualified cautery producer needs its own
    # resolved event contract before this shared query can admit that route.
    if route == 'ending' and event.event_type == 'LIFE_STATE_CHANGED':
        return {'circumstances': 'unknown', 'ending': 'unknown'}
    if established.get('circumstances', 'unknown') != 'unknown':
        chosen = [established['circumstances']]
    else:
        chosen = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACTS', event.sequence, owner.entity_id),
            declarant, CONTEXT, list(labels), labels=labels, preferred=['unknown'], allow_decline=True,
            automatic_options=['unknown'], default='decline',
            prompt=f'Funeral Ash after {action_name} affects {subject_name}: which circumstances are established?', **base)
    facts = {'circumstances': chosen[0] if chosen else 'unknown'}
    if facts['circumstances'] == 'real':
        if route == 'outgoing':
            options = {'battlefield': 'This method worked through battlefield residue',
                       'fresh': 'No battlefield residue was involved', 'unknown': 'Residue is unknown'}
            key = 'residue'
        elif route == 'incoming':
            # Fire/poison/necrotic and explicitly reviewed Disease are mechanically
            # known. Other ordinary damage needs an actual attrition judgment.
            method = source_method_facts(engine, event.source_definition_id) or {}
            kind = str(event.payload.get('damage_type') or '').lower()
            if method.get('category') == 'disease':
                facts['damage_category'] = 'disease'
                options = None
            elif kind in ('fire', 'poison', 'necrotic'):
                facts['damage_category'] = kind
                options = None
            else:
                options = {'attrition': 'Actual hostile attrition damage',
                           'blood_loss': 'Actual hostile blood-loss damage',
                           'other': 'Other damage, without established attrition', 'unknown': 'Damage context is unknown'}
            key = 'damage_category'
        else:
            options = {'defeat': 'A meaningful enemy defeat resolved under real danger',
                       **({'mercy': 'The defeated enemy was genuinely spared under real danger'}
                          if event.payload.get('nonlethal') else {})}
            options['unknown'] = 'No meaningful ending is established'
            key = 'ending'
        if options:
            if established.get(key, 'unknown') in options and established.get(key, 'unknown') != 'unknown':
                selected = [established[key]]
            else:
                selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACT_DETAIL', event.sequence, owner.entity_id),
                    declarant, CONTEXT + '.detail', list(options), labels=options, preferred=['unknown'],
                    automatic_options=['unknown'], allow_decline=True, default='decline',
                    prompt=f'Funeral Ash after {action_name} affects {subject_name}: confirm the observed {key.replace("_", " ")}.', **base)
            facts[key] = selected[0] if selected else 'unknown'
    engine._append_event('PASSIVE_TRIGGERED', source_id,
        actor_id=owner.entity_id, target_ids=event.target_ids,
        payload={'event_sequence': event.sequence, 'intent_id': intent.intent_id,
                 'fact_kind': 'foundation_event_context',
                 'route': route, 'declarant': declarant.entity_id,
                 **({'setup_sequence': established['setup_sequence']} if established else {}),
                 'log': f'Funeral Ash context after {action_name} affects {subject_name}: '
                        f'{labels[facts["circumstances"]]}. Recording context costs no action or resource.',
                 **facts})
    return facts
