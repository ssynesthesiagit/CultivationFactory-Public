"""Weapons second pass: committed table intents and cold CombatService reloads."""
import json

import pytest

from combat.ext.weapons_second_pass import INITIATE, CASTING, CAREFUL, CORRECTION, MEASURE, CONDUIT, CORRECTED
from tests.test_auto21_weapons import (
    ME, FOE, ALLY, DAGGER, SPEAR, WHIP, AXE, BLADE, EXTRA_ATTACK, fight, to_turn, ask, named,
    reload, force_naturals, events, conditions, attack_on,
)


def ask(table, mid, chosen, answers=('USE',), choice=None, prompts_out=None):
    state = table.state(mid)
    menu = state['menu']
    chosen = menu['end_turn'] if chosen == 'end' else chosen
    sent, prompts = [], []
    for _ in range(30):
        result = table.act(mid, chosen, menu['decision_id'], menu['state_version'], state['last_sequence'], sent)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            if prompts_out is not None:
                prompts_out.extend(prompts)
            return prompts
        prompt = result['reaction']
        prompts.append(prompt)
        selection = answers[min(len(sent),len(answers)-1)]
        answer = {**prompt['context'], 'selection': selection}
        if prompt.get('choice') and selection != 'DECLINE':
            options = [r['id'] for r in prompt['choice']['options']]
            answer['option_ids'] = [choice if choice in options else options[0]]
        sent.append(answer)
    raise AssertionError('repeated prompt')


def choose(table, mid, weapon):
    to_turn(table, mid, ME, choice=weapon)


def candidate(combat, mid, word, target=FOE):
    e = combat._load_session(mid).engine
    matches = [c for c in e.legal_candidates() if c.target_ids == (target,)
               and word in c.display_name]
    assert matches, [(c.display_name, c.target_ids) for c in e.legal_candidates()]
    return matches[0].candidate_id


def move_to(combat, table, mid, x, y):
    e = combat._load_session(mid).engine
    matches = [c for c in e.legal_candidates() if c.kind.value == 'MOVE'
               and c.destination.x == x and c.destination.y == y]
    assert matches, (x, y, [(c.kind.value, c.destination) for c in e.legal_candidates()])
    return ask(table, mid, matches[0].candidate_id)


def selected_id(root, mid):
    c = conditions(root, mid, ME).get(CONDUIT)
    return c.data['weapon'] if c else ''


def test_conduit_selection_is_explicit_and_does_not_replace_stats(tmp_path):
    combat, table, mid = fight(tmp_path, mids=(INITIATE,), me_kit=(DAGGER, AXE))
    e = combat._load_session(mid).engine
    base = next(a for a in e.action_catalog.values() if a.owner_id == ME and a.display_name.endswith('(Dagger) attack'))
    seen = []
    to_turn(table, mid, ME, choice=base.source_definition_id, seen=seen)
    assert selected_id(tmp_path, mid) == base.source_definition_id
    assert not [c for c in reload(tmp_path, mid).legal_candidates() if 'Choose Conduit Weapon:' in c.display_name]
    assert not [a for a in reload(tmp_path, mid).action_catalog.values() if '#conduit' in a.source_definition_id]
    assert any('Conduit Weapon' in json.dumps(p) for p in seen)


def test_casting_hand_changes_attack_and_damage_only_for_chosen_weapon(tmp_path, monkeypatch):
    import tests.test_auto21_weapons as support
    original = support.sheet
    def strong_key(*args, **kw):
        s = original(*args, **kw)
        s['identity']['path'] = 'Body Refining'
        for a in s['ability_scores_and_statistics']['abilities']:
            a.update(score=22 if a['ability'] == 'CON' else 10, modifier=6 if a['ability'] == 'CON' else 0)
        return s
    monkeypatch.setattr(support, 'sheet', strong_key)
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CASTING), me_kit=(DAGGER, AXE))
    e = combat._load_session(mid).engine
    base = next(a for a in e.action_catalog.values() if a.owner_id == ME and a.display_name.endswith('(Dagger) attack'))
    choose(table, mid, base.source_definition_id)
    e = reload(tmp_path, mid)
    variants = [a for a in e.action_catalog.values() if a.owner_id == ME and a.source_definition_id == base.source_definition_id+'#conduit']
    assert len(variants) == 1
    typed = variants[0].parameters['typed']
    assert typed['weapon']['ability_modifier'] == base.parameters['typed']['weapon']['ability_modifier']
    assert typed['numbers']['attack_bonus'] == base.parameters['typed']['numbers']['attack_bonus']
    assert typed['weapon']['damage']['modifier'] == base.parameters['typed']['weapon']['damage']['modifier']
    assert typed['weapons_casting_hand_explicit'] is True
    available = e.legal_candidates()
    assert not [c for c in available if c.source_definition_id.endswith('#conduit')
                and AXE == e.action_catalog[c.source_definition_id].parameters['typed']['weapon']['implement_id']]
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    ask(table, mid, candidate(combat, mid, '(Casting-Hand:'))
    roll = events(tmp_path, mid, 'ATTACK_ROLLED', ME)[-1].payload
    assert roll['modifier'] == typed['numbers']['attack_bonus'] + 6
    damage = events(tmp_path, mid, 'DAMAGE_ROLLED', ME)[-1].payload
    assert damage['modifier'] == typed['weapon']['damage']['modifier'] + 6
    assert selected_id(tmp_path, mid) == base.source_definition_id


@pytest.mark.parametrize('owned_insight,expected', [(True, 'ADVANTAGE'), (False, 'NORMAL')])
def test_careful_grip_protects_the_selected_conduit(tmp_path, monkeypatch, owned_insight, expected):
    mids = (INITIATE, CAREFUL) if owned_insight else (INITIATE,)
    combat, table, mid = fight(tmp_path, mids=mids, me_kit=(DAGGER,),
        foe_kit=('tianxia.mortal.weapon.tie_chi',), seed='A2WEAPONSS-careful')
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    force_naturals(monkeypatch, who=FOE, attack=15, save=3)
    to_turn(table, mid, FOE)
    ask(table, mid, candidate(combat, mid, 'Disarm', ME))
    saves = events(tmp_path, mid, 'SAVE_ROLLED', ME)
    assert saves and saves[-1].payload['mode'] == expected


@pytest.mark.parametrize('natural,answer,present', [(7, 'USE', True), (6, 'USE', True), (5, 'USE', False), (7, 'DECLINE', False)])
def test_conduit_hand_correction_near_miss_and_decline(tmp_path, monkeypatch, natural, answer, present):
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CORRECTION), me_kit=(DAGGER,), foe_kit=(DAGGER,))
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    force_naturals(monkeypatch, who=ME, attack=natural, save=3)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False), answers=(answer,))
    held = conditions(tmp_path, mid, ME).get(CORRECTED)
    assert bool(held) is present
    correction_prompts = [p for p in prompts if 'Conduit Hand Correction' in json.dumps(p)]
    assert bool(correction_prompts) is (natural in (6, 7))
    if correction_prompts:
        prompt = correction_prompts[0]
        engine = combat._load_session(mid).engine
        names = {a.entity_id: a.display_name for a in engine.state.actors.values()}
        attack_name = next(a.display_name for a in engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack'))
        assert prompt['action'] == attack_name
        assert prompt['trigger_actor'] == names[ME]
        assert prompt['affected'] == names[FOE]


@pytest.mark.parametrize('mode,who,attacks', [('MANUAL', FOE, 1), ('LOCAL_AUTO', FOE, 1), ('LOCAL_AUTO', ALLY, 0)])
def test_long_weapon_measure_uses_side_and_the_crossed_reach(tmp_path, monkeypatch, mode, who, attacks):
    combat, table, mid = fight(tmp_path, mids=(MEASURE,), me_kit=(SPEAR,),
        foe_at=(6, 6), ally_at=(4, 7) if who == FOE else (6, 7),
        modes={ME: mode, FOE: 'MANUAL', ALLY: 'MANUAL'}, seed='A2WEAPONSS-measure')
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    for _ in range(20):
        state = table.state(mid)
        if state['menu']['actor_id'] == who:
            break
        if 'end_turn' in state['menu']:
            ask(table, mid, 'end')
        else:
            assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
    before = len(events(tmp_path, mid, 'ATTACK_ROLLED', ME))
    if attacks:
        snapshot = reload(tmp_path, mid)
        guard, ally, foe = (snapshot.state.actors[a] for a in (ME, ALLY, FOE))
        assert snapshot._distance_actor_to_actor(guard, ally) <= 10
        entry = foe.position.model_copy(update={'x': 5, 'y': 6})
        assert snapshot._distance_actor_to_actor(foe, guard, actor_position=entry) <= 10
    move_to(combat, table, mid, 5, 6 if who == FOE else 7)
    rolled = events(tmp_path, mid, 'ATTACK_ROLLED', ME)
    assert len(rolled) - before == attacks
    if attacks:
        assert rolled[-1].target_ids == (FOE,)
        snapshot = reload(tmp_path, mid)
        assert snapshot._distance_actor_to_actor(snapshot.state.actors[ME], snapshot.state.actors[ALLY]) <= 10
        assert not reload(tmp_path, mid).state.actors[ME].reaction_available
        assert reload(tmp_path, mid).state.actors[ME].turn_flags['_round_weapons_measure'] == reload(tmp_path, mid).state.round_number
    else:
        assert reload(tmp_path, mid).state.actors[ME].reaction_available


def test_correction_is_spent_by_next_disarm_save(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CORRECTION), me_kit=(DAGGER,),
        foe_kit=('tianxia.mortal.weapon.tie_chi',))
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    force_naturals(monkeypatch, who=ME, attack=7, save=3)
    ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert CORRECTED in conditions(tmp_path, mid, ME)
    force_naturals(monkeypatch, who=FOE, attack=15, save=3)
    to_turn(table, mid, FOE)
    ask(table, mid, candidate(combat, mid, 'Disarm', ME))
    assert events(tmp_path, mid, 'SAVE_ROLLED', ME)[-1].payload['mode'] == 'ADVANTAGE'
    assert CORRECTED not in conditions(tmp_path, mid, ME)


def test_correction_expires_at_source_next_turn_after_cold_reload(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CORRECTION), me_kit=(DAGGER,), foe_kit=(DAGGER,))
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                            if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    force_naturals(monkeypatch, who=ME, attack=7, save=3)
    ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert CORRECTED in conditions(tmp_path, mid, ME)
    assert CORRECTED in {c.condition_id for c in reload(tmp_path, mid).state.actors[ME].conditions.values()}
    ask(table, mid, 'end')
    to_turn(table, mid, ME)
    assert CORRECTED not in conditions(tmp_path, mid, ME)
    assert CORRECTED not in {c.condition_id for c in reload(tmp_path, mid).state.actors[ME].conditions.values()}


@pytest.mark.parametrize('answer,waived', [('USE', True), ('DECLINE', False)])
def test_correction_waives_graze_damage_on_only_this_miss(tmp_path, monkeypatch, answer, waived):
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CORRECTION), me_kit=(BLADE,), foe_kit=(DAGGER,))
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith(' attack') and '#' not in a.source_definition_id
                           and (a.parameters.get('typed') or {}).get('weapon', {}).get('implement_id') == BLADE))
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    force_naturals(monkeypatch, who=ME, attack=7, save=3)
    e = combat._load_session(mid).engine
    plain = next(c.candidate_id for c in e.legal_candidates()
                 if c.source_definition_id == selected_id(tmp_path, mid) and c.target_ids == (FOE,))
    ask(table, mid, plain, answers=(answer,))
    after = reload(tmp_path, mid).state.actors[FOE].current_hp
    assert (before == after) is waived
    assert bool(conditions(tmp_path, mid, ME).get(CORRECTED)) is waived


def concentration_setup(monkeypatch, *, mediated):
    import tests.test_auto21_weapons as support
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    original = support.compile_character
    def compile_with_setup(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if bundle['actor_id'] == ME:
            base = next(a for a in bundle['action_catalog'] if a['display_name'].endswith('(Dagger) attack'))
            import copy
            typed = copy.deepcopy(base['parameters']['typed'])
            if not mediated:
                typed.pop('weapon', None)
            typed.update(source='action:test.a2weapons.concentrate', duration={'kind':'one_minute','concentration':True},
                         effects=[{'type':'ac_bonus','applies_to':'self','amount':1}])
            action = ActionDefinition(source_definition_id='action:test.a2weapons.concentrate',
                display_name='Test concentration', owner_id=ME, economy=EconomyKind.NONE,
                resolution_kind='TYPED', target_kind='SELF', parameters={'typed':typed})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(action.source_definition_id)
        return bundle
    monkeypatch.setattr(support, 'compile_character', compile_with_setup)


@pytest.mark.parametrize('mediated,mode,consumed', [(True,'ADVANTAGE',True),(False,'NORMAL',False)])
def test_correction_only_protects_weapon_mediated_concentration(tmp_path, monkeypatch, mediated, mode, consumed):
    concentration_setup(monkeypatch, mediated=mediated)
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CORRECTION), me_kit=(DAGGER,), foe_kit=(DAGGER,))
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    ask(table, mid, named(combat, mid, ME, 'Test concentration'))
    assert reload(tmp_path, mid).state.actors[ME].concentration
    force_naturals(monkeypatch, who=ME, attack=7, save=3)
    ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert CORRECTED in conditions(tmp_path, mid, ME)
    force_naturals(monkeypatch, who=FOE, attack=15, save=3)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    saves = [e for e in events(tmp_path, mid, 'SAVE_ROLLED', ME) if e.source_definition_id == 'system:combat.concentration']
    assert saves and saves[-1].payload['mode'] == mode
    assert (CORRECTED not in conditions(tmp_path, mid, ME)) is consumed


def test_careful_grip_applies_to_the_actual_disarm_ability_check(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CAREFUL), me_kit=(DAGGER,),
        foe_mids=('TAL_IRON_FIST_OPEN_HAND_DISARM',), foe_kit=())
    choose(table, mid, next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name.endswith('(Dagger) attack')))
    force_naturals(monkeypatch, who=FOE, attack=15, save=3)
    to_turn(table, mid, FOE)
    ask(table, mid, candidate(combat, mid, 'Unarmed Strike', ME))
    checks = events(tmp_path, mid, 'CHECK_ROLLED', FOE)
    assert checks and checks[-1].payload['target']['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('answer,expected_delta', [('USE',6),('DECLINE',0)])
def test_casting_hand_applies_to_a_real_opportunity_attack(tmp_path, monkeypatch, answer, expected_delta):
    import tests.test_auto21_weapons as support
    original = support.sheet
    def strong_key(*args, **kw):
        s = original(*args, **kw)
        s['identity']['path'] = 'Body Refining'
        for a in s['ability_scores_and_statistics']['abilities']:
            a.update(score=22 if a['ability']=='CON' else 10, modifier=6 if a['ability']=='CON' else 0)
        return s
    monkeypatch.setattr(support, 'sheet', strong_key)
    combat, table, mid = fight(tmp_path, mids=(INITIATE,CASTING), me_kit=(DAGGER,), foe_kit=(DAGGER,))
    base = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id==ME and a.display_name.endswith('(Dagger) attack'))
    choose(table, mid, base.source_definition_id)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, FOE)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination.x==5 and c.destination.y==6)
    # Consent to the OA, then make the separate optional ability substitution.
    prompts = ask(table, mid, move.candidate_id, answers=('USE',answer))
    roll = events(tmp_path, mid,'ATTACK_ROLLED',ME)[-1]
    assert roll.payload['modifier'] == base.parameters['typed']['numbers']['attack_bonus'] + expected_delta
    casting_prompts = [p for p in prompts if 'Casting-Hand' in json.dumps(p)]
    assert casting_prompts
    engine = combat._load_session(mid).engine
    names = {a.entity_id: a.display_name for a in engine.state.actors.values()}
    assert casting_prompts[0]['action'] == 'Opportunity Attack'
    assert casting_prompts[0]['trigger_actor'] == names[ME]
    assert casting_prompts[0]['affected'] == names[FOE]
    assert reload(tmp_path, mid).action_catalog[base.source_definition_id].parameters['typed']['weapon']['ability_modifier']==0


def test_manual_reaction_owner_gets_casting_hand_choice_during_local_ai_turn(tmp_path, monkeypatch):
    import tests.test_auto21_weapons as support
    original = support.sheet
    def strong_key(*args, **kw):
        s = original(*args, **kw)
        s['identity']['path'] = 'Body Refining'
        for a in s['ability_scores_and_statistics']['abilities']:
            a.update(score=22 if a['ability'] == 'CON' else 10, modifier=6 if a['ability'] == 'CON' else 0)
        return s
    monkeypatch.setattr(support, 'sheet', strong_key)
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CASTING, MEASURE), me_kit=(SPEAR,),
        foe_kit=(DAGGER,), foe_at=(6, 6), modes={ME: 'MANUAL', FOE: 'LOCAL_AUTO'},
        seed='A2WEAPONSS-ai-reaction-owner')
    base = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id == ME and a.display_name.endswith('(Spear) attack'))
    choose(table, mid, base.source_definition_id)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    ask(table, mid, 'end')
    answers, prompts = [], []
    for _ in range(20):
        state = table.state(mid)
        result = table.auto_step(mid, state['last_sequence'], answers)
        if result['status'] == 'REACTION_REQUIRED':
            prompt = result['reaction']
            prompts.append(prompt)
            assert prompt['context'].get('reactor_id') == ME
            answer = {**prompt['context'], 'selection': 'USE'}
            if prompt.get('choice'):
                answer['option_ids'] = [prompt['choice']['options'][0]['id']]
            answers.append(answer)
            continue
        assert result['status'] == 'COMMITTED', result
        answers = []
        if any('Casting-Hand' in json.dumps(prompt) for prompt in prompts):
            break
    casting_prompts = [prompt for prompt in prompts if 'Casting-Hand' in json.dumps(prompt)]
    assert casting_prompts
    loaded = reload(tmp_path, mid)
    names = {a.entity_id: a.display_name for a in loaded.state.actors.values()}
    assert casting_prompts[0]['action'] == 'Opportunity Attack'
    assert casting_prompts[0]['trigger_actor'] == names[ME]
    assert casting_prompts[0]['affected'] == names[FOE]
    rolls = [e for e in loaded.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ME]
    assert rolls and rolls[-1].payload['modifier'] == base.parameters['typed']['numbers']['attack_bonus'] + 6


def test_stowing_a_conduit_still_prevents_casting_hand_attacks(tmp_path):
    combat, table, mid = fight(tmp_path,mids=(INITIATE,CASTING),me_kit=(DAGGER,))
    base = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id==ME and a.display_name.endswith('(Dagger) attack'))
    choose(table,mid,base.source_definition_id)
    assert any(c.source_definition_id==base.source_definition_id+'#conduit' for c in reload(tmp_path,mid).legal_candidates())
    ask(table,mid,named(combat,mid,ME,'Stow Bi Shou'))
    assert not [c for c in reload(tmp_path,mid).legal_candidates() if c.source_definition_id.endswith('#conduit')]


def test_casting_hand_choice_is_per_strike_in_extra_attack(tmp_path, monkeypatch):
    import tests.test_auto21_weapons as support
    original = support.sheet
    def strong_key(*args, **kw):
        s = original(*args, **kw)
        s['identity']['path'] = 'Body Refining'
        for a in s['ability_scores_and_statistics']['abilities']:
            a.update(score=22 if a['ability'] == 'CON' else 10, modifier=6 if a['ability'] == 'CON' else 0)
        return s
    monkeypatch.setattr(support, 'sheet', strong_key)
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CASTING, EXTRA_ATTACK), me_kit=(DAGGER,))
    base = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id == ME and a.display_name.endswith('(Dagger) attack'))
    choose(table, mid, base.source_definition_id)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False), answers=('USE', 'DECLINE'))
    method_prompts = [p for p in prompts if 'Casting-Hand' in json.dumps(p)]
    rolls = [e.payload['modifier'] for e in events(tmp_path, mid, 'ATTACK_ROLLED', ME)]
    assert len(method_prompts) == 2, 'each actual strike receives its own ability choice'
    assert rolls[-2:] == [base.parameters['typed']['numbers']['attack_bonus'] + 6,
                          base.parameters['typed']['numbers']['attack_bonus']]
    loaded = reload(tmp_path, mid)
    assert len([e for e in loaded.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ME]) >= 2


@pytest.mark.parametrize('path,key,scores,ability,modifier', [
    ('Body Refining','INT',{'CON':16,'INT':20},'CON',3),
    ('Qi Cultivation','INT',{'INT':20,'CHA':18},'INT',5),
    ('Qi Cultivation','CHA',{'INT':20,'CHA':18},'CHA',4),
    ('Spirit Awakening','CON',{'CON':22,'WIS':18},'WIS',4),
])
def test_casting_hand_uses_the_printed_path_ability(tmp_path,monkeypatch,path,key,scores,ability,modifier):
    import tests.test_auto21_weapons as support
    original=support.sheet
    def path_sheet(*args,**kw):
        s=original(*args,**kw)
        s['identity'].update(path=path,key_ability=key)
        for a in s['ability_scores_and_statistics']['abilities']:
            score=scores.get(a['ability'],10)
            a.update(score=score,modifier=(score-10)//2)
        return s
    monkeypatch.setattr(support,'sheet',path_sheet)
    combat,table,mid=fight(tmp_path,mids=(INITIATE,CASTING),me_kit=(DAGGER,),foe_kit=(DAGGER,))
    base=next(a for a in combat._load_session(mid).engine.action_catalog.values()
              if a.owner_id==ME and a.display_name.endswith('(Dagger) attack'))
    assert base.parameters['typed']['weapon']['ability_modifier']==0
    choose(table,mid,base.source_definition_id)
    typed=reload(tmp_path,mid).action_catalog[base.source_definition_id+'#conduit'].parameters['typed']
    assert typed['weapon']['ability']==base.parameters['typed']['weapon']['ability']
    assert typed['weapon']['ability_modifier']==base.parameters['typed']['weapon']['ability_modifier']
    assert typed['weapons_casting_hand_explicit'] is True
    force_naturals(monkeypatch,who=ME,attack=15,save=3)
    ask(table,mid,candidate(combat,mid,'(Casting-Hand:'))
    assert events(tmp_path,mid,'ATTACK_ROLLED',ME)[-1].payload['modifier']==base.parameters['typed']['numbers']['attack_bonus']+modifier


@pytest.mark.parametrize('weapon,disengage', [(DAGGER, False), (SPEAR, True)])
def test_measure_requires_reach_and_respects_disengage(tmp_path, monkeypatch, weapon, disengage):
    combat, table, mid = fight(tmp_path, mids=(MEASURE,), me_kit=(weapon,), foe_at=(6, 6),
                               seed='A2WEAPONSS-measure-exempt')
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, FOE)
    if disengage:
        ask(table, mid, candidate(combat, mid, 'Disengage', FOE))
    before = len(events(tmp_path, mid, 'ATTACK_ROLLED', ME))
    move_to(combat, table, mid, 4, 6)
    assert len(events(tmp_path, mid, 'ATTACK_ROLLED', ME)) == before
    assert reload(tmp_path, mid).state.actors[ME].reaction_available
    assert '_round_weapons_measure' not in reload(tmp_path, mid).state.actors[ME].turn_flags


def test_measure_does_not_spend_reaction_when_reach_weapon_is_stowed(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(MEASURE,), me_kit=(WHIP, DAGGER), foe_at=(6, 6),
                               seed='A2WEAPONSS-measure-stowed')
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, 'Stow Jie Bian'))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, FOE)
    before = len(events(tmp_path, mid, 'ATTACK_ROLLED', ME))
    prompts = move_to(combat, table, mid, 4, 6)
    engine = reload(tmp_path, mid)
    assert not [p for p in prompts if 'Long Weapon Measure' in json.dumps(p)]
    assert len(events(tmp_path, mid, 'ATTACK_ROLLED', ME)) == before
    assert engine.state.actors[ME].reaction_available
    assert '_round_weapons_measure' not in engine.state.actors[ME].turn_flags


def test_measure_does_not_spend_reaction_when_reach_weapon_is_disarmed(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(MEASURE,), me_kit=(SPEAR,),
        foe_mids=('TAL_IRON_FIST_OPEN_HAND_DISARM',), foe_kit=(), foe_at=(4, 6),
        seed='A2WEAPONSS-measure-disarmed')
    force_naturals(monkeypatch, who=FOE, attack=15, save=3)
    to_turn(table, mid, FOE)
    ask(table, mid, candidate(combat, mid, 'Unarmed Strike', ME))
    assert any('disarmed' in condition_id for condition_id in conditions(tmp_path, mid, ME))
    assert reload(tmp_path, mid).state.actors[ME].reaction_available
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    before = len(events(tmp_path, mid, 'ATTACK_ROLLED', ME))
    measure_receipts_before = [e for e in events(tmp_path, mid, 'REACTION_RESOLVED', ME)
                               if e.source_definition_id == MEASURE]
    move_to(combat, table, mid, 7, 6)
    prompts = move_to(combat, table, mid, 5, 6)
    engine = reload(tmp_path, mid)
    assert not [p for p in prompts if 'Long Weapon Measure' in json.dumps(p)]
    assert len(events(tmp_path, mid, 'ATTACK_ROLLED', ME)) == before
    assert [e for e in events(tmp_path, mid, 'REACTION_RESOLVED', ME)
            if e.source_definition_id == MEASURE] == measure_receipts_before
    assert '_round_weapons_measure' not in engine.state.actors[ME].turn_flags


def test_measure_round_receipt_allows_a_new_reaction_next_round(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=(MEASURE,), me_kit=(SPEAR,), foe_at=(6, 6),
                               seed='A2WEAPONSS-measure-round-reset')
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, FOE)
    move_to(combat, table, mid, 5, 6)
    first = reload(tmp_path, mid)
    first_round = first.state.round_number
    assert first.state.actors[ME].turn_flags['_round_weapons_measure'] == first_round
    ask(table, mid, 'end')
    to_turn(table, mid, ME)
    ask(table, mid, 'end')
    to_turn(table, mid, FOE)
    assert reload(tmp_path, mid).state.actors[ME].reaction_available
    ask(table, mid, named(combat, mid, FOE, 'Disengage'))
    engine = reload(tmp_path, mid)
    guard, foe = engine.state.actors[ME], engine.state.actors[FOE]
    outward = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                   and engine._distance_actor_to_actor(foe, guard, actor_position=c.destination) > 10)
    ask(table, mid, outward.candidate_id)
    ask(table, mid, 'end')
    to_turn(table, mid, ME)
    ask(table, mid, 'end')
    to_turn(table, mid, FOE)
    for _ in range(10):
        engine = reload(tmp_path, mid)
        guard, foe = engine.state.actors[ME], engine.state.actors[FOE]
        distance = engine._distance_actor_to_actor(foe, guard)
        if distance <= 10:
            break
        inward = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                  and engine._distance_actor_to_actor(foe, guard, actor_position=c.destination) < distance]
        assert inward, 'no legal movement step returns toward the guard'
        candidate_step = min(inward, key=lambda c: engine._distance_actor_to_actor(foe, guard, actor_position=c.destination))
        prompts = ask(table, mid, candidate_step.candidate_id)
        if any('Long Weapon Measure' in json.dumps(prompt) for prompt in prompts):
            break
    second = reload(tmp_path, mid)
    assert second.state.round_number > first_round
    assert second.state.actors[ME].turn_flags['_round_weapons_measure'] == second.state.round_number
    assert len(events(tmp_path, mid, 'ATTACK_ROLLED', ME)) == 2


@pytest.mark.parametrize('answer,source', [('USE', MEASURE), ('DECLINE', 'TAL_SPEAR_INTERCEPTING_THRUST')])
def test_measure_and_spear_interception_share_the_reaction(tmp_path, monkeypatch, answer, source):
    intercept = 'TAL_SPEAR_INTERCEPTING_THRUST'
    combat, table, mid = fight(tmp_path, mids=(MEASURE, intercept), me_kit=(SPEAR,),
                               foe_at=(6, 6), seed='A2WEAPONSS-no-stack')
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    intercept_row = next(r for r in engine.typed_reaction_rows[ME] if r['feature_id'] == intercept)
    assert intercept_row['kind'] == 'enters_range' and intercept_row['toward']
    assert intercept_row['min_move_ft'] == 10
    before = len(events(tmp_path, mid, 'ATTACK_ROLLED', ME))
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination.x == 4 and c.destination.y == 6)
    ask(table, mid, move.candidate_id, answers=(answer, 'USE'))
    assert len(events(tmp_path, mid, 'ATTACK_ROLLED', ME)) - before == 1
    assert any(e.source_definition_id == source for e in events(tmp_path, mid, 'REACTION_RESOLVED', ME))
    assert not reload(tmp_path, mid).state.actors[ME].reaction_available


def test_casting_hand_preserves_offhand_positive_damage_omission(tmp_path, monkeypatch):
    import tests.test_auto21_weapons as support
    original = support.sheet
    def body_refiner(*args, **kw):
        s = original(*args, **kw)
        s['identity']['path'] = 'Body Refining'
        for a in s['ability_scores_and_statistics']['abilities']:
            a.update(score=22 if a['ability'] == 'CON' else 10,
                     modifier=6 if a['ability'] == 'CON' else 0)
        return s
    monkeypatch.setattr(support, 'sheet', body_refiner)
    combat, table, mid = fight(tmp_path, mids=(INITIATE, CASTING), me_kit=(DAGGER, AXE))
    engine = combat._load_session(mid).engine
    dagger = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and a.display_name.endswith('(Dagger) attack'))
    choose(table, mid, dagger.source_definition_id)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    engine = combat._load_session(mid).engine
    axe = next(c for c in engine.legal_candidates() if c.target_ids == (FOE,)
               and c.display_name == 'Fu (Short Axe) attack')
    ask(table, mid, axe.candidate_id)
    engine = reload(tmp_path, mid)
    offhand_id = dagger.source_definition_id+'#offhand#conduit'
    offhand = next(c for c in engine.legal_candidates() if c.source_definition_id == offhand_id and c.target_ids == (FOE,))
    original_typed = engine.action_catalog[dagger.source_definition_id+'#offhand'].parameters['typed']
    ask(table, mid, offhand.candidate_id)
    assert events(tmp_path, mid, 'ATTACK_ROLLED', ME)[-1].payload['modifier'] == original_typed['numbers']['attack_bonus']+6
    assert events(tmp_path, mid, 'DAMAGE_ROLLED', ME)[-1].payload['modifier'] == original_typed['weapon']['damage']['modifier'] == 0
