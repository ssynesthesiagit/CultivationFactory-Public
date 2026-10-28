"""Temporary diagnostic for the Road prompt options (deleted before commit)."""
import json
from combat.tabletop_service import TabletopService
from combat.ext import mgr_reserve_lantern_keeper_light_the_way as m
from combat.ext import needle, rider_choices
from tests.test_mgr_lantern_native import journey, POS, OWNER, ALLY, FOE, lamps, declare_source
from tests.worker2_support import settle, reload

def scenario(tmp_path,ward,picks_extra):
    log=[]
    real=needle.ask
    def spy(engine,intent,checkpoint,chooser,choice_id,options,**kw):
        log.append([str(choice_id),[str(o) for o in options]])
        return real(engine,intent,checkpoint,chooser,choice_id,options,**kw)
    needle.ask=spy;rider_choices.ask=spy
    try:
        combat,s=journey(tmp_path,cl=6);jid=s['journey_id']
        s=combat.journey_acquire_source(jid,s['revision'],OWNER,m.PARENT,{})
        if ward:s=declare_source(combat,s,FOE,'road-ward',[ward],position=POS[ALLY])
        for point in (POS[OWNER],{'x':9,'y':6}):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':point})
        mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions={**POS,FOE:{'x':5,'y':6}})['match_id']
        table=TabletopService(combat,tmp_path)
        picks={'choice:needle.lantern_road_destination_lantern':'first','choice:needle.lantern_moving_lantern':None,**picks_extra}
        err=None
        for _ in range(6):
            if table.state(mid)['menu']['actor_id']==ALLY:break
            try:settle(table,mid,table.state(mid)['menu']['end_turn'],picks=picks)
            except Exception as exc:err=type(exc).__name__+': '+str(exc);break
        e=reload(tmp_path,mid);a=e.state.actors[ALLY]
        return {'ward':ward,'err':err,'pos':[a.position.x,a.position.y],'hp':a.current_hp,'foe_reaction':e.state.actors[FOE].reaction_available,'asks':log}
    finally:
        needle.ask=real;rider_choices.ask=real

def test_probe(tmp_path):
    info=[scenario(tmp_path,None,{}),scenario(tmp_path,'teleport_block',{}),scenario(tmp_path,'spatial_lock',{})]
    print('PROBE '+json.dumps(info,indent=1,default=str))
    assert False, 'probe printed'