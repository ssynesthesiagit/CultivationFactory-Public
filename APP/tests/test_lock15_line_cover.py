"""Pillar clipping is shared by line previews, targets and committed Table effects."""
import json
import zipfile
import pytest
from combat.space import effect_ray
from combat.gate2_runtime_models import Position
from combat import typed_executor as te
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests import lock8_support as S
from tests.test_lock2_persistence import act


def test_oblique_ray_crosses_pillar_square_and_is_reversible():
    start,end=Position(x=3,y=5),Position(x=11,y=4)
    ray=effect_ray(start,end)
    assert (7,4,0) in ray and (7,5,0) in ray
    assert ray==tuple(reversed(effect_ray(end,start)))
    assert effect_ray(Position(x=2,y=2),Position(x=3,y=3))==((2,2,0),(3,3,0))


@pytest.mark.parametrize('end',[(11,4,0),(4,11,0),(11,4,4),(4,3,11),(3,5,0)])
def test_voxel_ray_has_no_skipped_interior_crossing(end):
    from fractions import Fraction
    start=(3,5,0);ray=effect_ray(start,end)
    expected=set()
    # Independent slab intersection checks every voxel in the bounding box.
    import itertools
    for cell in itertools.product(*(range(min(a,b),max(a,b)+1) for a,b in zip(start,end))):
        lower,upper=Fraction(0),Fraction(1)
        for a,b,c in zip(start,end,cell):
            if b==a:
                if c!=a:upper=Fraction(-1)
            else:
                edges=sorted((Fraction(2*c-1-2*a,2*(b-a)),Fraction(2*c+1-2*a,2*(b-a))))
                lower=max(lower,edges[0]);upper=min(upper,edges[1])
        if lower<upper:expected.add(cell)
    assert set(ray)==expected
    assert ray==tuple(reversed(effect_ray(end,start)))


def test_line_membership_and_finite_height_blocking():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),me_at=(3,5),foe_at=(11,4))
    a,t=e.state.actors[S.ME],e.state.actors[S.FOE]
    area={'shape':'line','size_ft':120,'width_ft':5}
    e.grid.blocked={(7,4)}
    assert not te.in_area(e,a.position,t.position,t.position,area)
    assert t.position not in te.area_cells(e,a.position,t.position,area)
    assert t not in te._area_targets(e,a,t.position,area)
    e.grid.terrain_heights={'BLOCKED':{(7,4):5}};e.grid.finite_heights=True
    assert te.in_area(e,Position(x=3,y=5,z=2),Position(x=11,y=4,z=2),Position(x=11,y=4,z=2),area)
    e.grid.blocked.clear()
    assert te.in_area(e,a.position,t.position,t.position,area)


@pytest.mark.parametrize('pillar',[True,False])
def test_judgment_ray_table_preview_commit_reload(monkeypatch,tmp_path,pillar):
    owner,target='actor:factory.aaaaaaaa','actor:factory.bbbbbbbb'
    for pid in ('aaaaaaaa','bbbbbbbb','cccccccc'):
        doc=sheet(['RADIANCE_TAL_JUDGMENT_RAY'] if pid=='aaaaaaaa' else [],cl=15)
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Line pillar yard','width_squares':16,'height_squares':12,
        'walls':[{'shape':'rect','points':[[7,4],[8,5]],'filled':True}] if pillar else [],
        'starts':{'team1':[[3,5]],'team2':[[11,4],[5,5]]}})
    near='actor:factory.cccccccc'
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[target,near],
        control_modes={owner:'MANUAL',target:'MANUAL',near:'MANUAL'},arena_id='battlefield:map.line-pillar-yard',match_seed='L15-LINE')['match_id']
    table=TabletopService(service,tmp_path)
    while table.state(mid)['menu']['actor_id']!=owner:assert act(table,mid,'end')['status']=='COMMITTED'
    engine=service._load_session(mid).engine;state=table.state(mid)
    assert ((7,4) in engine.grid.blocked) is pillar
    candidate=next(c for c in engine.legal_candidates() if 'JUDGMENT_RAY' in c.source_definition_id and c.destination==Position(x=11,y=4))
    option=next(o for g in state['menu']['actions'] for o in g['options'] if o['candidate_id']==candidate.candidate_id)
    cells={(p['x'],p['y']) for p in option['area']['affected_cells']}
    assert ((11,4) in cells) is (not pillar)
    before=len(engine.events)
    assert table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,state['last_sequence'])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    saves=[ev for ev in loaded.engine.events[before:] if ev.event_type=='SAVE_ROLLED' and ev.actor_id==target]
    assert bool(saves) is (not pillar)
    damage=[ev for ev in loaded.engine.events[before:] if ev.event_type=='DAMAGE_COMMITTED' and target in ev.target_ids]
    assert bool(damage) is (not pillar)
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==near for ev in loaded.engine.events[before:])
    assert loaded.engine.state==service._load_session(mid).engine.state
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
