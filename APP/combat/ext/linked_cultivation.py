"""Read-only linked-system views over committed source-owned placements.

Formation and Banner retain their existing zones, objects, geometry, payment,
expiry and identity. A Structure is a transient view, never a second registry.
Other source plug-ins may publish views through linked_structures(engine).
Policy consumers use allows() for the exact structure, endpoint and benefit.
Absent views/policies do not infer links from teamwork, names or damage.
"""
from dataclasses import dataclass, replace
from typing import Any
from . import hook, run_strict

BENEFITS = frozenset({'formation','aura','reaction','command','remote_origin','senses','defense','movement','cost','banner','power','teleport'})
ROLES = frozenset({'primary_anchor','secondary_anchor','commander','participant','beneficiary','banner','remote_origin','command_asset','power_core','domain_armament','asset'})


@dataclass(frozen=True)
class Structure:
    identity: str
    source: str
    owner: str
    cl: int
    dc: int
    # endpoint -> printed roles, link -> its actual endpoints
    roles: dict[str, tuple[str, ...]]
    links: dict[str, tuple[str, ...]]
    concealed: tuple[str, ...] = ()
    traceable: tuple[str, ...] = ()
    version: str = ''
    zone_id: str = ''
    name: str = 'Linked cultivation structure'


def structures(engine):
    """Validated current views; adapters must derive them from committed state."""
    result = {}
    for group in run_strict('linked_structures', engine):
        for row in group or ():
            if not isinstance(row, Structure) or not row.identity or not row.source or not row.owner:
                raise ValueError('Linked structures need source-owned identity.')
            if type(row.cl) is not int or row.cl < 1 or type(row.dc) is not int:
                raise ValueError('Linked structures need printed Source CL and save DC.')
            if set(row.links)-BENEFITS or any(set(roles)-ROLES for roles in row.roles.values()):
                raise ValueError('Unknown linked benefit or node role.')
            action=engine.action_catalog.get(row.source)
            from ..alternative_payments import owned
            owner=engine.state.actors.get(row.owner)
            if owner is None or not ((action is not None and action.owner_id==row.owner) or owned(engine,owner,row.source)):
                raise ValueError('A linked view must identify its actual acquired source owner.')
            if any(endpoint(engine,key) is None for key in row.roles) or any(set(ends)-set(row.roles) for ends in row.links.values()):
                raise ValueError('Linked endpoints must be native nodes declared by this source.')
            if not row.version:
                from hashlib import sha256
                import json
                row=replace(row,version=sha256(json.dumps({'source':row.source,'cl':row.cl,'dc':row.dc,'roles':row.roles,'links':row.links,'concealed':row.concealed,'traceable':row.traceable},sort_keys=True).encode()).hexdigest())
            if row.identity in result:
                raise ValueError('A linked structure cannot have duplicate providers.')
            result[row.identity] = row
    return result


def endpoint(engine, identity):
    return engine.state.actors.get(identity) or engine.state.objects.get(identity)


def node_id(node):
    return getattr(node, 'entity_id', None) or node.object_id


def allows(engine, structure, endpoint_id, benefit, *, other_id=''):
    """Pure exact-link query, default True; it never changes source membership."""
    if benefit not in structure.links or endpoint_id not in structure.links[benefit]:
        return True
    return not any(value is False for value in run_strict('linked_benefit_allowed', engine, structure, endpoint_id, benefit, other_id))


def for_endpoint(engine, identity):
    return [s for s in structures(engine).values() if identity in s.roles]


@hook('linked_structures')
def native_placements(engine):
    from . import formations, placed
    from .. import zones
    from ..canonical import canonical_sha256
    out=[]
    for zone in formations.arrays(engine):
        data=formations.record(zone); nums=data.get('numbers') or {}
        roles={obj.object_id: ('primary_anchor',) if obj.object_id==data.get('eye') else ('secondary_anchor',)
               for obj in formations.objects_of(engine, zone)}
        participants=[a.entity_id for a in engine.state.actors.values() if a.active and formations.inside(engine,a,zone)
                      and (a.entity_id in (data.get('keyed') or ()) or a.team_id==engine.state.actors[zone.owner_id].team_id)]
        roles.update({key: ('beneficiary','participant') for key in participants})
        # Creating a placement does not by itself declare a command node.
        commander=data.get('commander_id')
        if commander in engine.state.actors:
            roles[commander]=tuple(sorted(set(roles.get(commander,()))|{'commander'}))
        endpoints=tuple(roles)
        out.append(Structure(zone.zone_id,zone.source_definition_id,zone.owner_id,int(data['cl']),int(nums['save_dc']),roles,
            {'formation':endpoints,'defense':endpoints}, version=canonical_sha256({'record':data,'roles':roles,'centre':zone.center.model_dump(mode='json')}),
            zone_id=zone.zone_id,name=str(zone.trigger_profile.get('name') or 'Formation')))
    for zone in placed.of(engine,'standard'):
        data=placed.data(zone); obj=engine.state.objects.get('object:banner:'+zone.zone_id)
        if obj is None or obj.destroyed:continue
        owner=engine.state.actors.get(zone.owner_id)
        if owner is None:continue
        # Read the actual sealed radius, not an assumed proximity relationship.
        roles={obj.object_id:('banner','primary_anchor')}
        roles.update({a.entity_id:('participant','beneficiary') for a in engine.state.actors.values()
                      if a.active and a.team_id==owner.team_id and zones.actor_inside_zone(engine,a,zone)})
        nums=zone.trigger_profile.get('numbers') or data.get('numbers') or {}
        if 'cl' not in nums or 'save_dc' not in nums:continue
        endpoints=tuple(roles)
        out.append(Structure(zone.zone_id,zone.source_definition_id,owner.entity_id,int(nums['cl']),int(nums['save_dc']),roles,
            {'aura':endpoints,'banner':endpoints,'command':endpoints},zone_id=zone.zone_id,name=str(zone.trigger_profile.get('name') or 'Formation')))
    return out


@hook('linked_structures')
def native_command_links(engine):
    """Actual commanded native actors, not synthetic actors for object Assets."""
    groups={}
    for creature in engine.state.actors.values():
        record=getattr(creature,'summon',None)
        if not record or record.get('status')!='present' or record.get('command') in {'free','mount'}:continue
        owner=engine.state.actors.get(record.get('owner'))
        if owner is None:continue
        key=(owner.entity_id,str(record['source']),str(record.get('command_group') or record.get('family') or record['group']))
        groups.setdefault(key,[]).append(creature)
    out=[]
    for (owner,source,group),creatures in groups.items():
        # These are the actual source numbers sealed on the created actors'
        # attacks, not inferred from their names, damage or Proficiency Bonus.
        nums=next(((a.parameters.get('typed') or {}).get('numbers') for c in creatures
                   for a in engine.action_catalog.values() if a.owner_id==c.entity_id
                   and (a.parameters.get('typed') or {}).get('source')==source
                   and {'cl','save_dc'}<=set((a.parameters.get('typed') or {}).get('numbers') or {})),None)
        if nums is None:continue
        roles={owner:('commander',)}
        roles.update({c.entity_id:('participant',) for c in creatures})
        out.append(Structure('command:'+owner+':'+group,source,owner,int(nums['cl']),int(nums['save_dc']),roles,
            {'command':tuple(roles)},name='Companion command connection'))
    return out


def path_allows(engine, zone, sending_position, receiving_position, benefit):
    """Exact native placement path query, including hypothetical step endpoints.

    Membership remains owned by the placement provider. This positional adapter
    avoids recursively enumerating Structure membership while a source computes
    that membership. Default True; no registry, node or geometry is created.
    """
    return False not in run_strict('linked_path_allowed',engine,zone,sending_position,receiving_position,benefit)
