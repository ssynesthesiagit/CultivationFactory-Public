"""Newly sealed Flowing River declarations; legacy bundles keep their interpreter.

Use native granted paths for physical steps and native forced paths for Draw
Past. No saved-fight schema or core ability dispatch changes. The shared step helper
is also consumed by flowing_river for newly sealed Response movement: observed
paths, native hazards and exactly one exempted Opportunity Attack source.
"""
from . import effect, hook
from . import needle
from .condition_events import drop_condition
from contextlib import contextmanager
from contextvars import ContextVar

_BANK_SAVE = ContextVar("river_bank_save", default=None)
P = 'TAL_FLOWING_RIVER_'
DECL = 'river_second_pass'
TEN = 'condition:typed.river_ten_thousand'
BETWEEN = 'condition:typed.river_between_steps'
RETALIATE = 'condition:typed.river_between_retaliation'
GUARD = 'condition:typed.river_second_guard'

@effect(DECL)
def declaration(ctx, eff):
    pass  # compiled passive declaration

@hook('compile_actions')
def compile_declarations(info):
    for key in sorted(info['owned_ids']):
        for spec in (info['mechanics'].get(key) or {}).get('effects') or []:
            if spec.get('type') == DECL:
                info['passives'].append({'feature_id': key, 'block': DECL, 'kind': spec['kind'], 'numbers': dict(info['numbers'])})

def owns(engine, actor, kind):
    return any(r.get('block') == DECL and r.get('kind') == kind
               for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, []))

def context(engine, actor, other, kind, name):
    from ..typed_reactions import _generic_context
    row = next(r for r in engine.typed_passive_rows[actor.entity_id] if r.get('block') == DECL and r.get('kind') == kind)
    return _generic_context(engine, actor, other, {**row, 'name': name, 'effects': []}, engine._active_intent)

def step(ctx, mover, other, feet, name, *, trigger=None):
    """Optional native movement exempting only the printed triggering creature."""
    from .granted_moves import destinations, commit
    routes = [r for r in destinations(ctx.engine, mover, feet, lambda cell: True) if r[0] != mover.position]
    if not routes: return
    from ..target_knowledge import can_see
    if can_see(ctx.engine, mover, other):
        routes.sort(key=lambda r: (-ctx.engine.grid.distance_ft(r[0], other.position), r[2], r[0].y, r[0].x))
    else:
        routes.sort(key=lambda r: (r[2], r[0].y, r[0].x))
    trigger = trigger or f'{other.display_name} missed {mover.display_name} with a melee attack.'
    ids = [f'step:{cell.x},{cell.y},{cell.z}' for cell, _, _ in routes]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, name, mover.entity_id, other.entity_id),
        mover, 'choice:needle.river_step', ids, labels={i: f'Move to {r[0].x},{r[0].y} ({r[2]} feet)' for i,r in zip(ids,routes)},
        name=name, allow_decline=True, target_id=mover.entity_id,
        prompt=f'{name}: {trigger} Move up to {feet} feet to a square you choose, without provoking Opportunity Attacks from that creature, or stay.')
    if picked:
        commit(ctx.engine, mover, routes[ids.index(picked[0])][1], ctx.source, budget_ft=feet, provokes=True,
               ignore_oa_from=(other.entity_id,), intent=ctx.intent)


def missed_attack(ctx, target):
    """Use the resolving attack context, including reactions, not the outer intent."""
    return f'{ctx.actor.display_name} missed {target.display_name} with {ctx.action.display_name} (a melee attack).'

@hook('action_completed')
def prepare(engine, actor, economy, source_definition_id):
    action=engine.action_catalog.get(source_definition_id)
    kind=getattr(action,'resolution_kind',None) or {'system:combat.dodge':'DODGE','system:combat.disengage':'DISENGAGE'}.get(source_definition_id)
    if kind == 'DODGE':
        if owns(engine, actor, 'ten_thousand'):
            engine._remove_condition(actor, TEN, P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER')
            engine._apply_condition(actor, TEN, P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER', actor.entity_id,
                expires_on='START_OF_SOURCE_NEXT_TURN', data={'label':'Ten Thousand Edges: first melee hit each round misses'})
        if owns(engine, actor, 'turning_guard'):
            from ..target_knowledge import can_see
            seen = [a for a in engine.state.actors.values() if a.active and a is not actor and can_see(engine, actor, a)]
            engine._remove_condition(actor, GUARD, P+'TURNING_GUARD')
            picked = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine,'river_guard',actor.entity_id),
                actor, 'choice:needle.river_guard', [a.entity_id for a in seen], labels={a.entity_id:a.display_name for a in seen},
                name='Turning Guard', prompt='Turning Guard: choose one creature you can see. Until your next turn starts, each melee miss by it lets you move 5 feet.')
            if picked:
                engine._apply_condition(actor, GUARD, P+'TURNING_GUARD', actor.entity_id,
                    expires_on='START_OF_SOURCE_NEXT_TURN', data={'target':picked[0],'label':f'Turning Guard: {engine.state.actors[picked[0]].display_name} melee misses let you move 5 feet'})
    if kind == 'DISENGAGE' and owns(engine, actor, 'between_steps'):
        engine._remove_condition(actor, BETWEEN, P+'CURRENT_BETWEEN_STEPS')
        engine._apply_condition(actor, BETWEEN, P+'CURRENT_BETWEEN_STEPS', actor.entity_id,
            expires_on='END_OF_CURRENT_TURN', data={'label':'Current Between Steps: choose a creature whose reach you leave'})

@hook('event')
def leave_reach(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED' or (kwargs.get('payload') or {}).get('forced'): return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or not any(c.condition_id == BETWEEN for c in actor.conditions.values()): return
    from ..gate2_runtime_models import Position
    from ..typed_reactions import physical_melee_reach
    from ..target_knowledge import can_see
    path = [Position(**p) for p in (kwargs.get('payload') or {}).get('path') or []]
    if len(path)<2: return
    seen=[]
    for other in engine.state.actors.values():
        if other is actor or not other.active or not can_see(engine, actor, other): continue
        reach=int(physical_melee_reach(engine,other) or 5)
        if any(engine._distance_actor_to_actor(actor.model_copy(update={'position':a}),other)<=reach
               and engine._distance_actor_to_actor(actor.model_copy(update={'position':b}),other)>reach for a,b in zip(path,path[1:])):
            seen.append(other)
    picked=needle.ask(engine,engine._active_intent,needle.checkpoint_id(engine,'river_leave',actor.entity_id),
        actor,'choice:needle.river_leave',[a.entity_id for a in seen], labels={a.entity_id:a.display_name for a in seen},
        name='Current Between Steps', allow_decline=True,
        prompt='Current Between Steps: choose one creature whose reach you just left. Its next melee attack against you has Disadvantage until your next turn starts.')
    if picked:
        engine._remove_condition(actor,BETWEEN,P+'CURRENT_BETWEEN_STEPS')
        target=engine.state.actors[picked[0]]
        engine._apply_condition(target,RETALIATE,P+'CURRENT_BETWEEN_STEPS',actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN',data={'target':actor.entity_id,'label':f'Current Between Steps: next melee attack against {actor.display_name} has Disadvantage'})

@hook('hit_response')
def first_hit_misses(engine, attacker, target, spec, total, natural, effective_ac):
    if not any(c.condition_id==TEN for c in target.conditions.values()): return
    from .attack_scope import current
    frame=current(engine)
    if spec.get('range_ft') is not None or (frame and frame['effect'].get('attack_kind')=='ranged'): return
    key=f'river_ten_used_round_{engine.state.round_number}'
    if target.turn_flags.get(key): return
    target.turn_flags[key]=True
    if frame:
        frame['context'].damage_cache[('river_ten',frame['roll_id'])]=target.entity_id
    else:
        engine.__dict__.setdefault('_river_ten_native',set()).add((attacker.entity_id,target.entity_id))
    needle.say(engine,P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER',target,'Ten Thousand Edges Find No Center: the first melee hit this round misses instead.',(attacker.entity_id,))
    from ..attack_outcomes import unconditional_miss
    return unconditional_miss()

@hook('attack_mode')
def next_attack(ctx,target):
    if not melee(ctx): return
    held=next((c for c in ctx.actor.conditions.values() if c.condition_id==RETALIATE and c.data.get('target')==target.entity_id),None)
    if held:
        drop_condition(ctx.engine,ctx.actor,held.instance_id,P+'CURRENT_BETWEEN_STEPS')
        ctx.damage_cache[('river_between',target.entity_id)]=True
        return 'DISADVANTAGE'

@hook('attack_result')
def after_attack(ctx,target,hit,critical):
    between=ctx.damage_cache.pop(('river_between',target.entity_id),False)
    if hit or not melee(ctx): return
    regain_reed(ctx.engine,target)
    roll=(ctx.attack_result or {}).get('roll_id')
    if ctx.damage_cache.pop(('river_ten',roll),None)==target.entity_id:
        step(context(ctx.engine,target,ctx.actor,'ten_thousand','Ten Thousand Edges Find No Center'),target,ctx.actor,5,'Ten Thousand Edges Find No Center',trigger=missed_attack(ctx,target))
    if between:
        step(context(ctx.engine,target,ctx.actor,'between_steps','Current Between Steps'),target,ctx.actor,5,'Current Between Steps',trigger=missed_attack(ctx,target))
    guard=next((c for c in target.conditions.values() if c.condition_id==GUARD and c.data.get('target')==ctx.actor.entity_id),None)
    if guard: step(context(ctx.engine,target,ctx.actor,'turning_guard','Turning Guard'),target,ctx.actor,5,'Turning Guard',trigger=missed_attack(ctx,target))

@effect('river_draw_past')
def draw_past(ctx,eff):
    """Choose a visible adjacent destination along an unoccupied physical path."""
    from .teleport_steps import destination_allowed
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve
    engine,target=ctx.engine,ctx.target
    if target is None: return
    feet=int(eff['distance_ft']); routes={}
    # Choice queries use the controller's observed occupancy. Native execution
    # still checks actual bodies and records unseen contact, without menu leaks.
    occupied=engine._occupied_cells_except(ctx.actor.entity_id,observed=True) | set(engine._actor_cells(ctx.actor))
    occupied-=set(engine._actor_cells(target))
    volumes=engine._occupied_volumes_except(ctx.actor.entity_id,observed=True) | set(engine._actor_volume(ctx.actor))
    volumes-=set(engine._actor_volume(target))
    radius=feet//engine.grid.square_size_ft
    cells=[Position(x=x,y=y,z=target.position.z)
           for y in range(max(0,target.position.y-radius),min(engine.grid.height,target.position.y+radius+1))
           for x in range(max(0,target.position.x-radius),min(engine.grid.width,target.position.x+radius+1))]
    for cell in cells:
        if not destination_allowed(engine,target,cell,feet,viewer=ctx.actor,occupied_cells=occupied): continue
        if engine._distance_actor_to_actor(ctx.actor,target.model_copy(update={'position':cell}))>5: continue
        if engine.grid.volume_step_legal(target.position,cell,occupied_cells=volumes,footprint=engine._footprint(target)):
            routes[needle.cell_id(cell)]=(target.position,cell)
    picked=needle.ask(engine,ctx.intent,needle.checkpoint_id(engine,'river_draw',target.entity_id),ctx.actor,
        'choice:needle.river_draw',sorted(routes),labels={k:f'Move {target.display_name} to {k[5:]}' for k in routes},
        name='Draw Past',allow_decline=True,target_id=target.entity_id,
        prompt=f'Draw Past: choose a legal square adjacent to you within 5 feet of {target.display_name}. The movement does not provoke Opportunity Attacks.')
    if picked:
        resolve(engine,target,routes[picked[0]],P+'DRAW_PAST',kind='forced',feet=feet,intent=ctx.intent,source_actor_id=ctx.actor.entity_id,ctx=ctx)

@hook('evasion')
def empty_bank(ctx,subject,ability,failed,fail_effects):
    if str(ability).upper()[:3]!='DEX' or not owns(ctx.engine,subject,'empty_bank') or needle.focus(subject)<1: return
    from ..target_knowledge import can_see
    if not can_see(ctx.engine,subject,ctx.actor): return
    frame = _BANK_SAVE.get()
    if frame is None or frame['engine'] is not ctx.engine: return
    from .choice_costs import Payment
    payment=Payment(needle.FOCUS,1)
    picked=needle.ask(ctx.engine,ctx.intent,needle.checkpoint_id(ctx.engine,'river_bank',subject.entity_id),subject,
        'choice:needle.river_bank',['evade'],labels={'evade':'Expend Martial Focus: no damage on success, half damage on failure'},
        name='Empty Bank Evasion',allow_decline=True,payment=payment,
        prompt=f"Empty Bank Evasion: expend Martial Focus for {subject.display_name}'s Dexterity save against {ctx.actor.display_name}'s {ctx.action.display_name}? On success take no damage and optionally move 10 feet; on failure take half damage. Other effects still apply.")
    if not picked: return
    payment.pay(ctx.engine,subject,P+'EMPTY_BANK_EVASION')
    needle.say(ctx.engine,P+'EMPTY_BANK_EVASION',subject,'Empty Bank Evasion: Martial Focus expended; only this effect’s damage is changed.')
    if not failed:
        frame['steps'].append((subject.entity_id, ctx.actor.entity_id))
    return True

@hook('effect_resolution_scope')
def bank_save_scope(ctx, effect):
    """Finish each typed block, including saves called by custom effect blocks."""
    if any(owns(ctx.engine, a, 'empty_bank') for a in ctx.engine.state.actors.values()):
        return finish_bank_save(ctx)


@contextmanager
def finish_bank_save(ctx):
    frame = {'engine': ctx.engine, 'steps': []}
    token = _BANK_SAVE.set(frame)
    try:
        yield
        # Reach this point only after every branch effect has settled. A player
        # pause/error unwinds without draining; the service replays the intent.
        for who, other in frame['steps']:
            subject = ctx.engine.state.actors[who]
            source = ctx.engine.state.actors[other]
            step(context(ctx.engine, subject, source, 'empty_bank', 'Empty Bank Evasion'),
                 subject, source, 10, 'Empty Bank Evasion',
                 trigger=f"{subject.display_name} made a successful Dexterity save against {source.display_name}'s {ctx.action.display_name}.")
    finally:
        _BANK_SAVE.reset(token)


@hook('before_attack')
def native_next_attack(engine,attacker,target,intent,trigger):
    from .attack_scope import current
    if current(engine) is not None: return  # typed attack_mode owns that path
    action=trigger.get('action') or engine.action_catalog.get(trigger.get('source_id'))
    if action is None or action.reach_ft is None: return
    held=next((c for c in attacker.conditions.values() if c.condition_id==RETALIATE and c.data.get('target')==target.entity_id),None)
    if held:
        drop_condition(engine,attacker,held.instance_id,P+'CURRENT_BETWEEN_STEPS')
        engine.__dict__.setdefault('_river_between_native',set()).add((attacker.entity_id,target.entity_id))
        return {'mode':'DISADVANTAGE'}


@hook('after_miss')
def native_miss(ctx,target):
    notice=getattr(ctx,'attack_notice',None)
    if notice is None or not notice.melee: return
    regain_reed(ctx.engine,target)
    pair=(ctx.actor.entity_id,target.entity_id)
    for attr,kind,name in [('_river_ten_native','ten_thousand','Ten Thousand Edges Find No Center'),
                           ('_river_between_native','between_steps','Current Between Steps')]:
        pending=ctx.engine.__dict__.get(attr,set())
        if pair in pending:
            pending.remove(pair)
            step(context(ctx.engine,target,ctx.actor,kind,name),target,ctx.actor,5,name,trigger=missed_attack(ctx,target))
    guard=next((c for c in target.conditions.values() if c.condition_id==GUARD and c.data.get('target')==ctx.actor.entity_id),None)
    if guard: step(context(ctx.engine,target,ctx.actor,'turning_guard','Turning Guard'),target,ctx.actor,5,'Turning Guard',trigger=missed_attack(ctx,target))


@hook('after_hit')
def native_hit_cleanup(ctx,target,kind):
    if getattr(ctx,'attack_notice',None) is not None:
        ctx.engine.__dict__.get('_river_between_native',set()).discard((ctx.actor.entity_id,target.entity_id))



def melee(ctx):
    notice=getattr(ctx,'attack_notice',None)
    if notice is not None: return notice.melee
    return ctx.typed.get('range_ft') is None and (ctx.attack_effect or {}).get('attack_kind')!='ranged'


def regain_reed(engine,actor):
    if owns(engine,actor,'reed_in_storm') and any(c.condition_id=='condition:core.dodge' for c in actor.conditions.values()):
        needle.regain_focus(engine,actor,P+'REED_IN_STORM','Reed in Storm: a melee attack missed while you were Dodging')
