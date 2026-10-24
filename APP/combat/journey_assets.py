"""Public Asset/Anchor geometry and event adapter for native elapsed-time scenes.

This is a geometry adapter, not a combat engine. It derives actor positions and
footprints from committed journey bundles and uses the same placement/profile
functions as combat. OBJECT_UPDATED snapshots are journaled in the journey.
Only explicit source-owned journey commands construct this context.
"""
from types import SimpleNamespace
from .gate2_runtime_models import Position,RuntimeObjectState
from .footprints import ActorFootprintDefinition, standard_actor_footprint
from .roof_geometry import RoofGeometry
from . import asset_anchor_runtime as assets


class JourneyAssetContext:
    def __init__(self,session):
        self.session=session;self.grid=session.grid
        self.battlefield_document=session.state['battlefield']
        objects={key:RuntimeObjectState.model_validate(row) for key,row in session.state.get('runtime_objects',{}).items()}
        # Authored map objects are real collision/material inputs even before
        # a source first writes a runtime object in this journey.
        from . import object_rules
        from .ext.objects import object_id
        for row in self.battlefield_document.get('map_objects',()):
            oid=object_id(row)
            if oid in objects:continue
            n=object_rules.stats(row)
            objects[oid]=RuntimeObjectState(object_id=oid,object_kind=n['kind'],position=Position(x=int(row['x']),y=int(row['y']),z=int(row.get('z',0))),
                unattended=n['unattended'],flammable=n['flammable'],ac=n['ac'],current_hp=n['hp'],maximum_hp=n['hp'],
                damage_threshold=n['threshold'],damage_immunities=n['immune'],height_ft=row.get('height_ft'),destroyed=False,
                component={'name':n['name'],'material':n['material'],'structure':n['structure'],'blocks':n['blocks'],
                           'resist':list(n['resist']),'artifact':bool(row.get('artifact')),
                           **{key:row[key] for key in (*assets.PROFILE_FIELDS,'asset_declaration') if key in row}})
        actors={};self.actor_footprints={}
        self.typed_bundle_documents=tuple(a['bundle'] for a in session.state['actors'].values())
        for aid,a in session.state['actors'].items():
            template=a['bundle']['actor_template']
            import json
            from .gate2_runtime_models import ConditionInstance
            conditions={key:ConditionInstance.model_validate(json.loads(value)) for key,value in a.get('encounter_snapshot',{}).get('conditions',{}).items()}
            actors[aid]=SimpleNamespace(entity_id=aid,position=Position.model_validate(a['position']),active=True,
                team_id=str(a.get('team_id') or aid),resources=a['resources'],display_name=a['name'],conditions=conditions)
            definition=a['bundle'].get('actor_footprint')
            self.actor_footprints[aid]=ActorFootprintDefinition.model_validate(definition) if definition else standard_actor_footprint()
        self.state=SimpleNamespace(objects=objects,actors=actors,event_sequence=len(session.state['events']))

    def _actor_cells(self,actor):
        return self._footprint(actor).occupied_cells(actor.position)

    def _effect_volume(self,actor):
        return self._actor_volume(actor)

    def _actor_volume(self,actor):
        from .space import volume
        return volume(actor.position,self._footprint(actor))

    def _footprint(self,actor):
        return self.actor_footprints[actor.entity_id if hasattr(actor,'entity_id') else actor]

    def _update_object(self,obj,source,actor_id):
        self.state.objects[obj.object_id]=obj
        self.session.state.setdefault('runtime_objects',{})[obj.object_id]=obj.model_dump(mode='json')
        self.session.emit('OBJECT_UPDATED',actor_id,source=source,object=obj.model_dump(mode='json'))
        self.state.event_sequence=len(self.session.state['events'])

    def asset_runtime_refresh(self):
        # Live journey works share native roof geometry without invoking combat
        # turn subscribers or inventing an encounter to resolve a travel action.
        bind(self.session)
        self.grid=self.session.grid


def grid_for(session, *, ignore=()):
    """Derive a native grid from authored terrain plus live object geometry."""
    from .gate2_grid import SquareGrid
    from . import ext
    from .object_geometry import target_cells
    context=JourneyAssetContext(session)
    context.state.objects={k:o for k,o in context.state.objects.items() if k not in ignore}
    document=dict(session.state['battlefield'])
    regions=list(document.get('terrain_regions',()))
    for obj in context.state.objects.values():
        if obj.destroyed or not (obj.component or {}).get('blocks'):continue
        cells=[{'x':c.x,'y':c.y} for c in target_cells(context,obj)]
        regions.append({'region_id':'runtime:'+obj.object_id,'terrain_type':'BLOCKED','cells':cells,
            'movement_cost':1,'description':(obj.component or {}).get('name',obj.object_kind),
            'height_ft':obj.height_ft or 5,'base_altitude_ft':obj.position.z*5})
    document['terrain_regions']=regions
    roofs=[row for group in ext.run_strict('runtime_roof_surfaces',context) for row in group]
    document['roof_surfaces']=[*document.get('roof_surfaces',()),*roofs]
    return SquareGrid(document)


def bind(session):
    """Default inert without runtime objects or explicit GM routes; cold-load binding."""
    if session.state.get('runtime_objects') or any(row.get('ordinary_route') in ('ladder','slope') for row in session.state['battlefield'].get('map_objects',())):
        session.grid=grid_for(session)
