"""Native temporary stops followed by a separate evented grant loss.

The portable test bundle adds a deterministic self-dispel/suppress action using
the existing end_effect delivery. Particle ownership, activation, movement,
choice transport, persistence and replay are all real; no state is injected.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext.qi_subpaths_dust import FORM, primordial
from combat.opening_passage import solid_grid
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P, cold


def release_action(bundles, mode):
    owner=next(b for b in bundles if b['actor_id']==s.OWNER)
    original=next(a for a in owner['action_catalog']
        if a['parameters'].get('typed',{}).get('source')==P+'primordial_dust')
    action=deepcopy(original)
    action.update(source_definition_id='action:typed.test.particle_release',
        display_name='Test particle release',economy='ACTION',target_kind='SELF',
        range_ft=0,costs=[],concentration=False)
    action['parameters']={'typed':{'source':'test:particle_release',
        'numbers':deepcopy(original['parameters']['typed']['numbers']),
        'duration':{'kind':'instant'},'effects':[{'type':'end_effect',
            'conditions':[FORM.removeprefix('condition:typed.')],
            'select':'any','on_success':mode}]}}
    owner['action_catalog'].append(action)
    owner['actor_template']['action_ids'].append(action['source_definition_id'])
    owner.pop('bundle_sha256',None)
    owner['bundle_sha256']=canonical_sha256(owner)


@pytest.mark.parametrize('mode',['suppress','end'])
@pytest.mark.parametrize('stop',['creature','solid','free'])
def test_grant_loss_recovers_native_stop_in_same_commit(tmp_path,monkeypatch,mode,stop):
    if stop=='solid':
        from combat.tabletop import TabletopMapStore
        save=TabletopMapStore.save
        def authored(self,doc,*args,**kwargs):
            if doc.get('display_name')=='R1i Wide':
                doc={**doc,'objects':[{'id':1,'kind':'wall_section','x':4,'y':6,
                    'height_ft':100,'opening_width_milliinch':1000}]}
            return save(self,doc,*args,**kwargs)
        monkeypatch.setattr(TabletopMapStore,'save',authored)
    positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':4 if stop=='creature' else 12,'y':6},
        s.SECOND:{'x':15,'y':6}}
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'],owner_cl=18,
        wide=True,positions=positions,bundle_transform=lambda bundles:release_action(bundles,mode))
    commit(s.candidate(table,mid,'Primordial Dust'))
    e=cold(tmp_path,mid);initial=primordial(e.state.actors[s.OWNER])
    identity,expiry=initial.instance_id,initial.expires_on
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(4,6,0))
    commit(move.candidate_id)
    e=cold(tmp_path,mid);actor=e.state.actors[s.OWNER]
    assert (actor.position.x,actor.position.y,actor.position.z)==(4,6,0)
    hp,qi,movement=actor.current_hp,actor.resources['resource:core.qi'],actor.movement_remaining_ft
    sequence=e.state.event_sequence
    cid=s.candidate(table,mid,'Test particle release')
    if stop!='free':
        result=send(cid)
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']
        assert prompt['context']['reaction_source_id']=='choice:needle.dust_passage_lost'
        assert prompt['context']['reactor_id']==s.OWNER
        assert 'Primordial Dust' in prompt['moment']
        # Every nearest legal tie remains reachable by the human chooser.
        assert len(prompt['choice']['options'])>1
    commit(cid)
    e=cold(tmp_path,mid);actor=e.state.actors[s.OWNER]
    assert primordial(actor) is None
    assert solid_grid(e).volume_legal(actor.position,footprint=e._footprint(actor),
        occupied_cells=e._occupied_volumes_except(s.OWNER))
    assert (actor.current_hp,actor.resources['resource:core.qi'],actor.movement_remaining_ft)==(hp,qi,movement)
    recovery=[v for v in e.events if v.sequence>sequence and v.event_type=='MOVEMENT_COMMITTED']
    assert len(recovery)==int(stop!='free')
    if recovery:
        assert recovery[0].actor_id==s.OWNER and recovery[0].payload['forced'] is True
        assert recovery[0].payload['cost_ft']==0
        assert max(abs(actor.position.x-4),abs(actor.position.y-6),abs(actor.position.z))==1
    if mode=='suppress':
        retained=actor.conditions[identity]
        assert retained.condition_id==FORM.replace('condition:typed.','condition:typed.suppressed.',1)
        assert retained.expires_on==expiry
        # A later cold-loaded turn restores that exact effect, without a cast.
        for _ in range(12):
            commit(table.state(mid)['menu']['end_turn'])
            e=cold(tmp_path,mid)
            restored=primordial(e.state.actors[s.OWNER])
            if restored is not None:break
        assert restored is not None
        assert (restored.instance_id,restored.expires_on)==(identity,expiry)
    else:
        assert identity not in actor.conditions
