"""Draw's physical lines and Listen's private source-qualified information.

Reuses Thread's canonical creature mark, the public object_marks contract,
material_ledger inventory and Mason's Anchor identities. Lines are produced only
by actual hits. Movement knowledge comes from committed landed movement; handling
is an explicit target declaration, never inferred from allegiance or damage.
"""
from copy import deepcopy
from . import hook,effect
from .ability_source import mechanic_of
DRAW='THREAD_BASE_DRAW_THE_LINE';LISTEN='THREAD_BASE_LISTEN_THROUGH_TENSION'
GUIDE='condition:typed.thread_guide'; LISTENING='condition:typed.thread_listen'
CHECKS={'Insight':'WIS','Perception':'WIS','Sleight of Hand':'DEX'}


def line_rows(engine,owner):
    from .thread_common import mark_condition_id
    cid=mark_condition_id(owner.entity_id,'Thread Line');out=[]
    for target in engine.state.actors.values():
        for c in target.conditions.values():
            if c.condition_id==cid:out.append((target.entity_id,target,c))
    from .object_marks import KEY
    for obj in engine.state.objects.values():
        for r in (obj.component or {}).get(KEY,[]):
            if not obj.destroyed and r['owner_id']==owner.entity_id and r['name']=='Thread Line':
                c=owner.conditions.get(r['instance_id'])
                if c:out.append((obj.object_id,obj,c))
    return out


def stock(engine,actor):
    from .material_ledger import combat_materials
    return [r for r in combat_materials(engine,actor) if r['quantity']>0 and r['kind']=='thread_tool' and r.get('material') in ('thread','silk','wire','cord','needles')]


@hook('journey_combat_setup')
def carry_stock(bundle,session,aid):
    from . import material_ledger as ledger
    rows=[deepcopy(r) for r in ledger.holdings(session,aid).values() if r['quantity']>0 and r['kind']=='thread_tool'
          and ledger.sources(session).get(r['source_id'],{}).get('material') in ('thread','silk','wire','cord','needles')]
    return {**bundle,'thread_materials':rows} if rows else None


@hook('compile_action')
def compile_draw(action,info):
    source=mechanic_of(action)
    if source==LISTEN and LISTEN in info['owned_ids'] and not any(r.get('type')=='source_check' for r in action.parameters.get('typed',{}).get('effects',[])):
        t=deepcopy(action.parameters['typed']);t.update(effects=[{'type':'thread_listen'}],riders=[])
        return action.model_copy(update={'target_kind':'SELF','parameters':{**action.parameters,'typed':t}})
    if source!=DRAW or DRAW not in info['owned_ids']:return None
    t=deepcopy(action.parameters['typed']);t['riders']=[]
    def adjust(rows):
        for row in rows:
            if row.get('type')=='attack':
                row.update(object_target='any',object_on_hit_effects=['thread_object_line','thread_object_effect'],object_before_effects=['thread_prepare'])
                if t.get('option_label')=='Guide':row['on_hit'].append({'type':'thread_guide','applies_to':'target'})
                row['on_hit'].extend([{'type':'thread_object_line'},{'type':'thread_object_effect'}])
                for sub in row['on_hit']:
                    if sub.get('type')=='speed':sub['duration']='until_start_of_your_next_turn'
                    if sub.get('type')=='save' and sub.get('ability')=='str' and sub.get('min_size_larger')==1:sub['advantage_if_larger']=1
                    if sub.get('type')=='save' and sub.get('ability')=='str' and any(x.get('condition')=='disarmed' for x in sub.get('on_fail',[])):
                        sub['on_fail']=[{'type':'thread_disarm'}]
            for key in ('effects','on_hit','on_fail','on_success'):adjust(row.get(key,[]))
    adjust(t['effects']);t['effects'].insert(0,{'type':'thread_prepare'})
    return action.model_copy(update={'target_kind':'ANY_CREATURE','parameters':{**action.parameters,'typed':t,'replaces_attack':1}})


@hook('compile_actions')
def extra_actions(info):
    from .source_checks import check_action
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    out=[]
    if LISTEN in info['owned_ids']:
        out.append(check_action(info,LISTEN,'Listen: make a check involving the line',CHECKS,
            {'line':'A check involving the connected Thread Line','other':'An unrelated check'}))
    # Response actions are default-inert unless a real line connects the actor.
    # Player-only avoids inventing AI handling facts.
    for stance in ('holding','ignoring'):
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.thread.response.{stance}",display_name='Thread Line: '+stance,
            owner_id=info['actor_id'],economy=EconomyKind.NONE,
            resolution_kind='TYPED',target_kind='SELF',parameters={'player_only':True,'thread_response':stance,
                'description':'Hold a real connected line with a free hand, or release it and ignore it. To cut a line, attack its actual object with a weapon; its printed Armor Class and Hit Points determine whether it breaks.',
                'typed':{'effects':[{'type':'thread_response','stance':stance}],'numbers':dict(info['numbers']),'riders':[]}}))
    return out


@hook('candidate_allowed')
def line_gate(engine,actor,candidate,action):
    if action is None:return None
    if action.parameters.get('thread_response'):
        return None if any(line_rows(engine,owner) and any(tid==actor.entity_id for tid,_,_ in line_rows(engine,owner)) for owner in engine.state.actors.values()) else False
    source=mechanic_of(action)
    if source==LISTEN:return None if line_rows(engine,actor) else False
    if source!=DRAW:return None
    extra=action.parameters.get('thread_twin') or {}
    if not extra and not stock(engine,actor):return False
    return None


@hook('effect_origins')
def controlled_anchors(engine,actor,action):
    if mechanic_of(action)!=DRAW:return None
    from ..asset_anchor_runtime import anchors
    from ..target_knowledge import can_see
    # Controlled, live native Anchors only; ownership is persisted by the producer.
    return [{'id':obj.object_id,'label':'Your '+str((obj.component or {}).get('name') or 'Anchor'),'position':obj.position.model_dump(mode='json')}
        for obj in anchors(engine,actor.entity_id)]


@effect('thread_prepare',harmful=False)
def prepare(ctx,row):
    from .needle import ask,checkpoint_id
    extra=ctx.action.parameters.get('thread_twin') or {}
    if extra.get('qi'):
        ctx.damage_cache['thread_medium']='qi'
    else:
        materials=stock(ctx.engine,ctx.actor)
        if not materials:raise ValueError('Draw the Line needs your actual mundane thread stock or its paid Qi Thread option.')
        picks=[materials[0]['id']] if len(materials)==1 else ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_stock',ctx.source),ctx.actor,
            'choice:needle.thread_stock',[r['id'] for r in materials],labels={r['id']:r['name'] for r in materials},allow_decline=True,
            prompt='Draw the Line: choose your actual thread stock, or use your ordinary kit. No CP; merely using stock does not destroy it.',name='Draw the Line')
        if not picks:picks=[next((r['id'] for r in materials if r.get('source')==DRAW),materials[0]['id'])]
        ctx.damage_cache['thread_medium']='mundane';ctx.damage_cache['thread_stock']=picks[0]
    appearance=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_visibility',ctx.source),ctx.actor,
        'choice:needle.thread_visibility',['visible','hidden'],labels={'visible':'Visible Thread Line','hidden':'Concealed mundane thread or invisible Qi Thread'},
        name='Draw the Line',prompt='Conceal this Thread Line, or leave it visible. No extra CP or action; declining leaves it visible.',preferred=['visible'],allow_decline=True)
    ctx.damage_cache['thread_visible']=0 if appearance==['hidden'] else 1
    from ..action_geometry import record_for
    record=record_for(ctx.engine,ctx.actor)
    ctx.damage_cache['thread_anchor']=record['id'] if record else ctx.actor.entity_id


@hook('mark_applied')
def line_provenance(ctx,name,subject):
    if name!='Thread Line' or mechanic_of(ctx.action)!=DRAW:return
    from .thread_common import mark_condition_id
    for c in subject.conditions.values():
        if c.condition_id==mark_condition_id(ctx.actor.entity_id,name):
            ctx.engine._update_condition_data(subject,c,{**c.data,'thread_medium':ctx.damage_cache.get('thread_medium',''),
                'thread_anchor':ctx.damage_cache.get('thread_anchor',ctx.actor.entity_id),'thread_stock':ctx.damage_cache.get('thread_stock',''),
                'thread_motion':'still','thread_handling':'unknown'},ctx.source)
            materialize_line(ctx,subject,c)


@effect('thread_object_line',harmful=False)
def object_line(ctx,row):
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    if obj is None:return
    from .object_marks import add
    from ..typed_executor import mark_capacity
    add(ctx,obj,'Thread Line',mark_capacity(ctx,'Thread Line'),data={'thread_medium':ctx.damage_cache.get('thread_medium',''),'thread_anchor':ctx.damage_cache.get('thread_anchor',ctx.actor.entity_id),'thread_motion':'still','thread_handling':'unknown'})
    mark=next((c for c in ctx.actor.conditions.values() if c.data.get('object_mark_name')=='Thread Line' and c.data.get('object_id')==obj.object_id),None)
    if mark:materialize_line(ctx,obj,mark)


@effect('thread_guide',harmful=False)
def guide(ctx,row):
    target=ctx.target
    if target is None:return
    ctx.engine._apply_condition(ctx.actor,GUIDE,ctx.source,ctx.actor.entity_id,expires_on='END_OF_MARKER_NEXT_TURN',
        data={'target':target.entity_id,'marker_turn':ctx.actor.turns_started,'label':'Guide: next attack against this target ignores half cover'})


@hook('cover_reduction')
def guide_cover(engine,actor,target,cover):
    if cover!=2:return None
    return 1 if any(c.condition_id==GUIDE and c.data.get('target')==target.entity_id for c in actor.conditions.values()) else None


@hook('state_event')
def guide_spent(engine,event):
    if event.event_type!='ATTACK_ROLLED':return
    from .condition_ownership import remove_instance
    actor=engine.state.actors.get(event.actor_id)
    if actor:
        for iid,c in list(actor.conditions.items()):
            if c.condition_id==GUIDE and c.data.get('target') in event.target_ids:remove_instance(engine,actor,iid,c.source_definition_id)


@effect('thread_disarm')
def disarm(ctx,row):
    from .. import carry
    from .needle import ask,checkpoint_id
    target=ctx.target
    if target is None:return
    from .hand_occupancy import weapon_grips,occupancy
    grips=weapon_grips(ctx.engine,target)
    held={value for values in occupancy(ctx.engine,target,grips=grips).values() for value in values}
    items=[r for r in (carry.carrying_of(ctx.engine,target.entity_id) or {}).get('items',[]) if carry.holds(ctx.engine,target,r['key']) and (r.get('weapon_action') in grips or 'shield:'+r['key'] in held or str(carry.owned_item_location(target,r['key']) or '').startswith('hand:'))]
    if not items:return
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_disarm',target.entity_id),ctx.actor,
        'choice:needle.thread_disarm',[r['key'] for r in items],labels={r['key']:r.get('name','Held object') for r in items},
        name='Draw the Line: Disarm',prompt='Choose the held object the target drops into its space after its failed Strength save.')
    if selected:
        item=next(r for r in items if r['key']==selected[0])
        ctx.engine._apply_condition(target,carry.DROPPED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'item_key':item['key'],'disables_action':item.get('weapon_action',''),'dropped_at':target.position.model_dump(mode='json'),'label':'Disarmed: object dropped in its space'})


@effect('thread_listen',harmful=False)
def listen(ctx,row):
    from .needle import ask,checkpoint_id
    lines=line_rows(ctx.engine,ctx.actor)
    if not lines:raise ValueError('Listen Through Tension requires one active Thread Line you maintain.')
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_listen_line',ctx.source),ctx.actor,
        'choice:needle.thread_listen_line',[tid for tid,_,_ in lines],labels={tid:getattr(t,'display_name',None) or 'Connected object' for tid,t,_ in lines},
        name='Listen Through Tension',prompt='Choose one active Thread Line you maintain. Bonus Action; no CP.')
    if not picked:return
    benefit=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_listen_benefit',ctx.source),ctx.actor,
        'choice:needle.thread_listen_benefit',['motion','handling','check','space'],
        labels={'motion':'Know closer, farther or still','handling':'Know holding, cutting or ignoring the line','check':'Advantage on one qualifying check','space':'Know a connected Invisible target’s space; this does not grant sight'},
        name='Listen Through Tension',prompt='Choose one benefit for this connected line, until the end of your next turn (space knowledge lasts until the line ends).')
    if not benefit:return
    tid,target,c=next(r for r in lines if r[0]==picked[0])
    ctx.engine._apply_condition(ctx.actor,LISTENING,ctx.source,ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED' if benefit[0]=='space' else 'END_OF_MARKER_NEXT_TURN',
        data={'line_id':c.instance_id,'subject':tid,'benefit':benefit[0],'marker_turn':ctx.actor.turns_started,
            'label':'Listen Through Tension: '+benefit[0]})


@hook('source_check_subjects')
def line_check_subjects(ctx,row):
    if mechanic_of(ctx.action)!=LISTEN:return None
    return [tid for tid,_,_ in line_rows(ctx.engine,ctx.actor)]


@hook('source_check_mode')
def listen_check(engine,actor,ability,skill,against):
    from .source_checks import current
    frame=current(engine,actor)
    if not frame or frame['purpose']!='line' or CHECKS.get(skill)!=ability:return None
    ids={c.instance_id for _,_,c in line_rows(engine,actor)}
    return 'ADVANTAGE' if any(c.condition_id==LISTENING and c.data.get('benefit')=='check' and c.data.get('subject')==frame['subject'] and c.data.get('line_id') in ids for c in actor.conditions.values()) else None


@hook('state_event')
def listen_lifecycle(engine,event):
    from .condition_ownership import remove_instance
    from .source_checks import current
    for owner in engine.state.actors.values():
        ids={c.instance_id for _,_,c in line_rows(engine,owner)}
        frame=current(engine,owner)
        for iid,c in list(owner.conditions.items()):
            if c.condition_id!=LISTENING:continue
            used=(event.event_type=='CHECK_ROLLED' and event.actor_id==owner.entity_id and frame
                  and frame['purpose']=='line' and frame['subject']==c.data.get('subject') and frame['skill'] in CHECKS and c.data.get('benefit')=='check')
            if c.data.get('line_id') not in ids or used:remove_instance(engine,owner,iid,c.source_definition_id)


@hook('pinpoint_target')
def listen_space(engine,viewer,target):
    ids={c.instance_id for tid,_,c in line_rows(engine,viewer) if tid==target.entity_id}
    return True if ids and any(c.condition_id==LISTENING and c.data.get('benefit')=='space' and c.data.get('line_id') in ids for c in viewer.conditions.values()) else None


@effect('thread_response',harmful=False)
def response(ctx,row):
    from .needle import ask,checkpoint_id
    found=[(owner,c) for owner in ctx.engine.state.actors.values() for tid,_,c in line_rows(ctx.engine,owner) if tid==ctx.actor.entity_id]
    choices={c.instance_id:(owner,c) for owner,c in found}
    if not choices:return
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'thread_response',ctx.source),ctx.actor,
        'choice:needle.thread_response',list(choices),labels={iid:'Line maintained by '+owner.display_name for iid,(owner,c) in choices.items()},
        name='Thread Line',prompt='Which connected line are you holding, attempting to cut, or ignoring?',automatic_options=[])
    if selected:
        owner,c=choices[selected[0]]
        from .condition_ownership import remove_instance
        for iid,held in list(ctx.actor.conditions.items()):
            if held.condition_id=='condition:typed.thread_holding' and held.data.get('line_id')==c.instance_id:
                remove_instance(ctx.engine,ctx.actor,iid,ctx.source)
        if row['stance']=='holding':
            from .hand_occupancy import free_hands
            hands=free_hands(ctx.engine,ctx.actor)
            if not hands:raise ValueError('Holding this Thread Line requires an actual free hand; stow an item or release another hold first.')
            ctx.engine._apply_condition(ctx.actor,'condition:typed.thread_holding',ctx.source,ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED',data={'line_id':c.instance_id,'hand':hands[0],'label':'Holding a connected Thread Line'})
        ctx.engine._update_condition_data(ctx.actor,c,{**c.data,'thread_handling':row['stance']},ctx.source)


@hook('movement_landed')
def line_motion(engine,mover,previous,destination,intent,forced):
    for owner in engine.state.actors.values():
        for tid,target,c in line_rows(engine,owner):
            if tid!=mover.entity_id:continue
            anchor_id=c.data.get('thread_anchor',owner.entity_id)
            anchor=engine.state.actors.get(anchor_id) or engine.state.objects.get(anchor_id)
            if anchor is None:continue
            before=engine.grid.distance_ft(anchor.position,previous);after=engine.grid.distance_ft(anchor.position,destination)
            engine._update_condition_data(mover,c,{**c.data,'thread_motion':'closer' if after<before else 'farther' if after>before else 'still'},c.source_definition_id)


@hook('observer_information_rows')
def private_line_information(engine,viewer):
    rows=[];lines={c.instance_id:(tid,target,c) for tid,target,c in line_rows(engine,viewer)}
    for grant in viewer.conditions.values():
        if grant.condition_id!=LISTENING or grant.data.get('line_id') not in lines:continue
        tid,target,c=lines[grant.data['line_id']];benefit=grant.data['benefit']
        if benefit not in ('motion','handling','space'):continue
        details={'subject':tid,'line_id':c.instance_id}
        if benefit=='motion':details['motion']=c.data.get('thread_motion','unknown')
        elif benefit=='handling':details['handling']=c.data.get('thread_handling','unknown')
        else:details['position']=target.position.model_dump(mode='json')
        rows.append({'kind':'declaration','viewer_id':viewer.entity_id,'source_id':LISTEN,'details':details})
    return rows or None


@effect('thread_object_effect',harmful=False)
def object_effect(ctx,row):
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    if obj is None:return
    label=ctx.typed.get('option_label')
    if label=='Guide':
        ctx.engine._apply_condition(ctx.actor,GUIDE,ctx.source,ctx.actor.entity_id,expires_on='END_OF_MARKER_NEXT_TURN',
            data={'target':obj.object_id,'marker_turn':ctx.actor.turns_started,'label':'Guide: next attack against this object ignores half cover'})
    if label!='Pull' or not obj.unattended or (obj.component or {}).get('structure'):return
    sizes=('tiny','small','medium','large','huge','gargantuan')
    size=str((obj.component or {}).get('size','')).lower(); own=str(ctx.actor.size_category).lower()
    if size not in sizes or own not in sizes or sizes.index(size)>sizes.index(own):return
    from ..action_geometry import point
    from ..gate2_runtime_models import Position
    anchor=point(ctx.engine,ctx.actor);old=obj.position
    nxt=Position(x=old.x+(1 if anchor.x>old.x else -1 if anchor.x<old.x else 0),y=old.y+(1 if anchor.y>old.y else -1 if anchor.y<old.y else 0),z=old.z)
    if nxt==old or not ctx.engine.grid.step_legal(old,nxt):return
    if ctx.engine._occupied_cells_except('').intersection({(nxt.x,nxt.y)}):return
    if any(not o.destroyed and o.object_id!=obj.object_id and o.position==nxt for o in ctx.engine.state.objects.values()):return
    ctx.engine._update_object(obj.model_copy(update={'position':nxt}),ctx.source,ctx.actor.entity_id)


@hook('source_material_grants')
def ordinary_stock_acquisition(info):
    if DRAW not in info['owned_ids']:return None
    # The source's Thread Stock clause assumes this ordinary kit unless deprived.
    # One unit is the kit itself, not an invented number of feet or uses.
    return [{'source':DRAW,'name':'Ordinary Thread kit','material':'thread','kind':'thread_tool','unit':'kit','quantity':1}]

LINE_OBJECT='thread_line'


def materialize_line(ctx,target,mark):
    """Native line AC/HP are printed in General Thread Rules, not guessed."""
    from ..asset_anchor_runtime import create
    profile={'name':'Thread Line','kind':LINE_OBJECT,'ac':int(ctx.numbers['save_dc']),
        'hp':max(1,int(ctx.numbers['pb'])+int(ctx.numbers['key_mod'])),'source_cl':int(ctx.numbers['cl']),
        'height_ft':1,'group':'thread_lines','shared_space':1,'flammable':ctx.damage_cache.get('thread_medium')=='mundane'}
    component={'anchor':0,'line_instance':mark.instance_id,'line_holder':mark.target_id,'line_owner':ctx.actor.entity_id,
        'thread_anchor':ctx.damage_cache.get('thread_anchor',ctx.actor.entity_id),
        'line_target':getattr(target,'entity_id',None) or target.object_id,
        'thread_medium':ctx.damage_cache.get('thread_medium',''),'thread_visible':ctx.damage_cache.get('thread_visible',1),
        'thread_substantial':1 if ctx.damage_cache.get('thread_medium')=='mundane' else 0,
        'thread_range_ft':30 if ctx.damage_cache.get('thread_medium')=='qi' else 20}
    obj=create(ctx.engine,ctx.actor,ctx.source,profile,target.position,component=component)
    holder=ctx.engine.state.actors[mark.target_id]
    ctx.engine._update_condition_data(holder,mark,{**mark.data,'line_object_id':obj.object_id},ctx.source)


@hook('object_target_cells')
def line_cells(engine,obj):
    if obj.object_kind!=LINE_OBJECT:return None
    data=obj.component or {};anchor=engine.state.actors.get(data.get('thread_anchor')) or engine.state.objects.get(data.get('thread_anchor'))
    target=engine.state.actors.get(data.get('line_target')) or engine.state.objects.get(data.get('line_target'))
    if anchor is None or target is None:return (obj.position,)
    from ..gate2_runtime_models import Position
    return tuple(Position(x=x,y=y,z=z) for x,y,z in engine.grid.effect_ray_cells(anchor.position,target.position))


@hook('object_perception_required')
def line_projection(engine):
    return True if any(o.object_kind==LINE_OBJECT and not o.destroyed for o in engine.state.objects.values()) else None


@hook('object_perception_allowed')
def line_visibility(engine,viewer,obj):
    if obj.object_kind!=LINE_OBJECT:return None
    data=obj.component or {}
    if data.get('thread_visible')==1:return None
    if data.get('thread_medium')!='qi' and (data.get('line_owner')==viewer.entity_id or any(c.condition_id=='condition:typed.detected_thread' and c.data.get('line_id')==obj.object_id for c in viewer.conditions.values())):return None
    if data.get('thread_medium')=='qi':
        from ..senses import of
        sense=of(engine,viewer).get('spiritual_sense')
        if sense and any(engine.grid.distance_ft(viewer.position,cell)<=int(sense['range_ft']) and engine.grid.line_of_sight(viewer.position,cell) for cell in line_cells(engine,obj)):return None
    return False


@hook('after_search')
def find_hidden_lines(ctx,effect):
    from ..senses import perceives_cell
    from ..typed_executor import check_modes
    from .ability_source import combine_modes
    for obj in list(ctx.engine.state.objects.values()):
        if obj.destroyed or obj.object_kind!=LINE_OBJECT or line_visibility(ctx.engine,ctx.actor,obj) is not False:continue
        if not any(perceives_cell(ctx.engine,ctx.actor,cell) for cell in line_cells(ctx.engine,obj)):continue
        # A real Search attempts perception of a real hidden physical source.
        modes=check_modes(ctx.actor,'WIS','Perception',engine=ctx.engine)
        with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'source_id':ctx.source,'skill':'Perception','ability':'WIS','target_id':obj.object_id,'dc':obj.ac}):
            roll=ctx.engine.roller.d20(modifier=int(effect.get('bonus') or 0),actor_id=ctx.actor.entity_id,reason='CHECK:'+ctx.source,mode=combine_modes(modes))
        ctx.engine._record_roll(roll)
        ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(obj.object_id,),
            payload={'actor':roll.model_dump(mode='json'),'skill':'Perception','dc':obj.ac,'success':roll.total>=obj.ac})
        if roll.total>=obj.ac:
            ctx.engine._apply_condition(ctx.actor,'condition:typed.detected_thread',ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'line_id':obj.object_id,'label':'Detected a hidden Thread Line'})


@hook('candidate_allowed')
def can_attack_line(engine,actor,candidate,action):
    if action is None:return None
    objects=[engine.state.objects.get(tid) for tid in candidate.target_ids]
    for obj in objects:
        if obj is None or obj.object_kind!=LINE_OBJECT:continue
        known=(obj.component.get('line_owner')==actor.entity_id or any(c.condition_id=='condition:typed.detected_thread' and c.data.get('line_id')==obj.object_id for c in actor.conditions.values()))
        if not known and line_visibility(engine,actor,obj) is False:return False
        if obj.component.get('thread_medium')=='qi' and not obj.component.get('thread_substantial'):
            from .action_source_facts import profile
            if profile(engine,actor,action).get('thread_severing')!=1:return False
    return None


@hook('object_damage_admission')
def severance_gate(engine,actor,obj,packets,source,*,area_scope_resolved=False):
    if obj.object_kind!=LINE_OBJECT:return None
    if obj.component.get('thread_medium')!='qi' or (obj.component.get('thread_visible') and obj.component.get('thread_substantial')):return None
    from .action_source_facts import profile
    return profile(engine,actor,engine.action_catalog.get(source)).get('thread_severing')==1


@hook('state_event')
def line_object_lifecycle(engine,event):
    if event.event_type not in ('OBJECT_UPDATED','CONDITION_REMOVED'):return
    from .condition_ownership import remove_instance
    from ..asset_anchor_runtime import retire
    for obj in list(engine.state.objects.values()):
        if obj.object_kind!=LINE_OBJECT:continue
        data=obj.component;holder=engine.state.actors.get(data.get('line_holder'))
        mark=holder.conditions.get(data.get('line_instance')) if holder else None
        anchor=engine.state.actors.get(data.get('thread_anchor')) or engine.state.objects.get(data.get('thread_anchor'))
        target=engine.state.actors.get(data.get('line_target')) or engine.state.objects.get(data.get('line_target'))
        broken=anchor is None or getattr(anchor,'destroyed',False) or target is None or getattr(target,'destroyed',False)
        if mark and (obj.destroyed or broken):remove_instance(engine,holder,mark.instance_id,obj.component['created_by']);mark=None
        if mark is None and not obj.destroyed:retire(engine,obj,obj.component['created_by'])


@hook('hand_occupants')
def line_hands(engine,actor):
    return {c.data['hand']:'thread:'+c.instance_id for c in actor.conditions.values()
        if c.condition_id=='condition:typed.thread_holding'} or None


@hook('state_event')
def physical_handling(engine,event):
    from .condition_ownership import remove_instance
    if event.event_type=='ATTACK_ROLLED':
        for tid in event.target_ids:
            obj=engine.state.objects.get(tid)
            if obj is None or obj.object_kind!=LINE_OBJECT or obj.component.get('line_target')!=event.actor_id:continue
            holder=engine.state.actors.get(obj.component.get('line_holder'))
            mark=holder.conditions.get(obj.component.get('line_instance')) if holder else None
            if mark:engine._update_condition_data(holder,mark,{**mark.data,'thread_handling':'cutting'},event.source_definition_id)
    if event.event_type!='CONDITION_REMOVED':return
    live_ids={c.instance_id for owner in engine.state.actors.values() for _,_,c in line_rows(engine,owner)}
    for actor in engine.state.actors.values():
        for iid,c in list(actor.conditions.items()):
            if c.condition_id=='condition:typed.thread_holding' and c.data.get('line_id') not in live_ids:
                remove_instance(engine,actor,iid,c.source_definition_id)


@hook('object_attack_mode')
def unseen_line_attack(ctx,obj):
    if obj.object_kind!=LINE_OBJECT:return None
    from ..senses import perceives_object
    return 'DISADVANTAGE' if not perceives_object(ctx.engine,ctx.actor,obj) else None


@hook('compile_actions')
def thread_weapon_modes(info):
    """Potential weapon modes retain actual item numbers and live eligibility.

    Eligibility is an explicit native world fact for this exact acquired item,
    since the source defines eligible delivery but no universal weapon list.
    The caster chooses the mode by its ordinary action button when using Draw.
    """
    if DRAW not in info['owned_ids']:return None
    from ..weapon_delivery import weapon_variant_base
    rows=[]
    weapons=[a for a in info['actions'] if a.parameters.get('typed',{}).get('weapon')
        and not weapon_variant_base(a.parameters) and not a.parameters.get('thread_weapon_source')]
    draws=[a for a in info['actions'] if mechanic_of(a)==DRAW and not a.parameters.get('thread_weapon_source')]
    for draw in draws:
        for weapon in weapons:
            wt=weapon.parameters.get('typed',{})
            attack=next((r for r in wt.get('effects',[]) if r.get('type')=='attack' and str(r.get('attack_kind','')).startswith('weapon')),None)
            if attack is None:continue
            kind=attack['attack_kind'];modes=('needle','thrown') if kind=='weapon_ranged' else ('melee',)
            for mode in modes:
                t=deepcopy(draw.parameters['typed']);t['weapon']=deepcopy(wt['weapon'])
                t['numbers']['attack_bonus']=int(wt['numbers']['attack_bonus'])
                t['weapon_source_id']=weapon.source_definition_id
                for effect_row in t.get('effects',[]):
                    if effect_row.get('type')=='attack':effect_row['attack_kind']=kind
                maximum=min(draw.range_ft or 20,weapon.range_ft or 5)
                t['range_ft']=maximum
                rows.append(draw.model_copy(update={'source_definition_id':draw.source_definition_id+'.weapon.'+str(len(rows)),
                    'display_name':draw.display_name+' — '+weapon.display_name+' ('+mode+')',
                    'range_ft':maximum,'parameters':{**draw.parameters,'typed':t,
                        'thread_weapon_source':weapon.source_definition_id,'thread_weapon_mode':mode,
                        'weapon_variant_of':weapon.source_definition_id}}))
    return rows or None


@hook('candidate_allowed')
def eligible_thread_weapon(engine,actor,candidate,action):
    source=(action.parameters or {}).get('thread_weapon_source') if action else None
    if not source:return None
    from .action_source_facts import profile
    from ..weapon_delivery import ready_weapons
    if source not in ready_weapons(engine,actor):return False
    fact=profile(engine,actor,engine.action_catalog.get(source))
    return None if fact.get('thread_mode')==action.parameters['thread_weapon_mode'] else False


@hook('fact_admission_schema')
def anchor_control_schema(session,source,subject,kind):
    if source!=DRAW or kind!='anchor_control':return None
    from .scoped_information_scene import owns
    if not owns(session,subject,DRAW):return None
    return {'value_type':'document','maximum_seconds':3600,'authority':'table_owner',
        'description':'Record actual control of a specific existing object used as a Thread Anchor, with its factual provenance.'}


@hook('journey_command')
def designate_anchor(session,aid,kind,payload):
    if kind!='thread_anchor':return None
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    from ..asset_anchor_runtime import bind_anchor
    from ..fact_consent_admission import read
    from .scoped_information_scene import owns,distance
    require(owns(session,aid,DRAW) and set(payload)=={'object'},'A Thread owner must choose one actual object as an Anchor.')
    context=JourneyAssetContext(session);obj=context.state.objects.get(payload['object'])
    require(obj is not None and not obj.destroyed and distance(session,session.state['actors'][aid]['position'],obj.position.model_dump(mode='json'))<=5,'Touch the actual live object you control.')
    if obj.owner_id==aid:receipt='native-owner:'+aid
    else:
        fact=read(session,DRAW,aid,'anchor_control',obj.object_id,aid)
        require(fact is not None and fact['value']=={'object_id':obj.object_id,'controlled':1},'The native world owner must record your actual control of this exact object; presence or allegiance grants no control.')
        receipt=fact['receipt_id']
    bind_anchor(context,context.state.actors[aid],DRAW,obj,receipt)
    session.emit('THREAD_ANCHOR_DESIGNATED',aid,object_id=obj.object_id,receipt_id=receipt)
    return True


@hook('movement_landed')
def physical_line_limits(engine,mover,previous,destination,intent,forced):
    """Movement is never restrained by a simple line: an impossible line ends."""
    settle_line_geometry(engine)


@hook('teleport_settled')
def teleport_line_limits(ctx,subject,previous,destination,unwilling):
    settle_line_geometry(ctx.engine)


def settle_line_geometry(engine):
    from .condition_ownership import remove_instance
    for obj in list(engine.state.objects.values()):
        if obj.destroyed or obj.object_kind!=LINE_OBJECT:continue
        data=obj.component
        anchor=engine.state.actors.get(data.get('thread_anchor')) or engine.state.objects.get(data.get('thread_anchor'))
        target=engine.state.actors.get(data.get('line_target')) or engine.state.objects.get(data.get('line_target'))
        holder=engine.state.actors.get(data.get('line_holder'))
        mark=holder.conditions.get(data.get('line_instance')) if holder else None
        if anchor is None or target is None or mark is None:continue
        overlong=engine.grid.distance_ft(anchor.position,target.position)>data.get('thread_range_ft',30 if data.get('thread_medium')=='qi' else 20)
        blocked=not engine.grid.line_of_physical_transmission(anchor.position,target.position)
        if overlong or (blocked and data.get('thread_medium')=='mundane'):
            remove_instance(engine,holder,mark.instance_id,mark.source_definition_id)


@hook('fact_admission_validate')
def validate_anchor_control(session,payload,authority):
    if payload['source']!=DRAW or payload['kind']!='anchor_control':return None
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    obj=JourneyAssetContext(session).state.objects.get(payload['scope'])
    require(authority=='table_owner' and obj is not None and not obj.destroyed and
        payload['value']=={'object_id':obj.object_id,'controlled':1},
        'Record actual control of this exact existing object, with matching scope and typed control flag.')
    return True
