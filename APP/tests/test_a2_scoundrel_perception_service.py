"""Fresh AI service fight: a hostile behind a pillar is in range but not perceived."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.r1i_service_support import force_ai_candidate
from tests import auto11_service_support as S
import json,zipfile

def test_ai_area_excludes_unperceived_enemy_inside_radius(tmp_path):
    ids=[S.THIEF,S.ALLY,S.VICTIM,S.RIVAL]
    where={S.THIEF:{'x':3,'y':6},S.ALLY:{'x':3,'y':7},S.VICTIM:{'x':4,'y':6},S.RIVAL:{'x':8,'y':3}}
    talents=['TAL_SCOUNDREL_EVERYTHING_IN_THE_WRONG_PLACE','TAL_SCOUNDREL_STEAL','TAL_SCOUNDREL_DIRTY_TRICK']
    docs={who:S._doc(talents if who==S.THIEF else [],kit=S.PACK,name=who.rsplit('.',1)[-1]) for who in ids}
    for who,doc in docs.items():
        folder=tmp_path/'portable_characters'/who.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    bundles=[compile_character(docs[who],actor_id=who,reaction_plan={'ask':True} if who==S.THIEF else None) for who in ids]
    combat=CombatService(S.ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid=combat._finish_factory_match(bundles,ids,{who:'team:a' if who in (S.THIEF,S.ALLY) else 'team:b' for who in ids},where,arena,[S.THIEF],[who for who in ids if who!=S.THIEF],control_modes={who:'MANUAL' for who in ids},match_seed='A2SCOUNDRE-perception',display_name='Scoundrel perception',maximum_rounds=10)['match_id']
    S.to_thief(table,mid)
    engine=S.engine(combat,mid)
    from combat.target_knowledge import can_see
    assert engine._distance_actor_to_actor(engine.state.actors[S.THIEF],engine.state.actors[S.RIVAL])<=30
    assert not can_see(engine,engine.state.actors[S.THIEF],engine.state.actors[S.RIVAL])
    cid=S.candidate(table,mid,'EVERYTHING IN THE WRONG PLACE');force_ai_candidate(combat,mid,S.THIEF,cid)
    result=table.auto_step(mid,table.state(mid)['last_sequence']);assert result['status']=='COMMITTED',result
    cold=CombatService(S.ROOT,tmp_path);assert cold.replay(mid)['status']=='PASS'
    engine=S.engine(cold,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'EVERYTHING_IN_THE_WRONG_PLACE' in e.source_definition_id]
    assert {e.actor_id for e in saves}=={S.VICTIM}
    assert not engine.state.actors[S.RIVAL].conditions and not engine.state.actors[S.ALLY].conditions
