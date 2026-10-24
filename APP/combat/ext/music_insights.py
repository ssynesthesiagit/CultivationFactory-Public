"""Music Insight combat clauses, owned by hash-gated compiled passive rows.

A fight is one scene; rest/session recovery happens outside a running fight.
Shared owned(engine, actor, feature) is used by music.py to extend the Shared
Measure recipient count from sealed passive ownership. No live authority lookup,
runtime patching, or ability branches in the engine.
"""
from . import hook, note
from .passive_rows import row_of

BLOCK = 'music_insights'
ENSEMBLE = 'insight.ensemble-leader'
RESONANCE = 'insight.legacy-musical-resonance'
UNSHAKEN = 'insight.unshaken-rhythm'
SHARED = 'condition:typed.music_shared_measure'
RESONANCE_USED = '_round_music_resonance_received'
MISS_USED = '_round_music_ensemble_miss'
OPENING_USED = '_round_music_opening_received'


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor else None


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    outcomes = {
        ENSEMBLE: 'Shared Measure reaches one extra willing creature; once per round after an affected creature misses, another may step 5 feet without opportunity attacks.',
        RESONANCE: 'After spending CP on a Music talent, choose one hearing ally within 30 feet to gain Temporary HP equal to your Proficiency Bonus; once per recipient per round.',
        UNSHAKEN: 'Once between Full Cultivation Sessions, turn a failed Music Concentration save into success and optionally use Opening Phrase on yourself without an action.',
    }
    return [{**row, 'kind': row['feature_id'], 'numbers': dict(numbers),
             'choice_owner': 1, 'player_outcome': outcomes[row['feature_id']]}]


@hook('event')
def resonance(engine, event_type, kwargs):
    payload = kwargs.get('payload') or {}
    if event_type != 'RESOURCE_SPENT' or int(payload.get('amount') or 0) <= 0:
        return
    from ..typed_executor import CP_POOLS, cant_hear
    from ..target_knowledge import located
    from ..targeting import line_of_effect
    from .needle import ask, checkpoint_id, CHOICE, ai_controlled
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    row = owned(engine, actor, RESONANCE)
    action = engine.action_catalog.get(kwargs.get('source_definition_id'))
    typed = (action.parameters or {}).get('typed') or {} if action else {}
    if (not row or payload.get('resource_id') not in CP_POOLS
            or not str(typed.get('source') or '').startswith('tianxia.talent.music.')):
        return
    pool = [a for a in engine.state.actors.values() if a.active and a is not actor
            and a.team_id == actor.team_id and not cant_hear(a)
            and engine._distance_actor_to_actor(actor, a) <= 30
            and line_of_effect(engine, actor, target=a)
            and a.turn_flags.get(RESONANCE_USED) != engine.state.round_number
            and (not ai_controlled(engine, actor) or located(engine, actor, a))]
    pool.sort(key=lambda a: (a.temporary_hp, a.entity_id))
    from .choice_prompt import action_context
    picked = ask(engine, getattr(engine, '_active_intent', None),
                 checkpoint_id(engine, 'music_resonance', actor.entity_id), actor,
                 CHOICE + 'music_resonance', [a.entity_id for a in pool],
                 labels={a.entity_id: f'{a.display_name}: gain {row["numbers"]["pb"]} Temporary HP' for a in pool},
                 preferred=[a.entity_id for a in pool[:1]], allow_decline=True,
                 name='Musical Resonance', feature_id=RESONANCE,
                 prompt_context=action_context(engine, actor, action.source_definition_id, actor, action=action),
                 prompt=f'Musical Resonance after {actor.display_name} pays for {action.display_name}: choose one hearing ally within 30 feet. No additional cost. Each ally may benefit once per round.')
    if picked:
        subject = engine.state.actors[picked[0]]
        subject.turn_flags[RESONANCE_USED] = int(engine.state.round_number)
        engine._grant_temp_hp(subject, int(row['numbers']['pb']), RESONANCE, actor.entity_id)


@hook('after_miss')
def ensemble_miss(ctx, target):
    # Native/typed dispatch reaches this only for actual rolled or concealment
    # misses, never a canceled or out-of-range declaration.
    if target is None:
        return
    engine, actor = ctx.engine, ctx.actor
    mark = next((c for c in actor.conditions.values() if c.condition_id == SHARED), None)
    owner = engine.state.actors.get(mark.source_actor_id) if mark else None
    if not owned(engine, owner, ENSEMBLE) or owner.turn_flags.get(MISS_USED) == engine.state.round_number:
        return
    from .rider_choices import pick, step
    from .needle import ai_controlled
    from ..target_knowledge import located
    pool = [a for a in engine.state.actors.values() if a.active and a is not actor
            and any(c.condition_id == SHARED and c.source_actor_id == owner.entity_id for c in a.conditions.values())
            and (not ai_controlled(engine, owner) or (a.team_id == owner.team_id and located(engine, owner, a)))]
    pool.sort(key=lambda a: a.entity_id)
    from .choice_prompt import action_context
    metadata = action_context(engine, actor, ctx.action.source_definition_id, target, action=ctx.action)
    missed = f'{actor.display_name} misses {target.display_name} with {ctx.action.display_name}'
    picked = pick(engine, owner, 'music_ensemble_target', 'Ensemble Leader', [a.entity_id for a in pool],
                  labels={a.entity_id: f'Offer {a.display_name} a 5-foot step without opportunity attacks' for a in pool},
                  subject=actor, trigger=missed, prompt_context=metadata,
                  preferred=[a.entity_id for a in pool[:1]], intent=ctx.intent)
    if picked and step(engine, engine.state.actors[picked[0]], 'music_ensemble_step', 'Ensemble Leader', target,
                       5, ENSEMBLE, ctx.intent, trigger=missed, prompt_context=metadata):
        owner.turn_flags[MISS_USED] = int(engine.state.round_number)
        note(engine, ENSEMBLE, owner, 'Ensemble Leader: another performer steps after the miss.', tuple(picked))


def unshaken_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        row = owned(engine, actor, UNSHAKEN)
        if row:
            yield Holder(actor, UNSHAKEN, row, UNSHAKEN, row['numbers'])


def music_concentration(engine, holder, rc):
    action = engine.action_catalog.get(holder.actor.concentration.source_definition_id) if holder.actor.concentration else None
    typed = (action.parameters or {}).get('typed') or {} if action else {}
    return rc.source_id == 'system:combat.concentration' and typed.get('sphere') == 'tianxia.sphere.music'


def unshaken_phrase(engine, holder, rc, result):
    actor = holder.actor
    if actor.turn_flags.get(OPENING_USED) == engine.state.round_number:
        return
    if not any(c.condition_id == 'condition:typed.music_measure' for c in actor.conditions.values()):
        return
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import Context, run_effects
    actions = [engine.action_catalog[aid] for aid in actor.action_ids if aid in engine.action_catalog
               and (engine.action_catalog[aid].parameters.get('typed') or {}).get('source') == 'MUSIC_BASE_OPENING_PHRASE']
    picked = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'unshaken_phrase', actor.entity_id),
                 actor, CHOICE + 'music_unshaken_phrase', [a.source_definition_id for a in actions],
                 labels={a.source_definition_id: a.display_name for a in actions},
                 name='Unshaken Rhythm: Opening Phrase', feature_id=UNSHAKEN, allow_decline=True,
                 prompt='Your Music Concentration save succeeds. You may use one Opening Phrase benefit on yourself now, without spending an action or Bonus Action. Once per round per recipient.')
    if picked:
        action = engine.action_catalog[picked[0]]
        typed = action.parameters['typed']
        engine._spend_costs(actor, action.costs, action.source_definition_id)
        run_effects(Context(engine, actor, action, getattr(engine, '_active_intent', None), typed, [actor], actor, {}), typed['effects'])
        actor.turn_flags[OPENING_USED] = int(engine.state.round_number)
        actor.turn_flags[f'_round_music_opening:{actor.entity_id}'] = int(engine.state.round_number)


from .d20_rewrite import Rule, register
register(Rule('music_unshaken', 'Unshaken Rhythm', rolls=('save',), when='failed',
              op='choose', choose=lambda engine, holder, rc: rc.natural, outcome='success',
              limit='fight', finder=unshaken_holders, guard=music_concentration,
              ai=lambda engine, holder, rc: True, after=unshaken_phrase))
