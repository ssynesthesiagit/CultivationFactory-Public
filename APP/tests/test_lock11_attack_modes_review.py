"""Real mutual concealment must retain both modes until selective removal."""
import pytest
from combat import zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.ext.mind_hidden_eye import mark_analyzed
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.test_lock9_attack_modes import PIERCING, DISCERN, KIT
from tests.r10_fixup_support import fixed_dice


@pytest.mark.parametrize('talent,expected',[(PIERCING,'ADVANTAGE'),(DISCERN,'DISADVANTAGE'),(None,'NORMAL')])
def test_mutual_smoke_table_attack_policy_and_attack_after_reload(monkeypatch,tmp_path,talent,expected):
    combat,table,mid=H.table_fight(tmp_path,[talent] if talent else [],kit=KIT,ally_talents=[])
    def setup(e):
        if 'zone:test.smoke' in e.state.zones:
            return
        source=next(a for a in e.state.actors[H.LEFT].action_ids if '.weapon.dao' in a)
        z=ZoneState(zone_id='zone:test.smoke',source_definition_id=source,owner_id=H.LEFT,
            center=Position(x=3,y=4),radius_cells=2,
            affected_cells=tuple(Position(x=x,y=y) for x in range(2,6) for y in range(3,7)),
            concentration_link=False,created_round=e.state.round_number,
            trigger_profile={'kind':'TYPED','name':'Heavy smoke','obscured':'heavy','triggers':[],'inside':[]})
        e.state.zones[z.zone_id]=z
        e._append_event('ZONE_CREATED',source,actor_id=H.LEFT,payload={'zone':z.model_dump(mode='json')})
        if talent==DISCERN:
            mark_analyzed(e,e.state.actors[H.LEFT],e.state.actors[H.RIGHT],'test:analyze')
    H.on_hold(monkeypatch,setup)
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    # This test measures d20 modes, so pass the owner's new concealment roll.
    fixed_dice(monkeypatch, [100] * 100)
    attacker,target=(H.RIGHT,H.LEFT) if talent==DISCERN else (H.LEFT,H.RIGHT)
    turn(table,mid,attacker)
    for _ in range(2):
        e=CombatService(ROOT,tmp_path)._load_session(mid).engine
        before=e.state.model_dump(mode='json')
        assert set(zones.attack_modes(e,e.state.actors[attacker],e.state.actors[target]))=={'ADVANTAGE','DISADVANTAGE'}
        assert zones.attack_mode(e,e.state.actors[attacker],e.state.actors[target]) is None
        assert e.state.model_dump(mode='json')==before
        state=table.state(mid); menu=state['menu']
        group=next(g for g in menu['actions'] if '.weapon.dao' in g['source_definition_id'] and '#' not in g['source_definition_id'])
        option=next(o for o in group['options'] if target in o['target_ids'])
        assert table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
        fresh=CombatService(ROOT,tmp_path)._load_session(mid)
        rolls=[ev for ev in fresh.engine.events if ev.sequence>state['last_sequence'] and ev.event_type=='ATTACK_ROLLED'
               and ev.actor_id==attacker]
        assert rolls and all(ev.payload['mode']==expected for ev in rolls)
        assert all(bool(ev.payload.get('attack_mode_removed')) is bool(talent) for ev in rolls)
        assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'
        assert act(table,mid,'end')['status']=='COMMITTED'
        turn(table,mid,attacker)
