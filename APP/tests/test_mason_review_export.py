"""Continuation keeps source-use state with the actual source owner only."""
from tests.mason_native_support import *


@pytest.mark.parametrize('owns_mason',[False,True])
def test_native_encounter_return_keeps_nonowners_inert(tmp_path,owns_mason):
    combat,j=journey_fixture(tmp_path,features=FEATURES if owns_mason else [])
    jid=j['journey_id'];state=j
    if owns_mason:
        payload=journey_wall_payload()
        payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',chosen_allies=[s.OWNER])
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',payload)
    started=combat.journey_start_combat(jid,state['revision'],
        {s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=started['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold(tmp_path,mid).state.terminal_result is not None
    state=combat.journey_state(jid)
    resumed=combat.journey_resume(jid,state['revision'])
    for aid in (s.FOE,s.SECOND):
        assert BASE+'raise_the_imperial_bastion' not in resumed['actors'][aid]['travel_uses']
    if owns_mason:assert resumed['actors'][s.OWNER]['travel_uses'][BASE+'raise_the_imperial_bastion']==1
    else:assert BASE+'raise_the_imperial_bastion' not in resumed['actors'][s.OWNER]['travel_uses']
    assert CombatService(ROOT,tmp_path).journey_state(jid)==resumed
