"""A selected technique roll remains real when its weapon packet defeats the last foe."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, turn
from tests.test_mgr_t15_qi_potency_routes import P, VOLLEY, BOW, imported_fight, OWNER as ROUTE_OWNER, SECOND


def lethal_fight(tmp_path, hp):
    owner=sheet([P,VOLLEY,'TAL_LIGHTNING_THUNDER_ARROW'],cl=17,key='INT',score=18,kit=BOW)
    owner['identity']['proficiency_bonus']=6
    owner['ability_scores_and_statistics'].update(technique_attack_bonus=10,technique_save_dc=18)
    owner['ability_scores_and_statistics']['primary_resource']['maximum']=68
    ally=sheet([P],cl=1,key='INT',score=14)
    ally['identity']['proficiency_bonus']=2
    ally['ability_scores_and_statistics']['primary_resource']['maximum']=2
    ally['ability_scores_and_statistics']['hit_points']['maximum']=10
    ally['ability_scores_and_statistics']['armor_class']['base_value']=12
    foe=sheet([P],cl=1,key='INT',score=4)
    foe['identity']['proficiency_bonus']=2
    foe['ability_scores_and_statistics']['primary_resource']['maximum']=2
    foe['ability_scores_and_statistics']['hit_points']['maximum']=hp
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


@pytest.mark.parametrize('hp',[5,12])
@pytest.mark.parametrize('choice',['weapon','technique'])
def test_both_printed_packets_finish_when_primary_defeats_last_target(tmp_path,choice,hp):
    combat,table,mid=lethal_fight(tmp_path,hp)
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


def test_defeating_hit_does_not_spend_filtered_first_hit_maneuver(tmp_path):
    # The action strikes both of its targets in sequence, and the first strike
    # defeats its target before that target's maneuver packet resolves. Filtering
    # the packet off the body must leave the action's one first-hit maneuver
    # unspent, so the second, living target still receives it; a slot consumed by
    # the filtered packet would leave that target standing.
    from combat import typed_executor
    from combat.gate2_runtime_models import ActionIntent
    from tests.h1_support import script

    combat, table, mid = imported_fight(tmp_path, fragile=True)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[ROUTE_OWNER]
    first, second = engine.state.actors[FOE], engine.state.actors[SECOND]
    first.current_hp = 1
    first.armor_class = second.armor_class = 7
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == ROUTE_OWNER and (a.parameters.get('typed') or {}).get('weapon'))
    typed = action.parameters['typed']
    intent = ActionIntent(intent_id='maneuver-regression', decision_id='test', candidate_id='test',
                          state_version=engine.state.state_version, actor_id=ROUTE_OWNER, target_ids=(FOE, SECOND))
    ctx = typed_executor.Context(engine, actor, action, intent, typed, [first, second], first, {})
    attack = {'type': 'attack', 'attack_kind': 'weapon', 'count': 1,
              'on_hit': [{'type': 'damage', 'weapon_damage': True},
                         {'type': 'condition', 'condition': 'prone', 'applies_to': 'target',
                          'first_hit_only': True}]}
    script(engine, [19] * 100)
    typed_executor.block_attack(ctx, attack)
    assert not first.active
    prone = [target.entity_id for target in (first, second)
             if any(row.condition_id == 'condition:typed.prone'
                    for row in target.conditions.values())]
    assert prone == [SECOND], prone  # the filtered packet never lands on the body it killed
