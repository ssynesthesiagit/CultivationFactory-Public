"""Public native equipment adapter for source-qualified scene manipulations.

Uses the existing compiled inventory, hand occupancy and dropped-item condition
schema. No new items, ownership, weapon defaults or durability are manufactured.
Only explicit source consumers call drop; cold combat setup receives the same
item keys and ordinary carry conditions. Used by Thread Disarm.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
from .gate2_runtime_models import ActorState,ActionDefinition,ConditionInstance
from .journey_assets import JourneyAssetContext


class JourneyRuleContext(JourneyAssetContext):
    """Read-only native actor/geometry protocol for gear and source observers.

    This is an explicit scene adapter, not a patched combat engine. It reads
    actual acquired senses and surviving native conditions; it creates no
    visibility, relationship, action, elapsed time or new condition.
    """
    def _footprint(self,actor):
        from .footprints import standard_actor_footprint
        key=actor.entity_id if hasattr(actor,'entity_id') else actor
        return self.actor_footprints.get(key) or standard_actor_footprint()

    def _actor_cells(self,actor,position=None):
        return self.grid.footprint_cells(position or actor.position,self._footprint(actor))

    def _actor_volume(self,actor,position=None):
        from .space import volume
        return volume(position or actor.position,self._footprint(actor))

    def _on_battlefield(self,actor):
        return actor.position is not None and all(self.grid.in_bounds(cell) for cell in self._actor_cells(actor))

    def _distance_actor_to_actor(self,first,second):
        return self.grid.distance_between_cell_sets_ft(self._actor_volume(first),self._actor_volume(second))

    def _obscured_cells(self):
        # Ongoing combat zones cannot silently enter a journey; its native
        # snapshot validator requires their source continuation provider.
        return set()



def context(session):
    actors={};catalog={}
    for aid,row in session.state['actors'].items():
        template=row['bundle']['actor_template'];resources=row['resources']
        data={k:deepcopy(v) for k,v in template.items() if k in ActorState.model_fields}
        data.update(position=row['position'],current_hp=template['maximum_hp'],movement_remaining_ft=template['speed_ft'],
            resources=dict(resources),resource_maximums={r['resource_id']:r['maximum'] for r in template['resources']})
        data['conditions']={key:ConditionInstance.model_validate(json.loads(value))
            for key,value in row.get('encounter_snapshot',{}).get('conditions',{}).items()}
        if row.get('encounter_snapshot'):
            data['current_hp']=row['encounter_snapshot']['current_hp']
            data['active']=bool(row['encounter_snapshot']['active'])
            data['life_state']=row['encounter_snapshot']['life_state'] or None
        for index,item in enumerate(row.get('scene_dropped_items',[])):
            cid=f'scene-drop:{aid}:{index}'
            data['conditions'][cid]=ConditionInstance(instance_id=cid,condition_id='condition:typed.dropped_item',source_definition_id=item['source'],
                source_actor_id=item['writer'],target_id=aid,applied_sequence=index+1,expires_on='UNTIL_REMOVED',
                data={'item_key':item['item_key'],'disables_action':item.get('weapon_action',''),'dropped_at':item['position']})
        actors[aid]=ActorState.model_validate(data)
        for action in row['bundle']['action_catalog']:
            catalog[action['source_definition_id']]=ActionDefinition.model_validate(action)
    result=JourneyRuleContext(session)
    result.state.actors=actors;result.state.zones={};result.state.round_number=1;result.state.observations={}
    result.action_catalog=catalog
    result.typed_bundle_documents=[r['bundle'] for r in session.state['actors'].values()]
    result.typed_actor_ids=set(actors);result.typed_passive_rows={}
    return result


def held(session,aid):
    from . import carry
    from .ext.hand_occupancy import weapon_grips,occupancy
    engine=context(session);actor=engine.state.actors[aid]
    grips=weapon_grips(engine,actor);parts={v for values in occupancy(engine,actor,grips=grips).values() for v in values}
    return [deepcopy(r) for r in (carry.carrying_of(engine,aid) or {}).get('items',[])
        if carry.holds(engine,actor,r['key']) and (r.get('weapon_action') in grips or 'shield:'+r['key'] in parts
            or str(carry.owned_item_location(actor,r['key']) or '').startswith('hand:'))]


def drop(session,writer,holder,item_key,source):
    from .journey import require
    item=next((r for r in held(session,holder) if r['key']==item_key),None)
    require(item is not None,'Choose an actual held object, not a stowed or already dropped item.')
    row={'item_key':item_key,'weapon_action':item.get('weapon_action',''),'source':source,'writer':writer,
        'position':deepcopy(session.state['actors'][holder]['position'])}
    session.state['actors'][holder].setdefault('scene_dropped_items',[]).append(row)
    session.emit('SCENE_ITEM_DROPPED',holder,item=deepcopy(row))
