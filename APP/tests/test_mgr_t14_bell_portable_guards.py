"""Portable generic seam guards for Bell-Tower."""
from pathlib import Path
import subprocess
import pytest
from combat import initiative_modes


def test_initiative_surprise_removal_keeps_unrelated_disadvantage():
    benefit={'advantage':True,'ignore_surprise_disadvantage':True}
    assert initiative_modes.combine([benefit,{'surprise_disadvantage':True}])=='ADVANTAGE'
    assert initiative_modes.combine([benefit,{'surprise_disadvantage':True,'disadvantage':True}])=='NORMAL'
    assert initiative_modes.combine([])=='NORMAL'
    with pytest.raises(ValueError):initiative_modes.combine([{'advantage':1}])


def test_surprise_declaration_rejects_wrong_encounter_and_authority():
    assert initiative_modes.declarations(None,['a'])=={}
    for value in ({'actor_ids':['other'],'authority':'table_owner'},
                  {'actor_ids':['a','a'],'authority':'table_owner'},
                  {'actor_ids':['a'],'authority':'unverified'}):
        with pytest.raises(ValueError):initiative_modes.declarations(value,['a'])


def test_observer_information_frontend_keeps_private_scope():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','static/tabletop/observer-information.test.mjs'],
        cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_explicit_sound_path_override_beats_silence_but_not_deafness(monkeypatch):
    from types import SimpleNamespace
    from combat import ext, speech
    speaker=SimpleNamespace(entity_id='bell')
    listener=SimpleNamespace(entity_id='ally',conditions={})
    monkeypatch.setattr(ext,'run_strict',lambda *args:[False,True])
    engine=SimpleNamespace()
    assert speech.can_hear_from(engine,speaker,listener,'bell')
    listener.conditions={'deaf':SimpleNamespace(condition_id='condition:typed.deafened')}
    # The native Deafened predicate, rather than path overrides, remains controlling.
    from combat.typed_executor import cant_hear
    monkeypatch.setattr('combat.typed_executor.cant_hear',lambda actor: actor is listener)
    assert not speech.can_hear_from(engine,speaker,listener,'bell')


def test_ninefold_hearing_exception_is_limited_to_its_bell_source(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
    owner=SimpleNamespace(entity_id='owner')
    listener=SimpleNamespace(entity_id='ally')
    zone=SimpleNamespace(owner_id='owner',source_definition_id='bell-source')
    monkeypatch.setattr(bell.placed,'of',lambda engine,tag:[zone])
    monkeypatch.setattr(bell,'field_inside',lambda engine,actor,zone:True)
    monkeypatch.setattr(bell.placed,'data',lambda zone:{'chosen':['ally']})
    assert bell.ninefold_hearing(object(),owner,listener,'bell-source') is True
    assert bell.ninefold_hearing(object(),owner,listener,'unrelated-technique') is None


def test_information_source_requires_derived_numbers_and_typed_facts():
    from types import SimpleNamespace
    from combat.ext.information_sources import profile
    ctx=SimpleNamespace(numbers={'cl':14,'save_dc':17})
    assert profile(ctx,{'tags':['visual_illusion'],'save_ability':'wis'})=={
        'tags':['illusion','visual_illusion'],'source_cl':14,'save_dc':17,
        'save_ability':'WIS','full_control':0,'permanent':0,'authority':'ordinary'}
    for numbers in ({},{'cl':14},{'cl':True,'save_dc':17},{'cl':14,'save_dc':0}):
        with pytest.raises(ValueError):profile(SimpleNamespace(numbers=numbers),{'tags':['illusion']})
    for row in ({'tags':['invented']},{'tags':[{}]}, {'tags':['illusion'],'permanent':'false'},
                {'tags':['illusion'],'authority':'GM said so'},{'tags':['illusion'],'save_ability':3}):
        with pytest.raises(ValueError):profile(ctx,row)
