"""Review regressions through accepted intents, mixed controls and cold replay."""
import json
from pathlib import Path
import pytest
from tests.test_a2_flowers import (scene, commit, end, advance, seed_condition,
    ME, ALLY, FOE, HUNDRED, CALM, FRAGRANCE, WARD)
from tests.hunt12_support import candidate, send, reload
from tests.test_auto86_flowers import shape, at


def finish(combat,table,mid,chosen,*,auto=False):
    answers=[]; prompts=[]
    for _ in range(12):
        result=send(combat,table,mid,chosen,answers,auto=auto)
        if result['status']=='COMMITTED': return prompts
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']; prompts.append(prompt)
        answer={**prompt['context'],'selection':'USE' if prompt.get('choice') else 'DECLINE'}
        if prompt.get('choice'): answer['option_ids']=[prompt['choice']['options'][0]['id']]
        answers.append(answer)
    raise AssertionError('too many prompts')


def turn_end(combat,table,mid,*,auto=False):
    return finish(combat,table,mid,candidate(combat,mid,lambda c:c.kind.value=='END_TURN'),auto=auto)


@pytest.mark.parametrize('enemy',[False,True])
def test_hundred_service_options_explain_amounts_and_deadlines(tmp_path,enemy):
    combat,table,mid=scene(tmp_path,[HUNDRED])
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Garden of the Hundred Blossoms')))
    prompts=turn_end(combat,table,mid)
    if enemy: prompts=turn_end(combat,table,mid)
    (tmp_path/'returned-prompts.json').write_text(json.dumps(prompts,indent=2)+'\n')
    prompt=next(p for p in prompts if p['reaction']=='Garden of the Hundred Blossoms')
    assert prompt['context']['reactor_id']==ME
    assert prompt['affected']==reload(tmp_path,mid).state.actors[FOE if enemy else ALLY].display_name
    labels={o['id']:o['label'] for o in prompt['choice']['options']}
    assert 'starts its turn' in prompt['moment']
    if enemy:
        assert '2d8' in labels['Poison Damage']
        assert '20 feet' in labels['Reduce Speed']
        assert all('start of its next turn' in labels[k] for k in ['Poisoned','Reduce Speed','No Reactions'])
    else:
        assert 'proficiency bonus' in labels['Temporary HP'].lower()
        assert '10 feet' in labels['Increase Speed'] and 'end of this turn' in labels['Increase Speed']
    assert reload(tmp_path,mid).state.actors[FOE if enemy else ALLY].current_hp>0


@pytest.mark.parametrize('ai_owner',[False,True])
def test_hundred_mixed_control_choice_ownership(tmp_path,ai_owner):
    modes={ME:'LOCAL_AUTO' if ai_owner else 'MANUAL',ALLY:'LOCAL_AUTO',FOE:'MANUAL'}
    combat,table,mid=scene(tmp_path,[HUNDRED],control_modes=modes)
    finish(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Garden of the Hundred Blossoms')),auto=ai_owner)
    turn_end(combat,table,mid,auto=ai_owner)
    assert reload(tmp_path,mid).state.current_actor_id==ALLY
    prompts=turn_end(combat,table,mid,auto=True)
    (tmp_path/'returned-prompts.json').write_text(json.dumps(prompts,indent=2)+'\n')
    engine=reload(tmp_path,mid)
    assert engine.state.current_actor_id==FOE
    owned=[p for p in prompts if p['reaction']=='Garden of the Hundred Blossoms']
    if ai_owner: assert not owned
    else:
        assert len(owned)==1
        assert owned[0]['context']['reactor_id']==ME
        assert owned[0]['affected']==engine.state.actors[FOE].display_name
        assert 'starts its turn' in owned[0]['moment'] and 'Constitution' in owned[0]['moment']
    assert any(c.condition_id=='condition:typed.poisoned' for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('ai_recipient',[False,True])
def test_calming_mixed_control_recipient_consent_and_trigger(tmp_path,monkeypatch,ai_recipient):
    seed_condition(monkeypatch,FOE,'frightened',{'ability':'WIS','dc':1})
    modes={ME:'MANUAL',ALLY:'LOCAL_AUTO',FOE:'LOCAL_AUTO' if ai_recipient else 'MANUAL'}
    combat,table,mid=scene(tmp_path,[FRAGRANCE,CALM],control_modes=modes)
    shape(combat,table,mid,'Shape Fragrance: Calming Perfume')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6))
    turn_end(combat,table,mid)
    prompts=turn_end(combat,table,mid,auto=True)
    (tmp_path/'returned-prompts.json').write_text(json.dumps(prompts,indent=2)+'\n')
    engine=reload(tmp_path,mid)
    owned=[p for p in prompts if p['reaction']=='Calming Perfume']
    if ai_recipient: assert not owned
    else:
        assert len(owned)==1
        p=owned[0]
        assert p['context']['reactor_id']==FOE and p['affected']==engine.state.actors[FOE].display_name
        assert 'starts its turn inside the Fragrance' in p['moment']
        assert 'WIS' in p['choice']['options'][0]['label'] and 'DC 1' in p['choice']['options'][0]['label']
    assert not any(c.condition_id=='condition:typed.frightened' for c in engine.state.actors[FOE].conditions.values())
    assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and FRAGRANCE in e.source_definition_id])==1


def test_reviewed_flowers_have_one_authoritative_record():
    folder=Path(__file__).resolve().parents[1]/'authority/typed_mechanics/reviewed_final.d'
    owners={'TAL_FLOWERS_PETAL_DART':'owner_edits_2026-09-30.json',
            WARD:'life.json','TAL_FLOWERS_THORNED_BLOOM':'sys_placed-effects.json'}
    found={k:[] for k in owners}
    for path in folder.glob('*.json'):
        for key in json.loads(path.read_text()).get('mechanics',{}):
            if key in found: found[key].append(path.name)
    assert found=={k:[v] for k,v in owners.items()}
