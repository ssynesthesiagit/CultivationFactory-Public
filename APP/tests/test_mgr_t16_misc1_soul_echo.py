"""Soul-Echo procedure with admitted DC/facts, native choices and cold replay."""
import pytest

from combat.ext.soul_echo import FEATURE,RESULT
from tests.worker2_support import OWNER,ALLY,FOE,candidate,fixture,reload,settle
from tests.test_mgr_t16_misc1_ledger import auto_candidate


def fight(tmp_path,*,place=False,ai=False,dc=0,facts=None,foe_x=6):
    def arena(doc):
        doc['terrain_regions']=[]
        profile={'dc':dc,'facts':facts if facts is not None else {'possession':'Haunted by a ghost'}}
        if not place:
            profile['creature_id']=FOE
        doc['map_objects']=[{'id':601,'kind':'custom','name':'Investigation site','x':17 if place else 4,
            'y':5,'blocks':False,'source_profiles':{'soul_echo':profile}}]
    return fixture(tmp_path,[FEATURE],seed='T16-SOUL'+str(place)+str(ai)+str(dc)+str(facts),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':foe_x,'y':6}},
        battlefield_transform=arena,
        modes={OWNER:'LOCAL_AUTO' if ai else 'MANUAL',ALLY:'MANUAL',FOE:'MANUAL'})


@pytest.mark.parametrize('place,ai',[(False,False),(True,False),(False,True)])
def test_sound_check_and_all_five_questions_commit_and_reload(tmp_path,place,ai):
    combat,table,mid=fight(tmp_path,place=place,ai=ai)
    label='Soul-Echo Hearing: investigate '+('a place' if place else 'a creature')
    cid=candidate(combat,mid,label,target='object:map.601' if place else FOE).candidate_id
    prompts=(auto_candidate(combat,table,mid,cid) if ai else settle(table,mid,cid,
        picks={'choice:needle.soul_echo_fact':['possession']}))
    engine=reload(tmp_path,mid)
    learned=[c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id==RESULT]
    assert learned and learned[-1].data['value']=='Haunted by a ghost'
    if not ai:
        choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.soul_echo_fact')
        assert {o['id'] for o in choice['choice']['options']}=={
            'possession','coercion','empowered_name','residual_spirit','silence_origin'}
    if place:
        assert engine.grid.distance_ft(engine.state.actors[OWNER].position,engine.state.objects['object:map.601'].position)>60


def test_unknown_fact_never_invents_an_answer(tmp_path):
    combat,table,mid=fight(tmp_path,facts={})
    settle(table,mid,candidate(combat,mid,'Soul-Echo Hearing: investigate a creature',target=FOE).candidate_id,
        picks={'choice:needle.soul_echo_fact':['coercion']})
    assert not any(c.condition_id==RESULT for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())


def test_failed_check_gives_no_question_or_answer(tmp_path):
    combat,table,mid=fight(tmp_path,dc=1000)
    prompts=settle(table,mid,candidate(combat,mid,'Soul-Echo Hearing: investigate a creature',target=FOE).candidate_id)
    assert not prompts
    assert not any(c.condition_id==RESULT for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())


def test_creature_range_is_sixty_feet(tmp_path):
    combat,table,mid=fight(tmp_path,foe_x=17)
    engine=reload(tmp_path,mid)
    assert not any(c.target_ids==(FOE,) and
        getattr(engine.action_catalog.get(c.source_definition_id),'display_name','')=='Soul-Echo Hearing: investigate a creature'
        for c in engine.legal_candidates())
