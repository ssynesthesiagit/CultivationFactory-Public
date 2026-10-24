"""Review regressions through persisted session intents and cold replay."""
import json
from pathlib import Path
import pytest
from tests.test_auto2_sniper import (fight, reload, resolve, act, turn, LEFT, RIGHT,
    TRAIN, DEADLY, POSTURE, HEAD, PERFECT, FAR, WAIT, FOCUS, POSTURE_HELD,
    PERFECT_HELD, BOW, POSITIONS, hit_dice, labels, select, last_attack, edit, prefix_send)
from combat.ext.sniper_precision import QI, KILLING
from combat.stealth import sees
from combat.ext.sniper_angles import current_cover

@pytest.mark.parametrize('hit', [False, True])
def test_cover_posture_with_unseen_enemy_then_reveal(tmp_path, monkeypatch, hit):
    hit_dice(monkeypatch)
    def arena(a):
        a['terrain_regions'].append({'region_id':'test.cover','terrain_type':'SIMPLE_COVER',
                                    'movement_cost':5,'cells':[{'x':4,'y':6}]})
    def bundle(b):
        if b['actor_id']==RIGHT and not hit:b['actor_template']['armor_class']=1000
        if b['actor_id']==LEFT:
            reveal=next(a for a in b['action_catalog'] if a['display_name']=='Reveal')
            reveal['radius_ft']=20
            reveal['parameters']['typed']['area']={'shape':'sphere','size_ft':20}
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,POSTURE],left_kit=BOW,positions=POSITIONS,
        left_score=30,arena_edit=arena,bundle_edit=bundle,
        prepare=[{'type':'condition','condition':'invisible','applies_to':'target','duration':{'kind':'minutes','amount':1}},
                 {'type':'spend_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'}],
        extra_actions=[('Reveal',{'target_kind':'CELL','effects':[
            {'type':'remove_condition','condition':'invisible','applies_to':'creatures_in_area'}]})])
    resolve(lambda answers:act(t,m,'Prepare',answers,target_id=RIGHT))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m)
    assert not sees(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    assert current_cover(e,e.state.actors[RIGHT],e.state.actors[LEFT])==2
    resolve(prefix_send(t,m,'Reveal',(3,6)))
    e=reload(c,m)
    assert sees(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    assert any(v.condition_id==POSTURE_HELD for v in e.state.actors[LEFT].conditions.values())
    _,prompts=resolve(lambda answers:act(t,m,select(t,m,'Snipe Shot:'),answers,target_id=RIGHT),
        {'choice:needle.sniper.posture_focus':['focus'],'choice:needle.rider_step':['cell:3,5']})
    e=reload(c,m)
    if hit:assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(3,5)
    else:assert e.state.actors[LEFT].resources[FOCUS]==1
    assert any(p['context']['reaction_source_id']==('choice:needle.rider_step' if hit else 'choice:needle.sniper.posture_focus') for p in prompts)

@pytest.mark.parametrize('qi', [False, True])
def test_perfect_ranged_spell_description_and_consumption(tmp_path, monkeypatch, qi):
    hit_dice(monkeypatch)
    def spell(b):
        if b['actor_id']==LEFT:
            a=next(a for a in b['action_catalog'] if a['display_name']=='Prepare')
            a['parameters']['typed']['range_ft']=60
    c,t,m=fight(tmp_path,[PERFECT]+([QI] if qi else []),left_kit=BOW,positions=POSITIONS,
        prepare=[{'type':'attack','attack_kind':'cultivation_ranged','count':1,
                  'on_hit':[{'type':'damage','flat':1,'damage_types':['force']}]}],
        prepare_attack_bonus=100,bundle_edit=spell)
    resolve(lambda answers:act(t,m,'Perfect Shot',answers))
    e=reload(c,m)
    description=next(a.parameters['description'] for a in e.action_catalog.values() if a.display_name=='Perfect Shot')
    held=next(v for v in e.state.actors[LEFT].conditions.values() if v.condition_id==PERFECT_HELD)
    resolve(lambda answers:act(t,m,'Prepare',answers,target_id=RIGHT))
    e=reload(c,m)
    assert last_attack(e).payload['mode']==('ADVANTAGE' if qi else 'NORMAL')
    assert any(v.condition_id==PERFECT_HELD for v in e.state.actors[LEFT].conditions.values()) is (not qi)
    assert ('ranged spell' in description) is qi
    assert ('ranged spell' in held.data['label']) is qi

@pytest.mark.parametrize('aperture', [False, True])
def test_combined_head_description_matches_persisted_shot(tmp_path, monkeypatch, aperture):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[HEAD,DEADLY,PERFECT,'tianxia.path.body_refining.feature.extra_attack']+
        ([KILLING] if aperture else []),left_kit=BOW,left_score=30,positions=POSITIONS)
    resolve(lambda answers:act(t,m,'Perfect Shot',answers))
    label=next(l for l in labels(t,m) if l.startswith('Head Shot:') and '+ Deadly Shot' in l)
    resolve(lambda answers:act(t,m,label,answers,target_id=RIGHT))
    e=reload(c,m)
    text=e.action_catalog[last_attack(e).source_definition_id].parameters['description']
    assert '-5' in text and '+10' in text
    assert '1d8' in text
    assert ('1d10' in text and 'Aimed Line' in text) is aperture
    dice=next(v for v in e.events if v.event_type=='DAMAGE_ROLLED' and v.payload.get('bonus_component')=='surrendered_attacks')
    assert dice.payload['expression'].startswith('2d10' if aperture else '2d8')


def test_reviewed_rows_unique_and_service_still_uses_consolidated_authority(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[FAR,PERFECT,POSTURE,WAIT],left_kit=BOW,positions=POSITIONS,
                  bundle_edit=edit(short_range=True))
    resolve(lambda answers:act(t,m,'Perfect Shot',answers))
    resolve(lambda answers:act(t,m,select(t,m,'Gong Jian'),answers,target_id=RIGHT))
    e=reload(c,m)
    assert last_attack(e).payload['mode']=='ADVANTAGE'
    root=Path(__file__).resolve().parents[1]/'authority/typed_mechanics'
    files=[root/'reviewed_final.json',*sorted((root/'reviewed_final.d').glob('*.json'))]
    for key in [FAR,PERFECT,POSTURE,WAIT]:
        owners=[p.name for p in files if p.exists() and key in json.loads(p.read_text()).get('mechanics',{})]
        assert len(owners)==1,(key,owners)
