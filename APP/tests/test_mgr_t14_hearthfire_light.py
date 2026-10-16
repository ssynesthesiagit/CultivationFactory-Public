"""Native authored scene light -> acquired Hearth -> perception and cold replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import to_battlefield,TabletopError
from tests.h1_support import ROOT
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,turn,reload
from tests.test_mgr_t14_hearthfire_native import acquired_bundle,acquired_document


def night_sighted_bundle(tmp_path):
    # A real compiled Dark-sphere Meld supplies sight to the caster. The ally
    # remains an ordinary observer, so the Hearth's own light is still tested.
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    document=acquired_document(tmp_path,18)
    document['spheres_and_talents']=sheet(['TAL_DARK_DARKVISION'],cl=18)['spheres_and_talents']
    return compile_character(document,actor_id=OWNER,reaction_plan={'ask':True})


def scene(tmp_path,level='DARKNESS',**changes):
    document={'map_id':'hearth-light','display_name':'A declared dark camp','width_squares':25,'height_squares':15,
        'ambient_illumination':level,'illumination_declaration':{'actor':'table-owner','authority':'GM',
            'source_rule':'Ordinary illumination at this camp.','visibility':'public','expiry':'map_revision'},**changes}
    saved=CombatService(ROOT,tmp_path).tabletop_maps.save(document)
    cold=CombatService(ROOT,tmp_path).tabletop_maps.get(saved['map_id'])
    assert cold['ambient_illumination']==level
    return to_battlefield(cold)


def test_native_hearth_light_changes_actual_visibility_and_cold_reload(tmp_path):
    arena=scene(tmp_path)
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_bundle=night_sighted_bundle(tmp_path),
        owner_pb=6,battlefield=arena,foe_position={'x':10,'y':6},
        seed='HEARTH-LIGHT')
    e=reload(tmp_path,mid)
    from combat import senses
    assert not senses.perceives(e,e.state.actors[ALLY],e.state.actors[FOE],sight_only=True)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    assert senses.perceives(e,e.state.actors[ALLY],e.state.actors[FOE],sight_only=True)
    # Native creature and empty-square presentation share the actual emitter.
    from combat.illumination import level_at
    from combat.gate2_runtime_models import Position
    assert level_at(e,Position(x=8,y=6))=='BRIGHT' # exactly 15 feet
    assert level_at(e,Position(x=9,y=6))=='DIM'
    assert level_at(e,Position(x=11,y=6))=='DIM' # exactly 30 feet
    assert level_at(e,Position(x=12,y=6))=='DARKNESS'
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(3,2)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    assert not senses.perceives(e,e.state.actors[ALLY],e.state.actors[FOE],sight_only=True)


@pytest.mark.parametrize('fact',[
    None,{'actor':'table-owner','authority':'player','source_rule':'Dark camp','visibility':'public','expiry':'map_revision'},
    {'actor':'table-owner','authority':'GM','source_rule':'Dark camp','visibility':'public','expiry':'forever'}])
def test_ambient_light_requires_real_typed_scene_authority(tmp_path,fact):
    with pytest.raises(TabletopError,match='[Ii]llumination'):
        scene(tmp_path,illumination_declaration=fact)


def test_missing_scene_light_is_default_inert(tmp_path):
    combat,table,mid=fixture(tmp_path,[],seed='LIGHT-INERT')
    e=reload(tmp_path,mid)
    assert 'ambient_illumination' not in e.battlefield_document
    assert not any(a.display_name=='Search by sight' for a in e.action_catalog.values())


def test_dim_hearth_light_applies_to_native_sight_search_only(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    # Hide legally behind native authored geometry, then observe from around
    # the wall. The stationary hidden creature still requires a real Search.
    arena=scene(tmp_path,level='DIM',walls=[{'shape':'rect','points':[[7,5],[8,8]],'filled':True,'blocks':'sight_and_movement'}])
    foe=sheet([],cl=18,score=20)
    foe['identity']['proficiency_bonus']=6
    foe['ability_scores_and_statistics']['skills']=[{'skill':'Stealth','bonus':17,'proficiency':'expertise'}]
    document=acquired_document(tmp_path,18)
    next(a for a in document['ability_scores_and_statistics']['abilities'] if a['ability']=='WIS').update(score=1,modifier=-5)
    owner=compile_character(document,actor_id=OWNER,reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_bundle=owner,
        owner_pb=6,foe_sheet=foe,battlefield=arena,foe_position={'x':10,'y':6},seed='HEARTH-DIM-SEARCH')
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Hide').candidate_id)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.hidden' for c in e.state.actors[FOE].conditions.values())
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(6,4,0) and all(p.z==0 for p in c.canonical_path)]
    assert moves
    settle(table,mid,moves[0].candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(9,4,0) and all(p.z==0 for p in c.canonical_path))
    settle(table,mid,move.candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid);count=len(e.rolls)
    settle(table,mid,candidate(combat,mid,'Search by sight').candidate_id)
    e=reload(tmp_path,mid)
    checks=[r for r in e.rolls[count:] if r.reason.startswith('CHECK:') and r.reason.endswith(':Perception')]
    assert checks and checks[-1].mode=='DISADVANTAGE'
    assert any(c.condition_id=='condition:typed.hidden' for c in e.state.actors[FOE].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(8,4)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid);count=len(e.rolls)
    settle(table,mid,candidate(combat,mid,'Search by sight').candidate_id)
    e=reload(tmp_path,mid)
    checks=[r for r in e.rolls[count:] if r.reason.startswith('CHECK:') and r.reason.endswith(':Perception')]
    assert checks and checks[-1].mode=='NORMAL'


def test_native_lattice_suppresses_hearth_light_and_ward_without_refilling_clock(tmp_path):
    from tests.h1_support import sheet
    from combat.ext.area_suppression import suppressed
    from combat.ext.qi_hearthfire import aura_contains
    from combat.illumination import level_at
    from combat.gate2_runtime_models import Position
    foe=sheet(['TAL_UNMAKING_LATTICE_UNRAVELING'],cl=18,score=20)
    foe['identity']['proficiency_bonus']=6
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_bundle=night_sighted_bundle(tmp_path),
        owner_pb=6,foe_sheet=foe,battlefield=scene(tmp_path),foe_position={'x':6,'y':6},seed='HEARTH-SUPPRESSION')
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    ward=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object'))
    zid=ward.zone_id;created=ward.created_round
    for _ in range(10):
        turn(table,mid,FOE)
        settle(table,mid,candidate(combat,mid,'Lattice Unraveling',at=(5,6)).candidate_id)
        e=reload(tmp_path,mid)
        if suppressed(e.state.zones[zid]):break
    assert suppressed(e.state.zones[zid])
    assert not aura_contains(e,e.state.zones[zid],e.state.actors[ALLY])
    assert level_at(e,Position(x=5,y=6))=='DARKNESS'
    duration=e.state.zones[zid].duration_rounds
    for _ in range(8):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        e=reload(tmp_path,mid)
        if not suppressed(e.state.zones[zid]):break
    assert not suppressed(e.state.zones[zid])
    assert level_at(e,Position(x=5,y=6))=='BRIGHT'
    assert e.state.zones[zid].created_round==created and e.state.zones[zid].duration_rounds==duration
