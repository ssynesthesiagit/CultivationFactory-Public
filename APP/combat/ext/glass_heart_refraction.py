"""Private scene admission for the existing Glass Heart Refraction provider.

Two separate authorities keep this record honest:

* The owner/GM decides the scene ("you enter a major combat or emotionally
  decisive scene"). That external fact is either recorded through the
  owner-only declaration form or asked at the bearer's own turn start as an
  explicit GM adjudication; neither damage, teams, names nor a model's guess
  establishes scene importance, and the documented GM-adjudication transport
  forbids a local or model AI from inventing it.
* The character decides whether to stand in transparent clarity. That question
  is the character's own: the paid state appears in the bearer's ordinary
  action menu for both human and AI seats, so a player picks it and an AI seat
  picks it from its own menu. The owner never answers for the character.

The turn-start checkpoint means normal automatic play cannot pass the bearer's
qualifying turn while the owner input or the character's own opportunity is
still outstanding. This module adds no Reflection grant or positive numerical
combat benefit.
"""
from . import hook
from ..table_facts import apply as record_fact, records

SOURCE = 'foundation.glass_heart_meridian_v0_2A.perfected_glass_heart_refraction'
SCENES = ('Major combat', 'Emotionally decisive scene', 'Neither')
QUALIFYING = tuple(scene for scene in SCENES if scene != 'Neither')
# The safe answer leads: a story that is not clearly a qualifying scene stays
# unchecked until the owner picks one deliberately.
ASK_ORDER = ('Neither', 'Major combat', 'Emotionally decisive scene')
CHOICE = 'choice:needle.glass_refraction_scene'


def owned_action(engine, actor_id):
    return next((a for a in engine.action_catalog.values() if a.owner_id == actor_id
                 and (a.parameters.get('typed') or {}).get('source') == SOURCE), None)


def held(engine, actor_id):
    action = owned_action(engine, actor_id)
    if action is None:
        return False
    from .foundation_combat import held as holds
    actor = engine.state.actors.get(actor_id)
    return bool(actor is not None and holds(actor, 'glass_refraction'))


def declared(engine, actor):
    """True once the owner has answered the scene question for this bearer's current turn.

    Keyed to the turn stamp, not the whole fight: an earlier answer (including a
    Neither or a decline) must not hide a later qualifying scene.
    """
    record_id = SOURCE + ':' + actor.entity_id
    stamp = 'turn:' + str(expected_turn(engine, actor))
    for event in engine.events:
        if event.event_type != 'TABLE_FACT_RECORDED':
            continue
        fact = event.payload.get('fact') or {}
        answer = (fact.get('answers') or {}).get('glass_refraction') or {}
        if str(fact.get('record_id')) == record_id and answer.get('condition') == stamp:
            return True
    return False


def usable(engine, actor, action):
    """Pure: could this bearer actually pay for and use the state right now?"""
    if not actor.active or not actor.bonus_action_available:
        return False
    used = actor.resources.get('resource:uses.' + action.source_definition_id)
    if used is not None and int(used) <= 0:
        return False
    totals = {}
    for rid, amount in action.costs:
        totals[rid] = totals.get(rid, 0) + int(amount)
    return all(int(actor.resources.get(rid, 0)) >= amount for rid, amount in totals.items())


def expected_turn(engine, actor):
    """The one turn stamp a scene fact is written with and checked against.

    A bearer's own turn (current actor, turns_started already advanced by
    _system_start_turn before turn-start hooks) is the current turn. On any other
    creature's turn, the bearer's next natural start is the next stamp.
    """
    return actor.turns_started + int(engine.state.current_actor_id != actor.entity_id)


def _document(engine, actor, scene, reason):
    return {'record_id': SOURCE + ':' + actor.entity_id, 'subject_id': actor.entity_id,
            'subject_name': actor.display_name, 'subject_kind': 'creature',
            'position': actor.position.model_dump(mode='json'),
            'source_reference': (reason or '').strip()[:2000] or 'Owner-recorded scene declaration',
            'witness_ids': [actor.entity_id],
            # Entry on another creature's turn must reach the bearer's first
            # natural Bonus Action opportunity, including across initiative wrap.
            'valid_through_round': engine.state.round_number + 1,
            'answers': {'glass_refraction': {'fact': scene, 'category': 'scene',
                'visible_sign': 'Private owner declaration', 'source_cl': 0,
                'condition': 'turn:' + str(expected_turn(engine, actor))}}}


@hook('table_source_inputs')
def scene_forms(engine):
    """Owner/GM adjudication of the scene only; the character decides separately."""
    return [{'source_id': SOURCE, 'actor_id': a.entity_id,
             'label': f'{a.display_name}: Glass Heart Refraction',
             'description': 'Owner/GM only: record whether this character is entering a major combat or an '
                'emotionally decisive scene. This private note is free and only unlocks the character’s own '
                'choice; it never decides for them. If the scene qualifies, the character may use a Bonus Action '
                'and 2 cultivation points (CP) once per long rest to stand in transparent clarity for 1 minute — '
                'showing their true self instead of hiding behind beauty, denial or reflection. It does not raise '
                'Glass Reflection (the one-point reflection you can hold) above 1, and a Glass Reflection gained '
                'from this same scene cannot be spent on it.',
             'fields': [
                 {'name': 'scene', 'label': 'Scene being entered', 'options': list(SCENES)},
                 {'name': 'reason', 'label': 'Private scene details', 'options': []}]}
            for a in engine.state.actors.values() if owned_action(engine, a.entity_id)] or None


@hook('table_source_document')
def scene_document(engine, source_id, actor_id, values):
    if source_id != SOURCE:
        return None
    actor = engine.state.actors.get(actor_id)
    if actor is None or owned_action(engine, actor_id) is None:
        raise ValueError('Only a character with Perfected Glass Heart Refraction can declare it.')
    if (set(values) != {'scene', 'reason'}
            or not all(isinstance(v, str) for v in values.values()) or values['scene'] not in SCENES
            or not 1 <= len(values['reason'].strip()) <= 2000):
        raise ValueError('Choose the actual scene and add private details.')
    return _document(engine, actor, values['scene'], values['reason'].strip())


@hook('table_fact_validate')
def validate_scene(engine, fact):
    answer = fact.answers.get('glass_refraction')
    if answer is None:
        return
    actor = engine.state.actors.get(fact.subject_id)
    if (actor is None or owned_action(engine, fact.subject_id) is None
            or fact.record_id != SOURCE + ':' + fact.subject_id
            or fact.valid_through_round != engine.state.round_number + 1
            or fact.witness_ids != (fact.subject_id,)
            or answer.condition != 'turn:' + str(expected_turn(engine, actor))
            or answer.fact not in SCENES or answer.category != 'scene'):
        raise ValueError('Refraction needs this bearer’s current, private entry declaration.')


@hook('candidate_allowed')
def admitted(engine, actor, candidate, action):
    """The bearer's own decision: the paid state is offered in the ordinary menu.

    Only the scene is owner-adjudicated; standing in transparent clarity is the
    character's choice, so a human seat may pick it and an AI seat may pick it
    from its own menu without the owner answering for it.
    """
    if action is None or (action.parameters.get('typed') or {}).get('source') != SOURCE:
        return None
    if engine.state.current_actor_id != actor.entity_id:
        return False  # the paid state is an action on the bearer's own turn only
    fact = records(engine, actor).get(SOURCE + ':' + actor.entity_id)
    answer = fact.answers.get('glass_refraction') if fact else None
    return bool(answer and answer.fact in QUALIFYING
                and answer.condition == 'turn:' + str(expected_turn(engine, actor)))


@hook('turn_start_choice')
def scene_at_turn_start(engine, actor):
    """Safe checkpoint for the required owner scene fact.

    Run when the bearer could actually use the state this turn and no scene has
    been declared yet. The owner/GM answers (never inferred from damage, teams
    or names): the question is marked as a GM adjudication, so an automatic turn
    pauses for the table instead of skipping past this bearer's opportunity.
    """
    state = engine.state
    if state.terminal_result is not None or state.pending_resolution is not None or state.setup_tasks:
        return  # the fact journal is only writable outside a resolution
    action = owned_action(engine, actor.entity_id)
    if action is None or declared(engine, actor) or held(engine, actor.entity_id) or not usable(engine, actor, action):
        return
    from .needle import ask, can_ask, checkpoint_id
    if not can_ask(engine):
        # Fight setup starts the first creature's turn before any decision can
        # pause for the table. Leave the scene undeclared instead of recording
        # the fallback as the owner's own decline; the next real turn start asks.
        return
    picked = ask(engine, None,
        checkpoint_id(engine, 'glass_refraction_scene', actor.entity_id), actor, CHOICE, list(ASK_ORDER),
        labels={'Neither': 'Neither: not a qualifying scene — do not offer the choice this turn',
                'Major combat': 'Major combat: let this character choose it this turn',
                'Emotionally decisive scene': 'Emotionally decisive scene: let this character choose it this turn'},
        name='Glass Heart Refraction', feature_id=SOURCE, gm_adjudication=True,
        automatic=False, allow_decline=True, default='decline',
        prompt=f'{actor.display_name} is entering a scene. Owner/GM: is it a major combat or an emotionally '
            'decisive scene? Answering yes only unlocks this character\'s own choice: in their action menu they may '
            'stand in transparent clarity — show their true self instead of hiding behind beauty, denial or '
            'reflection — for a Bonus Action and 2 cultivation points (CP), once per long rest, for 1 minute. This '
            'free private declaration is the owner/GM scene call only.')
    # A decline means the table did not name a qualifying scene: record it as Neither, so the
    # question is asked once rather than at every bearer turn (review finding 2).
    scene = picked[0] if picked and picked[0] in SCENES else 'Neither'
    source = 'Owner/GM declared this scene in play.' if picked else 'Owner/GM declined the scene question.'
    record_fact(engine, _document(engine, actor, scene, source))


@hook('journey_rest')
def long_rest(session, actor_id):
    """Native eight-hour recipient rest restores only this owned use counter.

    The once-per-long-rest limit is the only thing rest resets: the 2 CP spent
    and the 1-minute state are not restored here.
    """
    actor = session.state['actors'][actor_id]
    bundle = actor['bundle']
    maxima = {r['resource_id']: int(r['maximum']) for r in bundle['actor_template']['resources']}
    for action in bundle.get('action_catalog') or []:
        if ((action.get('parameters') or {}).get('typed') or {}).get('source') != SOURCE:
            continue
        rid = 'resource:uses.' + action['source_definition_id']
        if rid in actor['resources'] and rid in maxima:
            actor['resources'][rid] = maxima[rid]
