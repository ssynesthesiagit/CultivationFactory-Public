"""Native suppression expires even when its actual source turn is omitted."""
from combat.factory_compiler import compile_character
from combat.ext.area_suppression import suppressed
from combat.turn_decisions import omits_turn
from tests.h1_support import sheet
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,turn,reload
from tests.test_mgr_t14_hearthfire_native import acquired_document


def test_native_suppression_does_not_last_forever_after_suppressor_is_defeated(tmp_path):
    document=acquired_document(tmp_path,18,dc=12)
    next(a for a in document['ability_scores_and_statistics']['abilities'] if a['ability']=='CON').update(score=6,modifier=-2)
    next(a for a in document['ability_scores_and_statistics']['abilities'] if a['ability']=='STR').update(score=40,modifier=15)
    owner=compile_character(document,actor_id=OWNER,reaction_plan={'ask':True})
    foe=sheet(['TAL_UNMAKING_LATTICE_UNRAVELING'],cl=18,score=20)
    foe['identity']['proficiency_bonus']=6
    foe['ability_scores_and_statistics']['hit_points']['maximum']=1
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_bundle=owner,foe_sheet=foe,extra_foes=1,
        ally_position={'x':3,'y':7},foe_position={'x':4,'y':6},seed='HEARTH-SUPPRESSOR-OMITTED')
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    zid=next(z.zone_id for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object'))
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Lattice Unraveling',at=(5,6)).candidate_id)
    e=reload(tmp_path,mid)
    assert suppressed(e.state.zones[zid])
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    attacks=[c for c in e.legal_candidates() if c.target_ids==(FOE,) and
        (e.action_catalog[c.source_definition_id].resolution_kind in ('ATTACK','MULTI_ATTACK')
         or any(r.get('type')=='attack' for r in (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',())))]
    assert attacks
    settle(table,mid,attacks[0].candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==0 and omits_turn(e,FOE)
    starts=e.state.actors[FOE].turns_started
    assert e.state.terminal_result is None and suppressed(e.state.zones[zid])
    for _ in range(2):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,OWNER)
        e=reload(tmp_path,mid)
        if not suppressed(e.state.zones[zid]):break
    assert e.state.actors[FOE].turns_started==starts
    assert not suppressed(e.state.zones[zid])
