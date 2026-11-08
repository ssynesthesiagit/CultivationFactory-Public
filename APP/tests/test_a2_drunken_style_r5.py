"""Attack-only substitution choices commit through service and cold replay."""
import copy
import json
import pytest
from tests import auto_worker1_support as S

BROKEN = 'TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE'
WRONG = 'TAL_DRUNKEN_STYLE_WRONG_HAND_STRIKE'
WEIGHT = 'TAL_GRAVITY_WEIGHT_SHIFT_BASE'
SLIP = 'TAL_DRUNKEN_STYLE_SLIPPING_PALM'
EXTRA = 'tianxia.path.body_refining.feature.extra_attack'
CHOICE = 'choice:needle.drunken_wrong_hand'
LABEL = 'Broken-Rhythm Strike: Gun (Staff)'
MARK = {'type':'mark', 'mark':'Off-Rhythm', 'applies_to':'target', 'duration':{'kind':'minutes','amount':1}}


@pytest.mark.parametrize('abilities', [('DEX','STR'), ('gravity_key','DEX'), ('STR','gravity_key')])
@pytest.mark.parametrize('key_score', [20,12])
def test_wrong_hand_respects_lightening_attack_only_scope_and_style_slot(tmp_path, monkeypatch, abilities, key_score):
    original = S.sheet
    def sheet(*args, **kwargs):
        doc = original(*args, **kwargs)
        doc['identity']['key_ability'] = 'WIS'
        for row in doc['ability_scores_and_statistics']['abilities']:
            value = {'STR':14, 'DEX':18, 'WIS':key_score}.get(row['ability'], row['score'])
            row.update(score=value, modifier=(value-10)//2)
        doc['combat_ability_choices'] = {'tianxia.mortal.weapon.gun':'STR'}
        return doc
    monkeypatch.setattr(S, 'sheet', sheet)
    def bonuses(bundle):
        for action in bundle['action_catalog']:
            typed = action['parameters'].get('typed', {})
            if typed.get('source') == BROKEN and typed.get('weapon'):
                typed['numbers']['attack_bonus'] += 40
                typed['weapon']['damage']['modifier'] += 7
    c,t,m = S.fight(tmp_path, [BROKEN,WRONG,WEIGHT,SLIP,EXTRA], cl=5, prepare=[MARK],
        left_kit={'items':[{'item_id':'tianxia.mortal.weapon.gun', 'name':'Gun', 'quantity':1}]}, bundle_edit=bonuses)
    S.settle(lambda answers:S.act(t,m,'Prepare',answers,target_id=S.RIGHT))
    S.settle(lambda answers:S.act(t,m,'Weight Shift: Body Lightening',answers))
    # Two real walking moves, then back in melee range: movement commits and
    # the active mode, not injected turn flags, qualify the Gravity provider.
    for cell in ((3,7),(3,6)):
        S.settle(S.cell_send(t,m,'Move',cell))
    from combat.ext.hold_still import moved_ft
    before_engine = S.reload(c,m)
    assert moved_ft(before_engine,before_engine.state.actors[S.LEFT]) == 10
    attack_start = len(before_engine.events)
    before = next(a for a in before_engine.action_catalog.values() if a.owner_id==S.LEFT and a.display_name==LABEL)
    sealed = copy.deepcopy(before.parameters)
    typed = sealed['typed']
    assert typed['weapon']['ability_modifier'] == 2
    assert typed['effects'][0]['count'] == 2
    picks = iter(abilities)
    seen = []
    def choose(prompt):
        key = prompt['context']['reaction_source_id']
        options = {o['id']:o['label'] for o in prompt['choice']['options']}
        if key == CHOICE:
            seen.append(options)
            chosen = next(picks)
            # On the predecessor missing-option cases still commit and replay;
            # final assertions below establish the behavioral red result.
            return [chosen if chosen in options else 'STR']
        if key == 'choice:needle.drunken_slipping_palm': return ['prone'] if 'prone' in options else list(options)[:1]
        if key == 'choice:needle.drunken_slipping_palm_use': return list(options)[:1]
        return [] if prompt['choice'].get('allow_decline') else list(options)[:1]
    result,prompts = S.settle(lambda answers:S.act(t,m,LABEL,answers,target_id=S.RIGHT), choose=choose)
    assert result['status'] == 'COMMITTED'
    (c.userdata_root/'r5-prompts.json').write_text(json.dumps(prompts,indent=2))
    e = S.reload(c,m)
    assert c._load_session(m).verify()['status'] == 'PASS'
    assert c._load_session(m).mechanical.replay()['status'] == 'PASS'
    attacks = [r.modifier for r in e.rolls if r.actor_id==S.LEFT and r.reason.startswith('ATTACK:')]
    damages = [r.modifier for r in e.rolls if r.actor_id==S.LEFT and r.reason.startswith('DAMAGE:')]
    attack_mods = {'STR':2, 'DEX':4, 'gravity_key':(key_score-10)//2}
    damage_mods = {'STR':2, 'DEX':4, 'gravity_key':2}
    assert attacks == [typed['numbers']['attack_bonus']-2+attack_mods[a] for a in abilities]
    assert damages == [typed['weapon']['damage']['modifier']-2+damage_mods[a] for a in abilities]
    assert len(seen) == 2 and all(set(o)=={'STR','DEX','gravity_key'} for o in seen)
    assert all('attack only' in o['gravity_key'] and 'Strength (+2)' in o['gravity_key']
               and 'ordinary ability choice' in o['gravity_key'] for o in seen)
    # Gravity is ordinary; only the non-finesse Dexterity grant spends the
    # attack's Style slot. The next strike reconstructs its own allocation.
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.drunken_slipping_palm_use']) == sum(a!='DEX' for a in abilities)
    assert len([r for r in e.rolls if r.actor_id==S.RIGHT and r.reason.startswith('SAVE:')]) == sum(a!='DEX' for a in abilities)
    assert e.action_catalog[before.source_definition_id].parameters == sealed
    assert not any(v.event_type=='GM_RIDER' for v in e.events[attack_start:])
