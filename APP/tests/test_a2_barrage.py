"""Barrage second-pass table transactions, owner choices and cold replay."""
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT, ROOT
from tests.test_sph_barrage_r1 import _send
from tests.test_auto58_barrage_projectiles import ARROW_KIT
COVER='TAL_BARRAGE_COVERING_VOLLEY'
SUPPRESS='TAL_BARRAGE_SUPPRESSING_FIRE'
MOBILE='TAL_BARRAGE_MOBILE_BARRAGE'
PROTECTED='condition:typed.barrage_covering_volley'
PRESSURE='condition:typed.barrage_suppressing_fire'


def finish(table, mid, cid, pick=None):
    answers=[]
    prompts=[]
    for _ in range(20):
        result=_send(table, mid, cid, answers)
        if result['status']=='COMMITTED':
            return prompts
        assert result['status']=='REACTION_REQUIRED', result
        prompt=result['reaction']; prompts.append(prompt)
        options=(prompt.get('choice') or {}).get('options') or []
        selected=pick(prompt) if pick else (options[0]['id'] if options else None)
        if prompt['context']['reaction_source_id']=='reaction:core.stamina_guard':
            selected=False
        answer={**prompt['context'], 'selection': 'USE' if selected is not False else 'DECLINE'}
        if options and selected is not False:
            answer['option_ids']=[selected]
        answers.append(answer)
    raise AssertionError(prompts)


def option(table,mid,text,target=None):
    groups=table.state(mid)['menu']['actions']
    group=next(g for g in groups if text in g['label'])
    return next(o['candidate_id'] for o in group['options'] if target is None or target in o.get('target_ids',[]))


def ready(table,mid):
    groups=table.state(mid)['menu']['actions']
    draw=next((g for g in groups if g['label'].startswith('Draw Gong Jian')),None)
    if draw:
        finish(table,mid,draw['options'][0]['candidate_id'])


def reload(tmp_path, mid):
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status']=='PASS'
    assert loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


@pytest.mark.parametrize('branch',['evade','ignore'])
def test_suppressing_fire_target_chooses_and_cold_reloads(tmp_path,branch):
    combat,table,mid=table_fight(tmp_path,[SUPPRESS],cl=5,kit=ARROW_KIT,ask=True)
    ready(table,mid)
    finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire',RIGHT))
    before=combat._load_session(mid).engine.state.actors[LEFT].turn_flags.copy()
    prompts=finish(table,mid,option(table,mid,'Suppressing Fire: Gong Jian',RIGHT),
                   lambda p: branch if p['context']['reaction_source_id']=='choice:needle.suppressing_fire' else False)
    choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.suppressing_fire')
    assert choice['context']['reactor_id']==RIGHT
    engine=reload(tmp_path,mid)
    source=next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==LEFT and a.display_name=='Suppressing Fire: Gong Jian (Bow and Arrow)')
    shots=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.source_definition_id==source]
    target=engine.state.actors[RIGHT]
    if branch=='evade':
        assert not shots
        assert engine._effective_speed(target)==target.speed_ft//2
        assert any(c.condition_id==PRESSURE for c in target.conditions.values())
    else:
        assert len(shots)==2
        assert all(e.payload['mode']=='DISADVANTAGE' for e in shots)
        assert not any(c.condition_id==PRESSURE for c in target.conditions.values())
    # One primary shot and both replacement shots use ordinary arrows.
    from combat.ext.ammunition import _SPENT_PREFIX
    assert sum(v for k,v in engine.state.actors[LEFT].turn_flags.items() if k.startswith(_SPENT_PREFIX))-sum(v for k,v in before.items() if k.startswith(_SPENT_PREFIX))==2
    assert not engine.state.actors[LEFT].bonus_action_available
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('automatic',[False,True])
def test_covering_volley_only_offers_allies_with_enemy_in_range(tmp_path,automatic):
    combat,table,mid=table_fight(tmp_path,[COVER],cl=5,kit=ARROW_KIT,ask=True)
    ready(table,mid)
    cid=option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Covering Volley',RIGHT)
    if automatic:
        from combat.gate4_adapters import ManualControllerAdapter
        real=combat.controller
        class Selected:
            def choose_primary_action(self,context):
                return ManualControllerAdapter(lambda _:(cid,())).choose_primary_action(context)
            def __getattr__(self,name):return getattr(real,name)
        combat.controller=Selected()
        combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
        try:
            assert table.auto_step(mid,table.state(mid)['last_sequence'],[])['status']=='COMMITTED'
        finally:
            combat.controller=real
        prompts=[]
    else:
        prompts=finish(table,mid,cid,lambda p: ALLY)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==PROTECTED for c in engine.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id==PROTECTED for c in engine.state.actors[RIGHT].conditions.values())
    if not automatic:
        prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.covering_volley')
        assert [o['id'] for o in prompt['choice']['options']]==[ALLY]
    assert not any(g['label'].startswith('Barrage follow-up: Gong Jian') for g in table.state(mid)['menu'].get('actions',[]))
    assert not any(v for k,v in engine.state.actors[LEFT].turn_flags.items() if k.startswith('barrage:'))


def test_mobile_barrage_chooses_route_charges_movement_and_preserves_bonus(tmp_path):
    combat,table,mid=table_fight(tmp_path,[MOBILE],cl=5,kit=ARROW_KIT,ask=True)
    ready(table,mid)
    before=combat._load_session(mid).engine.state.actors[LEFT].movement_remaining_ft
    prompts=finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Mobile Barrage',RIGHT),
                   lambda p: 'step:3,3,0' if p['context']['reaction_source_id']=='choice:needle.barrage_step' else False)
    assert any(p['context']['reaction_source_id']=='choice:needle.barrage_step' for p in prompts)
    engine=reload(tmp_path,mid)
    owner=engine.state.actors[LEFT]
    assert (owner.position.x,owner.position.y)==(3,3)
    assert owner.movement_remaining_ft==before-5
    assert owner.bonus_action_available
    assert any(g['label'].startswith('Barrage follow-up: Gong Jian') for g in table.state(mid)['menu']['actions'])


def test_quick_draw_combines_stow_and_draw_once_through_table(tmp_path):
    QUICK='TAL_BARRAGE_QUICK_DRAW_ARSENAL'
    from combat.ext.hand_occupancy import weapon_grips
    kit={'starting_kit': {'items': [
        {'item_id':'tianxia.mortal.weapon.gong_jian','quantity':1},
        {'item_id':'tianxia.mortal.weapon.fei_biao','quantity':1},
        {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    combat,table,mid=table_fight(tmp_path,[QUICK],cl=5,kit=kit,ask=True)
    finish(table,mid,option(table,mid,'Stow Fei Biao'))
    def pick(p):
        opts=p['choice']['options']
        return next(o['id'] for o in opts if 'stow' in o['label'])
    prompts=finish(table,mid,option(table,mid,'Quick-Draw Arsenal: draw'),pick)
    assert len(prompts)==1
    engine=reload(tmp_path,mid)
    assert any(e.source_definition_id==QUICK and e.event_type=='CONDITION_APPLIED' for e in engine.events)
    assert engine.state.actors[LEFT].action_available and engine.state.actors[LEFT].bonus_action_available
    assert not any('Quick-Draw Arsenal: draw' in g['label'] for g in table.state(mid)['menu']['actions'])
    assert len(weapon_grips(engine,engine.state.actors[LEFT]))==1


def test_suppressing_automatic_misses_honor_ceaseless_stock(tmp_path):
    from combat.ext.ammunition import _CEASELESS, _SPENT_PREFIX
    combat,table,mid=table_fight(tmp_path,[SUPPRESS,_CEASELESS],cl=5,kit=ARROW_KIT,ask=True)
    ready(table,mid)
    finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire',RIGHT))
    finish(table,mid,option(table,mid,'Suppressing Fire: Gong Jian',RIGHT),lambda p:'evade')
    engine=reload(tmp_path,mid)
    assert not any(k.startswith(_SPENT_PREFIX) for k in engine.state.actors[LEFT].turn_flags)
    assert any(c.condition_id==PRESSURE for c in engine.state.actors[RIGHT].conditions.values())
