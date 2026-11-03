"""Default-inert persistence of actual journey object snapshots.

Only an established journey's evented runtime/map objects cross its bound fight.
Source-owned lifetime objects remain with their own import/export providers.
This module never infers acquisition, source permissions or effect durations.
"""
from . import hook


@hook('journey_combat_bundle')
def snapshots(bundle,session,aid):
    if aid!=next(iter(session.state['actors'])):return
    rows=[row for row in session.state.get('runtime_objects',{}).values()
          if not (row.get('component') or {}).get('asset_anchor_runtime')]
    if rows:return {**bundle,'journey_object_snapshots':rows}


@hook('match_initialize')
def import_snapshots(engine):
    from ..gate2_runtime_models import RuntimeObjectState
    rows=[row for bundle in getattr(engine,'typed_bundle_documents',[]) for row in bundle.get('journey_object_snapshots',[])]
    for row in rows:
        obj=RuntimeObjectState.model_validate(row)
        engine._update_object(obj,'system:journey.object_continuation',obj.owner_id)
    if rows:
        from ..asset_anchor_runtime import refresh
        refresh(engine)
        return True


@hook('journey_encounter_settled')
def export_snapshots(session,aid,engine,creature):
    if aid!=next(iter(session.state['actors'])):return
    from .objects import object_id
    from ..journey_assets import JourneyAssetContext
    ids=set(session.state.get('runtime_objects',{}))|{object_id(row) for row in session.state['battlefield'].get('map_objects',[])}
    if not ids:return
    context=JourneyAssetContext(session)
    for oid in sorted(ids):
        obj=engine.state.objects.get(oid)
        if obj is not None:context._update_object(obj,'system:journey.object_continuation',obj.owner_id or next(iter(session.state['actors'])))


@hook('journey_view')
def project_assets(state, viewer_id):
    """Project private map, snapshot and event profiles without changing replay."""
    from copy import deepcopy
    from ..asset_anchor_runtime import public_map_object

    authored = state.get('battlefield', {}).get('map_objects', ())
    runtime = state.get('runtime_objects', {}).values()
    events = [event['object'] for event in state.get('events', ())
              if isinstance(event.get('object'), dict)]
    if not (any((row.get('asset_declaration') or {}).get('visibility') == 'gm' for row in authored)
            or any((row.get('component', {}).get('asset_declaration') or {}).get('visibility') == 'gm'
                   for row in (*runtime, *events))):
        return None
    out = deepcopy(state)
    if 'map_objects' in out.get('battlefield', {}):
        out['battlefield']['map_objects'] = [public_map_object(row) for row in authored]
    for obj in (*out.get('runtime_objects', {}).values(),
                *(event['object'] for event in out.get('events', ())
                  if isinstance(event.get('object'), dict))):
        if isinstance(obj.get('component'), dict):
            obj['component'] = public_map_object(obj['component'])
    return out
