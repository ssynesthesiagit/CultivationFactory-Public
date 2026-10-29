"""A selected technique roll remains real when its weapon packet defeats the last foe."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, turn
from tests.test_mgr_t15_qi_potency_routes import P, VOLLEY, BOW


def lethal_fight(tmp_path):
    owner=sheet([P,VOLLEY,'TAL_LIGHTNING_THUNDER_ARROW'],cl=17,key='INT',score=18,kit=BOW)
    owner['identity']['proficiency_bonus']=6
    owner['ability_scores_and_statistics'].update(technique_attack_bonus=10,technique_save_dc=18)
    owner['ability_scores_and_statistics']['primary_resource']['maximum']=68
    ally=sheet([P],cl=1,key='INT',score=14)
    ally['identity']['proficiency_bonus']=2
    ally['ability_scores_and_statistics']['primary_resource']['maximum']=2
    ally['ability_scores_and_statistics']['hit_points']['maximum']=10
    ally['ability_scores_and_statistics']['armor_class']['base_value']=12
    # A CL1 Qi hit die is 8 + CON(-3) = 5 HP, but this fixture tests the hit
    # boundary, not instant disintegration: 5 maximum HP would put the weapon
    # packet over the engine's massive-damage threshold (life_state.DOOMED),
    # which finalizes death before the second printed packet can roll. 12 HP
    # still lets the primary packet reduce the last foe to 0 and stay Dying,
    # so both packets of the one hit resolve before the fight ends.
    foe=sheet([P],cl=1,key='INT',score=4)
    foe['identity']['proficiency_bonus']=2
    foe['ability_scores_and_statistics']['primary_resource']['maximum']=2
    foe['ability_scores_and_statistics']['hit_points']['maximum']=12
    foe['ability_scores_and_statistics']['armor_class']['base_value']=7
    for aid,doc in [(OWNER,owner),(ALLY,ally),(FOE,foe)]:
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'display_name':'Qi packet completion yard','width_squares':12,'height_squares':8,
        'walls':[],'starts':{'team1':[[2,4],[1,1]],'team2':[[6,4]]}})
    mid=combat.create_factory_match(project_ids=['worker2-owner','worker2-ally'],opponent_actor_ids=[FOE],
        arena_id='battlefield:map.qi-packet-completion-yard',match_seed='QI-POTENCY-NATIVE',
        control_modes={a:'MANUAL' for a in [OWNER,ALLY,FOE]})['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,OWNER)
    return combat,table,mid


@pytest.mark.parametrize('choice',['weapon','technique'])
def test_both_printed_packets_finish_when_primary_defeats_last_target(tmp_path,choice):
    combat,table,mid=lethal_fight(tmp_path)
    settle(table,mid,candidate(combat,mid,'Thousand-Spark Volley',target=FOE).candidate_id,
        choices={'choice:needle.qi_potency':choice})
    engine=reload(tmp_path,mid)
    rolled=[r for r in engine.rolls if r.actor_id==OWNER and r.reason.startswith('DAMAGE') and r.dice]
    assert len(rolled)==2
    assert [r.modifier for r in rolled]==([8,0] if choice=='weapon' else [4,4])
    assert engine.state.actors[FOE].current_hp==0
    assert engine.state.terminal_result is not None
    receipts=list(engine.state.actors[OWNER].turn_flags['damage_activation_round_receipts'].values())
    assert receipts==[{'choice':choice,'used':True}]
