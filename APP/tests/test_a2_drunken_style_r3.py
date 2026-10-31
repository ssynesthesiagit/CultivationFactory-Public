"""Ability substitution composition through service execution and cold replay."""
import copy
import json
import pytest
from tests import auto_worker1_support as S

BROKEN = 'TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE'
WRONG = 'TAL_DRUNKEN_STYLE_WRONG_HAND_STRIKE'
IRON = 'TAL_SWORD_IRON_SWORD_BODY'
EXTRA = 'tianxia.path.body_refining.feature.extra_attack'
CHOICE = 'choice:needle.drunken_wrong_hand'
LABEL = 'Broken-Rhythm Strike: Jian (Straight Sword)'


@pytest.mark.parametrize('abilities', [('STR','DEX'), ('DEX','CON'), ('CON','STR')])
def test_wrong_hand_selects_one_legal_sword_ability_per_strike(tmp_path, monkeypatch, abilities):
    original = S.sheet
    def sheet(*args, **kwargs):
        doc = original(*args, **kwargs)
        for row in doc['ability_scores_and_statistics']['abilities']:
            value = {'STR':14, 'DEX':18, 'CON':20}.get(row['ability'], row['score'])
            row.update(score=value, modifier=(value-10)//2)
        doc['combat_ability_choices'] = {'tianxia.mortal.weapon.jian':'STR'}
        return doc
    monkeypatch.setattr(S, 'sheet', sheet)
    def bonuses(bundle):
        # Keep non-ability attack/damage components visible and hit reliably.
        # Only fixture inputs change; production hooks execute normally.
        for action in bundle['action_catalog']:
            typed = action['parameters'].get('typed', {})
            if typed.get('source') == BROKEN and typed.get('weapon'):
                typed['numbers']['attack_bonus'] += 40
                typed['weapon']['damage']['modifier'] += 7
    c,t,m = S.fight(tmp_path, [BROKEN,WRONG,IRON,EXTRA], cl=5,
        left_kit={'items':[{'item_id':'tianxia.mortal.weapon.jian', 'name':'Jian', 'quantity':1}]},
        bundle_edit=bonuses)
    before = next(a for a in S.reload(c,m).action_catalog.values() if a.owner_id==S.LEFT and a.display_name==LABEL)
    sealed = copy.deepcopy(before.parameters)
    typed = sealed['typed']
    assert typed['weapon']['ability'] == 'STR'
    assert typed['weapon']['ability_modifier'] == 2
    assert typed['effects'][0]['count'] == 2
    picks = iter(abilities)
    seen = []
    def choose(prompt):
        if prompt['context']['reaction_source_id'] == CHOICE:
            # All three ordinary/talent alternatives must be offered by the
            # same plain action; each selection stays with this player.
            options = {o['id']:o['label'] for o in prompt['choice']['options']}
            seen.append(options)
            chosen = next(picks)
            return [chosen] if chosen in options else ['STR']
        return [prompt['choice']['options'][0]['id']]
    result,prompts = S.settle(lambda answers:S.act(t,m,LABEL,answers,target_id=S.RIGHT), choose=choose)
    assert result['status'] == 'COMMITTED'
    (c.userdata_root/'r3-prompts.json').write_text(json.dumps(prompts,indent=2))
    e = S.reload(c,m)
    assert c._load_session(m).verify()['status'] == 'PASS'
    assert c._load_session(m).mechanical.replay()['status'] == 'PASS'
    expected = {'STR':2, 'DEX':4, 'CON':5}
    attacks = [r.modifier for r in e.rolls if r.actor_id==S.LEFT and r.reason.startswith('ATTACK:')]
    damages = [r.modifier for r in e.rolls if r.actor_id==S.LEFT and r.reason.startswith('DAMAGE:')]
    assert attacks == [typed['numbers']['attack_bonus']-2+expected[a] for a in abilities]
    assert damages == [typed['weapon']['damage']['modifier']-2+expected[a] for a in abilities]
    assert len(seen) == 2 and all(set(o)=={'STR','DEX','CON'} for o in seen)
    assert all('ordinary ability choice' in o['CON'] for o in seen)
    assert e.action_catalog[before.source_definition_id].parameters == sealed
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
